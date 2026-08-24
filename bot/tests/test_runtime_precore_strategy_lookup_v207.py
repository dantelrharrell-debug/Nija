from __future__ import annotations

import importlib
import sys
from types import SimpleNamespace


def test_nonblocking_lookup_never_calls_broad_existing_finder(monkeypatch):
    v207 = importlib.import_module("bot.runtime_precore_strategy_lookup_v207_patch")
    v203 = importlib.import_module("bot.runtime_existing_strategy_heartbeat_rearm_v203_patch")

    calls = {"broad": 0, "cached": 0}

    def broad_existing(*args, **kwargs):
        calls["broad"] += 1
        raise AssertionError("pre-core broad strategy discovery must not run")

    def cached_lookup():
        calls["cached"] += 1
        return None

    # Model the historical v203 function that could reach publication._existing.
    monkeypatch.setattr(v203, "_already_published_strategy", broad_existing)
    monkeypatch.setattr(v203, "_strategy_from_cached_runtime_publisher", cached_lookup)

    publication = SimpleNamespace(_PUBLISHED=None)
    monkeypatch.setitem(sys.modules, "bot.strategy_publication_patch", publication)

    # _patch_v203 replaces the broad immediate lookup before v203.install uses it.
    assert v207._patch_v203() is True
    installed = v203._already_published_strategy
    assert installed(publication) is None
    assert calls["broad"] == 0
    assert calls["cached"] == 1


def test_nonblocking_lookup_returns_exact_loaded_strategy(monkeypatch):
    v207 = importlib.import_module("bot.runtime_precore_strategy_lookup_v207_patch")

    strategy = SimpleNamespace(run_cycle=lambda: None)
    fake_bot_main = SimpleNamespace(_initialized_state={"strategy": strategy})
    monkeypatch.setitem(sys.modules, "bot.bot_main", fake_bot_main)

    publication = SimpleNamespace(_PUBLISHED=None)
    v203 = SimpleNamespace(
        _strategy_from_cached_runtime_publisher=lambda: (_ for _ in ()).throw(
            AssertionError("cached fallback should not run when a loaded strategy exists")
        )
    )

    recovered = v207._nonblocking_existing_strategy(publication, v203)
    assert recovered is strategy


def test_nonblocking_lookup_prefers_current_published_pointer(monkeypatch):
    v207 = importlib.import_module("bot.runtime_precore_strategy_lookup_v207_patch")

    strategy = SimpleNamespace(run_cycle=lambda: None)
    publication = SimpleNamespace(_PUBLISHED=strategy)
    v203 = SimpleNamespace(
        _strategy_from_cached_runtime_publisher=lambda: (_ for _ in ()).throw(
            AssertionError("cached fallback should not run for current _PUBLISHED")
        )
    )

    assert v207._nonblocking_existing_strategy(publication, v203) is strategy
