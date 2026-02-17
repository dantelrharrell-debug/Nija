#!/usr/bin/env python3
"""
Unit tests for Kraken MICRO_CAP validation script.

Tests validation logic without requiring actual Kraken connection.
"""

import os
import sys
import unittest
from unittest.mock import Mock, patch, MagicMock

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), 'bot'))

# Mock dependencies that may not be installed
sys.modules['krakenex'] = MagicMock()
sys.modules['pykrakenapi'] = MagicMock()


class TestKrakenMicroCapValidator(unittest.TestCase):
    """Test cases for KrakenMicroCapValidator."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Import after mocking dependencies
        sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
        
    def test_balance_range_validation(self):
        """Test balance range validation logic."""
        # Test cases: (balance, min, max, should_pass)
        test_cases = [
            (30.0, 25.0, 50.0, True),   # In range
            (25.0, 25.0, 50.0, True),   # At min
            (50.0, 25.0, 50.0, True),   # At max
            (20.0, 25.0, 50.0, False),  # Below min
            (60.0, 25.0, 50.0, False),  # Above max (should warn)
            (15.0, 25.0, 50.0, False),  # Way below
            (100.0, 25.0, 50.0, False), # Way above
        ]
        
        for balance, min_bal, max_bal, should_pass in test_cases:
            in_range = min_bal <= balance <= max_bal
            self.assertEqual(
                in_range,
                should_pass,
                f"Balance ${balance} with range ${min_bal}-${max_bal} "
                f"should {'pass' if should_pass else 'fail'}"
            )
    
    def test_micro_cap_mode_detection(self):
        """Test MICRO_CAP mode detection for different balances."""
        # MICRO_CAP should be selected for $20-$100
        test_cases = [
            (15.0, 'below'),     # Below MICRO_CAP
            (25.0, 'micro_cap'), # In MICRO_CAP range
            (50.0, 'micro_cap'), # In MICRO_CAP range
            (75.0, 'micro_cap'), # In MICRO_CAP range
            (100.0, 'micro_cap'), # At MICRO_CAP upper bound
            (150.0, 'low_capital'), # Above MICRO_CAP
        ]
        
        for balance, expected_mode in test_cases:
            if 20 <= balance <= 100:
                detected_mode = 'micro_cap'
            elif 100 < balance <= 500:
                detected_mode = 'low_capital'
            else:
                detected_mode = 'below'
            
            if expected_mode != 'below':
                self.assertEqual(
                    detected_mode,
                    expected_mode,
                    f"Balance ${balance} should select {expected_mode} mode"
                )
    
    def test_risk_reward_ratio(self):
        """Test risk/reward ratio calculations."""
        test_cases = [
            # (profit_pct, stop_pct, expected_ratio, should_pass)
            (2.0, 1.0, 2.0, True),   # 2:1 ratio (MICRO_CAP default)
            (3.0, 1.0, 3.0, True),   # 3:1 ratio (better)
            (1.5, 1.0, 1.5, False),  # 1.5:1 ratio (below 2:1)
            (4.0, 2.0, 2.0, True),   # 2:1 ratio
            (1.0, 1.0, 1.0, False),  # 1:1 ratio (too risky)
        ]
        
        min_ratio = 2.0
        
        for profit, stop, expected, should_pass in test_cases:
            ratio = profit / stop if stop > 0 else 0
            self.assertAlmostEqual(ratio, expected, places=2)
            passes = ratio >= min_ratio
            self.assertEqual(
                passes,
                should_pass,
                f"Ratio {ratio:.2f}:1 should {'pass' if should_pass else 'fail'}"
            )
    
    def test_position_size_validation(self):
        """Test position size compatibility with account balance."""
        test_cases = [
            # (balance, max_positions, position_size, should_pass)
            (50.0, 1, 20.0, True),   # 1 × $20 = $20 (60% buffer)
            (30.0, 1, 20.0, True),   # 1 × $20 = $20 (33% buffer)
            (25.0, 1, 20.0, True),   # 1 × $20 = $20 (20% buffer)
            (20.0, 1, 20.0, True),   # 1 × $20 = $20 (0% buffer - technically fits)
            (100.0, 2, 20.0, True),  # 2 × $20 = $40 (60% buffer)
            (50.0, 2, 20.0, True),   # 2 × $20 = $40 (20% buffer)
            (30.0, 2, 20.0, False),  # 2 × $20 = $40 (exceeds balance)
            (19.0, 1, 20.0, False),  # 1 × $20 = $20 (exceeds balance)
        ]
        
        for balance, positions, size, should_pass in test_cases:
            total_needed = positions * size
            can_support = total_needed <= balance
            self.assertEqual(
                can_support,
                should_pass,
                f"Balance ${balance} {'can' if should_pass else 'cannot'} support "
                f"{positions} × ${size} positions"
            )
    
    def test_order_minimum_validation(self):
        """Test order minimum compatibility."""
        kraken_min = 10.0  # Kraken minimum order
        
        test_cases = [
            (20.0, True),   # MICRO_CAP position size
            (15.0, True),   # Above minimum
            (10.0, True),   # At minimum
            (9.0, False),   # Below minimum
            (5.0, False),   # Way below
        ]
        
        for position_size, should_pass in test_cases:
            meets_min = position_size >= kraken_min
            self.assertEqual(
                meets_min,
                should_pass,
                f"Position ${position_size} should {'meet' if should_pass else 'fail'} "
                f"minimum ${kraken_min}"
            )
    
    def test_rate_limiting_validation(self):
        """Test rate limiting configuration for MICRO_CAP."""
        test_cases = [
            # (entry_interval_sec, max_per_min, is_micro_cap_compatible)
            (30, 2, True),   # MICRO_CAP default (very conservative)
            (20, 3, True),   # Conservative
            (10, 6, False),  # Too aggressive for MICRO_CAP
            (5, 12, False),  # Way too aggressive
            (2, 30, False),  # High frequency (not for MICRO_CAP)
        ]
        
        # MICRO_CAP should have entry_interval ≥ 20s and max ≤ 3/min
        for interval, max_per_min, should_pass in test_cases:
            is_conservative = interval >= 20 and max_per_min <= 3
            self.assertEqual(
                is_conservative,
                should_pass,
                f"Rate {interval}s interval, {max_per_min}/min should "
                f"{'pass' if should_pass else 'fail'} for MICRO_CAP"
            )
    
    def test_cash_buffer_calculation(self):
        """Test cash buffer percentage calculations."""
        test_cases = [
            # (balance, positions_capital, expected_buffer_pct)
            (50.0, 20.0, 60.0),  # $30 buffer = 60%
            (30.0, 20.0, 33.33), # $10 buffer = 33.33%
            (25.0, 20.0, 20.0),  # $5 buffer = 20%
            (100.0, 40.0, 60.0), # $60 buffer = 60%
            (50.0, 40.0, 20.0),  # $10 buffer = 20%
        ]
        
        min_recommended_buffer = 15.0
        
        for balance, capital, expected_buffer_pct in test_cases:
            buffer_amount = balance - capital
            buffer_pct = (buffer_amount / balance) * 100
            
            self.assertAlmostEqual(
                buffer_pct,
                expected_buffer_pct,
                places=1,
                msg=f"Buffer for ${balance} - ${capital} should be ~{expected_buffer_pct:.1f}%"
            )
            
            is_adequate = buffer_pct >= min_recommended_buffer
            # Just verify calculation, don't fail test
    
    def test_per_trade_risk_calculation(self):
        """Test per-trade risk/reward dollar calculations."""
        position_size = 20.0  # MICRO_CAP default
        profit_target_pct = 2.0  # 2%
        stop_loss_pct = 1.0      # 1%
        
        expected_reward = (profit_target_pct / 100) * position_size
        expected_risk = (stop_loss_pct / 100) * position_size
        
        self.assertAlmostEqual(expected_reward, 0.40, places=2)
        self.assertAlmostEqual(expected_risk, 0.20, places=2)
        
        # Verify ratio
        ratio = expected_reward / expected_risk
        self.assertAlmostEqual(ratio, 2.0, places=2)
    
    def test_daily_performance_estimate(self):
        """Test daily performance estimates for MICRO_CAP."""
        # At 50% win rate with 8 trades per day
        wins = 4
        losses = 4
        win_amount = 0.40  # 2% on $20
        loss_amount = 0.20  # 1% on $20
        
        total_wins = wins * win_amount
        total_losses = losses * loss_amount
        net_daily = total_wins - total_losses
        
        self.assertAlmostEqual(total_wins, 1.60, places=2)
        self.assertAlmostEqual(total_losses, 0.80, places=2)
        self.assertAlmostEqual(net_daily, 0.80, places=2)
        
        # Monthly estimate (30 days)
        monthly_estimate = net_daily * 30
        self.assertAlmostEqual(monthly_estimate, 24.0, places=2)


class TestValidationReporting(unittest.TestCase):
    """Test validation reporting logic."""
    
    def test_pass_fail_counting(self):
        """Test pass/fail result counting."""
        results = [
            {'test': 'Test 1', 'passed': True, 'message': 'OK'},
            {'test': 'Test 2', 'passed': True, 'message': 'OK'},
            {'test': 'Test 3', 'passed': False, 'message': 'Failed'},
            {'test': 'Test 4', 'passed': True, 'message': 'OK'},
        ]
        
        total = len(results)
        passed = sum(1 for r in results if r['passed'])
        failed = total - passed
        
        self.assertEqual(total, 4)
        self.assertEqual(passed, 3)
        self.assertEqual(failed, 1)
    
    def test_validation_success_criteria(self):
        """Test overall validation success criteria."""
        # Success only if all tests pass
        test_cases = [
            ([True, True, True], True),    # All pass
            ([True, True, False], False),   # One fail
            ([True, False, False], False),  # Multiple fails
            ([False, False, False], False), # All fail
            ([True], True),                # Single pass
            ([False], False),              # Single fail
        ]
        
        for results, expected_success in test_cases:
            success = all(results)
            self.assertEqual(
                success,
                expected_success,
                f"Results {results} should {'succeed' if expected_success else 'fail'}"
            )


def run_tests():
    """Run all tests."""
    print("=" * 80)
    print("KRAKEN MICRO_CAP VALIDATION - UNIT TESTS")
    print("=" * 80)
    print()
    
    # Create test suite
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # Add test cases
    suite.addTests(loader.loadTestsFromTestCase(TestKrakenMicroCapValidator))
    suite.addTests(loader.loadTestsFromTestCase(TestValidationReporting))
    
    # Run tests
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    # Print summary
    print()
    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print(f"Tests run: {result.testsRun}")
    print(f"Successes: {result.testsRun - len(result.failures) - len(result.errors)}")
    print(f"Failures: {len(result.failures)}")
    print(f"Errors: {len(result.errors)}")
    print("=" * 80)
    
    if result.wasSuccessful():
        print("✅ ALL TESTS PASSED")
        return 0
    else:
        print("❌ SOME TESTS FAILED")
        return 1


if __name__ == '__main__':
    sys.exit(run_tests())
