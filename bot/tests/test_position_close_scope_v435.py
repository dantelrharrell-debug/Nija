"""Offline canonical close consistency; no network, brokers, or live orders."""
from __future__ import annotations

import pytest

from bot.trade_ledger_db import TradeLedgerDB
from bot import position_close_pnl_runtime_patch as pnl_patch


@pytest.fixture
def ledger(tmp_path):
    pnl_patch.install_import_hook()
    return TradeLedgerDB(str(tmp_path / "trading_ledger.sqlite"))


def _open(db, *, position, owner="platform", symbol="XXBTZUSD"):
    assert db.open_position(
        position_id=position, user_id=owner, symbol=symbol, side="LONG",
        entry_price=100000.0, quantity=0.001, size_usd=100.0,
        entry_fee=0.20, notes="test-only",
    )


def _close(db, *, position, owner="platform", symbol="XXBTZUSD", order="EXIT-V435", fee=0.30):
    return db.close_position_with_pnl(
        position_id=position, user_id=owner, symbol=symbol,
        exit_price=101000.0, exit_fee=fee,
        exit_reason="canonical_confirmed_fill", broker="kraken",
        order_id=order,
    )


def test_atomic_scoped_close_binds_exact_owner_symbol_and_order(ledger):
    _open(ledger, position="POS-1")
    result = _close(ledger, position="POS-1")
    assert result["success"] is True
    assert result["net_profit"] == pytest.approx(0.50)
    assert ledger.get_open_positions(user_id="platform") == []
    assert len(ledger.get_trade_history(user_id="platform")) == 1
    assert len([x for x in ledger.get_ledger_transactions(user_id="platform")
                if x["action"] == "CLOSE"]) == 1


def test_position_id_cannot_cross_user_scope(ledger):
    _open(ledger, position="P-OTHER", owner="customer-b")
    result = _close(ledger, position="P-OTHER", owner="platform")
    assert result["success"] is False
    assert result["error"] == "position_owner_mismatch"
    assert len(ledger.get_open_positions(user_id="customer-b")) == 1
    assert ledger.get_trade_history(user_id="customer-b") == []


def test_position_id_cannot_cross_symbol_scope(ledger):
    _open(ledger, position="P-SYMBOL", symbol="ETH-USD")
    result = _close(ledger, position="P-SYMBOL", symbol="XXBTZUSD")
    assert result["success"] is False
    assert result["error"] == "position_symbol_mismatch"
    assert len(ledger.get_open_positions(user_id="platform")) == 1


@pytest.mark.parametrize("fee", [-1.0, float("inf"), float("nan")])
def test_invalid_exit_fee_never_reaches_pnl(ledger, fee):
    _open(ledger, position="P-FEE")
    result = _close(ledger, position="P-FEE", fee=fee)
    assert result["success"] is False
    assert result["error"] == "invalid_exit_economics"
    assert len(ledger.get_open_positions(user_id="platform")) == 1
    assert ledger.get_trade_history(user_id="platform") == []


def test_same_account_order_id_cannot_close_two_positions(ledger):
    _open(ledger, position="P-ONE")
    _open(ledger, position="P-TWO")
    assert _close(ledger, position="P-ONE")["success"]
    second = _close(ledger, position="P-TWO")
    assert second["success"] is False
    assert second["error"] == "confirmed_order_already_booked"
    assert len(ledger.get_open_positions(user_id="platform")) == 1
    assert len(ledger.get_trade_history(user_id="platform")) == 1


def test_reopened_position_id_cannot_replace_historical_completed_trade(ledger):
    _open(ledger, position="P-HIST")
    assert _close(ledger, position="P-HIST", order="ORIGINAL")["success"]
    initial = ledger.get_trade_history(user_id="platform")[0]
    _open(ledger, position="P-HIST")
    replay = _close(ledger, position="P-HIST", order="REPLAY")
    assert replay["success"] is False
    assert len(ledger.get_open_positions(user_id="platform")) == 1
    assert ledger.get_trade_history(user_id="platform")[0]["net_profit"] == initial["net_profit"]
    assert len(ledger.get_trade_history(user_id="platform")) == 1
