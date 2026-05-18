"""Deterministic startup coordinator for cross-FSM convergence."""

from __future__ import annotations

import logging
import threading
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
    FAIL_SAFE = "FAIL_SAFE"
    RESTART_REQUIRED = "RESTART_REQUIRED"


class RuntimeAuthorityState(str, Enum):
    BOOT = "BOOT"
    STANDBY = "STANDBY"
    READY = "READY"
    AUTHORIZED = "AUTHORIZED"
    EXECUTING = "EXECUTING"
    DEGRADED = "DEGRADED"


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
    authority_epoch: int
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
    dispatch_enabled: bool
    last_committed_snapshot_version: int
    runtime_authority_state: str
    runtime_authority_reason: str

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
    authority_epoch: int = 0
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
    dispatch_enabled: bool = False
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
                self._runtime.authority_epoch += 1
                self._runtime.dispatch_enabled = False
                self._runtime.last_committed_snapshot_version = 0
            self._runtime.authority_ready = bool(ready)
            self._runtime.authority_status = status
            return self._publish_locked(
                StartupEvent.AUTHORITY_REFRESHED,
                {
                    "ready": self._runtime.authority_ready,
                    "authority_version": self._runtime.authority_version,
                    "authority_epoch": self._runtime.authority_epoch,
                },
            )

    def record_nonce_status(self, *, ready: bool, detail: str = "") -> int:
        with self._lock:
            if self._runtime.nonce_ready != bool(ready):
                self._runtime.nonce_version += 1
                self._runtime.authority_epoch += 1
                self._runtime.dispatch_enabled = False
                self._runtime.last_committed_snapshot_version = 0
            self._runtime.nonce_ready = bool(ready)
            return self._publish_locked(
                StartupEvent.NONCE_STATUS_CHANGED,
                {
                    "ready": self._runtime.nonce_ready,
                    "detail": detail,
                    "nonce_version": self._runtime.nonce_version,
                    "authority_epoch": self._runtime.authority_epoch,
                },
            )

    def record_dispatch_health(self, *, ready: bool, detail: str = "") -> int:
        with self._lock:
            if self._runtime.dispatch_health_ready != bool(ready):
                self._runtime.dispatch_health_version += 1
                self._runtime.authority_epoch += 1
                self._runtime.dispatch_enabled = False
                self._runtime.last_committed_snapshot_version = 0
            self._runtime.dispatch_health_ready = bool(ready)
            return self._publish_locked(
                StartupEvent.DISPATCH_HEALTH_CHANGED,
                {
                    "ready": self._runtime.dispatch_health_ready,
                    "detail": detail,
                    "dispatch_health_version": self._runtime.dispatch_health_version,
                    "authority_epoch": self._runtime.authority_epoch,
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
                self._runtime.activation_epoch = self._runtime.authority_epoch
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
                self._runtime.coordinator_state = StartupCoordinatorState.FAIL_SAFE
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
            and self._runtime.activation_epoch == self._runtime.authority_epoch
        )
        executing = bool(
            authority_converged
            and self._runtime.dispatch_enabled
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
            StartupCoordinatorState.RESTART_REQUIRED,
            StartupCoordinatorState.DEGRADED_RETRY,
        }:
            severe_degradation = f"coordinator_state={self._runtime.coordinator_state.value}"
        elif self._runtime.capital_stale:
            severe_degradation = "capital_stale"
        elif activation_intent and self._runtime.activation_epoch != self._runtime.authority_epoch:
            severe_degradation = "authority_epoch_stale"
        elif self._runtime.dispatch_enabled and not authority_converged:
            severe_degradation = "dispatch_enabled_without_authority"
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
            self._runtime.dispatch_enabled and trading_state == "LIVE_ACTIVE"
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
            reason = "dispatch_enabled"
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
                authority_epoch=self._runtime.authority_epoch,
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
                dispatch_enabled=self._runtime.dispatch_enabled,
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
            self._runtime.dispatch_enabled = True
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


__all__ = [
    "ActivationDecision",
    "StartupConvergenceSnapshot",
    "StartupCoordinator",
    "StartupCoordinatorState",
    "StartupEvent",
    "RuntimeAuthorityState",
    "get_startup_coordinator",
]
