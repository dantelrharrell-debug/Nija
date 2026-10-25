"""Fail-closed broker history reconciliation plan.

This module deliberately does not mutate production ledger data or submit orders.
It produces deterministic, auditable reconciliation decisions from authenticated
broker observations and existing ledger records.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def plan_opening_reconciliation(
    account: str,
    broker_fills: Sequence[Mapping[str, Any]],
    ledger_rows: Sequence[Mapping[str, Any]],
    *,
    authenticated_readback: bool = False,
    complete_pagination: bool = False,
    account_identity_verified: bool = False,
) -> dict[str, Any]:
    """Return matched, unmatched and ambiguous fills without inventing intents.

    Caller must independently authenticate and paginate the broker readback.
    The resulting plan is not a migration approval or execution certificate.
    """
    if not all((authenticated_readback is True, complete_pagination is True, account_identity_verified is True)):
        raise ValueError("independent_broker_readback_certification_required")
    if not isinstance(account, str) or not account.strip() or account != account.strip():
        raise ValueError("account_scope_required")
    if not isinstance(broker_fills, (list, tuple)) or not isinstance(ledger_rows, (list, tuple)):
        raise TypeError("immutable_snapshot_sequences_required")

    ledger_by_trade: dict[str, list[Mapping[str, Any]]] = {}
    for row in ledger_rows:
        if not isinstance(row, Mapping) or row.get("account") != account:
            raise ValueError("ledger_scope_mismatch")
        trade_id = row.get("broker_trade_id")
        if isinstance(trade_id, str) and trade_id:
            ledger_by_trade.setdefault(trade_id, []).append(row)

    seen: set[str] = set()
    matched: list[str] = []
    missing: list[str] = []
    ambiguous: list[str] = []
    for fill in broker_fills:
        if not isinstance(fill, Mapping) or fill.get("account") != account:
            raise ValueError("broker_scope_mismatch")
        trade_id = fill.get("broker_trade_id")
        order_id = fill.get("broker_order_id")
        if not isinstance(trade_id, str) or not trade_id or not isinstance(order_id, str) or not order_id:
            raise ValueError("authenticated_trade_and_order_ids_required")
        if trade_id in seen:
            ambiguous.append(trade_id)
            continue
        seen.add(trade_id)
        rows = ledger_by_trade.get(trade_id, [])
        if len(rows) > 1:
            ambiguous.append(trade_id)
        elif len(rows) == 1 and rows[0].get("broker_order_id") == order_id:
            matched.append(trade_id)
        elif len(rows) == 1:
            ambiguous.append(trade_id)
        else:
            missing.append(trade_id)

    return {
        "account": account,
        "matched_trade_ids": sorted(matched),
        "missing_opening_record_trade_ids": sorted(missing),
        "ambiguous_trade_ids": sorted(ambiguous),
        "unknown_strategy_attribution_preserved": True,
        "can_apply_migration": False,
        "authorizes_orders": False,
    }
