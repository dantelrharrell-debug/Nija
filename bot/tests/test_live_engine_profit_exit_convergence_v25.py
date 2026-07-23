from __future__ import annotations

import importlib
from types import ModuleType, SimpleNamespace

import pytest


@pytest.fixture()
def modules(monkeypatch):
    monkeypatch.setenv("NIJA_DEFER_RUNTIME_SITE_HOOKS", "1")
    monkeypatch.setenv("NIJA_LIVE_BROKER_PROFIT_EXIT_V25_ENABLED", "false")
    broker_v25 = importlib.import_module("bot.live_broker_profit_exit_convergence_v25")
    engine_v25 = importlib.import_module("bot.live_engine_profit_exit_convergence_v25")
    broker_v25._PENDING.clear()
    engine_v25._PENDING.clear()
    return broker_v25, engine_v25


class Ledger:
    def __init__(self):
        self.positions = [{
            "position_id": "engine-p1",
            "symbol": "ETH-USD",
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


class Broker:
    connected = True
    broker_type = SimpleNamespace(value="coinbase")

    def __init__(self):
        self.status_calls = 0

    def get_quote(self, symbol):
        return {"price": 103.0}

    def place_market_order(self, **kwargs):
        return {"status": "accepted", "order_id": "engine-o1"}

    def get_order_status(self, **kwargs):
        self.status_calls += 1
        if self.status_calls == 1:
            return {"status": "open", "order_id": "engine-o1"}
        return {
            "status": "filled",
            "order_id": "engine-o1",
            "filled_size": 1.0,
            "filled_price": 103.0,
        }


class Engine:
    def __init__(self):
        self.trade_ledger = Ledger()
        self.broker = Broker()
        self.active_exit_orders = set()


def _zero_profit_floor(monkeypatch):
    monkeypatch.setenv("NIJA_COINBASE_ROUND_TRIP_FEE_PCT", "0")
    monkeypatch.setenv("NIJA_EXIT_SLIPPAGE_RESERVE_PCT", "0")
    monkeypatch.setenv("NIJA_MINIMUM_NET_PROFIT_PCT", "0")
    monkeypatch.setenv("NIJA_EXIT_FILL_CONFIRM_TIMEOUT_S", "30")


def test_engine_accepted_order_remains_open_until_fill(modules, monkeypatch):
    _, engine_v25 = modules
    _zero_profit_floor(monkeypatch)
    engine = Engine()

    assert engine_v25._scan_engine(engine) == 0
    assert engine.trade_ledger.closed == []
    assert engine_v25._PENDING

    assert engine_v25._scan_engine(engine) == 0
    assert engine.trade_ledger.closed == []

    assert engine_v25._scan_engine(engine) == 1
    assert len(engine.trade_ledger.closed) == 1
    assert engine_v25._PENDING == {}


def test_future_execution_engine_class_receives_v25_scanner(modules, monkeypatch):
    _, engine_v25 = modules
    calls = []

    class ExecutionEngine:
        pass

    fake = ModuleType("bot.execution_engine")
    fake.ExecutionEngine = ExecutionEngine
    monkeypatch.setattr(engine_v25, "_ORIGINAL_PATCH_ENGINE", lambda module: calls.append(module) or True)

    assert engine_v25._patch_engine(fake) is True
    assert calls == [fake]
    assert ExecutionEngine.scan_stop_loss_take_profit_once is engine_v25._scan_engine
    assert getattr(ExecutionEngine, "__nija_live_engine_profit_exit_v25__") is True


def test_unverified_engine_position_is_never_sold(modules):
    _, engine_v25 = modules
    engine = Engine()
    engine.trade_ledger.positions[0]["entry_price"] = 0.0

    assert engine_v25._scan_engine(engine) == 0
    assert engine.trade_ledger.closed == []
    assert engine_v25._PENDING == {}
