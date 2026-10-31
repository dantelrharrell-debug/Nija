"""Fail-closed, non-authorizing comparison of Kraken close evidence.

This module does not contact Kraken, update a ledger, or authorize orders.
Callers must independently authenticate and bind the account and obtain
unmodified exchange evidence. No raw identifiers are returned.
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Mapping, Any


def _positive(value: Any, *, allow_zero: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("invalid_amount")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError("invalid_amount") from None
    if not number.is_finite() or (number < 0 if allow_zero else number <= 0):
        raise ValueError("invalid_amount")
    return number


def verify_exact_close(
    expected: Mapping[str, Any],
    order: Mapping[str, Any],
    trades: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Validate exact IDs, side, pair, quantity, and fees; never infer opening basis."""
    refusal = {"verified": False, "execution_authorized": False,
               "ledger_mutation_allowed": False}
    try:
        if not all(isinstance(item, Mapping) for item in (expected, order, trades)):
            raise ValueError("incomplete_evidence")
        oid = expected["order_id"]
        if not isinstance(oid, str) or not oid or order.get("status") != "closed":
            raise ValueError("order_not_closed")
        desc = order["descr"]
        if not isinstance(desc, Mapping):
            raise ValueError("order_description_invalid")
        if (desc.get("pair") != expected["pair"]
                or desc.get("type") != expected["side"]):
            raise ValueError("order_identity_mismatch")
        ids = order["trades"]
        if (not isinstance(ids, list) or not ids
                or any(not isinstance(tid, str) or not tid for tid in ids)
                or len(ids) != len(set(ids))):
            raise ValueError("trade_ids_invalid")
        if any(not isinstance(tid, str) for tid in trades) or set(ids) != set(trades):
            raise ValueError("trade_ids_incomplete")
        total_volume = Decimal("0")
        total_cost = Decimal("0")
        total_fee = Decimal("0")
        for tid in ids:
            trade = trades[tid]
            if not isinstance(trade, Mapping):
                raise ValueError("trade_identity_mismatch")
            if (trade.get("ordertxid") != oid
                    or trade.get("pair") != expected["pair"]
                    or trade.get("type") != expected["side"]):
                raise ValueError("trade_identity_mismatch")
            total_volume += _positive(trade["vol"])
            total_cost += _positive(trade["cost"])
            total_fee += _positive(trade["fee"], allow_zero=True)
        if (total_volume != _positive(order["vol_exec"])
                or total_volume != _positive(expected["volume"])
                or total_cost != _positive(expected["cost"])
                or total_fee != _positive(expected["fee"], allow_zero=True)):
            raise ValueError("close_terms_mismatch")
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError) as exc:
        reason = str(exc)
        allowed = {"invalid_amount", "order_not_closed", "order_description_invalid",
                   "order_identity_mismatch", "trade_ids_invalid", "trade_ids_incomplete",
                   "trade_identity_mismatch", "close_terms_mismatch", "incomplete_evidence"}
        return {**refusal, "reason": reason if reason in allowed else "incomplete_evidence"}
    return {"verified": True, "close_terms_matched": True,
            "opening_basis_verified": False, "account_binding_verified": False,
            "protective_exits_verified": False, "execution_authorized": False,
            "ledger_mutation_allowed": False}


def verify_broker_readback_consistency(
    order_id: str,
    order: Mapping[str, Any],
    trades: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    """Cross-check exchange order/fill aggregates without asserting ledger truth.

    Cost and fee values are derived solely from broker trades; a successful
    result is NOT independent financial, account, or ledger certification.
    """
    denied = {"verified": False, "execution_authorized": False,
              "ledger_mutation_allowed": False}
    try:
        if (not isinstance(order_id, str) or not order_id
                or not isinstance(order, Mapping)
                or not isinstance(trades, Mapping)):
            raise ValueError("incomplete_evidence")
        desc = order.get("descr")
        if not isinstance(desc, Mapping):
            raise ValueError("incomplete_evidence")
        ids = order.get("trades")
        if (not isinstance(ids, list) or not ids
                or any(not isinstance(tid, str) or not tid for tid in ids)
                or len(ids) != len(set(ids)) or set(ids) != set(trades)):
            raise ValueError("trade_ids_incomplete")
        cost = Decimal("0")
        fee = Decimal("0")
        for tid in ids:
            trade = trades[tid]
            if not isinstance(trade, Mapping):
                raise ValueError("incomplete_evidence")
            cost += _positive(trade["cost"])
            fee += _positive(trade["fee"], allow_zero=True)
        expected = {
            "order_id": order_id,
            "pair": desc["pair"],
            "side": desc["type"],
            "volume": order["vol_exec"],
            "cost": cost,
            "fee": fee,
        }
        result = verify_exact_close(expected, order, trades)
        if not result["verified"]:
            return result
        return {**result, "source": "broker_only_readback",
                "independent_ledger_certified": False,
                "account_binding_verified": False}
    except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
        return {**denied, "reason": "incomplete_evidence"}
