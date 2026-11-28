#!/usr/bin/env python3
"""Read-only NIJA ledger recovery inventory. Never certifies missing history.

Designed for operator use on the *currently running* Render instance, with
source paths supplied explicitly. No brokerage requests, mutations, recovery
replays, execution flags, or trading orders are performed.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

TABLE_COUNT_QUERIES = {
    "trade_ledger": "SELECT COUNT(*) FROM trade_ledger",
    "open_positions": "SELECT COUNT(*) FROM open_positions",
    "completed_trades": "SELECT COUNT(*) FROM completed_trades",
    "strategy_order_intents": "SELECT COUNT(*) FROM strategy_order_intents",
    "pending_kraken_closes": "SELECT COUNT(*) FROM pending_kraken_closes",
}
REQUIRED_TABLES = ("trade_ledger", "open_positions", "completed_trades")


def _table_counts(conn: sqlite3.Connection) -> dict[str, int | None]:
    existing = {
        row[0] for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    return {
        table: int(conn.execute(query).fetchone()[0]) if table in existing else None
        for table, query in TABLE_COUNT_QUERIES.items()
    }


def inspect_ledger(db: Path) -> dict[str, Any]:
    """Inventory only, preserving SQLite WAL read semantics and source bytes."""
    if not db.is_file() or db.is_symlink():
        raise FileNotFoundError("SQLite ledger missing, unreadable or symlink")
    # mode=ro does not create an empty database if the path is wrong. Unlike
    # immutable=1, it can read transactionally committed WAL records.
    uri = db.resolve().as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=15)
    try:
        conn.execute("PRAGMA query_only=ON")
        # Keep schema, totals and pending states on the same SQLite snapshot.
        conn.execute("BEGIN")
        integrity = conn.execute("PRAGMA integrity_check").fetchall()
        counts = _table_counts(conn)
        if integrity != [("ok",)]:
            raise RuntimeError("SQLite integrity_check failed")
        absent = [t for t in REQUIRED_TABLES if counts[t] is None]
        if absent:
            raise RuntimeError("missing required ledger tables: " + ",".join(absent))
        unmatched = 0
        if counts.get("pending_kraken_closes") is not None:
            unmatched = int(conn.execute(
                "SELECT COUNT(*) FROM pending_kraken_closes WHERE state='pending'"
            ).fetchone()[0])
        return {
            "status": "read_only_structural_inventory",
            "database": str(db),
            "sqlite_integrity": "ok",
            "tables": counts,
            "unmatched_kraken_closes": unmatched,
            "historical_entry_absent_with_pending_closes": bool(
                unmatched and counts["trade_ledger"] == 0
            ),
            "broker_authenticated_entry_history_verified": False,
            "all_historical_fills_reconciled": False,
            "historical_realized_pnl_certified": False,
            "strategy_attribution_certified": False,
            "automatic_record_changes": False,
            "trading_controls_changed": False,
        }
    finally:
        conn.close()


def compare_archive(archive: Path, live_counts: dict[str, int | None]) -> dict[str, Any]:
    """Verify the supplied archive independently; never claim off-host proof."""
    # Same-directory import also works when the operator invokes this script
    # directly as python scripts/nija_ledger_evidence_v438.py.
    from nija_trade_ledger_snapshot_v436 import verify_snapshot
    import hashlib

    manifest = verify_snapshot(archive)
    with archive.open("rb") as stream:
        h = hashlib.sha256()
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    saved = manifest.get("sqlite_tables") or {}
    differences = {
        table: {
            "current_count": live_counts.get(table),
            "archive_count": saved.get(table),
        }
        for table in TABLE_COUNT_QUERIES
        if live_counts.get(table) != saved.get(table)
    }
    return {
        "archive_path": str(archive),
        "archive_sha256": h.hexdigest(),
        "archive_sqlite_and_member_hashes_verified": True,
        "archive_table_counts": {
            name: saved.get(name) for name in TABLE_COUNT_QUERIES
        },
        "count_differences_from_live": differences,
        "off_host_copy_independently_verified": False,
        "restore_on_production_performed": False,
        "historical_completeness_inferred": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", required=True, help="existing SQLite ledger path")
    parser.add_argument(
        "--archive", default="", help="optional independently obtained v436 archive"
    )
    opts = parser.parse_args()
    try:
        report = inspect_ledger(Path(opts.ledger))
        if opts.archive:
            report["comparison"] = compare_archive(
                Path(opts.archive), report["tables"]
            )
        print(json.dumps(report, indent=2, sort_keys=True))
        return 0
    except Exception as exc:
        print(json.dumps({
            "status": "FAILED_CLOSED",
            "error_type": type(exc).__name__,
            "note": "No accounting or trading state was modified.",
        }))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
