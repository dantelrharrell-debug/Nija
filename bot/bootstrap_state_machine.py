"""NIJA Composite Bootstrap State Machine
=========================================

Single source of truth for the entire NIJA system bootstrap sequence.

Maps the entire startup flow into a deterministic finite state machine with
explicit invariants and legally-allowed transitions.  Every component action
that advances the boot sequence must call :meth:`BootstrapStateMachine.transition`;
illegal transitions are rejected and logged instead of propagating as silent
side-effects.

States (17 total)
-----------------
  BOOT_INIT              – initial state when the process starts
  LOCK_ACQUIRED          – process/distributed writer lock held
  HEALTH_BOUND           – HTTP health server bound and accepting connections
  ENV_VERIFIED           – environment variables checked; ≥1 credential present
  STARTUP_VALIDATED      – startup_validation.py passed all pre-flight checks
  MODE_GATED             – trading state machine confirmed a legal mode
  PLATFORM_CONNECTING    – platform broker connection(s) in progress
  PLATFORM_READY         – at least one platform broker connected
    BALANCE_HYDRATED       – startup balance sync completed (authoritative)
  CAPITAL_REFRESHING     – capital authority refresh in progress
  CAPITAL_READY          – capital > 0 confirmed; trading gate open
  INIT_COMPLETE          – all initialization locked; execution logic ready
  THREADS_STARTING       – trading worker threads being spawned
  RUNNING_SUPERVISED     – trading threads live; supervisor loop active (resumable)
  CONFIG_ERROR_KEEPALIVE – no exchange credentials; process alive for monitoring
  BOOT_FAILED_RETRY      – transient failure; retry from PLATFORM_CONNECTING
  EXTERNAL_RESTART_REQUIRED – fatal condition; only clean process restart resolves
  SHUTDOWN               – process exiting gracefully (terminal)

Allowed transitions
-------------------
  BOOT_INIT              → LOCK_ACQUIRED
  LOCK_ACQUIRED          → HEALTH_BOUND
  HEALTH_BOUND           → ENV_VERIFIED
  ENV_VERIFIED           → STARTUP_VALIDATED | CONFIG_ERROR_KEEPALIVE
  STARTUP_VALIDATED      → MODE_GATED | BOOT_FAILED_RETRY
  MODE_GATED             → PLATFORM_CONNECTING
    PLATFORM_CONNECTING    → PLATFORM_READY | BOOT_FAILED_RETRY | EXTERNAL_RESTART_REQUIRED
    PLATFORM_READY         → BALANCE_HYDRATED | BOOT_FAILED_RETRY
    BALANCE_HYDRATED       → CAPITAL_REFRESHING | BOOT_FAILED_RETRY
  CAPITAL_REFRESHING     → CAPITAL_READY | BOOT_FAILED_RETRY
  CAPITAL_READY          → INIT_COMPLETE
  INIT_COMPLETE          → THREADS_STARTING
  THREADS_STARTING       → RUNNING_SUPERVISED | BOOT_FAILED_RETRY
  RUNNING_SUPERVISED     → BOOT_FAILED_RETRY | EXTERNAL_RESTART_REQUIRED | SHUTDOWN
  BOOT_FAILED_RETRY      → PLATFORM_CONNECTING | EXTERNAL_RESTART_REQUIRED
  CONFIG_ERROR_KEEPALIVE → SHUTDOWN
  EXTERNAL_RESTART_REQUIRED → SHUTDOWN
  SHUTDOWN               → (none — terminal)

Global invariants
-----------------
  I1  Single-writer          process lock must be held (state ≥ LOCK_ACQUIRED)
                             before any broker initialisation.
  I2  Liveness-first         health server must be bound (state ≥ HEALTH_BOUND)
                             before any blocking startup I/O.
  I3  Platform-first         user Kraken activity is illegal unless
                             KrakenStartupFSM is CONNECTED or FAILED.
  I4  Capital gate           trading thread start is illegal unless capital
                             bootstrap FSM is READY and capital > 0.
  I5  Readiness gate         trading loops are illegal before
                             StartupReadinessGate is open.
  I6  Mode safety            real order placement is illegal unless
                             TradingStateMachine is LIVE_ACTIVE.
  I7  Emergency safety       EMERGENCY_STOP mode blocks all activity except
                             the reset-to-OFF path.
  I8  Supervisor ownership   worker-thread restarts are only legal in the
                             RUNNING_SUPERVISED state.
  I9  Fail-closed nonce      fatal nonce RuntimeErrors must force
                             EXTERNAL_RESTART_REQUIRED.
  I10 Capital writer         only CapitalRefreshCoordinator (WRITER_ID) may
                             publish capital snapshots.
  I11 Strategy arm           strategy engine arming is illegal before
                             BootstrapStateMachine reaches CAPITAL_READY or INIT_COMPLETE.
  I12 Capital hydration      CAPITAL_READY is illegal unless the CSM-v2 capital
                             pipeline has run at least once (is_hydrated=True);
                             enforced synchronously in advance_to_capital_ready().
"""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.bootstrap_fsm")

# ---------------------------------------------------------------------------
# Capital writer constant — mirrors capital_flow_state_machine.WRITER_ID
# ---------------------------------------------------------------------------
_CAPITAL_WRITER_ID: str = "mabm_capital_refresh_coordinator"

# ---------------------------------------------------------------------------
# State enumeration
# ---------------------------------------------------------------------------


class BootstrapState(str, Enum):
    """Top-level bootstrap states for the composite NIJA system FSM."""

    BOOT_INIT = "BOOT_INIT"
    LOCK_ACQUIRED = "LOCK_ACQUIRED"
    HEALTH_BOUND = "HEALTH_BOUND"
    ENV_VERIFIED = "ENV_VERIFIED"
    STARTUP_VALIDATED = "STARTUP_VALIDATED"
    MODE_GATED = "MODE_GATED"
    PLATFORM_CONNECTING = "PLATFORM_CONNECTING"
    PLATFORM_READY = "PLATFORM_READY"
    BALANCE_HYDRATED = "BALANCE_HYDRATED"
    CAPITAL_REFRESHING = "CAPITAL_REFRESHING"
    CAPITAL_READY = "CAPITAL_READY"
    INIT_COMPLETE = "INIT_COMPLETE"
    THREADS_STARTING = "THREADS_STARTING"
    RUNNING_SUPERVISED = "RUNNING_SUPERVISED"
    CONFIG_ERROR_KEEPALIVE = "CONFIG_ERROR_KEEPALIVE"
    BOOT_FAILED_RETRY = "BOOT_FAILED_RETRY"
    EXTERNAL_RESTART_REQUIRED = "EXTERNAL_RESTART_REQUIRED"
    SHUTDOWN = "SHUTDOWN"


# ---------------------------------------------------------------------------
# Strategy-arm gate — states from which engine arming is permitted (I11)
# ---------------------------------------------------------------------------
_STRATEGY_ARM_ALLOWED_STATES = frozenset({
    BootstrapState.CAPITAL_READY,
    BootstrapState.INIT_COMPLETE,
    BootstrapState.THREADS_STARTING,
    BootstrapState.RUNNING_SUPERVISED,
})

# ---------------------------------------------------------------------------
# Emergency / terminal states that any thread may drive (FIX 4 — ownership)
# ---------------------------------------------------------------------------
# The bootstrap kernel (BotStartup thread) owns all non-terminal transitions.
# EXTERNAL_RESTART_REQUIRED and SHUTDOWN represent irreversible emergency
# conditions that the supervisor loop or signal handlers may also trigger.
_ANY_THREAD_ALLOWED_TARGETS = frozenset({
    BootstrapState.EXTERNAL_RESTART_REQUIRED,
    BootstrapState.SHUTDOWN,
})


# ---------------------------------------------------------------------------
# Transition table — the only legal moves
# ---------------------------------------------------------------------------
_VALID_TRANSITIONS: Dict[BootstrapState, List[BootstrapState]] = {
    BootstrapState.BOOT_INIT: [
        BootstrapState.LOCK_ACQUIRED,
    ],
    BootstrapState.LOCK_ACQUIRED: [
        BootstrapState.HEALTH_BOUND,
    ],
    BootstrapState.HEALTH_BOUND: [
        BootstrapState.ENV_VERIFIED,
    ],
    BootstrapState.ENV_VERIFIED: [
        BootstrapState.STARTUP_VALIDATED,
        BootstrapState.CONFIG_ERROR_KEEPALIVE,
    ],
    BootstrapState.STARTUP_VALIDATED: [
        BootstrapState.MODE_GATED,
        BootstrapState.BOOT_FAILED_RETRY,
    ],
    BootstrapState.MODE_GATED: [
        BootstrapState.PLATFORM_CONNECTING,
    ],
    BootstrapState.PLATFORM_CONNECTING: [
        BootstrapState.PLATFORM_READY,
        BootstrapState.BOOT_FAILED_RETRY,
        BootstrapState.EXTERNAL_RESTART_REQUIRED,
    ],
    BootstrapState.PLATFORM_READY: [
        BootstrapState.BALANCE_HYDRATED,
        BootstrapState.BOOT_FAILED_RETRY,
    ],
    BootstrapState.BALANCE_HYDRATED: [
        BootstrapState.CAPITAL_REFRESHING,
        BootstrapState.BOOT_FAILED_RETRY,
    ],
    BootstrapState.CAPITAL_REFRESHING: [
        BootstrapState.CAPITAL_READY,
        BootstrapState.BOOT_FAILED_RETRY,
    ],
    BootstrapState.CAPITAL_READY: [
        BootstrapState.INIT_COMPLETE,
        BootstrapState.BOOT_FAILED_RETRY,
    ],
    BootstrapState.INIT_COMPLETE: [
        BootstrapState.THREADS_STARTING,
        BootstrapState.BOOT_FAILED_RETRY,
    ],
    BootstrapState.THREADS_STARTING: [
        BootstrapState.RUNNING_SUPERVISED,
        BootstrapState.BOOT_FAILED_RETRY,
    ],
    BootstrapState.RUNNING_SUPERVISED: [
        BootstrapState.BOOT_FAILED_RETRY,
        BootstrapState.EXTERNAL_RESTART_REQUIRED,
        BootstrapState.SHUTDOWN,
    ],
    BootstrapState.BOOT_FAILED_RETRY: [
        BootstrapState.PLATFORM_CONNECTING,
        BootstrapState.EXTERNAL_RESTART_REQUIRED,
    ],
    BootstrapState.CONFIG_ERROR_KEEPALIVE: [
        BootstrapState.SHUTDOWN,
    ],
    BootstrapState.EXTERNAL_RESTART_REQUIRED: [
        BootstrapState.SHUTDOWN,
    ],
    BootstrapState.SHUTDOWN: [],  # terminal — no further transitions
}

# ---------------------------------------------------------------------------
# Happy-path chain to CAPITAL_READY (used by advance_to_capital_ready)
# ---------------------------------------------------------------------------
# Ordered list of every state that must be visited, in sequence, to walk the
# happy-path from BOOT_INIT to CAPITAL_READY.  advance_to_capital_ready()
# iterates this list and calls transition() for each entry; states that are
# already behind the current position return False and are silently skipped.
_HAPPY_PATH_TO_CAPITAL_READY: List[BootstrapState] = [
    BootstrapState.LOCK_ACQUIRED,
    BootstrapState.HEALTH_BOUND,
    BootstrapState.ENV_VERIFIED,
    BootstrapState.STARTUP_VALIDATED,
    BootstrapState.MODE_GATED,
    BootstrapState.PLATFORM_CONNECTING,
    BootstrapState.PLATFORM_READY,
    BootstrapState.BALANCE_HYDRATED,
    BootstrapState.CAPITAL_REFRESHING,
    BootstrapState.CAPITAL_READY,
    BootstrapState.INIT_COMPLETE,
]

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class BootstrapInvariantError(RuntimeError):
    """Raised when a global boot invariant is violated."""

    def __init__(self, invariant_id: str, message: str) -> None:
        super().__init__(f"[{invariant_id}] {message}")
        self.invariant_id = invariant_id


# ---------------------------------------------------------------------------
# Composite Bootstrap State Machine
# ---------------------------------------------------------------------------


class BootstrapStateMachine:
    """
    Composite Bootstrap State Machine — single source of truth for NIJA's
    system boot sequence.

    Thread-safe via a single ``threading.Lock``.  Every transition is recorded
    in an in-memory audit trail with wall-clock timestamps.

    Sub-machines referenced by invariant checks are imported lazily so this
    module never creates circular import cycles at load time.
    """

    _created: bool = False
    _created_lock = threading.Lock()

    def __init__(self) -> None:
        with self._created_lock:
            if self.__class__._created:
                raise RuntimeError("BootstrapFSM already exists")
            self.__class__._created = True
        self._state: BootstrapState = BootstrapState.BOOT_INIT
        self._lock = threading.Lock()
        self._history: List[Dict[str, Any]] = []
        self._boot_complete: bool = False
        self._execution_authority: bool = False
        # Single-owner kernel: only the designated thread may drive transitions.
        # None until claim_bootstrap_ownership() is called.
        self._owner_thread_id: Optional[int] = None

    # ------------------------------------------------------------------
    # State access
    # ------------------------------------------------------------------

    @property
    def state(self) -> BootstrapState:
        """Current bootstrap state (thread-safe, non-blocking)."""
        with self._lock:
            return self._state

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return the most recent *limit* transition records."""
        with self._lock:
            return list(self._history[-limit:])

    def get_status(self) -> Dict[str, Any]:
        """Serialisable snapshot suitable for a /status health endpoint."""
        with self._lock:
            return {
                "state": self._state.value,
                "boot_complete": self._boot_complete,
                "execution_authority": self._execution_authority,
                "history": list(self._history[-10:]),
                "owner_thread_id": self._owner_thread_id,
            }

    @property
    def boot_complete(self) -> bool:
        """True once bootstrap is finalized for runtime execution."""
        with self._lock:
            return self._boot_complete

    @property
    def execution_authority(self) -> bool:
        """True when runtime order execution is authorized by bootstrap."""
        with self._lock:
            return self._execution_authority

    def has_execution_authority(self) -> bool:
        """Compatibility helper used by execution gates."""
        return self.execution_authority

    # ------------------------------------------------------------------
    # Single-owner bootstrap kernel
    # ------------------------------------------------------------------

    def claim_bootstrap_ownership(self) -> None:
        """Designate the calling thread as the sole owner of bootstrap transitions.

        The single-owner kernel invariant: exactly one thread drives the bootstrap
        DAG forward.  Any other thread that calls :meth:`transition` while an
        owner is registered is rejected for non-terminal transitions and logged
        as an ownership violation.  This keeps bootstrap progression deterministic
        under a single authority while still allowing emergency terminal transitions
        (EXTERNAL_RESTART_REQUIRED / SHUTDOWN) from other threads.

        Idempotent: safe to call multiple times from the same thread.
        """
        caller_id = threading.get_ident()
        with self._lock:
            prev_owner = self._owner_thread_id
            self._owner_thread_id = caller_id
        if prev_owner != caller_id:
            logger.info(
                "🔑 [BootstrapFSM] Bootstrap ownership claimed by thread %d (%s)",
                caller_id,
                threading.current_thread().name,
            )

    # ------------------------------------------------------------------
    # Transition
    # ------------------------------------------------------------------

    def transition(
        self,
        new_state: BootstrapState,
        reason: str = "",
        *,
        raise_on_invalid: bool = False,
    ) -> bool:
        """
        Attempt a transition to *new_state*.

        Parameters
        ----------
        new_state:
            Target state.
        reason:
            Human-readable description of why this transition is happening.
        raise_on_invalid:
            If ``True``, raise :class:`BootstrapInvariantError` on an illegal
            transition instead of returning ``False``.  Defaults to ``False``
            so the FSM never crashes the boot process.

        Returns
        -------
        bool
            ``True`` if the transition was applied; ``False`` if illegal.
        """
        with self._lock:
            # Single-owner enforcement (FIX 4 — unify bootstrap ownership):
            # Non-terminal transitions may only be driven by the registered bootstrap
            # kernel thread (BotStartup).  Terminal transitions (EXTERNAL_RESTART_REQUIRED,
            # SHUTDOWN) are also permitted from the supervisor loop and signal handlers
            # so emergency shutdown is never blocked by an ownership mismatch.
            _caller_id = threading.get_ident()
            if (
                self._owner_thread_id is not None
                and _caller_id != self._owner_thread_id
                and new_state not in _ANY_THREAD_ALLOWED_TARGETS
            ):
                msg = (
                    f"Non-owner thread {_caller_id} ({threading.current_thread().name})"
                    f" attempted non-terminal transition → {new_state.value if hasattr(new_state, 'value') else new_state}"
                    f" (bootstrap owner={self._owner_thread_id})."
                    " Supervisor threads must be observer-only."
                    " This transition is REJECTED to enforce single-owner boot contract."
                )
                logger.error("❌ [BootstrapFSM] OWNERSHIP VIOLATION: %s", msg)
                if raise_on_invalid:
                    raise BootstrapInvariantError("FSM_OWNERSHIP", msg)
                return False

            current = self._state
            allowed = _VALID_TRANSITIONS.get(current, [])
            if new_state not in allowed:
                msg = (
                    f"Illegal transition {current.value} → {new_state.value} "
                    f"(reason={reason!r}). "
                    f"Allowed from {current.value}: "
                    f"{[s.value for s in allowed]}"
                )
                logger.error("❌ [BootstrapFSM] %s", msg)
                if raise_on_invalid:
                    raise BootstrapInvariantError("FSM_TRANSITION", msg)
                return False

            record: Dict[str, Any] = {
                "from": current.value,
                "to": new_state.value,
                "reason": reason or "—",
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            self._history.append(record)
            self._state = new_state
            if new_state == BootstrapState.RUNNING_SUPERVISED:
                self._boot_complete = True
                self._execution_authority = True
                # Runtime supervision is active; release strict bootstrap ownership.
                self._owner_thread_id = None
            elif new_state in {
                BootstrapState.BOOT_INIT,
                BootstrapState.BOOT_FAILED_RETRY,
                BootstrapState.EXTERNAL_RESTART_REQUIRED,
                BootstrapState.SHUTDOWN,
            }:
                self._boot_complete = False
                self._execution_authority = False

        logger.info(
            "🔄 [BootstrapFSM] %s → %s  reason=%s",
            current.value,
            new_state.value,
            reason or "—",
        )
        return True

    def reset_for_retry(self, reason: str = "retry") -> None:
        """
        Force state to :attr:`~BootstrapState.BOOT_FAILED_RETRY` from any
        non-terminal state so a new boot attempt can begin.

        No-op when already in SHUTDOWN or EXTERNAL_RESTART_REQUIRED (those
        states cannot be walked back).
        """
        with self._lock:
            current = self._state
            if current in (
                BootstrapState.SHUTDOWN,
                BootstrapState.EXTERNAL_RESTART_REQUIRED,
            ):
                logger.warning(
                    "[BootstrapFSM] reset_for_retry called from terminal state %s — ignored",
                    current.value,
                )
                return
            record: Dict[str, Any] = {
                "from": current.value,
                "to": BootstrapState.BOOT_FAILED_RETRY.value,
                "reason": f"reset_for_retry: {reason}",
                "ts": datetime.now(timezone.utc).isoformat(),
            }
            self._history.append(record)
            self._state = BootstrapState.BOOT_FAILED_RETRY

        logger.warning(
            "⚠️  [BootstrapFSM] reset_for_retry: %s → BOOT_FAILED_RETRY  reason=%s",
            current.value,
            reason,
        )

    def finalize_boot(self, reason: str = "runtime handoff") -> bool:
        """Force runtime bootstrap completion and grant execution authority.

        This is a deterministic handoff helper used when startup validation has
        completed and the runtime core loop is being launched.
        """
        with self._lock:
            _pre_env_states = {
                BootstrapState.BOOT_INIT,
                BootstrapState.LOCK_ACQUIRED,
                BootstrapState.HEALTH_BOUND,
            }
            if self._state in _pre_env_states:
                logger.error(
                    "❌ [BootstrapFSM] finalize_boot blocked: state=%s is before ENV_VERIFIED",
                    self._state.value,
                )
                return False

            if self._state in {
                BootstrapState.EXTERNAL_RESTART_REQUIRED,
                BootstrapState.SHUTDOWN,
            }:
                logger.error(
                    "❌ [BootstrapFSM] finalize_boot blocked: terminal state=%s",
                    self._state.value,
                )
                return False

            _from_state = self._state
            if self._state != BootstrapState.RUNNING_SUPERVISED:
                self._state = BootstrapState.RUNNING_SUPERVISED
                self._history.append(
                    {
                        "from": _from_state.value,
                        "to": BootstrapState.RUNNING_SUPERVISED.value,
                        "reason": f"finalize_boot: {reason}",
                        "ts": datetime.now(timezone.utc).isoformat(),
                    }
                )

            self._boot_complete = True
            self._execution_authority = True
            # Release bootstrap-thread ownership lock after successful handoff.
            self._owner_thread_id = None

        logger.critical(
            "✅ [BootstrapFSM] finalize_boot complete: state=%s boot_complete=%s execution_authority=%s",
            self.state.value,
            self.boot_complete,
            self.execution_authority,
        )
        return True

    def force_start(self, reason: str = "manual force start") -> bool:
        """Compatibility alias for minimal unblock workflows.

        Runs the same deterministic runtime handoff as finalize_boot().
        """
        return self.finalize_boot(reason=reason)

    # ------------------------------------------------------------------
    # Convenience: fast-forward to CAPITAL_READY
    # ------------------------------------------------------------------

    def advance_to_capital_ready(self, reason: str = "capital_confirmed") -> bool:
        """
        Fast-forward through all prerequisite happy-path states to
        :attr:`BootstrapState.CAPITAL_READY`.

        This method is the **Option A trigger**: it is called by
        :class:`MultiAccountBrokerManager` via a
        :meth:`~capital_flow_state_machine.CapitalBootstrapStateMachine.register_on_ready`
        callback the moment the capital pipeline emits ``CAPITAL_READY`` and
        the capital FSM reaches ``READY``.  After it returns, every call to
        :meth:`assert_invariant_i11_strategy_arm` will pass, unblocking
        ``TradingStrategy._init_advanced_features()`` and the trading loop.

        Algorithm
        ---------
        Iterates :data:`_HAPPY_PATH_TO_CAPITAL_READY` in order and calls
        :meth:`transition` for each step.  Steps that are already behind the
        FSM's current position silently return ``False`` and are skipped;
        steps that match the current allowed transition advance the FSM.
        This is safe to call from any pre-capital happy-path state.

        Returns
        -------
        bool
            ``True`` if the FSM is now in ``CAPITAL_READY``,
            ``THREADS_STARTING``, or ``RUNNING_SUPERVISED``
            (i.e. :attr:`assert_invariant_i11_strategy_arm` will pass).
            ``False`` if the FSM is in a terminal error state and cannot
            advance.
        """
        if self.state in _STRATEGY_ARM_ALLOWED_STATES:
            return True  # already at CAPITAL_READY or later

        _error_states = {
            BootstrapState.BOOT_FAILED_RETRY,
            BootstrapState.EXTERNAL_RESTART_REQUIRED,
            BootstrapState.CONFIG_ERROR_KEEPALIVE,
            BootstrapState.SHUTDOWN,
        }
        if self.state in _error_states:
            logger.warning(
                "[BootstrapFSM] advance_to_capital_ready: FSM is in error/terminal "
                "state %s — cannot advance to CAPITAL_READY",
                self.state.value,
            )
            return False

        # I12 — enforce the capital hydration barrier BEFORE declaring CAPITAL_READY.
        # This guarantees the CSM-v2 pipeline has run at least once and the
        # "balance is $0" is never confused with "balance is unknown".
        try:
            self.assert_invariant_i12_capital_hydration(timeout=5.0)
        except BootstrapInvariantError as _i12_err:
            logger.error(
                "❌ [BootstrapFSM] advance_to_capital_ready: I12 hydration barrier failed: %s",
                _i12_err,
            )
            return False

        for target in _HAPPY_PATH_TO_CAPITAL_READY:
            if self.state in _STRATEGY_ARM_ALLOWED_STATES:
                break
            self.transition(target, reason)

        reached = self.state in _STRATEGY_ARM_ALLOWED_STATES
        if reached:
            logger.info(
                "✅ [BootstrapFSM] advance_to_capital_ready: FSM is now %s (reason=%s)",
                self.state.value,
                reason,
            )
        else:
            logger.error(
                "❌ [BootstrapFSM] advance_to_capital_ready: ended at %s, not CAPITAL_READY "
                "(reason=%s) — strategy arming may still be blocked",
                self.state.value,
                reason,
            )
        return reached

    # ------------------------------------------------------------------
    # Invariant assertions
    # ------------------------------------------------------------------

    def assert_invariant_i1_single_writer(self) -> None:
        """I1 — process lock must be held before any broker initialisation."""
        state = self.state
        if state == BootstrapState.BOOT_INIT:
            raise BootstrapInvariantError(
                "I1_SINGLE_WRITER",
                f"Broker initialisation attempted before process lock acquired "
                f"(state={state.value}). Acquire the process lock first.",
            )

    def assert_invariant_i2_liveness_first(self) -> None:
        """I2 — health server must be bound before any blocking I/O."""
        state = self.state
        _pre_health = {BootstrapState.BOOT_INIT, BootstrapState.LOCK_ACQUIRED}
        if state in _pre_health:
            raise BootstrapInvariantError(
                "I2_LIVENESS_FIRST",
                f"Blocking startup I/O attempted before health server is bound "
                f"(state={state.value}). Start the health server first.",
            )

    def assert_invariant_i3_platform_first(self) -> None:
        """I3 — user Kraken activity illegal unless platform FSM is CONNECTED or FAILED."""
        try:
            from bot.broker_manager import _KRAKEN_STARTUP_FSM
        except ImportError:
            try:
                from broker_manager import _KRAKEN_STARTUP_FSM  # type: ignore[import]
            except ImportError:
                logger.debug("[BootstrapFSM] I3: KrakenStartupFSM unavailable — skipping check")
                return
        if not (_KRAKEN_STARTUP_FSM.is_connected or _KRAKEN_STARTUP_FSM.is_failed):
            raise BootstrapInvariantError(
                "I3_PLATFORM_FIRST",
                "User Kraken activity attempted before platform Kraken FSM reached "
                "CONNECTED or FAILED state. Wait for the platform boot to complete.",
            )

    def assert_invariant_i4_capital_gate(self) -> None:
        """I4 — trading threads illegal until capital bootstrap is READY."""
        try:
            from bot.capital_flow_state_machine import get_capital_bootstrap_fsm
        except ImportError:
            try:
                from capital_flow_state_machine import get_capital_bootstrap_fsm  # type: ignore[import]
            except ImportError:
                logger.debug("[BootstrapFSM] I4: CapitalBootstrapFSM unavailable — skipping check")
                return
        boot_fsm = get_capital_bootstrap_fsm()
        if not boot_fsm.is_ready:
            raise BootstrapInvariantError(
                "I4_CAPITAL_GATE",
                f"Trading threads requested but capital bootstrap FSM is not READY "
                f"(state={boot_fsm.state.value}). Wait for the capital refresh.",
            )

    def assert_invariant_i5_readiness_gate(self) -> None:
        """I5 — trading loops illegal before StartupReadinessGate is open."""
        try:
            from bot.startup_readiness_gate import get_startup_readiness_gate
        except ImportError:
            try:
                from startup_readiness_gate import get_startup_readiness_gate  # type: ignore[import]
            except ImportError:
                logger.debug("[BootstrapFSM] I5: StartupReadinessGate unavailable — skipping check")
                return
        gate = get_startup_readiness_gate()
        if not gate.is_ready():
            raise BootstrapInvariantError(
                "I5_READINESS_GATE",
                "Trading loops requested but StartupReadinessGate is not open. "
                "Wait for all registered components to signal ready.",
            )

    def assert_invariant_i6_mode_safety(self) -> None:
        """I6 — real order placement illegal unless TradingStateMachine is LIVE_ACTIVE."""
        try:
            from bot.trading_state_machine import get_state_machine
        except ImportError:
            try:
                from trading_state_machine import get_state_machine  # type: ignore[import]
            except ImportError:
                logger.debug("[BootstrapFSM] I6: TradingStateMachine unavailable — skipping check")
                return
        sm = get_state_machine()
        if not sm.is_live_trading_active():
            raise BootstrapInvariantError(
                "I6_MODE_SAFETY",
                f"Real order placement attempted but trading mode is "
                f"{sm.get_current_state().value} (must be LIVE_ACTIVE).",
            )

    def assert_invariant_i7_emergency_safety(self) -> None:
        """I7 — EMERGENCY_STOP mode blocks all activity except the reset path."""
        try:
            from bot.trading_state_machine import get_state_machine
        except ImportError:
            try:
                from trading_state_machine import get_state_machine  # type: ignore[import]
            except ImportError:
                logger.debug("[BootstrapFSM] I7: TradingStateMachine unavailable — skipping check")
                return
        sm = get_state_machine()
        if sm.is_emergency_stopped():
            raise BootstrapInvariantError(
                "I7_EMERGENCY_SAFETY",
                "System is in EMERGENCY_STOP mode. All activity blocked. "
                "Transition TradingStateMachine to OFF before proceeding.",
            )

    def assert_invariant_i8_supervisor_ownership(self) -> None:
        """I8 — worker-thread restarts only legal in RUNNING_SUPERVISED state."""
        state = self.state
        if state != BootstrapState.RUNNING_SUPERVISED:
            raise BootstrapInvariantError(
                "I8_SUPERVISOR_OWNERSHIP",
                f"Worker-thread restart attempted outside RUNNING_SUPERVISED state "
                f"(current state={state.value}).",
            )

    @staticmethod
    def assert_invariant_i9_fail_closed_nonce(exc: BaseException) -> None:
        """I9 — fatal nonce errors must force EXTERNAL_RESTART_REQUIRED.

        Call this from the exception handler whenever a nonce-related
        RuntimeError is caught to verify it is the fatal variant that requires
        a clean process restart.

        Raises :class:`BootstrapInvariantError` if *exc* is a fatal nonce error
        (so the caller knows to transition to EXTERNAL_RESTART_REQUIRED).
        """
        _fatal_fragments = (
            "nonce not authorized",
            "invalid nonce spike detected",
        )
        msg = str(exc).lower()
        if any(frag in msg for frag in _fatal_fragments):
            raise BootstrapInvariantError(
                "I9_FAIL_CLOSED_NONCE",
                f"Fatal nonce error detected: {exc}. "
                "Transition to EXTERNAL_RESTART_REQUIRED and request process restart.",
            )

    @staticmethod
    def assert_invariant_i10_capital_writer(writer_id: str) -> None:
        """I10 — only the canonical writer may publish capital snapshots."""
        if writer_id != _CAPITAL_WRITER_ID:
            raise BootstrapInvariantError(
                "I10_CAPITAL_WRITER",
                f"Capital snapshot published by unauthorised writer {writer_id!r}. "
                f"Only {_CAPITAL_WRITER_ID!r} is permitted.",
            )

    def assert_invariant_i11_strategy_arm(self) -> None:
        """I11 — strategy engine arming is illegal before CAPITAL_READY.

        Raises :class:`BootstrapInvariantError` when the bootstrap FSM has not
        yet reached :attr:`BootstrapState.CAPITAL_READY`.  Trading strategy
        engines, :class:`CapitalDecisionEngine`, and any module that begins
        live capital computation must call this before constructing itself.
        """
        state = self.state
        if state not in _STRATEGY_ARM_ALLOWED_STATES:
            raise BootstrapInvariantError(
                "I11_STRATEGY_ARM",
                f"Strategy engine arming attempted before CAPITAL_READY "
                f"(current bootstrap state={state.value}). "
                "Wait for BootstrapStateMachine to reach CAPITAL_READY "
                "before initialising trading engines.",
            )

    def assert_invariant_i12_capital_hydration(self, timeout: float = 5.0) -> None:
        """I12 — capital pipeline must be hydrated before CAPITAL_READY is legal.

        Enforces the hard hydration barrier introduced by CSM-v2.  Calls
        :meth:`~bot.capital_csm_v2.CapitalCSMv2.wait_for_hydration` on the
        process-wide CSM-v2 singleton.

        Must execute:

        * BEFORE tier calculation
        * BEFORE strategy init
        * BEFORE the execution engine starts

        This invariant is automatically checked by :meth:`advance_to_capital_ready`
        before the FSM steps into ``CAPITAL_READY``.

        Parameters
        ----------
        timeout:
            Maximum seconds to wait for hydration.  Default 5 s.

        Raises
        ------
        BootstrapInvariantError
            If hydration is not confirmed within *timeout*.
        """
        try:
            from bot.capital_csm_v2 import (  # noqa: PLC0415
                CapitalIntegrityError as _CIE,
                get_csm_v2 as _get_csm,
            )
        except ImportError:
            try:
                from capital_csm_v2 import (  # type: ignore[no-redef]  # noqa: PLC0415
                    CapitalIntegrityError as _CIE,
                    get_csm_v2 as _get_csm,
                )
            except ImportError:
                logger.debug(
                    "[BootstrapFSM] I12: CapitalCSMv2 unavailable — skipping hydration check"
                )
                return
        try:
            _get_csm().wait_for_hydration(timeout=timeout)
        except _CIE as exc:
            raise BootstrapInvariantError(
                "I12_CAPITAL_HYDRATION",
                f"Capital hydration barrier failed: {exc}. "
                "Ensure the capital pipeline runs before CAPITAL_READY is declared. "
                "Bootstrap order: broker_connect → balance_fetch → wait_for_hydration "
                "→ tier_calc → strategy_init → execution_loop.",
            ) from exc

    # ------------------------------------------------------------------
    # Convenience dispatcher
    # ------------------------------------------------------------------

    def check_invariant(self, invariant_id: str, **kwargs: Any) -> None:
        """
        Dispatch a named invariant check.

        Parameters
        ----------
        invariant_id:
            One of ``"I1"`` through ``"I12"``.
        **kwargs:
            Extra context for static invariant methods:

            - ``exc`` — for I9 (the exception object to classify)
            - ``writer_id`` — for I10
            - ``timeout`` — for I12 (hydration wait timeout in seconds)

        Raises
        ------
        BootstrapInvariantError
            If the invariant is violated.
        ValueError
            If *invariant_id* is not recognised.
        """
        _dispatch = {
            "I1": self.assert_invariant_i1_single_writer,
            "I2": self.assert_invariant_i2_liveness_first,
            "I3": self.assert_invariant_i3_platform_first,
            "I4": self.assert_invariant_i4_capital_gate,
            "I5": self.assert_invariant_i5_readiness_gate,
            "I6": self.assert_invariant_i6_mode_safety,
            "I7": self.assert_invariant_i7_emergency_safety,
            "I8": self.assert_invariant_i8_supervisor_ownership,
            "I11": self.assert_invariant_i11_strategy_arm,
        }
        if invariant_id in _dispatch:
            _dispatch[invariant_id]()
        elif invariant_id == "I9":
            exc = kwargs.get("exc")
            if exc is not None:
                self.assert_invariant_i9_fail_closed_nonce(exc)
        elif invariant_id == "I10":
            writer_id = kwargs.get("writer_id", "")
            self.assert_invariant_i10_capital_writer(writer_id)
        elif invariant_id == "I12":
            timeout = float(kwargs.get("timeout", 5.0))
            self.assert_invariant_i12_capital_hydration(timeout=timeout)
        else:
            raise ValueError(f"Unknown invariant id: {invariant_id!r}")


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------
_bootstrap_fsm: Optional[BootstrapStateMachine] = None
_bootstrap_fsm_lock = threading.Lock()


def get_bootstrap_fsm() -> BootstrapStateMachine:
    """Return the process-wide :class:`BootstrapStateMachine` singleton."""
    global _bootstrap_fsm
    if _bootstrap_fsm is None:
        with _bootstrap_fsm_lock:
            if _bootstrap_fsm is None:
                _bootstrap_fsm = BootstrapStateMachine()
    return _bootstrap_fsm


__all__ = [
    "BootstrapState",
    "BootstrapInvariantError",
    "BootstrapStateMachine",
    "get_bootstrap_fsm",
    "_STRATEGY_ARM_ALLOWED_STATES",
    "_ANY_THREAD_ALLOWED_TARGETS",
]
