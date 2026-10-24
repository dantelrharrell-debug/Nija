"""One-shot, non-authorizing exact Kraken QueryOrders readback for pending closes.

Explicitly injected, ALREADY-AUTHENTICATED Kraken broker only; no construction of
credentials or a nonce owner. No mutation of trading state, orders or the ledger.
This adapter is NOT installed in production. Requires a separately reviewed
operator/rate budget prior to calling it from an audited composition root.
"""
from __future__ import annotations

import math
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import sqlite3
import time
from typing import Any

from scripts.nija_kraken_readonly_history_collector_v441 import _broker_account_scope

ORDER_ID = re.compile(r"O[A-Z0-9]{5}-[A-Z0-9]{5}-[A-Z0-9]{6}\Z")
REQUIRED_COLUMNS = {"broker", "account_scope", "order_id", "symbol", "side",
                    "fill_price", "filled_usd", "exit_fee", "state"}
MAX_IDS = 50  # Kraken QueryOrders documented maximum
_ALLOWED_STATUSES = frozenset({"open", "closed", "canceled", "cancelled", "expired", "pending"})


class ReadbackDenied(ValueError):
    """Fixed safe reason only; never include private order ID or broker errors."""


def _decimal(value: Any) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ReadbackDenied("numeric_field_invalid")
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, OverflowError):
        raise ReadbackDenied("numeric_field_invalid") from None
    if not d.is_finite() or d < 0:
        raise ReadbackDenied("numeric_field_invalid")
    return d


def _pair(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 50:
        raise ReadbackDenied("pair_unavailable")
    compact = "".join(c for c in value.strip().upper().split(":", 1)[0] if c.isalnum())
    if compact in {"XXBTZUSD", "XBTUSD", "BTCUSD"}:
        return "BTCUSD"
    if compact in {"XETHZUSD", "ETHUSD"}:
        return "ETHUSD"
    return compact


def _near(a: Decimal, b: Decimal) -> bool:
    return abs(a - b) <= max(Decimal("0.00000001"), max(a, b) * Decimal("0.000001"))


def _read_pending(ledger: Path) -> dict[str, tuple[str, str, Decimal, Decimal, Decimal]]:
    """Read one SQLite snapshot without assuming an empty table means flat."""
    if not ledger.is_absolute() or ledger.is_symlink() or not ledger.is_file():
        raise ReadbackDenied("ledger_path_unverified")
    try:
        with sqlite3.connect(ledger.as_uri() + "?mode=ro", uri=True, timeout=3.0) as db:
            db.execute("PRAGMA query_only=ON")
            if db.execute("PRAGMA integrity_check").fetchone() != ("ok",):
                raise ReadbackDenied("ledger_integrity_invalid")
            columns = {row[1] for row in db.execute('PRAGMA table_info("pending_kraken_closes")')}
            if not REQUIRED_COLUMNS.issubset(columns):
                raise ReadbackDenied("pending_schema_invalid")
            rows = db.execute(
                "SELECT order_id,symbol,side,fill_price,filled_usd,exit_fee "
                "FROM pending_kraken_closes WHERE broker=? AND account_scope=? AND state=?",
                ("kraken", "platform:kraken", "pending"),
            ).fetchall()
    except sqlite3.Error:
        raise ReadbackDenied("ledger_read_unavailable") from None
    if not 1 <= len(rows) <= MAX_IDS:
        raise ReadbackDenied("pending_count_unavailable_or_exceeds_budget")
    result = {}
    for order_id, symbol, side, price, cost, fee in rows:
        if not isinstance(order_id, str) or not ORDER_ID.fullmatch(order_id) or order_id in result:
            raise ReadbackDenied("pending_order_ids_invalid_or_duplicated")
        if side not in {"buy", "sell"}:
            raise ReadbackDenied("pending_order_side_invalid")
        result[order_id] = (_pair(symbol), side, _decimal(price), _decimal(cost), _decimal(fee))
    return result


def inspect_exact_pending_orders(ledger: Path, broker: Any, *,
                                 account_scope: str, monitoring_category: Any) -> dict[str, Any]:
    """Read each pending order exactly once in one bounded authenticated query.

    A matching result is an order-readback observation, NOT fill or ownership
    certification. Identifiers and raw broker rows are never returned/logged.
    The trusted application must explicitly invoke this after rate review.
    """
    if account_scope != "platform:kraken":
        raise ReadbackDenied("account_scope_invalid")
    if monitoring_category is None or getattr(broker, "connected", False) is not True:
        raise ReadbackDenied("authenticated_client_unavailable")
    try:
        if _broker_account_scope(broker) != account_scope:
            raise ReadbackDenied("account_routing_mismatch")
    except (ValueError, AttributeError):
        raise ReadbackDenied("account_routing_mismatch") from None
    call = getattr(broker, "_kraken_private_call", None)
    if not callable(call):
        raise ReadbackDenied("authenticated_client_unavailable")
    pending = _read_pending(Path(ledger))
    identifiers = sorted(pending)
    start = time.time()
    # No retries, new clients, order-placement calls, or nonce-writing sidecars.
    try:
        response = call("QueryOrders", {"txid": ",".join(identifiers), "trades": True},
                        category=monitoring_category)
    except Exception:
        raise ReadbackDenied("authenticated_read_unavailable") from None
    finished = time.time()
    if not math.isfinite(start) or not math.isfinite(finished) or finished < start:
        raise ReadbackDenied("observation_clock_invalid")
    try:
        if _broker_account_scope(broker) != account_scope or getattr(broker, "connected", False) is not True:
            raise ReadbackDenied("account_routing_changed")
    except (ValueError, AttributeError):
        raise ReadbackDenied("account_routing_changed") from None
    if _read_pending(Path(ledger)) != pending:
        raise ReadbackDenied("ledger_changed_during_readback")
    if not isinstance(response, Mapping) or response.get("error") != []:
        raise ReadbackDenied("broker_query_failed")
    orders = response.get("result")
    if not isinstance(orders, Mapping) or set(orders) != set(pending):
        raise ReadbackDenied("exact_broker_order_set_incomplete")
    numeric_match = 0
    status_counts: dict[str, int] = {}
    for oid in identifiers:
        row = orders[oid]
        if not isinstance(row, Mapping) or not isinstance(row.get("descr"), Mapping):
            raise ReadbackDenied("broker_order_row_invalid")
        status = row.get("status")
        if status not in _ALLOWED_STATUSES:
            raise ReadbackDenied("broker_order_status_unverified")
        status_counts[status] = status_counts.get(status, 0) + 1
        symbol, side, recorded_price, recorded_cost, recorded_fee = pending[oid]
        descr = row["descr"]
        if _pair(descr.get("pair")) != symbol or descr.get("type") != side:
            raise ReadbackDenied("broker_order_symbol_or_side_mismatch")
        # These terms are readback comparisons only, NOT settlement evidence.
        actual_price = _decimal(row.get("price"))
        actual_cost = _decimal(row.get("cost"))
        actual_fee = _decimal(row.get("fee"))
        actual_vol = _decimal(row.get("vol_exec"))
        if actual_vol <= 0 or actual_cost <= 0 or actual_price <= 0:
            raise ReadbackDenied("broker_fill_terms_absent")
        if not (_near(actual_price, recorded_price)
                and _near(actual_cost, recorded_cost)
                and _near(actual_fee, recorded_fee)):
            raise ReadbackDenied("broker_fill_terms_disagree_with_audit")
        numeric_match += 1
    return {
        "status": "READ_ONLY_EXACT_ORDERS_OBSERVED",
        "account_scope": "platform_only",
        "requested_pending": len(identifiers),
        "broker_order_references_matched": len(orders),
        "audit_terms_consistent": numeric_match,
        "broker_status_counts": status_counts,
        "read_started_epoch": start,
        "read_finished_epoch": finished,
        "single_authenticated_query": True,
        "historical_account_completeness_verified": False,
        "authenticated_owner_independently_verified": False,
        "opening_lots_reconciled": False,
        "fills_and_fees_independently_reconciled": False,
        "protective_exit_coverage_verified": False,
        "ledger_writes_performed": False,
        "orders_submitted": False,
        "execution_authorized": False,
    }


def safe_inspection(ledger: Path, broker: Any, *, account_scope: str,
                    monitoring_category: Any) -> dict[str, Any]:
    """Redacted operator diagnostic wrapper; no upstream text in reports."""
    try:
        return inspect_exact_pending_orders(ledger, broker,
            account_scope=account_scope, monitoring_category=monitoring_category)
    except ReadbackDenied as exc:
        reason = str(exc)
        return {"status": "FAILED_CLOSED", "failure_code": reason,
                "ledger_writes_performed": False, "orders_submitted": False,
                "execution_authorized": False}
    except Exception:
        return {"status": "FAILED_CLOSED", "failure_code": "unexpected_readback_failure",
                "ledger_writes_performed": False, "orders_submitted": False,
                "execution_authorized": False}
