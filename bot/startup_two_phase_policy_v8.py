"""Reviewed-candidate two-phase startup policy; NOT connected to live admission.

Cold startup can be evaluated without demanding a prior trade, but only when
an independent, authenticated, account-scoped pretrade certificate and every
other safety prerequisite are current. Once an order is submitted, posttrade
verification remains mandatory. A passing decision here never clears a kill
switch, dispatches an order, or grants execution authority.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

PREFLIGHT = (
    "authenticated_pretrade_certificate",
    "broker_permissions", "broker_identity", "broker_balances",
    "ledger_reconciled", "protective_exits_verified",
    "open_orders_reconciled", "duplicate_fence_clear",
    "writer_lease_valid", "nonce_ready", "risk_ready",
    "strategy_ready", "capital_ready", "kill_switch_clear",
    "operator_authorized", "account_scope_verified",
    "backup_restore_certified",
)


def evaluate_startup_transition(
    facts: Mapping[str, Any], *, pending_execution: bool,
    posttrade_verified: bool,
) -> dict[str, Any]:
    """Diagnostic decision only; requires independent review before wiring."""
    missing = [key for key in PREFLIGHT if facts.get(key) is not True]
    if type(pending_execution) is not bool or type(posttrade_verified) is not bool:
        missing.append("execution_state_invalid")
    if pending_execution and posttrade_verified is not True:
        missing.append("posttrade_execution_proof")
    return {
        "diagnostic_only": True,
        "activation_allowed": False,
        "pretrade_candidate_ready": not missing,
        "missing": missing,
        "posttrade_verification_required": bool(pending_execution),
        "legacy_execution_gate_unchanged": True,
    }
