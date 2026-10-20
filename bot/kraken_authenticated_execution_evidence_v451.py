"""Strict normalization of read-only authenticated Kraken execution evidence.

This module never queries Kraken, mutates a ledger, refreshes proof timestamps,
or grants trading authority. Its output must be passed to the existing
canonical verifier; it is not an execution-ready flag.
"""
from __future__ import annotations

import math
import time
from typing import Any, Mapping


def validate_kraken_order_evidence(
    order_id: str,
    account_id: str,
    order: Mapping[str, Any],
    *,
    authenticated_account_id: str,
    event_epoch: float,
    now_epoch: float | None = None,
    max_age_seconds: float = 1800.0,
) -> dict[str, Any]:
    """Fail closed unless the exact authenticated order has a genuine recent fill."""
    now = time.time() if now_epoch is None else now_epoch
    failed = {"verified": False, "reason": "invalid_execution_evidence"}
    if not isinstance(order, Mapping):
        return failed
    if not order_id or not account_id or account_id != authenticated_account_id:
        return {"verified": False, "reason": "account_identity_mismatch"}
    if str(order.get("txid", "")).strip() != order_id:
        # Kraken QueryOrders keys are txids; caller must explicitly attach that key.
        return {"verified": False, "reason": "order_identity_mismatch"}
    if str(order.get("status", "")).lower() != "closed":
        return {"verified": False, "reason": "order_not_final_closed"}
    try:
        volume = float(order["vol_exec"])
        cost = float(order["cost"])
        event = float(event_epoch)
        clock = float(now)
        maximum = float(max_age_seconds)
    except (KeyError, TypeError, ValueError, OverflowError):
        return failed
    if not all(math.isfinite(x) for x in (volume, cost, event, clock, maximum)):
        return failed
    if volume <= 0 or cost <= 0 or maximum != 1800.0:
        return failed
    age = clock - event
    if event <= 0 or age < -5 or age > maximum:
        return {"verified": False, "reason": "broker_event_stale_or_future"}
    description = order.get("descr")
    if not isinstance(description, Mapping):
        return failed
    pair = str(description.get("pair") or "").strip()
    side = str(description.get("type") or "").strip().lower()
    if not pair or side not in {"buy", "sell"}:
        return failed
    return {
        "verified": True,
        "order_id": order_id,
        "account_id": account_id,
        "status": "closed",
        "vol_exec": volume,
        "cost": cost,
        "pair": pair,
        "side": side,
        "broker_event_at_epoch": event,
        "verification_age_seconds": age,
        "source": "authenticated_kraken_queryorders",
        "authorization_granted": False,
    }
