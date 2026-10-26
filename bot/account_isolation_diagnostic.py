"""Read-only account isolation diagnosis; never authorizes trading.

Only independently authenticated per-account evidence may satisfy local gates.
Platform-wide safety controls remain mandatory for every account.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class AccountReadiness:
    account: str
    billing_entitled: bool
    broker_authenticated: bool
    positions_reconciled: bool
    protective_exits_verified: bool
    orders_reconciled: bool
    nonce_verified: bool
    collector_fresh: bool


@dataclass(frozen=True)
class GlobalReadiness:
    writer_authorized: bool
    kill_switch_clear: bool
    execution_proof_fresh: bool


def inspect_account_isolation(
    accounts: Mapping[str, AccountReadiness],
    global_state: GlobalReadiness,
) -> dict[str, object]:
    """Report account-local blockers without hiding global failures.

    Diagnostic eligibility is not execution authority. Do not use this output
    to dispatch orders or to override the canonical execution controller.
    """
    global_checks = {
        "writer_authorized": global_state.writer_authorized,
        "kill_switch_clear": global_state.kill_switch_clear,
        "execution_proof_fresh": global_state.execution_proof_fresh,
    }
    global_missing = sorted(k for k, ok in global_checks.items() if ok is not True)
    per_account: dict[str, dict[str, object]] = {}
    for key, account in sorted(accounts.items()):
        local_checks = {
            "billing_entitled": account.billing_entitled,
            "broker_authenticated": account.broker_authenticated,
            "positions_reconciled": account.positions_reconciled,
            "protective_exits_verified": account.protective_exits_verified,
            "orders_reconciled": account.orders_reconciled,
            "nonce_verified": account.nonce_verified,
            "collector_fresh": account.collector_fresh,
        }
        local_missing = sorted(k for k, ok in local_checks.items() if ok is not True)
        per_account[key] = {
            "local_ready": not local_missing,
            "diagnostic_ready": not local_missing and not global_missing,
            "missing_local": local_missing,
            "authorizes_orders": False,
        }
    return {
        "global_missing": global_missing,
        "accounts": per_account,
        "authorizes_orders": False,
        "canonical_controller_required": True,
    }
