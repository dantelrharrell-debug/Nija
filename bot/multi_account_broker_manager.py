"""
NIJA Multi-Account Broker Manager
==================================

Manages separate trading accounts for:
- PLATFORM account: Nija system trading account
- USER accounts: Individual user/investor accounts

Each account trades independently with its own:
- API credentials
- Trading balance
- Position tracking
- Risk limits
"""

import logging
import os
import queue
import sys
import threading
import time
from types import MappingProxyType
import traceback
from typing import Callable, Dict, List, Optional, Tuple
from enum import Enum

# Import broker classes
try:
    from bot.broker_manager import (
        BrokerType, AccountType, BaseBroker,
        CoinbaseBroker, KrakenBroker, OKXBroker, AlpacaBroker,
        KrakenStartupFSM, _KRAKEN_STARTUP_FSM,
        GLOBAL_PLATFORM_BROKERS, _PLATFORM_BROKER_INSTANCES,
        _PLATFORM_BROKER_CONNECTED, _PLATFORM_BROKER_REGISTRY_LOCK,
        get_platform_broker,
        _user_env_prefix,
    )
except ImportError:
    from broker_manager import (
        BrokerType, AccountType, BaseBroker,
        CoinbaseBroker, KrakenBroker, OKXBroker, AlpacaBroker,
        KrakenStartupFSM, _KRAKEN_STARTUP_FSM,
        GLOBAL_PLATFORM_BROKERS, _PLATFORM_BROKER_INSTANCES,
        _PLATFORM_BROKER_CONNECTED, _PLATFORM_BROKER_REGISTRY_LOCK,
        get_platform_broker,
        _user_env_prefix,
    )

# Import broker registry for platform designation tracking
try:
    from bot.broker_registry import broker_registry, BrokerCriticality
except ImportError:
    try:
        from broker_registry import broker_registry, BrokerCriticality  # type: ignore[import]
    except ImportError:
        broker_registry = None
        BrokerCriticality = None  # type: ignore[assignment,misc]

# Import account isolation manager for failure isolation
try:
    from bot.account_isolation_manager import get_isolation_manager, FailureType
except ImportError:
    try:
        from account_isolation_manager import get_isolation_manager, FailureType
    except ImportError:
        get_isolation_manager = None
        FailureType = None

# Import broker failure manager for per-broker circuit-breaker isolation
# (prevents OKX/Binance errors from cascading to and blocking Kraken)
try:
    from bot.broker_failure_manager import get_broker_failure_manager
    _BFM_AVAILABLE = True
except ImportError:
    try:
        from broker_failure_manager import get_broker_failure_manager
        _BFM_AVAILABLE = True
    except ImportError:
        get_broker_failure_manager = None
        _BFM_AVAILABLE = False
        logger.debug("broker_failure_manager not importable — per-broker circuit breaker disabled")

# Import account mode manager for hierarchy-driven mode enforcement
try:
    from bot.account_mode_manager import get_account_mode_manager, AccountMode
except ImportError:
    try:
        from account_mode_manager import get_account_mode_manager, AccountMode
    except ImportError:
        get_account_mode_manager = None
        AccountMode = None

# Import PlatformAccountLayer singleton for platform-presence gating
try:
    from bot.platform_account_layer import get_platform_account_layer
except ImportError:
    try:
        from platform_account_layer import get_platform_account_layer
    except ImportError:
        get_platform_account_layer = None

# Import CapitalAuthority singleton for unified multi-broker capital readiness
try:
    from bot.capital_authority import get_capital_authority
except ImportError:
    try:
        from capital_authority import get_capital_authority
    except ImportError:
        get_capital_authority = None  # type: ignore[assignment]

logger = logging.getLogger('nija.multi_account')

# Import Execution Risk Firewall for per-venue API-call health scoring
try:
    from bot.execution_risk_firewall import get_execution_risk_firewall as _get_erf
    _ERF_AVAILABLE = True
except ImportError:
    try:
        from execution_risk_firewall import get_execution_risk_firewall as _get_erf
        _ERF_AVAILABLE = True
    except ImportError:
        _get_erf = None
        _ERF_AVAILABLE = False

# Broker types that are treated as degraded / optional.
# DEPRECATED: use broker_registry.get_criticality() instead.  Retained for
# any external callers that still reference this symbol; the logic inside
# connect_users_from_config() now uses the registry-based criticality check.
_OPTIONAL_BROKER_TYPES: frozenset = frozenset({BrokerType.OKX})


class ConnectionState(Enum):
    """Explicit connection state for platform brokers.

    State transitions:
        NOT_STARTED  →  CONNECTING  →  CONNECTED
                                   →  FAILED

    NOT_STARTED  : Broker object registered but no connect() call has started.
                   Set by add_platform_broker() or the initial default.
    DISCONNECTED : Legacy alias — kept for backward-compat with external callers
                   that may reference this value; treated identically to NOT_STARTED.
    CONNECTING   : connect() is in progress (set by begin_platform_connection()).
    CONNECTED    : Handshake succeeded (set by _mark_platform_connected()).
    FAILED       : Handshake permanently failed (set by mark_platform_failed()).
    """
    NOT_STARTED = "not_started"    # Broker registered; no connection attempt yet
    DISCONNECTED = "disconnected"  # Backward-compat alias for NOT_STARTED
    CONNECTING = "connecting"      # connect() call in progress
    CONNECTED = "connected"        # Handshake succeeded; ready for trading
    FAILED = "failed"              # Handshake failed; user connections blocked


# Root nija logger for flushing all handlers
# Child loggers (like 'nija.multi_account', 'nija.broker') propagate to this logger
# but don't have their own handlers, so we need to flush the root logger's handlers
_root_logger = logging.getLogger('nija')

# Minimum delay between sequential connections to the same broker type
# This helps prevent nonce conflicts and API rate limiting, especially for Kraken
# CRITICAL (Jan 14, 2026): Increased from 2.0s to 5.0s to further reduce Kraken nonce conflicts
# Each Kraken broker instance initializes with a random 0-5 second nonce offset.
# A 5-second delay ensures the nonce ranges don't overlap even in worst case.
MIN_CONNECTION_DELAY = 5.0  # seconds


class MultiAccountBrokerManager:
    """
    Manages brokers for multiple accounts (master + users).

    Each account can have connections to multiple exchanges.
    Accounts are completely isolated from each other.
    """

    # Maximum length for error messages stored in failed connection tracking
    # Prevents excessive memory usage from very long error strings
    MAX_ERROR_MESSAGE_LENGTH = 50

    # CRITICAL FIX (Jan 19, 2026): Balance cache for Kraken sequential API calls
    # Railway Golden Rule #3: Kraken = sequential API calls with delay + caching
    # Problem: Sequential balance calls cause 1-1.2s delay per user
    # Solution: Cache balances per trading cycle to prevent repeated API calls
    BALANCE_CACHE_TTL = 30.0   # Cache balance for 30 seconds (was 120s — more responsive for high-frequency trading without excessive API load)
    KRAKEN_BALANCE_CALL_DELAY = 1.1  # 1.1s delay between Kraken balance API calls
    # Hard timeout for a single balance API call.  Reduced to 12s so a hung
    # Kraken connection is detected quickly and the stale cache is used instead.
    BALANCE_FETCH_TIMEOUT = 25.0  # seconds (increased from 12s; Kraken APIs can lag)
    # Maximum age of a stale cached balance that is still acceptable as a fallback
    # when the live fetch times out.  5 minutes is safe for trading decisions.
    BALANCE_STALE_FALLBACK_AGE = 300.0  # seconds

    def __init__(self):
        """Initialize multi-account broker manager."""
        # Platform account brokers - registered once globally and marked immutable
        self._platform_brokers: Dict[BrokerType, BaseBroker] = {}
        self._platform_brokers_locked: bool = False

        # Connection state machine for platform brokers
        # Tracks each broker through NOT_STARTED → CONNECTING → CONNECTED / FAILED
        self._platform_state: Dict[str, ConnectionState] = {}

        # Per-broker-type threading.Event — set once the state reaches CONNECTED or FAILED.
        # Allows wait_for_platform_ready() to block without a polling loop.
        # Created lazily via _get_or_create_platform_event() and guaranteed to be
        # the same object for any given broker_type across all threads (setdefault).
        self._platform_ready_events: Dict[str, threading.Event] = {}

        # Broker types that attempted a platform connection but failed.
        # This set is populated by mark_platform_failed() so that the HARD BLOCK in
        # connect_users_from_config() can see failed attempts even when the broker was
        # never added to _platform_brokers (which only holds successfully-connected brokers).
        self._platform_failed_types: set = set()

        # User account brokers - structure: {user_id: {BrokerType: BaseBroker}}
        self.user_brokers: Dict[str, Dict[BrokerType, BaseBroker]] = {}

        # User configurations - structure: {user_id: UserConfig}
        # Stores user configs to check independent_trading and other settings
        self.user_configs: Dict[str, any] = {}

        # FIX #3: User portfolio states for total equity tracking
        # Structure: {(user_id, broker_type): UserPortfolioState}
        self.user_portfolios: Dict[Tuple[str, str], any] = {}

        # Track users with failed connections to avoid repeated attempts in same session
        # Structure: {(user_id, broker_type): error_reason}
        self._failed_user_connections: Dict[Tuple[str, BrokerType], str] = {}

        # Track users without credentials (not an error - credentials are optional)
        # Structure: {(user_id, broker_type): True}
        self._users_without_credentials: Dict[Tuple[str, BrokerType], bool] = {}

        # Track all user broker objects (even disconnected) to check credentials_configured flag
        # Structure: {(user_id, broker_type): BaseBroker}
        self._all_user_brokers: Dict[Tuple[str, BrokerType], BaseBroker] = {}

        # CRITICAL FIX (Jan 19, 2026): Balance cache to prevent repeated Kraken API calls
        # Structure: {(account_type, account_id, broker_type): (balance, timestamp)}
        # This prevents calling get_account_balance() multiple times per cycle for same user
        self._balance_cache: Dict[Tuple[str, str, BrokerType], Tuple[float, float]] = {}
        # Track last Kraken balance API call time for rate limiting
        self._last_kraken_balance_call: float = 0.0

        # Sticky connection: track last time each platform broker was seen connected.
        # Within STICKY_CONNECTION_WINDOW seconds of a confirmed connection, treat
        # the broker as connected even if the live check briefly flips False (avoids
        # transient disconnects blocking a full trading cycle).
        self._last_platform_connected_time: Dict[BrokerType, float] = {}
        self.STICKY_CONNECTION_WINDOW: float = 120.0  # seconds (raised from 60s to absorb transient API blips)

        # Connection flag dict — keyed by broker name string (e.g. 'kraken').
        # Set to True immediately after a platform broker registers successfully.
        # Used alongside _platform_brokers to surface flag/registry mismatches.
        self._platform_connected: Dict[str, bool] = {}

        # User metadata storage for audit and reporting
        # Structure: {user_id: {'name': str, 'enabled': bool, 'brokers': {BrokerType: bool}}}
        self._user_metadata: Dict[str, Dict] = {}

        # Track Kraken copy trading status (DEPRECATED - kept for backward compatibility)
        # NOTE: Copy trading is deprecated. NIJA uses independent trading where all accounts
        # trade independently. This flag is set to True only if legacy copy trading module exists.
        # Expected value: False (copy trading module doesn't exist)
        self.kraken_copy_trading_active: bool = False

        # FIX #3: Initialize portfolio manager for user portfolio states
        try:
            from portfolio_state import get_portfolio_manager
            self.portfolio_manager = get_portfolio_manager()
            logger.info("✅ Portfolio manager initialized for user accounts")
        except ImportError:
            logger.warning("⚠️ Portfolio state module not available")
            self.portfolio_manager = None

        # ISOLATION MANAGER: Initialize account isolation manager for failure isolation
        # This ensures one account failure can NEVER affect another account
        self.isolation_manager = None
        if get_isolation_manager is not None:
            try:
                self.isolation_manager = get_isolation_manager()
                logger.info("✅ Account isolation manager initialized - failure isolation active")
            except Exception as e:
                logger.warning(f"⚠️ Could not initialize isolation manager: {e}")

        # BROKER FAILURE MANAGER: per-broker circuit breaker so OKX/Binance
        # failures are isolated and never cascade to Kraken or other venues.
        self._broker_failure_mgr = None
        if _BFM_AVAILABLE and get_broker_failure_manager is not None:
            try:
                self._broker_failure_mgr = get_broker_failure_manager()
                logger.info("✅ Broker failure manager initialized - cross-broker isolation active")
            except Exception as _bfm_init_err:
                logger.warning("⚠️ Could not initialize broker failure manager: %s", _bfm_init_err)

        # CapitalAuthority readiness + watchdog state (fail-safe auto-refresh loop)
        self._capital_ready: bool = False
        self._capital_last_refresh_ts: float = 0.0
        self._capital_watchdog_started: bool = False
        self._capital_watchdog_stop: threading.Event = threading.Event()
        self._capital_watchdog_thread: Optional[threading.Thread] = None
        self._trading_halted_due_to_capital: bool = False
        self._capital_state_lock: threading.Lock = threading.Lock()
        self.capital_watchdog_interval_s: float = float(
            os.environ.get("NIJA_CAPITAL_WATCHDOG_INTERVAL_S", "10.0")
        )
        # Max acceptable age for authority snapshot before watchdog forces refresh.
        self.capital_stale_timeout_s: float = float(
            os.environ.get("NIJA_CAPITAL_STALE_TIMEOUT_S", "30.0")
        )
        self.capital_startup_invariant_timeout_s: float = float(
            os.environ.get("NIJA_CAPITAL_STARTUP_INVARIANT_TIMEOUT_S", "30.0")
        )
        self.capital_startup_invariant_poll_s: float = float(
            os.environ.get("NIJA_CAPITAL_STARTUP_INVARIANT_POLL_S", "1.0")
        )

        logger.info("=" * 70)
        logger.info("🔒 MULTI-ACCOUNT BROKER MANAGER INITIALIZED")
        logger.info("=" * 70)

    @property
    def platform_brokers(self) -> Dict[BrokerType, BaseBroker]:
        """
        Read-only access to platform brokers.
        
        Platform brokers must be registered via add_platform_broker() or
        register_platform_broker_instance() methods. Direct assignment is not allowed.
        
        Returns:
            Read-only mapping proxy of platform brokers (Dict[BrokerType, BaseBroker])
        """
        return MappingProxyType(self._platform_brokers)
    
    def _lock_platform_brokers(self):
        """
        Lock platform brokers to prevent further modifications.
        Called after initial broker registration is complete.
        """
        self._platform_brokers_locked = True
        logger.info("🔒 Platform brokers locked (immutable)")

    def register_platform_broker_instance(
        self,
        broker_type: BrokerType,
        broker: BaseBroker,
        mark_connected_state: bool = False,
    ) -> bool:
        """
        Register an already-created broker instance for the platform account.
        
        This method is for cases where the broker is created externally with custom configuration.
        Enforces the same invariant: Platform brokers registered once, globally, and marked immutable.
        
        Args:
            broker_type: Type of broker being registered
            broker: Already-created BaseBroker instance
            
        Returns:
            True if successfully registered, False if already registered (idempotent)
            
        Raises:
            RuntimeError: If platform brokers are locked
        """
        # Enforce immutability: Cannot add brokers after locking
        if self._platform_brokers_locked:
            error_msg = f"❌ INVARIANT VIOLATION: Cannot register platform broker {broker_type.value} - platform brokers are locked (immutable)"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        # Enforce single registration: Check if already registered
        if broker_type in self._platform_brokers:
            logger.warning(f"{broker_type.value} already registered — skipping duplicate")
            return False
        
        # Register the broker instance
        self._platform_brokers[broker_type] = broker
        # Pre-create the readiness Event before advancing the state machine.
        # This guarantees that any thread which calls _get_or_create_platform_event()
        # (directly or via wait_for_platform_ready()) always gets the same Event
        # object that _mark_platform_connected() will set below.
        self._get_or_create_platform_event(broker_type)
        # Caller controls whether this registration should also transition to
        # CONNECTED.  For failed connects we must register the object without
        # forcing a CONNECTED state.
        if mark_connected_state:
            self._mark_platform_connected(broker_type)
        # Mark in the global broker registry so any module can check is_platform()
        # and get_criticality() — single source of truth across all layers.
        if broker_registry is not None:
            broker_registry[broker_type.value]["platform"] = True
            logger.debug("broker_registry[%r]['platform'] = True", broker_type.value)
            # Criticality is NOT overridden here — each broker's tier is governed
            # by BROKER_DEFAULT_CRITICALITY (OKX/Binance/Alpaca = OPTIONAL, Kraken = CRITICAL).
            # Forcing CRITICAL on every platform broker caused OKX failures to trigger
            # the HARD BLOCK and block Kraken/Coinbase user connections.
        logger.info(f"✅ Platform broker instance registered: {broker_type.value}")
        logger.info(f"   Platform broker registered once, globally")
        return True

    def refresh_capital_authority(self, trigger: str = "manual") -> Dict[str, float]:
        """
        Refresh unified CapitalAuthority from all currently connected healthy platform brokers.

        READY condition:
            - at least one healthy connected platform broker contributes, and
            - aggregated total capital > 0.0
        """
        if get_capital_authority is None:
            with self._capital_state_lock:
                self._capital_ready = False
            return {"ready": 0.0, "total_capital": 0.0, "valid_brokers": 0.0}

        try:
            authority = get_capital_authority()
            broker_map: Dict[str, BaseBroker] = {}
            for broker_type, broker in self._platform_brokers.items():
                if broker is None or not getattr(broker, "connected", False):
                    continue
                if not self.is_platform_connected(broker_type):
                    continue
                broker_map[broker_type.value] = broker

            if broker_map:
                authority.refresh(broker_map, open_exposure_usd=0.0)
            else:
                authority.refresh({}, open_exposure_usd=0.0)

            total_capital = float(authority.get_real_capital())
            valid_brokers = len(broker_map)
            # Hard capital-truth contract:
            # If Kraken is connected, Kraken's balance is the startup/readiness
            # authority. This prevents cross-venue non-zero balances from masking
            # a phantom Kraken-zero state.
            kraken_connected = "kraken" in broker_map
            kraken_capital = (
                float(authority.get_raw_per_broker("kraken"))
                if kraken_connected
                else 0.0
            )
            ready = (kraken_capital > 0.0) if kraken_connected else (total_capital > 0.0)
            with self._capital_state_lock:
                self._capital_ready = ready
                self._capital_last_refresh_ts = time.time()

            if ready:
                with self._capital_state_lock:
                    was_halted = self._trading_halted_due_to_capital
                if was_halted:
                    logger.info(
                        "✅ CapitalAuthority recovered (trigger=%s): brokers=%d total=$%.2f — trading resume allowed",
                        trigger, valid_brokers, total_capital,
                    )
                with self._capital_state_lock:
                    self._trading_halted_due_to_capital = False
            else:
                logger.error(
                    "⛔ CapitalAuthority NOT READY (trigger=%s): valid_brokers=%d total_capital=$%.2f "
                    "kraken_connected=%s kraken_capital=$%.2f",
                    trigger, valid_brokers, total_capital, kraken_connected, kraken_capital,
                )

            return {
                "ready": 1.0 if ready else 0.0,
                "total_capital": total_capital,
                "valid_brokers": float(valid_brokers),
                "kraken_capital": kraken_capital,
            }
        except Exception as exc:
            logger.error("❌ CapitalAuthority refresh failed (%s): %s", trigger, exc)
            with self._capital_state_lock:
                self._capital_ready = False
            return {"ready": 0.0, "total_capital": 0.0, "valid_brokers": 0.0}

    def resolve_startup_capital_invariant(
        self,
        trigger: str,
        timeout_s: Optional[float] = None,
        poll_s: Optional[float] = None,
    ) -> Dict[str, float]:
        """
        Hard startup invariant resolver.

        No broker connect is considered complete until CapitalAuthority is READY
        with non-zero total capital.
        """
        timeout = (
            timeout_s
            if timeout_s is not None
            else max(1.0, self.capital_startup_invariant_timeout_s)
        )
        poll = (
            poll_s
            if poll_s is not None
            else max(0.1, self.capital_startup_invariant_poll_s)
        )

        start = time.monotonic()
        attempts = 0
        snapshot: Dict[str, float] = {"ready": 0.0, "total_capital": 0.0, "valid_brokers": 0.0}

        while True:
            attempts += 1
            snapshot = self.refresh_capital_authority(trigger=f"{trigger}:attempt_{attempts}")
            total_capital = snapshot.get("total_capital", 0.0)
            if snapshot.get("ready", 0.0) > 0.0 and total_capital > 0.0:
                elapsed = time.monotonic() - start
                logger.info(
                    "✅ Startup capital invariant satisfied (%s): attempts=%d elapsed=%.2fs total=$%.2f",
                    trigger,
                    attempts,
                    elapsed,
                    total_capital,
                )
                return {
                    "ready": 1.0,
                    "total_capital": total_capital,
                    "valid_brokers": float(snapshot.get("valid_brokers", 0.0)),
                    "attempts": float(attempts),
                    "elapsed_s": float(elapsed),
                }

            elapsed = time.monotonic() - start
            if elapsed >= timeout:
                with self._capital_state_lock:
                    self._capital_ready = False
                    self._trading_halted_due_to_capital = True
                logger.error(
                    "⛔ Startup capital invariant unresolved (%s): attempts=%d elapsed=%.2fs "
                    "valid_brokers=%d total=$%.2f",
                    trigger,
                    attempts,
                    elapsed,
                    int(snapshot.get("valid_brokers", 0.0)),
                    float(snapshot.get("total_capital", 0.0)),
                )
                return {
                    "ready": 0.0,
                    "total_capital": total_capital,
                    "valid_brokers": float(snapshot.get("valid_brokers", 0.0)),
                    "attempts": float(attempts),
                    "elapsed_s": float(elapsed),
                }

            time.sleep(min(poll, max(0.0, timeout - elapsed)))

    def is_capital_authority_ready(self) -> bool:
        """Return True only when unified capital is ready for trading gates."""
        with self._capital_state_lock:
            return bool(self._capital_ready)

    def is_trading_halted_due_to_capital(self) -> bool:
        """Return True when all brokers failed / zero-capital invariant is active."""
        with self._capital_state_lock:
            return bool(self._trading_halted_due_to_capital)

    def _start_capital_watchdog(self) -> None:
        """Start fail-safe capital auto-refresh watchdog thread once per process."""
        if self._capital_watchdog_started:
            return
        self._capital_watchdog_started = True
        self._capital_watchdog_stop.clear()

        def _watchdog() -> None:
            while not self._capital_watchdog_stop.wait(self.capital_watchdog_interval_s):
                try:
                    authority = get_capital_authority() if get_capital_authority else None
                    with self._capital_state_lock:
                        needs_refresh = not self._capital_ready
                    if authority is not None and authority.is_stale(ttl_s=self.capital_stale_timeout_s):
                        needs_refresh = True
                    if needs_refresh:
                        self.refresh_capital_authority(trigger="watchdog")

                    healthy_connected = any(
                        self.is_platform_connected(bt) and getattr(b, "connected", False)
                        for bt, b in self._platform_brokers.items()
                    )
                    with self._capital_state_lock:
                        capital_ready = self._capital_ready
                        halted = self._trading_halted_due_to_capital
                    if not capital_ready and not healthy_connected:
                        if not halted:
                            logger.critical(
                                "🛑 ALL platform brokers unavailable and capital not ready — HALTING trading until recovery"
                            )
                        with self._capital_state_lock:
                            self._trading_halted_due_to_capital = True
                    elif capital_ready:
                        with self._capital_state_lock:
                            self._trading_halted_due_to_capital = False
                except Exception as exc:
                    logger.debug("Capital watchdog iteration error: %s", exc)

        self._capital_watchdog_thread = threading.Thread(
            target=_watchdog,
            name="capital-authority-watchdog",
            daemon=True,
        )
        self._capital_watchdog_thread.start()

    def add_platform_broker(self, broker_type: BrokerType) -> Optional[BaseBroker]:
        """
        Add a broker for the master (Nija system) account.
        
        Enforces invariant: Platform brokers are registered once, globally, and marked immutable.

        Args:
            broker_type: Type of broker to add (COINBASE, KRAKEN, etc.)

        Returns:
            BaseBroker instance or None if failed
            
        Raises:
            RuntimeError: If platform brokers are locked or broker already registered
        """
        try:
            # Enforce immutability: Cannot add brokers after locking
            if self._platform_brokers_locked:
                error_msg = f"❌ INVARIANT VIOLATION: Cannot add platform broker {broker_type.value} - platform brokers are locked (immutable)"
                logger.error(error_msg)
                raise RuntimeError(error_msg)
            
            # Hard-skip: broker already registered — no side effects, no exception
            if broker_type in self._platform_brokers:
                logger.info(
                    "%s already registered — skipping duplicate",
                    broker_type.value,
                )
                return False
            
            broker = None

            if broker_type == BrokerType.COINBASE:
                broker = CoinbaseBroker()
            elif broker_type == BrokerType.KRAKEN:
                broker = KrakenBroker(account_type=AccountType.PLATFORM)
            elif broker_type == BrokerType.OKX:
                broker = OKXBroker()
            elif broker_type == BrokerType.ALPACA:
                broker = AlpacaBroker()
            else:
                logger.warning(f"⚠️  Unsupported broker type for platform: {broker_type.value}")
                return None

            # Registration only — connection lifecycle is managed externally.
            # ❌ DO NOT call broker.connect() here
            # ❌ DO NOT trigger reconnect or validate connection
            self._platform_brokers[broker_type] = broker
            self._platform_state[broker_type.value] = ConnectionState.NOT_STARTED
            # Pre-create the readiness event so wait_for_platform_ready() always
            # blocks on the same object that begin_platform_connection() + connect() will set.
            self._get_or_create_platform_event(broker_type)
            # Mark in the global broker registry so any module can check is_platform()
            # and get_criticality() — single source of truth across all layers.
            if broker_registry is not None:
                broker_registry[broker_type.value]["platform"] = True
                logger.debug("broker_registry[%r]['platform'] = True", broker_type.value)
                # Criticality is NOT overridden here — each broker's tier is governed
                # by BROKER_DEFAULT_CRITICALITY (OKX/Binance/Alpaca = OPTIONAL, Kraken = CRITICAL).
                # Forcing CRITICAL on every platform broker caused OKX failures to trigger
                # the HARD BLOCK and block Kraken/Coinbase user connections.
            # Register with broker failure manager for per-broker circuit-breaking.
            if self._broker_failure_mgr is not None:
                try:
                    self._broker_failure_mgr.register_broker(broker_type.value)
                except Exception:
                    pass
            logger.info(f"✅ Platform broker registered (passive): {broker_type.value}")
            logger.info(f"   Platform broker registered once, globally")
            return broker

        except Exception as e:
            self._platform_state[broker_type.value] = ConnectionState.FAILED
            logger.error(f"❌ Error registering platform broker {broker_type.value}: {e}")
            return None

    def add_user_broker(self, user_id: str, broker_type: BrokerType) -> Optional[BaseBroker]:
        """
        Add a broker for a user account with complete isolation.
        
        ISOLATION GUARANTEE: Failures in this operation will NOT affect other accounts.
        Each user account operates independently with its own error handling.

        Args:
            user_id: User identifier (e.g., 'tania_gilbert')
            broker_type: Type of broker to add

        Returns:
            BaseBroker instance (even if not connected) or None if broker type unsupported
        """
        try:
            # Register account with isolation manager before operation
            if self.isolation_manager:
                self.isolation_manager.register_account('user', user_id, broker_type.value)
                
                # Check if account can execute operations (circuit breaker check)
                can_execute, reason = self.isolation_manager.can_execute_operation(
                    'user', user_id, broker_type.value
                )
                if not can_execute:
                    logger.warning(f"⚠️  Cannot add broker for {user_id}/{broker_type.value}: {reason}")
                    # Return None but don't count as failure - account is quarantined
                    return None
            
            broker = None

            if broker_type == BrokerType.KRAKEN:
                broker = KrakenBroker(account_type=AccountType.USER, user_id=user_id)
            elif broker_type == BrokerType.ALPACA:
                broker = AlpacaBroker(account_type=AccountType.USER, user_id=user_id)
            elif broker_type == BrokerType.COINBASE:
                broker = CoinbaseBroker(account_type=AccountType.USER, user_id=user_id)
                _short, _ = _user_env_prefix(user_id)
                logger.info("   ℹ️  Coinbase USER broker requires COINBASE_USER_%s_API_KEY / _API_SECRET", _short)
            elif broker_type == BrokerType.OKX:
                broker = OKXBroker(account_type=AccountType.USER, user_id=user_id)
                _short, _ = _user_env_prefix(user_id)
                logger.info("   ℹ️  OKX USER broker requires OKX_USER_%s_API_KEY / _API_SECRET / _PASSPHRASE", _short)
            else:
                logger.warning(f"⚠️  Unsupported broker type for user: {broker_type.value}")
                logger.warning(f"   Supported types: KRAKEN, COINBASE, OKX, ALPACA")
                return None

            # Store broker object in all_user_brokers for credential checking, even if connection fails
            connection_key = (user_id, broker_type)
            self._all_user_brokers[connection_key] = broker

            # Connect the broker (wrapped in isolation)
            connect_start = time.time()
            try:
                if broker.connect():
                    if user_id not in self.user_brokers:
                        self.user_brokers[user_id] = {}

                    self.user_brokers[user_id][broker_type] = broker
                    
                    # Record success with isolation manager
                    if self.isolation_manager:
                        operation_time_ms = (time.time() - connect_start) * 1000
                        self.isolation_manager.record_success(
                            'user', user_id, broker_type.value, operation_time_ms
                        )
                    
                    # Note: Success/failure messages are logged by the caller (connect_users_from_config)
                    # which has access to user.name for more user-friendly messages
                else:
                    # Connection failed - determine failure type and record
                    if self.isolation_manager:
                        # Check if it's an authentication error
                        if not broker.credentials_configured:
                            failure_type = FailureType.AUTHENTICATION_ERROR if FailureType else None
                        else:
                            failure_type = FailureType.NETWORK_ERROR if FailureType else None
                        
                        if failure_type:
                            self.isolation_manager.record_failure(
                                'user', user_id, broker_type.value,
                                Exception("Connection failed"),
                                failure_type
                            )
                    # Caller will log appropriate message
                    pass
                    
            except Exception as connect_error:
                # Connection attempt raised an exception - record failure
                logger.error(f"❌ Exception connecting {broker_type.value} for {user_id}: {connect_error}")
                
                if self.isolation_manager:
                    # Determine failure type from exception
                    error_str = str(connect_error).lower()
                    if 'auth' in error_str or 'credential' in error_str or 'permission' in error_str:
                        failure_type = FailureType.AUTHENTICATION_ERROR if FailureType else None
                    elif 'rate' in error_str or 'limit' in error_str:
                        failure_type = FailureType.RATE_LIMIT_ERROR if FailureType else None
                    elif 'network' in error_str or 'connection' in error_str or 'timeout' in error_str:
                        failure_type = FailureType.NETWORK_ERROR if FailureType else None
                    else:
                        failure_type = FailureType.UNKNOWN_ERROR if FailureType else None
                    
                    if failure_type:
                        self.isolation_manager.record_failure(
                            'user', user_id, broker_type.value,
                            connect_error,
                            failure_type
                        )

            return broker

        except Exception as e:
            # Top-level exception handler - ensures this account failure doesn't affect others
            logger.error(f"❌ Error adding user broker {broker_type.value} for {user_id}: {e}")
            logger.error(f"   ISOLATION: This failure is contained to {user_id} only")
            
            if self.isolation_manager and FailureType:
                self.isolation_manager.record_failure(
                    'user', user_id, broker_type.value,
                    e,
                    FailureType.UNKNOWN_ERROR
                )
            
            return None

    def get_platform_broker(self, broker_type: BrokerType) -> Optional[BaseBroker]:
        """
        Get a platform account broker.

        Args:
            broker_type: Type of broker to get

        Returns:
            BaseBroker instance or None if not found
        """
        return self._platform_brokers.get(broker_type)

    def get_user_broker(self, user_id: str, broker_type: BrokerType) -> Optional[BaseBroker]:
        """
        Get a user account broker.

        Args:
            user_id: User identifier
            broker_type: Type of broker to get

        Returns:
            BaseBroker instance or None if not found
        """
        user_brokers = self.user_brokers.get(user_id, {})
        return user_brokers.get(broker_type)

    def get_all_brokers(self) -> List[Tuple[str, BaseBroker]]:
        """
        Get all broker instances as (account_id, broker) tuples.

        Returns platform brokers and user brokers in a unified list for
        iteration by components like the continuous dust monitor.

        Returns:
            List of (account_id, broker) tuples where account_id is a
            unique identifier for the account (e.g. 'KRAKEN' for platform,
            'tania_gilbert_KRAKEN' for user accounts).
        """
        result = []
        for broker_type, broker in self._platform_brokers.items():
            result.append((broker_type.value, broker))
        for user_id, user_broker_dict in self.user_brokers.items():
            for broker_type, broker in user_broker_dict.items():
                result.append((f"{user_id}_{broker_type.value}", broker))
        return result

    def is_platform_connected(self, broker_type: BrokerType) -> bool:
        """
        Check if a platform account is connected for a given broker type.

        For Kraken: the authoritative answer comes from ``_KRAKEN_STARTUP_FSM``
        (event = truth) before falling through to the ConnectionState machine,
        ensuring the result is always consistent with what USER threads see.

        For other brokers: uses the ConnectionState machine first, then falls back
        to inspecting the live broker object (with the sticky window).

        Args:
            broker_type: Type of broker to check

        Returns:
            bool: True if platform is connected, False otherwise
        """
        try:
            # Validate broker_type parameter
            if broker_type is None:
                logger.error("❌ is_platform_connected called with broker_type=None")
                return False

            # ── Kraken: FSM gates startup; live broker.connected is the runtime truth ──
            # The FSM is a one-way startup latch (once set it never clears) so it
            # is authoritative for blocking USER threads during startup.  However,
            # for runtime "is the broker currently connected?" checks it can
            # return stale True after a post-startup drop.  We therefore check the
            # live broker object AFTER confirming the FSM fired, mirroring the
            # sticky-window logic applied to every other broker type.
            if broker_type == BrokerType.KRAKEN:
                if not _KRAKEN_STARTUP_FSM.is_connected:
                    logger.debug(
                        f"🔍 Platform broker check for {broker_type.value}: FSM=not connected"
                    )
                    return False
                # FSM says CONNECTED — platform handshake completed at least once.
                # Now verify the live broker object so a post-startup drop is not
                # reported as still connected.
                broker_obj = self._platform_brokers.get(broker_type)
                if broker_obj is not None and hasattr(broker_obj, 'connected'):
                    live = getattr(broker_obj, 'connected', False)
                    if live:
                        self._last_platform_connected_time[broker_type] = time.time()
                        logger.debug(
                            f"🔍 Platform broker check for {broker_type.value}: FSM=CONNECTED, broker=CONNECTED"
                        )
                        return True
                    # Apply sticky-connection grace window for transient drops
                    # (same logic used for non-Kraken brokers below).
                    last_seen = self._last_platform_connected_time.get(broker_type, 0.0)
                    if (time.time() - last_seen) < self.STICKY_CONNECTION_WINDOW:
                        logger.debug(
                            f"🔍 Platform broker {broker_type.value} sticky-connected "
                            f"(FSM=CONNECTED, broker=DISCONNECTED, "
                            f"last seen {time.time() - last_seen:.1f}s ago, "
                            f"window={self.STICKY_CONNECTION_WINDOW}s)"
                        )
                        return True
                    logger.debug(
                        f"🔍 Platform broker check for {broker_type.value}: FSM=CONNECTED "
                        f"but broker.connected=False ({time.time() - last_seen:.1f}s "
                        f"since last connection) — reporting as disconnected"
                    )
                    return False
                # FSM connected but no registered broker object to verify — trust FSM.
                logger.debug(
                    f"🔍 Platform broker check for {broker_type.value}: FSM=CONNECTED (no live broker object)"
                )
                return True

            # Fast path: use the explicit ConnectionState machine
            state = self._platform_state.get(broker_type.value)
            if state is not None:
                logger.debug(f"🔍 Platform broker check for {broker_type.value}: state={state.value}")
                if state == ConnectionState.CONNECTED:
                    return True
                if state == ConnectionState.FAILED:
                    return False
                # State is NOT_STARTED or CONNECTING — the FSM may lag behind the
                # actual broker object (e.g. startup race condition or reconnect).
                # Fall through to the live-broker check below so a broker that is
                # already authenticated is not incorrectly reported as disconnected.
                logger.debug(
                    f"🔍 Platform broker {broker_type.value}: FSM state={state.value} "
                    f"— falling through to live broker check"
                )

            # Fallback: no state entry yet — check the live broker object
            broker_in_dict = broker_type in self.platform_brokers

            if not broker_in_dict:
                logger.debug(f"🔍 Platform broker check for {broker_type.value}: NOT in platform_brokers dict")
                registered = ', '.join(bt.value for bt in self.platform_brokers.keys()) if self.platform_brokers else 'none'
                logger.debug(f"   Registered platform brokers: {registered}")
                return False

            broker_obj = self.platform_brokers[broker_type]

            # Defensive check: Ensure broker object exists and has connected attribute
            if broker_obj is None:
                logger.debug(f"🔍 Platform broker check for {broker_type.value}: broker object is None")
                return False

            if not hasattr(broker_obj, 'connected'):
                logger.debug(f"🔍 Platform broker check for {broker_type.value}: broker has no 'connected' attribute")
                return False

            connected_status = broker_obj.connected
            logger.debug(f"🔍 Platform broker check for {broker_type.value}: broker={broker_obj.__class__.__name__}, connected={connected_status}")

            if connected_status:
                # Sync state machine and all related invariant mirrors.
                self._transition_platform_state(broker_type, ConnectionState.CONNECTED)
                return True

            # Sticky connection grace window: if the broker was connected very
            # recently (within STICKY_CONNECTION_WINDOW seconds), treat it as
            # still connected to absorb transient API hiccups.
            last_seen = self._last_platform_connected_time.get(broker_type, 0.0)
            if (time.time() - last_seen) < self.STICKY_CONNECTION_WINDOW:
                logger.debug(
                    f"🔍 Platform broker {broker_type.value} sticky-connected "
                    f"(last seen {time.time() - last_seen:.1f}s ago, window={self.STICKY_CONNECTION_WINDOW}s)"
                )
                return True

            return False

        except Exception:
            # Use logger.exception() to automatically include traceback
            # Safe fallback for broker name in case broker_type is malformed
            try:
                broker_name = broker_type.value
            except (AttributeError, TypeError):
                broker_name = str(broker_type) if broker_type else "Unknown"

            logger.exception(f"❌ Error checking platform broker connection for {broker_name}: This is unexpected - please report this error")
            return False

    def _wait_and_retry_platform_connection(
        self,
        broker_type: BrokerType,
        retries: int = 15,
        wait_secs: float = 2.0,
    ) -> bool:
        """
        Wait briefly and retry the platform connection check.

        Called when :meth:`is_platform_connected` returns ``False`` during
        user account setup.  Returns ``True`` as soon as the platform broker
        reports as connected; ``False`` if it is still offline after all
        retries.

        The default retry window is 15 × 2 s = 30 s, which gives the
        Platform broker enough time to complete its own internal retry loop.
        The Platform's KrakenBroker.connect() uses exponential back-off:
        attempt 1 at T+0, then waits 5s, 10s, 20s, 40s between retries—
        up to ~75 s total for 5 attempts.  30 s of user-side polling covers
        the first 2–3 Platform retry windows, which is sufficient for most
        transient failures (nonce errors, brief network blips).

        Args:
            broker_type: Exchange to check.
            retries: Number of additional attempts before giving up.
                     Default raised from 3 → 15 (30 s total window).
            wait_secs: Seconds to wait between each attempt.

        Returns:
            bool: True if platform became connected within the retry window.
        """
        broker_name = broker_type.value.upper()
        # Only log a progress line every 5 attempts to avoid flooding the log
        # while still giving visibility into the wait.
        for attempt in range(1, retries + 1):
            if attempt == 1 or attempt % 5 == 0:
                logger.info(
                    f"   ⏳ Platform {broker_name} not connected yet — "
                    f"waiting {wait_secs:.0f}s before retry {attempt}/{retries}..."
                )
            else:
                logger.debug(
                    f"   ⏳ Platform {broker_name} retry {attempt}/{retries}..."
                )
            time.sleep(wait_secs)
            logger.info(
                f"DEBUG: platform_connected_flag={self._platform_connected.get(broker_type.value)} "
                f"broker_exists={bool(self._platform_brokers.get(broker_type))}"
            )
            if self.is_platform_connected(broker_type):
                logger.info(
                    f"   ✅ Platform {broker_name} connected on retry {attempt}"
                )
                return True
        logger.warning(
            f"   ⚠️  Platform {broker_name} still not connected after "
            f"{retries} retries ({int(retries * wait_secs)}s total)"
        )
        return False

    def _get_or_create_platform_event(self, broker_type: BrokerType) -> threading.Event:
        """Return the readiness Event for *broker_type*, creating it if absent.

        Uses ``dict.setdefault`` directly so the operation is atomic under the
        GIL: only one ``threading.Event`` is ever stored for a given broker type,
        regardless of how many threads call this method concurrently.
        """
        return self._platform_ready_events.setdefault(broker_type.value, threading.Event())

    def _transition_platform_state(self, broker_type: BrokerType, new_state: ConnectionState) -> None:
        """Apply a platform-state transition while keeping all FSM invariants aligned.

        Invariants enforced per transition:
          - ``_platform_state[key]`` always matches the latest transition target.
          - ``_platform_connected[key]`` is True only in CONNECTED.
          - ``_platform_failed_types`` includes broker_type only in FAILED.
          - ``_last_platform_connected_time[broker_type]`` is refreshed only in CONNECTED.
          - ``_platform_ready_events[key]`` is set in terminal states (CONNECTED/FAILED)
            and cleared in non-terminal states (CONNECTING/NOT_STARTED/DISCONNECTED).
          - Kraken startup FSM mirror is synchronized for CONNECTED/FAILED transitions.
        """
        key = broker_type.value
        event = self._get_or_create_platform_event(broker_type)
        self._platform_state[key] = new_state

        if new_state == ConnectionState.CONNECTED:
            self._platform_connected[key] = True
            self._platform_failed_types.discard(broker_type)
            self._last_platform_connected_time[broker_type] = time.time()
            if broker_type == BrokerType.KRAKEN:
                _KRAKEN_STARTUP_FSM.mark_connected()
            event.set()
            return

        if new_state == ConnectionState.FAILED:
            self._platform_connected[key] = False
            self._platform_failed_types.add(broker_type)
            if broker_type == BrokerType.KRAKEN:
                _KRAKEN_STARTUP_FSM.mark_failed()
            event.set()
            return

        # CONNECTING / NOT_STARTED / DISCONNECTED
        self._platform_connected[key] = False
        event.clear()

    def begin_platform_connection(self, broker_type: BrokerType) -> None:
        """Signal that a platform connection attempt is about to start.

        Advances the state machine to CONNECTING and pre-creates the
        readiness Event so waiters in :meth:`wait_for_platform_ready`
        always block on the *same* event object, eliminating the
        create-then-set race condition.

        Call this immediately before invoking the broker's ``connect()``
        method (e.g. in ``trading_strategy.py`` before ``kraken.connect()``).
        """
        self._transition_platform_state(broker_type, ConnectionState.CONNECTING)
        logger.info(
            "🔄 Platform %s connection starting (state → CONNECTING)",
            broker_type.value.upper(),
        )

    def _mark_platform_connected(self, broker_type: BrokerType) -> None:
        """Advance the state machine to CONNECTED and record the timestamp.

        Extracted as a helper to avoid duplicating these two lines in every
        place that needs to confirm the platform broker is ready.
        Also notifies the PlatformAccountLayer singleton so that its
        ``platform_connected`` status flag reflects live broker state.

        For Kraken: also ensures the FSM is in CONNECTED state (idempotent —
        ``mark_connected()`` is a no-op after the first call).
        """
        self._transition_platform_state(broker_type, ConnectionState.CONNECTED)
        # Propagate connected status to the PlatformAccountLayer singleton so
        # display_hierarchy() and external health checks see "CONNECTED".
        try:
            _pal = get_platform_account_layer() if get_platform_account_layer is not None else None
            if _pal is not None:
                _pal.mark_platform_connected(True)
        except Exception:
            pass  # Never block the connection flow on a status-update failure
        # Record connection success with broker failure manager so the
        # per-broker circuit breaker stays in sync.
        if self._broker_failure_mgr is not None:
            try:
                self._broker_failure_mgr.record_success(broker_type.value)
            except Exception:
                pass
        # Record API success with the execution risk firewall venue scorer.
        if _ERF_AVAILABLE and _get_erf is not None:
            try:
                _get_erf().record_api_call(
                    venue=broker_type.value, latency_ms=0.0, success=True
                )
            except Exception:
                pass

    def mark_platform_failed(self, broker_type: BrokerType) -> None:
        """
        Record that a platform connection ATTEMPT was made but FAILED.

        Call this from trading_strategy.py (or any startup path) when a
        platform broker's connect() returns False.  This ensures that the
        HARD BLOCK in connect_users_from_config() can see the failure even
        though the broker was never added to _platform_brokers (which only
        stores successfully-connected brokers).

        For Kraken: also transitions the FSM to FAILED so USER threads that
        are blocked in ``wait_connected()`` are unblocked immediately instead
        of waiting for a timeout.

        USER accounts will be blocked from connecting until the platform
        either succeeds (clears this flag) or is explicitly retried.
        """
        self._transition_platform_state(broker_type, ConnectionState.FAILED)
        # Log at ERROR for CRITICAL brokers (they block trading) and WARNING
        # for non-CRITICAL brokers (system degrades but continues without them).
        is_critical = (
            broker_registry is not None
            and BrokerCriticality is not None
            and broker_registry.get_criticality(broker_type.value) == BrokerCriticality.CRITICAL
        )
        if is_critical:
            logger.error(
                "⛔ Platform %s (CRITICAL) connection FAILED — user accounts BLOCKED until "
                "platform reconnects.  Fix credentials or network, then restart.",
                broker_type.value.upper(),
            )
        else:
            logger.warning(
                "⚠️ Platform %s (non-CRITICAL) connection FAILED — system continues "
                "without this broker.  Fix credentials or network when possible.",
                broker_type.value.upper(),
            )
        # Record failure with broker failure manager — this increments the
        # per-broker error counter so the circuit breaker can disable only this
        # broker without affecting Kraken or other healthy venues.
        if self._broker_failure_mgr is not None:
            try:
                self._broker_failure_mgr.record_error(
                    broker_type.value,
                    reason=f"platform connect failed for {broker_type.value}",
                )
                if self._broker_failure_mgr.is_dead(broker_type.value):
                    logger.warning(
                        "🔌 Broker failure manager: '%s' quarantined — "
                        "other venues remain unaffected",
                        broker_type.value,
                    )
            except Exception:
                pass
        # Record API failure with the execution risk firewall venue scorer so
        # a repeated series of connection failures degrades the venue's health
        # score and eventually disables it automatically.
        if _ERF_AVAILABLE and _get_erf is not None:
            try:
                _get_erf().record_api_call(
                    venue=broker_type.value, latency_ms=0.0, success=False
                )
            except Exception:
                pass

    @staticmethod
    def _broker_ready_flag(broker) -> bool:
        """Return True when the broker has signalled readiness.

        For Kraken brokers the authoritative source is the module-level
        ``_KRAKEN_STARTUP_FSM`` (event = truth).  For all other broker types
        the legacy ``_platform_ready_flag`` attribute is checked so that
        non-Kraken brokers continue to work without changes.
        """
        if broker is None:
            return False
        if isinstance(broker, KrakenBroker):
            return _KRAKEN_STARTUP_FSM.is_connected
        return getattr(broker, "_platform_ready_flag", False)

    def wait_for_platform_ready(self, broker_type: BrokerType, timeout: int = None) -> bool:
        """
        Block until the platform broker is fully connected or a hard failure occurs.

        For Kraken: delegates directly to ``_KRAKEN_STARTUP_FSM.wait_connected()``
        (event = truth).  There is no polling loop, no partial-state window, and
        no dual-representation drift.  USER threads stay parked in the FSM's
        ``threading.Event.wait()`` until the single ``mark_connected()`` call fires,
        regardless of how many nonce retry cycles the PLATFORM account needs.

        For other broker types: falls back to the ``ConnectionState`` machine so
        non-Kraken brokers continue to work unchanged.

        The wait is indefinite by default — exits only on CONNECTED (True) or FAILED
        (False).  Set NIJA_PLATFORM_WAIT_TIMEOUT to a positive integer (seconds) to
        impose an upper ceiling.

        Args:
            broker_type: Exchange to wait for.
            timeout: Optional maximum seconds to wait.  Defaults to
                     NIJA_PLATFORM_WAIT_TIMEOUT env var; if unset or 0 the wait
                     is indefinite.

        Returns:
            bool: True if platform reached CONNECTED state, False on hard failure.
        """
        env_val = os.environ.get("NIJA_PLATFORM_WAIT_TIMEOUT", "0")
        if timeout is None:
            timeout = int(env_val) if env_val.strip().isdigit() else 0
        broker_name = broker_type.value.upper()
        # timeout=0 (default / env unset) means *indefinite* — consistent with
        # the original behaviour.  Callers that want a finite ceiling must pass
        # a positive integer or set NIJA_PLATFORM_WAIT_TIMEOUT.
        fsm_timeout = float(timeout) if timeout > 0 else None

        # ── Kraken: single FSM wait — zero dual-representation drift ──────────
        if broker_type == BrokerType.KRAKEN:
            # Fast path: already connected.
            if _KRAKEN_STARTUP_FSM.is_connected:
                logger.info(f"✅ Platform {broker_name} ready (FSM fast-path)")
                self._mark_platform_connected(broker_type)
                return True
            # Fast path: already failed.
            if _KRAKEN_STARTUP_FSM.is_failed:
                logger.error(f"❌ Platform {broker_name} connection failed (FSM)")
                return False
            logger.info(
                f"⏳ Platform {broker_name} — waiting for FSM CONNECTED signal"
                + (f" (up to {timeout}s)" if fsm_timeout else " (indefinite)") + " …"
            )
            result = _KRAKEN_STARTUP_FSM.wait_connected(timeout=fsm_timeout)
            if result:
                logger.info(f"✅ Platform {broker_name} fully ready (FSM)")
                self._mark_platform_connected(broker_type)
            else:
                logger.error(
                    f"❌ Platform {broker_name} did not reach CONNECTED"
                    + (" (FSM FAILED)" if _KRAKEN_STARTUP_FSM.is_failed else " (FSM timeout)")
                )
            return result

        # ── Non-Kraken: existing ConnectionState-machine path ─────────────────
        start = time.time()

        # `start` is captured here so `timeout` is the total function budget,
        # including fast-path checks.  The few milliseconds they take is
        # negligible and keeps the accounting simple.
        start = time.time()

        # ── Fast-path 1: state machine already at CONNECTED / FAILED ──────────
        state = self._platform_state.get(broker_type.value)
        if state == ConnectionState.CONNECTED:
            logger.info(f"✅ Platform {broker_name} ready (state=CONNECTED, fast-path)")
            return True
        if state == ConnectionState.FAILED:
            logger.error(f"❌ Platform {broker_name} previously FAILED (fast-path)")
            return False

        # ── Fast-path 2: broker's _platform_ready_flag already set ───────────
        broker = self._platform_brokers.get(broker_type)
        if self._broker_ready_flag(broker):
            logger.info(f"✅ Platform {broker_name} ready (fast-path via ready flag)")
            self._mark_platform_connected(broker_type)
            return True

        # ── Event-based wait ──────────────────────────────────────────────────
        # _get_or_create_platform_event() uses setdefault so we always operate
        # on the same threading.Event that _mark_platform_connected() and
        # mark_platform_failed() will call .set() on.
        event = self._get_or_create_platform_event(broker_type)
        logger.info(
            "⏳ Platform %s not yet ready (state=%s) — waiting event-driven%s …",
            broker_name,
            state.value if state else "unknown",
            f" (max {timeout}s)" if timeout > 0 else " (indefinite)",
        )

        if timeout > 0:
            remaining = max(0.0, timeout - (time.time() - start))
            event.wait(timeout=remaining)
        else:
            event.wait()  # indefinite — unblocked only by _mark_platform_connected / mark_platform_failed

            if self._broker_ready_flag(broker):
                logger.info(f"✅ Platform {broker_name} ready (ready flag set during wait)")
                self._mark_platform_connected(broker_type)
                return True

            if timeout > 0 and (time.time() - start) >= timeout:
                logger.error(f"⛔ Timeout waiting for platform {broker_name} to become ready ({timeout}s)")
                return False
        # ── Post-wait state check ─────────────────────────────────────────────
        state = self._platform_state.get(broker_type.value)
        if state == ConnectionState.CONNECTED:
            logger.info(f"✅ Platform {broker_name} fully ready (unblocked by event)")
            return True
        if state == ConnectionState.FAILED:
            logger.error(f"❌ Platform {broker_name} failed to connect (unblocked by event)")
            return False

        # Also re-check _platform_ready_flag in case connect() completed while
        # we were waiting but before the state machine was updated.
        if self._broker_ready_flag(broker):
            logger.info(f"✅ Platform {broker_name} ready (_platform_ready_flag set during wait)")
            self._mark_platform_connected(broker_type)
            return True

        # Reached here only when timeout fired without CONNECTED / FAILED
        if timeout > 0:
            logger.error(
                "⛔ Timeout waiting for platform %s to become ready (%ds). "
                "Last state: %s",
                broker_name, timeout,
                state.value if state else "unknown",
            )
        else:
            logger.warning(
                "⚠️ Platform %s event fired but state is still %s — possible concurrent reset.",
                broker_name,
                state.value if state else "unknown",
            )
        return False

    def user_has_credentials(self, user_id: str, broker_type: BrokerType) -> bool:
        """
        Check if a user has credentials configured for a broker type.

        Args:
            user_id: User identifier
            broker_type: Type of broker

        Returns:
            bool: True if credentials are configured, False if not or unknown
        """
        connection_key = (user_id, broker_type)

        # If explicitly tracked as no credentials, return False
        if connection_key in self._users_without_credentials:
            return False

        # Check if we have a broker object (even if disconnected) to check credentials
        # This is the primary and most reliable check since all brokers inherit credentials_configured from BaseBroker
        if connection_key in self._all_user_brokers:
            broker = self._all_user_brokers[connection_key]
            return broker.credentials_configured

        # Check if broker exists in user_brokers (only added when connected)
        # If connected, credentials must have been configured
        if user_id in self.user_brokers and broker_type in self.user_brokers[user_id]:
            broker = self.user_brokers[user_id][broker_type]
            return broker.credentials_configured

        # Unknown state - default to False (no credentials)
        # This is the safe default: if we don't know, assume no credentials
        return False

    def _get_cached_balance(self, account_type: str, account_id: str, broker_type: BrokerType, broker: BaseBroker) -> float:
        """
        Get balance with caching for Kraken to prevent repeated API calls.

        CRITICAL FIX (Jan 19, 2026): Railway Golden Rule #3 - Kraken sequential API calls
        Problem: Users not appearing funded because balance calls are sequential (1-1.2s delay each)
        Solution: Cache balances per trading cycle, add 1-1.2s delay between calls

        Args:
            account_type: 'platform' or 'user'
            account_id: Account identifier (e.g., 'platform', 'tania_gilbert')
            broker_type: Type of broker
            broker: Broker instance

        Returns:
            Balance in USD
        """
        cache_key = (account_type, account_id, broker_type)
        current_time = time.time()

        # Check if we have a valid cached balance
        if cache_key in self._balance_cache:
            cached_balance, cache_time = self._balance_cache[cache_key]
            age = current_time - cache_time

            if age < self.BALANCE_CACHE_TTL:
                logger.debug(f"Using cached balance for {account_type} {account_id} on {broker_type.value}: ${cached_balance:.2f} (age: {age:.1f}s)")
                return cached_balance

        # Need to fetch fresh balance from API
        # For Kraken, add delay between sequential calls to prevent rate limiting
        # NOTE: time.sleep() is intentional (Railway Golden Rule #3)
        # Kraken requires sequential API calls with delay to prevent nonce conflicts
        # This blocking operation is necessary for Railway deployment stability
        if broker_type == BrokerType.KRAKEN:
            time_since_last_call = current_time - self._last_kraken_balance_call
            if time_since_last_call < self.KRAKEN_BALANCE_CALL_DELAY:
                delay = self.KRAKEN_BALANCE_CALL_DELAY - time_since_last_call
                logger.debug(f"Kraken rate limit: waiting {delay:.2f}s before balance call")
                time.sleep(delay)  # Intentional blocking for Kraken rate limiting

            self._last_kraken_balance_call = time.time()

        # Fetch balance from broker API with a hard timeout so a slow or hung
        # Kraken connection never blocks the entire trading cycle.
        # Non-daemon thread so the API call can complete cleanly on shutdown.
        result_queue: queue.Queue = queue.Queue()

        def _fetch():
            try:
                result_queue.put((True, broker.get_account_balance()))
            except Exception as _e:
                result_queue.put((False, _e))

        fetch_thread = threading.Thread(target=_fetch, daemon=False)
        fetch_thread.start()
        fetch_thread.join(self.BALANCE_FETCH_TIMEOUT)

        if fetch_thread.is_alive():
            # Timed out — use any cached balance (stale or otherwise) as fallback.
            # The conditional only controls which warning message is emitted;
            # the balance is returned unconditionally.  Only return 0.0 if no cache exists.
            logger.warning(
                f"Balance fetch timed out after {self.BALANCE_FETCH_TIMEOUT:.0f}s "
                f"for {account_type} {account_id} on {broker_type.value}"
            )
            if cache_key in self._balance_cache:
                _stale_bal, _stale_ts = self._balance_cache[cache_key]
                _stale_age = current_time - _stale_ts
                if _stale_age <= self.BALANCE_STALE_FALLBACK_AGE:
                    logger.warning(
                        f"Using stale cached balance ${_stale_bal:.2f} "
                        f"(age {_stale_age:.0f}s) for {account_type} {account_id}"
                    )
                else:
                    logger.warning(
                        f"Cached balance is very old ({_stale_age:.0f}s > "
                        f"{self.BALANCE_STALE_FALLBACK_AGE:.0f}s) for {account_type} {account_id}"
                        f" — using stale balance as last resort (grace mode)"
                    )
                return _stale_bal  # Always return cached value — 0.0 only if no cache
            # No cache at all — nothing to fall back to
            logger.error(
                f"No cached balance available for {account_type} {account_id} on "
                f"{broker_type.value}; returning 0"
            )
            return 0.0

        try:
            success, value = result_queue.get_nowait()
        except queue.Empty:
            success, value = False, Exception("No result in queue after thread join")

        if not success:
            logger.error(
                f"Balance fetch raised exception for {account_type} {account_id}: {value}"
            )
            # Fall back to stale cache on exception too.  Any cached value is
            # returned unconditionally — the conditional only controls whether an
            # extra "very old" warning is emitted.  Only return 0.0 if no cache exists.
            if cache_key in self._balance_cache:
                _stale_bal, _stale_ts = self._balance_cache[cache_key]
                _stale_age = current_time - _stale_ts
                if _stale_age > self.BALANCE_STALE_FALLBACK_AGE:
                    logger.warning(
                        f"Cached balance is very old ({_stale_age:.0f}s) for "
                        f"{account_type} {account_id} — using stale balance as last resort (grace mode)"
                    )
                else:
                    logger.warning(
                        f"Using stale cached balance ${_stale_bal:.2f} "
                        f"(age {_stale_age:.0f}s) for {account_type} {account_id}"
                    )
                return _stale_bal  # Always return cached value — 0.0 only if no cache
            return 0.0

        balance = value

        # Cache the result
        self._balance_cache[cache_key] = (balance, time.time())
        logger.debug(f"Cached fresh balance for {account_type} {account_id} on {broker_type.value}: ${balance:.2f}")

        return balance

    def clear_balance_cache(self):
        """
        Clear the balance cache.

        Call this at the start of each trading cycle to force fresh balance fetches.
        This ensures balances are updated once per cycle but not more frequently.
        """
        self._balance_cache.clear()
        logger.debug("Balance cache cleared for new trading cycle")

    def try_reconnect_platform_broker(self, broker_type: BrokerType) -> bool:
        """
        Attempt to reconnect a platform broker that is registered but not connected.

        This is called from the main trading loop as a background self-heal so
        that a transient startup failure (network blip, nonce error, rate-limit)
        does not permanently prevent the Platform account from trading.

        Returns True if the broker is now connected after the attempt; False
        if it is still offline (caller should retry on the next cycle).
        """
        broker = self._platform_brokers.get(broker_type)
        if broker is None:
            return False
        if broker.connected:
            return True  # Already connected – nothing to do

        broker_name = broker_type.value.upper()
        logger.info(f"🔄 Background reconnect: attempting to reconnect Platform {broker_name}…")
        try:
            if broker.connect():
                logger.info(f"   ✅ Platform {broker_name} reconnected successfully")
                return True
            else:
                logger.debug(f"   ⚠️  Platform {broker_name} reconnect attempt failed (will retry later)")
                return False
        except Exception as exc:
            logger.debug(f"   ⚠️  Platform {broker_name} reconnect error: {exc}")
            return False

    def get_platform_balance(self, broker_type: Optional[BrokerType] = None) -> float:
        """
        Get platform account balance.

        Args:
            broker_type: Specific broker or None for total across all brokers

        Returns:
            Balance in USD
        """
        if broker_type:
            broker = self._platform_brokers.get(broker_type)
            if not broker:
                return 0.0

            # CRITICAL FIX (Jan 19, 2026): Use cached balance for Kraken to prevent repeated API calls
            if broker_type == BrokerType.KRAKEN:
                return self._get_cached_balance('platform', 'platform', broker_type, broker)

            return broker.get_account_balance()

        # Total across all master brokers
        total = 0.0
        for broker_type, broker in self._platform_brokers.items():
            if broker.connected:
                if broker_type == BrokerType.KRAKEN:
                    total += self._get_cached_balance('platform', 'platform', broker_type, broker)
                else:
                    total += broker.get_account_balance()
        return total

    def get_user_balance(self, user_id: str, broker_type: Optional[BrokerType] = None) -> float:
        """
        Get user account balance with isolation guarantee.
        
        ISOLATION GUARANTEE: Balance fetch failures for one account will NOT affect other accounts.

        Args:
            user_id: User identifier
            broker_type: Specific broker or None for total across all brokers

        Returns:
            Balance in USD
        """
        user_brokers = self.user_brokers.get(user_id, {})

        if broker_type:
            broker = user_brokers.get(broker_type)
            if not broker:
                return 0.0

            # Check isolation manager before fetching balance
            if self.isolation_manager:
                can_execute, reason = self.isolation_manager.can_execute_operation(
                    'user', user_id, broker_type.value
                )
                if not can_execute:
                    logger.debug(f"Cannot fetch balance for {user_id}/{broker_type.value}: {reason}")
                    return 0.0

            try:
                # CRITICAL FIX (Jan 19, 2026): Use cached balance for Kraken to prevent repeated API calls
                if broker_type == BrokerType.KRAKEN:
                    balance = self._get_cached_balance('user', user_id, broker_type, broker)
                else:
                    balance = broker.get_account_balance()
                
                # Record success with isolation manager
                if self.isolation_manager:
                    self.isolation_manager.record_success('user', user_id, broker_type.value)
                
                return balance
                
            except Exception as e:
                logger.error(f"❌ Error fetching balance for {user_id}/{broker_type.value}: {e}")
                logger.error(f"   ISOLATION: This failure is contained to {user_id} only")
                
                # Record failure with isolation manager
                if self.isolation_manager and FailureType:
                    self.isolation_manager.record_failure(
                        'user', user_id, broker_type.value,
                        e,
                        FailureType.BALANCE_ERROR
                    )
                
                return 0.0

        # Total across all user brokers (isolation applied per broker)
        total = 0.0
        for broker_type, broker in user_brokers.items():
            if broker.connected:
                # Check isolation for this specific broker
                can_execute = True
                if self.isolation_manager:
                    can_execute, _ = self.isolation_manager.can_execute_operation(
                        'user', user_id, broker_type.value
                    )
                
                if can_execute:
                    try:
                        if broker_type == BrokerType.KRAKEN:
                            total += self._get_cached_balance('user', user_id, broker_type, broker)
                        else:
                            total += broker.get_account_balance()
                        
                        # Record success
                        if self.isolation_manager:
                            self.isolation_manager.record_success('user', user_id, broker_type.value)
                            
                    except Exception as e:
                        # Log error but continue with other brokers (isolation guarantee)
                        logger.error(f"❌ Error fetching balance for {user_id}/{broker_type.value}: {e}")
                        logger.error(f"   ISOLATION: Continuing with other brokers")
                        
                        if self.isolation_manager and FailureType:
                            self.isolation_manager.record_failure(
                                'user', user_id, broker_type.value,
                                e,
                                FailureType.BALANCE_ERROR
                            )
                        
                        # Continue to next broker - don't let one failure stop others
                        continue
        
        return total

    def update_user_portfolio(self, user_id: str, broker_type: BrokerType) -> Optional[any]:
        """
        Update portfolio state for a user account.

        FIX #3: Maintains user-specific portfolio state with total equity tracking.

        Args:
            user_id: User identifier
            broker_type: Broker type

        Returns:
            UserPortfolioState or None if not available
        """
        if not self.portfolio_manager:
            return None

        # Get user's broker
        broker = self.get_user_broker(user_id, broker_type)
        if not broker or not broker.connected:
            return None

        try:
            # Get current balance and positions
            balance = broker.get_account_balance()
            positions = broker.get_positions() if hasattr(broker, 'get_positions') else []

            # Get or create user portfolio state
            portfolio_key = (user_id, broker_type.value)
            if portfolio_key not in self.user_portfolios:
                # Initialize new user portfolio
                user_portfolio = self.portfolio_manager.initialize_user_portfolio(
                    user_id=user_id,
                    broker_type=broker_type.value,
                    available_cash=balance
                )
                self.user_portfolios[portfolio_key] = user_portfolio
            else:
                user_portfolio = self.user_portfolios[portfolio_key]

            # Update portfolio from broker data
            self.portfolio_manager.update_portfolio_from_broker(
                portfolio=user_portfolio,
                available_cash=balance,
                positions=positions
            )

            logger.debug(
                f"Updated portfolio for {user_id} ({broker_type.value}): "
                f"equity=${user_portfolio.total_equity:.2f}, positions={user_portfolio.position_count}"
            )

            return user_portfolio

        except Exception as e:
            logger.warning(f"Failed to update portfolio for {user_id} ({broker_type.value}): {e}")
            return None

    def get_user_portfolio(self, user_id: str, broker_type: BrokerType) -> Optional[any]:
        """
        Get portfolio state for a user.

        Args:
            user_id: User identifier
            broker_type: Broker type

        Returns:
            UserPortfolioState or None if not found
        """
        portfolio_key = (user_id, broker_type.value)
        return self.user_portfolios.get(portfolio_key)

    def get_all_balances(self) -> Dict:
        """
        Get balances for all accounts.

        CRITICAL FIX (Jan 23, 2026): Include ALL configured users and their brokers,
        even if credentials are not configured or connection failed.
        This ensures maximum visibility - users can see all accounts that are supposed to exist.

        Returns:
            dict with structure: {
                'platform': {broker_type: balance, ...},
                'users': {user_id: {broker_type: balance, ...}, ...}
            }
        """
        result = {
            'platform': {},
            'users': {}
        }

        # Platform balances
        for broker_type, broker in self._platform_brokers.items():
            if broker.connected:
                result['platform'][broker_type.value] = broker.get_account_balance()

        # User balances - include ALL users from metadata with ALL their brokers
        # CRITICAL FIX: Use metadata as source of truth for which users/brokers should exist
        for user_id, metadata in self._user_metadata.items():
            if user_id not in result['users']:
                result['users'][user_id] = {}

            # Add all brokers from metadata for this user
            for broker_type in metadata.get('brokers', {}).keys():
                broker_name = broker_type.value
                # Initialize with $0.00 - will be updated if we can get actual balance
                result['users'][user_id][broker_name] = 0.0

        # Then update with actual balances for connected users
        for user_id, user_brokers in self.user_brokers.items():
            if user_id not in result['users']:
                result['users'][user_id] = {}
            for broker_type, broker in user_brokers.items():
                if broker.connected:
                    try:
                        result['users'][user_id][broker_type.value] = broker.get_account_balance()
                    except Exception as e:
                        logger.debug(f"Could not get balance for {user_id}/{broker_type.value}: {e}")
                        # Keep the $0.00 default

        # Also try to get balances from _all_user_brokers (in case some are connected but not in user_brokers)
        for (user_id, broker_type), broker in self._all_user_brokers.items():
            if user_id not in result['users']:
                result['users'][user_id] = {}

            # Only update if broker is not already in results (avoid overwriting connected broker balances)
            # CRITICAL: Check if broker_type exists in result, not if balance is 0.0
            # This prevents overwriting legitimate $0.00 balances from connected brokers
            if broker_type.value not in result['users'][user_id]:
                try:
                    if broker.connected:
                        result['users'][user_id][broker_type.value] = broker.get_account_balance()
                    # If not connected, keep $0.00 (already set above or default)
                except Exception as e:
                    logger.debug(f"Could not get balance for {user_id}/{broker_type.value}: {e}")
                    # Keep the $0.00 default

        return result

    def _get_broker_credentials_status(self, broker: BaseBroker) -> bool:
        """
        Helper to safely check if broker has credentials configured.

        Args:
            broker: Broker instance to check

        Returns:
            True if credentials are configured, False otherwise
        """
        return getattr(broker, 'credentials_configured', False)

    def get_all_balances_with_status(self) -> Dict:
        """
        Get balances for all accounts with connection and credential status.

        CRITICAL FIX (Jan 23, 2026): Provide detailed status for all users to improve visibility.
        This helps users understand why they can't see their account balances.

        Returns:
            dict with structure: {
                'platform': {broker_type: {'balance': float, 'connected': bool}, ...},
                'users': {
                    user_id: {
                        broker_type: {
                            'balance': float,
                            'connected': bool,
                            'credentials_configured': bool
                        },
                        ...
                    },
                    ...
                }
            }
        """
        result = {
            'platform': {},
            'users': {}
        }

        # Platform balances with status
        for broker_type, broker in self._platform_brokers.items():
            result['platform'][broker_type.value] = {
                'balance': broker.get_account_balance() if broker.connected else 0.0,
                'connected': broker.connected
            }

        # User balances with status - include ALL users
        # First from metadata
        for user_id in self._user_metadata.keys():
            if user_id not in result['users']:
                result['users'][user_id] = {}

        # Then from connected users
        for user_id, user_brokers in self.user_brokers.items():
            if user_id not in result['users']:
                result['users'][user_id] = {}
            for broker_type, broker in user_brokers.items():
                result['users'][user_id][broker_type.value] = {
                    'balance': broker.get_account_balance() if broker.connected else 0.0,
                    'connected': broker.connected,
                    'credentials_configured': self._get_broker_credentials_status(broker)
                }

        # Finally from _all_user_brokers (disconnected users)
        for (user_id, broker_type), broker in self._all_user_brokers.items():
            if user_id not in result['users']:
                result['users'][user_id] = {}

            if broker_type.value not in result['users'][user_id]:
                result['users'][user_id][broker_type.value] = {
                    'balance': 0.0,  # Disconnected, so balance is 0 or unknown
                    'connected': broker.connected,
                    'credentials_configured': self._get_broker_credentials_status(broker)
                }

        return result

    def get_status_report(self) -> str:
        """
        Generate a status report showing all accounts and balances.

        Returns:
            Formatted status report string
        """
        lines = []
        lines.append("=" * 70)
        lines.append("NIJA MULTI-ACCOUNT STATUS REPORT")
        lines.append("=" * 70)

        # Platform account
        lines.append("\n🔷 PLATFORM ACCOUNT (Nija System)")
        lines.append("-" * 70)
        if self._platform_brokers:
            platform_total = 0.0
            for broker_type, broker in self._platform_brokers.items():
                if broker.connected:
                    balance = broker.get_account_balance()
                    platform_total += balance
                    lines.append(f"   {broker_type.value.upper()}: ${balance:,.2f}")
                else:
                    lines.append(f"   {broker_type.value.upper()}: Not connected")
            lines.append(f"   TOTAL PLATFORM: ${platform_total:,.2f}")
        else:
            lines.append("   No master brokers configured")

        # User accounts
        lines.append("\n🔷 USER ACCOUNTS")
        lines.append("-" * 70)
        if self.user_brokers:
            for user_id, user_brokers in self.user_brokers.items():
                lines.append(f"\n   User: {user_id}")
                user_total = 0.0
                for broker_type, broker in user_brokers.items():
                    if broker.connected:
                        balance = broker.get_account_balance()
                        user_total += balance
                        lines.append(f"      {broker_type.value.upper()}: ${balance:,.2f}")
                    else:
                        lines.append(f"      {broker_type.value.upper()}: Not connected")
                lines.append(f"      TOTAL USER: ${user_total:,.2f}")
        else:
            lines.append("   No user brokers configured")

        lines.append("\n" + "=" * 70)

        return "\n".join(lines)

    def log_all_balances(self):
        """
        Log all account balances to the console.

        This is a convenience method for quick balance visibility.
        Calls get_status_report() and logs the output.
        """
        report = self.get_status_report()
        logger.info("\n" + report)

    def get_user_balance_summary(self) -> Dict:
        """
        Get a summary of all user balances for quick review.

        Returns:
            dict with structure: {
                'user_count': int,
                'total_capital': float,
                'average_balance': float,
                'users': [
                    {
                        'user_id': str,
                        'total': float,
                        'brokers': {broker: balance, ...}
                    },
                    ...
                ]
            }
        """
        balances = self.get_all_balances()
        user_balances = balances.get('users', {})

        users_list = []
        total_capital = 0.0

        for user_id, brokers in user_balances.items():
            user_total = sum(brokers.values())
            users_list.append({
                'user_id': user_id,
                'total': user_total,
                'brokers': brokers
            })
            total_capital += user_total

        # Sort by total balance (descending)
        users_list.sort(key=lambda x: x['total'], reverse=True)

        return {
            'user_count': len(users_list),
            'total_capital': total_capital,
            'average_balance': total_capital / len(users_list) if users_list else 0,
            'users': users_list
        }

    def connect_users_from_config(self) -> Dict[str, List[str]]:
        """
        Connect all users from configuration files.

        Loads user configurations from config/users/*.json files and connects
        each enabled user to their specified brokerage.

        Returns:
            dict: Summary of connected users by brokerage
                  Format: {brokerage: [user_ids]}
        """
        # HARD BLOCK — Platform must connect FIRST (for CRITICAL brokers only).
        # Two cases to guard:
        #   A) Platform broker registered (normal path): wait until CONNECTED.
        #   B) Platform connection ATTEMPTED but failed before registration:
        #      mark_platform_failed() populates _platform_failed_types so we
        #      can catch this even though the broker is not in _platform_brokers.
        #
        # Broker roles (from broker_registry.get_criticality()):
        #   CRITICAL (e.g. Kraken)  — nonce-sensitive; failure BLOCKS all user
        #                             connections until the platform reconnects.
        #   PRIMARY  (e.g. Coinbase) — first-choice execution venue; failure is
        #                             tolerated — system continues without it.
        #   OPTIONAL / DEFERRED     — supplementary; skipped on failure entirely.
        #
        # Only CRITICAL brokers trigger a hard stop.  Every other tier is logged
        # and skipped so that a Coinbase outage never blocks Kraken-connected users.

        def _is_critical_broker(bt: BrokerType) -> bool:
            """Return True only when this broker has CRITICAL criticality."""
            if broker_registry is not None and BrokerCriticality is not None:
                return broker_registry.get_criticality(bt.value) == BrokerCriticality.CRITICAL
            # Safe fallback when registry is unavailable: only Kraken is critical.
            return bt == BrokerType.KRAKEN

        for broker_type in list(self._platform_brokers.keys()):
            if not _is_critical_broker(broker_type):
                logger.info(
                    "ℹ️  Platform %s is non-CRITICAL — skipping platform-first hard-block check.",
                    broker_type.value.upper(),
                )
                continue
            if not self.wait_for_platform_ready(broker_type):
                logger.error(
                    "⛔ PLATFORM-FIRST RULE: platform %s (CRITICAL) not ready — "
                    "skipping ALL user connections to protect nonce integrity.",
                    broker_type.value.upper(),
                )
                return {}

        for broker_type in list(self._platform_failed_types):
            if not _is_critical_broker(broker_type):
                logger.warning(
                    "⚠️ Platform %s (non-CRITICAL) previously FAILED — "
                    "continuing user initialisation without it.",
                    broker_type.value.upper(),
                )
                continue
            logger.error(
                "⛔ PLATFORM-FIRST RULE: platform %s (CRITICAL) connection previously FAILED — "
                "refusing to connect user accounts.  Fix platform credentials/network "
                "and restart the bot.",
                broker_type.value.upper(),
            )
            return {}

        # Import user loader
        try:
            from config.user_loader import get_user_config_loader
        except ImportError:
            try:
                import sys
                import os
                sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                from config.user_loader import get_user_config_loader
            except ImportError:
                logger.error("❌ Failed to import user_loader - cannot load user configurations")
                return {}

        # Load user configurations
        user_loader = get_user_config_loader()
        enabled_users = user_loader.get_all_enabled_users()

        if not enabled_users:
            logger.info("⚪ No enabled users found in configuration files")
            return {}

        logger.info("=" * 70)
        logger.info("👤 CONNECTING USERS FROM CONFIG FILES")
        logger.info("=" * 70)
        logger.info("ℹ️  Users are SECONDARY accounts - Platform accounts have priority")
        logger.info("=" * 70)

        connected_users = {}

        # Track last connection time for each broker type to add delays between sequential connections
        # This prevents nonce conflicts and server-side rate limiting issues, especially for Kraken
        last_connection_time = {}

        for user in enabled_users:
            # Store user config for later access (e.g., checking independent_trading flag)
            self.user_configs[user.user_id] = user

            # Convert broker_type string to BrokerType enum
            try:
                if user.broker_type.upper() == 'KRAKEN':
                    broker_type = BrokerType.KRAKEN
                elif user.broker_type.upper() == 'ALPACA':
                    broker_type = BrokerType.ALPACA
                elif user.broker_type.upper() == 'COINBASE':
                    broker_type = BrokerType.COINBASE
                elif user.broker_type.upper() == 'OKX':
                    broker_type = BrokerType.OKX
                else:
                    logger.warning(f"⚠️  Unsupported broker type '{user.broker_type}' for {user.name}")
                    continue
            except Exception as e:
                logger.warning(f"⚠️  Error mapping broker type for {user.name}: {e}")
                continue

            # LEGACY CHECK: Skip if copy trading is active (deprecated feature)
            # NOTE: Copy trading is deprecated. This check is kept for backward compatibility.
            # In normal operation (independent trading), this will always be False and users connect normally.
            if broker_type == BrokerType.KRAKEN and self.kraken_copy_trading_active:
                logger.info("=" * 70)
                logger.info(f"✅ KRAKEN USER ALREADY ACTIVE VIA COPY TRADING: {user.name} ({user.user_id})")
                logger.info("=" * 70)
                continue
            # Check if Platform account is connected for this broker type
            # IMPORTANT: Platform accounts should connect first and be primary
            # User accounts are SECONDARY and should not connect if Platform isn't connected
            logger.debug(f"🔍 Checking platform connection for {broker_type.value}")
            logger.debug(f"   platform_brokers dict keys: {list(self.platform_brokers.keys())}")
            logger.debug(f"   {broker_type} in platform_brokers: {broker_type in self.platform_brokers}")
            platform_connected = self.is_platform_connected(broker_type)
            logger.debug(f"   is_platform_connected result: {platform_connected}")

            # --- Step 3: Verify platform presence before connecting the user ---
            # Use the PAL singleton to confirm that NIJA platform credentials exist
            # for this exchange.  If they are absent we fall back to USER-ONLY mode
            # so the user account can still trade independently.
            # Default False; set to True only when falling back to USER-ONLY mode
            # (no platform credentials configured for this exchange).
            allow_user_trading = False
            if not platform_connected:
                # Use the state-machine-based hard wait instead of the legacy
                # retry loop.  This returns True only when the state reaches
                # CONNECTED (not just "not failed yet").
                platform_connected = self.wait_for_platform_ready(broker_type)
                if not platform_connected:
                    _pal = get_platform_account_layer() if get_platform_account_layer is not None else None
                    _has_platform = _pal.has_platform_account(broker_type.value) if _pal is not None else False
                    if not _has_platform:
                        logger.warning("⚠️ Falling back to USER-ONLY mode")
                        allow_user_trading = True

            # Add delay between sequential connections to the same broker type
            # This helps prevent nonce conflicts and API rate limiting, especially for Kraken
            if broker_type in last_connection_time:
                time_since_last = time.time() - last_connection_time[broker_type]
                if time_since_last < MIN_CONNECTION_DELAY:
                    delay = MIN_CONNECTION_DELAY - time_since_last
                    logger.info(f"⏱️  Waiting {delay:.1f}s before connecting next user to {broker_type.value.title()}...")
                    time.sleep(delay)

            logger.info(f"📊 Connecting {user.name} ({user.user_id}) to {broker_type.value.title()}...")
            if platform_connected:
                logger.info(f"   ✅ Platform {broker_type.value.upper()} is connected (correct priority)")
            elif allow_user_trading:
                logger.info(f"   ℹ️  No platform account for {broker_type.value.upper()} — running in USER-ONLY mode")
            else:
                logger.info(f"   ℹ️  Platform {broker_type.value.upper()} is present but not yet connected")
            # Flush to ensure this message appears before connection attempt logs
            # CRITICAL FIX: Must flush the root 'nija' logger's handlers, not the child logger's
            # Child loggers (like 'nija.multi_account', 'nija.broker') propagate to parent but
            # don't have their own handlers. Flushing logger.handlers does nothing since it's empty.
            # We need to flush the parent 'nija' logger's handlers to ensure all logs are written.
            for handler in _root_logger.handlers:
                handler.flush()

            # SMART CACHE MANAGEMENT: Clear failed connection cache to allow retry
            # This allows automatic reconnection when credentials are added/fixed without requiring bot restart
            connection_key = (user.user_id, broker_type)
            if connection_key in self._failed_user_connections:
                # Always retry on each connect_users_from_config() call - if credentials were fixed,
                # connection will succeed; if still broken, it will fail again and be re-cached.
                # This gives users automatic retry on every bot restart without manual intervention.
                reason = self._failed_user_connections[connection_key]
                logger.info(f"   🔄 Clearing previous connection failure cache for {user.name} ({reason})")
                logger.info(f"   Will retry connection - credentials may have been added/fixed")
                del self._failed_user_connections[connection_key]

            try:
                broker = self.add_user_broker(user.user_id, broker_type)

                # Store/update user metadata for audit and reporting
                # Always update to ensure we have the latest user state
                if user.user_id not in self._user_metadata:
                    self._user_metadata[user.user_id] = {'brokers': {}}

                # Update user properties (may change between calls)
                self._user_metadata[user.user_id]['name'] = user.name
                self._user_metadata[user.user_id]['enabled'] = user.enabled

                if broker and broker.connected:
                    # Successfully connected
                    # Track connected user and broker connection status
                    if broker_type.value not in connected_users:
                        connected_users[broker_type.value] = []
                    connected_users[broker_type.value].append(user.user_id)

                    # Update metadata with connection status
                    self._user_metadata[user.user_id]['brokers'][broker_type] = True

                    logger.info(f"   ✅ {user.name} connected to {broker_type.value.title()}")

                    # Try to get and log balance
                    try:
                        balance = broker.get_account_balance()
                        logger.info(f"   💰 {user.name} balance: ${balance:,.2f}")
                    except Exception as bal_err:
                        logger.warning(f"   ⚠️  Could not get balance for {user.name}: {bal_err}")
                elif broker and not broker.credentials_configured:
                    # Credentials not configured - this is expected, not an error
                    # The broker's connect() method already logged informational messages
                    # Track this so we can show proper status later
                    self._users_without_credentials[connection_key] = True
                    # Update metadata with disconnected status
                    self._user_metadata[user.user_id]['brokers'][broker_type] = False
                    logger.info(f"   ⚪ {user.name} - credentials not configured (optional)")
                elif broker:
                    # Actual connection failure with configured credentials
                    logger.warning(f"   ⚠️  Failed to connect {user.name} to {broker_type.value.title()}")
                    # Track the failed connection to avoid repeated attempts
                    self._failed_user_connections[connection_key] = "connection_failed"
                    # Update metadata with disconnected status
                    self._user_metadata[user.user_id]['brokers'][broker_type] = False
                else:
                    # broker is None - unsupported broker type or exception
                    logger.warning(f"   ⚠️  Could not create broker for {user.name}")
                    self._failed_user_connections[connection_key] = "broker_creation_failed"
                    # Update metadata with disconnected status
                    self._user_metadata[user.user_id]['brokers'][broker_type] = False

            except Exception as e:
                # Initialize metadata if not already present (needed for exception case)
                if user.user_id not in self._user_metadata:
                    self._user_metadata[user.user_id] = {
                        'name': user.name,
                        'enabled': user.enabled,
                        'brokers': {}
                    }
                # Update metadata with disconnected status
                self._user_metadata[user.user_id]['brokers'][broker_type] = False

                logger.warning(f"   ⚠️  Error connecting {user.name}: {e}")
                # Track the failed connection to avoid repeated attempts
                # Truncate error message to prevent excessive memory usage, add ellipsis if truncated
                error_str = str(e)
                if len(error_str) > self.MAX_ERROR_MESSAGE_LENGTH:
                    error_msg = error_str[:self.MAX_ERROR_MESSAGE_LENGTH - 3] + '...'
                else:
                    error_msg = error_str
                self._failed_user_connections[connection_key] = error_msg
                import traceback
                logger.debug(traceback.format_exc())

            # Track connection time for this broker type
            last_connection_time[broker_type] = time.time()

        # Log summary
        logger.info("=" * 70)
        logger.info("📊 ACCOUNT HIERARCHY REPORT")
        logger.info("=" * 70)
        logger.info("🎯 PLATFORM accounts are PRIMARY - User accounts are SECONDARY")
        logger.info("=" * 70)

        # Show Platform broker status
        logger.info("🔷 PLATFORM ACCOUNTS (Primary Trading Accounts):")
        if self._platform_brokers:
            for broker_type, broker in self._platform_brokers.items():
                status = "✅ CONNECTED" if broker.connected else "❌ NOT CONNECTED"
                logger.info(f"   • {broker_type.value.upper()}: {status}")
        else:
            logger.info("   ⚠️  No platform brokers connected")

        logger.info("")
        logger.info("👤 USER ACCOUNTS (Secondary Trading Accounts):")

        if connected_users:
            total_connected = sum(len(users) for users in connected_users.values())
            logger.info(f"   ✅ {total_connected} user(s) connected across {len(connected_users)} brokerage(s)")
            for brokerage, user_ids in connected_users.items():
                logger.info(f"   • {brokerage.upper()}: {len(user_ids)} user(s)")
        else:
            # Check if there are users without credentials vs actual failures
            total_without_creds = len(self._users_without_credentials)
            total_failed = len(self._failed_user_connections)

            if total_without_creds > 0 and total_failed == 0:
                # Only users without credentials - this is informational
                logger.info(f"   ⚪ No users connected ({total_without_creds} user(s) have no credentials configured)")
                logger.info("   User accounts are optional. To enable, configure API credentials in environment variables.")
            elif total_failed > 0:
                # Some actual connection failures
                logger.warning(f"   ⚠️  No users connected ({total_failed} connection failure(s), {total_without_creds} without credentials)")
            else:
                # No users configured at all
                logger.info("   ⚪ No user accounts configured")

        # Log warnings for problematic setups
        logger.info("")

        # Account architecture validation
        # All accounts (Platform + Users) trade independently using same NIJA logic
        # Platform is not a "master" - it's just another independent trading account
        users_without_platform = []
        for brokerage, user_ids in connected_users.items():
            try:
                # Safely convert brokerage string to BrokerType enum
                # connected_users keys are lowercase broker names from broker_type.value
                broker_type = BrokerType[brokerage.upper()]
                platform_connected = self.is_platform_connected(broker_type)
                if not platform_connected and user_ids:
                    users_without_platform.append(brokerage.upper())
            except KeyError:
                # Invalid broker type - this shouldn't happen, but handle gracefully
                logger.warning(f"⚠️  Unknown broker type in connected users: {brokerage}")
                continue

        if users_without_platform:
            # Step 5: Standalone mode is blocked — trading requires a platform account.
            # Users without a matching platform account were skipped during connection above
            # (Step 3 guard).  This section surfaces any that slipped through (e.g. legacy
            # env-var users that bypassed the PAL check) with a clear warning.
            try:
                logger.warning("=" * 70)
                logger.warning("⛔  STANDALONE MODE BLOCKED — Platform Account Required")
                logger.warning("=" * 70)
                logger.warning(f"   Missing platform account on: {', '.join(users_without_platform)}")
                logger.warning("   User accounts require a NIJA Platform account to trade.")
                logger.warning("   Configure the platform credentials and restart:")
                for ex in users_without_platform:
                    logger.warning(f"     {ex}_PLATFORM_API_KEY / {ex}_PLATFORM_API_SECRET")
                logger.warning("")
                # Flush output to ensure messages are visible
                for handler in _root_logger.handlers:
                    handler.flush()
            except Exception as e:
                logger.error(f"⚠️  Error logging account configuration: {e}")
                logger.debug(traceback.format_exc())
        else:
            # All accounts connected and trading
            logger.info("✅ ACCOUNT STATUS:")
            logger.info("   ✅ Platform and User accounts connected - all trading independently")

        logger.info("=" * 70)
        # Flush final separator
        for handler in _root_logger.handlers:
            handler.flush()

        return connected_users

    def verify_account_hierarchy(self) -> Dict:
        """
        Verify that Platform accounts are PRIMARY and User accounts are SECONDARY.

        After the Kraken Platform account is configured:
        - All users adopt positions from the Platform correctly.
        - "Temporarily acting as primary" warnings are eliminated.
        - Unified reporting and capital protection are fully enabled.
        - Missing entry prices are automatically fetched from trade history
          via the Platform broker's get_real_entry_price() method.

        Returns:
            dict with keys:
              'platform_is_primary'   – True when at least one Platform broker is connected.
              'users_are_secondary'   – True when every connected user broker has a
                                        corresponding Platform broker (no user is acting
                                        as primary).
              'hierarchy_valid'       – True when both conditions above are met.
              'entry_price_fetch_enabled' – True when at least one Platform broker
                                           supports get_real_entry_price() (capital
                                           protection alignment is fully active).
              'hierarchy_issues'      – List of strings describing any violations found.
              'platform_brokers'      – Dict mapping broker name → connection status.
              'user_brokers'          – Dict mapping broker name → number of connected users.
              'standalone_mode_users' – List of user_ids operating in standalone mode
                                        (exits only, no new entries) because their Platform
                                        account is not connected.
        """
        issues: list = []
        standalone_mode_users: list = []

        # ── 1. Platform PRIMARY check ──────────────────────────────────────────
        platform_status: Dict[str, bool] = {}
        for broker_type, broker in self._platform_brokers.items():
            platform_status[broker_type.value.upper()] = broker.connected

        platform_is_primary = any(platform_status.values()) if platform_status else False

        if not platform_is_primary:
            issues.append(
                "No Platform broker is connected. "
                "Configure Platform credentials first so Platform is PRIMARY. "
                "See PLATFORM_ACCOUNT_REQUIRED.md for setup instructions."
            )

        # ── 2. User SECONDARY check ────────────────────────────────────────────
        # A user is "temporarily acting as primary" when their broker type has no
        # corresponding connected Platform broker.
        user_broker_summary: Dict[str, int] = {}
        users_are_secondary = True

        for user_id, brokers in self.user_brokers.items():
            for broker_type, broker in brokers.items():
                if not broker.connected:
                    continue
                name = broker_type.value.upper()
                user_broker_summary[name] = user_broker_summary.get(name, 0) + 1
                platform_broker = self._platform_brokers.get(broker_type)
                if platform_broker is None or not platform_broker.connected:
                    users_are_secondary = False
                    if user_id not in standalone_mode_users:
                        standalone_mode_users.append(user_id)
                    # Build broker-specific credential guidance
                    if name == "KRAKEN":
                        cred_hint = "KRAKEN_PLATFORM_API_KEY / KRAKEN_PLATFORM_API_SECRET"
                    elif name == "ALPACA":
                        cred_hint = "ALPACA_API_KEY / ALPACA_API_SECRET"
                    elif name == "COINBASE":
                        cred_hint = "COINBASE_API_KEY / COINBASE_API_SECRET"
                    elif name == "OKX":
                        cred_hint = "OKX_API_KEY / OKX_API_SECRET / OKX_PASSPHRASE"
                    else:
                        cred_hint = f"{name}_PLATFORM_API_KEY / {name}_PLATFORM_API_SECRET"
                    issues.append(
                        f"User account on {name} is temporarily acting as primary — "
                        f"Platform {name} account is not connected. "
                        f"Configure {cred_hint} "
                        f"to restore correct hierarchy."
                    )

        # ── 3. Entry-price auto-fetch (capital protection alignment) ──────────
        entry_price_fetch_enabled = any(
            hasattr(broker, 'get_real_entry_price')
            for broker in self._platform_brokers.values()
            if broker.connected
        )
        if platform_is_primary and not entry_price_fetch_enabled:
            issues.append(
                "Platform broker is connected but does not expose get_real_entry_price(). "
                "Missing entry prices cannot be auto-fetched from trade history."
            )

        hierarchy_valid = platform_is_primary and users_are_secondary

        # ── 4. Log results ─────────────────────────────────────────────────────
        logger.info("=" * 70)
        logger.info("🔍 ACCOUNT HIERARCHY VERIFICATION")
        logger.info("=" * 70)
        logger.info("🎯 PLATFORM accounts are PRIMARY - User accounts are SECONDARY")
        logger.info("")

        logger.info("🔷 PLATFORM ACCOUNTS (PRIMARY):")
        if platform_status:
            for name, connected in platform_status.items():
                status = "✅ CONNECTED (PRIMARY)" if connected else "❌ NOT CONNECTED"
                logger.info(f"   • {name}: {status}")
        else:
            logger.warning("   ⚠️  No platform brokers registered")

        logger.info("")
        logger.info("👤 USER ACCOUNTS (SECONDARY):")
        if user_broker_summary:
            for name, count in user_broker_summary.items():
                platform_ok = platform_status.get(name, False)
                role = "SECONDARY ✅" if platform_ok else "⛔ NO PLATFORM — trading blocked"
                logger.info(f"   • {name}: {count} user(s) — {role}")
        else:
            logger.info("   ⚪ No connected user accounts")

        logger.info("")
        if entry_price_fetch_enabled:
            logger.info(
                "✅ Entry price auto-fetch ENABLED — missing entry prices will be "
                "retrieved from trade history (capital protection ALIGNED)"
            )
        elif platform_is_primary:
            logger.warning(
                "⚠️  Entry price auto-fetch NOT available on connected Platform broker"
            )
        else:
            logger.info(
                "ℹ️  Entry price auto-fetch requires a connected Platform broker. "
                "Configure Platform account to enable capital protection alignment."
            )

        logger.info("")
        if hierarchy_valid:
            logger.info("✅ HIERARCHY VALID: Platform is PRIMARY, all users are SECONDARY")
        else:
            logger.warning("⛔ HIERARCHY INVALID: No Platform account configured — standalone mode blocked.")
            if standalone_mode_users:
                logger.warning(
                    f"   User(s) without platform coverage: {', '.join(standalone_mode_users)}"
                )
                logger.warning("   New trade entries are BLOCKED until a platform account is configured.")
                logger.warning("   Set {EXCHANGE}_PLATFORM_API_KEY / SECRET and restart.")

        logger.info("=" * 70)

        return {
            'platform_is_primary': platform_is_primary,
            'users_are_secondary': users_are_secondary,
            'hierarchy_valid': hierarchy_valid,
            'entry_price_fetch_enabled': entry_price_fetch_enabled,
            'hierarchy_issues': issues,
            'platform_brokers': platform_status,
            'user_brokers': user_broker_summary,
            'standalone_mode_users': standalone_mode_users,
        }

    def audit_user_accounts(self):
        """
        Audit and log all user accounts with broker status.

        This function displays:
        - PLATFORM-linked users
        - Any account with status=="ACTIVE" (enabled=True)
        - Shows connection status for each broker

        Output format is clean and investor-ready.
        Called at startup to ensure all active users are visible.
        """
        logger.info("=" * 70)
        logger.info("👥 USER ACCOUNT BALANCES AUDIT")
        logger.info("=" * 70)

        if not self._user_metadata:
            logger.info("   ⚪ No user accounts configured")
            logger.info("=" * 70)
            return

        # Collect all active users (enabled=True) with their broker statuses
        active_connected_count = 0

        for user_id, user_meta in self._user_metadata.items():
            user_name = user_meta.get('name', user_id)
            is_enabled = user_meta.get('enabled', True)
            brokers_status = user_meta.get('brokers', {})

            # Skip disabled users
            if not is_enabled:
                continue

            # Get actual broker connections from user_brokers
            user_broker_dict = self.user_brokers.get(user_id, {})

            # Track if this user has at least one active connection
            user_has_connection = False

            # Display all configured brokers for this user
            for broker_type, is_connected in brokers_status.items():
                broker_name = broker_type.value.upper()

                # Verify connection status from actual broker object
                if broker_type in user_broker_dict:
                    broker = user_broker_dict[broker_type]
                    if broker.connected:
                        logger.info(f"✅ {user_name} ({broker_name}): CONNECTED")
                        user_has_connection = True
                    else:
                        logger.info(f"⚪ {user_name} ({broker_name}): Not configured")
                else:
                    logger.info(f"⚪ {user_name} ({broker_name}): Not configured")

            # Count users with at least one connection
            if user_has_connection:
                active_connected_count += 1

        # Display summary
        if active_connected_count == 0:
            logger.info("")
            logger.info("   ⚪ No ACTIVE user accounts with broker connections")
        else:
            logger.info("")
            logger.info(f"✅ {active_connected_count} active user account(s) connected")

        logger.info("=" * 70)

    def initialize_platform_brokers(self) -> Dict[str, dict]:
        """Create, connect, and register all platform brokers.

        This is the **sole** entry-point for platform broker initialisation.
        No other layer (e.g. TradingStrategy) should instantiate platform
        broker objects directly.  Callers receive back a result dict so they
        can do strategy-specific post-processing (order cleanup, legacy compat
        wiring, etc.) without touching the broker lifecycle.

        Guard (idempotent)
        ------------------
        For every broker type the global ``GLOBAL_PLATFORM_BROKERS`` registry
        is checked under ``_PLATFORM_BROKER_REGISTRY_LOCK`` before creating a
        new object — if the flag is already ``True`` the existing instance is
        reused (no second instantiation).

        The ``_PLATFORM_BROKER_CONNECTED`` flag is checked before calling
        ``broker.connect()`` — if it is already ``True`` the connection step
        is skipped entirely.  This makes the method safe to call from multiple
        entry points (trading_strategy, self_healing_startup, tests) without
        duplicate connects.

        Return value
        ------------
        A mapping keyed by broker name (lowercase, matching BrokerType.value)::

            {
                "kraken":   {"broker": <KrakenBroker>,   "connected": True},
                "coinbase": {"broker": <CoinbaseBroker>, "connected": False},
                ...
            }

        A broker that was skipped (NIJA_DISABLE_COINBASE=true) or that failed
        to import its SDK will not appear in the dict.  The ``connected`` flag
        mirrors the result of ``broker.connect()``.
        """
        # Late import to avoid circular dependency (broker_manager → multi_account_broker_manager)
        try:
            from bot.broker_manager import BinanceBroker
        except ImportError:
            try:
                from broker_manager import BinanceBroker
            except ImportError:
                BinanceBroker = None  # type: ignore[assignment,misc]

        results: Dict[str, dict] = {}

        # ── Helpers ──────────────────────────────────────────────────────────

        def _guarded_create(key: str, factory: Callable[[], BaseBroker]) -> Optional[BaseBroker]:
            """Return existing instance if guard is set, else create + record.

            If the guard is set but the instance was never stored (e.g. a
            previous creation attempt raised an exception), the guard is
            cleared and creation is retried.

            Exceptions raised by *factory* propagate to the caller so the
            per-broker try/except in ``initialize_platform_brokers`` can
            record the failure without crashing the whole startup.
            """
            with _PLATFORM_BROKER_REGISTRY_LOCK:
                if GLOBAL_PLATFORM_BROKERS.get(key):
                    existing = _PLATFORM_BROKER_INSTANCES.get(key)
                    if existing is not None:
                        logger.info(
                            "🔒 Platform %s already initialised — reusing existing instance",
                            key.upper(),
                        )
                        return existing
                    # Guard set but instance missing — clear and retry.
                    logger.warning(
                        "⚠️  Platform %s guard was set but instance is missing — resetting and retrying",
                        key.upper(),
                    )
                    GLOBAL_PLATFORM_BROKERS[key] = False
                broker = factory()
                GLOBAL_PLATFORM_BROKERS[key] = True
                _PLATFORM_BROKER_INSTANCES[key] = broker
                return broker

        def _connect_and_register(broker_type: BrokerType, broker: BaseBroker, key: str) -> bool:
            """Run begin → connect → register/fail and return True if connected.

            If ``_PLATFORM_BROKER_CONNECTED[key]`` is already ``True`` the
            ``connect()`` call is skipped and the existing connected state is
            returned immediately (idempotency guard — Step 2).
            """
            # Idempotency: skip connect() if the lifecycle already ran.
            with _PLATFORM_BROKER_REGISTRY_LOCK:
                already_connected = _PLATFORM_BROKER_CONNECTED.get(key, False)
            if already_connected:
                logger.info(
                    "🔒 Platform %s connect() already completed — skipping duplicate",
                    key.upper(),
                )
                return getattr(broker, "connected", True)

            self.begin_platform_connection(broker_type)
            try:
                connected = broker.connect()
            except Exception as exc:
                logger.error("❌ Platform %s connect() raised: %s", key.upper(), exc)
                connected = False
            if connected:
                self.register_platform_broker_instance(
                    broker_type,
                    broker,
                    mark_connected_state=False,
                )
                # Event-driven capital refresh: any successful platform connect
                # immediately revalidates unified capital readiness.
                _cap = self.resolve_startup_capital_invariant(trigger=f"platform_connect:{key}")
                if _cap.get("ready", 0.0) > 0.0:
                    with _PLATFORM_BROKER_REGISTRY_LOCK:
                        _PLATFORM_BROKER_CONNECTED[key] = True
                    self._mark_platform_connected(broker_type)
                    logger.info(
                        "   ✅ Platform %s connected and capital-ready (total=$%.2f)",
                        key.upper(), float(_cap.get("total_capital", 0.0)),
                    )
                else:
                    with _PLATFORM_BROKER_REGISTRY_LOCK:
                        _PLATFORM_BROKER_CONNECTED[key] = False
                        setattr(broker, "connected", False)
                    self.mark_platform_failed(broker_type)
                    logger.error(
                        "   ⛔ Platform %s connected but capital not ready "
                        "(valid_brokers=%d total=$%.2f) — gating trading",
                        key.upper(),
                        int(_cap.get("valid_brokers", 0.0)),
                        float(_cap.get("total_capital", 0.0)),
                    )
            else:
                self.mark_platform_failed(broker_type)
                # Still register so the background reconnect loop can retry.
                self.register_platform_broker_instance(
                    broker_type,
                    broker,
                    mark_connected_state=False,
                )
                logger.warning(
                    "   ⚠️  Platform %s connection failed — registered for background retry",
                    key.upper(),
                )
            self._start_capital_watchdog()
            return connected and (_cap.get("ready", 0.0) > 0.0)

        # ── Kraken (PRIMARY) ─────────────────────────────────────────────────
        logger.info("📊 Attempting to connect Kraken Pro (PLATFORM - PRIMARY)…")
        try:
            broker = _guarded_create(
                "kraken",
                lambda: KrakenBroker(account_type=AccountType.PLATFORM),
            )
            connected = _connect_and_register(BrokerType.KRAKEN, broker, "kraken")
            results["kraken"] = {"broker": broker, "connected": connected}
        except Exception as exc:
            logger.error("❌ Kraken PLATFORM init error: %s", exc)
            results["kraken"] = {"broker": None, "connected": False, "error": str(exc)}

        time.sleep(2.0)  # Separate Kraken nonce window from next broker

        # ── Coinbase ─────────────────────────────────────────────────────────
        if os.environ.get("NIJA_DISABLE_COINBASE", "false").strip().lower() in ("1", "true", "yes"):
            logger.info("⏭️  Coinbase PLATFORM skipped (NIJA_DISABLE_COINBASE=true)")
        else:
            logger.info("📊 Attempting to connect Coinbase Advanced Trade (PLATFORM)…")
            try:
                broker = _guarded_create("coinbase", CoinbaseBroker)
                connected = _connect_and_register(BrokerType.COINBASE, broker, "coinbase")
                results["coinbase"] = {"broker": broker, "connected": connected}
            except Exception as exc:
                logger.warning("⚠️  Coinbase PLATFORM error: %s", exc)
                results["coinbase"] = {"broker": None, "connected": False, "error": str(exc)}

        # ── OKX ──────────────────────────────────────────────────────────────
        if os.environ.get("NIJA_DISABLE_OKX", "false").strip().lower() in ("1", "true", "yes"):
            logger.info("⏭️  OKX PLATFORM skipped (NIJA_DISABLE_OKX=true)")
        else:
            logger.info("📊 Attempting to connect OKX (PLATFORM — NON-CRITICAL)…")
            try:
                broker = _guarded_create("okx", OKXBroker)
                connected = _connect_and_register(BrokerType.OKX, broker, "okx")
                results["okx"] = {"broker": broker, "connected": connected}
            except Exception as exc:
                logger.warning("⚠️  OKX PLATFORM error: %s", exc)
                results["okx"] = {"broker": None, "connected": False, "error": str(exc)}

        time.sleep(0.5)

        # ── Binance ───────────────────────────────────────────────────────────
        if BinanceBroker is not None:
            logger.info("📊 Attempting to connect Binance (PLATFORM)…")
            try:
                broker = _guarded_create("binance", BinanceBroker)
                connected = _connect_and_register(BrokerType.BINANCE, broker, "binance")
                results["binance"] = {"broker": broker, "connected": connected}
            except Exception as exc:
                logger.warning("⚠️  Binance PLATFORM error: %s", exc)
                results["binance"] = {"broker": None, "connected": False, "error": str(exc)}

        time.sleep(0.5)

        # ── Alpaca ────────────────────────────────────────────────────────────
        logger.info("📊 Attempting to connect Alpaca (PLATFORM - Paper Trading)…")
        try:
            broker = _guarded_create("alpaca", AlpacaBroker)
            connected = _connect_and_register(BrokerType.ALPACA, broker, "alpaca")
            results["alpaca"] = {"broker": broker, "connected": connected}
        except Exception as exc:
            logger.warning("⚠️  Alpaca PLATFORM error: %s", exc)
            results["alpaca"] = {"broker": None, "connected": False, "error": str(exc)}

        # Startup ordering invariant:
        # 1) brokers connect, 2) balances fetched, 3) CapitalAuthority built,
        # 4) readiness marked, 5) trading engines may proceed.
        _startup_cap = self.resolve_startup_capital_invariant(
            trigger="initialize_platform_brokers"
        )
        if bool(_startup_cap.get("ready", 0.0)):
            logger.info(
                "✅ CapitalAuthority READY at startup (brokers=%d total=$%.2f)",
                int(_startup_cap.get("valid_brokers", 0.0)),
                float(_startup_cap.get("total_capital", 0.0)),
            )
        else:
            logger.error(
                "⛔ CapitalAuthority NOT READY at startup (brokers=%d total=$%.2f) "
                "— trading must remain gated until watchdog recovery",
                int(_startup_cap.get("valid_brokers", 0.0)),
                float(_startup_cap.get("total_capital", 0.0)),
            )
            self._trading_halted_due_to_capital = True
        self._start_capital_watchdog()

        return results


# Global instance
multi_account_broker_manager = MultiAccountBrokerManager()
