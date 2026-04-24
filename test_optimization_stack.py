"""
Test Suite for NIJA Optimization Algorithms Stack
=================================================

Tests all optimization layers and integration.

Author: NIJA Trading Systems
Version: 1.0
Date: January 30, 2026
"""

import sys
import os
import unittest
from unittest.mock import Mock, patch
import numpy as np

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.optimization_stack import (
    OptimizationStack,
    OptimizationLayer,
    BayesianOptimizer,
    KalmanFilter,
    HeuristicRegimeSwitcher,
    create_optimization_stack,
)
from bot.optimization_stack_config import (
    get_optimization_config,
    PERFORMANCE_TARGETS,
)


class TestBayesianOptimizer(unittest.TestCase):
    """Test Bayesian optimization layer"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.parameter_bounds = {
            'rsi_oversold': (20.0, 35.0),
            'rsi_overbought': (65.0, 80.0),
        }
        self.optimizer = BayesianOptimizer(self.parameter_bounds)
    
    def test_initialization(self):
        """Test optimizer initialization"""
        self.assertEqual(len(self.optimizer.parameter_bounds), 2)
        self.assertEqual(len(self.optimizer.observations), 0)
        self.assertIsNone(self.optimizer.best_params)
    
    def test_suggest_parameters(self):
        """Test parameter suggestion"""
        params = self.optimizer.suggest_parameters()
        
        # Check all parameters are present
        self.assertIn('rsi_oversold', params)
        self.assertIn('rsi_overbought', params)
        
        # Check parameters are within bounds
        self.assertGreaterEqual(params['rsi_oversold'], 20.0)
        self.assertLessEqual(params['rsi_oversold'], 35.0)
        self.assertGreaterEqual(params['rsi_overbought'], 65.0)
        self.assertLessEqual(params['rsi_overbought'], 80.0)
    
    def test_update_performance(self):
        """Test performance update"""
        params = {'rsi_oversold': 30.0, 'rsi_overbought': 70.0}
        performance = 0.05  # 5% return
        
        self.optimizer.update(params, performance)
        
        self.assertEqual(len(self.optimizer.observations), 1)
        self.assertEqual(self.optimizer.best_performance, 0.05)
        self.assertEqual(self.optimizer.best_params, params)
    
    def test_multiple_updates(self):
        """Test multiple performance updates"""
        params1 = {'rsi_oversold': 30.0, 'rsi_overbought': 70.0}
        params2 = {'rsi_oversold': 25.0, 'rsi_overbought': 75.0}
        
        self.optimizer.update(params1, 0.05)
        self.optimizer.update(params2, 0.08)  # Better performance
        
        self.assertEqual(len(self.optimizer.observations), 2)
        self.assertEqual(self.optimizer.best_performance, 0.08)
        self.assertEqual(self.optimizer.best_params, params2)


class TestKalmanFilter(unittest.TestCase):
    """Test Kalman filter layer"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.filter = KalmanFilter()
    
    def test_initialization(self):
        """Test filter initialization"""
        self.assertIsNone(self.filter.state_estimate)
        self.assertEqual(self.filter.error_estimate, 1.0)
    
    def test_first_update(self):
        """Test first measurement update"""
        measurement = 100.0
        estimate = self.filter.update(measurement)
        
        self.assertEqual(estimate, measurement)
        self.assertEqual(self.filter.state_estimate, measurement)
    
    def test_noise_filtering(self):
        """Test noise filtering"""
        # Set random seed for reproducibility
        np.random.seed(42)
        
        # Create noisy signal
        true_value = 100.0
        measurements = [true_value + np.random.normal(0, 10) for _ in range(100)]
        
        # Filter measurements
        filtered = [self.filter.update(m) for m in measurements]
        
        # Last estimate should be closer to true value than raw measurements
        avg_measurement_error = np.mean([abs(m - true_value) for m in measurements])
        filtered_error = abs(filtered[-1] - true_value)
        
        # Filtered error should be less than average measurement error
        self.assertLess(filtered_error, avg_measurement_error * 1.5)


class TestHeuristicRegimeSwitcher(unittest.TestCase):
    """Test heuristic regime switching layer"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.switcher = HeuristicRegimeSwitcher()
    
    def test_initialization(self):
        """Test switcher initialization"""
        self.assertEqual(self.switcher.current_regime, "normal")
        self.assertEqual(self.switcher.switch_count, 0)
    
    def test_normal_regime(self):
        """Test normal regime detection"""
        market_data = {
            'volatility': 1.0,
            'drawdown': 0.01,
            'correlation': 0.5,
        }
        
        regime = self.switcher.detect_regime(market_data)
        self.assertEqual(regime, "normal")
    
    def test_volatile_regime(self):
        """Test volatile regime detection"""
        market_data = {
            'volatility': 3.0,  # > 2.5x threshold
            'drawdown': 0.01,
            'correlation': 0.5,
        }
        
        regime = self.switcher.detect_regime(market_data)
        self.assertEqual(regime, "volatile")
    
    def test_crisis_regime(self):
        """Test crisis regime detection"""
        market_data = {
            'volatility': 2.5,
            'drawdown': 0.03,
            'correlation': 0.2,  # < 0.3 threshold
        }
        
        regime = self.switcher.detect_regime(market_data)
        self.assertEqual(regime, "crisis")
    
    def test_defensive_regime(self):
        """Test defensive regime detection"""
        market_data = {
            'volatility': 1.5,
            'drawdown': 0.06,  # > 0.05 threshold
            'correlation': 0.5,
        }
        
        regime = self.switcher.detect_regime(market_data)
        self.assertEqual(regime, "defensive")
    
    def test_regime_parameters(self):
        """Test regime-specific parameters"""
        params = self.switcher.get_regime_parameters('volatile')
        
        self.assertEqual(params['position_size_multiplier'], 0.5)
        self.assertEqual(params['stop_loss_multiplier'], 1.5)
    
    def test_regime_switch_tracking(self):
        """Test regime switch counting"""
        # Start in normal
        self.assertEqual(self.switcher.switch_count, 0)
        
        # Switch to volatile
        market_data = {'volatility': 3.0, 'drawdown': 0.01, 'correlation': 0.5}
        self.switcher.detect_regime(market_data)
        self.assertEqual(self.switcher.switch_count, 1)
        
        # Stay in volatile (no switch)
        self.switcher.detect_regime(market_data)
        self.assertEqual(self.switcher.switch_count, 1)
        
        # Switch back to normal
        market_data = {'volatility': 1.0, 'drawdown': 0.01, 'correlation': 0.5}
        self.switcher.detect_regime(market_data)
        self.assertEqual(self.switcher.switch_count, 2)


class TestOptimizationStack(unittest.TestCase):
    """Test full optimization stack"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.stack = OptimizationStack()
    
    def test_initialization(self):
        """Test stack initialization"""
        self.assertIsNotNone(self.stack.regime_switcher)
        self.assertEqual(len(self.stack.active_layers), 0)
    
    def test_enable_fast_layer(self):
        """Test enabling fast (Bayesian) layer"""
        self.stack.enable_layer(OptimizationLayer.FAST)
        
        self.assertIn(OptimizationLayer.FAST, self.stack.active_layers)
        self.assertIsNotNone(self.stack.bayesian_optimizer)
    
    def test_enable_emergency_layer(self):
        """Test enabling emergency layer"""
        self.stack.enable_layer(OptimizationLayer.EMERGENCY)
        
        self.assertIn(OptimizationLayer.EMERGENCY, self.stack.active_layers)
    
    def test_enable_stability_layer(self):
        """Test enabling stability (Kalman) layer"""
        self.stack.enable_layer(OptimizationLayer.STABILITY)
        
        self.assertIn(OptimizationLayer.STABILITY, self.stack.active_layers)
        # Should create filters for key metrics
        self.assertGreater(len(self.stack.kalman_filters), 0)
    
    def test_optimize_entry_timing(self):
        """Test entry timing optimization"""
        self.stack.enable_layer(OptimizationLayer.FAST)
        
        market_data = {
            'volatility': 1.2,
            'drawdown': 0.02,
            'correlation': 0.6,
            'rsi': 45.0,
        }
        
        params = self.stack.optimize_entry_timing(market_data)
        
        # Should return parameter dictionary
        self.assertIsInstance(params, dict)
        self.assertIn('rsi_oversold', params)
        self.assertIn('rsi_overbought', params)
    
    def test_optimize_position_size(self):
        """Test position size optimization"""
        self.stack.enable_layer(OptimizationLayer.EMERGENCY)
        
        market_data = {
            'volatility': 1.2,
            'drawdown': 0.02,
            'correlation': 0.6,
        }
        
        base_size = 1000.0
        optimized_size = self.stack.optimize_position_size(
            symbol='BTC-USD',
            market_data=market_data,
            base_size=base_size
        )
        
        # Should return a number
        self.assertIsInstance(optimized_size, float)
        # Should be positive
        self.assertGreater(optimized_size, 0)
    
    def test_get_filtered_value(self):
        """Test Kalman filtering"""
        self.stack.enable_layer(OptimizationLayer.STABILITY)
        
        # Filter a noisy signal
        raw_value = 100.0
        filtered_value = self.stack.get_filtered_value('price', raw_value)
        
        # Should return a filtered value
        self.assertIsInstance(filtered_value, float)
    
    def test_performance_metrics(self):
        """Test performance metrics tracking"""
        metrics = self.stack.get_performance_metrics()
        
        self.assertEqual(metrics.total_gain_pct, 0.0)
        self.assertIsInstance(metrics.active_layers, list)
    
    def test_status_reporting(self):
        """Test status reporting"""
        self.stack.enable_layer(OptimizationLayer.FAST)
        self.stack.enable_layer(OptimizationLayer.EMERGENCY)
        
        status = self.stack.get_status()
        
        self.assertIn('active_layers', status)
        self.assertIn('current_regime', status)
        self.assertIn('regime_switches', status)
        
        self.assertEqual(len(status['active_layers']), 2)


class TestStackIntegration(unittest.TestCase):
    """Test full stack integration"""
    
    def test_create_optimization_stack(self):
        """Test convenience function"""
        stack = create_optimization_stack(enable_all=True)
        
        # Should enable all layers
        self.assertIn(OptimizationLayer.FAST, stack.active_layers)
        self.assertIn(OptimizationLayer.EMERGENCY, stack.active_layers)
        self.assertIn(OptimizationLayer.STABILITY, stack.active_layers)
    
    def test_partial_stack(self):
        """Test creating partial stack"""
        stack = create_optimization_stack(enable_all=False)
        
        # Should have no active layers
        self.assertEqual(len(stack.active_layers), 0)


class TestConfiguration(unittest.TestCase):
    """Test configuration system"""
    
    def test_get_bayesian_config(self):
        """Test getting Bayesian config"""
        config = get_optimization_config('bayesian')
        
        self.assertIn('parameter_bounds', config)
        self.assertIn('max_iterations', config)
    
    def test_get_genetic_config(self):
        """Test getting genetic config"""
        config = get_optimization_config('genetic')
        
        self.assertIn('population_size', config)
        self.assertIn('generations', config)
    
    def test_get_full_config(self):
        """Test getting full config"""
        config = get_optimization_config()
        
        self.assertIn('bayesian', config)
        self.assertIn('genetic', config)
        self.assertIn('performance_targets', config)
    
    def test_performance_targets(self):
        """Test performance target definitions"""
        self.assertIn('volatility_adaptive_sizing', PERFORMANCE_TARGETS)
        self.assertIn('entry_timing_tuning', PERFORMANCE_TARGETS)
        
        # Check target structure
        target = PERFORMANCE_TARGETS['volatility_adaptive_sizing']
        self.assertIn('min', target)
        self.assertIn('target', target)
        self.assertIn('max', target)


def run_tests():
    """Run all tests"""
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add all test classes
    suite.addTests(loader.loadTestsFromTestCase(TestBayesianOptimizer))
    suite.addTests(loader.loadTestsFromTestCase(TestKalmanFilter))
    suite.addTests(loader.loadTestsFromTestCase(TestHeuristicRegimeSwitcher))
    suite.addTests(loader.loadTestsFromTestCase(TestOptimizationStack))
    suite.addTests(loader.loadTestsFromTestCase(TestStackIntegration))
    suite.addTests(loader.loadTestsFromTestCase(TestConfiguration))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Return success status
    return result.wasSuccessful()


if __name__ == '__main__':
    success = run_tests()
    sys.exit(0 if success else 1)
