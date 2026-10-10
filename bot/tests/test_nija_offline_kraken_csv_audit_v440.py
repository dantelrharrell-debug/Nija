"""Offline Kraken CSV triage regression: never authenticates exports or books P&L."""
import csv
import sqlite3

import pytest

from scripts.nija_offline_kraken_csv_audit_v440 import inspect


TRADE_HEADER = ["txid", "ordertxid", "pair", "type", "price", "cost", "fee", "vol"]
LEDGER_HEADER = ["txid", "refid"]


def _write_csv(path, header, rows):
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output)
        writer.writerow(header)
        writer.writerows(rows)


def _evidence(tmp_path, *, order="EXIT1", fee="0.20", ledg_ref="TRADE1"):
    db = tmp_path / "ledger.db"
    with sqlite3.connect(db) as conn:
        conn.execute("""CREATE TABLE pending_kraken_closes (
            broker TEXT, account_scope TEXT, order_id TEXT, symbol TEXT,
            side TEXT, fill_price REAL, filled_usd REAL, exit_fee REAL, state TEXT)""")
        conn.execute(
            "INSERT INTO pending_kraken_closes VALUES (?,?,?,?,?,?,?,?,?)",
            ("kraken", "platform:kraken", order, "BTC-USD", "sell",
             100.0, 100.0, 0.2, "pending"),
        )
    trades = tmp_path / "trades.csv"
    ledgers = tmp_path / "ledgers.csv"
    _write_csv(trades, TRADE_HEADER, [["TRADE1", "EXIT1", "XXBTZUSD", "sell", "100", "100", fee, "1"]])
    _write_csv(ledgers, LEDGER_HEADER, [["LEDGER1", ledg_ref]])
    return db, trades, ledgers


def test_consistent_exit_is_not_full_reconciliation(tmp_path):
    db, trades, ledgers = _evidence(tmp_path)
    original = db.read_bytes()
    result = inspect(db, trades, ledgers, "platform:kraken")
    assert result["pending_closes_examined"] == 1
    assert result["exit_csv_consistent"] == 1
    assert result["historical_realized_pnl_certified"] is False
    assert result["live_trading_eligible"] is False
    assert result["results"][0]["realized_pnl_usd"] is None
    assert result["results"][0]["entry_cost_basis_verified"] is False
    assert result["results"][0]["authenticated_account_provenance"] is False
    assert db.read_bytes() == original


def test_fee_mismatch_remains_unverified(tmp_path):
    db, trades, ledgers = _evidence(tmp_path, fee="1.5")
    result = inspect(db, trades, ledgers, "platform:kraken")
    assert result["exit_csv_consistent"] == 0
    assert "exit_fee_mismatch" in result["results"][0]["unverified_reasons"]


def test_unlinked_ledger_remains_unverified(tmp_path):
    db, trades, ledgers = _evidence(tmp_path, ledg_ref="DIFFERENT")
    result = inspect(db, trades, ledgers, "platform:kraken")
    assert result["exit_csv_consistent"] == 0
    assert "ledger_row_link_unproven" in result["results"][0]["unverified_reasons"]


def test_missing_order_remains_unverified(tmp_path):
    db, trades, ledgers = _evidence(tmp_path, order="ANOTHER_EXIT")
    result = inspect(db, trades, ledgers, "platform:kraken")
    assert result["exit_csv_consistent"] == 0
    assert "missing_exact_order_id" in result["results"][0]["unverified_reasons"]


def test_wrong_account_scope_rejected(tmp_path):
    db, trades, ledgers = _evidence(tmp_path)
    with pytest.raises(ValueError):
        inspect(db, trades, ledgers, "platform:coinbase")


def test_symlinked_sqlite_rejected(tmp_path):
    db, trades, ledgers = _evidence(tmp_path)
    link = tmp_path / "link.db"
    link.symlink_to(db)
    with pytest.raises(ValueError):
        inspect(link, trades, ledgers, "platform:kraken")


def test_duplicate_trade_ids_fail_closed(tmp_path):
    db, trades, ledgers = _evidence(tmp_path)
    _write_csv(trades, TRADE_HEADER, [
        ["TRADE1", "EXIT1", "XXBTZUSD", "sell", "100", "100", "0.2", "1"],
        ["TRADE1", "EXIT1", "XXBTZUSD", "sell", "100", "100", "0.2", "1"],
    ])
    with pytest.raises(ValueError, match="duplicate"):
        inspect(db, trades, ledgers, "platform:kraken")
