"""
Tests for bot/risk_budget_engine.py
====================================

Covers:
- Core position-size formula
- Floor / cap clamping logic
- Dynamic risk scaling (winning streak, losing streak, baseline)
- Edge cases (zero stop-distance, invalid inputs)
- Convenience wrapper function
"""

import unittest

try:
    from bot.risk_budget_engine import (
        RiskBudgetEngine,
        RiskBudgetConfig,
        TradeRecord,
        calculate_risk_position,
        DEFAULT_BASE_RISK_PCT,
        WINNING_RISK_PCT,
        LOSING_RISK_PCT,
        WIN_RATE_THRESHOLD,
        LOSING_STREAK_THRESHOLD,
        LOOKBACK_TRADES,
        OUTCOME_WIN,
        OUTCOME_LOSS,
    )
except ImportError:
    from risk_budget_engine import (
        RiskBudgetEngine,
        RiskBudgetConfig,
        TradeRecord,
        calculate_risk_position,
        DEFAULT_BASE_RISK_PCT,
        WINNING_RISK_PCT,
        LOSING_RISK_PCT,
        WIN_RATE_THRESHOLD,
        LOSING_STREAK_THRESHOLD,
        LOOKBACK_TRADES,
        OUTCOME_WIN,
        OUTCOME_LOSS,
    )


class TestRiskBudgetEngineCore(unittest.TestCase):
    """Core formula: risk_per_trade / stop_distance."""

    def setUp(self):
        self.config = RiskBudgetConfig(
            base_risk_pct=0.01,
            min_position=1.0,
            tier_floor=1.0,
            exchange_minimum=1.0,
            max_position_cap=100_000.0,
            enable_dynamic_scaling=False,  # isolate core logic
        )
        self.engine = RiskBudgetEngine(self.config)

    def test_basic_position_size(self):
        """1 % of $10 000 / 5 % stop-distance = $2 000."""
        result = self.engine.calculate_position_size(
            account_balance=10_000.0,
            entry_price=100.0,
            stop_price=95.0,   # 5 % below entry
        )
        self.assertTrue(result["valid"])
        self.assertAlmostEqual(result["stop_distance_pct"], 0.05, places=4)
        self.assertAlmostEqual(result["risk_per_trade_usd"], 100.0, places=2)
        self.assertAlmostEqual(result["position_size_usd"], 2_000.0, places=2)

    def test_stop_distance_calculation(self):
        """Stop distance is |entry - stop| / entry (both directions)."""
        # stop below entry
        r1 = self.engine.calculate_position_size(1000.0, 50.0, 45.0)
        self.assertAlmostEqual(r1["stop_distance_pct"], 0.10, places=4)

        # stop above entry (short-side stop)
        r2 = self.engine.calculate_position_size(1000.0, 50.0, 55.0)
        self.assertAlmostEqual(r2["stop_distance_pct"], 0.10, places=4)

    def test_risk_per_trade_is_one_percent(self):
        """risk_per_trade == account_balance * base_risk_pct."""
        result = self.engine.calculate_position_size(5_000.0, 200.0, 190.0)
        self.assertAlmostEqual(result["risk_per_trade_usd"], 50.0, places=2)

    def test_valid_flag_on_success(self):
        result = self.engine.calculate_position_size(1_000.0, 100.0, 90.0)
        self.assertTrue(result["valid"])
        self.assertEqual(result["error"], "")


class TestRiskBudgetEngineClamping(unittest.TestCase):
    """Position size clamping: floor and cap."""

    def _engine(self, **kwargs):
        cfg = RiskBudgetConfig(
            enable_dynamic_scaling=False,
            **kwargs,
        )
        return RiskBudgetEngine(cfg)

    def test_floor_applied_when_position_too_small(self):
        """Very tight stop + tiny balance → size gets raised to floor."""
        # balance=$100, risk=$1, stop_dist=50 % → raw=$2; floor=$10
        engine = self._engine(
            base_risk_pct=0.01,
            min_position=10.0,
            tier_floor=10.0,
            exchange_minimum=1.0,
            max_position_cap=100_000.0,
        )
        result = engine.calculate_position_size(100.0, 100.0, 50.0)
        self.assertEqual(result["position_size_usd"], 10.0)
        self.assertTrue(result["clamped"])
        self.assertIn("floor", result["clamp_reason"])

    def test_cap_applied_when_position_too_large(self):
        """Tiny stop + huge balance → size capped at max_position_cap."""
        engine = self._engine(
            base_risk_pct=0.01,
            min_position=1.0,
            tier_floor=1.0,
            exchange_minimum=1.0,
            max_position_cap=500.0,
        )
        # balance=$1M, risk=$10k, stop_dist=0.1 % → raw=$10M → cap=$500
        result = engine.calculate_position_size(1_000_000.0, 100.0, 99.9)
        self.assertEqual(result["position_size_usd"], 500.0)
        self.assertTrue(result["clamped"])
        self.assertIn("cap", result["clamp_reason"])

    def test_effective_floor_is_max_of_three_minimums(self):
        """The floor is the largest of min_position, tier_floor, exchange_minimum."""
        engine = self._engine(
            base_risk_pct=0.01,
            min_position=2.0,
            tier_floor=8.0,      # <- highest
            exchange_minimum=5.0,
            max_position_cap=100_000.0,
        )
        # raw < tier_floor → clamped to 8.0
        result = engine.calculate_position_size(100.0, 100.0, 50.0)
        self.assertEqual(result["position_size_usd"], 8.0)

    def test_no_clamping_when_in_range(self):
        """When raw size is within [floor, cap] no clamping should occur."""
        engine = self._engine(
            base_risk_pct=0.01,
            min_position=1.0,
            tier_floor=1.0,
            exchange_minimum=1.0,
            max_position_cap=100_000.0,
        )
        result = engine.calculate_position_size(10_000.0, 100.0, 95.0)
        self.assertFalse(result["clamped"])
        self.assertEqual(result["clamp_reason"], "")


class TestRiskBudgetEngineInvalidInputs(unittest.TestCase):
    """Invalid input handling."""

    def setUp(self):
        self.engine = RiskBudgetEngine()

    def _assert_invalid(self, result, substring=""):
        self.assertFalse(result["valid"])
        self.assertEqual(result["position_size_usd"], 0.0)
        if substring:
            self.assertIn(substring, result["error"])

    def test_zero_account_balance(self):
        result = self.engine.calculate_position_size(0.0, 100.0, 95.0)
        self._assert_invalid(result, "account_balance")

    def test_negative_account_balance(self):
        result = self.engine.calculate_position_size(-500.0, 100.0, 95.0)
        self._assert_invalid(result, "account_balance")

    def test_zero_entry_price(self):
        result = self.engine.calculate_position_size(1000.0, 0.0, 95.0)
        self._assert_invalid(result, "entry_price")

    def test_zero_stop_price(self):
        result = self.engine.calculate_position_size(1000.0, 100.0, 0.0)
        self._assert_invalid(result, "stop_price")

    def test_stop_equals_entry(self):
        result = self.engine.calculate_position_size(1000.0, 100.0, 100.0)
        self._assert_invalid(result, "stop_price")


class TestDynamicRiskScaling(unittest.TestCase):
    """Dynamic risk scaling based on recent trade history."""

    def _engine_with_trades(self, outcomes):
        """Build an engine and record the given outcome sequence."""
        cfg = RiskBudgetConfig(
            base_risk_pct=DEFAULT_BASE_RISK_PCT,
            winning_risk_pct=WINNING_RISK_PCT,
            losing_risk_pct=LOSING_RISK_PCT,
            win_rate_threshold=WIN_RATE_THRESHOLD,
            losing_streak_threshold=LOSING_STREAK_THRESHOLD,
            lookback_trades=LOOKBACK_TRADES,
            enable_dynamic_scaling=True,
            min_position=1.0,
            tier_floor=1.0,
            exchange_minimum=1.0,
            max_position_cap=100_000.0,
        )
        engine = RiskBudgetEngine(cfg)
        for outcome in outcomes:
            engine.record_trade_outcome(outcome)
        return engine

    def test_baseline_when_no_trades(self):
        engine = self._engine_with_trades([])
        result = engine.calculate_position_size(10_000.0, 100.0, 95.0)
        self.assertAlmostEqual(result["risk_pct_used"], DEFAULT_BASE_RISK_PCT)
        self.assertEqual(result["scaling_reason"], "baseline")

    def test_baseline_when_fewer_than_lookback_trades_and_no_losing_streak(self):
        # 5 wins, 2 losses – fewer than LOOKBACK_TRADES (10)
        engine = self._engine_with_trades([OUTCOME_WIN] * 5 + [OUTCOME_LOSS] * 2)
        result = engine.calculate_position_size(10_000.0, 100.0, 95.0)
        self.assertAlmostEqual(result["risk_pct_used"], DEFAULT_BASE_RISK_PCT)
        self.assertEqual(result["scaling_reason"], "baseline")

    def test_winning_risk_when_win_rate_above_threshold(self):
        """7 wins out of 10 → 70 % win rate → winning risk %."""
        # Ensure the sequence does NOT end in a 3-loss streak
        trades = [OUTCOME_LOSS, OUTCOME_WIN, OUTCOME_LOSS, OUTCOME_WIN, OUTCOME_WIN, OUTCOME_WIN, OUTCOME_WIN, OUTCOME_WIN, OUTCOME_WIN, OUTCOME_WIN]
        # win_rate = 8/10 = 80 %; tail ends with win → no losing streak
        engine = self._engine_with_trades(trades)
        result = engine.calculate_position_size(10_000.0, 100.0, 95.0)
        self.assertAlmostEqual(result["risk_pct_used"], WINNING_RISK_PCT)
        self.assertIn("high_win_rate", result["scaling_reason"])

    def test_baseline_when_win_rate_at_threshold(self):
        """60 % win rate (below 65 % threshold) → baseline (no losing streak)."""
        # 6 wins, 4 losses interleaved so there is no 3-loss streak at the tail
        trades = [OUTCOME_WIN, OUTCOME_LOSS, OUTCOME_WIN, OUTCOME_LOSS, OUTCOME_WIN, OUTCOME_WIN, OUTCOME_LOSS, OUTCOME_WIN, OUTCOME_WIN, OUTCOME_LOSS]
        # tail: …win, win, loss → streak = 1, win_rate = 6/10 = 60 % → baseline
        engine = self._engine_with_trades(trades)
        result = engine.calculate_position_size(10_000.0, 100.0, 95.0)
        self.assertAlmostEqual(result["risk_pct_used"], DEFAULT_BASE_RISK_PCT)

    def test_losing_risk_when_losing_streak_detected(self):
        """3+ consecutive losses at the end → losing risk %."""
        trades = [OUTCOME_WIN] * 7 + [OUTCOME_LOSS] * LOSING_STREAK_THRESHOLD
        engine = self._engine_with_trades(trades)
        result = engine.calculate_position_size(10_000.0, 100.0, 95.0)
        self.assertAlmostEqual(result["risk_pct_used"], LOSING_RISK_PCT)
        self.assertIn("losing_streak", result["scaling_reason"])

    def test_losing_streak_takes_priority_over_high_win_rate(self):
        """Even with a good historical win rate, a losing streak overrides."""
        # 8 wins then 3 losses → win rate of last 10 is 7/10 = 70 % but
        # there is a losing streak of 3 at the tail → losing risk takes priority
        trades = [OUTCOME_WIN] * 8 + [OUTCOME_LOSS] * LOSING_STREAK_THRESHOLD
        engine = self._engine_with_trades(trades)
        result = engine.calculate_position_size(10_000.0, 100.0, 95.0)
        self.assertAlmostEqual(result["risk_pct_used"], LOSING_RISK_PCT)

    def test_winning_risk_applied_to_position_size(self):
        """Higher risk % produces a proportionally larger position."""
        # 8 wins, 2 losses; sequence ends with win → no losing streak
        trades = [OUTCOME_LOSS, OUTCOME_WIN, OUTCOME_WIN, OUTCOME_WIN, OUTCOME_LOSS, OUTCOME_WIN, OUTCOME_WIN, OUTCOME_WIN, OUTCOME_WIN, OUTCOME_WIN]
        engine = self._engine_with_trades(trades)
        result = engine.calculate_position_size(10_000.0, 100.0, 95.0)
        # risk_per_trade = 10000 * 0.0125 = 125; stop_dist = 5 % → size = 2500
        self.assertAlmostEqual(result["risk_per_trade_usd"], 125.0, places=2)
        self.assertAlmostEqual(result["position_size_usd"], 2_500.0, places=2)

    def test_losing_risk_applied_to_position_size(self):
        """Lower risk % produces a proportionally smaller position."""
        trades = [OUTCOME_WIN] * 2 + [OUTCOME_LOSS] * LOSING_STREAK_THRESHOLD
        engine = self._engine_with_trades(trades)
        result = engine.calculate_position_size(10_000.0, 100.0, 95.0)
        # risk_per_trade = 10000 * 0.005 = 50; stop_dist = 5 % → size = 1000
        self.assertAlmostEqual(result["risk_per_trade_usd"], 50.0, places=2)
        self.assertAlmostEqual(result["position_size_usd"], 1_000.0, places=2)


class TestRecordTradeOutcome(unittest.TestCase):
    """record_trade_outcome() and get_performance_summary()."""

    def setUp(self):
        self.engine = RiskBudgetEngine()

    def test_record_win(self):
        self.engine.record_trade_outcome(OUTCOME_WIN, pnl=100.0)
        summary = self.engine.get_performance_summary()
        self.assertEqual(summary["win_rate"], 1.0)

    def test_record_loss(self):
        self.engine.record_trade_outcome(OUTCOME_LOSS, pnl=-50.0)
        summary = self.engine.get_performance_summary()
        self.assertEqual(summary["win_rate"], 0.0)
        self.assertEqual(summary["losing_streak"], 1)

    def test_invalid_outcome_raises(self):
        with self.assertRaises(ValueError):
            self.engine.record_trade_outcome("breakeven")

    def test_performance_summary_structure(self):
        self.engine.record_trade_outcome(OUTCOME_WIN, pnl=200.0)
        summary = self.engine.get_performance_summary()
        self.assertIn("lookback", summary)
        self.assertIn("win_rate", summary)
        self.assertIn("losing_streak", summary)
        self.assertIn("risk_pct", summary)
        self.assertIn("scaling_reason", summary)


class TestOverrideRiskPct(unittest.TestCase):
    """override_risk_pct parameter bypasses dynamic scaling."""

    def setUp(self):
        self.engine = RiskBudgetEngine()

    def test_override_applied(self):
        result = self.engine.calculate_position_size(
            10_000.0, 100.0, 95.0, override_risk_pct=0.02
        )
        self.assertAlmostEqual(result["risk_per_trade_usd"], 200.0, places=2)
        self.assertEqual(result["scaling_reason"], "override")

    def test_override_ignores_dynamic_scaling(self):
        # Build winning streak that would normally bump to WINNING_RISK_PCT
        for _ in range(10):
            self.engine.record_trade_outcome(OUTCOME_WIN)
        result = self.engine.calculate_position_size(
            10_000.0, 100.0, 95.0, override_risk_pct=0.005
        )
        self.assertAlmostEqual(result["risk_pct_used"], 0.005, places=4)


class TestConvenienceFunction(unittest.TestCase):
    """calculate_risk_position() stateless wrapper."""

    def test_basic_call(self):
        result = calculate_risk_position(10_000.0, 100.0, 95.0)
        self.assertTrue(result["valid"])
        self.assertAlmostEqual(result["position_size_usd"], 2_000.0, places=2)

    def test_custom_config(self):
        cfg = RiskBudgetConfig(
            base_risk_pct=0.02,
            enable_dynamic_scaling=False,
            min_position=1.0,
            tier_floor=1.0,
            exchange_minimum=1.0,
            max_position_cap=100_000.0,
        )
        result = calculate_risk_position(10_000.0, 100.0, 95.0, config=cfg)
        self.assertAlmostEqual(result["risk_per_trade_usd"], 200.0, places=2)


if __name__ == "__main__":
    unittest.main()
