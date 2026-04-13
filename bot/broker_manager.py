# bot/broker_manager.py
"""
NIJA Multi-Brokerage Manager
Supports: Coinbase, Interactive Brokers, TD Ameritrade, Alpaca, etc.
"""

from enum import Enum
from abc import ABC, abstractmethod
from typing import Callable, Dict, List, Optional
import functools
import json
import logging
import os
import random
import re
import time
import traceback
import uuid
import threading

# Import circuit breaker for API reliability
try:
    from bot.broker_circuit_breaker import get_circuit_breaker, BrokerHealthState  # type: ignore[assignment]
    CIRCUIT_BREAKER_AVAILABLE = True
except ImportError:
    try:
        from broker_circuit_breaker import get_circuit_breaker, BrokerHealthState  # type: ignore[assignment]
        CIRCUIT_BREAKER_AVAILABLE = True
    except ImportError:
        CIRCUIT_BREAKER_AVAILABLE = False
        BrokerHealthState = None
        def get_circuit_breaker(*args, **kwargs):  # type: ignore[misc]
            return None

# Import requests exceptions for proper timeout error handling
# These are used in KrakenBroker.connect() to detect network timeouts
# Note: The flag name is specific to clarify we're checking for timeout exception classes,
# not just whether requests is available (it's used elsewhere for HTTP calls)
try:
    from requests.exceptions import (
        Timeout,
        ReadTimeout,
        ConnectTimeout,
        ConnectionError as RequestsConnectionError  # Avoid shadowing built-in ConnectionError
    )
    REQUESTS_TIMEOUT_EXCEPTIONS_AVAILABLE = True
except (ImportError, ModuleNotFoundError):
    # If requests isn't available, we'll fallback to string matching
    # ModuleNotFoundError is more specific but we catch both for compatibility
    REQUESTS_TIMEOUT_EXCEPTIONS_AVAILABLE = False

# Try to load dotenv if available, but don't fail if not
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not available, env vars should be set externally

# Import rate limiter for API call throttling
try:
    from bot.rate_limiter import RateLimiter
except ImportError:
    try:
        from rate_limiter import RateLimiter
    except ImportError:
        # Fallback if rate_limiter not available
        RateLimiter = None

# Import Global Kraken Nonce Manager (ONE source for all users - FINAL FIX)
try:
    from bot.global_kraken_nonce import (
        NonceManager,
        get_global_kraken_nonce,
        get_kraken_nonce,
        get_kraken_api_lock,
        jump_global_kraken_nonce_forward,
        get_global_nonce_manager,
        reset_global_kraken_nonce,
        is_nonce_trading_paused,
        get_nonce_pause_remaining,
        probe_and_resync_nonce,
        register_broker_quarantine_callback,
        is_broker_quarantined,
        is_kraken_key_invalidated,
        rebuild_nonce_manager,
        clear_broker_quarantine,
    )
except ImportError:
    try:
        from global_kraken_nonce import (
            NonceManager,
            get_global_kraken_nonce,
            get_kraken_nonce,
            get_kraken_api_lock,
            jump_global_kraken_nonce_forward,
            get_global_nonce_manager,
            reset_global_kraken_nonce,
            is_nonce_trading_paused,
            get_nonce_pause_remaining,
            probe_and_resync_nonce,
            register_broker_quarantine_callback,
            is_broker_quarantined,
            is_kraken_key_invalidated,
            rebuild_nonce_manager,
            clear_broker_quarantine,
        )
    except ImportError:
        # Fallback: Global nonce manager not available
        NonceManager = None
        get_global_kraken_nonce = None
        get_kraken_nonce = None
        get_kraken_api_lock = None
        jump_global_kraken_nonce_forward = None
        get_global_nonce_manager = None
        reset_global_kraken_nonce = None
        is_nonce_trading_paused = None
        get_nonce_pause_remaining = None
        probe_and_resync_nonce = None
        register_broker_quarantine_callback = None
        is_broker_quarantined = None
        is_kraken_key_invalidated = None
        rebuild_nonce_manager = None
        clear_broker_quarantine = None

# ── Broker quarantine state ───────────────────────────────────────────────────
# Set to True when the nonce manager confirms nonce poisoning (consecutive
# nuclear resets >= threshold).  Once active, the KrakenBroker blocks new BUY
# orders (exit-only) and BrokerManager auto-promotes Coinbase to primary.
_kraken_quarantine_active: bool = False


# ── Shared credential-prefix helper ──────────────────────────────────────────
def _user_env_prefix(user_id: str) -> tuple:
    """Return ``(short_prefix, full_prefix)`` env-var name prefixes for *user_id*.

    ``short_prefix`` is the first word of user_id in upper-case
    (e.g. ``"DAIVON"`` for ``"daivon_frazier"``).
    ``full_prefix`` is the entire user_id upper-cased with hyphens → underscores
    (e.g. ``"DAIVON_FRAZIER"`` for ``"daivon_frazier"``).

    Used by CoinbaseBroker, OKXBroker, and multi_account_broker_manager to build
    environment-variable names like ``COINBASE_USER_{prefix}_API_KEY``.
    """
    short = user_id.split('_')[0].upper() if '_' in user_id else user_id.upper()
    full = user_id.upper().replace('-', '_')
    return short, full


class NoncePauseActive(Exception):
    """Raised when a Kraken nonce trading pause is active.

    Signals the trade execution path to fail fast and retry on the next
    scan cycle instead of sleeping inside the execution thread.
    """


def _on_kraken_nonce_quarantine() -> None:
    """Quarantine callback: fired by KrakenNonceManager when nonce poisoning is
    confirmed.  Marks every connected KrakenBroker PLATFORM instance as
    exit-only and logs a prominent alert.  USER accounts have independent API
    keys and are intentionally NOT quarantined here — only the platform account
    whose nonce window is poisoned is restricted.
    BrokerManager.get_primary_broker() will then skip Kraken and promote the
    next available broker (Coinbase) automatically.
    """
    global _kraken_quarantine_active
    _kraken_quarantine_active = True
    logging.critical(
        "\n" + "=" * 70 + "\n"
        "🚫  KRAKEN BROKER QUARANTINED — NONCE POISONING CONFIRMED\n"
        "    Consecutive nuclear nonce resets have exceeded the quarantine\n"
        "    threshold.  Kraken PLATFORM is now in EXIT-ONLY mode; all new\n"
        "    entries will be routed to the Coinbase fallback broker.\n"
        "    USER accounts with separate API keys remain unaffected.\n\n"
        "    REQUIRED RECOVERY STEPS:\n"
        "      1. Stop ALL Railway/Heroku deployments using this API key.\n"
        "      2. Revoke the compromised Kraken key and create a NEW one.\n"
        "      3. Set Nonce Window = 10000 on the new key.\n"
        "      4. Update KRAKEN_PLATFORM_API_KEY / KRAKEN_PLATFORM_API_SECRET.\n"
        "      5. Set NIJA_DEEP_NONCE_RESET=1 on the first restart.\n"
        "      6. Deploy ONE instance only.\n"
        + "=" * 70
    )
    # Mark every live PLATFORM KrakenBroker with quarantine flags so per-instance
    # callers can inspect broker.quarantined without reading the module global.
    # USER accounts are deliberately skipped — their nonce windows are independent.
    try:
        for _broker in KrakenBroker._iter_live():
            if getattr(_broker, 'account_type', None) == AccountType.PLATFORM:
                _broker.exit_only_mode = True
                _broker.quarantined = True
                _broker.quarantine_until = 0.0  # permanent until cleared
                logging.warning(
                    "🚫  KrakenBroker[PLATFORM] flagged quarantined/exit-only"
                )
    except Exception as _qe:
        logging.warning("⚠️  Could not mark broker instances during quarantine: %s", _qe)


def clear_kraken_broker_quarantine() -> None:
    """Clear the Kraken broker quarantine after a successful key rotation + resync.

    Performs a full reset:
      - Clears the module-level ``_kraken_quarantine_active`` flag.
      - Calls ``clear_broker_quarantine()`` on the nonce module to reset
        ``_quarantine_triggered`` there too.
      - Resets every live KrakenBroker instance:
          broker.exit_only_mode  = False
          broker.quarantined     = False
          broker.quarantine_until = 0
          broker.error_count     = 0

    Call this only after the compromised API key has been rotated and a fresh
    ``probe_and_resync_nonce()`` confirms the new key is healthy.
    """
    global _kraken_quarantine_active
    _kraken_quarantine_active = False

    # Clear the nonce-module quarantine flag as well
    if clear_broker_quarantine is not None:
        try:
            clear_broker_quarantine()
        except Exception as _ce:
            logging.warning("⚠️  clear_broker_quarantine() raised: %s", _ce)

    # Reset all live KrakenBroker instances
    cleared_count = 0
    try:
        for _broker in KrakenBroker._iter_live():
            _broker.exit_only_mode = False
            _broker.quarantined = False
            _broker.quarantine_until = 0.0
            _broker.error_count = 0
            cleared_count += 1
    except Exception as _re:
        logging.warning("⚠️  Error resetting broker instances during quarantine clear: %s", _re)

    logging.warning(
        "✅  Kraken broker quarantine CLEARED — %d broker instance(s) reset.  "
        "Ensure the API key has been rotated before resuming live entries.",
        cleared_count,
    )


if register_broker_quarantine_callback is not None:
    register_broker_quarantine_callback(_on_kraken_nonce_quarantine)
try:
    from bot.balance_models import BalanceSnapshot, UserBrokerState, create_balance_snapshot_from_broker_response
except ImportError:
    try:
        from balance_models import BalanceSnapshot, UserBrokerState, create_balance_snapshot_from_broker_response
    except ImportError:
        # Fallback: Balance models not available
        BalanceSnapshot = None
        UserBrokerState = None
        create_balance_snapshot_from_broker_response = None

# Import Entry Price Store — rich metadata Layer 2 fallback + self-healing repair job
try:
    from bot.entry_price_store import get_entry_price_store
    ENTRY_PRICE_STORE_AVAILABLE = True
except ImportError:
    try:
        from entry_price_store import get_entry_price_store
        ENTRY_PRICE_STORE_AVAILABLE = True
    except ImportError:
        ENTRY_PRICE_STORE_AVAILABLE = False
        get_entry_price_store = None  # type: ignore

# Import BrokerPerformanceScorer — used for score-based broker auto-promotion
try:
    from bot.broker_performance_scorer import get_broker_performance_scorer as _get_broker_performance_scorer
    _BROKER_PERFORMANCE_SCORER_AVAILABLE = True
except ImportError:
    try:
        from broker_performance_scorer import get_broker_performance_scorer as _get_broker_performance_scorer
        _BROKER_PERFORMANCE_SCORER_AVAILABLE = True
    except ImportError:
        _BROKER_PERFORMANCE_SCORER_AVAILABLE = False
        _get_broker_performance_scorer = None  # type: ignore

# Import Kraken Symbol Mapper for symbol validation and conversion
try:
    from bot.kraken_symbol_mapper import get_kraken_symbol_mapper, validate_kraken_symbol, convert_to_kraken
except ImportError:
    try:
        from kraken_symbol_mapper import get_kraken_symbol_mapper, validate_kraken_symbol, convert_to_kraken
    except ImportError:
        # Fallback: Symbol mapper not available
        get_kraken_symbol_mapper = None
        validate_kraken_symbol = None
        convert_to_kraken = None

# Import Kraken Order Validator for order size validation
try:
    from bot.kraken_order_validator import validate_order_size, KRAKEN_MINIMUM_ORDER_USD
except ImportError:
    try:
        from kraken_order_validator import validate_order_size, KRAKEN_MINIMUM_ORDER_USD
    except ImportError:
        # Fallback: Order validator not available
        validate_order_size = None
        KRAKEN_MINIMUM_ORDER_USD = None

# Import Emergency Symbol Resolver for delisted/renamed symbol handling
try:
    from bot.emergency_symbol_resolver import (
        EmergencySymbolResolver, SymbolStatus,
        DelistedAssetRegistry, is_excluded_from_exposure,
    )
    EMERGENCY_RESOLVER_AVAILABLE = True
except ImportError:
    try:
        from emergency_symbol_resolver import (
            EmergencySymbolResolver, SymbolStatus,
            DelistedAssetRegistry, is_excluded_from_exposure,
        )
        EMERGENCY_RESOLVER_AVAILABLE = True
    except ImportError:
        EMERGENCY_RESOLVER_AVAILABLE = False
        EmergencySymbolResolver = None
        SymbolStatus = None
        DelistedAssetRegistry = None
        is_excluded_from_exposure = None

# Import Kraken Rate Profiles for separate entry/exit API budgets (Jan 23, 2026)
try:
    from bot.kraken_rate_profiles import (
        KrakenRateMode,
        KrakenAPICategory,
        get_kraken_rate_profile,
        get_category_for_method,
        calculate_min_interval,
        get_rate_profile_summary
    )
except ImportError:
    try:
        from kraken_rate_profiles import (
            KrakenRateMode,
            KrakenAPICategory,
            get_kraken_rate_profile,
            get_category_for_method,
            calculate_min_interval,
            get_rate_profile_summary
        )
    except ImportError:
        # Fallback: Rate profiles not available
        KrakenRateMode = None
        KrakenAPICategory = None
        get_kraken_rate_profile = None
        get_category_for_method = None
        calculate_min_interval = None
        get_rate_profile_summary = None

# Import Tier Configuration for minimum enforcement and auto-resize
try:
    from bot.tier_config import get_tier_from_balance, get_tier_config, validate_trade_size, auto_resize_trade
except ImportError:
    try:
        from tier_config import get_tier_from_balance, get_tier_config, validate_trade_size, auto_resize_trade
    except ImportError:
        # Fallback: Tier config not available
        get_tier_from_balance = None

# Configure logger for broker operations (must be before imports that use it)
logger = logging.getLogger('nija.broker')

# ── Optional: entry price store (local truth for entry prices) ─────────────
try:
    from bot.entry_price_store import get_entry_price_store as _get_eps
    _ENTRY_PRICE_STORE_AVAILABLE = True
except ImportError:
    try:
        from entry_price_store import get_entry_price_store as _get_eps
        _ENTRY_PRICE_STORE_AVAILABLE = True
    except ImportError:
        _ENTRY_PRICE_STORE_AVAILABLE = False
        _get_eps = None

# ── Execution Risk Firewall — venue health-score routing ────────────────────
try:
    from bot.execution_risk_firewall import get_execution_risk_firewall as _get_erf_bm
    _ERF_BM_AVAILABLE = True
except ImportError:
    try:
        from execution_risk_firewall import get_execution_risk_firewall as _get_erf_bm
        _ERF_BM_AVAILABLE = True
    except ImportError:
        _ERF_BM_AVAILABLE = False
        _get_erf_bm = None  # type: ignore

# Import Execution Layer Hardening (Feb 16, 2026) - CRITICAL ENFORCEMENT
# This module enforces ALL hardening requirements at the execution layer:
# 1. Position cap enforcement
# 2. Minimum position size enforcement
# 3. Average position size monitoring
# 4. Dust prevention
# These checks CANNOT be bypassed by strategy, signal engine, or broker adapters
try:
    from bot.execution_layer_hardening import get_execution_layer_hardening  # type: ignore[assignment]
    EXECUTION_HARDENING_AVAILABLE = True
    logger.info("✅ Execution Layer Hardening loaded - ENFORCING POSITION CAPS AND MINIMUMS")
except ImportError:
    try:
        from execution_layer_hardening import get_execution_layer_hardening  # type: ignore[assignment]
        EXECUTION_HARDENING_AVAILABLE = True
        logger.info("✅ Execution Layer Hardening loaded - ENFORCING POSITION CAPS AND MINIMUMS")
    except ImportError:
        EXECUTION_HARDENING_AVAILABLE = False
        logger.warning("⚠️ Execution Layer Hardening not available - POSITION CONTROLS DISABLED")
        def get_execution_layer_hardening(*args, **kwargs):  # type: ignore[misc]
            return None
        get_tier_config = None
        validate_trade_size = None
        auto_resize_trade = None

# Import Connection Stability Manager for watchdog, auto-reconnect, and HTTP pool optimisation
try:
    from bot.connection_stability_manager import get_connection_stability_manager  # type: ignore[assignment]
    CONNECTION_STABILITY_AVAILABLE = True
except ImportError:
    try:
        from connection_stability_manager import get_connection_stability_manager  # type: ignore[assignment]
        CONNECTION_STABILITY_AVAILABLE = True
    except ImportError:
        CONNECTION_STABILITY_AVAILABLE = False
        def get_connection_stability_manager(*args, **kwargs):  # type: ignore[misc]
            return None

# ── Exchange Order Validator — step-size normalisation + PERMANENT_DUST_UNSELLABLE ──
try:
    from bot.exchange_order_validator import (  # type: ignore[assignment]
        get_exchange_order_validator,
        validate_order as _eov_validate_order,
    )
    EXCHANGE_ORDER_VALIDATOR_AVAILABLE = True
    logger.info("✅ Exchange Order Validator loaded — step-size normalisation + PERMANENT_DUST_UNSELLABLE active")
except ImportError:
    try:
        from exchange_order_validator import (  # type: ignore[assignment]
            get_exchange_order_validator,
            validate_order as _eov_validate_order,
        )
        EXCHANGE_ORDER_VALIDATOR_AVAILABLE = True
        logger.info("✅ Exchange Order Validator loaded — step-size normalisation + PERMANENT_DUST_UNSELLABLE active")
    except ImportError:
        EXCHANGE_ORDER_VALIDATOR_AVAILABLE = False
        get_exchange_order_validator = None  # type: ignore
        _eov_validate_order = None  # type: ignore
        logger.warning("⚠️ Exchange Order Validator not available — order normalisation disabled")

# Root nija logger for flushing all handlers
# Child loggers (like 'nija.broker', 'nija.multi_account') propagate to this logger
# but don't have their own handlers, so we need to flush the root logger's handlers
_root_logger = logging.getLogger('nija')

# ============================================================================
# STDOUT SUPPRESSION FOR PYKRAKENAPI (FIX - Jan 20, 2026)
# ============================================================================
# Import the shared utility for suppressing pykrakenapi's print() statements
# The pykrakenapi library uses print() instead of logging for retry messages
# ============================================================================
try:
    from bot.stdout_utils import suppress_pykrakenapi_prints
except ImportError:
    try:
        from stdout_utils import suppress_pykrakenapi_prints
    except ImportError:
        # Fallback: Define locally if import fails
        import sys
        import io
        from contextlib import contextmanager

        @contextmanager
        def suppress_pykrakenapi_prints():
            original_stdout = sys.stdout
            try:
                sys.stdout = io.StringIO()
                yield
            finally:
                sys.stdout = original_stdout

# Import custom exceptions for safety checks
try:
    from bot.exceptions import ExecutionError, BrokerMismatchError, InvalidTxidError, InvalidFillPriceError, OrderRejectedError  # type: ignore[assignment]
except ImportError:
    try:
        from exceptions import ExecutionError, BrokerMismatchError, InvalidTxidError, InvalidFillPriceError, OrderRejectedError  # type: ignore[assignment]
    except ImportError:
        # Fallback: Define locally if import fails
        class ExecutionError(Exception):
            pass
        class BrokerMismatchError(ExecutionError):
            pass
        class InvalidTxidError(ExecutionError):
            pass
        class InvalidFillPriceError(ExecutionError):
            pass
        class OrderRejectedError(ExecutionError):
            pass

# Import DelistedAssetRegistry for persistent tracking of invalid/delisted symbols
try:
    from bot.delisted_asset_registry import get_delisted_asset_registry
except ImportError:
    try:
        from delisted_asset_registry import get_delisted_asset_registry
    except ImportError:
        get_delisted_asset_registry = None

# Balance threshold constants
# Note: Gap between PROTECTION and TRADING thresholds allows small account operation:
#   - PROTECTION ($0.50): Absolute minimum to allow bot to start (hard requirement)
#   - TRADING ($10.00): Default minimum for trading (can be raised via environment variable)
#   This allows small accounts ($10-20) to trade while preventing dust-level trading
#
# ACCOUNT SIZE MODES: Can be customized via MINIMUM_TRADING_BALANCE environment variable:
#   - Small accounts: $10-15 (default, suitable for testing and small capital)
#   - Standard accounts: $25+ (better for fee efficiency and multiple positions)
#   - Large accounts: See tier-specific env files (.env.saver_tier, .env.investor_tier, etc.)
MINIMUM_BALANCE_PROTECTION = 0.50  # Absolute minimum to start (system-wide hard floor)
STANDARD_MINIMUM_BALANCE = float(os.getenv('MINIMUM_TRADING_BALANCE', '1'))  # Capital gate: $1.00 minimum (unlocked for all account sizes)
MINIMUM_TRADING_BALANCE = STANDARD_MINIMUM_BALANCE  # Alias for backward compatibility
MIN_CASH_TO_BUY = float(os.getenv('MIN_CASH_TO_BUY', '5.50'))  # Minimum cash required to place a buy order
DUST_THRESHOLD_USD = 1.00  # USD value threshold for dust positions (consistent with enforcer)

# Broker-specific minimum balance requirements
# Both require the same amount (default $1, configurable via MINIMUM_TRADING_BALANCE env var) but with different priority and strategy rules:
# - Kraken: PRIMARY engine for small accounts ($10-$75 range with low-capital mode)
# - Coinbase: SECONDARY/selective (uses Coinbase-specific strategy, higher fees)
KRAKEN_MINIMUM_BALANCE = STANDARD_MINIMUM_BALANCE  # Kraken is PRIMARY for small accounts
# 🚑 FIX (Jan 24, 2026): Use environment variable for Coinbase minimum to support small accounts
# Coinbase has higher fees than Kraken, but should still support small balances when needed
# Can be overridden via COINBASE_MINIMUM_BALANCE or MINIMUM_TRADING_BALANCE environment variable
# At $10 balance, can make smaller trades; at $25+ can make multiple concurrent trades
COINBASE_MINIMUM_BALANCE = float(os.getenv('COINBASE_MINIMUM_BALANCE', STANDARD_MINIMUM_BALANCE))  # Respects env override or uses STANDARD_MINIMUM_BALANCE

# ── Exchange-scoped capital rules (Steps 2, 5, 6) ──────────────────────────
# Coinbase uses its own floors, independent of Kraken conservatism.
COINBASE_MIN_CAPITAL: float = float(os.getenv('COINBASE_MIN_CAPITAL', '1.0'))
COINBASE_MIN_ORDER: float = float(os.getenv('COINBASE_MIN_ORDER_USD', os.getenv('COINBASE_MIN_ORDER', '1.0')))
COINBASE_MICRO_CAP_MODE: bool = os.getenv('COINBASE_MICRO_CAP_MODE', 'true').strip().lower() in ('1', 'true', 'yes')
COINBASE_IGNORE_GLOBAL_CAPITAL_FLOOR: bool = os.getenv('COINBASE_IGNORE_GLOBAL_CAPITAL_FLOOR', 'false').strip().lower() in ('1', 'true', 'yes')
KRAKEN_EXECUTION_DISABLED: bool = os.getenv('KRAKEN_EXECUTION_DISABLED', 'false').strip().lower() in ('1', 'true', 'yes')

# When micro-cap mode is active, Coinbase minimum balance matches COINBASE_MIN_CAPITAL ($1)
if COINBASE_MICRO_CAP_MODE:
    COINBASE_MINIMUM_BALANCE = COINBASE_MIN_CAPITAL

# ── Isolation skip sentinel (Step 6) ───────────────────────────────────────
_BROKER_ISOLATION_SKIP: Dict = {
    'status': 'broker_isolated_skip',
    'partial_fill': False,
    'filled_pct': 0.0,
}


def _check_broker_isolation(broker_type: 'BrokerType', side: str) -> Optional[Dict]:
    """Check isolation registry; return skip-result if execution should be blocked.

    This is the LAYER 1 guard inserted at the top of every broker's
    ``place_market_order``.  It replaces the pattern::

        raise RuntimeError("Capital below minimum")

    with::

        logger.warning("Broker isolated mode: non-execution broker")
        return SKIP_BROKER
    """
    try:
        try:
            from bot.broker_isolation_registry import get_broker_isolation_registry
        except ImportError:
            from broker_isolation_registry import get_broker_isolation_registry  # type: ignore
        registry = get_broker_isolation_registry()
        skip = registry.check_execution(broker_type.value, side)
        if skip is not None:
            return _BROKER_ISOLATION_SKIP
    except Exception:
        pass
    return None

# Broker health monitoring constants
# Maximum consecutive errors before marking broker unavailable
# This prevents trading when API is persistently failing
BROKER_MAX_CONSECUTIVE_ERRORS = 3

# 🔒 CAPITAL PROTECTION: Balance fetch retry configuration (Feb 2026)
# Balance fetch must retry exactly 3 times before pausing trading cycle
# This ensures we never trade with stale or missing balance data
BALANCE_FETCH_MAX_RETRIES = 3  # Exactly 3 retries as per capital protection requirements

# Hard timeout (seconds) for Kraken trade-history fetches — applies to both
# get_real_entry_price() and get_bulk_entry_prices().  If elapsed wall-clock
# time exceeds this value no further retry/page attempts are started and the
# function returns whatever it has (or None / {}).  Override via env var.
_TRADE_HISTORY_TIMEOUT_SECONDS: int = int(os.environ.get('NIJA_TRADE_HISTORY_TIMEOUT', '8'))

# TTL (seconds) for the bulk-entry-price cache stored on KrakenBroker.
# Subsequent adoption cycles within this window skip the API call entirely.
_BULK_PRICE_CACHE_TTL_SECONDS: int = int(os.environ.get('NIJA_BULK_PRICE_CACHE_TTL', '300'))

# TTL (seconds) for KrakenBroker.get_account_balance() — if the last
# successful fetch is younger than this value the cached balance is returned
# immediately, avoiding a BlockingIO Kraken API round-trip every cycle.
# Default is 55 s (5 s below the BALANCE_STABLE_SECONDS guard threshold of 60 s)
# so that a fresh API call is always made before the timing guard fires and
# blocks new entries.  Override via NIJA_KRAKEN_BALANCE_CACHE_TTL env var.
_KRAKEN_BALANCE_CACHE_TTL_SECONDS: int = int(os.environ.get('NIJA_KRAKEN_BALANCE_CACHE_TTL', '55'))

# Kraken startup delay (Jan 17, 2026) - Critical fix for nonce collisions
# This delay is applied before the first Kraken API call to ensure:
# - Nonce file exists and is initialized properly
# - No collision with other user accounts starting simultaneously
# - No parallel nonce generation during bootstrap
KRAKEN_STARTUP_DELAY_SECONDS = 10.0   # Base startup cooldown (increased from 5 s)
KRAKEN_STARTUP_DELAY_JITTER  =  5.0   # Additional random jitter (0 – 5 s) to stagger multi-instance starts
# Minimum inter-call spacing injected in _kraken_private_call() to prevent
# ultra-fast bursts that can cause nonce-ordering issues on Kraken's servers.
# Jittered: random.uniform(0.05, 0.15) seconds per call.
_KRAKEN_PRIVATE_CALL_SPACING_MIN_S: float = 0.05   # 50 ms
_KRAKEN_PRIVATE_CALL_SPACING_MAX_S: float = 0.15   # 150 ms
# Retry attempt on which to perform a single nonce reset during connect().
# Only ONE reset is applied (at this attempt) to avoid pushing the nonce too far ahead.
_KRAKEN_CONNECT_NONCE_RESET_ATTEMPT: int = 2
# Per-attempt probe jump during connect() nonce resync handshake.
# 0 = let AdaptiveNonceOffsetEngine choose (recommended); set an explicit value
# (e.g. 300_000 = 5 min) via env NIJA_NONCE_PROBE_STEP_MS to override.
_NONCE_PROBE_STEP_MS: int = int(os.environ.get("NIJA_NONCE_PROBE_STEP_MS", "0"))
# Fallback step used by the retry-loop probe jump when _NONCE_PROBE_STEP_MS==0
# (i.e. when AdaptiveOffsetEngine owns the step during the pre-flight probe but
# the retry loop still needs a concrete jump value).
_KRAKEN_CONNECT_PROBE_FALLBACK_MS: int = 300_000   # 5 min

# ── Platform-first gate ───────────────────────────────────────────────────────
# When the Kraken PLATFORM account connects successfully, it sets this Event so
# that USER accounts waiting in connect() can proceed.  USER accounts wait on
# this flag indefinitely — they proceed only when the platform connects or raises
# a hard failure.  Set NIJA_USER_PLATFORM_WAIT to a positive integer (seconds)
# to impose an upper limit.
#
# Rule: Kraken is extremely sensitive to clock drift and nonce ordering.
# The platform account MUST connect and stabilise its nonce FIRST.
# User accounts connecting simultaneously risk nonce-window collisions.
class KrakenStartupFSM:
    """Single source of truth for the Kraken platform startup sequence.

    States (strictly linear — no backward transitions once CONNECTED):

        IDLE → CONNECTING → CONNECTED   (success path)
        IDLE → CONNECTING → FAILED      (failure path)

    Principle: **event = truth, state = derived.**

    The two ``threading.Event`` objects are the authoritative primitives.
    Every boolean helper (``is_connected``, ``is_failed``, …) is a pure read of
    those events.  This eliminates the three-write race that existed when
    ``_platform_ready_flag`` (bool) + ``_connection_already_complete`` (bool) +
    ``_PLATFORM_KRAKEN_READY`` (Event) were set in three separate statements and
    could be observed in partial state by concurrent USER threads.
    """

    def __init__(self) -> None:
        self._connected: threading.Event = threading.Event()
        self._failed: threading.Event = threading.Event()
        # Lightweight "in-flight" marker — NOT the authoritative state.
        self._connecting: bool = False
        self._lock: threading.Lock = threading.Lock()

    # ── Transitions (all writes go through here) ──────────────────────────────

    def mark_connecting(self) -> None:
        """Signal that the PLATFORM handshake has started."""
        with self._lock:
            if not self._connected.is_set() and not self._failed.is_set():
                self._connecting = True

    def mark_connected(self) -> None:
        """Atomically signal CONNECTED — wakes all waiting USER threads instantly.

        This is a single atomic ``Event.set()`` call.  There is no window in
        which ``is_connected`` can be True while other guards are still False.
        """
        with self._lock:
            self._connecting = False
        self._connected.set()

    def mark_failed(self) -> None:
        """Atomically signal FAILED — wakes all waiting USER threads instantly."""
        with self._lock:
            self._connecting = False
        self._failed.set()

    def reset(self) -> None:
        """Reset to IDLE so a retry can start fresh.

        Safe to call only before CONNECTED is reached; calling after
        ``mark_connected()`` is a no-op to protect the stable state.
        """
        with self._lock:
            if not self._connected.is_set():
                self._failed.clear()
                self._connecting = False

    # ── Queries (read-only, derived from events) ───────────────────────────────

    @property
    def is_connected(self) -> bool:
        return self._connected.is_set()

    @property
    def is_failed(self) -> bool:
        # The FSM invariant ensures _connected and _failed are mutually exclusive
        # (mark_connected() and mark_failed() each hold _lock while clearing
        # _connecting, and neither unsets the other event).  The ``not connected``
        # guard is a defensive belt-and-suspenders check so that if external code
        # ever calls both in sequence, is_failed() returns False rather than True
        # while the broker is actually usable.
        return self._failed.is_set() and not self._connected.is_set()

    @property
    def is_connecting(self) -> bool:
        with self._lock:
            return (
                self._connecting
                and not self._connected.is_set()
                and not self._failed.is_set()
            )

    # ── Blocking wait (called by USER accounts) ────────────────────────────────

    def wait_connected(self, timeout: Optional[float] = None) -> bool:
        """Block until CONNECTED or FAILED.

        Returns ``True`` only on CONNECTED; ``False`` on FAILED or timeout.

        ``timeout=None`` (default) means *indefinite* — the call returns only
        when the FSM transitions to CONNECTED or FAILED, never on a time-limit.
        ``timeout=0.0`` is a non-blocking probe.

        USER threads stay parked here across all nonce retries that the
        PLATFORM account may need — they are unblocked only by a single
        ``mark_connected()`` call, which guarantees deterministic startup
        regardless of how many retry cycles occur.

        Implementation note: the loop uses a 1-second wake-up ceiling even for
        the indefinite case so that the ``_failed`` event can be detected promptly.
        Python's ``threading.Event`` does not support waiting on two events
        simultaneously, so short-polling is the cleanest cross-version solution.
        """
        if self._connected.is_set():
            return True
        if self._failed.is_set():
            return False
        deadline = (time.monotonic() + timeout) if timeout is not None else None
        while True:
            remaining = (
                max(0.0, deadline - time.monotonic())
                if deadline is not None
                else 1.0  # wake every 1 s to check _failed (see note above)
            )
            if self._connected.wait(timeout=min(remaining, 1.0)):
                return True
            if self._failed.is_set():
                return False
            if deadline is not None and time.monotonic() >= deadline:
                return False


# Module-level singleton — one FSM per process, shared by all KrakenBroker
# instances.  USER KrakenBroker instances call ``wait_connected()``; the
# PLATFORM KrakenBroker instance calls ``mark_connecting()`` /
# ``mark_connected()`` / ``mark_failed()``.
_KRAKEN_STARTUP_FSM: KrakenStartupFSM = KrakenStartupFSM()

_env_wait = os.environ.get("NIJA_USER_PLATFORM_WAIT", "0")
_USER_PLATFORM_WAIT_S: Optional[int] = int(_env_wait) if _env_wait.strip().isdigit() and int(_env_wait) > 0 else None

# ── Global platform-broker registry guard ────────────────────────────────────
# Tracks whether a PLATFORM broker of each type has already been initialised
# in this process.  The guard prevents a second instantiation from racing with
# the first one (e.g. when TradingStrategy and a background thread both enter
# the broker-creation path before the first instance is registered).
#
# Usage (in MultiAccountBrokerManager.initialize_platform_brokers):
#
#   with _PLATFORM_BROKER_REGISTRY_LOCK:
#       if GLOBAL_PLATFORM_BROKERS["coinbase"]:
#           return _PLATFORM_BROKER_INSTANCES.get("coinbase")
#       GLOBAL_PLATFORM_BROKERS["coinbase"] = True
#       broker = CoinbaseBroker()
#       _PLATFORM_BROKER_INSTANCES["coinbase"] = broker
#
# Keys must match the lowercase BrokerType.value strings used throughout the
# codebase ("coinbase", "kraken", "okx", "binance", "alpaca").
GLOBAL_PLATFORM_BROKERS: Dict[str, bool] = {
    "coinbase": False,
    "kraken":   False,
    "okx":      False,
    "binance":  False,
    "alpaca":   False,
}
# Stores the actual singleton broker instance once created.
_PLATFORM_BROKER_INSTANCES: Dict[str, "BaseBroker"] = {}
# Tracks whether the initial connect() lifecycle has completed for each broker.
# Distinct from GLOBAL_PLATFORM_BROKERS (instance exists) so that a second call
# to initialize_platform_brokers() can skip connect() even when the instance flag
# was set in a previous run.
_PLATFORM_BROKER_CONNECTED: Dict[str, bool] = {
    "coinbase": False,
    "kraken":   False,
    "okx":      False,
    "binance":  False,
    "alpaca":   False,
}
# Protects all three dicts from concurrent reads/writes during startup.
_PLATFORM_BROKER_REGISTRY_LOCK: threading.Lock = threading.Lock()


def get_platform_broker(key: str) -> "Optional[BaseBroker]":
    """Return the singleton platform broker for *key* (e.g. ``"coinbase"``).

    Returns ``None`` when the broker has not been initialised yet.  Callers
    must not call ``connect()`` on the returned object — connection lifecycle
    is owned exclusively by
    ``MultiAccountBrokerManager.initialize_platform_brokers()``.
    """
    return _PLATFORM_BROKER_INSTANCES.get(key)


def register_platform_broker(key: str, broker: "BaseBroker", connected: bool = True) -> None:
    """Register a platform broker instance in the global registry.

    This is the **public** API for writing into the registry.  It is
    intended for use by the fallback/standalone paths in
    ``CoinbaseBrokerAdapter`` and similar modules that construct a broker
    without going through ``MultiAccountBrokerManager.initialize_platform_brokers()``.

    Args:
        key:       Lowercase broker key matching ``BrokerType.value``
                   (e.g. ``"coinbase"``).
        broker:    Fully-constructed broker instance to register.
        connected: Whether the broker's ``connect()`` lifecycle has already
                   completed successfully.  Defaults to ``True`` so callers
                   that call this after a successful ``broker.connect()`` do
                   not need to pass the flag explicitly.
    """
    with _PLATFORM_BROKER_REGISTRY_LOCK:
        GLOBAL_PLATFORM_BROKERS[key] = True
        _PLATFORM_BROKER_INSTANCES[key] = broker
        if connected:
            _PLATFORM_BROKER_CONNECTED[key] = True

# Credential validation constants
PLACEHOLDER_PASSPHRASE_VALUES = [
    'your_passphrase', 'YOUR_PASSPHRASE',
    'passphrase', 'PASSPHRASE',
    'your_password', 'YOUR_PASSWORD',
    'password', 'PASSWORD'
]

# Regex that detects unfilled placeholder values in API credentials (e.g.
# "your_kraken_api_key_here", "your_kraken_private_key_here", "<your-secret>").
# Anchored so real keys that happen to start with a common word are NOT flagged.
# Bracketed groups use negated char classes (e.g. [^>]+) to prevent backtracking
# and ensure only exact delimited values match (e.g. "<foo>" but not "abc<foo>").
# "none" / "null" are anchored by ^...$ so they only match when the entire
# credential value is that word, not when a real key starts with it.
_KRAKEN_PLACEHOLDER_RE = re.compile(
    r"^(your[_\-]?.*|replace[_\-]?.*|change[_\-]?me?|insert[_\-]?.*|fill[_\-]?.*|"
    r"xxx+|placeholder.*|example.*|sample.*|testkey|test[_\-]api|test[_\-]secret|"
    r"dummy.*|fake.*|todo.*|none|null|n/?a|"
    r"<[^>]+>|\[[^\]]+\]|\{[^}]+\}|api[_\-]?key|api[_\-]?secret|key[_\-]?here|"
    r"secret[_\-]?here|\*+)$",
    re.IGNORECASE,
)

# Logging constants
LOG_SEPARATOR = "=" * 70

# First trade tracking flag (for legal/operational protection)
# This flag ensures the "FIRST LIVE TRADE" banner is displayed only once per bot session
_FIRST_TRADE_EXECUTED = False
_FIRST_TRADE_LOCK = threading.Lock()

# ── Market scanning / cycle timing constants (NIJA Profit Mode) ──────────────
# Reduce the number of markets scanned per cycle from 150 → 50 so each
# rotation completes in 8–10 min instead of 30–38 min, keeping prices fresh
# and capturing fast volatility on micro-cap accounts.
MARKETS_PER_SCAN: int = 50

# Rate-limit intervals for MICRO_CAP accounts ($20–$100).
# These mirror the values in kraken_rate_profiles.py KrakenRateMode.MICRO_CAP
# and are exposed here so broker-level logic can reference them directly.
ENTRY_INTERVAL_MICRO_CAP: int = 30    # seconds between entry orders
MONITOR_INTERVAL_MICRO_CAP: int = 60  # seconds between balance/position checks


# ============================================================================
# BROKER-AWARE SYMBOL NORMALIZATION (FIX #1 - Jan 19, 2026)
# ============================================================================
# Each exchange uses different symbol formats:
# - Coinbase:  ETH-USD, ETH-USDT, ETH-USDC (dash separator)
# - Kraken:    ETH-USD, ETH-USDT (dash separator, internally XETHZUSD/XXBTZUSD)
# - Binance:   ETHUSDT, ETHBUSD (no separator, includes BUSD)
# - OKX:       ETH-USDT (dash separator, prefers USDT over USD)
#
# Common mistakes that cause failures:
# - Using Binance symbols (ETH.BUSD) on Kraken → Kraken doesn't support BUSD
# - Using generic symbols without broker-specific mapping → Invalid product errors
#
# This function ensures symbols are properly formatted for each broker.
# ============================================================================

def normalize_symbol_for_broker(symbol: str, broker_name: str) -> str:
    """
    Normalize a trading symbol to the format expected by a specific broker.

    This prevents cross-broker symbol compatibility issues like trying to
    trade Binance-only pairs (BUSD) on Kraken, or using wrong separators.

    Args:
        symbol: Input symbol in any format (ETH-USD, ETH.BUSD, ETHUSDT, etc.)
        broker_name: Broker name ('coinbase', 'kraken', 'binance', 'okx', etc.)

    Returns:
        Normalized symbol in broker-specific format

    Examples:
        normalize_symbol_for_broker("ETH.BUSD", "kraken") → "ETH-USD"
        normalize_symbol_for_broker("ETH-USD", "kraken") → "ETH-USD"
        normalize_symbol_for_broker("ETHUSDT", "coinbase") → "ETH-USD"
        normalize_symbol_for_broker("BTC-USD", "binance") → "BTCUSDT"
    """
    if not symbol or not broker_name:
        return symbol

    broker_name = broker_name.lower()
    symbol_upper = symbol.upper()

    # Extract base and quote currencies from various formats
    # Handle formats: ETH-USD, ETH.BUSD, ETHUSDT, ETH/USD
    base = None
    quote = None

    # Split on common separators
    if '-' in symbol_upper:
        parts = symbol_upper.split('-')
        base, quote = parts[0], parts[1] if len(parts) > 1 else 'USD'
    elif '/' in symbol_upper:
        parts = symbol_upper.split('/')
        base, quote = parts[0], parts[1] if len(parts) > 1 else 'USD'
    elif '.' in symbol_upper:
        parts = symbol_upper.split('.')
        base, quote = parts[0], parts[1] if len(parts) > 1 else 'USD'
    else:
        # No separator - try to detect common patterns
        # Most common: ETHUSDT, BTCUSDT, ETHBUSD
        if symbol_upper.endswith('USDT'):
            base = symbol_upper[:-4]
            quote = 'USDT'
        elif symbol_upper.endswith('BUSD'):
            base = symbol_upper[:-4]
            quote = 'BUSD'
        elif symbol_upper.endswith('USDC'):
            base = symbol_upper[:-4]
            quote = 'USDC'
        elif symbol_upper.endswith('USD'):
            base = symbol_upper[:-3]
            quote = 'USD'
        else:
            # Can't parse - return as-is
            return symbol

    # CRITICAL: Map BUSD (Binance-only) to supported stablecoins
    # Kraken, Coinbase, OKX don't support BUSD
    if quote == 'BUSD':
        if broker_name == 'kraken':
            quote = 'USD'  # Kraken prefers native USD
        elif broker_name == 'coinbase':
            quote = 'USD'  # Coinbase prefers native USD
        elif broker_name == 'okx':
            quote = 'USDT'  # OKX prefers USDT
        elif broker_name == 'binance':
            quote = 'BUSD'  # Keep BUSD for Binance
        else:
            quote = 'USD'  # Default to USD for unknown brokers

    # Broker-specific formatting
    if broker_name == 'kraken':
        # Kraken: ETH-USD (dash separator, matches kraken_symbol_mapper expectations)
        return f"{base}-{quote}"

    elif broker_name == 'coinbase':
        # Coinbase format: ETH-USD, BTC-USDT (dash separator)
        # NOTE: Coinbase supports both USD and USDT/USDC pairs
        # We don't auto-convert USDC/USDT to USD because some assets
        # may only have USDT/USDC pairs available, not USD
        return f"{base}-{quote}"

    elif broker_name == 'binance':
        # Binance format: ETHUSDT, BTCBUSD (no separator)
        return f"{base}{quote}"

    elif broker_name == 'okx':
        # OKX format: ETH-USDT, BTC-USDT (dash separator, prefers USDT)
        # Convert USD to USDT for OKX
        if quote == 'USD':
            quote = 'USDT'
        return f"{base}-{quote}"

    elif broker_name == 'alpaca':
        # Alpaca format: varies, but generally handles standard formats
        # Keep dash separator
        return f"{base}-{quote}"

    else:
        # Unknown broker - return with dash separator (most common)
        return f"{base}-{quote}"

# Rate limiting retry constants
# UPDATED (Jan 10, 2026): Significantly increased 403 error delays to prevent persistent API blocks
# 403 "Forbidden Too many errors" indicates API key is temporarily banned - needs longer cooldown
RATE_LIMIT_MAX_RETRIES = 3  # Maximum retries for rate limit errors (reduced from 6)
RATE_LIMIT_BASE_DELAY = 5.0  # Base delay in seconds for exponential backoff on 429 errors
FORBIDDEN_BASE_DELAY = 60.0  # Fixed delay for 403 "Forbidden" errors (increased from 30s to 60s for API key temporary ban)
FORBIDDEN_JITTER_MAX = 30.0   # Maximum additional random delay for 403 "Forbidden" errors (60-90s total, increased from 30-45s)

# Fallback market list - popular crypto trading pairs used when API fails
FALLBACK_MARKETS = [
    'BTC-USD', 'ETH-USD', 'SOL-USD', 'XRP-USD', 'ADA-USD',
    'DOGE-USD', 'MATIC-USD', 'DOT-USD', 'LINK-USD', 'UNI-USD',
    'AVAX-USD', 'ATOM-USD', 'LTC-USD', 'NEAR-USD', 'ALGO-USD',
    'XLM-USD', 'HBAR-USD', 'APT-USD', 'ARB-USD', 'OP-USD',
    'INJ-USD', 'SUI-USD', 'TIA-USD', 'SEI-USD', 'RUNE-USD',
    'FET-USD', 'IMX-USD', 'RENDER-USD', 'GRT-USD', 'AAVE-USD',
    'MKR-USD', 'SNX-USD', 'CRV-USD', 'LDO-USD', 'COMP-USD',
    'SAND-USD', 'MANA-USD', 'AXS-USD', 'FIL-USD', 'VET-USD',
    'ICP-USD', 'FLOW-USD', 'EOS-USD', 'XTZ-USD', 'THETA-USD',
    'ZEC-USD', 'ETC-USD', 'BAT-USD', 'ENJ-USD', 'CHZ-USD'
]


def _serialize_object_to_dict(obj) -> Dict:
    """
    Safely convert any object to a dictionary for JSON serialization.
    Handles nested objects, dataclasses, and Coinbase SDK response objects.

    Args:
        obj: Any object to convert

    Returns:
        dict: Flattened dictionary representation
    """
    if obj is None:
        return {}

    if isinstance(obj, dict):
        return obj

    # If it's already a string that looks like JSON/dict, try to parse
    if isinstance(obj, str):
        try:
            return json.loads(obj)
        except Exception:
            try:
                import ast
                return ast.literal_eval(obj)
            except Exception:
                return {"_raw": obj, "_type": type(obj).__name__}

    # Try JSON serialization first (handles dataclasses with json.JSONEncoder)
    try:
        json_str = json.dumps(obj, default=str)
        return json.loads(json_str)
    except Exception:
        pass

    # Fallback: convert object attributes
    try:
        result = {}
        if hasattr(obj, '__dict__'):
            for key, value in obj.__dict__.items():
                # Recursively serialize nested objects
                if isinstance(value, (dict, list, str, int, float, bool, type(None))):
                    result[key] = value
                else:
                    # For nested objects, convert to string representation
                    result[key] = str(value)
        return result
    except Exception:
        # Last resort: convert to string
        return {"_object": str(obj), "_type": type(obj).__name__}

class BrokerType(Enum):
    COINBASE = "coinbase"
    BINANCE = "binance"
    KRAKEN = "kraken"
    OKX = "okx"
    INTERACTIVE_BROKERS = "interactive_brokers"
    TD_AMERITRADE = "td_ameritrade"
    ALPACA = "alpaca"
    TRADIER = "tradier"


class AccountType(Enum):
    """
    Account type for separating platform (Nija system) from user accounts.

    PLATFORM: Nija platform account that controls the system
    USER: Individual user/investor accounts
    """
    PLATFORM = "platform"
    USER = "user"


class BaseBroker(ABC):
    """Base class for all broker integrations"""

    def __init__(self, broker_type: BrokerType, account_type: AccountType = AccountType.PLATFORM, user_id: Optional[str] = None):
        self.broker_type = broker_type
        self.account_type = account_type  # PLATFORM or USER account
        self.user_id = user_id  # User identifier for USER accounts (None for PLATFORM)
        self.connected = False
        self.credentials_configured = False  # Track if credentials were provided
        self.last_connection_error = None  # Track last connection error for troubleshooting
        self.exit_only_mode = False  # Default: not in exit-only mode (can be overridden by subclasses)
        self.mode = "ACTIVE"  # Broker deployment mode: "ACTIVE" = tradable, "PASSIVE" = track-only (balance below deployable threshold)

        # ── Quarantine state (broker-instance level) ─────────────────────────
        # Set by clear_kraken_broker_quarantine() / _on_kraken_nonce_quarantine().
        # `quarantined` mirrors the module-level _kraken_quarantine_active flag
        # so external code can inspect individual broker instances without reading
        # the module global.  `quarantine_until` is reserved for time-bounded
        # quarantines (0 = permanent until explicitly cleared).  `error_count`
        # is the consecutive-error counter driving quarantine escalation.
        self.quarantined: bool = False
        self.quarantine_until: float = 0.0   # epoch seconds; 0 = not time-bounded
        self.error_count: int = 0
        
        # Initialize circuit breaker for this broker
        if CIRCUIT_BREAKER_AVAILABLE:
            broker_name = f"{broker_type.value}_{account_type.value}"
            if user_id:
                broker_name = f"{broker_name}_{user_id}"
            self.circuit_breaker = get_circuit_breaker(broker_name)
        else:
            self.circuit_breaker = None
    
    def get_broker_health_state(self) -> Optional[str]:
        """
        Get current broker health state.
        
        Returns:
            str: Health state ('healthy', 'degraded', 'offline') or None if unavailable
        """
        if self.circuit_breaker:
            return self.circuit_breaker.get_health_state().value
        return None
    
    def is_trading_allowed(self) -> bool:
        """
        Check if trading is allowed based on broker health.
        
        Returns:
            bool: True if trading allowed, False if broker offline
        """
        if self.circuit_breaker:
            return self.circuit_breaker.is_trading_allowed()
        return self.connected  # Fallback to connection state
    
    def get_circuit_breaker_status(self) -> Optional[Dict]:
        """
        Get circuit breaker status for monitoring.
        
        Returns:
            dict: Status information or None if unavailable
        """
        if self.circuit_breaker:
            return self.circuit_breaker.get_status()
        return None

    @abstractmethod
    def connect(self) -> bool:
        """Establish connection to broker"""
        pass

    @abstractmethod
    def get_account_balance(self) -> float:
        """Get USD trading balance. Must be implemented by each broker."""
        pass

    @abstractmethod
    def get_positions(self) -> List[Dict]:
        """Get open positions. Must be implemented by each broker."""
        pass

    @abstractmethod
    def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        size_type: str = 'quote',
        ignore_balance: bool = False,
        ignore_min_trade: bool = False,
        force_liquidate: bool = False
    ) -> Dict:
        """
        Place market order. Must be implemented by each broker.

        Args:
            symbol: Trading symbol
            side: 'buy' or 'sell'
            quantity: Order size
            size_type: 'quote' (USD) or 'base' (crypto quantity)
            ignore_balance: Bypass balance validation (EMERGENCY ONLY)
            ignore_min_trade: Bypass minimum trade size validation (EMERGENCY ONLY)
            force_liquidate: Bypass ALL validation (EMERGENCY ONLY)
        """
        pass
    
    def _call_with_circuit_breaker(self, func, *args, **kwargs):
        """
        Execute broker API call with circuit breaker protection.
        
        Args:
            func: Function to call
            *args: Positional arguments for function
            **kwargs: Keyword arguments for function
        
        Returns:
            Result from function
        
        Raises:
            Exception: If circuit is open or call fails
        """
        if self.circuit_breaker:
            return self.circuit_breaker.call_with_circuit_breaker(func, *args, **kwargs)
        else:
            # No circuit breaker, call directly
            return func(*args, **kwargs)

    def close_position(self, symbol: str, base_size: Optional[float] = None, **kwargs) -> Dict:
        """Default implementation calls place_market_order. Brokers can override."""
        quantity = kwargs.get('quantity', base_size)
        side = kwargs.get('side', 'sell')
        size_type = kwargs.get('size_type', 'base')
        if quantity is None:
            raise ValueError("close_position requires a quantity or base_size")
        return self.place_market_order(symbol, side, quantity, size_type)

    def get_asset_balance(self, base_asset: str) -> float:
        """Return the held quantity of *base_asset* (e.g. 'BTC', 'ETH').

        Default implementation scans ``get_positions()`` for any entry whose
        symbol starts with *base_asset* and returns its ``quantity`` /
        ``base_size`` / ``size`` field.  Brokers with a dedicated balance API
        should override this method.

        Returns 0.0 when the asset is not found or on any error.
        """
        try:
            positions = self.get_positions() or []
            for pos in positions:
                sym = pos.get('symbol', '')
                # Accept both "BTC-USD" and "BTC/USD" notations
                pos_base = sym.split('-')[0].split('/')[0]
                if pos_base.upper() == base_asset.upper():
                    # Use explicit None checks so a legitimate 0.0 holding
                    # does not accidentally trigger the next fallback field.
                    for field in ('quantity', 'base_size', 'size'):
                        val = pos.get(field)
                        if val is not None:
                            return float(val)
                    return 0.0
        except Exception as exc:
            logging.warning(
                "get_asset_balance(%s): error scanning positions: %s",
                base_asset, exc,
            )
        return 0.0

    def cancel_all_orders(self) -> int:
        """Cancel all open orders. Optional method, brokers can override.

        Default implementation uses duck typing: if the broker exposes
        ``get_open_orders()`` and ``cancel_order(order_id)`` methods they are
        called to enumerate and cancel every open order. Returns 0 when
        neither method is available.

        Returns:
            int: Number of orders successfully cancelled.
        """
        cancelled = 0
        try:
            _get_orders = getattr(self, 'get_open_orders', None)
            if callable(_get_orders):
                orders = _get_orders()
                _cancel = getattr(self, 'cancel_order', None)
                if not isinstance(orders, list):
                    orders = []
                for order in orders:
                    order_id = (
                        order.get('order_id') or order.get('id') or order.get('txid')
                    )
                    if order_id and callable(_cancel):
                        try:
                            if _cancel(order_id):
                                cancelled += 1
                        except Exception:
                            pass
        except Exception as e:
            logging.warning(f"cancel_all_orders: error listing/cancelling orders: {e}")
        return cancelled

    def get_candles(self, symbol: str, timeframe: str, count: int) -> List[Dict]:
        """Get candle data. Optional method, brokers can override."""
        return []

    def get_current_price(self, symbol: str) -> float:
        """Get current price. Optional method, brokers can override."""
        return 0.0

    def get_total_capital(self, include_positions: bool = True) -> Dict:
        """
        Get total capital including both free balance and open position values.

        PRO MODE Feature: Default implementation for brokers that don't override.

        Args:
            include_positions: If True, includes position values in total capital (default True)

        Returns:
            dict: Capital breakdown with keys:
                - free_balance: Available USD/USDC for new trades
                - position_value: Total USD value of all open positions
                - total_capital: free_balance + position_value
                - positions: List of positions with values
                - position_count: Number of open positions
        """
        try:
            # Get free balance
            free_balance = self.get_account_balance()

            # Get positions and calculate their values
            positions = self.get_positions()
            position_value_total = 0.0
            position_details = []

            if include_positions:
                for pos in positions:
                    symbol = pos.get('symbol')
                    quantity = pos.get('quantity', 0)

                    if not symbol or quantity <= 0:
                        continue

                    # Get current price for position
                    try:
                        price = self.get_current_price(symbol)
                        if price > 0:
                            value = quantity * price
                            position_value_total += value
                            position_details.append({
                                'symbol': symbol,
                                'quantity': quantity,
                                'price': price,
                                'value': value
                            })
                    except Exception:
                        continue

            total_capital = free_balance + position_value_total

            return {
                'free_balance': free_balance,
                'position_value': position_value_total,
                'total_capital': total_capital,
                'positions': position_details,
                'position_count': len(position_details)
            }

        except Exception:
            return {
                'free_balance': 0.0,
                'position_value': 0.0,
                'total_capital': 0.0,
                'positions': [],
                'position_count': 0
            }

    def get_market_data(self, symbol: str, timeframe: str = '5m', limit: int = 100) -> Dict:
        """Get market data. Optional method, brokers can override."""
        candles = self.get_candles(symbol, timeframe, limit)
        return {'candles': candles}

    def supports_asset_class(self, asset_class: str) -> bool:
        """Check if broker supports asset class. Optional method, brokers can override."""
        return False

    def supports_symbol(self, symbol: str) -> bool:
        """
        Check if broker supports a given trading symbol.

        This is a critical safety check to prevent attempting trades on unsupported pairs.
        For example, Kraken doesn't support BUSD (Binance-only stablecoin).

        Args:
            symbol: Trading symbol to check (any format)

        Returns:
            bool: True if broker supports this symbol, False otherwise

        Default implementation: extracts quote currency and checks against known unsupported pairs.
        Brokers can override for more sophisticated checks (e.g., API-based validation).
        """
        if not symbol:
            return False

        symbol_upper = symbol.upper()
        broker_name = self.broker_type.value.lower()

        # Extract quote currency (USD, USDT, BUSD, etc.)
        quote = None
        if '-' in symbol_upper:
            quote = symbol_upper.split('-')[-1]
        elif '/' in symbol_upper:
            quote = symbol_upper.split('/')[-1]
        elif '.' in symbol_upper:
            quote = symbol_upper.split('.')[-1]
        else:
            # No separator - try to detect common patterns
            # CRITICAL: Check longer patterns first to avoid false matches
            # Check USDT/USDC first (4 chars), then BUSD (4 chars), then USD (3 chars)
            if symbol_upper.endswith('USDT'):
                quote = 'USDT'
            elif symbol_upper.endswith('USDC'):
                quote = 'USDC'
            elif symbol_upper.endswith('BUSD'):
                quote = 'BUSD'
            elif symbol_upper.endswith('USD'):
                quote = 'USD'

        if not quote:
            # Can't determine quote currency - assume supported
            return True

        # Broker-specific unsupported pairs
        unsupported = {
            'kraken': ['BUSD'],  # Kraken doesn't support Binance USD
            'coinbase': ['BUSD'],  # Coinbase doesn't support BUSD
            'okx': ['BUSD'],  # OKX doesn't support BUSD
            'alpaca': ['BUSD', 'USDT', 'USDC'],  # Alpaca is stocks/traditional assets
        }

        # Check if quote currency is unsupported for this broker
        if broker_name in unsupported:
            if quote in unsupported[broker_name]:
                logger.debug(f"⏭️ {broker_name.title()} doesn't support {quote} pairs (symbol: {symbol})")
                return False

        return True

    @property
    def min_trade_size(self) -> float:
        """
        Minimum trade size for this broker (hard block).
        Trades below this size will be rejected.

        Broker-specific minimums:
        - Coinbase: $5.00 (higher fees require larger trades)
        - Kraken: $5.00 (allows smaller positions)
        - Default: $5.00

        Returns:
            float: Minimum trade size in USD
        """
        broker_name = self.broker_type.value.lower()

        # Broker-specific minimums
        minimums = {
            'coinbase': 5.00,
            'kraken': 5.00,
            'binance': 5.00,
            'okx': 5.00,
            'alpaca': 1.00,  # Stocks/traditional assets have lower minimums
        }

        return minimums.get(broker_name, 5.00)

    @property
    def warn_trade_size(self) -> float:
        """
        Warning threshold for trade size.
        Trades below this size will generate a warning but still execute.

        Set to $10 for copy trading optics (user experience).

        Returns:
            float: Warning threshold in USD
        """
        return 10.00

    def execute_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        size_type: str = 'quote',
        ignore_balance: bool = False,
        ignore_min_trade: bool = False,
        force_liquidate: bool = False,
        metadata: Optional[Dict] = None,
    ) -> Dict:
        """
        Execute order with broker-specific pre-flight validation.

        This is a wrapper around place_market_order that adds:
        1. Symbol support validation
        2. EXIT-ONLY mode validation
        3. Minimum trade size validation with warnings

        One signal → Broker-specific execution
        SIGNAL: AUSD-USD BUY
        ├── Kraken → SUPPORTED → EXECUTE ✅
        └── Coinbase → UNSUPPORTED + EXIT-ONLY → SKIP 🚫

        Args:
            symbol: Trading symbol
            side: 'buy' or 'sell'
            quantity: Order size
            size_type: 'quote' (USD) or 'base' (crypto quantity)
            ignore_balance: Bypass balance validation (EMERGENCY ONLY)
            ignore_min_trade: Bypass minimum trade size validation (EMERGENCY ONLY)
            force_liquidate: Bypass ALL validation (EMERGENCY ONLY)

        Returns:
            Dict with order result or error
        """
        broker_name = self.broker_type.value.lower()
        broker_title = broker_name.title()

        # ── EXEC TEST MODE detection ──────────────────────────────────────
        # When the caller passes reason="EXEC_TEST_PROBE" via metadata, log
        # the test intent and force ignore_min_trade so a tiny probe order
        # is not silently rejected by size guards.
        # Auth, nonce, and exchange connection are intentionally NOT bypassed.
        _metadata = metadata or {}
        if _metadata.get("reason") == "EXEC_TEST_PROBE":
            logger.info(
                "🧪 TEST ORDER — bypassing non-critical validations "
                "(strategy filters / scoring gates) for %s",
                symbol,
            )
            ignore_min_trade = True

        # PRE-FLIGHT CHECK 1: Symbol support validation
        # Skip if symbol not supported by this broker
        if not self.supports_symbol(symbol):
            logger.info(f"   ❌ Trade rejected for {symbol}")
            logger.info(f"      Reason: {broker_title} does not support this symbol")
            logger.info(f"      💡 This symbol may be specific to another exchange")
            return {
                "status": "skipped",
                "error": "UNSUPPORTED_SYMBOL",
                "message": f"{broker_title} does not support {symbol}",
                "partial_fill": False,
                "filled_pct": 0.0
            }

        # PRE-FLIGHT CHECK 2: EXIT-ONLY mode validation
        # Block BUY orders when broker is in exit-only mode
        if side.lower() == 'buy' and self.exit_only_mode and not force_liquidate:
            logger.info(f"   ❌ Trade rejected for {symbol}")
            logger.info(f"      Reason: {broker_title} is in EXIT-ONLY mode")
            logger.info(f"      Only SELL orders are allowed to close existing positions")
            return {
                "status": "skipped",
                "error": "EXIT_ONLY_MODE",
                "message": f"BUY orders blocked: {broker_title} in EXIT-ONLY mode",
                "partial_fill": False,
                "filled_pct": 0.0
            }

        # PRE-FLIGHT CHECK 3: Minimum trade size validation
        # Only check for quote (USD) size, not base (crypto quantity)
        if size_type == 'quote' and not ignore_min_trade and not force_liquidate:
            # Check warning threshold
            if quantity < self.warn_trade_size:
                logger.warning(f"   ⚠️  Trade size warning for {symbol}")
                logger.warning(f"      Size: ${quantity:.2f} < ${self.warn_trade_size:.2f} (warning threshold)")
                logger.warning(f"      Broker: {broker_title}")
                logger.warning(f"      💡 For better copy trading optics, consider larger positions")

            # Check hard minimum (block)
            if quantity < self.min_trade_size:
                logger.info(f"   ❌ Trade rejected for {symbol}")
                logger.info(f"      Reason: Size ${quantity:.2f} < ${self.min_trade_size:.2f} minimum for {broker_title}")
                logger.info(f"      Minimum trade size: ${self.min_trade_size:.2f}")
                return {
                    "status": "skipped",
                    "error": "TRADE_SIZE_TOO_SMALL",
                    "message": f"Trade size ${quantity:.2f} below ${self.min_trade_size:.2f} minimum",
                    "partial_fill": False,
                    "filled_pct": 0.0
                }

        # All pre-flight checks passed - execute order
        return self.place_market_order(
            symbol=symbol,
            side=side,
            quantity=quantity,
            size_type=size_type,
            ignore_balance=ignore_balance,
            ignore_min_trade=ignore_min_trade,
            force_liquidate=force_liquidate
        )


# CRITICAL FIX (Jan 11, 2026): Invalid ProductID error detection
# Used by both logging filter and exception handler for consistency
def _is_invalid_product_error(error_message: str) -> bool:
    """
    Check if an error message indicates an invalid/delisted product.

    This function is used both for logging filter and exception handling to
    maintain consistency in how we detect invalid ProductID errors.

    Args:
        error_message: The error message to check (case-insensitive)

    Returns:
        True if the error indicates an invalid product, False otherwise
    """
    error_str = str(error_message).lower()

    # Check for various patterns that indicate invalid/delisted products
    has_invalid_keyword = 'invalid' in error_str and ('product' in error_str or 'symbol' in error_str)
    is_productid_invalid = 'productid is invalid' in error_str
    is_400_invalid_arg = '400' in error_str and 'invalid_argument' in error_str
    is_no_key_error = 'no key' in error_str and 'was found' in error_str

    return has_invalid_keyword or is_productid_invalid or is_400_invalid_arg or is_no_key_error


class _CoinbaseInvalidProductFilter(logging.Filter):
    """Filter to suppress Coinbase SDK errors for invalid/delisted products"""
    def filter(self, record):
        """
        Determine if a log record should be logged.

        Filters out ERROR-level logs from Coinbase SDK that contain
        invalid ProductID error messages, as these are expected errors
        that are already handled by exception handlers.

        Args:
            record: LogRecord instance to be filtered

        Returns:
            False if the record should be filtered out (invalid ProductID error),
            True if the record should be logged normally
        """
        # Only filter records from coinbase.RESTClient logger
        if not record.name.startswith('coinbase'):
            return True

        # Check if this is an invalid ProductID error using shared detection logic
        msg = record.getMessage()
        is_invalid_product = _is_invalid_product_error(msg)

        # Completely suppress ERROR logs for invalid products
        # Return False to prevent the log from being emitted at all
        if is_invalid_product and record.levelno >= logging.ERROR:
            return False  # Filter out completely

        # Let all other logs through
        return True


# Coinbase-specific broker implementation
class CoinbaseBroker(BaseBroker):
    """Coinbase Advanced Trade broker implementation"""

    def __init__(self, account_type: AccountType = AccountType.PLATFORM, user_id: Optional[str] = None):
        """Initialize Coinbase broker"""
        super().__init__(BrokerType.COINBASE, account_type=account_type, user_id=user_id)
        self.client: Any = None
        self.portfolio_uuid = None
        self._product_cache = {}  # Cache for product metadata (tick sizes, increments)
        self._invalid_symbols_cache = set()  # In-memory fast-lookup; backed by DelistedAssetRegistry

        # Persistent registry for delisted/invalid symbols (survives restarts)
        self._delisted_registry = get_delisted_asset_registry() if get_delisted_asset_registry else None
        if self._delisted_registry:
            # Pre-populate in-memory cache from persisted registry
            self._invalid_symbols_cache = set(self._delisted_registry.all_symbols().keys())
            if self._invalid_symbols_cache:
                logging.info(
                    f"DelistedAssetRegistry: pre-loaded {len(self._invalid_symbols_cache)} "
                    "cached invalid symbol(s) from disk"
                )

        # Cache for account data to prevent redundant API calls during initialization
        # NOTE: These caches are only accessed during bot startup in the main thread,
        # before any trading threads are spawned. Thread safety is not a concern as
        # the cache TTL (120s) expires before multi-threaded trading begins.
        self._accounts_cache = None
        self._accounts_cache_time = None
        self._balance_cache = None
        self._balance_cache_time = None
        self._cache_ttl = 120  # Cache TTL in seconds (increased from 30s to 120s to reduce API calls and avoid rate limits)

        # Initialize rate limiter for API calls to prevent 403/429 errors
        # Coinbase has strict rate limits: ~10 req/s burst but much lower sustained rate
        # Using 12 requests per minute (1 every 5 seconds) for safe sustained operation
        if RateLimiter:
            self._rate_limiter = RateLimiter(
                default_per_min=12,  # 12 requests per minute = 1 request every 5 seconds
                per_key_overrides={
                    'get_candles': 8,   # Very conservative for candle fetching (7.5s between calls = 8 req/min)
                    'get_product': 15,  # Slightly faster for product queries (4s between calls)
                    'get_all_products': 5,  # Ultra conservative for bulk product fetching (12s between calls = 5 req/min)
                    'get_fills': 12,    # Standard rate for fills fetching (5s between calls)
                }
            )
            logger.info("✅ Rate limiter initialized (12 req/min default)")
            logger.debug("   - get_candles: 8 req/min, get_all_products: 5 req/min, get_fills: 12 req/min")
        else:
            self._rate_limiter = None
            logger.warning("⚠️ RateLimiter not available - using manual delays only")

        # Initialize position tracker for profit-based exits
        # 🔒 CAPITAL PROTECTION: Position tracker is MANDATORY - no silent fallback
        try:
            from position_tracker import PositionTracker
            self.position_tracker = PositionTracker(storage_file="data/positions.json")
            logger.info("✅ Position tracker initialized for profit-based exits")
        except Exception as e:
            logger.error(f"❌ CAPITAL PROTECTION: Position tracker initialization FAILED: {e}")
            logger.error("❌ Position tracker is MANDATORY for capital protection - cannot proceed")
            raise RuntimeError(f"MANDATORY position_tracker initialization failed: {e}")

        # Entry Price Store — self-healing sync repair job (every 5 min)
        # Re-fetches real entry prices from broker fills API for any record that
        # wasn't captured at execution time, overwriting stale/override values.
        if ENTRY_PRICE_STORE_AVAILABLE and get_entry_price_store is not None:
            try:
                _eps = get_entry_price_store()
                _self_ref = self  # capture broker reference for the lambda
                _eps.start_sync_repair_job(  # type: ignore[union-attr]
                    broker_getter=lambda: _self_ref,
                    interval_secs=300,
                    symbols_getter=lambda: (
                        list(_self_ref.position_tracker.positions.keys())
                        if _self_ref.position_tracker else []
                    ),
                )
                logger.info("✅ EntryPriceStore sync repair job started (interval=300s)")
            except Exception as _eps_init_err:
                logger.warning(f"⚠️ EntryPriceStore repair job failed to start: {_eps_init_err}")


        # When balance fetch fails, preserve last known balance instead of returning 0
        self._last_known_balance = None  # Last successful balance fetch
        self._balance_last_updated = None  # Timestamp of last successful balance fetch (Jan 24, 2026)
        self._balance_fetch_errors = 0   # Count of consecutive errors
        self._is_available = True        # Broker availability flag

        # In-memory permanent cache for entry prices fetched from Coinbase fills.
        # Once fetched successfully the price is not re-fetched until the position
        # changes, eliminating redundant API calls.
        self._entry_price_cache: dict = {}
        self._entry_price_cache_lock = threading.Lock()

        # FIX 2: EXIT-ONLY mode when balance is below minimum (Jan 20, 2026)
        # Allows emergency sells even when account is too small for new entries
        self.exit_only_mode = False

        # CONNECTION STABILITY: Initialize per-broker watchdog and HTTP pool manager
        if CONNECTION_STABILITY_AVAILABLE:
            _cm_key = f"coinbase_{account_type.value}"
            if user_id:
                _cm_key = f"{_cm_key}_{user_id}"
            self._connection_stability_manager = get_connection_stability_manager(_cm_key)
            logger.info("✅ ConnectionStabilityManager attached to CoinbaseBroker")
        else:
            self._connection_stability_manager = None

        # CRITICAL FIX (Jan 11, 2026): Install logging filter to suppress invalid ProductID errors
        # The Coinbase SDK logs "ProductID is invalid" as ERROR before raising exceptions
        # These errors are expected (delisted coins) and already handled by our exception logic
        # This filter prevents log pollution while preserving our own error handling
        self._install_logging_filter()

    def _install_logging_filter(self):
        """Suppress noisy third-party loggers used by the Coinbase SDK."""
        # NOTE: Unlike handlers, filters are NOT inherited by child loggers.
        # We must add the filter to both the parent and child loggers explicitly.
        # See: https://docs.python.org/3/library/logging.html#filter-objects

        # Apply invalid-product filter to parent 'coinbase' logger
        coinbase_logger = logging.getLogger('coinbase')
        coinbase_logger.addFilter(_CoinbaseInvalidProductFilter())
        # Silence SDK info/debug chatter — only warnings and above pass through
        coinbase_logger.setLevel(logging.WARNING)

        # Apply filter to 'coinbase.RESTClient' child logger (not inherited from parent)
        rest_logger = logging.getLogger('coinbase.RESTClient')
        rest_logger.addFilter(_CoinbaseInvalidProductFilter())
        rest_logger.setLevel(logging.WARNING)

        # Silence urllib3 and http.client — they log every HTTP request at DEBUG/INFO
        for _noisy in ('urllib3', 'urllib3.connectionpool', 'http.client'):
            logging.getLogger(_noisy).setLevel(logging.WARNING)

        logging.debug("✅ Coinbase SDK logging filter installed (SDK + urllib3 silenced to WARNING)")

    def _is_cache_valid(self, cache_time) -> bool:
        """
        Check if a cache entry is still valid based on its timestamp.

        Args:
            cache_time: Timestamp when cache was last updated (or None if never cached)

        Returns:
            True if cache is still valid, False otherwise
        """
        return cache_time is not None and (time.time() - cache_time) < self._cache_ttl

    def clear_cache(self):
        """
        Clear all cached data to force fresh API calls.

        This is useful when stale cached data needs to be refreshed,
        particularly for balance checking immediately after connection.
        """
        self._balance_cache = None
        self._balance_cache_time = None
        self._accounts_cache = None
        self._accounts_cache_time = None
        logger.debug("Cache cleared (balance and accounts)")

    def _api_call_with_retry(self, api_func, *args, max_retries=3, base_delay=5.0, **kwargs):
        """
        Execute an API call with exponential backoff retry logic for rate limiting and connection errors.

        Args:
            api_func: The API function to call
            *args: Positional arguments for the API function
            max_retries: Maximum number of retry attempts (default: 3 — tightened from 5)
            base_delay: Base delay in seconds for exponential backoff (default: 5.0)
            **kwargs: Keyword arguments for the API function

        Returns:
            The API response if successful

        Raises:
            Exception: If all retries are exhausted
        """
        for attempt in range(max_retries):
            try:
                return api_func(*args, **kwargs)
            except Exception as e:
                # Catch all exceptions to handle various API error types (HTTP errors, network errors, etc.)
                # This is intentionally broad to ensure all rate limiting and connection errors are caught
                error_msg = str(e).lower()

                # Check if this is a connection error (network issues, connection reset, etc.)
                is_connection_error = (
                    'connection' in error_msg or
                    'connectionreseterror' in error_msg or
                    'connection reset' in error_msg or
                    'connection aborted' in error_msg or
                    'timeout' in error_msg or
                    'timed out' in error_msg or
                    'network' in error_msg or
                    'unreachable' in error_msg or
                    'eof occurred' in error_msg or
                    'broken pipe' in error_msg
                )

                # Check if this is a rate limiting error (403, 429, or "too many" errors)
                # Use precise pattern matching to avoid false positives
                is_403_error = (
                    '403 ' in error_msg or ' 403' in error_msg or
                    'forbidden' in error_msg or
                    'too many errors' in error_msg or
                    'too many' in error_msg  # Coinbase sometimes returns "too many" without "errors"
                )
                is_429_error = (
                    '429 ' in error_msg or ' 429' in error_msg or
                    'rate limit' in error_msg or
                    'too many requests' in error_msg
                )
                is_rate_limit = is_403_error or is_429_error

                # Determine if error is retryable
                is_retryable = is_rate_limit or is_connection_error

                # If this is the last attempt or not a retryable error, raise
                if attempt >= max_retries - 1 or not is_retryable:
                    raise

                # Calculate exponential backoff delay with maximum cap (tightened upper bounds)
                # attempt=0 → first retry delay; attempt=1 → second retry delay (max_retries=3 → 2 retries)
                # For connection errors, use moderate delays
                # For 403 errors, use longer delays (more aggressive backoff)
                if is_connection_error:
                    delay = min(base_delay * (1.5 ** attempt), 20.0)  # retry 1: 5s, retry 2: 7.5s (capped at 20s)
                    error_type = "Connection error"
                elif is_403_error:
                    delay = min(base_delay * (3 ** attempt), 30.0)   # retry 1: 5s, retry 2: 15s (capped at 30s)
                    error_type = "Rate limit (403)"
                else:
                    delay = min(base_delay * (2 ** attempt), 30.0)   # retry 1: 5s, retry 2: 10s (capped at 30s)
                    error_type = "Rate limit (429)"

                logging.warning(f"⚠️  API {error_type} (attempt {attempt + 1}/{max_retries}): {e}")
                logging.warning(f"   Waiting {delay:.1f}s before retry...")
                time.sleep(delay)

    def _log_trade_to_journal(self, symbol: str, side: str, price: float,
                               size_usd: float, quantity: float, pnl_data: Optional[dict] = None):
        """
        Log trade to trade_journal.jsonl with P&L tracking.

        Args:
            symbol: Trading symbol
            side: 'BUY' or 'SELL'
            price: Execution price
            size_usd: Trade size in USD
            quantity: Crypto quantity
            pnl_data: Optional P&L data for SELL orders (from position_tracker.calculate_pnl)
        """
        try:
            from datetime import datetime

            trade_entry = {
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "side": side,
                "price": price,
                "size_usd": size_usd,
                "quantity": quantity
            }

            # Add P&L data for SELL orders
            if pnl_data and side == 'SELL':
                trade_entry["entry_price"] = pnl_data.get('entry_price', 0)
                trade_entry["pnl_dollars"] = pnl_data.get('pnl_dollars', 0)
                trade_entry["pnl_percent"] = pnl_data.get('pnl_percent', 0)
                trade_entry["entry_value"] = pnl_data.get('entry_value', 0)

            # Append to trade journal file
            journal_file = "trade_journal.jsonl"
            with open(journal_file, 'a') as f:
                f.write(json.dumps(trade_entry) + '\n')

            logger.debug(f"Trade logged to journal: {symbol} {side} @ ${price:.2f}")
        except Exception as e:
            logger.warning(f"Failed to log trade to journal: {e}")

    def connect(self) -> bool:
        """Connect to Coinbase Advanced Trade API with retry logic"""
        # Guard: skip reconnect if already connected — prevents repeated "Connected" log spam
        if self.connected:
            return True
        try:
            from coinbase.rest import RESTClient
            import os
            import time

            # Get credentials from environment — support per-user overrides for USER accounts
            if self.account_type == AccountType.USER and self.user_id:
                # Per-user Coinbase credentials: COINBASE_USER_{USERID}_API_KEY / _API_SECRET
                _short_env, _full_env = _user_env_prefix(self.user_id)
                api_key = os.getenv(f"COINBASE_USER_{_short_env}_API_KEY", "")
                api_secret = os.getenv(f"COINBASE_USER_{_short_env}_API_SECRET", "")
                # Fallback: try full user_id in uppercase (e.g. COINBASE_USER_TANIA_GILBERT_API_KEY)
                if (not api_key or not api_secret) and _full_env != _short_env:
                    api_key = api_key or os.getenv(f"COINBASE_USER_{_full_env}_API_KEY", "")
                    api_secret = api_secret or os.getenv(f"COINBASE_USER_{_full_env}_API_SECRET", "")
                if not api_key or not api_secret:
                    logging.info(
                        "ℹ️  Coinbase USER credentials not configured for %s "
                        "(checked COINBASE_USER_%s_API_KEY / _API_SECRET) — skipping",
                        self.user_id, _short_env,
                    )
                    return False
            else:
                api_key = os.getenv("COINBASE_API_KEY")
                api_secret = os.getenv("COINBASE_API_SECRET")

            if not api_key or not api_secret:
                logging.error("❌ Coinbase API credentials not found")
                return False

            # Normalize PEM key: Railway/Docker env vars may store newlines as
            # literal '\n' two-character sequences instead of real newlines.
            if '\\n' in api_secret:
                api_secret = api_secret.replace('\\n', '\n')

            # Initialize REST client
            self.client = RESTClient(api_key=api_key, api_secret=api_secret)

            # Test connection by fetching accounts with retry logic
            # Increased max attempts for 403 "too many errors" which indicates temporary API key blocking
            # Note: 403 differs from 429 (rate limiting) - it means the API key was temporarily blocked
            max_attempts = 10  # Increased from 6 to give more chances for API to recover from rate limits

            for attempt in range(1, max_attempts + 1):
                try:
                    accounts_resp = self.client.get_accounts()

                    # Cache accounts response to avoid redundant API calls during initialization
                    self._accounts_cache = accounts_resp
                    self._accounts_cache_time = time.time()

                    self.connected = True

                    if attempt > 1:
                        logging.info(f"✅ Connected to Coinbase Advanced Trade API (succeeded on attempt {attempt})")
                    else:
                        logging.info("✅ Connected to Coinbase Advanced Trade API")

                    # Portfolio detection (will use cached accounts)
                    self._detect_portfolio()

                    # 🚑 FIX 2: DISABLE COINBASE FOR SMALL ACCOUNTS
                    # If total equity < $75, disable Coinbase and route to Kraken
                    # This prevents Coinbase fees from eating small accounts
                    try:
                        balance_data = self._get_account_balance_detailed()
                        if balance_data is None:
                            # Balance fetch failed - this is critical for small account check
                            # We MUST know account size before allowing connection
                            logging.error("=" * 70)
                            logging.error("⚠️  COINBASE CONNECTION BLOCKED")
                            logging.error("=" * 70)
                            logging.error("   Could not verify account balance")
                            logging.error("   This check prevents small accounts from using Coinbase")
                            logging.error("   ")
                            logging.error("   Possible causes:")
                            logging.error("   1. API permission issues")
                            logging.error("   2. Network connectivity problems")
                            logging.error("   3. Coinbase API temporarily unavailable")
                            logging.error("   ")
                            logging.error("   Solution: Fix API connectivity first")
                            logging.error("=" * 70)
                            self.connected = False
                            return False

                        total_funds = balance_data.get('total_funds', 0.0)

                        # EXIT-ONLY MODE DISABLED: Allow full trading regardless of balance.
                        # The balance check that previously forced exit_only_mode=True has been
                        # removed so the bot can enter new positions at any balance level.
                        if total_funds < COINBASE_MINIMUM_BALANCE:
                            logging.info(
                                f"   ℹ️  Balance ${total_funds:.2f} is below soft minimum "
                                f"${COINBASE_MINIMUM_BALANCE:.2f} — EXIT-ONLY mode is OFF, "
                                f"full trading allowed."
                            )
                        self.exit_only_mode = False  # EXIT-ONLY mode permanently OFF
                        self.connected = True
                    except Exception as balance_check_err:
                        # Balance check failed - this is CRITICAL, do NOT allow connection
                        # We cannot safely determine if account is too small
                        logging.error("=" * 70)
                        logging.error("⚠️  COINBASE CONNECTION BLOCKED")
                        logging.error("=" * 70)
                        logging.error(f"   Balance check failed: {balance_check_err}")
                        logging.error("   Cannot verify account size - blocking Coinbase connection")
                        logging.error("   ")
                        logging.error("   This safety check prevents small accounts from using Coinbase.")
                        logging.error("   Fix the balance check error before allowing Coinbase connection.")
                        logging.error("=" * 70)
                        self.connected = False
                        return False

                    # CONNECTION STABILITY: Register broker and start watchdog
                    if self._connection_stability_manager is not None:
                        self._connection_stability_manager.register_broker(
                            broker=self,
                            reconnect_fn=self.connect,
                        )
                        self._connection_stability_manager.mark_connected()
                        self._connection_stability_manager.start_watchdog()

                    return True

                except Exception as e:
                    error_msg = str(e)
                    error_msg_lower = error_msg.lower()

                    # Distinguish between error types to decide retry strategy
                    is_401_unauthorized = (
                        '401' in error_msg_lower or
                        'unauthorized' in error_msg_lower
                    )
                    is_403_forbidden = (
                        '403' in error_msg_lower or
                        'forbidden' in error_msg_lower or
                        'too many errors' in error_msg_lower
                    )
                    is_429_rate_limit = (
                        '429' in error_msg_lower or
                        'rate limit' in error_msg_lower or
                        'too many requests' in error_msg_lower
                    )
                    is_network_error = any(keyword in error_msg_lower for keyword in [
                        'timeout', 'connection', 'network', 'service unavailable',
                        '503', '504', 'temporary', 'try again'
                    ])

                    # 401 Unauthorized means invalid credentials — retrying is pointless
                    if is_401_unauthorized:
                        logging.error("❌ Coinbase authentication failed (401 Unauthorized)")
                        logging.error("   Your COINBASE_API_KEY or COINBASE_API_SECRET is invalid.")
                        logging.error("   Possible causes:")
                        logging.error("   1. API key was revoked or expired")
                        logging.error("   2. Wrong key/secret values in environment")
                        logging.error("   3. API key created for wrong account or environment")
                        logging.error("   Fix: Verify credentials at https://www.coinbase.com/settings/api")
                        logging.error("   Then run: python3 validate_all_env_vars.py")
                        return False

                    is_retryable = is_403_forbidden or is_429_rate_limit or is_network_error

                    if is_retryable and attempt < max_attempts:
                        # Use different delays based on error type
                        if is_403_forbidden:
                            # 403 errors: API key temporarily blocked - use LONG fixed delay with jitter
                            # This prevents rapid retries that make the block worse
                            delay = FORBIDDEN_BASE_DELAY + random.uniform(0, FORBIDDEN_JITTER_MAX)
                            logging.warning(f"⚠️  Connection attempt {attempt}/{max_attempts} failed (retryable): {error_msg}")
                            logging.warning(f"   API key temporarily blocked - waiting {delay:.1f}s before retry...")
                        elif is_429_rate_limit:
                            # 429 errors: Rate limit quota - use exponential backoff
                            delay = min(RATE_LIMIT_BASE_DELAY * (2 ** (attempt - 1)), 120.0)
                            logging.warning(f"⚠️  Connection attempt {attempt}/{max_attempts} failed (retryable): {error_msg}")
                            logging.warning(f"   Rate limit exceeded - waiting {delay:.1f}s before retry...")
                        else:
                            # Network errors: Moderate exponential backoff
                            delay = min(10.0 * (2 ** (attempt - 1)), 60.0)
                            logging.warning(f"⚠️  Connection attempt {attempt}/{max_attempts} failed (retryable): {error_msg}")
                            logging.warning(f"   Network error - waiting {delay:.1f}s before retry...")

                        logging.info(f"🔄 Retrying connection in {delay:.1f}s (attempt {attempt + 1}/{max_attempts})...")
                        time.sleep(delay)
                        continue
                    else:
                        logging.error(f"❌ Failed to verify Coinbase connection: {e}")
                        return False

            # Should never reach here, but just in case
            logging.error("❌ Failed to connect after maximum retry attempts")
            return False

        except ImportError:
            logging.error("❌ Coinbase SDK not installed. Run: pip install coinbase-advanced-py")
            return False
        except Exception as e:
            logging.error(f"❌ Coinbase connection error: {e}")
            return False

    def _detect_portfolio(self):
        """DISABLED: Always use default Advanced Trade portfolio"""
        try:
            # CRITICAL FIX: Do NOT auto-detect portfolio
            # The Coinbase Advanced Trade API can ONLY trade from the default trading portfolio
            # Consumer wallets (even if they show up in accounts list) CANNOT be used for trading
            # The SDK's market_order_buy() always routes to the default portfolio

            logging.debug("=" * 70)
            logging.debug("🎯 PORTFOLIO ROUTING: DEFAULT ADVANCED TRADE")
            logging.debug("=" * 70)
            logging.debug("   Using default Advanced Trade portfolio (SDK default)")
            logging.debug("   Consumer wallets are NOT accessible for trading")
            logging.debug("   Transfer funds via: https://www.coinbase.com/advanced-portfolio")
            logging.debug("=" * 70)

            # Do NOT set portfolio_uuid - let SDK use default
            self.portfolio_uuid = None

            # Use cached accounts if available to avoid redundant API calls
            try:
                if self._accounts_cache and self._is_cache_valid(self._accounts_cache_time):
                    # Use cached response
                    accounts_resp = self._accounts_cache
                    logging.debug("Using cached accounts data from connect()")
                else:
                    # Cache expired or not available, fetch fresh
                    accounts_resp = self.client.get_accounts() if hasattr(self.client, 'get_accounts') else self.client.list_accounts()
                    self._accounts_cache = accounts_resp
                    self._accounts_cache_time = time.time()

                accounts = getattr(accounts_resp, 'accounts', [])

                logging.debug("📊 ACCOUNT BALANCES (for information only):")
                logging.debug("-" * 70)

                for account in accounts:
                    currency = getattr(account, 'currency', None)
                    available_obj = getattr(account, 'available_balance', None)
                    available = float(getattr(available_obj, 'value', 0) or 0)
                    account_name = getattr(account, 'name', 'Unknown')
                    account_type = getattr(account, 'type', 'Unknown')

                    if currency in ['USD', 'USDC'] and available > 0:
                        tradeable = "✅ TRADEABLE" if account_type == "ACCOUNT_TYPE_CRYPTO" else "❌ NOT TRADEABLE (Consumer)"
                        logging.debug(f"   {currency}: ${available:.2f} | {account_name} | {tradeable}")

                logging.debug("=" * 70)

            except Exception as e:
                logging.warning(f"⚠️  Portfolio detection failed: {e}")
                logging.info("   Will use default portfolio routing")

        except Exception as e:
            logging.error(f"❌ Portfolio detection error: {e}")

    def _is_account_tradeable(self, account_type: Optional[str], platform: Optional[str]) -> bool:
        """
        IMPROVEMENT #3: Expanded account type matching patterns.
        Checks multiple patterns to identify tradeable accounts.

        Args:
            account_type: Type string from API (e.g., "ACCOUNT_TYPE_CRYPTO")
            platform: Platform string from API (e.g., "ADVANCED_TRADE")

        Returns:
            True if account is tradeable via Advanced Trade API
        """
        if not account_type:
            return False

        account_type_str = str(account_type).upper()
        platform_str = str(platform or "").upper()

        # Pattern 1: Explicit ACCOUNT_TYPE_CRYPTO
        if account_type_str == "ACCOUNT_TYPE_CRYPTO":
            return True

        # Pattern 2: Advanced Trade platform designation
        if "ADVANCED_TRADE" in platform_str or "ADVANCED" in platform_str:
            return True

        # Pattern 3: Trading portfolio indicators
        if "TRADING" in platform_str or "TRADING_PORTFOLIO" in account_type_str:
            return True

        # Pattern 4: Not explicitly a consumer/vault account
        if "CONSUMER" not in account_type_str and "VAULT" not in account_type_str and "WALLET" not in account_type_str:
            # If platform is not explicitly consumer, assume tradeable
            if platform_str and "ADVANCED" in platform_str:
                return True

        return False

    def get_all_products(self) -> list:
        """
        Fetch ALL available products (cryptocurrency pairs) from Coinbase.
        Handles pagination to retrieve 700+ markets without timeouts.
        Uses rate limiting and retry logic to prevent 403/429 errors.

        Returns:
            List of product IDs (e.g., ['BTC-USD', 'ETH-USD', ...])
        """
        try:
            logging.debug("📡 Fetching all products from Coinbase API (700+ markets)...")
            all_products = []

            # Get products with pagination
            if hasattr(self.client, 'get_products'):
                # CRITICAL FIX: Add retry logic for 403/429 rate limit errors
                # The Coinbase SDK's get_all_products=True can trigger rate limits
                # We need to retry with exponential backoff to handle temporary blocks
                max_retries = RATE_LIMIT_MAX_RETRIES
                retry_count = 0
                products_resp = None

                while retry_count <= max_retries:
                    try:
                        # CRITICAL FIX: Wrap get_products() call with rate limiting
                        # The Coinbase SDK's get_all_products=True internally makes multiple paginated
                        # requests rapidly, which can exhaust rate limits before market scanning begins
                        # Using rate limiter with retry logic to prevent 403 "Forbidden" errors

                        def _fetch_products():
                            """Inner function for rate-limited product fetching"""
                            return self.client.get_products(get_all_products=True)

                        # Apply rate limiting if available
                        if self._rate_limiter:
                            # Rate-limited call - enforces minimum interval between requests
                            products_resp = self._rate_limiter.call('get_all_products', _fetch_products)
                        else:
                            # Fallback to direct call without rate limiting
                            products_resp = _fetch_products()

                        # Success! Break out of retry loop
                        break

                    except Exception as fetch_err:
                        error_str = str(fetch_err)

                        # Check if it's a rate limit error (403 or 429)
                        is_rate_limit = '429' in error_str or 'rate limit' in error_str.lower()
                        is_forbidden = '403' in error_str or 'forbidden' in error_str.lower() or 'too many' in error_str.lower()

                        if (is_rate_limit or is_forbidden) and retry_count < max_retries:
                            retry_count += 1

                            # Calculate backoff delay
                            if is_forbidden:
                                # 403 errors: Use fixed delay with jitter (API key temporarily blocked)
                                delay = FORBIDDEN_BASE_DELAY + random.uniform(0, FORBIDDEN_JITTER_MAX)
                                logging.warning(f"⚠️  Rate limit (403 Forbidden): API key temporarily blocked on get_all_products, waiting {delay:.1f}s before retry {retry_count}/{max_retries}")
                            else:
                                # 429 errors: Use exponential backoff
                                delay = RATE_LIMIT_BASE_DELAY * (2 ** (retry_count - 1))
                                logging.warning(f"⚠️  Rate limit (429 Too Many Requests): Quota exceeded on get_all_products, waiting {delay:.1f}s before retry {retry_count}/{max_retries}")

                            time.sleep(delay)
                            continue
                        else:
                            # Not a rate limit error or max retries reached
                            raise fetch_err

                # Check if we successfully fetched products
                if not products_resp:
                    logging.error("⚠️  Failed to fetch products after retries")
                    return FALLBACK_MARKETS

                # Log response type and structure
                logging.debug(f"   Response type: {type(products_resp).__name__}")

                # Handle both object and dict responses
                if hasattr(products_resp, 'products'):
                    products = products_resp.products
                    logging.debug(f"   Extracted {len(products) if products else 0} products from .products attribute")
                elif isinstance(products_resp, dict):
                    products = products_resp.get('products', [])
                    logging.debug(f"   Extracted {len(products)} products from dict['products']")
                else:
                    products = []
                    logging.warning(f"⚠️  Unexpected response type: {type(products_resp).__name__}")

                if not products:
                    logging.warning("⚠️  No products returned from API - response may be empty or malformed")
                    # Debug: Show what attributes/keys are available
                    if hasattr(products_resp, '__dict__'):
                        attrs = [k for k in dir(products_resp) if not k.startswith('_')][:10]
                        logging.info(f"   Available attributes: {attrs}")
                    elif isinstance(products_resp, dict):
                        logging.info(f"   Available keys: {list(products_resp.keys())}")
                    return []

                # Extract product IDs - handle various response formats
                # CRITICAL FIX (Jan 10, 2026): Add status filtering to exclude delisted/disabled products
                # This prevents invalid symbols (e.g., 2Z-USD, AGLD-USD, HIO, BOE) from causing API errors
                filtered_count = 0
                filtered_products_count = 0  # Tracks all filtered products (status, disabled, format)
                DEBUG_LOG_LIMIT = 5  # Maximum number of filtered products to log at debug level

                for i, product in enumerate(products):
                    product_id = None
                    status = None
                    trading_disabled = False

                    # Debug first product to understand structure
                    if i == 0:
                        if hasattr(product, '__dict__'):
                            attrs = [k for k in dir(product) if not k.startswith('_')][:10]
                            logging.debug(f"   First product attributes: {attrs}")
                        elif isinstance(product, dict):
                            logging.debug(f"   First product keys: {list(product.keys())[:10]}")

                    # Try object attribute access (Coinbase uses 'product_id', not 'id')
                    if hasattr(product, 'product_id'):
                        product_id = getattr(product, 'product_id', None)
                        status = getattr(product, 'status', None)
                        trading_disabled = getattr(product, 'trading_disabled', False)
                    elif hasattr(product, 'id'):
                        product_id = getattr(product, 'id', None)
                        status = getattr(product, 'status', None)
                        trading_disabled = getattr(product, 'trading_disabled', False)
                    # Try dict access
                    elif isinstance(product, dict):
                        product_id = product.get('product_id') or product.get('id')
                        status = product.get('status')
                        trading_disabled = product.get('trading_disabled', False)

                    # CRITICAL FILTERS to prevent invalid symbol errors:
                    # 1. Must have product_id
                    if not product_id:
                        continue

                    # 2. Must be USD or USDC pair
                    if not (product_id.endswith('-USD') or product_id.endswith('-USDC')):
                        continue

                    # 3. Status must be 'online' (exclude offline, delisted, etc.)
                    # This is the KEY fix - prevents delisted coins from being scanned
                    if not status or status.lower() != 'online':
                        filtered_products_count += 1
                        if filtered_products_count <= DEBUG_LOG_LIMIT:  # Log first 5 for debugging
                            logging.debug(f"   Filtered out {product_id}: status={status}")
                        continue

                    # 4. Trading must not be disabled
                    if trading_disabled:
                        filtered_products_count += 1
                        if filtered_products_count <= DEBUG_LOG_LIMIT:
                            logging.debug(f"   Filtered out {product_id}: trading_disabled=True")
                        continue

                    # 5. Validate symbol format (basic sanity check)
                    # Valid format: 2-8 chars, dash, USD/USDC
                    parts = product_id.split('-')
                    if len(parts) != 2 or len(parts[0]) < 2 or len(parts[0]) > 8:
                        filtered_products_count += 1
                        if filtered_products_count <= DEBUG_LOG_LIMIT:
                            logging.debug(f"   Filtered out {product_id}: invalid format (length)")
                        continue

                    # Passed all filters - add to list
                    all_products.append(product_id)

                if filtered_products_count > 0:
                    logging.debug(f"   Filtered out {filtered_products_count} products (offline/delisted/disabled/invalid format)")

                logging.debug(f"   Fetched {len(products)} total products, {len(all_products)} USD/USDC pairs after filtering")

                # Remove duplicates and sort
                all_products = sorted(list(set(all_products)))

                logging.info(f"✅ Coinbase: {len(all_products)} markets ready")
                logging.debug(f"   Sample markets: {', '.join(all_products[:10])}")

                # CRITICAL FIX (Jan 10, 2026): Add cooldown after get_all_products to prevent burst
                # This gives the API time to reset before we start scanning markets
                logging.debug("   💤 Cooling down for 10s after bulk product fetch to prevent rate limiting...")
                time.sleep(10.0)

                return all_products

            # Fallback: Use curated list of popular crypto markets
            logging.warning("⚠️  Could not fetch products from API, using fallback list of popular markets")
            logging.debug(f"   Using {len(FALLBACK_MARKETS)} fallback markets")
            return FALLBACK_MARKETS

        except Exception as e:
            logging.error(f"🔥 Error fetching all products: {e}")
            return []

    def _get_account_balance_detailed(self, verbose: bool = True):
        """Return ONLY tradable Advanced Trade USD/USDC balances (detailed version).

        Coinbase frequently shows Consumer wallet balances that **cannot** be used
        for Advanced Trade orders. To avoid false positives (and endless
        INSUFFICIENT_FUND rejections), we enumerate accounts and only count
        ones marked as Advanced Trade / crypto accounts.

        IMPROVEMENTS:
        1. Better consumer wallet diagnostics - tells user to transfer funds
        2. API permission validation - checks if we can see accounts
        3. Expanded account type matching - handles more Coinbase account types
        4. Caching - reuses accounts data from connect() to avoid redundant API calls

        Args:
            verbose: If True, logs detailed balance breakdown (default: True)

        Returns dict with: {"usdc", "usd", "trading_balance", "crypto", "consumer_*"}
        """
        # Check if we have a cached balance (during initialization only)
        if self._balance_cache and self._is_cache_valid(self._balance_cache_time):
            logging.debug("Using cached balance data")
            return self._balance_cache

        usd_balance = 0.0
        usdc_balance = 0.0
        usd_held = 0.0  # Track held funds (in open orders/positions)
        usdc_held = 0.0
        consumer_usd = 0.0
        consumer_usdc = 0.0
        crypto_holdings = {}
        accounts_seen = 0
        tradeable_accounts = 0

        # Preferred path: portfolio breakdown (more reliable than get_accounts)
        try:
            if verbose:
                logging.info("💰 Fetching account balance via portfolio breakdown (preferred)...")

            # 🔒 CAPITAL PROTECTION: Use exactly 3 retries for balance fetch operations
            # Use retry logic for portfolio API calls to handle rate limiting
            portfolios_resp = None
            if hasattr(self.client, 'get_portfolios'):
                portfolios_resp = self._api_call_with_retry(
                    self.client.get_portfolios,
                    max_retries=BALANCE_FETCH_MAX_RETRIES
                )

            portfolios = getattr(portfolios_resp, 'portfolios', [])
            if isinstance(portfolios_resp, dict):
                portfolios = portfolios_resp.get('portfolios', [])

            default_portfolio = None
            for pf in portfolios:
                pf_type = getattr(pf, 'type', None) if not isinstance(pf, dict) else pf.get('type')
                if str(pf_type).upper() == 'DEFAULT':
                    default_portfolio = pf
                    break
            if not default_portfolio and portfolios:
                default_portfolio = portfolios[0]

            portfolio_uuid = None
            if default_portfolio:
                portfolio_uuid = getattr(default_portfolio, 'uuid', None)
                if isinstance(default_portfolio, dict):
                    portfolio_uuid = default_portfolio.get('uuid', portfolio_uuid)

            if default_portfolio and portfolio_uuid:
                # 🔒 CAPITAL PROTECTION: Use exactly 3 retries for balance fetch operations
                # Use retry logic for portfolio breakdown API call
                breakdown_resp = self._api_call_with_retry(
                    self.client.get_portfolio_breakdown,
                    portfolio_uuid=portfolio_uuid,
                    max_retries=BALANCE_FETCH_MAX_RETRIES
                )
                breakdown = getattr(breakdown_resp, 'breakdown', None)
                if isinstance(breakdown_resp, dict):
                    breakdown = breakdown_resp.get('breakdown', breakdown)

                spot_positions = getattr(breakdown, 'spot_positions', []) if breakdown else []
                if isinstance(breakdown, dict):
                    spot_positions = breakdown.get('spot_positions', spot_positions)

                logging.debug(f"💡 Portfolio breakdown: Found {len(spot_positions)} spot positions")

                for pos in spot_positions:
                    asset = getattr(pos, 'asset', None) if not isinstance(pos, dict) else pos.get('asset')
                    available_val = getattr(pos, 'available_to_trade_fiat', None) if not isinstance(pos, dict) else pos.get('available_to_trade_fiat')
                    # Try to get held amount if available in the response
                    held_val = getattr(pos, 'hold_fiat', None) if not isinstance(pos, dict) else pos.get('hold_fiat')

                    # CRITICAL FIX (Jan 24, 2026): Use CORRECT Coinbase API field names
                    # The Coinbase Advanced Trade API uses:
                    # - available_to_trade_crypto (amount freely tradable in crypto units)
                    # - total_balance_crypto (total balance in crypto units)
                    # NOT the old field names: available_to_trade_base, hold_base, available_to_trade, hold
                    base_available = None
                    base_total = None
                    if isinstance(pos, dict):
                        base_available = pos.get('available_to_trade_crypto')
                        base_total = pos.get('total_balance_crypto')
                        # Debug: log what fields are available in the response
                        if asset and asset not in ['USD', 'USDC']:
                            logging.debug(f"   📊 {asset} API fields: total_balance_crypto={base_total}, available_to_trade_crypto={base_available}")
                    else:
                        base_available = getattr(pos, 'available_to_trade_crypto', None)
                        base_total = getattr(pos, 'total_balance_crypto', None)
                        # Debug: log what fields are available in the response
                        if asset and asset not in ['USD', 'USDC']:
                            logging.debug(f"   📊 {asset} API fields: total_balance_crypto={base_total}, available_to_trade_crypto={base_available}")

                    try:
                        available = float(available_val or 0)
                    except Exception:
                        available = 0.0

                    try:
                        held = float(held_val or 0)
                    except Exception:
                        held = 0.0

                    try:
                        base_avail_qty = float(base_available or 0)
                    except Exception:
                        base_avail_qty = 0.0

                    try:
                        base_total_qty = float(base_total or 0)
                    except Exception:
                        base_total_qty = 0.0

                    if asset == 'USD':
                        usd_balance += available
                        usd_held += held
                    elif asset == 'USDC':
                        usdc_balance += available
                        usdc_held += held
                    elif asset:
                        # CRITICAL FIX (Jan 24, 2026): Use total_balance_crypto which includes available + held
                        # This ensures sells can find the FULL position on the exchange
                        # The API provides total_balance_crypto which is the complete amount we own
                        if base_total_qty is not None and base_total_qty > 0:
                            # Use total balance in crypto units (e.g., BTC amount, not USD value)
                            crypto_holdings[asset] = crypto_holdings.get(asset, 0.0) + base_total_qty
                            # Calculate held amount (total - available), ensure non-negative
                            base_held_qty = max(0, base_total_qty - base_avail_qty)
                            if base_held_qty > 0:
                                logging.debug(f"   {asset}: available={base_avail_qty:.8f}, held={base_held_qty:.8f}, total={base_total_qty:.8f}")
                            else:
                                logging.debug(f"   {asset}: total={base_total_qty:.8f}")
                        elif base_avail_qty > 0:
                            # Fallback: if only available_to_trade_crypto is present
                            crypto_holdings[asset] = crypto_holdings.get(asset, 0.0) + base_avail_qty
                            logging.debug(f"   {asset}: available={base_avail_qty:.8f} (total not available)")
                        else:
                            # Last fallback: if base quantities not available, skip (don't use fiat values)
                            # This prevents incorrect calculations
                            logging.debug(f"   {asset}: No crypto quantity data available in API response")

                trading_balance = usd_balance + usdc_balance
                total_held = usd_held + usdc_held
                total_funds = trading_balance + total_held

                if verbose:
                    logging.info("-" * 70)
                    logging.info(f"   💰 Available USD (portfolio):  ${usd_balance:.2f}")
                    logging.info(f"   💰 Available USDC (portfolio): ${usdc_balance:.2f}")
                    logging.info(f"   💰 Total Available: ${trading_balance:.2f}")
                    if total_held > 0:
                        logging.info(f"   🔒 Held USD:  ${usd_held:.2f} (in open orders/positions)")
                        logging.info(f"   🔒 Held USDC: ${usdc_held:.2f} (in open orders/positions)")
                        logging.info(f"   🔒 Total Held: ${total_held:.2f}")
                        logging.info(f"   💎 TOTAL FUNDS (Available + Held): ${total_funds:.2f}")
                    logging.info("   (Source: get_portfolio_breakdown)")
                    logging.info("-" * 70)

                result = {
                    "usdc": usdc_balance,
                    "usd": usd_balance,
                    "trading_balance": trading_balance,
                    "usd_held": usd_held,
                    "usdc_held": usdc_held,
                    "total_held": total_held,
                    "total_funds": total_funds,
                    "crypto": crypto_holdings,
                    "consumer_usd": consumer_usd,
                    "consumer_usdc": consumer_usdc,
                }

                # Cache the result
                self._balance_cache = result
                self._balance_cache_time = time.time()

                return result
            else:
                logging.warning("⚠️  No default portfolio found; falling back to get_accounts()")
        except Exception as e:
            # Format connection errors more clearly for better readability
            error_msg = str(e)
            if 'ConnectionResetError' in error_msg or 'Connection reset' in error_msg:
                logging.warning("⚠️  Portfolio breakdown failed: Network connection reset by Coinbase API")
                logging.warning("   Falling back to get_accounts() method...")
            elif 'Connection aborted' in error_msg or 'ConnectionAbortedError' in error_msg:
                logging.warning("⚠️  Portfolio breakdown failed: Network connection aborted")
                logging.warning("   Falling back to get_accounts() method...")
            elif 'timeout' in error_msg.lower() or 'timed out' in error_msg.lower():
                logging.warning("⚠️  Portfolio breakdown failed: API request timed out")
                logging.warning("   Falling back to get_accounts() method...")
            else:
                logging.warning(f"⚠️  Portfolio breakdown failed, falling back to get_accounts(): {error_msg}")

        try:
            if verbose:
                logging.info("💰 Fetching account balance (Advanced Trade only)...")

            # Use cached accounts if available to avoid redundant API calls
            if self._accounts_cache and self._is_cache_valid(self._accounts_cache_time):
                logging.debug("Using cached accounts data")
                resp = self._accounts_cache
            else:
                # 🔒 CAPITAL PROTECTION: Use exactly 3 retries for balance fetch operations
                # Use retry logic for get_accounts API call to handle rate limiting
                resp = self._api_call_with_retry(
                    self.client.get_accounts,
                    max_retries=BALANCE_FETCH_MAX_RETRIES
                )
                self._accounts_cache = resp
                self._accounts_cache_time = time.time()

            accounts = getattr(resp, 'accounts', []) or (resp.get('accounts', []) if isinstance(resp, dict) else [])

            # IMPROVEMENT #2: Validate API permissions
            if not accounts:
                if verbose:
                    logging.warning("=" * 70)
                    logging.warning("⚠️  API PERMISSION CHECK: Zero accounts returned")
                    logging.warning("=" * 70)
                    logging.warning("This usually means:")
                    logging.warning("  1. ❌ API key lacks 'View account details' permission")
                    logging.warning("  2. ❌ No Advanced Trade portfolio created yet")
                    logging.warning("  3. ❌ Wrong API credentials for this account")
                    logging.warning("")
                    logging.warning("FIX:")
                    logging.warning("  1. Go to: https://portal.cloud.coinbase.com/access/api")
                    logging.warning("  2. Edit your API key → Enable 'View' permission")
                    logging.warning("  3. Or create portfolio: https://www.coinbase.com/advanced-portfolio")
                    logging.warning("=" * 70)

            if verbose:
                logging.info("=" * 70)
                logging.info("📊 ACCOUNT BALANCES (v3 get_accounts)")
                logging.info(f"📁 Total accounts returned: {len(accounts)}")
                logging.info("=" * 70)

            for acc in accounts:
                accounts_seen += 1
                # Normalize object/dict access
                if isinstance(acc, dict):
                    currency = acc.get('currency')
                    name = acc.get('name')
                    platform = acc.get('platform')
                    account_type = acc.get('type')
                    available_val = (acc.get('available_balance') or {}).get('value')
                    hold_val = (acc.get('hold') or {}).get('value')
                else:
                    currency = getattr(acc, 'currency', None)
                    name = getattr(acc, 'name', None)
                    platform = getattr(acc, 'platform', None)
                    account_type = getattr(acc, 'type', None)
                    available_val = getattr(getattr(acc, 'available_balance', None), 'value', None)
                    hold_val = getattr(getattr(acc, 'hold', None), 'value', None)

                try:
                    available = float(available_val or 0)
                    hold = float(hold_val or 0)
                except Exception:
                    available = 0.0
                    hold = 0.0

                # IMPROVEMENT #3: Use expanded matching function
                is_tradeable = self._is_account_tradeable(account_type, platform)
                if is_tradeable:
                    tradeable_accounts += 1

                if currency in ("USD", "USDC"):
                    location = "✅ TRADEABLE" if is_tradeable else "❌ CONSUMER"
                    logging.info(
                        f"   {currency:>4} | avail=${available:8.2f} | hold=${hold:8.2f} | type={account_type} | platform={platform} | {location}"
                    )

                    if is_tradeable:
                        if currency == "USD":
                            usd_balance += available
                            usd_held += hold  # Track held funds
                        else:
                            usdc_balance += available
                            usdc_held += hold  # Track held funds
                    else:
                        # IMPROVEMENT #1: Better consumer wallet diagnostics
                        if currency == "USD":
                            consumer_usd += available
                        else:
                            consumer_usdc += available
                elif currency and (available > 0 or hold > 0):
                    # Track non-cash crypto holdings ONLY if tradeable via API
                    # Consumer wallet positions cannot be traded and will cause INSUFFICIENT_FUND errors
                    if is_tradeable:
                        # CRITICAL FIX: Include HELD crypto, not just available
                        # This ensures sells can see the full position (available + held in orders/positions)
                        # Use same logic as portfolio breakdown path for consistency
                        total_crypto = available + hold
                        if total_crypto > 0:
                            crypto_holdings[currency] = total_crypto
                            if hold > 0:
                                logging.info(
                                    f"   ✅ 🪙 {currency}: available={available:.8f}, held={hold:.8f}, total={total_crypto:.8f} (type={account_type}, platform={platform})"
                                )
                            else:
                                logging.info(
                                    f"   ✅ 🪙 {currency}: {available:.8f} (type={account_type}, platform={platform})"
                                )
                    else:
                        # Log consumer wallet holdings separately but don't add to crypto_holdings
                        logging.info(
                            f"   ⏭️  {currency}: {available} in CONSUMER wallet (not API-tradeable, skipping)"
                        )

            trading_balance = usd_balance + usdc_balance
            total_held = usd_held + usdc_held
            total_funds = trading_balance + total_held

            if verbose:
                logging.info("-" * 70)
                logging.info(f"   💰 Available USD:  ${usd_balance:.2f}")
                logging.info(f"   💰 Available USDC: ${usdc_balance:.2f}")
                logging.info(f"   💰 Total Available: ${trading_balance:.2f}")
                if total_held > 0:
                    logging.info(f"   🔒 Held USD:  ${usd_held:.2f} (in open orders/positions)")
                    logging.info(f"   🔒 Held USDC: ${usdc_held:.2f} (in open orders/positions)")
                    logging.info(f"   🔒 Total Held: ${total_held:.2f}")
                    logging.info(f"   💎 TOTAL FUNDS (Available + Held): ${total_funds:.2f}")
                logging.info(f"   🪙 Crypto Holdings: {len(crypto_holdings)} assets")

            # IMPROVEMENT #1: Enhanced consumer wallet detection and diagnosis
            if consumer_usd > 0 or consumer_usdc > 0:
                if verbose:
                    logging.warning("-" * 70)
                    logging.warning("⚠️  CONSUMER WALLET DETECTED:")
                    logging.warning(f"   🏦 Consumer USD:  ${consumer_usd:.2f}")
                    logging.warning(f"   🏦 Consumer USDC: ${consumer_usdc:.2f}")
                    logging.warning("")
                    logging.warning("These funds are in your Coinbase Consumer wallet and")
                    logging.warning("CANNOT be used for Advanced Trade API orders.")
                    logging.warning("")
                    logging.warning("TO FIX:")
                    logging.warning("  1. Go to: https://www.coinbase.com/advanced-portfolio")
                    logging.warning("  2. Click 'Deposit' on the Advanced Trade portfolio")
                    logging.warning(f"  3. Transfer ${consumer_usd + consumer_usdc:.2f} from Consumer wallet")
                    logging.warning("")
                    logging.warning("After transfer, bot will see funds and start trading! ✅")
                    logging.warning("-" * 70)

            if verbose:
                logging.info(f"📊 API Status: Saw {accounts_seen} accounts, {tradeable_accounts} tradeable")
                logging.info(f"   💎 Tradeable crypto holdings: {len(crypto_holdings)} assets")
                logging.info("=" * 70)

            result = {
                "usdc": usdc_balance,
                "usd": usd_balance,
                "trading_balance": trading_balance,
                "usd_held": usd_held,
                "usdc_held": usdc_held,
                "total_held": total_held,
                "total_funds": total_funds,
                "crypto": crypto_holdings,
                "consumer_usd": consumer_usd,
                "consumer_usdc": consumer_usdc,
            }

            # Cache the result
            self._balance_cache = result
            self._balance_cache_time = time.time()

            return result
        except Exception as e:
            logging.error(f"🔥 ERROR get_account_balance: {e}")
            logging.error("This usually indicates:")
            logging.error("  1. Invalid API credentials")
            logging.error("  2. Network connectivity issue")
            logging.error("  3. Coinbase API temporarily unavailable")
            logging.error("")
            logging.error("Verify your credentials at:")
            logging.error("  https://portal.cloud.coinbase.com/access/api")
            import traceback
            logging.error(traceback.format_exc())
            return {
                "usdc": usdc_balance,
                "usd": usd_balance,
                "trading_balance": usd_balance + usdc_balance,
                "usd_held": 0.0,
                "usdc_held": 0.0,
                "total_held": 0.0,
                "total_funds": usd_balance + usdc_balance,
                "crypto": crypto_holdings,
                "consumer_usd": consumer_usd,
                "consumer_usdc": consumer_usdc,
            }

    def get_account_balance(self, verbose: bool = True) -> float:
        """Get USD trading balance with fail-closed behavior (conforms to BaseBroker interface).

        🚑 FIX 4: BALANCE MUST INCLUDE LOCKED FUNDS
        Returns total_equity (available + locked) instead of just available_usd.
        This prevents NIJA from thinking it's broke when it has funds locked in positions.

        CRITICAL FIX (Jan 19, 2026): Fail closed - not "balance = 0"
        - On error: Return last known balance (if available) instead of 0
        - Track consecutive errors to mark broker unavailable
        - Distinguish API errors from actual zero balance

        Args:
            verbose: If True, logs detailed balance breakdown (default: True)

        Returns:
            float: TOTAL EQUITY (cash + positions) not just available cash
                   Returns last known balance on error (not 0)
        """
        try:
            balance_data = self._get_account_balance_detailed(verbose=verbose)

            if balance_data is None:
                # 🔒 CAPITAL PROTECTION: After 3 failed retries, pause trading cycle
                # API call failed - use last known balance if available
                self._balance_fetch_errors += 1
                if self._balance_fetch_errors >= BROKER_MAX_CONSECUTIVE_ERRORS:
                    self._is_available = False
                    self.exit_only_mode = True  # Pause new entries, only allow exits
                    logger.error(f"❌ CAPITAL PROTECTION: Coinbase balance fetch failed after {self._balance_fetch_errors} retries")
                    logger.error(f"❌ Trading cycle PAUSED - entering EXIT-ONLY mode")

                if self._last_known_balance is not None:
                    logger.warning(f"⚠️ Coinbase balance fetch failed, using last known balance: ${self._last_known_balance:.2f}")
                    return self._last_known_balance
                else:
                    logger.error("❌ Coinbase balance fetch failed and no last known balance available, returning 0.0")
                    return 0.0

            # 🚑 FIX 4: Return total_funds (available + locked) instead of just trading_balance
            # This ensures rotation and sizing use TOTAL EQUITY not just free cash
            # Fallback chain: total_funds -> trading_balance -> 0.0
            total_funds = balance_data.get('total_funds', None)
            if total_funds is None:
                total_funds = balance_data.get('trading_balance', 0.0)
            result = float(total_funds)

            # Log what we're returning for transparency
            trading_balance = float(balance_data.get('trading_balance', 0.0))
            total_held = float(balance_data.get('total_held', 0.0))

            if total_held > 0:
                logger.debug(f"💎 Total Equity: ${result:.2f} (Available: ${trading_balance:.2f} + Locked: ${total_held:.2f})")
            else:
                logger.debug(f"💰 Total Equity: ${result:.2f} (no locked funds)")

            # SUCCESS: Update last known balance and reset error count
            self._last_known_balance = result
            self._balance_last_updated = time.time()  # Track when balance was last updated (Jan 24, 2026)
            self._balance_fetch_errors = 0
            self._is_available = True
            # 🔒 CAPITAL PROTECTION: Resume trading if it was paused due to balance errors
            if self.exit_only_mode:
                logger.info("✅ Balance fetch successful - resuming normal trading (EXIT-ONLY mode cleared)")
                self.exit_only_mode = False

            return result

        except Exception as e:
            logger.error(f"❌ Exception fetching Coinbase balance: {e}")
            self._balance_fetch_errors += 1
            if self._balance_fetch_errors >= BROKER_MAX_CONSECUTIVE_ERRORS:
                self._is_available = False
                self.exit_only_mode = True  # Pause new entries after consecutive errors
                logger.error(f"❌ CAPITAL PROTECTION: Coinbase marked unavailable after {self._balance_fetch_errors} consecutive errors")
                logger.error(f"❌ Trading cycle PAUSED - entering EXIT-ONLY mode")

            # Return last known balance instead of 0
            if self._last_known_balance is not None:
                logger.warning(f"   ⚠️ Using last known balance: ${self._last_known_balance:.2f}")
                return self._last_known_balance

            return 0.0

    def get_account_balance_detailed(self, verbose: bool = True) -> dict:
        """Get detailed account balance information including crypto holdings.

        This is a public wrapper around _get_account_balance_detailed() for
        callers that need the full balance breakdown (crypto holdings, consumer wallets, etc).

        Args:
            verbose: If True, logs detailed balance breakdown (default: True)

        Returns:
            dict: Detailed balance info with keys: usdc, usd, trading_balance, crypto, consumer_usd, consumer_usdc
        """
        return self._get_account_balance_detailed(verbose=verbose)

    def cancel_all_orders(self) -> int:
        """Cancel all open orders on Coinbase.

        Uses the Coinbase Advanced Trade API to list and cancel every open
        order. Delegates to the base-class default if the client is not yet
        initialized.

        Returns:
            int: Number of orders successfully cancelled.
        """
        if self.client is None:
            return 0

        cancelled = 0
        try:
            resp = self.client.list_orders(order_status=["OPEN"])
            orders = getattr(resp, 'orders', None)
            if isinstance(resp, dict):
                orders = resp.get('orders', [])
            if not orders:
                return 0

            for order in orders:
                order_id = (
                    order.get('order_id') if isinstance(order, dict)
                    else getattr(order, 'order_id', None)
                )
                if not order_id:
                    continue
                try:
                    self.client.cancel_orders(order_ids=[order_id])
                    logger.info(f"   ✅ Cancelled Coinbase order: {order_id}")
                    cancelled += 1
                except Exception as exc:
                    logger.warning(f"   ⚠️ Could not cancel order {order_id}: {exc}")
        except Exception as e:
            logger.error(f"cancel_all_orders: Coinbase error: {e}")

        return cancelled

    def is_available(self) -> bool:
        """
        Check if Coinbase broker is available for trading.

        Returns False if there have been 3+ consecutive balance fetch errors.
        This prevents trading when the API is not working properly.

        Returns:
            bool: True if broker is available, False if unavailable
        """
        return self._is_available

    def get_error_count(self) -> int:
        """
        Get the number of consecutive balance fetch errors.

        Returns:
            int: Number of consecutive errors
        """
        return self._balance_fetch_errors

    def get_total_capital(self, include_positions: bool = True) -> Dict:
        """
        Get total capital including both free balance and open position values.

        PRO MODE Feature: Counts open positions as available capital for rotation trading.

        Args:
            include_positions: If True, includes position values in total capital (default True)

        Returns:
            dict: Capital breakdown with keys:
                - free_balance: Available USD/USDC for new trades
                - position_value: Total USD value of all open positions
                - total_capital: free_balance + position_value
                - positions: List of positions with values
                - position_count: Number of open positions
        """
        try:
            # Get free balance
            free_balance = self.get_account_balance()

            # Get positions and calculate their values
            positions = self.get_positions()
            position_value_total = 0.0
            position_details = []

            if include_positions:
                for pos in positions:
                    symbol = pos.get('symbol')
                    quantity = pos.get('quantity', 0)

                    if not symbol or quantity <= 0:
                        continue

                    # Get current price for position
                    try:
                        price = self.get_current_price(symbol)
                        if price > 0:
                            value = quantity * price
                            position_value_total += value
                            position_details.append({
                                'symbol': symbol,
                                'quantity': quantity,
                                'price': price,
                                'value': value
                            })
                    except Exception as price_err:
                        logger.warning(f"⚠️ Could not get price for {symbol}: {price_err}")
                        continue

            total_capital = free_balance + position_value_total

            result = {
                'free_balance': free_balance,
                'position_value': position_value_total,
                'total_capital': total_capital,
                'positions': position_details,
                'position_count': len(position_details)
            }

            logger.debug(f"💰 Total capital: ${total_capital:.2f} (free: ${free_balance:.2f}, positions: ${position_value_total:.2f})")

            return result

        except Exception as e:
            logger.error(f"Error calculating total capital: {e}")
            return {
                'free_balance': 0.0,
                'position_value': 0.0,
                'total_capital': 0.0,
                'positions': [],
                'position_count': 0
            }

    def get_account_balance_OLD_BROKEN_METHOD(self):
        """
        OLD METHOD - DOES NOT WORK - Kept for reference
        Parse balances from ONLY v3 Advanced Trade API

        CRITICAL: Consumer wallet balances are NOT usable for API trading.
        Only Advanced Trade portfolio balance can be used for orders.
        This method ONLY returns Advanced Trade balance to prevent mismatches.
        """
        usd_balance = 0.0
        usdc_balance = 0.0
        consumer_usd = 0.0
        consumer_usdc = 0.0
        crypto_holdings: Dict[str, float] = {}

        try:
            # Check v2 Consumer wallets for DIAGNOSTIC purposes only
            logging.info(f"💰 Checking v2 API (Consumer wallets - DIAGNOSTIC ONLY)...")
            try:
                import requests
                import time
                import jwt
                from cryptography.hazmat.primitives import serialization

                api_key = os.getenv("COINBASE_API_KEY")
                api_secret = os.getenv("COINBASE_API_SECRET")

                if not api_secret:
                    raise ValueError("COINBASE_API_SECRET environment variable not set")

                # Normalize PEM
                if '\\n' in api_secret:
                    api_secret = api_secret.replace('\\n', '\n')

                from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePrivateKey
                private_key = serialization.load_pem_private_key(api_secret.encode('utf-8'), password=None)
                if not isinstance(private_key, EllipticCurvePrivateKey):
                    raise ValueError("Expected EC private key for Coinbase JWT")

                # Make v2 API call
                uri = "GET api.coinbase.com/v2/accounts"
                payload = {
                    'sub': api_key,
                    'iss': 'coinbase-cloud',
                    'nbf': int(time.time()),
                    'exp': int(time.time()) + 120,
                    'aud': ['coinbase-apis'],
                    'uri': uri
                }
                token = jwt.encode(payload, private_key, algorithm='ES256',
                                  headers={'kid': api_key, 'nonce': str(int(time.time()))})
                headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
                response = requests.get(f"https://api.coinbase.com/v2/accounts", headers=headers, timeout=10)

                if response.status_code == 200:
                    data = response.json()
                    v2_accounts = data.get('data', [])
                    logging.info(f"📁 v2 Consumer API: {len(v2_accounts)} account(s)")

                    for acc in v2_accounts:
                        currency_obj = acc.get('currency', {})
                        currency = currency_obj.get('code', 'N/A') if isinstance(currency_obj, dict) else currency_obj
                        balance_obj = acc.get('balance', {})
                        balance = float(balance_obj.get('amount', 0) if isinstance(balance_obj, dict) else balance_obj or 0)
                        account_type = acc.get('type', 'unknown')
                        name = acc.get('name', 'Unknown')

                        if currency == "USD":
                            consumer_usd += balance
                            if balance > 0:
                                logging.info(f"   📊 Consumer USD: ${balance:.2f} (type={account_type}, name={name}) [NOT TRADABLE VIA API]")
                        elif currency == "USDC":
                            consumer_usdc += balance
                            if balance > 0:
                                logging.info(f"   📊 Consumer USDC: ${balance:.2f} (type={account_type}, name={name}) [NOT TRADABLE VIA API]")
                else:
                    logging.warning(f"⚠️  v2 API returned status {response.status_code}")

            except Exception as v2_error:
                logging.warning(f"⚠️  v2 API check failed: {v2_error}")

            # Check v3 Advanced Trade API - THIS IS THE ONLY TRADABLE BALANCE
            logging.info(f"💰 Checking v3 API (Advanced Trade - TRADABLE BALANCE)...")
            try:
                logging.info(f"   🔍 Calling client.list_accounts()...")
                accounts_resp = self.client.list_accounts() if hasattr(self.client, 'list_accounts') else self.client.get_accounts()
                accounts = getattr(accounts_resp, 'accounts', [])
                logging.info(f"📁 v3 Advanced Trade API: {len(accounts)} account(s)")

                # ENHANCED DEBUG: Show ALL accounts
                if len(accounts) == 0:
                    logging.error(f"   🚨 API returned ZERO accounts!")
                    logging.error(f"   Response type: {type(accounts_resp)}")
                    logging.error(f"   Response object: {accounts_resp}")
                else:
                    logging.info(f"   📋 Listing all {len(accounts)} accounts:")

                for account in accounts:
                    currency = getattr(account, 'currency', None)
                    available_obj = getattr(account, 'available_balance', None)
                    available = float(getattr(available_obj, 'value', 0) or 0)
                    account_type = getattr(account, 'type', None)
                    account_name = getattr(account, 'name', 'Unknown')
                    account_uuid = getattr(account, 'uuid', 'no-uuid')

                    # DEBUG: Log EVERY account we see
                    logging.info(f"      → {currency}: ${available:.2f} | {account_name} | {account_type} | UUID: {account_uuid[:8]}...")

                    # ONLY count Advanced Trade balances for trading
                    if currency == "USD":
                        usd_balance += available
                        if available > 0:
                            logging.info(f"   ✅ Advanced Trade USD: ${available:.2f} (name={account_name}, type={account_type}) [TRADABLE]")
                    elif currency == "USDC":
                        usdc_balance += available
                        if available > 0:
                            logging.info(f"   ✅ Advanced Trade USDC: ${available:.2f} (name={account_name}, type={account_type}) [TRADABLE]")
                    elif available > 0 and currency:
                        crypto_holdings[currency] = crypto_holdings.get(currency, 0) + available
            except Exception as v3_error:
                logging.error(f"⚠️  v3 API check failed!")
                logging.error(f"   Error type: {type(v3_error).__name__}")
                logging.error(f"   Error message: {v3_error}")
                import traceback
                logging.error(f"   Traceback: {traceback.format_exc()}")

            # CRITICAL FIX: ONLY Advanced Trade balances are tradeable
            # Consumer wallet balances CANNOT be used for trading via API
            # The market_order_buy() function can ONLY access Advanced Trade portfolio
            trading_balance = usdc_balance if usdc_balance > 0 else usd_balance

            # IGNORE ALLOW_CONSUMER_USD flag - it's misleading
            # Consumer wallets are simply NOT accessible for API trading
            if getattr(self, 'allow_consumer_usd', False) and (consumer_usd > 0 or consumer_usdc > 0):
                logging.warning("⚠️  ALLOW_CONSUMER_USD is enabled, but API cannot trade from Consumer wallets!")
                logging.warning("   This flag has no effect. Transfer funds to Advanced Trade instead.")

            logging.info("=" * 70)
            logging.info("💰 BALANCE SUMMARY:")
            logging.info(f"   Consumer USD:  ${consumer_usd:.2f} ❌ [NOT TRADABLE - API LIMITATION]")
            logging.info(f"   Consumer USDC: ${consumer_usdc:.2f} ❌ [NOT TRADABLE - API LIMITATION]")
            logging.info(f"   Advanced Trade USD:  ${usd_balance:.2f} ✅ [TRADABLE]")
            logging.info(f"   Advanced Trade USDC: ${usdc_balance:.2f} ✅ [TRADABLE]")
            logging.info(f"   ▶ TRADING BALANCE: ${trading_balance:.2f}")
            logging.info("")

            # Warn if funds are insufficient (using module-level constants)
            if trading_balance < MINIMUM_BALANCE_PROTECTION:
                funding_needed = MINIMUM_BALANCE_PROTECTION - trading_balance
                logging.error("=" * 70)
                logging.error("🚨 CRITICAL: INSUFFICIENT TRADING BALANCE!")
                logging.error(f"   Current balance: ${trading_balance:.2f}")
                logging.error(f"   MINIMUM_BALANCE (Protection): ${MINIMUM_BALANCE_PROTECTION:.2f}")
                logging.error(f"   💵 Funding Needed: ${funding_needed:.2f}")
                logging.error(f"   Why? Minimum for small trades to cover fees and safety margin")
                logging.error("")
                if (consumer_usd > 0 or consumer_usdc > 0):
                    logging.error("   🔍 ROOT CAUSE: Your funds are in Consumer wallet!")
                    logging.error(f"   Consumer wallet has ${consumer_usd + consumer_usdc:.2f} (NOT TRADABLE)")
                    logging.error(f"   Advanced Trade has ${trading_balance:.2f} (TRADABLE)")
                    logging.error("")
                    logging.error("   🔧 SOLUTION: Transfer to Advanced Trade")
                    logging.error("      1. Go to: https://www.coinbase.com/advanced-portfolio")
                    logging.error("      2. Click 'Deposit' → 'From Coinbase'")
                    logging.error(f"      3. Transfer ${consumer_usd + consumer_usdc:.2f} USD/USDC to Advanced Trade")
                    logging.error("      4. Instant transfer, no fees")
                    logging.error("")
                    logging.error("   ❌ CANNOT FIX WITH CODE:")
                    logging.error("      The Coinbase Advanced Trade API cannot access Consumer wallets")
                    logging.error("      This is a Coinbase API limitation, not a bot issue")
                elif trading_balance == 0:
                    logging.error("   No funds detected in any account")
                    logging.error("   Add funds to your Coinbase account")
                else:
                    logging.error("   Your balance is very low for reliable trading")
                    logging.error("   💡 Note: Funds will become available as open positions are sold")
                    logging.error("   💡 Bot will attempt to trade but with very limited capacity")
                    logging.error(f"   With ${trading_balance:.2f}, position sizing will be extremely small")
                    logging.error("")
                    logging.error("   🎯 RECOMMENDED: Deposit at least $25-$50")
                    logging.error("      - Allows multiple trades")
                    logging.error("      - Better position sizing")
                    logging.error("      - Strategy works more effectively")
                logging.error("=" * 70)
            elif trading_balance < MINIMUM_TRADING_BALANCE:
                funding_recommended = MINIMUM_TRADING_BALANCE - trading_balance
                logging.warning("=" * 70)
                logging.warning("⚠️  WARNING: Trading balance below recommended minimum")
                logging.warning(f"   Current balance: ${trading_balance:.2f}")
                logging.warning(f"   MINIMUM_TRADING_BALANCE (Recommended): ${MINIMUM_TRADING_BALANCE:.2f}")
                logging.warning(f"   💵 Additional Funding Recommended: ${funding_recommended:.2f}")
                logging.warning("")
                logging.warning("   Bot can operate but with limited capacity")
                logging.warning("   💡 Add funds for optimal trading performance")
                logging.warning("   💡 Or wait for positions to close and reinvest profits")
                logging.warning("=" * 70)
            else:
                logging.info(f"   ✅ Sufficient funds in Advanced Trade for trading!")

            logging.info("=" * 70)

            return {
                "usdc": usdc_balance,
                "usd": usd_balance,
                "trading_balance": trading_balance,
                "crypto": crypto_holdings,
                "consumer_usd": consumer_usd,
                "consumer_usdc": consumer_usdc,
            }
        except Exception as e:
            logging.error(f"🔥 ERROR get_account_balance: {e}")
            import traceback
            traceback.print_exc()
            return {
                "usdc": 0.0,
                "usd": 0.0,
                "trading_balance": 0.0,
                "crypto": {},
                "consumer_usd": 0.0,
                "consumer_usdc": 0.0,
            }

    def _dump_portfolio_summary(self):
        """Diagnostic: dump all portfolios and their USD/USDC balances"""
        try:
            # RATE LIMIT FIX: Wrap get_accounts with retry logic to prevent 429 errors
            accounts_resp = self._api_call_with_retry(self.client.get_accounts)
            accounts = getattr(accounts_resp, 'accounts', [])
            usd_total = 0.0
            usdc_total = 0.0
            for a in accounts:
                curr = getattr(a, 'currency', None)
                av = float(getattr(getattr(a, 'available_balance', None), 'value', 0) or 0)
                if curr == "USD":
                    usd_total += av
                elif curr == "USDC":
                    usdc_total += av
            logging.info(f"   Default portfolio | USD: ${usd_total:.2f} | USDC: ${usdc_total:.2f}")
        except Exception as e:
            logging.warning(f"⚠️ Portfolio summary failed: {e}")

    def get_usd_usdc_inventory(self) -> list[str]:
        """Return a formatted USD/USDC inventory for logging by callers.

        This method mirrors the inventory logic used by diagnostics but returns
        strings so the caller can log with its own logger configuration
        (important because some apps only attach handlers to the 'nija' logger).
        """
        lines: list[str] = []
        try:
            # RATE LIMIT FIX: Wrap get_accounts with retry logic to prevent 429 errors
            resp = self._api_call_with_retry(self.client.get_accounts)
            accounts = getattr(resp, 'accounts', []) or (resp.get('accounts', []) if isinstance(resp, dict) else [])
            usd_total = 0.0
            usdc_total = 0.0

            def _as_float(v):
                try:
                    return float(v)
                except Exception:
                    return 0.0

            for a in accounts:
                if isinstance(a, dict):
                    currency = a.get('currency')
                    name = a.get('name')
                    platform = a.get('platform')
                    account_type = a.get('type')
                    av = (a.get('available_balance') or {}).get('value')
                    hd = (a.get('hold') or {}).get('value')
                else:
                    currency = getattr(a, 'currency', None)
                    name = getattr(a, 'name', None)
                    platform = getattr(a, 'platform', None)
                    account_type = getattr(a, 'type', None)
                    av = getattr(getattr(a, 'available_balance', None), 'value', None)
                    hd = getattr(getattr(a, 'hold', None), 'value', None)

                is_tradeable = account_type == "ACCOUNT_TYPE_CRYPTO" or (platform and "ADVANCED_TRADE" in str(platform))

                if currency in ("USD", "USDC"):
                    avf = _as_float(av)
                    hdf = _as_float(hd)
                    tag = "TRADEABLE" if is_tradeable else "CONSUMER"
                    lines.append(f"{currency:>4} | name={name} | platform={platform} | type={account_type} | avail={avf:>10.2f} | held={hdf:>10.2f} | {tag}")
                    if is_tradeable:
                        if currency == "USD":
                            usd_total += avf
                        else:
                            usdc_total += avf

            lines.append("-" * 70)
            trading = usd_total + usdc_total
            lines.append(f"Totals → USD: ${usd_total:.2f} | USDC: ${usdc_total:.2f} | Trading Balance: ${trading:.2f}")
            if usd_total == 0.0 and usdc_total == 0.0:
                lines.append("👉 Move funds into your Advanced Trade portfolio: https://www.coinbase.com/advanced-portfolio")
        except Exception as e:
            lines.append(f"⚠️ Failed to fetch USD/USDC inventory: {e}")

        return lines

    def _log_insufficient_fund_context(self, base_currency: str, quote_currency: str) -> None:
        """Log available balances for base/quote/USD/USDC across portfolios for diagnostics."""
        try:
            # RATE LIMIT FIX: Wrap get_accounts with retry logic to prevent 429 errors
            resp = self._api_call_with_retry(self.client.get_accounts)
            accounts = getattr(resp, 'accounts', []) or (resp.get('accounts', []) if isinstance(resp, dict) else [])

            def _as_float(val):
                try:
                    return float(val)
                except Exception:
                    return 0.0

            interesting = {base_currency, quote_currency, 'USD', 'USDC'}
            logger.error(f"   Fund snapshot ({', '.join(sorted(interesting))})")
            for a in accounts:
                if isinstance(a, dict):
                    currency = a.get('currency')
                    platform = a.get('platform')
                    account_type = a.get('type')
                    av = (a.get('available_balance') or {}).get('value')
                    hd = (a.get('hold') or {}).get('value')
                else:
                    currency = getattr(a, 'currency', None)
                    platform = getattr(a, 'platform', None)
                    account_type = getattr(a, 'type', None)
                    av = getattr(getattr(a, 'available_balance', None), 'value', None)
                    hd = getattr(getattr(a, 'hold', None), 'value', None)

                if currency not in interesting:
                    continue

                avf = _as_float(av)
                hdf = _as_float(hd)
                tag = "TRADEABLE" if account_type == "ACCOUNT_TYPE_CRYPTO" or (platform and "ADVANCED_TRADE" in str(platform)) else "CONSUMER"
                logger.error(f"     {currency:>4} | avail={avf:>14.6f} | held={hdf:>12.6f} | type={account_type} | platform={platform} | {tag}")
        except Exception as diag_err:
            logger.error(f"   ⚠️ fund diagnostic failed: {diag_err}")

    def _get_product_metadata(self, symbol: str) -> Dict:
        """Fetch and cache product metadata (base_increment, quote_increment)."""
        # Ensure cache exists (defensive programming)
        if not hasattr(self, '_product_cache'):
            self._product_cache = {}

        if symbol in self._product_cache:
            return self._product_cache[symbol]

        meta: Dict = {}
        try:
            # RATE LIMIT FIX: Wrap get_product with rate limiter to prevent 429 errors
            def _fetch_product():
                return self.client.get_product(product_id=symbol)

            if self._rate_limiter:
                product = self._rate_limiter.call('get_product', _fetch_product)
            else:
                product = _fetch_product()

            if isinstance(product, dict):
                meta = product
            else:
                # Serialize SDK object to dict
                meta = _serialize_object_to_dict(product)
            # Some SDK responses nest data under a top-level "product" key
            if isinstance(meta, dict) and 'product' in meta and isinstance(meta['product'], dict):
                meta = meta['product']
            # Some responses wrap the single product in a list under "products"
            if isinstance(meta, dict) and 'products' in meta and isinstance(meta['products'], list) and meta['products']:
                first = meta['products'][0]
                if isinstance(first, dict):
                    meta = first
        except Exception as e:
            logger.warning(f"⚠️ Could not fetch product metadata for {symbol}: {e}")

        self._product_cache[symbol] = meta
        return meta

    def _fetch_actual_fill_price(self, order_dict: dict, symbol: str) -> Optional[float]:
        """
        Resolve the actual average fill price for a completed Coinbase order.

        Checks (in priority order):
          1. ``success_response.average_filled_price`` — present in some immediate responses
          2. ``get_order(order_id)``                   — follow-up API call for the real fill data
          3. ``get_current_price(symbol)``             — live market price as last resort

        Returns float or None.
        """
        # 1. Immediate response field
        success_response = order_dict.get('success_response', {}) if isinstance(order_dict, dict) else {}
        price_str = (success_response or {}).get('average_filled_price')
        if price_str:
            try:
                p = float(price_str)
                if p > 0:
                    return p
            except (TypeError, ValueError):
                pass

        # 2. Follow-up get_order() call to fetch actual fill details
        order_id = (
            (success_response or {}).get('order_id')
            or (order_dict.get('order_id') if isinstance(order_dict, dict) else None)
        )
        if order_id and self.client and hasattr(self.client, 'get_order'):
            try:
                resp = self.client.get_order(order_id=order_id)
                resp_dict = _serialize_object_to_dict(resp)
                if isinstance(resp_dict, dict):
                    order_info = resp_dict.get('order', resp_dict)
                    avg_price = order_info.get('average_filled_price')
                    if avg_price:
                        p = float(avg_price)
                        if p > 0:
                            logger.debug(f"[FillVerify] {symbol}: confirmed fill @ ${p:.4g} (get_order)")
                            return p
            except Exception as _e:
                logger.debug(f"[FillVerify] {symbol}: get_order() unavailable: {_e}")

        # 3. Live market price as last resort
        return self.get_current_price(symbol)

    def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        size_type: str = 'quote',
        ignore_balance: bool = False,
        ignore_min_trade: bool = False,
        force_liquidate: bool = False
    ) -> Dict:
        """
        Place market order with balance verification (and optional bypasses for emergencies).

        Args:
            symbol: Trading pair (e.g., 'BTC-USD')
            side: 'buy' or 'sell'
            quantity: Amount to trade
            size_type: 'quote' for USD amount (default) or 'base' for crypto amount
            ignore_balance: Bypass balance validation (EMERGENCY ONLY - FIX 1)
            ignore_min_trade: Bypass minimum trade size validation (EMERGENCY ONLY - FIX 1)
            force_liquidate: Bypass ALL validation (EMERGENCY ONLY - FIX 1)

        Returns:
            Order response dictionary
        """
        # 🍎 CRITICAL LAYER 0: APP STORE MODE CHECK (Absolute Block)
        # This check happens BEFORE all other checks to ensure Apple App Review safety
        # When APP_STORE_MODE=true, NO real orders can be placed
        try:
            from bot.app_store_mode import get_app_store_mode
            app_store_mode = get_app_store_mode()
            if app_store_mode.is_enabled():
                return app_store_mode.block_execution_with_log(
                    operation='place_market_order',
                    symbol=symbol,
                    side=side,
                    size=quantity
                )
        except ImportError:
            # App Store mode module not available - continue with other checks
            pass
        
        try:
            # CRITICAL FIX (Jan 10, 2026): Validate symbol parameter before any API calls
            # Prevents "ProductID is invalid" errors from Coinbase API
            if not symbol:
                logger.error("❌ INVALID SYMBOL: Symbol parameter is None or empty")
                logger.error(f"   Side: {side}, Quantity: {quantity}, Size Type: {size_type}")
                return {
                    "status": "error",
                    "error": "INVALID_SYMBOL",
                    "message": "Symbol parameter is None or empty",
                    "partial_fill": False,
                    "filled_pct": 0.0
                }

            if not isinstance(symbol, str):
                logger.error(f"❌ INVALID SYMBOL: Symbol must be string, got {type(symbol)}")
                logger.error(f"   Symbol value: {symbol}")
                return {
                    "status": "error",
                    "error": "INVALID_SYMBOL",
                    "message": f"Symbol must be string, got {type(symbol)}",
                    "partial_fill": False,
                    "filled_pct": 0.0
                }

            # Validate symbol format (should be like "BTC-USD", "ETH-USD", etc.)
            # 🔒 LAYER 1: BROKER ISOLATION CHECK (Steps 2-6)
            _iso = _check_broker_isolation(self.broker_type, side)
            if _iso is not None:
                return _iso

            if '-' not in symbol or len(symbol) < 5:
                logger.error(f"❌ INVALID SYMBOL: Invalid format '{symbol}'")
                logger.error(f"   Expected format: BASE-QUOTE (e.g., 'BTC-USD')")
                logger.error(f"   Side: {side}, Quantity: {quantity}")
                return {
                    "status": "error",
                    "error": "INVALID_SYMBOL",
                    "message": f"Invalid symbol format '{symbol}' - expected 'BASE-QUOTE'",
                    "partial_fill": False,
                    "filled_pct": 0.0
                }

            # Global BUY guard: block all buys when emergency stop is active or HARD_BUY_OFF=1
            try:
                import os as _os
                lock_path = _os.path.join(_os.path.dirname(__file__), '..', 'TRADING_EMERGENCY_STOP.conf')
                hard_buy_off = (_os.getenv('HARD_BUY_OFF', '0') in ('1', 'true', 'True'))
                if side.lower() == 'buy' and (hard_buy_off or _os.path.exists(lock_path)):
                    logger.error("🛑 BUY BLOCKED at broker layer: SELL-ONLY mode or HARD_BUY_OFF active")
                    logger.error(f"   Symbol: {symbol}")
                    logger.error(f"   Reason: {'HARD_BUY_OFF' if hard_buy_off else 'TRADING_EMERGENCY_STOP.conf present'}")
                    return {
                        "status": "unfilled",
                        "error": "BUY_BLOCKED",
                        "message": "Global buy guard active (sell-only mode)",
                        "partial_fill": False,
                        "filled_pct": 0.0
                    }
            except Exception:
                # If guard check fails, proceed but log later if needed
                pass

            # 🚑 FIX #1: FORCE SELL OVERRIDE - SELL orders bypass ALL restrictions
            # ================================================================
            # CRITICAL: SELL orders are NEVER blocked by:
            #   ✅ MINIMUM_TRADING_BALANCE (balance checks only apply to BUY)
            #   ✅ MIN_CASH_TO_BUY (balance checks only apply to BUY)
            #   ✅ ENTRY_ONLY mode / EXIT_ONLY mode (blocks BUY, not SELL)
            #   ✅ Broker preference routing (SELL always executes)
            #   ✅ Emergency stop flags (only block BUY)
            #
            # This ensures:
            #   - Stop-loss exits always execute
            #   - Emergency liquidation always executes
            #   - Losing positions can always be closed
            #   - Capital bleeding can always be stopped
            # ================================================================

            # Log explicit bypass for SELL orders
            if side.lower() == 'sell':
                logger.info(f"🛡️ PROTECTIVE SELL MODE for {symbol}: EMERGENCY EXIT MODE — SELL ONLY")
                logger.info(f"   ✅ Balance validation: SKIPPED (protective exit)")
                logger.info(f"   ✅ Minimum balance check: SKIPPED (protective exit)")
                logger.info(f"   ✅ EXIT-ONLY mode: ALLOWED (protective exit)")
                logger.info(f"   ✅ Capital preservation: ACTIVE")

            # FIX 2: Reject BUY orders when in EXIT-ONLY mode
            # NOTE: SELL orders are NOT checked here - they always pass through
            if side.lower() == 'buy' and getattr(self, 'exit_only_mode', False) and not force_liquidate:
                logger.error(f"❌ BUY order rejected: Coinbase is in EXIT-ONLY mode (balance < ${COINBASE_MINIMUM_BALANCE:.2f})")
                logger.error(f"   Only SELL orders are allowed to close existing positions")
                logger.error(f"   To enable new entries, fund your account to at least ${COINBASE_MINIMUM_BALANCE:.2f}")
                return {
                    "status": "unfilled",
                    "error": "EXIT_ONLY_MODE",
                    "message": f"BUY orders blocked: Account balance below ${COINBASE_MINIMUM_BALANCE:.2f} minimum",
                    "partial_fill": False,
                    "filled_pct": 0.0
                }

            if quantity <= 0:
                raise ValueError(f"Refusing to place {side} order with non-positive size: {quantity}")

            base_currency, quote_currency = (symbol.split('-') + ['USD'])[:2]

            # 🛡️ PROTECTIVE EXIT OVERRIDE - Skip balance check for protective exits
            # This allows NIJA to exit losing positions for capital preservation
            if force_liquidate or ignore_balance:
                logger.warning(f"🛡️ PROTECTIVE EXIT MODE for {symbol} (force_liquidate={force_liquidate}, ignore_balance={ignore_balance})")

            # PRE-FLIGHT CHECK: Verify sufficient balance before placing order
            # CRITICAL: This check ONLY applies to BUY orders
            # SELL orders ALWAYS bypass this check
            # SKIP if force_liquidate or ignore_balance is True
            if side.lower() == 'buy' and not (force_liquidate or ignore_balance):
                balance_data = self._get_account_balance_detailed()
                trading_balance = float(balance_data.get('trading_balance', 0.0))

                logger.info(f"💰 Pre-flight balance check for {symbol}:")
                logger.info(f"   Available: ${trading_balance:.2f}")
                logger.info(f"   Required:  ${quantity:.2f}")

                # ADD FIX #2: Add 2% safety buffer for fees/rounding (Coinbase typically takes 0.5-1%)
                safety_buffer = quantity * 0.02  # 2% buffer
                required_with_buffer = quantity + safety_buffer

                if trading_balance < required_with_buffer:
                    error_msg = f"Insufficient funds: ${trading_balance:.2f} available, ${required_with_buffer:.2f} required (with 2% fee buffer)"
                    logger.error(f"❌ PRE-FLIGHT CHECK FAILED: {error_msg}")
                    logger.error(f"   Bot detected ${trading_balance:.2f} but needs ${required_with_buffer:.2f} for this order")

                    # Log USD/USDC inventory for debugging
                    logger.error(f"   Account inventory:")
                    inventory_lines = self.get_usd_usdc_inventory()
                    for line in inventory_lines:
                        logger.error(f"     {line}")

                    return {
                        "status": "unfilled",
                        "error": "INSUFFICIENT_FUND",
                        "message": error_msg,
                        "partial_fill": False,
                        "filled_pct": 0.0
                    }

            # ============================================================
            # 🛡️ EXECUTION LAYER HARDENING (Feb 16, 2026) - CRITICAL
            # ============================================================
            # This enforcement runs at the EXECUTION LAYER and CANNOT be bypassed
            # by strategy layer, signal engine, copy trading, or broker adapters.
            #
            # Enforces:
            # 1. User position cap (match platform cap)
            # 2. Minimum per-position allocation (5-10% of account)
            # 3. Block new entries below $X minimum position size
            # 4. Consolidate dust positions
            # 5. Disable trading if average position size < fee threshold
            #
            # CRITICAL: These checks only apply to BUY orders (new positions).
            # SELL orders always bypass to ensure exits can execute.
            # ============================================================
            if EXECUTION_HARDENING_AVAILABLE and side.lower() == 'buy' and not force_liquidate:
                try:
                    # Get current positions for validation
                    current_positions = self.get_positions()
                    
                    # Get account balance
                    account_balance = self.get_account_balance()
                    
                    # Get hardening enforcer
                    hardening = get_execution_layer_hardening(broker_type='coinbase')
                    
                    # Validate order against ALL hardening requirements
                    is_valid, error_reason, validation_details = hardening.validate_order_hardening(
                        symbol=symbol,
                        side=side,
                        position_size_usd=quantity,
                        balance=account_balance,
                        current_positions=current_positions,
                        user_id=getattr(self, 'user_id', None),
                        force_liquidate=force_liquidate
                    )
                    
                    if not is_valid:
                        # Hardening check FAILED - block this order
                        logger.error("=" * 80)
                        logger.error("🛡️ EXECUTION LAYER HARDENING: ORDER BLOCKED")
                        logger.error("=" * 80)
                        logger.error(f"Symbol: {symbol}")
                        logger.error(f"Side: {side}")
                        logger.error(f"Position Size: ${quantity:.2f}")
                        logger.error(f"Balance: ${account_balance:.2f}")
                        logger.error(f"Current Positions: {len(current_positions)}")
                        logger.error(f"Reason: {error_reason}")
                        logger.error("")
                        logger.error("This order was blocked to prevent:")
                        logger.error("  • Excessive position count (exceeding tier limits)")
                        logger.error("  • Position sizes too small to be profitable")
                        logger.error("  • Dust accumulation and fee bleeding")
                        logger.error("  • Average position size below profitability threshold")
                        logger.error("")
                        logger.error("To fix: Close small positions or increase position size")
                        logger.error("=" * 80)
                        
                        return {
                            "status": "unfilled",
                            "error": "HARDENING_ENFORCEMENT",
                            "message": error_reason,
                            "partial_fill": False,
                            "filled_pct": 0.0,
                            "validation_details": validation_details
                        }
                    
                    logger.info(f"✅ EXECUTION LAYER HARDENING: Order validated")
                    logger.info(f"   Checks performed: {len(validation_details.get('checks_performed', []))}")
                    
                except Exception as hardening_error:
                    # If hardening check fails (e.g., module error), LOG but allow order
                    # This prevents hardening bugs from blocking legitimate trades
                    logger.error(f"⚠️ Hardening validation error (allowing order): {hardening_error}")
                    logger.error(f"   This is a bug - hardening should never crash")
                    logger.error(f"   Order will proceed but hardening may not be enforced")

            # ================================================================
            # 🛡️ EXCHANGE ORDER VALIDATOR — step-size + PERMANENT_DUST_UNSELLABLE
            # ================================================================
            # Runs for EVERY order (buy, sell, cleanup, forced exit) BEFORE the
            # API call.  Responsibilities:
            #   1. Reject permanently-unsellable symbols immediately (no retry).
            #   2. Normalise base-size SELL quantities to the exchange step size.
            #   3. Normalise quote-size BUY amounts to 2 decimal places.
            #   4. Mark symbols as PERMANENT_DUST_UNSELLABLE when adjusted value
            #      is still below the exchange floor after normalisation.
            #   5. Emit [ORDER NORMALIZED] log whenever quantity is adjusted.
            # ================================================================
            if EXCHANGE_ORDER_VALIDATOR_AVAILABLE:
                try:
                    _eov = get_exchange_order_validator()

                    # Fast-path: block permanently flagged symbols immediately
                    if _eov.is_permanently_unsellable(symbol):
                        logger.warning(
                            "🚫 PERMANENT_DUST_UNSELLABLE: %s — order blocked, "
                            "excluded from all systems permanently",
                            symbol,
                        )
                        return {
                            "status": "unfilled",
                            "error": "PERMANENT_DUST_UNSELLABLE",
                            "message": (
                                f"{symbol} is permanently marked as unsellable "
                                "(below exchange minimum — will not retry)"
                            ),
                            "partial_fill": False,
                            "filled_pct": 0.0,
                        }

                    # Determine current price for notional checks on base-size orders
                    _eov_price = 0.0
                    if size_type == "base":
                        try:
                            _eov_price = float(self.get_current_price(symbol) or 0)
                        except Exception:
                            _eov_price = 0.0

                    # Full validation + normalisation
                    _norm = _eov.validate_and_normalize(
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                        price=_eov_price,
                        size_type=size_type,
                        broker_ref=self,
                    )

                    if _norm.is_permanently_unsellable:
                        logger.warning(
                            "🚫 PERMANENT_DUST_UNSELLABLE: %s — $%.4f — order blocked permanently",
                            symbol, _norm.value_usd,
                        )
                        return {
                            "status": "unfilled",
                            "error": "PERMANENT_DUST_UNSELLABLE",
                            "message": (
                                f"{symbol} value ${_norm.value_usd:.4f} is permanently "
                                "below exchange minimum — will not retry"
                            ),
                            "partial_fill": False,
                            "filled_pct": 0.0,
                        }

                    if not _norm.is_valid:
                        logger.warning(
                            "⚠️ ORDER BLOCKED by exchange validator: %s — %s",
                            symbol, _norm.reason,
                        )
                        return {
                            "status": "unfilled",
                            "error": "ORDER_TOO_SMALL",
                            "message": _norm.reason,
                            "partial_fill": False,
                            "filled_pct": 0.0,
                        }

                    # Apply normalised quantity for the rest of this method
                    if _norm.adjusted_qty != quantity:
                        quantity = _norm.adjusted_qty

                except Exception as _eov_err:
                    # Validator must never block a legitimate order due to its own bug
                    logger.warning(
                        "⚠️ Exchange order validator error (allowing order): %s", _eov_err
                    )

            client_order_id = str(uuid.uuid4())

            if side.lower() == 'buy':
                # CRITICAL FIX: Round quote_size to 2 decimal places for Coinbase precision requirements
                # Floating point math can create values like 23.016000000000002
                # Coinbase rejects these with PREVIEW_INVALID_QUOTE_SIZE_PRECISION
                quote_size_rounded = round(quantity, 2)

                # Use positional client_order_id to avoid SDK signature mismatch
                logger.info(f"📤 Placing BUY order: {symbol}, quote_size=${quote_size_rounded:.2f}")
                if self.portfolio_uuid:
                    logger.info(f"   Routing to portfolio: {self.portfolio_uuid[:8]}...")
                else:
                    logger.info(f"   This API can ONLY trade from Advanced Trade portfolio, NOT Consumer wallets")

                # ── Fix 5: Maker-preferred orders (Coinbase) ──────────────────
                # When NIJA_PREFER_MAKER_ORDERS=true (default) attempt a
                # post-only limit order at the current ask price so we pay the
                # maker fee (0 % on Coinbase Advanced) instead of the taker fee
                # (0.60 %).  On rejection we fall back to market_order_buy.
                import os as _os
                _cb_prefer_maker = _os.environ.get("NIJA_PREFER_MAKER_ORDERS", "true").lower() not in ("0", "false", "no")
                order = None

                if _cb_prefer_maker:
                    try:
                        _cb_price = self.get_current_price(symbol)
                        if _cb_price and _cb_price > 0:
                            # base_size = quote / price, rounded to 8 dp
                            import math as _math
                            _cb_base = _math.floor((quote_size_rounded / _cb_price) * 1e8) / 1e8
                            logger.info(
                                f"📌 MAKER BUY [{symbol}]: {_cb_base:.8f} @ ${_cb_price:.8f} "
                                f"(post-only limit, Coinbase)"
                            )
                            order = self.client.create_order(
                                client_order_id=client_order_id,
                                product_id=symbol,
                                side="BUY",
                                order_configuration={
                                    'limit_limit_gtc': {
                                        'base_size':  str(_cb_base),
                                        'limit_price': str(round(_cb_price, 8)),
                                        'post_only':  True,
                                    }
                                },
                                **({'portfolio_id': self.portfolio_uuid} if getattr(self, 'portfolio_uuid', None) else {})
                            )
                        else:
                            _cb_prefer_maker = False
                    except Exception as _cb_maker_err:
                        logger.warning(f"⚠️  Coinbase maker BUY failed ({_cb_maker_err}) — retrying as market")
                        order = None
                        _cb_prefer_maker = False

                if not _cb_prefer_maker or order is None:
                    # Market fallback (original path)
                    logger.info(f"   Using Coinbase market_order_buy (taker)")
                    order = self.client.market_order_buy(
                        client_order_id,
                        product_id=symbol,
                        quote_size=str(quote_size_rounded)
                    )
            else:
                # SELL order - use base_size (crypto amount) or quote_size (USD value)
                if size_type == 'base':
                    base_currency = symbol.split('-')[0].upper()

                    precision_map = {
                        'XRP': 2,
                        'DOGE': 2,
                        'ADA': 2,
                        'SHIB': 0,
                        'BTC': 8,
                        'ETH': 6,
                        'SOL': 4,
                        'ATOM': 4,
                        'LTC': 8,
                        'BCH': 8,
                        'LINK': 4,
                        'IMX': 4,
                        'XLM': 4,
                        'CRV': 4,
                        'APT': 4,
                        'ICP': 5,
                        'NEAR': 5,
                        'AAVE': 4,
                    }

                    # CRITICAL FIX: Use ACTUAL Coinbase increment values
                    # Many coins only accept WHOLE numbers (increment=1) despite supporting decimal balances
                    fallback_increment_map = {
                        'BTC': 0.00000001,  # 8 decimals
                        'ETH': 0.000001,    # 6 decimals
                        'ADA': 1,           # WHOLE NUMBERS ONLY
                        'SOL': 0.001,       # 3 decimals
                        'XRP': 1,           # WHOLE NUMBERS ONLY
                        'DOGE': 1,          # WHOLE NUMBERS ONLY
                        'AVAX': 0.001,      # 3 decimals
                        'DOT': 0.1,         # 1 decimal
                        'LINK': 0.01,       # 2 decimals
                        'LTC': 0.00000001,  # 8 decimals
                        'UNI': 0.01,        # 2 decimals
                        'XLM': 1,           # WHOLE NUMBERS ONLY
                        'HBAR': 1,          # WHOLE NUMBERS ONLY
                        'APT': 0.01,        # 2 decimals
                        'ICP': 0.01,        # 2 decimals
                        'RENDER': 0.1,      # 1 decimal
                        'ZRX': 1,           # WHOLE NUMBERS ONLY
                        'CRV': 1,           # WHOLE NUMBERS ONLY
                        'FET': 1,           # WHOLE NUMBERS ONLY
                        'AAVE': 0.001,      # 3 decimals
                        'VET': 1,           # WHOLE NUMBERS ONLY
                        'SHIB': 1,          # WHOLE NUMBERS ONLY
                        'BCH': 0.00000001,  # 8 decimals
                        'ATOM': 0.0001,     # 4 decimals
                        'IMX': 0.0001,      # 4 decimals
                        'NEAR': 0.00001,    # 5 decimals
                    }

                    precision = max(0, min(precision_map.get(base_currency, 2), 8))
                    base_increment = None

                    # Emergency mode: skip preflight balance calls to reduce API 429s
                    emergency_file = os.path.join(os.path.dirname(__file__), '..', 'LIQUIDATE_ALL_NOW.conf')
                    skip_preflight = side.lower() == 'sell' and os.path.exists(emergency_file)

                    if not skip_preflight:
                        try:
                            balance_snapshot = self._get_account_balance_detailed()
                            holdings = (balance_snapshot or {}).get('crypto', {}) or {}
                            available_base = float(holdings.get(base_currency, 0.0))

                            # NOTE: available_base now includes BOTH available AND held crypto
                            # (fixed in _get_account_balance_detailed to prevent INSUFFICIENT_FUND errors)
                            # No need to adjust for holds separately - they're already included

                            logger.info(f"   Real-time balance check: {available_base:.8f} {base_currency} total (available+held)")
                            logger.info(f"   Tracked position size: {quantity:.8f} {base_currency}")

                            # FIX 2: SELL MUST IGNORE CASH BALANCE
                            # CRITICAL: We're selling CRYPTO, not buying with USD
                            # The check should be: "Do we have the crypto?" NOT "Do we have USD?"
                            # Old (WRONG): if available_base <= epsilon: block_sell()
                            # New (CORRECT): if position.quantity > 0: execute_sell()
                            #
                            # This single change stops the bleeding:
                            # - We can now exit losing positions even with $0 USD balance
                            # - Sells are NOT blocked by insufficient USD (which makes no sense!)
                            # - Position management works correctly

                            epsilon = 1e-8

                            # Validate quantity is positive before proceeding
                            if quantity <= epsilon:
                                logger.error(
                                    f"❌ INVALID SELL: Zero or negative quantity "
                                    f"(quantity: {quantity:.8f})"
                                )
                                return {
                                    "status": "unfilled",
                                    "error": "INVALID_QUANTITY",
                                    "message": f"Cannot sell zero or negative quantity: {quantity}",
                                    "partial_fill": False,
                                    "filled_pct": 0.0
                                }

                            if available_base <= epsilon:
                                # FIX 2: Changed from ERROR to WARNING
                                # We should still TRY to sell even if balance shows zero
                                # (position might exist on exchange but not in our cache)
                                logger.warning(
                                    f"⚠️ PRE-FLIGHT WARNING: Zero {base_currency} balance shown "
                                    f"(available: {available_base:.8f})"
                                )
                                logger.warning(
                                    f"   Attempting sell anyway - position may exist on exchange"
                                )
                                # DON'T RETURN - continue with sell attempt
                                # The exchange will reject if there's truly no balance

                                # CRITICAL FIX (Jan 24, 2026): Preemptively clear likely phantom positions
                                # When balance is zero and we're being asked to sell, this is likely
                                # a phantom position (already sold/transferred but still tracked)
                                # We'll continue with the sell attempt (in case position exists on exchange)
                                # but if it fails later, the position will already be marked for cleanup
                                if quantity > epsilon and self.position_tracker:
                                    logger.warning(
                                        f"   ⚠️ LIKELY PHANTOM: Tracked {quantity:.8f} {base_currency} but balance is zero"
                                    )
                                    logger.warning(
                                        f"   If sell fails, position will be auto-cleared from tracker"
                                    )

                            if available_base < quantity:
                                diff = quantity - available_base
                                logger.warning(
                                    f"⚠️ Balance mismatch: tracked {quantity:.8f} but only {available_base:.8f} total (available+held)"
                                )
                                logger.warning(f"   Difference: {diff:.8f} {base_currency} (likely from partial fills or fees)")
                                logger.warning(f"   SOLUTION: Adjusting sell size to actual total balance")
                                quantity = available_base
                        except Exception as bal_err:
                            logger.warning(f"⚠️ Could not pre-check balance for {base_currency}: {bal_err}")
                    else:
                        logger.info("   EMERGENCY MODE: Skipping pre-flight balance checks")

                    meta = self._get_product_metadata(symbol)
                    inc_candidates = []
                    if isinstance(meta, dict):
                        inc_candidates = [
                            meta.get('base_increment'),
                            meta.get('base_increment_decimal'),
                            meta.get('base_increment_value'),
                            # base_min_size is a minimum size, not an increment; exclude from precision detection
                        ]
                        if meta.get('base_increment_exponent') is not None:
                            try:
                                exp_raw = meta.get('base_increment_exponent')
                                exp_val = float(exp_raw)  # type: ignore[arg-type]
                                inc_candidates.append(10 ** exp_val)
                            except Exception as exp_err:
                                logger.warning(f"⚠️ Could not parse base_increment_exponent for {symbol}: {exp_err}")
                    for inc in inc_candidates:
                        if not inc:
                            continue
                        try:
                            base_increment = float(inc)
                            if base_increment > 0:
                                break
                        except Exception as inc_err:
                            logger.warning(f"⚠️ Could not parse base_increment for {symbol}: {inc_err}")

                    # If API metadata did not provide an increment, use a conservative fallback per asset
                    if base_increment is None and base_currency in fallback_increment_map:
                        base_increment = fallback_increment_map[base_currency]

                    # Final safety: ensure we have an increment
                    if base_increment is None:
                        base_increment = 0.01  # Default to 2 decimal places

                    # Calculate precision from increment CORRECTLY
                    import math
                    if base_increment >= 1:
                        precision = 0  # Whole numbers only
                    else:
                        # Count decimal places: 0.001 → 3, 0.0001 → 4, etc.
                        precision = int(abs(math.floor(math.log10(base_increment))))

                    # Adjust requested quantity against available balance with a safety margin
                    # FIX #3: Use a larger safety margin to account for fees and rounding
                    # Coinbase typically charges 0.5-1% in trading fees, plus potential precision rounding
                    requested_qty = float(quantity)  # Already adjusted to available if needed

                    # CRITICAL FIX: For small positions (< $10 value), use minimal safety margin
                    # The 0.5% margin was causing tiny positions to round to 0 after subtraction
                    try:
                        current_price = self.get_current_price(symbol)
                        position_usd_value = requested_qty * current_price
                    except Exception as price_err:
                        # If we can't get price, assume it's a larger position (safer - uses percentage margin)
                        logger.warning(f"⚠️ Could not get price for {symbol}: {price_err}")
                        position_usd_value = 100  # Default to large position logic

                    if position_usd_value < 10.0:
                        # For small positions, use tiny epsilon only (not percentage)
                        # These positions are too small for fees to matter much
                        safety_margin = 1e-8  # Minimal epsilon
                        logger.info(f"   Small position (${position_usd_value:.2f}) - using minimal safety margin")
                    else:
                        # For larger positions, use 0.5% margin
                        safety_margin = max(requested_qty * 0.005, 1e-8)

                    # Subtract safety margin to leave room for fees and rounding
                    trade_qty = max(0.0, requested_qty - safety_margin)

                    logger.info(f"   Safety margin: {safety_margin:.8f} {base_currency}")
                    logger.info(f"   Final trade qty: {trade_qty:.8f} {base_currency}")

                    # Quantize size DOWN to allowed increment using floor division
                    # This is more reliable than Decimal arithmetic
                    import math

                    # Calculate how many increments fit into trade_qty (floor division)
                    num_increments = math.floor(trade_qty / base_increment)
                    base_size_rounded = num_increments * base_increment

                    # Round to the correct decimal places to avoid floating point artifacts
                    base_size_rounded = round(base_size_rounded, precision)

                    # CRITICAL FIX: If rounding resulted in 0 or too small, try selling FULL available balance
                    # This happens with very small positions where safety margin + rounding = 0
                    if base_size_rounded <= 0 or base_size_rounded < base_increment:
                        logger.warning(f"   ⚠️ Rounded size too small ({base_size_rounded}), attempting to sell FULL balance")
                        # Try using the full requested quantity without safety margin
                        num_increments = math.floor(requested_qty / base_increment)
                        base_size_rounded = num_increments * base_increment
                        base_size_rounded = round(base_size_rounded, precision)
                        logger.info(f"   Retry with full balance: {base_size_rounded} {base_currency}")

                    logger.info(f"   Derived base_increment={base_increment} precision={precision} → rounded={base_size_rounded}")

                    # FINAL CHECK: If still too small, mark as dust and skip
                    # This is expected behavior for very small positions, not an error
                    if base_size_rounded <= 0 or base_size_rounded < base_increment:
                        logger.warning(f"   💡 Position too small to sell - marking as dust")
                        logger.info(f"   Symbol: {symbol}, Base: {base_currency}")
                        logger.info(f"   Available: {available_base:.8f}" if not skip_preflight else f"   Available: (preflight skipped)")
                        logger.info(f"   Requested: {requested_qty}")
                        logger.info(f"   Increment: {base_increment}, Precision: {precision}")
                        logger.info(f"   Rounded: {base_size_rounded}")
                        logger.info(f"   💡 This dust position will be retried in 24h in case it grows")

                        # CRITICAL FIX (Jan 24, 2026): Clear phantom positions from tracker
                        # If available balance is essentially zero (< 1e-8) but position is tracked,
                        # this is a phantom position that needs to be cleared from tracker
                        if not skip_preflight and available_base <= 1e-8 and self.position_tracker and self.position_tracker.get_position(symbol):
                            logger.warning(f"   🧹 PHANTOM POSITION DETECTED: Zero balance but position tracked")
                            logger.warning(f"   Clearing {symbol} from position tracker (likely already sold/transferred)")
                            try:
                                self.position_tracker.track_exit(symbol, exit_quantity=None)
                                logger.info(f"   ✅ Phantom position cleared from tracker")
                            except Exception as clear_err:
                                logger.error(f"   ❌ Failed to clear phantom position: {clear_err}")

                        return {
                            "status": "skipped_dust",
                            "error": "INVALID_SIZE",
                            "message": f"Position too small (dust): {symbol} rounded to {base_size_rounded} (min: {base_increment}). Will retry later.",
                            "partial_fill": False,
                            "filled_pct": 0.0
                        }

                    logger.info(f"📤 Placing SELL order: {symbol}, base_size={base_size_rounded} ({precision} decimals)")
                    if self.portfolio_uuid:
                        logger.info(f"   Routing to portfolio: {self.portfolio_uuid[:8]}...")

                    # Prefer create_order; fallback to market_order_sell, with 429 backoff
                    def _with_backoff(fn, *args, **kwargs):
                        import time
                        delays = [1, 2, 4]
                        for i, d in enumerate(delays):
                            try:
                                return fn(*args, **kwargs)
                            except Exception as err:
                                msg = str(err)
                                if 'Too Many Requests' in msg or '429' in msg:
                                    logger.warning(f"⚠️ Rate limited, retrying in {d}s (attempt {i+1}/{len(delays)})")
                                    time.sleep(d)
                                    continue
                                raise
                        return fn(*args, **kwargs)

                    try:
                        order = _with_backoff(
                            self.client.create_order,
                            client_order_id=client_order_id,
                            product_id=symbol,
                            order_configuration={
                                'market_market_ioc': {
                                    'base_size': str(base_size_rounded),
                                    'reduce_only': True
                                }
                            },
                            **({'portfolio_id': self.portfolio_uuid} if getattr(self, 'portfolio_uuid', None) else {})
                        )
                    except Exception as co_err:
                        logger.warning(f"⚠️ create_order failed, falling back to market_order_sell: {co_err}")
                        order = _with_backoff(
                            self.client.market_order_sell,
                            client_order_id,
                            product_id=symbol,
                            base_size=str(base_size_rounded)
                        )
                else:
                    # Use quote_size for SELL (less common, but supported)
                    quote_size_rounded = round(quantity, 2)
                    logger.info(f"📤 Placing SELL order: {symbol}, quote_size=${quote_size_rounded:.2f}")
                    if self.portfolio_uuid:
                        logger.info(f"   Routing to portfolio: {self.portfolio_uuid[:8]}...")

                    order = _with_backoff(
                        self.client.market_order_sell,
                        client_order_id,
                        product_id=symbol,
                        quote_size=str(quote_size_rounded)
                    )

            # CRITICAL: Parse order response to check for success/failure
            # Coinbase returns an object with 'success' field and 'error_response'
            # Use helper to safely serialize the response
            order_dict = _serialize_object_to_dict(order)

            # If SDK returns a stringified dict, coerce it to a dict to avoid false positives
            if isinstance(order_dict, str):
                try:
                    order_dict = json.loads(order_dict)
                except Exception:
                    try:
                        import ast
                        order_dict = ast.literal_eval(order_dict)
                    except Exception:
                        pass

            # Guard against SDK returning plain strings or unexpected types
            if not isinstance(order_dict, dict):
                logger.error("Received non-dict order response from Coinbase SDK")
                logger.error(f"   Raw response: {order_dict}")
                logger.error(f"   Response type: {type(order_dict)}")
                return {
                    "status": "error",
                    "error": "INVALID_ORDER_RESPONSE",
                    "message": "Coinbase SDK returned non-dict response",
                    "raw_response": str(order_dict)
                }

            # Check for Coinbase error response
            success = order_dict.get('success', True)
            error_response = order_dict.get('error_response', {})

            if not success or error_response:
                error_code = error_response.get('error', 'UNKNOWN_ERROR')
                error_message = error_response.get('message', 'Unknown error from broker')

                logger.error(f"❌ Trade failed for {symbol}:")
                logger.error(f"   Status: unfilled")
                logger.error(f"   Error: {error_message}")
                logger.error(f"   Full order response: {order_dict}")

                if error_code == 'INSUFFICIENT_FUND':
                    self._log_insufficient_fund_context(base_currency, quote_currency)
                elif error_code == 'INVALID_SIZE_PRECISION' and size_type == 'base':
                    # One-shot degradation retry: use stricter per-asset increment if available
                    logger.error(
                        f"   Hint: base_increment={base_increment} precision={precision} quantity={quantity} rounded={base_size_rounded}"
                    )
                    stricter_map = {
                        'APT': 0.001,
                        'NEAR': 0.0001,
                        'ICP': 0.0001,
                        'AAVE': 0.01,
                    }
                    base_currency = symbol.split('-')[0].upper()
                    alt_inc = stricter_map.get(base_currency)
                    if alt_inc and (base_increment is None or alt_inc != base_increment):
                        try:
                            from decimal import Decimal, ROUND_DOWN, getcontext
                            getcontext().prec = 18
                            step2 = Decimal(str(alt_inc))

                            # Recompute safe trade qty based on same available snapshot
                            safety_epsilon2 = max(alt_inc, 1e-6)
                            safe_available2 = max(0.0, (available_base if 'available_base' in locals() else 0.0) - safety_epsilon2)
                            trade_qty2 = min(float(quantity), safe_available2)

                            qty2 = (Decimal(str(trade_qty2)) / step2).to_integral_value(rounding=ROUND_DOWN) * step2
                            base_size_rounded2 = float(qty2)
                            inc_str2 = f"{alt_inc:.16f}".rstrip('0').rstrip('.')
                            precision2 = len(inc_str2.split('.')[1]) if '.' in inc_str2 else 0
                            logger.info(f"   Retry with alt increment {alt_inc} (precision {precision2}) → {base_size_rounded2}")

                            order2 = self.client.market_order_sell(
                                client_order_id,
                                product_id=symbol,
                                base_size=str(base_size_rounded2)
                            )
                            order_dict2 = _serialize_object_to_dict(order2)
                            if isinstance(order_dict2, str):
                                try:
                                    order_dict2 = json.loads(order_dict2)
                                except Exception:
                                    try:
                                        import ast
                                        order_dict2 = ast.literal_eval(order_dict2)
                                    except Exception:
                                        pass

                            success2 = isinstance(order_dict2, dict) and order_dict2.get('success', True) and not order_dict2.get('error_response')
                            if success2:
                                logger.info(f"✅ Order filled successfully (retry): {symbol}")
                                return {
                                    "status": "filled",
                                    "order": order_dict2,
                                    "filled_size": base_size_rounded2
                                }
                            else:
                                logger.error(f"   Retry failed: {order_dict2}")
                        except Exception as retry_err:
                            logger.error(f"   Retry with stricter increment failed: {retry_err}")

                # Generic fallback: decrement by one increment and retry a few times
                if size_type == 'base' and base_increment and error_code in ('INVALID_SIZE_PRECISION', 'INSUFFICIENT_FUND', 'PREVIEW_INVALID_SIZE_PRECISION', 'PREVIEW_INSUFFICIENT_FUND'):
                    try:
                        from decimal import Decimal, ROUND_DOWN, getcontext
                        getcontext().prec = 18
                        step = Decimal(str(base_increment))

                        max_attempts = 5
                        current_qty = Decimal(str(base_size_rounded if 'base_size_rounded' in locals() else quantity))
                        for attempt in range(1, max_attempts + 1):
                            # Reduce by one increment per attempt and quantize down
                            reduced = current_qty - step * attempt
                            if reduced <= Decimal('0'):
                                break
                            qtry = (reduced / step).to_integral_value(rounding=ROUND_DOWN) * step
                            new_size = float(qtry)
                            logger.info(f"   Fallback attempt {attempt}/{max_attempts}: base_size → {new_size} (decrement by {attempt}×{base_increment})")

                            order_try = self.client.market_order_sell(
                                client_order_id,
                                product_id=symbol,
                                base_size=str(new_size)
                            )
                            od_try = _serialize_object_to_dict(order_try)
                            if isinstance(od_try, str):
                                try:
                                    od_try = json.loads(od_try)
                                except Exception:
                                    try:
                                        import ast
                                        od_try = ast.literal_eval(od_try)
                                    except Exception:
                                        pass

                            if isinstance(od_try, dict) and od_try.get('success', True) and not od_try.get('error_response'):
                                logger.info(f"✅ Order filled successfully (fallback attempt {attempt}): {symbol}")
                                return {
                                    "status": "filled",
                                    "order": od_try,
                                    "filled_size": new_size
                                }
                            else:
                                emsg = od_try.get('error_response', {}).get('message') if isinstance(od_try, dict) else str(od_try)
                                logger.error(f"   Fallback attempt {attempt} failed: {emsg}")
                    except Exception as fb_err:
                        logger.error(f"   Fallback decrement retry failed: {fb_err}")

                return {
                    "status": "unfilled",
                    "error": error_code,
                    "message": error_message,
                    "order": order_dict,
                    "partial_fill": order_dict.get('partial_fill', False),
                    "filled_pct": order_dict.get('filled_pct', 0.0)
                }

            logger.info(f"✅ Order filled successfully: {symbol}")

            # P0 GUARD: Execution broker decides reality - verify order success before ANY position creation
            # This is the CRITICAL guard that prevents "fake positions" when broker orders actually fail
            if not success:
                logger.error("=" * 70)
                logger.error("🔴 P0 GUARD: Order failed — aborting position creation")
                logger.error("=" * 70)
                logger.error(f"   Symbol: {symbol}")
                logger.error(f"   Side: {side.upper()}")
                logger.error(f"   Reason: Execution broker reported order failure")
                logger.error(f"   Enforcement: No ledger write. No position. No copy trading.")
                logger.error("=" * 70)
                return {
                    "status": "unfilled",
                    "error": "ORDER_FAILED",
                    "message": "Broker reported order failure",
                    "order": order_dict
                }

            # Account label used in confirmation logs
            account_label = f"{self.account_identifier}" if hasattr(self, 'account_identifier') else "PLATFORM"

            # FIRST LIVE TRADE BANNER (for legal/operational protection)
            global _FIRST_TRADE_EXECUTED
            with _FIRST_TRADE_LOCK:
                if not _FIRST_TRADE_EXECUTED:
                    _FIRST_TRADE_EXECUTED = True
                    logger.info(LOG_SEPARATOR)
                    logger.info("🚨 FIRST LIVE TRADE EXECUTED 🚨")
                    logger.info(LOG_SEPARATOR)
                    logger.info(f"   {side.upper()} {symbol}  account={account_label}  exchange=Coinbase  "
                                f"ts={time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
                    logger.info(LOG_SEPARATOR)

            # Extract or estimate filled size
            # Coinbase API v3 doesn't return filled_size in the response,
            # so we estimate based on what we sent
            filled_size = None

            # Try to extract from success_response
            success_response = order_dict.get('success_response', {})
            if success_response:
                filled_size = success_response.get('filled_size')

            # If not available, estimate based on order configuration
            if not filled_size:
                order_config = order_dict.get('order_configuration', {})
                market_config = order_config.get('market_market_ioc', {})

                if side.upper() == 'BUY' and 'quote_size' in market_config:
                    # For buy orders, estimate crypto received = quote_size / price
                    try:
                        quote_size = float(market_config['quote_size'])
                        # RATE LIMIT FIX: Wrap get_product with rate limiter to prevent 429 errors
                        def _fetch_price_data():
                            return self.client.get_product(symbol)

                        if self._rate_limiter:
                            price_data = self._rate_limiter.call('get_product', _fetch_price_data)
                        else:
                            price_data = _fetch_price_data()

                        if price_data and 'price' in price_data:
                            current_price = float(price_data['price'])
                            filled_size = quote_size / current_price
                    except Exception:
                        # Fallback: use quantity as estimate
                        filled_size = quantity
                else:
                    # For sell orders or unknown, use quantity as estimate
                    filled_size = quantity

            logger.debug(f"   Filled crypto amount: {filled_size:.6f}" if filled_size else "   Filled amount: unknown")

            # Resolve actual fill price: immediate response → get_order() → current price
            fill_price = self._fetch_actual_fill_price(order_dict, symbol)

            # ── ENTRY CONFIRMED (BUY only — single-line end-to-end verification) ────
            if side.lower() == 'buy':
                size_usd = quantity if size_type == 'quote' else (
                    (filled_size * fill_price) if (filled_size and fill_price) else 0)
                logger.info(
                    f"▶ ENTRY CONFIRMED [{symbol}]: "
                    f"filled @ ${fill_price:.4g} | "
                    f"qty: {filled_size:.6g} | "
                    f"size: ${size_usd:.2f} | "
                    f"acct: {account_label}"
                )

            # Flush logs immediately to ensure confirmation is visible
            if _root_logger.handlers:
                for handler in _root_logger.handlers:
                    handler.flush()

            # CRITICAL: Track position for profit-based exits (ONLY after P0 guard passes)
            if self.position_tracker:
                try:
                    if side.lower() == 'buy':
                        # Track entry for profit calculation
                        if fill_price and fill_price > 0:
                            size_usd = quantity if size_type == 'quote' else (filled_size * fill_price if filled_size else 0)
                            self.position_tracker.track_entry(
                                symbol=symbol,
                                entry_price=fill_price,
                                quantity=filled_size if filled_size else 0,
                                size_usd=size_usd,
                                strategy="APEX_v7.1"
                            )
                            logger.debug(f"   Position tracked: entry=${fill_price:.4g}, size=${size_usd:.2f}")

                            # Log BUY trade to journal
                            self._log_trade_to_journal(
                                symbol=symbol,
                                side='BUY',
                                price=fill_price,
                                size_usd=size_usd,
                                quantity=filled_size if filled_size else 0
                            )
                    else:
                        # Calculate P&L for this exit
                        pnl_data = None
                        if fill_price and fill_price > 0:
                            pnl_data = self.position_tracker.calculate_pnl(symbol, fill_price)

                        # ── EXIT CONFIRMED (single-line, includes P&L when available) ──
                        if pnl_data:
                            logger.info(
                                f"◀ EXIT CONFIRMED [{symbol}]: "
                                f"fill @ ${fill_price:.4g} | "
                                f"qty: {filled_size:.6g} | "
                                f"P&L: ${pnl_data['pnl_dollars']:+.2f} "
                                f"({pnl_data['pnl_percent']:+.2f}%)"
                            )
                        else:
                            logger.info(
                                f"◀ EXIT CONFIRMED [{symbol}]: "
                                f"fill @ ${fill_price:.4g} | "
                                f"qty: {filled_size:.6g} | "
                                f"acct: {account_label}"
                            )

                        # Track exit (partial or full sell)
                        self.position_tracker.track_exit(
                            symbol=symbol,
                            exit_quantity=filled_size if filled_size else None
                        )
                        logger.debug(f"   Position exit recorded")

                        # Log SELL trade to journal with P&L
                        self._log_trade_to_journal(
                            symbol=symbol,
                            side='SELL',
                            price=fill_price if fill_price else 0,
                            size_usd=quantity if size_type == 'quote' else (filled_size * fill_price if filled_size and fill_price else 0),
                            quantity=filled_size if filled_size else 0,
                            pnl_data=pnl_data
                        )
                except Exception as track_err:
                    logger.warning(f"   ⚠️ Position tracking failed: {track_err}")

            # COPY TRADING: Emit trade signal for platform account trades
            # This allows user accounts to replicate platform trades automatically
            try:
                # Only emit signals for PLATFORM accounts (not USER accounts)
                if self.account_type == AccountType.PLATFORM:
                    from trade_signal_emitter import emit_trade_signal

                    # Get current balance for position sizing
                    balance_data = self._get_account_balance_detailed()
                    platform_balance = balance_data.get('trading_balance', 0.0) if balance_data else 0.0

                    # CRITICAL: Log if platform balance fetch failed
                    if not balance_data or platform_balance <= 0:
                        logger.warning("⚠️  Platform balance could not be retrieved for copy trading")
                        logger.warning(f"   Balance data: {balance_data}")
                        logger.warning("   Position sizing for users may fail without valid platform balance")

                    # Get execution price
                    exec_price = fill_price if (fill_price and fill_price > 0) else self.get_current_price(symbol)

                    # Determine broker name
                    broker_name = self.broker_type.value.lower() if hasattr(self, 'broker_type') else 'coinbase'

                    logger.debug(
                        f"📡 Emitting copy signal: {side.upper()} {symbol} @ "
                        f"${exec_price:.4g} size={quantity} ({size_type})"
                    )

                    # Emit signal
                    # CRITICAL FIX (Jan 23, 2026): Add order_status parameter
                    # Use actual order status from order_dict if available, otherwise assume FILLED
                    # This is accurate because this code runs after fill confirmation
                    actual_status = order_dict.get('status', 'FILLED').upper() if order_dict else 'FILLED'
                    # Map partial fills to PARTIALLY_FILLED for consistency
                    if actual_status in ['PARTIAL_FILL', 'PARTIAL', 'PARTIALLY_FILLED']:
                        signal_status = 'PARTIALLY_FILLED'
                    else:
                        signal_status = actual_status

                    signal_emitted = emit_trade_signal(
                        broker=broker_name,
                        symbol=symbol,
                        side=side,
                        price=exec_price if exec_price else 0.0,
                        size=quantity,
                        size_type=size_type,
                        order_id=order_dict.get('order_id', client_order_id),
                        platform_balance=platform_balance,
                        order_status=signal_status  # Use actual order status
                    )

                    if signal_emitted:
                        logger.info(f"✅ Copy signal emitted: {side.upper()} {symbol}")
                    else:
                        logger.error("❌ CRITICAL: TRADE SIGNAL EMISSION FAILED")
                        logger.error(f"   Symbol: {symbol}, Side: {side} — user accounts will NOT copy this trade!")
                        logger.error("   🔧 Check trade_signal_emitter.py logs for error details")
            except Exception as signal_err:
                # Don't fail the trade if signal emission fails
                logger.warning(f"   ⚠️ Trade signal emission failed: {signal_err}")
                logger.warning(f"   ⚠️ User accounts will NOT copy this trade!")
                logger.warning(f"   Traceback: {traceback.format_exc()}")

            return {
                "status": "filled",
                "order": order_dict,
                "filled_size": float(filled_size) if filled_size else 0.0
            }

        except Exception as e:
            # Enhanced error logging with full details
            error_msg = str(e)
            error_type = type(e).__name__
            logger.error(f"🚨 Coinbase order error for {symbol}:")
            logger.error(f"   Type: {error_type}")
            logger.error(f"   Message: {error_msg}")
            logger.error(f"   Side: {side}, Quantity: {quantity}")

            # Log additional context if available
            if hasattr(e, 'response'):
                logger.error(f"   Response: {e.response}")
            if hasattr(e, 'status_code'):
                logger.error(f"   Status code: {e.status_code}")

            return {"status": "error", "error": f"{error_type}: {error_msg}"}

    def force_liquidate(
        self,
        symbol: str,
        quantity: float,
        reason: str = "Emergency liquidation"
    ) -> Dict:
        """
        🚑 EMERGENCY SELL OVERRIDE - Force liquidate position bypassing ALL checks.

        This is the FIX 1 implementation that allows NIJA to exit losing positions
        immediately without being blocked by balance validation or minimum trade limits.

        CRITICAL: This method MUST be used for emergency exits and losing trades.
        It bypasses:
        - Balance checks (ignore_balance=True)
        - Minimum trade size validation (ignore_min_trade=True)
        - All other validation that could prevent exit

        Args:
            symbol: Trading symbol (e.g., 'BTC-USD')
            quantity: Quantity to sell (in base currency)
            reason: Reason for forced liquidation (for logging)

        Returns:
            Order result dict with status
        """
        logger.warning("=" * 70)
        logger.warning(f"🛡️ PROTECTIVE LIQUIDATION: {symbol}")
        logger.warning(f"   Reason: {reason}")
        logger.warning(f"   Quantity: {quantity}")
        logger.warning(f"   Mode: EMERGENCY EXIT MODE — SELL ONLY")
        logger.warning("=" * 70)

        try:
            # Force market sell with ALL checks bypassed
            # This uses place_market_order but with special flags
            result = self.place_market_order(
                symbol=symbol,
                side='sell',
                quantity=quantity,
                size_type='base',
                ignore_balance=True,      # ← REQUIRED: Bypass balance validation
                ignore_min_trade=True,    # ← REQUIRED: Bypass minimum trade size
                force_liquidate=True      # ← REQUIRED: Bypass all other checks
            )

            if result.get('status') == 'filled':
                logger.warning(f"✅ FORCE LIQUIDATE SUCCESSFUL: {symbol}")
            else:
                logger.error(f"❌ FORCE LIQUIDATE FAILED: {symbol} - {result.get('error', 'Unknown error')}")

            return result

        except Exception as e:
            logger.error(f"❌ FORCE LIQUIDATE EXCEPTION: {symbol} - {e}")
            logger.error(traceback.format_exc())
            return {
                "status": "error",
                "error": str(e),
                "symbol": symbol
            }

    def close_position(
        self,
        symbol: str,
        base_size: Optional[float] = None,
        *,
        side: str = 'sell',
        quantity: Optional[float] = None,
        size_type: str = 'base',
        **_: Dict
    ) -> Dict:
        """Close a position by submitting a market order.

        Accepts both legacy (symbol, base_size) calls and newer keyword-based
        calls that provide ``side``/``quantity``/``size_type``. Defaults to
        selling a base-size amount when only ``base_size`` is provided.
        """
        # Prefer explicitly provided quantity; fall back to legacy base_size
        size = quantity if quantity is not None else base_size
        if size is None:
            raise ValueError("close_position requires a quantity or base_size")

        try:
            return self.place_market_order(
                symbol,
                side.lower() if side else 'sell',
                size,
                size_type=size_type or 'base'
            )
        except TypeError:
            # Graceful fallback if upstream signatures drift
            return self.place_market_order(symbol, 'sell', size, size_type='base')

    def get_positions(self) -> List[Dict]:
        """Return tradable crypto positions with base quantities.

        Prefers portfolio breakdown (Advanced Trade) for accurate, tradable amounts.
        Falls back to get_accounts() if breakdown is unavailable.
        """
        positions: List[Dict] = []

        # Preferred: Use portfolio breakdown to derive base quantities
        try:
            # RATE LIMIT FIX: Wrap get_portfolios with rate limiter to prevent 429 errors
            portfolios_resp = None
            if hasattr(self.client, 'get_portfolios'):
                portfolios_resp = self._api_call_with_retry(self.client.get_portfolios)

            portfolios = getattr(portfolios_resp, 'portfolios', [])
            if isinstance(portfolios_resp, dict):
                portfolios = portfolios_resp.get('portfolios', [])

            default_portfolio = None
            for pf in portfolios:
                pf_type = getattr(pf, 'type', None) if not isinstance(pf, dict) else pf.get('type')
                if str(pf_type).upper() == 'DEFAULT':
                    default_portfolio = pf
                    break
            if not default_portfolio and portfolios:
                default_portfolio = portfolios[0]

            portfolio_uuid = None
            if default_portfolio:
                portfolio_uuid = getattr(default_portfolio, 'uuid', None)
                if isinstance(default_portfolio, dict):
                    portfolio_uuid = default_portfolio.get('uuid', portfolio_uuid)

            if default_portfolio and portfolio_uuid:
                # RATE LIMIT FIX: Wrap get_portfolio_breakdown with retry logic to prevent 429 errors
                breakdown_resp = self._api_call_with_retry(
                    self.client.get_portfolio_breakdown,
                    portfolio_uuid=portfolio_uuid
                )
                breakdown = getattr(breakdown_resp, 'breakdown', None)
                if isinstance(breakdown_resp, dict):
                    breakdown = breakdown_resp.get('breakdown', breakdown)

                spot_positions = getattr(breakdown, 'spot_positions', []) if breakdown else []
                if isinstance(breakdown, dict):
                    spot_positions = breakdown.get('spot_positions', spot_positions)

                for pos in spot_positions:
                    asset = getattr(pos, 'asset', None) if not isinstance(pos, dict) else pos.get('asset')

                    # Skip fiat assets; we only return crypto positions
                    if not asset or asset in ['USD', 'USDC']:
                        continue

                    # CRITICAL FIX (Jan 24, 2026): Use CORRECT Coinbase API field names
                    # Try to fetch base available to trade using correct field name
                    base_avail = None
                    base_total = None
                    if isinstance(pos, dict):
                        base_avail = pos.get('available_to_trade_crypto')
                        base_total = pos.get('total_balance_crypto')
                        fiat_avail = pos.get('available_to_trade_fiat')
                    else:
                        base_avail = getattr(pos, 'available_to_trade_crypto', None)
                        base_total = getattr(pos, 'total_balance_crypto', None)
                        fiat_avail = getattr(pos, 'available_to_trade_fiat', None)

                    quantity = 0.0
                    try:
                        # Prefer total_balance_crypto (includes available + held)
                        if base_total is not None:
                            quantity = float(base_total or 0)
                        elif base_avail is not None:
                            quantity = float(base_avail or 0)
                        else:
                            # Derive base qty from fiat using current price
                            fiat_val = float(fiat_avail or 0)
                            if fiat_val > 0:
                                symbol = f"{asset}-USD"
                                price = self.get_current_price(symbol)
                                if price > 0:
                                    quantity = fiat_val / price
                    except Exception:
                        quantity = 0.0

                    # CRITICAL FIX: Skip true dust positions to match enforcer
                    # Calculate USD value to filter consistently
                    if quantity > 0:
                        position_symbol = f"{asset}-USD"
                        price = 0.0
                        usd_value = 0.0
                        try:
                            price = self.get_current_price(position_symbol)
                            usd_value = quantity * price if price > 0 else 0
                            # Only skip TRUE dust - count all other positions
                            if usd_value < DUST_THRESHOLD_USD:
                                logger.debug(f"Skipping dust position {position_symbol}: qty={quantity}, value=${usd_value:.4f}")
                                continue
                        except Exception:
                            # If we can't get price, include it anyway to be safe
                            pass

                        positions.append({
                            'symbol': position_symbol,
                            'quantity': quantity,
                            'currency': asset,
                            'current_price': price,
                            'size_usd': usd_value,
                        })

                # If we built positions from breakdown, return them
                if positions:
                    return positions
        except Exception as e:
            logger.warning(f"⚠️ Portfolio breakdown unavailable, falling back to get_accounts(): {e}")

        # Fallback: Use get_accounts available balances
        try:
            # RATE LIMIT FIX: Wrap get_accounts with retry logic to prevent 429 errors
            accounts = self._api_call_with_retry(self.client.get_accounts)
            # Handle both dict and object responses from Coinbase SDK
            accounts_list = accounts.get('accounts') if isinstance(accounts, dict) else getattr(accounts, 'accounts', [])

            for account in accounts_list:
                if isinstance(account, dict):
                    currency = account.get('currency')
                    balance = float(account.get('available_balance', {}).get('value', 0)) if account.get('available_balance') else 0
                else:
                    currency = getattr(account, 'currency', None)
                    balance_obj = getattr(account, 'available_balance', {})
                    balance = float(balance_obj.get('value', 0)) if isinstance(balance_obj, dict) else float(getattr(balance_obj, 'value', 0)) if balance_obj else 0

                # CRITICAL FIX: Apply same dust filtering as primary path
                if currency and currency not in ['USD', 'USDC'] and balance > 0:
                    # Calculate USD value to filter consistently
                    position_symbol = f"{currency}-USD"
                    price = 0.0
                    usd_value = 0.0
                    try:
                        price = self.get_current_price(position_symbol)
                        usd_value = balance * price if price > 0 else 0
                        # Only skip TRUE dust - count all other positions
                        if usd_value < DUST_THRESHOLD_USD:
                            logger.debug(f"Skipping dust position {position_symbol}: qty={balance}, value=${usd_value:.4f}")
                            continue
                    except Exception:
                        # If we can't get price, include it anyway to be safe
                        pass

                    positions.append({
                        'symbol': position_symbol,
                        'quantity': balance,
                        'currency': currency,
                        'current_price': price,
                        'size_usd': usd_value,
                    })
            return positions
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []

    def get_market_data(self, symbol: str, timeframe: str = '5m', limit: int = 100) -> Dict:
        """
        Get market data (wrapper around get_candles for compatibility)
        Returns dict with 'candles' key containing list of candle dicts
        """
        candles = self.get_candles(symbol, timeframe, limit)
        return {'candles': candles}

    def get_current_price(self, symbol: str) -> float:
        """Fetch latest trade/last candle price for a product."""
        try:
            # CRITICAL FIX (Jan 19, 2026): Normalize symbol for Coinbase format
            # This prevents cross-broker symbol issues (e.g., using Binance BUSD symbols on Coinbase)
            normalized_symbol = normalize_symbol_for_broker(symbol, self.broker_type.value)

            # Check if broker supports this symbol (e.g., Coinbase doesn't support BUSD)
            if not self.supports_symbol(normalized_symbol):
                logger.info(f"⏭️ Skipping unsupported symbol {symbol} on Coinbase (normalized: {normalized_symbol})")
                return 0.0

            # Fast path: product ticker price
            try:
                # RATE LIMIT FIX: Wrap get_product with rate limiter to prevent 429 errors
                def _fetch_product_price():
                    return self.client.get_product(normalized_symbol)

                if self._rate_limiter:
                    product = self._rate_limiter.call('get_product', _fetch_product_price)
                else:
                    product = _fetch_product_price()

                price_val = product.get('price') if isinstance(product, dict) else getattr(product, 'price', None)
                if price_val:
                    return float(price_val)
            except Exception:
                # Ignore and fall back to candles
                pass

            # Fallback: last close from 1m candle
            candles = self.get_candles(normalized_symbol, '1m', 1)
            if candles:
                last = candles[-1]
                close = last.get('close') if isinstance(last, dict) else getattr(last, 'close', None)
                if close:
                    return float(close)
            raise RuntimeError("No price data available")
        except Exception as e:
            logging.error(f"⚠️ get_current_price failed for {symbol}: {e}")
            return 0.0

    def get_candles(self, symbol: str, timeframe: str, count: int) -> List[Dict]:
        """Get candle data with rate limiting and retry logic

        UPDATED (Jan 9, 2026): Added RateLimiter integration to prevent 403/429 errors
        - Uses centralized rate limiter (10 req/min for candles = 1 every 6 seconds)
        - Reduced max retries from 6 to 3 for 403 errors (API key ban, not transient)
        - 429 errors get standard retry with exponential backoff
        - Rate limiter prevents cascading retries that trigger API key bans

        UPDATED (Jan 11, 2026): Added invalid symbol caching to prevent repeated API calls
        - Caches known invalid symbols to avoid wasted API calls
        - Reduces log pollution from Coinbase SDK error messages
        """

        # CRITICAL FIX (Jan 11, 2026): Check invalid symbols cache first
        # If symbol is known to be invalid, skip API call entirely
        if symbol in self._invalid_symbols_cache:
            logging.debug(f"⚠️  Skipping cached invalid symbol: {symbol}")
            return []

        # Wrapper function for rate-limited API call
        def _fetch_candles():
            granularity_map = {
                "1m": "ONE_MINUTE",
                "5m": "FIVE_MINUTE",
                "15m": "FIFTEEN_MINUTE",
                "1h": "ONE_HOUR",
                "1d": "ONE_DAY"
            }

            granularity = granularity_map.get(timeframe, "FIVE_MINUTE")

            end = int(time.time())
            start = end - (300 * count)  # 5 min candles

            candles = self.client.get_candles(
                product_id=symbol,
                start=start,
                end=end,
                granularity=granularity
            )

            if hasattr(candles, 'candles'):
                return [dict(vars(c)) for c in candles.candles]
            elif isinstance(candles, dict) and 'candles' in candles:
                return candles['candles']
            return []

        # Use rate limiter if available
        for attempt in range(RATE_LIMIT_MAX_RETRIES):
            try:
                if self._rate_limiter:
                    # Rate-limited call - automatically enforces minimum interval between requests
                    return self._rate_limiter.call('get_candles', _fetch_candles)
                else:
                    # Fallback to direct call without rate limiting
                    return _fetch_candles()

            except Exception as e:
                error_str = str(e).lower()

                # CRITICAL FIX (Jan 10, 2026): Distinguish invalid symbols from rate limits
                # Invalid symbols should not trigger retries or count toward rate limit errors
                # This prevents delisted coins from causing circuit breaker activation

                # Check for invalid product/symbol errors using shared detection logic
                is_invalid_symbol = _is_invalid_product_error(str(e))

                # If invalid symbol, don't retry - just skip it
                if is_invalid_symbol:
                    # CRITICAL FIX (Jan 11, 2026): Cache invalid symbol to prevent future API calls
                    self._invalid_symbols_cache.add(symbol)
                    # Persist to disk so the symbol is remembered across restarts
                    if self._delisted_registry:
                        self._delisted_registry.register(symbol)
                    logging.debug(f"⚠️  Invalid/delisted symbol: {symbol} - cached and skipping")
                    return []  # Return empty to signal "no data" without counting as error

                # Distinguish between 429 (rate limit) and 403 (too many errors / temporary ban)
                is_403_forbidden = '403' in error_str or 'forbidden' in error_str or 'too many errors' in error_str
                is_429_rate_limit = '429' in error_str or 'rate limit' in error_str or 'too many requests' in error_str
                is_rate_limited = is_403_forbidden or is_429_rate_limit

                if is_rate_limited and attempt < RATE_LIMIT_MAX_RETRIES - 1:
                    # Different handling for 403 vs 429
                    if is_403_forbidden:
                        # 403 "too many errors" means API key was temporarily blocked
                        # Don't retry aggressively - the key needs time to unblock
                        # Use fixed delay with jitter
                        total_delay = FORBIDDEN_BASE_DELAY + random.uniform(0, FORBIDDEN_JITTER_MAX)
                        logging.warning(f"⚠️  API key temporarily blocked (403) on {symbol}, waiting {total_delay:.1f}s before retry {attempt+1}/{RATE_LIMIT_MAX_RETRIES}")
                    else:
                        # 429 rate limit - exponential backoff
                        retry_delay = RATE_LIMIT_BASE_DELAY * (2 ** attempt)
                        jitter = random.uniform(0, retry_delay * 0.3)  # 30% jitter
                        total_delay = retry_delay + jitter
                        logging.warning(f"⚠️  Rate limited (429) on {symbol}, retrying in {total_delay:.1f}s (attempt {attempt+1}/{RATE_LIMIT_MAX_RETRIES})")

                    time.sleep(total_delay)
                    continue
                else:
                    if attempt == RATE_LIMIT_MAX_RETRIES - 1:
                        # Only log as debug - this is expected during rate limiting
                        logging.debug(f"Failed to fetch candles for {symbol} after {RATE_LIMIT_MAX_RETRIES} attempts")
                    else:
                        # Only log non-rate-limit errors as errors
                        if not is_rate_limited:
                            logging.error(f"Error fetching candles for {symbol}: {e}")
                    return []

        return []

    def get_real_entry_price(self, symbol: str) -> Optional[float]:
        """
        Get real entry price for *symbol* with three layers of resilience:

        1. **In-memory cache** — return immediately if already fetched this session.
        2. **Local entry price store** — check the JSON-backed store populated when
           trades execute; avoids redundant API calls after restarts.
        3. **Coinbase fills API** — up to 3 retries (backoff: 1.5 s, 3 s, 4.5 s).

        Successful results are cached permanently in memory and in the local store.

        Args:
            symbol: Trading symbol (e.g., 'BNB-USD')

        Returns:
            Real entry price if found, None otherwise
        """
        # ── Layer 1: in-memory permanent cache ────────────────────────────────
        with self._entry_price_cache_lock:
            cached = self._entry_price_cache.get(symbol)
        if cached is not None:
            return cached

        # ── Layer 2: local entry price store (JSON) ───────────────────────────
        if _ENTRY_PRICE_STORE_AVAILABLE and _get_eps is not None:
            try:
                local_price = _get_eps().get(symbol)
                if local_price and local_price > 0:
                    logger.debug(f"[EntryPrice] {symbol}: Using local store price ${local_price:.6g}")
                    with self._entry_price_cache_lock:
                        self._entry_price_cache[symbol] = local_price
                    return local_price
            except Exception as _eps_err:
                logger.debug(f"[EntryPrice] {symbol}: local store lookup failed: {_eps_err}")

        # ── Layer 3: Coinbase fills API (3× retry with backoff) ───────────────
        if not self.client:
            logger.debug(f"[EntryPrice] {symbol}: Coinbase client not connected")
            return None

        last_exc = None
        for attempt in range(3):
            try:
                def _fetch_fills():
                    fills_resp = self.client.get_fills(
                        product_ids=[symbol],
                        limit=100,
                    )
                    return fills_resp

                if self._rate_limiter:
                    fills_resp = self._rate_limiter.call('get_fills', _fetch_fills)
                else:
                    fills_resp = _fetch_fills()

                # Parse fills response
                fills = []
                if hasattr(fills_resp, 'fills'):
                    fills = fills_resp.fills
                elif isinstance(fills_resp, dict) and 'fills' in fills_resp:
                    fills = fills_resp['fills']

                if not fills:
                    logger.debug(f"[EntryPrice] {symbol}: No fills found in Coinbase history")
                    return None

                # Find the most recent BUY fill
                for fill in fills:
                    if isinstance(fill, dict):
                        side = fill.get('side', '').upper()
                        price = fill.get('price')
                        size = fill.get('size')
                    else:
                        side = getattr(fill, 'side', '').upper()
                        price = getattr(fill, 'price', None)
                        size = getattr(fill, 'size', None)

                    if side == 'BUY' and price:
                        try:
                            entry_price = float(price)
                            fill_size = float(size) if size else 0
                            logger.info(f"[EntryPrice] {symbol}: Fetched ${entry_price:.6g} from Coinbase fills (size: {fill_size})")
                            # Persist to in-memory cache and local store
                            with self._entry_price_cache_lock:
                                self._entry_price_cache[symbol] = entry_price
                            if _ENTRY_PRICE_STORE_AVAILABLE and _get_eps is not None:
                                try:
                                    _get_eps().save(symbol, entry_price)
                                except Exception:
                                    pass
                            return entry_price
                        except (ValueError, TypeError) as parse_err:
                            logger.warning(f"[EntryPrice] {symbol}: Invalid price data {price}: {parse_err}")
                            continue

                # Successful call, no BUY fill — stop retrying
                logger.debug(f"[EntryPrice] {symbol}: No BUY fills found in Coinbase history")
                return None

            except Exception as exc:
                last_exc = exc
                if attempt < 2:
                    delay = 1.5 * (attempt + 1)
                    logger.warning(
                        f"[EntryPrice] {symbol}: Coinbase fills attempt {attempt + 1}/3 failed "
                        f"({exc}); retrying in {delay:.1f}s"
                    )
                    time.sleep(delay)

        logger.warning(f"[EntryPrice] {symbol}: All 3 Coinbase attempts failed ({last_exc})")
        return None

    def get_bulk_entry_prices(self, symbols: List[str]) -> Dict[str, float]:
        """
        Bulk fetch entry prices from Coinbase fills for multiple symbols at once.

        Calls get_fills() with all product_ids in a single request, then computes
        VWAP per symbol from BUY fills. Far more efficient than N individual
        get_real_entry_price() calls when adopting many positions on startup.

        Args:
            symbols: List of trading symbols (e.g., ['BTC-USD', 'ETH-USD'])

        Returns:
            Dict mapping symbol -> VWAP entry price. Missing symbols not included.
        """
        if not self.client or not symbols:
            return {}

        entry_prices: Dict[str, float] = {}

        try:
            logger.info(f"   📋 Bulk-fetching entry prices for {len(symbols)} symbols from Coinbase fills...")

            def _fetch_bulk_fills():
                return self.client.get_fills(
                    product_ids=symbols,
                    limit=250,
                )

            if self._rate_limiter:
                fills_resp = self._rate_limiter.call('get_fills', _fetch_bulk_fills)
            else:
                fills_resp = _fetch_bulk_fills()

            # Parse fills response (SDK returns object or dict)
            fills = []
            if hasattr(fills_resp, 'fills'):
                fills = fills_resp.fills
            elif isinstance(fills_resp, dict) and 'fills' in fills_resp:
                fills = fills_resp['fills']

            if not fills:
                logger.debug("   Bulk fill fetch returned no fills")
                return {}

            # Group BUY fills by product_id and compute VWAP per symbol
            symbol_fills: Dict[str, list] = {}
            for fill in fills:
                if isinstance(fill, dict):
                    side = fill.get('side', '').upper()
                    price_str = fill.get('price')
                    size_str = fill.get('size')
                    product_id = fill.get('product_id', '')
                else:
                    side = getattr(fill, 'side', '').upper()
                    price_str = getattr(fill, 'price', None)
                    size_str = getattr(fill, 'size', None)
                    product_id = getattr(fill, 'product_id', '')

                if side == 'BUY' and price_str and product_id:
                    try:
                        price = float(price_str)
                        size = float(size_str) if size_str else 0.0
                        if price > 0 and size > 0:
                            symbol_fills.setdefault(product_id, []).append((price, size))
                    except (ValueError, TypeError):
                        continue

            for symbol, fills_data in symbol_fills.items():
                if fills_data:
                    total_vol = sum(s for _, s in fills_data)
                    if total_vol > 0:
                        vwap = sum(p * s for p, s in fills_data) / total_vol
                        entry_prices[symbol] = vwap
                        logger.debug(f"   {symbol}: VWAP entry ${vwap:.4f} ({len(fills_data)} fill(s))")

            found = len(entry_prices)
            missing = len(symbols) - found
            logger.info(
                f"   ✅ Bulk entry prices: {found}/{len(symbols)} found"
                + (f", {missing} not found in fills" if missing else "")
            )

        except Exception as e:
            logger.warning(f"   Coinbase bulk entry price fetch failed: {e}")

        return entry_prices

    def supports_asset_class(self, asset_class: str) -> bool:
        """Coinbase supports crypto only"""
        return asset_class.lower() == "crypto"


class AlpacaBroker(BaseBroker):
    """
    Alpaca integration for stocks and crypto.

    Features:
    - Stock trading (US equities)
    - Crypto trading (select cryptocurrencies)
    - Paper and live trading modes
    - Multi-account support (platform + user accounts)

    Documentation: https://alpaca.markets/docs/
    """

    def __init__(self, account_type: AccountType = AccountType.PLATFORM, user_id: Optional[str] = None):
        """
        Initialize Alpaca broker with account type support.

        Args:
            account_type: PLATFORM for Nija system account, USER for individual user accounts
            user_id: User ID for USER account_type (e.g., 'tania_gilbert')

        Raises:
            ValueError: If account_type is USER but user_id is not provided
        """
        super().__init__(BrokerType.ALPACA, account_type=account_type, user_id=user_id)

        # Validate that USER account_type has user_id
        if account_type == AccountType.USER and not user_id:
            raise ValueError("USER account_type requires user_id parameter")

        self.api = None

        # Set identifier for logging
        if account_type == AccountType.PLATFORM:
            self.account_identifier = "PLATFORM"
        else:
            self.account_identifier = f"USER:{user_id}" if user_id else "USER:unknown"

        # Initialize position tracker for profit-based exits
        # 🔒 CAPITAL PROTECTION: Position tracker is MANDATORY - no silent fallback
        try:
            from position_tracker import PositionTracker
            self.position_tracker = PositionTracker(storage_file="data/positions.json")
            logger.info("✅ Position tracker initialized for profit-based exits")
        except Exception as e:
            logger.error(f"❌ CAPITAL PROTECTION: Position tracker initialization FAILED: {e}")
            logger.error("❌ Position tracker is MANDATORY for capital protection - cannot proceed")
            raise RuntimeError(f"MANDATORY position_tracker initialization failed: {e}")

    @property
    def client(self):
        """Alias for self.api to maintain consistency with other brokers"""
        return self.api

    def connect(self) -> bool:
        """
        Connect to Alpaca API with retry logic.

        Uses different credentials based on account_type:
        - PLATFORM: ALPACA_API_KEY / ALPACA_API_SECRET / ALPACA_PAPER
        - USER: ALPACA_USER_{user_id}_API_KEY / ALPACA_USER_{user_id}_API_SECRET / ALPACA_USER_{user_id}_PAPER

        Returns:
            bool: True if connected successfully
        """
        try:
            from alpaca.trading.client import TradingClient
            import time

            # Get credentials based on account type
            if self.account_type == AccountType.PLATFORM:
                api_key = os.getenv("ALPACA_API_KEY", "").strip()
                api_secret = os.getenv("ALPACA_API_SECRET", "").strip()
                paper = os.getenv("ALPACA_PAPER", "true").lower() == "true"
                cred_label = "PLATFORM"
            else:
                # User account - construct env var name from user_id
                # Convert user_id to uppercase for env var
                # For user_id like 'tania_gilbert', extracts 'TANIA' for ALPACA_USER_TANIA_API_KEY
                # For user_id like 'john', uses 'JOHN' for ALPACA_USER_JOHN_API_KEY
                user_env_name = self.user_id.split('_')[0].upper() if '_' in self.user_id else self.user_id.upper()
                api_key = os.getenv(f"ALPACA_USER_{user_env_name}_API_KEY", "").strip()
                api_secret = os.getenv(f"ALPACA_USER_{user_env_name}_API_SECRET", "").strip()
                # Fallback: also try the full user_id in uppercase
                # e.g. ALPACA_USER_TANIA_GILBERT_API_KEY for user_id='tania_gilbert'
                if not api_key or not api_secret:
                    full_env_name = self.user_id.upper()
                    if full_env_name != user_env_name:
                        if not api_key:
                            api_key = os.getenv(f"ALPACA_USER_{full_env_name}_API_KEY", "").strip()
                        if not api_secret:
                            api_secret = os.getenv(f"ALPACA_USER_{full_env_name}_API_SECRET", "").strip()
                paper_str = os.getenv(
                    f"ALPACA_USER_{user_env_name}_PAPER",
                    os.getenv(f"ALPACA_USER_{self.user_id.upper()}_PAPER", "true"),
                ).strip()
                paper = paper_str.lower() == "true"
                cred_label = f"USER:{self.user_id}"

            if not api_key or not api_secret:
                # Mark that credentials were not configured (not an error, just not set up)
                self.credentials_configured = False
                # Silently skip - Alpaca is optional
                logger.info(f"⚠️  Alpaca credentials not configured for {cred_label} (skipping)")
                if self.account_type == AccountType.PLATFORM:
                    logger.info("   To enable Alpaca PLATFORM trading, set:")
                    logger.info("      ALPACA_API_KEY=<your-api-key>")
                    logger.info("      ALPACA_API_SECRET=<your-api-secret>")
                    logger.info("      ALPACA_PAPER=true  # or false for live trading")
                else:
                    # USER account - provide specific instructions
                    logger.info(f"   To enable Alpaca USER trading for {self.user_id}, set:")
                    logger.info(f"      ALPACA_USER_{user_env_name}_API_KEY=<your-api-key>")
                    logger.info(f"      ALPACA_USER_{user_env_name}_API_SECRET=<your-api-secret>")
                    logger.info(f"      ALPACA_USER_{user_env_name}_PAPER=true  # or false for live trading")
                return False

            # Log connection mode
            mode_str = "PAPER" if paper else "LIVE"
            logging.info(f"📊 Attempting to connect Alpaca {cred_label} ({mode_str} mode)...")

            self.api = TradingClient(api_key, api_secret, paper=paper)

            # Mark that credentials were configured (we have API key and secret)
            self.credentials_configured = True

            # Test connection with retry logic
            # Increased max attempts for 403 "too many errors" which indicates temporary API key blocking
            # Note: 403 differs from 429 (rate limiting) - it means the API key was temporarily blocked
            max_attempts = 5
            base_delay = 5.0  # Increased from 2.0 to allow API key blocks to reset

            for attempt in range(1, max_attempts + 1):
                try:
                    if attempt > 1:
                        # Add delay before retry with exponential backoff
                        # For 403 errors, we need longer delays: 5s, 10s, 20s, 40s (attempts 2-5)
                        delay = base_delay * (2 ** (attempt - 2))
                        logging.info(f"🔄 Retrying Alpaca {cred_label} connection in {delay}s (attempt {attempt}/{max_attempts})...")
                        time.sleep(delay)

                    account = self.api.get_account()
                    self.connected = True

                    if attempt > 1:
                        logging.info(f"✅ Connected to Alpaca {cred_label} API (succeeded on attempt {attempt})")
                    else:
                        logging.info(f"✅ Alpaca {cred_label} connected ({'PAPER' if paper else 'LIVE'})")

                    return True

                except Exception as e:
                    error_msg = str(e)

                    # Special handling for paper trading being disabled
                    if "paper" in error_msg.lower() and "not" in error_msg.lower():
                        logging.warning(f"⚠️  Alpaca {cred_label} paper trading may be disabled or account not configured for paper trading")
                        logging.warning(f"   Try setting ALPACA{'_USER_' + user_env_name if self.account_type == AccountType.USER else ''}_PAPER=false for live trading")
                        return False

                    # Check if error is retryable (rate limiting, network issues, 403 errors, etc.)
                    # CRITICAL: Include 403, forbidden, and "too many errors" as retryable
                    # These indicate API key blocking and need longer cooldown periods
                    is_retryable = any(keyword in error_msg.lower() for keyword in [
                        'timeout', 'connection', 'network', 'rate limit',
                        'too many requests', 'service unavailable',
                        '503', '504', '429', '403', 'forbidden',
                        'too many errors', 'temporary', 'try again'
                    ])

                    if is_retryable and attempt < max_attempts:
                        logging.warning(f"⚠️  Alpaca {cred_label} connection attempt {attempt}/{max_attempts} failed (retryable): {error_msg}")
                        continue
                    else:
                        logging.warning(f"⚠️  Alpaca {cred_label} connection failed: {e}")
                        return False

            # Should never reach here, but just in case
            logging.error(f"❌ Failed to connect to Alpaca {cred_label} after maximum retry attempts")
            return False

        except ImportError as e:
            # SDK not installed or import failed
            logging.error(f"❌ Alpaca connection failed ({self.account_identifier}): SDK import error")
            logging.error(f"   ImportError: {e}")
            logging.error("   The Alpaca SDK (alpaca-py) failed to import")
            logging.error("")
            logging.error("   📋 Troubleshooting steps:")
            logging.error("      1. Verify alpaca-py is in requirements.txt")
            logging.error("      2. Check deployment logs for package installation errors")
            logging.error("      3. Try manual install: pip install alpaca-py")
            logging.error("      4. Check for dependency conflicts with: pip check")
            return False

    def get_account_balance(self, verbose: bool = True) -> float:
        """
        Get total equity (cash + position values) for Alpaca account.

        CRITICAL FIX (Rule #3): Balance = CASH + POSITION VALUE
        Returns total equity (available cash + position market value), not just cash.

        For Alpaca, the account object provides 'equity' which includes both cash and positions.
        This is the correct value to use for risk calculations and position sizing.

        Args:
            verbose: If True, logs detailed balance breakdown (default: True)

        Returns:
            float: Total equity (cash + positions)
        """
        try:
            account = self.api.get_account()

            # Alpaca provides 'equity' which is cash + position values
            # This is exactly what we need per Rule #3
            equity = float(account.equity)
            cash = float(account.cash)
            position_value = equity - cash

            # Enhanced logging to show breakdown (only if verbose=True)
            if verbose:
                logger.info("=" * 70)
                logger.info(f"💰 Alpaca Balance ({self.account_identifier}):")
                logger.info(f"   ✅ Cash: ${cash:.2f}")
                if position_value > 0:
                    logger.info(f"   📊 Position Value: ${position_value:.2f}")
                    logger.info(f"   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                    logger.info(f"   💎 TOTAL EQUITY: ${equity:.2f}")
                else:
                    logger.info(f"   💎 TOTAL EQUITY: ${equity:.2f} (no positions)")
                logger.info("=" * 70)
            else:
                # Minimal logging when verbose=False
                logger.debug(f"Alpaca balance ({self.account_identifier}): ${equity:.2f}")

            return equity

        except Exception as e:
            logger.error(f"Error fetching Alpaca balance: {e}")
            return 0.0

    def place_market_order(self, symbol: str, side: str, quantity: float) -> Dict:
        """Place market order"""
        # 🍎 CRITICAL LAYER 0: APP STORE MODE CHECK (Absolute Block)
        try:
            from bot.app_store_mode import get_app_store_mode
            app_store_mode = get_app_store_mode()
            if app_store_mode.is_enabled():
                return app_store_mode.block_execution_with_log(
                    operation='place_market_order',
                    symbol=symbol,
                    side=side,
                    size=quantity
                )
        except ImportError:
            pass
        
        try:
            # 🔒 LAYER 1: BROKER ISOLATION CHECK
            _iso = _check_broker_isolation(self.broker_type, side)
            if _iso is not None:
                return _iso

            from alpaca.trading.requests import MarketOrderRequest
            from alpaca.trading.enums import OrderSide, TimeInForce

            order_side = OrderSide.BUY if side.lower() == 'buy' else OrderSide.SELL

            order_data = MarketOrderRequest(
                symbol=symbol,
                qty=quantity,
                side=order_side,
                time_in_force=TimeInForce.DAY
            )

            order = self.api.submit_order(order_data)

            # Enhanced trade confirmation logging with account identification
            account_label = f"{self.account_identifier}" if hasattr(self, 'account_identifier') else "PLATFORM"

            # FIRST LIVE TRADE BANNER (for legal/operational protection)
            global _FIRST_TRADE_EXECUTED
            with _FIRST_TRADE_LOCK:
                if not _FIRST_TRADE_EXECUTED:
                    _FIRST_TRADE_EXECUTED = True
                    logger.info("")
                    logger.info(LOG_SEPARATOR)
                    logger.info("🚨 FIRST LIVE TRADE EXECUTED 🚨")
                    logger.info(LOG_SEPARATOR)
                    logger.info(f"   Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
                    logger.info(f"   Symbol: {symbol}")
                    logger.info(f"   Size: {quantity} (shares)")
                    logger.info(f"   Account: {account_label}")
                    logger.info(f"   Side: {side.upper()}")
                    logger.info(f"   Exchange: Alpaca (Stocks)")
                    logger.info("")
                    logger.info("   This confirms live trading is operational.")
                    logger.info("   All subsequent trades will be logged normally.")
                    logger.info(LOG_SEPARATOR)
                    logger.info("")

            logger.info(LOG_SEPARATOR)
            logger.info(f"✅ TRADE CONFIRMATION - {account_label}")
            logger.info(LOG_SEPARATOR)
            logger.info(f"   Exchange: Alpaca (Stocks)")
            logger.info(f"   Order Type: {side.upper()}")
            logger.info(f"   Symbol: {symbol}")
            logger.info(f"   Quantity: {quantity}")
            logger.info(f"   Order ID: {order.id if hasattr(order, 'id') else 'N/A'}")
            logger.info(f"   Account: {account_label}")
            logger.info(f"   Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
            logger.info(LOG_SEPARATOR)

            # Flush logs immediately to ensure confirmation is visible
            if _root_logger.handlers:
                for handler in _root_logger.handlers:
                    handler.flush()

            return {
                "status": "submitted",
                "order": order,
                "account": account_label  # Add account identification to result
            }

        except Exception as e:
            logger.error(f"Alpaca order error: {e}")
            return {"status": "error", "error": str(e)}

    def get_positions(self) -> List[Dict]:
        """Get open positions with normalized field names.

        Alpaca's API already provides avg_entry_price, current_price, and
        market_value, so no additional price fetches are required.
        """
        try:
            positions = self.api.get_all_positions()
            result = []
            for pos in positions:
                entry_price = 0.0
                current_price = 0.0
                size_usd = 0.0
                try:
                    entry_price = float(pos.avg_entry_price)
                except (TypeError, ValueError, AttributeError):
                    pass
                try:
                    current_price = float(pos.current_price) if hasattr(pos, 'current_price') else 0.0
                except (TypeError, ValueError):
                    pass
                try:
                    size_usd = float(pos.market_value)
                except (TypeError, ValueError, AttributeError):
                    pass
                result.append({
                    'symbol': pos.symbol,
                    'quantity': float(pos.qty),
                    'entry_price': entry_price,
                    'current_price': current_price,
                    'size_usd': size_usd,
                    'unrealized_pl': float(pos.unrealized_pl) if hasattr(pos, 'unrealized_pl') else 0.0,
                })
            return result
        except Exception as e:
            logger.error(f"Error fetching positions: {e}")
            return []

    def get_candles(self, symbol: str, timeframe: str, count: int) -> List[Dict]:
        """Get candle data with retry logic for rate limiting"""
        # Import Alpaca SDK dependencies (method-level import to avoid import errors when SDK not installed)
        try:
            from alpaca.data.historical import StockHistoricalDataClient
            from alpaca.data.requests import StockBarsRequest
            from alpaca.data.timeframe import TimeFrame
            from datetime import datetime, timedelta
        except ImportError:
            logging.error("Alpaca SDK not installed. Run: pip install alpaca-py")
            return []

        # Get credentials and create client outside retry loop (doesn't change between retries)
        api_key = os.getenv("ALPACA_API_KEY")
        api_secret = os.getenv("ALPACA_API_SECRET")

        if not api_key or not api_secret:
            logging.error("Alpaca API credentials not configured")
            return []

        data_client = StockHistoricalDataClient(api_key, api_secret)

        # Timeframe mapping (constant for all retries)
        timeframe_map = {
            "1m": TimeFrame.Minute,
            "5m": TimeFrame(5, TimeFrame.Minute),
            "15m": TimeFrame(15, TimeFrame.Minute),
            "1h": TimeFrame.Hour,
            "1d": TimeFrame.Day
        }
        tf = timeframe_map.get(timeframe, TimeFrame(5, TimeFrame.Minute))

        # Retry loop for API call (1-based indexing for clearer log messages)
        for attempt in range(1, RATE_LIMIT_MAX_RETRIES + 1):
            try:
                request_params = StockBarsRequest(
                    symbol_or_symbols=symbol,
                    timeframe=tf,
                    start=datetime.now() - timedelta(days=7)
                )

                bars = data_client.get_stock_bars(request_params)

                candles = []
                for bar in bars[symbol]:
                    candles.append({
                        'time': bar.timestamp,
                        'open': float(bar.open),
                        'high': float(bar.high),
                        'low': float(bar.low),
                        'close': float(bar.close),
                        'volume': float(bar.volume)
                    })

                return candles[-count:] if len(candles) > count else candles

            except Exception as e:
                error_str = str(e).lower()

                # CRITICAL FIX (Jan 13, 2026): Use centralized error detection function
                # Alpaca returns various error messages for invalid/delisted stocks:
                # - "invalid symbol", "symbol not found", "asset not found"
                # - "No key SYMBOL was found" (common for delisted stocks)
                # These should not trigger retries or count toward rate limit errors
                is_invalid_symbol = _is_invalid_product_error(str(e))

                # Log invalid symbols at debug level (not error) since it's expected
                if is_invalid_symbol:
                    logging.debug(f"⚠️  Invalid/delisted stock symbol: {symbol} - skipping")
                    return []  # Return empty to signal "no data" without counting as error

                # Distinguish between 429 (rate limit) and 403 (too many errors / temporary ban)
                is_403_forbidden = '403' in error_str or 'forbidden' in error_str or 'too many errors' in error_str
                is_429_rate_limit = '429' in error_str or 'rate limit' in error_str or 'too many requests' in error_str
                is_rate_limited = is_403_forbidden or is_429_rate_limit

                if is_rate_limited and attempt < RATE_LIMIT_MAX_RETRIES:
                    # Different handling for 403 vs 429
                    if is_403_forbidden:
                        # 403 errors: Use fixed delay with jitter (API key temporarily blocked)
                        delay = FORBIDDEN_BASE_DELAY + random.uniform(0, FORBIDDEN_JITTER_MAX)
                        logging.warning(f"⚠️  Alpaca rate limit (403 Forbidden): API key temporarily blocked for {symbol}")
                        logging.warning(f"   Waiting {delay:.1f}s before retry {attempt}/{RATE_LIMIT_MAX_RETRIES}...")
                    else:
                        # 429 errors: Use exponential backoff with jitter (prevent thundering herd)
                        base_delay = RATE_LIMIT_BASE_DELAY * (2 ** (attempt - 1))
                        jitter = random.uniform(0, base_delay * 0.3)  # 30% jitter
                        delay = base_delay + jitter
                        logging.warning(f"⚠️  Alpaca rate limit (429): Too many requests for {symbol}")
                        logging.warning(f"   Waiting {delay:.1f}s before retry {attempt}/{RATE_LIMIT_MAX_RETRIES}...")

                    time.sleep(delay)
                    continue
                else:
                    # Not rate limited or max retries reached
                    if is_rate_limited:
                        # Rate limit persisted after retries - log at WARNING level
                        logging.warning(f"⚠️  Alpaca rate limit exceeded for {symbol} after {RATE_LIMIT_MAX_RETRIES} retries")
                    else:
                        # Non-rate-limit error - log at ERROR level
                        logging.error(f"Error fetching candles for {symbol}: {e}")
                    return []

        return []

    def supports_asset_class(self, asset_class: str) -> bool:
        """Alpaca supports stocks"""
        return asset_class.lower() in ["stocks", "stock"]

    def get_all_products(self) -> list:
        """
        Get list of tradeable stock symbols from Alpaca.
        Note: Alpaca is for stocks, not crypto. Returns popular stock symbols.

        Returns:
            List of stock symbols (e.g., ['AAPL', 'MSFT', 'GOOGL', ...])
        """
        try:
            if not self.api:
                logging.warning("⚠️  Alpaca not connected, cannot fetch products")
                return []

            # Get all active assets from Alpaca
            from alpaca.trading.requests import GetAssetsRequest
            from alpaca.trading.enums import AssetClass, AssetStatus

            request = GetAssetsRequest(
                status=AssetStatus.ACTIVE,
                asset_class=AssetClass.US_EQUITY
            )

            assets = self.api.get_all_assets(request)

            # Extract tradeable symbols
            symbols = []
            for asset in assets:
                if asset.tradable and asset.status == AssetStatus.ACTIVE:
                    symbols.append(asset.symbol)

            logging.info(f"📊 Alpaca: Found {len(symbols)} tradeable stock symbols")
            return symbols

        except ImportError:
            logging.warning("⚠️  Alpaca SDK not available")
            return []
        except Exception as e:
            logging.warning(f"⚠️  Error fetching Alpaca products: {e}")
            # Return a fallback list of popular stocks
            fallback_stocks = [
                'AAPL', 'MSFT', 'GOOGL', 'AMZN', 'TSLA', 'META', 'NVDA', 'JPM',
                'V', 'WMT', 'MA', 'DIS', 'NFLX', 'ADBE', 'PYPL', 'INTC',
                'CSCO', 'PFE', 'KO', 'NKE', 'BAC', 'XOM', 'T', 'VZ'
            ]
            logging.info(f"📊 Alpaca: Using fallback list of {len(fallback_stocks)} stock symbols")
            return fallback_stocks

class BinanceBroker(BaseBroker):
    """
    Binance Exchange integration for cryptocurrency spot trading.

    Features:
    - Spot trading (USDT pairs)
    - Market and limit orders
    - Real-time account balance
    - Historical candle data (OHLCV)

    Documentation: https://python-binance.readthedocs.io/
    """

    def __init__(self, account_type: AccountType = AccountType.PLATFORM, user_id: Optional[str] = None):
        super().__init__(BrokerType.BINANCE, account_type=account_type, user_id=user_id)
        self.client = None

        # Initialize position tracker for profit-based exits
        # 🔒 CAPITAL PROTECTION: Position tracker is MANDATORY - no silent fallback
        try:
            from position_tracker import PositionTracker
            self.position_tracker = PositionTracker(storage_file="data/positions.json")
            logger.info("✅ Position tracker initialized for profit-based exits")
        except Exception as e:
            logger.error(f"❌ CAPITAL PROTECTION: Position tracker initialization FAILED: {e}")
            logger.error("❌ Position tracker is MANDATORY for capital protection - cannot proceed")
            raise RuntimeError(f"MANDATORY position_tracker initialization failed: {e}")

    def connect(self) -> bool:
        """
        Connect to Binance API with retry logic.

        Requires environment variables:
        - BINANCE_API_KEY: Your Binance API key
        - BINANCE_API_SECRET: Your Binance API secret
        - BINANCE_USE_TESTNET: 'true' for testnet, 'false' for live (optional, default: false)

        Returns:
            bool: True if connected successfully
        """
        try:
            from binance.client import Client
            import time

            api_key = os.getenv("BINANCE_API_KEY", "").strip()
            api_secret = os.getenv("BINANCE_API_SECRET", "").strip()
            use_testnet = os.getenv("BINANCE_USE_TESTNET", "false").lower() in ["true", "1", "yes"]

            if not api_key or not api_secret:
                # Partial credentials are more likely a misconfiguration — warn at WARNING level
                if api_key and not api_secret:
                    logging.warning("⚠️  Binance BINANCE_API_KEY is set but BINANCE_API_SECRET is missing — skipping Binance")
                elif api_secret and not api_key:
                    logging.warning("⚠️  Binance BINANCE_API_SECRET is set but BINANCE_API_KEY is missing — skipping Binance")
                else:
                    logging.info("ℹ️  Binance credentials not configured (optional broker — skipping)")
                return False

            # Initialize Binance client
            if use_testnet:
                # Testnet base URL
                self.client = Client(api_key, api_secret, testnet=True)
            else:
                self.client = Client(api_key, api_secret)

            # Test connection by fetching account status with retry logic
            # Increased max attempts for 403 "too many errors" which indicates temporary API key blocking
            # Note: 403 differs from 429 (rate limiting) - it means the API key was temporarily blocked
            max_attempts = 5
            base_delay = 5.0  # Increased from 2.0 to allow API key blocks to reset

            for attempt in range(1, max_attempts + 1):
                try:
                    if attempt > 1:
                        # Add delay before retry with exponential backoff
                        # For 403 errors, we need longer delays: 5s, 10s, 20s, 40s (attempts 2-5)
                        delay = base_delay * (2 ** (attempt - 2))
                        logging.info(f"🔄 Retrying Binance connection in {delay}s (attempt {attempt}/{max_attempts})...")
                        time.sleep(delay)

                    account = self.client.get_account()

                    if account:
                        self.connected = True

                        if attempt > 1:
                            logging.info(f"✅ Connected to Binance API (succeeded on attempt {attempt})")

                        env_type = "🧪 TESTNET" if use_testnet else "🔴 LIVE"
                        logging.info("=" * 70)
                        logging.info(f"✅ BINANCE CONNECTED ({env_type})")
                        logging.info("=" * 70)

                        # Log account trading status
                        can_trade = account.get('canTrade', False)
                        logging.info(f"   Trading Enabled: {'✅' if can_trade else '❌'}")

                        # Log USDT balance
                        for balance in account.get('balances', []):
                            if balance['asset'] == 'USDT':
                                usdt_balance = float(balance['free'])
                                logging.info(f"   USDT Balance: ${usdt_balance:.2f}")
                                break

                        logging.info("=" * 70)
                        return True
                    else:
                        if attempt < max_attempts:
                            logging.warning(f"⚠️  Binance connection attempt {attempt}/{max_attempts} failed (retryable): No account data returned")
                            continue
                        else:
                            logging.warning("⚠️  Binance connection test failed: No account data returned")
                            return False

                except Exception as e:
                    error_msg = str(e)

                    # Check if error is retryable (rate limiting, network issues, 403 errors, etc.)
                    # CRITICAL: Include 403, forbidden, and "too many errors" as retryable
                    # These indicate API key blocking and need longer cooldown periods
                    is_retryable = any(keyword in error_msg.lower() for keyword in [
                        'timeout', 'connection', 'network', 'rate limit',
                        'too many requests', 'service unavailable',
                        '503', '504', '429', '403', 'forbidden',
                        'too many errors', 'temporary', 'try again'
                    ])

                    if is_retryable and attempt < max_attempts:
                        logging.warning(f"⚠️  Binance connection attempt {attempt}/{max_attempts} failed (retryable): {error_msg}")
                        continue
                    else:
                        # Handle authentication errors gracefully
                        error_str = error_msg.lower()
                        if 'api' in error_str and ('key' in error_str or 'signature' in error_str or 'authentication' in error_str):
                            logging.warning("⚠️  Binance authentication failed - invalid or expired API credentials")
                            logging.warning("   Please check your BINANCE_API_KEY and BINANCE_API_SECRET")
                        elif 'connection' in error_str or 'network' in error_str or 'timeout' in error_str:
                            logging.warning("⚠️  Binance connection failed - network issue or API unavailable")
                        else:
                            logging.warning(f"⚠️  Binance connection failed: {e}")
                        return False

            # Should never reach here, but just in case
            logging.error("❌ Failed to connect to Binance after maximum retry attempts")
            return False

        except ImportError as e:
            # SDK not installed or import failed
            logging.error("❌ Binance connection failed: SDK import error")
            logging.error(f"   ImportError: {e}")
            logging.error("   The Binance SDK (python-binance) failed to import")
            logging.error("")
            logging.error("   📋 Troubleshooting steps:")
            logging.error("      1. Verify python-binance is in requirements.txt")
            logging.error("      2. Check deployment logs for package installation errors")
            logging.error("      3. Try manual install: pip install python-binance")
            logging.error("      4. Check for dependency conflicts with: pip check")
            return False

    def get_account_balance(self, verbose: bool = True) -> float:
        """
        Get USDT balance available for trading.

        Args:
            verbose: If True, logs detailed balance breakdown (default: True)

        Returns:
            float: Available USDT balance
        """
        try:
            if not self.client:
                return 0.0

            # Get account balances
            account = self.client.get_account()

            # Find USDT balance
            for balance in account.get('balances', []):
                if balance['asset'] == 'USDT':
                    available = float(balance.get('free', 0))
                    if verbose:
                        logging.info(f"💰 Binance USDT Balance: ${available:.2f}")
                    else:
                        logging.debug(f"Binance USDT Balance: ${available:.2f}")
                    return available

            # No USDT found
            if verbose:
                logging.warning("⚠️  No USDT balance found in Binance account")
            return 0.0

        except Exception as e:
            logging.error(f"Error fetching Binance balance: {e}")
            return 0.0

    def place_market_order(self, symbol: str, side: str, quantity: float) -> Dict:
        """
        Place market order on Binance.

        Args:
            symbol: Trading pair (e.g., 'BTC-USD' or 'BTCUSDT')
            side: 'buy' or 'sell'
            quantity: Order size in USDT (for buys) or base currency (for sells)

        Returns:
            dict: Order result with status, order_id, etc.
        """
        try:
            # 🔒 LAYER 1: BROKER ISOLATION CHECK
            _iso = _check_broker_isolation(self.broker_type, side)
            if _iso is not None:
                return _iso

            if not self.client:
                return {"status": "error", "error": "Not connected to Binance"}

            # Convert symbol format (BTC-USD -> BTCUSDT)
            binance_symbol = symbol.replace('-USD', 'USDT').replace('-', '')

            # Binance uses uppercase for side
            binance_side = side.upper()

            # Place market order
            # Note: Binance requires 'quantity' parameter for market orders
            # For buy orders, you may want to use quoteOrderQty instead
            if binance_side == 'BUY':
                # Use quoteOrderQty for buy orders (spend X USDT)
                order = self.client.order_market_buy(
                    symbol=binance_symbol,
                    quoteOrderQty=quantity
                )
            else:
                # Use quantity for sell orders (sell X crypto)
                order = self.client.order_market_sell(
                    symbol=binance_symbol,
                    quantity=quantity
                )

            if order:
                order_id = order.get('orderId')
                status = order.get('status', 'UNKNOWN')
                filled_qty = float(order.get('executedQty', 0))

                logging.info(f"✅ Binance order placed: {binance_side} {binance_symbol}")
                logging.info(f"   Order ID: {order_id}")
                logging.info(f"   Status: {status}")
                logging.info(f"   Filled: {filled_qty}")

                return {
                    "status": "filled" if status == "FILLED" else "unfilled",
                    "order_id": str(order_id),
                    "symbol": binance_symbol,
                    "side": binance_side.lower(),
                    "quantity": quantity,
                    "filled_quantity": filled_qty
                }

            logging.error("❌ Binance order failed: No order data returned")
            return {"status": "error", "error": "No order data"}

        except Exception as e:
            logging.error(f"Binance order error: {e}")
            return {"status": "error", "error": str(e)}

    def get_positions(self) -> List[Dict]:
        """
        Get open positions (non-zero balances) enriched with current prices.

        Batch-fetches all prices in a single get_all_tickers() call to avoid
        N individual price requests.

        Returns:
            list: List of position dicts with symbol, quantity, currency,
                  current_price, and size_usd.
        """
        try:
            if not self.client:
                return []

            # Get account balances
            account = self.client.get_account()

            # Build raw list of non-zero, non-USDT holdings
            raw_holdings = []
            for balance in account.get('balances', []):
                asset = balance['asset']
                available = float(balance.get('free', 0))
                if asset != 'USDT' and available > 0:
                    binance_symbol = f'{asset}USDT'
                    raw_holdings.append((asset, available, binance_symbol))

            if not raw_holdings:
                return []

            # Batch-fetch prices for all holdings in one call
            batch_prices: Dict[str, float] = {}
            try:
                all_tickers = self.client.get_all_tickers()
                for ticker in all_tickers:
                    sym = ticker.get('symbol', '')
                    try:
                        batch_prices[sym] = float(ticker.get('price', 0))
                    except (ValueError, TypeError):
                        pass
            except Exception as _ticker_err:
                logger.warning(f"Binance batch ticker fetch failed: {_ticker_err}")

            positions = []
            for asset, available, binance_symbol in raw_holdings:
                current_price = batch_prices.get(binance_symbol, 0.0)
                size_usd = available * current_price if current_price > 0 else 0.0
                positions.append({
                    'symbol': f'{asset}-USD',
                    'quantity': available,
                    'currency': asset,
                    'current_price': current_price,
                    'size_usd': size_usd,
                })

            return positions

        except Exception as e:
            logger.error(f"Error fetching Binance positions: {e}")
            return []

    def get_bulk_entry_prices(self, symbols: List[str]) -> Dict[str, float]:
        """
        Bulk fetch entry prices from Binance trade history for multiple symbols.

        Fetches my_trades for each symbol and computes VWAP of BUY trades.
        More efficient than individual calls when adopting many positions.

        Args:
            symbols: Standard-format symbols (e.g., ['BTC-USD', 'ETH-USD'])

        Returns:
            Dict mapping symbol -> VWAP entry price.
        """
        if not self.client or not symbols:
            return {}

        entry_prices: Dict[str, float] = {}
        logger.info(f"   📋 Bulk-fetching entry prices for {len(symbols)} symbols from Binance trade history...")

        for symbol in symbols:
            binance_symbol = symbol.replace('-USD', 'USDT').replace('-', '')
            try:
                trades = self.client.get_my_trades(symbol=binance_symbol, limit=500)
                buy_fills = []
                for trade in trades:
                    if trade.get('isBuyer', False):
                        try:
                            price = float(trade.get('price', 0))
                            qty = float(trade.get('qty', 0))
                            if price > 0 and qty > 0:
                                buy_fills.append((price, qty))
                        except (ValueError, TypeError):
                            pass
                if buy_fills:
                    total_qty = sum(q for _, q in buy_fills)
                    if total_qty > 0:
                        vwap = sum(p * q for p, q in buy_fills) / total_qty
                        entry_prices[symbol] = vwap
                        logger.debug(f"   {symbol}: VWAP entry ${vwap:.4f} ({len(buy_fills)} fill(s))")
            except Exception as _e:
                logger.debug(f"   Could not fetch Binance trades for {symbol}: {_e}")

        found = len(entry_prices)
        missing = len(symbols) - found
        logger.info(
            f"   ✅ Bulk entry prices: {found}/{len(symbols)} found"
            + (f", {missing} not found in trade history" if missing else "")
        )
        return entry_prices

    def get_candles(self, symbol: str, timeframe: str, count: int) -> List[Dict]:
        """
        Get historical candle data from Binance.

        Args:
            symbol: Trading pair (e.g., 'BTC-USD' or 'BTCUSDT')
            timeframe: Candle interval ('1m', '5m', '15m', '1h', '1d', etc.)
            count: Number of candles to fetch (max 1000)

        Returns:
            list: List of candle dicts with OHLCV data
        """
        try:
            if not self.client:
                return []

            # Convert symbol format
            binance_symbol = symbol.replace('-USD', 'USDT').replace('-', '')

            # Map timeframe to Binance interval
            # Binance uses: 1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 6h, 8h, 12h, 1d, 3d, 1w, 1M
            interval_map = {
                "1m": "1m",
                "5m": "5m",
                "15m": "15m",
                "1h": "1h",
                "4h": "4h",
                "1d": "1d"
            }

            binance_interval = interval_map.get(timeframe.lower(), "5m")

            # Fetch klines (candles)
            klines = self.client.get_klines(
                symbol=binance_symbol,
                interval=binance_interval,
                limit=min(count, 1000)  # Binance max is 1000
            )

            candles = []
            for kline in klines:
                # Binance kline format: [timestamp, open, high, low, close, volume, ...]
                candles.append({
                    'time': int(kline[0]),
                    'open': float(kline[1]),
                    'high': float(kline[2]),
                    'low': float(kline[3]),
                    'close': float(kline[4]),
                    'volume': float(kline[5])
                })

            return candles

        except Exception as e:
            logging.error(f"Error fetching Binance candles: {e}")
            return []

    def supports_asset_class(self, asset_class: str) -> bool:
        """Binance supports crypto spot trading"""
        return asset_class.lower() in ["crypto", "cryptocurrency"]

    def get_all_products(self) -> list:
        """
        Get list of all tradeable cryptocurrency pairs from Binance.

        Returns:
            List of trading pairs (e.g., ['BTCUSDT', 'ETHUSDT', ...])
        """
        try:
            if not self.client:
                logging.warning("⚠️  Binance not connected, cannot fetch products")
                return []

            # Get all exchange info (includes all trading pairs)
            exchange_info = self.client.get_exchange_info()

            # Extract symbols that are trading (status = 'TRADING')
            symbols = []
            for symbol_info in exchange_info.get('symbols', []):
                if symbol_info.get('status') == 'TRADING':
                    # Filter for USDT pairs (most common for crypto trading)
                    symbol = symbol_info.get('symbol', '')
                    if symbol.endswith('USDT'):
                        symbols.append(symbol)

            logging.info(f"📊 Binance: Found {len(symbols)} tradeable USDT pairs")
            return symbols

        except Exception as e:
            logging.warning(f"⚠️  Error fetching Binance products: {e}")
            # Return a fallback list of popular crypto pairs
            fallback_pairs = [
                'BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT', 'ADAUSDT',
                'DOGEUSDT', 'MATICUSDT', 'DOTUSDT', 'LINKUSDT', 'UNIUSDT', 'AVAXUSDT',
                'ATOMUSDT', 'LTCUSDT', 'NEARUSDT', 'ALGOUSDT', 'XLMUSDT', 'HBARUSDT'
            ]
            logging.info(f"📊 Binance: Using fallback list of {len(fallback_pairs)} crypto pairs")
            return fallback_pairs









class KrakenBroker(BaseBroker):
    """
    Kraken Pro Exchange integration for cryptocurrency spot trading.

    Features:
    - Spot trading (USD/USDT pairs)
    - Market and limit orders
    - Real-time account balance
    - Historical candle data (OHLCV)

    Documentation: https://docs.kraken.com/rest/
    Python wrapper: https://github.com/veox/python3-krakenex
    """

    # HTTP timeout for Kraken API calls (in seconds)
    # This prevents indefinite hanging if the API is slow or unresponsive
    # 12 seconds is sufficient as Kraken normally responds in 1-5 seconds
    API_TIMEOUT_SECONDS = 12

    # Class-level flag to track if detailed permission error instructions have been logged
    # This prevents spamming the logs with duplicate permission error messages
    # The detailed instructions are logged ONCE GLOBALLY (not once per account)
    # because the fix instructions are the same for all accounts
    # Thread-safe: uses lock for concurrent access protection
    _permission_error_details_logged = False
    _permission_errors_lock = threading.Lock()

    # Class-level set to track accounts that have had permission errors
    # This prevents retrying connections for accounts with permission errors
    # Permission errors require user action (fixing API key permissions) and cannot
    # be resolved by retrying. Thread-safe: uses same lock as _permission_error_details_logged
    _permission_failed_accounts = set()

    # ── Live-instance registry (weakrefs) ─────────────────────────────────────
    # Used by _on_kraken_nonce_quarantine() and clear_kraken_broker_quarantine()
    # to update per-instance quarantine state on all live KrakenBroker objects
    # without requiring a shared dict or a global reference.
    _live_instances: "ClassVar[List[weakref.ref]]" = []
    _instances_lock: "ClassVar[threading.Lock]" = threading.Lock()

    @classmethod
    def _register_instance(cls, instance: "KrakenBroker") -> None:
        """Register a new instance and prune stale weakrefs."""
        import weakref as _wr
        with cls._instances_lock:
            # Prune dead refs before appending so the list never grows unboundedly.
            cls._live_instances = [r for r in cls._live_instances if r() is not None]
            cls._live_instances.append(_wr.ref(instance))

    @classmethod
    def _iter_live(cls) -> "List[KrakenBroker]":
        """Return a snapshot list of all currently alive KrakenBroker instances."""
        with cls._instances_lock:
            live = [r() for r in cls._live_instances]
        return [b for b in live if b is not None]

    def __init__(self, account_type: AccountType = AccountType.PLATFORM, user_id: Optional[str] = None):
        """
        Initialize Kraken broker with account type support.

        Args:
            account_type: PLATFORM for Nija system account, USER for individual user accounts
            user_id: User ID for USER account_type (e.g., 'daivon_frazier')

        Raises:
            ValueError: If account_type is USER but user_id is not provided
        """
        super().__init__(BrokerType.KRAKEN, account_type=account_type, user_id=user_id)

        # Register this instance in the class-level live-instance registry so
        # quarantine callbacks can reach every KrakenBroker in the process.
        KrakenBroker._register_instance(self)

        # Validate that USER account_type has user_id
        if account_type == AccountType.USER and not user_id:
            raise ValueError("USER account_type requires user_id parameter")

        self.api = None
        self.kraken_api = None

        # Balance tracking for fail-closed behavior (Fix 3)
        # When balance fetch fails, preserve last known balance instead of returning 0
        self._last_known_balance = None  # Last successful balance fetch
        self._balance_last_updated = None  # Timestamp of last successful balance fetch (Jan 24, 2026)
        self._balance_fetch_errors = 0   # Count of consecutive errors
        self._is_available = True        # Broker availability flag

        # FIX 2: EXIT-ONLY mode when balance is below minimum (Jan 20, 2026)
        # Allows emergency sells even when account is too small for new entries
        self.exit_only_mode = False

        # FIX #2: Balance cache and health status for Kraken
        # Cache balance after successful fetch and track health
        self.balance_cache = {}  # Structure: {"kraken": balance_value}
        self.kraken_health = "UNKNOWN"  # Status: "OK", "ERROR", or "UNKNOWN"

        # CRITICAL FIX (Jan 17, 2026): Monotonic nonce with API call serialization
        #
        # Nonce tracking for guaranteeing strict monotonic increase
        # This prevents "Invalid nonce" errors from rapid consecutive requests
        #
        # Research findings from Kraken API documentation and testing:
        # - Kraken REMEMBERS the last nonce it saw for each API key (persists 60+ seconds)
        # - Kraken expects nonces to be NEAR CURRENT TIME (not far in the future)
        # - The strict monotonic counter prevents collisions even with current time
        # - Nonces should be based on current UNIX timestamp (Kraken's best practice)
        #
        # Why 0-5 seconds is CORRECT:
        # - Aligns with Kraken's expectations (nonces near current time)
        # - Strict monotonic counter prevents all collisions within a session
        # - Small jitter (0-5s) prevents multi-instance collisions
        # - Error recovery uses 60-second immediate jump when nonce errors occur
        #
        # Why 10-20 seconds FAILS:
        # - Nonces too far in the future may exceed Kraken's acceptable window
        # - Causes "Invalid nonce" errors on first connection attempt
        # - Each retry wastes 30-60 seconds before eventual success
        #
        # Why very large offsets (180-240s) FAIL:
        # - Definitely exceeds Kraken's acceptable forward time window
        # - Kraken rejects nonces too far in the future
        #
        # Session Restart Handling:
        # - The strict monotonic counter already handles rapid restarts
        # - If current time hasn't advanced enough, counter increments by 1
        # - This guarantees each nonce is unique and increasing
        # - No large forward offset needed for restart protection
        #
        # Set identifier for logging (must be set BEFORE nonce initialization)
        if account_type == AccountType.PLATFORM:
            self.account_identifier = "PLATFORM"
        else:
            self.account_identifier = f"USER:{user_id}" if user_id else "USER:unknown"

        # ONE global source of nonces for all accounts and threads — no per-instance setup needed.
        logger.debug(f"   ✅ Using GLOBAL KrakenNonceManager for {self.account_identifier}")

        # Instance-level reference to the shared nonce manager singleton.
        # Populated during connect() from get_global_nonce_manager().
        self.nonce_manager = None
        self._kraken_private_call_nonce = None

        # CRITICAL FIX: API call serialization to prevent simultaneous Kraken calls
        # Problem: Multiple threads can call Kraken API simultaneously, causing nonce collisions
        # Solution: Serialize all private API calls through a lock
        # - This ensures only ONE Kraken private API call happens at a time per account
        # - Public API calls don't need nonces and are not serialized
        # - Lock is per-instance, so PLATFORM and USER accounts can still call in parallel
        self._api_call_lock = threading.Lock()

        # Timestamp of last API call for rate limiting
        # Ensures minimum delay between consecutive Kraken API calls
        # CRITICAL FIX (Jan 18, 2026): Increased from 200ms to 1000ms to prevent nonce errors
        # The short 200ms interval was causing "Invalid nonce" errors when balance was checked
        # immediately after connection test. Kraken's API needs more time between requests.
        #
        # NEW (Jan 23, 2026): Per-category rate limiting with separate entry/exit budgets
        # Track last call time per API category for fine-grained rate control
        self._last_api_call_time = 0.0
        self._min_call_interval = 1.0  # 1000ms (1 second) minimum between calls (fallback)
        self._last_call_by_category = {}  # Per-category call tracking: {category: timestamp}

        # Kraken rate profile configuration
        # Will be set during connect() based on account balance
        self._kraken_rate_mode = None  # KrakenRateMode enum
        self._kraken_rate_profile = None  # Rate profile dict

        # Instance-level product list cache (avoids repeated get_tradable_asset_pairs() calls)
        self._kraken_products_cache: list = []
        self._kraken_products_cache_time: float = 0.0
        self._kraken_products_cache_ttl: float = 4 * 3600  # 4-hour TTL

        # Initialize position tracker for profit-based exits
        # 🔒 CAPITAL PROTECTION: Position tracker is MANDATORY - no silent fallback
        try:
            from position_tracker import PositionTracker
            self.position_tracker = PositionTracker(storage_file="data/positions.json")
            logger.info("✅ Position tracker initialized for profit-based exits")
        except Exception as e:
            logger.error(f"❌ CAPITAL PROTECTION: Position tracker initialization FAILED: {e}")
            logger.error("❌ Position tracker is MANDATORY for capital protection - cannot proceed")
            raise RuntimeError(f"MANDATORY position_tracker initialization failed: {e}")

        # In-memory permanent cache for entry prices fetched from Kraken trade history.
        # Once fetched successfully the price is not re-fetched until the position
        # changes, eliminating redundant API calls.
        self._entry_price_cache: dict = {}
        self._entry_price_cache_lock = threading.Lock()

        # Bulk entry-price result cache — avoids re-fetching TradesHistory on
        # every adoption cycle when positions haven't changed.
        # Populated by get_bulk_entry_prices(); expires after _BULK_PRICE_CACHE_TTL_SECONDS.
        self._bulk_entry_prices_cache: Dict[str, float] = {}
        self._bulk_entry_prices_cache_time: Optional[float] = None

        # Kraken balance cache TTL — get_account_balance() returns the in-memory
        # value without an API call when the cache is younger than this value.
        self._kraken_balance_cache_ttl: int = _KRAKEN_BALANCE_CACHE_TTL_SECONDS

        # Short-lived price cache for get_current_price().
        # Stores {symbol: {"price": float, "ts": float}} where ts = time.monotonic().
        # Used as a fallback when a live ticker fetch times out — if the cached
        # price is ≤10 s old it is returned so the scan loop is never blocked.
        self._price_cache: dict = {}
        self._price_cache_lock = threading.Lock()

        # CONNECTION STABILITY: Initialize per-broker watchdog and HTTP pool manager
        # Mirrors the CoinbaseBroker pattern so Kraken connections benefit from the
        # same keep-alive / connection-reuse infrastructure.
        if CONNECTION_STABILITY_AVAILABLE:
            _cm_key = f"kraken_{account_type.value}"
            if user_id:
                _cm_key = f"{_cm_key}_{user_id}"
            self._connection_stability_manager = get_connection_stability_manager(_cm_key)
            logger.info("✅ ConnectionStabilityManager attached to KrakenBroker")
        else:
            self._connection_stability_manager = None

        # Guard flag — set to True after the first successful handshake and nonce
        # stabilisation so that subsequent polling / retry calls skip the full
        # connection routine and return immediately.
        # Note: for PLATFORM accounts the guard is the module-level
        # ``_KRAKEN_STARTUP_FSM.is_connected``; this flag is used only by USER
        # accounts which have their own independent connection lifecycles.
        self._connection_already_complete: bool = False

    def _initialize_kraken_market_data(self):
        """
        Initialize Kraken market data for dynamic minimum volumes.

        This fetches trading pair information from Kraken API and caches it.
        Called after successful connection to ensure API is available.
        """
        try:
            from bot.kraken_market_data import get_kraken_market_data  # type: ignore[import]
            market_data = get_kraken_market_data()
            if market_data.fetch_and_cache(self.kraken_api):
                pair_count = len(market_data.get_all_pairs())
                logger.info(f"   ✅ Market data loaded: {pair_count} trading pairs with minimum volumes")
                return True
            else:
                logger.debug("   Market data will use fallback to static minimums")
                return False
        except ImportError:
            logger.debug("   Market data module not available, using static minimums")
            return False
        except Exception as e:
            logger.warning(f"   ⚠️  Could not load market data: {e}")
            logger.warning("   Will use static minimum volumes as fallback")
            return False

    def _kraken_private_call(self, method: str, params: Optional[Dict] = None, category: Optional['KrakenAPICategory'] = None):
        """
        CRITICAL: Serialized wrapper for Kraken private API calls.

        This method ensures:
        1. Only ONE private API call happens at a time (prevents nonce collisions)
        2. Category-specific rate limiting (separate budgets for entry/exit/monitoring)
        3. Thread-safe execution using locks
        4. GLOBAL serialization across PLATFORM + ALL USERS (Option B)

        Problem solved:
        - Multiple threads calling Kraken API simultaneously with same nonce
        - Rapid consecutive calls generating duplicate nonces
        - Race conditions in nonce generation
        - Nonce collisions between PLATFORM and USER accounts
        - Different API budgets for entry vs exit vs monitoring operations

        Args:
            method: Kraken API method name (e.g., 'Balance', 'AddOrder')
            params: Optional parameters dict for the API call
            category: Optional KrakenAPICategory to override auto-detection

        Returns:
            API response dict

        Raises:
            Exception: If API call fails or self.api is not initialized
        """
        if not self.api:
            raise Exception("Kraken API not initialized - call connect() first")

        # Determine API category for rate limiting
        if category is None and KrakenAPICategory is not None:
            # Auto-detect category from method name
            category = get_category_for_method(method) if get_category_for_method else KrakenAPICategory.MONITORING

        # Use GLOBAL API lock to serialize calls across ALL accounts (Option B)
        # This ensures only ONE Kraken API call happens at a time across PLATFORM + ALL USERS
        if get_kraken_api_lock is not None:
            global_lock = get_kraken_api_lock()
        else:
            global_lock = self._api_call_lock  # Fallback to per-account lock

        # Respect nonce-triggered trading pause BEFORE acquiring the global lock.
        # Waiting inside the lock would serialize ALL accounts for up to 65 s,
        # blocking every connected user account even if their own nonces are fine.
        # By waiting here (lock-free) each account waits independently and only
        # acquires the global lock once it is safe to proceed.
        if is_nonce_trading_paused is not None and is_nonce_trading_paused():
            remaining = get_nonce_pause_remaining() if get_nonce_pause_remaining is not None else 0.0
            raise NoncePauseActive(
                f"Nonce trading pause active ({remaining:.0f}s remaining) — "
                "skipping cycle, will retry next scan"
            )

        # Serialize API calls - only one call at a time across ALL accounts
        with global_lock:
            # Enforce minimum delay between calls (per-category tracking)
            with self._api_call_lock:
                current_time = time.time()

                # Get category-specific rate limit or fallback to default
                if category and self._kraken_rate_profile and calculate_min_interval:
                    # Use category-specific rate limit from profile
                    min_interval = calculate_min_interval(category, self._kraken_rate_mode)
                    # Extract category key safely - check if it's an enum first
                    if KrakenAPICategory and isinstance(category, type(KrakenAPICategory.ENTRY)):
                        category_key = category.value
                    else:
                        category_key = str(category)
                    last_call = self._last_call_by_category.get(category_key, 0)

                    logger.debug(f"   📊 Rate limit for {method} ({category_key}): {min_interval:.1f}s")
                else:
                    # Fallback to global rate limit
                    min_interval = self._min_call_interval
                    last_call = self._last_api_call_time
                    category_key = 'global'

                time_since_last_call = current_time - last_call

                if time_since_last_call < min_interval:
                    # Sleep to maintain minimum interval
                    sleep_time = min_interval - time_since_last_call
                    logger.debug(f"   🛡️  Rate limiting ({category_key}): sleeping {sleep_time*1000:.0f}ms between Kraken calls")
                    time.sleep(sleep_time)

                # Update last call time for this category
                if category and self._kraken_rate_profile:
                    self._last_call_by_category[category_key] = time.time()

                # Also update global last call time
                self._last_api_call_time = time.time()

            # Nonce is generated inside krakenex's query_private() via our
            # _nonce_monotonic override (self.api._nonce = _nonce_monotonic).
            # Do NOT pre-stamp params["nonce"] here — query_private always
            # overwrites data['nonce'] = self._nonce() before signing, so any
            # value set here would be discarded and would only waste a nonce
            # counter increment.
            if params is None:
                params = {}

            # Jitter delay: 50–150 ms per call — prevents burst calls that cause
            # nonce-ordering issues on Kraken's servers.
            time.sleep(random.uniform(_KRAKEN_PRIVATE_CALL_SPACING_MIN_S, _KRAKEN_PRIVATE_CALL_SPACING_MAX_S))

            try:
                # Suppress pykrakenapi's print() statements that flood the console
                with suppress_pykrakenapi_prints():
                    result = self.api.query_private(method, params)
            finally:
                self.nonce_manager.end_request()

            return result

    def _kraken_api_call(self, method: str, params: Optional[Dict] = None, category: Optional['KrakenAPICategory'] = None):
        """
        Compatibility wrapper for _kraken_private_call().

        This method provides compatibility with code that expects _kraken_api_call()
        (like KrakenOrderCleanup) while delegating to the actual implementation
        in _kraken_private_call().

        Args:
            method: Kraken API method name (e.g., 'Balance', 'OpenOrders')
            params: Optional parameters dict for the API call
            category: Optional KrakenAPICategory for rate limiting. If None, the category
                     is auto-detected by _kraken_private_call based on the method name.

        Returns:
            API response dict
        """
        return self._kraken_private_call(method, params, category)

    def _test_connection(self, retries: int = 5) -> bool:
        """
        Test Kraken connectivity with retry logic.

        Calls the 'Balance' endpoint up to *retries* times.  Returns True on
        the first success.  Uses a fixed 3-second delay between retries — no
        nonce resets or forward jumps are applied here.
        """
        balance_category = KrakenAPICategory.MONITORING if KrakenAPICategory is not None else None
        for attempt in range(1, retries + 1):
            try:
                result = self._kraken_private_call("Balance", {}, category=balance_category)
                if result and "result" in result:
                    logger.info(
                        "✅ Kraken connection test successful on attempt %d (%s)",
                        attempt,
                        self.account_identifier,
                    )
                    return True
                # API returned an error dict rather than raising — treat as failure
                error_msgs = ", ".join(result.get("error", [])) if result else "empty response"
                raise Exception(f"API error: {error_msgs}")
            except Exception as exc:
                logger.warning(
                    "⚠️  Kraken connection test attempt %d/%d failed (%s): %s",
                    attempt,
                    retries,
                    self.account_identifier,
                    exc,
                )
                if attempt < retries:
                    time.sleep(3)
        raise RuntimeError(
            f"❌ Kraken connection test failed after {retries} attempts ({self.account_identifier})"
        )

    def connect(self) -> bool:
        """
        Connect to Kraken Pro API with retry logic.

        Uses different credentials based on account_type:
        - MASTER: KRAKEN_PLATFORM_API_KEY / KRAKEN_PLATFORM_API_SECRET
        - USER: KRAKEN_USER_{user_id}_API_KEY / KRAKEN_USER_{user_id}_API_SECRET

        Returns:
            bool: True if connected successfully
        """
        # Skip the full connection routine when a prior successful handshake
        # has already been recorded.  For PLATFORM accounts the authoritative
        # guard is the FSM (event = truth); for USER accounts the per-instance
        # bool is sufficient.
        _label = "PLATFORM" if self.account_type == AccountType.PLATFORM else f"USER:{self.user_id}"
        _already_done = (
            _KRAKEN_STARTUP_FSM.is_connected
            if self.account_type == AccountType.PLATFORM
            else self._connection_already_complete
        )
        if _already_done:
            logger.debug(f"[KrakenBroker:{_label}] Connection already established — skipping reconnect routine")
            return True

        # ── PLATFORM-FIRST GATE (USER accounts only) ─────────────────────────
        # Kraken is extremely sensitive to clock drift and nonce ordering.
        # The PLATFORM account must connect and stabilise its nonce before any
        # USER account begins its own connection handshake.  Concurrent nonce
        # windows from multiple API keys are the #1 source of "EAPI:Invalid nonce"
        # errors on multi-account deployments.
        if self.account_type == AccountType.USER:
            if not _KRAKEN_STARTUP_FSM.is_connected:
                if _USER_PLATFORM_WAIT_S is None:
                    logger.info(
                        "⏳ USER %s waiting indefinitely for PLATFORM Kraken to connect first …",
                        self.user_id,
                    )
                else:
                    logger.info(
                        "⏳ USER %s waiting for PLATFORM Kraken to connect first "
                        "(up to %d s) …",
                        self.user_id, _USER_PLATFORM_WAIT_S,
                    )
                ready = _KRAKEN_STARTUP_FSM.wait_connected(
                    timeout=float(_USER_PLATFORM_WAIT_S) if _USER_PLATFORM_WAIT_S is not None else None
                )
                if not ready:
                    if _KRAKEN_STARTUP_FSM.is_failed:
                        logger.error(
                            "⛔ USER %s: PLATFORM Kraken connection failed permanently. "
                            "Refusing USER connection to protect nonce integrity. "
                            "Fix platform credentials/clock, then restart the bot.",
                            self.user_id,
                        )
                    else:
                        logger.error(
                            "⛔ USER %s: PLATFORM Kraken did not connect within %d s. "
                            "Refusing USER connection to protect nonce integrity. "
                            "Fix platform credentials/clock, then restart the bot.",
                            self.user_id, _USER_PLATFORM_WAIT_S,
                        )
                    self.connected = False
                    return False
                logger.info("✅ PLATFORM ready — proceeding with USER %s connection.", self.user_id)

        try:
            import krakenex
            from pykrakenapi import KrakenAPI
            import time

            # Suppress verbose logging from Kraken SDK libraries
            # This prevents "attempt: XXX | ['EQuery:...']" messages from flooding the logs
            kraken_logger = logging.getLogger('krakenex')
            kraken_logger.setLevel(logging.WARNING)
            pykraken_logger = logging.getLogger('pykrakenapi')
            pykraken_logger.setLevel(logging.WARNING)

            # Get credentials based on account type
            # Enhanced credential detection to identify "set but invalid" variables
            if self.account_type == AccountType.PLATFORM:
                key_name = "KRAKEN_PLATFORM_API_KEY"
                secret_name = "KRAKEN_PLATFORM_API_SECRET"
                api_key_raw = os.getenv(key_name, "")
                api_secret_raw = os.getenv(secret_name, "")

                # Log when master credentials are found
                if api_key_raw and api_secret_raw:
                    logger.info("   ✅ Using KRAKEN_PLATFORM_API_KEY and KRAKEN_PLATFORM_API_SECRET for platform account")

                # Fallback to legacy credentials if master credentials not set
                # This provides backward compatibility for deployments using KRAKEN_API_KEY
                if not api_key_raw:
                    legacy_key = os.getenv("KRAKEN_API_KEY", "")
                    if legacy_key:
                        api_key_raw = legacy_key
                        key_name = "KRAKEN_API_KEY (legacy)"
                        logger.info("   Using legacy KRAKEN_API_KEY for platform account")

                if not api_secret_raw:
                    legacy_secret = os.getenv("KRAKEN_API_SECRET", "")
                    if legacy_secret:
                        api_secret_raw = legacy_secret
                        secret_name = "KRAKEN_API_SECRET (legacy)"
                        logger.info("   Using legacy KRAKEN_API_SECRET for platform account")

                api_key = api_key_raw.strip()
                api_secret = api_secret_raw.strip()
                cred_label = "PLATFORM"
            else:
                # User account - construct env var name from user_id
                # Convert user_id to uppercase for env var
                # For user_id like 'daivon_frazier', extracts 'DAIVON' for KRAKEN_USER_DAIVON_API_KEY
                # For user_id like 'john', uses 'JOHN' for KRAKEN_USER_JOHN_API_KEY
                user_env_name = self.user_id.split('_')[0].upper() if '_' in self.user_id else self.user_id.upper()
                key_name = f"KRAKEN_USER_{user_env_name}_API_KEY"
                secret_name = f"KRAKEN_USER_{user_env_name}_API_SECRET"
                api_key_raw = os.getenv(key_name, "")
                api_secret_raw = os.getenv(secret_name, "")
                # Fallback: also try the full user_id in uppercase
                # e.g. KRAKEN_USER_TANIA_GILBERT_API_KEY for user_id='tania_gilbert'
                # This fixes the contradiction where PAL discovers credentials via the full
                # env var name but KrakenBroker only looks at the first word of user_id.
                if not api_key_raw or not api_secret_raw:
                    full_env_name = self.user_id.upper()
                    if full_env_name != user_env_name:
                        full_key_name = f"KRAKEN_USER_{full_env_name}_API_KEY"
                        full_secret_name = f"KRAKEN_USER_{full_env_name}_API_SECRET"
                        if not api_key_raw:
                            api_key_raw = os.getenv(full_key_name, "")
                            if api_key_raw:
                                key_name = full_key_name
                        if not api_secret_raw:
                            api_secret_raw = os.getenv(full_secret_name, "")
                            if api_secret_raw:
                                secret_name = full_secret_name
                api_key = api_key_raw.strip()
                api_secret = api_secret_raw.strip()
                cred_label = f"USER:{self.user_id}"

            # Enhanced validation: detect if variables are set but contain only whitespace
            key_is_set = api_key_raw != ""
            secret_is_set = api_secret_raw != ""
            key_valid_after_strip = bool(api_key)
            secret_valid_after_strip = bool(api_secret)

            # Check for malformed credentials (set but empty after stripping)
            if (key_is_set and not key_valid_after_strip) or (secret_is_set and not secret_valid_after_strip):
                # Mark that credentials were NOT properly configured (empty/whitespace = not configured)
                # This ensures the status display shows "NOT CONFIGURED" instead of "Connection failed"
                self.credentials_configured = False
                self.last_connection_error = "Credentials contain only whitespace"
                logger.warning(f"⚠️  Kraken credentials DETECTED but INVALID for {cred_label}")

                # Determine status messages for each credential
                key_status = 'SET but contains only whitespace/invisible characters' if (key_is_set and not key_valid_after_strip) else 'valid'
                secret_status = 'SET but contains only whitespace/invisible characters' if (secret_is_set and not secret_valid_after_strip) else 'valid'

                logger.warning(f"   {key_name}: {key_status}")
                logger.warning(f"   {secret_name}: {secret_status}")
                logger.warning("   🔧 FIX: Check your deployment platform (Railway/Render) environment variables:")
                logger.warning("      1. Remove any leading/trailing spaces or newlines from the values")
                logger.warning("      2. Ensure the values are not just whitespace characters")
                logger.warning("      3. Re-deploy after fixing the values")
                return False

            # Check for placeholder values (e.g. "your_kraken_api_key_here" from .env templates)
            key_is_placeholder = bool(api_key and _KRAKEN_PLACEHOLDER_RE.match(api_key))
            secret_is_placeholder = bool(api_secret and _KRAKEN_PLACEHOLDER_RE.match(api_secret))
            if key_is_placeholder or secret_is_placeholder:
                self.credentials_configured = False
                self.last_connection_error = "Credentials appear to be unfilled placeholder values"
                logger.warning(f"⚠️  Kraken credentials appear to be PLACEHOLDER VALUES for {cred_label}")
                if key_is_placeholder:
                    logger.warning(f"   {key_name}: '{api_key}' looks like a template placeholder")
                if secret_is_placeholder:
                    logger.warning(f"   {secret_name}: value looks like a template placeholder")
                logger.warning("   🔧 FIX: Replace the placeholder with your real Kraken Classic API credentials:")
                logger.warning("      1. Go to https://www.kraken.com/u/security/api")
                logger.warning("      2. Generate a Classic API key (NOT OAuth) with trading permissions")
                logger.warning("      3. Set KRAKEN_PLATFORM_API_KEY and KRAKEN_PLATFORM_API_SECRET")
                logger.warning("      4. Restart the bot")
                return False

            # SMART CACHE MANAGEMENT: If credentials exist NOW, clear any previous permission error cache
            # This allows users to fix their credentials/permissions and have the bot retry automatically
            # without requiring a full restart. The cache is meant to prevent retry loops during a single
            # session with the SAME bad credentials, not to permanently block an account.
            # NOTE: This must happen BEFORE the missing credentials check below, so that if credentials
            # are added after a previous failure, we clear the cache before discovering they're still missing.
            if api_key and api_secret:
                with KrakenBroker._permission_errors_lock:
                    if cred_label in KrakenBroker._permission_failed_accounts:
                        logger.info(f"🔄 Clearing previous permission error cache for {cred_label} - credentials now available")
                        logger.info(f"   Will retry connection with current credentials")
                        KrakenBroker._permission_failed_accounts.discard(cred_label)

            if not api_key or not api_secret:
                # Mark that credentials were not configured (not an error, just not set up)
                self.credentials_configured = False
                # Silently skip - Kraken is optional, no need for scary error messages
                logger.info(f"⚠️  Kraken credentials not configured for {cred_label} (skipping)")
                if self.account_type == AccountType.PLATFORM:
                    logger.info("   🔧 FIX #1 — To enable Kraken PLATFORM trading, set:")
                    logger.info("      KRAKEN_PLATFORM_API_KEY=<your-api-key>")
                    logger.info("      KRAKEN_PLATFORM_API_SECRET=<your-api-secret>")
                    logger.info("   OR use legacy credentials:")
                    logger.info("      KRAKEN_API_KEY=<your-api-key>")
                    logger.info("      KRAKEN_API_SECRET=<your-api-secret>")
                    logger.info("   🔧 FIX #3 — Must be Classic API key (NOT OAuth)")
                    logger.info("   📖 Get credentials: https://www.kraken.com/u/security/api")
                else:
                    # USER account - provide specific instructions
                    # Note: user_env_name is guaranteed to be defined from the else block above
                    logger.info(f"   🔧 FIX #1 — To enable Kraken USER trading for {self.user_id}, set:")
                    logger.info(f"      KRAKEN_USER_{user_env_name}_API_KEY=<your-api-key>")
                    logger.info(f"      KRAKEN_USER_{user_env_name}_API_SECRET=<your-api-secret>")
                    logger.info(f"   ⚠️  NOTE: {self.user_id} needs THEIR OWN Kraken account (not a sub-account)")
                    logger.info(f"   🔧 FIX #3 — Must be Classic API key (NOT OAuth)")
                    logger.info(f"   📖 Each user must create their own API key at: https://www.kraken.com/u/security/api")
                    logger.info("   📖 Setup guide: KRAKEN_QUICK_START.md")
                return False

            # Initialize Kraken API with custom nonce generator to fix "Invalid nonce" errors
            # CRITICAL FIX: Override default nonce generation to guarantee strict monotonic increase
            # The default krakenex nonce uses time.time() which has seconds precision and can
            # produce duplicate nonces if multiple requests happen in the same second.
            #
            # SOLUTION: Use milliseconds + tracking to ensure each nonce is strictly greater
            # than the previous one, even if requests happen in the same millisecond.
            self.api = krakenex.API(key=api_key, secret=api_secret)

            # CRITICAL FIX (Jan 17, 2026): Set timeout on HTTP requests to prevent hanging
            # krakenex doesn't set a default timeout, causing indefinite hangs if API is slow.
            # We use functools.partial to patch the session (standard pattern for krakenex).
            # Per-instance modification - no global state affected. Degrades gracefully if session changes.
            try:
                self.api.session.request = functools.partial(
                    self.api.session.request,
                    timeout=self.API_TIMEOUT_SECONDS
                )
                logger.debug(f"✅ HTTP timeout configured ({self.API_TIMEOUT_SECONDS}s) for {cred_label}")
            except AttributeError as e:
                # If session attribute doesn't exist, log warning but continue
                # This maintains backward compatibility if krakenex changes its internals
                logger.warning(f"⚠️  Could not configure HTTP timeout: {e}")

            # Configure HTTP keep-alive / connection reuse to prevent RemoteDisconnected errors.
            # Use ConnectionStabilityManager.apply_connection_pool() when available for richer
            # pool configuration (pool_connections=4, pool_maxsize=10, transport-level retries).
            # Falls back to a basic HTTPAdapter if the manager is not initialised.
            # pool_connections=4, pool_maxsize=10 chosen to match ConnectionPoolConfig defaults
            # in connection_stability_manager.py — enough headroom for concurrent balance checks
            # and order submissions without exhausting TCP resources.
            try:
                if self._connection_stability_manager is not None:
                    self._connection_stability_manager.apply_connection_pool(self.api.session)
                    logger.debug(f"✅ HTTP connection pool applied via ConnectionStabilityManager for {cred_label}")
                else:
                    import requests
                    from requests.adapters import HTTPAdapter

                    _kraken_adapter = HTTPAdapter(
                        pool_connections=4,   # Aligned with ConnectionPoolConfig defaults
                        pool_maxsize=10,      # Aligned with ConnectionPoolConfig defaults
                        max_retries=0,  # Retry logic is handled by our own retry loop
                    )
                    self.api.session.mount("https://", _kraken_adapter)
                    self.api.session.mount("http://", _kraken_adapter)
                    logger.debug(f"✅ HTTP keep-alive adapter configured for {cred_label} (prevents RemoteDisconnected)")
            except Exception as e:
                logger.debug(f"⚠️  Could not configure keep-alive adapter: {e}")

            # Mark that credentials were configured (we have API key and secret)
            self.credentials_configured = True

            # Install the single global nonce generator.
            # ONE source of nonces across every broker, account, and thread.
            self.nonce_manager = get_global_nonce_manager()
            self._kraken_private_call_nonce = self.nonce_manager.get_nonce

            def _nonce_monotonic() -> str:
                """Thread-safe ms nonce — single global counter for all accounts."""
                return str(get_kraken_nonce())

            # Replace the nonce generator
            # NOTE: This directly overrides the internal _nonce method of krakenex.API
            try:
                self.api._nonce = _nonce_monotonic
                if logger.isEnabledFor(logging.DEBUG):
                    _mgr = get_global_nonce_manager()
                    logger.debug(f"   Initial nonce (GLOBAL): {_mgr.get_last_nonce()} (peek only, counter not advanced)")
            except AttributeError as e:
                self.last_connection_error = f"Nonce generator override failed: {str(e)}"
                logger.error(f"❌ Failed to override krakenex nonce generator: {e}")
                logger.error("   This may indicate a version incompatibility with krakenex library")
                logger.error("   Please report this issue with your krakenex version")
                return False

            self.kraken_api = KrakenAPI(self.api)

            # ONE startup reset — sets nonce to now + 1 s so the first API call
            # lands safely ahead of any nonce Kraken may still hold from a
            # previous session.  This is the only place reset_to_safe_value()
            # is called proactively; subsequent resets are triggered only by
            # KrakenNonceManager.record_error() after 3 consecutive errors with
            # no active in-flight requests.
            get_global_nonce_manager().reset_to_safe_value()
            logger.debug(f"   🔄 Startup nonce reset complete for {cred_label}")


            # Startup delay before first Kraken API call.
            # A random jitter staggers simultaneous multi-account starts so they
            # do not all fire their first API call at the exact same millisecond.
            _startup_jitter = random.uniform(0, KRAKEN_STARTUP_DELAY_JITTER)
            _startup_total  = KRAKEN_STARTUP_DELAY_SECONDS + _startup_jitter
            logger.info(f"   ⏳ Waiting {_startup_total:.1f}s before Kraken connection test (jitter={_startup_jitter:.1f}s)...")
            time.sleep(_startup_total)
            logger.info(f"   ✅ Startup delay complete, testing Kraken connection...")

            # ── Nonce resync handshake ────────────────────────────────────────
            # Probe Kraken's server-side nonce floor BEFORE the main retry loop.
            # This resolves all three root-cause nonce failure scenarios:
            #
            #   1. Another process still running — cross-process lock detected;
            #      adaptive step is automatically larger to clear any gap.
            #   2. Kraken expecting a much higher nonce — ephemeral-filesystem
            #      restart (Railway/Heroku) loses state file; Kraken's floor is
            #      far ahead.  Probe jumps +adaptive_step until accepted.
            #   3. Clock slightly off — probe converges to the correct range even
            #      if NTP drift has pushed our nonces outside the ±1 s window.
            #
            # AdaptiveNonceOffsetEngine records each outcome (how many jump steps
            # were needed) and feeds an EMA so subsequent restarts land in range
            # on the very first probe attempt instead of iterating several times.
            if probe_and_resync_nonce is not None:
                _probe_cat = KrakenAPICategory.MONITORING if KrakenAPICategory is not None else None
                logger.info(f"   🔍 Nonce resync handshake: calibrating nonce to Kraken's server window ({cred_label})...")
                _probe_ok = probe_and_resync_nonce(
                    lambda: self._kraken_private_call("Balance", {}, category=_probe_cat),
                    step_ms=_NONCE_PROBE_STEP_MS,   # 0 = let AdaptiveOffsetEngine choose
                )
                if _probe_ok:
                    logger.info(f"   ✅ Nonce resync handshake complete for {cred_label}")
                else:
                    # Nonce desync could not be resolved in one server-sync recovery
                    # cycle.  This is a temporary resync issue, not a key-validity
                    # problem.  The bot will retry on the next connection attempt.
                    logger.error(
                        f"   ❌ Nonce resync handshake failed for {cred_label} — "
                        f"nonce desync unresolved.  Wait and retry, or restart with "
                        f"NIJA_FORCE_NONCE_RESYNC=1 if this persists."
                    )
                    return False

            # Test connection by fetching account balance.
            # Probe already calibrated the nonce — a single attempt is sufficient.
            # No retry loop: if it fails here the outer reconnect logic will retry.
            max_attempts = 1
            base_delay = 5.0        # exponential backoff for normal errors
            lockout_base_delay = 120.0  # 2 min per step for "Temporary lockout"
            last_error_was_lockout = False
            last_error_was_nonce = False

            for attempt in range(1, max_attempts + 1):
                try:
                    # Log connection attempt at INFO level so users can see progress
                    if attempt == 1:
                        logger.info("🔌 RECONNECT [%s] attempt %d/%d — connecting to Kraken…",
                                    cred_label, attempt, max_attempts)

                    if attempt > 1:
                        if last_error_was_lockout:
                            delay = lockout_base_delay * (attempt - 1)
                            logger.warning(
                                "🔄 RECONNECT [%s] attempt %d/%d in %.0fs (lockout backoff)",
                                cred_label, attempt, max_attempts, delay,
                            )
                        elif last_error_was_nonce:
                            delay = 5.0
                            logger.warning(
                                "🔄 RECONNECT [%s] attempt %d/%d in %.0fs (nonce recovery)",
                                cred_label, attempt, max_attempts, delay,
                            )
                        else:
                            delay = base_delay * (2 ** (attempt - 2))
                            logger.info(
                                "🔄 RECONNECT [%s] attempt %d/%d in %.0fs",
                                cred_label, attempt, max_attempts, delay,
                            )
                        time.sleep(delay)

                    # The _nonce_monotonic() function automatically handles nonce generation
                    # with guaranteed strict monotonic increase. No manual nonce refresh needed.
                    # It will be called automatically by krakenex when query_private() is invoked.
                    # CRITICAL: Use _kraken_private_call() wrapper to serialize API calls
                    # Use MONITORING category for balance checks (conservative rate limiting)
                    balance_category = KrakenAPICategory.MONITORING if KrakenAPICategory is not None else None
                    balance = self._kraken_private_call('Balance', category=balance_category)

                    if balance and 'error' in balance:
                        if balance['error']:
                            error_msgs = ', '.join(balance['error'])

                            # Check if it's a permission error (EGeneral:Permission denied, EAPI:Invalid permission, etc.)
                            is_permission_error = any(keyword in error_msgs.lower() for keyword in [
                                'permission denied', 'egeneral:permission',
                                'eapi:invalid permission', 'insufficient permission'
                            ])

                            if is_permission_error:
                                self.last_connection_error = f"Permission denied: {error_msgs}"
                                logger.error(f"❌ Kraken connection test failed ({cred_label}): {error_msgs}")

                                # Track this account as failed due to permission error for this session
                                # The cache will be automatically cleared if valid credentials are detected later
                                # Thread-safe update using class-level lock
                                with KrakenBroker._permission_errors_lock:
                                    KrakenBroker._permission_failed_accounts.add(cred_label)

                                    # Only log detailed permission error instructions ONCE GLOBALLY
                                    # After the first account with permission error, subsequent accounts
                                    # get a brief reference message instead of full instructions
                                    # This prevents log spam when multiple users have permission errors
                                    if not KrakenBroker._permission_error_details_logged:
                                        KrakenBroker._permission_error_details_logged = True
                                        should_log_details = True
                                    else:
                                        should_log_details = False

                                if should_log_details:
                                    logger.error("   ⚠️  API KEY PERMISSION ERROR")
                                    logger.error("   Your Kraken API key does not have the required permissions.")
                                    logger.warning("")
                                    logger.warning("   🔧 FIX #1 — Ensure you're using KRAKEN PLATFORM keys")
                                    logger.warning("      Environment variables: KRAKEN_PLATFORM_API_KEY / KRAKEN_PLATFORM_API_SECRET")
                                    logger.warning("      (Not legacy KRAKEN_API_KEY)")
                                    logger.warning("")
                                    logger.warning("   🔧 FIX #2 — Fix Kraken API permissions (mandatory):")
                                    logger.warning("   1. Go to https://www.kraken.com/u/security/api")
                                    logger.warning("   2. Find your API key and edit its permissions")
                                    logger.warning("   3. Enable these permissions:")
                                    logger.warning("      ✅ Query Funds (required to check balance)")
                                    logger.warning("      ✅ Query Open Orders & Trades (required for position tracking)")
                                    logger.warning("      ✅ Query Closed Orders & Trades (required for trade history)")
                                    logger.warning("      ✅ Create & Modify Orders (required to place trades)")
                                    logger.warning("      ✅ Cancel/Close Orders (required for stop losses)")
                                    logger.warning("   4. Save changes and restart the bot")
                                    logger.warning("")
                                    logger.warning("   🔧 FIX #3 — Confirm Kraken key type:")
                                    logger.warning("      ✅ Must be Classic API key (NOT OAuth or App key)")
                                    logger.warning("      To create: Settings > API > Generate New Key")
                                    logger.warning("")
                                    logger.warning("   🔧 FIX #4 — Nonce handling (auto-fixed):")
                                    logger.warning("      ✅ Bot uses microsecond-precision nonces (monotonically increasing)")
                                    logger.warning("      ✅ If nonce errors persist, check system clock (use NTP sync)")
                                    logger.warning("")
                                    logger.warning("   For security, do NOT enable 'Withdraw Funds' permission")
                                    logger.warning("   📖 See KRAKEN_PERMISSION_ERROR_FIX.md for detailed instructions")
                                    # Flush handlers to ensure all permission error messages appear together
                                    # CRITICAL: Flush root 'nija' logger handlers, not child logger (which has no handlers)
                                    for handler in _root_logger.handlers:
                                        handler.flush()
                                else:
                                    logger.error("   ⚠️  API KEY PERMISSION ERROR")
                                    logger.error("   Your Kraken API key does not have the required permissions.")
                                    logger.error("   🔧 FIX: Must use Classic API key with Query/Create/Cancel Orders permissions")
                                    logger.error("   https://www.kraken.com/u/security/api")
                                    logger.error("   📖 See KRAKEN_PERMISSION_ERROR_FIX.md for detailed instructions")

                                return False

                            # Check if error is retryable (rate limiting, network issues, 403 errors, nonce errors, lockout, etc.)
                            # CRITICAL: Include "invalid nonce" and "lockout" as retryable errors
                            # Invalid nonce errors can happen due to:
                            # - Clock drift/NTP adjustments
                            # - Rapid consecutive requests
                            # - Previous failed requests leaving the nonce counter in inconsistent state
                            # The microsecond-based nonce generator should fix this, but we still retry
                            # to handle edge cases and transient issues.
                            #
                            # "Temporary lockout" errors require special handling with longer delays (minutes, not seconds)
                            # "Invalid nonce" errors require moderate delays (30s increments) and aggressive nonce jumps (10x)
                            is_lockout_error = 'lockout' in error_msgs.lower()
                            # Be specific about nonce errors - match exact Kraken error messages
                            is_nonce_error = any(keyword in error_msgs.lower() for keyword in [
                                'invalid nonce', 'eapi:invalid nonce', 'nonce window'
                            ])
                            is_retryable = is_lockout_error or is_nonce_error or any(keyword in error_msgs.lower() for keyword in [
                                'timeout', 'connection', 'network', 'rate limit',
                                'too many requests', 'service unavailable',
                                '503', '504', '429', '403', 'forbidden',
                                'too many errors', 'temporary', 'try again'
                            ])

                            if is_retryable and attempt < max_attempts:
                                # Set flags for special error types to use appropriate delays on next retry
                                last_error_was_lockout = is_lockout_error
                                last_error_was_nonce = is_nonce_error and not is_lockout_error  # Lockout takes precedence

                                if is_nonce_error:
                                    if get_global_nonce_manager is not None:
                                        get_global_nonce_manager().record_error()

                                # ── Structured logging for nonce / auth / reconnect ───────────
                                if is_nonce_error:
                                    # Always warn on nonce errors — they indicate a real sync issue
                                    _nonce_state = ""
                                    if get_global_nonce_manager is not None:
                                        try:
                                            _mgr = get_global_nonce_manager()
                                            _nonce_state = (
                                                f" nonce={_mgr.get_last_nonce()}"
                                                f" nuclear_resets={_mgr.nuclear_reset_count}"
                                            )
                                        except Exception:
                                            pass
                                    logger.warning(
                                        "⚠️  NONCE ERROR [%s] attempt %d/%d: %s%s — "
                                        "nonce manager will rebuild on next call",
                                        cred_label, attempt, max_attempts,
                                        error_msgs, _nonce_state,
                                    )
                                elif is_lockout_error:
                                    logger.warning(
                                        "⚠️  AUTH/LOCKOUT [%s] attempt %d/%d: %s",
                                        cred_label, attempt, max_attempts, error_msgs,
                                    )
                                else:
                                    logger.info(
                                        "🔄 RECONNECT [%s] attempt %d/%d retrying: %s",
                                        cred_label, attempt, max_attempts, error_msgs,
                                    )
                                continue
                            else:
                                self.last_connection_error = error_msgs
                                if is_nonce_error:
                                    _nonce_state = ""
                                    if get_global_nonce_manager is not None:
                                        try:
                                            _mgr = get_global_nonce_manager()
                                            _nonce_state = (
                                                f" (nonce={_mgr.get_last_nonce()}"
                                                f", nuclear_resets={_mgr.nuclear_reset_count})"
                                            )
                                        except Exception:
                                            pass
                                    logger.error(
                                        "❌ NONCE ERROR [%s] all %d attempts exhausted: %s%s",
                                        cred_label, max_attempts, error_msgs, _nonce_state,
                                    )
                                elif is_lockout_error:
                                    # Do not include raw credential variable names — log account label only
                                    logger.error(
                                        "❌ AUTH FAILURE [%s]: %s",
                                        cred_label, error_msgs,
                                    )
                                else:
                                    logger.error(
                                        "❌ Kraken connection test failed [%s]: %s",
                                        cred_label, error_msgs,
                                    )
                                return False

                    if balance and 'result' in balance:
                        self.connected = True

                        # Record success — resets the consecutive-error counter
                        if get_global_nonce_manager is not None:
                            get_global_nonce_manager().record_success()

                        if attempt > 1:
                            logger.info(f"✅ Connected to Kraken Pro API ({cred_label}) (succeeded on attempt {attempt})")

                        logger.info("=" * 70)
                        # Display "PLATFORM KRAKEN CONNECTED" for platform accounts, "USER KRAKEN CONNECTED" for users
                        if cred_label == "PLATFORM":
                            logger.info("✅ PLATFORM KRAKEN CONNECTED")
                        else:
                            logger.info(f"✅ KRAKEN CONNECTED ({cred_label})")
                        logger.info("=" * 70)

                        # Log USD/USDT balance
                        result = balance.get('result', {})
                        usd_balance = float(result.get('ZUSD', 0))  # Kraken uses ZUSD for USD
                        usdt_balance = float(result.get('USDT', 0))

                        total = usd_balance + usdt_balance

                        # FIX (Jan 23, 2026): Calculate held funds to get total account equity
                        # This ensures EXIT-ONLY mode is based on total funds (available + held)
                        # not just available balance, matching the logic in get_account_balance()
                        # Note: get_account_balance() also fetches TradeBalance to calculate held funds
                        balance_category = KrakenAPICategory.MONITORING if KrakenAPICategory is not None else None
                        trade_balance = self._kraken_private_call('TradeBalance', {'asset': 'ZUSD'}, category=balance_category)
                        held_amount = 0.0

                        if trade_balance and 'result' in trade_balance:
                            tb_result = trade_balance['result']
                            # equivalent_balance = total balance including held orders
                            # trade_balance_free = free margin available
                            # held = equivalent_balance - trade_balance_free
                            equivalent_balance = float(tb_result.get('eb', 0))
                            trade_balance_free = float(tb_result.get('tb', 0))
                            held_amount = equivalent_balance - trade_balance_free if equivalent_balance > trade_balance_free else 0.0

                        # Calculate total funds (available + held) for minimum balance check
                        total_funds = total + held_amount

                        # CRITICAL FIX: Cache the balance fetched during connection
                        # This prevents redundant API calls when get_account_balance() is called immediately after connect()
                        # Reduces startup time and prevents potential rate limiting issues
                        self._last_known_balance = total_funds
                        self._balance_last_updated = time.time()
                        self.balance_cache["kraken"] = total_funds

                        logger.info(f"   Account: {self.account_identifier}")
                        logger.info(f"   USD Balance: ${usd_balance:.2f}")
                        logger.info(f"   USDT Balance: ${usdt_balance:.2f}")
                        logger.info(f"   Total Available: ${total:.2f}")
                        if held_amount > 0:
                            logger.info(f"   Held in Orders: ${held_amount:.2f}")
                            logger.info(f"   Total Funds: ${total_funds:.2f}")

                        # Initialize Kraken rate profile based on account balance (Jan 23, 2026)
                        # Separate entry/exit/monitoring API budgets for optimal performance
                        # Use total_funds for rate profile selection to match actual capital capacity
                        if get_kraken_rate_profile is not None and KrakenRateMode is not None:
                            # Auto-select rate mode based on account balance.
                            # MICRO_CAP = $20-$50  (30s entry / 60s monitoring — single position)
                            # SMALL_CAP  = $50-$500  (5s entry / 10s monitoring — multi-position)
                            # STANDARD   = $500-$1000
                            # AGGRESSIVE = $1000+
                            self._kraken_rate_profile = get_kraken_rate_profile(account_balance=total_funds)
                            self._kraken_rate_mode = (
                                KrakenRateMode.MICRO_CAP if total_funds < 50.0
                                else KrakenRateMode.SMALL_CAP if total_funds < 500.0
                                else KrakenRateMode.STANDARD if total_funds < 1000.0
                                else KrakenRateMode.AGGRESSIVE
                            )
                            logger.info(f"   📊 Rate Profile: {self._kraken_rate_profile['name']}")
                            logger.info(f"      Entry: {self._kraken_rate_profile['entry']['min_interval_seconds']:.1f}s interval")
                            logger.info(f"      Monitoring: {self._kraken_rate_profile['monitoring']['min_interval_seconds']:.1f}s interval")
                        else:
                            logger.debug(f"   ⚠️  Kraken rate profiles not available, using default rate limiting")

                        # Check minimum balance requirement for Kraken
                        # Kraken is PRIMARY engine for small accounts ($25+)
                        # FIX 2: FORCED EXIT OVERRIDES - Allow connection even when balance < minimum
                        # This enables emergency sells to close losing positions
                        # FIX (Jan 23, 2026): Use total_funds (available + held) for minimum check
                        if total_funds < KRAKEN_MINIMUM_BALANCE:
                            logger.warning("=" * 70)
                            logger.warning("⚠️ KRAKEN: Account balance below minimum for NEW ENTRIES")
                            logger.warning("=" * 70)
                            logger.warning(f"   Available balance: ${total:.2f}")
                            logger.warning(f"   Total funds (incl. held): ${total_funds:.2f}")
                            logger.warning(f"   Minimum for entries: ${KRAKEN_MINIMUM_BALANCE:.2f}")
                            logger.warning(f"   ")
                            logger.warning(f"   📋 Trading Mode: EXIT-ONLY")
                            logger.warning(f"      ✅ Can SELL (close positions)")
                            logger.warning(f"      ❌ Cannot BUY (new entries blocked)")
                            logger.warning(f"   ")
                            logger.warning(f"   💡 Solution: Fund account to at least ${KRAKEN_MINIMUM_BALANCE:.2f}")
                            logger.warning(f"      Kraken is the best choice for small accounts (4x lower fees)")
                            logger.warning(f"   ")
                            logger.warning(f"   ✅ Kraken connection maintained for emergency exits")
                            logger.warning("=" * 70)

                            # Mark as EXIT-ONLY mode (not fully disabled)
                            self.exit_only_mode = True
                            # Keep connected = True so sells can execute
                            self.connected = True
                        else:
                            # Normal mode - full trading allowed
                            self.exit_only_mode = False

                        logger.info("=" * 70)

                        # CRITICAL FIX (Jan 23, 2026): Initialize market data right after connection
                        # Fetch minimum volumes for all trading pairs to prevent order rejections
                        self._initialize_kraken_market_data()

                        # CRITICAL FIX (Jan 18, 2026): Add post-connection delay
                        # After successful connection test, wait before allowing next API call
                        # This prevents "Invalid nonce" when balance is checked immediately after
                        # The connection test already called Balance API, and rapid consecutive
                        # calls (even with 1s interval) can trigger nonce errors
                        # NOTE: time.sleep() blocking is INTENTIONAL - we want to pause execution
                        # to ensure proper timing between API calls. This is a synchronous operation
                        # during bot startup, not an async/event-driven context.
                        post_connection_delay = 10.0  # 10 seconds post-connection cooldown (increased from 2 s to allow nonce to settle)
                        logger.info(f"   ⏳ Post-connection cooldown: {post_connection_delay:.1f}s (prevents nonce errors)...")
                        time.sleep(post_connection_delay)
                        logger.debug(f"   ✅ Cooldown complete - ready for balance checks")

                        # CONNECTION STABILITY: Register broker and start watchdog
                        if self._connection_stability_manager is not None:
                            self._connection_stability_manager.register_broker(
                                broker=self,
                                reconnect_fn=self.connect,
                            )
                            self._connection_stability_manager.mark_connected()
                            self._connection_stability_manager.start_watchdog()

                        # Mark handshake as complete so future calls to connect()
                        # return immediately without re-running the full routine.
                        self._connection_already_complete = True

                        # For PLATFORM: one atomic FSM transition replaces the
                        # three-write race (_connection_already_complete bool +
                        # _platform_ready_flag bool + _PLATFORM_KRAKEN_READY event)
                        # that previously had a partial-state window between writes.
                        # event = truth: mark_connected() is the single authoritative write;
                        # all readers derive their answer from the FSM.
                        if self.account_type == AccountType.PLATFORM:
                            _KRAKEN_STARTUP_FSM.mark_connected()
                            logger.info(
                                "✅ PLATFORM Kraken connected — USER accounts may now connect."
                            )
                            # If the platform was previously quarantined due to nonce poisoning
                            # and has now successfully reconnected (implying a key rotation + resync
                            # completed), automatically lift the quarantine so new entries are
                            # re-enabled without requiring a full bot restart.
                            if _kraken_quarantine_active:
                                logger.warning(
                                    "🔓 PLATFORM Kraken reconnected while quarantine was active — "
                                    "lifting quarantine now."
                                )
                                clear_kraken_broker_quarantine()

                        return True
                    else:
                        # No result, but could be retryable
                        error_msg = "No balance data returned"
                        if attempt < max_attempts:
                            logger.warning(f"⚠️  Kraken connection attempt {attempt}/{max_attempts} failed (retryable): {error_msg}")
                            continue
                        else:
                            self.last_connection_error = error_msg
                            logger.error(f"❌ Kraken connection test failed: {error_msg}")
                            return False

                except Exception as e:
                    error_msg = str(e)

                    # Check if this is a timeout or connection error from requests library
                    # These errors should be logged clearly and are always retryable
                    # Use the module-level flag to avoid repeated import attempts
                    # NOTE: The imported exception classes (Timeout, etc.) are only defined when
                    # REQUESTS_TIMEOUT_EXCEPTIONS_AVAILABLE is True, so they're only used inside that branch
                    if REQUESTS_TIMEOUT_EXCEPTIONS_AVAILABLE:
                        # Include both timeout and connection errors (network issues)
                        # Note: Using RequestsConnectionError alias to avoid shadowing built-in ConnectionError
                        is_timeout_error = isinstance(e, (Timeout, ReadTimeout, ConnectTimeout, RequestsConnectionError))
                    else:
                        # Fallback to string matching if requests isn't available
                        is_timeout_error = (
                            'timeout' in error_msg.lower() or
                            'timed out' in error_msg.lower() or
                            'connection' in error_msg.lower()
                        )

                    if is_timeout_error:
                        # Timeout/connection errors are common and expected - log at INFO level, not ERROR
                        # After logging, we 'continue' to the next iteration which applies exponential
                        # backoff via the retry delay logic at the top of the loop
                        if attempt < max_attempts:
                            logger.info(f"   ⏱️  Connection timeout/network error ({cred_label}) - attempt {attempt}/{max_attempts}")
                            logger.info(f"   Will retry with exponential backoff...")
                            continue  # Jump to next iteration, which adds delay before retry
                        else:
                            self.last_connection_error = "Connection timeout or network error (API unresponsive)"
                            logger.warning(f"⚠️  Kraken connection failed after {max_attempts} timeout attempts")
                            logger.warning(f"   The Kraken API may be experiencing issues or network connectivity problems")
                            logger.warning(f"   Will try again on next connection cycle")
                            return False

                    # CRITICAL FIX: Check if this is a permission error in the exception path
                    # Permission errors can also be raised as exceptions by krakenex/pykrakenapi
                    is_permission_error = any(keyword in error_msg.lower() for keyword in [
                        'permission denied', 'egeneral:permission',
                        'eapi:invalid permission', 'insufficient permission'
                    ])

                    if is_permission_error:
                        self.last_connection_error = f"Permission denied: {error_msg}"
                        logger.error(f"❌ Kraken connection test failed ({cred_label}): {error_msg}")

                        # Track this account as failed due to permission error for this session
                        # The cache will be automatically cleared if valid credentials are detected later
                        # Thread-safe update using class-level lock
                        with KrakenBroker._permission_errors_lock:
                            KrakenBroker._permission_failed_accounts.add(cred_label)

                            # Only log detailed instructions ONCE GLOBALLY (not once per account)
                            # This prevents log spam when multiple users have permission errors
                            if not KrakenBroker._permission_error_details_logged:
                                KrakenBroker._permission_error_details_logged = True
                                should_log_details = True
                            else:
                                should_log_details = False

                        if should_log_details:
                            logger.error("   ⚠️  API KEY PERMISSION ERROR")
                            logger.error("   Your Kraken API key does not have the required permissions.")
                            logger.warning("")
                            logger.warning("   🔧 FIX #1 — Ensure you're using KRAKEN PLATFORM keys")
                            logger.warning("      Environment variables: KRAKEN_PLATFORM_API_KEY / KRAKEN_PLATFORM_API_SECRET")
                            logger.warning("      (Not legacy KRAKEN_API_KEY)")
                            logger.warning("")
                            logger.warning("   🔧 FIX #2 — Fix Kraken API permissions (mandatory):")
                            logger.warning("   1. Go to https://www.kraken.com/u/security/api")
                            logger.warning("   2. Find your API key and edit its permissions")
                            logger.warning("   3. Enable these permissions:")
                            logger.warning("      ✅ Query Funds (required to check balance)")
                            logger.warning("      ✅ Query Open Orders & Trades (required for position tracking)")
                            logger.warning("      ✅ Query Closed Orders & Trades (required for trade history)")
                            logger.warning("      ✅ Create & Modify Orders (required to place trades)")
                            logger.warning("      ✅ Cancel/Close Orders (required for stop losses)")
                            logger.warning("   4. Save changes and restart the bot")
                            logger.warning("")
                            logger.warning("   🔧 FIX #3 — Confirm Kraken key type:")
                            logger.warning("      ✅ Must be Classic API key (NOT OAuth or App key)")
                            logger.warning("      To create: Settings > API > Generate New Key")
                            logger.warning("")
                            logger.warning("   🔧 FIX #4 — Nonce handling (auto-fixed):")
                            logger.warning("      ✅ Bot uses microsecond-precision nonces (monotonically increasing)")
                            logger.warning("      ✅ If nonce errors persist, check system clock (use NTP sync)")
                            logger.warning("")
                            logger.warning("   For security, do NOT enable 'Withdraw Funds' permission")
                            logger.warning("   📖 See KRAKEN_PERMISSION_ERROR_FIX.md for detailed instructions")
                            # Flush handlers to ensure all permission error messages appear together
                            # CRITICAL: Flush root 'nija' logger handlers, not child logger (which has no handlers)
                            for handler in _root_logger.handlers:
                                handler.flush()
                        else:
                            logger.error("   ⚠️  API KEY PERMISSION ERROR")
                            logger.error("   Your Kraken API key does not have the required permissions.")
                            logger.error("   🔧 FIX: Must use Classic API key with Query/Create/Cancel Orders permissions")
                            logger.error("   https://www.kraken.com/u/security/api")
                            logger.error("   📖 See KRAKEN_PERMISSION_ERROR_FIX.md for detailed instructions")

                        return False

                    # Check if error is retryable (rate limiting, network issues, 403 errors, nonce errors, lockout, etc.)
                    # CRITICAL: Include "invalid nonce" and "lockout" as retryable errors
                    # Invalid nonce errors can happen due to:
                    # - Clock drift/NTP adjustments
                    # - Rapid consecutive requests
                    # - Previous failed requests leaving the nonce counter in inconsistent state
                    # The microsecond-based nonce generator should fix this, but we still retry
                    # to handle edge cases and transient issues.
                    #
                    # "Temporary lockout" errors require special handling with longer delays (minutes, not seconds)
                    # "Invalid nonce" errors require moderate delays (30s increments) and aggressive nonce jumps (10x)
                    is_lockout_error = 'lockout' in error_msg.lower()
                    # Be specific about nonce errors - match exact Kraken error messages
                    is_nonce_error = any(keyword in error_msg.lower() for keyword in [
                        'invalid nonce', 'eapi:invalid nonce', 'nonce window'
                    ])
                    is_retryable = is_lockout_error or is_nonce_error or any(keyword in error_msg.lower() for keyword in [
                        'timeout', 'connection', 'network', 'rate limit',
                        'too many requests', 'service unavailable',
                        '503', '504', '429', '403', 'forbidden',
                        'too many errors', 'temporary', 'try again',
                        'remote end closed', 'remotedisconnected',  # keep-alive reset
                        'connection reset', 'broken pipe',
                    ])

                    if is_retryable and attempt < max_attempts:
                        # Set flags for special error types to use appropriate delays on next retry
                        last_error_was_lockout = is_lockout_error
                        last_error_was_nonce = is_nonce_error and not is_lockout_error  # Lockout takes precedence

                        if is_nonce_error:
                            if get_global_nonce_manager is not None:
                                get_global_nonce_manager().record_error()

                        # Log retryable errors appropriately:
                        # - Timeout errors: Already logged above (special case)
                        # - Nonce errors: Log at INFO level (transient, will auto-retry)
                        # - Lockout/other errors: Log at WARNING on first attempt, INFO on retries
                        error_type = "lockout" if is_lockout_error else "nonce" if is_nonce_error else "retryable"

                        # For nonce errors, log at INFO level so users see progress
                        if is_nonce_error:
                            logger.info(f"   🔄 Kraken ({cred_label}) nonce error - auto-retry (attempt {attempt}/{max_attempts})")
                        # For lockout/other errors, log at WARNING on first attempt, INFO on retries
                        elif attempt == 1:
                            logger.warning(f"⚠️  Kraken ({cred_label}) attempt {attempt}/{max_attempts} failed ({error_type}): {error_msg}")
                        # All retries after first attempt: INFO level for visibility
                        else:
                            logger.info(f"   🔄 Kraken ({cred_label}) retry {attempt}/{max_attempts} ({error_type})")
                        continue
                    else:
                        # Handle errors gracefully for non-retryable or final attempt
                        self.last_connection_error = error_msg
                        error_str = error_msg.lower()
                        if 'api' in error_str and ('key' in error_str or 'signature' in error_str or 'authentication' in error_str):
                            logger.warning("⚠️  Kraken authentication failed - invalid or expired API credentials")
                        elif 'connection' in error_str or 'network' in error_str or 'timeout' in error_str:
                            logger.warning("⚠️  Kraken connection failed - network issue or API unavailable")
                        else:
                            logger.warning(f"⚠️  Kraken connection failed: {error_msg}")
                        return False

            # Should never reach here, but just in case
            # Log summary of all failed attempts to help with debugging
            self.last_connection_error = "Failed after max retry attempts"
            logger.error(f"❌ Kraken ({cred_label}) failed after {max_attempts} attempts")
            if last_error_was_nonce:
                self.last_connection_error = "Invalid nonce (retry exhausted)"
                logger.error("   Last error was: Invalid nonce (API nonce synchronization issue)")
                logger.error("   This usually resolves after waiting 1-2 minutes")
            elif last_error_was_lockout:
                self.last_connection_error = "Temporary lockout (retry exhausted)"
                logger.error("   Last error was: Temporary lockout (too many failed requests)")
                logger.error("   Wait 5-10 minutes before restarting")
            return False

        except ImportError as e:
            # SDK not installed or import failed
            self.last_connection_error = f"SDK import error: {str(e)}"
            logger.error(f"❌ Kraken connection failed ({self.account_identifier}): SDK import error")
            logger.error(f"   ImportError: {e}")
            logger.error("   The Kraken SDK (krakenex or pykrakenapi) failed to import")
            logger.error("")
            logger.error("   📋 Troubleshooting steps:")
            logger.error("      1. Verify krakenex and pykrakenapi are in requirements.txt")
            logger.error("      2. Check deployment logs for package installation errors")
            logger.error("      3. Try manual install: pip install krakenex pykrakenapi")
            logger.error("      4. Check for dependency conflicts with: pip check")
            logger.error("")
            logger.error("   If the packages are installed but import still fails,")
            logger.error("   there may be a dependency version conflict.")
            return False

    def get_account_balance(self, verbose: bool = True) -> float:
        """
        Get USD/USDT balance available for trading with fail-closed behavior.

        CRITICAL FIX (Fix 3): Fail closed - not "balance = 0"
        - On error: Return last known balance (if available) instead of 0
        - Track consecutive errors to mark broker unavailable
        - Distinguish API errors from actual zero balance

        Args:
            verbose: If True, logs detailed balance breakdown (default: True)

        Returns:
            float: Available USD + USDT balance (not including held funds)
                   Returns last known balance on error (not 0)
        """
        try:
            if not self.api:
                # FIX #2: Not connected - log warning and use last known balance
                # 🔒 CAPITAL PROTECTION: After 3 failed retries, pause trading cycle
                self._balance_fetch_errors += 1
                if self._balance_fetch_errors >= BROKER_MAX_CONSECUTIVE_ERRORS:
                    self._is_available = False
                    self.exit_only_mode = True  # Pause new entries
                    self.kraken_health = "ERROR"
                    logger.error(f"❌ CAPITAL PROTECTION: Kraken marked unavailable ({self.account_identifier}) after {self._balance_fetch_errors} consecutive errors")
                    logger.error(f"❌ Trading cycle PAUSED - entering EXIT-ONLY mode")

                if self._last_known_balance is not None:
                    logger.warning(f"⚠️ Kraken API not connected ({self.account_identifier}), using last known balance: ${self._last_known_balance:.2f}")
                    # Use cached balance if available
                    if "kraken" in self.balance_cache:
                        return self.balance_cache["kraken"]
                    return self._last_known_balance
                else:
                    logger.error(f"❌ Kraken API not connected ({self.account_identifier}) and no last known balance")
                    self._is_available = False
                    self.kraken_health = "ERROR"
                    return 0.0

            # ── TTL cache check: skip API call if balance was recently fetched ──────
            if (self._last_known_balance is not None
                    and self._balance_last_updated is not None
                    and (time.time() - self._balance_last_updated) < self._kraken_balance_cache_ttl):
                _cache_age = time.time() - self._balance_last_updated
                logger.debug(
                    f"Kraken balance cache hit ({self.account_identifier}): "
                    f"${self._last_known_balance:.2f} "
                    f"(age {_cache_age:.0f}s / TTL {self._kraken_balance_cache_ttl}s)"
                )
                return self.balance_cache.get("kraken", self._last_known_balance)

            # Get account balance using serialized API call
            # Use MONITORING category for balance checks (conservative rate limiting)
            balance_category = KrakenAPICategory.MONITORING if KrakenAPICategory is not None else None
            balance = self._kraken_private_call('Balance', category=balance_category)

            if balance and 'error' in balance and balance['error']:
                error_msgs = ', '.join(balance['error'])

                # FIX #2: On error, log warning and use last known balance
                logger.warning(f"⚠️ Kraken API error fetching balance ({self.account_identifier}): {error_msgs}")

                # DO NOT zero balance on one failure
                # 🔒 CAPITAL PROTECTION: After 3 failed retries, pause trading cycle
                self._balance_fetch_errors += 1
                if self._balance_fetch_errors >= BROKER_MAX_CONSECUTIVE_ERRORS:
                    self._is_available = False
                    self.exit_only_mode = True  # Pause new entries, only allow exits
                    self.kraken_health = "ERROR"
                    logger.error(f"❌ CAPITAL PROTECTION: Kraken balance fetch failed after {self._balance_fetch_errors} retries ({self.account_identifier})")
                    logger.error(f"❌ Trading cycle PAUSED - entering EXIT-ONLY mode")

                if self._last_known_balance is not None:
                    logger.warning(f"   ⚠️ Using last known balance: ${self._last_known_balance:.2f}")
                    # Use cached balance if available
                    if "kraken" in self.balance_cache:
                        return self.balance_cache["kraken"]
                    return self._last_known_balance
                else:
                    logger.error(f"   ❌ No last known balance available, returning 0")
                    return 0.0

            if balance and 'result' in balance:
                result = balance['result']

                # Kraken uses ZUSD for USD and USDT for Tether
                usd_balance = float(result.get('ZUSD', 0))
                usdt_balance = float(result.get('USDT', 0))

                total = usd_balance + usdt_balance

                # Also get TradeBalance to see held funds
                # Use MONITORING category for balance checks (conservative rate limiting)
                balance_category = KrakenAPICategory.MONITORING if KrakenAPICategory is not None else None
                trade_balance = self._kraken_private_call('TradeBalance', {'asset': 'ZUSD'}, category=balance_category)
                held_amount = 0.0

                if trade_balance and 'result' in trade_balance:
                    tb_result = trade_balance['result']
                    # eb = equivalent balance (total balance including held orders)
                    # tb = trade balance (free margin available)
                    # held = eb - tb
                    eb = float(tb_result.get('eb', 0))
                    tb = float(tb_result.get('tb', 0))
                    held_amount = eb - tb if eb > tb else 0.0

                # Enhanced balance logging with clear breakdown (Jan 19, 2026)
                # Only log detailed breakdown if verbose is True
                if verbose:
                    logger.info("=" * 70)
                    logger.info(f"💰 Kraken Balance ({self.account_identifier}):")
                    logger.info(f"   ✅ Available USD:  ${usd_balance:.2f}")
                    logger.info(f"   ✅ Available USDT: ${usdt_balance:.2f}")
                    logger.info(f"   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                    logger.info(f"   💵 Total Available: ${total:.2f}")

                # 🚑 FIX 4: Calculate total_funds (available + locked) for Kraken
                total_funds = total + held_amount

                if verbose:
                    if held_amount > 0:
                        logger.info(f"   🔒 Held in open orders: ${held_amount:.2f}")
                        logger.info(f"   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                        logger.info(f"   💎 TOTAL FUNDS (Available + Held): ${total_funds:.2f}")
                    logger.info("=" * 70)

                    # FIX #3 (Jan 20, 2026): Confirmation log for Kraken balance fetch
                    logger.info(f"✅ KRAKEN balance fetched: ${total_funds:.2f}")
                else:
                    # Minimal logging when verbose=False
                    logger.debug(f"Kraken balance ({self.account_identifier}): ${total_funds:.2f}")

                # SUCCESS: Update last known balance and reset error count
                # 🚑 FIX 4: Store and return total_funds instead of just available
                self._last_known_balance = total_funds
                self._balance_last_updated = time.time()  # Track when balance was last updated (Jan 24, 2026)
                self._balance_fetch_errors = 0
                self._is_available = True
                # 🔒 CAPITAL PROTECTION: Resume trading if it was paused due to balance errors
                if self.exit_only_mode:
                    logger.info(f"✅ Balance fetch successful - resuming normal trading (EXIT-ONLY mode cleared) ({self.account_identifier})")
                    self.exit_only_mode = False

                # FIX #2: Force Kraken balance cache after success
                self.balance_cache["kraken"] = total_funds
                self.kraken_health = "OK"

                return total_funds

            # Unexpected response - treat as error
            # FIX #2: Log warning and use last known balance
            logger.warning(f"⚠️ Unexpected Kraken API response format ({self.account_identifier})")
            self._balance_fetch_errors += 1
            if self._balance_fetch_errors >= BROKER_MAX_CONSECUTIVE_ERRORS:
                self._is_available = False
                self.kraken_health = "ERROR"

            if self._last_known_balance is not None:
                logger.warning(f"   ⚠️ Using last known balance: ${self._last_known_balance:.2f}")
                # Use cached balance if available
                if "kraken" in self.balance_cache:
                    return self.balance_cache["kraken"]
                return self._last_known_balance

            return 0.0

        except Exception as e:
            # FIX #2: Log warning and use last known balance on exception
            # 🔒 CAPITAL PROTECTION: After 3 failed retries, pause trading cycle
            logger.warning(f"⚠️ Exception fetching Kraken balance ({self.account_identifier}): {e}")
            self._balance_fetch_errors += 1
            if self._balance_fetch_errors >= BROKER_MAX_CONSECUTIVE_ERRORS:
                self._is_available = False
                self.exit_only_mode = True  # Pause new entries after consecutive errors
                self.kraken_health = "ERROR"
                logger.error(f"❌ CAPITAL PROTECTION: Kraken marked unavailable ({self.account_identifier}) after {self._balance_fetch_errors} consecutive errors")
                logger.error(f"❌ Trading cycle PAUSED - entering EXIT-ONLY mode")

            # Return last known balance instead of 0
            if self._last_known_balance is not None:
                logger.warning(f"   ⚠️ Using last known balance: ${self._last_known_balance:.2f}")
                # Use cached balance if available
                if "kraken" in self.balance_cache:
                    return self.balance_cache["kraken"]
                return self._last_known_balance

            return 0.0

    def get_account_balance_detailed(self) -> dict:
        """
        Get detailed account balance information with fail-closed behavior.

        CRITICAL FIX (Fix 3): Fail closed - not "balance = 0"
        - On error: Include error flag in response
        - Return last known balance if available
        - Don't return all zeros on error

        Returns detailed balance breakdown for comprehensive fund visibility.
        Matches CoinbaseBroker interface for consistency.

        Returns:
            dict: Detailed balance info with keys:
                - usd: Available USD balance
                - usdt: Available USDT balance
                - trading_balance: Total available (USD + USDT)
                - usd_held: USD held in open orders
                - usdt_held: USDT held in open orders
                - total_held: Total held (usd_held + usdt_held)
                - total_funds: Complete balance (trading_balance + total_held)
                - crypto: Dictionary of crypto asset balances
                - error: Boolean indicating if fetch failed
                - error_message: Error description (if error=True)
        """
        # Default return structure for error cases
        default_balance = {
            'usd': 0.0,
            'usdt': 0.0,
            'trading_balance': 0.0,
            'usd_held': 0.0,
            'usdt_held': 0.0,
            'total_held': 0.0,
            'total_funds': 0.0,
            'crypto': {},
            'error': True,
            'error_message': 'Unknown error'
        }

        try:
            if not self.api:
                error_msg = 'API not connected'
                logger.warning(f"⚠️ {error_msg} ({self.account_identifier})")
                return {**default_balance, 'error_message': error_msg}

            # Get account balance using serialized API call
            # Use MONITORING category for balance checks (conservative rate limiting)
            balance_category = KrakenAPICategory.MONITORING if KrakenAPICategory is not None else None
            balance = self._kraken_private_call('Balance', category=balance_category)

            if balance and 'error' in balance and balance['error']:
                error_msgs = ', '.join(balance['error'])
                logger.error(f"❌ Kraken API error fetching detailed balance ({self.account_identifier}): {error_msgs}")
                return {**default_balance, 'error_message': f'API error: {error_msgs}'}

            if balance and 'result' in balance:
                result = balance['result']

                # Kraken uses ZUSD for USD and USDT for Tether
                usd_balance = float(result.get('ZUSD', 0))
                usdt_balance = float(result.get('USDT', 0))

                # Get crypto holdings (exclude USD and USDT)
                crypto_holdings = {}
                for currency, amount in result.items():
                    if currency not in ['ZUSD', 'USDT'] and float(amount) > 0:
                        # Strip the 'Z' or 'X' prefix Kraken uses for some currencies
                        clean_currency = currency.lstrip('ZX')
                        crypto_holdings[clean_currency] = float(amount)

                trading_balance = usd_balance + usdt_balance

                # Get TradeBalance to calculate held funds
                # Use MONITORING category for balance checks (conservative rate limiting)
                balance_category = KrakenAPICategory.MONITORING if KrakenAPICategory is not None else None
                trade_balance = self._kraken_private_call('TradeBalance', {'asset': 'ZUSD'}, category=balance_category)
                usd_held = 0.0
                usdt_held = 0.0
                total_held = 0.0

                if trade_balance and 'result' in trade_balance:
                    tb_result = trade_balance['result']
                    # eb = equivalent balance (total balance including held orders)
                    # tb = trade balance (free margin available)
                    # held = eb - tb
                    eb = float(tb_result.get('eb', 0))
                    tb = float(tb_result.get('tb', 0))
                    total_held = eb - tb if eb > tb else 0.0

                    # NOTE: Kraken's TradeBalance API returns total held amount in base currency (USD)
                    # but doesn't break it down by USD vs USDT. We approximate the distribution
                    # based on the ratio of USD to USDT in available balances.
                    if trading_balance > 0 and total_held > 0:
                        usd_ratio = usd_balance / trading_balance
                        usdt_ratio = usdt_balance / trading_balance
                        usd_held = total_held * usd_ratio
                        usdt_held = total_held * usdt_ratio
                    elif usd_balance > 0:
                        # If only USD, assign all held to USD
                        usd_held = total_held
                    else:
                        # If only USDT or no balance, assign all held to USDT
                        usdt_held = total_held

                total_funds = trading_balance + total_held

                return {
                    'usd': usd_balance,
                    'usdt': usdt_balance,
                    'trading_balance': trading_balance,
                    'usd_held': usd_held,
                    'usdt_held': usdt_held,
                    'total_held': total_held,
                    'total_funds': total_funds,
                    'crypto': crypto_holdings,
                    'error': False
                }

            # Unexpected response
            return {**default_balance, 'error_message': 'Unexpected API response format'}

        except Exception as e:
            error_msg = str(e)
            logger.error(f"❌ Exception fetching Kraken detailed balance ({self.account_identifier}): {error_msg}")
            return {**default_balance, 'error_message': error_msg}

    def is_available(self) -> bool:
        """
        Check if Kraken broker is available for trading.

        Returns False if there have been 3+ consecutive balance fetch errors.
        This prevents trading when the API is not working properly.

        Returns:
            bool: True if broker is available, False if unavailable
        """
        return self._is_available

    def get_error_count(self) -> int:
        """
        Get the number of consecutive balance fetch errors.

        Returns:
            int: Number of consecutive errors
        """
        return self._balance_fetch_errors

    def get_current_price(self, symbol: str) -> Optional[float]:
        """
        Get current market price for a symbol from Kraken.

        CRITICAL FIX: Implements proper price fetching with broker-specific symbol translation.
        This prevents ghost positions by ensuring prices can be fetched correctly.

        Extended with Emergency Symbol Resolver: if the primary ticker lookup fails,
        the resolver tries alternate pair mappings, base/quote inversions, and a USD
        bridge before classifying the asset as a DelistedAsset (Non-Tradeable Residual).

        Args:
            symbol: Trading pair in standard format (e.g., 'BTC-USD', 'ETH-USD', 'DOGE-USD')

        Returns:
            float: Current market price, or None if fetch fails

        Safety:
            - Uses symbol mapper to convert to Kraken format
            - Falls back to EmergencySymbolResolver on failure
            - Returns None on failure (not 0.0) for explicit error handling
            - Logs errors with symbol mismatch hints
        """
        try:
            if not self.api:
                logger.error(f"❌ Price fetch failed for {symbol} — Kraken API not connected")
                return None

            # CRITICAL: Use symbol mapper to convert to Kraken format
            # This ensures we use the correct format (e.g., XETHZUSD, XXBTZUSD)
            # instead of incorrect formats like ETHUSD, BTCUSD
            kraken_symbol = None
            normalized_symbol = normalize_symbol_for_broker(symbol, self.broker_type.value)

            if convert_to_kraken:
                kraken_symbol = convert_to_kraken(normalized_symbol)
                if not kraken_symbol:
                    logger.warning(f"⚠️ Price fetch: Cannot convert {symbol} to Kraken format — activating Emergency Resolver")
                    return self._resolve_price_emergency(symbol)
            else:
                # Fallback: Manual conversion if symbol mapper not available
                kraken_symbol = normalized_symbol.replace('-', '').upper()
                if kraken_symbol.startswith('BTC'):
                    kraken_symbol = kraken_symbol.replace('BTC', 'XBT', 1)

            logger.debug(f"📊 Fetching price for {symbol} (Kraken: {kraken_symbol})")

            # Fetch current price using Kraken Ticker API
            # Ticker is a public endpoint (no authentication needed)
            # CRITICAL FIX: pykrakenapi 0.3.2 retries indefinitely on RemoteDisconnected.
            # Wrap in a 10-second thread timeout to prevent the position-analysis loop
            # from hanging for hours when the Kraken connection is broken.
            _ticker_result_holder = [None]
            _ticker_err_holder    = [None]
            def _fetch_ticker():
                try:
                    with suppress_pykrakenapi_prints():
                        _ticker_result_holder[0] = self.api.query_public(
                            'Ticker', {'pair': kraken_symbol}
                        )
                except Exception as _te:
                    _ticker_err_holder[0] = _te
            _ticker_thread = threading.Thread(target=_fetch_ticker, daemon=True)
            _ticker_thread.start()
            _ticker_thread.join(10)  # 10-second hard cap per price fetch
            if _ticker_thread.is_alive():
                # Live fetch timed out — try the short-lived price cache (≤10s old).
                # Read price and ts atomically under the lock to avoid a race where
                # another thread could overwrite the entry between the two accesses.
                with self._price_cache_lock:
                    cached = self._price_cache.get(symbol)
                    cached_price = cached["price"] if cached else None
                    cached_age = (time.monotonic() - cached["ts"]) if cached else None
                if cached_price is not None and cached_age is not None and cached_age <= 10.0:
                    logger.debug(
                        f"⏱️  Ticker fetch for {symbol} timed out — returning cached price "
                        f"${cached_price:.6f} ({cached_age:.1f}s old)"
                    )
                    return cached_price
                logger.debug(
                    f"⏱️  Ticker fetch for {symbol} timed out (10s) — returning None"
                )
                return None
            if _ticker_err_holder[0] is not None:
                raise _ticker_err_holder[0]
            ticker_result = _ticker_result_holder[0]

            if ticker_result and 'result' in ticker_result:
                ticker_data = ticker_result['result'].get(kraken_symbol, {})
                if ticker_data:
                    # Use last trade price ('c' field is last trade closed array [price, lot volume])
                    last_price = ticker_data.get('c', [None])[0]
                    if last_price:
                        price = float(last_price)
                        with self._price_cache_lock:
                            self._price_cache[symbol] = {"price": price, "ts": time.monotonic()}
                        logger.debug(f"✅ Price for {symbol}: ${price:.2f}")
                        return price
                    else:
                        logger.warning(f"⚠️ No last trade price for {symbol} — activating Emergency Resolver")
                        return self._resolve_price_emergency(symbol)
                else:
                    logger.warning(
                        f"⚠️ {symbol} not found in Kraken ticker ('{kraken_symbol}') "
                        f"— activating Emergency Resolver"
                    )
                    return self._resolve_price_emergency(symbol)
            else:
                logger.warning(f"⚠️ Ticker API error for {symbol} — activating Emergency Resolver")
                if ticker_result and 'error' in ticker_result and ticker_result['error']:
                    logger.warning(f"   API errors: {', '.join(ticker_result['error'])}")
                return self._resolve_price_emergency(symbol)

        except Exception as e:
            logger.warning(f"⚠️ Price fetch exception for {symbol}: {e} — activating Emergency Resolver")
            return self._resolve_price_emergency(symbol)

    def _resolve_price_emergency(self, symbol: str) -> Optional[float]:
        """
        Emergency Symbol Resolver — called when the primary price fetch fails.

        Resolution pipeline (in order):
          1. Alternate pair mapping  (e.g., AUT-USD → AUTUSD, AUTUSDT, …)
          2. USD bridge valuation    (ASSET → BTC → USD estimate)
          3. DelistedAsset protocol  (Non-Tradeable Residual classification)

        Args:
            symbol: Standard format symbol (e.g. "AUT-USD")

        Returns:
            float price if found via alternate means, or None if unresolvable.
        """
        if not EMERGENCY_RESOLVER_AVAILABLE or EmergencySymbolResolver is None:
            logger.error(f"❌ Price fetch failed for {symbol} — Emergency Resolver unavailable")
            return None

        # Use a per-broker-instance resolver (lazy-init)
        if not hasattr(self, '_emergency_resolver') or self._emergency_resolver is None:
            self._emergency_resolver = EmergencySymbolResolver(self.api)

        result = self._emergency_resolver.resolve(symbol)

        if result.price is not None:
            logger.info(
                f"🔁 Emergency Resolver succeeded for {symbol}: "
                f"${result.price:.6f} via {result.status.value} ({result.reason})"
            )
            return result.price

        if result.status == SymbolStatus.DELISTED:
            logger.warning(
                f"🚫 {symbol} classified as Non-Tradeable Residual (delisted). "
                f"Excluded from cap count and exposure modeling. "
                f"Bot will attempt market sell when liquidity appears."
            )
            # Log to the delisted registry (already done inside the resolver)
            return None

        logger.error(
            f"❌ Emergency Resolver exhausted all options for {symbol} "
            f"({result.reason}) — returning None"
        )
        return None

    def force_liquidate(
        self,
        symbol: str,
        quantity: float,
        reason: str = "Emergency liquidation"
    ) -> Dict:
        """
        🚑 EMERGENCY SELL OVERRIDE - Force liquidate position bypassing ALL checks.

        This is the FIX 1 implementation for Kraken that allows NIJA to exit losing positions
        immediately without being blocked by validation.

        CRITICAL: This method MUST be used for emergency exits and losing trades.

        Args:
            symbol: Trading symbol (e.g., 'BTC-USD')
            quantity: Quantity to sell (in base currency)
            reason: Reason for forced liquidation (for logging)

        Returns:
            Order result dict with status
        """
        logger.warning("=" * 70)
        logger.warning(f"🚑 FORCE LIQUIDATE [Kraken]: {symbol}")
        logger.warning(f"   Account: {self.account_identifier if hasattr(self, 'account_identifier') else 'UNKNOWN'}")
        logger.warning(f"   Reason: {reason}")
        logger.warning(f"   Quantity: {quantity}")
        logger.warning(f"   Mode: EMERGENCY EXIT MODE — SELL ONLY")
        logger.warning("=" * 70)

        try:
            # Force market sell with emergency bypass flags
            result = self.place_market_order(
                symbol=symbol,
                side='sell',
                quantity=quantity,
                ignore_balance=True,
                ignore_min_trade=True,
                force_liquidate=True
            )

            if result.get('status') == 'filled':
                logger.warning(f"✅ PROTECTIVE LIQUIDATION SUCCESSFUL [Kraken]: {symbol}")
            else:
                logger.error(f"❌ PROTECTIVE LIQUIDATION FAILED [Kraken]: {symbol} - {result.get('error', 'Unknown error')}")

            return result

        except Exception as e:
            logger.error(f"❌ PROTECTIVE LIQUIDATION EXCEPTION [Kraken]: {symbol} - {e}")
            logger.error(traceback.format_exc())
            return {
                "status": "error",
                "error": str(e),
                "symbol": symbol
            }

    def place_market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        size_type: str = 'quote',
        ignore_balance: bool = False,
        ignore_min_trade: bool = False,
        force_liquidate: bool = False
    ) -> Dict:
        """
        Place market order on Kraken.

        Args:
            symbol: Trading pair (e.g., 'BTC-USD' or 'XBTUSDT')
            side: 'buy' or 'sell'
            quantity: Order size in USD (for buys) or base currency (for sells)

        Returns:
            dict: Order result with status, order_id, etc.
        """
        # 🍎 CRITICAL LAYER 0: APP STORE MODE CHECK (Absolute Block)
        try:
            from bot.app_store_mode import get_app_store_mode
            app_store_mode = get_app_store_mode()
            if app_store_mode.is_enabled():
                return app_store_mode.block_execution_with_log(
                    operation='place_market_order',
                    symbol=symbol,
                    side=side,
                    size=quantity
                )
        except ImportError:
            pass

        # 🔒 LAYER 1: BROKER ISOLATION CHECK (Step 6)
        # Replaces raise RuntimeError("Capital below minimum")
        # With: logger.warning("Kraken isolated mode: non-execution broker")
        _iso = _check_broker_isolation(self.broker_type, side)
        if _iso is not None:
            logger.warning("Kraken isolated mode: non-execution broker — %s skipped", side.upper())
            return _iso

        try:
            if not self.api:
                return {"status": "error", "error": "Not connected to Kraken"}

            # 🚑 FIX #1: FORCE SELL OVERRIDE - SELL orders bypass ALL restrictions
            # ================================================================
            # CRITICAL: SELL orders are NEVER blocked by:
            #   ✅ MINIMUM_TRADING_BALANCE (balance checks only apply to BUY)
            #   ✅ MIN_CASH_TO_BUY (balance checks only apply to BUY)
            #   ✅ ENTRY_ONLY mode / EXIT_ONLY mode (blocks BUY, not SELL)
            #   ✅ Broker preference routing (SELL always executes)
            #   ✅ Emergency stop flags (only block BUY)
            #
            # This ensures:
            #   - Stop-loss exits always execute
            #   - Emergency liquidation always executes
            #   - Losing positions can always be closed
            #   - Capital bleeding can always be stopped
            # ================================================================

            # Log explicit bypass for SELL orders
            if side.lower() == 'sell':
                logger.info(f"🛡️ PROTECTIVE SELL MODE for {symbol}: EMERGENCY EXIT MODE — SELL ONLY")
                logger.info(f"   ✅ Balance validation: SKIPPED (protective exit)")
                logger.info(f"   ✅ Minimum balance check: SKIPPED (protective exit)")
                logger.info(f"   ✅ EXIT-ONLY mode: ALLOWED (protective exit)")
                logger.info(f"   ✅ Capital preservation: ACTIVE")

            # FIX 2: Reject BUY orders when in EXIT-ONLY mode
            # NOTE: SELL orders are NOT checked here - they always pass through
            if side.lower() == 'buy' and getattr(self, 'exit_only_mode', False) and not force_liquidate:
                logger.error(f"❌ BUY order rejected: Kraken is in EXIT-ONLY mode (balance < ${KRAKEN_MINIMUM_BALANCE:.2f})")
                logger.error(f"   Only SELL orders are allowed to close existing positions")
                logger.error(f"   To enable new entries, fund your account to at least ${KRAKEN_MINIMUM_BALANCE:.2f}")
                return {
                    "status": "unfilled",
                    "error": "EXIT_ONLY_MODE",
                    "message": f"BUY orders blocked: Account balance below ${KRAKEN_MINIMUM_BALANCE:.2f} minimum",
                    "partial_fill": False,
                    "filled_pct": 0.0
                }

            # Quarantine check: nonce poisoning confirmed — no new entries until key is rotated.
            # Only the PLATFORM account is quarantined; USER accounts have independent API keys
            # with their own nonce windows and must not be blocked by a platform-level quarantine.
            if (side.lower() == 'buy'
                    and _kraken_quarantine_active
                    and self.account_type == AccountType.PLATFORM
                    and not force_liquidate):
                logger.critical(
                    "🚫 BUY order BLOCKED: Kraken broker is QUARANTINED due to confirmed nonce "
                    "poisoning.  Rotate the API key and restart to re-enable entries."
                )
                return {
                    "status": "unfilled",
                    "error": "BROKER_QUARANTINED",
                    "message": "Kraken blocked: nonce poisoning confirmed — rotate API key to recover",
                    "partial_fill": False,
                    "filled_pct": 0.0,
                }

            # CRITICAL FIX (Jan 19, 2026): Normalize symbol for Kraken and check support
            # Railway Golden Rule #4: Broker-specific trading pairs
            # This prevents trying to trade Binance-only pairs (BUSD) on Kraken
            if not self.supports_symbol(symbol):
                error_msg = f"Kraken does not support symbol: {symbol} (broker-specific pair filtering)"
                logger.warning(f"⏭️ SKIPPING TRADE: {error_msg}")
                logger.warning(f"   💡 TIP: This symbol contains unsupported quote currency for Kraken (e.g., BUSD)")
                return {"status": "error", "error": error_msg}

            # Normalize to standard format for Kraken (ETH-USD, BTC-USDT, etc.)
            normalized_symbol = normalize_symbol_for_broker(symbol, self.broker_type.value)

            # SYMBOL VALIDATION FIX (Jan 20, 2026): Use symbol mapper to validate and convert
            # This prevents "EQuery:Unknown asset pair" errors by validating symbols before trading
            kraken_symbol = None
            if validate_kraken_symbol and convert_to_kraken:
                # Validate symbol is available on Kraken
                if not validate_kraken_symbol(normalized_symbol):
                    error_msg = f"Symbol {normalized_symbol} not available on Kraken"
                    logger.warning(f"⏭️ SKIPPING TRADE: {error_msg}")
                    logger.warning(f"   💡 TIP: This pair may have been delisted or is not tradable")
                    return {"status": "error", "error": error_msg}

                # Convert to Kraken format using symbol mapper
                kraken_symbol = convert_to_kraken(normalized_symbol)
                if not kraken_symbol:
                    error_msg = f"Cannot convert {normalized_symbol} to Kraken format"
                    logger.error(f"❌ CONVERSION ERROR: {error_msg}")
                    return {"status": "error", "error": error_msg}

                logger.debug(f"✅ Symbol validated: {normalized_symbol} -> {kraken_symbol}")

            # Fallback: Manual conversion if symbol mapper not available
            # Convert from standard format (ETH-USD) to Kraken internal format (XETHZUSD)
            # Kraken internal format: no separator, X prefix for some assets
            # Examples: ETH-USD -> XETHZUSD, BTC-USD -> XXBTZUSD
            if not kraken_symbol:
                kraken_symbol = normalized_symbol.replace('-', '').upper()

                # Kraken uses X prefix for BTC
                if kraken_symbol.startswith('BTC'):
                    kraken_symbol = kraken_symbol.replace('BTC', 'XBT', 1)

            # Determine order type
            order_type = side.lower()  # 'buy' or 'sell'

            # ✅ TIER LOCK ENFORCEMENT: Validate trade size against tier minimums
            # This prevents small trades that will be eaten by fees
            # Track if tier auto-resize occurred (used for Kraken minimum enforcement later)
            tier_was_auto_resized = False
            # Determine if this is a platform account (not subject to tier limits)
            # Used in both tier validation and Kraken minimum enforcement
            is_platform_account = (self.account_type == AccountType.PLATFORM)

            if side.lower() == 'buy' and get_tier_from_balance and validate_trade_size:
                try:
                    # Get current balance
                    balance_info = self.get_account_balance_detailed()
                    if balance_info and not balance_info.get('error', False):
                        current_balance = balance_info.get('trading_balance', 0.0)

                        # Check if balance meets minimum tier requirement ($10 SAVER tier minimum)
                        # Use tier config to get the minimum balance
                        saver_tier_config = get_tier_config(get_tier_from_balance(10.0))
                        min_balance_required = saver_tier_config.capital_min

                        if current_balance < min_balance_required:
                            logging.error(LOG_SEPARATOR)
                            logging.error("❌ TIER ENFORCEMENT: BUY ORDER BLOCKED")
                            logging.error(LOG_SEPARATOR)
                            logging.error(f"   Account balance: ${current_balance:.2f}")
                            logging.error(f"   Minimum required: ${min_balance_required:.2f} (SAVER tier minimum)")
                            logging.error("   ⚠️  Cannot execute trades below tier minimum")
                            logging.error(LOG_SEPARATOR)
                            return {
                                "status": "error",
                                "error": f"Account balance ${current_balance:.2f} below minimum tier requirement ${min_balance_required:.2f}"
                            }

                        # Determine user's tier based on balance
                        # Platform accounts always get BALLER tier regardless of balance
                        user_tier = get_tier_from_balance(current_balance, is_platform=is_platform_account)
                        tier_config = get_tier_config(user_tier)

                        # Calculate order size in USD (quantity is already in USD for buy orders)
                        order_size_usd = quantity

                        # AUTO-RESIZE trade instead of rejecting (smarter approach)
                        # If trade exceeds tier limits, resize to maximum safe size
                        # NOTE: Platform accounts have more flexible limits
                        if auto_resize_trade:
                            resized_size, resize_reason = auto_resize_trade(
                                order_size_usd, user_tier, current_balance,
                                is_platform=is_platform_account, exchange='kraken'
                            )

                            if resized_size == 0.0:
                                # Trade is below minimum - cannot resize
                                logging.error(LOG_SEPARATOR)
                                logging.error("❌ TIER ENFORCEMENT: TRADE SIZE TOO SMALL")
                                logging.error(LOG_SEPARATOR)
                                logging.error(f"   Tier: {user_tier.value}")
                                logging.error(f"   Account balance: ${current_balance:.2f}")
                                logging.error(f"   Trade size: ${order_size_usd:.2f}")
                                logging.error(f"   Reason: {resize_reason}")
                                logging.error(LOG_SEPARATOR)
                                return {
                                    "status": "error",
                                    "error": f"[{user_tier.value} Tier] {resize_reason}"
                                }
                            elif resized_size != order_size_usd:
                                # Trade was auto-resized
                                logging.info(LOG_SEPARATOR)
                                logging.info("📏 AUTO-RESIZE: Trade adjusted to tier limits")
                                logging.info(LOG_SEPARATOR)
                                logging.info(f"   Tier: {user_tier.value}")
                                logging.info(f"   Requested: ${order_size_usd:.2f}")
                                logging.info(f"   Allowed max: ${resized_size:.2f}")
                                logging.info(f"   Executed size: ${resized_size:.2f}")
                                logging.info(f"   Reason: {resize_reason}")
                                logging.info(LOG_SEPARATOR)

                                # Update quantity to resized amount
                                quantity = resized_size
                                order_size_usd = resized_size
                                # Set flag for Kraken minimum enforcement below
                                tier_was_auto_resized = True
                            else:
                                # Trade is within limits
                                logging.info(f"✅ Tier validation passed: [{user_tier.value}] ${order_size_usd:.2f} trade")
                                logging.info(f"   Account balance: ${current_balance:.2f}")
                                logging.info(f"   Tier range: ${tier_config.trade_size_min:.2f}-${tier_config.trade_size_max:.2f}")
                        else:
                            # Fallback to old validation if auto_resize not available
                            is_valid, reason = validate_trade_size(order_size_usd, user_tier, current_balance)

                            if not is_valid:
                                logging.error(LOG_SEPARATOR)
                                logging.error("❌ TIER ENFORCEMENT: TRADE SIZE BLOCKED")
                                logging.error(LOG_SEPARATOR)
                                logging.error(f"   Tier: {user_tier.value}")
                                logging.error(f"   Account balance: ${current_balance:.2f}")
                                logging.error(f"   Trade size: ${order_size_usd:.2f}")
                                logging.error(f"   Reason: {reason}")
                                logging.error("   ⚠️  Trade blocked to prevent fee destruction")
                                logging.error(LOG_SEPARATOR)
                                return {
                                    "status": "error",
                                    "error": f"[{user_tier.value} Tier] {reason}"
                                }

                            # Log tier validation success
                            logging.info(f"✅ Tier validation passed: [{user_tier.value}] ${order_size_usd:.2f} trade")
                            logging.info(f"   Account balance: ${current_balance:.2f}")
                            logging.info(f"   Tier range: ${tier_config.trade_size_min:.2f}-${tier_config.trade_size_max:.2f}")

                except Exception as tier_err:
                    # Don't block trade if tier validation fails - just log warning
                    logging.warning(f"⚠️  Tier validation error (allowing trade): {tier_err}")

            # ✅ KRAKEN MINIMUM ENFORCEMENT: Check if trade meets Kraken's minimum
            # However, DO NOT bump up trades that were auto-resized down by tier limits
            # This prevents violating tier-based risk management for profit protection
            # EXCEPTION: Platform accounts are NOT subject to tier limits
            if side.lower() == 'buy' and size_type == 'quote':
                # Use Kraken minimum from imported constant
                kraken_min = KRAKEN_MINIMUM_ORDER_USD or 10.00

                # Log pre-clamp size so multiplier chain is always visible in logs,
                # regardless of whether the floor adjustment fires.
                logging.info(
                    f"   📐 Kraken size check [{symbol}]: "
                    f"pre-clamp=${quantity:.2f} | floor=${kraken_min:.2f}"
                )

                if quantity < kraken_min:
                    # Check if this trade was auto-resized down due to tier limits
                    # using explicit flag set during tier validation above
                    # CRITICAL: Only enforce tier protection for USER accounts, not MASTER
                    # Note: is_platform_account is defined at line 6691

                    if tier_was_auto_resized and not is_platform_account:
                        # USER account: Trade was resized down by tier limits, and result is below Kraken minimum
                        # REJECT the trade to protect tier-based risk management
                        logging.error(LOG_SEPARATOR)
                        logging.error("❌ TRADE REJECTED: Tier limit conflicts with Kraken minimum")
                        logging.error(LOG_SEPARATOR)
                        # Try to log tier details if available
                        if 'user_tier' in locals() and 'current_balance' in locals():
                            logging.error(f"   Tier: {user_tier.value}")
                            logging.error(f"   Account balance: ${current_balance:.2f}")
                        logging.error(f"   Tier-adjusted size: ${quantity:.2f}")
                        logging.error(f"   Kraken minimum: ${kraken_min:.2f}")
                        logging.error(f"   ⚠️  Cannot meet Kraken minimum without violating tier limits")
                        logging.error(f"   💡 Tier limits protect small USER accounts from excessive risk")
                        logging.error(f"   💡 Platform account is not subject to tier limits")
                        logging.error(LOG_SEPARATOR)
                        return {
                            "status": "error",
                            "error": f"Trade size ${quantity:.2f} below Kraken minimum ${kraken_min:.2f} after tier adjustment. Cannot execute without violating tier risk limits."
                        }
                    else:
                        # Either: (1) Trade wasn't tier-resized, OR (2) This is MASTER account
                        # Safe to bump up to Kraken minimum
                        original_quantity = quantity
                        quantity = kraken_min

                        if is_platform_account and tier_was_auto_resized:
                            # Platform account: tier resize occurred but we override for Kraken minimum
                            logging.info(LOG_SEPARATOR)
                            logging.info("💰 KRAKEN MINIMUM ENFORCEMENT: Trade rounded up (PLATFORM account)")
                            logging.info(LOG_SEPARATOR)
                            logging.info(f"   Original size: ${original_quantity:.2f}")
                            logging.info(f"   Kraken minimum: ${kraken_min:.2f}")
                            logging.info(f"   Adjusted size: ${quantity:.2f}")
                            logging.info(f"   Reason: Meeting Kraken's ${kraken_min:.2f} minimum order value")
                            logging.info(f"   🎯 PLATFORM account: Not subject to tier limits")
                            logging.info(LOG_SEPARATOR)
                        else:
                            # Normal Kraken minimum bump (not tier-resized)
                            logging.info(LOG_SEPARATOR)
                            logging.info("💰 KRAKEN MINIMUM ENFORCEMENT: Trade rounded up")
                            logging.info(LOG_SEPARATOR)
                            logging.info(f"   Original size: ${original_quantity:.2f}")
                            logging.info(f"   Kraken minimum: ${kraken_min:.2f}")
                            logging.info(f"   Adjusted size: ${quantity:.2f}")
                            logging.info(f"   Reason: Meeting Kraken's ${kraken_min:.2f} minimum order value")
                            logging.info(LOG_SEPARATOR)

                # Log post-clamp size so the final quantity submitted to Kraken
                # is always visible regardless of whether the floor fired.
                logging.info(
                    f"   ✅ Kraken size check [{symbol}]: "
                    f"post-clamp=${quantity:.2f}"
                )

            # ✅ PRE-FLIGHT BALANCE CHECK: Verify sufficient funds BEFORE sending to Kraken API
            # This prevents "EOrder:Insufficient funds" rejections from the API
            # Same pattern as Coinbase broker (lines 2550-2580)
            if side.lower() == 'buy' and not (force_liquidate or ignore_balance):
                balance_data = self.get_account_balance_detailed()
                if balance_data and not balance_data.get('error', False):
                    trading_balance = float(balance_data.get('trading_balance', 0.0))

                    logging.info(f"💰 Pre-flight balance check for {symbol}:")
                    logging.info(f"   Available: ${trading_balance:.2f}")
                    logging.info(f"   Required:  ${quantity:.2f}")

                    # Add 2% safety buffer for fees/rounding (Kraken typically takes 0.16-0.26%)
                    safety_buffer = quantity * 0.02  # 2% buffer
                    required_with_buffer = quantity + safety_buffer

                    if trading_balance < required_with_buffer:
                        error_msg = f"Insufficient funds: ${trading_balance:.2f} available, ${required_with_buffer:.2f} required (with 2% fee buffer)"
                        logging.error(f"❌ PRE-FLIGHT CHECK FAILED: {error_msg}")
                        logging.error(f"   Bot detected ${trading_balance:.2f} but needs ${required_with_buffer:.2f} for this order")
                        logging.error(f"   This prevents 'EOrder:Insufficient funds' rejection from Kraken API")

                        # Return unfilled status to prevent API call
                        return {
                            "status": "unfilled",
                            "error": "INSUFFICIENT_FUND",
                            "message": error_msg,
                            "partial_fill": False,
                            "filled_pct": 0.0
                        }
                    else:
                        logging.info(f"   ✅ Balance sufficient: ${trading_balance:.2f} available >= ${required_with_buffer:.2f} required")

            # ✅ CRITICAL FIX: Convert USD quantity to base currency volume for Kraken
            # Kraken's AddOrder API expects 'volume' in base currency (e.g., number of tokens)
            # not in quote currency (USD). When size_type='quote', we need to convert.
            #
            # Example: To buy $9.16 worth of FIDA at $0.97/FIDA:
            #   volume = $9.16 / $0.97 = 9.44 FIDA (base currency)
            #
            # This fixes "volume minimum not met" errors when trades are auto-resized
            # to tier limits but the USD amount is too small to meet minimum volume requirements.
            #
            # NOTE: SELL orders always use size_type='base' (selling specific token quantity),
            # so this conversion is only needed for BUY orders with size_type='quote'.
            volume_for_order = quantity  # Default: use quantity as-is

            if size_type == 'quote' and side.lower() == 'buy':
                # For BUY orders with quote currency (USD), convert to base currency
                logging.debug(f"🔄 Converting USD quantity to base currency volume for Kraken")
                logging.debug(f"   Quote amount (USD): ${quantity:.2f}")

                # Get current market price for conversion
                current_price = self.get_current_price(symbol)

                if not current_price or current_price <= 0:
                    error_msg = f"Cannot convert USD to volume: price unavailable for {symbol}"
                    logging.error(f"❌ {error_msg}")
                    logging.error(f"   USD amount: ${quantity:.2f}")
                    logging.error(f"   Price: {current_price}")
                    return {
                        "status": "error",
                        "error": "PRICE_UNAVAILABLE",
                        "message": error_msg
                    }

                # Convert USD to base currency volume
                volume_for_order = quantity / current_price
                logging.info(f"📊 USD to Volume Conversion:")
                logging.info(f"   USD amount: ${quantity:.2f}")
                logging.info(f"   Price: ${current_price:.8f}")
                logging.info(f"   Volume (base): {volume_for_order:.8f}")

                # ✅ VALIDATION: Check if converted volume meets Kraken minimums
                # This prevents "volume minimum not met" rejections
                if validate_order_size:
                    is_valid, validation_error = validate_order_size(
                        pair=kraken_symbol,
                        volume=volume_for_order,
                        price=current_price,
                        side=side
                    )

                    if not is_valid:
                        logging.error(LOG_SEPARATOR)
                        logging.error("❌ KRAKEN ORDER VALIDATION FAILED")
                        logging.error(LOG_SEPARATOR)
                        logging.error(f"   Symbol: {kraken_symbol}")
                        logging.error(f"   USD amount: ${quantity:.2f}")
                        logging.error(f"   Converted volume: {volume_for_order:.8f}")
                        logging.error(f"   Price: ${current_price:.8f}")
                        logging.error(f"   Validation error: {validation_error}")
                        logging.error("   ⚠️  Trade size too small after conversion")
                        logging.error(LOG_SEPARATOR)
                        return {
                            "status": "error",
                            "error": "VOLUME_TOO_SMALL",
                            "message": validation_error
                        }

                    logging.info(f"   ✅ Volume validation passed: {volume_for_order:.8f} meets Kraken minimums")

            # ── Fix 5: Maker-preferred orders ────────────────────────────────
            # When NIJA_PREFER_MAKER_ORDERS=true (default), place a post-only
            # limit order at the current price so the order rests in the book
            # and pays the maker fee (~0.16 %) instead of the taker fee (~0.26 %).
            # This cuts round-trip fees nearly in half.
            #
            # Kraken post-only: ordertype=limit + oflags=post
            #   • If the order would cross the spread and fill immediately, Kraken
            #     rejects it with "EOrder:Post only order".  We catch that rejection
            #     and fall back to a plain market order so execution is never lost.
            #   • For SELL orders we fetch the current price here (reuses the price
            #     already fetched for BUY conversions above when available).
            _prefer_maker = os.environ.get("NIJA_PREFER_MAKER_ORDERS", "true").lower() not in ("0", "false", "no")

            if _prefer_maker:
                # Reuse current_price already fetched above; fetch if not yet set.
                _maker_price = locals().get('current_price') or None
                if not _maker_price or _maker_price <= 0:
                    try:
                        _maker_price = self.get_current_price(symbol)
                    except Exception:
                        _maker_price = None

                if _maker_price and _maker_price > 0:
                    order_params = {
                        'pair':      kraken_symbol,
                        'type':      order_type,
                        'ordertype': 'limit',
                        'price':     str(round(_maker_price, 8)),
                        'volume':    str(volume_for_order),
                        'oflags':    'post',   # post-only — guarantees maker fill
                    }
                    logging.info(
                        f"📌 MAKER order [{symbol}]: {order_type} {volume_for_order:.8f} "
                        f"@ ${_maker_price:.8f} (post-only, oflags=post)"
                    )
                else:
                    # Price unavailable — fall back to market silently
                    _prefer_maker = False

            if not _prefer_maker:
                order_params = {
                    'pair':      kraken_symbol,
                    'type':      order_type,
                    'ordertype': 'market',
                    'volume':    str(volume_for_order),
                }

            # Determine API category: ENTRY for buy, EXIT for sell
            if KrakenAPICategory is not None:
                api_category = KrakenAPICategory.ENTRY if side.lower() == 'buy' else KrakenAPICategory.EXIT
            else:
                api_category = None

            result = self._kraken_private_call('AddOrder', order_params, category=api_category)

            # ── Maker-order fallback: retry as market if post-only was rejected ──
            if (
                _prefer_maker
                and result
                and result.get('error')
                and any('Post only' in str(e) or 'post only' in str(e).lower() for e in result['error'])
            ):
                logging.warning(
                    f"⚠️  Post-only order rejected for {symbol} (would cross spread) — "
                    f"retrying as market order"
                )
                fallback_params = {
                    'pair':      kraken_symbol,
                    'type':      order_type,
                    'ordertype': 'market',
                    'volume':    str(volume_for_order),
                }
                result = self._kraken_private_call('AddOrder', fallback_params, category=api_category)

            # ✅ SAFETY CHECK #2: Hard-stop on rejected orders
            # DO NOT allow rejected orders to be recorded as successful trades
            if result and 'error' in result and result['error']:
                error_msgs = ', '.join(result['error'])
                logging.error(LOG_SEPARATOR)
                logging.error("❌ KRAKEN ORDER REJECTED - ABORTING")
                logging.error(LOG_SEPARATOR)
                logging.error(f"   Symbol: {kraken_symbol}, Side: {order_type}, Volume: {volume_for_order:.8f}")
                if size_type == 'quote' and side.lower() == 'buy':
                    logging.error(f"   Original USD amount: ${quantity:.2f}")
                logging.error(f"   Rejection Reason: {error_msgs}")
                logging.error("   ⚠️  ORDER REJECTED - DO NOT RECORD TRADE")
                logging.error(LOG_SEPARATOR)
                # Return error status to prevent recording this as a successful trade
                return {"status": "error", "error": error_msgs}

            # ✅ REQUIREMENT 1: VERIFY TXID EXISTS (no txid → no trade → nothing visible)
            if result and 'result' in result:
                order_result = result['result']
                txid = order_result.get('txid', [])
                order_id = txid[0] if txid else None

                # ✅ SAFETY CHECK #3: Require txid before recording position
                # If no txid → trade not executed → return error
                if not order_id:
                    account_label = f"{self.account_identifier}" if hasattr(self, 'account_identifier') else "UNKNOWN"
                    logging.error(LOG_SEPARATOR)
                    logging.error(f"❌ KRAKEN ORDER FAILED - NO TXID RETURNED")
                    logging.error(LOG_SEPARATOR)
                    logging.error(f"   Account: {account_label}")
                    logging.error(f"   Symbol: {kraken_symbol}, Side: {order_type}, Quantity: {quantity}")
                    logging.error(f"   API Response: {result}")
                    logging.error("   ⚠️  NO TRADE EXECUTED - Kraken must return txid for valid order")
                    logging.error(LOG_SEPARATOR)
                    # Return error status to prevent recording this as a successful trade
                    return {"status": "error", "error": "No txid returned from Kraken - order did not execute"}

                logging.info(f"✅ Kraken txid received: {order_id}")

                # Enhanced trade confirmation logging with account identification
                account_label = f"{self.account_identifier}" if hasattr(self, 'account_identifier') else "UNKNOWN"

                # FIRST LIVE TRADE BANNER (for legal/operational protection)
                global _FIRST_TRADE_EXECUTED
                with _FIRST_TRADE_LOCK:
                    if not _FIRST_TRADE_EXECUTED:
                        _FIRST_TRADE_EXECUTED = True
                        logging.info("")
                        logging.info(LOG_SEPARATOR)
                        logging.info("🚨 FIRST LIVE TRADE EXECUTED 🚨")
                        logging.info(LOG_SEPARATOR)
                        logging.info(f"   Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
                        logging.info(f"   Symbol: {kraken_symbol}")
                        logging.info(f"   Size: {quantity} (base currency)")
                        logging.info(f"   Account: {account_label}")
                        logging.info(f"   Side: {order_type.upper()}")
                        logging.info(f"   Exchange: Kraken")
                        logging.info("")
                        logging.info("   This confirms live trading is operational.")
                        logging.info("   All subsequent trades will be logged normally.")
                        logging.info(LOG_SEPARATOR)
                        logging.info("")

                logging.info(LOG_SEPARATOR)
                logging.info(f"✅ TRADE CONFIRMATION - {account_label}")
                logging.info(LOG_SEPARATOR)
                logging.info(f"   Exchange: Kraken")
                logging.info(f"   Order Type: {order_type.upper()}")
                logging.info(f"   Symbol: {kraken_symbol}")
                logging.info(f"   Quantity: {quantity}")
                logging.info(f"   Order ID: {order_id}")
                logging.info(f"   Account: {account_label}")
                logging.info(f"   Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")
                logging.info(LOG_SEPARATOR)

                # Flush logs immediately to ensure confirmation is visible
                if _root_logger.handlers:
                    for handler in _root_logger.handlers:
                        handler.flush()

                # COPY TRADING: Emit trade signal for platform account trades
                # This allows user accounts to replicate platform trades automatically
                try:
                    # Only emit signals for PLATFORM accounts (not USER accounts)
                    if self.account_type == AccountType.PLATFORM:
                        from trade_signal_emitter import emit_trade_signal

                        # Get current balance for position sizing
                        balance_data = self.get_account_balance_detailed()
                        platform_balance = balance_data.get('trading_balance', 0.0) if balance_data else 0.0

                        # Get current price for this symbol
                        # For market orders, use a reasonable estimate
                        # In future, could fetch actual execution price from order details
                        exec_price = 0.0
                        try:
                            # Try to get current market price using public API
                            # Ticker is a public endpoint, so we use query_public instead of _kraken_private_call
                            # Suppress pykrakenapi's print() statements
                            with suppress_pykrakenapi_prints():
                                ticker_result = self.api.query_public('Ticker', {'pair': kraken_symbol})
                            if ticker_result and 'result' in ticker_result:
                                ticker_data = ticker_result['result'].get(kraken_symbol, {})
                                if ticker_data:
                                    # Use last trade price if available
                                    last_price = ticker_data.get('c', [0.0])[0]  # 'c' is last trade closed array [price, lot volume]
                                    exec_price = float(last_price) if last_price else 0.0
                        except Exception as price_err:
                            logger.debug(f"Could not fetch execution price: {price_err}")

                        # Determine broker name
                        broker_name = self.broker_type.value.lower() if hasattr(self, 'broker_type') else 'kraken'

                        # Determine size_type (Kraken uses base currency quantity for market orders)
                        size_type = 'base'

                        logger.info("📡 Emitting trade signal to copy engine")

                        # Emit signal
                        signal_emitted = emit_trade_signal(
                            broker=broker_name,
                            symbol=symbol,  # Use original symbol format (e.g., BTC-USD)
                            side=side,
                            price=exec_price if exec_price else 0.0,
                            size=quantity,
                            size_type=size_type,
                            order_id=order_id,
                            platform_balance=platform_balance
                        )

                        # ENHANCED COPY TRADING: Also trigger direct on_platform_trade hook
                        # This provides a simplified interface for copy trading implementations
                        try:
                            from bot.kraken_copy_trading import on_platform_trade  # type: ignore[import]

                            # Build trade object for hook
                            trade_obj = {
                                'symbol': symbol,
                                'side': side,
                                'size': quantity,
                                'platform_balance': platform_balance,
                                'price': exec_price if exec_price else 0.0,
                                'order_id': order_id,
                                'broker': broker_name
                            }

                            logger.info("🎯 Triggering on_platform_trade hook for direct copy execution")
                            on_platform_trade(trade_obj)
                            logger.info("✅ on_platform_trade hook completed")
                        except ImportError:
                            logger.debug("on_platform_trade hook not available (expected for non-copy-trading setups)")
                        except Exception as hook_err:
                            logger.warning(f"⚠️ on_platform_trade hook failed: {hook_err}")
                            logger.warning(f"   Copy trading may not execute properly")

                        # Confirm signal emission status
                        if signal_emitted:
                            logger.info(f"✅ Trade signal emitted successfully for {symbol} {side}")
                        else:
                            logger.error(f"❌ Trade signal emission FAILED for {symbol} {side}")
                            logger.error("   ⚠️ User accounts will NOT copy this trade!")
                except Exception as signal_err:
                    # Don't fail the trade if signal emission fails
                    logger.warning(f"   ⚠️ Trade signal emission failed: {signal_err}")
                    logger.warning(f"   ⚠️ User accounts will NOT copy this trade!")
                    logger.warning(f"   Traceback: {traceback.format_exc()}")

                return {
                    "status": "filled",
                    "order_id": order_id,
                    "symbol": kraken_symbol,
                    "side": order_type,
                    "quantity": quantity,
                    "account": account_label  # Add account identification to result
                }

            logger.error("❌ Kraken order failed: No result data")
            return {"status": "error", "error": "No result data"}

        except NoncePauseActive as _npa:
            # Nonce trading pause is active — fail fast instead of sleeping.
            # The nonce recovery runs asynchronously; this cycle is skipped and
            # the next scan will retry automatically.
            logger.warning("⚠️  NONCE PAUSE: %s", _npa)
            logger.warning("   Skipping cycle — will retry next scan")
            return {
                "status": "nonce_skip",
                "error": "NONCE_PAUSE",
                "message": str(_npa),
            }

        except Exception as e:
            logger.error(f"Kraken order error: {e}")
            return {"status": "error", "error": str(e)}

    def get_positions(self) -> List[Dict]:
        """
        Get open positions (non-zero balances) enriched with current prices.

        Returns:
            list: List of position dicts with symbol, quantity, currency,
                  current_price, and size_usd. Prices are batch-fetched in
                  a single Ticker API call to minimise rate-limit pressure.
        """
        try:
            if not self.api:
                return []

            # Get account balance using serialized API call
            # Use MONITORING category for balance checks (conservative rate limiting)
            balance_category = KrakenAPICategory.MONITORING if KrakenAPICategory is not None else None
            balance = self._kraken_private_call('Balance', category=balance_category)

            if balance and 'error' in balance and balance['error']:
                error_msgs = ', '.join(balance['error'])
                logger.error(f"Error fetching Kraken positions: {error_msgs}")
                return []

            if not (balance and 'result' in balance):
                return []

            result = balance['result']
            raw_positions = []  # (symbol, currency, balance_val, kraken_pair)

            for asset, amount in result.items():
                balance_val = float(amount)

                # Skip USD/USDT and zero balances
                if asset in ['ZUSD', 'USDT'] or balance_val <= 0:
                    continue

                # Convert Kraken asset codes to standard format
                # XXBT -> BTC, XETH -> ETH, etc.
                currency = asset
                if currency.startswith('X') and len(currency) == 4:
                    currency = currency[1:]
                if currency == 'XBT':
                    currency = 'BTC'

                # CRITICAL FIX: Create symbol with dash separator to avoid ambiguity
                # This prevents ARBUSD being misinterpreted as ARB-BUSD instead of ARB-USD
                # Always use dash separator for Kraken symbols: ARB-USD, ETH-USD, etc.
                symbol = f'{currency}-USD'

                # CRITICAL FIX: Filter out unsupported symbols before adding to positions
                # This prevents orphaned positions from unsupported pairs (e.g., BUSD-based)
                if not self.supports_symbol(symbol):
                    logger.debug(f"⏭️ Skipping unsupported position: {symbol} (balance: {balance_val} {currency})")
                    continue

                # Determine Kraken pair name for batch Ticker fetch
                kraken_pair = None
                if convert_to_kraken is not None:
                    try:
                        kraken_pair = convert_to_kraken(symbol)
                    except Exception:
                        pass

                raw_positions.append((symbol, currency, balance_val, kraken_pair))

            if not raw_positions:
                return []

            # Batch-fetch current prices for all positions in ONE Ticker API call.
            # Kraken Ticker accepts a comma-separated list of pairs, so we avoid
            # N individual per-symbol price calls (each rate-limited at ~5-30s).
            batch_prices: Dict[str, float] = {}
            kraken_pairs = [kp for _, _, _, kp in raw_positions if kp]
            if kraken_pairs:
                try:
                    pair_str = ','.join(kraken_pairs)
                    with suppress_pykrakenapi_prints():
                        ticker_result = self.api.query_public('Ticker', {'pair': pair_str})
                    if ticker_result and 'result' in ticker_result:
                        for pair_key, ticker_data in ticker_result['result'].items():
                            last_price_arr = ticker_data.get('c', [None])
                            if last_price_arr and last_price_arr[0]:
                                try:
                                    batch_prices[pair_key.upper()] = float(last_price_arr[0])
                                except (ValueError, TypeError):
                                    pass
                except Exception as _ticker_err:
                    logger.warning(f"Batch Ticker fetch failed, prices will be fetched per-symbol: {_ticker_err}")

            positions = []
            for symbol, currency, balance_val, kraken_pair in raw_positions:
                # Look up price from batch result; fall back to individual fetch
                current_price = 0.0
                if kraken_pair and kraken_pair.upper() in batch_prices:
                    current_price = batch_prices[kraken_pair.upper()]
                elif kraken_pair:
                    # Fallback: individual price fetch (slower, but correct for edge cases)
                    try:
                        fetched = self.get_current_price(symbol)
                        if fetched and fetched > 0:
                            current_price = fetched
                    except Exception:
                        pass

                # Skip positions we cannot price — cannot determine tradability without a price
                if current_price <= 0:
                    logger.debug(
                        f"⏭️ Skipping {symbol}: price unavailable "
                        f"(cannot determine tradability)"
                    )
                    continue

                size_usd = balance_val * current_price

                # Skip true dust positions (below the hard floor).
                # Positions between DUST_THRESHOLD_USD and the exchange minimum order
                # size are still returned here; the trading strategy applies a
                # higher filter (EXCHANGE_MIN_ORDER_SIZE) when counting positions.
                if size_usd < DUST_THRESHOLD_USD:
                    logger.debug(
                        f"⏭️ Skipping dust position {symbol}: "
                        f"qty={balance_val}, value=${size_usd:.4f}"
                    )
                    continue

                positions.append({
                    'symbol': symbol,
                    'quantity': balance_val,
                    'currency': currency,
                    'current_price': current_price,
                    'size_usd': size_usd,
                })

            return positions

        except Exception as e:
            logger.error(f"Error fetching Kraken positions: {e}")
            return []

    def get_real_entry_price(self, symbol: str) -> Optional[float]:
        """
        Get real entry price for *symbol* with three layers of resilience:

        1. **In-memory cache** — return immediately if already fetched this session.
        2. **Local entry price store** — check the JSON-backed store populated when
           trades execute; avoids redundant API calls after restarts.
        3. **Kraken TradesHistory API** — up to 3 retries (backoff: 1.5 s, 3 s, 4.5 s).

        Successful results are cached permanently in memory and in the local store.

        Args:
            symbol: Standard format symbol (e.g., 'BTC-USD', 'ETH-USD')

        Returns:
            Volume-weighted average entry price if found, None otherwise
        """
        # ── Layer 1: in-memory permanent cache ────────────────────────────────
        with self._entry_price_cache_lock:
            cached = self._entry_price_cache.get(symbol)
        if cached is not None:
            return cached

        # ── Layer 2: local entry price store (JSON) ───────────────────────────
        if _ENTRY_PRICE_STORE_AVAILABLE and _get_eps is not None:
            try:
                local_price = _get_eps().get(symbol)
                if local_price and local_price > 0:
                    logger.debug(f"[EntryPrice] {symbol}: Using local store price ${local_price:.6g}")
                    with self._entry_price_cache_lock:
                        self._entry_price_cache[symbol] = local_price
                    return local_price
            except Exception as _eps_err:
                logger.debug(f"[EntryPrice] {symbol}: local store lookup failed: {_eps_err}")

        # ── Layer 3: Kraken TradesHistory API (3× retry with backoff) ─────────
        if not self.api:
            logger.debug(f"[EntryPrice] {symbol}: Kraken API not connected")
            return None

        # Convert standard symbol to Kraken pair format for filtering
        kraken_pair = None
        if convert_to_kraken is not None:
            kraken_pair = convert_to_kraken(symbol)

        symbol_currency = symbol.replace('-USD', '').replace('-USDT', '')
        match_pairs: set = set()
        if kraken_pair:
            match_pairs.add(kraken_pair.upper())
        match_pairs.add(f"X{symbol_currency}ZUSD")
        match_pairs.add(f"{symbol_currency}USD")
        match_pairs.add(f"X{symbol_currency}ZUSDT")
        match_pairs.add(f"{symbol_currency}USDT")
        match_pairs.add(f"{symbol_currency}/USD")
        match_pairs.add(f"{symbol_currency}/USDT")

        last_exc = None
        _deadline = time.monotonic() + _TRADE_HISTORY_TIMEOUT_SECONDS
        for attempt in range(3):
            # Hard-stop: don't start a new attempt after the wall-clock deadline
            if time.monotonic() > _deadline:
                logger.warning(
                    f"[EntryPrice] {symbol}: trade history deadline exceeded "
                    f"({_TRADE_HISTORY_TIMEOUT_SECONDS}s) — skipping remaining retries"
                )
                break
            try:
                history_category = KrakenAPICategory.MONITORING if KrakenAPICategory is not None else None
                response = self._kraken_private_call('TradesHistory', category=history_category)

                if not response or 'result' not in response:
                    logger.debug(f"[EntryPrice] {symbol}: No trade history response")
                    return None

                if response.get('error'):
                    error_msgs = ', '.join(response['error'])
                    logger.warning(f"[EntryPrice] {symbol}: Kraken TradesHistory error: {error_msgs}")
                    return None

                trades = response['result'].get('trades', {})
                if not trades:
                    logger.debug(f"[EntryPrice] {symbol}: No trade history found")
                    return None

                # Collect all BUY trades for this symbol
                buy_trades = []
                for _tid, trade in trades.items():
                    trade_pair = trade.get('pair', '').upper()
                    if trade.get('type', '').lower() != 'buy':
                        continue
                    pair_matches = (
                        trade_pair in match_pairs
                        or symbol_currency.upper() in trade_pair
                    )
                    if not pair_matches:
                        continue
                    try:
                        price = float(trade.get('price', 0))
                        vol = float(trade.get('vol', 0))
                        trade_time = float(trade.get('time', 0))
                        if price > 0 and vol > 0:
                            buy_trades.append((trade_time, price, vol))
                    except (ValueError, TypeError):
                        continue

                if not buy_trades:
                    logger.debug(f"[EntryPrice] {symbol}: No BUY trades found in Kraken history")
                    return None

                # VWAP of all found BUY trades (most recent first)
                buy_trades.sort(key=lambda t: t[0], reverse=True)
                total_vol = sum(vol for _, _, vol in buy_trades)
                vwap = sum(price * vol for _, price, vol in buy_trades) / total_vol

                logger.info(
                    f"[EntryPrice] {symbol}: Fetched ${vwap:.4f} from Kraken history "
                    f"(VWAP of {len(buy_trades)} buy trade(s))"
                )
                # Persist to in-memory cache and local store
                with self._entry_price_cache_lock:
                    self._entry_price_cache[symbol] = vwap
                if _ENTRY_PRICE_STORE_AVAILABLE and _get_eps is not None:
                    try:
                        _get_eps().save(symbol, vwap)
                    except Exception:
                        pass
                return vwap

            except Exception as exc:
                last_exc = exc
                if attempt < 2:
                    delay = 1.5 * (attempt + 1)
                    logger.warning(
                        f"[EntryPrice] {symbol}: Kraken TradesHistory attempt {attempt + 1}/3 failed "
                        f"({exc}); retrying in {delay:.1f}s"
                    )
                    time.sleep(delay)

        logger.warning(f"[EntryPrice] {symbol}: All 3 Kraken attempts failed ({last_exc})")
        return None

    def get_bulk_entry_prices(self, symbols: List[str]) -> Dict[str, float]:
        """
        Bulk fetch entry prices from Kraken trade history for multiple symbols at once.

        Fetches paginated TradesHistory once and builds a symbol→VWAP entry price map.
        Far more efficient than calling get_real_entry_price() individually for each symbol
        (one API call instead of N calls, each rate-limited at ~30s each).

        Args:
            symbols: List of standard format symbols (e.g., ['BTC-USD', 'ETH-USD'])

        Returns:
            Dict mapping symbol -> VWAP entry price from most recent BUY trades.
            Symbols with no BUY trades found are absent from the dict.
        """
        if not self.api or not symbols:
            return {}

        # ── Bulk entry price cache (TTL) ──────────────────────────────────────
        # Return the cached result when it is still fresh — this prevents a
        # blocking TradesHistory API call on every adoption cycle.
        if (self._bulk_entry_prices_cache
                and self._bulk_entry_prices_cache_time is not None
                and (time.time() - self._bulk_entry_prices_cache_time) < _BULK_PRICE_CACHE_TTL_SECONDS):
            _cache_age = time.time() - self._bulk_entry_prices_cache_time
            logger.debug(
                f"   Bulk entry price cache hit "
                f"({len(self._bulk_entry_prices_cache)} symbol(s), "
                f"age {_cache_age:.0f}s / TTL {_BULK_PRICE_CACHE_TTL_SECONDS}s)"
            )
            return dict(self._bulk_entry_prices_cache)

        entry_prices: Dict[str, float] = {}

        try:
            logger.info(f"   📋 Bulk-fetching entry prices for {len(symbols)} symbols from Kraken trade history...")

            # Build match-pair sets for every requested symbol.
            # Kraken returns pairs in many formats (e.g. XXBTZUSD, XBTUSD, BTC/USD),
            # so we pre-build all known variants to avoid per-symbol re-computation.
            symbol_match_sets: Dict[str, tuple] = {}
            for symbol in symbols:
                symbol_currency = symbol.replace('-USD', '').replace('-USDT', '')
                match_pairs: set = set()
                if convert_to_kraken is not None:
                    try:
                        kraken_pair = convert_to_kraken(symbol)
                        if kraken_pair:
                            match_pairs.add(kraken_pair.upper())
                    except Exception:
                        pass
                # Common Kraken pair variants
                match_pairs.update([
                    f"X{symbol_currency}ZUSD",
                    f"{symbol_currency}USD",
                    f"X{symbol_currency}ZUSDT",
                    f"{symbol_currency}USDT",
                    f"{symbol_currency}/USD",
                    f"{symbol_currency}/USDT",
                ])
                symbol_match_sets[symbol] = (symbol_currency, match_pairs)

            # Accumulate BUY trades per symbol across paginated TradesHistory pages.
            # Kraken returns up to 50 trades per page; we page until we have prices for
            # all symbols or exhaust available history (up to MAX_PAGES × 50 trades).
            all_buy_trades: Dict[str, list] = {}   # symbol -> [(trade_time, price, vol)]
            history_category = KrakenAPICategory.MONITORING if KrakenAPICategory is not None else None
            MAX_PAGES = 5  # Cap at 250 trades — keeps the fetch within the hard timeout
            offset = 0
            total_trade_count = None  # filled from first response
            _bulk_deadline = time.monotonic() + _TRADE_HISTORY_TIMEOUT_SECONDS

            for page in range(MAX_PAGES):
                # Hard wall-clock deadline — don't start another page after timeout
                if time.monotonic() > _bulk_deadline:
                    logger.warning(
                        f"   Bulk fetch: wall-clock deadline ({_TRADE_HISTORY_TIMEOUT_SECONDS}s) "
                        f"exceeded after {page} page(s) — stopping early"
                    )
                    break

                params = {'ofs': offset} if offset > 0 else {}
                response = self._kraken_private_call('TradesHistory', params, category=history_category)

                if not response or 'result' not in response:
                    logger.debug(f"   Bulk fetch: no result on page {page + 1} (offset={offset})")
                    break

                if response.get('error'):
                    error_msgs = ', '.join(response['error'])
                    logger.warning(f"   Bulk fetch TradesHistory error: {error_msgs}")
                    break

                result = response['result']
                trades = result.get('trades', {})
                if total_trade_count is None:
                    total_trade_count = result.get('count', 0)

                if not trades:
                    break

                # Match each BUY trade to a requested symbol
                for _trade_id, trade in trades.items():
                    if trade.get('type', '').lower() != 'buy':
                        continue

                    trade_pair = trade.get('pair', '').upper()

                    for symbol, (symbol_currency, match_pairs) in symbol_match_sets.items():
                        if trade_pair in match_pairs or symbol_currency.upper() in trade_pair:
                            try:
                                price = float(trade.get('price', 0))
                                vol = float(trade.get('vol', 0))
                                trade_time = float(trade.get('time', 0))
                                if price > 0 and vol > 0:
                                    all_buy_trades.setdefault(symbol, []).append((trade_time, price, vol))
                            except (ValueError, TypeError):
                                pass
                            break  # Each trade belongs to at most one symbol

                offset += len(trades)

                # Stop early once we've found prices for every requested symbol
                if len(all_buy_trades) >= len(symbols):
                    logger.debug(f"   Bulk fetch: found prices for all {len(symbols)} symbols after {page + 1} page(s)")
                    break

                # Stop if we've consumed all available trades
                if total_trade_count is not None and offset >= total_trade_count:
                    break

            # Compute VWAP per symbol from accumulated BUY trades
            for symbol, trades_data in all_buy_trades.items():
                if not trades_data:
                    continue
                total_vol = sum(vol for _, _, vol in trades_data)
                if total_vol > 0:
                    vwap = sum(price * vol for _, price, vol in trades_data) / total_vol
                    entry_prices[symbol] = vwap
                    logger.debug(f"   {symbol}: VWAP entry price ${vwap:.4f} ({len(trades_data)} buy trade(s))")

            found_count = len(entry_prices)
            missing_count = len(symbols) - found_count
            logger.info(
                f"   ✅ Bulk entry prices: {found_count}/{len(symbols)} found"
                + (f", {missing_count} not found in trade history" if missing_count else "")
            )

            # Persist results in the TTL cache so subsequent adoption cycles are instant
            if entry_prices:
                self._bulk_entry_prices_cache = dict(entry_prices)
                self._bulk_entry_prices_cache_time = time.time()

        except Exception as e:
            logger.warning(f"   Bulk entry price fetch failed: {e}")

        return entry_prices

    def get_candles(self, symbol: str, timeframe: str, count: int) -> List[Dict]:
        """
        Get historical candle data from Kraken.

        Args:
            symbol: Trading pair (e.g., 'BTC-USD' or 'XBTUSD')
            timeframe: Candle interval ('1m', '5m', '15m', '1h', '1d', etc.)
            count: Number of candles to fetch (max 720)

        Returns:
            list: List of candle dicts with OHLCV data
        """
        try:
            if not self.kraken_api:
                return []

            # CRITICAL FIX: Use symbol mapper to convert to Kraken format
            # This ensures we use the correct format (e.g., XETHZUSD, XXBTZUSD)
            # instead of incorrect formats like ETHUSD, BTCUSD
            kraken_symbol = None
            normalized_symbol = normalize_symbol_for_broker(symbol, self.broker_type.value)

            if convert_to_kraken:
                kraken_symbol = convert_to_kraken(normalized_symbol)
                if not kraken_symbol:
                    logger.error(f"❌ Cannot convert {symbol} to Kraken format for candles")
                    return []
            else:
                # Fallback: Manual conversion if symbol mapper not available
                kraken_symbol = normalized_symbol.replace('-', '').upper()
                if kraken_symbol.startswith('BTC'):
                    kraken_symbol = kraken_symbol.replace('BTC', 'XBT', 1)

            # Map timeframe to Kraken interval (in minutes)
            # Kraken supports: 1, 5, 15, 30, 60, 240, 1440, 10080, 21600
            interval_map = {
                "1m": 1,
                "5m": 5,
                "15m": 15,
                "30m": 30,
                "1h": 60,
                "4h": 240,
                "1d": 1440
            }

            kraken_interval = interval_map.get(timeframe.lower(), 5)

            # Fetch OHLC data using pykrakenapi
            # CRITICAL FIX: pykrakenapi 0.3.2 retries indefinitely on RemoteDisconnected.
            # Wrap in a 15-second thread timeout so a broken connection never hangs the
            # position-analysis loop for hours (root cause of 13,000s+ pre-scan times).
            _ohlc_result_holder = [None]
            _ohlc_err_holder    = [None]
            _kraken_symbol_cap  = kraken_symbol
            _kraken_interval_cap = kraken_interval
            def _fetch_ohlc():
                try:
                    with suppress_pykrakenapi_prints():
                        _ohlc_result_holder[0] = self.kraken_api.get_ohlc_data(
                            _kraken_symbol_cap,
                            interval=_kraken_interval_cap,
                            ascending=True,
                        )
                except Exception as _oe:
                    _ohlc_err_holder[0] = _oe
            _ohlc_thread = threading.Thread(target=_fetch_ohlc, daemon=True)
            _ohlc_thread.start()
            _ohlc_thread.join(15)  # 15-second hard cap per candle fetch
            if _ohlc_thread.is_alive():
                logging.warning(
                    f"⏱️  get_ohlc_data for {symbol} timed out (15s) — returning []"
                )
                return []
            if _ohlc_err_holder[0] is not None:
                raise _ohlc_err_holder[0]
            ohlc, last = _ohlc_result_holder[0]

            # Convert to standard format (vectorised – avoids iterrows overhead)
            tail = ohlc.tail(count)
            timestamps = [int(ts.timestamp()) for ts in tail.index]
            ohlcv_data = tail[['open', 'high', 'low', 'close', 'volume']].astype(float).values
            candles = [
                {'time': ts, 'open': o, 'high': h, 'low': l, 'close': c, 'volume': v}
                for ts, (o, h, l, c, v) in zip(timestamps, ohlcv_data)
            ]

            return candles

        except Exception as e:
            logging.error(f"Error fetching Kraken candles: {e}")
            return []

    def supports_asset_class(self, asset_class: str) -> bool:
        """
        Kraken supports multiple asset classes.

        - Crypto: Spot trading via Kraken API (fully supported)
        - Futures: Via Kraken Futures API (enabled)
        - Stocks: Via AlpacaBroker integration (use AlpacaBroker for stocks)
        - Options: In development by Kraken (not yet available)

        Returns:
            bool: True if asset class is supported
        """
        supported = asset_class.lower() in ["crypto", "cryptocurrency", "futures"]
        return supported

    def get_all_products(self) -> list:
        """
        Get list of all tradeable cryptocurrency and futures pairs from Kraken.

        Includes:
        - Crypto spot pairs (BTC-USD, ETH-USD, etc.)
        - Futures pairs (if enable_futures is True in config)

        Returns:
            List of trading pairs in standard format (e.g., ['BTC-USD', 'ETH-USD', 'BTC-PERP', ...])
        """
        # ── Instance-level product cache (4-hour TTL) ─────────────────────────
        # Avoids repeated get_tradable_asset_pairs() + _initialize_kraken_market_data()
        # calls within a session, which are the dominant source of pre-scan overhead.
        _now = time.time()
        if (
            hasattr(self, '_kraken_products_cache')
            and self._kraken_products_cache
            and (_now - self._kraken_products_cache_time) < self._kraken_products_cache_ttl
        ):
            _cache_age_min = int((_now - self._kraken_products_cache_time) / 60)
            logging.debug(
                f"[KrakenProducts] Returning cached product list "
                f"({len(self._kraken_products_cache)} pairs, age {_cache_age_min}m)"
            )
            return list(self._kraken_products_cache)

        try:
            if not self.kraken_api:
                logging.warning("⚠️  Kraken not connected, cannot fetch products")
                return []

            # Initialize symbol mapper with API data for dynamic symbol detection
            # This prevents "Unknown asset pair" errors by building a complete symbol map
            if get_kraken_symbol_mapper:
                try:
                    mapper = get_kraken_symbol_mapper()
                    mapper.initialize_from_api(self.kraken_api)
                    logging.debug("✅ Symbol mapper initialized with Kraken API data")
                except Exception as mapper_err:
                    logging.warning(f"⚠️  Could not initialize symbol mapper: {mapper_err}")

            # CRITICAL FIX (Jan 23, 2026): Initialize market data for dynamic minimum volumes
            # This prevents "volume minimum not met" rejections by fetching actual pair minimums
            self._initialize_kraken_market_data()

            # Fetch tradable asset pairs with retry + exponential backoff
            asset_pairs = None
            _max_fetch_attempts = 3
            _fetch_delay = 2.0
            for _attempt in range(1, _max_fetch_attempts + 1):
                try:
                    with suppress_pykrakenapi_prints():
                        asset_pairs = self.kraken_api.get_tradable_asset_pairs()
                    break  # success — exit retry loop
                except Exception as _fetch_err:
                    if _attempt < _max_fetch_attempts:
                        logging.warning(
                            f"⚠️  Kraken get_tradable_asset_pairs attempt {_attempt}/{_max_fetch_attempts} "
                            f"failed: {_fetch_err} — retrying in {_fetch_delay:.0f}s"
                        )
                        time.sleep(_fetch_delay)
                        _fetch_delay = min(_fetch_delay * 2.0, 30.0)
                    else:
                        logging.warning(
                            f"⚠️  Kraken get_tradable_asset_pairs failed after {_max_fetch_attempts} "
                            f"attempts: {_fetch_err}"
                        )

            if asset_pairs is None:
                raise RuntimeError("get_tradable_asset_pairs returned no data after retries")

            # Extract pairs that trade against USD or USDT
            symbols = []
            futures_count = 0
            spot_count = 0

            # Iterate over DataFrame rows using iterrows()
            # pykrakenapi returns DataFrame with pair info including 'wsname' column
            for pair_name, pair_info in asset_pairs.iterrows():
                # Kraken uses format like 'XXBTZUSD' for BTC/USD
                # Convert to our standard format BTC-USD
                # Access DataFrame column value - pair_info is a pandas Series
                wsname = pair_info.get('wsname', '')
                if wsname and ('USD' in wsname or 'USDT' in wsname):
                    # Convert from Kraken format to standard format
                    # e.g., BTC/USD -> BTC-USD
                    symbol = wsname.replace('/', '-')

                    # Detect futures pairs (contain 'PERP', 'F0', or quarter codes like 'Z24', 'H25')
                    # Kraken futures typically have symbols like BTC-PERP, ETH-F0, BTC-Z24
                    is_futures = any(x in symbol for x in ['PERP', 'F0', 'F1', 'F2', 'F3', 'F4'])

                    if is_futures:
                        futures_count += 1
                        # Only add futures if enabled in config
                        from bot.broker_configs.kraken_config import KRAKEN_CONFIG
                        if KRAKEN_CONFIG.enable_futures:
                            symbols.append(symbol)
                    else:
                        spot_count += 1
                        symbols.append(symbol)

            logging.info(f"📊 Kraken: Found {spot_count} spot pairs + {futures_count} futures pairs = {len(symbols)} total tradable USD/USDT pairs")

            # Populate instance cache so subsequent calls within the TTL are instant
            if symbols:
                self._kraken_products_cache = list(symbols)
                self._kraken_products_cache_time = time.time()

            return symbols

        except Exception as e:
            logging.warning(f"⚠️  Error fetching Kraken products: {e}")
            # Return a comprehensive fallback list covering the most-liquid Kraken USD pairs.
            # Intentionally larger (100 pairs) to give the bot meaningful coverage
            # even when the API is temporarily unavailable.
            fallback_pairs = [
                # Majors
                'BTC-USD', 'ETH-USD', 'SOL-USD', 'XRP-USD', 'ADA-USD', 'DOGE-USD',
                'DOT-USD', 'LINK-USD', 'AVAX-USD', 'ATOM-USD', 'LTC-USD', 'ALGO-USD',
                'XLM-USD', 'UNI-USD', 'MATIC-USD',
                # Mid-caps
                'FIL-USD', 'AAVE-USD', 'COMP-USD', 'MKR-USD', 'SNX-USD', 'YFI-USD',
                'SUSHI-USD', 'CRV-USD', '1INCH-USD', 'BAL-USD', 'REN-USD', 'KNC-USD',
                'ZRX-USD', 'ENJ-USD', 'MANA-USD', 'SAND-USD', 'GRT-USD', 'LRC-USD',
                'BAND-USD', 'BAT-USD', 'OGN-USD', 'OMG-USD', 'OCEAN-USD', 'ANKR-USD',
                # Alt layer-1 / layer-2
                'NEAR-USD', 'FLOW-USD', 'ICP-USD', 'VET-USD', 'EOS-USD', 'TRX-USD',
                'XTZ-USD', 'THETA-USD', 'EGLD-USD', 'HBAR-USD', 'ONE-USD', 'KLAY-USD',
                'CELO-USD', 'ZIL-USD', 'ICX-USD', 'ONT-USD', 'IOST-USD', 'QTUM-USD',
                'NEO-USD', 'WAVES-USD', 'ZEC-USD', 'DASH-USD', 'XMR-USD', 'ETC-USD',
                'BCH-USD',
                # DeFi / newer
                'APE-USD', 'APT-USD', 'ARB-USD', 'OP-USD', 'SUI-USD', 'INJ-USD',
                'FTM-USD', 'ROSE-USD', 'RNDR-USD', 'IMX-USD', 'CHZ-USD', 'AXS-USD',
                'GMT-USD', 'STX-USD', 'CFG-USD', 'KSM-USD', 'SCRT-USD', 'KAVA-USD',
                'GLMR-USD', 'CTSI-USD', 'ALICE-USD',
                # USDT variants of top pairs
                'BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'XRP-USDT', 'ADA-USDT',
                'AVAX-USDT', 'DOGE-USDT', 'DOT-USDT', 'MATIC-USDT', 'LINK-USDT',
            ]
            logging.info(f"📊 Kraken: Using fallback list of {len(fallback_pairs)} crypto pairs")
            return fallback_pairs


class OKXBroker(BaseBroker):
    """
    OKX Exchange integration for crypto spot and futures trading.

    Features:
    - Spot trading (USDT pairs)
    - Futures/perpetual contracts
    - Testnet support for paper trading
    - Advanced order types

    Documentation: https://www.okx.com/docs-v5/en/
    Python SDK: https://github.com/okx/okx-python-sdk
    """

    def __init__(self, account_type: AccountType = AccountType.PLATFORM, user_id: Optional[str] = None):
        super().__init__(BrokerType.OKX, account_type=account_type, user_id=user_id)
        self.client = None
        self.account_api = None
        self.market_api = None
        self.trade_api = None
        self.use_testnet = False

        # Balance tracking for fail-closed behavior (Jan 19, 2026)
        # When balance fetch fails, preserve last known balance instead of returning 0
        self._last_known_balance = None  # Last successful balance fetch
        self._balance_fetch_errors = 0   # Count of consecutive errors
        self._is_available = True        # Broker availability flag

        # Initialize position tracker for profit-based exits.
        # OKX is a degraded optional broker — a position-tracker failure puts the
        # instance into degraded mode rather than crashing startup entirely.
        self.position_tracker = None
        try:
            from position_tracker import PositionTracker
            # Resolve an absolute path for the data directory so the tracker works
            # regardless of the current working directory, and create it with
            # restrictive permissions (0o750) to prevent world-readable config files.
            _okx_data_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data'
            )
            os.makedirs(_okx_data_dir, mode=0o750, exist_ok=True)
            _okx_positions_file = os.path.join(_okx_data_dir, "positions.json")
            self.position_tracker = PositionTracker(storage_file=_okx_positions_file)
            logger.info("✅ Position tracker initialized for profit-based exits")
        except Exception as e:
            logger.warning(
                "⚠️ OKX position tracker unavailable (degraded optional broker): %s", e
            )
            self._is_available = False

    def connect(self) -> bool:
        """
        Connect to OKX Exchange API with retry logic.

        Requires environment variables:
        - OKX_API_KEY: Your OKX API key
        - OKX_API_SECRET: Your OKX API secret
        - OKX_PASSPHRASE: Your OKX API passphrase
        - OKX_USE_TESTNET: 'true' for testnet, 'false' for live (optional, default: false)

        Returns:
            bool: True if connected successfully
        """
        try:
            from okx.api import Account, Market, Trade
            import time

            # Support per-user credentials for USER accounts:
            #   OKX_USER_{USERID}_API_KEY / _API_SECRET / _PASSPHRASE
            if self.account_type == AccountType.USER and self.user_id:
                _short_env, _full_env = _user_env_prefix(self.user_id)
                api_key = os.getenv(f"OKX_USER_{_short_env}_API_KEY", "").strip()
                api_secret = os.getenv(f"OKX_USER_{_short_env}_API_SECRET", "").strip()
                passphrase = os.getenv(f"OKX_USER_{_short_env}_PASSPHRASE", "").strip()
                # Fallback: full user_id in uppercase
                if (not api_key or not api_secret or not passphrase) and _full_env != _short_env:
                    api_key = api_key or os.getenv(f"OKX_USER_{_full_env}_API_KEY", "").strip()
                    api_secret = api_secret or os.getenv(f"OKX_USER_{_full_env}_API_SECRET", "").strip()
                    passphrase = passphrase or os.getenv(f"OKX_USER_{_full_env}_PASSPHRASE", "").strip()
                if not api_key or not api_secret or not passphrase:
                    logging.info(
                        "ℹ️  OKX USER credentials not configured for %s "
                        "(checked OKX_USER_%s_API_KEY / _API_SECRET / _PASSPHRASE) — skipping",
                        self.user_id, _short_env,
                    )
                    return False
            else:
                api_key = os.getenv("OKX_API_KEY", "").strip()
                api_secret = os.getenv("OKX_API_SECRET", "").strip()
                passphrase = os.getenv("OKX_PASSPHRASE", "").strip()
            self.use_testnet = os.getenv("OKX_USE_TESTNET", "false").lower() in ["true", "1", "yes"]

            if not api_key or not api_secret or not passphrase:
                # Partial credentials are more likely a misconfiguration — warn at WARNING level
                missing = []
                if not api_key:
                    missing.append("OKX_API_KEY")
                if not api_secret:
                    missing.append("OKX_API_SECRET")
                if not passphrase:
                    missing.append("OKX_PASSPHRASE")
                have_any = bool(api_key or api_secret or passphrase)
                if have_any:
                    logging.warning(
                        "⚠️  OKX credentials partially configured — missing: %s (skipping OKX)",
                        ", ".join(missing),
                    )
                else:
                    logging.info("ℹ️  OKX credentials not configured (optional broker — skipping)")
                return False


            # Check for placeholder passphrase (most common user error)
            # Note: Only checking passphrase because API keys are UUIDs/hex without obvious placeholder patterns
            if passphrase in PLACEHOLDER_PASSPHRASE_VALUES:
                logging.warning("⚠️  OKX passphrase appears to be a placeholder value")
                logging.warning("   Please set a valid OKX_PASSPHRASE in your environment")
                logging.warning("   Current value looks like a placeholder (e.g., 'your_passphrase')")
                logging.warning("   Replace it with your actual OKX API passphrase from https://www.okx.com/account/my-api")
                return False

            # Determine API flag (0 = live, 1 = testnet)
            flag = "1" if self.use_testnet else "0"

            # Initialize OKX API clients
            self.account_api = Account(api_key, api_secret, passphrase, flag)
            self.market_api = Market(api_key, api_secret, passphrase, flag)
            self.trade_api = Trade(api_key, api_secret, passphrase, flag)

            # Test connection by fetching account balance with retry logic
            # Increased max attempts for 403 "too many errors" which indicates temporary API key blocking
            # Note: 403 differs from 429 (rate limiting) - it means the API key was temporarily blocked
            max_attempts = 5
            base_delay = 5.0  # Increased from 2.0 to allow API key blocks to reset

            for attempt in range(1, max_attempts + 1):
                try:
                    if attempt > 1:
                        # Add delay before retry with exponential backoff
                        # For 403 errors, we need longer delays: 5s, 10s, 20s, 40s (attempts 2-5)
                        delay = base_delay * (2 ** (attempt - 2))
                        logging.info(f"🔄 Retrying OKX connection in {delay}s (attempt {attempt}/{max_attempts})...")
                        time.sleep(delay)

                    result = self.account_api.get_balance()

                    if result and result.get('code') == '0':
                        self.connected = True

                        if attempt > 1:
                            logging.info(f"✅ Connected to OKX API (succeeded on attempt {attempt})")

                        env_type = "🧪 TESTNET" if self.use_testnet else "🔴 LIVE"
                        logging.info("=" * 70)
                        logging.info(f"✅ OKX CONNECTED ({env_type})")
                        logging.info("=" * 70)

                        # Log account info
                        data = result.get('data', [])
                        if data and len(data) > 0:
                            total_eq = data[0].get('totalEq', '0')
                            logging.info(f"   Total Account Value: ${float(total_eq):.2f}")

                        logging.info("=" * 70)
                        return True
                    else:
                        error_msg = result.get('msg', 'Unknown error') if result else 'No response'

                        # Check if error is retryable
                        is_retryable = any(keyword in error_msg.lower() for keyword in [
                            'timeout', 'connection', 'network', 'rate limit',
                            'too many requests', 'service unavailable',
                            '503', '504', '429', '403', 'forbidden',
                            'too many errors', 'temporary', 'try again'
                        ])

                        if is_retryable and attempt < max_attempts:
                            logging.warning(f"⚠️  OKX connection attempt {attempt}/{max_attempts} failed (retryable): {error_msg}")
                            continue
                        else:
                            logging.warning(f"⚠️  OKX connection test failed: {error_msg}")
                            return False

                except Exception as e:
                    error_msg = str(e)

                    # Check if error is retryable (rate limiting, network issues, 403 errors, etc.)
                    # CRITICAL: Include 403, forbidden, and "too many errors" as retryable
                    # These indicate API key blocking and need longer cooldown periods
                    is_retryable = any(keyword in error_msg.lower() for keyword in [
                        'timeout', 'connection', 'network', 'rate limit',
                        'too many requests', 'service unavailable',
                        '503', '504', '429', '403', 'forbidden',
                        'too many errors', 'temporary', 'try again'
                    ])

                    if is_retryable and attempt < max_attempts:
                        logging.warning(f"⚠️  OKX connection attempt {attempt}/{max_attempts} failed (retryable): {error_msg}")
                        continue
                    else:
                        # Handle authentication errors gracefully
                        # Note: OKX error code 50119 = "API key doesn't exist"
                        error_str = error_msg.lower()
                        if 'api key' in error_str or '401' in error_str or 'authentication' in error_str or '50119' in error_str:
                            logging.warning("⚠️  OKX authentication failed - invalid or expired API credentials")
                            logging.warning("   Please check your OKX_API_KEY, OKX_API_SECRET, and OKX_PASSPHRASE")
                        elif 'connection' in error_str or 'network' in error_str or 'timeout' in error_str:
                            logging.warning("⚠️  OKX connection failed - network issue or API unavailable")
                        else:
                            logging.warning(f"⚠️  OKX connection failed: {e}")
                        return False

            # Should never reach here, but just in case
            logging.error("❌ Failed to connect to OKX after maximum retry attempts")
            return False

        except ImportError as e:
            # SDK not installed or import failed
            logging.error("❌ OKX connection failed: SDK import error")
            logging.error(f"   ImportError: {e}")
            logging.error("   The OKX SDK (okx) failed to import")
            logging.error("")
            logging.error("   📋 Troubleshooting steps:")
            logging.error("      1. Verify okx is in requirements.txt")
            logging.error("      2. Check deployment logs for package installation errors")
            logging.error("      3. Try manual install: pip install okx")
            logging.error("      4. Check for dependency conflicts with: pip check")
            return False

    def get_account_balance(self, verbose: bool = True) -> float:
        """
        Get total equity (USDT + position values) with fail-closed behavior.

        CRITICAL FIX (Rule #3): Balance = CASH + POSITION VALUE
        Returns total equity (available cash + position market value), not just available balance.
        This ensures risk calculations and position sizing account for capital deployed in positions.

        CRITICAL FIX (Jan 19, 2026): Fail closed - not "balance = 0"
        - On error: Return last known balance (if available) instead of 0
        - Track consecutive errors to mark broker unavailable
        - Distinguish API errors from actual zero balance

        Args:
            verbose: If True, logs detailed balance breakdown (default: True)

        Returns:
            float: Total equity (available USDT + position values)
                   Returns last known balance on error (not 0)
        """
        try:
            if not self.account_api:
                # Not connected - return last known balance if available
                if self._last_known_balance is not None:
                    logger.warning(f"⚠️ OKX API not connected, using last known balance: ${self._last_known_balance:.2f}")
                    self._balance_fetch_errors += 1
                    if self._balance_fetch_errors >= BROKER_MAX_CONSECUTIVE_ERRORS:
                        self._is_available = False
                        logger.error(f"❌ OKX marked unavailable after {self._balance_fetch_errors} consecutive errors")
                    return self._last_known_balance
                else:
                    logger.error("❌ OKX API not connected and no last known balance")
                    self._balance_fetch_errors += 1
                    self._is_available = False
                    return 0.0

            # Get account balance (available cash)
            result = self.account_api.get_balance()

            if result and result.get('code') == '0':
                data = result.get('data', [])
                if data and len(data) > 0:
                    details = data[0].get('details', [])

                    # Find USDT balance
                    available = 0.0
                    for detail in details:
                        if detail.get('ccy') == 'USDT':
                            available = float(detail.get('availBal', 0))
                            break

                    # FIX Rule #3: Get position values and add to available cash
                    position_value = 0.0
                    try:
                        positions = self.get_positions()
                        for pos in positions:
                            symbol = pos.get('symbol', '')
                            quantity = pos.get('quantity', 0.0)
                            if symbol and quantity > 0:
                                # Get current price for this position
                                try:
                                    price = self.get_current_price(symbol)
                                    if price > 0:
                                        pos_value = quantity * price
                                        position_value += pos_value
                                        logger.debug(f"   Position {symbol}: {quantity:.8f} @ ${price:.2f} = ${pos_value:.2f}")
                                except Exception as price_err:
                                    logger.debug(f"   Could not price position {symbol}: {price_err}")
                                    # If we can't price a position, skip it rather than fail
                                    continue
                    except Exception as pos_err:
                        logger.debug(f"   Could not fetch positions: {pos_err}")
                        # Continue with just cash balance if positions can't be fetched

                    # Calculate total equity
                    total_equity = available + position_value

                    # Enhanced logging (only if verbose=True)
                    if verbose:
                        logger.info("=" * 70)
                        logger.info(f"💰 OKX Balance:")
                        logger.info(f"   ✅ Available USDT: ${available:.2f}")
                        if position_value > 0:
                            logger.info(f"   📊 Position Value: ${position_value:.2f}")
                            logger.info(f"   ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
                            logger.info(f"   💎 TOTAL EQUITY (Available + Positions): ${total_equity:.2f}")
                        else:
                            logger.info(f"   💎 TOTAL EQUITY: ${total_equity:.2f} (no positions)")
                        logger.info("=" * 70)
                    else:
                        # Minimal logging when verbose=False
                        logger.debug(f"OKX balance: ${total_equity:.2f}")

                    # SUCCESS: Update last known balance and reset error count
                    self._last_known_balance = total_equity
                    self._balance_fetch_errors = 0
                    self._is_available = True

                    return total_equity

                # No USDT found - treat as zero balance (not an error)
                if verbose:
                    logger.warning("⚠️  No USDT balance found in OKX account")
                # Update last known balance to 0 (this is a successful API call, just zero balance)
                self._last_known_balance = 0.0
                self._balance_fetch_errors = 0
                self._is_available = True
                return 0.0
            else:
                error_msg = result.get('msg', 'Unknown error') if result else 'No response'
                logger.error(f"❌ OKX API error fetching balance: {error_msg}")

                # Return last known balance instead of 0
                self._balance_fetch_errors += 1
                if self._balance_fetch_errors >= BROKER_MAX_CONSECUTIVE_ERRORS:
                    self._is_available = False
                    logger.error(f"❌ OKX marked unavailable after {self._balance_fetch_errors} consecutive errors")

                if self._last_known_balance is not None:
                    logger.warning(f"   ⚠️ Using last known balance: ${self._last_known_balance:.2f}")
                    return self._last_known_balance
                else:
                    logger.error(f"   ❌ No last known balance available, returning 0")
                    return 0.0

        except Exception as e:
            logger.error(f"❌ Exception fetching OKX balance: {e}")
            self._balance_fetch_errors += 1
            if self._balance_fetch_errors >= BROKER_MAX_CONSECUTIVE_ERRORS:
                self._is_available = False
                logger.error(f"❌ OKX marked unavailable after {self._balance_fetch_errors} consecutive errors")

            # Return last known balance instead of 0
            if self._last_known_balance is not None:
                logger.warning(f"   ⚠️ Using last known balance: ${self._last_known_balance:.2f}")
                return self._last_known_balance

            return 0.0

    def is_available(self) -> bool:
        """
        Check if OKX broker is available for trading.

        Returns False if there have been 3+ consecutive balance fetch errors.
        This prevents trading when the API is not working properly.

        Returns:
            bool: True if broker is available, False if unavailable
        """
        return self._is_available

    def get_error_count(self) -> int:
        """
        Get the number of consecutive balance fetch errors.

        Returns:
            int: Number of consecutive errors
        """
        return self._balance_fetch_errors

    def place_market_order(self, symbol: str, side: str, quantity: float) -> Dict:
        """
        Place market order on OKX.

        Args:
            symbol: Trading pair (e.g., 'BTC-USDT')
            side: 'buy' or 'sell'
            quantity: Order size in USDT (for buys) or base currency (for sells)

        Returns:
            dict: Order result with status, order_id, etc.
        """
        try:
            # 🔒 LAYER 1: BROKER ISOLATION CHECK
            _iso = _check_broker_isolation(self.broker_type, side)
            if _iso is not None:
                return _iso

            if not self.trade_api:
                return {"status": "error", "error": "Not connected to OKX"}

            # Convert symbol format if needed (BTC-USD -> BTC-USDT)
            okx_symbol = symbol.replace('-USD', '-USDT') if '-USD' in symbol else symbol

            # Determine order side (buy/sell)
            okx_side = side.lower()

            # Place market order
            # For spot trading: tdMode = 'cash'
            # For margin/futures: tdMode = 'cross' or 'isolated'
            result = self.trade_api.place_order(
                instId=okx_symbol,
                tdMode='cash',  # Spot trading mode
                side=okx_side,
                ordType='market',
                sz=str(quantity)
            )

            if result and result.get('code') == '0':
                data = result.get('data', [])
                if data and len(data) > 0:
                    order_id = data[0].get('ordId')
                    logging.info(f"✅ OKX order placed: {okx_side.upper()} {okx_symbol} (Order ID: {order_id})")
                    return {
                        "status": "filled",
                        "order_id": order_id,
                        "symbol": okx_symbol,
                        "side": okx_side,
                        "quantity": quantity
                    }

            error_msg = result.get('msg', 'Unknown error') if result else 'No response'
            logging.error(f"❌ OKX order failed: {error_msg}")
            return {"status": "error", "error": error_msg}

        except Exception as e:
            logging.error(f"OKX order error: {e}")
            return {"status": "error", "error": str(e)}

    def get_positions(self) -> List[Dict]:
        """
        Get open positions (non-zero balances) enriched with current prices.

        Batch-fetches all prices via the OKX tickers endpoint (one API call)
        to avoid N individual per-symbol price requests.

        Returns:
            list: List of position dicts with symbol, quantity, currency,
                  current_price, and size_usd.
        """
        try:
            if not self.account_api:
                return []

            # Get account balance to see all assets
            result = self.account_api.get_balance()

            if not (result and result.get('code') == '0'):
                return []

            data = result.get('data', [])
            if not data:
                return []

            details = data[0].get('details', [])
            raw_holdings = []
            for detail in details:
                ccy = detail.get('ccy')
                available = float(detail.get('availBal', 0))
                if ccy != 'USDT' and available > 0:
                    okx_symbol = f'{ccy}-USDT'
                    raw_holdings.append((ccy, available, okx_symbol))

            if not raw_holdings:
                return []

            # Batch-fetch prices for all holdings in one tickers call
            batch_prices: Dict[str, float] = {}
            if self.market_api:
                try:
                    tickers_result = self.market_api.get_tickers(instType='SPOT')
                    if tickers_result and tickers_result.get('code') == '0':
                        for ticker in tickers_result.get('data', []):
                            inst_id = ticker.get('instId', '')
                            try:
                                batch_prices[inst_id] = float(ticker.get('last', 0))
                            except (ValueError, TypeError):
                                pass
                except Exception as _ticker_err:
                    logger.warning(f"OKX batch ticker fetch failed: {_ticker_err}")

            positions = []
            for ccy, available, okx_symbol in raw_holdings:
                current_price = batch_prices.get(okx_symbol, 0.0)
                if current_price == 0.0:
                    # Fallback: individual ticker fetch
                    current_price = self.get_current_price(f'{ccy}-USD') or 0.0
                size_usd = available * current_price if current_price > 0 else 0.0
                positions.append({
                    'symbol': f'{ccy}-USD',
                    'quantity': available,
                    'currency': ccy,
                    'current_price': current_price,
                    'size_usd': size_usd,
                })

            return positions

        except Exception as e:
            logger.error(f"Error fetching OKX positions: {e}")
            return []

    def get_bulk_entry_prices(self, symbols: List[str]) -> Dict[str, float]:
        """
        Bulk fetch entry prices from OKX trade history for multiple symbols.

        Fetches fills (transaction history) for each symbol and computes VWAP
        of BUY trades. More efficient than individual calls when adopting many
        positions on startup.

        Args:
            symbols: Standard-format symbols (e.g., ['BTC-USD', 'ETH-USD'])

        Returns:
            Dict mapping symbol -> VWAP entry price.
        """
        if not self.trade_api or not symbols:
            return {}

        entry_prices: Dict[str, float] = {}
        logger.info(f"   📋 Bulk-fetching entry prices for {len(symbols)} symbols from OKX trade history...")

        for symbol in symbols:
            okx_symbol = symbol.replace('-USD', '-USDT') if '-USD' in symbol else symbol
            try:
                result = self.trade_api.get_fills(instId=okx_symbol, limit='100')
                if not (result and result.get('code') == '0'):
                    continue
                buy_fills = []
                for fill in result.get('data', []):
                    if fill.get('side', '').lower() == 'buy':
                        try:
                            price = float(fill.get('fillPx', 0))
                            qty = float(fill.get('fillSz', 0))
                            if price > 0 and qty > 0:
                                buy_fills.append((price, qty))
                        except (ValueError, TypeError):
                            pass
                if buy_fills:
                    total_qty = sum(q for _, q in buy_fills)
                    if total_qty > 0:
                        vwap = sum(p * q for p, q in buy_fills) / total_qty
                        entry_prices[symbol] = vwap
                        logger.debug(f"   {symbol}: VWAP entry ${vwap:.4f} ({len(buy_fills)} fill(s))")
            except Exception as _e:
                logger.debug(f"   Could not fetch OKX fills for {symbol}: {_e}")

        found = len(entry_prices)
        missing = len(symbols) - found
        logger.info(
            f"   ✅ Bulk entry prices: {found}/{len(symbols)} found"
            + (f", {missing} not found in trade history" if missing else "")
        )
        return entry_prices

    def get_candles(self, symbol: str, timeframe: str, count: int) -> List[Dict]:
        """
        Get historical candle data from OKX.

        Args:
            symbol: Trading pair (e.g., 'BTC-USDT')
            timeframe: Candle interval ('1m', '5m', '15m', '1H', '1D', etc.)
            count: Number of candles to fetch (max 100)

        Returns:
            list: List of candle dicts with OHLCV data
        """
        try:
            if not self.market_api:
                return []

            # Convert symbol format if needed
            okx_symbol = symbol.replace('-USD', '-USDT') if '-USD' in symbol else symbol

            # Map timeframe to OKX format
            # OKX uses: 1m, 3m, 5m, 15m, 30m, 1H, 2H, 4H, 6H, 12H, 1D, 1W, 1M
            timeframe_map = {
                "1m": "1m",
                "5m": "5m",
                "15m": "15m",
                "1h": "1H",
                "4h": "4H",
                "1d": "1D"
            }

            okx_timeframe = timeframe_map.get(timeframe.lower(), "5m")

            # Fetch candles
            result = self.market_api.get_candles(
                instId=okx_symbol,
                bar=okx_timeframe,
                limit=str(min(count, 100))  # OKX max is 100
            )

            if result and result.get('code') == '0':
                data = result.get('data', [])
                candles = []

                for candle in data:
                    # OKX candle format: [timestamp, open, high, low, close, volume, volumeCcy, volumeCcyQuote, confirm]
                    candles.append({
                        'time': int(candle[0]),
                        'open': float(candle[1]),
                        'high': float(candle[2]),
                        'low': float(candle[3]),
                        'close': float(candle[4]),
                        'volume': float(candle[5])
                    })

                return candles

            return []

        except Exception as e:
            logging.error(f"Error fetching OKX candles: {e}")
            return []

    def get_current_price(self, symbol: str) -> float:
        """
        Get current market price for a symbol.

        Args:
            symbol: Trading pair (e.g., 'BTC-USDT')

        Returns:
            float: Current price or 0.0 on error
        """
        try:
            if not self.market_api:
                return 0.0

            # Convert symbol format if needed
            okx_symbol = symbol.replace('-USD', '-USDT') if '-USD' in symbol else symbol

            # Get ticker data
            result = self.market_api.get_ticker(instId=okx_symbol)

            if result and result.get('code') == '0':
                data = result.get('data', [])
                if data and len(data) > 0:
                    last_price = data[0].get('last')
                    return float(last_price) if last_price else 0.0

            return 0.0

        except Exception as e:
            logging.debug(f"Error fetching OKX price for {symbol}: {e}")
            return 0.0

    def supports_asset_class(self, asset_class: str) -> bool:
        """OKX supports crypto spot and futures"""
        return asset_class.lower() in ["crypto", "futures"]

    def get_all_products(self) -> list:
        """
        Get list of all tradeable cryptocurrency pairs from OKX.

        Returns:
            List of trading pairs (e.g., ['BTC-USDT', 'ETH-USDT', ...])
        """
        try:
            if not self.market_api:
                logging.warning("⚠️  OKX not connected, cannot fetch products")
                return []

            # Get all trading instruments (spot trading)
            result = self.market_api.get_instruments(instType='SPOT')

            if result and result.get('code') == '0':
                instruments = result.get('data', [])

                # Extract symbols that trade against USDT
                symbols = []
                for inst in instruments:
                    inst_id = inst.get('instId', '')
                    # Filter for USDT pairs
                    if inst_id.endswith('-USDT') and inst.get('state') == 'live':
                        symbols.append(inst_id)

                logging.info(f"📊 OKX: Found {len(symbols)} tradeable USDT pairs")
                return symbols
            else:
                logging.warning(f"⚠️  OKX API returned error: {result.get('msg', 'Unknown error')}")
                return self._get_okx_fallback_pairs()

        except Exception as e:
            logging.warning(f"⚠️  Error fetching OKX products: {e}")
            return self._get_okx_fallback_pairs()

    def _get_okx_fallback_pairs(self) -> list:
        """Get fallback list of popular OKX trading pairs"""
        fallback_pairs = [
            'BTC-USDT', 'ETH-USDT', 'SOL-USDT', 'XRP-USDT', 'ADA-USDT', 'DOGE-USDT',
            'MATIC-USDT', 'DOT-USDT', 'LINK-USDT', 'UNI-USDT', 'AVAX-USDT', 'ATOM-USDT',
            'LTC-USDT', 'NEAR-USDT', 'ALGO-USDT', 'XLM-USDT', 'HBAR-USDT', 'APT-USDT'
        ]
        logging.info(f"📊 OKX: Using fallback list of {len(fallback_pairs)} crypto pairs")
        return fallback_pairs


# ---------------------------------------------------------------------------
# Execution Eligibility Layer
# ---------------------------------------------------------------------------

class BrokerEligibilityStatus(Enum):
    """Precise reason a broker is or is not eligible for execution routing.

    The three ineligibility states map directly to the three independent
    checks that constitute full eligibility:

        CONNECTED  ──┐
        HEALTHY    ──┤  ALL three required  →  ELIGIBLE
        NOT_QUARANTINED ──┘

    Having CONNECTED alone is not sufficient.  A quarantined broker may
    remain CONNECTED (for price feeds and exit orders) but must never
    receive new capital or new BUY routing.
    """

    ELIGIBLE                 = "ELIGIBLE"
    INELIGIBLE_DISCONNECTED  = "INELIGIBLE_DISCONNECTED"
    INELIGIBLE_UNHEALTHY     = "INELIGIBLE_UNHEALTHY"
    INELIGIBLE_QUARANTINED   = "INELIGIBLE_QUARANTINED"
    INELIGIBLE_EXIT_ONLY     = "INELIGIBLE_EXIT_ONLY"

    def is_eligible(self) -> bool:
        return self == BrokerEligibilityStatus.ELIGIBLE


class BrokerManager:
    """
    Manages multiple broker connections with independent operation.

    ARCHITECTURE (Jan 10, 2026 Update):
    ------------------------------------
    Each broker operates INDEPENDENTLY and should NOT affect other brokers.

    The "primary broker" concept exists only for backward compatibility:
    - Used by legacy single-broker code paths
    - Used for platform account position cap enforcement
    - Does NOT control independent broker trading

    For multi-broker trading, use IndependentBrokerTrader which:
    - Runs each broker in its own thread
    - Isolates errors between brokers
    - Prevents cascade failures
    - Ensures one broker's issues don't affect others

    CRITICAL: No broker should have automatic priority over others.
    Previously, Coinbase was automatically set as primary, which caused
    it to control trading decisions for all brokers. This has been fixed.
    """

    def __init__(self):
        self.brokers: Dict[BrokerType, BaseBroker] = {}
        self.active_broker: Optional[BaseBroker] = None
        self.primary_broker_type: Optional[BrokerType] = None
        self.platform_broker: Optional[BaseBroker] = None
        self.primary_broker: Optional[BaseBroker] = None
        self._platform_locked: bool = False

    def add_broker(self, broker: BaseBroker):
        """
        Add a broker to the manager.

        IMPORTANT: Each broker is independent and should be treated equally.
        No broker automatically becomes "primary" - this prevents one broker
        from controlling or affecting trading decisions for other brokers.

        To set a primary broker for legacy compatibility, explicitly call
        set_primary_broker() after adding brokers.
        """
        self.brokers[broker.broker_type] = broker

        # ── Platform-slot registration ───────────────────────────────────────
        # KRAKEN-FIRST RULE (Apr 2026): Kraken is the sole execution authority.
        # It must own the platform_broker / primary_broker slots.  Coinbase (or
        # any other non-Kraken broker) must never overwrite a Kraken entry here,
        # because once `_platform_locked` is set, set_primary_broker() is blocked
        # and the bot would be stuck on Coinbase for the rest of the session.
        account_type_val = getattr(broker.account_type, 'value', None)
        is_kraken = broker.broker_type == BrokerType.KRAKEN
        if account_type_val == "platform":
            kraken_already_primary = (
                self.platform_broker is not None
                and self.platform_broker.broker_type == BrokerType.KRAKEN
            )
            if is_kraken or not kraken_already_primary:
                # Register this broker as the execution authority only when it
                # is Kraken, or when no Kraken has been registered yet.
                self.platform_broker = broker
                self.primary_broker = broker
                self._platform_locked = True
                logger.info("✅ PLATFORM broker registered globally")
                logger.info(f"✅ {broker.broker_type.value} set as PRIMARY (execution authority)")
                logger.info("✅ Cross-account orchestration ENABLED")
            else:
                # Coinbase (or other non-Kraken) added after Kraken — do NOT
                # overwrite Kraken's authority in the platform/primary slots.
                logger.info(
                    f"✅ {broker.broker_type.value} registered (Kraken remains execution authority)"
                )

        # ── active_broker assignment ─────────────────────────────────────────
        # BUGFIX (Mar 2026): set_primary_broker() returns False when
        # _platform_locked=True, leaving active_broker=None and the bot showing
        # "NO TRADING ACTIVE".  We set active_broker directly here instead.
        #
        # KRAKEN-FIRST RULE (Apr 2026): If Kraken is added and is already
        # connected (late re-registration after a startup retry), it immediately
        # takes over as active_broker regardless of what was set before.
        if is_kraken and getattr(broker, 'connected', False):
            self.active_broker = broker
            self.primary_broker_type = BrokerType.KRAKEN
            logger.info("🎯 Kraken connected — promoted to active_broker (execution authority)")
        elif self.active_broker is None:
            self.active_broker = broker
            self.primary_broker_type = broker.broker_type
            logger.info(f"   First broker {broker.broker_type.value} set as active (for legacy compatibility)")

        logger.info(f"📊 Added {broker.broker_type.value} broker (independent operation)")

    def set_primary_broker(self, broker_type: BrokerType) -> bool:
        """
        Set a specific broker as the primary/active broker.

        NOTE: This method exists for backward compatibility with legacy code
        that expects a "primary" broker. In modern multi-broker architecture,
        each broker should operate independently via IndependentBrokerTrader.

        The primary broker is used only for:
        - Legacy single-broker trading logic
        - Position cap enforcement (shared across platform account)
        - Backward compatibility with older code

        It does NOT control or affect other brokers' independent trading.

        Args:
            broker_type: Type of broker to set as primary

        Returns:
            bool: True if successfully set as primary
        """
        # KRAKEN-FIRST RULE (Apr 2026): Kraken may always claim the primary slot
        # even when the platform is locked.  All other brokers are blocked so
        # they cannot silently take over execution authority from Kraken.
        if getattr(self, "_platform_locked", False) and broker_type != BrokerType.KRAKEN:
            return False  # 🔒 Only Kraken can override the platform lock

        if broker_type in self.brokers:
            self.active_broker = self.brokers[broker_type]
            self.primary_broker_type = broker_type
            logging.info(f"📌 PRIMARY BROKER SET: {broker_type.value}")
            return True
        else:
            logging.warning(f"⚠️  Cannot set {broker_type.value} as primary - not connected")
            return False

    # ── Execution Eligibility Layer ──────────────────────────────────────────
    # Single source of truth for "can this broker receive new BUY orders / capital".
    # All routing and capital-allocation paths MUST gate on this — never on
    # `connected` alone.  The three independent guards are:
    #   1. CONNECTED           — broker TCP connection is live
    #   2. HEALTHY             — venue health score ≥ firewall threshold
    #   3. NOT QUARANTINED     — nonce-poisoning quarantine is NOT active
    #   4. NOT EXIT_ONLY       — broker is not restricted to sell-side only
    # A broker that passes only subset of these guards is partially usable
    # (e.g. for price feeds or SELL execution) but must not receive new entries
    # or capital weight.

    def get_broker_eligibility(self, broker: BaseBroker) -> BrokerEligibilityStatus:
        """Return the precise eligibility status for *broker*.

        This is the authoritative eligibility check.  Callers that need a
        simple boolean should use :meth:`is_execution_eligible` instead.

        Checks are evaluated in priority order so the most actionable reason
        is returned first:

        1. Disconnected  → ``INELIGIBLE_DISCONNECTED``
        2. Quarantined   → ``INELIGIBLE_QUARANTINED``  (still connected — SELLs OK)
        3. Exit-only     → ``INELIGIBLE_EXIT_ONLY``    (still connected — SELLs OK)
        4. Unhealthy     → ``INELIGIBLE_UNHEALTHY``    (venue score below threshold)
        5. All clear     → ``ELIGIBLE``
        """
        if not getattr(broker, 'connected', False):
            return BrokerEligibilityStatus.INELIGIBLE_DISCONNECTED

        if (
            _kraken_quarantine_active
            and broker.broker_type == BrokerType.KRAKEN
        ):
            return BrokerEligibilityStatus.INELIGIBLE_QUARANTINED

        if getattr(broker, 'exit_only_mode', False):
            return BrokerEligibilityStatus.INELIGIBLE_EXIT_ONLY

        if _ERF_BM_AVAILABLE and _get_erf_bm is not None:
            try:
                if not _get_erf_bm().is_venue_healthy(broker.broker_type.value):
                    return BrokerEligibilityStatus.INELIGIBLE_UNHEALTHY
            except Exception:
                pass  # health check unavailable — treat as healthy

        return BrokerEligibilityStatus.ELIGIBLE

    def is_execution_eligible(self, broker: BaseBroker) -> bool:
        """Return ``True`` only when *broker* may receive new entries and capital.

        Convenience wrapper around :meth:`get_broker_eligibility` for use in
        filter expressions::

            eligible = [b for b in self.brokers.values()
                        if self.is_execution_eligible(b)]
        """
        return self.get_broker_eligibility(broker).is_eligible()

    def get_eligible_brokers(self) -> Dict[str, BaseBroker]:
        """Return ``{broker_type_value: broker}`` for every execution-eligible broker.

        Eligible means CONNECTED + HEALTHY + NOT QUARANTINED + NOT EXIT_ONLY.
        Use this for any routing or capital-allocation decision that involves
        new BUY orders.

        Returns:
            Ordered dict (insertion order) of eligible brokers.  Empty dict
            when no broker is currently eligible.
        """
        return {
            b.broker_type.value: b
            for b in self.brokers.values()
            if self.is_execution_eligible(b)
        }

    def get_primary_broker(self, prefer_platform: bool = False) -> Optional[BaseBroker]:
        """
        Get the current primary/active broker.

        This is the single authoritative resolution path for obtaining the
        active broker.  All code that needs a broker should call this method
        rather than reading ``self.active_broker`` directly.

        Parameters
        ----------
        prefer_platform:
            When ``True`` and the platform broker is connected, return it
            immediately regardless of ``active_broker``.  Useful for
            platform-level orchestration that must always use the platform
            account (e.g. position-cap enforcement, copy-trading).

        Resolution order
        ----------------
        1. Platform broker (when ``prefer_platform=True`` and connected).
        2. ``active_broker`` when it is connected.
        3. Score-based auto-promotion: rank all connected brokers by their
           ``BrokerPerformanceScorer`` composite score and promote the winner.
        4. Disconnected ``active_broker`` (legacy safety net).
        5. ``platform_broker`` → ``primary_broker`` (final fallback).

        Returns
        -------
        BaseBroker instance or None if no broker is active
        """
        # ── 1. Prefer platform broker ────────────────────────────────
        if prefer_platform and self.platform_broker is not None:
            if getattr(self.platform_broker, 'connected', False):
                return self.platform_broker

        # ── 1b. KRAKEN-FIRST execution-layer rule ─────────────────────────────
        # Bridges the gap between the platform-layer FSM (which may have promoted
        # Kraken) and the execution-layer ``active_broker`` slot (which may still
        # point to Coinbase from before a reconnect or from initial startup when
        # Kraken was added while disconnected).
        # When Kraken is connected, non-quarantined, and non-exit-only it always
        # takes priority so the execution router never sticks on Coinbase after a
        # Kraken recovery.
        if (
            not _kraken_quarantine_active
            and BrokerType.KRAKEN in self.brokers
        ):
            _kraken_broker = self.brokers[BrokerType.KRAKEN]
            if (
                getattr(_kraken_broker, 'connected', False)
                and not getattr(_kraken_broker, 'exit_only_mode', False)
            ):
                if self.active_broker is not _kraken_broker:
                    logger.info(
                        "🎯 KRAKEN-FIRST (execution): Kraken connected — "
                        "promoting to active_broker (was %s)",
                        self.active_broker.broker_type.value if self.active_broker else "none",
                    )
                    self.active_broker = _kraken_broker
                    self.primary_broker_type = BrokerType.KRAKEN
                return _kraken_broker

        # ── 2. Active broker is healthy ─────────────────────────────
        if self.active_broker is not None:
            if getattr(self.active_broker, 'connected', False):
                # ── 2a. Quarantine check — skip quarantined Kraken ────────
                # When nonce poisoning is confirmed, force a fallback to the
                # next available broker (Coinbase) so new entries are never
                # routed through a poisoned Kraken key.
                if (
                    _kraken_quarantine_active
                    and self.active_broker.broker_type == BrokerType.KRAKEN
                ):
                    fallback = next(
                        (
                            b for bt, b in self.brokers.items()
                            if bt != BrokerType.KRAKEN
                            and getattr(b, 'connected', False)
                            and not getattr(b, 'exit_only_mode', False)
                        ),
                        None,
                    )
                    if fallback is not None:
                        logger.warning(
                            "🔄 Kraken QUARANTINED (nonce poisoning) — "
                            "forced fallback to %s broker.",
                            fallback.broker_type.value,
                        )
                        self.active_broker = fallback
                        self.primary_broker_type = fallback.broker_type
                        return fallback
                    # No healthy fallback — allow Kraken to serve SELLs only.
                    logger.warning(
                        "⚠️  Kraken quarantined but no fallback broker is available; "
                        "Kraken will handle exits only."
                    )
                    return self.active_broker

                # ── 2b. Venue health check — route to highest-score venue ─────
                # When active_broker is connected but its venue health score has
                # degraded below the firewall threshold, bypass it and let the
                # promotion scan (step 3) pick the healthiest available venue.
                _venue_ok = True
                if _ERF_BM_AVAILABLE and _get_erf_bm is not None:
                    try:
                        _venue_ok = _get_erf_bm().is_venue_healthy(
                            self.active_broker.broker_type.value
                        )
                    except Exception:
                        pass
                if _venue_ok:
                    return self.active_broker
                logger.warning(
                    "⚠️ BrokerRouter: venue '%s' health degraded — "
                    "bypassing for promotion scan.",
                    self.active_broker.broker_type.value,
                )
                # Fall through to step 3 to pick the highest-score venue

        # ── 3. Health-score-based promotion ──────────────────────────────
        # Build the eligible candidate pool using consistent criteria:
        # connected, non-exit-only, non-quarantined.
        connected_brokers = {
            broker.broker_type.value: broker
            for broker in self.brokers.values()
            if (getattr(broker, 'connected', False)
                and not getattr(broker, 'exit_only_mode', False)
                and not (
                    _kraken_quarantine_active
                    and broker.broker_type == BrokerType.KRAKEN
                ))
        }

        if connected_brokers:
            # ── Health-score-first selection ──────────────────────────────
            # Pick the venue with the highest composite health score.  When the
            # firewall is unavailable fall back to the legacy KRAKEN-FIRST rule.
            best_broker: Optional[BaseBroker] = None
            if _ERF_BM_AVAILABLE and _get_erf_bm is not None:
                try:
                    best_venue = _get_erf_bm().get_best_venue(list(connected_brokers.keys()))
                    if best_venue is not None:
                        best_broker = connected_brokers.get(best_venue)
                except Exception:
                    pass

            # Legacy fallback: KRAKEN-FIRST when ERF is unavailable
            if best_broker is None and not _kraken_quarantine_active:
                best_broker = connected_brokers.get(BrokerType.KRAKEN.value)

            # Final fallback: BrokerPerformanceScorer composite score
            if best_broker is None:
                if _BROKER_PERFORMANCE_SCORER_AVAILABLE and _get_broker_performance_scorer is not None:
                    try:
                        scorer = _get_broker_performance_scorer()
                        best_name = scorer.get_best_broker(list(connected_brokers.keys()))
                        if best_name is not None:
                            best_broker = connected_brokers.get(best_name)
                    except Exception:
                        pass

            if best_broker is None:
                best_broker = next(iter(connected_brokers.values()))

            prev = self.active_broker.broker_type.value if self.active_broker else "none"
            logger.info(
                "🔄 BrokerRouter: health-score promotion %s → %s",
                prev, best_broker.broker_type.value,
            )
            self.active_broker = best_broker
            self.primary_broker_type = best_broker.broker_type
            return best_broker

        # No connected broker found — return the disconnected one for legacy compatibility
        if self.active_broker is not None:
            return self.active_broker

        # ── 4. Fallback ──────────────────────────────────────────────
        if self.platform_broker is not None:
            return self.platform_broker
        return self.primary_broker

    def select_primary_platform_broker(self):
        """
        Select the primary master broker with intelligent fallback logic.

        KRAKEN-FIRST RULE (Apr 2026): Kraken is always the execution authority
        for new entries.  If Kraken is connected and healthy it immediately
        takes the active_broker slot regardless of what was set before.

        Priority rules:
        1. Kraken connected & healthy → always PRIMARY (execution authority)
        2. If Coinbase is in exit_only mode → Kraken becomes PRIMARY for all new entries
        3. If current primary has insufficient balance → Promote Kraken to PRIMARY
        4. Coinbase exists ONLY for: Emergency exits, Position closures, Legacy compatibility

        This ensures the platform portfolio uses the correct broker for new entries.
        """
        if not self.active_broker and BrokerType.KRAKEN not in self.brokers:
            # No active broker AND no Kraken registered — try any connected broker
            # before giving up so Coinbase can serve as the sole execution authority.
            for _fb_type, _fb_broker in self.brokers.items():
                if getattr(_fb_broker, 'connected', False) and not getattr(_fb_broker, 'exit_only_mode', False):
                    self.active_broker = _fb_broker
                    self.primary_broker_type = _fb_type
                    logger.info(
                        "🔄 select_primary_platform_broker: no active broker — "
                        "promoted %s as primary (first connected broker)",
                        _fb_type.value,
                    )
                    return
            logger.warning("⚠️ No primary broker set - cannot select primary platform")
            return

        # ── KRAKEN-FIRST: Restore Kraken as active_broker whenever it is ─────
        # connected and healthy, even if Coinbase was promoted during a Kraken
        # outage.  This is the primary guard against the "stuck on Coinbase" bug.
        kraken_broker = self.brokers.get(BrokerType.KRAKEN)
        if (kraken_broker is not None
                and getattr(kraken_broker, 'connected', False)
                and not getattr(kraken_broker, 'exit_only_mode', False)
                and not _kraken_quarantine_active):
            if self.active_broker is None or self.active_broker.broker_type != BrokerType.KRAKEN:
                logger.info("🎯 Kraken connected — restoring as PRIMARY (execution authority)")
                self.active_broker = kraken_broker
                self.primary_broker_type = BrokerType.KRAKEN
                self.primary_broker = kraken_broker
            else:
                logger.debug("✅ Kraken already active_broker — no change needed")
            return

        if not self.active_broker:
            # Kraken is offline and no active_broker is set — promote the first
            # connected, non-exit-only broker so trading is not silently blocked.
            for _fb_type, _fb_broker in self.brokers.items():
                if getattr(_fb_broker, 'connected', False) and not getattr(_fb_broker, 'exit_only_mode', False):
                    self.active_broker = _fb_broker
                    self.primary_broker_type = _fb_type
                    logger.info(
                        "🔄 select_primary_platform_broker: Kraken offline, active_broker=None — "
                        "promoted %s as primary fallback",
                        _fb_type.value,
                    )
                    return
            logger.warning("⚠️ No primary broker set - cannot select primary platform")
            return

        # ✅ HARDENING: Short-circuit when the current broker is already healthy.
        # Avoids redundant balance API calls and Kraken promotion churn on every
        # cycle when nothing has changed.
        # A quarantined Kraken broker is NOT considered healthy for new entries.
        # A venue whose health score has fallen below the firewall threshold is
        # also NOT considered healthy — fall through to the promotion scan.
        kraken_is_quarantined = (
            _kraken_quarantine_active
            and self.active_broker.broker_type == BrokerType.KRAKEN
        )
        _venue_is_healthy = True
        if _ERF_BM_AVAILABLE and _get_erf_bm is not None:
            try:
                _venue_is_healthy = _get_erf_bm().is_venue_healthy(
                    self.active_broker.broker_type.value
                )
            except Exception:
                pass
        if (self.active_broker.connected
                and not getattr(self.active_broker, 'exit_only_mode', False)
                and not kraken_is_quarantined
                and _venue_is_healthy):
            logger.debug("✅ Active broker healthy — skipping promotion scan")
            return

        current_primary = self.active_broker.broker_type.value.upper()

        # FIX #2: Check if Coinbase is in exit_only mode (Kraken becomes PRIMARY)
        should_promote_kraken = False
        promotion_reason = ""

        # Primary check: Is the current broker in EXIT_ONLY mode?
        if self.active_broker.exit_only_mode:
            should_promote_kraken = True
            promotion_reason = f"{current_primary} in EXIT-ONLY mode"
            logger.info(f"🔍 {current_primary} is in EXIT_ONLY mode → Kraken will become PRIMARY for entries")
        else:
            # Secondary check: Does current broker have sufficient balance?
            try:
                balance = self.active_broker.get_account_balance()
                if balance < MINIMUM_TRADING_BALANCE:
                    should_promote_kraken = True
                    promotion_reason = f"{current_primary} balance (${balance:.2f}) < minimum (${MINIMUM_TRADING_BALANCE:.2f})"
                    logger.info(f"🔍 {current_primary} has insufficient balance: ${balance:.2f} < ${MINIMUM_TRADING_BALANCE:.2f}")
            except Exception as e:
                # Broker is unreachable — treat the same as insufficient balance so the
                # fallback scan below promotes Coinbase (or another live broker) instead
                # of silently leaving a disconnected Kraken as active_broker.
                should_promote_kraken = True
                promotion_reason = f"{current_primary} balance unavailable (exception: {e})"
                logger.warning(
                    "⚠️ Could not check balance for %s — treating as offline and "
                    "promoting fallback broker: %s",
                    current_primary, e,
                )

        if should_promote_kraken:
            # FIX #2: Promote Kraken to PRIMARY broker for all new entries
            if BrokerType.KRAKEN in self.brokers:
                kraken = self.brokers[BrokerType.KRAKEN]
                if kraken.connected and not kraken.exit_only_mode:
                    logger.info("=" * 70)
                    logger.info("🔄 KRAKEN PROMOTED TO PRIMARY BROKER (FIX #2)")
                    logger.info("=" * 70)
                    logger.info(f"   Reason: {promotion_reason}")
                    logger.info(f"   ✅ Kraken: PRIMARY for all new entries")
                    logger.info(f"   ✅ Coinbase: EXIT-ONLY (emergency sells, position closures)")
                    logger.info("=" * 70)
                    self.active_broker = kraken
                    self.primary_broker_type = BrokerType.KRAKEN
                    return
                else:
                    logger.warning(f"⚠️ Kraken not available for promotion")
                    logger.warning(f"   Connected: {kraken.connected}, Exit-Only: {getattr(kraken, 'exit_only_mode', 'unknown')}")
            else:
                logger.warning("⚠️ Kraken broker not configured - cannot promote to PRIMARY")
                logger.warning("   Add Kraken credentials to enable PRIMARY broker fallback")

            # BUGFIX (Mar 2026): When Kraken cannot be promoted, fall back to ANY connected,
            # non-exit-only broker rather than leaving active_broker pointing at a broken one.
            # This ensures Coinbase (or another exchange) is used when Kraken is unavailable.
            current_active_type = (
                self.active_broker.broker_type if self.active_broker is not None else None
            )
            for fb_type, fb_broker in self.brokers.items():
                if (fb_broker.connected
                        and not fb_broker.exit_only_mode
                        and fb_type != current_active_type):
                    logger.info(
                        f"🔄 Switching primary broker to {fb_type.value} "
                        f"(fallback — {current_primary} is unavailable)"
                    )
                    self.active_broker = fb_broker
                    self.primary_broker_type = fb_type
                    return

            logger.warning(
                f"⚠️ No connected, non-exit-only broker available as fallback "
                f"(staying with {current_primary})"
            )
        else:
            logger.debug(f"✅ Primary broker ({current_primary}) is ready for entries")

    def connect_all(self):
        """Connect to all configured brokers, platform accounts first.

        Connecting the platform (MASTER) Kraken account before any user
        accounts ensures the global nonce is stabilised before concurrent
        user-account threads begin issuing API calls.  This eliminates the
        most common source of startup nonce collisions on multi-account
        deployments.
        """
        logger.info("")
        logger.info("🔌 Connecting to brokers...")

        platform_brokers = [
            b for b in self.brokers.values()
            if getattr(b, "account_type", None) == AccountType.PLATFORM
        ]
        user_brokers = [
            b for b in self.brokers.values()
            if b not in platform_brokers
        ]

        # Step 1: connect platform broker(s) synchronously so the nonce is
        # fully stabilised before user accounts begin their connection handshake.
        for broker in platform_brokers:
            broker.connect()

        # Step 2: connect remaining (user / non-Kraken) brokers.
        for broker in user_brokers:
            broker.connect()

    def get_broker_for_symbol(self, symbol: str) -> Optional[BaseBroker]:
        """Get appropriate broker for a symbol, preferring the healthiest venue."""
        from market_adapter import market_adapter

        # Detect market type
        market_type = market_adapter.detect_market_type(symbol)

        # Map to asset class
        asset_class_map = {
            "crypto": "crypto",
            "stocks": "stocks",
            "futures": "futures",
            "options": "options"
        }

        asset_class = asset_class_map.get(market_type.value, "stocks")

        # Build the eligible candidates — execution-eligible + supports asset class.
        # Execution eligibility enforces CONNECTED + HEALTHY + NOT QUARANTINED +
        # NOT EXIT_ONLY so that quarantined/degraded venues never receive new orders.
        candidates = {
            broker.broker_type.value: broker
            for broker in self.brokers.values()
            if self.is_execution_eligible(broker) and broker.supports_asset_class(asset_class)
        }

        if not candidates:
            return None

        # Route to the venue with the highest health score
        if _ERF_BM_AVAILABLE and _get_erf_bm is not None:
            try:
                best_venue = _get_erf_bm().get_best_venue(list(candidates.keys()))
                if best_venue is not None and best_venue in candidates:
                    return candidates[best_venue]
            except Exception:
                pass

        # Fallback: first eligible broker
        return next(iter(candidates.values()))

    def get_health_weighted_capital_split(
        self, total_capital: float
    ) -> Dict[str, float]:
        """Allocate *total_capital* across execution-eligible brokers weighted by venue health.

        Only execution-eligible brokers (CONNECTED + HEALTHY + NOT QUARANTINED +
        NOT EXIT_ONLY) participate in capital allocation.  A quarantined broker
        such as Kraken during nonce poisoning is excluded from the pool entirely
        so no phantom capital is routed to it.

        A broker whose venue health score is twice that of another receives
        twice the capital.  Disabled venues (score below the firewall
        threshold) receive $0.  If all venues are disabled, capital is split
        equally so it is never stranded.

        Args:
            total_capital: USD amount to be distributed.

        Returns:
            ``{broker_type_value: usd_amount}`` mapping that sums to
            *total_capital*.  Returns ``{}`` when no eligible brokers exist.

        Example::

            split = manager.get_health_weighted_capital_split(1000.0)
            # → {"coinbase": 1000.0}  when kraken is quarantined
            # → {"kraken": 666.67, "coinbase": 333.33}  when both healthy (scores 80/40)
        """
        eligible_venues = [
            b.broker_type.value
            for b in self.brokers.values()
            if self.is_execution_eligible(b)
        ]
        if not eligible_venues:
            return {}

        def _equal_split() -> Dict[str, float]:
            # Adjust last entry so amounts sum exactly to total_capital.
            result: Dict[str, float] = {}
            running = 0.0
            for v in eligible_venues[:-1]:
                amt = round(total_capital / len(eligible_venues), 6)
                result[v] = amt
                running += amt
            result[eligible_venues[-1]] = round(total_capital - running, 6)
            return result

        if not (_ERF_BM_AVAILABLE and _get_erf_bm is not None):
            return _equal_split()

        try:
            weights = _get_erf_bm().get_capital_weights(eligible_venues)
        except Exception:
            return _equal_split()

        # Multiply weights × total_capital; last entry absorbs rounding residual.
        result: Dict[str, float] = {}
        running = 0.0
        items = list(weights.items())
        for v, w in items[:-1]:
            amt = round(w * total_capital, 6)
            result[v] = amt
            running += amt
        result[items[-1][0]] = round(total_capital - running, 6)
        return result

    def place_order(self, symbol: str, side: str, quantity: float) -> Dict:
        """Route order to appropriate broker"""
        broker = self.get_broker_for_symbol(symbol)

        if not broker:
            return {
                "status": "error",
                "error": f"No broker available for {symbol}"
            }

        logger.info(f"📤 Routing {side} order for {symbol} to {broker.broker_type.value}")
        return broker.place_market_order(symbol, side, quantity)

    def get_total_balance(self) -> float:
        """Get total USD balance across all brokers"""
        total = 0.0
        for broker in self.brokers.values():
            if broker.connected:
                total += broker.get_account_balance()
        return total

    def get_all_positions(self) -> List[Dict]:
        """Get positions from all brokers"""
        all_positions = []
        for broker_type, broker in self.brokers.items():
            if broker.connected:
                positions = broker.get_positions()
                for pos in positions:
                    pos['broker'] = broker_type.value
                all_positions.extend(positions)
        return all_positions

    def get_connected_brokers(self) -> List[str]:
        """Get list of connected broker names"""
        return [b.broker_type.value for b in self.brokers.values() if b.connected]

    def get_all_brokers(self) -> Dict[BrokerType, 'BaseBroker']:
        """
        Get all broker objects managed by this BrokerManager.
        
        Returns:
            Dict[BrokerType, BaseBroker]: Dictionary mapping broker types to broker instances.
            Returns a copy to prevent external modification of internal state.
        """
        return self.brokers.copy()

# Global instance
broker_manager = BrokerManager()

def get_broker_manager():
    """Get the global broker manager instance."""
    return broker_manager
