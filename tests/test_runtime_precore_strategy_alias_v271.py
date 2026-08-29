from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
V207 = ROOT / "bot" / "runtime_precore_strategy_lookup_v207_patch.py"
V269 = ROOT / "bot" / "runtime_precore_symbol_discovery_liveness_v269_patch.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _strategy_module(name: str) -> ModuleType:
    module = ModuleType(name)

    class TradingStrategy:
        @staticmethod
        def _broker_key_from_obj(_broker):
            return "kraken"

        @staticmethod
        def _dedupe_symbols(symbols):
            return list(dict.fromkeys(str(item) for item in symbols if item))

        def _discover_broker_symbols(self, broker):
            return list(broker.get_available_markets())

    module.TradingStrategy = TradingStrategy
    return module


def test_v269_patches_top_level_strategy_alias_without_package_alias(monkeypatch) -> None:
    v269 = _load("test_precore_alias_v269", V269)
    top_level = _strategy_module("trading_strategy")
    monkeypatch.setitem(sys.modules, "trading_strategy", top_level)
    monkeypatch.delitem(sys.modules, "bot.trading_strategy", raising=False)

    original = top_level.TradingStrategy._discover_broker_symbols
    assert v269._patch_trading_strategy() is True
    patched = top_level.TradingStrategy._discover_broker_symbols

    assert patched is not original
    assert getattr(patched, v269._PATCH_ATTR, False) is True


def test_v269_patches_distinct_package_and_top_level_classes(monkeypatch) -> None:
    v269 = _load("test_precore_alias_v269_dual", V269)
    package_module = _strategy_module("bot.trading_strategy")
    top_level = _strategy_module("trading_strategy")
    monkeypatch.setitem(sys.modules, "bot.trading_strategy", package_module)
    monkeypatch.setitem(sys.modules, "trading_strategy", top_level)

    assert package_module.TradingStrategy is not top_level.TradingStrategy
    assert v269._patch_trading_strategy() is True
    assert getattr(
        package_module.TradingStrategy._discover_broker_symbols,
        v269._PATCH_ATTR,
        False,
    ) is True
    assert getattr(
        top_level.TradingStrategy._discover_broker_symbols,
        v269._PATCH_ATTR,
        False,
    ) is True


def test_v207_alias_guard_patches_already_loaded_top_level_alias(monkeypatch) -> None:
    v207 = _load("test_precore_alias_v207_loaded", V207)
    top_level = _strategy_module("trading_strategy")
    monkeypatch.setitem(sys.modules, "trading_strategy", top_level)

    v269 = ModuleType("bot.runtime_precore_symbol_discovery_liveness_v269_patch")
    calls = []

    def patch():
        calls.append("patched")
        return True

    v269._patch_trading_strategy = patch
    monkeypatch.setitem(
        sys.modules,
        "bot.runtime_precore_symbol_discovery_liveness_v269_patch",
        v269,
    )

    assert v207._install_strategy_alias_guard() is True
    assert calls == ["patched"]


def test_v207_alias_guard_arms_without_importing_strategy(monkeypatch) -> None:
    v207 = _load("test_precore_alias_v207_arm", V207)
    monkeypatch.delitem(sys.modules, "trading_strategy", raising=False)
    original_meta_path = list(sys.meta_path)
    monkeypatch.setattr(sys, "meta_path", list(original_meta_path))

    assert v207._install_strategy_alias_guard() is True
    assert "trading_strategy" not in sys.modules
    assert any(
        isinstance(finder, v207._TradingStrategyAliasFinder)
        for finder in sys.meta_path
    )
