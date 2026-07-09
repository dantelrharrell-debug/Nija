from __future__ import annotations

import time
from types import SimpleNamespace

from bot import phase3_scan_stall_guard_patch as patch


class FakeCoreLoop:
    def __init__(self):
        self.last_symbols = None

    def _fetch_df(self, broker, symbol):
        return {"symbol": symbol}

    def _phase3_scan_and_enter(self, broker, snapshot, symbols, available_slots, zero_signal_streak=0):
        self.last_symbols = list(symbols)
        return (0, 0, len(self.last_symbols), {})


def test_phase3_window_limits_and_rotates_symbols(monkeypatch):
    monkeypatch.setenv("NIJA_PHASE3_SCAN_MAX_SYMBOLS", "10")
    monkeypatch.setenv("NIJA_PHASE3_SCAN_SYMBOLS_PER_SLOT", "5")
    owner = SimpleNamespace()
    symbols = [f"S{i}" for i in range(25)]

    first, meta1 = patch._window_symbols(owner, symbols, available_slots=1)
    second, meta2 = patch._window_symbols(owner, symbols, available_slots=1)

    assert len(first) == 10
    assert len(second) == 10
    assert first[0] == "S0"
    assert second[0] == "S10"
    assert meta1["next_cursor"] == 10
    assert meta2["next_cursor"] == 20


def test_fetch_df_deadline_skip_returns_none(monkeypatch):
    module = SimpleNamespace(NijaCoreLoop=FakeCoreLoop, __name__="bot.nija_core_loop")
    assert patch._patch_core_loop_module(module) is True
    loop = module.NijaCoreLoop()
    loop._nija_phase3_deadline_ts_20260709al = time.monotonic() - 1.0

    assert loop._fetch_df(object(), "BTC-USD") is None


def test_phase3_wrapper_sends_bounded_symbol_window(monkeypatch):
    monkeypatch.setenv("NIJA_PHASE3_SCAN_MAX_SYMBOLS", "12")
    monkeypatch.setenv("NIJA_PHASE3_SCAN_SYMBOLS_PER_SLOT", "5")
    module = SimpleNamespace(NijaCoreLoop=FakeCoreLoop, __name__="bot.nija_core_loop")
    assert patch._patch_core_loop_module(module) is True
    loop = module.NijaCoreLoop()
    symbols = [f"S{i}" for i in range(50)]

    result = loop._phase3_scan_and_enter(object(), object(), symbols, 1)

    assert result[2] == 12
    assert len(loop.last_symbols) == 12
    assert loop.last_symbols[0] == "S0"
