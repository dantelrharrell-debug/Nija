"""
Tests for bot/portfolio_alpha_allocator.py
==========================================

Covers:
- Core institutional formula with compounding examples from the spec
- ATR volatility filter (skip below minimum threshold)
- 200 EMA trend filter (reduce size / block when price < EMA)
- BTC market regime filter (pause altcoins on BTC volatility spike)
- Combined filter stack (multipliers chain correctly)
- Floor / cap clamping
- Edge cases (invalid inputs, zero stop distance)
- Convenience wrapper function
"""

import unittest

try:
    from bot.portfolio_alpha_allocator import (
        PortfolioAlphaAllocator,
        PortfolioAlphaConfig,
        AllocationResult,
        FilterResult,
        allocate_alpha_position,
        DEFAULT_RISK_PCT,
        DEFAULT_MIN_ATR_THRESHOLD,
        DEFAULT_TREND_MULTIPLIER,
        DEFAULT_BTC_SPIKE_THRESHOLD,
        BTC_SYMBOLS,
    )
except ImportError:
    from portfolio_alpha_allocator import (
        PortfolioAlphaAllocator,
        PortfolioAlphaConfig,
        AllocationResult,
        FilterResult,
        allocate_alpha_position,
        DEFAULT_RISK_PCT,
        DEFAULT_MIN_ATR_THRESHOLD,
        DEFAULT_TREND_MULTIPLIER,
        DEFAULT_BTC_SPIKE_THRESHOLD,
        BTC_SYMBOLS,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _allocator(
    risk_pct: float = 0.02,
    min_atr_threshold: float = DEFAULT_MIN_ATR_THRESHOLD,
    trend_multiplier: float = DEFAULT_TREND_MULTIPLIER,
    btc_spike_threshold: float = DEFAULT_BTC_SPIKE_THRESHOLD,
    min_position_usd: float = 1.0,
    max_position_pct: float = 1.0,   # generous cap for most tests
) -> PortfolioAlphaAllocator:
    cfg = PortfolioAlphaConfig(
        risk_pct=risk_pct,
        min_atr_threshold=min_atr_threshold,
        trend_filter_multiplier=trend_multiplier,
        btc_spike_threshold=btc_spike_threshold,
        min_position_usd=min_position_usd,
        max_position_pct=max_position_pct,
    )
    return PortfolioAlphaAllocator(cfg)


# ---------------------------------------------------------------------------
# Core formula & compounding
# ---------------------------------------------------------------------------

class TestCoreFormula(unittest.TestCase):
    """Institutional formula: position_size = (portfolio_value × risk_pct) / stop_distance."""

    def setUp(self):
        self.engine = _allocator(risk_pct=0.02)

    def test_spec_example_portfolio_500(self):
        """
        Spec example: Portfolio $500, risk 2 %, stop 5 %.
        risk_per_trade = $10; position_size = $10 / 0.05 = $200.
        """
        result = self.engine.calculate_position_size(
            portfolio_value=500.0,
            entry_price=100.0,
            stop_price=95.0,  # 5 % below entry
        )
        self.assertTrue(result.valid)
        self.assertAlmostEqual(result.risk_per_trade_usd, 10.0, places=2)
        self.assertAlmostEqual(result.stop_distance_pct, 0.05, places=4)
        self.assertAlmostEqual(result.position_size_usd, 200.0, places=2)

    def test_spec_example_portfolio_2000(self):
        """
        Spec example: Portfolio $2 000, risk 2 %, stop 5 %.
        risk_per_trade = $40; position_size = $40 / 0.05 = $800.
        Position size grows 4× as portfolio grows 4× — compounding in action.
        """
        result = self.engine.calculate_position_size(
            portfolio_value=2_000.0,
            entry_price=100.0,
            stop_price=95.0,
        )
        self.assertTrue(result.valid)
        self.assertAlmostEqual(result.risk_per_trade_usd, 40.0, places=2)
        self.assertAlmostEqual(result.position_size_usd, 800.0, places=2)

    def test_compounding_position_scales_with_portfolio(self):
        """Position size doubles when portfolio doubles (same % risk and same stop)."""
        r1 = self.engine.calculate_position_size(1_000.0, 100.0, 90.0)
        r2 = self.engine.calculate_position_size(2_000.0, 100.0, 90.0)
        self.assertAlmostEqual(r2.position_size_usd, r1.position_size_usd * 2, places=2)

    def test_stop_distance_symmetric(self):
        """Stop distance is |entry - stop| / entry regardless of direction."""
        r_long = self.engine.calculate_position_size(1_000.0, 100.0, 90.0)   # long stop
        r_short = self.engine.calculate_position_size(1_000.0, 100.0, 110.0)  # short stop
        self.assertAlmostEqual(r_long.stop_distance_pct, r_short.stop_distance_pct, places=4)

    def test_institutional_1pct_risk_10k_portfolio(self):
        """Standard institutional example: 1 % risk, $10 000, 5 % stop → $2 000 position."""
        engine = _allocator(risk_pct=0.01)
        result = engine.calculate_position_size(10_000.0, 100.0, 95.0)
        self.assertTrue(result.valid)
        self.assertAlmostEqual(result.risk_per_trade_usd, 100.0, places=2)
        self.assertAlmostEqual(result.position_size_usd, 2_000.0, places=2)

    def test_valid_flag_set_on_success(self):
        result = self.engine.calculate_position_size(1_000.0, 50.0, 45.0)
        self.assertTrue(result.valid)
        self.assertEqual(result.error, "")


# ---------------------------------------------------------------------------
# ATR Volatility Filter
# ---------------------------------------------------------------------------

class TestATRFilter(unittest.TestCase):
    """ATR volatility filter: skip trade when ATR < min_atr_threshold."""

    def setUp(self):
        # min_atr = 0.5 %; anything below skips the trade
        self.engine = _allocator(min_atr_threshold=0.005)

    def test_skip_when_atr_below_minimum(self):
        """ATR = 0.3 % < 0.5 % threshold → trade blocked."""
        result = self.engine.calculate_position_size(
            portfolio_value=1_000.0,
            entry_price=100.0,
            stop_price=95.0,
            atr_pct=0.003,  # 0.3 %
        )
        self.assertTrue(result.valid)    # inputs OK
        self.assertFalse(result.atr_filter.approved)
        self.assertEqual(result.position_size_usd, 0.0)
        self.assertIn("ATR", result.error)

    def test_allow_when_atr_equals_minimum(self):
        """ATR exactly at threshold is permitted (boundary condition)."""
        result = self.engine.calculate_position_size(
            portfolio_value=1_000.0,
            entry_price=100.0,
            stop_price=95.0,
            atr_pct=0.005,  # exactly at threshold
        )
        self.assertTrue(result.valid)
        self.assertTrue(result.atr_filter.approved)
        self.assertGreater(result.position_size_usd, 0.0)

    def test_allow_when_atr_above_minimum(self):
        """ATR = 1.2 % > 0.5 % threshold → full size approved."""
        result = self.engine.calculate_position_size(
            portfolio_value=1_000.0,
            entry_price=100.0,
            stop_price=95.0,
            atr_pct=0.012,  # 1.2 %
        )
        self.assertTrue(result.valid)
        self.assertTrue(result.atr_filter.approved)
        self.assertAlmostEqual(result.atr_filter.size_multiplier, 1.0)

    def test_bypassed_when_no_atr_data(self):
        """Without ATR data the filter is a no-op and trade is allowed."""
        result = self.engine.calculate_position_size(
            portfolio_value=1_000.0,
            entry_price=100.0,
            stop_price=95.0,
            atr_pct=None,
        )
        self.assertTrue(result.valid)
        self.assertTrue(result.atr_filter.approved)
        self.assertGreater(result.position_size_usd, 0.0)


# ---------------------------------------------------------------------------
# Trend Filter (200 EMA)
# ---------------------------------------------------------------------------

class TestTrendFilter(unittest.TestCase):
    """200 EMA trend filter: reduce position size when price < EMA."""

    def setUp(self):
        # trend_multiplier=0.5 → halve size when below EMA
        self.engine = _allocator(risk_pct=0.02, trend_multiplier=0.5)

    def test_full_size_when_price_above_ema(self):
        """Price above 200 EMA → uptrend, full position size."""
        result = self.engine.calculate_position_size(
            portfolio_value=1_000.0,
            entry_price=110.0,
            stop_price=104.5,  # 5 % stop
            ema_200=100.0,
        )
        self.assertTrue(result.valid)
        self.assertTrue(result.trend_filter.approved)
        self.assertAlmostEqual(result.trend_filter.size_multiplier, 1.0)
        # risk=$20, stop=5 %, size=$400
        self.assertAlmostEqual(result.position_size_usd, 400.0, places=2)

    def test_halved_size_when_price_below_ema(self):
        """Price below 200 EMA → position halved (multiplier=0.5)."""
        result = self.engine.calculate_position_size(
            portfolio_value=1_000.0,
            entry_price=90.0,
            stop_price=85.5,  # 5 % stop
            ema_200=100.0,
        )
        self.assertTrue(result.valid)
        self.assertTrue(result.trend_filter.approved)   # allowed, just reduced
        self.assertAlmostEqual(result.trend_filter.size_multiplier, 0.5)
        # raw size = $20 / 0.05 = $400; × 0.5 = $200
        self.assertAlmostEqual(result.position_size_usd, 200.0, places=2)

    def test_blocked_when_multiplier_zero_and_price_below_ema(self):
        """trend_multiplier=0 → block trade entirely when price < EMA."""
        engine = _allocator(risk_pct=0.02, trend_multiplier=0.0)
        result = engine.calculate_position_size(
            portfolio_value=1_000.0,
            entry_price=90.0,
            stop_price=85.5,
            ema_200=100.0,
        )
        self.assertTrue(result.valid)
        self.assertFalse(result.trend_filter.approved)
        self.assertEqual(result.position_size_usd, 0.0)

    def test_bypassed_when_no_ema_data(self):
        """Without EMA data, trend filter is bypassed and trade allowed."""
        result = self.engine.calculate_position_size(
            portfolio_value=1_000.0,
            entry_price=100.0,
            stop_price=95.0,
            ema_200=None,
        )
        self.assertTrue(result.valid)
        self.assertTrue(result.trend_filter.approved)
        self.assertGreater(result.position_size_usd, 0.0)


# ---------------------------------------------------------------------------
# Market Regime Filter (BTC volatility spike)
# ---------------------------------------------------------------------------

class TestMarketRegimeFilter(unittest.TestCase):
    """BTC volatility spike filter: pause altcoin trading when BTC ATR spikes."""

    def setUp(self):
        # spike threshold = 4 %
        self.engine = _allocator(btc_spike_threshold=0.04)

    def test_altcoin_blocked_on_btc_spike(self):
        """BTC ATR 5 % > 4 % threshold → altcoin trade paused."""
        result = self.engine.calculate_position_size(
            portfolio_value=1_000.0,
            entry_price=100.0,
            stop_price=95.0,
            symbol="ETH-USD",
            btc_atr_pct=0.05,   # 5 % — spike
        )
        self.assertTrue(result.valid)
        self.assertFalse(result.regime_filter.approved)
        self.assertEqual(result.position_size_usd, 0.0)
        self.assertIn("Regime", result.error)

    def test_altcoin_allowed_below_spike_threshold(self):
        """BTC ATR 2 % < 4 % threshold → altcoin trade proceeds normally."""
        result = self.engine.calculate_position_size(
            portfolio_value=1_000.0,
            entry_price=100.0,
            stop_price=95.0,
            symbol="ETH-USD",
            btc_atr_pct=0.02,   # 2 % — normal
        )
        self.assertTrue(result.valid)
        self.assertTrue(result.regime_filter.approved)
        self.assertGreater(result.position_size_usd, 0.0)

    def test_btc_symbol_not_subject_to_regime_filter(self):
        """BTC-USD is never blocked by the BTC regime filter."""
        result = self.engine.calculate_position_size(
            portfolio_value=1_000.0,
            entry_price=50_000.0,
            stop_price=47_500.0,
            symbol="BTC-USD",
            btc_atr_pct=0.10,   # extreme spike — but this IS BTC
        )
        self.assertTrue(result.valid)
        self.assertTrue(result.regime_filter.approved)
        self.assertGreater(result.position_size_usd, 0.0)

    def test_all_btc_symbol_variants_exempt(self):
        """All known BTC symbols bypass the regime filter."""
        for sym in ["BTC-USD", "BTC-USDT", "BTCUSD", "WBTC-USD"]:
            with self.subTest(symbol=sym):
                result = self.engine.calculate_position_size(
                    portfolio_value=1_000.0,
                    entry_price=50_000.0,
                    stop_price=47_500.0,
                    symbol=sym,
                    btc_atr_pct=0.10,
                )
                self.assertTrue(result.regime_filter.approved, f"{sym} should be exempt")

    def test_bypassed_when_no_btc_atr_data(self):
        """Without BTC ATR data the filter is bypassed and trade is allowed."""
        result = self.engine.calculate_position_size(
            portfolio_value=1_000.0,
            entry_price=100.0,
            stop_price=95.0,
            symbol="SOL-USD",
            btc_atr_pct=None,
        )
        self.assertTrue(result.valid)
        self.assertTrue(result.regime_filter.approved)
        self.assertGreater(result.position_size_usd, 0.0)

    def test_bypassed_when_no_symbol(self):
        """Without a symbol the filter is bypassed (no context to classify)."""
        result = self.engine.calculate_position_size(
            portfolio_value=1_000.0,
            entry_price=100.0,
            stop_price=95.0,
            symbol="",
            btc_atr_pct=0.10,
        )
        self.assertTrue(result.valid)
        self.assertGreater(result.position_size_usd, 0.0)


# ---------------------------------------------------------------------------
# Combined filter stack
# ---------------------------------------------------------------------------

class TestCombinedFilters(unittest.TestCase):
    """
    Verify that multiple filters chain correctly.
    - ATR filter (size × 1.0) + Trend filter (size × 0.5) → combined × 0.5
    - Any blocking filter stops the trade regardless of others
    """

    def setUp(self):
        self.engine = _allocator(
            risk_pct=0.02,
            min_atr_threshold=0.005,
            trend_multiplier=0.5,
            btc_spike_threshold=0.04,
        )

    def test_all_filters_pass_full_size(self):
        """All three filters passing → no multiplier reduction."""
        result = self.engine.calculate_position_size(
            portfolio_value=1_000.0,
            entry_price=110.0,
            stop_price=104.5,  # 5 % stop
            atr_pct=0.012,
            ema_200=100.0,
            symbol="ETH-USD",
            btc_atr_pct=0.02,
        )
        self.assertTrue(result.valid)
        self.assertAlmostEqual(result.effective_multiplier, 1.0)
        # $20 risk / 5 % stop = $400
        self.assertAlmostEqual(result.position_size_usd, 400.0, places=2)

    def test_atr_ok_trend_below_ema_halves_size(self):
        """ATR OK + price below EMA → size halved."""
        result = self.engine.calculate_position_size(
            portfolio_value=1_000.0,
            entry_price=90.0,
            stop_price=85.5,  # 5 % stop
            atr_pct=0.012,
            ema_200=100.0,
            symbol="ETH-USD",
            btc_atr_pct=0.02,
        )
        self.assertTrue(result.valid)
        self.assertAlmostEqual(result.effective_multiplier, 0.5)
        # $20 / 0.05 = $400 × 0.5 = $200
        self.assertAlmostEqual(result.position_size_usd, 200.0, places=2)

    def test_atr_too_low_blocks_despite_other_filters_ok(self):
        """Choppy ATR blocks trade even when trend and regime are fine."""
        result = self.engine.calculate_position_size(
            portfolio_value=1_000.0,
            entry_price=110.0,
            stop_price=104.5,
            atr_pct=0.002,    # below 0.5 % threshold
            ema_200=100.0,
            symbol="ETH-USD",
            btc_atr_pct=0.02,
        )
        self.assertTrue(result.valid)
        self.assertEqual(result.position_size_usd, 0.0)
        self.assertFalse(result.atr_filter.approved)

    def test_btc_spike_blocks_alt_despite_other_filters_ok(self):
        """BTC spike blocks altcoin trade even when ATR and trend are fine."""
        result = self.engine.calculate_position_size(
            portfolio_value=1_000.0,
            entry_price=110.0,
            stop_price=104.5,
            atr_pct=0.012,
            ema_200=100.0,
            symbol="SOL-USD",
            btc_atr_pct=0.08,  # extreme BTC spike
        )
        self.assertTrue(result.valid)
        self.assertEqual(result.position_size_usd, 0.0)
        self.assertFalse(result.regime_filter.approved)


# ---------------------------------------------------------------------------
# Clamping
# ---------------------------------------------------------------------------

class TestPositionClamping(unittest.TestCase):
    """Floor and cap constraints on position size."""

    def test_floor_applied_when_size_too_small(self):
        """Very wide stop + small portfolio → size raised to floor."""
        engine = _allocator(risk_pct=0.01, min_position_usd=20.0, max_position_pct=1.0)
        # risk=$1, stop=50 % → raw=$2 < floor=$20
        result = engine.calculate_position_size(100.0, 100.0, 50.0)
        self.assertEqual(result.position_size_usd, 20.0)
        self.assertTrue(result.clamped)
        self.assertIn("floor", result.clamp_reason)

    def test_cap_applied_when_size_too_large(self):
        """Tiny stop + large portfolio → size capped at max_position_pct."""
        # max position = 10 % of $10 000 = $1 000
        engine = _allocator(risk_pct=0.01, min_position_usd=1.0, max_position_pct=0.10)
        # risk=$100, stop=0.1 % → raw=$100 000 → cap=$1 000
        result = engine.calculate_position_size(10_000.0, 100.0, 99.9)
        self.assertEqual(result.position_size_usd, 1_000.0)
        self.assertTrue(result.clamped)
        self.assertIn("cap", result.clamp_reason)

    def test_no_clamping_within_range(self):
        """Size within [floor, cap] → no clamping."""
        engine = _allocator(risk_pct=0.02, min_position_usd=1.0, max_position_pct=1.0)
        result = engine.calculate_position_size(1_000.0, 100.0, 95.0)
        self.assertFalse(result.clamped)
        self.assertEqual(result.clamp_reason, "")


# ---------------------------------------------------------------------------
# Invalid input handling
# ---------------------------------------------------------------------------

class TestInvalidInputs(unittest.TestCase):
    """Engine returns valid=False with a descriptive error for bad inputs."""

    def setUp(self):
        self.engine = _allocator()

    def _assert_invalid(self, result, substring=""):
        self.assertFalse(result.valid)
        self.assertEqual(result.position_size_usd, 0.0)
        if substring:
            self.assertIn(substring, result.error)

    def test_zero_portfolio_value(self):
        result = self.engine.calculate_position_size(0.0, 100.0, 95.0)
        self._assert_invalid(result, "portfolio_value")

    def test_negative_portfolio_value(self):
        result = self.engine.calculate_position_size(-500.0, 100.0, 95.0)
        self._assert_invalid(result, "portfolio_value")

    def test_zero_entry_price(self):
        result = self.engine.calculate_position_size(1_000.0, 0.0, 95.0)
        self._assert_invalid(result, "entry_price")

    def test_zero_stop_price(self):
        result = self.engine.calculate_position_size(1_000.0, 100.0, 0.0)
        self._assert_invalid(result, "stop_price")

    def test_stop_equals_entry(self):
        result = self.engine.calculate_position_size(1_000.0, 100.0, 100.0)
        self._assert_invalid(result, "stop_price")


# ---------------------------------------------------------------------------
# AllocationResult.to_dict
# ---------------------------------------------------------------------------

class TestToDict(unittest.TestCase):
    """to_dict() produces the expected key set."""

    def test_keys_present_on_valid_result(self):
        engine = _allocator()
        result = engine.calculate_position_size(1_000.0, 100.0, 95.0)
        d = result.to_dict()
        required_keys = {
            "valid", "position_size_usd", "risk_per_trade_usd",
            "stop_distance_pct", "risk_pct_used", "portfolio_value",
            "filters", "effective_multiplier", "clamped", "clamp_reason", "error",
        }
        self.assertTrue(required_keys.issubset(d.keys()))

    def test_filter_sub_keys(self):
        engine = _allocator()
        result = engine.calculate_position_size(
            1_000.0, 100.0, 95.0, atr_pct=0.012, ema_200=98.0,
            symbol="ETH-USD", btc_atr_pct=0.02,
        )
        d = result.to_dict()
        for key in ("atr", "trend_200ema", "btc_regime"):
            self.assertIn(key, d["filters"])
            self.assertIn("approved", d["filters"][key])
            self.assertIn("size_multiplier", d["filters"][key])
            self.assertIn("reason", d["filters"][key])


# ---------------------------------------------------------------------------
# Convenience wrapper
# ---------------------------------------------------------------------------

class TestConvenienceWrapper(unittest.TestCase):
    """allocate_alpha_position() stateless wrapper."""

    def test_basic_call_returns_dict(self):
        d = allocate_alpha_position(2_000.0, 100.0, 95.0)
        self.assertTrue(d["valid"])
        self.assertAlmostEqual(d["position_size_usd"], 800.0, places=2)

    def test_custom_config(self):
        cfg = PortfolioAlphaConfig(risk_pct=0.01)
        d = allocate_alpha_position(10_000.0, 100.0, 95.0, config=cfg)
        self.assertAlmostEqual(d["risk_per_trade_usd"], 100.0, places=2)
        self.assertAlmostEqual(d["position_size_usd"], 2_000.0, places=2)

    def test_filters_forwarded(self):
        """Filters are forwarded and influence the result."""
        # BTC spike should block the altcoin trade
        d = allocate_alpha_position(
            1_000.0, 100.0, 95.0,
            symbol="ADA-USD",
            btc_atr_pct=0.10,  # big spike
        )
        self.assertTrue(d["valid"])
        self.assertEqual(d["position_size_usd"], 0.0)
        self.assertFalse(d["filters"]["btc_regime"]["approved"])


if __name__ == "__main__":
    unittest.main()
