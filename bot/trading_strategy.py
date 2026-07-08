"""
NIJA Trading Strategy — TradingStrategy wrapper class
======================================================

This module provides the TradingStrategy class that orchestrates the NIJA
APEX v7.1 strategy across multiple brokers.

The heartbeat trade feature executes a small $5 test trade on startup to
verify all systems are operational before enabling full trading mode.

Author: NIJA Trading Systems
Version: 7.1
"""

from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
from contextlib import nullcontext
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from bot.pending_order_reconciler import reconcile_stale_pending_orders
except ImportError:
    try:
        from pending_order_reconciler import reconcile_stale_pending_orders  # type: ignore[import]
    except ImportError:
        reconcile_stale_pending_orders = None  # type: ignore[assignment]

logger = logging.getLogger("nija.trading_strategy")

# Balance calls must never stall startup/trade eligibility indefinitely.
BALANCE_FETCH_TIMEOUT = 12
CACHED_BALANCE_MAX_AGE_SECONDS = 90


def call_with_timeout(fn: Any, *args: Any, timeout_seconds: float = BALANCE_FETCH_TIMEOUT, **kwargs: Any) -> tuple[Any, Optional[BaseException]]:
    """Run ``fn`` in a daemon thread and return ``(result, error)``.

    The implementation intentionally avoids ``ThreadPoolExecutor`` context
    managers because they wait for timed-out worker threads during shutdown.
    Balance probes against exchanges such as Kraken can hang during bootstrap; a
    daemon thread plus a queue lets callers continue immediately after the
    timeout while still capturing normal return values and exceptions.
    """

    result_queue: "queue.Queue[tuple[str, Any]]" = queue.Queue(maxsize=1)

    def _runner() -> None:
        try:
            result_queue.put(("result", fn(*args, **kwargs)))
        except BaseException as exc:  # propagate to caller as the error slot
            result_queue.put(("error", exc))

    worker = threading.Thread(target=_runner, name="nija-call-with-timeout", daemon=True)
    worker.start()
    try:
        kind, payload = result_queue.get(timeout=max(0.0, float(timeout_seconds)))
    except queue.Empty:
        return None, TimeoutError(f"call_with_timeout timed out after {timeout_seconds}s")
    if kind == "error":
        return None, payload
    return payload, None

try:
    from bot.log_rate_limiter import get_log_rate_limiter
except ImportError:
    from log_rate_limiter import get_log_rate_limiter  # type: ignore[import]

try:
    from bot.runtime_correlation import runtime_correlation_scope
except ImportError:
    try:
        from runtime_correlation import runtime_correlation_scope  # type: ignore[import]
    except ImportError:
        from contextlib import contextmanager

        @contextmanager
        def runtime_correlation_scope(**_: Any):  # type: ignore[no-redef]
            yield {}

try:
    from bot.execution_venue_config import get_preferred_execution_venue
except ImportError:
    try:
        from execution_venue_config import get_preferred_execution_venue  # type: ignore[import]
    except ImportError:
        get_preferred_execution_venue = None  # type: ignore[assignment]

try:
    from bot.market_readiness_gate import MarketReadinessGate
    _MARKET_READINESS_GATE_AVAILABLE = True
except ImportError:
    try:
        from market_readiness_gate import MarketReadinessGate  # type: ignore[import]
        _MARKET_READINESS_GATE_AVAILABLE = True
    except ImportError:
        MarketReadinessGate = None  # type: ignore[assignment,misc]
        _MARKET_READINESS_GATE_AVAILABLE = False
        logger.warning("MarketReadinessGate not available — startup market probe will run degraded")

_HEARTBEAT_LOG_LIMITER = get_log_rate_limiter()


def _heartbeat_rate_limited_info(category: str, key: str, window_seconds: float, message: str, *args: Any) -> None:
    allowed, suppressed = _HEARTBEAT_LOG_LIMITER.allow_with_count(
        category=category,
        key=key,
        window_seconds=window_seconds,
    )
    if not allowed:
        return
    if suppressed:
        logger.debug(
            "[HeartbeatTrade] suppressed=%d category=%s key=%s",
            suppressed,
            category,
            key,
        )
    logger.info(message, *args)

# ---------------------------------------------------------------------------
# Optional imports — degrade gracefully when modules are unavailable
# ---------------------------------------------------------------------------

try:
    from bot.nija_apex_strategy_v71 import NIJAApexStrategyV71
    _APEX_AVAILABLE = True
except ImportError:
    try:
        from nija_apex_strategy_v71 import NIJAApexStrategyV71  # type: ignore[import]
        _APEX_AVAILABLE = True
    except ImportError:
        NIJAApexStrategyV71 = None  # type: ignore[assignment,misc]
        _APEX_AVAILABLE = False
        logger.warning("NIJAApexStrategyV71 not available — strategy will run in degraded mode")

try:
    from bot.broker_manager import BrokerType, KrakenBroker, CoinbaseBroker, BaseBroker
    _BROKER_MANAGER_AVAILABLE = True
except ImportError:
    try:
        from broker_manager import BrokerType, KrakenBroker, CoinbaseBroker, BaseBroker  # type: ignore[import]
        _BROKER_MANAGER_AVAILABLE = True
    except ImportError:
        BrokerType = None  # type: ignore[assignment,misc]
        KrakenBroker = None  # type: ignore[assignment,misc]
        CoinbaseBroker = None  # type: ignore[assignment,misc]
        BaseBroker = None  # type: ignore[assignment,misc]
        _BROKER_MANAGER_AVAILABLE = False
        logger.warning("broker_manager not available")

try:
    from bot.multi_account_broker_manager import MultiAccountBrokerManager
    _MABM_AVAILABLE = True
except ImportError:
    try:
        from multi_account_broker_manager import MultiAccountBrokerManager  # type: ignore[import]
        _MABM_AVAILABLE = True
    except ImportError:
        MultiAccountBrokerManager = None  # type: ignore[assignment,misc]
        _MABM_AVAILABLE = False

try:
    from bot.independent_broker_trader import IndependentBrokerTrader
    _IBT_AVAILABLE = True
except ImportError:
    try:
        from independent_broker_trader import IndependentBrokerTrader  # type: ignore[import]
        _IBT_AVAILABLE = True
    except ImportError:
        IndependentBrokerTrader = None  # type: ignore[assignment,misc]
        _IBT_AVAILABLE = False

try:
    from bot.broker_manager import BrokerManager
    _BM_AVAILABLE = True
except ImportError:
    try:
        from broker_manager import BrokerManager  # type: ignore[import]
        _BM_AVAILABLE = True
    except ImportError:
        BrokerManager = None  # type: ignore[assignment,misc]
        _BM_AVAILABLE = False

try:
    from bot.execution_authority_context import startup_execution_probe_scope
except ImportError:
    try:
        from execution_authority_context import startup_execution_probe_scope  # type: ignore[import]
    except ImportError:
        startup_execution_probe_scope = None  # type: ignore[assignment]

try:
    from bot.nija_core_loop import get_nija_core_loop
    _CORE_LOOP_AVAILABLE = True
except ImportError:
    try:
        from nija_core_loop import get_nija_core_loop  # type: ignore[import]
        _CORE_LOOP_AVAILABLE = True
    except ImportError:
        get_nija_core_loop = None  # type: ignore[assignment,misc]
        _CORE_LOOP_AVAILABLE = False

try:
    from bot.pipeline_order_submitter import submit_market_order_via_pipeline
except ImportError:
    try:
        from pipeline_order_submitter import submit_market_order_via_pipeline  # type: ignore[import]
    except ImportError:
        submit_market_order_via_pipeline = None  # type: ignore[assignment]

try:
    from bot.broker_identity import format_broker_identity
except ImportError:
    try:
        from broker_identity import format_broker_identity  # type: ignore[import]
    except ImportError:
        def format_broker_identity(broker: Any) -> str:  # type: ignore[misc]
            return type(broker).__name__.replace("Broker", "").strip().lower() if broker is not None else "unknown"

# ---------------------------------------------------------------------------
# Heartbeat trade configuration
# ---------------------------------------------------------------------------

def _env_float(*names: str, default: float) -> float:
    """Read float env value from the first present key in `names`."""
    for name in names:
        raw = os.environ.get(name)
        if raw is None:
            continue
        try:
            return float(str(raw).strip())
        except (TypeError, ValueError):
            logger.warning("Invalid float env %s=%r — using fallback", name, raw)
    return float(default)


_HEARTBEAT_TRADE_AMOUNT_USD: float = _env_float(
    "HEARTBEAT_TRADE_AMOUNT_USD",
    "HEARTBEAT_TRADE_SIZE",
    default=5.0,
)
_HEARTBEAT_TRADE_INTERVAL_S: float = _env_float(
    "HEARTBEAT_TRADE_INTERVAL_S",
    "HEARTBEAT_TRADE_INTERVAL",
    default=15.0,
)
_HEARTBEAT_TRADE_FIRST_ATTEMPT_DELAY_S: float = float(
    os.environ.get("HEARTBEAT_TRADE_FIRST_ATTEMPT_DELAY_S", "0") or "0"
)
_HEARTBEAT_RETRY_BACKOFF_ENABLED: bool = os.environ.get(
    "NIJA_HEARTBEAT_RETRY_BACKOFF_ENABLED", "false"
).strip().lower() in ("1", "true", "yes", "enabled", "on")
_HEARTBEAT_RETRY_BACKOFF_MAX_S: float = _env_float(
    "NIJA_HEARTBEAT_RETRY_BACKOFF_MAX_S",
    default=120.0,
)
_HEARTBEAT_TRADE_SYMBOL: str = os.environ.get(
    "HEARTBEAT_TRADE_SYMBOL", "BTC-USD"
).strip()
_SYMBOL_UNIVERSE_REFRESH_INTERVAL_S: float = _env_float(
    "NIJA_SYMBOL_UNIVERSE_REFRESH_INTERVAL_S",
    default=900.0,
)

# Default symbols to try for the heartbeat trade (in order of preference)
_HEARTBEAT_SYMBOL_CANDIDATES: List[str] = [
    "BTC-USD",
    "ETH-USD",
    "SOL-USD",
    "XRP-USD",
]

# Global minimum trade size — single source of truth imported by position_sizer.py.
# Lowered to $10 for micro-cap / HF scalp mode with $174 balance (Apr 2026).
GLOBAL_MIN_TRADE: float = float(os.environ.get("MIN_TRADE_USD", os.environ.get("MIN_NOTIONAL_USD", "10.0")))

# Backward-compatibility constants retained for legacy test/import paths.
# Venue-specific account balance floors: the entry router skips a broker
# if its last-known balance is below the floor.  These are intentionally
# LOW (account balance is not the same as order size) — the exchange
# minimum notional is enforced later by exchange_constraints_enforcer.
# Operators can override individual venues via environment variables.
ENTRY_BROKER_PRIORITY: List[str] = ["kraken", "coinbase", "okx", "alpaca"]
BROKER_MIN_BALANCE: Dict[str, float] = {
    "default": float(os.environ.get("NIJA_DEFAULT_MIN_BALANCE", "10.0")),
    # Kraken floor: the kraken_execution_floor_guard_patch enforces a final BUY
    # minimum of $23.00–$23.10.  Set the routing floor to match so Kraken is
    # only selected when there is enough FREE cash to actually clear that floor.
    # Operators can lower this via KRAKEN_MIN_BALANCE_USD if needed.
    "kraken": float(os.environ.get("KRAKEN_MIN_BALANCE_USD", "23.10")),
    "coinbase": float(os.environ.get("COINBASE_MIN_BALANCE_USD", "2.0")),  # Coinbase min is ~$1
    "okx": float(os.environ.get("OKX_MIN_BALANCE_USD", "10.0")),          # OKX exchange min ~$5 + fee buffer
    "alpaca": float(os.environ.get("ALPACA_MIN_BALANCE_USD", "2.0")),
}

_HEARTBEAT_STAGE_ORDER: Dict[str, int] = {
    "AUTH_VERIFY": 1,
    "ORDER_VERIFY": 2,
    "FILL_VERIFY": 3,
}


def _heartbeat_required_stage() -> str:
    stage = os.environ.get("HEARTBEAT_VERIFICATION_REQUIRED_STAGE", "ORDER_VERIFY").strip().upper()
    if stage not in _HEARTBEAT_STAGE_ORDER:
        return "ORDER_VERIFY"
    return stage


def _heartbeat_stage_is_sufficient(stage: str, required_stage: str) -> bool:
    return _HEARTBEAT_STAGE_ORDER.get(stage, 0) >= _HEARTBEAT_STAGE_ORDER.get(required_stage, 0)


def _is_nonce_auth_error(exc: BaseException) -> bool:
    """Return True when an auth/probe exception indicates nonce desynchronization."""
    detail = str(exc or "").strip().lower()
    if not detail:
        return False
    nonce_markers = (
        "invalid nonce",
        "eapi:invalid nonce",
        "nonce window",
        "nonce out of window",
        "nonce not authorized",
    )
    return any(marker in detail for marker in nonce_markers)


# ---------------------------------------------------------------------------
# TradingStrategy
# ---------------------------------------------------------------------------


class TradingStrategy:
    """
    Top-level trading strategy orchestrator for NIJA APEX v7.1.

    Wraps NIJAApexStrategyV71 and manages broker connections, multi-account
    support, and the heartbeat trade verification system.

    The heartbeat trade executes a small $5 test trade on startup to confirm
    that the full execution stack (broker connection → order submission →
    fill confirmation) is operational before enabling full trading mode.
    """

    def __init__(
        self,
        broker_results: Optional[Dict] = None,
        connected_user_brokers: Optional[Dict] = None,
    ) -> None:
        """
        Initialize TradingStrategy.

        Args:
            broker_results: Pre-connected platform broker results from bootstrap.
            connected_user_brokers: Pre-connected user broker results from bootstrap.
        """
        logger.info("🚀 TradingStrategy.__init__ starting")

        # ── Core attributes ────────────────────────────────────────────────
        self.broker: Optional[Any] = None
        self.broker_manager: Optional[Any] = None
        self.multi_account_manager: Optional[Any] = None
        self.independent_trader: Optional[Any] = None
        self.apex: Optional[Any] = None
        self.nija_core_loop: Optional[Any] = None
        self.execution_engine: Optional[Any] = None
        self.market_readiness_gate: Optional[Any] = None
        self.symbols: List[str] = []
        self.failed_brokers: Dict = {}
        self._symbol_universe_refresh_interval_s: float = max(
            0.0,
            float(_SYMBOL_UNIVERSE_REFRESH_INTERVAL_S),
        )
        self._last_symbol_refresh_ts: float = 0.0

        # Heartbeat trade state
        self._heartbeat_trade_enabled: bool = (
            os.environ.get("HEARTBEAT_TRADE", "false").strip().lower()
            in ("1", "true", "yes", "enabled")
        )
        self._heartbeat_trade_completed: bool = False
        self._heartbeat_trade_success: bool = False
        self._heartbeat_trade_lock = threading.Lock()
        self._heartbeat_trade_thread: Optional[threading.Thread] = None

        # ── Wire up multi-account broker manager ───────────────────────────
        try:
            from bot.multi_account_broker_manager import multi_account_broker_manager as _mabm
            self.multi_account_manager = _mabm
            logger.info("✅ MultiAccountBrokerManager attached")
        except ImportError:
            try:
                from multi_account_broker_manager import multi_account_broker_manager as _mabm  # type: ignore[import]
                self.multi_account_manager = _mabm
                logger.info("✅ MultiAccountBrokerManager attached (fallback import)")
            except ImportError:
                logger.warning("⚠️  MultiAccountBrokerManager not available")

        # ── Wire up broker manager ─────────────────────────────────────────
        try:
            from bot.broker_manager import get_broker_manager as _get_bm
            self.broker_manager = _get_bm()
            logger.info("✅ BrokerManager attached")
        except ImportError:
            try:
                from broker_manager import get_broker_manager as _get_bm  # type: ignore[import]
                self.broker_manager = _get_bm()
                logger.info("✅ BrokerManager attached (fallback import)")
            except ImportError:
                logger.warning("⚠️  BrokerManager not available")

        # ── Resolve primary broker ─────────────────────────────────────────
        self._resolve_primary_broker(broker_results)

        # ── Wire up APEX strategy ──────────────────────────────────────────
        if _APEX_AVAILABLE and NIJAApexStrategyV71 is not None:
            try:
                self.apex = NIJAApexStrategyV71(broker_client=self.broker)
                self.execution_engine = getattr(self.apex, "execution_engine", None)
                logger.info("✅ NIJAApexStrategyV71 initialized")
            except Exception as _apex_err:
                logger.error("❌ NIJAApexStrategyV71 init failed: %s", _apex_err)
                self.apex = None

        if _CORE_LOOP_AVAILABLE and get_nija_core_loop is not None and self.apex is not None:
            try:
                _max_positions = int(os.environ.get("NIJA_MAX_POSITIONS", "5") or 5)
                self.nija_core_loop = get_nija_core_loop(
                    apex_strategy=self.apex,
                    max_positions=max(1, _max_positions),
                )
                # Ensure the singleton loop points at the currently active apex instance.
                if getattr(self.nija_core_loop, "apex", None) is not self.apex:
                    self.nija_core_loop.apex = self.apex
                logger.info("✅ NijaCoreLoop attached to TradingStrategy")
            except Exception as _core_loop_err:
                self.nija_core_loop = None
                logger.warning("⚠️ Could not attach NijaCoreLoop: %s", _core_loop_err)

        # ── Wire up IndependentBrokerTrader ────────────────────────────────
        if _IBT_AVAILABLE and IndependentBrokerTrader is not None:
            try:
                self.independent_trader = IndependentBrokerTrader(
                    broker_manager=self.broker_manager,
                    trading_strategy=self,
                    multi_account_manager=self.multi_account_manager,
                )
                logger.info("✅ IndependentBrokerTrader initialized")
            except Exception as _ibt_err:
                logger.warning("⚠️  IndependentBrokerTrader init failed: %s", _ibt_err)
                self.independent_trader = None
        else:
            self.independent_trader = None

        if _MARKET_READINESS_GATE_AVAILABLE and MarketReadinessGate is not None:
            try:
                self.market_readiness_gate = MarketReadinessGate()
                logger.info("✅ MarketReadinessGate attached")
            except Exception as _mrg_err:
                self.market_readiness_gate = None
                logger.warning("⚠️ Could not attach MarketReadinessGate: %s", _mrg_err)

        # ── Populate symbol list ───────────────────────────────────────────
        self._populate_symbols()

        # ── Wire up MarketReadinessGate ────────────────────────────────────
        self.market_readiness_gate: Optional[Any] = None
        try:
            from bot.market_readiness_gate import MarketReadinessGate as _MRG
            self.market_readiness_gate = _MRG()
            logger.info("✅ MarketReadinessGate initialized")
        except ImportError:
            try:
                from market_readiness_gate import MarketReadinessGate as _MRG  # type: ignore[import]
                self.market_readiness_gate = _MRG()
                logger.info("✅ MarketReadinessGate initialized (fallback import)")
            except ImportError:
                logger.warning("⚠️  MarketReadinessGate not available")
        except Exception as _mrg_err:
            logger.warning("⚠️  MarketReadinessGate init failed: %s", _mrg_err)

        # ── Start heartbeat trade if enabled ───────────────────────────────
        if self._heartbeat_trade_enabled:
            logger.info(
                "💓 Heartbeat trade enabled — scheduling immediate $%.2f verification "
                "(first_delay=%.0fs retry_interval=%.0fs)",
                _HEARTBEAT_TRADE_AMOUNT_USD,
                _HEARTBEAT_TRADE_FIRST_ATTEMPT_DELAY_S,
                _HEARTBEAT_TRADE_INTERVAL_S,
            )
            self._schedule_heartbeat_trade()
        else:
            logger.info("ℹ️  Heartbeat trade disabled (HEARTBEAT_TRADE not set)")

        logger.info("✅ TradingStrategy initialized")

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    def _recover_nonce_auth_probe(self) -> tuple[bool, str]:
        """Best-effort nonce recovery used when heartbeat auth probe hits nonce drift."""
        platform_key = (
            os.environ.get("KRAKEN_PLATFORM_API_KEY", "").strip()
            or os.environ.get("KRAKEN_API_KEY", "").strip()
        )
        if not platform_key:
            return False, "kraken_key_missing"
        try:
            try:
                from bot.distributed_nonce_manager import (
                    get_distributed_nonce_manager,
                    make_api_key_id,
                )
            except ImportError:
                from distributed_nonce_manager import (  # type: ignore[import]
                    get_distributed_nonce_manager,
                    make_api_key_id,
                )
            manager = get_distributed_nonce_manager()
            key_id = make_api_key_id(platform_key)
            manager.probe_server_sync(key_id)
            manager.ensure_writer_lock(key_id)
            return True, "probe_server_sync"
        except Exception as exc:
            return False, str(exc)

    def _resolve_primary_broker(self, broker_results: Optional[Dict]) -> None:
        """Resolve the primary broker from bootstrap results or manager."""
        # Try broker_results first (bootstrap path)
        if broker_results:
            for _bt, _meta in broker_results.items():
                _broker_obj = (_meta or {}).get("broker")
                if _broker_obj is not None and getattr(_broker_obj, "connected", False):
                    self.broker = _broker_obj
                    logger.info(
                        "✅ Primary broker resolved from bootstrap: %s",
                        getattr(_bt, "value", str(_bt)).upper(),
                    )
                    return

        # Try multi_account_manager
        if self.multi_account_manager is not None:
            try:
                _platform_brokers = getattr(
                    self.multi_account_manager, "platform_brokers", {}
                )
                for _bt, _b in (_platform_brokers or {}).items():
                    if _b is not None and getattr(_b, "connected", False):
                        self.broker = _b
                        logger.info(
                            "✅ Primary broker resolved from MABM: %s",
                            getattr(_bt, "value", str(_bt)).upper(),
                        )
                        return
            except Exception as _mabm_err:
                logger.debug("MABM broker resolution failed: %s", _mabm_err)

        # Try broker_manager
        if self.broker_manager is not None:
            try:
                _primary = self.broker_manager.get_primary_broker()
                if _primary is not None and getattr(_primary, "connected", False):
                    self.broker = _primary
                    logger.info("✅ Primary broker resolved from BrokerManager")
                    return
            except Exception as _bm_err:
                logger.debug("BrokerManager broker resolution failed: %s", _bm_err)

        logger.warning("⚠️  No connected primary broker found at init time")

    def _populate_symbols(self) -> None:
        """Populate the symbol universe from ALL connected brokers.

        Collects tradeable instruments from every connected platform broker
        (Kraken, Coinbase, OKX, Alpaca) and merges them into a single
        deduplicated list.  This expands the scan universe from Kraken-only
        crypto pairs to stocks, forex, commodities, and all crypto venues.
        """
        all_symbols: List[str] = []
        broker_counts: dict = {}

        # ── Collect symbols from all connected platform brokers ────────────
        brokers_to_query: List[Any] = []

        # Gather from MultiAccountBrokerManager platform brokers
        if self.multi_account_manager is not None:
            try:
                _platform_brokers = getattr(
                    self.multi_account_manager, "platform_brokers", {}
                ) or {}
                for _bt, _b in _platform_brokers.items():
                    if _b is not None and getattr(_b, "connected", False):
                        brokers_to_query.append(_b)
            except Exception as _mabm_err:
                logger.debug("MABM broker query failed during symbol population: %s", _mabm_err)

        # Also include the primary broker if not already covered
        if self.broker is not None and self.broker not in brokers_to_query:
            brokers_to_query.append(self.broker)

        # Fallback: try BrokerManager
        if not brokers_to_query and self.broker_manager is not None:
            try:
                for _bt, _b in (getattr(self.broker_manager, "brokers", {}) or {}).items():
                    if _b is not None and getattr(_b, "connected", False):
                        brokers_to_query.append(_b)
            except Exception as _bm_err:
                logger.debug("BrokerManager broker query failed during symbol population: %s", _bm_err)

        for _broker in brokers_to_query:
            _broker_name = self._broker_key_from_obj(_broker)
            try:
                if hasattr(_broker, "get_all_products"):
                    _products = _broker.get_all_products()
                    if isinstance(_products, list) and _products:
                        _count = len(_products)
                        broker_counts[_broker_name] = _count
                        all_symbols.extend(str(p) for p in _products if p)
                        logger.info(
                            "✅ [SymbolUniverse] %s: loaded %d symbols",
                            _broker_name.upper(),
                            _count,
                        )
            except Exception as _sym_err:
                logger.debug(
                    "Symbol population failed for broker %s: %s", _broker_name, _sym_err
                )

        if all_symbols:
            # Deduplicate while preserving order (first occurrence wins)
            seen: set = set()
            merged: List[str] = []
            for sym in all_symbols:
                if sym not in seen:
                    seen.add(sym)
                    merged.append(sym)
            self.symbols = merged
            self._last_symbol_refresh_ts = time.time()
            logger.info(
                "✅ [SymbolUniverse] Merged %d unique symbols across %d broker(s): %s",
                len(self.symbols),
                len(broker_counts),
                ", ".join(f"{k.upper()}={v}" for k, v in broker_counts.items()),
            )
            return

        # Fallback: use a curated default list
        if not self.symbols:
            self.symbols = _HEARTBEAT_SYMBOL_CANDIDATES.copy()
            self._last_symbol_refresh_ts = time.time()
            logger.info(
                "ℹ️  Using default symbol list (%d symbols)", len(self.symbols)
            )
        else:
            logger.debug(
                "Symbol refresh fallback: keeping existing universe (%d symbols)",
                len(self.symbols),
            )

    @staticmethod
    def _broker_key_from_obj(broker: Any) -> str:
        """Return a normalized broker key for priority/min-balance lookups."""
        broker_type = getattr(broker, "broker_type", None)
        if broker_type is not None:
            value = getattr(broker_type, "value", None)
            if value:
                return str(value).strip().lower()
            return str(broker_type).split(".")[-1].strip().lower()
        name = getattr(broker, "NAME", "") or broker.__class__.__name__
        name_l = str(name).strip().lower()
        for candidate in ENTRY_BROKER_PRIORITY:
            if candidate in name_l:
                return candidate
        return name_l

    @staticmethod
    def _balance_from_payload(payload: Any) -> float:
        """Extract a USD scalar from common broker balance payload shapes.

        Key order prioritises free/spendable cash (``available_balance``,
        ``available_usd``, ``available``) over total equity (``total_balance``,
        ``balance``, etc.) so broker-eligibility routing uses the cash that can
        actually be spent on a new order, not capital that is already locked in
        open positions.
        """
        if isinstance(payload, (int, float)):
            return float(payload)
        if isinstance(payload, dict):
            for key in (
                "available_balance",   # free/spendable cash — broker adapters set this
                "available_usd",
                "available",
                "free",
                "free_usd",
                "total_balance",       # fallback: total equity including locked positions
                "balance",
                "usd_balance",
                "equity",
                "total_usd",
            ):
                if key in payload:
                    try:
                        return float(payload.get(key) or 0.0)
                    except (TypeError, ValueError):
                        return 0.0
        return 0.0

    def _broker_entry_balance(self, broker: Any, broker_key: Optional[str] = None) -> float:
        """Return best-known entry balance without requiring a fresh exchange call."""
        key = broker_key or self._broker_key_from_obj(broker)

        # Prefer the broker's hydrated payload; this is set by capital/bootstrap
        # refreshes and avoids blocking entry routing on a new synchronous API call.
        cached = getattr(broker, "_last_known_balance", None)
        if cached is not None:
            try:
                return float(cached or 0.0)
            except (TypeError, ValueError):
                pass

        try:
            from bot.balance_service import BalanceService
        except ImportError:
            try:
                from balance_service import BalanceService  # type: ignore[import]
            except ImportError:
                BalanceService = None  # type: ignore[assignment]
        if BalanceService is not None:
            try:
                service_balance = float(BalanceService.get(key) or 0.0)
                if service_balance > 0.0:
                    return service_balance
            except Exception:
                pass

        # Last resort for legacy test doubles and non-orchestrated startup paths.
        getter = getattr(broker, "get_account_balance", None)
        if callable(getter):
            try:
                return self._balance_from_payload(getter())
            except Exception as exc:
                logger.debug("Broker balance fallback failed for %s: %s", key, exc)
        return 0.0

    def _is_broker_eligible_for_entry(self, broker: Any) -> tuple[bool, str]:
        """Return whether *broker* can accept new entry orders right now.

        The entry router intentionally excludes disconnected, EXIT_ONLY, and
        underfunded venues so the strategy loop does not stall on a broker that
        can only close positions or cannot meet minimum order sizing.
        """
        if broker is None:
            return False, "broker missing"

        broker_key = self._broker_key_from_obj(broker)
        if not getattr(broker, "connected", False):
            return False, f"{broker_key} not connected"

        if getattr(broker, "exit_only_mode", False):
            return False, f"{broker_key} is in EXIT-ONLY mode"

        # A missing position tracker is a capital-protection risk for real
        # broker adapters because exits/P&L cannot be reconciled safely.  Some
        # external adapters may not expose the attribute; only block when the
        # adapter declares it but it is unset.
        if hasattr(broker, "position_tracker") and getattr(broker, "position_tracker") is None:
            return False, f"{broker_key} position tracker unavailable"

        minimum = float(BROKER_MIN_BALANCE.get(broker_key, BROKER_MIN_BALANCE["default"]))
        balance = self._broker_entry_balance(broker, broker_key)
        if balance < minimum:
            return False, f"{broker_key} balance ${balance:.2f} below minimum ${minimum:.2f}"

        return True, f"{broker_key} eligible (balance=${balance:.2f})"

    def _select_entry_broker(self, brokers: Dict[Any, Any]) -> tuple[Optional[Any], Optional[str], Dict[str, str]]:
        """Select the highest-priority broker eligible for new entries.

        Returns ``(broker, broker_name, status_by_broker)``.  ``status_by_broker``
        records the reason every inspected broker was accepted or rejected for
        operator diagnostics.
        """
        if not brokers:
            return None, None, {}

        by_key: Dict[str, Any] = {}
        for raw_key, broker in brokers.items():
            if broker is None:
                continue
            name = self._broker_key_from_obj(broker)
            if not name and raw_key is not None:
                raw_value = getattr(raw_key, "value", raw_key)
                name = str(raw_value).strip().lower()
            if name:
                by_key[name] = broker

        status: Dict[str, str] = {}
        inspected = set()
        priority_order = list(ENTRY_BROKER_PRIORITY)
        preferred_venue = (
            get_preferred_execution_venue(os.environ)
            if get_preferred_execution_venue is not None
            else None
        )
        if preferred_venue in by_key:
            priority_order = [preferred_venue] + [name for name in priority_order if name != preferred_venue]

        for name in priority_order:
            broker = by_key.get(name)
            if broker is None:
                status[name] = "not configured"
                continue
            inspected.add(name)
            eligible, reason = self._is_broker_eligible_for_entry(broker)
            status[name] = reason
            if eligible:
                return broker, name, status

        # Optional venues are diagnostics-only for new entries unless explicitly
        # promoted into ENTRY_BROKER_PRIORITY.
        for name in sorted(set(by_key) - inspected):
            status[name] = "not in entry priority"

        return None, None, status

    def _maybe_refresh_symbols(self, *, force: bool = False) -> None:
        """Refresh the symbol universe periodically to capture newly listed markets."""
        interval = float(self._symbol_universe_refresh_interval_s)
        if interval <= 0.0 and not force:
            return
        now_ts = time.time()
        if (
            not force
            and self._last_symbol_refresh_ts > 0.0
            and (now_ts - self._last_symbol_refresh_ts) < interval
        ):
            return
        prev_count = len(self.symbols)
        self._populate_symbols()
        if len(self.symbols) != prev_count:
            logger.info(
                "🔄 Symbol universe refreshed: %d → %d",
                prev_count,
                len(self.symbols),
            )

    # -----------------------------------------------------------------------
    # Heartbeat trade
    # -----------------------------------------------------------------------

    def _schedule_heartbeat_trade(self) -> None:
        """Schedule the heartbeat trade in a background daemon thread."""
        with self._heartbeat_trade_lock:
            if self._heartbeat_trade_thread is not None and self._heartbeat_trade_thread.is_alive():
                logger.debug("Heartbeat trade thread already running")
                return
            self._heartbeat_trade_thread = threading.Thread(
                target=self._heartbeat_trade_runner,
                name="HeartbeatTrade",
                daemon=True,
            )
            self._heartbeat_trade_thread.start()
        logger.info("💓 Heartbeat trade thread started")

    def _heartbeat_trade_runner(self) -> None:
        """Background thread: execute heartbeat immediately and retry until verification succeeds."""
        first_delay_s = max(0.0, _HEARTBEAT_TRADE_FIRST_ATTEMPT_DELAY_S)
        retry_interval_s = max(1.0, _HEARTBEAT_TRADE_INTERVAL_S)
        retry_backoff_max_s = max(retry_interval_s, float(_HEARTBEAT_RETRY_BACKOFF_MAX_S))
        if first_delay_s > 0:
            _heartbeat_rate_limited_info(
                "heartbeat_runner_delay",
                "runner",
                60.0,
                "💓 Heartbeat trade runner sleeping %.0fs before first attempt",
                first_delay_s,
            )
            time.sleep(first_delay_s)
        attempt = 1
        while True:
            try:
                success = self._execute_heartbeat_trade()
                with self._heartbeat_trade_lock:
                    self._heartbeat_trade_success = success
                    self._heartbeat_trade_completed = success
                if success:
                    logger.info("✅ Heartbeat trade PASSED — bot confirmed ready for live trading")
                    return
                sleep_s = retry_interval_s
                if _HEARTBEAT_RETRY_BACKOFF_ENABLED:
                    sleep_s = min(
                        retry_backoff_max_s,
                        retry_interval_s * float(2 ** min(attempt - 1, 10)),
                    )
                _heartbeat_rate_limited_info(
                    "heartbeat_runner_retry",
                    "runner",
                    max(10.0, retry_interval_s),
                    "❌ Heartbeat trade FAILED on attempt %d — retrying in %.0fs",
                    attempt,
                    sleep_s,
                )
                logger.error(
                    "❌ Heartbeat trade FAILED on attempt %d — retrying in %.0fs",
                    attempt,
                    sleep_s,
                )
            except Exception as _hb_err:
                logger.error(
                    "❌ Heartbeat trade runner raised on attempt %d: %s",
                    attempt,
                    _hb_err,
                    exc_info=True,
                )
                with self._heartbeat_trade_lock:
                    self._heartbeat_trade_success = False
                    self._heartbeat_trade_completed = False
                sleep_s = retry_interval_s
                if _HEARTBEAT_RETRY_BACKOFF_ENABLED:
                    sleep_s = min(
                        retry_backoff_max_s,
                        retry_interval_s * float(2 ** min(attempt - 1, 10)),
                    )
            attempt += 1
            time.sleep(sleep_s)

    def _heartbeat_auth_verify(self, broker: Any) -> tuple[bool, str]:
        """Best-effort authenticated request probe for AUTH_VERIFY stage."""
        probe_methods = ("get_account_balance", "get_balance", "get_accounts", "get_portfolio")
        for method_name in probe_methods:
            method = getattr(broker, method_name, None)
            if callable(method):
                try:
                    probe_scope = (
                        startup_execution_probe_scope("HEARTBEAT_TRADE")
                        if callable(startup_execution_probe_scope)
                        else nullcontext()
                    )
                    with probe_scope:
                        method()
                    return True, method_name
                except Exception as exc:
                    if _is_nonce_auth_error(exc):
                        recovered, recovery_detail = self._recover_nonce_auth_probe()
                        if recovered:
                            try:
                                probe_scope = (
                                    startup_execution_probe_scope("HEARTBEAT_TRADE")
                                    if callable(startup_execution_probe_scope)
                                    else nullcontext()
                                )
                                with probe_scope:
                                    method()
                                logger.warning(
                                    "⚠️  Heartbeat AUTH_VERIFY nonce drift recovered via %s; continuing",
                                    recovery_detail,
                                )
                                return True, f"{method_name}:nonce_recovered"
                            except Exception as retry_exc:
                                return False, f"{method_name}:{retry_exc}"
                        return False, f"{method_name}:{exc} nonce_recovery={recovery_detail}"
                    return False, f"{method_name}:{exc}"
        # Fallback for broker test doubles that don't expose auth probe methods.
        if getattr(broker, "connected", False) and callable(getattr(broker, "execute_order", None)):
            return True, "connected_fallback"
        return False, "auth_probe_unavailable"

    def _execute_heartbeat_trade(self) -> bool:
        """
        Execute a small $5 test trade to verify the full execution stack.

        This is a one-shot verification that runs once on startup.  It places
        a market buy order for the configured heartbeat symbol (default BTC-USD)
        and immediately sells it to close the position.

        Returns:
            True if the heartbeat trade executed successfully, False otherwise.

        Note:
            Uses ``get_available_markets()`` (the BaseBroker abstract method
            added in this PR) if the broker exposes it, falling back to
            ``get_all_products()`` for older broker implementations.  Either
            way, market discovery failure never blocks heartbeat execution.
        """
        # ── Resolve broker ─────────────────────────────────────────────────
        broker = self._get_active_broker()
        if broker is None:
            logger.error("❌ Heartbeat trade: no active broker available")
            return False

        broker_name = type(broker).__name__
        heartbeat_trace_id = f"heartbeat-{int(time.time())}-{broker_name.lower()}"
        broker_identity = format_broker_identity(broker)
        trade_amount_usd = self._resolve_heartbeat_trade_amount_usd(broker)
        required_stage = _heartbeat_required_stage()
        _heartbeat_rate_limited_info(
            "heartbeat_trade_start",
            broker_name,
            30.0,
            "💓 Executing heartbeat trade: $%.2f on %s",
            trade_amount_usd,
            _HEARTBEAT_TRADE_SYMBOL,
        )
        _heartbeat_rate_limited_info(
            "heartbeat_trade_broker",
            broker_name,
            30.0,
            "💓 Heartbeat trade using broker: %s",
            broker_name,
        )
        _heartbeat_rate_limited_info(
            "heartbeat_trade_required_stage",
            broker_name,
            30.0,
            "[HeartbeatTrade] required_stage=%s",
            required_stage,
        )
        logger.info("💓 Heartbeat trade using broker: %s", broker_identity)
        logger.info("[HeartbeatTrade] required_stage=%s", required_stage)

        # ── Stage 1: AUTH_VERIFY ─────────────────────────────────────────────
        auth_ok, auth_detail = self._heartbeat_auth_verify(broker)
        if not auth_ok:
            logger.error("❌ Heartbeat AUTH_VERIFY failed: %s", auth_detail)
            return False
        stage_achieved = "AUTH_VERIFY"
        stage_details: Dict[str, Any] = {"auth_probe": auth_detail}

        # ── Verify the symbol is available on this broker ──────────────────
        # Prefer get_available_markets() when the broker exposes it (satisfies
        # the BaseBroker abstract interface added in this PR); fall back to
        # get_all_products() for brokers that haven't been updated yet.
        symbol = _HEARTBEAT_TRADE_SYMBOL
        try:
            _market_getter = (
                "get_available_markets"
                if hasattr(broker, "get_available_markets")
                else "get_all_products"
                if hasattr(broker, "get_all_products")
                else None
            )
            if _market_getter is not None:
                available_markets = getattr(broker, _market_getter)()
                _discovery_count = len(available_markets) if isinstance(available_markets, list) else 0
                _heartbeat_rate_limited_info(
                    "heartbeat_market_discovery_count",
                    broker_name,
                    30.0,
                    "[HeartbeatTrade] market_discovery_count=%s",
                    _discovery_count,
                )
                if isinstance(available_markets, list) and available_markets:
                    # Check if our preferred symbol is available; fall back to
                    # the first available candidate if not.
                    if symbol not in available_markets:
                        for candidate in _HEARTBEAT_SYMBOL_CANDIDATES:
                            if candidate in available_markets:
                                logger.info(
                                    "💓 Heartbeat symbol %s not available — using %s instead",
                                    symbol,
                                    candidate,
                                )
                                symbol = candidate
                                break
                        else:
                            # Use the first available market as a last resort
                            symbol = available_markets[0]
                            logger.info(
                                "💓 Heartbeat using first available market: %s", symbol
                            )
                    else:
                        logger.info("💓 Heartbeat symbol %s confirmed available", symbol)
                else:
                    _heartbeat_rate_limited_info(
                        "heartbeat_market_discovery_count",
                        broker_name,
                        30.0,
                        "[HeartbeatTrade] market_discovery_count=0",
                    )
                    logger.warning(
                        "⚠️  %s() returned empty list — proceeding with %s",
                        _market_getter,
                        symbol,
                    )
            else:
                _heartbeat_rate_limited_info(
                    "heartbeat_market_discovery_count",
                    broker_name,
                    30.0,
                    "[HeartbeatTrade] market_discovery_count=0",
                )
                logger.warning(
                    "⚠️  Broker %s has no market discovery method — "
                    "proceeding with symbol %s without market verification",
                    broker_identity,
                    symbol,
                )
        except Exception as _market_err:
            _heartbeat_rate_limited_info(
                "heartbeat_market_discovery_count",
                broker_name,
                30.0,
                "[HeartbeatTrade] market_discovery_count=0",
            )
            logger.warning(
                "⚠️  Market availability check failed (%s) — proceeding with %s",
                _market_err,
                symbol,
            )

        # ── Stage 2 + 3 via heartbeat BUY order ────────────────────────────
        try:
            _report_anomaly = None
            try:
                from bot.trading_state_machine import report_execution_anomaly as _report_anomaly
            except Exception:
                _report_anomaly = None
            logger.info(
                "💓 Placing heartbeat BUY: %s $%.2f",
                symbol,
                trade_amount_usd,
            )
            buy_scope = (
                startup_execution_probe_scope("HEARTBEAT_TRADE")
                if callable(startup_execution_probe_scope)
                else nullcontext()
            )
            with runtime_correlation_scope(
                trace_id=heartbeat_trace_id,
                account_id=str(getattr(broker, "account_identifier", "") or ""),
                broker_identity=broker_name,
            ):
                with buy_scope:
                    if submit_market_order_via_pipeline is None:
                        buy_result = {
                            "status": "error",
                            "error": "ExecutionPipeline submit helper unavailable; direct broker fallback blocked",
                        }
                    else:
                        buy_result = submit_market_order_via_pipeline(
                            broker=broker,
                            symbol=symbol,
                            side="buy",
                            quantity=trade_amount_usd,
                            size_type="quote",
                            strategy="HEARTBEAT_TRADE",
                        )
            buy_status = (buy_result or {}).get("status", "error")
            buy_order_id = (buy_result or {}).get("order_id")
            buy_submitted = bool(buy_result)
            buy_submitted = buy_submitted and str(buy_status).lower().strip() not in {
                "error",
                "rejected",
                "failed",
                "unfilled",
                "skipped",
            }
            buy_filled = str(buy_status).lower().strip() in ("filled", "ok", "success")
            stage_details.update(
                {
                    "symbol": symbol,
                    "buy_status": buy_status,
                    "buy_submitted": buy_submitted,
                    "buy_filled": buy_filled,
                }
            )
            logger.info(
                "[HeartbeatTrade] submit=%s fill=%s broker=%s pair=%s size=%s",
                buy_submitted,
                buy_filled,
                broker_identity,
                symbol,
                trade_amount_usd,
            )
            logger.info("💓 Heartbeat BUY result: status=%s", buy_status)

            if buy_submitted:
                stage_achieved = "ORDER_VERIFY"
            if buy_filled:
                stage_achieved = "FILL_VERIFY"

            if not buy_submitted:
                if callable(_report_anomaly):
                    _report_anomaly("rejected_orders", f"heartbeat_buy_not_accepted status={buy_status}")
                logger.error(
                    "❌ Heartbeat BUY not accepted: status=%s error=%s",
                    buy_status,
                    (buy_result or {}).get("error", "unknown"),
                )
                return False

            if not _heartbeat_stage_is_sufficient(stage_achieved, required_stage):
                if callable(_report_anomaly):
                    _report_anomaly(
                        "rejected_orders",
                        f"heartbeat_stage_insufficient achieved={stage_achieved} required={required_stage}",
                    )
                logger.error(
                    "❌ Heartbeat stage insufficient: achieved=%s required=%s",
                    stage_achieved,
                    required_stage,
                )
                return False

            self._persist_heartbeat_marker(stage=stage_achieved, details=stage_details)

            if not buy_filled:
                if callable(_report_anomaly):
                    _report_anomaly("partial_fills", f"heartbeat_buy_not_filled status={buy_status}")
                logger.warning(
                    "⚠️  Heartbeat BUY accepted but not immediately filled; stage=%s",
                    stage_achieved,
                )
                return True

            logger.info("✅ Heartbeat BUY confirmed — order filled")

            # Brief pause before the sell to allow the position to settle
            time.sleep(2.0)

            # ── Place the heartbeat sell order to close the position ────────
            logger.info("💓 Placing heartbeat SELL to close position: %s", symbol)
            sell_scope = (
                startup_execution_probe_scope("HEARTBEAT_TRADE_CLOSE")
                if callable(startup_execution_probe_scope)
                else nullcontext()
            )
            with runtime_correlation_scope(
                trace_id=heartbeat_trace_id,
                account_id=str(getattr(broker, "account_identifier", "") or ""),
                broker_identity=broker_name,
            ):
                with sell_scope:
                    if submit_market_order_via_pipeline is None:
                        sell_result = {
                            "status": "error",
                            "error": "ExecutionPipeline submit helper unavailable; direct broker fallback blocked",
                        }
                    else:
                        sell_result = submit_market_order_via_pipeline(
                            broker=broker,
                            symbol=symbol,
                            side="sell",
                            quantity=trade_amount_usd,
                            size_type="quote",
                            strategy="HEARTBEAT_TRADE_CLOSE",
                        )
            sell_status = (sell_result or {}).get("status", "error")
            sell_submitted = bool(sell_result)
            sell_filled = sell_status in ("filled", "ok", "success")
            logger.info(
                "[HeartbeatTrade] submit=%s fill=%s broker=%s pair=%s size=%s",
                sell_submitted,
                sell_filled,
                broker_identity,
                symbol,
                trade_amount_usd,
            )
            logger.info("💓 Heartbeat SELL result: status=%s", sell_status)

            if not sell_filled:
                if callable(_report_anomaly):
                    _report_anomaly("partial_fills", f"heartbeat_sell_not_filled status={sell_status}")
                logger.warning(
                    "⚠️  Heartbeat SELL returned status=%s — position may remain open",
                    sell_status,
                )
                return True

            logger.info("✅ Heartbeat trade round-trip complete")
            return True

        except Exception as _trade_err:
            try:
                from bot.trading_state_machine import report_execution_anomaly as _report_anomaly
                _report_anomaly("rejected_orders", f"heartbeat_exception:{_trade_err}")
            except Exception:
                pass
            logger.error(
                "❌ Heartbeat trade execution raised: %s", _trade_err, exc_info=True
            )
            return False

    def _resolve_heartbeat_trade_amount_usd(self, broker: Any) -> float:
        """Resolve a safe heartbeat notional above exchange minimums."""
        broker_name = format_broker_identity(broker).split(":", 1)[0]
        exchange_minimum = 0.0

        try:
            from bot.minimum_notional_gate import get_minimum_notional_gate
        except ImportError:
            try:
                from minimum_notional_gate import get_minimum_notional_gate  # type: ignore[import]
            except ImportError:
                get_minimum_notional_gate = None  # type: ignore[assignment]

        if get_minimum_notional_gate is not None:
            try:
                exchange_minimum = float(
                    get_minimum_notional_gate().get_minimum_for_symbol(
                        _HEARTBEAT_TRADE_SYMBOL,
                        broker_name=broker_name,
                    )
                    or 0.0
                )
            except Exception as _min_gate_err:
                logger.debug("Heartbeat notional gate minimum lookup failed: %s", _min_gate_err)

        if exchange_minimum <= 0.0:
            try:
                exchange_minimum = float(getattr(broker, "min_trade_size", 0.0) or 0.0)
            except Exception:
                exchange_minimum = 0.0

        resolved = max(_HEARTBEAT_TRADE_AMOUNT_USD, exchange_minimum * 1.25, 10.0)
        logger.info(
            "[HeartbeatTrade] amount_resolved configured=%.2f exchange_min=%.2f final=%.2f",
            _HEARTBEAT_TRADE_AMOUNT_USD,
            exchange_minimum,
            resolved,
        )
        return resolved

    def _persist_heartbeat_marker(self, *, stage: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Persist stage-aware heartbeat verification marker for activation gates."""
        marker_path = os.environ.get("HEARTBEAT_MARKER_PATH", "./data/heartbeat_verified.flag")
        try:
            marker = Path(marker_path)
            marker.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "verified": True,
                "version": 2,
                "stage": str(stage or "AUTH_VERIFY").strip().upper(),
                "verified_at_epoch": float(time.time()),
                "verified_at_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "details": dict(details or {}),
            }
            deployment_id = (
                os.environ.get("NIJA_DEPLOYMENT_ID")
                or os.environ.get("RAILWAY_DEPLOYMENT_ID")
                or os.environ.get("RAILWAY_DEPLOYMENT_INSTANCE_ID")
                or ""
            )
            lease_generation_raw = (
                os.environ.get("NIJA_WRITER_LEASE_GENERATION")
                or os.environ.get("NIJA_WRITER_FENCING_TOKEN")
                or "0"
            )
            nonce_epoch_raw = os.environ.get("NIJA_NONCE_EPOCH", "0")
            try:
                payload["lease_generation"] = int(str(lease_generation_raw).strip())
            except (TypeError, ValueError):
                payload["lease_generation"] = 0
            try:
                payload["nonce_epoch"] = int(str(nonce_epoch_raw).strip() or "0")
            except (TypeError, ValueError):
                payload["nonce_epoch"] = 0
            payload["deployment_id"] = deployment_id
            marker.write_text(json.dumps(payload, sort_keys=True), encoding="utf-8")
            logger.info(
                "[HeartbeatTrade] marker_written path=%s stage=%s",
                str(marker),
                payload["stage"],
            )
        except Exception as _marker_err:
            logger.error("❌ Failed to persist heartbeat marker %s: %s", marker_path, _marker_err)

    def _get_active_broker(self) -> Optional[Any]:
        """Return the best broker that is eligible for new entry/heartbeat orders."""
        # 1. Reuse the cached broker only when it can still accept entries.
        if self.broker is not None:
            eligible, reason = self._is_broker_eligible_for_entry(self.broker)
            if eligible:
                return self.broker
            logger.info(
                "Cached broker is not entry-eligible; selecting fallback: %s",
                reason,
            )

        candidates: Dict[Any, Any] = {}

        # 2. Include all platform brokers from MultiAccountBrokerManager.
        if self.multi_account_manager is not None:
            try:
                _platform_brokers = getattr(
                    self.multi_account_manager, "platform_brokers", {}
                )
                candidates.update(_platform_brokers or {})
            except Exception as _err:
                logger.debug("MABM broker lookup failed: %s", _err)

        # 3. Include BrokerManager brokers and active/primary aliases.
        if self.broker_manager is not None:
            try:
                candidates.update(getattr(self.broker_manager, "brokers", {}) or {})
                _primary = self.broker_manager.get_primary_broker()
                if _primary is not None:
                    candidates.setdefault(getattr(_primary, "broker_type", "primary"), _primary)
            except Exception as _err:
                logger.debug("BrokerManager lookup failed: %s", _err)

        selected, name, status = self._select_entry_broker(candidates)
        if selected is not None:
            self.broker = selected
            if self.broker_manager is not None:
                try:
                    self.broker_manager.active_broker = selected
                except Exception:
                    pass
            logger.info("✅ Selected entry broker: %s", name)
            return selected

        if status:
            logger.warning("No entry-eligible broker available: %s", status)
        return None

    @staticmethod
    def _position_symbol(position: Any) -> str:
        if isinstance(position, dict):
            return str(position.get("symbol") or position.get("pair") or "")
        return str(getattr(position, "symbol", "") or getattr(position, "pair", ""))

    @staticmethod
    def _position_quantity(position: Any) -> float:
        if isinstance(position, dict):
            for key in ("quantity", "qty", "volume", "size", "amount"):
                if key in position:
                    try:
                        return float(position.get(key) or 0.0)
                    except (TypeError, ValueError):
                        return 0.0
        for key in ("quantity", "qty", "volume", "size", "amount"):
            if hasattr(position, key):
                try:
                    return float(getattr(position, key) or 0.0)
                except (TypeError, ValueError):
                    return 0.0
        return 0.0

    @staticmethod
    def _position_entry_price(position: Any) -> float:
        if isinstance(position, dict):
            for key in ("entry_price", "avg_entry_price", "average_price", "price", "current_price"):
                if key in position:
                    try:
                        return float(position.get(key) or 0.0)
                    except (TypeError, ValueError):
                        return 0.0
        for key in ("entry_price", "avg_entry_price", "average_price", "price", "current_price"):
            if hasattr(position, key):
                try:
                    return float(getattr(position, key) or 0.0)
                except (TypeError, ValueError):
                    return 0.0
        return 0.0

    @staticmethod
    def _position_size_usd(position: Any, entry_price: float, quantity: float) -> float:
        if isinstance(position, dict):
            for key in ("size_usd", "usd_value", "market_value", "notional", "value"):
                if key in position:
                    try:
                        return float(position.get(key) or 0.0)
                    except (TypeError, ValueError):
                        return 0.0
        for key in ("size_usd", "usd_value", "market_value", "notional", "value"):
            if hasattr(position, key):
                try:
                    return float(getattr(position, key) or 0.0)
                except (TypeError, ValueError):
                    return 0.0
        return max(0.0, entry_price * quantity)

    def adopt_existing_positions(
        self,
        broker: Any,
        broker_name: str = "",
        account_id: str = "",
    ) -> Dict[str, Any]:
        """Adopt already-open broker positions so exit logic manages them.

        This is used on startup/restart and for user-account loops.  It treats
        open orders as a transitional state: adoption succeeds with zero
        positions while reporting the pending order count, then the next cycle
        adopts positions as soon as those orders fill.
        """
        result: Dict[str, Any] = {
            "success": False,
            "broker_name": broker_name,
            "account_id": account_id,
            "positions_found": 0,
            "positions_adopted": 0,
            "open_orders_count": 0,
            "adopted_symbols": [],
        }
        if broker is None:
            result["error"] = "broker missing"
            return result

        try:
            open_orders_getter = getattr(broker, "get_open_orders", None)
            if callable(open_orders_getter):
                open_orders = open_orders_getter() or []
                result["open_orders_count"] = len(open_orders) if isinstance(open_orders, list) else 0
                if result["open_orders_count"]:
                    logger.info(
                        "Position adoption: %s has %d open order(s); they will be adopted after fill",
                        account_id or broker_name or self._broker_key_from_obj(broker),
                        result["open_orders_count"],
                    )

            positions_getter = getattr(broker, "get_positions", None)
            positions = positions_getter() if callable(positions_getter) else []
            positions = positions or []
            if isinstance(positions, dict):
                iterable_positions = list(positions.values())
            else:
                iterable_positions = list(positions)
            result["positions_found"] = len(iterable_positions)

            tracker = getattr(broker, "position_tracker", None)
            adopted = 0
            adopted_symbols: List[str] = []
            for position in iterable_positions:
                symbol = self._position_symbol(position)
                quantity = self._position_quantity(position)
                entry_price = self._position_entry_price(position)
                size_usd = self._position_size_usd(position, entry_price, quantity)
                if not symbol or quantity <= 0.0:
                    logger.debug(
                        "Position adoption skipped malformed position account=%s broker=%s position=%r",
                        account_id,
                        broker_name,
                        position,
                    )
                    continue

                if tracker is not None and callable(getattr(tracker, "track_entry", None)):
                    tracker.track_entry(
                        symbol=symbol,
                        entry_price=entry_price,
                        quantity=quantity,
                        size_usd=size_usd,
                        strategy="POSITION_ADOPTION",
                        position_source="broker_existing",
                    )
                adopted += 1
                adopted_symbols.append(symbol)

            result["positions_adopted"] = adopted
            result["adopted_symbols"] = adopted_symbols
            result["success"] = True
            return result
        except Exception as exc:
            logger.error(
                "Position adoption failed account=%s broker=%s: %s",
                account_id,
                broker_name,
                exc,
                exc_info=True,
            )
            result["error"] = str(exc)
            return result

    def verify_position_adoption_status(
        self,
        broker: Any,
        broker_name: str = "",
        account_id: str = "",
    ) -> bool:
        """Return True when broker positions can be read after adoption."""
        if broker is None:
            return False
        positions_getter = getattr(broker, "get_positions", None)
        if not callable(positions_getter):
            return False
        try:
            positions_getter()
            return True
        except Exception as exc:
            logger.warning(
                "Position adoption verification failed account=%s broker=%s: %s",
                account_id,
                broker_name,
                exc,
            )
            return False


    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def _ensure_nija_wiring(self) -> None:
        """Ensure APEX and NijaCoreLoop references are correctly wired.

        This self-heals runtime ordering issues where TradingStrategy is
        constructed before all optional modules are fully ready.
        """
        if self.apex is None:
            return

        if self.execution_engine is None:
            self.execution_engine = getattr(self.apex, "execution_engine", None)

        if not _CORE_LOOP_AVAILABLE or get_nija_core_loop is None:
            return

        if self.nija_core_loop is None:
            try:
                _max_positions = int(os.environ.get("NIJA_MAX_POSITIONS", "5") or 5)
                self.nija_core_loop = get_nija_core_loop(
                    apex_strategy=self.apex,
                    max_positions=max(1, _max_positions),
                )
                logger.info("✅ NijaCoreLoop lazily attached during run_cycle")
            except Exception as _wire_err:
                logger.warning("⚠️ NijaCoreLoop lazy attach failed: %s", _wire_err)
                return

        # Keep singleton core loop aligned with the active APEX instance.
        if getattr(self.nija_core_loop, "apex", None) is not self.apex:
            self.nija_core_loop.apex = self.apex
            logger.info("🔗 NijaCoreLoop apex reference re-synchronized")

    def run_cycle(self, broker: Optional[Any] = None, user_mode: bool = False) -> int:
        """Execute one trading cycle and return the recommended next interval in seconds.

        ``IndependentBrokerTrader`` runs the same strategy object for platform and
        user venues, so callers must be able to pin the cycle to the broker whose
        thread is ticking.  When ``broker`` is supplied, do not re-select a cached
        platform broker; use the supplied broker and pass ``user_mode`` through to
        the core loop so independent Kraken users can generate entries while
        copy-mode users remain position-management only.
        """
        next_interval_s = 150
        logger.critical(
            "🔄 [RUN_CYCLE_ENTER] TradingStrategy.run_cycle() ENTERED | "
            "apex=%s nija_core_loop=%s",
            type(self.apex).__name__ if self.apex is not None else "None",
            type(self.nija_core_loop).__name__ if self.nija_core_loop is not None else "None",
        )
        print(
            f"[NIJA-PRINT] RUN_CYCLE_ENTER | "
            f"apex={type(self.apex).__name__ if self.apex is not None else 'None'} "
            f"nija_core_loop={type(self.nija_core_loop).__name__ if self.nija_core_loop is not None else 'None'}",
            flush=True,
        )
        if self.apex is not None:
            try:
                self._ensure_nija_wiring()
                print(
                    f"[NIJA-PRINT] after _ensure_nija_wiring | "
                    f"nija_core_loop={type(self.nija_core_loop).__name__ if self.nija_core_loop is not None else 'None'} "
                    f"apex_has_run_cycle={hasattr(self.apex, 'run_cycle')} "
                    f"apex_has_analyze_market={hasattr(self.apex, 'analyze_market')}",
                    flush=True,
                )
                if self.nija_core_loop is None:
                    logger.critical(
                        "⚠️ [RUN_CYCLE] nija_core_loop is None after _ensure_nija_wiring — "
                        "will use legacy analyze_market+execute_action path. "
                        "apex_has_run_cycle=%s apex_has_analyze_market=%s",
                        hasattr(self.apex, "run_cycle"),
                        hasattr(self.apex, "analyze_market"),
                    )

                logger.critical(
                    "✅ [RUN_CYCLE_PREFLIGHT_OK] wiring verified | "
                    "apex=%s core_loop=%s broker=%s",
                    type(self.apex).__name__,
                    type(self.nija_core_loop).__name__ if self.nija_core_loop is not None else "None",
                    type(getattr(self, "broker", None)).__name__ if getattr(self, "broker", None) is not None else "None",
                )
                print(
                    f"[NIJA-PRINT] RUN_CYCLE_PREFLIGHT_OK | "
                    f"apex={type(self.apex).__name__} "
                    f"core_loop={type(self.nija_core_loop).__name__ if self.nija_core_loop is not None else 'None'}",
                    flush=True,
                )

                # Delegate to the caller-selected venue when provided.  This is
                # required for per-broker platform loops and independent user
                # loops; otherwise _get_active_broker() may choose the platform
                # broker and every user cycle silently scans/executes the wrong
                # account.
                _broker = broker if broker is not None else self._get_active_broker()
                if _broker is not None and self.broker != _broker:
                    self.broker = _broker
                    if hasattr(self.apex, "update_broker_client"):
                        self.apex.update_broker_client(_broker)

                self._maybe_refresh_symbols()

                _account_balance = float(getattr(self.apex, "_last_account_balance", 0.0) or 0.0)
                if _account_balance <= 0.0 and _broker is not None:
                    _balance_method = getattr(_broker, "get_account_balance", None)
                    if callable(_balance_method):
                        try:
                            _bal = _balance_method()
                            if isinstance(_bal, (int, float)):
                                _account_balance = float(_bal)
                            elif isinstance(_bal, dict):
                                for _key in ("total_balance", "balance", "usd_balance", "equity"):
                                    if _key in _bal:
                                        _account_balance = float(_bal.get(_key) or 0.0)
                                        break
                        except Exception as _balance_err:
                            logger.debug("run_cycle balance probe failed: %s", _balance_err)

                _open_positions_count = 0
                _engine = getattr(self.apex, "execution_engine", None)
                _get_all_positions = getattr(_engine, "get_all_positions", None)
                if callable(_get_all_positions):
                    try:
                        _positions = _get_all_positions() or {}
                        if isinstance(_positions, dict):
                            _open_positions_count = len(_positions)
                        elif isinstance(_positions, list):
                            _open_positions_count = len(_positions)
                    except Exception as _pos_err:
                        logger.debug("run_cycle open-position probe failed: %s", _pos_err)

                if self.nija_core_loop is not None:
                    # ── Reconcile stale pending orders before scanning ────────
                    # Clears orders that timed out or were filled/cancelled on the
                    # exchange but never updated locally, preventing them from
                    # blocking new entries via symbol-lock contention.
                    if reconcile_stale_pending_orders is not None:
                        try:
                            _reconcile_result = reconcile_stale_pending_orders(
                                owner=self,
                                broker=_broker,
                            )
                            if (
                                _reconcile_result.cleared
                                or _reconcile_result.filled
                                or _reconcile_result.cancelled
                            ):
                                logger.warning(
                                    "🧹 [RECONCILE] stale pending orders cleared before scan | "
                                    "cleared=%d filled=%d cancelled=%d still_pending=%d errors=%d",
                                    _reconcile_result.cleared,
                                    _reconcile_result.filled,
                                    _reconcile_result.cancelled,
                                    _reconcile_result.still_pending,
                                    _reconcile_result.errors,
                                )
                            else:
                                logger.debug(
                                    "[RECONCILE] no stale pending orders | still_pending=%d",
                                    _reconcile_result.still_pending,
                                )
                        except Exception as _reconcile_err:
                            logger.warning(
                                "[RECONCILE] reconcile_stale_pending_orders failed (non-fatal): %s",
                                _reconcile_err,
                            )
                    # ── End reconcile stale pending orders ───────────────────

                    _symbols_to_scan = self.symbols or []
                    if not _symbols_to_scan:
                        self._maybe_refresh_symbols(force=True)
                        _symbols_to_scan = self.symbols or []
                    if not _symbols_to_scan:
                        logger.warning(
                            "⚠️ [RUN_CYCLE_EXIT] symbol universe empty — "
                            "skipping scan. RUN_CYCLE_PHASE3_START will not be reached."
                        )
                        print("[NIJA-PRINT] RUN_CYCLE_EXIT reason=symbols_empty", flush=True)
                        return next_interval_s

                    logger.critical(
                        "🔬 [RUN_CYCLE_PHASE3_START] entering Phase 3 scan | "
                        "symbols=%d balance=$%.2f open_positions=%d",
                        len(_symbols_to_scan), _account_balance, _open_positions_count,
                    )
                    print(
                        f"[NIJA-PRINT] RUN_CYCLE_PHASE3_START | "
                        f"symbols={len(_symbols_to_scan)} "
                        f"balance={_account_balance:.2f}",
                        flush=True,
                    )
                    _core_result = self.nija_core_loop.run_scan_phase(
                        broker=_broker,
                        balance=_account_balance,
                        symbols=_symbols_to_scan,
                        open_positions_count=_open_positions_count,
                        user_mode=bool(user_mode),
                    )
                    logger.critical(
                        "✅ [RUN_CYCLE_PHASE3_COMPLETE] Phase 3 scan complete | "
                        "scored=%d entered=%d blocked=%d exited=%d next=%ss",
                        _core_result.symbols_scored,
                        _core_result.entries_taken,
                        _core_result.entries_blocked,
                        _core_result.exits_taken,
                        _core_result.next_interval,
                    )
                    print(
                        f"[NIJA-PRINT] RUN_CYCLE_PHASE3_COMPLETE | "
                        f"scored={_core_result.symbols_scored} "
                        f"entered={_core_result.entries_taken} "
                        f"blocked={_core_result.entries_blocked}",
                        flush=True,
                    )

                    logger.info(
                        "run_cycle(core_loop): scored=%d entered=%d blocked=%d exited=%d next=%ss",
                        _core_result.symbols_scored,
                        _core_result.entries_taken,
                        _core_result.entries_blocked,
                        _core_result.exits_taken,
                        _core_result.next_interval,
                    )

                    try:
                        next_interval_s = max(1, int(_core_result.next_interval))
                    except Exception:
                        next_interval_s = 150
                    logger.critical(
                        "✅ [RUN_CYCLE_EXIT] cycle complete | next_interval=%ds",
                        next_interval_s,
                    )
                    print(
                        f"[NIJA-PRINT] RUN_CYCLE_EXIT | next_interval={next_interval_s}",
                        flush=True,
                    )
                    return next_interval_s



                # Run the APEX strategy cycle
                if hasattr(self.apex, "run_cycle"):
                    self.apex.run_cycle()
                elif hasattr(self.apex, "analyze_market"):

                    # Legacy fallback: fetch market data then call analyze_market(df, symbol, balance).
                    # CRITICAL FIX: capture the result and call execute_action() so signals are
                    # connected to order submission.  Previously the result was discarded, causing
                    # signals to be generated ("Score: X.X", "Trade allowed: True") but no trades
                    # to be placed because _phase3_scan_and_enter() was never reached.
                    print(
                        "[NIJA-PRINT] legacy fallback path active — "
                        f"nija_core_loop={self.nija_core_loop!r} "
                        f"symbols={len(self.symbols)} "
                        f"apex={type(self.apex).__name__}",
                        flush=True,
                    )
                    logger.critical(
                        "⚡ [RUN_CYCLE] legacy analyze_market path — "
                        "nija_core_loop unavailable, calling analyze_market+execute_action directly | "
                        "symbols=%d balance=$%.2f",
                        len(self.symbols[:20]),
                        _account_balance,
                    )
                    for symbol in self.symbols[:20]:  # cap at 20 per cycle
                        try:
                            if _broker is None or not callable(getattr(_broker, "get_candles", None)):
                                continue
                            _candles = _broker.get_candles(symbol, limit=200)
                            if isinstance(_candles, tuple):
                                _df, _err = _candles
                                if _err is not None or _df is None:
                                    continue
                            else:
                                _df = _candles
                            if _df is None:
                                continue
                            # ── FIX: capture result and call execute_action() ──────────
                            # analyze_market() generates signals and evaluates market
                            # conditions but does NOT submit orders on its own.
                            # execute_action() must be called explicitly with the result.
                            print(
                                f"[NIJA-PRINT] legacy path calling analyze_market | symbol={symbol}",
                                flush=True,
                            )
                            _analysis = self.apex.analyze_market(_df, symbol, _account_balance)
                            _action = _analysis.get("action") if isinstance(_analysis, dict) else None
                            print(
                                f"[NIJA-PRINT] legacy path analyze_market returned | "
                                f"symbol={symbol} action={_action}",
                                flush=True,
                            )
                            logger.critical(
                                "🔍 [legacy_path] analyze_market returned | symbol=%s action=%s",
                                symbol,
                                _action,
                            )
                            # Call execute_action() for any non-hold action so orders are submitted.
                            if (
                                isinstance(_analysis, dict)
                                and _action is not None
                                and _action != "hold"
                                and hasattr(self.apex, "execute_action")
                            ):
                                print(
                                    f"[NIJA-PRINT] legacy path calling execute_action | "
                                    f"symbol={symbol} action={_action}",
                                    flush=True,
                                )
                                logger.critical(
                                    "⚡ [legacy_path] calling execute_action | symbol=%s action=%s",
                                    symbol,
                                    _action,
                                )
                                _exec_result = self.apex.execute_action(_analysis, symbol)
                                print(
                                    f"[NIJA-PRINT] legacy path execute_action returned | "
                                    f"symbol={symbol} action={_action} result={_exec_result}",
                                    flush=True,
                                )
                                if _exec_result:
                                    logger.critical(
                                        "✅ [legacy_path] execute_action returned | symbol=%s action=%s result=%s",
                                        symbol,
                                        _action,
                                        _exec_result,
                                    )
                                else:
                                    logger.critical(
                                        "❌ [legacy_path] execute_action FAILED | symbol=%s action=%s "
                                        "position_size=$%.2f entry_price=%.6f stop_loss=%.6f result=%s — "
                                        "See execute_action / ExecutionEngine logs above for the broker "
                                        "rejection reason (gate name, error message, or exception).",
                                        symbol,
                                        _action,
                                        float((_analysis or {}).get("position_size", 0.0) or 0.0),
                                        float((_analysis or {}).get("entry_price", 0.0) or 0.0),
                                        float((_analysis or {}).get("stop_loss", 0.0) or 0.0),
                                        _exec_result,
                                    )
                                    print(
                                        f"[NIJA-PRINT] legacy path ORDER REJECTED | "
                                        f"symbol={symbol} action={_action} "
                                        f"size=${float((_analysis or {}).get('position_size', 0.0) or 0.0):.2f} "
                                        f"price={float((_analysis or {}).get('entry_price', 0.0) or 0.0):.6f} "
                                        f"sl={float((_analysis or {}).get('stop_loss', 0.0) or 0.0):.6f}",
                                        flush=True,
                                    )
                        except Exception as _sym_err:
                            logger.debug("Symbol %s cycle error: %s", symbol, _sym_err)
            except Exception as _cycle_err:
                logger.critical(
                    "❌ [RUN_CYCLE_ERROR] run_cycle raised exception: %s",
                    _cycle_err,
                    exc_info=True,
                )
                print(
                    f"[NIJA-PRINT] RUN_CYCLE_ERROR "
                    f"error={type(_cycle_err).__name__}: {_cycle_err}",
                    flush=True,
                )
        else:
            logger.critical(
                "⛔ [RUN_CYCLE_ERROR] run_cycle: no APEX strategy available — "
                "strategy.apex is None; cycle will be a no-op"
            )
            print("[NIJA-PRINT] RUN_CYCLE_ERROR reason=apex_is_None", flush=True)
        logger.critical(
            "✅ [RUN_CYCLE_EXIT] run_cycle returning | next_interval=%ds",
            next_interval_s,
        )
        print(
            f"[NIJA-PRINT] RUN_CYCLE_EXIT | next_interval={next_interval_s}",
            flush=True,
        )
        return next_interval_s

    def log_multi_broker_status(self) -> None:
        """Log the status of all connected brokers."""
        try:
            if self.multi_account_manager is not None and hasattr(
                self.multi_account_manager, "platform_brokers"
            ):
                _platform_brokers = self.multi_account_manager.platform_brokers or {}
                for _bt, _b in _platform_brokers.items():
                    _name = getattr(_bt, "value", str(_bt)).upper()
                    _connected = getattr(_b, "connected", False) if _b else False
                    logger.info(
                        "BROKER STATUS | %s connected=%s", _name, _connected
                    )
            elif self.broker_manager is not None and hasattr(
                self.broker_manager, "brokers"
            ):
                for _bt, _b in (self.broker_manager.brokers or {}).items():
                    _name = getattr(_bt, "value", str(_bt)).upper()
                    _connected = getattr(_b, "connected", False) if _b else False
                    logger.info(
                        "BROKER STATUS | %s connected=%s", _name, _connected
                    )
        except Exception as _log_err:
            logger.debug("log_multi_broker_status error: %s", _log_err)

    @property
    def heartbeat_trade_completed(self) -> bool:
        """True when the heartbeat trade has been attempted (pass or fail)."""
        with self._heartbeat_trade_lock:
            return self._heartbeat_trade_completed

    @property
    def heartbeat_trade_success(self) -> bool:
        """True when the heartbeat trade completed successfully."""
        with self._heartbeat_trade_lock:
            return self._heartbeat_trade_success
