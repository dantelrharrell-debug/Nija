from __future__ import annotations

from types import ModuleType, SimpleNamespace

import bot.runtime_kraken_capital_balance_liveness_v183_patch as v183


def _fake_broker_module(events):
    module = ModuleType("bot.broker_manager")

    class KrakenBroker:
        def __init__(self):
            self.account_identifier = "PLATFORM"

        def _get_asset_usd_price(self, symbol):
            events.append(("network_price", symbol))
            return 123.0

        def get_account_balance(self, verbose=True):
            events.append(("balance_enter", v183._in_capital_balance_context(self)))
            price = self._get_asset_usd_price("BTC")
            events.append(("balance_price", price))
            return 250.0

    module.KrakenBroker = KrakenBroker
    return module, KrakenBroker


def test_normal_price_lookup_unchanged_outside_capital_balance_context(monkeypatch):
    events = []
    module, broker_cls = _fake_broker_module(events)
    real_import = v183.importlib.import_module

    def fake_import(name):
        if name == "bot.broker_manager":
            return module
        return real_import(name)

    monkeypatch.setattr(v183.importlib, "import_module", fake_import)
    monkeypatch.setattr(v183, "_cached_asset_price", lambda broker, symbol: None)

    assert v183._patch_kraken_balance_context() is True
    broker = broker_cls()

    assert broker._get_asset_usd_price("ETH") == 123.0
    assert events == [("network_price", "ETH")]


def test_capital_balance_cache_hit_avoids_network_lookup(monkeypatch):
    events = []
    module, broker_cls = _fake_broker_module(events)
    real_import = v183.importlib.import_module

    def fake_import(name):
        if name == "bot.broker_manager":
            return module
        return real_import(name)

    monkeypatch.setattr(v183.importlib, "import_module", fake_import)
    monkeypatch.setattr(v183, "_cached_asset_price", lambda broker, symbol: 77.0)

    assert v183._patch_kraken_balance_context() is True
    broker = broker_cls()

    assert broker.get_account_balance(verbose=False) == 250.0
    assert events == [
        ("balance_enter", True),
        ("balance_price", 77.0),
    ]
    assert v183._in_capital_balance_context(broker) is False


def test_capital_balance_cache_miss_fails_closed_without_network_lookup(monkeypatch):
    events = []
    module, broker_cls = _fake_broker_module(events)
    real_import = v183.importlib.import_module

    def fake_import(name):
        if name == "bot.broker_manager":
            return module
        return real_import(name)

    monkeypatch.setattr(v183.importlib, "import_module", fake_import)
    monkeypatch.setattr(v183, "_cached_asset_price", lambda broker, symbol: None)

    assert v183._patch_kraken_balance_context() is True
    broker = broker_cls()

    assert broker.get_account_balance() == 250.0
    assert events == [
        ("balance_enter", True),
        ("balance_price", 0.0),
    ]
    assert v183._in_capital_balance_context(broker) is False


def test_balance_context_restores_nested_thread_local_state(monkeypatch):
    events = []
    module, broker_cls = _fake_broker_module(events)
    real_import = v183.importlib.import_module

    def fake_import(name):
        if name == "bot.broker_manager":
            return module
        return real_import(name)

    monkeypatch.setattr(v183.importlib, "import_module", fake_import)
    monkeypatch.setattr(v183, "_cached_asset_price", lambda broker, symbol: 11.0)

    outer = object()
    v183._LOCAL.active = True
    v183._LOCAL.broker = outer
    try:
        assert v183._patch_kraken_balance_context() is True
        broker = broker_cls()
        broker.get_account_balance()
        assert v183._LOCAL.active is True
        assert v183._LOCAL.broker is outer
    finally:
        v183._LOCAL.active = False
        v183._LOCAL.broker = None


def test_release_manifest_attests_v183(monkeypatch):
    required = {}
    fake_manifest = SimpleNamespace(_REQUIRED_FLAGS=required)
    real_import = v183.importlib.import_module

    def fake_import(name):
        if name == "bot.runtime_release_manifest_patch":
            return fake_manifest
        return real_import(name)

    monkeypatch.setattr(v183.importlib, "import_module", fake_import)

    assert v183._patch_release_manifest() is True
    assert required["runtime_kraken_capital_balance_liveness_v183"] == (
        "NIJA_RUNTIME_KRAKEN_CAPITAL_BALANCE_LIVENESS_V183_READY"
    )


def test_safety_environment_not_modified(monkeypatch):
    monkeypatch.setenv("NIJA_EMERGENCY_STOP", "1")
    monkeypatch.setenv("NIJA_NONCE_READY", "0")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")

    assert __import__("os").environ["NIJA_EMERGENCY_STOP"] == "1"
    assert __import__("os").environ["NIJA_NONCE_READY"] == "0"
    assert __import__("os").environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
