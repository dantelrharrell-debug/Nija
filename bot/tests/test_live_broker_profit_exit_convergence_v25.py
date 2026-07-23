from __future__ import annotations

import importlib
import os
from types import SimpleNamespace

import pytest


@pytest.fixture()
def module(monkeypatch):
    monkeypatch.setenv("NIJA_DEFER_RUNTIME_SITE_HOOKS", "1")
    monkeypatch.setenv("NIJA_LIVE_BROKER_PROFIT_EXIT_V25_ENABLED", "false")
    mod = importlib.import_module("bot.live_broker_profit_exit_convergence_v25")
    mod._PENDING.clear()
    mod.supervisor._ACTIVE.clear()
    return mod


def test_short_fee_aware_target_is_below_entry(module, monkeypatch):
    monkeypatch.setenv("NIJA_OKX_ROUND_TRIP_FEE_PCT", "0.004")
    monkeypatch.setenv("NIJA_EXIT_SLIPPAGE_RESERVE_PCT", "0.001")
    monkeypatch.setenv("NIJA_MINIMUM_NET_PROFIT_PCT", "0.005")
    broker = SimpleNamespace(broker_type=SimpleNamespace(value="okx"))
    pos = {"symbol": "BTC-USDT", "side": "short", "entry_price": 100.0, "quantity": 1.0}

    target = module._fee_aware_profit_target(broker, pos)

    assert target == pytest.approx(99.0)
    assert target < pos["entry_price"]


def test_profit_trigger_waits_until_fee_and_net_floor(module, monkeypatch):
    monkeypatch.setenv("NIJA_KRAKEN_ROUND_TRIP_FEE_PCT", "0.008")
    monkeypatch.setenv("NIJA_EXIT_SLIPPAGE_RESERVE_PCT", "0.0015")
    monkeypatch.setenv("NIJA_MINIMUM_NET_PROFIT_PCT", "0.004")
    broker = SimpleNamespace(broker_type=SimpleNamespace(value="kraken"))
    pos = {
        "symbol": "ETH-USD",
        "side": "long",
        "entry_price": 100.0,
        "quantity": 1.0,
        "take_profit_1": 100.5,
    }
    monkeypatch.setattr(module, "_ORIGINAL_TRIGGER", lambda b, p, m: (True, "take_profit_1", 100.5))

    assert module._trigger(broker, pos, 100.6) == (False, "", 0.0)
    hit, reason, target = module._trigger(broker, pos, 101.4)
    assert hit is True
    assert reason == "take_profit_1"
    assert target == pytest.approx(101.35)


class _Tracker:
    def __init__(self):
        self.positions = [{
            "position_id": "p1",
            "symbol": "BTC-USD",
            "side": "long",
            "entry_price": 100.0,
            "quantity": 1.0,
            "take_profit_1": 101.0,
        }]
        self.closed = []

    def get_open_positions(self):
        return list(self.positions)

    def close_position_with_pnl(self, **kwargs):
        self.closed.append(kwargs)
        self.positions = []
        return {"success": True}


class _AcceptedThenFilledBroker:
    connected = True
    account_id = "platform"
    broker_type = SimpleNamespace(value="coinbase")

    def __init__(self):
        self.position_tracker = _Tracker()
        self.status_calls = 0

    def get_quote(self, symbol):
        return {"price": 103.0}

    def place_market_order(self, **kwargs):
        return {"status": "accepted", "order_id": "o1"}

    def get_order_status(self, **kwargs):
        self.status_calls += 1
        if self.status_calls == 1:
            return {"status": "open", "order_id": "o1"}
        return {"status": "filled", "order_id": "o1", "filled_size": 1.0, "filled_price": 103.0}


def test_accepted_exit_is_not_marked_closed_until_fill(module, monkeypatch):
    monkeypatch.setenv("NIJA_COINBASE_ROUND_TRIP_FEE_PCT", "0.001")
    monkeypatch.setenv("NIJA_EXIT_SLIPPAGE_RESERVE_PCT", "0")
    monkeypatch.setenv("NIJA_MINIMUM_NET_PROFIT_PCT", "0")
    monkeypatch.setenv("NIJA_EXIT_FILL_CONFIRM_TIMEOUT_S", "30")
    broker = _AcceptedThenFilledBroker()

    first = module._scan_broker(broker)
    assert first == 0
    assert broker.position_tracker.closed == []
    assert module._PENDING

    second = module._scan_broker(broker)
    assert second == 0
    assert broker.position_tracker.closed == []
    assert module._PENDING

    third = module._scan_broker(broker)
    assert third == 1
    assert len(broker.position_tracker.closed) == 1
    assert module._PENDING == {}


def test_immediate_filled_exit_closes_once(module, monkeypatch):
    class Broker(_AcceptedThenFilledBroker):
        broker_type = SimpleNamespace(value="okx")

        def place_market_order(self, **kwargs):
            return {
                "status": "filled",
                "order_id": "okx-1",
                "filled_size": 1.0,
                "filled_price": 103.0,
            }

    monkeypatch.setenv("NIJA_OKX_ROUND_TRIP_FEE_PCT", "0.001")
    monkeypatch.setenv("NIJA_EXIT_SLIPPAGE_RESERVE_PCT", "0")
    monkeypatch.setenv("NIJA_MINIMUM_NET_PROFIT_PCT", "0")
    broker = Broker()

    assert module._scan_broker(broker) == 1
    assert len(broker.position_tracker.closed) == 1
    assert module._PENDING == {}


def test_unverified_held_position_is_not_fabricated_or_sold(module):
    broker = _AcceptedThenFilledBroker()
    broker.position_tracker.positions[0]["entry_price"] = 0.0

    assert module._scan_broker(broker) == 0
    assert broker.position_tracker.closed == []
    assert module._PENDING == {}
