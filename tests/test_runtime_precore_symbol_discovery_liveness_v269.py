from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import threading
import time
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
PATCH = ROOT / "bot" / "runtime_precore_symbol_discovery_liveness_v269_patch.py"
V207 = ROOT / "bot" / "runtime_precore_strategy_lookup_v207_patch.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _strategy_module() -> ModuleType:
    module = ModuleType("bot.trading_strategy")

    class TradingStrategy:
        @staticmethod
        def _broker_key_from_obj(_broker):
            return "kraken"

        @staticmethod
        def _dedupe_symbols(symbols):
            out = []
            seen = set()
            for raw in symbols:
                symbol = str(raw or "").strip()
                if symbol and symbol not in seen:
                    seen.add(symbol)
                    out.append(symbol)
            return out

        def _discover_broker_symbols(self, broker):
            return list(broker.get_available_markets())

    module.TradingStrategy = TradingStrategy
    return module


def test_v269_bounds_hung_discovery_and_preserves_fallback_contract(monkeypatch) -> None:
    v269 = _load("test_precore_symbol_v269_timeout", PATCH)
    strategy_module = _strategy_module()
    monkeypatch.setitem(sys.modules, "bot.trading_strategy", strategy_module)
    monkeypatch.setenv("NIJA_PRECORE_SYMBOL_DISCOVERY_TIMEOUT_S", "0.05")
    monkeypatch.setattr(v269, "_timeout_s", lambda: 0.05)

    block = threading.Event()

    class Broker:
        connected = True

        def get_available_markets(self):
            block.wait(1.0)
            return ["BTC-USD"]

    assert v269._patch_trading_strategy() is True
    strategy = strategy_module.TradingStrategy()
    started = time.monotonic()
    assert strategy._discover_broker_symbols(Broker()) == []
    elapsed = time.monotonic() - started
    block.set()

    assert elapsed < 0.30


def test_v269_successful_discovery_is_deduped(monkeypatch) -> None:
    v269 = _load("test_precore_symbol_v269_success", PATCH)
    strategy_module = _strategy_module()
    monkeypatch.setitem(sys.modules, "bot.trading_strategy", strategy_module)

    class Broker:
        connected = True

        def get_available_markets(self):
            return ["BTC-USD", "BTC-USD", "ETH-USD", ""]

    assert v269._patch_trading_strategy() is True
    strategy = strategy_module.TradingStrategy()
    assert strategy._discover_broker_symbols(Broker()) == ["BTC-USD", "ETH-USD"]


def test_v269_single_flight_refuses_duplicate_hung_read(monkeypatch) -> None:
    v269 = _load("test_precore_symbol_v269_singleflight", PATCH)
    monkeypatch.setattr(v269, "_timeout_s", lambda: 0.05)
    release = threading.Event()
    calls = []

    class Broker:
        def get_available_markets(self):
            calls.append(time.monotonic())
            release.wait(1.0)
            return ["BTC-USD"]

    broker = Broker()
    try:
        v269._bounded_read(broker, "get_available_markets")
        assert False, "first read should time out"
    except TimeoutError:
        pass

    started = time.monotonic()
    try:
        v269._bounded_read(broker, "get_available_markets")
        assert False, "duplicate read should be rejected while first worker is alive"
    except TimeoutError as exc:
        assert "inflight" in str(exc)
    elapsed = time.monotonic() - started
    release.set()

    assert len(calls) == 1
    assert elapsed < 0.10


def test_v269_does_not_mutate_trading_safety_state(monkeypatch) -> None:
    v269 = _load("test_precore_symbol_v269_invariants", PATCH)
    strategy_module = _strategy_module()
    manifest = ModuleType("bot.runtime_release_manifest_patch")
    manifest._REQUIRED_FLAGS = {}
    manifest._INSTALLERS = ()
    monkeypatch.setitem(sys.modules, "bot.trading_strategy", strategy_module)
    monkeypatch.setitem(sys.modules, "bot.runtime_release_manifest_patch", manifest)

    names = (
        "NIJA_RUNTIME_EXECUTION_AUTHORITY",
        "NIJA_RUNTIME_TRADING_STATE",
        "NIJA_KILL_SWITCH_ACTIVE",
        "NIJA_WRITER_FENCING_TOKEN",
        "NIJA_WRITER_LEASE_GENERATION",
    )
    before = {name: os.environ.get(name) for name in names}

    assert v269.install() is True

    after = {name: os.environ.get(name) for name in names}
    assert after == before
    assert os.environ["NIJA_RUNTIME_PRECORE_SYMBOL_DISCOVERY_LIVENESS_V269_READY"] == "1"
    assert manifest._REQUIRED_FLAGS["precore_symbol_discovery_liveness_v269"] == (
        "NIJA_RUNTIME_PRECORE_SYMBOL_DISCOVERY_LIVENESS_V269_READY"
    )


def test_v207_arms_v269_at_constructor_boundary(monkeypatch) -> None:
    v207 = _load("test_precore_strategy_v207_builder_v269", V207)
    publication = ModuleType("bot.strategy_publication_patch")
    calls = []

    def build(cls, brokers):
        calls.append(("build", cls, brokers))
        return cls()

    publication._build_strategy = build
    monkeypatch.setitem(sys.modules, "bot.strategy_publication_patch", publication)

    v269 = ModuleType("bot.runtime_precore_symbol_discovery_liveness_v269_patch")

    def install_v269():
        calls.append(("v269",))
        return True

    v269.install = install_v269
    monkeypatch.setitem(
        sys.modules,
        "bot.runtime_precore_symbol_discovery_liveness_v269_patch",
        v269,
    )

    assert v207._patch_strategy_builder() is True

    class Strategy:
        pass

    result = publication._build_strategy(Strategy, {"kraken": {"entry_ready": True}})
    assert isinstance(result, Strategy)
    assert calls[0] == ("v269",)
    assert calls[1][0] == "build"
