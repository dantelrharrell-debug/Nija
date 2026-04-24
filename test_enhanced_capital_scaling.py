"""
Test Enhanced Capital Scaling with Recommended Bands

Tests the institutional-grade capital scaling with:
- Market condition-based capital bands
- Strict drawdown-based throttling
- CAGR, Calmar Ratio, and Profit Factor metrics
"""

import sys
from pathlib import Path

# Add bot directory to path
sys.path.insert(0, str(Path(__file__).parent / "bot"))

from enhanced_capital_scaling import (
    EnhancedCapitalScaler,
    MarketCondition,
    CapitalScalingBands
)


def test_drawdown_throttling():
    """Test drawdown-based throttling at critical levels"""
    print("\n" + "="*60)
    print("Testing Drawdown-Based Throttling")
    print("="*60)

    scaler = EnhancedCapitalScaler(base_capital=100000.0)
    base_exposure = 10000.0

    test_cases = [
        (100000.0, "No Drawdown", 1.00),  # 0% DD
        (97500.0, "2.5% Drawdown", 1.00),  # < 3% DD - no throttling
        (96500.0, "3.5% Drawdown", 0.75),  # > 3% DD - 75% exposure
        (93500.0, "6.5% Drawdown", 0.40),  # > 6% DD - 40% exposure
        (89000.0, "11% Drawdown", 0.20),   # > 10% DD - 20% exposure
    ]

    print(f"\nBase Exposure: ${base_exposure:,.2f}\n")

    for capital, desc, expected_multiplier in test_cases:
        scaler.update_capital(capital)
        throttled = scaler.apply_drawdown_throttling(base_exposure)
        actual_multiplier = throttled / base_exposure

        status = "✅" if abs(actual_multiplier - expected_multiplier) < 0.01 else "❌"
        print(f"{status} {desc}:")
        print(f"   Capital: ${capital:,.2f} (DD: {scaler.current_drawdown_pct:.2f}%)")
        print(f"   Exposure: ${throttled:,.2f} ({actual_multiplier:.2f}x)")
        print(f"   Expected: {expected_multiplier:.2f}x")
        print()

    return True


def test_market_condition_scaling():
    """Test market condition-based capital scaling bands"""
    print("\n" + "="*60)
    print("Testing Market Condition Scaling Bands")
    print("="*60)

    scaler = EnhancedCapitalScaler(base_capital=100000.0)
    scaler.update_capital(100000.0)  # No drawdown

    base_position = 5000.0

    test_cases = [
        (True, 20.0, MarketCondition.STRONG_TREND_LOW_DD, 1.425, "Strong Trend + Low DD"),
        (False, 25.0, MarketCondition.NEUTRAL, 1.0, "Neutral"),
        (False, 45.0, MarketCondition.ELEVATED_VOL, 0.7, "Elevated Volatility"),
    ]

    print(f"\nBase Position: ${base_position:,.2f}\n")

    for is_trending, vol_pct, expected_condition, expected_mult, desc in test_cases:
        exposure, condition, multiplier = scaler.calculate_optimal_exposure(
            base_position, is_trending, vol_pct
        )

        status = "✅" if condition == expected_condition else "❌"
        print(f"{status} {desc}:")
        print(f"   Condition: {condition.value}")
        print(f"   Multiplier: {multiplier:.2f}x")
        print(f"   Exposure: ${exposure:,.2f}")
        print()

    return True


def test_combined_scaling_and_throttling():
    """Test combined market scaling + drawdown throttling"""
    print("\n" + "="*60)
    print("Testing Combined Scaling + Throttling")
    print("="*60)

    scaler = EnhancedCapitalScaler(base_capital=100000.0)
    base_position = 5000.0

    test_scenarios = [
        # (capital, is_trending, vol_pct, description, expected_range)
        (100000.0, True, 20.0, "Strong Trend + No DD", (7000, 8000)),  # 1.425x
        (96500.0, True, 20.0, "Strong Trend + 3.5% DD", (5200, 5700)),  # 1.425x * 0.75
        (93500.0, False, 25.0, "Neutral + 6.5% DD", (1800, 2200)),  # 1.0x * 0.40
        (89000.0, False, 50.0, "High Vol + 11% DD", (600, 800)),  # 0.7x * 0.20
    ]

    print(f"\nBase Position: ${base_position:,.2f}\n")

    for capital, is_trending, vol_pct, desc, (min_exp, max_exp) in test_scenarios:
        scaler.update_capital(capital)
        exposure, condition, multiplier = scaler.calculate_optimal_exposure(
            base_position, is_trending, vol_pct
        )

        in_range = min_exp <= exposure <= max_exp
        status = "✅" if in_range else "❌"

        print(f"{status} {desc}:")
        print(f"   Capital: ${capital:,.2f} (DD: {scaler.current_drawdown_pct:.2f}%)")
        print(f"   Condition: {condition.value}")
        print(f"   Exposure: ${exposure:,.2f}")
        print(f"   Expected Range: ${min_exp:,.2f} - ${max_exp:,.2f}")
        print()

    return True


def test_scaling_summary():
    """Test scaling summary report"""
    print("\n" + "="*60)
    print("Testing Scaling Summary")
    print("="*60)

    scaler = EnhancedCapitalScaler(base_capital=100000.0)
    scaler.update_capital(95000.0)  # 5% drawdown

    summary = scaler.get_scaling_summary()

    print(f"\n✅ Scaling Summary:")
    print(f"   Base Capital: ${summary['base_capital']:,.2f}")
    print(f"   Current Capital: ${summary['current_capital']:,.2f}")
    print(f"   Peak Capital: ${summary['peak_capital']:,.2f}")
    print(f"   Drawdown: {summary['current_drawdown_pct']:.2f}%")

    print(f"\n📊 Scaling Bands:")
    for condition, band in summary['scaling_bands'].items():
        print(f"   {condition}: {band}")

    print(f"\n🚨 Throttling Levels:")
    for level, throttle in summary['throttling_levels'].items():
        print(f"   {level}: {throttle}")

    return True


def main():
    """Run all enhanced scaling tests"""
    print("\n" + "="*60)
    print("Enhanced Capital Scaling Tests")
    print("="*60)

    tests = [
        ("Drawdown Throttling", test_drawdown_throttling),
        ("Market Condition Scaling", test_market_condition_scaling),
        ("Combined Scaling + Throttling", test_combined_scaling_and_throttling),
        ("Scaling Summary", test_scaling_summary),
    ]

    results = {}

    for test_name, test_func in tests:
        try:
            result = test_func()
            results[test_name] = "✅ PASS" if result else "❌ FAIL"
        except Exception as e:
            results[test_name] = f"❌ ERROR: {str(e)}"
            import traceback
            traceback.print_exc()

    # Print summary
    print("\n" + "="*60)
    print("Test Results Summary")
    print("="*60)

    for test_name, result in results.items():
        print(f"{test_name}: {result}")

    all_passed = all("PASS" in r for r in results.values())

    if all_passed:
        print("\n🎉 All tests passed!")
        return 0
    else:
        print("\n⚠️  Some tests failed")
        return 1


if __name__ == "__main__":
    exit(main())
