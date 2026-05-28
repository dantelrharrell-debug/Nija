"""NIJA Bootstrap Coordinator
==============================

Single source of truth for all bootstrap authority in the NIJA trading bot.

Eliminates bootstrap race conditions and deadlocks by consolidating every
startup component behind explicit, ordered phase barriers.  All auxiliary
daemons (nonce manager, signal broadcaster, market regime detector, etc.)
must wait for their prerequisite phase before starting.

Phases (in strict order)
------------------------
  PRECHECK              – Validate environment, Redis connectivity, kill switch
  LOCK_ACQUIRED         – Acquire distributed writer lock
  HEARTBEATS_READY      – Start authority heartbeat monitor
  FSM_READY             – Initialize trading state machine
  BROKERS_READY         – Connect and validate all brokers
  STRATEGY_READY        – Load and validate trading strategy
  RUNNING_SUPERVISED    – Start core trading loop with supervision

Phase Barriers
--------------
* Phases can only advance forward — no skipping, no reordering.
* Each phase has a configurable timeout (env var or default 30 s).
* Each phase records entry/exit timestamps for diagnostics.
* Rollback on failure: the coordinator logs the failing phase and reason.
* Thread-safe via ``threading.RLock``.

Auxiliary Daemon Blocking
-------------------------
* Nonce manager          → blocked until LOCK_ACQUIRED
* Heartbeat monitor      → blocked until PRECHECK, starts at HEARTBEATS_READY
* Signal broadcaster     → blocked until STRATEGY_READY
* Market regime detector → blocked until STRATEGY_READY
* Capital authority      → blocked until BROKERS_READY
* Core trading loop      → blocked until RUNNING_SUPERVISED

Integration
-----------
``bot.py`` creates the coordinator at startup and passes it to each component.
Components call :meth:`BootstrapCoordinator.wait_for_phase` to block until
their prerequisite phase is reached, then call
:meth:`BootstrapCoordinator.advance_to` to signal their own phase completion.

Usage::

    from bot.bootstrap_coordinator import (
        BootstrapCoordinator,
        BootstrapPhase,
        get_bootstrap_coordinator,
    )

    coordinator = get_bootstrap_coordinator()

    # Block until BROKERS_READY before starting capital authority:
    coordinator.wait_for_phase(BootstrapPhase.BROKERS_READY, timeout_s=60.0)

    # Signal that this component's phase is complete:
    coordinator.advance_to(BootstrapPhase.STRATEGY_READY, reason="strategy loaded")

Author: NIJA Trading Systems
Version: 1.0
"""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.bootstrap_coordinator")

# ---------------------------------------------------------------------------
# Phase enumeration — ordered by bootstrap sequence
# ---------------------------------------------------------------------------


class BootstrapPhase(int, Enum):
    """Ordered bootstrap phases.  Higher integer = later in the sequence.

    The integer value is used for forward-only enforcement: a transition is
    legal only when ``new_phase.value > current_phase.value``.
    """

    UNSTARTED = 0
    PRECHECK = 1
    LOCK_ACQUIRED = 2
    HEARTBEATS_READY = 3
    FSM_READY = 4
    BROKERS_READY = 5
    STRATEGY_READY = 6
    RUNNING_SUPERVISED = 7

    # Terminal states — no further advancement is possible.
    FAILED = -1
    SHUTDOWN = -2


# Human-readable labels for log messages.
_PHASE_LABELS: Dict[BootstrapPhase, str] = {
    BootstrapPhase.UNSTARTED: "UNSTARTED",
    BootstrapPhase.PRECHECK: "PRECHECK",
    BootstrapPhase.LOCK_ACQUIRED: "LOCK_ACQUIRED",
    BootstrapPhase.HEARTBEATS_READY: "HEARTBEATS_READY",
    BootstrapPhase.FSM_READY: "FSM_READY",
    BootstrapPhase.BROKERS_READY: "BROKERS_READY",
    BootstrapPhase.STRATEGY_READY: "STRATEGY_READY",
    BootstrapPhase.RUNNING_SUPERVISED: "RUNNING_SUPERVISED",
    BootstrapPhase.FAILED: "FAILED",
    BootstrapPhase.SHUTDOWN: "SHUTDOWN",
}

# Default timeout (seconds) for each phase barrier.
# Overridable via environment variables of the form
# ``NIJA_BOOTSTRAP_<PHASE>_TIMEOUT_S`` (e.g. ``NIJA_BOOTSTRAP_PRECHECK_TIMEOUT_S=60``).
_DEFAULT_PHASE_TIMEOUT_S: float = 30.0

_PHASE_TIMEOUT_ENV_VARS: Dict[BootstrapPhase, str] = {
    BootstrapPhase.PRECHECK: "NIJA_BOOTSTRAP_PRECHECK_TIMEOUT_S",
    BootstrapPhase.LOCK_ACQUIRED: "NIJA_BOOTSTRAP_LOCK_ACQUIRED_TIMEOUT_S",
    BootstrapPhase.HEARTBEATS_READY: "NIJA_BOOTSTRAP_HEARTBEATS_READY_TIMEOUT_S",
    BootstrapPhase.FSM_READY: "NIJA_BOOTSTRAP_FSM_READY_TIMEOUT_S",
    BootstrapPhase.BROKERS_READY: "NIJA_BOOTSTRAP_BROKERS_READY_TIMEOUT_S",
    BootstrapPhase.STRATEGY_READY: "NIJA_BOOTSTRAP_STRATEGY_READY_TIMEOUT_S",
    BootstrapPhase.RUNNING_SUPERVISED: "NIJA_BOOTSTRAP_RUNNING_SUPERVISED_TIMEOUT_S",
}


def _phase_timeout(phase: BootstrapPhase) -> float:
    """Return the configured timeout for *phase* (seconds)."""
    env_var = _PHASE_TIMEOUT_ENV_VARS.get(phase)
    if env_var:
        raw = os.environ.get(env_var, "").strip()
        if raw:
            try:
                return max(1.0, float(raw))
            except (TypeError, ValueError):
                logger.warning(
                    "Invalid %s=%r — using default %.1fs",
                    env_var,
                    raw,
                    _DEFAULT_PHASE_TIMEOUT_S,
                )
    return _DEFAULT_PHASE_TIMEOUT_S


# ---------------------------------------------------------------------------
# Phase record — one entry per completed phase in the audit trail
# ---------------------------------------------------------------------------


class PhaseRecord:
    """Immutable record of a single phase transition."""

    __slots__ = (
        "phase",
        "reason",
        "entered_at",
        "completed_at",
        "duration_s",
        "failed",
        "failure_reason",
    )

    def __init__(
        self,
        phase: BootstrapPhase,
        reason: str,
        entered_at: float,
        completed_at: float,
        *,
        failed: bool = False,
        failure_reason: str = "",
    ) -> None:
        self.phase = phase
        self.reason = reason
        self.entered_at = entered_at
        self.completed_at = completed_at
        self.duration_s = completed_at - entered_at
        self.failed = failed
        self.failure_reason = failure_reason

    def as_dict(self) -> Dict[str, Any]:
        return {
            "phase": _PHASE_LABELS.get(self.phase, str(self.phase)),
            "reason": self.reason,
            "entered_at": datetime.fromtimestamp(self.entered_at, tz=timezone.utc).isoformat(),
            "completed_at": datetime.fromtimestamp(self.completed_at, tz=timezone.utc).isoformat(),
            "duration_s": round(self.duration_s, 3),
            "failed": self.failed,
            "failure_reason": self.failure_reason,
        }


# ---------------------------------------------------------------------------
# BootstrapCoordinator
# ---------------------------------------------------------------------------


class BootstrapCoordinator:
    """Single source of truth for NIJA bootstrap authority.

    Thread-safe via a single ``threading.RLock``.  Phase barriers are
    implemented as ``threading.Event`` objects — one per phase — so that
    waiting threads are woken immediately when a phase completes rather than
    polling.

    Singleton enforcement
    ---------------------
    Use :func:`get_bootstrap_coordinator` to obtain the process-wide instance.
    Direct construction is allowed for testing (set ``PYTEST_CURRENT_TEST`` or
    ``UNITTEST_RUNNING`` in the environment).

    Phase advancement rules
    -----------------------
    * Phases must advance in strict forward order (``UNSTARTED → PRECHECK →
      LOCK_ACQUIRED → … → RUNNING_SUPERVISED``).
    * Terminal phases (``FAILED``, ``SHUTDOWN``) may be entered from any state.
    * Attempting to advance to a phase that is already reached is a no-op and
      returns ``True`` (idempotent).
    * Attempting to skip a phase raises ``BootstrapPhaseError`` unless
      ``allow_skip=True`` is passed (for degraded-mode paths).
    """

    _instance: Optional["BootstrapCoordinator"] = None
    _instance_lock: threading.Lock = threading.Lock()

    # ------------------------------------------------------------------
    # Construction
    # ------------------------------------------------------------------

    def __init__(self) -> None:
        self._lock = threading.RLock()

        # Current phase — starts at UNSTARTED.
        self._phase: BootstrapPhase = BootstrapPhase.UNSTARTED

        # Per-phase completion events.  Waiting threads block on these.
        self._phase_events: Dict[BootstrapPhase, threading.Event] = {
            p: threading.Event()
            for p in BootstrapPhase
            if p not in (BootstrapPhase.UNSTARTED, BootstrapPhase.FAILED, BootstrapPhase.SHUTDOWN)
        }

        # Audit trail — list of PhaseRecord objects.
        self._history: List[PhaseRecord] = []

        # Phase entry timestamps (monotonic) — set when we *enter* a phase.
        self._phase_entered_at: Dict[BootstrapPhase, float] = {}

        # Registered callbacks: phase → list of callables.
        self._callbacks: Dict[BootstrapPhase, List[Callable[[BootstrapPhase, str], None]]] = {
            p: [] for p in BootstrapPhase
        }

        # Failure state.
        self._failed: bool = False
        self._failure_phase: Optional[BootstrapPhase] = None
        self._failure_reason: str = ""

        # Owner thread — the thread that drives phase transitions.
        # None until :meth:`claim_ownership` is called.
        self._owner_thread_id: Optional[int] = None

        logger.info(
            "BootstrapCoordinator: initialized pid=%d thread=%s",
            os.getpid(),
            threading.current_thread().name,
        )

    # ------------------------------------------------------------------
    # Singleton access
    # ------------------------------------------------------------------

    @classmethod
    def get_instance(cls) -> "BootstrapCoordinator":
        """Return the process-wide singleton, creating it if necessary."""
        if cls._instance is not None:
            return cls._instance
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
        return cls._instance

    @classmethod
    def _reset_for_testing(cls) -> None:
        """⚠️ TEST-ONLY — reset the singleton so a fresh instance can be created.

        Raises ``RuntimeError`` if called outside a recognised test context.
        """
        if not (
            os.environ.get("PYTEST_CURRENT_TEST")
            or os.environ.get("UNITTEST_RUNNING")
        ):
            raise RuntimeError(
                "BootstrapCoordinator._reset_for_testing() must only be called "
                "from test code (PYTEST_CURRENT_TEST or UNITTEST_RUNNING must be set)"
            )
        with cls._instance_lock:
            cls._instance = None

    # ------------------------------------------------------------------
    # Ownership
    # ------------------------------------------------------------------

    def claim_ownership(self) -> None:
        """Designate the calling thread as the sole owner of phase transitions.

        Idempotent: safe to call multiple times from the same thread.
        Non-owner threads that attempt non-terminal phase advances are rejected.
        """
        caller_id = threading.get_ident()
        with self._lock:
            prev = self._owner_thread_id
            self._owner_thread_id = caller_id
        if prev != caller_id:
            logger.info(
                "BootstrapCoordinator: ownership claimed by thread %d (%s)",
                caller_id,
                threading.current_thread().name,
            )

    def _is_owner(self) -> bool:
        """Return True when the calling thread is the registered owner."""
        with self._lock:
            return (
                self._owner_thread_id is None
                or self._owner_thread_id == threading.get_ident()
            )

    # ------------------------------------------------------------------
    # Phase access
    # ------------------------------------------------------------------

    @property
    def phase(self) -> BootstrapPhase:
        """Current bootstrap phase (thread-safe, non-blocking)."""
        with self._lock:
            return self._phase

    @property
    def is_failed(self) -> bool:
        """True when the coordinator has entered the FAILED terminal state."""
        with self._lock:
            return self._failed

    @property
    def failure_reason(self) -> str:
        """Human-readable reason for the last failure (empty if not failed)."""
        with self._lock:
            return self._failure_reason

    def has_reached(self, phase: BootstrapPhase) -> bool:
        """Return True when *phase* has been reached or surpassed."""
        with self._lock:
            if self._failed or self._phase == BootstrapPhase.SHUTDOWN:
                # Terminal states: only RUNNING_SUPERVISED counts as "reached".
                return phase in (BootstrapPhase.FAILED, BootstrapPhase.SHUTDOWN)
            return self._phase.value >= phase.value

    def get_history(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Return the most recent *limit* phase records as dicts."""
        with self._lock:
            return [r.as_dict() for r in self._history[-limit:]]

    def get_status(self) -> Dict[str, Any]:
        """Serialisable snapshot suitable for a /status health endpoint."""
        with self._lock:
            return {
                "phase": _PHASE_LABELS.get(self._phase, str(self._phase)),
                "failed": self._failed,
                "failure_phase": (
                    _PHASE_LABELS.get(self._failure_phase, str(self._failure_phase))
                    if self._failure_phase is not None
                    else None
                ),
                "failure_reason": self._failure_reason,
                "owner_thread_id": self._owner_thread_id,
                "history": [r.as_dict() for r in self._history[-10:]],
            }

    # ------------------------------------------------------------------
    # Phase advancement
    # ------------------------------------------------------------------

    def advance_to(
        self,
        phase: BootstrapPhase,
        reason: str = "",
        *,
        allow_skip: bool = False,
    ) -> bool:
        """Advance the coordinator to *phase*.

        Parameters
        ----------
        phase:
            Target phase.  Must be strictly greater than the current phase
            unless *allow_skip* is True.
        reason:
            Human-readable description of why this phase is being entered.
        allow_skip:
            When True, intermediate phases may be skipped (degraded-mode paths
            only).  Defaults to False.

        Returns
        -------
        bool
            True if the phase was advanced (or was already at/past *phase*).
            False if the advance was rejected (ownership violation, terminal
            state, or illegal backward transition).

        Raises
        ------
        BootstrapPhaseError
            If a phase skip is detected and *allow_skip* is False.
        """
        # Terminal phases may be entered from any state by any thread.
        _terminal = (BootstrapPhase.FAILED, BootstrapPhase.SHUTDOWN)
        if phase not in _terminal and not self._is_owner():
            logger.error(
                "BootstrapCoordinator: non-owner thread %d (%s) attempted to advance to %s — rejected",
                threading.get_ident(),
                threading.current_thread().name,
                _PHASE_LABELS.get(phase, str(phase)),
            )
            return False

        with self._lock:
            current = self._phase

            # Already in a terminal state — only SHUTDOWN can follow FAILED.
            if current == BootstrapPhase.FAILED and phase != BootstrapPhase.SHUTDOWN:
                logger.warning(
                    "BootstrapCoordinator: advance_to(%s) rejected — coordinator is in FAILED state",
                    _PHASE_LABELS.get(phase, str(phase)),
                )
                return False
            if current == BootstrapPhase.SHUTDOWN:
                logger.warning(
                    "BootstrapCoordinator: advance_to(%s) rejected — coordinator is in SHUTDOWN state",
                    _PHASE_LABELS.get(phase, str(phase)),
                )
                return False

            # Idempotent: already at or past this phase.
            if phase not in _terminal and current.value >= phase.value:
                logger.debug(
                    "BootstrapCoordinator: advance_to(%s) no-op — already at %s",
                    _PHASE_LABELS.get(phase, str(phase)),
                    _PHASE_LABELS.get(current, str(current)),
                )
                return True

            # Detect phase skips for non-terminal advances.
            if phase not in _terminal and not allow_skip:
                _expected_next = current.value + 1
                if phase.value > _expected_next:
                    _skipped = [
                        _PHASE_LABELS.get(BootstrapPhase(v), str(v))
                        for v in range(_expected_next, phase.value)
                        if v in BootstrapPhase._value2member_map_
                    ]
                    if _skipped:
                        raise BootstrapPhaseError(
                            f"Phase skip detected: {_PHASE_LABELS.get(current, str(current))} → "
                            f"{_PHASE_LABELS.get(phase, str(phase))} "
                            f"(skipped: {', '.join(_skipped)}). "
                            "Pass allow_skip=True for degraded-mode paths."
                        )

            # Record entry timestamp.
            _now = time.monotonic()
            _wall = time.time()
            self._phase_entered_at[phase] = _now

            # Commit the transition.
            prev_phase = self._phase
            if phase == BootstrapPhase.FAILED:
                self._failed = True
                self._failure_phase = current
                self._failure_reason = reason or "unspecified failure"
                self._phase = BootstrapPhase.FAILED
            elif phase == BootstrapPhase.SHUTDOWN:
                self._phase = BootstrapPhase.SHUTDOWN
            else:
                self._phase = phase

            # Record in audit trail.
            _record = PhaseRecord(
                phase=phase,
                reason=reason or "—",
                entered_at=_wall,
                completed_at=_wall,
                failed=(phase == BootstrapPhase.FAILED),
                failure_reason=self._failure_reason if phase == BootstrapPhase.FAILED else "",
            )
            self._history.append(_record)

            # Collect callbacks to fire outside the lock.
            _cbs = list(self._callbacks.get(phase, []))

        # Signal the phase event so waiting threads are unblocked.
        _event = self._phase_events.get(phase)
        if _event is not None:
            _event.set()

        # Log the transition.
        if phase == BootstrapPhase.FAILED:
            logger.critical(
                "❌ [BootstrapCoordinator] FAILED at phase=%s reason=%s",
                _PHASE_LABELS.get(prev_phase, str(prev_phase)),
                reason or "—",
            )
        elif phase == BootstrapPhase.SHUTDOWN:
            logger.info(
                "🛑 [BootstrapCoordinator] SHUTDOWN reason=%s",
                reason or "—",
            )
        else:
            logger.info(
                "✅ [BootstrapCoordinator] %s → %s  reason=%s",
                _PHASE_LABELS.get(prev_phase, str(prev_phase)),
                _PHASE_LABELS.get(phase, str(phase)),
                reason or "—",
            )

        # Fire callbacks outside the lock to avoid deadlocks.
        for cb in _cbs:
            try:
                cb(phase, reason or "")
            except Exception as exc:
                logger.warning(
                    "BootstrapCoordinator: callback for phase %s raised: %s",
                    _PHASE_LABELS.get(phase, str(phase)),
                    exc,
                )

        return True

    def mark_failed(self, reason: str, *, phase: Optional[BootstrapPhase] = None) -> None:
        """Enter the FAILED terminal state with a descriptive reason.

        Safe to call from any thread.  Unblocks all waiting threads so they
        can detect the failure and abort.
        """
        with self._lock:
            if self._phase in (BootstrapPhase.FAILED, BootstrapPhase.SHUTDOWN):
                return
            _failing_phase = phase or self._phase
            self._failed = True
            self._failure_phase = _failing_phase
            self._failure_reason = reason
            self._phase = BootstrapPhase.FAILED
            _record = PhaseRecord(
                phase=BootstrapPhase.FAILED,
                reason=reason,
                entered_at=time.time(),
                completed_at=time.time(),
                failed=True,
                failure_reason=reason,
            )
            self._history.append(_record)

        # Unblock all waiting threads so they can detect the failure.
        for event in self._phase_events.values():
            event.set()

        logger.critical(
            "❌ [BootstrapCoordinator] FAILED phase=%s reason=%s",
            _PHASE_LABELS.get(_failing_phase, str(_failing_phase)),
            reason,
        )

    def mark_shutdown(self, reason: str = "graceful shutdown") -> None:
        """Enter the SHUTDOWN terminal state.  Safe to call from any thread."""
        with self._lock:
            if self._phase == BootstrapPhase.SHUTDOWN:
                return
            self._phase = BootstrapPhase.SHUTDOWN
            _record = PhaseRecord(
                phase=BootstrapPhase.SHUTDOWN,
                reason=reason,
                entered_at=time.time(),
                completed_at=time.time(),
            )
            self._history.append(_record)

        for event in self._phase_events.values():
            event.set()

        logger.info("🛑 [BootstrapCoordinator] SHUTDOWN reason=%s", reason)

    # ------------------------------------------------------------------
    # Phase barriers — blocking wait API
    # ------------------------------------------------------------------

    def wait_for_phase(
        self,
        phase: BootstrapPhase,
        *,
        timeout_s: Optional[float] = None,
        poll_interval_s: float = 0.25,
        context: str = "",
    ) -> bool:
        """Block until *phase* is reached (or the coordinator fails/shuts down).

        Parameters
        ----------
        phase:
            The phase to wait for.
        timeout_s:
            Maximum seconds to wait.  Defaults to the configured phase timeout
            (``NIJA_BOOTSTRAP_<PHASE>_TIMEOUT_S`` or 30 s).
        poll_interval_s:
            How often to re-check the failure flag while waiting.  The event
            itself wakes immediately on phase completion; this is only used to
            detect failure/shutdown between event waits.
        context:
            Diagnostic label appended to timeout log messages.

        Returns
        -------
        bool
            True when *phase* has been reached.
            False when the coordinator failed, shut down, or timed out.
        """
        if timeout_s is None:
            timeout_s = _phase_timeout(phase)

        _deadline = time.monotonic() + timeout_s
        _label = _PHASE_LABELS.get(phase, str(phase))
        _ctx = f" ({context})" if context else ""

        # Fast path: already at or past this phase.
        if self.has_reached(phase):
            return True

        # Failure fast path.
        if self._failed:
            logger.warning(
                "BootstrapCoordinator: wait_for_phase(%s)%s — coordinator already FAILED: %s",
                _label,
                _ctx,
                self._failure_reason,
            )
            return False

        _event = self._phase_events.get(phase)
        if _event is None:
            # Terminal phases don't have events; check directly.
            return self.has_reached(phase)

        logger.debug(
            "BootstrapCoordinator: waiting for phase %s%s timeout=%.1fs",
            _label,
            _ctx,
            timeout_s,
        )

        _last_log = time.monotonic()
        _log_interval = 10.0

        while True:
            _remaining = _deadline - time.monotonic()
            if _remaining <= 0:
                break

            # Wait for the event with a bounded interval so we can check
            # the failure flag and emit progress logs.
            _wait_s = min(poll_interval_s, _remaining)
            _reached = _event.wait(timeout=_wait_s)

            if _reached and self.has_reached(phase):
                logger.debug(
                    "BootstrapCoordinator: phase %s reached%s",
                    _label,
                    _ctx,
                )
                return True

            # Check for terminal states.
            with self._lock:
                _current = self._phase
                _is_failed = self._failed

            if _is_failed:
                logger.warning(
                    "BootstrapCoordinator: wait_for_phase(%s)%s aborted — coordinator FAILED: %s",
                    _label,
                    _ctx,
                    self._failure_reason,
                )
                return False

            if _current == BootstrapPhase.SHUTDOWN:
                logger.warning(
                    "BootstrapCoordinator: wait_for_phase(%s)%s aborted — coordinator SHUTDOWN",
                    _label,
                    _ctx,
                )
                return False

            # Emit periodic progress log.
            _now = time.monotonic()
            if _now - _last_log >= _log_interval:
                _elapsed = timeout_s - (_deadline - _now)
                logger.info(
                    "BootstrapCoordinator: still waiting for phase %s%s "
                    "current=%s elapsed=%.1fs remaining=%.1fs",
                    _label,
                    _ctx,
                    _PHASE_LABELS.get(_current, str(_current)),
                    _elapsed,
                    max(0.0, _deadline - _now),
                )
                _last_log = _now

        # Timeout.
        with self._lock:
            _current = self._phase
        logger.critical(
            "BootstrapCoordinator: TIMEOUT waiting for phase %s%s "
            "current=%s timeout=%.1fs",
            _label,
            _ctx,
            _PHASE_LABELS.get(_current, str(_current)),
            timeout_s,
        )
        return False

    def assert_phase_reached(
        self,
        phase: BootstrapPhase,
        *,
        context: str = "",
    ) -> None:
        """Raise :class:`BootstrapPhaseError` if *phase* has not been reached.

        Use this as a lightweight guard at the start of functions that must
        only run after a specific phase.
        """
        if not self.has_reached(phase):
            _label = _PHASE_LABELS.get(phase, str(phase))
            _current_label = _PHASE_LABELS.get(self._phase, str(self._phase))
            raise BootstrapPhaseError(
                f"Phase barrier violated{' (' + context + ')' if context else ''}: "
                f"required={_label} current={_current_label}"
            )

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def on_phase(
        self,
        phase: BootstrapPhase,
        callback: Callable[[BootstrapPhase, str], None],
    ) -> None:
        """Register *callback* to be called when *phase* is reached.

        The callback receives ``(phase, reason)`` as arguments.  If the phase
        has already been reached, the callback is fired immediately.

        Callbacks are fired outside the coordinator lock to avoid deadlocks.
        Exceptions raised by callbacks are caught and logged.
        """
        _already_reached = False
        with self._lock:
            if self.has_reached(phase):
                _already_reached = True
            else:
                self._callbacks.setdefault(phase, []).append(callback)

        if _already_reached:
            try:
                callback(phase, "already_reached")
            except Exception as exc:
                logger.warning(
                    "BootstrapCoordinator: immediate callback for phase %s raised: %s",
                    _PHASE_LABELS.get(phase, str(phase)),
                    exc,
                )

    # ------------------------------------------------------------------
    # Daemon blocking helpers
    # ------------------------------------------------------------------

    def block_until_lock_acquired(
        self,
        *,
        timeout_s: Optional[float] = None,
        context: str = "nonce_manager",
    ) -> bool:
        """Block until LOCK_ACQUIRED phase.  Used by the nonce manager.

        Returns True when the lock has been acquired, False on failure/timeout.
        """
        return self.wait_for_phase(
            BootstrapPhase.LOCK_ACQUIRED,
            timeout_s=timeout_s,
            context=context,
        )

    def block_until_strategy_ready(
        self,
        *,
        timeout_s: Optional[float] = None,
        context: str = "auxiliary_daemon",
    ) -> bool:
        """Block until STRATEGY_READY phase.

        Used by signal broadcaster and market regime detector.
        Returns True when strategy is ready, False on failure/timeout.
        """
        return self.wait_for_phase(
            BootstrapPhase.STRATEGY_READY,
            timeout_s=timeout_s,
            context=context,
        )

    def block_until_brokers_ready(
        self,
        *,
        timeout_s: Optional[float] = None,
        context: str = "capital_authority",
    ) -> bool:
        """Block until BROKERS_READY phase.  Used by capital authority.

        Returns True when brokers are ready, False on failure/timeout.
        """
        return self.wait_for_phase(
            BootstrapPhase.BROKERS_READY,
            timeout_s=timeout_s,
            context=context,
        )

    def block_until_running_supervised(
        self,
        *,
        timeout_s: Optional[float] = None,
        context: str = "core_trading_loop",
    ) -> bool:
        """Block until RUNNING_SUPERVISED phase.  Used by the core trading loop.

        Returns True when the supervised runtime is active, False on failure/timeout.
        """
        return self.wait_for_phase(
            BootstrapPhase.RUNNING_SUPERVISED,
            timeout_s=timeout_s,
            context=context,
        )

    # ------------------------------------------------------------------
    # Convenience: fast-forward through phases
    # ------------------------------------------------------------------

    def advance_through(
        self,
        phases: List[Tuple[BootstrapPhase, str]],
        *,
        stop_on_failure: bool = True,
    ) -> bool:
        """Advance through a sequence of ``(phase, reason)`` pairs.

        Parameters
        ----------
        phases:
            Ordered list of ``(BootstrapPhase, reason_str)`` tuples.
        stop_on_failure:
            When True (default), stop advancing if any phase fails.

        Returns
        -------
        bool
            True if all phases were advanced successfully.
        """
        for phase, reason in phases:
            ok = self.advance_to(phase, reason)
            if not ok and stop_on_failure:
                logger.error(
                    "BootstrapCoordinator: advance_through stopped at phase %s",
                    _PHASE_LABELS.get(phase, str(phase)),
                )
                return False
        return True


# ---------------------------------------------------------------------------
# Exception
# ---------------------------------------------------------------------------


class BootstrapPhaseError(RuntimeError):
    """Raised when a phase barrier is violated or an illegal skip is attempted."""


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_coordinator: Optional[BootstrapCoordinator] = None
_coordinator_lock = threading.Lock()


def get_bootstrap_coordinator() -> BootstrapCoordinator:
    """Return the process-wide :class:`BootstrapCoordinator` singleton."""
    global _coordinator
    if _coordinator is not None:
        return _coordinator
    with _coordinator_lock:
        if _coordinator is None:
            _coordinator = BootstrapCoordinator()
    return _coordinator


# ---------------------------------------------------------------------------
# Convenience module-level helpers (mirror the instance API)
# ---------------------------------------------------------------------------


def coordinator_advance_to(phase: BootstrapPhase, reason: str = "") -> bool:
    """Advance the global coordinator to *phase*."""
    return get_bootstrap_coordinator().advance_to(phase, reason)


def coordinator_wait_for(
    phase: BootstrapPhase,
    *,
    timeout_s: Optional[float] = None,
    context: str = "",
) -> bool:
    """Wait for the global coordinator to reach *phase*."""
    return get_bootstrap_coordinator().wait_for_phase(
        phase, timeout_s=timeout_s, context=context
    )


def coordinator_has_reached(phase: BootstrapPhase) -> bool:
    """Return True when the global coordinator has reached *phase*."""
    return get_bootstrap_coordinator().has_reached(phase)


def coordinator_mark_failed(reason: str) -> None:
    """Mark the global coordinator as FAILED."""
    get_bootstrap_coordinator().mark_failed(reason)


__all__ = [
    "BootstrapPhase",
    "BootstrapPhaseError",
    "BootstrapCoordinator",
    "PhaseRecord",
    "get_bootstrap_coordinator",
    "coordinator_advance_to",
    "coordinator_wait_for",
    "coordinator_has_reached",
    "coordinator_mark_failed",
]
