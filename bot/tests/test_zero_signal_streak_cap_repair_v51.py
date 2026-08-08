from __future__ import annotations

import sys
from types import ModuleType

import bot.zero_signal_streak_cap_repair_v51_patch as v51


def _core_module(func):
    module = ModuleType("bot.nija_core_loop")
    module.NijaCoreLoop = type("NijaCoreLoop", (), {"_phase3_scan_and_enter": func})
    return module


def test_v51_restores_missing_cap_without_removing_state_guard(monkeypatch):
    def leaf(self, broker, snapshot, symbols, slots, streak=0):
        return streak

    def state(self, broker, snapshot, symbols, slots, streak=0):
        return leaf(self, broker, snapshot, symbols, slots, streak)

    state.__wrapped__ = leaf
    setattr(state, v51._STATE_ATTR, True)
    core = _core_module(state)
    monkeypatch.setitem(sys.modules, "bot.nija_core_loop", core)
    monkeypatch.delitem(sys.modules, "nija_core_loop", raising=False)
    monkeypatch.setenv("NIJA_ZERO_SIGNAL_STREAK_CAP", "12")

    assert v51._install_on_core_loop(core) is True
    current = core.NijaCoreLoop._phase3_scan_and_enter
    cap_found, cycle, _ = v51._chain_contains(current)
    state_found, state_cycle, _ = v51._chain_contains(current, v51._STATE_ATTR)

    assert cap_found is True
    assert state_found is True
    assert cycle is False
    assert state_cycle is False
    assert current(object(), None, None, None, None, 99) == 12


def test_v51_is_idempotent(monkeypatch):
    def leaf(self, broker, snapshot, symbols, slots, streak=0):
        return streak

    core = _core_module(leaf)
    monkeypatch.setitem(sys.modules, "bot.nija_core_loop", core)
    monkeypatch.delitem(sys.modules, "nija_core_loop", raising=False)

    assert v51._install_on_core_loop(core) is True
    first = core.NijaCoreLoop._phase3_scan_and_enter
    assert v51._install_on_core_loop(core) is True
    second = core.NijaCoreLoop._phase3_scan_and_enter

    assert first is second


def test_v51_rejects_wrapper_cycle(monkeypatch):
    def first(self, broker, snapshot, symbols, slots, streak=0):
        return streak

    def second(self, broker, snapshot, symbols, slots, streak=0):
        return streak

    first.__wrapped__ = second
    second.__wrapped__ = first
    core = _core_module(first)
    monkeypatch.setitem(sys.modules, "bot.nija_core_loop", core)
    monkeypatch.delenv("NIJA_ZERO_SIGNAL_STREAK_CAP_READY", raising=False)

    assert v51._install_on_core_loop(core) is False
    assert v51.os.environ["NIJA_ZERO_SIGNAL_STREAK_CAP_READY"] == "0"


def test_v51_cap_is_bounded_by_policy(monkeypatch):
    monkeypatch.setenv("NIJA_ZERO_SIGNAL_STREAK_CAP", "999")
    assert v51._cap_value() == 12
    monkeypatch.setenv("NIJA_ZERO_SIGNAL_STREAK_CAP", "1")
    assert v51._cap_value() == 2
