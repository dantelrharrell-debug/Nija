"""Synthetic, strictly read-only NIJA recovery inventory tests."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.nija_ledger_evidence_v438 import inspect_ledger


def _fixture(path: Path, *, pending: bool = True) -> None:
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE trade_ledger (id INTEGER PRIMARY KEY)")
        db.execute("CREATE TABLE open_positions (id INTEGER PRIMARY KEY)")
        db.execute("CREATE TABLE completed_trades (id INTEGER PRIMARY KEY)")
        db.execute("CREATE TABLE strategy_order_intents (id INTEGER PRIMARY KEY)")
        db.execute(
            "CREATE TABLE pending_kraken_closes "
            "(state TEXT NOT NULL, order_id TEXT NOT NULL)"
        )
        if pending:
            db.execute(
                "INSERT INTO pending_kraken_closes VALUES (?, ?)",
                ("pending", "synthetic-exit"),
            )


def test_empty_historical_ledger_with_pending_is_not_certified(tmp_path):
    source = tmp_path / "ledger.db"
    _fixture(source)
    original = source.read_bytes()
    result = inspect_ledger(source)
    assert result["sqlite_integrity"] == "ok"
    assert result["historical_entry_absent_with_pending_closes"] is True
    assert result["tables"]["trade_ledger"] == 0
    assert result["unmatched_kraken_closes"] == 1
    assert result["historical_realized_pnl_certified"] is False
    assert result["broker_authenticated_entry_history_verified"] is False
    assert original == source.read_bytes()


def test_no_pending_still_does_not_certify_historical_completeness(tmp_path):
    source = tmp_path / "ledger.db"
    _fixture(source, pending=False)
    report = inspect_ledger(source)
    assert report["historical_entry_absent_with_pending_closes"] is False
    assert report["all_historical_fills_reconciled"] is False
    assert report["strategy_attribution_certified"] is False


def test_missing_or_symlink_source_fails_closed(tmp_path):
    import pytest
    with pytest.raises(FileNotFoundError):
        inspect_ledger(tmp_path / "absent.db")
    actual = tmp_path / "actual.db"
    _fixture(actual)
    link = tmp_path / "link.db"
    link.symlink_to(actual)
    with pytest.raises(FileNotFoundError):
        inspect_ledger(link)


def test_nonledger_sqlite_fails_closed(tmp_path):
    import pytest
    source = tmp_path / "other.db"
    with sqlite3.connect(source) as conn:
        conn.execute("CREATE TABLE unrelated (id INT)")
    with pytest.raises(RuntimeError, match="missing required ledger tables"):
        inspect_ledger(source)
