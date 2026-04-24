"""
Tests for bot/rl_validation_engine.py
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from rl_validation_engine import (
    TradeRecord,
    RLValidationEngine,
    ValidationStatus,
    ValidationReport,
    WindowMetrics,
    get_rl_validation_engine,
    DEFAULT_WINDOW_SIZE,
)


def _make_trade(
    trade_id: str = "T001",
    strategy: str = "ApexTrend",
    regime: str = "trending",
    pnl_usd: float = 50.0,
    return_pct: float = 0.01,
    is_win: bool = True,
    rl_reward: float = 0.5,
) -> TradeRecord:
    return TradeRecord(
        trade_id=trade_id,
        strategy=strategy,
        regime=regime,
        pnl_usd=pnl_usd,
        return_pct=return_pct,
        is_win=is_win,
        rl_action=0,
        rl_reward=rl_reward,
    )


def _generate_trades(n: int, is_win: bool = True, regime: str = "trending") -> list:
    return [
        _make_trade(
            trade_id=f"T{i:04d}",
            pnl_usd=50.0 if is_win else -30.0,
            return_pct=0.01 if is_win else -0.006,
            is_win=is_win,
            regime=regime,
        )
        for i in range(n)
    ]


class TestRLValidationEngine:
    @pytest.fixture
    def engine(self):
        return RLValidationEngine(window_size=10, min_windows=2)

    def test_insufficient_data_initially(self, engine):
        report = engine.validate()
        assert report.status == ValidationStatus.INSUFFICIENT_DATA

    def test_insufficient_data_one_window(self, engine):
        engine.record_trades(_generate_trades(10))
        report = engine.validate()
        assert report.status == ValidationStatus.INSUFFICIENT_DATA

    def test_stable_after_enough_windows(self, engine):
        # Feed 20 trades → 2 complete windows with 50 % win rate (above min 45%)
        trades = _generate_trades(10, is_win=True) + _generate_trades(10, is_win=False)
        engine.record_trades(trades)
        report = engine.validate()
        assert report.status in (
            ValidationStatus.LEARNING,
            ValidationStatus.STABLE,
            ValidationStatus.DEGRADING,
        )
        assert report.num_windows == 2

    def test_degrading_when_win_rate_too_low(self):
        engine = RLValidationEngine(window_size=5, min_windows=2, min_win_rate=0.60)
        # Only 20% win rate
        trades = _generate_trades(3, is_win=False) + _generate_trades(2, is_win=True)
        trades += _generate_trades(3, is_win=False) + _generate_trades(2, is_win=True)
        engine.record_trades(trades)
        report = engine.validate()
        assert report.status == ValidationStatus.DEGRADING

    def test_learning_when_scores_improve(self):
        engine = RLValidationEngine(window_size=5, min_windows=2, improvement_threshold=0.0)
        # Improve win rate in second window
        window1 = [
            _make_trade(trade_id=f"W1T{i}", is_win=(i % 3 != 0), pnl_usd=30, return_pct=0.01, rl_reward=0.3)
            for i in range(5)
        ]
        window2 = [
            _make_trade(trade_id=f"W2T{i}", is_win=True, pnl_usd=60, return_pct=0.02, rl_reward=0.8)
            for i in range(5)
        ]
        engine.record_trades(window1 + window2)
        report = engine.validate()
        assert report.status == ValidationStatus.LEARNING

    def test_get_latest_window_none_before_data(self, engine):
        assert engine.get_latest_window() is None

    def test_get_latest_window_after_first_window(self, engine):
        engine.record_trades(_generate_trades(10))
        w = engine.get_latest_window()
        assert isinstance(w, WindowMetrics)
        assert w.window_id == 0

    def test_trade_count_increments(self, engine):
        assert engine.get_trade_count() == 0
        engine.record_trade(_make_trade())
        assert engine.get_trade_count() == 1

    def test_window_count_increments(self, engine):
        assert engine.get_window_count() == 0
        engine.record_trades(_generate_trades(10))
        assert engine.get_window_count() == 1

    def test_reset_clears_state(self, engine):
        engine.record_trades(_generate_trades(10))
        engine.reset()
        assert engine.get_trade_count() == 0
        assert engine.get_window_count() == 0

    def test_report_contains_window_metrics(self, engine):
        trades = _generate_trades(10) + _generate_trades(10)
        engine.record_trades(trades)
        report = engine.validate()
        assert len(report.window_metrics) == 2

    def test_singleton(self):
        a = get_rl_validation_engine()
        b = get_rl_validation_engine()
        assert a is b
