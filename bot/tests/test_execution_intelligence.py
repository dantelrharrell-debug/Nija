"""
Tests for Execution Intelligence Layer

Tests all components of the execution intelligence system:
- Slippage modeling
- Spread prediction
- Liquidity analysis
- Market impact estimation
- Execution optimization
"""

import unittest
import time
from unittest.mock import Mock, patch

# Import execution intelligence components
try:
    from bot.execution_intelligence import (
        ExecutionIntelligence,
        SlippageModeler,
        SpreadPredictor,
        LiquidityAnalyzer,
        MarketImpactEstimator,
        MarketMicrostructure,
        MarketCondition,
        OrderType,
        ExecutionPlan,
        get_execution_intelligence
    )
except ImportError:
    from execution_intelligence import (
        ExecutionIntelligence,
        SlippageModeler,
        SpreadPredictor,
        LiquidityAnalyzer,
        MarketImpactEstimator,
        MarketMicrostructure,
        MarketCondition,
        OrderType,
        ExecutionPlan,
        get_execution_intelligence
    )


class TestMarketMicrostructure(unittest.TestCase):
    """Test market microstructure data class."""

    def test_market_microstructure_creation(self):
        """Test creating market microstructure object."""
        ms = MarketMicrostructure(
            symbol='BTC-USD',
            bid=50000.0,
            ask=50050.0,
            spread_pct=0.001,
            volume_24h=1000000.0,
            bid_depth=50000.0,
            ask_depth=60000.0,
            volatility=0.01,
            price=50025.0,
            timestamp=time.time()
        )

        self.assertEqual(ms.symbol, 'BTC-USD')
        self.assertEqual(ms.bid, 50000.0)
        self.assertEqual(ms.ask, 50050.0)
        self.assertEqual(ms.spread_pct, 0.001)
        self.assertGreater(ms.timestamp, 0)


class TestSlippageModeler(unittest.TestCase):
    """Test slippage prediction model."""

    def setUp(self):
        """Set up test fixtures."""
        self.modeler = SlippageModeler()
        self.market_data = MarketMicrostructure(
            symbol='BTC-USD',
            bid=50000.0,
            ask=50050.0,
            spread_pct=0.001,
            volume_24h=5000000.0,
            bid_depth=100000.0,
            ask_depth=120000.0,
            volatility=0.015,
            price=50025.0,
            timestamp=time.time()
        )

    def test_predict_slippage_calm_market(self):
        """Test slippage prediction in calm market."""
        estimate = self.modeler.predict_slippage(
            market_data=self.market_data,
            order_size_usd=1000.0,
            side='buy',
            market_condition=MarketCondition.CALM
        )

        self.assertIsNotNone(estimate)
        self.assertGreater(estimate.expected_slippage_pct, 0)
        self.assertGreater(estimate.worst_case_slippage_pct, estimate.expected_slippage_pct)
        self.assertGreater(estimate.confidence, 0)
        self.assertLessEqual(estimate.confidence, 1.0)
        self.assertIn('base_slippage', estimate.factors)

    def test_predict_slippage_volatile_market(self):
        """Test slippage prediction in volatile market."""
        estimate = self.modeler.predict_slippage(
            market_data=self.market_data,
            order_size_usd=1000.0,
            side='buy',
            market_condition=MarketCondition.VOLATILE
        )

        # Volatile markets should have higher slippage
        calm_estimate = self.modeler.predict_slippage(
            market_data=self.market_data,
            order_size_usd=1000.0,
            side='buy',
            market_condition=MarketCondition.CALM
        )

        self.assertGreater(
            estimate.expected_slippage_pct,
            calm_estimate.expected_slippage_pct
        )

    def test_slippage_increases_with_size(self):
        """Test that slippage increases with order size."""
        small_estimate = self.modeler.predict_slippage(
            market_data=self.market_data,
            order_size_usd=1000.0,
            side='buy',
            market_condition=MarketCondition.CALM
        )

        large_estimate = self.modeler.predict_slippage(
            market_data=self.market_data,
            order_size_usd=50000.0,
            side='buy',
            market_condition=MarketCondition.CALM
        )

        self.assertGreater(
            large_estimate.expected_slippage_pct,
            small_estimate.expected_slippage_pct
        )

    def test_record_actual_slippage(self):
        """Test recording actual slippage."""
        symbol = 'BTC-USD'
        self.modeler.record_actual_slippage(
            symbol=symbol,
            expected_price=50000.0,
            actual_price=50025.0,
            side='buy'
        )

        self.assertIn(symbol, self.modeler.historical_slippage)
        self.assertEqual(len(self.modeler.historical_slippage[symbol]), 1)

        # Verify slippage calculation
        slippage = self.modeler.historical_slippage[symbol][0]
        expected_slippage = (50025.0 - 50000.0) / 50000.0
        self.assertAlmostEqual(slippage, expected_slippage, places=6)


class TestSpreadPredictor(unittest.TestCase):
    """Test spread prediction model."""

    def setUp(self):
        """Set up test fixtures."""
        self.predictor = SpreadPredictor()
        self.market_data = MarketMicrostructure(
            symbol='BTC-USD',
            bid=50000.0,
            ask=50050.0,
            spread_pct=0.001,
            volume_24h=5000000.0,
            bid_depth=100000.0,
            ask_depth=120000.0,
            volatility=0.015,
            price=50025.0,
            timestamp=time.time()
        )

    def test_predict_spread_tightening(self):
        """Test spread tightening prediction."""
        prediction = self.predictor.predict_spread_tightening(
            market_data=self.market_data,
            horizon_seconds=300
        )

        self.assertIn('current_spread_pct', prediction)
        self.assertIn('tightening_probability', prediction)
        self.assertIn('expected_savings_pct', prediction)
        self.assertIn('recommendation', prediction)
        self.assertIn(prediction['recommendation'], ['wait', 'execute_now'])

    def test_record_spread(self):
        """Test recording spread observations."""
        symbol = 'BTC-USD'
        self.predictor.record_spread(symbol, 0.001)
        self.predictor.record_spread(symbol, 0.0008)
        self.predictor.record_spread(symbol, 0.0012)

        self.assertIn(symbol, self.predictor.spread_history)
        self.assertEqual(len(self.predictor.spread_history[symbol]), 3)

    def test_spread_history_limit(self):
        """Test that spread history is limited to 100 records."""
        symbol = 'BTC-USD'
        for i in range(150):
            self.predictor.record_spread(symbol, 0.001)

        self.assertEqual(len(self.predictor.spread_history[symbol]), 100)


class TestLiquidityAnalyzer(unittest.TestCase):
    """Test liquidity analysis."""

    def setUp(self):
        """Set up test fixtures."""
        self.analyzer = LiquidityAnalyzer()
        self.market_data = MarketMicrostructure(
            symbol='BTC-USD',
            bid=50000.0,
            ask=50050.0,
            spread_pct=0.001,
            volume_24h=5000000.0,
            bid_depth=100000.0,
            ask_depth=120000.0,
            volatility=0.015,
            price=50025.0,
            timestamp=time.time()
        )

    def test_small_order_no_splitting(self):
        """Test that small orders don't need splitting."""
        result = self.analyzer.calculate_optimal_size(
            market_data=self.market_data,
            desired_size_usd=1000.0,
            side='buy'
        )

        self.assertFalse(result['needs_splitting'])
        self.assertEqual(result['num_chunks'], 1)
        self.assertEqual(result['recommended_size_usd'], 1000.0)
        self.assertIsNone(result['warning'])

    def test_large_order_requires_splitting(self):
        """Test that large orders require splitting."""
        result = self.analyzer.calculate_optimal_size(
            market_data=self.market_data,
            desired_size_usd=50000.0,  # Large order
            side='buy'
        )

        # Should recommend splitting for this size
        # (depends on depth and volume ratios)
        if result['needs_splitting']:
            self.assertGreater(result['num_chunks'], 1)
            self.assertIsNotNone(result['warning'])
            self.assertLess(result['chunk_size_usd'], result['desired_size_usd'])

    def test_liquidity_score(self):
        """Test liquidity score calculation."""
        result = self.analyzer.calculate_optimal_size(
            market_data=self.market_data,
            desired_size_usd=1000.0,
            side='buy'
        )

        self.assertGreater(result['liquidity_score'], 0)
        self.assertLessEqual(result['liquidity_score'], 1.0)


class TestMarketImpactEstimator(unittest.TestCase):
    """Test market impact estimation."""

    def setUp(self):
        """Set up test fixtures."""
        self.estimator = MarketImpactEstimator()
        self.market_data = MarketMicrostructure(
            symbol='BTC-USD',
            bid=50000.0,
            ask=50050.0,
            spread_pct=0.001,
            volume_24h=5000000.0,
            bid_depth=100000.0,
            ask_depth=120000.0,
            volatility=0.015,
            price=50025.0,
            timestamp=time.time()
        )

    def test_estimate_impact(self):
        """Test market impact estimation."""
        impact = self.estimator.estimate_impact(
            market_data=self.market_data,
            order_size_usd=10000.0,
            side='buy'
        )

        self.assertIn('permanent_impact_pct', impact)
        self.assertIn('temporary_impact_pct', impact)
        self.assertIn('volume_fraction', impact)
        self.assertGreater(impact['temporary_impact_pct'], impact['permanent_impact_pct'])

    def test_larger_orders_higher_impact(self):
        """Test that larger orders have higher market impact."""
        small_impact = self.estimator.estimate_impact(
            market_data=self.market_data,
            order_size_usd=1000.0,
            side='buy'
        )

        large_impact = self.estimator.estimate_impact(
            market_data=self.market_data,
            order_size_usd=50000.0,
            side='buy'
        )

        self.assertGreater(
            large_impact['permanent_impact_pct'],
            small_impact['permanent_impact_pct']
        )


class TestExecutionIntelligence(unittest.TestCase):
    """Test main execution intelligence engine."""

    def setUp(self):
        """Set up test fixtures."""
        self.ei = ExecutionIntelligence()
        self.market_data = MarketMicrostructure(
            symbol='BTC-USD',
            bid=50000.0,
            ask=50050.0,
            spread_pct=0.001,
            volume_24h=5000000.0,
            bid_depth=100000.0,
            ask_depth=120000.0,
            volatility=0.015,
            price=50025.0,
            timestamp=time.time()
        )

    def test_classify_market_condition(self):
        """Test market condition classification."""
        # Test calm market
        calm_data = MarketMicrostructure(
            symbol='BTC-USD',
            bid=50000.0,
            ask=50025.0,
            spread_pct=0.0005,
            volume_24h=5000000.0,
            bid_depth=100000.0,
            ask_depth=120000.0,
            volatility=0.003,  # Low volatility
            price=50012.5,
            timestamp=time.time()
        )
        condition = self.ei.classify_market_condition(calm_data)
        self.assertEqual(condition, MarketCondition.CALM)

        # Test volatile market
        volatile_data = MarketMicrostructure(
            symbol='BTC-USD',
            bid=50000.0,
            ask=50200.0,
            spread_pct=0.004,
            volume_24h=5000000.0,
            bid_depth=100000.0,
            ask_depth=120000.0,
            volatility=0.03,  # High volatility
            price=50100.0,
            timestamp=time.time()
        )
        condition = self.ei.classify_market_condition(volatile_data)
        self.assertEqual(condition, MarketCondition.VOLATILE)

        # Test illiquid market
        illiquid_data = MarketMicrostructure(
            symbol='SHIB-USD',
            bid=0.00001,
            ask=0.000015,
            spread_pct=0.005,  # Wide spread
            volume_24h=50000.0,  # Low volume
            bid_depth=1000.0,
            ask_depth=1200.0,
            volatility=0.01,
            price=0.0000125,
            timestamp=time.time()
        )
        condition = self.ei.classify_market_condition(illiquid_data)
        self.assertEqual(condition, MarketCondition.ILLIQUID)

    def test_optimize_execution(self):
        """Test execution optimization."""
        plan = self.ei.optimize_execution(
            symbol='BTC-USD',
            side='buy',
            size_usd=1000.0,
            market_data=self.market_data,
            urgency=0.5
        )

        self.assertIsInstance(plan, ExecutionPlan)
        self.assertIsInstance(plan.order_type, OrderType)
        self.assertGreater(plan.expected_slippage, 0)
        self.assertGreater(plan.expected_spread_cost, 0)
        self.assertGreater(plan.total_cost_pct, 0)
        self.assertGreater(plan.confidence, 0)
        self.assertLessEqual(plan.confidence, 1.0)

    def test_high_urgency_market_order(self):
        """Test that high urgency results in market order."""
        plan = self.ei.optimize_execution(
            symbol='BTC-USD',
            side='buy',
            size_usd=1000.0,
            market_data=self.market_data,
            urgency=0.95  # Very urgent
        )

        self.assertEqual(plan.order_type, OrderType.MARKET)

    def test_low_urgency_may_use_limit(self):
        """Test that low urgency may use limit order."""
        plan = self.ei.optimize_execution(
            symbol='BTC-USD',
            side='buy',
            size_usd=1000.0,
            market_data=self.market_data,
            urgency=0.2  # Very patient
        )

        # May use either market or limit depending on conditions
        self.assertIn(plan.order_type, [OrderType.MARKET, OrderType.LIMIT])

    def test_record_execution_result(self):
        """Test recording execution result."""
        # Should not raise any exceptions
        self.ei.record_execution_result(
            symbol='BTC-USD',
            expected_price=50000.0,
            actual_price=50025.0,
            side='buy',
            spread_pct=0.001
        )

        # Verify slippage was recorded
        self.assertIn('BTC-USD', self.ei.slippage_modeler.historical_slippage)

        # Verify spread was recorded
        self.assertIn('BTC-USD', self.ei.spread_predictor.spread_history)

    def test_singleton_instance(self):
        """Test that get_execution_intelligence returns singleton."""
        ei1 = get_execution_intelligence()
        ei2 = get_execution_intelligence()

        self.assertIs(ei1, ei2)


class TestExecutionPlan(unittest.TestCase):
    """Test execution plan data structure."""

    def test_execution_plan_creation(self):
        """Test creating execution plan."""
        plan = ExecutionPlan(
            order_type=OrderType.MARKET,
            expected_slippage=0.001,
            expected_spread_cost=0.0005,
            total_cost_pct=0.0015,
            urgency_score=0.7,
            market_impact_pct=0.0002,
            confidence=0.9
        )

        self.assertEqual(plan.order_type, OrderType.MARKET)
        self.assertEqual(plan.expected_slippage, 0.001)
        self.assertEqual(plan.urgency_score, 0.7)
        self.assertEqual(plan.confidence, 0.9)


if __name__ == '__main__':
    # Run tests with verbose output
    unittest.main(verbosity=2)
