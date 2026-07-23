from __future__ import annotations

from types import ModuleType

import bot.zero_signal_streak_state_repair_patch as patch


def _module(observed):
    module = ModuleType("bot.nija_core_loop")

    class NijaCoreLoop:
        def __init__(self, streak):
            self._zero_signal_streak = streak

        def _phase3_scan_and_enter(
            self,
            broker,
            snapshot,
            symbols,
            available_slots,
            zero_signal_streak=0,
        ):
            observed.append((self._zero_signal_streak, zero_signal_streak))
            self._zero_signal_streak += 1
            return 0, 0, 1, {}

    module.NijaCoreLoop = NijaCoreLoop
    return module


def test_stale_999_state_is_reset_before_phase3(monkeypatch):
    monkeypatch.setenv("NIJA_ZERO_SIGNAL_STREAK_CAP", "12")
    monkeypatch.setenv("NIJA_ZERO_SIGNAL_STREAK_STALE_THRESHOLD", "100")
    observed = []
    module = _module(observed)

    assert patch._install_on_core_loop(module) is True
    loop = module.NijaCoreLoop(999)
    result = loop._phase3_scan_and_enter(None, None, [], 1, 999)

    assert result[:3] == (0, 0, 1)
    assert observed == [(0, 0)]
    assert loop._zero_signal_streak == 1
    assert patch.os.environ["NIJA_ZERO_SIGNAL_STREAK_STATE_READY"] == "1"


def test_ordinary_long_streak_is_bounded_not_reset(monkeypatch):
    monkeypatch.setenv("NIJA_ZERO_SIGNAL_STREAK_CAP", "12")
    monkeypatch.setenv("NIJA_ZERO_SIGNAL_STREAK_STALE_THRESHOLD", "100")
    observed = []
    module = _module(observed)

    patch._install_on_core_loop(module)
    loop = module.NijaCoreLoop(20)
    loop._phase3_scan_and_enter(None, None, [], 1, 20)

    assert observed == [(12, 12)]
    assert loop._zero_signal_streak == 13


def test_next_cycle_rebounds_post_increment_state(monkeypatch):
    monkeypatch.setenv("NIJA_ZERO_SIGNAL_STREAK_CAP", "12")
    monkeypatch.setenv("NIJA_ZERO_SIGNAL_STREAK_STALE_THRESHOLD", "100")
    observed = []
    module = _module(observed)

    patch._install_on_core_loop(module)
    loop = module.NijaCoreLoop(20)
    loop._phase3_scan_and_enter(None, None, [], 1, 20)
    loop._phase3_scan_and_enter(None, None, [], 1, loop._zero_signal_streak)

    assert observed == [(12, 12), (12, 12)]
    assert loop._zero_signal_streak == 13


def test_repair_value_contract():
    assert patch._repair_value(999, 12, 100) == (0, "stale_sentinel_reset")
    assert patch._repair_value(20, 12, 100) == (12, "bounded")
    assert patch._repair_value(1, 12, 100) == (1, "unchanged")


def test_install_is_chain_aware(monkeypatch):
    monkeypatch.setenv("NIJA_ZERO_SIGNAL_STREAK_CAP", "12")
    observed = []
    module = _module(observed)

    assert patch._install_on_core_loop(module) is True
    first = module.NijaCoreLoop._phase3_scan_and_enter
    assert patch._install_on_core_loop(module) is True
    assert module.NijaCoreLoop._phase3_scan_and_enter is first


def test_try_loaded_reattaches_after_late_phase3_replacement(monkeypatch):
    observed = []
    module = _module(observed)
    monkeypatch.setitem(patch.sys.modules, "bot.nija_core_loop", module)
    monkeypatch.delitem(patch.sys.modules, "nija_core_loop", raising=False)

    assert patch._try_loaded() is True
    first = module.NijaCoreLoop._phase3_scan_and_enter
    found, cycle, _ = patch._chain_contains(first)
    assert found is True
    assert cycle is False

    def late_replacement(
        self,
        broker,
        snapshot,
        symbols,
        available_slots,
        zero_signal_streak=0,
    ):
        observed.append((self._zero_signal_streak, zero_signal_streak))
        return 0, 0, 0, {}

    module.NijaCoreLoop._phase3_scan_and_enter = late_replacement
    found, cycle, _ = patch._chain_contains(module.NijaCoreLoop._phase3_scan_and_enter)
    assert found is False
    assert cycle is False

    assert patch._try_loaded() is True
    repaired = module.NijaCoreLoop._phase3_scan_and_enter
    found, cycle, _ = patch._chain_contains(repaired)
    assert repaired is not late_replacement
    assert found is True
    assert cycle is False
    assert repaired.__wrapped__ is late_replacement
    assert patch.os.environ["NIJA_ZERO_SIGNAL_STREAK_STATE_READY"] == "1"
