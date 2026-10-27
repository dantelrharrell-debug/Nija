"""Independently matched, read-only Kraken open-order evidence (v452 single field).

Only the trusted composition root may bind the existing nonce-owning Kraken
client, external approved account/key pins, and an independently reviewed live
ledger-open-intent reader. No startup hook or registration. This is NOT the
separate historical fill/lot reconciliation or protective-exit certification.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import time
from collections.abc import Callable, Mapping
from decimal import Decimal, InvalidOperation
from typing import Any

from bot.kraken_authenticated_identity_v480 import make_kraken_account_identity_provider

_ORDER_ID = re.compile(r"O[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{6}\Z")
_PAIR = re.compile(r"[A-Z0-9]{3,32}\Z")
_ORDER_TYPES = frozenset({
    "limit", "market", "stop-loss", "stop-loss-limit", "take-profit",
    "take-profit-limit", "trailing-stop", "trailing-stop-limit",
    "settle-position", "iceberg",
})
_PAGE_SIZE = 50
_MAX_PAGES = 10
_MAX_AGE_S = 60.0


class KrakenOpenOrderDenied(ValueError):
    """Non-sensitive reason code: do not retain raw broker/ledger exceptions."""


def _id(value: Any) -> bool:
    return (isinstance(value, str) and bool(value) and value == value.strip()
            and not any(char.isspace() for char in value))


def _decimal(value: Any, *, positive: bool = False) -> Decimal:
    if (isinstance(value, bool) or not isinstance(value, (str, int, Decimal))
            or len(str(value)) > 128):
        raise KrakenOpenOrderDenied("order_amount_invalid")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise KrakenOpenOrderDenied("order_amount_invalid") from None
    if (not amount.is_finite() or amount < 0
            or (positive and amount <= 0) or (amount and abs(amount.adjusted()) > 60)):
        raise KrakenOpenOrderDenied("order_amount_invalid")
    return amount


def _canonical_pair(value: Any) -> str:
    if not isinstance(value, str) or not _PAIR.fullmatch(value.upper()):
        raise KrakenOpenOrderDenied("order_pair_invalid")
    normalized = value.upper()
    return {"XXBTZUSD": "BTCUSD", "XBTUSD": "BTCUSD",
            "XETHZUSD": "ETHUSD"}.get(normalized, normalized)


def _orders(rows: Any, *, from_broker: bool) -> dict[str, tuple[str, str, str, str, str, str]]:
    if not isinstance(rows, Mapping) or len(rows) > _PAGE_SIZE * _MAX_PAGES:
        raise KrakenOpenOrderDenied("order_registry_invalid")
    output = {}
    for txid, row in rows.items():
        if not isinstance(txid, str) or not _ORDER_ID.fullmatch(txid) or not isinstance(row, Mapping):
            raise KrakenOpenOrderDenied("order_identity_invalid")
        if from_broker:
            description = row.get("descr")
            if not isinstance(description, Mapping) or row.get("status") != "open":
                raise KrakenOpenOrderDenied("order_status_or_description_invalid")
            pair, side, kind, price = (
                description.get("pair"), description.get("type"),
                description.get("ordertype"), description.get("price"),
            )
            volume, executed = row.get("vol"), row.get("vol_exec")
        else:
            if set(row) != {"pair", "side", "ordertype", "price", "volume", "executed"}:
                raise KrakenOpenOrderDenied("ledger_order_fields_invalid")
            pair, side, kind, price = (row["pair"], row["side"], row["ordertype"], row["price"])
            volume, executed = row["volume"], row["executed"]
        if side not in ("buy", "sell") or kind not in _ORDER_TYPES:
            raise KrakenOpenOrderDenied("order_side_or_type_invalid")
        vol = _decimal(volume, positive=True)
        filled = _decimal(executed)
        if filled > vol:
            raise KrakenOpenOrderDenied("order_filled_exceeds_volume")
        limit = _decimal(price)
        output[txid] = (
            _canonical_pair(pair), side, kind, format(limit.normalize(), "f"),
            format(vol.normalize(), "f"), format(filled.normalize(), "f"),
        )
    return output


def _ledger_snapshot(read: Callable[[], Mapping[str, Any]], *,
                     account: str, ledger_id: str, now: float) -> tuple[dict[str, tuple[str, str, str, str, str, str]], str]:
    try:
        snapshot = read()
    except Exception:
        raise KrakenOpenOrderDenied("independent_ledger_read_failed") from None
    if not isinstance(snapshot, Mapping):
        raise KrakenOpenOrderDenied("independent_ledger_unverified")
    observed = snapshot.get("observed_at_epoch")
    if (snapshot.get("account") != account
            or snapshot.get("provider_id") != ledger_id
            or snapshot.get("source") != "independent_ledger"
            or snapshot.get("snapshot_complete") is not True
            or snapshot.get("outstanding_intents_reconciled") is not True
            or type(snapshot.get("unresolved_submission_count")) is not int
            or snapshot.get("unresolved_submission_count") != 0
            or not _id(snapshot.get("snapshot_id"))
            or isinstance(observed, bool) or not isinstance(observed, (int, float))
            or not math.isfinite(observed) or not 0 <= now - observed <= _MAX_AGE_S):
        raise KrakenOpenOrderDenied("independent_ledger_unverified")
    return _orders(snapshot.get("orders"), from_broker=False), snapshot["snapshot_id"]


def _broker_orders(broker: Any, *, monitoring_category: Any) -> dict[str, tuple[str, str, str, str, str, str]]:
    read = getattr(broker, "_kraken_private_call", None)
    if not callable(read):
        raise KrakenOpenOrderDenied("authenticated_broker_read_unavailable")
    params: dict[str, Any] = {"with_cursor": True, "limit": _PAGE_SIZE, "trades": True}
    all_rows: dict[str, Any] = {}
    cursors: set[str] = set()
    for _ in range(_MAX_PAGES):
        try:
            response = read("OpenOrders", params, category=monitoring_category)
        except Exception:
            raise KrakenOpenOrderDenied("authenticated_open_order_read_failed") from None
        if (not isinstance(response, Mapping) or response.get("error") != []
                or not isinstance(response.get("result"), Mapping)):
            raise KrakenOpenOrderDenied("authenticated_open_order_envelope_invalid")
        result = response["result"]
        batch, page = result.get("open"), result.get("cursor")
        if (not isinstance(batch, Mapping) or len(batch) > _PAGE_SIZE
                or not isinstance(page, Mapping)
                or set(result) - {"open", "cursor"}):
            # Explicit cursor proof is required. A non-cursor endpoint response
            # must never be mistaken for a complete first page.
            raise KrakenOpenOrderDenied("open_order_pagination_unverified")
        if any(txid in all_rows for txid in batch):
            raise KrakenOpenOrderDenied("open_order_duplicate_across_pages")
        all_rows.update(batch)
        if len(all_rows) > _PAGE_SIZE * _MAX_PAGES:
            raise KrakenOpenOrderDenied("open_order_page_budget_exceeded")
        nxt = page.get("next")
        if nxt is None or nxt == "":
            return _orders(all_rows, from_broker=True)
        if not isinstance(nxt, str) or not nxt.strip() or nxt in cursors or not batch:
            raise KrakenOpenOrderDenied("open_order_pagination_unverified")
        cursors.add(nxt)
        params = {"with_cursor": True, "limit": _PAGE_SIZE, "trades": True, "cursor": nxt}
    raise KrakenOpenOrderDenied("open_order_page_budget_exceeded")


def make_kraken_open_order_reconciliation_provider(
    broker: Any, *, account_scope: str, approved_iban_sha256: str,
    approved_api_key_sha256: str, reviewed_provider_id: str,
    reviewed_ledger_provider_id: str,
    independent_open_intents: Callable[[], Mapping[str, Any]],
    monitoring_category: Any, clock: Callable[[], float] = time.time,
) -> Callable[[], Mapping[str, Any]]:
    """Match unchanged authenticated OpenOrders to independent ledger intents.

    The independent callback MUST be bound by a separately audited composition
    root; observations are not accepted from configuration booleans or user input.
    A matching open-order set is NOT a historical ledger/fill reconciliation,
    risk authorization or evidence of exchange-side protective exits.
    """
    if (not _id(reviewed_provider_id) or not _id(reviewed_ledger_provider_id)
            or reviewed_provider_id == reviewed_ledger_provider_id
            or not callable(independent_open_intents) or not callable(clock)):
        raise KrakenOpenOrderDenied("separate_reviewed_provider_bindings_required")
    identity = make_kraken_account_identity_provider(
        broker, account_scope=account_scope, approved_iban_sha256=approved_iban_sha256,
        approved_api_key_sha256=approved_api_key_sha256,
        reviewed_provider_id=reviewed_provider_id,
        monitoring_category=monitoring_category, clock=clock,
    )

    def observe() -> Mapping[str, Any]:
        try:
            started = clock()
            if (isinstance(started, bool) or not isinstance(started, (int, float))
                    or not math.isfinite(started) or started <= 0):
                raise KrakenOpenOrderDenied("observation_clock_invalid")
            first_identity = identity()
            if (first_identity.get("account") != account_scope
                    or first_identity.get("verified") is not True):
                raise KrakenOpenOrderDenied("authenticated_identity_unverified")
            ledger_first = _ledger_snapshot(
                independent_open_intents, account=account_scope,
                ledger_id=reviewed_ledger_provider_id, now=clock(),
            )
            open_first = _broker_orders(broker, monitoring_category=monitoring_category)
            open_second = _broker_orders(broker, monitoring_category=monitoring_category)
            ledger_second = _ledger_snapshot(
                independent_open_intents, account=account_scope,
                ledger_id=reviewed_ledger_provider_id, now=clock(),
            )
            second_identity = identity()
            finished = clock()
            if (not isinstance(finished, (int, float)) or isinstance(finished, bool)
                    or not math.isfinite(finished) or not 0 <= finished - started <= _MAX_AGE_S):
                raise KrakenOpenOrderDenied("observation_stale_or_invalid")
            if (second_identity.get("account") != account_scope
                    or second_identity.get("verified") is not True
                    or open_first != open_second or ledger_first != ledger_second
                    or open_first != ledger_first[0]):
                raise KrakenOpenOrderDenied("broker_ledger_open_orders_disagree")
            digest = hashlib.sha256(json.dumps(
                sorted(open_first.items()), separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            receipt = hashlib.sha256(
                ("kraken-open-orders-v482:" + account_scope + ":" + digest + ":" +
                 repr(started)).encode("utf-8")
            ).hexdigest()
            return {
                "account": account_scope, "source": "authenticated_broker",
                "provider_id": reviewed_provider_id, "evidence_id": receipt,
                "verified": True, "read_only": True, "scope_verified": True,
                "observed_at_epoch": started, "authorizes_orders": False,
                "provenance": {
                    "account_scope_verified": True,
                    "collector_identity_verified": True, "snapshot_complete": True,
                    "authenticated_broker_read_verified": True,
                    "complete_pagination_verified": True,
                },
            }
        except KrakenOpenOrderDenied:
            raise
        except Exception:
            raise KrakenOpenOrderDenied("open_order_reconciliation_unavailable") from None

    return observe


__all__ = ["KrakenOpenOrderDenied", "make_kraken_open_order_reconciliation_provider"]
