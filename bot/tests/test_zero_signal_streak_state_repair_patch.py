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
            # Mirror the production post-scan no-entry update source behavior.
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
