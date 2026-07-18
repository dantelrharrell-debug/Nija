from __future__ import annotations

import importlib
import os
from types import SimpleNamespace


auto_exit = importlib.import_module("bot.auto_exit_sl_tp_runtime_patch")
trailing = importlib.import_module("bot.trailing_take_profit_runtime_patch")


def test_fixed_take_profit_triggers_long_position(monkeypatch):
    monkeypatch.setattr(auto_exit, "_HIGH_WATER", {})
    position = {
        "position_id": "p-long",
        "user_id": "platform",
        "symbol": "BTC-USD",
        "side": "long",
        "entry_price": 100.0,
        "quantity": 1.0,
        "stop_loss": 98.0,
        "take_profit_1": 101.0,
        "take_profit_2": 102.0,
        "take_profit_3": 103.0,
    }

    hit, reason, target = auto_exit._trigger(position, 101.0)

    assert hit is True
    assert reason == "take_profit_1"
    assert target == 101.0


def test_fixed_take_profit_triggers_short_position(monkeypatch):
    monkeypatch.setattr(auto_exit, "_HIGH_WATER", {})
    position = {
        "position_id": "p-short",
        "user_id": "user-1",
        "symbol": "ETH-USD",
        "side": "short",
        "entry_price": 100.0,
        "quantity": 1.0,
        "stop_loss": 102.0,
        "take_profit_1": 99.0,
        "take_profit_2": 98.0,
        "take_profit_3": 97.0,
    }

    hit, reason, target = auto_exit._trigger(position, 99.0)

    assert hit is True
    assert reason == "take_profit_1"
    assert target == 99.0


def test_trailing_monitor_delegates_to_canonical_auto_exit(monkeypatch):
    monkeypatch.setenv("NIJA_AUTO_EXIT_SL_TP_ENABLED", "true")
    monkeypatch.delenv("NIJA_TRAILING_TP_CANONICAL_OWNER", raising=False)
    monkeypatch.setattr(trailing, "_PROCESS_STARTED", False)

    trailing._start_monitor()

    assert os.environ["NIJA_TRAILING_TP_CANONICAL_OWNER"] == "auto_exit_sl_tp_runtime_patch"
    assert trailing._PROCESS_STARTED is False


def test_trailing_fallback_registry_keeps_multiple_engines(monkeypatch):
    monkeypatch.setenv("NIJA_AUTO_EXIT_SL_TP_ENABLED", "true")
    monkeypatch.setattr(trailing, "_ENGINES", trailing.weakref.WeakSet())
    monkeypatch.setattr(trailing.builtins, "_NIJA_TRAILING_TP_ENGINE_REGISTRY", [], raising=False)

    first = SimpleNamespace()
    second = SimpleNamespace()
    trailing._register_engine(first)
    trailing._register_engine(second)

    snapshot = trailing._engine_snapshot()
    assert first in snapshot
    assert second in snapshot
