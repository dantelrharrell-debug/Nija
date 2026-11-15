"""Authenticate spot inventory and compare it to ledger and adopted runtime state.

Uses the existing broker only. The reviewed default-wallet scope deliberately
matches the ledger provider's BTC/USD and ETH/USD long-spot coverage. Unsupported
holdings, margin, missing attribution, stale snapshots and mismatches deny.
No position adoption, order changes, second client or automatic registration.
"""
from __future__ import annotations

import copy
import math
import os
import time
import uuid
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from bot.kraken_authenticated_identity_v480 import make_kraken_account_identity_provider
from bot.kraken_authenticated_open_order_reconciliation_v482 import _canonical_pair
from bot.pretrade_attestation_validation_v452 import evidence_expiry_failure


class KrakenPositionSyncDenied(ValueError):
    """Sanitized fixed denial reason."""


def _require(value: bool, reason: str) -> None:
    if not value:
        raise KrakenPositionSyncDenied(reason)


def _stamp(value: Any, now: float) -> float:
    _require(type(value) in (int, float) and math.isfinite(value)
             and 0 < value <= now and now - value < 60, "source_snapshot_stale")
    return float(value)


def _quantity(value: Any) -> Decimal:
    _require(type(value) in (str, int, float, Decimal) and len(str(value)) <= 128,
             "position_quantity_invalid")
    try:
        number = Decimal(str(value))
        _require(number.is_finite() and number >= 0
                 and (not number or abs(number.adjusted()) <= 60), "position_quantity_invalid")
    except (ValueError, InvalidOperation):
        raise KrakenPositionSyncDenied("position_quantity_invalid") from None
    return number


def _pair(value: Any) -> str:
    try:
        aliases = {"BTC/USD": "BTCUSD", "XBT/USD": "XBTUSD", "ETH/USD": "ETHUSD",
                   "BTC-USD": "BTCUSD", "XBT-USD": "XBTUSD", "ETH-USD": "ETHUSD"}
        pair = _canonical_pair(aliases.get(value, value))
    except Exception:
        raise KrakenPositionSyncDenied("position_pair_invalid") from None
    _require(pair in {"BTCUSD", "ETHUSD"}, "position_pair_unsupported")
    return pair


def _runtime_max_age() -> float:
    # Mirror v285's documented 15..600s clamp without importing its runtime
    # patch graph. Evidence additionally has a hard 60s ceiling.
    try:
        value = float(os.environ.get("NIJA_AUTHORITATIVE_POSITION_SNAPSHOT_MAX_AGE_S", "90") or 90)
    except (TypeError, ValueError):
        raise KrakenPositionSyncDenied("runtime_age_config_invalid") from None
    _require(math.isfinite(value), "runtime_age_config_invalid")
    return min(60.0, max(15.0, min(600.0, value)))


def make_kraken_position_sync_provider(
    broker: Any, *, account_scope: str, approved_api_key_sha256: str,
    approved_iban_sha256: str, reviewed_provider_id: str,
    reviewed_ledger_provider_id: str,
    independent_positions: Callable[[], Mapping[str, Any]],
    monitoring_category: Any, independently_reviewed: bool = False,
    clock: Callable[[], float] = time.time,
    identity_method: str = "response_echo",
) -> Callable[[], Mapping[str, Any]]:
    """Compare current authenticated holdings with complete ledger and v285 adoption.

The independent position reader is the same reconciled ledger interface used
by v485. Revisions/content and original timestamps must remain unchanged.
An empty margin response never proves spot inventory is empty. Balance and
OpenPositions are both queried; any unsupported nonzero holding denies.
    """
    _require(independently_reviewed is True, "independent_review_required")
    _require(account_scope == "platform:kraken" and callable(independent_positions)
             and callable(clock), "reviewed_platform_sources_required")
    _require(all(isinstance(v, str) and v and v == v.strip()
                 and not any(c.isspace() for c in v)
                 for v in (reviewed_provider_id, reviewed_ledger_provider_id))
             and reviewed_provider_id != reviewed_ledger_provider_id,
             "independent_provider_ids_required")
    identity = make_kraken_account_identity_provider(
        broker, account_scope=account_scope, approved_api_key_sha256=approved_api_key_sha256,
        approved_iban_sha256=approved_iban_sha256, reviewed_provider_id=reviewed_provider_id,
        monitoring_category=monitoring_category, clock=clock, identity_method=identity_method,
    )

    def ledger() -> tuple[Mapping[str, Any], dict[str, Decimal], float, float]:
        snap = copy.deepcopy(independent_positions())
        _require(isinstance(snap, Mapping), "ledger_snapshot_invalid")
        _require(snap.get("account") == account_scope
                 and snap.get("provider_id") == reviewed_ledger_provider_id
                 and snap.get("source") == "independent_ledger"
                 and all(snap.get(k) is True for k in (
                     "snapshot_complete", "fills_reconciled", "positions_reconciled"))
                 and isinstance(snap.get("snapshot_id"), str) and bool(snap["snapshot_id"]),
                 "reconciled_ledger_required")
        stamp = _stamp(snap.get("observed_at_epoch"), clock())
        _require(evidence_expiry_failure(snap, now_epoch=clock()) is None, "ledger_source_expired")
        expiry = min(stamp + 60, snap.get("expires_at_epoch", stamp + 60))
        rows = snap.get("positions")
        _require(isinstance(rows, Mapping) and len(rows) <= 100, "ledger_positions_incomplete")
        totals: dict[str, Decimal] = {}
        for lot_id, row in rows.items():
            _require(isinstance(lot_id, str) and bool(lot_id) and isinstance(row, Mapping)
                     and row.get("side") == "long", "ledger_lot_unsupported")
            pair, quantity = _pair(row.get("pair")), _quantity(row.get("quantity"))
            _require(quantity > 0, "ledger_quantity_invalid")
            totals[pair] = totals.get(pair, Decimal(0)) + quantity
        return snap, totals, stamp, expiry

    def adopted() -> tuple[Any, dict[str, Decimal], float, float]:
        _require(all(getattr(broker, field, None) is True for field in (
            "_startup_position_sync_fetch_ok", "_startup_position_sync_adopted",
            "_nija_authoritative_position_snapshot_fetch_ok_v285")), "runtime_positions_not_adopted")
        generation = getattr(broker, "_nija_authoritative_position_snapshot_generation_v285", None)
        _require(type(generation) is int and generation > 0, "runtime_generation_invalid")
        wall = getattr(broker, "_nija_authoritative_position_snapshot_at_wall_v285", None)
        stamp = _stamp(wall, clock())
        max_age = _runtime_max_age()
        _require(clock() - stamp < max_age, "runtime_snapshot_stale")
        mono = getattr(broker, "_nija_authoritative_position_snapshot_at_monotonic_v285", None)
        _require(type(mono) in (int, float) and math.isfinite(mono)
                 and mono > 0 and 0 <= time.monotonic() - mono < max_age, "runtime_snapshot_stale")
        rows = copy.deepcopy(getattr(broker, "_nija_authoritative_position_snapshot_rows_v285", None))
        _require(type(rows) in (list, tuple) and len(rows) <= 100, "runtime_positions_incomplete")
        totals: dict[str, Decimal] = {}
        for row in rows:
            _require(isinstance(row, Mapping), "runtime_position_invalid")
            pair, quantity = _pair(row.get("symbol")), _quantity(row.get("quantity"))
            _require(pair not in totals and quantity > 0, "runtime_position_duplicate_or_invalid")
            totals[pair] = quantity
        return (generation, wall, mono, rows, max_age), totals, stamp, stamp + max_age

    def exchange() -> dict[str, Decimal]:
        results = []
        for endpoint in ("Balance", "OpenPositions"):
            reply = broker._kraken_private_call(endpoint, {}, category=monitoring_category)
            _require(isinstance(reply, Mapping) and reply.get("error") == []
                     and isinstance(reply.get("result"), Mapping), "authenticated_position_read_failed")
            results.append(reply["result"])
        balances, margin = results
        _require(not margin, "margin_inventory_unsupported")
        _require(len(balances) <= 4096, "balance_inventory_invalid")
        aliases = {"XXBT": "BTCUSD", "XBT": "BTCUSD", "BTC": "BTCUSD",
                   "XETH": "ETHUSD", "ETH": "ETHUSD", "ZUSD": "cash", "USD": "cash"}
        totals: dict[str, Decimal] = {}
        seen: set[str] = set()
        for asset, value in balances.items():
            quantity = _quantity(value)
            if not quantity:
                continue
            pair = aliases.get(asset)
            _require(pair is not None and pair not in seen, "unsupported_or_ambiguous_balance_asset")
            seen.add(pair)
            if pair != "cash":
                totals[pair] = quantity
        return totals

    def observe() -> Mapping[str, Any]:
        try:
            start = clock()
            _stamp(start, start)
            monotonic = time.monotonic()
            with localcontext() as context:
                context.prec = 256
                identity()
                first_ledger, expected, ledger_stamp, ledger_expiry = ledger()
                first_runtime, runtime, runtime_stamp, runtime_expiry = adopted()
                first_exchange = exchange()
                second_exchange = exchange()
                second_runtime, _, _, _ = adopted()
                second_ledger, _, _, _ = ledger()
                identity()
            finish = clock()
            _stamp(start, finish)
            stamp = min(start, ledger_stamp, runtime_stamp)
            _stamp(stamp, finish)
            expires = min(stamp + 60, ledger_expiry, runtime_expiry)
            _require(finish < expires, "position_source_expired")
            _require(0 <= time.monotonic() - monotonic < 60, "collection_stale")
            _require(first_ledger == second_ledger and first_runtime == second_runtime
                     and first_exchange == second_exchange, "position_sources_changed")
            _require(first_exchange == expected == runtime, "position_inventory_mismatch")
            return {
                "account": account_scope, "source": "authenticated_broker",
                "provider_id": reviewed_provider_id, "evidence_id": uuid.uuid4().hex,
                "verified": True, "read_only": True, "scope_verified": True,
                "observed_at_epoch": stamp, "expires_at_epoch": expires,
                "authorizes_orders": False,
                "provenance": {
                    "account_scope_verified": True, "collector_identity_verified": True,
                    "snapshot_complete": True, "authenticated_broker_read_verified": True,
                    "complete_pagination_verified": True,
                },
            }
        except KrakenPositionSyncDenied:
            raise
        except Exception:
            raise KrakenPositionSyncDenied("position_sync_read_unverified") from None

    return observe
