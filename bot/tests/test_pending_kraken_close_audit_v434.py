"""Offline NIJA unmatched Kraken close audits: no broker orders or synthetic P&L."""
from __future__ import annotations

import pytest

from bot.trade_ledger_db import TradeLedgerDB
from bot.pending_kraken_close_audit_v434 import (
    mark_reconciled,
    pending_summary,
    record_unmatched_confirmed_close,
)
from bot import runtime_realized_pnl_reconciliation_v412_patch as realized


def _ledger(tmp_path):
    return TradeLedgerDB(str(tmp_path / "trading_ledger.db"))


def _fill(account="platform:kraken"):
    return {"broker": "kraken", "account": account, "order_id": "EXIT-434", "fee": 0.11}


def _record(db, *, result=None, price=101000.0):
    return record_unmatched_confirmed_close(
        db, result=result or _fill(),
        symbol="XXBTZUSD", side="sell", price=price,
        filled_usd=101.0, fee=0.11, reason="missing_position",
    )


def test_confirmed_unmatched_fill_is_pending_and_never_booked(tmp_path, monkeypatch):
    ledger = _ledger(tmp_path)
    from bot import trade_ledger_db
    monkeypatch.setattr(trade_ledger_db, "_trade_ledger_db", ledger)
    realized._reconcile_confirmed_fill(
        _fill(), symbol="XXBTZUSD", side="sell",
        fill_price=101000.0, filled_usd=101.0,
    )
    assert ledger.get_trade_history(user_id="platform") == []
    assert ledger.get_ledger_transactions(user_id="platform") == []
    report = pending_summary(ledger, account_scope="platform:kraken")
    assert report["pending_confirmed_closes"] == 1
    assert report["reasons"] == {"missing_position": 1}
    assert report["realized_pnl_from_pending_usd"] is None


def test_exact_replay_is_idempotent_and_conflicting_fill_is_rejected(tmp_path):
    ledger = _ledger(tmp_path)
    assert _record(ledger)
    assert _record(ledger)
    assert _record(ledger, price=102000.0) is False
    with ledger._get_connection() as conn:
        rows = conn.execute("SELECT * FROM pending_kraken_closes").fetchall()
    assert len(rows) == 1
    assert rows[0]["seen_count"] == 2
    assert rows[0]["fill_price"] == 101000.0
    assert rows[0]["state"] == "pending"


def test_accounts_remain_isolated_even_if_order_id_matches(tmp_path):
    ledger = _ledger(tmp_path)
    assert _record(ledger)
    assert _record(ledger, result=_fill("user:customer:kraken"))
    assert pending_summary(ledger, account_scope="platform:kraken")["pending_confirmed_closes"] == 1
    assert pending_summary(ledger, account_scope="user:customer:kraken")["pending_confirmed_closes"] == 1


def test_opaque_account_or_unverified_broker_cannot_create_pending_pnl(tmp_path):
    ledger = _ledger(tmp_path)
    assert not _record(ledger, result=_fill("opaque-account"))
    assert not _record(ledger, result={**_fill(), "broker": "coinbase"})
    assert ledger.get_trade_history(user_id="platform") == []


def test_cannot_mark_pending_reconciled_without_confirmed_ledger_close(tmp_path):
    ledger = _ledger(tmp_path)
    assert _record(ledger)
    assert not mark_reconciled(
        ledger, result=_fill(), order_id="EXIT-434", position_id="P-434",
    )
    assert pending_summary(ledger, account_scope="platform:kraken")["pending_confirmed_closes"] == 1


def test_pending_closure_reconciles_only_after_authenticated_entry_and_confirmed_close(
    tmp_path, monkeypatch,
):
    ledger = _ledger(tmp_path)
    from bot import trade_ledger_db
    from bot import runtime_kraken_fee_pnl_bridge_v413_patch as bridge
    monkeypatch.setattr(trade_ledger_db, "_trade_ledger_db", ledger)

    realized._reconcile_confirmed_fill(
        _fill(), symbol="XXBTZUSD", side="sell",
        fill_price=101000.0, filled_usd=101.0,
    )
    assert pending_summary(ledger, account_scope="platform:kraken")["pending_confirmed_closes"] == 1

    bridge._ensure_opening_cost_basis(
        {"order_id": "ENTRY-434", "opening_position_id": "P-434",
         "account": "platform:kraken", "broker": "kraken", "fee": 0.12,
         "authenticated_kraken_queryorders": True,
         "authenticated_kraken_opening_order": True},
        symbol="XXBTZUSD", side="buy",
        fill_price=100000.0, filled_usd=100.0,
    )
    realized._reconcile_confirmed_fill(
        _fill(), symbol="XXBTZUSD", side="sell",
        fill_price=101000.0, filled_usd=101.0,
    )
    report = pending_summary(ledger, account_scope="platform:kraken")
    assert report["pending_confirmed_closes"] == 0
    assert len(ledger.get_trade_history(user_id="platform")) == 1
    assert abs(ledger.get_trade_history(user_id="platform")[0]["net_profit"] - 0.77) < 1e-7
    with ledger._get_connection() as conn:
        row = conn.execute("SELECT state, matched_position_id FROM pending_kraken_closes").fetchone()
    assert row["state"] == "reconciled" and row["matched_position_id"] == "P-434"


@pytest.mark.parametrize("mismatch", ["pending_symbol", "completed_symbol", "broker", "order_id"])
def test_pending_resolution_rejects_mismatched_identity(tmp_path, monkeypatch, mismatch):
    ledger = _ledger(tmp_path)
    from bot import trade_ledger_db
    from bot import runtime_kraken_fee_pnl_bridge_v413_patch as bridge
    monkeypatch.setattr(trade_ledger_db, "_trade_ledger_db", ledger)
    assert _record(ledger)
    bridge._ensure_opening_cost_basis(
        {"order_id": "ENTRY-434", "opening_position_id": "P-434",
         "account": "platform:kraken", "broker": "kraken", "fee": 0.12,
         "authenticated_kraken_queryorders": True,
         "authenticated_kraken_opening_order": True},
        symbol="XXBTZUSD", side="buy", fill_price=100000.0, filled_usd=100.0,
    )
    realized._reconcile_confirmed_fill(
        _fill(), symbol="XXBTZUSD", side="sell", fill_price=101000.0, filled_usd=101.0,
    )
    # Replay a pending audit against genuine canonical accounting, changing
    # one identity field while retaining all prices, quantities and fees.
    with ledger._get_connection() as conn:
        conn.execute("UPDATE pending_kraken_closes SET state='pending', matched_position_id=NULL")
        if mismatch == "pending_symbol":
            conn.execute("UPDATE pending_kraken_closes SET symbol='ETHUSD'")
        if mismatch == "completed_symbol":
            conn.execute("UPDATE completed_trades SET symbol='ETHUSD'")
    result = _fill()
    if mismatch == "broker":
        result["broker"] = "coinbase"
    if mismatch == "order_id":
        result["order_id"] = "OTHER-ORDER"
    assert not mark_reconciled(ledger, result=result, order_id="EXIT-434", position_id="P-434")
    assert pending_summary(ledger, account_scope="platform:kraken")["pending_confirmed_closes"] == 1


def test_pending_resolution_accepts_equivalent_kraken_symbol_alias(tmp_path, monkeypatch):
    test_pending_closure_reconciles_only_after_authenticated_entry_and_confirmed_close(tmp_path, monkeypatch)
    ledger = _ledger(tmp_path)
    with ledger._get_connection() as conn:
        conn.execute("UPDATE pending_kraken_closes SET state='pending', symbol='BTC-USD'")
    assert mark_reconciled(ledger, result=_fill(), order_id="EXIT-434", position_id="P-434")
