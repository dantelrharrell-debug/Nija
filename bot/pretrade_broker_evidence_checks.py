"""Independent broker evidence consistency rules; never authorizes orders.

All inputs must originate from authenticated, account-scoped broker readback
and a durable ledger snapshot obtained under an audited transaction. No
network requests or mutations occur in this module.
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any


def _nonnegative(value: Any) -> Decimal | None:
    if isinstance(value, bool):
        return None
    try:
        parsed = Decimal(str(value))
        return parsed if parsed.is_finite() and parsed >= 0 else None
    except (InvalidOperation, ValueError, TypeError):
        return None


def reconcile_order_fills(
    account: str, broker_fills: Sequence[Mapping[str, Any]],
    ledger_fills: Sequence[Mapping[str, Any]],
) -> tuple[bool, list[str]]:
    """Compare exact account/order/trade IDs, quantities, costs and fees.

    Duplicate or missing rows fail closed; an empty broker history is not
    certified without a separate authenticated completeness attestation.
    """
    failures: list[str] = []
    if not account or not broker_fills or not ledger_fills:
        return False, ["history_missing_or_unproven"]
    def normalize(rows: Sequence[Mapping[str, Any]], label: str):
        result = {}
        for row in rows:
            if not isinstance(row, Mapping) or row.get("account") != account:
                failures.append(label + "_account_invalid")
                continue
            order_id, trade_id = row.get("order_id"), row.get("trade_id")
            if not isinstance(order_id, str) or not order_id or not isinstance(trade_id, str) or not trade_id:
                failures.append(label + "_identity_invalid")
                continue
            key = (order_id, trade_id)
            if key in result:
                failures.append(label + "_duplicate_fill")
                continue
            numbers = tuple(_nonnegative(row.get(k)) for k in ("quantity", "cost", "fee"))
            if any(v is None for v in numbers) or numbers[0] == 0:
                failures.append(label + "_amount_invalid")
                continue
            result[key] = (row.get("symbol"), row.get("side"), numbers)
        return result
    broker = normalize(broker_fills, "broker")
    ledger = normalize(ledger_fills, "ledger")
    if set(broker) != set(ledger):
        failures.append("fill_id_set_mismatch")
    for key in broker.keys() & ledger.keys():
        if broker[key] != ledger[key]:
            failures.append("fill_detail_mismatch")
    return not failures, sorted(set(failures))


def verify_protective_orders(
    account: str, positions: Sequence[Mapping[str, Any]],
    broker_orders: Sequence[Mapping[str, Any]],
) -> tuple[bool, list[str]]:
    """Reject missing/insufficient opposite-side protection for open positions."""
    failures = []
    if not account:
        return False, ["account_missing"]
    for position in positions:
        if not isinstance(position, Mapping) or position.get("account") != account:
            failures.append("position_account_invalid")
            continue
        quantity = _nonnegative(position.get("quantity"))
        if quantity is None or quantity == 0:
            failures.append("position_quantity_invalid")
            continue
        side = position.get("side")
        if side not in {"long", "short"} or not position.get("symbol"):
            failures.append("position_identity_invalid")
            continue
        exit_side = "sell" if side == "long" else "buy"
        covered = Decimal(0)
        seen = set()
        for order in broker_orders:
            if (not isinstance(order, Mapping) or order.get("account") != account
                    or order.get("symbol") != position.get("symbol")
                    or order.get("side") != exit_side
                    or order.get("status") != "open"
                    or order.get("protective_verified") is not True
                    or order.get("reduce_only_verified") is not True):
                continue
            oid = order.get("order_id")
            remaining = _nonnegative(order.get("remaining_quantity"))
            if not isinstance(oid, str) or not oid or oid in seen or remaining is None:
                failures.append("protective_order_invalid")
                continue
            seen.add(oid)
            covered += remaining
        if covered < quantity:
            failures.append("protective_coverage_insufficient")
    return not failures, sorted(set(failures))
