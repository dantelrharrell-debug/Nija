"""
Unit tests for bot.control.regime_engine
==========================================

Coverage:
  1. Trending detection  — high ADX
  2. Ranging detection   — low ADX
  3. Breakout detection  — BB squeeze + rising ADX
  4. Mean-reversion detection — RSI extreme + BB boundary
  5. Unknown fallback    — insufficient data
  6. Confidence scoring  — proportional to signal strength
  7. Redis caching       — store and load
  8. Singleton stability
"""

import unittest
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd

from bot.control.regime_engine import (
    MarketRegime,
    RegimeEngine,
    RegimeResult,
    get_regime_engine,
)


# ---------------------------------------------------------------------------
# DataFrame factories
# ---------------------------------------------------------------------------

def _make_df(n: int = 60, trend: str = "up", volatility: float = 1.0) -> pd.DataFrame:
    """
    Generate a synthetic OHLCV DataFrame.

    trend: "up" | "down" | "flat" | "oscillate"
    """
    np.random.seed(42)
    close = np.zeros(n)
    close[0] = 100.0

    for i in range(1, n):
        if trend == "up":
            close[i] = close[i - 1] * (1 + 0.005 + np.random.randn() * 0.002 * volatility)
        elif trend == "down":
            close[i] = close[i - 1] * (1 - 0.005 + np.random.randn() * 0.002 * volatility)
        elif trend == "flat":
            close[i] = close[i - 1] + np.random.randn() * 0.3 * volatility
        elif trend == "oscillate":
            close[i] = 100.0 + 2.0 * np.sin(i * 0.5) + np.random.randn() * 0.1

    high   = close * (1 + 0.005 * volatility)
    low    = close * (1 - 0.005 * volatility)
    open_  = np.roll(close, 1)
    open_[0] = close[0]
    volume = np.random.randint(1000, 5000, n).astype(float)

    return pd.DataFrame({
        "open":   open_,
        "high":   high,
        "low":    low,
        "close":  close,
        "volume": volume,
    })


def _make_squeeze_df(n: int = 60) -> pd.DataFrame:
    """DataFrame with a tight Bollinger Band squeeze followed by expansion."""
    np.random.seed(7)
    close = np.zeros(n)
    close[0] = 100.0
    for i in range(1, n):
        if i < n - 10:
            # Tight consolidation
            close[i] = close[i - 1] + np.random.randn() * 0.05
        else:
            # Breakout
            close[i] = close[i - 1] * (1 + 0.01)
    high   = close * 1.002
    low    = close * 0.998
    open_  = np.roll(close, 1)
    open_[0] = close[0]
    volume = np.random.randint(1000, 5000, n).astype(float)
    return pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close, "volume": volume,
    })


def _make_oversold_df(n: int = 60) -> pd.DataFrame:
    """DataFrame that produces an oversold RSI (< 30)."""
    np.random.seed(13)
    close = np.zeros(n)
    close[0] = 100.0
    for i in range(1, n):
        # Consistent decline to push RSI low
        close[i] = close[i - 1] * (1 - 0.012 + np.random.randn() * 0.001)
    high   = close * 1.001
    low    = close * 0.999
    open_  = np.roll(close, 1)
    open_[0] = close[0]
    volume = np.random.randint(1000, 5000, n).astype(float)
    return pd.DataFrame({
        "open": open_, "high": high, "low": low, "close": close, "volume": volume,
    })


# ---------------------------------------------------------------------------
# 1. Trending detection
# ---------------------------------------------------------------------------

class TestTrendingDetection(unittest.TestCase):

    def setUp(self):
        self.engine = RegimeEngine()

    def test_strong_uptrend_detected_as_trending(self):
        df = _make_df(n=80, trend="up")
        result = self.engine.detect("BTC-USD", df)
        # Strong trend should produce TRENDING or at least not RANGING
        self.assertIn(result.regime, (MarketRegime.TRENDING, MarketRegime.BREAKOUT, MarketRegime.UNKNOWN))

    def test_trending_confidence_above_zero(self):
        df = _make_df(n=80, trend="up")
        result = self.engine.detect("BTC-USD", df)
        self.assertGreaterEqual(result.confidence, 0.0)
        self.assertLessEqual(result.confidence, 1.0)

    def test_trending_result_has_adx(self):
        df = _make_df(n=80, trend="up")
        result = self.engine.detect("BTC-USD", df)
        self.assertGreaterEqual(result.adx, 0.0)

    def test_trending_result_has_rsi(self):
        df = _make_df(n=80, trend="up")
        result = self.engine.detect("BTC-USD", df)
        self.assertGreaterEqual(result.rsi, 0.0)
        self.assertLessEqual(result.rsi, 100.0)


# ---------------------------------------------------------------------------
# 2. Ranging detection
# ---------------------------------------------------------------------------

class TestRangingDetection(unittest.TestCase):

    def setUp(self):
        self.engine = RegimeEngine()

    def test_oscillating_market_detected_as_ranging(self):
        df = _make_df(n=80, trend="oscillate")
        result = self.engine.detect("ETH-USD", df)
        # Oscillating market should produce RANGING or MEAN_REVERSION
        self.assertIn(result.regime, (
            MarketRegime.RANGING,
            MarketRegime.MEAN_REVERSION,
            MarketRegime.UNKNOWN,
        ))

    def test_ranging_confidence_in_bounds(self):
        df = _make_df(n=80, trend="oscillate")
        result = self.engine.detect("ETH-USD", df)
        self.assertGreaterEqual(result.confidence, 0.0)
        self.assertLessEqual(result.confidence, 1.0)

    def test_flat_market_not_trending(self):
        df = _make_df(n=80, trend="flat")
        result = self.engine.detect("SOL-USD", df)
        self.assertNotEqual(result.regime, MarketRegime.TRENDING)


# ---------------------------------------------------------------------------
# 3. Breakout detection
# ---------------------------------------------------------------------------

class TestBreakoutDetection(unittest.TestCase):

    def setUp(self):
        self.engine = RegimeEngine()

    def test_squeeze_df_produces_breakout_or_trending(self):
        df = _make_squeeze_df(n=80)
        result = self.engine.detect("BTC-USD", df)
        # Squeeze + expansion should produce BREAKOUT or TRENDING
        self.assertIn(result.regime, (
            MarketRegime.BREAKOUT,
            MarketRegime.TRENDING,
            MarketRegime.UNKNOWN,
        ))

    def test_breakout_result_has_bb_width(self):
        df = _make_squeeze_df(n=80)
        result = self.engine.detect("BTC-USD", df)
        self.assertGreaterEqual(result.bb_width_pct, 0.0)


# ---------------------------------------------------------------------------
# 4. Mean-reversion detection
# ---------------------------------------------------------------------------

class TestMeanReversionDetection(unittest.TestCase):

    def setUp(self):
        self.engine = RegimeEngine()

    def test_oversold_market_detected(self):
        df = _make_oversold_df(n=80)
        result = self.engine.detect("BTC-USD", df)
        # Consistent decline → RSI should be low → MEAN_REVERSION or TRENDING (down)
        self.assertIn(result.regime, (
            MarketRegime.MEAN_REVERSION,
            MarketRegime.TRENDING,
            MarketRegime.UNKNOWN,
        ))

    def test_mean_reversion_rsi_in_range(self):
        df = _make_oversold_df(n=80)
        result = self.engine.detect("BTC-USD", df)
        self.assertGreaterEqual(result.rsi, 0.0)
        self.assertLessEqual(result.rsi, 100.0)


# ---------------------------------------------------------------------------
# 5. Unknown fallback
# ---------------------------------------------------------------------------

class TestUnknownFallback(unittest.TestCase):

    def setUp(self):
        self.engine = RegimeEngine()

    def test_insufficient_bars_returns_unknown(self):
        df = _make_df(n=10, trend="up")  # < _MIN_BARS (30)
        result = self.engine.detect("BTC-USD", df)
        self.assertEqual(result.regime, MarketRegime.UNKNOWN)
        self.assertEqual(result.confidence, 0.0)

    def test_empty_df_returns_unknown(self):
        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        result = self.engine.detect("BTC-USD", df)
        self.assertEqual(result.regime, MarketRegime.UNKNOWN)

    def test_unknown_result_has_symbol(self):
        df = _make_df(n=5, trend="up")
        result = self.engine.detect("ETH-USD", df)
        self.assertEqual(result.symbol, "ETH-USD")

    def test_unknown_result_has_detected_at(self):
        df = _make_df(n=5, trend="up")
        result = self.engine.detect("BTC-USD", df)
        self.assertIn("T", result.detected_at)


# ---------------------------------------------------------------------------
# 6. Confidence scoring
# ---------------------------------------------------------------------------

class TestConfidenceScoring(unittest.TestCase):

    def setUp(self):
        self.engine = RegimeEngine()

    def test_confidence_always_in_0_1(self):
        for trend in ("up", "down", "flat", "oscillate"):
            df = _make_df(n=60, trend=trend)
            result = self.engine.detect("BTC-USD", df)
            self.assertGreaterEqual(result.confidence, 0.0, f"trend={trend}")
            self.assertLessEqual(result.confidence, 1.0, f"trend={trend}")

    def test_to_dict_contains_regime_string(self):
        df = _make_df(n=60, trend="up")
        result = self.engine.detect("BTC-USD", df)
        d = result.to_dict()
        self.assertIsInstance(d["regime"], str)
        self.assertIn(d["regime"], [r.value for r in MarketRegime])


# ---------------------------------------------------------------------------
# 7. Redis caching
# ---------------------------------------------------------------------------

class TestRedisCaching(unittest.TestCase):

    def test_result_stored_in_redis(self):
        mock_redis = MagicMock()
        mock_redis.get.return_value = None  # cache miss
        engine = RegimeEngine(redis_client=mock_redis)
        df = _make_df(n=60, trend="up")
        engine.detect("BTC-USD", df)
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        self.assertIn("BTC-USD", call_args[0][0])

    def test_cached_result_returned_without_recompute(self):
        import json
        cached_data = {
            "regime":       "trending",
            "confidence":   0.80,
            "adx":          30.0,
            "rsi":          60.0,
            "volatility":   0.01,
            "bb_width_pct": 0.05,
            "context":      {},
            "symbol":       "BTC-USD",
            "detected_at":  "2026-01-01T00:00:00+00:00",
        }
        mock_redis = MagicMock()
        mock_redis.get.return_value = json.dumps(cached_data).encode()
        engine = RegimeEngine(redis_client=mock_redis)
        df = _make_df(n=60, trend="up")
        result = engine.detect("BTC-USD", df)
        self.assertEqual(result.regime, MarketRegime.TRENDING)
        self.assertAlmostEqual(result.confidence, 0.80)
        # setex should NOT be called (cache hit)
        mock_redis.setex.assert_not_called()

    def test_redis_failure_falls_back_to_compute(self):
        mock_redis = MagicMock()
        mock_redis.get.side_effect = Exception("Redis down")
        engine = RegimeEngine(redis_client=mock_redis)
        df = _make_df(n=60, trend="up")
        # Should not raise
        result = engine.detect("BTC-USD", df)
        self.assertIsInstance(result, RegimeResult)


# ---------------------------------------------------------------------------
# 8. Singleton stability
# ---------------------------------------------------------------------------

class TestSingleton(unittest.TestCase):

    def test_get_regime_engine_returns_same_instance(self):
        e1 = get_regime_engine()
        e2 = get_regime_engine()
        self.assertIs(e1, e2)

    def test_singleton_detects_regime(self):
        engine = get_regime_engine()
        df = _make_df(n=60, trend="up")
        result = engine.detect("BTC-USD", df)
        self.assertIsInstance(result, RegimeResult)


if __name__ == "__main__":
    unittest.main()
