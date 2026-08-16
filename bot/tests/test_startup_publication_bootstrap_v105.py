from __future__ import annotations

import builtins
import importlib
import sys
import types


def _fresh_v105():
    sys.modules.pop("bot.startup_publication_bootstrap_v105_patch", None)
    return importlib.import_module("bot.startup_publication_bootstrap_v105_patch")


def test_v105_defers_cycle_prone_imports_while_trading_strategy_initializes(monkeypatch):
    v105 = _fresh_v105()
    original = builtins.__import__
    try:
        assert v105.install() is True
        fake = types.ModuleType("bot.trading_strategy")
        fake.__spec__ = types.SimpleNamespace(_initializing=True)
        monkeypatch.setitem(sys.modules, "bot.trading_strategy", fake)
        globals_dict = {"__name__": "bot.trading_strategy"}
        try:
            builtins.__import__("bot.nija_core_loop", globals_dict, globals_dict, (), 0)
        except ImportError as exc:
            assert "v105 deferred optional import" in str(exc)
        else:
            raise AssertionError("cycle-prone import was not deferred")
    finally:
        builtins.__import__ = original


def test_v105_platform_ready_callback_is_single_flight(monkeypatch):
    v105 = _fresh_v105()

    class Manager:
        calls = 0

        def _on_platform_ready(self, broker_type):
            type(self).calls += 1
            if type(self).calls == 1:
                self._on_platform_ready(broker_type)
            return "ok"

    fake = types.ModuleType("bot.multi_account_broker_manager")
    fake.MultiAccountBrokerManager = Manager
    fake.__spec__ = types.SimpleNamespace(_initializing=False)
    monkeypatch.setitem(sys.modules, "bot.multi_account_broker_manager", fake)

    assert v105._patch_mabm_module(fake) is True
    manager = Manager()
    assert manager._on_platform_ready("kraken") == "ok"
    assert Manager.calls == 1


def test_v105_hydrates_strategy_dependencies_after_class_publication(monkeypatch):
    v105 = _fresh_v105()
    strategy = types.ModuleType("bot.trading_strategy")
    strategy.__spec__ = types.SimpleNamespace(_initializing=False)

    class TradingStrategy:
        def __init__(self):
            self.seen_apex_available = strategy._APEX_AVAILABLE

    strategy.TradingStrategy = TradingStrategy
    strategy._APEX_AVAILABLE = False

    apex = types.ModuleType("bot.nija_apex_strategy_v71")

    class Apex:
        pass

    apex.NIJAApexStrategyV71 = Apex
    broker = types.ModuleType("bot.broker_manager")
    for name in ("BrokerType", "KrakenBroker", "CoinbaseBroker", "BaseBroker", "BrokerManager"):
        setattr(broker, name, type(name, (), {}))
    mabm = types.ModuleType("bot.multi_account_broker_manager")
    mabm.MultiAccountBrokerManager = type("MultiAccountBrokerManager", (), {})
    ibt = types.ModuleType("bot.independent_broker_trader")
    ibt.IndependentBrokerTrader = type("IndependentBrokerTrader", (), {})
    core = types.ModuleType("bot.nija_core_loop")
    core.get_nija_core_loop = lambda **kwargs: object()
    pipeline = types.ModuleType("bot.pipeline_order_submitter")
    pipeline.submit_market_order_via_pipeline = lambda *args, **kwargs: None
    market = types.ModuleType("bot.market_readiness_gate")
    market.MarketReadinessGate = type("MarketReadinessGate", (), {})

    for name, module in {
        "bot.trading_strategy": strategy,
        "bot.nija_apex_strategy_v71": apex,
        "bot.broker_manager": broker,
        "bot.multi_account_broker_manager": mabm,
        "bot.independent_broker_trader": ibt,
        "bot.nija_core_loop": core,
        "bot.pipeline_order_submitter": pipeline,
        "bot.market_readiness_gate": market,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)

    assert v105._patch_strategy_module(strategy) is True
    instance = strategy.TradingStrategy()
    assert instance.seen_apex_available is True
    assert strategy.NIJAApexStrategyV71 is Apex
