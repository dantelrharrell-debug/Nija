"""Offline strategy attribution: pipeline intent is not itself a fill."""
from __future__ import annotations

from types import SimpleNamespace

from bot.trade_ledger_db import TradeLedgerDB
from bot.strategy_order_provenance import record_pipeline_order_intent
from bot.confirmed_performance_report import get_confirmed_performance_report


def _intent(*, strategy="trend_breakout", scope="platform:kraken", symbol="BTC-USD"):
    return SimpleNamespace(
        account_id=scope, preferred_broker="kraken",
        strategy=strategy, strategy_metadata={"version": "v7"},
        symbol=symbol, side="buy", intent_id="signal-001",
        intent_type="entry", metadata={},
    )


def _ack():
    return SimpleNamespace(
        broker="kraken", success=True, order_id="OPEN-STRAT-1",
    )


def _confirmed_trade(ledger, monkeypatch):
    from bot import trade_ledger_db
    from bot import runtime_kraken_fee_pnl_bridge_v413_patch as entries
    from bot import runtime_realized_pnl_reconciliation_v412_patch as exits
    monkeypatch.setattr(trade_ledger_db, "_trade_ledger_db", ledger)
    entries._ensure_opening_cost_basis(
        {"order_id": "OPEN-STRAT-1", "opening_position_id": "POS-STRAT-1",
         "account": "platform:kraken", "broker": "kraken", "fee": 0.12,
         "authenticated_kraken_queryorders": True,
         "authenticated_kraken_opening_order": True},
        symbol="XXBTZUSD", side="buy", fill_price=100000.0, filled_usd=100.0,
    )
    exits._reconcile_confirmed_fill(
        {"order_id": "CLOSE-STRAT-1", "account": "platform:kraken",
         "broker": "kraken", "fee": 0.13},
        symbol="XXBTZUSD", side="sell", fill_price=101000.0, filled_usd=101.0,
    )


def test_strategy_proven_only_after_verified_open_and_close(tmp_path, monkeypatch):
    db = TradeLedgerDB(str(tmp_path / "ledger.db"))
    assert record_pipeline_order_intent(_intent(), _ack(), ledger=db)
    before = get_confirmed_performance_report(db, broker="kraken", user_id="platform")
    assert before["strategy_attribution"] == "unavailable"
    assert before["overall"]["trades"] == 0

    _confirmed_trade(db, monkeypatch)
    report = get_confirmed_performance_report(db, broker="kraken", user_id="platform")
    assert report["overall"]["trades"] == 1
    assert report["strategy_attribution"] == "verified_subset"
    assert report["strategy_attribution_proven_closes"] == 1
    assert report["strategy_attribution_unproven_closes"] == 0
    assert len(report["strategy_metrics"]) == 1
    first = report["strategy_metrics"][0]
    assert first["strategy_id"] == "trend_breakout"
    assert first["strategy_version"] == "v7"
    assert first["wins"] == 1
    assert round(first["net_pnl_usd"], 2) == 0.75


def test_strategy_claim_cannot_be_reassigned_to_different_strategy(tmp_path):
    db = TradeLedgerDB(str(tmp_path / "ledger.db"))
    assert record_pipeline_order_intent(_intent(), _ack(), ledger=db)
    assert record_pipeline_order_intent(_intent(strategy="other"), _ack(), ledger=db) is False
    with db._get_connection() as conn:
        rows = conn.execute("SELECT strategy_id FROM strategy_order_intents").fetchall()
    assert [row["strategy_id"] for row in rows] == ["trend_breakout"]


def test_confirmed_trade_without_linked_strategy_is_unattributed(tmp_path, monkeypatch):
    db = TradeLedgerDB(str(tmp_path / "ledger.db"))
    _confirmed_trade(db, monkeypatch)
    report = get_confirmed_performance_report(db, broker="kraken", user_id="platform")
    assert report["overall"]["trades"] == 1
    assert report["strategy_attribution"] == "unavailable"
    assert report["strategy_attribution_proven_closes"] == 0
    assert report["strategy_attribution_unproven_closes"] == 1


def test_cross_account_intent_cannot_claim_platform_trade(tmp_path, monkeypatch):
    db = TradeLedgerDB(str(tmp_path / "ledger.db"))
    assert record_pipeline_order_intent(
        _intent(scope="user:customer-1:kraken"), _ack(), ledger=db,
    )
    _confirmed_trade(db, monkeypatch)
    report = get_confirmed_performance_report(db, broker="kraken", user_id="platform")
    assert report["strategy_attribution"] == "unavailable"
    assert report["strategy_attribution_unproven_closes"] == 1


def test_ack_without_scoped_owner_never_records_strategy(tmp_path):
    db = TradeLedgerDB(str(tmp_path / "ledger.db"))
    assert record_pipeline_order_intent(_intent(scope="unknown"), _ack(), ledger=db) is False
    with db._get_connection() as conn:
        rows = conn.execute("SELECT * FROM strategy_order_intents").fetchall()
    assert rows == []
