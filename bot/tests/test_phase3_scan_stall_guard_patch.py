from __future__ import annotations

import time
from types import SimpleNamespace

from bot import phase3_scan_stall_guard_patch as patch


class FakeILoc:
    def __init__(self, values):
        self.values = list(values)

    def __getitem__(self, idx):
        return self.values[idx]


class FakeSeries:
    def __init__(self, values):
        self.values = list(values)
        self.iloc = FakeILoc(self.values)

    def tail(self, n):
        return FakeSeries(self.values[-n:])

    def max(self):
        return max(self.values) if self.values else 0.0


class FakeDF:
    columns = ["volume", "close"]

    def __init__(self, rows=60, volume=1.0):
        self.rows = rows
        self.volume = volume

    def __len__(self):
        return self.rows

    def __getitem__(self, key):
        if key == "volume":
            return FakeSeries([self.volume] * self.rows)
        raise KeyError(key)


class WeakDF(FakeDF):
    def __init__(self):
        super().__init__(rows=1, volume=0.0)


class FakeCoreLoop:
    def __init__(self):
        self.last_symbols = None
        self.fetch_results = {}

    def _fetch_df(self, broker, symbol):
        result = self.fetch_results.get(symbol)
        if isinstance(result, list):
            return result.pop(0)
        if result is not None:
            return result
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


def test_fetch_df_deadline_elapsed_preserves_selected_candidate_by_default(monkeypatch):
    monkeypatch.delenv("NIJA_PHASE3_FETCH_DEADLINE_SKIP_ENABLED", raising=False)
    module = SimpleNamespace(NijaCoreLoop=FakeCoreLoop, __name__="bot.nija_core_loop")
    assert patch._patch_core_loop_module(module) is True
    loop = module.NijaCoreLoop()
    loop._nija_phase3_deadline_ts_20260709an = time.monotonic() - 1.0

    assert loop._fetch_df(object(), "AAVE-USD") == {"symbol": "AAVE-USD"}


def test_fetch_df_deadline_hard_skip_can_be_enabled_without_cache(monkeypatch):
    monkeypatch.setenv("NIJA_PHASE3_FETCH_DEADLINE_SKIP_ENABLED", "true")
    module = SimpleNamespace(NijaCoreLoop=FakeCoreLoop, __name__="bot.nija_core_loop")
    assert patch._patch_core_loop_module(module) is True
    loop = module.NijaCoreLoop()
    loop._nija_phase3_deadline_ts_20260709an = time.monotonic() - 1.0

    assert loop._fetch_df(object(), "BTC-USD") is None


def test_same_cycle_cache_reuses_strong_df_when_late_fetch_is_weak(monkeypatch):
    monkeypatch.delenv("NIJA_PHASE3_FETCH_DEADLINE_SKIP_ENABLED", raising=False)
    module = SimpleNamespace(NijaCoreLoop=FakeCoreLoop, __name__="bot.nija_core_loop")
    assert patch._patch_core_loop_module(module) is True
    loop = module.NijaCoreLoop()
    strong = FakeDF(rows=60, volume=5.0)
    loop.fetch_results["AI16Z-USD"] = [strong, WeakDF()]
    loop._nija_phase3_market_data_cache_active_20260709an = True
    loop._nija_phase3_market_data_cache_20260709an = {}

    assert loop._fetch_df(object(), "AI16Z-USD") is strong
    assert loop._fetch_df(object(), "AI16Z-USD") is strong


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
