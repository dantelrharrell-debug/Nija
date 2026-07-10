from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

from bot import trading_engine_strategy_wrapper_patch as patch


class FakeBroker:
    connected = True
    _last_known_balance = 25.0

    def get_account_balance(self):
        return 25.0


class FakeCoreLoop:
    def __init__(self):
        self.calls = []

    def run_scan_phase(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(next_interval=7.0)


class FakeApex:
    symbols = ["ADA-USD"]

    def __init__(self, broker_client=None):
        self.broker_client = broker_client
        self.execution_engine = SimpleNamespace()

    def update_broker_client(self, broker):
        self.broker_client = broker


def test_broker_wrapper_does_not_raise_when_trading_strategy_class_missing(monkeypatch):
    fake_strategy_module = ModuleType("bot.trading_strategy")
    monkeypatch.setitem(sys.modules, "bot.trading_strategy", fake_strategy_module)

    fake_apex_module = ModuleType("bot.nija_apex_strategy_v71")
    fake_apex_module.NIJAApexStrategyV71 = FakeApex
    monkeypatch.setitem(sys.modules, "bot.nija_apex_strategy_v71", fake_apex_module)

    fake_core_module = ModuleType("bot.nija_core_loop")
    fake_core = FakeCoreLoop()
    fake_core_module.get_nija_core_loop = lambda **_: fake_core
    monkeypatch.setitem(sys.modules, "bot.nija_core_loop", fake_core_module)

    runtime = patch._wrap_broker_as_strategy(FakeBroker())

    assert runtime.broker is not None
    assert callable(runtime.run_cycle)
    assert runtime.apex is not None
    assert runtime.nija_core_loop is fake_core
    assert runtime.run_cycle() == 7.0
    assert fake_core.calls
    assert fake_core.calls[0]["symbols"] == ["ADA-USD"]


def test_broker_wrapper_prefers_real_trading_strategy_class(monkeypatch):
    class FakeTradingStrategy:
        def __init__(self, broker_results=None):
            self.broker_results = broker_results
            self.broker = None
            self.apex = SimpleNamespace(update_broker_client=lambda broker: None)
            self.execution_engine = SimpleNamespace()
            self.symbols = ["BTC-USD"]

        def run_cycle(self):
            return 5.0

    fake_strategy_module = ModuleType("bot.trading_strategy")
    fake_strategy_module.TradingStrategy = FakeTradingStrategy
    monkeypatch.setitem(sys.modules, "bot.trading_strategy", fake_strategy_module)

    broker = FakeBroker()
    runtime = patch._wrap_broker_as_strategy(broker)

    assert isinstance(runtime, FakeTradingStrategy)
    assert runtime.broker is broker
    assert runtime.broker_results == {"fake": {"broker": broker}}
