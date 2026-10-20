"""Reviewed startup admission policy candidate; NO production hook installed.

Decouples the requirement for an unrelated recent trade from preflight
evaluation, but does not modify canonical execution authority. Any actual
dispatch remains controlled by the existing writer/risk/kill-switch gates.
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def evaluate_startup_transition(
    certificate: Mapping[str, Any],
    controls: Mapping[str, Any],
) -> dict[str, Any]:
    """Produce a review recommendation, never an executable authorization."""
    required = (
        "writer_fenced", "nonce_current", "kill_switch_clear",
        "capital_current", "positions_reconciled",
        "protective_exits_confirmed", "ledger_certified",
        "broker_account_authenticated", "duplicate_order_fence",
        "operator_approved",
    )
    blockers = [name for name in required if controls.get(name) is not True]
    if certificate.get("certified") is not True:
        blockers.append("independent_pretrade_certificate")
    return {
        "pretrade_transition_candidate": not blockers,
        "missing": blockers,
        "execution_authority": False,
        "allow_new_orders": False,
        "last_trade_freshness_not_used_as_pretrade_liveness": True,
        "post_trade_exact_fill_verification_required": True,
        "review_only": True,
    }
