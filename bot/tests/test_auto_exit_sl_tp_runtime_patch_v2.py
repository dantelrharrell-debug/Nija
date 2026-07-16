from __future__ import annotations

from types import SimpleNamespace

import bot.auto_exit_sl_tp_runtime_patch as patch


def test_kraken_qty_alias_and_missing_side_are_treated_as_long(monkeypatch):
    monkeypatch.setenv("NIJA_MAX_POSITION_LOSS_USD", "2.00")
    monkeypatch.setenv("NIJA_HARD_STOP_LOSS_PCT", "0.015")
    pos = {
        "symbol": "SOL-USD",
        "qty": 0.51389914,
        "entry_price": 81.99,
        "cost_basis_verified": True,
    }
    assert patch._quantity(pos) == 0.51389914
    assert patch._side(pos.get("side"), pos) == "long"
    stop, source = patch._effective_stop(pos, 76.26)
    assert source == "synthesized_loss_cap"
    # Percentage stop is tighter than the $2 cap for this position.
    assert round(stop, 4) == round(81.99 * (1 - 0.015), 4)
    hit, reason, target = patch._trigger(pos, 76.26)
    assert hit is True
    assert reason == "stop_loss:synthesized_loss_cap"
    assert target == stop


def test_dollar_loss_cap_is_used_when_tighter(monkeypatch):
    monkeypatch.setenv("NIJA_MAX_POSITION_LOSS_USD", "2.00")
    monkeypatch.setenv("NIJA_HARD_STOP_LOSS_PCT", "0.05")
    pos = {"symbol": "SOL-USD", "qty": 1.0, "entry_price": 100.0, "side": "long"}
    stop, source = patch._effective_stop(pos, 97.0)
    assert source == "synthesized_loss_cap"
    assert stop == 98.0


def test_exit_order_accepts_qty_alias():
    calls = []

    class Broker:
        def place_market_order(self, **kwargs):
            calls.append(kwargs)
            return {"status": "filled", "order_id": "exit-1"}

    result = patch._exit_order(
        Broker(),
        {"symbol": "SOL-USD", "qty": 0.5, "entry_price": 80.0, "side": "long"},
        78.0,
    )
    assert result["status"] == "filled"
    assert calls == [{"symbol": "SOL-USD", "side": "sell", "size": 0.5}]


def test_profit_lock_exits_after_gain_reversal(monkeypatch):
    monkeypatch.setenv("NIJA_PROFIT_LOCK_ACTIVATION_PCT", "0.008")
    monkeypatch.setenv("NIJA_PROFIT_LOCK_CALLBACK_PCT", "0.0035")
    pos = {
        "position_id": "sol-1",
        "symbol": "SOL-USD",
        "qty": 1.0,
        "entry_price": 100.0,
        "side": "long",
        "stop_loss": 98.0,
    }
    patch._HIGH_WATER.clear()
    assert patch._trigger(pos, 101.0)[0] is False
    hit, reason, _ = patch._trigger(pos, 100.60)
    assert hit is True
    assert reason == "profit_lock_trailing_exit"


def test_process_registry_scans_every_engine(monkeypatch):
    patch._ENGINES.clear()
    monkeypatch.setattr(patch, "_PROCESS_STARTED", True)

    class Engine:
        pass

    first = Engine()
    second = Engine()
    patch._register_engine(first)
    patch._register_engine(second)
    snapshot = patch._engine_snapshot()
    assert first in snapshot
    assert second in snapshot


def test_scan_once_closes_sol_with_verified_entry_and_no_stored_stop(monkeypatch):
    monkeypatch.setenv("NIJA_MAX_POSITION_LOSS_USD", "2.00")
    monkeypatch.setenv("NIJA_HARD_STOP_LOSS_PCT", "0.015")

    class Ledger:
        def get_open_positions(self):
            return [{
                "position_id": "sol-platform",
                "symbol": "SOL-USD",
                "qty": 0.51389914,
                "entry_price": 81.99,
                "cost_basis_verified": True,
            }]

        def close_position_with_pnl(self, **kwargs):
            return {"success": True, "net_profit": -2.89, "profit_pct": -7.0}

    class Broker:
        broker_type = "kraken"

        def get_quote(self, symbol):
            return {"price": 76.26}

        def place_market_order(self, **kwargs):
            return {"status": "filled", "order_id": "sol-exit", "filled_price": 76.26}

    engine = SimpleNamespace(
        trade_ledger=Ledger(),
        broker_client=Broker(),
        active_exit_orders=set(),
    )
    assert patch._scan_once(engine) == 1
