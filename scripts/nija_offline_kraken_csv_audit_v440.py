#!/usr/bin/env python3
"""Offline, read-only comparison of pending Kraken closes to operator-supplied CSV exports.

This is an evidence triage tool, NOT authenticated exchange verification.
It never contacts a broker, writes to SQLite, computes realized P&L, or changes
trading authority. Its output MUST NOT be used as a release/readiness gate.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

MAX_CSV_BYTES = 32 * 1024 * 1024
REQUIRED_TRADE_FIELDS = ("txid", "ordertxid", "pair", "type", "price", "cost", "fee", "vol")
REQUIRED_LEDGER_FIELDS = ("txid", "refid")
REQUIRED_PENDING_FIELDS = (
    "broker", "account_scope", "order_id", "symbol", "side", "fill_price",
    "filled_usd", "exit_fee", "state",
)


def _csv_rows(path: Path, fields: tuple[str, ...]) -> tuple[list[dict[str, str]], str]:
    """Read a bounded CSV, rejecting duplicate/absent headers and unsafe paths."""
    if not path.is_file() or path.is_symlink() or path.stat().st_size > MAX_CSV_BYTES:
        raise ValueError("CSV missing, symlinked, or too large")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        header = [str(col or "").strip().lower() for col in (reader.fieldnames or [])]
        if len(header) != len(set(header)) or not set(fields).issubset(header):
            raise ValueError("CSV missing required or unique column headings")
        result: list[dict[str, str]] = []
        for row in reader:
            if None in row:
                raise ValueError("Malformed CSV: surplus fields")
            cleaned = {str(k).strip().lower(): str(v or "").strip() for k, v in row.items()}
            result.append(cleaned)
    return result, digest


def _dec(value: Any, *, positive: bool = False) -> Decimal:
    """Reject nonfinite, malformed and (where required) nonpositive amounts."""
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Invalid numeric evidence") from exc
    if not amount.is_finite() or (positive and amount <= 0) or (not positive and amount < 0):
        raise ValueError("Invalid numeric evidence")
    return amount


def _symbol(value: str) -> str:
    """Normalize the common Kraken BTC and ETH USD pair aliases only."""
    compact = "".join(c for c in str(value).upper().split(":", 1)[0] if c.isalnum())
    return {"XXBTZUSD": "BTCUSD", "XBTUSD": "BTCUSD",
            "XETHZUSD": "ETHUSD"}.get(compact, compact)


def _near(actual: Decimal, recorded: Any) -> bool:
    """Allow only serialization-level rounding, not substantive differences."""
    expected = _dec(recorded)
    return abs(actual - expected) <= max(Decimal("0.00000001"), abs(expected) * Decimal("0.00001"))


def _pending_rows(path: Path, scope: str) -> tuple[list[dict[str, Any]], str]:
    """Use SQLite read-only URI; never create a missing source database."""
    if not path.is_file() or path.is_symlink():
        raise ValueError("Ledger missing or symlinked")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA query_only=ON")
        if connection.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise ValueError("SQLite integrity check failed")
        columns = {item["name"] for item in connection.execute("PRAGMA table_info(pending_kraken_closes)")}
        if not set(REQUIRED_PENDING_FIELDS).issubset(columns):
            raise ValueError("Pending Kraken audit schema incomplete")
        rows = connection.execute(
            """SELECT broker, account_scope, order_id, symbol, side,
                      fill_price, filled_usd, exit_fee, state
               FROM pending_kraken_closes
               WHERE account_scope=? AND state='pending' AND broker='kraken'
               ORDER BY order_id""",
            (scope,),
        ).fetchall()
        return [dict(item) for item in rows], digest
    finally:
        connection.close()


def inspect(db: Path, trades: Path, ledgers: Path, scope: str) -> dict[str, Any]:
    """Compare exact exit order evidence without reconstructing entry cost or P&L."""
    if scope != "platform:kraken" and not (
        scope.startswith("user:") and scope.endswith(":kraken")
        and len(scope.split(":")) == 3 and bool(scope.split(":")[1])
    ):
        raise ValueError("Explicit full Kraken account scope required")
    pending, db_hash = _pending_rows(db, scope)
    trade_rows, trades_hash = _csv_rows(trades, REQUIRED_TRADE_FIELDS)
    ledger_rows, ledgers_hash = _csv_rows(ledgers, REQUIRED_LEDGER_FIELDS)
    ledger_txids = {row["txid"] for row in ledger_rows if row["txid"]}
    ledger_refs = {row["refid"] for row in ledger_rows if row["refid"]}

    by_order: dict[str, list[dict[str, str]]] = defaultdict(list)
    seen_trade_ids: set[str] = set()
    for row in trade_rows:
        txid = row["txid"]
        oid = row["ordertxid"]
        if not txid or not oid or txid in seen_trade_ids:
            raise ValueError("Trades CSV has missing or duplicate exchange identifiers")
        seen_trade_ids.add(txid)
        by_order[oid].append(row)

    results: list[dict[str, Any]] = []
    for item in pending:
        oid = str(item["order_id"])
        fills = by_order.get(oid, [])
        reasons: list[str] = []
        linkage = False
        if not fills:
            reasons.append("missing_exact_order_id")
        else:
            try:
                if any(
                    _symbol(row["pair"]) != _symbol(str(item["symbol"]))
                    or row["type"].lower() != str(item["side"]).lower()
                    for row in fills
                ):
                    reasons.append("symbol_or_side_conflict")
                qty = sum((_dec(row["vol"], positive=True) for row in fills), Decimal(0))
                cost = sum((_dec(row["cost"], positive=True) for row in fills), Decimal(0))
                fees = sum((_dec(row["fee"]) for row in fills), Decimal(0))
                # Validate individual execution prices too, not just the aggregate.
                for row in fills:
                    _dec(row["price"], positive=True)
                if not _near(cost / qty, item["fill_price"]):
                    reasons.append("weighted_exit_price_mismatch")
                if not _near(cost, item["filled_usd"]):
                    reasons.append("exit_notional_mismatch")
                if not _near(fees, item["exit_fee"]):
                    reasons.append("exit_fee_mismatch")
                # Kraken trade IDs can appear as ledger refid; some Trades
                # exports instead list the linked ledger txids explicitly.
                # A nonblank CSV field such as "," has ZERO real
                # references; all([]) would otherwise incorrectly pass.
                # Require at least one nonempty exchange ledger txid,
                # and every supplied identifier must be present.
                def has_ledger_evidence(row: dict[str, str]) -> bool:
                    if row["txid"] in ledger_refs:
                        return True
                    raw_links = str(row.get("ledgers") or "")
                    linked_ids = [ident.strip() for ident in raw_links.split(",")]
                    if not linked_ids or not all(linked_ids):
                        return False
                    return all(ident in ledger_txids for ident in linked_ids)

                linkage = all(has_ledger_evidence(row) for row in fills)
                if not linkage:
                    reasons.append("ledger_row_link_unproven")
            except (InvalidOperation, ValueError, ZeroDivisionError):
                reasons.append("invalid_or_incomplete_fill_amounts")
        results.append({
            "order_id": oid,
            "exit_csv_evidence_consistent": not reasons,
            "matching_trade_rows": len(fills),
            "ledger_row_link_supported": linkage,
            "unverified_reasons": sorted(set(reasons)),
            "authenticated_account_provenance": False,
            "entry_cost_basis_verified": False,
            "realized_pnl_usd": None,
            "strategy_attribution_verified": False,
        })
    return {
        "status": "operator_supplied_csv_evidence_only",
        "scope_asserted_by_operator_not_authenticated": scope,
        "source_sha256": {"sqlite": db_hash, "trades_csv": trades_hash, "ledgers_csv": ledgers_hash},
        "pending_closes_examined": len(results),
        "exit_csv_consistent": sum(1 for row in results if row["exit_csv_evidence_consistent"]),
        "results": results,
        "all_historical_fills_reconciled": False,
        "historical_realized_pnl_certified": False,
        "strategy_pnl_certified": False,
        "live_trading_eligible": False,
        "changes_to_database_or_broker": False,
        "next": "Verify each account/export independently with authenticated Kraken QueryOrders/TradesHistory; "
                "recover exact opening fills, quantities and fees before P&L booking.",
    }


def main() -> int:
    """Command-line operator entrypoint; prints evidence JSON only."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="verified isolated SQLite copy, never a production write target")
    parser.add_argument("--trades-csv", type=Path, required=True)
    parser.add_argument("--ledgers-csv", type=Path, required=True)
    parser.add_argument("--account-scope", required=True, help="e.g. platform:kraken")
    args = parser.parse_args()
    try:
        report = inspect(args.db, args.trades_csv, args.ledgers_csv, args.account_scope)
        print(json.dumps(report, sort_keys=True, indent=2))
        return 0
    except (ValueError, sqlite3.Error, OSError, UnicodeError) as exc:
        print(json.dumps({"status": "FAILED_CLOSED", "reason": type(exc).__name__,
                          "database_or_trading_mutated": False}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
