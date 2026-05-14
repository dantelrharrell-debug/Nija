"""
Tests for bot/core_strategy_mode.py
======================================

Covers:
- Symbol scope enforcement (BTC-USD / ETH-USD pass; others blocked)
- No-leverage clamp (position_size clamped to account_balance when active)
- Counter-trend blocking in trending regimes
- Risk-cap values exposed via get_core_mode_config()
- ATR multiplier for BTC/ETH
- Integration with market_filters.is_core_mode_symbol()
- Integration with ai_trade_confidence_engine counter-trend penalty
"""

import os
import sys
import importlib
import unittest

# Ensure bot directory is on the path so imports work from both repo root
# and from inside bot/tests/.
_bot_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _bot_dir not in sys.path:
    sys.path.insert(0, _bot_dir)


# ---------------------------------------------------------------------------
# Helper: reload core_strategy_mode with specific env flags
# ---------------------------------------------------------------------------

def _load_csm(core_mode: bool = False, no_leverage: bool = False):
    """Import (or reimport) core_strategy_mode with the given env flags."""
    os.environ["NIJA_CORE_STRATEGY_MODE"] = "true" if core_mode else "false"
    os.environ["NIJA_NO_LEVERAGE"]        = "true" if no_leverage else "false"

    import bot.core_strategy_mode as csm
    importlib.reload(csm)
    return csm


# ---------------------------------------------------------------------------
# Symbol scope tests
# ---------------------------------------------------------------------------

class TestSymbolScope(unittest.TestCase):

    def setUp(self):
        self.csm = _load_csm(core_mode=True)

    def tearDown(self):
        os.environ.pop("NIJA_CORE_STRATEGY_MODE", None)
        os.environ.pop("NIJA_NO_LEVERAGE", None)

    def test_btc_usd_allowed(self):
        self.assertTrue(self.csm.is_symbol_allowed("BTC-USD"))

    def test_eth_usd_allowed(self):
        self.assertTrue(self.csm.is_symbol_allowed("ETH-USD"))

    def test_sol_usd_blocked(self):
        self.assertFalse(self.csm.is_symbol_allowed("SOL-USD"))

    def test_doge_usd_blocked(self):
        self.assertFalse(self.csm.is_symbol_allowed("DOGE-USD"))

    def test_case_insensitive(self):
        """Symbol check must normalise to uppercase."""
        self.assertTrue(self.csm.is_symbol_allowed("btc-usd"))
        self.assertFalse(self.csm.is_symbol_allowed("sol-usd"))

    def test_all_symbols_pass_when_core_mode_off(self):
        csm_off = _load_csm(core_mode=False)
        for sym in ("SOL-USD", "DOGE-USD", "ADA-USD", "XRP-USD"):
            self.assertTrue(csm_off.is_symbol_allowed(sym))


# ---------------------------------------------------------------------------
# No-leverage clamp tests
# ---------------------------------------------------------------------------

class TestNoLeverageClamp(unittest.TestCase):

    def tearDown(self):
        os.environ.pop("NIJA_CORE_STRATEGY_MODE", None)
        os.environ.pop("NIJA_NO_LEVERAGE", None)

    def test_clamp_when_core_mode_active(self):
        csm = _load_csm(core_mode=True)
        result = csm.clamp_no_leverage(1_500.0, 1_000.0)
        self.assertAlmostEqual(result, 1_000.0)

    def test_clamp_when_no_leverage_flag(self):
        csm = _load_csm(core_mode=False, no_leverage=True)
        result = csm.clamp_no_leverage(2_000.0, 1_800.0)
        self.assertAlmostEqual(result, 1_800.0)

    def test_no_clamp_when_both_flags_off(self):
        csm = _load_csm(core_mode=False, no_leverage=False)
        result = csm.clamp_no_leverage(1_500.0, 1_000.0)
        self.assertAlmostEqual(result, 1_500.0)

    def test_no_clamp_when_position_within_balance(self):
        csm = _load_csm(core_mode=True)
        result = csm.clamp_no_leverage(800.0, 1_000.0)
        self.assertAlmostEqual(result, 800.0)

    def test_zero_balance_no_clamp(self):
        """Zero balance should not cause a division by zero or wrong clamp."""
        csm = _load_csm(core_mode=True)
        result = csm.clamp_no_leverage(500.0, 0.0)
        self.assertAlmostEqual(result, 500.0)


# ---------------------------------------------------------------------------
# Counter-trend blocking tests
# ---------------------------------------------------------------------------

class TestCounterTrendBlocked(unittest.TestCase):

    def setUp(self):
        self.csm = _load_csm(core_mode=True)

    def tearDown(self):
        os.environ.pop("NIJA_CORE_STRATEGY_MODE", None)
        os.environ.pop("NIJA_NO_LEVERAGE", None)

    # --- should block ---

    def test_long_overbought_in_strong_trend(self):
        blocked = self.csm.is_counter_trend_blocked("strong_trend", "long", 68.0)
        self.assertTrue(blocked)

    def test_short_oversold_in_strong_trend(self):
        blocked = self.csm.is_counter_trend_blocked("strong_trend", "short", 30.0)
        self.assertTrue(blocked)

    def test_long_overbought_in_expansion(self):
        blocked = self.csm.is_counter_trend_blocked("expansion", "long", 70.0)
        self.assertTrue(blocked)

    def test_case_normalisation(self):
        """Regime string 'Strong Trend' should normalise correctly."""
        blocked = self.csm.is_counter_trend_blocked("Strong Trend", "long", 70.0)
        self.assertTrue(blocked)

    # --- should allow ---

    def test_long_rsi_below_threshold_in_strong_trend(self):
        """RSI = 60 is below 65 — entry not considered counter-trend."""
        blocked = self.csm.is_counter_trend_blocked("strong_trend", "long", 60.0)
        self.assertFalse(blocked)

    def test_short_rsi_above_threshold_in_strong_trend(self):
        """RSI = 40 is above 35 — entry not considered counter-trend."""
        blocked = self.csm.is_counter_trend_blocked("strong_trend", "short", 40.0)
        self.assertFalse(blocked)

    def test_ranging_regime_never_blocked(self):
        """Mean-reversion in ranging — counter-trend gate must NOT fire."""
        blocked = self.csm.is_counter_trend_blocked("ranging", "long", 30.0)
        self.assertFalse(blocked)

    def test_consolidation_not_blocked(self):
        blocked = self.csm.is_counter_trend_blocked("consolidation", "short", 70.0)
        self.assertFalse(blocked)

    def test_core_mode_off_never_blocks(self):
        csm_off = _load_csm(core_mode=False)
        blocked = csm_off.is_counter_trend_blocked("strong_trend", "long", 90.0)
        self.assertFalse(blocked)


# ---------------------------------------------------------------------------
# Risk cap and config tests
# ---------------------------------------------------------------------------

class TestCoreModeConfig(unittest.TestCase):

    def tearDown(self):
        os.environ.pop("NIJA_CORE_STRATEGY_MODE", None)
        os.environ.pop("NIJA_NO_LEVERAGE", None)

    def test_risk_pct_tighter_in_core_mode(self):
        csm = _load_csm(core_mode=True)
        cfg = csm.get_core_mode_config()
        self.assertTrue(cfg.active)
        # 0.75% vs 1.5% default
        self.assertAlmostEqual(cfg.risk_pct, 0.0075)
        self.assertLess(cfg.risk_pct, 0.015)

    def test_daily_loss_tighter_in_core_mode(self):
        csm = _load_csm(core_mode=True)
        cfg = csm.get_core_mode_config()
        self.assertAlmostEqual(cfg.daily_loss_pct, 2.0)
        self.assertLess(cfg.daily_loss_pct, 3.0)  # below default

    def test_max_positions_enforced(self):
        csm = _load_csm(core_mode=True)
        cfg = csm.get_core_mode_config()
        self.assertEqual(cfg.max_positions, 3)

    def test_max_position_pct_tighter(self):
        csm = _load_csm(core_mode=True)
        cfg = csm.get_core_mode_config()
        self.assertAlmostEqual(cfg.max_position_pct, 0.10)
        self.assertLess(cfg.max_position_pct, 0.15)  # below default

    def test_atr_multiplier_set(self):
        csm = _load_csm(core_mode=True)
        cfg = csm.get_core_mode_config()
        self.assertAlmostEqual(cfg.atr_multiplier, 1.3)

    def test_no_leverage_implied_by_core_mode(self):
        csm = _load_csm(core_mode=True)
        cfg = csm.get_core_mode_config()
        self.assertTrue(cfg.no_leverage)

    def test_defaults_when_core_mode_off(self):
        csm = _load_csm(core_mode=False)
        cfg = csm.get_core_mode_config()
        self.assertFalse(cfg.active)
        self.assertEqual(cfg.allowed_symbols, frozenset())   # no restriction
        self.assertAlmostEqual(cfg.risk_pct, 0.015)
        self.assertAlmostEqual(cfg.daily_loss_pct, 3.0)
        self.assertEqual(cfg.max_positions, 0)
        self.assertAlmostEqual(cfg.atr_multiplier, 1.5)

    def test_standalone_no_leverage_activates_only_leverage_clamp(self):
        csm = _load_csm(core_mode=False, no_leverage=True)
        cfg = csm.get_core_mode_config()
        self.assertFalse(cfg.active)           # core mode is off
        self.assertTrue(cfg.no_leverage)       # but leverage clamped
        self.assertEqual(cfg.allowed_symbols, frozenset())


# ---------------------------------------------------------------------------
# market_filters.is_core_mode_symbol() integration
# ---------------------------------------------------------------------------

try:
    import pandas as _pd_check   # noqa: F401
    _HAS_PANDAS = True
except ImportError:
    _HAS_PANDAS = False

try:
    import numpy as _np_check    # noqa: F401
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False


@unittest.skipUnless(_HAS_PANDAS, "pandas not installed — skipping market_filters integration tests")
class TestMarketFiltersIntegration(unittest.TestCase):

    def tearDown(self):
        os.environ.pop("NIJA_CORE_STRATEGY_MODE", None)
        os.environ.pop("NIJA_NO_LEVERAGE", None)
        # Clear cached import of core_strategy_mode so next test gets a fresh read
        for mod_name in list(sys.modules.keys()):
            if "core_strategy_mode" in mod_name:
                del sys.modules[mod_name]

    def test_core_mode_symbol_btc_passes(self):
        _load_csm(core_mode=True)
        import bot.market_filters as mf
        importlib.reload(mf)
        self.assertTrue(mf.is_core_mode_symbol("BTC-USD"))

    def test_core_mode_symbol_eth_passes(self):
        _load_csm(core_mode=True)
        import bot.market_filters as mf
        importlib.reload(mf)
        self.assertTrue(mf.is_core_mode_symbol("ETH-USD"))

    def test_core_mode_symbol_sol_blocked(self):
        _load_csm(core_mode=True)
        import bot.market_filters as mf
        importlib.reload(mf)
        self.assertFalse(mf.is_core_mode_symbol("SOL-USD"))

    def test_core_mode_off_all_pass(self):
        _load_csm(core_mode=False)
        import bot.market_filters as mf
        importlib.reload(mf)
        for sym in ("SOL-USD", "DOGE-USD", "XRP-USD"):
            self.assertTrue(mf.is_core_mode_symbol(sym))


# ---------------------------------------------------------------------------
# ai_trade_confidence_engine counter-trend penalty integration
# ---------------------------------------------------------------------------

@unittest.skipUnless(
    _HAS_NUMPY and _HAS_PANDAS,
    "numpy/pandas not installed — skipping confidence engine integration tests",
)
class TestConfidenceEngineCoreMode(unittest.TestCase):
    """
    Verifies that the confidence engine applies the 0.30× score penalty for
    counter-trend entries in trending regimes when core mode is active.
    """

    def tearDown(self):
        os.environ.pop("NIJA_CORE_STRATEGY_MODE", None)
        os.environ.pop("NIJA_NO_LEVERAGE", None)
        for mod_name in list(sys.modules.keys()):
            if "core_strategy_mode" in mod_name or "ai_trade_confidence" in mod_name:
                del sys.modules[mod_name]

    def _make_df(self, n: int = 30):
        import numpy as np
        import pandas as pd
        np.random.seed(0)
        closes = 50_000 + np.cumsum(np.random.normal(0, 50, n))
        return pd.DataFrame({
            "open":   closes,
            "high":   closes * 1.001,
            "low":    closes * 0.999,
            "close":  closes,
            "volume": [1_000_000.0] * n,
        })

    def _base_indicators(self):
        return {
            "adx":              35.0,
            "rsi_14":           70.0,   # overbought — counter-trend long
            "rsi_9":            72.0,
            "atr":              200.0,
            "macd_histogram":   5.0,
            "ema_9":            50_200.0,
            "ema_21":           50_100.0,
            "ema_50":           50_000.0,
        }

    def test_score_penalised_for_counter_trend_in_core_mode(self):
        """Counter-trend long in strong_trend should receive 0.30× score penalty."""
        _load_csm(core_mode=True)

        import bot.ai_trade_confidence_engine as ace
        importlib.reload(ace)

        engine = ace.AITradeConfidenceEngine(
            confidence_threshold=ace.CONFIDENCE_THRESHOLD,
            use_regime_detector=False,
        )

        df = self._make_df()
        indicators = self._base_indicators()

        # Inject a strong-trend regime via ADX (fallback path uses ADX ≥ 30 → strong_trend)
        result_core = engine.evaluate(df, indicators, side="long", symbol="BTC-USD")

        # Score should be heavily penalised
        self.assertLess(result_core["score"], 40.0,
                        "Counter-trend entry in core mode should score < 40")

    def test_score_NOT_penalised_when_core_mode_off(self):
        """Same signal with core mode off must not receive the penalty."""
        _load_csm(core_mode=False)

        import bot.ai_trade_confidence_engine as ace
        importlib.reload(ace)

        engine = ace.AITradeConfidenceEngine(
            confidence_threshold=ace.CONFIDENCE_THRESHOLD,
            use_regime_detector=False,
        )

        df = self._make_df()
        indicators = self._base_indicators()
        result_off = engine.evaluate(df, indicators, side="long", symbol="BTC-USD")

        # Score should be unreduced (likely ≥ 40 without penalty)
        self.assertGreater(result_off["score"], 40.0,
                           "Without core mode penalty the score should be > 40")

    def test_no_penalty_in_ranging_regime(self):
        """Mean-reversion long in ranging regime must NOT be penalised."""
        _load_csm(core_mode=True)

        import bot.ai_trade_confidence_engine as ace
        importlib.reload(ace)

        engine = ace.AITradeConfidenceEngine(
            confidence_threshold=ace.CONFIDENCE_THRESHOLD,
            use_regime_detector=False,
        )

        df = self._make_df()
        # Low ADX → ranging regime (fallback path: ADX < 20 → ranging)
        indicators = self._base_indicators()
        indicators["adx"] = 10.0
        indicators["rsi_14"] = 30.0    # oversold long — mean-reversion
        indicators["rsi_9"]  = 28.0

        result = engine.evaluate(df, indicators, side="long", symbol="BTC-USD")
        # Should not be penalised (ranging regime is not in _STRONG_TREND_REGIMES)
        # The counter-trend block only fires in strong_trend / expansion / trending
        self.assertGreater(result["score"], 10.0,
                           "Ranging regime long should not be penalised")


if __name__ == "__main__":
    unittest.main()
