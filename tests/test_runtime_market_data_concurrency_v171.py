from __future__ import annotations

import time
from types import SimpleNamespace

from bot import phase3_scan_stall_guard_patch as guard


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


def test_bounded_prefetch_populates_cache_concurrently(monkeypatch):
    monkeypatch.setenv("NIJA_PHASE3_PREFETCH_WORKERS", "4")
    monkeypatch.setenv("NIJA_MAX_OHLC_WORKERS", "8")
    owner = SimpleNamespace()
    cache = {}
    calls = []

    def fetch_fn(_owner, _broker, symbol):
        calls.append(symbol)
        time.sleep(0.02)
        return FakeDF()

    deadline = time.monotonic() + 1.0
    submitted, cached = guard._bounded_prefetch(
        owner,
        object(),
        [f"S{i}" for i in range(8)],
        fetch_fn,
        cache,
        deadline,
    )

    assert submitted == 8
    assert cached == 8
    assert len(cache) == 8
    assert len(calls) == 8


def test_bounded_prefetch_respects_existing_deadline(monkeypatch):
    monkeypatch.setenv("NIJA_PHASE3_PREFETCH_WORKERS", "4")
    owner = SimpleNamespace()
    cache = {}

    def slow_fetch(_owner, _broker, _symbol):
        time.sleep(0.20)
        return FakeDF()

    started = time.monotonic()
    deadline = started + 0.08
    submitted, _ = guard._bounded_prefetch(
        owner,
        object(),
        [f"S{i}" for i in range(20)],
        slow_fetch,
        cache,
        deadline,
    )
    elapsed = time.monotonic() - started

    assert submitted > 0
    assert elapsed < 0.18


def test_prefetch_cache_is_consumed_without_second_fetch(monkeypatch):
    monkeypatch.setenv("NIJA_PHASE3_PREFETCH_ENABLED", "true")
    monkeypatch.setenv("NIJA_PHASE3_SCAN_DEADLINE_S", "5")

    class FakeCoreLoop:
        def __init__(self):
            self.fetch_calls = 0

        def _fetch_df(self, broker, symbol):
            self.fetch_calls += 1
            return FakeDF()

        def _phase3_scan_and_enter(self, broker, snapshot, symbols, available_slots, *args, **kwargs):
            for symbol in symbols:
                assert self._fetch_df(broker, symbol) is not None
            return (0, 0, len(symbols), {})

    module = SimpleNamespace(NijaCoreLoop=FakeCoreLoop, __name__="bot.nija_core_loop")
    assert guard._patch_core_loop_module(module) is True
    loop = module.NijaCoreLoop()

    symbols = ["BTC-USD", "ETH-USD", "SOL-USD"]
    result = loop._phase3_scan_and_enter(object(), object(), symbols, 1)

    assert result[2] == 3
    assert loop.fetch_calls == 3
    assert getattr(module.NijaCoreLoop._phase3_scan_and_enter, guard._PREFETCH_PATCH_ATTR, False)
    assert getattr(module.NijaCoreLoop._fetch_df, guard._PREFETCH_PATCH_ATTR, False)
