"""
Test Suite for Automated Capital Throttle

Validates:
1. Capital threshold progression
2. Risk-of-ruin parallel modeling
3. 25% drawdown stress testing before $50k
4. Dynamic position size throttling
5. Performance metric tracking
6. State persistence

Author: NIJA Trading Systems
Date: February 15, 2026
"""

import sys
import os
import logging
import numpy as np
import json
from pathlib import Path

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from automated_capital_throttle import (
    AutomatedCapitalThrottle,
    ThrottleConfig,
    ThrottleLevel,
    CapitalThreshold
)

logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def test_capital_threshold_progression():
    """Test that capital thresholds progress correctly"""
    logger.info("\n" + "=" * 70)
    logger.info("TEST 1: Capital Threshold Progression")
    logger.info("=" * 70)
    
    throttle = AutomatedCapitalThrottle(initial_capital=5000.0)
    
    # Test tier transitions
    test_cases = [
        (5000.0, 10000.0, 0.02),   # Tier 1
        (15000.0, 25000.0, 0.03),  # Tier 2
        (30000.0, 50000.0, 0.04),  # Tier 3
        (60000.0, float('inf'), 0.05)  # Tier 4
    ]
    
    for capital, expected_threshold, expected_max_pos in test_cases:
        throttle.update_capital(capital)
        assert throttle.state.current_threshold.threshold_amount == expected_threshold, \
            f"Expected threshold ${expected_threshold:,.2f}, got ${throttle.state.current_threshold.threshold_amount:,.2f}"
        assert throttle.state.current_threshold.max_position_size_pct == expected_max_pos, \
            f"Expected max position {expected_max_pos*100}%, got {throttle.state.current_threshold.max_position_size_pct*100}%"
        logger.info(f"✅ Capital ${capital:,.2f} → Threshold ${expected_threshold:,.2f}, Max Pos {expected_max_pos*100}%")
    
    logger.info("✅ TEST PASSED: Capital threshold progression working correctly")
    return True


def test_performance_tracking():
    """Test that performance metrics are tracked correctly"""
    logger.info("\n" + "=" * 70)
    logger.info("TEST 2: Performance Tracking")
    logger.info("=" * 70)
    
    throttle = AutomatedCapitalThrottle(initial_capital=10000.0)
    
    # Simulate trades
    wins = 60
    losses = 40
    
    for i in range(wins):
        throttle.record_trade(is_winner=True, profit_loss=100.0)
    
    for i in range(losses):
        throttle.record_trade(is_winner=False, profit_loss=-50.0)
    
    # Verify metrics
    assert throttle.state.total_trades == 100, f"Expected 100 trades, got {throttle.state.total_trades}"
    assert throttle.state.winning_trades == 60, f"Expected 60 wins, got {throttle.state.winning_trades}"
    assert throttle.state.losing_trades == 40, f"Expected 40 losses, got {throttle.state.losing_trades}"
    assert abs(throttle.state.current_win_rate - 0.60) < 0.01, f"Expected 60% win rate, got {throttle.state.current_win_rate*100:.1f}%"
    
    # Profit factor should be 6000/2000 = 3.0
    expected_pf = 6000.0 / 2000.0
    assert abs(throttle.state.current_profit_factor - expected_pf) < 0.1, \
        f"Expected profit factor {expected_pf:.1f}, got {throttle.state.current_profit_factor:.1f}"
    
    logger.info(f"✅ Trades: {throttle.state.total_trades}")
    logger.info(f"✅ Win Rate: {throttle.state.current_win_rate:.2%}")
    logger.info(f"✅ Profit Factor: {throttle.state.current_profit_factor:.2f}")
    logger.info("✅ TEST PASSED: Performance tracking working correctly")
    return True


def test_throttle_on_poor_performance():
    """Test that throttle activates on poor performance"""
    logger.info("\n" + "=" * 70)
    logger.info("TEST 3: Throttle on Poor Performance")
    logger.info("=" * 70)
    
    throttle = AutomatedCapitalThrottle(initial_capital=10000.0)
    
    # Simulate poor performance (30% win rate, below 50% requirement)
    for i in range(30):
        throttle.record_trade(is_winner=True, profit_loss=100.0)
    
    for i in range(70):
        throttle.record_trade(is_winner=False, profit_loss=-100.0)
    
    # Should be throttled due to low win rate
    assert throttle.state.is_throttled, "Throttle should be active with 30% win rate"
    assert "WIN_RATE_LOW" in throttle.state.throttle_reason, f"Expected WIN_RATE_LOW, got {throttle.state.throttle_reason}"
    
    # Max position size should be reduced
    max_pos = throttle.get_max_position_size()
    base_pos = throttle.state.current_threshold.max_position_size_pct
    assert max_pos < base_pos, f"Throttled position size {max_pos*100}% should be less than base {base_pos*100}%"
    
    logger.info(f"✅ Throttled: {throttle.state.is_throttled}")
    logger.info(f"✅ Reason: {throttle.state.throttle_reason}")
    logger.info(f"✅ Position Size: {max_pos*100:.2f}% (base: {base_pos*100:.2f}%)")
    logger.info("✅ TEST PASSED: Throttle activates on poor performance")
    return True


def test_drawdown_throttle():
    """Test that throttle activates on excessive drawdown"""
    logger.info("\n" + "=" * 70)
    logger.info("TEST 4: Drawdown Throttle")
    logger.info("=" * 70)
    
    throttle = AutomatedCapitalThrottle(initial_capital=10000.0)
    
    # Build up to good performance first
    for i in range(60):
        throttle.record_trade(is_winner=True, profit_loss=100.0)
        throttle.update_capital(10000.0 + (i + 1) * 100)
    
    # Peak capital should be around $16,000
    peak = throttle.state.peak_capital
    logger.info(f"Peak capital: ${peak:,.2f}")
    
    # Now simulate large drawdown (>15% for tier 1)
    drawdown_capital = peak * 0.80  # 20% drawdown
    throttle.update_capital(drawdown_capital)
    
    # Record some losing trades to trigger check
    throttle.record_trade(is_winner=False, profit_loss=-100.0)
    
    # Should be throttled due to excessive drawdown
    assert throttle.state.is_throttled, "Throttle should be active with 20% drawdown"
    assert "DRAWDOWN_EXCEEDED" in throttle.state.throttle_reason, f"Expected DRAWDOWN_EXCEEDED, got {throttle.state.throttle_reason}"
    
    logger.info(f"✅ Drawdown: {throttle.state.current_drawdown_pct:.1f}%")
    logger.info(f"✅ Throttled: {throttle.state.is_throttled}")
    logger.info(f"✅ Reason: {throttle.state.throttle_reason}")
    logger.info("✅ TEST PASSED: Drawdown throttle working correctly")
    return True


def test_stress_test_requirement():
    """Test that stress test is required before $50k threshold"""
    logger.info("\n" + "=" * 70)
    logger.info("TEST 5: Stress Test Requirement at $50k")
    logger.info("=" * 70)
    
    throttle = AutomatedCapitalThrottle(initial_capital=45000.0)
    
    # Build good performance history
    for i in range(60):
        throttle.record_trade(is_winner=True, profit_loss=500.0)
        throttle.update_capital(45000.0 + (i + 1) * 100)
    
    # Now at ~$51k, crossing $50k threshold
    throttle.update_capital(51000.0)
    
    # Should be throttled until stress test passes
    assert throttle.state.is_throttled, "Should be throttled at $50k without stress test"
    assert "STRESS_TEST_REQUIRED" in throttle.state.throttle_reason, \
        f"Expected STRESS_TEST_REQUIRED, got {throttle.state.throttle_reason}"
    
    logger.info(f"✅ Capital: ${throttle.state.current_capital:,.2f}")
    logger.info(f"✅ Throttled: {throttle.state.is_throttled}")
    logger.info(f"✅ Reason: {throttle.state.throttle_reason}")
    logger.info("✅ TEST PASSED: Stress test requirement enforced at $50k")
    return True


def test_25_percent_drawdown_simulation():
    """Test the 25% drawdown stress test"""
    logger.info("\n" + "=" * 70)
    logger.info("TEST 6: 25% Drawdown Simulation")
    logger.info("=" * 70)
    
    throttle = AutomatedCapitalThrottle(initial_capital=50000.0)
    
    # Build robust performance history (60% win rate, 2.0 profit factor)
    for i in range(60):
        throttle.record_trade(is_winner=True, profit_loss=200.0)
    
    for i in range(40):
        throttle.record_trade(is_winner=False, profit_loss=-100.0)
    
    logger.info(f"Performance: WR={throttle.state.current_win_rate:.2%}, PF={throttle.state.current_profit_factor:.2f}")
    
    # Run stress test
    results = throttle.simulate_drawdown_stress_test(
        drawdown_pct=25.0,
        duration_days=30
    )
    
    # Verify results
    assert 'passed' in results, "Results should contain 'passed' field"
    assert 'recovery_probability' in results, "Results should contain 'recovery_probability'"
    assert results['drawdown_pct'] == 25.0, "Should simulate 25% drawdown"
    
    logger.info(f"✅ Stress Test Passed: {results['passed']}")
    logger.info(f"✅ Recovery Probability: {results['recovery_probability']:.2%}")
    logger.info(f"✅ Required: {results['required_probability']:.2%}")
    
    if results['passed']:
        # Throttle should be released
        assert not throttle.state.is_throttled or throttle.state.throttle_reason != "STRESS_TEST_FAILED", \
            "Throttle should be released after passing stress test"
        logger.info("✅ Throttle released after passing stress test")
    
    logger.info("✅ TEST PASSED: 25% drawdown simulation working correctly")
    return True


def test_parallel_risk_modeling():
    """Test parallel risk-of-ruin modeling"""
    logger.info("\n" + "=" * 70)
    logger.info("TEST 7: Parallel Risk-of-Ruin Modeling")
    logger.info("=" * 70)
    
    config = ThrottleConfig()
    config.enable_parallel_risk_modeling = True
    config.risk_update_interval_trades = 20  # Run every 20 trades
    
    throttle = AutomatedCapitalThrottle(initial_capital=10000.0, config=config)
    
    # Simulate 50 trades to trigger risk analysis
    for i in range(50):
        is_winner = i % 5 != 0  # 80% win rate
        throttle.record_trade(is_winner=is_winner, profit_loss=100.0 if is_winner else -50.0)
    
    # Risk analysis should have run
    assert throttle.state.last_ruin_analysis is not None, "Risk analysis should have run"
    assert throttle.state.current_ruin_probability >= 0, "Ruin probability should be calculated"
    
    logger.info(f"✅ Trades Completed: {throttle.state.total_trades}")
    logger.info(f"✅ Risk Analysis Run: {throttle.state.last_ruin_analysis is not None}")
    logger.info(f"✅ Ruin Probability: {throttle.state.current_ruin_probability:.4%}")
    logger.info(f"✅ Risk Rating: {throttle.state.last_ruin_analysis.risk_rating if throttle.state.last_ruin_analysis else 'N/A'}")
    logger.info("✅ TEST PASSED: Parallel risk modeling working correctly")
    return True


def test_state_persistence():
    """Test that throttle state persists across instances"""
    logger.info("\n" + "=" * 70)
    logger.info("TEST 8: State Persistence")
    logger.info("=" * 70)
    
    # Create throttle and record some trades
    throttle1 = AutomatedCapitalThrottle(initial_capital=10000.0)
    
    for i in range(30):
        throttle1.record_trade(is_winner=True, profit_loss=100.0)
    
    trades_count = throttle1.state.total_trades
    win_rate = throttle1.state.current_win_rate
    
    logger.info(f"Instance 1: Trades={trades_count}, WR={win_rate:.2%}")
    
    # Create new instance (should load saved state)
    throttle2 = AutomatedCapitalThrottle(initial_capital=10000.0)
    
    # Verify state loaded
    assert throttle2.state.total_trades == trades_count, \
        f"Expected {trades_count} trades, got {throttle2.state.total_trades}"
    assert abs(throttle2.state.current_win_rate - win_rate) < 0.01, \
        f"Expected {win_rate:.2%} win rate, got {throttle2.state.current_win_rate:.2%}"
    
    logger.info(f"Instance 2: Trades={throttle2.state.total_trades}, WR={throttle2.state.current_win_rate:.2%}")
    logger.info("✅ TEST PASSED: State persistence working correctly")
    
    # Cleanup
    if throttle2.THROTTLE_FILE.exists():
        throttle2.THROTTLE_FILE.unlink()
    
    return True


def test_status_report():
    """Test comprehensive status report"""
    logger.info("\n" + "=" * 70)
    logger.info("TEST 9: Status Report")
    logger.info("=" * 70)
    
    throttle = AutomatedCapitalThrottle(initial_capital=25000.0)
    
    # Simulate some activity
    for i in range(50):
        is_winner = i % 3 != 0  # ~67% win rate
        throttle.record_trade(is_winner=is_winner, profit_loss=200.0 if is_winner else -100.0)
        throttle.update_capital(25000.0 + i * 100)
    
    # Get status report
    status = throttle.get_status_report()
    
    # Verify report structure
    required_sections = ['capital', 'threshold', 'performance', 'risk', 'throttle', 'stress_test']
    for section in required_sections:
        assert section in status, f"Status report missing '{section}' section"
    
    # Verify data
    assert status['capital']['current'] == throttle.state.current_capital
    assert status['performance']['total_trades'] == throttle.state.total_trades
    assert status['throttle']['is_throttled'] == throttle.state.is_throttled
    
    logger.info("✅ Status Report Structure:")
    for section in required_sections:
        logger.info(f"  ✅ {section}: {list(status[section].keys())}")
    
    logger.info("\n📊 Full Status Report:")
    logger.info(json.dumps(status, indent=2, default=str))
    
    logger.info("\n✅ TEST PASSED: Status report working correctly")
    return True


def run_all_tests():
    """Run all tests"""
    logger.info("\n" + "=" * 70)
    logger.info("AUTOMATED CAPITAL THROTTLE - TEST SUITE")
    logger.info("=" * 70)
    
    tests = [
        ("Capital Threshold Progression", test_capital_threshold_progression),
        ("Performance Tracking", test_performance_tracking),
        ("Throttle on Poor Performance", test_throttle_on_poor_performance),
        ("Drawdown Throttle", test_drawdown_throttle),
        ("Stress Test Requirement", test_stress_test_requirement),
        ("25% Drawdown Simulation", test_25_percent_drawdown_simulation),
        ("Parallel Risk Modeling", test_parallel_risk_modeling),
        ("State Persistence", test_state_persistence),
        ("Status Report", test_status_report)
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except Exception as e:
            logger.error(f"❌ TEST FAILED: {test_name}")
            logger.error(f"   Error: {str(e)}")
            failed += 1
    
    logger.info("\n" + "=" * 70)
    logger.info("TEST RESULTS")
    logger.info("=" * 70)
    logger.info(f"✅ Passed: {passed}/{len(tests)}")
    logger.info(f"❌ Failed: {failed}/{len(tests)}")
    
    if failed == 0:
        logger.info("\n🎉 ALL TESTS PASSED!")
    else:
        logger.error(f"\n⚠️ {failed} TEST(S) FAILED")
    
    logger.info("=" * 70)
    
    return failed == 0


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
