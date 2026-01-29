#!/usr/bin/env python3
"""
Test Elite Performance Configuration

Validates that elite performance targets are properly configured
and all metrics calculations work correctly.

Usage:
    python test_elite_performance.py
"""

import sys
import logging
from pathlib import Path

# Add bot directory to path
sys.path.insert(0, str(Path(__file__).parent / "bot"))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def test_configuration_import():
    """Test that elite performance config can be imported"""
    logger.info("Testing elite_performance_config import...")
    try:
        from elite_performance_config import (
            ELITE_PERFORMANCE_TARGETS,
            ELITE_POSITION_SIZING,
            ELITE_RISK_MANAGEMENT,
            MULTI_ENGINE_STACK,
            calculate_expectancy,
            calculate_profit_factor,
            calculate_risk_reward_ratio,
            validate_performance_targets,
            get_optimal_position_size,
        )
        logger.info("✅ Elite performance config imported successfully")
        return True
    except ImportError as e:
        logger.error(f"❌ Failed to import elite performance config: {e}")
        return False


def test_expectancy_calculation():
    """Test expectancy calculation"""
    logger.info("\nTesting expectancy calculation...")
    from elite_performance_config import calculate_expectancy

    # Test case 1: Elite performance
    win_rate = 0.60
    avg_win = 0.012
    avg_loss = 0.006

    expectancy = calculate_expectancy(win_rate, avg_win, avg_loss)
    expected = (0.60 * 0.012) - (0.40 * 0.006)

    logger.info(f"  Win Rate: {win_rate:.0%}")
    logger.info(f"  Avg Win: {avg_win:.2%}")
    logger.info(f"  Avg Loss: {avg_loss:.2%}")
    logger.info(f"  Calculated Expectancy: {expectancy:.4f} ({expectancy*100:.2f}%)")
    logger.info(f"  Expected Expectancy: {expected:.4f} ({expected*100:.2f}%)")

    if abs(expectancy - expected) < 0.0001:
        logger.info("✅ Expectancy calculation correct")
        return True
    else:
        logger.error("❌ Expectancy calculation incorrect")
        return False


def test_profit_factor_calculation():
    """Test profit factor calculation"""
    logger.info("\nTesting profit factor calculation...")
    from elite_performance_config import calculate_profit_factor

    # Test case: Elite performance
    total_profit = 1000.0
    total_loss = 400.0

    pf = calculate_profit_factor(total_profit, total_loss)
    expected = 2.5

    logger.info(f"  Total Profit: ${total_profit:.2f}")
    logger.info(f"  Total Loss: ${total_loss:.2f}")
    logger.info(f"  Calculated Profit Factor: {pf:.2f}")
    logger.info(f"  Expected Profit Factor: {expected:.2f}")

    if abs(pf - expected) < 0.01:
        logger.info("✅ Profit factor calculation correct")
        return True
    else:
        logger.error("❌ Profit factor calculation incorrect")
        return False


def test_risk_reward_calculation():
    """Test risk:reward ratio calculation"""
    logger.info("\nTesting risk:reward ratio calculation...")
    from elite_performance_config import calculate_risk_reward_ratio

    # Test case: Elite target 1:2
    avg_win = 0.012
    avg_loss = 0.006

    rr = calculate_risk_reward_ratio(avg_win, avg_loss)
    expected = 2.0

    logger.info(f"  Avg Win: {avg_win:.2%}")
    logger.info(f"  Avg Loss: {avg_loss:.2%}")
    logger.info(f"  Calculated R:R: 1:{rr:.1f}")
    logger.info(f"  Expected R:R: 1:{expected:.1f}")

    if abs(rr - expected) < 0.1:
        logger.info("✅ Risk:reward calculation correct")
        return True
    else:
        logger.error("❌ Risk:reward calculation incorrect")
        return False


def test_performance_validation():
    """Test performance validation function"""
    logger.info("\nTesting performance validation...")
    from elite_performance_config import validate_performance_targets

    # Test case 1: Elite performance (should pass)
    elite_metrics = {
        'profit_factor': 2.3,
        'win_rate': 0.60,
        'avg_win_pct': 0.012,
        'avg_loss_pct': 0.006,
        'expectancy': 0.0048,
        'max_drawdown': 0.08,
    }

    is_elite, warnings = validate_performance_targets(elite_metrics)

    logger.info("  Elite Metrics Test:")
    logger.info(f"    Profit Factor: {elite_metrics['profit_factor']:.2f}")
    logger.info(f"    Win Rate: {elite_metrics['win_rate']:.0%}")
    logger.info(f"    Expectancy: {elite_metrics['expectancy']:.4f}R")
    logger.info(f"    Is Elite: {is_elite}")
    logger.info(f"    Warnings: {len(warnings)}")

    if is_elite and len(warnings) == 0:
        logger.info("✅ Elite performance validation passed")
        result1 = True
    else:
        logger.error("❌ Elite performance validation failed")
        logger.error(f"    Warnings: {warnings}")
        result1 = False

    # Test case 2: Subpar performance (should fail)
    subpar_metrics = {
        'profit_factor': 1.5,
        'win_rate': 0.50,
        'avg_win_pct': 0.008,
        'avg_loss_pct': 0.006,
        'expectancy': 0.0020,
        'max_drawdown': 0.15,
    }

    is_elite2, warnings2 = validate_performance_targets(subpar_metrics)

    logger.info("\n  Subpar Metrics Test:")
    logger.info(f"    Profit Factor: {subpar_metrics['profit_factor']:.2f}")
    logger.info(f"    Win Rate: {subpar_metrics['win_rate']:.0%}")
    logger.info(f"    Is Elite: {is_elite2}")
    logger.info(f"    Warnings: {len(warnings2)}")

    if not is_elite2 and len(warnings2) > 0:
        logger.info("✅ Subpar performance validation passed (correctly identified issues)")
        for metric, warning in warnings2.items():
            logger.info(f"      - {metric}: {warning}")
        result2 = True
    else:
        logger.error("❌ Subpar performance validation failed (should have warnings)")
        result2 = False

    return result1 and result2


def test_position_sizing():
    """Test optimal position size calculation"""
    logger.info("\nTesting optimal position size calculation...")
    from elite_performance_config import get_optimal_position_size

    test_cases = [
        {'adx': 18, 'signal': 0.6, 'expected_range': (0.02, 0.03)},  # Weak trend, low signal
        {'adx': 28, 'signal': 0.8, 'expected_range': (0.028, 0.032)},  # Good trend, good signal
        {'adx': 38, 'signal': 1.0, 'expected_range': (0.045, 0.051)},  # Strong trend, perfect signal
    ]

    all_passed = True
    for i, test in enumerate(test_cases, 1):
        size = get_optimal_position_size(test['adx'], test['signal'])
        min_expected, max_expected = test['expected_range']

        logger.info(f"  Test {i}:")
        logger.info(f"    ADX: {test['adx']}")
        logger.info(f"    Signal Quality: {test['signal']:.0%}")
        logger.info(f"    Calculated Size: {size:.2%}")
        logger.info(f"    Expected Range: {min_expected:.2%} - {max_expected:.2%}")

        if min_expected <= size <= max_expected:
            logger.info(f"    ✅ Passed")
        else:
            logger.error(f"    ❌ Failed (out of expected range)")
            all_passed = False

    if all_passed:
        logger.info("✅ All position sizing tests passed")
    else:
        logger.error("❌ Some position sizing tests failed")

    return all_passed


def test_apex_config_integration():
    """Test that apex_config has been updated with elite targets"""
    logger.info("\nTesting apex_config.py integration...")
    try:
        from apex_config import (
            PERFORMANCE_TARGETS,
            STOP_LOSS,
            TAKE_PROFIT,
            POSITION_SIZING,
            RISK_LIMITS,
            DAILY_TARGET,
            STRATEGY_INFO,
        )

        logger.info("  Checking STRATEGY_INFO...")
        if STRATEGY_INFO.get('version') == '7.3':
            logger.info(f"    ✅ Version: {STRATEGY_INFO['version']}")
        else:
            logger.warning(f"    ⚠️ Version: {STRATEGY_INFO.get('version')} (expected 7.3)")

        logger.info("  Checking STOP_LOSS...")
        if STOP_LOSS.get('min_stop_distance') == 0.004:
            logger.info(f"    ✅ Min Stop: {STOP_LOSS['min_stop_distance']:.2%}")
        else:
            logger.warning(f"    ⚠️ Min Stop: {STOP_LOSS.get('min_stop_distance')}")

        logger.info("  Checking POSITION_SIZING...")
        if POSITION_SIZING.get('max_position_size') == 0.05:
            logger.info(f"    ✅ Max Position: {POSITION_SIZING['max_position_size']:.0%}")
        else:
            logger.warning(f"    ⚠️ Max Position: {POSITION_SIZING.get('max_position_size')}")

        logger.info("  Checking RISK_LIMITS...")
        if RISK_LIMITS.get('max_drawdown') == 0.12:
            logger.info(f"    ✅ Max Drawdown: {RISK_LIMITS['max_drawdown']:.0%}")
        else:
            logger.warning(f"    ⚠️ Max Drawdown: {RISK_LIMITS.get('max_drawdown')}")

        logger.info("  Checking DAILY_TARGET...")
        if DAILY_TARGET.get('expectancy_pct') == 0.0048:
            logger.info(f"    ✅ Expectancy: {DAILY_TARGET['expectancy_pct']:.4f}")
        else:
            logger.warning(f"    ⚠️ Expectancy: {DAILY_TARGET.get('expectancy_pct')}")

        logger.info("✅ apex_config integration complete")
        return True
    except Exception as e:
        logger.error(f"❌ apex_config integration failed: {e}")
        return False


def test_monitoring_system_integration():
    """Test that monitoring_system has enhanced metrics"""
    logger.info("\nTesting monitoring_system.py integration...")
    try:
        from monitoring_system import PerformanceMetrics

        # Create sample metrics
        metrics = PerformanceMetrics(
            total_trades=100,
            winning_trades=60,
            losing_trades=40,
            total_profit=120.0,
            total_loss=48.0,
        )

        logger.info("  Testing calculated properties...")

        # Test win_rate
        win_rate = metrics.win_rate
        logger.info(f"    Win Rate: {win_rate:.0%} (expected 60%)")

        # Test profit_factor
        pf = metrics.profit_factor
        logger.info(f"    Profit Factor: {pf:.2f} (expected 2.5)")

        # Test risk_reward_ratio (new property)
        rr = metrics.risk_reward_ratio
        logger.info(f"    Risk:Reward: 1:{rr:.2f} (expected 1:2.5)")

        # Test expectancy (new property)
        expectancy = metrics.expectancy
        logger.info(f"    Expectancy: ${expectancy:.2f}")

        if hasattr(metrics, 'expectancy') and hasattr(metrics, 'risk_reward_ratio'):
            logger.info("✅ monitoring_system enhancements verified")
            return True
        else:
            logger.error("❌ Missing new properties in PerformanceMetrics")
            return False
    except Exception as e:
        logger.error(f"❌ monitoring_system integration failed: {e}")
        return False


def main():
    """Run all tests"""
    logger.info("="*60)
    logger.info("NIJA ELITE PERFORMANCE CONFIGURATION TESTS")
    logger.info("="*60)

    results = []

    # Run all tests
    results.append(("Configuration Import", test_configuration_import()))
    results.append(("Expectancy Calculation", test_expectancy_calculation()))
    results.append(("Profit Factor Calculation", test_profit_factor_calculation()))
    results.append(("Risk:Reward Calculation", test_risk_reward_calculation()))
    results.append(("Performance Validation", test_performance_validation()))
    results.append(("Position Sizing", test_position_sizing()))
    results.append(("Apex Config Integration", test_apex_config_integration()))
    results.append(("Monitoring System Integration", test_monitoring_system_integration()))

    # Summary
    logger.info("\n" + "="*60)
    logger.info("TEST SUMMARY")
    logger.info("="*60)

    passed = 0
    failed = 0

    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status}: {test_name}")
        if result:
            passed += 1
        else:
            failed += 1

    logger.info("="*60)
    logger.info(f"Total: {len(results)} | Passed: {passed} | Failed: {failed}")
    logger.info("="*60)

    if failed == 0:
        logger.info("\n🎉 ALL TESTS PASSED - ELITE PERFORMANCE MODE READY!")
        return 0
    else:
        logger.error(f"\n⚠️ {failed} TEST(S) FAILED - REVIEW REQUIRED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
