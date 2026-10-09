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


def test_platform_account_identity_matches_platform_ledger_user(tmp_path, monkeypatch):
    db = _fresh_ledger(tmp_path, monkeypatch)
    importlib.import_module("bot.position_close_pnl_runtime_patch").install_import_hook()
    realized = importlib.import_module("bot.runtime_realized_pnl_reconciliation_v412_patch")

    assert realized._candidate_user({"account": "platform:kraken"}) == "platform"
    assert realized._candidate_user({"account": "platform"}) == "platform"
    assert realized._candidate_user({"account": "user:daivon_frazier:kraken"}) == "daivon_frazier"
    assert realized._candidate_user({"account_id": "opaque-kraken-account"}) == "__unresolved_account_identity__"

    assert db.open_position(
        position_id="PLATFORM-1", symbol="XXBTZUSD", side="LONG",
        entry_price=100000.0, quantity=0.001, size_usd=100.0,
        entry_fee=0.25, user_id="platform",
    )
    realized._reconcile_confirmed_fill(
        {"order_id": "PLATFORM-EXIT-1", "account": "platform:kraken",
         "broker": "kraken", "fee": 0.30},
        symbol="XXBTZUSD", side="sell", fill_price=101000.0,
        filled_usd=101.0,
    )
    assert db.get_open_positions(user_id="platform") == []
    trades = db.get_trade_history(user_id="platform")
    assert len(trades) == 1
    assert trades[0]["net_profit"] == pytest.approx(0.45)


def test_unrecognized_account_does_not_book_other_users_pnl(tmp_path, monkeypatch):
    db = _fresh_ledger(tmp_path, monkeypatch)
    importlib.import_module("bot.position_close_pnl_runtime_patch").install_import_hook()
    realized = importlib.import_module("bot.runtime_realized_pnl_reconciliation_v412_patch")
    assert db.open_position(
        position_id="USER-1", symbol="XXBTZUSD", side="LONG",
        entry_price=100000.0, quantity=0.001, size_usd=100.0,
        entry_fee=0.25, user_id="customer-a",
    )
    realized._reconcile_confirmed_fill(
        {"order_id": "OPAQUE-EXIT-1", "account": "opaque-kraken-account",
         "broker": "kraken", "fee": 0.30},
        symbol="XXBTZUSD", side="sell", fill_price=101000.0,
        filled_usd=101.0,
    )
    assert len(db.get_open_positions(user_id="customer-a")) == 1
    assert db.get_trade_history(user_id="customer-a") == []


def test_accountless_exit_cannot_close_any_accounts_ledger(tmp_path, monkeypatch):
    db = _fresh_ledger(tmp_path, monkeypatch)
    realized = importlib.import_module("bot.runtime_realized_pnl_reconciliation_v412_patch")
    assert realized._candidate_user({"broker": "kraken"}) == "__unresolved_account_identity__"
    assert db.open_position(
        position_id="REAL-1", symbol="XXBTZUSD", side="LONG",
        entry_price=100000.0, quantity=0.001, size_usd=100.0,
        entry_fee=0.25, user_id="platform",
    )
    realized._reconcile_confirmed_fill(
        {"order_id": "ACCOUNTLESS-EXIT-1", "broker": "kraken", "fee": 0.30},
        symbol="XXBTZUSD", side="sell", fill_price=101000.0, filled_usd=101.0,
    )
    assert len(db.get_open_positions(user_id="platform")) == 1
    assert db.get_trade_history(user_id="platform") == []


def test_authenticated_kraken_fee_cache_retains_platform_owner(monkeypatch):
    bridge = importlib.import_module("bot.runtime_kraken_fee_pnl_bridge_v413_patch")
    monkeypatch.setitem(bridge._FEE_CACHE, "REAL-FEE-1", (0.21, "platform:kraken"))
    fee, reason = bridge._query_exact_fee("REAL-FEE-1", "XXBTZUSD", "sell")
    assert reason == "cache"
    assert fee == {
        "fee": 0.21, "broker": "kraken",
        "fee_source": "authenticated_kraken_queryorders",
        "account": "platform:kraken",
    }


def test_authenticated_opening_without_scoped_account_cannot_be_misattributed(tmp_path, monkeypatch):
    db = _fresh_ledger(tmp_path, monkeypatch)
    bridge = importlib.import_module("bot.runtime_kraken_fee_pnl_bridge_v413_patch")
    proof = {
        "order_id": "ACCOUNTLESS-ENTRY-1",
        "execution_role": "entry", "authenticated_kraken_opening_order": True,
        "authenticated_kraken_queryorders": True,
        "opening_position_id": "ACCOUNTLESS-POS-1", "fee": 0.30,
    }
    bridge._ensure_opening_cost_basis(
        proof, symbol="XXBTZUSD", side="buy",
        fill_price=100000.0, filled_usd=100.0,
    )
    assert db.get_open_positions(user_id="platform") == []
    assert db.get_ledger_transactions(user_id="platform") == []


def test_queryorders_fee_provenance_rejects_conflicting_user_attribution(monkeypatch):
    bridge = importlib.import_module("bot.runtime_kraken_fee_pnl_bridge_v413_patch")
    assert bridge._account_owner({"account": "platform:kraken"}) == "platform"
    assert bridge._account_owner({"account": "user:customer-1:kraken"}) == "customer-1"
    assert bridge._account_owner({"account": "opaque-account"}) == ""
    assert bridge._ledger_user_id({"account": "user:customer-1:kraken"}) == "customer-1"


def test_authenticated_short_entry_is_open_not_a_close(tmp_path, monkeypatch):
    db = _fresh_ledger(tmp_path, monkeypatch)
    bridge = importlib.import_module("bot.runtime_kraken_fee_pnl_bridge_v413_patch")
    bridge._ensure_opening_cost_basis(
        {"order_id": "SHORT-ENTRY-1", "opening_position_id": "SHORT-POS-1",
         "account": "platform:kraken", "fee": 0.16, "broker": "kraken",
         "authenticated_kraken_queryorders": True,
         "authenticated_kraken_opening_order": True},
        symbol="XXBTZUSD", side="sell", fill_price=100000.0, filled_usd=100.0,
    )
    positions = db.get_open_positions(user_id="platform")
    assert len(positions) == 1 and positions[0]["side"] == "SHORT"
    txs = db.get_ledger_transactions(user_id="platform")
    assert len(txs) == 1
    assert txs[0]["action"] == "OPEN"
    assert txs[0]["side"] == "SELL"
    assert db.get_trade_history(user_id="platform") == []


def test_recover_matching_orphan_open_transaction_without_second_ledger_entry(tmp_path, monkeypatch):
    db = _fresh_ledger(tmp_path, monkeypatch)
    notes = "authenticated_kraken_queryorders_entry; order_id=OLD-ENTRY-1; account=platform:kraken"
    db.record_buy(
        symbol="XXBTZUSD", price=100000.0, quantity=0.001,
        size_usd=100.0, fee=0.26, order_id="OLD-ENTRY-1",
        position_id="OLD-POS-1", user_id="platform", notes=notes,
    )
    assert db.record_confirmed_entry_atomic(
        position_id="OLD-POS-1", order_id="OLD-ENTRY-1", user_id="platform",
        symbol="XXBTZUSD", side="LONG", entry_price=100000.0,
        quantity=0.001, size_usd=100.0, entry_fee=0.26, notes=notes,
    ) is True
    assert len(db.get_ledger_transactions(user_id="platform")) == 1
    assert len(db.get_open_positions(user_id="platform")) == 1


def test_conflicting_orphan_fill_is_not_assigned_an_open_position(tmp_path, monkeypatch):
    db = _fresh_ledger(tmp_path, monkeypatch)
    db.record_buy(
        symbol="XXBTZUSD", price=100000.0, quantity=0.001,
        size_usd=100.0, fee=0.26, order_id="OLD-ENTRY-2",
        position_id="OLD-POS-2", user_id="platform", notes="wrong-identity",
    )
    with pytest.raises(ValueError, match="opening transaction identity"):
        db.record_confirmed_entry_atomic(
            position_id="OLD-POS-2", order_id="OLD-ENTRY-2", user_id="platform",
            symbol="XXBTZUSD", side="LONG", entry_price=100000.0,
            quantity=0.001, size_usd=100.0, entry_fee=0.26,
            notes="authenticated_kraken_queryorders_entry; order_id=OLD-ENTRY-2; account=platform:kraken",
        )
    assert len(db.get_ledger_transactions(user_id="platform")) == 1
    assert db.get_open_positions(user_id="platform") == []


def test_legacy_close_row_prevents_resurrection_of_an_entry(tmp_path, monkeypatch):
    db = _fresh_ledger(tmp_path, monkeypatch)
    db.record_sell(
        symbol="XXBTZUSD", price=100100.0, quantity=0.001,
        size_usd=100.1, fee=0.26, order_id="CLOSE-1",
        position_id="PAST-POS-1", user_id="platform", notes="confirmed close",
    )
    with pytest.raises(ValueError, match="known close"):
        db.record_confirmed_entry_atomic(
            position_id="PAST-POS-1", order_id="PAST-ENTRY-1", user_id="platform",
            symbol="XXBTZUSD", side="LONG", entry_price=100000.0,
            quantity=0.001, size_usd=100.0, entry_fee=0.26,
            notes="authenticated_kraken_queryorders_entry; order_id=PAST-ENTRY-1; account=platform:kraken",
        )
    assert db.get_open_positions(user_id="platform") == []


def test_configured_external_ledger_path_survives_new_instance(tmp_path, monkeypatch):
    from bot.trade_ledger_db import TradeLedgerDB
    path = tmp_path / "mounted" / "trade_ledger.db"
    monkeypatch.setenv("NIJA_TRADE_LEDGER_DB_PATH", str(path))
    first = TradeLedgerDB()
    assert first.db_path == path
    notes = "authenticated_kraken_queryorders_entry; order_id=DURABLE-ENTRY-1; account=platform:kraken"
    assert first.record_confirmed_entry_atomic(
        position_id="DURABLE-POS-1", order_id="DURABLE-ENTRY-1",
        user_id="platform", symbol="XXBTZUSD", side="LONG",
        entry_price=100000.0, quantity=0.001, size_usd=100.0,
        entry_fee=0.15, notes=notes,
    ) is True
    second = TradeLedgerDB()
    assert len(second.get_open_positions(user_id="platform")) == 1
    assert len(second.get_ledger_transactions(user_id="platform")) == 1
