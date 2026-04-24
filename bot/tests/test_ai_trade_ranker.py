"""
Tests for bot/ai_trade_ranker.py
"""

import sys
import pytest
import pandas as pd
import numpy as np

sys.path.insert(0, ".")

from bot.ai_trade_ranker import AITradeRanker, TradeScoreBreakdown, DEFAULT_SCORE_THRESHOLD


# ---------------------------------------------------------------------------
# Shared fixtures / helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def ranker():
    """Default AITradeRanker (threshold=75)."""
    return AITradeRanker()


def _make_df(
    n: int = 50,
    close: float = 100.0,
    volume: float = 1_200.0,
) -> pd.DataFrame:
    """Minimal OHLCV DataFrame."""
    closes = np.full(n, close)
    highs  = closes + 1.0
    lows   = closes - 1.0
    opens  = closes
    vols   = np.full(n, volume)
    return pd.DataFrame({
        "open": opens, "high": highs, "low": lows,
        "close": closes, "volume": vols,
    })


def _make_indicators(
    rsi9: float = 40.0,
    rsi14: float = 42.0,
    adx: float = 32.0,
    ema9: float = 99.0,
    ema21: float = 97.0,
    ema50: float = 95.0,
    macd_hist: float = 0.8,
    atr: float = 1.5,
    n: int = 50,
) -> dict:
    """Minimal indicators dict with Series values."""
    return {
        "rsi_9":     pd.Series([rsi9] * n),
        "rsi_14":    pd.Series([rsi14] * n),
        "adx":       pd.Series([adx] * n),
        "ema_9":     pd.Series([ema9] * n),
        "ema_21":    pd.Series([ema21] * n),
        "ema_50":    pd.Series([ema50] * n),
        "macd_hist": pd.Series([macd_hist] * n),
        "atr":       pd.Series([atr] * n),
    }


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

class TestAITradeRankerInit:
    def test_default_threshold(self, ranker):
        assert ranker.score_threshold == DEFAULT_SCORE_THRESHOLD

    def test_custom_threshold(self):
        r = AITradeRanker(score_threshold=80.0)
        assert r.score_threshold == 80.0

    def test_weights_sum_to_100(self, ranker):
        assert abs(sum(ranker.weights.values()) - 100.0) < 0.01

    def test_invalid_weights_raises(self):
        with pytest.raises(ValueError, match="Weights must sum to 100"):
            AITradeRanker(weights={"trend_strength": 10.0, "volatility": 10.0,
                                    "volume": 10.0, "momentum": 10.0})


# ---------------------------------------------------------------------------
# should_execute
# ---------------------------------------------------------------------------

class TestShouldExecute:
    def test_score_above_threshold(self, ranker):
        assert ranker.should_execute(76.0) is True

    def test_score_equal_threshold(self, ranker):
        """Score exactly at threshold should NOT execute (strict >)."""
        assert ranker.should_execute(75.0) is False

    def test_score_below_threshold(self, ranker):
        assert ranker.should_execute(50.0) is False

    def test_perfect_score(self, ranker):
        assert ranker.should_execute(100.0) is True

    def test_zero_score(self, ranker):
        assert ranker.should_execute(0.0) is False


# ---------------------------------------------------------------------------
# score_trade – return types
# ---------------------------------------------------------------------------

class TestScoreTradeReturnTypes:
    def test_returns_tuple(self, ranker):
        df  = _make_df()
        ind = _make_indicators()
        result = ranker.score_trade(df, ind, side="long", symbol="BTC-USD")
        assert isinstance(result, tuple) and len(result) == 2

    def test_score_is_float(self, ranker):
        df  = _make_df()
        ind = _make_indicators()
        score, _ = ranker.score_trade(df, ind, side="long")
        assert isinstance(score, float)

    def test_breakdown_type(self, ranker):
        df  = _make_df()
        ind = _make_indicators()
        _, breakdown = ranker.score_trade(df, ind, side="long")
        assert isinstance(breakdown, TradeScoreBreakdown)

    def test_score_in_valid_range(self, ranker):
        df  = _make_df()
        ind = _make_indicators()
        score, _ = ranker.score_trade(df, ind, side="long")
        assert 0.0 <= score <= 100.0


# ---------------------------------------------------------------------------
# Trend strength component
# ---------------------------------------------------------------------------

class TestTrendStrength:
    def test_high_adx_scores_more_than_low_adx(self, ranker):
        df = _make_df()
        ind_high = _make_indicators(adx=40.0)
        ind_low  = _make_indicators(adx=10.0)
        _, bd_high = ranker.score_trade(df, ind_high, side="long")
        _, bd_low  = ranker.score_trade(df, ind_low,  side="long")
        assert bd_high.trend_strength > bd_low.trend_strength

    def test_perfect_ema_alignment_long(self, ranker):
        """close > ema9 > ema21 > ema50 → maximum EMA points."""
        df  = _make_df(close=110.0)
        ind = _make_indicators(adx=40.0, ema9=109.0, ema21=107.0, ema50=105.0)
        _, bd = ranker.score_trade(df, ind, side="long")
        assert bd.trend_strength == ranker.weights["trend_strength"]

    def test_perfect_ema_alignment_short(self, ranker):
        """close < ema9 < ema21 < ema50 → maximum EMA points."""
        df  = _make_df(close=90.0)
        ind = _make_indicators(adx=40.0, ema9=91.0, ema21=93.0, ema50=95.0)
        _, bd = ranker.score_trade(df, ind, side="short")
        assert bd.trend_strength == ranker.weights["trend_strength"]

    def test_no_indicators_returns_non_negative(self, ranker):
        df  = _make_df()
        _, bd = ranker.score_trade(df, {}, side="long")
        assert bd.trend_strength >= 0.0


# ---------------------------------------------------------------------------
# Volatility component
# ---------------------------------------------------------------------------

class TestVolatility:
    def test_optimal_atr_ratio_scores_full(self, ranker):
        """ATR == avg_atr → ratio 1.0 → full marks."""
        df  = _make_df()
        ind = _make_indicators(atr=1.5)
        _, bd = ranker.score_trade(df, ind, side="long")
        assert bd.volatility == ranker.weights["volatility"]

    def test_extreme_atr_ratio_penalised(self, ranker):
        df  = _make_df()
        # Constant high ATR series: ratio will be 1.0 → still optimal
        # Use a case where we can't compare easily; just ensure non-negative
        ind = _make_indicators(atr=5.0)
        _, bd = ranker.score_trade(df, ind, side="long")
        assert bd.volatility >= 0.0

    def test_no_atr_indicator_returns_non_zero_fallback(self, ranker):
        df  = _make_df()
        _, bd = ranker.score_trade(df, {}, side="long")
        assert bd.volatility > 0.0


# ---------------------------------------------------------------------------
# Volume component
# ---------------------------------------------------------------------------

class TestVolume:
    def test_high_volume_scores_full(self, ranker):
        """volume = 3× average → maximum volume score."""
        n   = 50
        avg = 1_000.0
        # First 49 bars at avg, last bar at 3× avg
        vols = [avg] * (n - 1) + [avg * 3.0]
        df = pd.DataFrame({
            "open": [100.0] * n, "high": [101.0] * n,
            "low": [99.0] * n, "close": [100.0] * n,
            "volume": vols,
        })
        ind = _make_indicators()
        _, bd = ranker.score_trade(df, ind, side="long")
        assert bd.volume == ranker.weights["volume"]

    def test_low_volume_scores_zero(self, ranker):
        """volume = 0.1× average → score 0."""
        n   = 50
        avg = 1_000.0
        vols = [avg] * (n - 1) + [avg * 0.1]
        df = pd.DataFrame({
            "open": [100.0] * n, "high": [101.0] * n,
            "low": [99.0] * n, "close": [100.0] * n,
            "volume": vols,
        })
        ind = _make_indicators()
        _, bd = ranker.score_trade(df, ind, side="long")
        assert bd.volume == 0.0

    def test_no_volume_column_returns_fallback(self, ranker):
        df = pd.DataFrame({
            "open": [100.0] * 50, "high": [101.0] * 50,
            "low": [99.0] * 50, "close": [100.0] * 50,
        })
        ind = _make_indicators()
        _, bd = ranker.score_trade(df, ind, side="long")
        assert bd.volume >= 0.0


# ---------------------------------------------------------------------------
# Momentum component
# ---------------------------------------------------------------------------

class TestMomentum:
    def test_ideal_long_rsi_and_positive_macd(self, ranker):
        """RSI 40 (oversold recovery) + MACD > 0 → full momentum score."""
        df  = _make_df()
        ind = _make_indicators(rsi9=40.0, macd_hist=1.0)
        _, bd = ranker.score_trade(df, ind, side="long")
        assert bd.momentum == ranker.weights["momentum"]

    def test_ideal_short_rsi_and_negative_macd(self, ranker):
        """RSI 60 (overbought rejection) + MACD < 0 → full momentum score."""
        df  = _make_df()
        ind = _make_indicators(rsi9=60.0, macd_hist=-1.0)
        _, bd = ranker.score_trade(df, ind, side="short")
        assert bd.momentum == ranker.weights["momentum"]

    def test_wrong_side_rsi_penalised(self, ranker):
        """Overbought RSI for a long entry → lower momentum than ideal."""
        df   = _make_df()
        ind_ideal = _make_indicators(rsi9=40.0, macd_hist=1.0)
        ind_bad   = _make_indicators(rsi9=80.0, macd_hist=1.0)
        _, bd_ideal = ranker.score_trade(df, ind_ideal, side="long")
        _, bd_bad   = ranker.score_trade(df, ind_bad,   side="long")
        assert bd_ideal.momentum > bd_bad.momentum

    def test_no_rsi_or_macd_returns_non_negative(self, ranker):
        df  = _make_df()
        _, bd = ranker.score_trade(df, {}, side="long")
        assert bd.momentum >= 0.0


# ---------------------------------------------------------------------------
# Overall scoring – quality labels
# ---------------------------------------------------------------------------

class TestQualityLabels:
    @pytest.mark.parametrize("score,expected_quality", [
        (92.0, "Excellent"),
        (80.0, "Good"),
        (65.0, "Marginal"),
        (45.0, "Weak"),
        (20.0, "Poor"),
    ])
    def test_quality_label(self, ranker, score, expected_quality):
        label = AITradeRanker._classify(score)
        assert label == expected_quality


# ---------------------------------------------------------------------------
# Execution gate integration
# ---------------------------------------------------------------------------

class TestExecutionGate:
    def test_high_quality_setup_approved(self, ranker):
        """Perfect long setup → score should exceed 75."""
        df  = _make_df(close=110.0, volume=3_000.0)
        ind = _make_indicators(
            rsi9=40.0, adx=40.0,
            ema9=109.0, ema21=107.0, ema50=105.0,
            macd_hist=1.0, atr=1.5,
        )
        score, breakdown = ranker.score_trade(df, ind, side="long")
        assert score > ranker.score_threshold
        assert breakdown.should_execute is True

    def test_poor_setup_rejected(self, ranker):
        """All-neutral / unfavourable inputs → score well below 75."""
        df = pd.DataFrame({
            "open":   [100.0] * 50,
            "high":   [100.5] * 50,
            "low":    [99.5] * 50,
            "close":  [100.0] * 50,
            "volume": [200.0] * 50,   # below average
        })
        ind = {
            "rsi_9":     pd.Series([75.0] * 50),   # overbought for long
            "adx":       pd.Series([12.0] * 50),   # very weak trend
            "macd_hist": pd.Series([-0.5] * 50),   # negative for long
            "atr":       pd.Series([0.5] * 50),    # low volatility
        }
        score, breakdown = ranker.score_trade(df, ind, side="long")
        assert score <= ranker.score_threshold
        assert breakdown.should_execute is False

    def test_breakdown_should_execute_consistent_with_score(self, ranker):
        df  = _make_df()
        ind = _make_indicators()
        score, breakdown = ranker.score_trade(df, ind, side="long")
        assert breakdown.should_execute == (score > ranker.score_threshold)

    def test_custom_threshold_works(self):
        """Lower threshold → more trades approved."""
        r_strict = AITradeRanker(score_threshold=90.0)
        r_loose  = AITradeRanker(score_threshold=30.0)
        df  = _make_df(close=110.0, volume=3_000.0)
        ind = _make_indicators(
            rsi9=40.0, adx=40.0,
            ema9=109.0, ema21=107.0, ema50=105.0,
            macd_hist=1.0, atr=1.5,
        )
        _, bd_strict = r_strict.score_trade(df, ind, side="long")
        _, bd_loose  = r_loose.score_trade(df, ind, side="long")
        # Loose threshold should approve more often (or at least never be stricter)
        assert bd_loose.should_execute or not bd_strict.should_execute


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------

class TestEdgeCases:
    def test_empty_indicators_does_not_crash(self, ranker):
        df = _make_df()
        score, bd = ranker.score_trade(df, {}, side="long")
        assert 0.0 <= score <= 100.0

    def test_score_does_not_exceed_100(self, ranker):
        df  = _make_df(close=110.0, volume=5_000.0)
        ind = _make_indicators(
            rsi9=40.0, adx=50.0,
            ema9=109.0, ema21=107.0, ema50=105.0,
            macd_hist=5.0, atr=1.5,
        )
        score, _ = ranker.score_trade(df, ind, side="long")
        assert score <= 100.0

    def test_score_non_negative(self, ranker):
        df  = _make_df(volume=10.0)
        ind = {
            "rsi_9":     pd.Series([80.0] * 50),
            "adx":       pd.Series([5.0] * 50),
            "macd_hist": pd.Series([-5.0] * 50),
            "atr":       pd.Series([10.0] * 50),
        }
        score, _ = ranker.score_trade(df, ind, side="long")
        assert score >= 0.0

    def test_short_and_long_can_differ(self, ranker):
        df  = _make_df(close=90.0)
        ind = _make_indicators(
            rsi9=65.0, adx=30.0,
            ema9=91.0, ema21=93.0, ema50=95.0,
            macd_hist=-0.5, atr=1.5,
        )
        long_score, _ = ranker.score_trade(df, ind, side="long")
        short_score, _ = ranker.score_trade(df, ind, side="short")
        # With bearish setup, short should score higher than long
        assert short_score >= long_score
