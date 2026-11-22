"""Pure transition guard for read-only diagnostic projections."""
from __future__ import annotations
from dataclasses import dataclass
from .kraken_activation_status_v1 import State

CRITICAL = frozenset({
    "protective_exit_readback", "writer_lease", "nonce_sequence",
    "kill_switch_clear", "risk_limits", "position_sync",
    "duplicate_order_fence", "position_ledger_reconciliation",
})

@dataclass(frozen=True)
class Transition:
    state: State
    reason: str
    authorizes_orders: bool = False

def transition(previous: State, proposed: State, *,
               missing_observations: frozenset[str] = frozenset(),
               restarted: bool = False, approval_revoked: bool = False,
               integrity_failure: bool = False,
               authenticated_gate: bool = False) -> Transition:
    """Never grants trading authority; preserves canonical gate ownership."""
    if integrity_failure or (previous == State.CONTROLLED and
                             (approval_revoked or missing_observations & CRITICAL)):
        return Transition(State.PROTECTIVE_STOP, "critical_integrity_or_revocation")
    if restarted:
        return Transition(State.RECOVERY, "deployment_epoch_changed")
    if proposed == State.CONTROLLED and not authenticated_gate:
        return Transition(State.READY_FOR_APPROVAL, "canonical_gate_unverified")
    if previous == State.PROTECTIVE_STOP and proposed == State.CONTROLLED:
        return Transition(State.VERIFYING, "protective_stop_requires_reverification")
    return Transition(proposed, "diagnostic_only")
