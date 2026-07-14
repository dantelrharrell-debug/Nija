from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any


PATCH_PATH = Path(__file__).resolve().parents[1] / "phase3_execution_handoff_repair_patch.py"
SPEC = importlib.util.spec_from_file_location("phase3_execution_handoff_repair_patch_test", PATCH_PATH)
assert SPEC is not None and SPEC.loader is not None
patch = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(patch)


class SyntheticLoop:
    def __init__(self, frame_size: int = 60) -> None:
        self.frame_size = frame_size
        self.fetch_calls = 0

    def _phase3_scan_and_enter(self, df: Any) -> str:
        if df is None or len(df) < 100:
            return "skip_before_execute_action"
        return "execute_action"

    def _fetch_df(self, broker: Any, symbol: str):
        self.fetch_calls += 1
        return list(range(self.frame_size))


def test_execution_threshold_matches_scoring_threshold() -> None:
    assert SyntheticLoop()._phase3_scan_and_enter(list(range(60))) == "skip_before_execute_action"

    assert patch._repair_phase3_threshold(SyntheticLoop) is True

    loop = SyntheticLoop()
    assert loop._phase3_scan_and_enter(list(range(49))) == "skip_before_execute_action"
    assert loop._phase3_scan_and_enter(list(range(50))) == "execute_action"
    assert loop._phase3_scan_and_enter(list(range(60))) == "execute_action"

    # The repair is idempotent when startup/import hooks revisit the class.
    assert patch._repair_phase3_threshold(SyntheticLoop) is True


def test_validated_frame_is_reused_during_same_cycle(monkeypatch) -> None:
    monkeypatch.setenv("NIJA_PHASE3_FRAME_CACHE_TTL_S", "60")
    assert patch._wrap_fetch_df_cache(SyntheticLoop) is True

    loop = SyntheticLoop(frame_size=60)
    broker = object()

    first = loop._fetch_df(broker, "BTC-USD")
    second = loop._fetch_df(broker, "BTC-USD")

    assert first is second
    assert len(second) == 60
    assert loop.fetch_calls == 1

    # Different symbols remain isolated.
    loop._fetch_df(broker, "ETH-USD")
    assert loop.fetch_calls == 2

    # The wrapper is idempotent too.
    assert patch._wrap_fetch_df_cache(SyntheticLoop) is True


def test_short_frame_is_not_cached(monkeypatch) -> None:
    monkeypatch.setenv("NIJA_PHASE3_FRAME_CACHE_TTL_S", "60")
    patch._wrap_fetch_df_cache(SyntheticLoop)

    loop = SyntheticLoop(frame_size=49)
    broker = object()

    assert len(loop._fetch_df(broker, "SOL-USD")) == 49
    assert len(loop._fetch_df(broker, "SOL-USD")) == 49
    assert loop.fetch_calls == 2
