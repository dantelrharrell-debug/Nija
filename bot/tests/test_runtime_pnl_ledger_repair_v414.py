from __future__ import annotations

import importlib

import pytest


def _fresh_ledger(tmp_path, monkeypatch):
    ledger_module = importlib.import_module("bot.trade_ledger_db")
    db = ledger_module.TradeLedgerDB(str(tmp_path / "trade_ledger.db"))
    monkeypatch.setattr(ledger_module, "_trade_ledger_db", db)
    return db


def test_authenticated_opening_fill_creates_idempotent_cost_basis(tmp_path, monkeypatch):
    db = _fresh_ledger(tmp_path, monkeypatch)
    bridge = importlib.import_module("bot.runtime_kraken_fee_pnl_bridge_v413_patch")

    proof = {
        "order_id": "ENTRY-1",
        "status": "closed",
        "execution_role": "entry",
        "authenticated_kraken_opening_order": True,
        "authenticated_kraken_queryorders": True,
        "opening_position_id": "POS-1",
        "account": "platform:kraken",
        "fee": 0.75,
        "broker": "kraken",
    }

    bridge._ensure_opening_cost_basis(
        proof,
        symbol="ETHUSD:BTNL",
        side="buy",
        fill_price=2500.0,
        filled_usd=250.0,
    )
    bridge._ensure_opening_cost_basis(
        proof,
        symbol="ETHUSD:BTNL",
        side="buy",
        fill_price=2500.0,
        filled_usd=250.0,
    )

    positions = db.get_open_positions(user_id="platform")
    assert len(positions) == 1
    row = positions[0]
    assert row["position_id"] == "POS-1"
    assert row["symbol"] == "ETHUSD:BTNL"
    assert row["side"] == "LONG"
    assert row["entry_price"] == pytest.approx(2500.0)
    assert row["quantity"] == pytest.approx(0.1)
    assert row["size_usd"] == pytest.approx(250.0)
    assert row["entry_fee"] == pytest.approx(0.75)

    txs = db.get_ledger_transactions(user_id="platform")
    assert len(txs) == 1
    assert txs[0]["order_id"] == "ENTRY-1"
    assert txs[0]["action"] == "OPEN"


def test_confirmed_exit_books_realized_pnl_from_authenticated_cost_basis(tmp_path, monkeypatch):
    db = _fresh_ledger(tmp_path, monkeypatch)
    bridge = importlib.import_module("bot.runtime_kraken_fee_pnl_bridge_v413_patch")
    realized = importlib.import_module("bot.runtime_realized_pnl_reconciliation_v412_patch")

    entry = {
        "order_id": "ENTRY-2",
        "execution_role": "entry",
        "authenticated_kraken_opening_order": True,
        "authenticated_kraken_queryorders": True,
        "opening_position_id": "POS-2",
        "account": "platform:kraken",
        "fee": 0.50,
        "broker": "kraken",
    }
    bridge._ensure_opening_cost_basis(
        entry,
        symbol="XXBTZUSD",
        side="buy",
        fill_price=100000.0,
        filled_usd=200.0,
    )

    qty = 200.0 / 100000.0
    exit_price = 101000.0
    exit_result = {
        "order_id": "EXIT-2",
        "account": "platform:kraken",
        "fee": 0.60,
        "broker": "kraken",
    }
    realized._reconcile_confirmed_fill(
        exit_result,
        symbol="XXBTZUSD",
        side="sell",
        fill_price=exit_price,
        filled_usd=qty * exit_price,
    )

    assert db.get_open_positions(user_id="platform") == []
    history = db.get_trade_history(user_id="platform")
    assert len(history) == 1
    trade = history[0]
    assert trade["position_id"] == "POS-2"
    assert trade["exit_price"] == pytest.approx(exit_price)
    assert trade["gross_profit"] == pytest.approx(2.0)
    assert trade["total_fees"] == pytest.approx(1.10)
    assert trade["net_profit"] == pytest.approx(0.90)
