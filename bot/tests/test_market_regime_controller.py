"""
Tests for bot/market_regime_controller.py
==========================================

Covers:
- RegimeMetrics dataclass
- MarketRegimeController.compute_metrics()
- MarketRegimeController.classify() — all three regimes
- MarketRegimeController.evaluate() convenience wrapper
- Regime transition logging (state change tracking)
- get_market_regime_controller() singleton helper
- RegimeControls.to_dict() serialisation
"""

import sys
import os
import unittest
import numpy as np
import pandas as pd

# Ensure the bot directory is on the path so imports work both from the repo
# root and from inside bot/tests/.
_bot_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _bot_dir)

try:
    from market_regime_controller import (
        MarketRegime,
        MarketRegimeController,
        RegimeControls,
        RegimeMetrics,
        TradePermission,
        get_market_regime_controller,
    )
except ImportError:
    from bot.market_regime_controller import (
        MarketRegime,
        MarketRegimeController,
        RegimeControls,
        RegimeMetrics,
        TradePermission,
        get_market_regime_controller,
    )


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_df(n: int = 30, base_price: float = 100.0, noise: float = 0.01) -> pd.DataFrame:
    """Return a synthetic OHLCV DataFrame."""
    np.random.seed(42)
    closes = base_price + np.cumsum(
        np.random.normal(0, base_price * noise, n)
    )
    highs  = closes + abs(np.random.normal(0, base_price * 0.005, n))
    lows   = closes - abs(np.random.normal(0, base_price * 0.005, n))
    return pd.DataFrame({
        "open":   closes,
        "high":   highs,
        "low":    lows,
        "close":  closes,
        "volume": np.ones(n) * 1_000_000,
    })


def _make_volatile_df(n: int = 30, base_price: float = 100.0) -> pd.DataFrame:
    """Return a highly volatile OHLCV DataFrame."""
    np.random.seed(7)
    closes = base_price + np.cumsum(
        np.random.normal(0, base_price * 0.06, n)   # 6 % std-dev per bar
    )
    highs  = closes * 1.02
    lows   = closes * 0.98
    return pd.DataFrame({
        "open":   closes,
        "high":   highs,
        "low":    lows,
        "close":  closes,
        "volume": np.ones(n) * 1_000_000,
    })


def _controller(**kwargs) -> MarketRegimeController:
    return MarketRegimeController(config=kwargs if kwargs else None)


# ---------------------------------------------------------------------------
# RegimeMetrics tests
# ---------------------------------------------------------------------------

class TestRegimeMetrics(unittest.TestCase):
    """Ensure RegimeMetrics is a plain dataclass with sane defaults."""

    def test_defaults(self):
        m = RegimeMetrics()
        self.assertEqual(m.volatility_pct, 0.0)
        self.assertEqual(m.trend_strength, 0.0)
        self.assertEqual(m.market_breadth, 0.5)
        self.assertEqual(m.liquidity_ratio, 1.0)

    def test_to_dict_keys(self):
        m = RegimeMetrics(volatility_pct=2.5, trend_strength=28.0)
        d = m.to_dict()
        for key in ("volatility_pct", "trend_strength", "market_breadth", "liquidity_ratio"):
            self.assertIn(key, d)

    def test_to_dict_values_rounded(self):
        m = RegimeMetrics(volatility_pct=1.23456789)
        d = m.to_dict()
        # Should be rounded to 4 decimal places
        self.assertAlmostEqual(d["volatility_pct"], 1.2346, places=3)


# ---------------------------------------------------------------------------
# RegimeControls tests
# ---------------------------------------------------------------------------

class TestRegimeControls(unittest.TestCase):

    def test_to_dict_has_all_fields(self):
        ctrl = RegimeControls(
            regime=MarketRegime.TRENDING,
            trade_permission=TradePermission.ALLOWED,
            position_size_multiplier=1.0,
            scan_frequency_seconds=150,
            reason="test",
        )
        d = ctrl.to_dict()
        for key in ("regime", "trade_permission", "position_size_multiplier",
                    "scan_frequency_seconds", "reason", "timestamp"):
            self.assertIn(key, d)
        self.assertEqual(d["regime"], "TRENDING")
        self.assertEqual(d["trade_permission"], "ALLOWED")


# ---------------------------------------------------------------------------
# MarketRegimeController — classify() tests
# ---------------------------------------------------------------------------

class TestClassify(unittest.TestCase):
    """Unit tests for the core classification logic."""

    def setUp(self):
        self.ctrl = _controller()

    def _classify(self, **kwargs) -> RegimeControls:
        m = RegimeMetrics(**kwargs)
        return self.ctrl.classify(m)

    # --- CHAOTIC ---

    def test_chaotic_extreme_volatility(self):
        """High volatility triggers CHAOTIC regardless of other metrics."""
        ctrl = self._classify(
            volatility_pct=10.0,    # >> 6 % threshold
            trend_strength=35.0,    # Strong ADX — would normally be TRENDING
            market_breadth=0.8,
            liquidity_ratio=2.0,
        )
        self.assertEqual(ctrl.regime, MarketRegime.CHAOTIC)
        self.assertEqual(ctrl.trade_permission, TradePermission.PAUSED)
        self.assertAlmostEqual(ctrl.position_size_multiplier, 0.10)

    def test_chaotic_thin_liquidity(self):
        """Thin liquidity (ratio < 0.5) triggers CHAOTIC."""
        ctrl = self._classify(
            volatility_pct=1.0,
            trend_strength=30.0,
            market_breadth=0.7,
            liquidity_ratio=0.1,   # << 0.5 threshold
        )
        self.assertEqual(ctrl.regime, MarketRegime.CHAOTIC)
        self.assertEqual(ctrl.trade_permission, TradePermission.PAUSED)

    def test_chaotic_scan_frequency_is_slower(self):
        ctrl = self._classify(volatility_pct=8.0)
        ranging_ctrl = self._classify(volatility_pct=0.5, trend_strength=10.0)
        # CHAOTIC scan should be at least as slow as RANGING
        self.assertGreaterEqual(
            ctrl.scan_frequency_seconds,
            ranging_ctrl.scan_frequency_seconds,
        )

    # --- TRENDING ---

    def test_trending_normal_conditions(self):
        ctrl = self._classify(
            volatility_pct=1.5,
            trend_strength=30.0,    # > 25 threshold
            market_breadth=0.70,    # > 0.55 threshold
            liquidity_ratio=2.0,
        )
        self.assertEqual(ctrl.regime, MarketRegime.TRENDING)
        self.assertEqual(ctrl.trade_permission, TradePermission.ALLOWED)
        self.assertAlmostEqual(ctrl.position_size_multiplier, 1.0)

    def test_trending_requires_sufficient_breadth(self):
        """Strong ADX alone is not enough — breadth must also be high."""
        ctrl = self._classify(
            volatility_pct=1.5,
            trend_strength=30.0,
            market_breadth=0.30,    # Low breadth → not TRENDING
        )
        self.assertNotEqual(ctrl.regime, MarketRegime.TRENDING)

    def test_trending_requires_sufficient_adx(self):
        """High breadth alone is not enough — ADX must be above threshold."""
        ctrl = self._classify(
            volatility_pct=1.5,
            trend_strength=15.0,    # Low ADX → not TRENDING
            market_breadth=0.80,
        )
        self.assertNotEqual(ctrl.regime, MarketRegime.TRENDING)

    # --- RANGING ---

    def test_ranging_low_adx(self):
        ctrl = self._classify(
            volatility_pct=1.0,
            trend_strength=10.0,    # Low ADX
            market_breadth=0.5,
            liquidity_ratio=1.5,
        )
        self.assertEqual(ctrl.regime, MarketRegime.RANGING)
        self.assertEqual(ctrl.trade_permission, TradePermission.ALLOWED)
        self.assertAlmostEqual(ctrl.position_size_multiplier, 0.5)

    def test_ranging_moderate_conditions(self):
        ctrl = self._classify(
            volatility_pct=2.0,
            trend_strength=22.0,    # Moderate ADX
            market_breadth=0.50,    # Neutral breadth
        )
        self.assertEqual(ctrl.regime, MarketRegime.RANGING)

    # --- Position size invariants ---

    def test_position_size_ordering(self):
        """TRENDING > RANGING > CHAOTIC position multipliers."""
        trending = self._classify(
            volatility_pct=1.0, trend_strength=30.0, market_breadth=0.7
        ).position_size_multiplier
        ranging = self._classify(
            volatility_pct=1.0, trend_strength=10.0
        ).position_size_multiplier
        chaotic = self._classify(volatility_pct=8.0).position_size_multiplier

        self.assertGreater(trending, ranging)
        self.assertGreater(ranging, chaotic)
        self.assertAlmostEqual(chaotic, 0.10)


# ---------------------------------------------------------------------------
# MarketRegimeController — compute_metrics() tests
# ---------------------------------------------------------------------------

class TestComputeMetrics(unittest.TestCase):

    def setUp(self):
        self.ctrl = _controller()
        self.df   = _make_df()

    def test_volatility_computed(self):
        metrics = self.ctrl.compute_metrics(
            df=self.df,
            indicators={"adx": 20.0},
        )
        self.assertGreater(metrics.volatility_pct, 0.0)

    def test_adx_from_scalar(self):
        metrics = self.ctrl.compute_metrics(
            df=self.df, indicators={"adx": 35.0}
        )
        self.assertAlmostEqual(metrics.trend_strength, 35.0)

    def test_adx_from_series(self):
        adx_series = pd.Series([15.0, 20.0, 28.0, 32.0])
        metrics = self.ctrl.compute_metrics(
            df=self.df, indicators={"adx": adx_series}
        )
        self.assertAlmostEqual(metrics.trend_strength, 32.0)

    def test_liquidity_ratio(self):
        metrics = self.ctrl.compute_metrics(
            df=self.df,
            indicators={},
            volume_24h=2_000_000,
            min_liquidity_volume=1_000_000,
        )
        self.assertAlmostEqual(metrics.liquidity_ratio, 2.0)

    def test_liquidity_ratio_zero_volume(self):
        metrics = self.ctrl.compute_metrics(
            df=self.df, indicators={}, volume_24h=0, min_liquidity_volume=1_000_000
        )
        self.assertAlmostEqual(metrics.liquidity_ratio, 0.0)

    def test_breadth_with_symbol_prices(self):
        # Use a left-skewed price list so most values are above the mean
        # (100 is the low outlier; 150-180 cluster above the mean of ~152)
        metrics = self.ctrl.compute_metrics(
            df=self.df,
            indicators={},
            symbol_prices=[100.0, 150.0, 160.0, 170.0, 180.0],
        )
        self.assertGreater(metrics.market_breadth, 0.5)

    def test_breadth_neutral_when_no_prices(self):
        short_df = _make_df(n=5)   # Fewer rows than ema_period
        metrics = self.ctrl.compute_metrics(
            df=short_df,
            indicators={},
            symbol_prices=None,
        )
        self.assertEqual(metrics.market_breadth, 0.5)

    def test_volatile_df_gives_high_volatility(self):
        vol_df  = _make_volatile_df()
        metrics = self.ctrl.compute_metrics(df=vol_df, indicators={})
        self.assertGreater(metrics.volatility_pct, 3.0)

    def test_metrics_history_grows(self):
        for _ in range(5):
            self.ctrl.compute_metrics(df=self.df, indicators={})
        self.assertGreaterEqual(len(self.ctrl._metrics_history), 5)


# ---------------------------------------------------------------------------
# MarketRegimeController — evaluate() integration test
# ---------------------------------------------------------------------------

class TestEvaluate(unittest.TestCase):

    def test_evaluate_returns_controls(self):
        ctrl = _controller()
        df   = _make_df()
        controls = ctrl.evaluate(
            df=df,
            indicators={"adx": 30.0},
            volume_24h=2_000_000,
            min_liquidity_volume=1_000_000,
            symbol_prices=[100.0, 101.0, 102.0, 103.0, 104.0],
        )
        self.assertIsInstance(controls, RegimeControls)
        self.assertIsInstance(controls.regime, MarketRegime)

    def test_evaluate_chaotic_on_volatile_data(self):
        ctrl    = _controller()
        vol_df  = _make_volatile_df()
        controls = ctrl.evaluate(df=vol_df, indicators={"adx": 5.0})
        self.assertEqual(controls.regime, MarketRegime.CHAOTIC)
        self.assertEqual(controls.trade_permission, TradePermission.PAUSED)


# ---------------------------------------------------------------------------
# Transition tracking
# ---------------------------------------------------------------------------

class TestRegimeTransition(unittest.TestCase):

    def test_transition_recorded(self):
        ctrl = _controller()
        # First call → RANGING
        m_ranging = RegimeMetrics(
            volatility_pct=1.0, trend_strength=10.0,
            market_breadth=0.4, liquidity_ratio=1.5
        )
        ctrl.classify(m_ranging)
        self.assertEqual(ctrl.current_controls.regime, MarketRegime.RANGING)

        # Second call → CHAOTIC
        m_chaotic = RegimeMetrics(volatility_pct=9.0)
        ctrl.classify(m_chaotic)
        self.assertEqual(ctrl.current_controls.regime, MarketRegime.CHAOTIC)

    def test_same_regime_no_transition(self):
        ctrl = _controller()
        m = RegimeMetrics(volatility_pct=1.0, trend_strength=10.0)
        ctrl.classify(m)
        first_ts = ctrl.current_controls.timestamp
        ctrl.classify(m)
        # Still RANGING; timestamp will differ (new object each call) but regime is same
        self.assertEqual(ctrl.current_controls.regime, MarketRegime.RANGING)


# ---------------------------------------------------------------------------
# get_status()
# ---------------------------------------------------------------------------

class TestGetStatus(unittest.TestCase):

    def test_status_before_classify(self):
        ctrl = _controller()
        status = ctrl.get_status()
        self.assertIsNone(status["regime"])

    def test_status_after_classify(self):
        ctrl = _controller()
        ctrl.classify(RegimeMetrics(volatility_pct=1.0, trend_strength=10.0))
        status = ctrl.get_status()
        self.assertEqual(status["regime"], "RANGING")
        self.assertIn("controls", status)


# ---------------------------------------------------------------------------
# Singleton helper
# ---------------------------------------------------------------------------

class TestSingleton(unittest.TestCase):

    def test_singleton_returns_same_instance(self):
        import importlib
        import market_regime_controller as mrc
        # Reset the singleton for test isolation
        mrc._controller_instance = None
        inst1 = get_market_regime_controller()
        inst2 = get_market_regime_controller()
        self.assertIs(inst1, inst2)
        # Restore
        mrc._controller_instance = None


# ---------------------------------------------------------------------------
# Custom threshold configuration
# ---------------------------------------------------------------------------

class TestCustomConfig(unittest.TestCase):

    def test_custom_chaotic_threshold(self):
        """Custom threshold — CHAOTIC should trigger at 4 % vol instead of 6 %."""
        ctrl = _controller(chaotic_volatility_pct=4.0)
        m = RegimeMetrics(volatility_pct=5.0, trend_strength=30.0, market_breadth=0.8)
        controls = ctrl.classify(m)
        self.assertEqual(controls.regime, MarketRegime.CHAOTIC)

    def test_custom_trending_adx_threshold(self):
        """Lower trending ADX threshold → regime becomes TRENDING at ADX=20."""
        ctrl = _controller(trending_adx_threshold=18.0, trending_breadth_min=0.4)
        m = RegimeMetrics(volatility_pct=1.0, trend_strength=20.0, market_breadth=0.6)
        controls = ctrl.classify(m)
        self.assertEqual(controls.regime, MarketRegime.TRENDING)

    def test_custom_size_multipliers(self):
        ctrl = _controller(
            trending_size_multiplier=1.5,
            ranging_size_multiplier=0.25,
            chaotic_size_multiplier=0.0,
        )
        trending = ctrl.classify(
            RegimeMetrics(volatility_pct=0.5, trend_strength=30.0, market_breadth=0.7)
        )
        ranging = ctrl.classify(
            RegimeMetrics(volatility_pct=0.5, trend_strength=10.0)
        )
        self.assertAlmostEqual(trending.position_size_multiplier, 1.5)
        self.assertAlmostEqual(ranging.position_size_multiplier, 0.25)


if __name__ == "__main__":
    unittest.main()
