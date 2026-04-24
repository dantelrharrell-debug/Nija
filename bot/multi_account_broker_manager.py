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

import importlib
import logging
import os
import queue
import sys
import threading
import time
from datetime import datetime, timezone
from types import MappingProxyType
import traceback
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
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
        MIN_CASH_TO_BUY,
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
        MIN_CASH_TO_BUY,
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
    from bot.capital_authority import get_capital_authority, STARTUP_LOCK
except ImportError:
    try:
        from capital_authority import get_capital_authority, STARTUP_LOCK  # type: ignore[assignment]
    except ImportError:
        get_capital_authority = None  # type: ignore[assignment]
        STARTUP_LOCK = None  # type: ignore[assignment]

# Import deterministic capital-flow infrastructure (coordinator + FSMs)
try:
    from bot.capital_flow_state_machine import (
        BrokerPayloadFSM,
        BrokerPayloadState,
        CapitalBootstrapState,
        CapitalBootstrapStateMachine,
        CapitalEvent,
        CapitalEventBus,
        CapitalEventType,
        CapitalRefreshCoordinator,
        CapitalRuntimeState,
        CapitalRuntimeStateMachine,
        get_capital_bootstrap_fsm,
        get_capital_event_bus,
        get_capital_runtime_fsm,
    )
    _CAPITAL_FSM_AVAILABLE = True
except ImportError:
    try:
        from capital_flow_state_machine import (  # type: ignore[no-redef]
            BrokerPayloadFSM,
            BrokerPayloadState,
            CapitalBootstrapState,
            CapitalBootstrapStateMachine,
            CapitalEvent,
            CapitalEventBus,
            CapitalEventType,
            CapitalRefreshCoordinator,
            CapitalRuntimeState,
            CapitalRuntimeStateMachine,
            get_capital_bootstrap_fsm,
            get_capital_event_bus,
            get_capital_runtime_fsm,
        )
        _CAPITAL_FSM_AVAILABLE = True
    except ImportError:
        BrokerPayloadFSM = None   # type: ignore[assignment,misc]
        BrokerPayloadState = None  # type: ignore[assignment]
        CapitalRuntimeState = None  # type: ignore[assignment]
        _CAPITAL_FSM_AVAILABLE = False

logger = logging.getLogger('nija.multi_account')

ACCOUNT_USABLE_BALANCE_MIN = float(os.getenv("NIJA_ACCOUNT_USABLE_BALANCE_MIN", "50"))
ACCOUNT_USABLE_BALANCE_RECOMMENDED = float(
    os.getenv("NIJA_ACCOUNT_USABLE_BALANCE_RECOMMENDED", "100")
)

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


def is_broker_fully_ready(broker: Any) -> bool:
    """Return ``True`` only when *broker* is connected **and** has a hydrated balance payload.

    A broker is considered fully ready when both of the following hold:

    * ``broker.connected`` is ``True`` — the transport-layer session is live.
    * A balance payload is available — at least one of the following is true:

      - ``broker.has_balance_payload_for_capital()`` returns ``True``
      - ``broker.has_balance_payload()`` returns ``True``
      - ``broker._last_known_balance`` is not ``None``

    Uses :func:`getattr` with safe defaults so the function is safe to call on
    any object, including stubs and partially-initialised broker adapters.

    Note: the ``payload_hydrated`` attribute is **not** a standard attribute on
    broker objects in this codebase.  Payload readiness must be detected via the
    methods and attributes listed above.
    """
    if not getattr(broker, "connected", False):
        return False
    has_payload = (
        (callable(getattr(broker, "has_balance_payload_for_capital", None))
         and broker.has_balance_payload_for_capital())
        or (callable(getattr(broker, "has_balance_payload", None))
            and broker.has_balance_payload())
        or getattr(broker, "_last_known_balance", None) is not None
    )
    return has_payload


class MultiAccountBrokerManager:
    """
    Manages brokers for multiple accounts (master + users).

    Each account can have connections to multiple exchanges.
    Accounts are completely isolated from each other.
    """

    # Maximum length for error messages stored in failed connection tracking
    # Prevents excessive memory usage from very long error strings
    MAX_ERROR_MESSAGE_LENGTH = 50
    MIN_STARTUP_CAPITAL_TIMEOUT_S = 1.0
    MIN_STARTUP_CAPITAL_POLL_S = 0.1
    MIN_STARTUP_CAPITAL_SLEEP_S = 0.05
    BOOTSTRAP_REFRESH_TRIGGER_PREFIXES = ("platform_connect:", "initialize_platform_brokers")
    WATCHDOG_REFRESH_TRIGGER = "watchdog"
    # Minimum seconds between successive refresh_capital_authority() calls.
    # Rapid back-to-back callers (startup loop, watchdog, connect hooks) are
    # coalesced into a single coordinator run; the cached ready-state is
    # returned immediately for any call that arrives within this window.
    REFRESH_MIN_INTERVAL_S: float = 0.5
    BOOTSTRAP_CONNECTED_ELIGIBLE_STATES = (
        CapitalBootstrapState.WAIT_PLATFORM,
        CapitalBootstrapState.REFRESH_REQUESTED,
        CapitalBootstrapState.REFRESH_IN_FLIGHT,
        CapitalBootstrapState.SNAPSHOT_EVALUATING,
        CapitalBootstrapState.DEGRADED,
        CapitalBootstrapState.FAILED,
    )

    BOOTSTRAP_TRIGGERS = {
        "platform_connect",
        "initialize_platform_brokers",
        "capital_allocation_brain",
        # FIX 3: watchdog fires before bootstrap is READY; include it so the
        # watchdog path uses BrokerPayloadFSM probe logic instead of the strict
        # is_ready_for_capital() gate that blocks startup.
        "watchdog",
        # FIX: Kraken's own connect() calls resolve_startup_capital_invariant()
        # with this trigger before _KRAKEN_STARTUP_FSM.mark_connected() has fired.
        # Without this entry the trigger falls through to the non-bootstrap path,
        # which gates on is_platform_connected(KRAKEN) == True — a condition that
        # can never be satisfied because mark_connected() is only called after
        # capital is READY, creating a permanent deadlock:
        #   Kraken excluded from broker_map → capital never ready → FSM never set
        #   → Kraken excluded from broker_map → …
        # Adding it here routes the trigger through the BrokerPayloadFSM path,
        # which checks _last_known_balance directly and includes Kraken in
        # broker_map as soon as a valid balance payload exists.
        "kraken_platform_connect",
        # FIX (Class 3): explicit bootstrap trigger used by trading_strategy.py and
        # the recovery path after finalize_broker_registration() lifts Gate B.
        # Without this entry the trigger falls through to the non-bootstrap path,
        # which uses strict is_ready_for_capital() gating instead of the relaxed
        # BrokerPayloadFSM / _last_known_balance probe logic required at startup.
        "BOOTSTRAP_START",
        # bootstrap_contract trigger used by enforce_trading_bootstrap_contract().
        # Same rationale: must use FSM probe logic while bootstrap is in progress.
        "bootstrap_contract",
    }
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
        logger.info("[MABM-M1] __init__ entered — starting field initialisation")
        # Platform account brokers - registered once globally and marked immutable
        self._platform_brokers: Dict[BrokerType, BaseBroker] = {}
        self._platform_brokers_locked: bool = False
        self._registry_version: int = 0
        self._primary_registration_count: int = 0
        self._last_update_ts: float = time.time()
        self._event_bus: Optional[Any] = None
        self._broker_registered_callbacks: List[Callable[[BaseBroker], None]] = []
        self._registry_meta_lock: threading.Lock = threading.Lock()

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

        # Track connected accounts that are blocked from new entries because
        # usable capital is too low or tied up in existing positions.
        self._capital_blocked_users: Dict[Tuple[str, BrokerType], str] = {}

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

        logger.info("[MABM-M2] field init complete — importing optional managers (portfolio, isolation, BFM)")
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

        # ── Broker registration hard gate ─────────────────────────────────────
        # Set exactly once via finalize_broker_registration() after all expected
        # platform and user brokers have been registered.  Any capital evaluation
        # (refresh_capital_authority, feed_broker_balance) that fires before this
        # event is set will be skipped/queued so that $0-capital snapshots from
        # partial broker maps cannot drive allocation or halt logic.
        self._broker_registration_complete: threading.Event = threading.Event()

        # ── Global startup lock — one-way latch separate from broker registration ──
        # Set exactly once via finalize_bootstrap_ready() AFTER all of the
        # following are confirmed: brokers registered, broker list reflected in
        # CapitalAuthority, first feed batch processed / confirmed empty-safe,
        # FSM initialized.  Until this flag is True, CapitalAllocationBrain
        # evaluation and CA.refresh() (external callers) are hard-blocked.
        self._startup_lock_released: bool = False

        # ── Forced bootstrap seed — one-shot deadlock breaker ──────────────────
        # Guards the single forced snapshot that seeds CapitalAuthority and sets
        # STARTUP_LOCK when the normal coordinator pipeline cannot run yet (e.g.
        # _broker_registration_complete not yet set).  Protected by
        # _bootstrap_seed_lock for thread-safety; checked with double-checked
        # locking inside refresh_capital_authority().
        self._bootstrap_seed_done: bool = False
        self._bootstrap_seed_lock: threading.Lock = threading.Lock()

        # CapitalAuthority readiness + watchdog state (fail-safe auto-refresh loop)
        self._capital_ready: bool = False
        self._capital_last_valid_brokers: int = 0
        self._capital_last_refresh_ts: float = 0.0
        self._capital_watchdog_started: bool = False
        self._capital_watchdog_stop: threading.Event = threading.Event()
        self._capital_watchdog_thread: Optional[threading.Thread] = None
        self._trading_halted_due_to_capital: bool = False
        self._bootstrap_contract_ok: bool = False
        self._bootstrap_contract_last_error: str = ""
        self._capital_state_lock: threading.Lock = threading.Lock()
        self._capital_bootstrap_barrier_started_at: Optional[float] = None
        self.capital_watchdog_interval_s: float = float(
            os.environ.get("NIJA_CAPITAL_WATCHDOG_INTERVAL_S", "10.0")
        )
        # Max acceptable age for authority snapshot before watchdog forces refresh.
        self.capital_stale_timeout_s: float = float(
            os.environ.get("NIJA_CAPITAL_STALE_TIMEOUT_S", "30.0")
        )
        # Startup capital truth contract tuning:
        # - timeout: maximum wait for non-zero capital readiness during startup
        # - poll: refresh cadence while resolving the startup capital invariant
        self.capital_startup_invariant_timeout_s: float = max(
            self.MIN_STARTUP_CAPITAL_TIMEOUT_S,
            float(os.environ.get("NIJA_CAPITAL_STARTUP_INVARIANT_TIMEOUT_S", "30.0")),
        )
        self.capital_startup_invariant_poll_s: float = max(
            self.MIN_STARTUP_CAPITAL_POLL_S,
            float(os.environ.get("NIJA_CAPITAL_STARTUP_INVARIANT_POLL_S", "1.0")),
        )
        # Max time to allow CapitalBootstrapFSM to remain in WAIT_PLATFORM
        # before we force a recovery transition and trigger a bootstrap refresh.
        self.wait_platform_timeout_s: float = max(
            1.0,
            float(os.environ.get("NIJA_WAIT_PLATFORM_TIMEOUT_S", "45.0")),
        )

        # ── Deterministic capital-flow infrastructure ──────────────────────────
        logger.info("[MABM-M3] optional managers done — constructing CapitalFSM / coordinator")
        # The coordinator is the **single writer** for CapitalAuthority.  All
        # balance fetches, snapshot computations, and authority publishes go
        # through it.  The bootstrap / runtime FSMs track readiness state.
        #
        # Guard: if this block has already run (e.g. due to a re-entrant __init__
        # call or accidental double-construction), skip it entirely to prevent
        # creating a second set of FSM / coordinator objects that would shadow
        # the process-wide singletons.
        self._fsm_initialized: bool = False
        if _CAPITAL_FSM_AVAILABLE:
            self._capital_event_bus: CapitalEventBus = get_capital_event_bus()
            self._capital_bootstrap_fsm: CapitalBootstrapStateMachine = (
                get_capital_bootstrap_fsm()
            )
            self._capital_runtime_fsm: CapitalRuntimeStateMachine = (
                get_capital_runtime_fsm()
            )
            self._capital_coordinator: CapitalRefreshCoordinator = (
                CapitalRefreshCoordinator(
                    event_bus=self._capital_event_bus,
                    bootstrap_fsm=self._capital_bootstrap_fsm,
                    runtime_fsm=self._capital_runtime_fsm,
                )
            )
            # Advance bootstrap FSM to WAIT_PLATFORM — brokers not yet connected.
            self._capital_bootstrap_fsm.transition(
                CapitalBootstrapState.WAIT_PLATFORM, "mabm_init"
            )
            self._capital_bootstrap_fsm.transition(
                CapitalBootstrapState.INIT_COMPLETE, "mabm_preflight_complete"
            )
            # ── Option A: wire capital-ready → system FSM → trading loop ──────
            # Register a one-shot callback on the capital bootstrap FSM.  When
            # the capital pipeline reaches READY (event emitted, bus flushed,
            # CapitalAuthority confirmed), this callback advances the composite
            # BootstrapStateMachine through all prerequisite states to
            # CAPITAL_READY.  That single transition unblocks:
            #   • assert_invariant_i11_strategy_arm()  in _init_advanced_features()
            #   • any other I11-gated code that checks get_bootstrap_fsm().state
            # which is the final gate before the trading loop is allowed to run.
            self._capital_bootstrap_fsm.register_on_ready(
                self._on_capital_bootstrap_ready
            )
            self._fsm_initialized = True
        else:
            self._capital_event_bus = None  # type: ignore[assignment]
            self._capital_bootstrap_fsm = None  # type: ignore[assignment]
            self._capital_runtime_fsm = None  # type: ignore[assignment]
            self._capital_coordinator = None  # type: ignore[assignment]

        # ── Per-broker balance-payload bootstrap FSMs ──────────────────────────
        logger.info("[MABM-M4] CapitalFSM/coordinator wired — initialising per-broker payload FSMs")
        # One BrokerPayloadFSM per registered platform broker.
        # These replace the scattered `has_balance_payload_for_capital()` +
        # `_last_known_balance is not None` eligibility checks with a strict,
        # bounded state machine that guarantees convergence to PAYLOAD_READY
        # or EXHAUSTED for every broker — making infinite eligibility loops
        # structurally impossible.
        self._broker_payload_fsm: Dict[BrokerType, "BrokerPayloadFSM"] = {}

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

    def set_registry_event_bus(self, event_bus: Any) -> None:
        """Attach an optional event bus exposing ``publish(event_name, payload)``."""
        with self._registry_meta_lock:
            self._event_bus = event_bus

    def register_broker_registered_callback(self, callback: Callable[[BaseBroker], None]) -> None:
        """Register a direct callback used when no event bus is attached."""
        with self._registry_meta_lock:
            self._broker_registered_callbacks.append(callback)

    def refresh_registry(self) -> None:
        """Rehydrate registry mirrors from the current platform broker map."""
        with self._registry_meta_lock:
            broker_items = list(self._platform_brokers.items())
        with _PLATFORM_BROKER_REGISTRY_LOCK:
            for broker_type, broker in broker_items:
                _PLATFORM_BROKER_INSTANCES[broker_type.value] = broker
                connected = bool(getattr(broker, "connected", False))
                GLOBAL_PLATFORM_BROKERS[broker_type.value] = connected
                self._platform_connected[broker_type.value] = connected
                if broker_registry is not None:
                    broker_registry[broker_type.value]["platform"] = True
            self._registry_version += 1
            self._last_update_ts = time.time()

    def has_registered_sources(self) -> bool:
        """Return True when at least one primary registration exists and at least one platform source is present."""
        with self._registry_meta_lock:
            source_count = len(self._platform_brokers)
            primary_registrations = self._primary_registration_count
        return source_count > 0 and primary_registrations > 0

    def has_registered_brokers(self) -> bool:
        """Return True when at least one real platform broker has been registered.

        Use this gate before calling :meth:`refresh_capital_authority` during
        bootstrap to prevent the brain from hydrating with a ``__bootstrap_seed__``
        placeholder before any real broker exists.
        """
        with self._registry_meta_lock:
            return len(self._platform_brokers) > 0

    def has_attempted_connections(self) -> bool:
        """Return True when broker registration has been finalized.

        :meth:`finalize_broker_registration` sets this flag once all expected
        brokers have been registered (connected or failed).  Waiting on this
        gate ensures the full broker map is stable before capital evaluation.
        """
        return self._broker_registration_complete.is_set()

    def _force_minimal_capital_snapshot(self) -> Optional[Any]:
        """Build a minimal :class:`~capital_flow_state_machine.CapitalSnapshot` from
        whatever broker balances are already cached in ``_last_known_balance``.

        This is the **seed bootstrap path** — it runs exactly once per process,
        before the normal coordinator pipeline can execute, to break the
        initialization deadlock where ``CapitalAllocationBrain.__init__`` blocks
        on ``CAPITAL_SYSTEM_READY`` while the coordinator is blocked behind
        ``_broker_registration_complete``.

        Returns ``None`` when:
        * ``capital_flow_state_machine`` is not importable.
        * No registered broker has a cached balance yet.
        * The total of all cached balances is zero.

        The returned snapshot has confidence ``MEDIUM`` (freshness treated as
        fresh, pricing assumed 100 % until a real fetch corrects it) so that
        ``publish_snapshot()`` → ``CAPITAL_SYSTEM_READY.set()`` fires
        immediately.  The normal coordinator refresh cycle will overwrite this
        seed snapshot on the very next cycle with accurate data.
        """
        if not _CAPITAL_FSM_AVAILABLE:
            return None

        try:
            from bot.capital_flow_state_machine import (  # type: ignore[import]
                CapitalConfidence,
                CapitalSnapshot,
            )
        except ImportError:
            try:
                from capital_flow_state_machine import (  # type: ignore[import]
                    CapitalConfidence,
                    CapitalSnapshot,
                )
            except ImportError:
                logger.warning("[MABM] _force_minimal_capital_snapshot: cannot import CapitalSnapshot")
                return None

        broker_balances: Dict[str, float] = {}
        with self._registry_meta_lock:
            broker_items = list(self._platform_brokers.items())

        for broker_type, broker in broker_items:
            if not getattr(broker, "connected", False):
                logger.debug(
                    "[MABM] _force_minimal_capital_snapshot: skipping broker=%s "
                    "(connected=%s last_balance=%s)",
                    broker_type.value,
                    getattr(broker, "connected", None),
                    getattr(broker, "_last_known_balance", None),
                )
                continue
            raw = getattr(broker, "_last_known_balance", None)
            if raw is None:
                # _last_known_balance not yet seeded — call get_account_balance()
                # directly.  This is the only acceptable live API call in the
                # seed path; it runs at most once per broker per process lifetime.
                try:
                    raw = broker.get_account_balance()
                except Exception as _exc:
                    logger.debug(
                        "[MABM] _force_minimal_capital_snapshot: broker=%s get_account_balance raised: %s",
                        broker_type.value,
                        _exc,
                    )
                    continue
            if raw is None:
                continue
            try:
                if isinstance(raw, dict):
                    # Use explicit None-checks so zero values (e.g. exactly 0.0
                    # in "trading_balance") are not silently skipped.
                    tb = raw.get("trading_balance")
                    tf = raw.get("total_funds")
                    scalar = float(
                        tb if tb is not None
                        else tf if tf is not None
                        else (raw.get("usd", 0.0) + raw.get("usdc", 0.0))
                    )
                else:
                    scalar = float(raw)
            except (TypeError, ValueError):
                scalar = 0.0
            broker_balances[broker_type.value] = scalar

        if broker_balances:
            logger.warning("[BOOTSTRAP] balances collected: %s", broker_balances)
        else:
            connected_broker_types = [
                bt.value for bt, b in broker_items if getattr(b, "connected", False)
            ]
            logger.warning(
                "[BOOTSTRAP] balances collected: {} — no connected broker returned a balance "
                "(registered=%d, connected=%s). "
                "CapitalAllocationBrain must not be initialized until broker_registry is non-empty.",
                len(broker_items),
                connected_broker_types,
            )

        # ── Bootstrap seed bypass: Kraken connected but balance unavailable ────
        # If Kraken reports connected=True but get_account_balance() failed (e.g.
        # gateway connection established before API balance is reachable), its
        # balance is absent from broker_balances.  Without this bypass the seed
        # snapshot contains no entries and returns None, leaving
        # CapitalAllocationBrain blocked on CAPITAL_SYSTEM_READY indefinitely.
        #
        # Seed Kraken at 0.0 so CA hydrates immediately.  The coordinator's
        # normal refresh cycle will overwrite this with the real balance once
        # Kraken's API becomes reachable.  The watchdog will detect non-zero
        # capital at that point and flip ready=True.
        kraken_broker_obj = self._platform_brokers.get(BrokerType.KRAKEN)
        if (
            kraken_broker_obj is not None
            and getattr(kraken_broker_obj, "connected", False)
            and "kraken" not in broker_balances
        ):
            broker_balances["kraken"] = 0.0
            logger.info(
                "[BOOTSTRAP] Kraken connected but no balance payload yet — "
                "seeding kraken=0.0 to unblock CA hydration"
            )

        if not broker_balances:
            # No connected brokers returned a balance — seed a zero-balance snapshot
            # for any registered platform brokers that ARE connected so CA hydrates
            # immediately (PHASE 1 bootstrap escape hatch) rather than staying
            # INITIALIZING indefinitely.  Non-connected brokers are excluded so that
            # a completely disconnected system still returns pending=1.0 as expected.
            with self._registry_meta_lock:
                for _bt, _broker in self._platform_brokers.items():
                    if getattr(_broker, "connected", False):
                        broker_balances[_bt.value] = 0.0
            if not broker_balances:
                # No connected broker has a balance payload yet — return None so
                # the caller falls through to Guard 0 and returns pending=1.0.
                # The broker registry barrier (Gate A) already guarantees at least
                # one real broker is registered; we wait for it to connect and
                # report a balance before seeding CapitalAuthority.  Seeding
                # disconnected brokers at 0.0 would incorrectly hydrate the Brain
                # and hide the fact that no capital is available.
                logger.debug(
                    "[BOOTSTRAP] _force_minimal_capital_snapshot: no connected broker "
                    "has a balance — returning None (will retry on next cycle)"
                )
                return None
            logger.info(
                "[MABM] _force_minimal_capital_snapshot: seeding zero-balance snapshot "
                "for brokers=%s",
                sorted(broker_balances.keys()),
            )

        real = sum(broker_balances.values())

        try:
            _gca = get_capital_authority() if get_capital_authority else None
            reserve_pct = float(getattr(_gca, "_reserve_pct", 0.02)) if _gca is not None else 0.02
        except Exception:
            reserve_pct = 0.02

        usable = real * (1.0 - reserve_pct)
        risk_capital = max(0.0, usable)
        now = datetime.now(timezone.utc)
        expected = max(1, len(broker_balances))
        confidence = CapitalConfidence.compute(
            kraken_response_age_s=0.0,
            assets_priced_success_pct=1.0,
            api_error_count=0,
        )
        _is_fresh = real > 0.0
        snapshot = CapitalSnapshot(
            real_capital=real,
            usable_capital=usable,
            risk_capital=risk_capital,
            open_exposure_usd=0.0,
            reserve_pct=reserve_pct,
            broker_balances=broker_balances,
            broker_count=len(broker_balances),
            expected_brokers=expected,
            computed_at=now,
            snapshot_age_s=0.0,
            kraken_response_age_s=0.0,
            assets_priced_success_pct=1.0,
            api_error_count=0,
            confidence=confidence,
            is_fresh=_is_fresh,
            is_stale=not _is_fresh,
        )
        logger.info(
            "[MABM] _force_minimal_capital_snapshot: built seed snapshot "
            "real=$%.2f brokers=%s",
            real,
            sorted(broker_balances.keys()),
        )
        return snapshot

    def finalize_broker_registration(self) -> None:
        """Signal that all expected brokers have been registered.

        Call this once — after all platform and user brokers have been added —
        to lift the hard gate that blocks capital evaluation.  Any call to
        :meth:`refresh_capital_authority` or
        :meth:`~bot.capital_authority.CapitalAuthority.feed_broker_balance` that
        arrived before this point will have been skipped or queued.  Once the
        gate is set those queued feeds are flushed automatically via
        :meth:`~bot.capital_authority.CapitalAuthority.finalize_broker_registration`.

        The event is idempotent: calling this method more than once is safe.

        Correct startup order
        ---------------------
        1. Load config
        2. Register ALL brokers (platform + users)
        3. ``finalize_broker_registration()``  ← call this
        4. Start CapitalAllocationBrain
        5. Start CapitalAuthority refresh loops
        6. Enable feed_event processing
        """
        if self._broker_registration_complete.is_set():
            logger.debug("[MABM] finalize_broker_registration: already complete — no-op")
            return
        self._broker_registration_complete.set()
        # Reset the dedup timestamp so that the very next refresh_capital_authority
        # call unconditionally bypasses the REFRESH_MIN_INTERVAL_S guard.
        # Without this reset, any refresh that happened within the last 0.5 s
        # (e.g. an early probe during broker connect) would be returned as the
        # cached result — still showing ready=False — even though the gate just
        # opened and a real evaluation is now valid.  This is the deterministic
        # "immediate post-registration refresh trigger": the gate opens, the
        # timestamp clears, and the next call gets a fresh coordinator run.
        with self._capital_state_lock:
            self._capital_last_refresh_ts = 0.0
        logger.info(
            "✅ [MABM] Broker registration finalized — capital evaluation gates are now open "
            "(registered_brokers=%d)",
            len(self._platform_brokers),
        )
        # Also lift the gate on CapitalAuthority so feed_broker_balance() can
        # flush any pending feeds that arrived before registration was complete.
        try:
            _gca = None
            for _mod in ("bot.capital_authority", "capital_authority"):
                try:
                    _gca = importlib.import_module(_mod).get_capital_authority
                    break
                except (ImportError, AttributeError):
                    continue
            if _gca is not None:
                _ca = _gca()
                if _ca is not None and hasattr(_ca, "finalize_broker_registration"):
                    _ca.finalize_broker_registration()
        except Exception as _exc:
            logger.warning(
                "[MABM] finalize_broker_registration: could not lift CA gate: %s", _exc
            )

        # ── No-Failure Activation Contract ────────────────────────────────────
        # Install all three boot invariants now that brokers are registered
        # and the coordinator is ready:
        #   1. Monotonic snapshot progression (patched in capital_authority.py)
        #   2. Guaranteed CA hydration loop   (retries execute_refresh until hydrated)
        #   3. Forced activation fallback timer (forces all gates open if CA stalls)
        try:
            _install = None
            for _mod_name in ("bot.no_failure_activation_contract", "no_failure_activation_contract"):
                try:
                    _mod_obj = importlib.import_module(_mod_name)
                    _install = getattr(_mod_obj, "install_no_failure_activation_contract", None)
                    if _install is not None:
                        break
                except ImportError:
                    continue
            if _install is not None:
                _broker_map = {
                    str(bt.value) if hasattr(bt, "value") else str(bt): br
                    for bt, br in self._platform_brokers.items()
                    if br is not None
                }
                _install(
                    coordinator=self._capital_coordinator if _CAPITAL_FSM_AVAILABLE else None,
                    broker_map=_broker_map if _broker_map else None,
                )
        except Exception as _exc:
            logger.warning(
                "[MABM] finalize_broker_registration: could not install no_failure_activation_contract: %s",
                _exc,
            )

    @staticmethod
    def _startup_lock_is_set() -> bool:
        """Return True if the module-level STARTUP_LOCK event has been set.

        Using the event directly (rather than the instance flag) means that a
        release performed by CapitalAuthority outside of this class is also seen
        as authoritative — preventing any double-release attempt.
        """
        return STARTUP_LOCK is not None and STARTUP_LOCK.is_set()

    def finalize_bootstrap_ready(self) -> None:
        """Release the global startup lock after full system sync is confirmed.

        This is the **final** step in the bootstrap sequence and MUST be called
        only after ALL of the following are true:

        1. All expected brokers have been registered
           (:meth:`finalize_broker_registration` has been called).
        2. The broker list is reflected in :class:`~bot.capital_authority.CapitalAuthority`
           (pending feeds flushed, ``_broker_registration_complete`` set on CA).
        3. The first feed batch has been processed (or confirmed empty-safe) —
           i.e. :meth:`refresh_capital_authority` has returned ``ready=True``
           at least once.
        4. The capital bootstrap FSM has been initialised.

        Contrast with :meth:`finalize_broker_registration`, which only lifts
        the *broker-registration* gate and is called as soon as all brokers are
        registered.  The startup lock is a **later, stricter** gate that prevents
        :class:`~bot.capital_allocation_brain.CapitalAllocationBrain` and
        external :meth:`~bot.capital_authority.CapitalAuthority.refresh` callers
        from evaluating capital during the broker-stabilization window.

        This method is idempotent: calling it more than once is safe.
        It is called automatically from :meth:`refresh_capital_authority` the
        first time ``ready=True`` is observed after broker registration.
        """
        # Use the module-level STARTUP_LOCK event as the authoritative source of
        # truth so that if CapitalAuthority released the lock directly (e.g. in a
        # test) MABM still treats it as already done.  Sync the local bool so all
        # subsequent checks (including the inline guard in refresh_capital_authority)
        # see the consistent state without re-importing the event each time.
        if self._startup_lock_released or self._startup_lock_is_set():
            if not self._startup_lock_released:
                self._startup_lock_released = True  # sync local flag to event state
            logger.debug("[MABM] finalize_bootstrap_ready: startup lock already released — no-op")
            return
        # Verify prerequisite: broker registration must be complete.
        if not self._broker_registration_complete.is_set():
            logger.warning(
                "[MABM] finalize_bootstrap_ready: broker registration not yet complete — aborting"
            )
            return
        self._startup_lock_released = True
        logger.warning(
            "✅ [MABM] STARTUP LOCK RELEASING — all prerequisites confirmed "
            "(registered_brokers=%d)",
            len(self._platform_brokers),
        )
        # Delegate to CapitalAuthority to set the module-level STARTUP_LOCK event.
        # Use the same deferred-import pattern as finalize_broker_registration() to
        # avoid a circular import: capital_authority.py already imports from this
        # module, so a top-level import here would create a cycle.
        try:
            _gca = None
            for _mod in ("bot.capital_authority", "capital_authority"):
                try:
                    _gca = importlib.import_module(_mod).get_capital_authority
                    break
                except (ImportError, AttributeError):
                    continue
            if _gca is not None:
                _ca = _gca()
                if _ca is not None and hasattr(_ca, "finalize_bootstrap_ready"):
                    _ca.finalize_bootstrap_ready()
        except Exception as _exc:
            logger.warning(
                "[MABM] finalize_bootstrap_ready: could not release CA startup lock: %s", _exc
            )

    def _on_capital_bootstrap_ready(self) -> None:
        """Option A trigger: advance the system BootstrapStateMachine to CAPITAL_READY.

        Called exactly once, synchronously within
        :meth:`~capital_flow_state_machine.CapitalRefreshCoordinator.execute_refresh`,
        after all of the following have completed in the same pipeline tick:

        1. ``CapitalAuthority`` holds a confirmed non-zero snapshot.
        2. All pending ``CapitalEventBus`` events (``CAPITAL_READY``, etc.) have
           been dispatched by ``dispatch_pending()``.
        3. ``CapitalBootstrapStateMachine`` transitions to ``READY``.

        This callback then drives the composite ``BootstrapStateMachine``
        (``bootstrap_state_machine.py``) through all prerequisite happy-path
        states to ``CAPITAL_READY``.  That single advance unblocks:

        * ``assert_invariant_i11_strategy_arm()`` inside
          ``TradingStrategy._init_advanced_features()``
        * any other I11-gated module that checks ``get_bootstrap_fsm().state``

        which is the final guard before the trading loop is permitted to run.
        """
        try:
            try:
                from bot.bootstrap_state_machine import get_bootstrap_fsm
            except ImportError:
                from bootstrap_state_machine import get_bootstrap_fsm  # type: ignore[no-redef]
            fsm = get_bootstrap_fsm()
            advanced = fsm.advance_to_capital_ready("capital_fsm_ready")
            if advanced:
                logger.info(
                    "✅ [MABM] Option A: BootstrapStateMachine → %s "
                    "— trading loop unblocked",
                    fsm.state.value,
                )
            else:
                logger.warning(
                    "⚠️  [MABM] Option A: BootstrapStateMachine could not advance "
                    "to CAPITAL_READY (current=%s) — I11 invariant may still block",
                    fsm.state.value,
                )
        except Exception as _exc:
            logger.warning(
                "[MABM] _on_capital_bootstrap_ready: could not advance system FSM: %s",
                _exc,
            )

    def _record_broker_registration(self, broker_type: BrokerType, broker: BaseBroker) -> None:
        """Propagate broker-registration metadata and notifications."""
        with self._registry_meta_lock:
            self._registry_version += 1
            self._primary_registration_count += 1
            self._last_update_ts = time.time()
            callbacks = list(self._broker_registered_callbacks)
            event_bus = self._event_bus
        logger.info("broker_registered: %s", broker_type.value.title())
        if event_bus is not None and hasattr(event_bus, "publish"):
            try:
                event_bus.publish("broker_registered", broker)
            except Exception as _pub_exc:
                logger.warning("registry event publish failed for %s: %s", broker_type.value, _pub_exc)
        else:
            for _cb in callbacks:
                try:
                    _cb(broker)
                except Exception as _cb_exc:
                    logger.warning("broker_registered callback failed for %s: %s", broker_type.value, _cb_exc)

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
        target_manager = self._get_registration_target_manager(broker_type)
        if target_manager is not self:
            return target_manager.register_platform_broker_instance(
                broker_type=broker_type,
                broker=broker,
                mark_connected_state=mark_connected_state,
            )

        # Enforce immutability and single-registration atomically under the
        # registry lock so two concurrent callers cannot both pass the
        # "already registered?" check and double-write the same broker.
        with self._registry_meta_lock:
            if self._platform_brokers_locked:
                error_msg = f"❌ INVARIANT VIOLATION: Cannot register platform broker {broker_type.value} - platform brokers are locked (immutable)"
                logger.error(error_msg)
                raise RuntimeError(error_msg)
            if broker_type in self._platform_brokers:
                if self._platform_brokers[broker_type] is broker:
                    # Same instance re-registering (e.g. broker.connect() called after
                    # MABM pre-registered it) — idempotent, no error.
                    logger.debug(
                        "%s already registered (same instance) — skipping duplicate (idempotent)",
                        broker_type.value,
                    )
                    return False
                # Different instance for the same broker type — this is an invariant
                # violation: platform brokers must be registered exactly once.
                error_msg = (
                    f"❌ INVARIANT VIOLATION: {broker_type.value} already registered "
                    f"with a different broker instance — platform brokers must be "
                    f"registered exactly once globally"
                )
                logger.error(error_msg)
                raise RuntimeError(error_msg)
            # Atomic write — visible to all threads once the lock is released.
            self._platform_brokers[broker_type] = broker
        self._record_broker_registration(broker_type, broker)
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

        # ── Create BrokerPayloadFSM for this broker ────────────────────────────
        # Each registered platform broker gets its own strict state machine that
        # drives it to PAYLOAD_READY or EXHAUSTED during bootstrap.  This
        # replaces the scattered `has_balance_payload_for_capital()` eligibility
        # checks that could leave a broker permanently stuck with no payload.
        if _CAPITAL_FSM_AVAILABLE and BrokerPayloadFSM is not None:
            if broker_type not in self._broker_payload_fsm:
                self._broker_payload_fsm[broker_type] = BrokerPayloadFSM(
                    broker_id=broker_type.value
                )
                logger.debug(
                    "[BrokerPayloadFSM] created for broker=%s", broker_type.value
                )
            # Fast-path: if connect() already seeded _last_known_balance, advance
            # the FSM to PAYLOAD_READY immediately so no probing round-trip is needed.
            if getattr(broker, "_last_known_balance", None) is not None:
                self._broker_payload_fsm[broker_type].mark_payload_ready()
                logger.debug(
                    "[BrokerPayloadFSM] broker=%s PAYLOAD_READY at registration "
                    "(balance already seeded by connect())",
                    broker_type.value,
                )

        logger.info(f"✅ Platform broker instance registered: {broker_type.value}")
        logger.info(f"   Platform broker registered once, globally")
        return True

    def register_broker(self, broker_type: Union[str, BrokerType], broker: BaseBroker) -> bool:
        """Canonical broker registration entrypoint used by broker connect() paths."""
        if isinstance(broker_type, BrokerType):
            broker_enum = broker_type
        else:
            broker_key = str(broker_type).strip()
            broker_key_lower = broker_key.lower()
            broker_enum = None
            for candidate in BrokerType:
                if candidate.value.lower() == broker_key_lower or candidate.name.lower() == broker_key_lower:
                    broker_enum = candidate
                    break
            if broker_enum is None:
                raise ValueError(f"Unsupported broker type for platform registration: {broker_type}")
        return self.register_platform_broker_instance(
            broker_type=broker_enum,
            broker=broker,
            mark_connected_state=bool(getattr(broker, "connected", False)),
        )

    def _get_registration_target_manager(
        self, broker_type: Optional[Union[str, BrokerType]] = None
    ) -> "MultiAccountBrokerManager":
        """Return canonical registration target manager and log when redirecting."""
        canonical_manager = get_broker_manager()
        if self is canonical_manager:
            return self
        broker_label = (
            broker_type.value if isinstance(broker_type, BrokerType) else str(broker_type or "unknown")
        )
        logger.warning(
            "Redirecting platform broker registration to canonical manager instance "
            "(broker=%s source_manager_id=%s canonical_manager_id=%s)",
            broker_label,
            hex(id(self)),
            hex(id(canonical_manager)),
        )
        return canonical_manager

    def refresh_capital_authority(self, trigger: str = "manual") -> Dict[str, float]:
        """
        Refresh unified CapitalAuthority from all currently connected healthy
        platform brokers via the deterministic five-stage pipeline.

        READY condition:
            - at least one healthy connected platform broker contributes, and
            - aggregated total capital > 0.0

        Return keys (all callers should treat unknown keys as informational):
            ready           1.0 = capital ready, 0.0 = not ready
            total_capital   aggregate USD capital from this refresh
            valid_brokers   number of contributing brokers
            kraken_capital  Kraken-specific capital (0.0 if not included)
            pending         1.0 = no registered sources yet (early call)
            dedup           1.0 = call was coalesced (within REFRESH_MIN_INTERVAL_S)

        Entry guards (applied before any work):
            A. ``has_registered_brokers()`` — hard pre-flight gate; return
               ``pending=1.0`` immediately when no real platform broker has been
               registered yet.  Prevents any refresh path — including the
               bootstrap seed bypass — from running against an empty broker map.
            B. ``has_attempted_connections()`` — hard pre-flight gate; return
               ``pending=1.0`` until :meth:`finalize_broker_registration` has
               been called.  Enforces the strict startup ordering:
               register brokers → finalize → refresh → start Brain.
               This gate also covers the bootstrap seed path, which previously
               bypassed Guard 0 and could hydrate the Brain before the full
               broker set was stable.
            0. ``_broker_registration_complete`` — redundant after gate B but
               retained as a defence-in-depth barrier.
            1. ``has_registered_sources()`` — skip silently when no brokers are
               registered yet (avoids log storms from early watchdog cycles).
            2. ``REFRESH_MIN_INTERVAL_S`` dedup — coalesce rapid back-to-back calls
               (startup loop + watchdog + connect hooks) into a single coordinator run.
        """
        if get_capital_authority is None:
            with self._capital_state_lock:
                self._capital_ready = False
            return {"ready": 0.0, "total_capital": 0.0, "valid_brokers": 0.0}

        # ── Pre-flight broker-registration gates (A + B) ──────────────────────
        # HARD ordering barrier: do not run ANY refresh path — including the
        # bootstrap seed bypass below — until:
        #   A. at least one real platform broker has been registered (broker
        #      registry barrier).  Without this gate the seed path can hydrate
        #      CapitalAllocationBrain before any real broker exists.
        #   B. finalize_broker_registration() has been called (full broker map
        #      is stable).  Applied only to non-bootstrap triggers so that the
        #      one-shot seed path (a deadlock breaker) can run for bootstrap
        #      triggers before finalization is complete.  The seed path itself
        #      calls finalize_broker_registration() on success, so Gate B is
        #      self-lifting for the bootstrap sequence.
        # Both gates are non-blocking: callers that arrive early simply receive
        # pending=1.0 and retry on the next cycle.  The blocking while-loops in
        # the bootstrap master sequence (bot.py) ensure the explicit
        # BOOTSTRAP_START call waits until both conditions are satisfied.
        if not self.has_registered_brokers():
            logger.debug(
                "⏳ [CapitalAuthorityRefresh] trigger=%s skipped — no brokers registered yet",
                trigger,
            )
            return {"ready": 0.0, "total_capital": 0.0, "valid_brokers": 0.0, "pending": 1.0}
        if not self.has_attempted_connections() and not self._is_bootstrap_trigger(trigger):
            logger.debug(
                "⏳ [CapitalAuthorityRefresh] trigger=%s skipped — broker registration not finalized",
                trigger,
            )
            return {"ready": 0.0, "total_capital": 0.0, "valid_brokers": 0.0, "pending": 1.0}

        # ── MABM Broker-Readiness Gate (bootstrap-phase only) ─────────────────
        # During initial bootstrap — before _capital_ready has ever been set
        # True — block any refresh attempt when no platform broker is fully
        # ready (connected + balance payload available).  This prevents
        # spurious $0 snapshots from being published before any real balance
        # data exists, which would seed CapitalAllocationBrain with invalid
        # capital figures and freeze allocation logic.
        #
        # CRITICAL: the gate is intentionally restricted to the pre-capital-ready
        # window (``not _cap_ready``).  Once bootstrap has succeeded and
        # ``_capital_ready`` has been set ``True`` by the coordinator pipeline,
        # this check is skipped unconditionally so that watchdog, per-cycle,
        # and recovery refreshes are never blocked by it.  If the gate were
        # applied permanently it would re-block entry execution whenever a
        # reconnect cycle leaves ``_last_known_balance`` temporarily None —
        # causing the exact "entries blocked after bootstrap handoff" failure
        # this gate is designed to prevent during *startup only*.
        with self._capital_state_lock:
            _cap_ready = self._capital_ready
        if not _cap_ready:
            _not_ready_brokers = [
                (name, b)
                for name, b in self._platform_brokers.items()
                if not is_broker_fully_ready(b)
            ]
            if _not_ready_brokers:
                for _broker_name, _broker in _not_ready_brokers:
                    logger.warning(
                        "[MABM-GATE] BLOCKED refresh_capital_authority — "
                        "%s: connected=%s payload_hydrated=%s",
                        _broker_name,
                        getattr(_broker, "connected", False),
                        (
                            (callable(getattr(_broker, "has_balance_payload_for_capital", None))
                             and _broker.has_balance_payload_for_capital())
                            or (callable(getattr(_broker, "has_balance_payload", None))
                                and _broker.has_balance_payload())
                            or getattr(_broker, "_last_known_balance", None) is not None
                        ),
                    )
                return {
                    "ready": 0.0,
                    "total_capital": 0.0,
                    "valid_brokers": 0.0,
                    "reason": "BROKERS_NOT_READY_GATE",
                    "pending": 1.0,
                }

        # ── Forced bootstrap seed (one-shot deadlock breaker) ─────────────────
        # If STARTUP_LOCK has never been set and the normal coordinator pipeline
        # is blocked behind _broker_registration_complete (Guard 0 below), a
        # CapitalAllocationBrain.__init__ that blocks on CAPITAL_SYSTEM_READY
        # will never unblock — a hard initialization deadlock.
        #
        # The seed path bypasses Guard 0 exactly once per process:
        #   1. Read _last_known_balance from every already-registered broker.
        #   2. Publish a minimal CapitalSnapshot → sets CAPITAL_SYSTEM_READY.
        #   3. Lift _broker_registration_complete and finalize_bootstrap_ready()
        #      so the normal pipeline takes over immediately afterward.
        #
        # Double-checked locking (DCL) pattern: the outer unsynchronised read
        # of _bootstrap_seed_done is safe because the flag transitions
        # monotonically False → True under _bootstrap_seed_lock and Python's
        # GIL guarantees that a plain bool read/write is atomic.  Multiple
        # threads may pass the outer gate before the first one sets the flag,
        # but they immediately contend on _bootstrap_seed_lock and the inner
        # check serialises them — only the first thread runs the seed block.
        #
        # is_hydrated fast-path: if CapitalAuthority is already hydrated (via
        # the normal coordinator pipeline or a prior seed on another thread) the
        # seed is unnecessary regardless of _startup_lock_is_set().
        # Checking is_hydrated first avoids taking _bootstrap_seed_lock on every
        # call once the system is initialised — a common hot-path optimisation.
        # _ca_for_seed may be None during very early startup if the singleton
        # has not yet been created; in that case we allow the seed path to
        # proceed so the system can still bootstrap normally.
        #
        # Bootstrap is state-driven, not trigger-driven: the trigger check has
        # been intentionally removed so that any call can seed CapitalAuthority
        # when the three state conditions are satisfied.  Trigger-based logic is
        # inherently non-deterministic in multi-threaded startup.
        _ca_for_seed = get_capital_authority() if get_capital_authority else None
        if (
            (_ca_for_seed is None or not _ca_for_seed.is_hydrated)
            and not self._startup_lock_is_set()
            and not self._bootstrap_seed_done
        ):
            with self._bootstrap_seed_lock:
                if not self._bootstrap_seed_done:
                    _seed_snapshot = self._force_minimal_capital_snapshot()
                    if _seed_snapshot is not None:
                        # Always re-fetch the CA singleton inside the lock so that
                        # test resets, hot reloads, or multiple import paths cannot
                        # leave us holding a stale reference obtained before the lock.
                        _authority = _ca_for_seed or get_capital_authority()
                        _WRITER_ID: Optional[str] = None
                        for _fsm_mod in ("bot.capital_flow_state_machine", "capital_flow_state_machine"):
                            try:
                                _WRITER_ID = __import__(
                                    _fsm_mod, fromlist=["WRITER_ID"]
                                ).WRITER_ID
                                break
                            except ImportError:
                                continue
                        if _authority is not None and _WRITER_ID is not None:
                            _accepted = _authority.publish_snapshot(_seed_snapshot, writer_id=_WRITER_ID)
                            if _accepted:
                                # Mark done only after a successful publish so that a
                                # rejected snapshot does not permanently close the retry
                                # path on the next call.
                                self._bootstrap_seed_done = True
                                logger.info(
                                    "[MABM] bootstrap seed published: real=$%.2f brokers=%s — "
                                    "lifting registration gate and startup lock",
                                    _seed_snapshot.real_capital,
                                    sorted(_seed_snapshot.broker_balances.keys()),
                                )
                                self.finalize_broker_registration()
                                self.finalize_bootstrap_ready()
                                # ── Drive bootstrap FSM to READY (seed path shortcut) ────────
                                # The coordinator's _pipeline() is the normal FSM driver, but
                                # the seed path bypasses the coordinator entirely (it uses
                                # cached balances and returns early).  Without advancing the
                                # FSM here, is_capital_authority_ready() — which delegates
                                # exclusively to the FSM — stays False even though the seed
                                # published a valid snapshot and set _capital_ready = True.
                                # That False-FSM gap prevents the trading gate from ever
                                # flipping to ACTIVE:
                                #
                                #   seed published → _capital_ready = True
                                #   is_capital_authority_ready() → _capital_bootstrap_fsm.is_ready
                                #                                → WAIT_PLATFORM → False  ← BUG
                                #
                                # Transition the FSM through the full forward path so the
                                # process-wide singleton matches the observed capital state.
                                # Each transition() call is a no-op when invalid (logs DEBUG),
                                # so this is safe to call even if a concurrent coordinator run
                                # already advanced the FSM partway.
                                if _CAPITAL_FSM_AVAILABLE and self._capital_bootstrap_fsm is not None:
                                    _bseed_fsm = self._capital_bootstrap_fsm
                                    # ── Notify CSM-v2 BEFORE the READY transition ────────────────
                                    # The READY transition fires _on_capital_bootstrap_ready
                                    # synchronously; that callback calls advance_to_capital_ready()
                                    # which runs the I12 hydration barrier.  Feed CSM-v2 the seed
                                    # snapshot here so it is already hydrated when I12 fires.
                                    try:
                                        from bot.capital_csm_v2 import get_csm_v2 as _csmv2  # noqa: PLC0415
                                        _csmv2().ingest_snapshot(_seed_snapshot)
                                    except ImportError:
                                        pass
                                    except Exception as _csm_seed_exc:
                                        logger.warning(
                                            "[MABM] bootstrap seed CSM-v2 ingest failed (non-fatal): %s",
                                            _csm_seed_exc,
                                        )
                                    _bseed_fsm.transition(
                                        CapitalBootstrapState.REFRESH_REQUESTED, "bootstrap_seed"
                                    )
                                    _bseed_fsm.transition(
                                        CapitalBootstrapState.REFRESH_IN_FLIGHT, "bootstrap_seed"
                                    )
                                    _bseed_fsm.transition(
                                        CapitalBootstrapState.SNAPSHOT_EVALUATING, "bootstrap_seed"
                                    )
                                    _bseed_fsm.transition(
                                        CapitalBootstrapState.READY, "bootstrap_seed"
                                    )
                                    if self._capital_event_bus is not None:
                                        self._capital_event_bus.emit(CapitalEvent(
                                            event_type=CapitalEventType.CAPITAL_READY,
                                            trigger="bootstrap_seed",
                                        ))
                                with self._capital_state_lock:
                                    self._capital_ready = True
                                    self._capital_last_refresh_ts = time.time()
                                return {
                                    "ready": 1.0,
                                    "total_capital": _seed_snapshot.real_capital,
                                    "valid_brokers": float(_seed_snapshot.broker_count),
                                    "kraken_capital": float(
                                        _seed_snapshot.broker_balances.get("kraken", 0.0)
                                    ),
                                    "bootstrap_seed": 1.0,
                                }
                            else:
                                logger.warning(
                                    "[MABM] bootstrap seed publish rejected — "
                                    "falling through to normal pipeline"
                                )
                        else:
                            logger.warning(
                                "[MABM] bootstrap seed: authority or WRITER_ID unavailable — "
                                "falling through to normal pipeline"
                            )
                    else:
                        logger.info(
                            "[MABM] bootstrap seed: no cached balances yet — "
                            "falling through to normal pipeline"
                        )

        # ── Guard 0: broker registration hard gate ────────────────────────────
        # CRITICAL: never evaluate capital before ALL brokers are registered.
        # Without this gate a refresh triggered immediately at startup (by the
        # watchdog or CapitalAllocationBrain.__init__) runs against a broker map
        # that is still being populated, producing spurious $0-capital snapshots
        # that can freeze allocation or trigger halt logic.
        if not self._broker_registration_complete.is_set():
            logger.info(
                "⏳ [CapitalAuthorityRefresh] trigger=%s skipped — broker registration not complete",
                trigger,
            )
            return {"ready": 0.0, "total_capital": 0.0, "valid_brokers": 0.0, "pending": 1.0}

        # ── Guard 1: no registered sources yet ────────────────────────────────
        if not self.has_registered_sources():
            logger.debug(
                "[CapitalAuthorityRefresh] trigger=%s skipped — no registered capital sources yet",
                trigger,
            )
            return {"ready": 0.0, "total_capital": 0.0, "valid_brokers": 0.0, "pending": 1.0}

        # ── Guard 2: rapid-call deduplication ─────────────────────────────────
        with self._capital_state_lock:
            _last = self._capital_last_refresh_ts
            _ready = self._capital_ready
            _last_vb = self._capital_last_valid_brokers
        if (time.time() - _last) < self.REFRESH_MIN_INTERVAL_S:
            logger.debug(
                "[CapitalAuthorityRefresh] trigger=%s skipped (dedup) — last refresh %.3fs ago",
                trigger,
                time.time() - _last,
            )
            return {"ready": 1.0 if _ready else 0.0, "total_capital": 0.0, "valid_brokers": float(_last_vb), "dedup": 1.0}

        try:
            bootstrap_trigger = self._is_bootstrap_trigger(trigger)
            if bootstrap_trigger and self._capital_bootstrap_barrier_started_at is None:
                self._capital_bootstrap_barrier_started_at = time.monotonic()
            broker_map: Dict[str, BaseBroker] = {}
            registered_sources = len(self._platform_brokers)
            # Fix 4: Hard assertion — a globally connected broker must appear in MABM
            # registered sources.  Fires as a loud AssertionError (caught by the outer
            # except and surfaced as an ERROR log) instead of silently producing $0
            # capital and blocking all trading indefinitely.
            _kraken_broker_connected = (
                _KRAKEN_STARTUP_FSM is not None and _KRAKEN_STARTUP_FSM.is_connected
            )
            assert not (_kraken_broker_connected and registered_sources == 0), (
                "Capital source registration failure: "
                "Kraken broker connected but not registered with capital manager"
            )
            for broker_type, broker in self._platform_brokers.items():

                # ── Bootstrap path: BrokerPayloadFSM-driven eligibility ────────
                # During startup triggers, the FSM is the sole eligibility gate.
                # It actively probes brokers that are registered but have no
                # payload yet, advancing them to PAYLOAD_READY or EXHAUSTED in a
                # bounded number of attempts.  This eliminates the class of
                # failure where connect() failed before seeding _last_known_balance
                # (logged as reason=bootstrap_missing_balance_payload in prior code),
                # leaving the broker permanently stuck with no payload and capital
                # frozen at $0 indefinitely.
                if bootstrap_trigger and _CAPITAL_FSM_AVAILABLE and BrokerPayloadFSM is not None:
                    payload_fsm = self._broker_payload_fsm.get(broker_type)
                    if payload_fsm is None:
                        # FSM not yet created (late-registered broker) — create it now.
                        payload_fsm = BrokerPayloadFSM(broker_id=broker_type.value)
                        self._broker_payload_fsm[broker_type] = payload_fsm
                        # Check if balance is already present on the broker object.
                        if getattr(broker, "_last_known_balance", None) is not None:
                            payload_fsm.mark_payload_ready()

                    if payload_fsm.is_exhausted:
                        logger.warning(
                            "[CapitalAuthorityRefresh] trigger=%s skip broker=%s "
                            "reason=payload_fsm_exhausted (probe_attempts=%d/%d)",
                            trigger,
                            broker_type.value,
                            payload_fsm.probe_attempts,
                            payload_fsm.max_probe_attempts,
                        )
                        continue

                    if not payload_fsm.is_payload_ready:
                        # Synchronise FSM with any balance that connect() may have
                        # seeded after the FSM was last checked.
                        if getattr(broker, "_last_known_balance", None) is not None:
                            payload_fsm.mark_payload_ready()
                        else:
                            # Actively probe the broker to break the chicken-and-egg:
                            # broker needs a payload to enter broker_map, but the only
                            # call that sets the payload (get_account_balance via
                            # CapitalAuthority.refresh) only runs for brokers that are
                            # already in broker_map.  probe_and_advance() calls
                            # get_account_balance() directly, resolving the deadlock.
                            logger.info(
                                "[CapitalAuthorityRefresh] trigger=%s broker=%s "
                                "FSM=%s — probing balance to seed payload",
                                trigger,
                                broker_type.value,
                                payload_fsm.state.value,
                            )
                            payload_fsm.probe_and_advance(broker)

                    if not payload_fsm.is_payload_ready:
                        logger.info(
                            "[CapitalAuthorityRefresh] trigger=%s skip broker=%s "
                            "reason=payload_fsm_not_ready (state=%s attempts=%d/%d)",
                            trigger,
                            broker_type.value,
                            payload_fsm.state.value,
                            payload_fsm.probe_attempts,
                            payload_fsm.max_probe_attempts,
                        )
                        continue

                    # FSM is PAYLOAD_READY — include unconditionally during bootstrap.
                    logger.debug(
                        "[CapitalAuthorityRefresh] trigger=%s include broker=%s "
                        "reason=payload_fsm_ready",
                        trigger,
                        broker_type.value,
                    )
                    broker_map[broker_type.value] = broker
                    continue

                # ── Non-bootstrap path ────────────────────────────────────────
                # Inclusion Contract: connection state is irrelevant for capital
                # inclusion.  The ONLY gate is whether the broker has a balance
                # payload.  If it does, it MUST appear in the snapshot.
                has_payload = (
                    getattr(broker, "_last_known_balance", None) is not None
                    or getattr(broker, "has_balance_payload_for_capital", lambda: False)()
                    or getattr(broker, "has_balance_payload", lambda: False)()
                )
                logger.info(
                    "[TRACE][MABM_ELIGIBILITY] broker=%s "
                    "connected=%s "
                    "_last_known_balance=%s "
                    "has_balance_payload=%s "
                    "has_balance_payload_for_capital=%s "
                    "has_payload=%s",
                    broker.name,
                    getattr(broker, "connected", None),
                    getattr(broker, "_last_known_balance", None),
                    broker.has_balance_payload() if hasattr(broker, "has_balance_payload") else None,
                    broker.has_balance_payload_for_capital() if hasattr(broker, "has_balance_payload_for_capital") else None,
                    has_payload,
                )
                if not has_payload:
                    logger.info(
                        "[CapitalAuthorityRefresh] trigger=%s skip broker=%s reason=no_balance_payload",
                        trigger,
                        broker_type.value,
                    )
                    continue
                logger.info(
                    "[CapitalAuthorityRefresh] trigger=%s include broker=%s reason=has_payload"
                    " (platform_connected=%s)",
                    trigger,
                    broker_type.value,
                    self.is_platform_connected(broker_type),
                )
                broker_map[broker_type.value] = broker

            logger.info(
                "[CapitalAuthorityRefresh] trigger=%s eligible_brokers=%s",
                trigger,
                sorted(broker_map.keys()),
            )

            # Bootstrap minimum-source barrier: never run an authority refresh on
            # empty eligible inputs during startup. This prevents empty-input
            # $0 snapshots from driving FAILED loops while brokers are still
            # registering / producing first balance payloads.
            if not broker_map:
                barrier_elapsed = (
                    0.0
                    if self._capital_bootstrap_barrier_started_at is None
                    else (time.monotonic() - self._capital_bootstrap_barrier_started_at)
                )
                barrier_timeout = max(
                    self.MIN_STARTUP_CAPITAL_TIMEOUT_S,
                    self.capital_startup_invariant_timeout_s,
                )
                if bootstrap_trigger or (
                    trigger == self.WATCHDOG_REFRESH_TRIGGER and barrier_elapsed < barrier_timeout
                ):
                    pending_reason = (
                        "no_registered_sources"
                        if registered_sources <= 0
                        else "no_eligible_capital_sources"
                    )
                    logger.info(
                        "[CapitalAuthorityRefresh] pending trigger=%s reason=%s "
                        "registered_sources=%d elapsed=%.2fs timeout=%.2fs",
                        trigger,
                        pending_reason,
                        registered_sources,
                        barrier_elapsed,
                        barrier_timeout,
                    )
                    with self._capital_state_lock:
                        self._capital_ready = False
                    return {
                        "ready": 0.0,
                        "total_capital": 0.0,
                        "valid_brokers": 0.0,
                        "kraken_capital": 0.0,
                        "pending": 1.0,
                    }

            # ── Emit REFRESH_REQUESTED event (bootstrap FSM observability) ────
            # The event is for observability only; FSM transitions are driven
            # by the coordinator's _pipeline() — MABM no longer advances the
            # bootstrap FSM directly from this point.
            if _CAPITAL_FSM_AVAILABLE and self._capital_event_bus is not None:
                self._capital_event_bus.emit(CapitalEvent(
                    event_type=CapitalEventType.REFRESH_REQUESTED,
                    trigger=trigger,
                ))

            # ── Route through coordinator (single writer) ─────────────────────
            snapshot = None
            if _CAPITAL_FSM_AVAILABLE and self._capital_coordinator is not None:
                snapshot = self._capital_coordinator.execute_refresh(
                    broker_map=broker_map,
                    trigger=trigger,
                    open_exposure_usd=0.0,
                )

            # ── Derive return dict from snapshot or fall back to legacy read ──
            authority = get_capital_authority()
            if snapshot is not None:
                total_capital = snapshot.real_capital
                kraken_capital = snapshot.broker_balances.get("kraken", 0.0)
                valid_brokers = snapshot.broker_count
            else:
                # Coordinator not available or rejected snapshot — read CA directly.
                # _bypass_startup_lock=True is required here: this bootstrap path
                # BUILDS the initial snapshot, so it must bypass the startup lock
                # that guards external/consumer callers.  finalize_bootstrap_ready()
                # will be called below once ready=True is confirmed.
                if broker_map:
                    authority.refresh(broker_map, open_exposure_usd=0.0, _bypass_startup_lock=True)
                else:
                    authority.refresh({}, open_exposure_usd=0.0, _bypass_startup_lock=True)
                total_capital = float(authority.get_real_capital())
                authority.update(total_capital)
                valid_brokers = len(broker_map)
                kraken_capital = (
                    float(authority.get_raw_per_broker("kraken"))
                    if "kraken" in broker_map
                    else 0.0
                )

            kraken_connected = "kraken" in broker_map
            # Unified readiness should reflect aggregate usable capital, not require
            # a specific venue to hold funds.
            has_connected_brokers = bool(broker_map)
            ready = has_connected_brokers and (total_capital > 0.0)
            kraken_broker = self._platform_brokers.get(BrokerType.KRAKEN)
            kraken_connected_layer = bool(getattr(kraken_broker, "connected", False))
            kraken_included = "kraken" in broker_map
            # ── assets_priced_ok: resolve from best available source ──────────
            # When the coordinator returns a snapshot, use it directly.
            # When the coordinator returns None (in-flight concurrent call,
            # monotonic-guard rejection, or unrecoverable exception), fall back
            # to the most recently accepted snapshot already held by
            # CapitalAuthority.  As a last resort, read the Kraken broker's
            # cached pricing-coverage value (_last_pricing_coverage_pct),
            # which defaults to 1.0 at broker init and is updated after every
            # successful balance compute.  This prevents a transient coordinator
            # unavailability from permanently blocking readiness when Kraken is
            # connected: snapshot=None → assets_priced_ok=False → kraken_ready=False
            # → ready=False even though capital exists and coverage is fine.
            _assets_pct: float = 0.0
            if snapshot is not None:
                _assets_pct = float(getattr(snapshot, "assets_priced_success_pct", 0.0))
            else:
                if authority is not None:
                    _ca_typed_snap = getattr(authority, "_last_typed_snapshot", None)
                    if _ca_typed_snap is not None:
                        _assets_pct = float(
                            getattr(_ca_typed_snap, "assets_priced_success_pct", 0.0)
                        )
                if _assets_pct == 0.0:
                    _kbkr = self._platform_brokers.get(BrokerType.KRAKEN)
                    if _kbkr is not None:
                        _assets_pct = float(
                            getattr(_kbkr, "_last_pricing_coverage_pct", 1.0)
                        )
            assets_priced_ok = _assets_pct > 0.0
            # bootstrap_ok: True  = bootstrap FSM has not reached FAILED state.
            # Recovery from FAILED is handled by the coordinator's _pipeline()
            # at the start of the next refresh cycle — MABM does not drive FSM
            # transitions here (FSM is the authority on readiness).
            bootstrap_ok = True
            if _CAPITAL_FSM_AVAILABLE and self._capital_bootstrap_fsm is not None:
                bootstrap_ok = (
                    self._capital_bootstrap_fsm.state != CapitalBootstrapState.FAILED
                )
            kraken_ready = (
                kraken_connected_layer
                and kraken_included
                and (kraken_capital > 0.0)
                and assets_priced_ok
                and bootstrap_ok
            )
            # ── Readiness fallback: exhausted Kraken FSM must not block other brokers ─
            # If Kraken is physically connected (kraken_connected_layer=True) but its
            # BrokerPayloadFSM is in EXHAUSTED state (all probe attempts consumed and
            # the TTL-based auto-reset has not fired yet), the normal formula
            #   ready = kraken_ready if kraken_connected_layer else (total_capital > 0.0)
            # permanently evaluates to False even when other brokers supply positive
            # capital — creating a hard deadlock.
            #
            # The fallback: treat a connected-but-exhausted Kraken as "temporarily
            # unavailable" and allow other broker capital to satisfy readiness.
            # This is safe because the auto-reset in BrokerPayloadFSM.is_exhausted
            # will re-admit Kraken to the probe cycle after EXHAUSTED_RESET_TTL_S,
            # and the watchdog will re-evaluate once Kraken's payload is confirmed.
            kraken_fsm_exhausted = False
            if (
                kraken_connected_layer
                and not kraken_included
                and _CAPITAL_FSM_AVAILABLE
            ):
                _kfsm = self._broker_payload_fsm.get(BrokerType.KRAKEN)
                if _kfsm is not None and _kfsm.is_exhausted:
                    kraken_fsm_exhausted = True
                    logger.warning(
                        "[CapitalAuthorityRefresh] trigger=%s Kraken FSM EXHAUSTED — "
                        "falling back to non-Kraken capital readiness (total=$%.2f)",
                        trigger,
                        total_capital,
                    )

            if kraken_connected_layer and not kraken_fsm_exhausted:
                ready = kraken_ready
            else:
                ready = total_capital > 0.0
            with self._capital_state_lock:
                self._capital_ready = ready
                self._capital_last_refresh_ts = time.time()
                if valid_brokers > 0:
                    self._capital_last_valid_brokers = valid_brokers
            logger.info(
                "[CapitalAuthorityRefresh] trigger=%s ready=%s total=$%.2f valid_brokers=%d "
                "kraken_connected_layer=%s kraken_included=%s assets_priced_ok=%s "
                "bootstrap_trigger=%s bootstrap_ok=%s kraken_capital=$%.2f"
                " kraken_fsm_exhausted=%s",
                trigger,
                ready,
                total_capital,
                valid_brokers,
                kraken_connected_layer,
                kraken_included,
                assets_priced_ok,
                bootstrap_trigger,
                bootstrap_ok,
                kraken_capital,
                kraken_fsm_exhausted,
            )

            if ready:
                self._capital_bootstrap_barrier_started_at = None
                logger.info("CAPITAL_READY")
                self._sync_platform_connection_states(broker_map)
                if kraken_connected:
                    if kraken_included:
                        try:
                            _KRAKEN_STARTUP_FSM.mark_capital_ready()
                        except Exception as exc:
                            logger.warning(
                                "[CapitalAuthorityRefresh] Failed to mark Kraken capital ready: %s",
                                exc,
                            )
                with self._capital_state_lock:
                    was_halted = self._trading_halted_due_to_capital
                if was_halted:
                    logger.info(
                        "✅ CapitalAuthority recovered (trigger=%s): brokers=%d total=$%.2f — trading resume allowed",
                        trigger, valid_brokers, total_capital,
                    )
                with self._capital_state_lock:
                    self._trading_halted_due_to_capital = False
                # Release the global startup lock the first time we reach READY.
                # This is the point at which:
                #   1. broker registration is confirmed (guard 0 already passed)
                #   2. broker list is in CA (pending feeds flushed via finalize_broker_registration)
                #   3. first feed batch processed (snapshot has real_capital > 0)
                #   4. FSM initialized (bootstrap_ok confirmed above)
                # ONLY NOW allow CapitalAllocationBrain + external refresh loops.
                # Check both the local flag and the authoritative STARTUP_LOCK event so
                # that a direct CA release is also respected here.
                if not self._startup_lock_released and not self._startup_lock_is_set():
                    try:
                        self.finalize_bootstrap_ready()
                    except Exception as _slk_exc:
                        logger.warning(
                            "[CapitalAuthorityRefresh] finalize_bootstrap_ready failed: %s",
                            _slk_exc,
                        )
            else:
                logger.error(
                    "⛔ CapitalAuthority NOT READY (trigger=%s): valid_brokers=%d total_capital=$%.2f "
                    "kraken_connected_layer=%s kraken_included=%s assets_priced_ok=%s "
                    "bootstrap_trigger=%s bootstrap_ok=%s kraken_capital=$%.2f",
                    trigger,
                    valid_brokers,
                    total_capital,
                    kraken_connected_layer,
                    kraken_included,
                    assets_priced_ok,
                    bootstrap_trigger,
                    bootstrap_ok,
                    kraken_capital,
                )

            return {
                "ready": 1.0 if ready else 0.0,
                "total_capital": total_capital,
                "valid_brokers": float(valid_brokers),
                "kraken_capital": kraken_capital,
                # snapshot_source distinguishes data obtained from a live exchange
                # API call ("live_exchange") from placeholder/fallback snapshots
                # ("placeholder").  Downstream bootstrap guards use this field to
                # reject snapshots that were produced without real exchange data.
                # An empty broker_map means no connected brokers contributed; the
                # dict is intentionally falsy when empty.
                "snapshot_source": "live_exchange" if broker_map else "placeholder",
            }
        except Exception as exc:
            logger.error("❌ CapitalAuthority refresh failed (%s): %s", trigger, exc)
            with self._capital_state_lock:
                self._capital_ready = False
            return {"ready": 0.0, "total_capital": 0.0, "valid_brokers": 0.0, "snapshot_source": "placeholder"}

    def enforce_trading_bootstrap_contract(
        self,
        max_attempts: int = 3,
        retry_delay_s: float = 1.0,
    ) -> Dict[str, float]:
        """Fail-closed bootstrap contract for singleton/registry/capital readiness."""
        last_snapshot: Dict[str, float] = {"ready": 0.0, "total_capital": 0.0, "valid_brokers": 0.0}
        self._bootstrap_contract_ok = False
        self._bootstrap_contract_last_error = ""

        for attempt in range(1, max(1, int(max_attempts)) + 1):
            try:
                canonical_manager = get_broker_manager()
                if self is not canonical_manager:
                    self._bootstrap_contract_last_error = "singleton_mismatch"
                    logger.critical(
                        "[BootstrapContract] attempt=%d/%d failed: singleton mismatch",
                        attempt, max_attempts,
                    )
                    with self._capital_state_lock:
                        self._trading_halted_due_to_capital = True
                    return last_snapshot

                self.refresh_registry()
                last_snapshot = self.refresh_capital_authority(
                    trigger=f"bootstrap_contract:{attempt}"
                )
                ready = bool(last_snapshot.get("ready", 0.0))
                valid_brokers = int(last_snapshot.get("valid_brokers", 0.0))
                total_capital = float(last_snapshot.get("total_capital", 0.0))

                if ready and valid_brokers > 0 and total_capital > 1e-6:
                    self._bootstrap_contract_ok = True
                    self._bootstrap_contract_last_error = ""
                    with self._capital_state_lock:
                        self._trading_halted_due_to_capital = False
                    logger.info(
                        "[BootstrapContract] satisfied on attempt %d/%d "
                        "(valid_brokers=%d total_capital=$%.2f ready=%s)",
                        attempt, max_attempts, valid_brokers, total_capital, ready,
                    )
                    return last_snapshot

                self._bootstrap_contract_last_error = (
                    f"capital_not_ready(valid_brokers={valid_brokers}, total_capital={total_capital:.2f}, ready={ready})"
                )
                logger.warning(
                    "[BootstrapContract] attempt=%d/%d not ready: %s",
                    attempt, max_attempts, self._bootstrap_contract_last_error,
                )
            except Exception as exc:
                self._bootstrap_contract_last_error = f"exception:{exc}"
                logger.error(
                    "[BootstrapContract] attempt=%d/%d error: %s",
                    attempt, max_attempts, exc,
                )

            if attempt < max_attempts:
                time.sleep(max(0.0, float(retry_delay_s)))

        with self._capital_state_lock:
            self._trading_halted_due_to_capital = True
        logger.critical(
            "[BootstrapContract] FAILED after %d attempts — trading remains halted. last_error=%s",
            max_attempts, self._bootstrap_contract_last_error or "unknown",
        )
        return last_snapshot

    def _is_broker_ready_for_capital_refresh(
        self,
        broker_type: BrokerType,
        broker: Optional[BaseBroker],
        trigger: str = "manual",
    ) -> Tuple[bool, str]:
        """
        Unified broker-readiness gate for capital refresh.

        Normal mode is strict state-driven readiness. Bootstrap mode is strict
        payload-driven readiness.

        Args:
            broker_type: Platform broker type being evaluated.
            broker: Platform broker instance (may be None).

        Returns:
            Tuple[bool, str]:
                - bool: Whether this broker is eligible to contribute capital now.
                - str: Eligibility reason code for observability/logging.
        """
        if broker is None:
            return False, "missing_broker"
        name = broker_type.value
        ready_getter = getattr(broker, "is_ready_for_capital", None)
        if callable(ready_getter):
            try:
                # FIX 1: STRICT MODE only after bootstrap is fully complete (FSM == READY).
                # Before READY, fall through to the payload-based check so that
                # watchdog / manual triggers during startup never produce the
                # broker_not_ready_for_capital hard block.  The circular dependency
                # (broker needs _last_known_balance to pass is_ready_for_capital, but
                # _last_known_balance is only set by a refresh that already includes the
                # broker) is broken by always using payload-based gating until READY.
                # Re-uses is_bootstrap_phase to avoid duplicating the FSM state check.
                if not self._is_bootstrap_trigger(trigger) and not self.is_bootstrap_phase:
                    # STRICT MODE (normal steady-state operation post-bootstrap)
                    is_ready = bool(ready_getter())
                    return is_ready, "broker_ready_for_capital" if is_ready else "broker_not_ready_for_capital"

                # BOOTSTRAP / PRE-READY MODE (payload-driven only)
                has_payload = (
                    getattr(broker, "has_balance_payload_for_capital", lambda: False)()
                    or getattr(broker, "has_balance_payload", lambda: False)()
                    or getattr(broker, "_last_known_balance", None) is not None
                )
                logger.info(
                    f"[CapitalAuthorityDebug] broker={name} "
                    f"has_payload={has_payload} "
                    f"balance={getattr(broker, '_last_known_balance', None)}"
                )
                if has_payload:
                    return True, "bootstrap_balance_payload_ready"
                return False, "bootstrap_missing_balance_payload"
            except Exception as exc:
                logger.debug(
                    "[CapitalAuthorityRefresh] broker=%s is_ready_for_capital raised: %s",
                    name,
                    exc,
                )
                return False, "capital_readiness_error"
        return False, "capital_readiness_unavailable"

    def _can_include_bootstrap_connected_broker(
        self,
        trigger: str,
        is_platform_ready: bool,
        broker: BaseBroker,
    ) -> bool:
        # Bootstrap-only relaxation: include connected brokers that already
        # produced a balance payload, even before platform-ready flips true.
        # Once bootstrap reaches READY, strict gating resumes automatically.
        if is_platform_ready:
            return False
        has_payload = False
        has_payload_for_capital_attr = getattr(broker, "has_balance_payload_for_capital", None)
        if callable(has_payload_for_capital_attr):
            try:
                has_payload = bool(has_payload_for_capital_attr())
            except Exception as exc:
                logger.debug(
                    "[CapitalAuthorityRefresh] broker=%s has_balance_payload_for_capital raised: %s",
                    getattr(getattr(broker, "broker_type", None), "value", "unknown"),
                    exc,
                )
                has_payload = False
        elif hasattr(broker, "has_balance_payload"):
            has_payload_attr = getattr(broker, "has_balance_payload", None)
            try:
                has_payload = bool(has_payload_attr()) if callable(has_payload_attr) else False
            except Exception as exc:
                logger.debug(
                    "[CapitalAuthorityRefresh] broker=%s has_balance_payload raised: %s",
                    getattr(getattr(broker, "broker_type", None), "value", "unknown"),
                    exc,
                )
                has_payload = False
        if not has_payload:
            return False
        if not (
            self._is_bootstrap_trigger(trigger)
            or trigger == self.WATCHDOG_REFRESH_TRIGGER
        ):
            return False
        if not _CAPITAL_FSM_AVAILABLE or self._capital_bootstrap_fsm is None:
            return False
        return self._capital_bootstrap_fsm.state in self.BOOTSTRAP_CONNECTED_ELIGIBLE_STATES

    def _is_bootstrap_trigger(self, trigger: str) -> bool:
        return trigger.split(":", 1)[0] in self.BOOTSTRAP_TRIGGERS

    def _sync_platform_connection_states(self, broker_map: Dict[str, BaseBroker]) -> None:
        """Mark connected platform brokers as CONNECTED after capital becomes ready."""
        for broker_type, broker in self._platform_brokers.items():
            if (
                broker_type.value in broker_map
                and getattr(broker, "connected", False)
                and not self.is_platform_connected(broker_type)
            ):
                self._mark_platform_connected(broker_type)

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
            else max(self.MIN_STARTUP_CAPITAL_TIMEOUT_S, self.capital_startup_invariant_timeout_s)
        )
        poll = (
            poll_s
            if poll_s is not None
            else max(self.MIN_STARTUP_CAPITAL_POLL_S, self.capital_startup_invariant_poll_s)
        )

        start = time.monotonic()
        attempts = 0
        snapshot: Dict[str, float] = {"ready": 0.0, "total_capital": 0.0, "valid_brokers": 0.0}

        while True:
            attempts += 1
            # Bootstrap loop requests a refresh via the event bus for
            # observability, then calls refresh_capital_authority() which routes
            # through the coordinator.  The coordinator's _pipeline() now owns
            # the full FSM path (WAIT_PLATFORM/DEGRADED/FAILED → REFRESH_REQUESTED
            # → REFRESH_IN_FLIGHT → … → READY/DEGRADED/FAILED) — MABM no longer
            # drives FSM transitions here.
            if _CAPITAL_FSM_AVAILABLE and self._capital_event_bus is not None:
                self._capital_event_bus.emit(CapitalEvent(
                    event_type=CapitalEventType.REFRESH_REQUESTED,
                    trigger=f"{trigger}:attempt_{attempts}",
                ))
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

            remaining = max(0.0, timeout - elapsed)
            # Keep a small floor to avoid a tight near-timeout spin loop that
            # can burn CPU while still allowing prompt timeout exit.
            sleep_for = min(
                remaining,
                max(self.MIN_STARTUP_CAPITAL_SLEEP_S, min(poll, remaining)),
            )
            time.sleep(sleep_for)

    @property
    def is_bootstrap_phase(self) -> bool:
        """True while the capital bootstrap FSM has not yet reached READY.

        FIX 4 bootstrap bypass: callers may check this flag to decide whether
        to call ``force_accept_feed()`` on CapitalAuthority directly instead of
        waiting for the coordinator pipeline to complete.
        """
        if not _CAPITAL_FSM_AVAILABLE or self._capital_bootstrap_fsm is None:
            # No FSM available — assume bootstrap until proven otherwise.
            return True
        return not self._capital_bootstrap_fsm.is_ready

    @property
    def bootstrap_state(self) -> str:
        """Current CapitalBootstrapStateMachine state as a string.

        FSM is the single authority on readiness — callers should read this
        property instead of accessing the FSM directly.  Returns
        ``"unavailable"`` when the FSM module could not be imported.
        """
        if not _CAPITAL_FSM_AVAILABLE or self._capital_bootstrap_fsm is None:
            return "unavailable"
        return self._capital_bootstrap_fsm.state.value

    def is_capital_authority_ready(self) -> bool:
        """Return True only when capital is ready for trading gates.

        **FSM is the authority on readiness.**  The bootstrap FSM's ``READY``
        state is the canonical signal — it is set by the coordinator after a
        successful five-stage pipeline run and is never cleared after being
        set.  The local ``_capital_ready`` bool is retained as a fallback for
        deployments where the FSM module is unavailable.
        """
        if _CAPITAL_FSM_AVAILABLE and self._capital_bootstrap_fsm is not None:
            return self._capital_bootstrap_fsm.is_ready
        with self._capital_state_lock:
            return bool(self._capital_ready)

    def is_ready_for_balance_fetch(self) -> Tuple[bool, str]:
        """Return (True, "") when a live balance fetch is safe to perform.

        Checks only the two pre-fetch prerequisites:

        1. **connected** — at least one platform broker has ``broker.connected == True``.
        2. **payload_hydrated** — at least one connected broker has produced a
           prior balance payload.

        Intentionally does NOT check ``capital_ready`` or ``nonce_lock_acquired``
        because the balance fetch is what *produces* capital-ready state, and the
        nonce lock only gates order placement, not balance reads.

        Returns
        -------
        Tuple[bool, str]
            ``(True, "")`` when the fetch may proceed.
            ``(False, reason)`` otherwise (reason codes: ``"not_connected"``,
            ``"payload_not_hydrated"``).
        """
        connected = any(
            getattr(b, "connected", False)
            for b in self._platform_brokers.values()
        )
        if not connected:
            return False, "not_connected"

        payload_ok = False
        for broker in self._platform_brokers.values():
            if not getattr(broker, "connected", False):
                continue
            has_payload = (
                (callable(getattr(broker, "has_balance_payload_for_capital", None))
                 and broker.has_balance_payload_for_capital())
                or (callable(getattr(broker, "has_balance_payload", None))
                    and broker.has_balance_payload())
                or getattr(broker, "_last_known_balance", None) is not None
            )
            if has_payload:
                payload_ok = True
                break
        if not payload_ok:
            return False, "payload_not_hydrated"

        return True, ""

    def is_fully_hydrated_for_trading(self) -> Tuple[bool, str]:
        """Return (True, "") only when all four hydration invariants are met.

        Gates new *entry* execution (not balance fetching).  Balance fetching
        uses the lighter :meth:`is_ready_for_balance_fetch` check so that the
        capital pipeline can run and set ``capital_ready`` before this gate is
        consulted.

        The four required conditions, checked in order:

        1. **connected** — at least one platform broker has ``broker.connected == True``.
        2. **payload_hydrated** — at least one connected broker has produced a
           balance payload (``has_balance_payload_for_capital()`` or
           ``has_balance_payload()`` or ``_last_known_balance is not None``).
        3. **capital_ready** — :meth:`is_capital_authority_ready` returns ``True``.
        4. **nonce_lock_acquired** — the ``KrakenNonceManager`` singleton holds
           the process-lifetime PID lock (``_pid_lock_acquired == True``).

        Returns
        -------
        Tuple[bool, str]
            ``(True, "")`` when all invariants are satisfied.
            ``(False, reason)`` with a human-readable *reason* code when any
            invariant is not yet met.  Reason codes (one per failing condition):

            * ``"not_connected"``        — no platform broker is connected yet.
            * ``"payload_not_hydrated"`` — no connected broker has a balance payload.
            * ``"capital_not_ready"``    — capital authority bootstrap not complete.
            * ``"nonce_lock_not_held"``  — nonce manager lacks the PID writer lock.
        """
        # ── Condition 1: connected ────────────────────────────────────────────
        connected = any(
            getattr(b, "connected", False)
            for b in self._platform_brokers.values()
        )
        if not connected:
            return False, "not_connected"

        # ── Condition 2: payload_hydrated ─────────────────────────────────────
        payload_ok = False
        for broker in self._platform_brokers.values():
            if not getattr(broker, "connected", False):
                continue
            has_payload = (
                (callable(getattr(broker, "has_balance_payload_for_capital", None))
                 and broker.has_balance_payload_for_capital())
                or (callable(getattr(broker, "has_balance_payload", None))
                    and broker.has_balance_payload())
                or getattr(broker, "_last_known_balance", None) is not None
            )
            if has_payload:
                payload_ok = True
                break
        if not payload_ok:
            return False, "payload_not_hydrated"

        # ── Condition 3: capital_ready ────────────────────────────────────────
        if not self.is_capital_authority_ready():
            return False, "capital_not_ready"

        # ── Condition 4: nonce_lock_acquired ──────────────────────────────────
        try:
            _nonce_mod = None
            for _mod_name in ("bot.global_kraken_nonce", "global_kraken_nonce"):
                try:
                    _nonce_mod = __import__(_mod_name, fromlist=["get_global_nonce_manager"])
                    break
                except ImportError:
                    continue
            if _nonce_mod is not None:
                _nmgr = _nonce_mod.get_global_nonce_manager()
                if _nmgr is not None and not getattr(_nmgr, "_pid_lock_acquired", True):
                    return False, "nonce_lock_not_held"
        except Exception:
            # Nonce module unavailable — skip this gate to avoid blocking on
            # platforms that do not use file-based nonce locking.
            pass

        return True, ""

    def all_brokers_fully_ready(self) -> bool:
        """Return ``True`` only when **every** registered platform broker is fully ready.

        A broker is fully ready when :func:`is_broker_fully_ready` returns ``True``
        for it — i.e. it is connected *and* has a hydrated balance payload.

        Returns ``False`` immediately (short-circuit) if no platform brokers are
        registered, or if any registered broker is not yet connected/hydrated.

        This helper is the class-level counterpart to the module-level
        :func:`is_broker_fully_ready` function.  Use it to gate
        :class:`~bot.capital_allocation_brain.CapitalAllocationBrain` bootstrap
        and any other component that must not run until all brokers are healthy.

        When called during an active NijaCoreLoop cycle the method checks
        ``nija_core_loop.get_current_cycle_snapshot()`` first.  If a frozen
        snapshot is available its ``mabm_brokers_ready`` field is returned
        immediately, ensuring every MABM readiness check within a single cycle
        uses the same world-view captured at cycle start.

        Falls back to the live per-broker check when no cycle snapshot is set.
        """
        # ── Fast path: use frozen cycle snapshot when available ───────────
        try:
            try:
                from nija_core_loop import get_current_cycle_snapshot as _get_snap  # type: ignore[import]
            except ImportError:
                from bot.nija_core_loop import get_current_cycle_snapshot as _get_snap  # type: ignore[import]
            _snap = _get_snap()
            if _snap is not None:
                return bool(_snap.mabm_brokers_ready)
        except Exception:
            pass

        # ── Live check (bootstrap or outside run_trading_loop) ────────────
        brokers = list(self._platform_brokers.values())
        if not brokers:
            return False
        return all(is_broker_fully_ready(b) for b in brokers)

    def get_state(self) -> dict:
        """Return a diagnostic snapshot of the aggregation pipeline state.

        This is the ``capital_aggregator.get_state()`` call described in the
        capital-pipeline diagnostic guide.  Operators can log it every cycle to
        confirm the sequential pipeline (broker fetch → CA aggregation → tier
        classification) has completed correctly.

        Returns a plain dict so it is safe to pass directly to
        ``logger.critical("AGGREGATED STATE: %s", ...)``.

        Keys
        ----
        aggregation_ready   : bool  — True when CA is hydrated AND all registered
                                      broker balances have propagated through.
        capital_authority_ready : bool  — delegates to is_capital_authority_ready().
        all_brokers_ready   : bool  — delegates to all_brokers_fully_ready().
        valid_brokers       : int   — number of brokers that contributed a balance.
        platform_brokers    : list  — broker-type values of registered platform brokers.
        bootstrap_state     : str   — current CapitalBootstrapStateMachine state.
        runtime_state       : str   — current CapitalRuntimeStateMachine state.
        """
        ca_ready = self.is_capital_authority_ready()
        all_ready = self.all_brokers_fully_ready()
        valid_brokers = int(self._capital_last_valid_brokers or 0)
        platform_broker_names = [bt.value for bt in self._platform_brokers]

        bootstrap_state = "unavailable"
        if _CAPITAL_FSM_AVAILABLE and self._capital_bootstrap_fsm is not None:
            try:
                bootstrap_state = str(self._capital_bootstrap_fsm.state.value)
            except Exception:
                pass

        runtime_state = "unavailable"
        if _CAPITAL_FSM_AVAILABLE and self._capital_runtime_fsm is not None:
            try:
                runtime_state = str(self._capital_runtime_fsm.state.value)
            except Exception:
                pass

        return {
            "aggregation_ready": ca_ready and valid_brokers > 0,
            "capital_authority_ready": ca_ready,
            "all_brokers_ready": all_ready,
            "valid_brokers": valid_brokers,
            "platform_brokers": platform_broker_names,
            "bootstrap_state": bootstrap_state,
            "runtime_state": runtime_state,
        }

    def is_trading_halted_due_to_capital(self) -> bool:
        """Return True when capital is halted.

        **Runtime FSM is the authority on halt state.**  The coordinator drives
        ``RUN_HALTED`` via ``on_snapshot_received()``; this method delegates
        to that state.  Falls back to the local bool when FSM is unavailable.
        """
        if _CAPITAL_FSM_AVAILABLE and self._capital_runtime_fsm is not None:
            return self._capital_runtime_fsm.state == CapitalRuntimeState.RUN_HALTED
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
                    # FSM is the authority on readiness — read via delegating method.
                    capital_ready = self.is_capital_authority_ready()
                    needs_refresh = not capital_ready
                    if not needs_refresh and authority is not None:
                        needs_refresh = authority.is_stale(ttl_s=self.capital_stale_timeout_s)
                    if needs_refresh:
                        # refresh_capital_authority gates on has_registered_sources
                        # internally — no duplicate guard needed here.
                        self.refresh_capital_authority(trigger=self.WATCHDOG_REFRESH_TRIGGER)
                        capital_ready = self.is_capital_authority_ready()

                    healthy_connected = any(
                        self.is_platform_connected(bt) and getattr(b, "connected", False)
                        for bt, b in self._platform_brokers.items()
                    )
                    # Runtime FSM is the authority on halt state — read via delegating method.
                    halted = self.is_trading_halted_due_to_capital()
                    if not capital_ready and not healthy_connected:
                        if not halted:
                            logger.critical(
                                "🛑 ALL platform brokers unavailable and capital not ready — HALTING trading until recovery"
                            )
                        # When FSM is unavailable, maintain the local fallback bool.
                        if not (_CAPITAL_FSM_AVAILABLE and self._capital_runtime_fsm is not None):
                            with self._capital_state_lock:
                                self._trading_halted_due_to_capital = True
                    elif capital_ready:
                        if not (_CAPITAL_FSM_AVAILABLE and self._capital_runtime_fsm is not None):
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
            target_manager = self._get_registration_target_manager(broker_type)
            if target_manager is not self:
                return target_manager.add_platform_broker(broker_type)

            # Enforce immutability: Cannot add brokers after locking
            if self._platform_brokers_locked:
                error_msg = f"❌ INVARIANT VIOLATION: Cannot add platform broker {broker_type.value} - platform brokers are locked (immutable)"
                logger.error(error_msg)
                raise RuntimeError(error_msg)
            
            # Hard-skip: broker already registered — return existing instance (idempotent)
            if broker_type in self._platform_brokers:
                logger.info(
                    "%s already registered — returning existing instance (idempotent)",
                    broker_type.value,
                )
                return self._platform_brokers[broker_type]
            
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
            self._record_broker_registration(broker_type, broker)
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

    def on_broker_ready(self, broker_id: str, balance_feed: Callable[[], Any]) -> None:
        """Deterministic broker-readiness hook — call once per broker when connected.

        This is the single authoritative hook that wires a newly-connected broker
        into :class:`~bot.capital_authority.CapitalAuthority`.  It must be called
        **exactly once** per broker, immediately after ``broker.connect()`` returns
        ``True``.

        What it does
        ------------
        1. Calls ``CapitalAuthority.register_source(broker_id, balance_feed)``
           which (a) stores the feed callable and (b) immediately seeds the
           broker's initial balance — so ``has_registered_sources()`` flips to
           ``True`` without waiting for the next coordinator cycle.

        Parameters
        ----------
        broker_id:
            Logical broker key (e.g. ``"kraken"`` or ``"alpaca"``).
        balance_feed:
            Zero-argument callable that returns the current balance for this
            broker (typically ``broker.get_account_balance``).
        """
        if get_capital_authority is None:
            logger.warning(
                "[MABM] on_broker_ready: CapitalAuthority unavailable — skipping register_source for broker=%s",
                broker_id,
            )
            return
        try:
            authority = get_capital_authority()
            authority.register_source(broker_id, balance_feed)
        except Exception as exc:
            logger.warning(
                "[MABM] on_broker_ready: register_source failed for broker=%s: %s",
                broker_id,
                exc,
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
        self._on_platform_ready(broker_type)

    def _on_platform_ready(self, broker_type: BrokerType) -> None:
        """Event-driven continuation when a platform broker becomes ready.

        This callback advances the capital bootstrap flow out of WAIT_PLATFORM
        and immediately triggers a startup refresh so execution can continue
        without waiting for a later periodic tick.
        """
        if not _CAPITAL_FSM_AVAILABLE or self._capital_bootstrap_fsm is None:
            return
        # Hard identity assertion — detect any FSM duplication at the earliest
        # possible moment.  If get_capital_bootstrap_fsm() returns a *different*
        # object than self._capital_bootstrap_fsm, two separate singleton
        # instances exist and the system is in an inconsistent state.
        _singleton_fsm = get_capital_bootstrap_fsm()
        assert id(_singleton_fsm) == id(self._capital_bootstrap_fsm), (
            f"CapitalBootstrapFSM identity mismatch: "
            f"singleton id={id(_singleton_fsm)}, "
            f"self id={id(self._capital_bootstrap_fsm)} — "
            "duplicate FSM instances detected; check import paths and __init__ ordering"
        )
        trigger = f"on_platform_ready:{broker_type.value}"
        # Advance through startup states deterministically from any cold-start
        # entry point (including BOOT_IDLE) before requesting refresh.
        self._capital_bootstrap_fsm.transition(
            CapitalBootstrapState.WAIT_PLATFORM,
            trigger,
        )
        self._capital_bootstrap_fsm.transition(
            CapitalBootstrapState.INIT_COMPLETE,
            trigger,
        )
        self._capital_bootstrap_fsm.transition(
            CapitalBootstrapState.REFRESH_REQUESTED,
            trigger,
        )
        try:
            self.refresh_capital_authority(trigger=trigger)
        except Exception as exc:
            logger.warning(
                "[MABM] on_platform_ready refresh failed for %s: %s",
                broker_type.value,
                exc,
            )

    def _any_platform_ready(self) -> bool:
        """Return True once any platform broker reaches a connected/ready state."""
        for broker_type, broker in self._platform_brokers.items():
            if self.is_platform_connected(broker_type):
                return True
            if self._broker_ready_flag(broker):
                return True
        return False

    def _wait_for_platform_ready_or_timeout(self) -> None:
        """Poll for platform readiness and recover if WAIT_PLATFORM stalls."""
        if not _CAPITAL_FSM_AVAILABLE or self._capital_bootstrap_fsm is None:
            return

        deadline = time.monotonic() + self.wait_platform_timeout_s
        while not self._any_platform_ready():
            if time.monotonic() >= deadline:
                break
            time.sleep(1.0)

        if self._any_platform_ready():
            self._capital_bootstrap_fsm.transition(
                CapitalBootstrapState.INIT_COMPLETE,
                "wait_platform_poll_ready",
            )
            self._capital_bootstrap_fsm.transition(
                CapitalBootstrapState.REFRESH_REQUESTED,
                "wait_platform_poll_ready",
            )
            return

        if self._capital_bootstrap_fsm.state == CapitalBootstrapState.WAIT_PLATFORM:
            logger.error(
                "⛔ [MABM] WAIT_PLATFORM timeout after %.1fs — forcing bootstrap continuation",
                self.wait_platform_timeout_s,
            )
            self._capital_bootstrap_fsm.force_transition(
                CapitalBootstrapState.INIT_COMPLETE,
                "wait_platform_timeout_fallback",
            )
            self._capital_bootstrap_fsm.transition(
                CapitalBootstrapState.REFRESH_REQUESTED,
                "wait_platform_timeout_fallback",
            )
            try:
                self.refresh_capital_authority(trigger="wait_platform_timeout_fallback")
            except Exception as exc:
                logger.warning(
                    "[MABM] timeout fallback refresh failed: %s",
                    exc,
                )

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

        # Reset the BrokerPayloadFSM so a reconnect attempt starts with a clean
        # probe counter rather than inheriting exhausted state from a prior
        # failed connect().  The FSM will re-probe during the next bootstrap
        # refresh loop iteration.
        payload_fsm = self._broker_payload_fsm.get(broker_type)
        if payload_fsm is not None:
            payload_fsm.reset()
            logger.debug(
                "[BrokerPayloadFSM] broker=%s reset after connection failure "
                "— probe counter cleared for reconnect",
                broker_type.value,
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

    @staticmethod
    def _normalize_balance_value(balance: Any) -> float:
        """Return the best available cash-like scalar from a broker balance payload."""
        if isinstance(balance, dict):
            for key in (
                "trading_balance",
                "available_balance",
                "available_cash",
                "cash",
                "usd",
                "usdc",
                "total_balance",
            ):
                value = balance.get(key)
                if value is not None:
                    try:
                        return float(value)
                    except (TypeError, ValueError):
                        continue
            return 0.0
        try:
            return float(balance or 0.0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _extract_position_count(positions: Any) -> int:
        """Count materially-open positions from a broker payload."""
        if positions is None:
            return 0
        if isinstance(positions, dict):
            count = 0
            for value in positions.values():
                if isinstance(value, dict):
                    size = value.get("size") or value.get("quantity") or value.get("amount") or value.get("value")
                    try:
                        if float(size or 0.0) > 0.0:
                            count += 1
                    except (TypeError, ValueError):
                        count += 1
                else:
                    count += 1
            return count
        if isinstance(positions, (list, tuple, set)):
            return len(positions)
        return 0

    def _audit_user_trading_capital(
        self,
        user_id: str,
        broker_type: BrokerType,
        broker: BaseBroker,
    ) -> Tuple[bool, Dict[str, float], str]:
        """Return whether a connected user account has enough usable capital to trade."""
        raw_balance = broker.get_account_balance()
        usable_balance = self._normalize_balance_value(raw_balance)
        total_equity = usable_balance
        position_count = 0

        portfolio = self.update_user_portfolio(user_id, broker_type)
        if portfolio is not None:
            usable_balance = float(getattr(portfolio, "available_cash", usable_balance) or usable_balance)
            total_equity = float(getattr(portfolio, "total_equity", usable_balance) or usable_balance)
            position_count = int(getattr(portfolio, "position_count", 0) or 0)

        if position_count == 0 and hasattr(broker, "get_positions"):
            try:
                position_count = self._extract_position_count(broker.get_positions())
            except Exception:
                position_count = 0

        locked_capital = max(0.0, total_equity - usable_balance)
        exchange_minimum = float(MIN_CASH_TO_BUY)

        reasons: List[str] = []
        if usable_balance < exchange_minimum:
            reasons.append(
                f"usable ${usable_balance:.2f} below exchange minimum ${exchange_minimum:.2f}"
            )
        if usable_balance < ACCOUNT_USABLE_BALANCE_MIN:
            reasons.append(
                f"usable ${usable_balance:.2f} below required trading floor ${ACCOUNT_USABLE_BALANCE_MIN:.2f}"
            )
        if locked_capital > 0.0 and usable_balance < ACCOUNT_USABLE_BALANCE_MIN:
            reasons.append(
                f"${locked_capital:.2f} locked in {position_count} open position(s)"
            )

        diagnostics = {
            "usable_balance": usable_balance,
            "total_equity": total_equity,
            "locked_capital": locked_capital,
            "position_count": float(position_count),
            "exchange_minimum": exchange_minimum,
            "required_minimum": ACCOUNT_USABLE_BALANCE_MIN,
            "recommended_minimum": ACCOUNT_USABLE_BALANCE_RECOMMENDED,
        }
        return not reasons, diagnostics, "; ".join(reasons)

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
                    logger.info(f"   ✅ {user.name} connected to {broker_type.value.title()}")

                    try:
                        is_tradable, capital_diag, capital_reason = self._audit_user_trading_capital(
                            user.user_id,
                            broker_type,
                            broker,
                        )
                        if is_tradable:
                            if broker_type.value not in connected_users:
                                connected_users[broker_type.value] = []
                            connected_users[broker_type.value].append(user.user_id)
                            self._user_metadata[user.user_id]['brokers'][broker_type] = True
                            self._capital_blocked_users.pop(connection_key, None)
                            logger.info(
                                "   💰 %s usable balance: $%.2f (equity=$%.2f, positions=%d)",
                                user.name,
                                capital_diag['usable_balance'],
                                capital_diag['total_equity'],
                                int(capital_diag['position_count']),
                            )
                            if capital_diag['usable_balance'] < capital_diag['recommended_minimum']:
                                logger.warning(
                                    "   ⚠️  %s is tradable but under recommended usable cash ($%.2f < $%.2f)",
                                    user.name,
                                    capital_diag['usable_balance'],
                                    capital_diag['recommended_minimum'],
                                )
                        else:
                            self._user_metadata[user.user_id]['brokers'][broker_type] = False
                            self._capital_blocked_users[connection_key] = capital_reason
                            logger.error(
                                "   ⛔ CAPITAL BLOCKED: %s (%s) not eligible for new trades",
                                user.name,
                                broker_type.value.title(),
                            )
                            logger.error("      Reason: %s", capital_reason)
                            logger.error(
                                "      Usable=$%.2f Equity=$%.2f Locked=$%.2f Positions=%d ExchangeMin=$%.2f Required=$%.2f",
                                capital_diag['usable_balance'],
                                capital_diag['total_equity'],
                                capital_diag['locked_capital'],
                                int(capital_diag['position_count']),
                                capital_diag['exchange_minimum'],
                                capital_diag['required_minimum'],
                            )
                    except Exception as bal_err:
                        self._user_metadata[user.user_id]['brokers'][broker_type] = False
                        self._capital_blocked_users[connection_key] = f"capital_audit_failed: {bal_err}"
                        logger.warning(f"   ⚠️  Could not audit trading capital for {user.name}: {bal_err}")
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
            if self._capital_blocked_users:
                logger.warning(
                    "   ⛔ %d connected account(s) blocked from new trades due to insufficient usable capital",
                    len(self._capital_blocked_users),
                )
        else:
            # Check if there are users without credentials vs actual failures
            total_without_creds = len(self._users_without_credentials)
            total_failed = len(self._failed_user_connections)
            total_capital_blocked = len(self._capital_blocked_users)

            if total_without_creds > 0 and total_failed == 0 and total_capital_blocked == 0:
                # Only users without credentials - this is informational
                logger.info(f"   ⚪ No users connected ({total_without_creds} user(s) have no credentials configured)")
                logger.info("   User accounts are optional. To enable, configure API credentials in environment variables.")
            elif total_capital_blocked > 0 and total_failed == 0:
                logger.warning(
                    "   ⛔ No users eligible for new trades (%d account(s) blocked by capital checks, %d without credentials)",
                    total_capital_blocked,
                    total_without_creds,
                )
            elif total_failed > 0:
                # Some actual connection failures
                logger.warning(
                    f"   ⚠️  No users connected ({total_failed} connection failure(s), {total_without_creds} without credentials, {total_capital_blocked} capital-blocked)"
                )
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

            # Register the broker object first so startup capital-refresh loops
            # can deterministically observe a non-empty source registry even
            # while connect() is still in flight.
            self.register_platform_broker_instance(
                broker_type,
                broker,
                mark_connected_state=False,
            )
            self.begin_platform_connection(broker_type)
            try:
                connected = broker.connect()
            except Exception as exc:
                logger.error("❌ Platform %s connect() raised: %s", key.upper(), exc)
                connected = False

            # ── Sync BrokerPayloadFSM immediately after connect() ──────────────
            # If connect() successfully seeded _last_known_balance, advance the
            # FSM to PAYLOAD_READY so the bootstrap resolver does not need to
            # wait for a probe round-trip.  If connect() failed or did not seed
            # the balance, the FSM stays in REGISTERED — the probing loop inside
            # refresh_capital_authority will converge it to PAYLOAD_READY or
            # EXHAUSTED with a bounded number of attempts.
            _payload_fsm = self._broker_payload_fsm.get(broker_type)
            if _payload_fsm is not None:
                if getattr(broker, "_last_known_balance", None) is not None:
                    _payload_fsm.mark_payload_ready()
                    logger.info(
                        "[BrokerPayloadFSM] broker=%s PAYLOAD_READY "
                        "(connect() seeded balance=%.2f)",
                        broker_type.value,
                        float(getattr(broker, "_last_known_balance", 0.0)),
                    )
                elif not connected:
                    # connect() failed — reset so reconnect attempts get a full
                    # probe budget rather than continuing from a prior counter.
                    _payload_fsm.reset()

            if connected:
                # Broker-readiness hook: register the balance feed with CapitalAuthority
                # exactly once, immediately after connect() succeeds.  This is the single
                # deterministic seeding point required by the capital-authority contract.
                # All platform broker implementations expose get_account_balance() per the
                # BaseBroker contract defined in broker_integration.py.
                try:
                    self.on_broker_ready(key, broker.get_account_balance)
                except Exception as _exc:
                    logger.warning("[MABM] on_broker_ready call failed for %s: %s", key, _exc)
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
                    logger.warning(
                        "   ⏳ Platform %s connected but capital not ready yet "
                        "(valid_brokers=%d total=$%.2f) — waiting for re-evaluation",
                        key.upper(),
                        int(_cap.get("valid_brokers", 0.0)),
                        float(_cap.get("total_capital", 0.0)),
                    )
            else:
                self.mark_platform_failed(broker_type)
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
        # 1) brokers connect, 2) registration gate lifted, 3) balances fetched,
        # 4) CapitalAuthority built, 5) readiness marked, 6) trading engines may proceed.
        #
        # CRITICAL: finalize_broker_registration() MUST be called before
        # enforce_trading_bootstrap_contract() to break the Gate B dependency cycle:
        #
        #   refresh_capital_authority() has a pre-flight Gate B that blocks ALL
        #   refresh paths (including the bootstrap seed) until finalize_broker_registration()
        #   has been called.  But finalize_broker_registration() is only called from
        #   INSIDE the bootstrap seed block — which Gate B prevents from running.
        #
        #   Without this explicit call the cycle is:
        #     enforce_trading_bootstrap_contract()
        #       → refresh_capital_authority()
        #         → Gate B: has_attempted_connections() == False → return pending
        #             ← finalize_broker_registration() never fires
        #             ← CA never hydrates
        #             ← CapitalAllocationBrain.__init__() blocks on CAPITAL_HYDRATED_EVENT
        #             ← timeout → $0 capital → trading halted
        #
        #   This call is idempotent: if trading_strategy.py already called it via
        #   finalize_broker_registration() the second invocation is a no-op.
        self.finalize_broker_registration()
        self._wait_for_platform_ready_or_timeout()
        _startup_cap = self.enforce_trading_bootstrap_contract(
            max_attempts=3,
            retry_delay_s=1.0,
        )
        if (
            not bool(_startup_cap.get("ready", 0.0))
            and _CAPITAL_FSM_AVAILABLE
            and self._capital_bootstrap_fsm is not None
            and self._capital_bootstrap_fsm.state != CapitalBootstrapState.WAIT_PLATFORM
        ):
            # Forced WAIT_PLATFORM recovery may have just fired; run one more
            # contract pass so startup can observe the new state immediately.
            _startup_cap = self.enforce_trading_bootstrap_contract(
                max_attempts=1,
                retry_delay_s=0.0,
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


# Global singleton guard + accessor (hard containment for registry integrity)
_manager: Optional[MultiAccountBrokerManager] = None
_manager_lock: threading.RLock = threading.RLock()
_manager_init_in_progress: bool = False


def get_broker_manager() -> MultiAccountBrokerManager:
    """Return the process-wide MultiAccountBrokerManager singleton.

    Uses an RLock with a re-entrancy sentinel so that any recursive call
    originating from inside the MultiAccountBrokerManager constructor raises
    an explicit RuntimeError instead of deadlocking or silently creating a
    second instance.
    """
    global _manager, _manager_init_in_progress

    with _manager_lock:
        if _manager is not None:
            return _manager

        if _manager_init_in_progress:
            raise RuntimeError(
                "Recursive/re-entrant broker manager initialization detected"
            )

        _manager_init_in_progress = True

        try:
            _manager = MultiAccountBrokerManager()
            logger.debug("[MABM] singleton created (id=%d)", id(_manager))
            return _manager
        finally:
            _manager_init_in_progress = False


def reset_broker_manager_singleton() -> None:
    """Clear the cached MultiAccountBrokerManager singleton (cold-start helper)."""
    global _manager
    with _manager_lock:
        _manager = None
    logger.warning("MultiAccountBrokerManager singleton cache cleared")


# Backward-compatible module export
multi_account_broker_manager = get_broker_manager()
