"""Authenticated Kraken protective-exit readback against independent ledger lots.

Only the existing nonce-owning broker may be used. This is a read-only v452
single-field producer, not an order placement, repair, or activation hook.
The trusted composition root must independently approve account pins, provider
IDs, and a complete current ledger-position reader.
"""
from __future__ import annotations

import hashlib
import json
import math
import time
from collections.abc import Callable, Mapping
from decimal import Decimal
from typing import Any

from bot.kraken_authenticated_identity_v480 import make_kraken_account_identity_provider
from bot.kraken_authenticated_open_order_reconciliation_v482 import (
    _ORDER_ID, _broker_orders, _canonical_pair, _decimal,
)

STOP_TYPES = frozenset({"stop-loss", "stop-loss-limit", "trailing-stop", "trailing-stop-limit"})
PROFIT_TYPES = frozenset({"take-profit", "take-profit-limit"})
MAX_AGE = 60.0


class KrakenProtectionDenied(ValueError):
    """Fixed non-sensitive refusal code."""


def make_kraken_protective_exit_provider(
    broker: Any, *, account_scope: str,
    approved_api_key_sha256: str, approved_iban_sha256: str,
    reviewed_provider_id: str, reviewed_ledger_provider_id: str,
    independent_positions: Callable[[], Mapping[str, Any]],
    monitoring_category: Any, clock: Callable[[], float] = time.time,
) -> Callable[[], Mapping[str, Any]]:
    """Verify both exchange-side stop and take-profit orders for every ledger lot.

    The ledger reader must certify its own complete fills/positions snapshot.
    This provider refuses empty positions, partial closes, unverified
    snapshots, unmatched orders, and inconsistent repeated reads.
    """
    if (account_scope != "platform:kraken"
            or not isinstance(reviewed_provider_id, str) or not reviewed_provider_id
            or not isinstance(reviewed_ledger_provider_id, str)
            or not reviewed_ledger_provider_id
            or reviewed_provider_id == reviewed_ledger_provider_id
            or not callable(independent_positions) or not callable(clock)
            or monitoring_category is None):
        raise KrakenProtectionDenied("reviewed_bindings_required")
    identity = make_kraken_account_identity_provider(
        broker, account_scope=account_scope,
        approved_api_key_sha256=approved_api_key_sha256,
        approved_iban_sha256=approved_iban_sha256,
        reviewed_provider_id=reviewed_provider_id,
        monitoring_category=monitoring_category, clock=clock,
    )

    def ledger_snapshot() -> tuple:
        try:
            snap = independent_positions()
            now = clock()
        except Exception:
            raise KrakenProtectionDenied("independent_ledger_read_failed") from None
        if not isinstance(snap, Mapping):
            raise KrakenProtectionDenied("independent_ledger_invalid")
        stamp = snap.get("observed_at_epoch")
        if (snap.get("account") != account_scope
                or snap.get("provider_id") != reviewed_ledger_provider_id
                or snap.get("source") != "independent_ledger"
                or snap.get("snapshot_complete") is not True
                or snap.get("fills_reconciled") is not True
                or snap.get("positions_reconciled") is not True
                or not isinstance(snap.get("snapshot_id"), str)
                or not snap["snapshot_id"]
                or isinstance(stamp, bool) or not isinstance(stamp, (int, float))
                or not math.isfinite(stamp) or not 0 <= now - stamp <= MAX_AGE):
            raise KrakenProtectionDenied("independent_ledger_unverified")
        positions = snap.get("positions")
        if not isinstance(positions, Mapping) or not positions or len(positions) > 100:
            raise KrakenProtectionDenied("complete_nonempty_positions_required")
        normalized = []
        used = set()
        for lot_id, lot in positions.items():
            if (not isinstance(lot_id, str) or not lot_id
                    or not isinstance(lot, Mapping)
                    or set(lot) != {"pair", "side", "quantity", "stop_order_id", "take_profit_order_id"}
                    or lot.get("side") not in ("long", "short")):
                raise KrakenProtectionDenied("ledger_lot_invalid")
            try:
                pair = _canonical_pair(lot["pair"])
                qty = _decimal(lot["quantity"], positive=True)
            except Exception:
                raise KrakenProtectionDenied("ledger_quantity_invalid") from None
            stop, profit = lot["stop_order_id"], lot["take_profit_order_id"]
            if (not isinstance(stop, str) or not isinstance(profit, str)
                    or not _ORDER_ID.fullmatch(stop) or not _ORDER_ID.fullmatch(profit) or stop == profit
                    or stop in used or profit in used):
                raise KrakenProtectionDenied("exit_identity_missing_or_reused")
            used.update((stop, profit))
            normalized.append((lot_id, pair, lot["side"], qty, stop, profit))
        return (snap["snapshot_id"], tuple(sorted(normalized)))

    def verify_coverage(positions: tuple, orders: Mapping[str, tuple]) -> None:
        for _lot, pair, side, quantity, stop_id, profit_id in positions:
            exit_side = "sell" if side == "long" else "buy"
            for order_id, allowed in ((stop_id, STOP_TYPES), (profit_id, PROFIT_TYPES)):
                row = orders.get(order_id)
                if row is None:
                    raise KrakenProtectionDenied("protective_order_not_open")
                order_pair, order_side, kind, _price, volume, executed = row
                remaining = Decimal(volume) - Decimal(executed)
                if (order_pair != pair or order_side != exit_side
                        or kind not in allowed or remaining < quantity):
                    raise KrakenProtectionDenied("protective_exit_coverage_mismatch")

    def observe() -> Mapping[str, Any]:
        try:
            start = clock()
            if not isinstance(start, (int, float)) or isinstance(start, bool) or not math.isfinite(start):
                raise KrakenProtectionDenied("clock_invalid")
            if identity().get("verified") is not True:
                raise KrakenProtectionDenied("broker_identity_unverified")
            first_ledger = ledger_snapshot()
            first_orders = _broker_orders(broker, monitoring_category=monitoring_category)
            second_orders = _broker_orders(broker, monitoring_category=monitoring_category)
            second_ledger = ledger_snapshot()
            if identity().get("verified") is not True:
                raise KrakenProtectionDenied("broker_identity_changed")
            finish = clock()
            if (not isinstance(finish, (int, float)) or isinstance(finish, bool)
                    or not math.isfinite(finish) or not 0 <= finish - start <= MAX_AGE
                    or first_ledger != second_ledger or first_orders != second_orders):
                raise KrakenProtectionDenied("readback_changed_or_stale")
            verify_coverage(first_ledger[1], first_orders)
            digest = hashlib.sha256(json.dumps(
                [first_ledger[0], sorted(first_orders.items())],
                separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            return {
                "account": account_scope, "source": "authenticated_broker",
                "provider_id": reviewed_provider_id,
                "evidence_id": digest, "verified": True, "read_only": True,
                "scope_verified": True, "observed_at_epoch": start,
                "authorizes_orders": False,
                "provenance": {
                    "account_scope_verified": True,
                    "collector_identity_verified": True,
                    "snapshot_complete": True,
                    "authenticated_broker_read_verified": True,
                    "complete_pagination_verified": True,
                },
            }
        except KrakenProtectionDenied:
            raise
        except Exception:
            raise KrakenProtectionDenied("protective_readback_unavailable") from None

    return observe


__all__ = ["KrakenProtectionDenied", "make_kraken_protective_exit_provider"]
