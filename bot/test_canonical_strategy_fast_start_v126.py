from __future__ import annotations

import os
import time
from types import ModuleType

from bot import canonical_strategy_fast_start_v126_patch as patch


class FakeBroker:
    connected = True


class FakeStrategy:
    def __init__(self, broker_results=None):
        self.broker = None
        self.symbols = []
        self.populate_calls = 0
        for meta in (broker_results or {}).values():
            broker = (meta or {}).get("broker")
            if broker is not None and getattr(broker, "connected", False):
                self.broker = broker
                break
        self._populate_symbols()

    def _ensure_symbol_universe_state(self):
        if self.symbols is None:
            self.symbols = []

    def _populate_symbols(self):
        self.populate_calls += 1
        time.sleep(0.05)
        self.symbols = ["BTC-USD"]

    def run_cycle(self):
        return None


def _publication_module():
    module = ModuleType("fake_publication")

    def best(brokers):
        for meta in brokers.values():
            broker = meta.get("broker") if isinstance(meta, dict) else None
            if broker is not None and getattr(broker, "connected", False):
                return broker
        return None

    def build(cls, brokers):
        return cls(broker_results=brokers)

    def sync(strategy, broker):
        strategy.broker = broker

    module._best_broker_from_results = best
    module._build_strategy = build
    module._sync_broker_into_strategy = sync
    return module


def test_fast_start_requires_real_connected_broker():
    publication = _publication_module()
    strategy_module = ModuleType("fake_strategy")
    strategy_module.TradingStrategy = FakeStrategy
    assert patch._patch_build_strategy(publication, strategy_module)

    disconnected = FakeBroker()
    disconnected.connected = False
    strategy = publication._build_strategy(
        FakeStrategy, {"kraken": {"broker": disconnected}}
    )
    assert strategy.broker is None


def test_fast_start_defers_symbol_io_and_preserves_real_broker(monkeypatch):
    publication = _publication_module()
    strategy_module = ModuleType("fake_strategy")
    strategy_module.TradingStrategy = FakeStrategy
    assert patch._patch_build_strategy(publication, strategy_module)

    monkeypatch.setenv("NIJA_V126_SYMBOL_DEFER_S", "0.25")
    broker = FakeBroker()
    started = time.monotonic()
    strategy = publication._build_strategy(
        FakeStrategy, {"kraken": {"broker": broker}}
    )
    elapsed = time.monotonic() - started

    assert elapsed < 0.05
    assert strategy.broker is broker
    assert strategy.symbols == []
    assert callable(strategy.run_cycle)

    deadline = time.monotonic() + 1.0
    while not strategy.symbols and time.monotonic() < deadline:
        time.sleep(0.02)
    assert strategy.symbols == ["BTC-USD"]


def test_fast_start_does_not_grant_execution_authority(monkeypatch):
    publication = _publication_module()
    strategy_module = ModuleType("fake_strategy")
    strategy_module.TradingStrategy = FakeStrategy
    assert patch._patch_build_strategy(publication, strategy_module)

    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")
    broker = FakeBroker()
    publication._build_strategy(FakeStrategy, {"kraken": {"broker": broker}})
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"


def test_release_manifest_is_v126(monkeypatch):
    manifest = ModuleType("bot.runtime_release_manifest_patch")
    manifest._REQUIRED_FLAGS = {}
    monkeypatch.setitem(__import__("sys").modules, "bot.runtime_release_manifest_patch", manifest)
    assert patch._patch_release_manifest()
    assert manifest.RELEASE_ID == patch.RELEASE_ID
    assert manifest._REQUIRED_FLAGS["canonical_strategy_fast_start_v126"] == patch._FLAG
