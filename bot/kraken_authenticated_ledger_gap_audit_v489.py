"""One-shot, read-only Kraken broker-to-ledger gap audit (v489).

Uses the EXISTING nonce-owning authenticated Kraken client and NIJA's v441
complete, repeat-checked private history reader. It compares broker fills to
real platform ledger rows in the existing SQLite store. It does not invent
order ownership or infer missing cost basis, protect positions, edit records,
install a pretrade provider, or authorize orders.

This operation requires a separately approved monitoring API budget. Do not
call from startup, heartbeat, public routes, or other automatic retry loops.
The result intentionally NEVER conforms to the v452 attestation contract.
"""
from __future__ import annotations

import math
import sqlite3
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from bot.kraken_authenticated_identity_v480 import (
    make_kraken_account_identity_provider,
)
from bot.kraken_authenticated_open_order_reconciliation_v482 import (
    _ORDER_ID, _canonical_pair,
)
from bot.kraken_sqlite_readonly_preflight_v488 import inspect_kraken_ledger
from scripts.nija_kraken_readonly_history_collector_v441 import (
    collect_from_existing_broker,
)

SCOPE = "platform:kraken"
MAX_APPROVED_PAGES = 10
MAX_LOCAL_ROWS = 10000


def _amount(value: Any, *, positive: bool = False) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError("non_decimal")
    if len(str(value)) > 128:
        raise ValueError("non_decimal")
    try:
        number = Decimal(str(value))
    except (ValueError, InvalidOperation):
        raise ValueError("non_decimal") from None
    if (not number.is_finite() or number < 0
            or (positive and number <= 0)):
        raise ValueError("non_decimal")
    return number


def _pair(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("pair_invalid")
    # The SQLite ledger uses BTC-USD / ETH-USD; Kraken returns XBTUSD,
    # XXBTZUSD, XETHZUSD etc. Reject other punctuation.
    cleaned = value.upper().replace("-", "").replace("/", "")
    return _canonical_pair(cleaned)


def _summarize_trades(trades: Any) -> dict[str, tuple[str, str, Decimal, Decimal, Decimal]]:
    """Aggregate *all* Kraken fills per exact exchange order ID."""
    if not isinstance(trades, Mapping) or not trades:
        raise ValueError("authenticated_trades_missing")
    orders: dict[str, tuple[str, str, Decimal, Decimal, Decimal]] = {}
    seen: set[str] = set()
    for trade_id, row in trades.items():
        if (not isinstance(trade_id, str)
                or not trade_id.startswith("T") or trade_id in seen
                or not isinstance(row, Mapping)):
            raise ValueError("trade_identifier_invalid")
        seen.add(trade_id)
        order_id = row.get("ordertxid")
        side = row.get("type")
        if (not isinstance(order_id, str) or not _ORDER_ID.fullmatch(order_id)
                or side not in ("buy", "sell")):
            raise ValueError("broker_trade_order_link_invalid")
        pair = _pair(row.get("pair"))
        quantity = _amount(row.get("vol"), positive=True)
        cost = _amount(row.get("cost"))
        fee = _amount(row.get("fee"))
        price = _amount(row.get("price"), positive=True)
        # The broker publishes rounded quote values. Reject orders with
        # internally inconsistent values rather than minting a new basis.
        if abs(cost - quantity * price) > Decimal("0.0001") + cost * Decimal("0.000001"):
            raise ValueError("broker_trade_cost_inconsistent")
        prior = orders.get(order_id)
        if prior is None:
            orders[order_id] = (pair, side, quantity, cost, fee)
        else:
            old_pair, old_side, old_qty, old_cost, old_fee = prior
            if old_pair != pair or old_side != side:
                raise ValueError("broker_order_fill_conflict")
            orders[order_id] = (
                pair, side, old_qty + quantity, old_cost + cost, old_fee + fee,
            )
    return orders


def _summarize_ledger(rows: Any) -> tuple[
    dict[str, tuple[str, str, Decimal, Decimal, Decimal]], int
]:
    """Read actual SQLite ledger rows; never guess absent order ownership."""
    orders: dict[str, tuple[str, str, Decimal, Decimal, Decimal]] = {}
    unlinked = 0
    for order_id, symbol, side, action, qty, cost, fee in rows:
        if not isinstance(order_id, str) or not _ORDER_ID.fullmatch(order_id):
            unlinked += 1
            continue
        if (side, action) not in (("BUY", "OPEN"), ("SELL", "CLOSE")):
            raise ValueError("ledger_action_conflict")
        pair = _pair(symbol)
        quantity = _amount(qty, positive=True)
        notional = _amount(cost)
        commission = _amount(fee)
        normalized_side = side.lower()
        prior = orders.get(order_id)
        if prior is None:
            orders[order_id] = (pair, normalized_side, quantity, notional, commission)
        else:
            old_pair, old_side, old_qty, old_cost, old_fee = prior
            if old_pair != pair or old_side != normalized_side:
                raise ValueError("ledger_order_conflict")
            orders[order_id] = (
                pair, normalized_side, old_qty + quantity,
                old_cost + notional, old_fee + commission,
            )
    return orders, unlinked


def inspect_authenticated_kraken_ledger_gaps(
    broker: Any, *, ledger_path: Path, persistent_root: Path,
    approved_api_key_sha256: str, approved_iban_sha256: str,
    reviewed_identity_provider_id: str, monitoring_category: Any,
    max_pages: int, independently_reviewed: bool = False,
    monitoring_budget_approved: bool = False,
) -> dict[str, Any]:
    """Perform ONE authenticated, account-pinned gap audit; never certify trading.

    A complete full-history collection and exact local fill comparison are
    prerequisites, not sufficient evidence of audited lot attribution, backup,
    current protective orders, or pretrade order admission.
    """
    report: dict[str, Any] = {
        "status": "NOT_CERTIFIED",
        "account_scope": SCOPE,
        "read_only": True,
        "authorizes_orders": False,
        "collector_install_allowed": False,
        "independent_ledger_certified": False,
        "offhost_backup_restore_certified": False,
        "broker_protective_exit_coverage_certified": False,
        "historical_lot_basis_certified": False,
        "issues": [],
        "counts": {},
    }
    issues: list[str] = report["issues"]
    counts: dict[str, int] = report["counts"]

    def reject(code: str) -> dict[str, Any]:
        if code not in issues:
            issues.append(code)
        return report

    if (independently_reviewed is not True
            or monitoring_budget_approved is not True
            or type(max_pages) is not int or not 1 <= max_pages <= MAX_APPROVED_PAGES
            or monitoring_category is None):
        return reject("independent_review_and_private_read_budget_required")

    local = inspect_kraken_ledger(
        ledger_path, persistent_root=persistent_root,
    )
    if (local.get("sqlite_integrity_ok") is not True
            or any(item.startswith("required_table_or_columns_missing:")
                   for item in local["issues"])
            or "ledger_audit_row_budget_exceeded" in local["issues"]):
        return reject("local_ledger_schema_or_integrity_unverified")
    # Carry only allowlisted issue labels/counters, never positions or IDs.
    for issue in local["issues"]:
        if issue not in issues:
            issues.append(issue)
    counts.update(local["counts"])

    try:
        root = Path(persistent_root).resolve(strict=True)
        resolved = Path(ledger_path).resolve(strict=True)
        if root not in resolved.parents or not resolved.is_file():
            return reject("persistent_ledger_path_unverified")
        connection = sqlite3.connect(
            resolved.as_uri() + "?mode=ro", uri=True, timeout=3,
        )
    except (sqlite3.Error, ValueError, OSError):
        return reject("local_ledger_unavailable")
    try:
        connection.execute("PRAGMA query_only=ON")
        before = connection.execute("PRAGMA data_version").fetchone()[0]
        connection.execute("BEGIN")
        rows = connection.execute(
            "SELECT order_id,symbol,side,action,quantity,size_usd,fee "
            "FROM trade_ledger WHERE user_id='platform'"
        ).fetchall()
        intent_rows = connection.execute(
            "SELECT order_id FROM strategy_order_intents "
            "WHERE broker='kraken' AND account_scope='platform:kraken'"
        ).fetchall()
        connection.execute("COMMIT")
        if len(rows) > MAX_LOCAL_ROWS or len(intent_rows) > MAX_LOCAL_ROWS:
            return reject("ledger_comparison_row_budget_exceeded")
        ledger_orders, unattributed = _summarize_ledger(rows)
        counts["platform_ledger_rows_without_exchange_id"] = unattributed
        counts["platform_kraken_intent_rows"] = len(intent_rows)
        intent_ids = set()
        for (order_id,) in intent_rows:
            if not isinstance(order_id, str) or not _ORDER_ID.fullmatch(order_id):
                return reject("kraken_strategy_intent_identity_invalid")
            if order_id in intent_ids:
                return reject("duplicate_kraken_strategy_intent")
            intent_ids.add(order_id)
    except (sqlite3.Error, ValueError, TypeError):
        connection.close()
        return reject("ledger_accounting_records_invalid")

    try:
        # v480 pins the actual key and internal account identifier by authenticated
        # GetApiKeyInfo. Neither a cached software scope nor a supplied hash can
        # certify identity alone.
        identity = make_kraken_account_identity_provider(
            broker, account_scope=SCOPE,
            approved_api_key_sha256=approved_api_key_sha256,
            approved_iban_sha256=approved_iban_sha256,
            reviewed_provider_id=reviewed_identity_provider_id,
            monitoring_category=monitoring_category,
        )
        if identity().get("verified") is not True:
            return reject("authenticated_broker_identity_unverified")
        # v441 owns pagination, repeat checks, nonce isolation, scope verification,
        # balance bracketing and complete cursor-paginated OpenOrders. Never
        # construct an additional broker client, send orders or widen its budget.
        observed = collect_from_existing_broker(
            broker, account_scope=SCOPE,
            monitoring_category=monitoring_category, max_pages=max_pages,
            include_balance=True, include_open_orders=True,
        )
        if identity().get("verified") is not True:
            return reject("authenticated_broker_identity_changed")
        if (observed.get("account_scope_asserted_by_caller") != SCOPE
                or observed.get("repeat_read_consistent") is not True
                or observed.get("trading_authorized") is not False
                or not isinstance(observed.get("history"), Mapping)
                or not all(isinstance(observed["history"].get(key), Mapping)
                           for key in ("trades", "closed", "ledger"))
                or not isinstance(observed.get("open_orders"), Mapping)
                or not isinstance(observed.get("balance"), Mapping)):
            return reject("broker_history_or_scope_unverified")
        broker_orders = _summarize_trades(observed["history"]["trades"])
        counts["authenticated_kraken_fill_orders"] = len(broker_orders)
        counts["kraken_fill_orders_without_ledger"] = len(
            broker_orders.keys() - ledger_orders.keys()
        )
        counts["kraken_fill_orders_without_intents"] = len(
            broker_orders.keys() - intent_ids
        )
        counts["kraken_ledger_orders_without_fills"] = len(
            ledger_orders.keys() - broker_orders.keys()
        )
        counts["kraken_intents_without_fill"] = len(
            intent_ids - broker_orders.keys()
        )
        mismatch = 0
        for order_id in broker_orders.keys() & ledger_orders.keys():
            bp, bs, bq, bc, bf = broker_orders[order_id]
            lp, ls, lq, lc, lf = ledger_orders[order_id]
            if (bp != lp or bs != ls or bq != lq
                    or abs(bc - lc) > Decimal("0.01")
                    or abs(bf - lf) > Decimal("0.01")):
                mismatch += 1
        counts["broker_ledger_fill_amount_mismatches"] = mismatch
        if (counts["kraken_fill_orders_without_ledger"]
                or counts["kraken_ledger_orders_without_fills"]
                or mismatch):
            reject("authenticated_broker_fills_disagree_with_local_ledger")
        if counts["kraken_fill_orders_without_intents"] or counts["kraken_intents_without_fill"]:
            reject("kraken_strategy_intent_history_incomplete")
        if unattributed:
            reject("platform_ledger_exchange_attribution_incomplete")
        if not broker_orders:
            reject("broker_trade_history_empty_or_incomplete")
        if connection.execute("PRAGMA data_version").fetchone()[0] != before:
            reject("ledger_changed_during_broker_readback")
    except Exception:
        # Never emit exception text, raw broker histories, key/IBAN/IDs, or
        # SQLite rows. The operator retains confidential evidence separately.
        reject("authenticated_history_reconciliation_unavailable")
    finally:
        connection.close()

    # This remains non-certifying even if every matched order is exact. Broker
    # deposits/withdrawals, opening lots, stop/take-profit status, historical
    # basis, off-host backup custody and current operator risk still need proof.
    reject("historical_lots_protective_exits_and_backup_require_certification")
    return report


__all__ = ["inspect_authenticated_kraken_ledger_gaps"]
