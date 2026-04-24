"""
Tests for bot/regime_aware_memory.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Allow imports from bot/
sys.path.insert(0, str(Path(__file__).parent.parent))

from regime_aware_memory import (
    DEFAULT_EMA_ALPHA,
    DEFAULT_MIN_TRADES,
    DEFAULT_WINDOW,
    SCALE_DOWN_THRESHOLD,
    SCALE_UP_THRESHOLD,
    Recommendation,
    RegimeAwareMemory,
    RegimeStats,
    get_regime_aware_memory,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fresh(window: int = 20, min_trades: int = 5) -> RegimeAwareMemory:
    """Return a fresh (non-singleton) RegimeAwareMemory for each test."""
    return RegimeAwareMemory(window=window, min_trades=min_trades)


def _feed_wins(mem: RegimeAwareMemory, regime: str, n: int, pnl: float = 100.0) -> None:
    for _ in range(n):
        mem.record_trade(regime=regime, pnl_usd=pnl, is_win=True)


def _feed_losses(mem: RegimeAwareMemory, regime: str, n: int, pnl: float = -50.0) -> None:
    for _ in range(n):
        mem.record_trade(regime=regime, pnl_usd=pnl, is_win=False)


# ---------------------------------------------------------------------------
# Basic recording
# ---------------------------------------------------------------------------


class TestRecordTrade:
    def test_increments_total_trades(self) -> None:
        mem = _fresh()
        mem.record_trade("BULL", 100.0, True)
        mem.record_trade("BULL", -20.0, False)
        stats = mem.get_stats("BULL")
        assert stats.total_trades == 2

    def test_window_capped(self) -> None:
        mem = _fresh(window=5)
        for i in range(10):
            mem.record_trade("BULL", float(i), True)
        stats = mem.get_stats("BULL")
        assert stats.window_trades == 5  # rolling window

    def test_separate_regime_buckets(self) -> None:
        mem = _fresh()
        _feed_wins(mem, "BULL", 3)
        _feed_losses(mem, "BEAR", 3)
        assert mem.get_stats("BULL").total_trades == 3
        assert mem.get_stats("BEAR").total_trades == 3

    def test_auto_registers_unknown_regime(self) -> None:
        mem = _fresh()
        mem.record_trade("TRENDING", 50.0, True)
        stats = mem.get_stats("TRENDING")
        assert stats.total_trades == 1

    def test_case_insensitive(self) -> None:
        mem = _fresh()
        mem.record_trade("bull", 100.0, True)
        mem.record_trade("Bull", 100.0, True)
        assert mem.get_stats("BULL").total_trades == 2


# ---------------------------------------------------------------------------
# EMA score — min_trades gate
# ---------------------------------------------------------------------------


class TestEmaScore:
    def test_score_stays_neutral_below_min_trades(self) -> None:
        mem = _fresh(min_trades=10)
        # Feed fewer trades than the minimum
        _feed_wins(mem, "BULL", 5)
        # EMA is never updated → stays at initial 50.0
        assert mem.get_stats("BULL").score == 50.0

    def test_score_updates_after_min_trades(self) -> None:
        mem = _fresh(min_trades=5)
        _feed_wins(mem, "BULL", 8, pnl=200.0)
        stats = mem.get_stats("BULL")
        # After consistently profitable trades the score should be above 50
        assert stats.score > 50.0


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------


class TestRecommendation:
    def test_neutral_below_min_trades(self) -> None:
        mem = _fresh(min_trades=10)
        _feed_wins(mem, "BULL", 5)
        assert mem.get_recommendation("BULL") == Recommendation.NEUTRAL.value

    def test_scale_up_after_strong_wins(self) -> None:
        mem = _fresh(min_trades=5)
        # 20 big winners → score should exceed SCALE_UP_THRESHOLD
        _feed_wins(mem, "BULL", 20, pnl=200.0)
        assert mem.get_recommendation("BULL") == Recommendation.SCALE_UP.value

    def test_scale_down_after_consistent_losses(self) -> None:
        mem = _fresh(min_trades=5)
        # 20 pure losses → score should fall below SCALE_DOWN_THRESHOLD
        _feed_losses(mem, "BEAR", 20, pnl=-100.0)
        assert mem.get_recommendation("BEAR") == Recommendation.SCALE_DOWN.value

    def test_neutral_mixed_performance(self) -> None:
        mem = _fresh(min_trades=5)
        # Alternate wins and losses with balanced PnL
        for _ in range(10):
            mem.record_trade("SIDEWAYS", 10.0, True)
            mem.record_trade("SIDEWAYS", -9.0, False)
        rec = mem.get_recommendation("SIDEWAYS")
        # Might be NEUTRAL or SCALE_UP with slightly positive edge; just not SCALE_DOWN
        assert rec in (Recommendation.NEUTRAL.value, Recommendation.SCALE_UP.value)


# ---------------------------------------------------------------------------
# Quality multiplier
# ---------------------------------------------------------------------------


class TestQualityMultiplier:
    def test_scale_up_multiplier(self) -> None:
        mem = _fresh(min_trades=5)
        _feed_wins(mem, "BULL", 20, pnl=200.0)
        assert mem.get_quality_multiplier("BULL") == pytest.approx(1.20)

    def test_scale_down_multiplier(self) -> None:
        mem = _fresh(min_trades=5)
        _feed_losses(mem, "BEAR", 20, pnl=-100.0)
        assert mem.get_quality_multiplier("BEAR") == pytest.approx(0.70)

    def test_neutral_multiplier(self) -> None:
        mem = _fresh(min_trades=10)
        # Below min_trades → NEUTRAL
        _feed_wins(mem, "SIDEWAYS", 3)
        assert mem.get_quality_multiplier("SIDEWAYS") == pytest.approx(1.00)


# ---------------------------------------------------------------------------
# get_all_stats
# ---------------------------------------------------------------------------


class TestGetAllStats:
    def test_all_default_regimes_present(self) -> None:
        mem = _fresh()
        all_stats = mem.get_all_stats()
        for regime in ("BULL", "BEAR", "SIDEWAYS"):
            assert regime in all_stats

    def test_returns_regime_stats_type(self) -> None:
        mem = _fresh()
        for stats in mem.get_all_stats().values():
            assert isinstance(stats, RegimeStats)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------


class TestSingleton:
    def test_singleton_returns_same_instance(self) -> None:
        a = get_regime_aware_memory(reset=True)
        b = get_regime_aware_memory()
        assert a is b

    def test_reset_creates_new_instance(self) -> None:
        a = get_regime_aware_memory(reset=True)
        b = get_regime_aware_memory(reset=True)
        assert a is not b


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------


class TestReport:
    def test_report_contains_all_regimes(self) -> None:
        mem = _fresh()
        report = mem.get_report()
        for regime in ("BULL", "BEAR", "SIDEWAYS"):
            assert regime in report
