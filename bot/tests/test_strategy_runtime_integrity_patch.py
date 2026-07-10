from __future__ import annotations

from types import SimpleNamespace

from bot import strategy_runtime_integrity_patch as patch


class Broker:
    connected = True


class BrokenStrategy:
    def __init__(self):
        self.broker = None
        self.apex = None
        self.nija_core_loop = None
        self.execution_engine = None

    def _ensure_nija_wiring(self):
        return None


class Apex:
    def __init__(self):
        self.broker_client = None
        self.execution_engine = SimpleNamespace(broker_client=None)

    def update_broker_client(self, broker):
        self.broker_client = broker


class FallbackStrategy:
    def __init__(self, broker):
        self.broker = broker
        self.apex = Apex()
        self.nija_core_loop = SimpleNamespace(apex=self.apex)
        self.execution_engine = self.apex.execution_engine

    def _ensure_nija_wiring(self):
        return None


def test_incomplete_primary_strategy_is_replaced_by_wired_fallback(monkeypatch):
    module = SimpleNamespace(
        __name__="bot.trading_engine_strategy_wrapper_patch",
        _BrokerRuntimeStrategy=FallbackStrategy,
        _wrap_broker_as_strategy=lambda broker: BrokenStrategy(),
    )
    monkeypatch.setattr(patch.importlib, "import_module", lambda name: (_ for _ in ()).throw(ImportError(name)))

    assert patch._patch_module(module) is True
    broker = Broker()
    strategy = module._wrap_broker_as_strategy(broker)

    assert isinstance(strategy, FallbackStrategy)
    assert strategy.broker is broker
    assert strategy.apex is not None
    assert strategy.nija_core_loop is not None
    assert strategy.apex.broker_client is broker
    assert strategy.execution_engine.broker_client is broker


def test_wired_primary_strategy_is_preserved():
    broker = Broker()
    primary = FallbackStrategy(broker)
    module = SimpleNamespace(
        __name__="bot.trading_engine_strategy_wrapper_patch",
        _BrokerRuntimeStrategy=FallbackStrategy,
        _wrap_broker_as_strategy=lambda supplied: primary,
    )

    assert patch._patch_module(module) is True
    assert module._wrap_broker_as_strategy(broker) is primary
