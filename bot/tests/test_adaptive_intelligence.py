#!/usr/bin/env python3
"""
Tests for AdaptiveIntelligenceEngine and its subsystems
=========================================================

Covers:
1. DynamicRiskController — dynamic risk parameter adjustment
2. SectorLearningEngine  — cross-market sector learning & confidence weights
3. StrategyEvolutionController — paper-trading experiments, promotion, rollback
4. CapitalRebalancer — capital allocation rebalancing
5. AdaptiveIntelligenceEngine — master orchestrator integration

Author: NIJA Trading Systems
Date: February 2026
"""

import sys
import os
import unittest
import tempfile
import shutil

# Ensure the bot directory is on the path
bot_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, bot_dir)

from adaptive_intelligence_engine import (
    DynamicRiskController,
    RiskParameters,
    VolatilityLevel,
    SectorLearningEngine,
    StrategyEvolutionController,
    ExperimentState,
    CapitalRebalancer,
    AdaptiveIntelligenceEngine,
    get_adaptive_intelligence_engine,
    HARD_CAP_MAX_TRADE_PCT,
    HARD_CAP_MIN_TRADE_PCT,
    HARD_CAP_MAX_CONCURRENT,
    HARD_CAP_MIN_CONCURRENT,
)


# ---------------------------------------------------------------------------
# Feature 1 — DynamicRiskController Tests
# ---------------------------------------------------------------------------

class TestDynamicRiskController(unittest.TestCase):
    """Tests for DynamicRiskController"""

    def setUp(self):
        self.controller = DynamicRiskController(
            base_max_trade_pct=0.03,
            base_max_concurrent=5,
            evaluation_window=10,
        )

    def test_initial_parameters_within_hard_caps(self):
        """Parameters must start within hard caps"""
        params = self.controller.get_current_parameters()
        self.assertGreaterEqual(params.max_trade_pct, HARD_CAP_MIN_TRADE_PCT)
        self.assertLessEqual(params.max_trade_pct, HARD_CAP_MAX_TRADE_PCT)
        self.assertGreaterEqual(params.max_concurrent_positions, HARD_CAP_MIN_CONCURRENT)
        self.assertLessEqual(params.max_concurrent_positions, HARD_CAP_MAX_CONCURRENT)

    def test_extreme_volatility_reduces_parameters(self):
        """Extreme volatility should reduce trade size and concurrent positions"""
        for _ in range(5):
            self.controller.record_trade_result(pnl=-0.01, is_win=False,
                                                current_drawdown_pct=5.0, volatility_pct=80.0)
        params = self.controller.update_parameters(
            current_volatility_pct=80.0, current_drawdown_pct=5.0
        )
        self.assertLess(params.max_trade_pct, 0.03)
        self.assertEqual(params.volatility_level, VolatilityLevel.EXTREME)

    def test_low_volatility_winning_streak_increases_parameters(self):
        """Low volatility + winning streak should increase trade size"""
        for _ in range(10):
            self.controller.record_trade_result(pnl=0.02, is_win=True,
                                                current_drawdown_pct=1.0, volatility_pct=10.0)
        params = self.controller.update_parameters(
            current_volatility_pct=10.0, current_drawdown_pct=1.0
        )
        self.assertGreater(params.max_trade_pct, 0.03)
        self.assertEqual(params.volatility_level, VolatilityLevel.LOW)

    def test_high_drawdown_reduces_parameters(self):
        """High drawdown should reduce trade size"""
        params = self.controller.update_parameters(
            current_volatility_pct=25.0, current_drawdown_pct=25.0
        )
        self.assertLess(params.max_trade_pct, 0.03)

    def test_hard_caps_never_exceeded(self):
        """Hard caps must never be violated regardless of conditions"""
        # Simulate the most extreme possible case
        for _ in range(15):
            self.controller.record_trade_result(pnl=1.0, is_win=True,
                                                current_drawdown_pct=0.0, volatility_pct=1.0)
        params = self.controller.update_parameters(
            current_volatility_pct=1.0, current_drawdown_pct=0.0
        )
        self.assertLessEqual(params.max_trade_pct, HARD_CAP_MAX_TRADE_PCT)
        self.assertLessEqual(params.max_concurrent_positions, HARD_CAP_MAX_CONCURRENT)
        self.assertGreaterEqual(params.max_trade_pct, HARD_CAP_MIN_TRADE_PCT)
        self.assertGreaterEqual(params.max_concurrent_positions, HARD_CAP_MIN_CONCURRENT)

    def test_riskparameters_clamp_enforces_caps(self):
        """RiskParameters.clamp() must enforce all hard caps"""
        params = RiskParameters(
            max_trade_pct=999.0,
            max_concurrent_positions=9999,
        ).clamp()
        self.assertLessEqual(params.max_trade_pct, HARD_CAP_MAX_TRADE_PCT)
        self.assertLessEqual(params.max_concurrent_positions, HARD_CAP_MAX_CONCURRENT)

        params2 = RiskParameters(
            max_trade_pct=-999.0,
            max_concurrent_positions=-5,
        ).clamp()
        self.assertGreaterEqual(params2.max_trade_pct, HARD_CAP_MIN_TRADE_PCT)
        self.assertGreaterEqual(params2.max_concurrent_positions, HARD_CAP_MIN_CONCURRENT)


# ---------------------------------------------------------------------------
# Feature 2 — SectorLearningEngine Tests
# ---------------------------------------------------------------------------

class TestSectorLearningEngine(unittest.TestCase):
    """Tests for SectorLearningEngine"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = SectorLearningEngine(data_dir=self.tmpdir)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_default_weight_without_data(self):
        """Engine should return neutral weight (1.0) for unknown symbols"""
        weight = self.engine.get_confidence_weight("NEW-USD", "unknown_sector")
        self.assertEqual(weight, 1.0)

    def test_high_win_rate_increases_weight(self):
        """Consistent wins should push weight above 1.0"""
        for _ in range(15):
            self.engine.record_trade("BTC-USD", "bitcoin", pnl=0.02, is_win=True)
        weight = self.engine.get_confidence_weight("BTC-USD", "bitcoin")
        self.assertGreater(weight, 1.0)

    def test_low_win_rate_decreases_weight(self):
        """Consistent losses should push weight below 1.0"""
        for _ in range(15):
            self.engine.record_trade("DOGE-USD", "meme_coins", pnl=-0.01, is_win=False)
        weight = self.engine.get_confidence_weight("DOGE-USD", "meme_coins")
        self.assertLess(weight, 1.0)

    def test_weight_floor_prevents_blocking(self):
        """Weight floor must ensure low-confidence instruments are never fully blocked"""
        for _ in range(20):
            self.engine.record_trade("SHIB-USD", "meme_coins", pnl=-0.05, is_win=False)
        weight = self.engine.get_confidence_weight("SHIB-USD", "meme_coins")
        self.assertGreaterEqual(weight, SectorLearningEngine.MIN_WEIGHT)

    def test_weight_ceiling_enforced(self):
        """Weight ceiling must be enforced for high performers"""
        for _ in range(20):
            self.engine.record_trade("ETH-USD", "ethereum", pnl=0.1, is_win=True)
        weight = self.engine.get_confidence_weight("ETH-USD", "ethereum")
        self.assertLessEqual(weight, SectorLearningEngine.MAX_WEIGHT)

    def test_insufficient_data_returns_neutral(self):
        """Fewer than MIN_TRADES_FOR_WEIGHTING should return neutral weight"""
        for _ in range(5):  # Below MIN_TRADES_FOR_WEIGHTING (10)
            self.engine.record_trade("SOL-USD", "layer_1_alt", pnl=0.02, is_win=True)
        weight = self.engine.get_confidence_weight("SOL-USD", "layer_1_alt")
        self.assertEqual(weight, 1.0)

    def test_get_top_sectors_returns_list(self):
        """get_top_sectors should return a list of (sector, weight) tuples"""
        for i in range(12):
            self.engine.record_trade("BTC-USD", "bitcoin", pnl=0.01, is_win=True)
        top = self.engine.get_top_sectors(n=3)
        self.assertIsInstance(top, list)
        self.assertGreater(len(top), 0)
        self.assertIsInstance(top[0], tuple)

    def test_persistence_across_instances(self):
        """Data should persist across SectorLearningEngine instances"""
        for _ in range(12):
            self.engine.record_trade("ADA-USD", "layer_1_alt", pnl=0.01, is_win=True)
        weight_before = self.engine.get_confidence_weight("ADA-USD", "layer_1_alt")

        # Create a new instance pointing to the same directory
        engine2 = SectorLearningEngine(data_dir=self.tmpdir)
        weight_after = engine2.get_confidence_weight("ADA-USD", "layer_1_alt")

        self.assertAlmostEqual(weight_before, weight_after, places=4)


# ---------------------------------------------------------------------------
# Feature 3 — StrategyEvolutionController Tests
# ---------------------------------------------------------------------------

class TestStrategyEvolutionController(unittest.TestCase):
    """Tests for StrategyEvolutionController"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.controller = StrategyEvolutionController(data_dir=self.tmpdir)
        self.controller.set_base_parameters({"rsi_oversold": 30, "rsi_overbought": 70})

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_experiment_starts_in_paper_trading_state(self):
        """New experiments should start in PAPER_TRADING state"""
        exp = self.controller.register_experiment("exp_1", {"rsi_oversold": 28})
        self.assertEqual(exp.state, ExperimentState.PAPER_TRADING)

    def test_promotion_after_sufficient_winning_paper_trades(self):
        """Experiment should be promoted after meeting criteria"""
        self.controller.register_experiment("exp_promo", {"rsi_oversold": 27})
        # Feed 20 winning trades
        for _ in range(20):
            self.controller.record_paper_result("exp_promo", pnl=0.01, is_win=True)
        exp = self.controller._experiments["exp_promo"]
        self.assertEqual(exp.state, ExperimentState.PROMOTED)
        self.assertEqual(self.controller._active_experiment_id, "exp_promo")

    def test_no_promotion_when_below_win_rate_threshold(self):
        """Experiment should NOT be promoted if win rate is too low"""
        self.controller.register_experiment("exp_low_wr", {"rsi_oversold": 25})
        # Feed 20 trades with 30% win rate (below 55% threshold)
        for i in range(20):
            is_win = (i < 6)  # 6/20 = 30%
            self.controller.record_paper_result("exp_low_wr", pnl=0.005 if is_win else -0.01, is_win=is_win)
        exp = self.controller._experiments["exp_low_wr"]
        self.assertNotEqual(exp.state, ExperimentState.PROMOTED)

    def test_rollback_after_live_losses(self):
        """Promoted experiment should roll back when live losses exceed threshold"""
        self.controller.register_experiment("exp_rollback", {"rsi_oversold": 26})
        # Promote it
        for _ in range(20):
            self.controller.record_paper_result("exp_rollback", pnl=0.01, is_win=True)
        self.assertEqual(self.controller._active_experiment_id, "exp_rollback")

        # Feed failing live trades (average PnL = -0.02, well below -0.005 threshold)
        for _ in range(15):
            self.controller.record_live_result(pnl=-0.02, is_win=False)

        exp = self.controller._experiments["exp_rollback"]
        self.assertEqual(exp.state, ExperimentState.ROLLED_BACK)
        self.assertIsNone(self.controller._active_experiment_id)

    def test_base_parameters_returned_when_no_active_experiment(self):
        """Base parameters should be returned when no experiment is promoted"""
        params = self.controller.get_active_parameters()
        self.assertEqual(params, {"rsi_oversold": 30, "rsi_overbought": 70})

    def test_promoted_parameters_returned_when_active(self):
        """Promoted experiment parameters should override base parameters"""
        exp_params = {"rsi_oversold": 28, "rsi_overbought": 72}
        self.controller.register_experiment("exp_live", exp_params)
        for _ in range(20):
            self.controller.record_paper_result("exp_live", pnl=0.01, is_win=True)
        active = self.controller.get_active_parameters()
        self.assertEqual(active, exp_params)

    def test_get_status_returns_expected_shape(self):
        """get_status() should return a dict with expected keys"""
        self.controller.register_experiment("exp_s", {"p": 1})
        status = self.controller.get_status()
        self.assertIn("active_experiment", status)
        self.assertIn("active_parameters", status)
        self.assertIn("experiments", status)

    def test_persistence_across_instances(self):
        """State should be persisted to disk and reloaded"""
        self.controller.register_experiment("exp_persist", {"x": 99})
        for _ in range(20):
            self.controller.record_paper_result("exp_persist", pnl=0.01, is_win=True)

        ctrl2 = StrategyEvolutionController(data_dir=self.tmpdir)
        self.assertEqual(ctrl2._active_experiment_id, "exp_persist")


# ---------------------------------------------------------------------------
# Feature 4 — CapitalRebalancer Tests
# ---------------------------------------------------------------------------

class TestCapitalRebalancer(unittest.TestCase):
    """Tests for CapitalRebalancer"""

    def setUp(self):
        self.rebalancer = CapitalRebalancer(min_alloc_pct=0.05, max_alloc_pct=0.70)

    def test_register_account(self):
        """Accounts should be registered successfully"""
        alloc = self.rebalancer.register_account("ACC1", "Coinbase", 5000.0, 0.50)
        self.assertEqual(alloc.account_id, "ACC1")
        self.assertEqual(alloc.broker, "Coinbase")

    def test_allocations_sum_to_one_after_rebalance(self):
        """Allocation percentages should sum to approximately 1.0 after rebalance"""
        self.rebalancer.register_account("ACC1", "Coinbase", 5000.0, 0.50)
        self.rebalancer.register_account("ACC2", "Kraken",   2000.0, 0.30)
        self.rebalancer.register_account("ACC3", "Binance",  1000.0, 0.20)

        # Feed trade history
        for _ in range(20):
            self.rebalancer.record_account_trade("ACC1", pnl=0.02, is_win=True)
        for _ in range(20):
            self.rebalancer.record_account_trade("ACC2", pnl=-0.01, is_win=False)

        allocs = self.rebalancer.rebalance()
        total = sum(allocs.values())
        self.assertAlmostEqual(total, 1.0, places=4)

    def test_high_performer_gets_more_capital(self):
        """Better-performing accounts should receive more capital"""
        self.rebalancer.register_account("GOOD", "Coinbase", 5000.0, 0.50)
        self.rebalancer.register_account("BAD",  "Kraken",   5000.0, 0.50)

        for _ in range(20):
            self.rebalancer.record_account_trade("GOOD", pnl=0.02, is_win=True)
        for _ in range(20):
            self.rebalancer.record_account_trade("BAD",  pnl=-0.02, is_win=False)

        allocs = self.rebalancer.rebalance()
        self.assertGreater(allocs["GOOD"], allocs["BAD"])

    def test_per_account_caps_respected(self):
        """No account should exceed max_alloc_pct"""
        for i in range(5):
            self.rebalancer.register_account(f"ACC{i}", "Broker", 1000.0, 0.20)
        for _ in range(20):
            self.rebalancer.record_account_trade("ACC0", pnl=0.05, is_win=True)
        allocs = self.rebalancer.rebalance()
        for alloc in allocs.values():
            self.assertLessEqual(alloc, 0.70)
            self.assertGreaterEqual(alloc, 0.05)

    def test_update_account_balance(self):
        """Balance updates should be reflected in allocation data"""
        self.rebalancer.register_account("ACC", "CB", 1000.0)
        self.rebalancer.update_account_balance("ACC", 2000.0)
        self.assertEqual(self.rebalancer._accounts["ACC"].current_balance, 2000.0)


# ---------------------------------------------------------------------------
# Feature 5 — AdaptiveIntelligenceEngine (Orchestrator) Tests
# ---------------------------------------------------------------------------

class TestAdaptiveIntelligenceEngine(unittest.TestCase):
    """Integration tests for the master AdaptiveIntelligenceEngine"""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.engine = AdaptiveIntelligenceEngine(
            data_dir=self.tmpdir,
            base_max_trade_pct=0.03,
            base_max_concurrent=5,
            dry_run=False,
        )
        self.engine.capital_rebalancer.register_account("PLATFORM", "Coinbase", 5000.0, 1.0)

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_on_trade_completed_returns_expected_keys(self):
        """on_trade_completed should return a dict with all required keys"""
        result = self.engine.on_trade_completed(
            account_id="PLATFORM",
            symbol="BTC-USD",
            sector="bitcoin",
            pnl=0.01,
            is_win=True,
            current_drawdown_pct=3.0,
            current_volatility_pct=25.0,
        )
        self.assertIn("risk_parameters", result)
        self.assertIn("sector_confidence_weight", result)
        self.assertIn("active_strategy_parameters", result)
        self.assertIn("max_trade_pct", result["risk_parameters"])
        self.assertIn("max_concurrent_positions", result["risk_parameters"])

    def test_get_trade_parameters_returns_valid_params(self):
        """get_trade_parameters should return valid parameters for trade sizing"""
        params = self.engine.get_trade_parameters("ETH-USD", "ethereum", "PLATFORM")
        self.assertIn("max_trade_pct", params)
        self.assertIn("max_concurrent_positions", params)
        self.assertIn("sector_confidence_weight", params)
        self.assertGreaterEqual(params["max_trade_pct"], HARD_CAP_MIN_TRADE_PCT)
        self.assertLessEqual(params["max_trade_pct"], HARD_CAP_MAX_TRADE_PCT)

    def test_full_status_has_all_sections(self):
        """get_full_status() should contain status from all subsystems"""
        status = self.engine.get_full_status()
        self.assertIn("risk_parameters", status)
        self.assertIn("sector_learning", status)
        self.assertIn("strategy_evolution", status)
        self.assertIn("capital_allocation", status)

    def test_audit_log_records_trades(self):
        """Audit log should record every on_trade_completed call"""
        self.engine.on_trade_completed(
            account_id="PLATFORM",
            symbol="SOL-USD",
            sector="layer_1_alt",
            pnl=-0.005,
            is_win=False,
            current_drawdown_pct=8.0,
            current_volatility_pct=40.0,
        )
        log = self.engine.get_audit_log()
        self.assertGreater(len(log), 0)
        self.assertEqual(log[-1]["event"], "trade_completed")
        self.assertEqual(log[-1]["symbol"], "SOL-USD")

    def test_dry_run_skips_live_rebalance(self):
        """In dry_run mode, run_rebalance() should return empty dict"""
        dry_engine = AdaptiveIntelligenceEngine(
            data_dir=self.tmpdir,
            dry_run=True,
        )
        result = dry_engine.run_rebalance()
        self.assertEqual(result, {})

    def test_experiment_flow_via_engine(self):
        """Full experiment lifecycle should work through the engine"""
        self.engine.evolution_controller.set_base_parameters({"rsi": 30})
        self.engine.evolution_controller.register_experiment("exp_e2e", {"rsi": 28})

        for _ in range(20):
            self.engine.on_trade_completed(
                account_id="PLATFORM",
                symbol="BTC-USD",
                sector="bitcoin",
                pnl=0.01,
                is_win=True,
                current_drawdown_pct=2.0,
                current_volatility_pct=20.0,
                experiment_id="exp_e2e",
            )

        active_params = self.engine.evolution_controller.get_active_parameters()
        self.assertEqual(active_params, {"rsi": 28})

    def test_singleton_factory(self):
        """get_adaptive_intelligence_engine should return the same instance"""
        engine1 = get_adaptive_intelligence_engine(
            data_dir=self.tmpdir, reset=True
        )
        engine2 = get_adaptive_intelligence_engine(data_dir=self.tmpdir)
        self.assertIs(engine1, engine2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
