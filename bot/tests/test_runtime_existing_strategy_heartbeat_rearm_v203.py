from __future__ import annotations

import importlib
import threading
from types import SimpleNamespace


class _AliveThread:
    def is_alive(self) -> bool:
        return True


def test_rearm_already_published_strategy_uses_existing_object(monkeypatch):
    module = importlib.import_module("bot.runtime_existing_strategy_heartbeat_rearm_v203_patch")

    calls = {"scheduler": 0}
    strategy = SimpleNamespace(
        _heartbeat_trade_enabled=False,
        _heartbeat_trade_thread=None,
        _heartbeat_trade_completed=False,
        _heartbeat_trade_success=False,
        _heartbeat_trade_lock=threading.Lock(),
    )

    def schedule() -> None:
        calls["scheduler"] += 1
        strategy._heartbeat_trade_thread = _AliveThread()

    strategy._schedule_heartbeat_trade = schedule
    publication = SimpleNamespace(_PUBLISHED=strategy)

    monkeypatch.setenv("HEARTBEAT_TRADE", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")

    assert module._rearm_already_published_strategy(publication) is True
    assert publication._PUBLISHED is strategy
    assert calls["scheduler"] == 1
    assert strategy._heartbeat_trade_enabled is True
    assert strategy._heartbeat_trade_thread.is_alive() is True
    assert __import__("os").environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"


def test_rearm_already_published_strategy_is_noop_when_none_exists(monkeypatch):
    module = importlib.import_module("bot.runtime_existing_strategy_heartbeat_rearm_v203_patch")
    publication = SimpleNamespace(_PUBLISHED=None)

    monkeypatch.setenv("HEARTBEAT_TRADE", "true")

    assert module._rearm_already_published_strategy(publication) is True


def test_existing_live_scheduler_is_not_duplicated(monkeypatch):
    module = importlib.import_module("bot.runtime_existing_strategy_heartbeat_rearm_v203_patch")

    calls = {"scheduler": 0}
    strategy = SimpleNamespace(
        _heartbeat_trade_enabled=True,
        _heartbeat_trade_thread=_AliveThread(),
        _heartbeat_trade_completed=False,
        _heartbeat_trade_success=False,
        _heartbeat_trade_lock=threading.Lock(),
    )

    def schedule() -> None:
        calls["scheduler"] += 1

    strategy._schedule_heartbeat_trade = schedule

    monkeypatch.setenv("HEARTBEAT_TRADE", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")

    assert module._ensure_heartbeat_scheduler(strategy) is True
    assert calls["scheduler"] == 0
