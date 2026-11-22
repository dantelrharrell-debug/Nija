"""Read-only Kraken activation status evaluator.

This module cannot authorize, enable, submit or cancel orders. All inputs must
come from separately authenticated production evidence; this is a diagnostic
projection, not an alternative execution gate.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

REQUIRED_OBSERVATIONS = (
    "account_permissions", "account_identity", "broker_balances",
    "position_ledger_reconciliation", "protective_exit_readback",
    "open_order_reconciliation", "duplicate_order_fence", "writer_lease",
    "nonce_sequence", "operator_authorization", "kill_switch_clear",
    "risk_limits", "position_sync",
)


class State(str, Enum):
    RECOVERY = "RECOVERY"
    VERIFYING = "VERIFYING"
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
    CONTROLLED = "CONTROLLED"
    PROTECTIVE_STOP = "PROTECTIVE_STOP"


@dataclass(frozen=True)
class Snapshot:
    protected_artifacts_verified: bool
    collector_installed: bool
    observations: Mapping[str, bool]
    broker_reconciled: bool
    security_certified: bool
    independent_receipts_verified: bool
    explicit_bounded_authorization: bool
    canonical_gate_allows_orders: bool
    material_integrity_failure: bool = False


@dataclass(frozen=True)
class Assessment:
    state: State
    blockers: tuple[str, ...]
    observations_verified: int
    diagnostic_only: bool = True
    authorizes_orders: bool = False


def assess(snapshot: Snapshot) -> Assessment:
    """Evaluate caller-supplied evidence without touching Kraken or order state.

    A CONTROLLED label describes *observed* authority from the canonical gate,
    never grants it. Unknown/stale evidence must be supplied as False.
    """
    if set(snapshot.observations) - set(REQUIRED_OBSERVATIONS):
        raise ValueError("unknown_observation")
    verified = sum(snapshot.observations.get(name) is True for name in REQUIRED_OBSERVATIONS)
    blockers = []
    if not snapshot.protected_artifacts_verified:
        blockers.append("protected_artifacts_unverified")
    if not snapshot.collector_installed:
        blockers.append("collector_missing")
    blockers.extend(
        "observation_missing:" + name
        for name in REQUIRED_OBSERVATIONS
        if snapshot.observations.get(name) is not True
    )
    if not snapshot.broker_reconciled:
        blockers.append("broker_reconciliation_unverified")
    if not snapshot.security_certified:
        blockers.append("security_certification_unverified")
    if not snapshot.independent_receipts_verified:
        blockers.append("independent_receipts_unverified")
    if not snapshot.explicit_bounded_authorization:
        blockers.append("bounded_authorization_missing")
    if not snapshot.canonical_gate_allows_orders:
        blockers.append("canonical_execution_gate_denied")
    if snapshot.material_integrity_failure:
        state = State.PROTECTIVE_STOP
        blockers.append("material_integrity_failure")
    elif not snapshot.protected_artifacts_verified or not snapshot.collector_installed:
        state = State.RECOVERY
    elif verified != len(REQUIRED_OBSERVATIONS) or not (
        snapshot.broker_reconciled and snapshot.security_certified
        and snapshot.independent_receipts_verified
    ):
        state = State.VERIFYING
    elif not snapshot.explicit_bounded_authorization or not snapshot.canonical_gate_allows_orders:
        state = State.READY_FOR_APPROVAL
    else:
        state = State.CONTROLLED
    return Assessment(state, tuple(blockers), verified)

def assess_authenticated(snapshot: Snapshot, verified_observations: frozenset[str],
                         *, evidence_errors: tuple[str, ...] = (),
                         authenticated_gate: bool = False) -> Assessment:
    """Read-only production-facing projection of separately verified evidence.

    A caller's Boolean assertions never establish authenticated readiness.
    This method remains diagnostic-only and cannot enable any order.
    """
    if set(verified_observations) - set(REQUIRED_OBSERVATIONS):
        raise ValueError("unknown_verified_observation")
    filtered = {name: name in verified_observations for name in REQUIRED_OBSERVATIONS}
    sanitized = Snapshot(
        protected_artifacts_verified=snapshot.protected_artifacts_verified,
        collector_installed=snapshot.collector_installed,
        observations=filtered,
        broker_reconciled=snapshot.broker_reconciled,
        security_certified=snapshot.security_certified,
        independent_receipts_verified=snapshot.independent_receipts_verified,
        explicit_bounded_authorization=snapshot.explicit_bounded_authorization,
        canonical_gate_allows_orders=authenticated_gate and snapshot.canonical_gate_allows_orders,
        material_integrity_failure=snapshot.material_integrity_failure,
    )
    result = assess(sanitized)
    if evidence_errors and result.state in (State.READY_FOR_APPROVAL, State.CONTROLLED):
        return Assessment(State.VERIFYING, result.blockers + tuple(evidence_errors),
                          result.observations_verified)
    return Assessment(result.state, result.blockers + tuple(evidence_errors),
                      result.observations_verified)
