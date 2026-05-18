"""Formal, machine-readable state-machine specification for NIJA safety flows.

This module converts the runtime FSM design into a stable specification object
that can be validated in tests and consumed by external verification tooling.
The spec is intentionally declarative: transition graphs, invariants, and
temporal validity rules are encoded as immutable data instead of prose only.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Dict, Iterable, Mapping, Sequence

from bot.bootstrap_state_machine import BootstrapState, _VALID_TRANSITIONS as BOOTSTRAP_VALID_TRANSITIONS
from bot.capital_flow_state_machine import (
    CapitalBootstrapState,
    CapitalBootstrapStateMachine,
    CapitalRuntimeState,
    CapitalRuntimeStateMachine,
    WRITER_ID as CAPITAL_WRITER_ID,
)
from bot.execution_state_controller import ExecutionOrderState, _TERMINAL_STATES as EXECUTION_TERMINAL_STATES
from bot.nonce_fsm import _State as NonceState
from bot.nonce_fsm import _TRANSITIONS as NONCE_VALID_TRANSITIONS
from bot.startup_coordinator import StartupCoordinatorState
from bot.trading_state_machine import ExecutionProgressState, TradingState, TradingStateMachine


@dataclass(frozen=True)
class TransitionEdge:
    """Single directed edge in a state-transition graph."""

    source: str
    target: str
    guard: str

    def as_dict(self) -> Dict[str, str]:
        return {"source": self.source, "target": self.target, "guard": self.guard}


@dataclass(frozen=True)
class InvariantRule:
    """Safety property that must hold in all reachable states."""

    rule_id: str
    expression: str
    intent: str

    def as_dict(self) -> Dict[str, str]:
        return {
            "rule_id": self.rule_id,
            "expression": self.expression,
            "intent": self.intent,
        }


@dataclass(frozen=True)
class TemporalRule:
    """Liveness or ordering property expressed as a temporal formula."""

    rule_id: str
    formula: str
    intent: str

    def as_dict(self) -> Dict[str, str]:
        return {
            "rule_id": self.rule_id,
            "formula": self.formula,
            "intent": self.intent,
        }


@dataclass(frozen=True)
class MachineSpec:
    """Formal specification for a single finite state machine."""

    name: str
    initial_state: str
    states: tuple[str, ...]
    terminal_states: tuple[str, ...]
    transitions: tuple[TransitionEdge, ...]
    invariants: tuple[InvariantRule, ...]
    temporal_rules: tuple[TemporalRule, ...]

    def transition_map(self) -> Dict[str, tuple[str, ...]]:
        graph: Dict[str, list[str]] = {}
        for edge in self.transitions:
            if edge.source == "*":
                continue
            graph.setdefault(edge.source, []).append(edge.target)
        return {source: tuple(targets) for source, targets in graph.items()}

    def as_dict(self) -> Dict[str, object]:
        return {
            "name": self.name,
            "initial_state": self.initial_state,
            "states": list(self.states),
            "terminal_states": list(self.terminal_states),
            "transitions": [edge.as_dict() for edge in self.transitions],
            "invariants": [rule.as_dict() for rule in self.invariants],
            "temporal_rules": [rule.as_dict() for rule in self.temporal_rules],
        }


@dataclass(frozen=True)
class FormalStateMachineSpec:
    """Repository-wide formal state-machine contract."""

    machines: tuple[MachineSpec, ...]
    cross_machine_invariants: tuple[InvariantRule, ...]
    temporal_rules: tuple[TemporalRule, ...]

    def machine(self, name: str) -> MachineSpec:
        for machine in self.machines:
            if machine.name == name:
                return machine
        raise KeyError(name)

    def as_dict(self) -> Dict[str, object]:
        return {
            "machines": [machine.as_dict() for machine in self.machines],
            "cross_machine_invariants": [rule.as_dict() for rule in self.cross_machine_invariants],
            "temporal_rules": [rule.as_dict() for rule in self.temporal_rules],
        }


def _enum_names(enum_cls: type) -> tuple[str, ...]:
    return tuple(member.value for member in enum_cls)


def _edges_from_transition_map(
    transition_map: Mapping[object, Sequence[object]],
    *,
    guards: Mapping[tuple[str, str], str] | None = None,
) -> tuple[TransitionEdge, ...]:
    edges = []
    guard_map = guards or {}
    for source, targets in transition_map.items():
        source_name = getattr(source, "value", str(source))
        for target in targets:
            target_name = getattr(target, "value", str(target))
            edges.append(
                TransitionEdge(
                    source=source_name,
                    target=target_name,
                    guard=guard_map.get((source_name, target_name), "implementation-defined legal transition"),
                )
            )
    return tuple(edges)


def _startup_coordinator_spec() -> MachineSpec:
    states = _enum_names(StartupCoordinatorState)
    transitions = (
        TransitionEdge("BOOT_INIT", "LOCKED", "record_bootstrap_state(LOCK_ACQUIRED)"),
        TransitionEdge("LOCKED", "HEALTHY", "record_bootstrap_state(HEALTH_BOUND)"),
        TransitionEdge("HEALTHY", "ENV_READY", "record_bootstrap_state(ENV_VERIFIED)"),
        TransitionEdge("ENV_READY", "MODE_READY", "record_bootstrap_state(MODE_GATED)"),
        TransitionEdge("MODE_READY", "BROKER_READY", "record_bootstrap_state(PLATFORM_READY)"),
        TransitionEdge("BROKER_READY", "BALANCE_READY", "record_bootstrap_state(BALANCE_HYDRATED)"),
        TransitionEdge("BALANCE_READY", "CAPABILITY_READY", "record_bootstrap_state(CAPABILITY_VERIFIED)"),
        TransitionEdge("CAPABILITY_READY", "PREFLIGHT_READY", "record_bootstrap_state(STARTUP_VALIDATED)"),
        TransitionEdge("PREFLIGHT_READY", "CAPITAL_PENDING", "record_bootstrap_state(CAPITAL_REFRESHING)"),
        TransitionEdge("CAPITAL_PENDING", "CAPITAL_READY", "record_bootstrap_state(CAPITAL_READY)"),
        TransitionEdge("CAPITAL_READY", "INIT_COMMITTED", "readiness_table[bootstrap_ready] becomes true"),
        TransitionEdge("INIT_COMMITTED", "THREADS_PENDING", "record_threads_launched(count>0)"),
        TransitionEdge(
            "THREADS_PENDING",
            "SUPERVISED_RUNNING",
            "record_threads_confirmed_running(bootstrap_state=RUNNING_SUPERVISED)",
        ),
        TransitionEdge("SUPERVISED_RUNNING", "ACTIVATION_ARMED", "record_activation_requested(requested=true)"),
        TransitionEdge("ACTIVATION_ARMED", "ACTIVATION_CONVERGING", "activation intent present but P_dispatch unresolved"),
        TransitionEdge("ACTIVATION_CONVERGING", "DEGRADED_RETRY", "authority_epoch stale or subsystem not ready"),
        TransitionEdge("ACTIVATION_CONVERGING", "DISPATCH_ENABLED", "evaluate_activation(snapshot).allowed"),
        TransitionEdge("DISPATCH_ENABLED", "LIVE_COMMITTED", "finalize_activation_commit(snapshot)"),
        TransitionEdge("LIVE_COMMITTED", "DISPATCH_ENABLED", "evaluate_activation(snapshot already committed)"),
        TransitionEdge("*", "FAIL_SAFE", "kill_switch_active"),
        TransitionEdge("*", "DEGRADED_RETRY", "capital_stale or authority_not_ready or nonce_not_ready"),
        TransitionEdge("*", "RESTART_REQUIRED", "record_bootstrap_state(EXTERNAL_RESTART_REQUIRED)"),
    )
    invariants = (
        InvariantRule(
            "I_SC_1",
            "dispatch_enabled => coordinator_state in {LIVE_COMMITTED, DISPATCH_ENABLED}",
            "Dispatch authority is only exposed from a committed live snapshot.",
        ),
        InvariantRule(
            "I_SC_2",
            "authority/nonce/dispatch_health change => authority_epoch increments and dispatch_enabled becomes false",
            "Any authority invalidation must revoke dispatch before the next order path runs.",
        ),
        InvariantRule(
            "I_SC_3",
            "coordinator_state = FAIL_SAFE => kill_switch_active",
            "Kill-switch driven fail-safe is explicit and never silent.",
        ),
        InvariantRule(
            "I_SC_4",
            "coordinator_state = DISPATCH_ENABLED => activation_epoch = authority_epoch",
            "Stale activation intent can never enable dispatch.",
        ),
    )
    temporal_rules = (
        TemporalRule(
            "T_SC_1",
            "[](authority_epoch changes => <> dispatch_enabled = false)",
            "Dispatch is eventually revoked after any authority change.",
        ),
        TemporalRule(
            "T_SC_2",
            "[](kill_switch_active => <> coordinator_state = FAIL_SAFE)",
            "Kill-switch activation must deterministically force fail-safe.",
        ),
        TemporalRule(
            "T_SC_3",
            "<> P_dispatch => <> coordinator_state = DISPATCH_ENABLED",
            "Once all prerequisites converge, dispatch eventually becomes enabled.",
        ),
    )
    return MachineSpec(
        name="startup_coordinator",
        initial_state=StartupCoordinatorState.BOOT_INIT.value,
        states=states,
        terminal_states=(StartupCoordinatorState.FAIL_SAFE.value, StartupCoordinatorState.RESTART_REQUIRED.value),
        transitions=transitions,
        invariants=invariants,
        temporal_rules=temporal_rules,
    )


def _execution_authority_spec() -> MachineSpec:
    states = _enum_names(ExecutionProgressState)
    transitions = (
        TransitionEdge("LOCKED", "ARMED", "intent_present"),
        TransitionEdge("ARMED", "BLOCKED_RETRY", "prereqs_ready and not gates_ok"),
        TransitionEdge("ARMED", "CONVERGING", "prereqs_ready and gates_ok"),
        TransitionEdge("BLOCKED_RETRY", "FAIL_SAFE", "elapsed >= timeout_s"),
        TransitionEdge("BLOCKED_RETRY", "CONVERGING", "gates_ok recovers"),
        TransitionEdge("FAIL_SAFE", "CONVERGING", "gates_ok recovers"),
        TransitionEdge("FAIL_SAFE", "LOCKED", "reset()"),
        TransitionEdge("CONVERGING", "AUTHORIZED", "P_converge"),
        TransitionEdge("AUTHORIZED", "CONVERGING", "convergence lost while gates_ok"),
        TransitionEdge("*", "LOCKED", "intent_present = false"),
        TransitionEdge("*", "ARMED", "intent_present and not prereqs_ready"),
    )
    invariants = (
        InvariantRule(
            "I_EA_1",
            "safety_state = AUTHORIZED <=> P_converge and progress_state != FAIL_SAFE",
            "Single binary authority signal is derived from convergence and fail-safe status.",
        ),
        InvariantRule(
            "I_EA_2",
            "intent_present = false => progress_state = LOCKED",
            "The FSM hard-resets when no activation intent exists.",
        ),
        InvariantRule(
            "I_EA_3",
            "progress_state = FAIL_SAFE => safety_state = LOCKED",
            "Fail-safe always overrides optimistic convergence.",
        ),
    )
    temporal_rules = (
        TemporalRule(
            "T_EA_1",
            "[](FAIL_SAFE and gates_ok => <> CONVERGING)",
            "Fail-safe is recoverable once gates return healthy.",
        ),
        TemporalRule(
            "T_EA_2",
            "[](AUTHORIZED => trading_live)",
            "Execution authority can never outgrow live trading state.",
        ),
    )
    return MachineSpec(
        name="execution_authority_convergence",
        initial_state=ExecutionProgressState.LOCKED.value,
        states=states,
        terminal_states=(),
        transitions=transitions,
        invariants=invariants,
        temporal_rules=temporal_rules,
    )


def _execution_controller_spec() -> MachineSpec:
    states = _enum_names(ExecutionOrderState)
    transitions = (
        TransitionEdge("IDLE", "SUBMITTING", "submit() called and dispatch_enabled"),
        TransitionEdge("SUBMITTING", "AWAITING_CONFIRM", "broker_fn succeeds"),
        TransitionEdge("AWAITING_CONFIRM", "COMPLETED", "success_fn confirms fill"),
        TransitionEdge("SUBMITTING", "RETRYING", "NONCE error and retries_left"),
        TransitionEdge("RETRYING", "SUBMITTING", "retry delay completes"),
        TransitionEdge("SUBMITTING", "BACKING_OFF", "RATE_LIMIT error and retries_left"),
        TransitionEdge("BACKING_OFF", "SUBMITTING", "exponential backoff completes"),
        TransitionEdge("SUBMITTING", "FAILED", "UNKNOWN error or retries exhausted"),
        TransitionEdge("SUBMITTING", "HALTED_AUTH", "AUTH error"),
        TransitionEdge("SUBMITTING", "HALTED_CONFIG", "PERMISSION error"),
        TransitionEdge("SUBMITTING", "HALTED_FUNDS", "FUNDS error"),
    )
    invariants = (
        InvariantRule(
            "I_ESC_1",
            "state in terminal_states => no further broker call occurs in this submit() cycle",
            "Order execution paths always terminate cleanly.",
        ),
        InvariantRule(
            "I_ESC_2",
            "state = SUBMITTING => broker call in flight",
            "Broker I/O only occurs in one explicit state.",
        ),
        InvariantRule(
            "I_ESC_3",
            "HALTED_AUTH => gate_fail_callback invoked when configured",
            "Fatal auth failures propagate to upstream safety gates.",
        ),
    )
    temporal_rules = (
        TemporalRule(
            "T_ESC_1",
            "[](state = IDLE and submit => <> state in terminal_states)",
            "Every submission attempt eventually reaches a terminal result.",
        ),
    )
    return MachineSpec(
        name="execution_state_controller",
        initial_state=ExecutionOrderState.IDLE.value,
        states=states,
        terminal_states=tuple(state.value for state in EXECUTION_TERMINAL_STATES),
        transitions=transitions,
        invariants=invariants,
        temporal_rules=temporal_rules,
    )


@lru_cache(maxsize=1)
def get_formal_state_machine_spec() -> FormalStateMachineSpec:
    """Return the canonical formal FSM specification for the repository."""

    trading_guards = {
        ("OFF", "DRY_RUN"): "dry_run_requested",
        ("OFF", "LIVE_PENDING_CONFIRMATION"): "explicit live intent without activation commit",
        ("OFF", "LIVE_ACTIVE"): "auto-activate path and activation gates pass",
        ("OFF", "EMERGENCY_STOP"): "kill_switch_active",
        ("DRY_RUN", "OFF"): "operator reset",
        ("DRY_RUN", "LIVE_PENDING_CONFIRMATION"): "operator requests live mode",
        ("DRY_RUN", "EMERGENCY_STOP"): "kill_switch_active",
        ("LIVE_PENDING_CONFIRMATION", "OFF"): "operator reset",
        ("LIVE_PENDING_CONFIRMATION", "LIVE_ACTIVE"): "operator confirmation and activation gates pass",
        ("LIVE_PENDING_CONFIRMATION", "EMERGENCY_STOP"): "kill_switch_active",
        ("LIVE_ACTIVE", "OFF"): "operator reset",
        ("LIVE_ACTIVE", "DRY_RUN"): "operator downgrade",
        ("LIVE_ACTIVE", "EMERGENCY_STOP"): "kill_switch_active or fatal runtime stop",
        ("EMERGENCY_STOP", "OFF"): "explicit operator acknowledgement",
    }
    trading_spec = MachineSpec(
        name="trading_state_machine",
        initial_state=TradingState.OFF.value,
        states=_enum_names(TradingState),
        terminal_states=(),
        transitions=_edges_from_transition_map(TradingStateMachine.VALID_TRANSITIONS, guards=trading_guards),
        invariants=(
            InvariantRule(
                "I_TSM_1",
                "cold_start => state = OFF",
                "Restarts always begin from a safe disabled state.",
            ),
            InvariantRule(
                "I_TSM_2",
                "dispatch_enabled => state = LIVE_ACTIVE",
                "Live order flow is impossible outside live trading mode.",
            ),
            InvariantRule(
                "I_TSM_3",
                "state = LIVE_ACTIVE => activation_committed and first_snap_accepted",
                "Live activation always rests on explicit capital readiness.",
            ),
            InvariantRule(
                "I_TSM_4",
                "state = EMERGENCY_STOP => not dispatch_enabled",
                "Emergency stop revokes runtime dispatch immediately.",
            ),
        ),
        temporal_rules=(
            TemporalRule(
                "T_TSM_1",
                "[](kill_switch_active => <> state = EMERGENCY_STOP)",
                "Kill-switch activation eventually halts the trading FSM.",
            ),
            TemporalRule(
                "T_TSM_2",
                "[](state = EMERGENCY_STOP => [] not dispatch_enabled)",
                "Dispatch remains disabled while emergency stop is active.",
            ),
        ),
    )

    bootstrap_spec = MachineSpec(
        name="bootstrap_state_machine",
        initial_state=BootstrapState.BOOT_INIT.value,
        states=_enum_names(BootstrapState),
        terminal_states=(BootstrapState.SHUTDOWN.value,),
        transitions=_edges_from_transition_map(BOOTSTRAP_VALID_TRANSITIONS),
        invariants=(
            InvariantRule(
                "I_BOOT_1",
                "state >= LOCK_ACQUIRED => single-writer process lock held",
                "Broker initialization never precedes writer-lock ownership.",
            ),
            InvariantRule(
                "I_BOOT_2",
                "state >= HEALTH_BOUND => health server is available before blocking startup I/O",
                "Startup remains observable even under degraded boot conditions.",
            ),
            InvariantRule(
                "I_BOOT_3",
                "state in strategy_arm_allowed_states => bootstrap reached capital-ready-or-better",
                "Strategy arming cannot race capital initialization.",
            ),
        ),
        temporal_rules=(
            TemporalRule(
                "T_BOOT_1",
                "[](state = BOOT_FAILED_RETRY => <> state in {PLATFORM_CONNECTING, EXTERNAL_RESTART_REQUIRED})",
                "Retry states cannot stall indefinitely without a next decision.",
            ),
        ),
    )

    capital_bootstrap_spec = MachineSpec(
        name="capital_bootstrap_state_machine",
        initial_state=CapitalBootstrapState.BOOT_IDLE.value,
        states=_enum_names(CapitalBootstrapState),
        terminal_states=(CapitalBootstrapState.RUNNING.value,),
        transitions=_edges_from_transition_map(CapitalBootstrapStateMachine._VALID_TRANSITIONS),
        invariants=(
            InvariantRule(
                "I_CAP_BOOT_1",
                f"publish_snapshot writer_id = {CAPITAL_WRITER_ID!r}",
                "Capital authority accepts writes only from the bootstrap coordinator writer.",
            ),
            InvariantRule(
                "I_CAP_BOOT_2",
                "state = RUNNING => capital_hydrated",
                "Terminal success requires an authoritative capital snapshot.",
            ),
        ),
        temporal_rules=(
            TemporalRule(
                "T_CAP_BOOT_1",
                "[](state in {DEGRADED, FAILED} => <> state = REFRESH_REQUESTED)",
                "Degraded and failed capital startup states recover through an explicit retry path.",
            ),
        ),
    )

    capital_runtime_spec = MachineSpec(
        name="capital_runtime_state_machine",
        initial_state=CapitalRuntimeState.RUN_READY.value,
        states=_enum_names(CapitalRuntimeState),
        terminal_states=(CapitalRuntimeState.RUN_HALTED.value,),
        transitions=_edges_from_transition_map(CapitalRuntimeStateMachine._VALID_TRANSITIONS),
        invariants=(
            InvariantRule(
                "I_CAP_RUN_1",
                "state = RUN_HALTED => new entries blocked",
                "Capital halt blocks new execution until recovery begins.",
            ),
            InvariantRule(
                "I_CAP_RUN_2",
                "capital_stale => state in {RUN_STALE, RUN_DEGRADED, RUN_HALTED}",
                "Stale capital is represented explicitly in runtime state.",
            ),
        ),
        temporal_rules=(
            TemporalRule(
                "T_CAP_RUN_1",
                "[](state = RUN_HALTED and recovery_requested => <> state = RUN_REFRESHING)",
                "Halted capital runtime can recover only through a refresh cycle.",
            ),
        ),
    )

    nonce_spec = MachineSpec(
        name="nonce_fsm",
        initial_state=NonceState.IDLE.value,
        states=_enum_names(NonceState),
        terminal_states=(NonceState.CIRCUIT_OPEN.value, NonceState.FAILED.value),
        transitions=_edges_from_transition_map(NONCE_VALID_TRANSITIONS),
        invariants=(
            InvariantRule(
                "I_NONCE_1",
                "state = LIVE => nonce issuance allowed",
                "Nonce issuance is legal only in the live state.",
            ),
            InvariantRule(
                "I_NONCE_2",
                "resync failures >= threshold => state = CIRCUIT_OPEN",
                "Repeated resync failure trips a hard circuit breaker.",
            ),
            InvariantRule(
                "I_NONCE_3",
                "probe drift is not persisted across recovery attempts",
                "Forward-probe loops cannot accumulate permanent nonce drift.",
            ),
            InvariantRule(
                "I_NONCE_4",
                "probe window timeout => watchdog closes window and returns to recovery",
                "Probe windows cannot deadlock the process.",
            ),
        ),
        temporal_rules=(
            TemporalRule(
                "T_NONCE_1",
                "[](probe_window_open => <> probe_window_closed)",
                "Probe windows always close eventually.",
            ),
            TemporalRule(
                "T_NONCE_2",
                "[](state = CIRCUIT_OPEN => [] not nonce_issued until reset_circuit)",
                "The circuit breaker fail-closes until explicitly reset.",
            ),
        ),
    )

    spec = FormalStateMachineSpec(
        machines=(
            trading_spec,
            bootstrap_spec,
            _startup_coordinator_spec(),
            _execution_authority_spec(),
            capital_bootstrap_spec,
            capital_runtime_spec,
            nonce_spec,
            _execution_controller_spec(),
        ),
        cross_machine_invariants=(
            InvariantRule(
                "X1",
                "order_dispatch <=> (TSM = LIVE_ACTIVE and EACF = AUTHORIZED and SC = DISPATCH_ENABLED and NonceFSM = LIVE)",
                "Live order flow requires simultaneous agreement from trading, authority, startup, and nonce state machines.",
            ),
            InvariantRule(
                "X2",
                "TSM = LIVE_ACTIVE => SC bootstrap_state = RUNNING_SUPERVISED",
                "Trading cannot outrun startup supervision.",
            ),
            InvariantRule(
                "X3",
                "NonceFSM != LIVE => SC.nonce_ready = false => SC.dispatch_enabled = false",
                "Loss of nonce readiness revokes dispatch end-to-end.",
            ),
            InvariantRule(
                "X4",
                "CapitalBootstrap in {FAILED, DEGRADED} => SC coordinator_state != DISPATCH_ENABLED",
                "Capital startup failures block live dispatch.",
            ),
            InvariantRule(
                "X5",
                "kill_switch_active => SC = FAIL_SAFE and TSM = EMERGENCY_STOP",
                "Kill-switch semantics propagate across the runtime safety stack.",
            ),
            InvariantRule(
                "X6",
                "SC activation_epoch = authority_epoch at commit time",
                "Activation intent must be fresh when dispatch is committed.",
            ),
            InvariantRule(
                "X7",
                "nonce rebuild cooldown => cached capital balance preserved",
                "Kraken nonce recovery cannot zero live capital authority.",
            ),
            InvariantRule(
                "X8",
                "EACF FAIL_SAFE and gates_ok => eventual recovery to CONVERGING",
                "Execution fail-safe is self-healing once gates recover.",
            ),
            InvariantRule(
                "X9",
                "ESC HALTED_AUTH => upstream gate failure is propagated",
                "Per-order fatal auth errors revoke broader execution authority.",
            ),
        ),
        temporal_rules=(
            TemporalRule(
                "XT1",
                "[](authority_epoch changes => <> order_dispatch = false)",
                "Authority changes eventually drain active dispatch authority.",
            ),
            TemporalRule(
                "XT2",
                "[](P_dispatch => <> order_dispatch)",
                "Once all dispatch prerequisites converge, dispatch eventually becomes available.",
            ),
        ),
    )
    return spec

