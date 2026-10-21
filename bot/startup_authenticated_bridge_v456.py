"""Account-scoped, fail-closed bridge to reviewed two-phase startup diagnostics.

No broker I/O, mutation, or order-admission hook. All safety facts not supplied
by separately audited producers remain False; the bridge cannot self-certify.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from bot.pretrade_independent_attestation import current_authenticated_attestations
from bot.startup_two_phase_policy_v8 import evaluate_startup_transition

_REQUIRED_EXTERNAL = (
    "risk_ready", "strategy_ready", "capital_ready", "kill_switch_clear",
    "backup_restore_certified", "account_scope_verified",
)


def evaluate_authenticated_startup_candidate(
    account: str, external: Mapping[str, Any], *,
    pending_execution: bool, posttrade_verified: bool,
) -> dict[str, Any]:
    """Read authenticated attestation and explicitly verified external gates."""
    broker = current_authenticated_attestations(account)
    facts = {
        "authenticated_pretrade_certificate": all(value is True for value in broker.values()),
        "broker_permissions": broker["account_permissions"] is True,
        "broker_identity": broker["account_identity"] is True,
        "broker_balances": broker["broker_balances"] is True,
        "ledger_reconciled": broker["position_ledger_reconciliation"] is True,
        "protective_exits_verified": broker["protective_exit_readback"] is True,
        "open_orders_reconciled": broker["open_order_reconciliation"] is True,
        "duplicate_fence_clear": broker["duplicate_order_fence"] is True,
        "writer_lease_valid": broker["writer_lease"] is True,
        "nonce_ready": broker["nonce_sequence"] is True,
        "operator_authorized": broker["operator_authorization"] is True,
    }
    for key in _REQUIRED_EXTERNAL:
        facts[key] = isinstance(external, Mapping) and external.get(key) is True
    result = evaluate_startup_transition(
        facts, pending_execution=pending_execution,
        posttrade_verified=posttrade_verified,
    )
    return dict(result, account_scope=account, independent_attestation_diagnostic=True)
