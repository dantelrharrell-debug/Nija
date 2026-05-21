"""Deterministic startup coordinator for cross-FSM convergence.

Model-checking invariants
-------------------------
GLOBAL_STATE
    The :data:`GLOBAL_STATE` singleton provides an *atomic snapshot* of the
    full runtime state across all FSMs via :meth:`GlobalState.capture`.  Any
    reader that needs a consistent view must call :meth:`GlobalState.capture`
    rather than inspecting individual sub-system objects.

GLOBAL_EPOCH
    A single monotonic counter — :attr:`_RuntimeState.global_epoch` — advances
    whenever authority, nonce, or dispatch-health changes.  The
    ``activation_epoch`` gating check uses this unified counter so that any
    authority-invalidating event requires a fresh activation request.

dispatch_enabled (derived)
    ``dispatch_enabled`` is **derived** — it is never stored as primary mutable
    state.  The :attr:`StartupConvergenceSnapshot.dispatch_enabled` property
    returns ``True`` iff ``runtime_authority_state == EXECUTING``.  The
    coordinator only tracks ``last_committed_snapshot_version`` as the durable
    latch; the derived property is recomputed on every snapshot read.

FAIL_SAFE (3-tier)
    :class:`FailSafeTier` normalises failure severity into three tiers:
    WARN (degraded-operational), HALT (trading stopped, recoverable), and
    SHUTDOWN (restart required).  The coordinator exposes
    :meth:`StartupCoordinator.record_fail_safe` to enter a specific tier.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Deque, Dict, Optional

logger = logging.getLogger("nija.startup_coordinator")


class StartupEvent(str, Enum):
    LOCK_ACQUIRED = "LOCK_ACQUIRED"
    HEALTH_BOUND = "HEALTH_BOUND"
    ENV_VERIFIED = "ENV_VERIFIED"
    MODE_GATED = "MODE_GATED"
    BROKER_CONNECTED = "BROKER_CONNECTED"
    BALANCE_HYDRATED = "BALANCE_HYDRATED"
    CAPABILITY_VERIFIED = "CAPABILITY_VERIFIED"
    STARTUP_VALIDATED = "STARTUP_VALIDATED"
    CAPITAL_REFRESH_STARTED = "CAPITAL_REFRESH_STARTED"
    CAPITAL_REFRESHED = "CAPITAL_REFRESHED"
    READINESS_CHANGED = "READINESS_CHANGED"
    THREADS_LAUNCHED = "THREADS_LAUNCHED"
    THREADS_CONFIRMED_RUNNING = "THREADS_CONFIRMED_RUNNING"
    ACTIVATION_REQUESTED = "ACTIVATION_REQUESTED"
    AUTHORITY_REFRESHED = "AUTHORITY_REFRESHED"
    KILL_SWITCH_CHANGED = "KILL_SWITCH_CHANGED"
    NONCE_STATUS_CHANGED = "NONCE_STATUS_CHANGED"
    DISPATCH_HEALTH_CHANGED = "DISPATCH_HEALTH_CHANGED"
    DISPATCH_ENABLED = "DISPATCH_ENABLED"


class FailSafeTier(int, Enum):
    """3-tier severity model for FAIL_SAFE semantics.

    Tier 1 – WARN
        System is degraded but still operational.  Alerts are raised and
        non-critical subsystems may be suspended, but trading continues.

    Tier 2 – HALT
        Trading is stopped.  The failure is recoverable via operator
        intervention (e.g. restarting a subsystem, re-enabling a kill switch).
        The process stays alive waiting for recovery.

    Tier 3 – SHUTDOWN
        Unrecoverable failure.  The process must be restarted from scratch.
        All dispatch is permanently blocked until restart completes.
    """

    WARN = 1
    """Degraded-operational — trading continues with alerts."""

    HALT = 2
    """Trading halted — recoverable with operator intervention."""

    SHUTDOWN = 3
    """Unrecoverable — requires full process restart."""


class StartupCoordinatorState(str, Enum):
    BOOT_INIT = "BOOT_INIT"
    LOCKED = "LOCKED"
    HEALTHY = "HEALTHY"
    ENV_READY = "ENV_READY"
    MODE_READY = "MODE_READY"
    BROKER_READY = "BROKER_READY"
    BALANCE_READY = "BALANCE_READY"
    CAPABILITY_READY = "CAPABILITY_READY"
    PREFLIGHT_READY = "PREFLIGHT_READY"
    CAPITAL_PENDING = "CAPITAL_PENDING"
    CAPITAL_READY = "CAPITAL_READY"
    INIT_COMMITTED = "INIT_COMMITTED"
    THREADS_PENDING = "THREADS_PENDING"
    SUPERVISED_RUNNING = "SUPERVISED_RUNNING"
    ACTIVATION_ARMED = "ACTIVATION_ARMED"
    ACTIVATION_CONVERGING = "ACTIVATION_CONVERGING"
    LIVE_COMMITTED = "LIVE_COMMITTED"
    DISPATCH_ENABLED = "DISPATCH_ENABLED"
    DEGRADED_RETRY = "DEGRADED_RETRY"
    # 3-tier FAIL_SAFE model (item 4)
    FAIL_SAFE_WARN = "FAIL_SAFE_WARN"
    """Tier 1: degraded-operational — trading continues with alerts."""
    FAIL_SAFE_HALT = "FAIL_SAFE_HALT"
    """Tier 2: trading halted — recoverable with operator intervention."""
    FAIL_SAFE_SHUTDOWN = "FAIL_SAFE_SHUTDOWN"
    """Tier 3: unrecoverable — requires full process restart."""
    # Legacy alias kept for backward compatibility with existing callers.
    FAIL_SAFE = "FAIL_SAFE"
    RESTART_REQUIRED = "RESTART_REQUIRED"


class RuntimeAuthorityState(str, Enum):
    BOOT = "BOOT"
    STANDBY = "STANDBY"
    READY = "READY"
    AUTHORIZED = "AUTHORIZED"
    EXECUTING = "EXECUTING"
    DEGRADED = "DEGRADED"


class LifecyclePhase(str, Enum):
    """Coarse runtime lifecycle phase used as the top-level execution gate.

    Phase is derived from :class:`RuntimeAuthorityState` and acts as the
    primary control primitive that gates execution, control, and reconciliation
    across the whole system.

    BOOT
        Early startup: broker connection, capital hydration, and bootstrap
        reconciliation only.  No strategy execution or live dispatch.

    WARM
        Authority has converged (all prerequisites met) but the activation
        commit has not yet been recorded.  Control logic and reconciliation
        may proceed; live order dispatch remains blocked.

    LIVE
        Dispatch commit is in place and the runtime is trading.  Full
        execution, control, and reconciliation are permitted subject to the
        lower-level gates in :func:`can_execute`.
    """

    BOOT = "BOOT"
    WARM = "WARM"
    LIVE = "LIVE"


def _compute_lifecycle_phase(runtime_authority_state: str) -> LifecyclePhase:
    """Derive the coarse :class:`LifecyclePhase` from a runtime authority state string.

    Mapping:
    - ``EXECUTING``  → :attr:`LifecyclePhase.LIVE`  — dispatch committed, trading active
    - ``AUTHORIZED`` → :attr:`LifecyclePhase.WARM`  — all prerequisites met, awaiting commit
    - ``READY``      → :attr:`LifecyclePhase.WARM`  — prerequisites ready, converging
    - anything else  → :attr:`LifecyclePhase.BOOT`  — BOOT / STANDBY / DEGRADED
    """
    if runtime_authority_state == RuntimeAuthorityState.EXECUTING.value:
        return LifecyclePhase.LIVE
    if runtime_authority_state in {
        RuntimeAuthorityState.AUTHORIZED.value,
        RuntimeAuthorityState.READY.value,
    }:
        return LifecyclePhase.WARM
    return LifecyclePhase.BOOT


_EARLY_BOOTSTRAP_STATES = frozenset(
    {
        "BOOT_INIT",
        "LOCK_ACQUIRED",
        "HEALTH_BOUND",
        "ENV_VERIFIED",
        "MODE_GATED",
        "unknown",
    }
)

_DEGRADED_BOOTSTRAP_STATES = frozenset(
    {
        "BOOT_FAILED_RETRY",
        "EXTERNAL_RESTART_REQUIRED",
    }
)

_RUNTIME_ALLOWED_TRANSITIONS = {
    RuntimeAuthorityState.BOOT: {
        RuntimeAuthorityState.STANDBY,
        RuntimeAuthorityState.READY,
        RuntimeAuthorityState.AUTHORIZED,
        RuntimeAuthorityState.EXECUTING,
        RuntimeAuthorityState.DEGRADED,
    },
    RuntimeAuthorityState.STANDBY: {
        RuntimeAuthorityState.BOOT,
        RuntimeAuthorityState.READY,
        RuntimeAuthorityState.AUTHORIZED,
        RuntimeAuthorityState.EXECUTING,
        RuntimeAuthorityState.DEGRADED,
    },
    RuntimeAuthorityState.READY: {
        RuntimeAuthorityState.STANDBY,
        RuntimeAuthorityState.AUTHORIZED,
        RuntimeAuthorityState.EXECUTING,
        RuntimeAuthorityState.DEGRADED,
    },
    RuntimeAuthorityState.AUTHORIZED: {
        RuntimeAuthorityState.READY,
        RuntimeAuthorityState.EXECUTING,
        RuntimeAuthorityState.DEGRADED,
    },
    RuntimeAuthorityState.EXECUTING: {
        RuntimeAuthorityState.AUTHORIZED,
        RuntimeAuthorityState.READY,
        RuntimeAuthorityState.STANDBY,
        RuntimeAuthorityState.DEGRADED,
    },
    RuntimeAuthorityState.DEGRADED: {
        RuntimeAuthorityState.BOOT,
        RuntimeAuthorityState.STANDBY,
        RuntimeAuthorityState.READY,
        RuntimeAuthorityState.AUTHORIZED,
        RuntimeAuthorityState.EXECUTING,
    },
}


@dataclass(frozen=True)
class StartupConvergenceSnapshot:
    snapshot_version: int
    coordinator_state: str
    bootstrap_state: str
    capital_state: str
    capital_version: int
    readiness_version: int
    readiness_table: Dict[str, bool]
    capital_hydrated: bool
    capital_balance: Optional[float]
    capital_stale: bool
    authority_version: int
    global_epoch: int
    """Unified monotonic epoch — advances on authority/nonce/dispatch-health changes."""
    authority_ready: bool
    authority_status: Dict[str, Any]
    nonce_version: int
    nonce_ready: bool
    dispatch_health_version: int
    dispatch_health_ready: bool
    threads_launched: int
    threads_confirmed_running: bool
    trading_state: str
    activation_intent: bool
    activation_epoch: int
    kill_switch_active: bool
    last_committed_snapshot_version: int
    runtime_authority_state: str
    runtime_authority_reason: str

    @property
    def dispatch_enabled(self) -> bool:
        """Derived: True iff the runtime authority state is EXECUTING.

        ``dispatch_enabled`` is **not** stored as primary mutable state.  It
        is recomputed from ``runtime_authority_state`` on every snapshot read,
        ensuring that any authority regression is immediately reflected without
        requiring an explicit flag reset.
        """
        return self.runtime_authority_state == RuntimeAuthorityState.EXECUTING.value

    @property
    def pending_readiness(self) -> list[str]:
        return sorted(key for key, value in self.readiness_table.items() if not value)

    @property
    def trading_authority(self) -> bool:
        return self.runtime_authority_state in {
            RuntimeAuthorityState.AUTHORIZED.value,
            RuntimeAuthorityState.EXECUTING.value,
        }

    @property
    def execution_permitted(self) -> bool:
        return self.runtime_authority_state == RuntimeAuthorityState.EXECUTING.value

    @property
    def lifecycle_phase(self) -> str:
        """Coarse lifecycle phase derived from ``runtime_authority_state``.

        Returns the string value of :class:`LifecyclePhase`:

        * ``"LIVE"``  — EXECUTING state (dispatch committed, trading active)
        * ``"WARM"``  — AUTHORIZED or READY (converging, no execution yet)
        * ``"BOOT"``  — everything else (early startup, standby, degraded)

        This is the **top-level execution gate**.  Callers that need to check
        whether order dispatch is even plausible should test::

            if snapshot.lifecycle_phase != LifecyclePhase.LIVE.value:
                deny(...)
        """
        return _compute_lifecycle_phase(self.runtime_authority_state).value


@dataclass(frozen=True)
class ActivationDecision:
    allowed: bool
    target_state: StartupCoordinatorState
    reason: str
    snapshot_version: int


@dataclass
class _RuntimeState:
    coordinator_state: StartupCoordinatorState = StartupCoordinatorState.BOOT_INIT
    event_version: int = 0
    bootstrap_state: str = "BOOT_INIT"
    capital_state: str = "BOOT_INIT"
    capital_version: int = 0
    readiness_version: int = 0
    readiness_table: Dict[str, bool] = field(default_factory=dict)
    capital_hydrated: bool = False
    capital_balance: Optional[float] = None
    capital_stale: bool = True
    authority_version: int = 0
    global_epoch: int = 0
    """Unified monotonic epoch — advances on any authority-invalidating change."""
    authority_ready: bool = False
    authority_status: Dict[str, Any] = field(default_factory=dict)
    nonce_version: int = 0
    nonce_ready: bool = False
    dispatch_health_version: int = 0
    dispatch_health_ready: bool = False
    threads_launched: int = 0
    threads_confirmed_running: bool = False
    activation_requested: bool = False
    activation_epoch: int = 0
    kill_switch_active: bool = False
    last_committed_snapshot_version: int = 0
    runtime_authority_state: RuntimeAuthorityState = RuntimeAuthorityState.BOOT
    runtime_authority_reason: str = "boot_init"


class StartupCoordinator:
    """Single serialized owner for startup convergence state."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._history: Deque[Dict[str, Any]] = deque(maxlen=256)
        self._runtime = _RuntimeState()

    def reset_for_testing(self) -> None:
        with self._lock:
            self._history.clear()
            self._runtime = _RuntimeState()

    def _publish_locked(self, event: StartupEvent, payload: Optional[Dict[str, Any]] = None) -> int:
        payload = dict(payload or {})
        self._runtime.event_version += 1
        version = self._runtime.event_version
        self._history.append(
            {
                "version": version,
                "event": event.value,
                "payload": payload,
                "state": self._runtime.coordinator_state.value,
            }
        )
        return version

    def record_bootstrap_state(self, state: str) -> int:
        with self._lock:
            state = str(state or "unknown")
            self._runtime.bootstrap_state = state
            event_map = {
                "LOCK_ACQUIRED": (StartupEvent.LOCK_ACQUIRED, StartupCoordinatorState.LOCKED),
                "HEALTH_BOUND": (StartupEvent.HEALTH_BOUND, StartupCoordinatorState.HEALTHY),
                "ENV_VERIFIED": (StartupEvent.ENV_VERIFIED, StartupCoordinatorState.ENV_READY),
                "MODE_GATED": (StartupEvent.MODE_GATED, StartupCoordinatorState.MODE_READY),
                "PLATFORM_READY": (StartupEvent.BROKER_CONNECTED, StartupCoordinatorState.BROKER_READY),
                "BALANCE_HYDRATED": (StartupEvent.BALANCE_HYDRATED, StartupCoordinatorState.BALANCE_READY),
                "CAPABILITY_VERIFIED": (StartupEvent.CAPABILITY_VERIFIED, StartupCoordinatorState.CAPABILITY_READY),
                "STARTUP_VALIDATED": (StartupEvent.STARTUP_VALIDATED, StartupCoordinatorState.PREFLIGHT_READY),
                "CAPITAL_REFRESHING": (StartupEvent.CAPITAL_REFRESH_STARTED, StartupCoordinatorState.CAPITAL_PENDING),
                "CAPITAL_READY": (StartupEvent.CAPITAL_REFRESHED, StartupCoordinatorState.CAPITAL_READY),
                "INIT_COMPLETE": (StartupEvent.READINESS_CHANGED, StartupCoordinatorState.INIT_COMMITTED),
                "THREADS_STARTING": (StartupEvent.THREADS_LAUNCHED, StartupCoordinatorState.THREADS_PENDING),
                "RUNNING_SUPERVISED": (
                    StartupEvent.THREADS_CONFIRMED_RUNNING,
                    StartupCoordinatorState.SUPERVISED_RUNNING,
                ),
                "BOOT_FAILED_RETRY": (StartupEvent.CAPITAL_REFRESH_STARTED, StartupCoordinatorState.DEGRADED_RETRY),
                "EXTERNAL_RESTART_REQUIRED": (
                    StartupEvent.CAPITAL_REFRESH_STARTED,
                    StartupCoordinatorState.RESTART_REQUIRED,
                ),
            }
            event, target = event_map.get(
                state,
                (StartupEvent.READINESS_CHANGED, self._runtime.coordinator_state),
            )
            version = self._publish_locked(event, {"bootstrap_state": state})
            self._runtime.coordinator_state = target
            if state == "RUNNING_SUPERVISED":
                self._runtime.threads_confirmed_running = True
            return version

    def record_readiness(
        self,
        *,
        key: str,
        value: bool,
        version: int,
        table: Dict[str, bool],
    ) -> int:
        with self._lock:
            self._runtime.readiness_version = max(int(version or 0), self._runtime.readiness_version)
            self._runtime.readiness_table = dict(table)
            event_version = self._publish_locked(
                StartupEvent.READINESS_CHANGED,
                {"key": key, "value": bool(value), "readiness_version": self._runtime.readiness_version},
            )
            if table.get("bootstrap_ready"):
                self._runtime.coordinator_state = StartupCoordinatorState.INIT_COMMITTED
            if key == "broker_connected" and value:
                self._runtime.coordinator_state = StartupCoordinatorState.BROKER_READY
            return event_version

    def record_capital_state(
        self,
        *,
        state: str,
        hydrated: bool,
        balance: Optional[float],
        stale: bool,
    ) -> int:
        with self._lock:
            changed = (
                self._runtime.capital_state != state
                or self._runtime.capital_hydrated != bool(hydrated)
                or self._runtime.capital_balance != balance
                or self._runtime.capital_stale != bool(stale)
            )
            if changed:
                self._runtime.capital_version += 1
            self._runtime.capital_state = str(state or "unknown")
            self._runtime.capital_hydrated = bool(hydrated)
            self._runtime.capital_balance = balance
            self._runtime.capital_stale = bool(stale)
            event_version = self._publish_locked(
                StartupEvent.CAPITAL_REFRESHED,
                {
                    "capital_state": self._runtime.capital_state,
                    "capital_version": self._runtime.capital_version,
                    "hydrated": self._runtime.capital_hydrated,
                    "balance": self._runtime.capital_balance,
                    "stale": self._runtime.capital_stale,
                },
            )
            self._runtime.coordinator_state = (
                StartupCoordinatorState.CAPITAL_READY
                if self._runtime.capital_state == "RUNNING" and self._runtime.capital_hydrated
                else StartupCoordinatorState.CAPITAL_PENDING
            )
            return event_version

    def record_authority(self, *, ready: bool, status: Optional[Dict[str, Any]] = None) -> int:
        with self._lock:
            status = dict(status or {})
            if self._runtime.authority_ready != bool(ready) or self._runtime.authority_status != status:
                self._runtime.authority_version += 1
                self._runtime.global_epoch += 1
                self._runtime.last_committed_snapshot_version = 0
            self._runtime.authority_ready = bool(ready)
            self._runtime.authority_status = status
            return self._publish_locked(
                StartupEvent.AUTHORITY_REFRESHED,
                {
                    "ready": self._runtime.authority_ready,
                    "authority_version": self._runtime.authority_version,
                    "global_epoch": self._runtime.global_epoch,
                },
            )

    def record_nonce_status(self, *, ready: bool, detail: str = "") -> int:
        with self._lock:
            if self._runtime.nonce_ready != bool(ready):
                self._runtime.nonce_version += 1
                self._runtime.global_epoch += 1
                self._runtime.last_committed_snapshot_version = 0
            self._runtime.nonce_ready = bool(ready)
            return self._publish_locked(
                StartupEvent.NONCE_STATUS_CHANGED,
                {
                    "ready": self._runtime.nonce_ready,
                    "detail": detail,
                    "nonce_version": self._runtime.nonce_version,
                    "global_epoch": self._runtime.global_epoch,
                },
            )

    def record_dispatch_health(self, *, ready: bool, detail: str = "") -> int:
        with self._lock:
            if self._runtime.dispatch_health_ready != bool(ready):
                self._runtime.dispatch_health_version += 1
                self._runtime.global_epoch += 1
                self._runtime.last_committed_snapshot_version = 0
            self._runtime.dispatch_health_ready = bool(ready)
            return self._publish_locked(
                StartupEvent.DISPATCH_HEALTH_CHANGED,
                {
                    "ready": self._runtime.dispatch_health_ready,
                    "detail": detail,
                    "dispatch_health_version": self._runtime.dispatch_health_version,
                    "global_epoch": self._runtime.global_epoch,
                },
            )

    def record_threads_launched(self, count: int) -> int:
        with self._lock:
            self._runtime.threads_launched = max(0, int(count or 0))
            self._runtime.coordinator_state = StartupCoordinatorState.THREADS_PENDING
            return self._publish_locked(
                StartupEvent.THREADS_LAUNCHED,
                {"count": self._runtime.threads_launched},
            )

    def record_threads_confirmed_running(self, *, bootstrap_state: Optional[str] = None) -> int:
        with self._lock:
            if bootstrap_state:
                self._runtime.bootstrap_state = bootstrap_state
            self._runtime.threads_confirmed_running = True
            self._runtime.coordinator_state = StartupCoordinatorState.SUPERVISED_RUNNING
            return self._publish_locked(
                StartupEvent.THREADS_CONFIRMED_RUNNING,
                {"bootstrap_state": self._runtime.bootstrap_state},
            )

    def record_activation_requested(self, *, requested: bool = True, source: str = "") -> int:
        with self._lock:
            self._runtime.activation_requested = bool(requested)
            if self._runtime.activation_requested:
                self._runtime.activation_epoch = self._runtime.global_epoch
            if self._runtime.coordinator_state not in {
                StartupCoordinatorState.DISPATCH_ENABLED,
                StartupCoordinatorState.LIVE_COMMITTED,
            }:
                self._runtime.coordinator_state = StartupCoordinatorState.ACTIVATION_ARMED
            return self._publish_locked(
                StartupEvent.ACTIVATION_REQUESTED,
                {
                    "requested": self._runtime.activation_requested,
                    "source": source,
                    "activation_epoch": self._runtime.activation_epoch,
                },
            )

    def record_kill_switch(self, *, active: bool) -> int:
        with self._lock:
            self._runtime.kill_switch_active = bool(active)
            if self._runtime.kill_switch_active:
                # Kill-switch activation is always a SHUTDOWN-tier event.
                self._runtime.coordinator_state = StartupCoordinatorState.FAIL_SAFE_SHUTDOWN
            return self._publish_locked(
                StartupEvent.KILL_SWITCH_CHANGED,
                {"active": self._runtime.kill_switch_active},
            )

    def _reconcile_runtime_authority_locked(
        self,
        *,
        trading_state: str,
        activation_intent: bool,
    ) -> tuple[RuntimeAuthorityState, str]:
        bootstrap_state = str(self._runtime.bootstrap_state or "unknown")
        capital_state = str(self._runtime.capital_state or "unknown")
        trading_state = str(trading_state or "").strip() or "OFF"
        activation_intent = bool(activation_intent or self._runtime.activation_requested)
        pending_readiness = sorted(
            key for key, value in self._runtime.readiness_table.items() if not value
        )
        prereqs_ready = bool(
            bootstrap_state == "RUNNING_SUPERVISED"
            and capital_state == "RUNNING"
            and self._runtime.threads_launched > 0
            and self._runtime.threads_confirmed_running
            and self._runtime.capital_hydrated
            and self._runtime.capital_balance is not None
            and not self._runtime.capital_stale
            and not pending_readiness
        )
        authority_converged = bool(
            prereqs_ready
            and activation_intent
            and self._runtime.authority_ready
            and self._runtime.nonce_ready
            and self._runtime.dispatch_health_ready
            and not self._runtime.kill_switch_active
            and self._runtime.activation_epoch == self._runtime.global_epoch
        )
        # dispatch_enabled is derived: True iff a valid activation commit exists.
        # This replaces the former primary flag with a computed condition so that
        # any authority-invalidating change (which resets last_committed_snapshot_version)
        # automatically revokes execution authority.
        dispatch_committed = self._runtime.last_committed_snapshot_version > 0
        executing = bool(
            authority_converged
            and dispatch_committed
            and trading_state == "LIVE_ACTIVE"
        )
        severe_degradation = None
        if self._runtime.kill_switch_active:
            severe_degradation = "kill_switch_active"
        elif trading_state == "EMERGENCY_STOP":
            severe_degradation = "trading_state_emergency_stop"
        elif bootstrap_state in _DEGRADED_BOOTSTRAP_STATES:
            severe_degradation = f"bootstrap_state={bootstrap_state}"
        elif self._runtime.coordinator_state in {
            StartupCoordinatorState.FAIL_SAFE,
            StartupCoordinatorState.FAIL_SAFE_WARN,
            StartupCoordinatorState.FAIL_SAFE_HALT,
            StartupCoordinatorState.FAIL_SAFE_SHUTDOWN,
            StartupCoordinatorState.RESTART_REQUIRED,
            StartupCoordinatorState.DEGRADED_RETRY,
        }:
            severe_degradation = f"coordinator_state={self._runtime.coordinator_state.value}"
        elif self._runtime.capital_stale:
            severe_degradation = "capital_stale"
        elif activation_intent and self._runtime.activation_epoch != self._runtime.global_epoch:
            severe_degradation = "global_epoch_stale"
        elif dispatch_committed and not authority_converged:
            severe_degradation = "dispatch_committed_without_authority"
        elif (
            self._runtime.runtime_authority_state in {
                RuntimeAuthorityState.AUTHORIZED,
                RuntimeAuthorityState.EXECUTING,
            }
            and activation_intent
            and not authority_converged
        ):
            severe_degradation = "authority_regressed"
        elif self._runtime.runtime_authority_state == RuntimeAuthorityState.EXECUTING and not (
            dispatch_committed and trading_state == "LIVE_ACTIVE"
        ):
            severe_degradation = "execution_revoked"

        if severe_degradation:
            target_state = RuntimeAuthorityState.DEGRADED
            reason = severe_degradation
        elif bootstrap_state in _EARLY_BOOTSTRAP_STATES:
            target_state = RuntimeAuthorityState.BOOT
            reason = f"bootstrap_state={bootstrap_state}"
        elif executing:
            target_state = RuntimeAuthorityState.EXECUTING
            reason = "dispatch_committed"
        elif authority_converged:
            target_state = RuntimeAuthorityState.AUTHORIZED
            reason = "authority_converged"
        elif prereqs_ready:
            target_state = RuntimeAuthorityState.READY
            if not activation_intent:
                reason = "activation_intent_missing"
            elif not self._runtime.authority_ready:
                reason = "authority_not_ready"
            elif not self._runtime.nonce_ready:
                reason = "nonce_not_ready"
            elif not self._runtime.dispatch_health_ready:
                reason = "dispatch_health_not_ready"
            else:
                reason = "awaiting_authority_convergence"
        else:
            target_state = RuntimeAuthorityState.STANDBY
            if bootstrap_state != "RUNNING_SUPERVISED":
                reason = f"bootstrap_state={bootstrap_state}"
            elif capital_state != "RUNNING":
                reason = f"capital_state={capital_state}"
            elif self._runtime.threads_launched <= 0 or not self._runtime.threads_confirmed_running:
                reason = "threads_not_running"
            elif pending_readiness:
                reason = f"readiness_pending={','.join(pending_readiness)}"
            elif not self._runtime.capital_hydrated:
                reason = "capital_not_hydrated"
            elif self._runtime.capital_balance is None:
                reason = "capital_balance_unknown"
            else:
                reason = "standing_by"

        current = self._runtime.runtime_authority_state
        if target_state != current and target_state not in _RUNTIME_ALLOWED_TRANSITIONS.get(current, set()):
            target_state = RuntimeAuthorityState.DEGRADED
            reason = f"invalid_transition={current.value}->{target_state.value}"

        self._runtime.runtime_authority_state = target_state
        self._runtime.runtime_authority_reason = reason
        return target_state, reason

    def build_snapshot(self, *, trading_state: str, activation_intent: bool) -> StartupConvergenceSnapshot:
        with self._lock:
            runtime_authority_state, runtime_authority_reason = self._reconcile_runtime_authority_locked(
                trading_state=str(trading_state),
                activation_intent=bool(activation_intent),
            )
            return StartupConvergenceSnapshot(
                snapshot_version=self._runtime.event_version,
                coordinator_state=self._runtime.coordinator_state.value,
                bootstrap_state=self._runtime.bootstrap_state,
                capital_state=self._runtime.capital_state,
                capital_version=self._runtime.capital_version,
                readiness_version=self._runtime.readiness_version,
                readiness_table=dict(self._runtime.readiness_table),
                capital_hydrated=self._runtime.capital_hydrated,
                capital_balance=self._runtime.capital_balance,
                capital_stale=self._runtime.capital_stale,
                authority_version=self._runtime.authority_version,
                global_epoch=self._runtime.global_epoch,
                authority_ready=self._runtime.authority_ready,
                authority_status=dict(self._runtime.authority_status),
                nonce_version=self._runtime.nonce_version,
                nonce_ready=self._runtime.nonce_ready,
                dispatch_health_version=self._runtime.dispatch_health_version,
                dispatch_health_ready=self._runtime.dispatch_health_ready,
                threads_launched=self._runtime.threads_launched,
                threads_confirmed_running=self._runtime.threads_confirmed_running,
                trading_state=str(trading_state),
                activation_intent=bool(activation_intent or self._runtime.activation_requested),
                activation_epoch=self._runtime.activation_epoch,
                kill_switch_active=self._runtime.kill_switch_active,
                last_committed_snapshot_version=self._runtime.last_committed_snapshot_version,
                runtime_authority_state=runtime_authority_state.value,
                runtime_authority_reason=runtime_authority_reason,
            )

    def evaluate_activation(self, snapshot: StartupConvergenceSnapshot) -> ActivationDecision:
        with self._lock:
            if snapshot.runtime_authority_state == RuntimeAuthorityState.EXECUTING.value:
                self._runtime.coordinator_state = StartupCoordinatorState.DISPATCH_ENABLED
                return ActivationDecision(
                    True,
                    StartupCoordinatorState.DISPATCH_ENABLED,
                    snapshot.runtime_authority_reason or "already_enabled",
                    snapshot.snapshot_version,
                )

            if snapshot.runtime_authority_state == RuntimeAuthorityState.AUTHORIZED.value:
                target = StartupCoordinatorState.DISPATCH_ENABLED
                reason = snapshot.runtime_authority_reason or "runtime_authorized"
            elif snapshot.runtime_authority_state == RuntimeAuthorityState.DEGRADED.value:
                target = StartupCoordinatorState.DEGRADED_RETRY
                reason = snapshot.runtime_authority_reason or "runtime_degraded"
            elif not snapshot.activation_intent:
                target = StartupCoordinatorState.ACTIVATION_ARMED
                reason = snapshot.runtime_authority_reason or "activation_intent_missing"
            else:
                target = StartupCoordinatorState.ACTIVATION_CONVERGING
                reason = snapshot.runtime_authority_reason or "awaiting_runtime_authority"

            self._runtime.coordinator_state = target
            return ActivationDecision(target == StartupCoordinatorState.DISPATCH_ENABLED, target, reason, snapshot.snapshot_version)

    def finalize_activation_commit(self, snapshot: StartupConvergenceSnapshot) -> int:
        with self._lock:
            self._runtime.last_committed_snapshot_version = snapshot.snapshot_version
            # dispatch_enabled is derived — not stored as primary state.
            # Setting last_committed_snapshot_version > 0 is the only durable
            # latch.  The snapshot's dispatch_enabled property computes the
            # final value from runtime_authority_state.
            self._runtime.coordinator_state = StartupCoordinatorState.LIVE_COMMITTED
            self._publish_locked(
                StartupEvent.DISPATCH_ENABLED,
                {"snapshot_version": snapshot.snapshot_version, "phase": StartupCoordinatorState.LIVE_COMMITTED.value},
            )
            self._runtime.coordinator_state = StartupCoordinatorState.DISPATCH_ENABLED
            return self._publish_locked(
                StartupEvent.DISPATCH_ENABLED,
                {"snapshot_version": snapshot.snapshot_version, "phase": StartupCoordinatorState.DISPATCH_ENABLED.value},
            )

    def record_fail_safe(self, tier: "FailSafeTier", reason: str = "") -> int:
        """Enter a FAIL_SAFE state at the specified *tier*.

        Parameters
        ----------
        tier:
            :class:`FailSafeTier` severity level.

            * ``WARN`` → :attr:`StartupCoordinatorState.FAIL_SAFE_WARN`
            * ``HALT`` → :attr:`StartupCoordinatorState.FAIL_SAFE_HALT`
            * ``SHUTDOWN`` → :attr:`StartupCoordinatorState.FAIL_SAFE_SHUTDOWN`

        reason:
            Human-readable description of why FAIL_SAFE was triggered.
        """
        _tier_to_state = {
            FailSafeTier.WARN: StartupCoordinatorState.FAIL_SAFE_WARN,
            FailSafeTier.HALT: StartupCoordinatorState.FAIL_SAFE_HALT,
            FailSafeTier.SHUTDOWN: StartupCoordinatorState.FAIL_SAFE_SHUTDOWN,
        }
        with self._lock:
            target = _tier_to_state.get(tier, StartupCoordinatorState.FAIL_SAFE_SHUTDOWN)
            self._runtime.coordinator_state = target
            return self._publish_locked(
                StartupEvent.KILL_SWITCH_CHANGED,
                {"fail_safe_tier": tier.value, "reason": reason or target.value},
            )

    def get_state(self) -> str:
        with self._lock:
            return self._runtime.coordinator_state.value

    def get_history(self) -> list[Dict[str, Any]]:
        with self._lock:
            return list(self._history)


_startup_coordinator: Optional[StartupCoordinator] = None
_startup_coordinator_lock = threading.Lock()


def get_startup_coordinator() -> StartupCoordinator:
    global _startup_coordinator
    with _startup_coordinator_lock:
        if _startup_coordinator is None:
            _startup_coordinator = StartupCoordinator()
        return _startup_coordinator


# ---------------------------------------------------------------------------
# GLOBAL_STATE — atomic snapshot model (item 1)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GlobalStateSnapshot:
    """Immutable atomic snapshot of the full runtime state across all FSMs.

    Produced by :meth:`GlobalState.capture`.  All fields are read under a
    single coordinator lock to ensure a consistent view — callers must never
    assemble global state by calling multiple methods independently.

    Attributes
    ----------
    startup:
        The :class:`StartupConvergenceSnapshot` captured at ``snapshot_ts``.
    esc_state:
        String value of the current :class:`ExecutionOrderState` (or
        ``"IDLE"`` when the ESC is not active).
    snapshot_ts:
        Monotonic timestamp (``time.monotonic()``) at which the snapshot
        was taken.  Useful for staleness checks.
    global_epoch:
        Mirrors ``startup.global_epoch`` for convenience.
    """

    startup: StartupConvergenceSnapshot
    esc_state: str
    snapshot_ts: float
    global_epoch: int

    @property
    def dispatch_enabled(self) -> bool:
        """Convenience alias: delegates to the startup snapshot."""
        return self.startup.dispatch_enabled

    @property
    def runtime_authority_state(self) -> str:
        """Convenience alias: delegates to the startup snapshot."""
        return self.startup.runtime_authority_state

    @property
    def lifecycle_phase(self) -> str:
        """Convenience alias: delegates to the startup snapshot.

        Returns the string value of :class:`LifecyclePhase` (``"BOOT"``,
        ``"WARM"``, or ``"LIVE"``).
        """
        return self.startup.lifecycle_phase


class GlobalState:
    """Singleton registry that provides atomic cross-FSM state snapshots.

    Usage::

        from bot.startup_coordinator import GLOBAL_STATE

        snapshot = GLOBAL_STATE.capture(
            trading_state="LIVE_ACTIVE",
            activation_intent=True,
        )
        if snapshot.dispatch_enabled:
            ...

    The :meth:`capture` method calls :meth:`StartupCoordinator.build_snapshot`
    under the coordinator's own lock, so the returned snapshot is always
    internally consistent.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._latest: Optional[GlobalStateSnapshot] = None

    def capture(
        self,
        *,
        trading_state: str,
        activation_intent: bool,
        esc_state: str = "IDLE",
    ) -> "GlobalStateSnapshot":
        """Build and store a new :class:`GlobalStateSnapshot`.

        Parameters
        ----------
        trading_state:
            Current trading state string (e.g. ``"LIVE_ACTIVE"``).
        activation_intent:
            Whether the operator has requested activation.
        esc_state:
            Current :class:`~bot.execution_state_controller.ExecutionOrderState`
            value string.  Defaults to ``"IDLE"``.

        Returns
        -------
        GlobalStateSnapshot
            A fully consistent, immutable snapshot of the global state.
        """
        coordinator = get_startup_coordinator()
        startup = coordinator.build_snapshot(
            trading_state=trading_state,
            activation_intent=activation_intent,
        )
        snapshot = GlobalStateSnapshot(
            startup=startup,
            esc_state=esc_state,
            snapshot_ts=time.monotonic(),
            global_epoch=startup.global_epoch,
        )
        with self._lock:
            self._latest = snapshot
        return snapshot

    def latest(self) -> Optional["GlobalStateSnapshot"]:
        """Return the most recently captured snapshot, or ``None``."""
        with self._lock:
            return self._latest


#: Module-level GLOBAL_STATE singleton.  Use :meth:`GlobalState.capture` to
#: obtain an atomic snapshot of the full runtime state.
GLOBAL_STATE = GlobalState()


__all__ = [
    "ActivationDecision",
    "FailSafeTier",
    "GlobalState",
    "GlobalStateSnapshot",
    "GLOBAL_STATE",
    "LifecyclePhase",
    "StartupConvergenceSnapshot",
    "StartupCoordinator",
    "StartupCoordinatorState",
    "StartupEvent",
    "RuntimeAuthorityState",
    "_compute_lifecycle_phase",
    "get_startup_coordinator",
]
