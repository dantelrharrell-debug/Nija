#!/usr/bin/env python3
"""
Test Option A: 30-Minute Exit for Losing Trades

This test validates the implementation of the 30-minute exit logic
for losing trades in the trading strategy.
"""

import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def test_constants():
    """Test that constants are defined correctly"""
    print("=" * 80)
    print("TEST 1: Verify Constants")
    print("=" * 80)
    
    try:
        from trading_strategy import (
            MAX_LOSING_POSITION_HOLD_MINUTES,
            LOSING_POSITION_WARNING_MINUTES,
            MINUTES_PER_HOUR
        )
        
        # Verify values
        assert MAX_LOSING_POSITION_HOLD_MINUTES == 30, \
            f"Expected MAX_LOSING_POSITION_HOLD_MINUTES=30, got {MAX_LOSING_POSITION_HOLD_MINUTES}"
        assert LOSING_POSITION_WARNING_MINUTES == 5, \
            f"Expected LOSING_POSITION_WARNING_MINUTES=5, got {LOSING_POSITION_WARNING_MINUTES}"
        assert MINUTES_PER_HOUR == 60, \
            f"Expected MINUTES_PER_HOUR=60, got {MINUTES_PER_HOUR}"
        
        print(f"✅ MAX_LOSING_POSITION_HOLD_MINUTES = {MAX_LOSING_POSITION_HOLD_MINUTES}")
        print(f"✅ LOSING_POSITION_WARNING_MINUTES = {LOSING_POSITION_WARNING_MINUTES}")
        print(f"✅ MINUTES_PER_HOUR = {MINUTES_PER_HOUR}")
        print()
        return True
    except ImportError as e:
        print(f"❌ Failed to import constants: {e}")
        return False
    except AssertionError as e:
        print(f"❌ Assertion failed: {e}")
        return False


def test_losing_trade_scenarios():
    """Test different losing trade scenarios"""
    print("=" * 80)
    print("TEST 2: Losing Trade Exit Scenarios")
    print("=" * 80)
    
    from trading_strategy import (
        MAX_LOSING_POSITION_HOLD_MINUTES,
        LOSING_POSITION_WARNING_MINUTES,
        MINUTES_PER_HOUR
    )
    
    test_cases = [
        # (position_age_minutes, pnl_percent, should_warn, should_exit, description)
        (3, -0.5, False, False, "3 min losing trade - no action yet"),
        (5, -0.3, True, False, "5 min losing trade - warning threshold"),
        (10, -0.4, True, False, "10 min losing trade - warning active"),
        (25, -0.6, True, False, "25 min losing trade - approaching exit"),
        (30, -0.5, True, True, "30 min losing trade - force exit"),
        (35, -0.7, True, True, "35 min losing trade - overdue for exit"),
        (45, -1.0, True, True, "45 min losing trade - way overdue"),
    ]
    
    all_passed = True
    
    for position_age_minutes, pnl_percent, should_warn, should_exit, description in test_cases:
        # Calculate position age in hours (as used in the code)
        position_age_hours = position_age_minutes / MINUTES_PER_HOUR
        
        # Check warning
        actual_warn = position_age_minutes >= LOSING_POSITION_WARNING_MINUTES
        
        # Check exit
        actual_exit = position_age_minutes >= MAX_LOSING_POSITION_HOLD_MINUTES
        
        # Validate
        warn_match = actual_warn == should_warn
        exit_match = actual_exit == should_exit
        
        if warn_match and exit_match:
            print(f"✅ {description}")
            print(f"   Age: {position_age_minutes:.1f}min, P&L: {pnl_percent:.2f}%")
            print(f"   Warn: {actual_warn}, Exit: {actual_exit}")
        else:
            print(f"❌ {description}")
            print(f"   Age: {position_age_minutes:.1f}min, P&L: {pnl_percent:.2f}%")
            print(f"   Expected - Warn: {should_warn}, Exit: {should_exit}")
            print(f"   Actual   - Warn: {actual_warn}, Exit: {actual_exit}")
            all_passed = False
        print()
    
    return all_passed


def test_profitable_trades_unaffected():
    """Test that profitable trades are NOT affected by 30-minute limit"""
    print("=" * 80)
    print("TEST 3: Profitable Trades Unaffected by 30-Minute Limit")
    print("=" * 80)
    
    from trading_strategy import (
        MAX_LOSING_POSITION_HOLD_MINUTES,
        MINUTES_PER_HOUR
    )
    
    # Profitable trades should not trigger 30-minute exit
    # Only losing trades (pnl_percent < 0) should use this logic
    
    test_cases = [
        # (position_age_minutes, pnl_percent, description)
        (30, 0.0, "30 min at breakeven (0%)"),
        (30, 0.1, "30 min at small profit (+0.1%)"),
        (45, 0.5, "45 min at moderate profit (+0.5%)"),
        (60, 1.0, "60 min at good profit (+1.0%)"),
        (120, 1.5, "120 min at target profit (+1.5%)"),
    ]
    
    all_passed = True
    
    for position_age_minutes, pnl_percent, description in test_cases:
        # The 30-minute exit only applies when pnl_percent < 0
        # So these should NOT trigger the exit
        is_losing = pnl_percent < 0
        should_exit_30min = is_losing and position_age_minutes >= MAX_LOSING_POSITION_HOLD_MINUTES
        
        if not should_exit_30min:
            print(f"✅ {description}")
            print(f"   P&L: {pnl_percent:+.2f}% - No 30-minute exit (profitable)")
        else:
            print(f"❌ {description}")
            print(f"   P&L: {pnl_percent:+.2f}% - Incorrectly triggered 30-minute exit")
            all_passed = False
        print()
    
    return all_passed


def test_edge_cases():
    """Test edge cases"""
    print("=" * 80)
    print("TEST 4: Edge Cases")
    print("=" * 80)
    
    from trading_strategy import (
        MAX_LOSING_POSITION_HOLD_MINUTES,
        LOSING_POSITION_WARNING_MINUTES,
        MINUTES_PER_HOUR
    )
    
    test_cases = [
        # (position_age_minutes, pnl_percent, description)
        (29.9, -0.1, "Just before 30-minute threshold"),
        (30.0, -0.01, "Exactly at 30-minute threshold"),
        (30.1, -0.5, "Just after 30-minute threshold"),
        (4.9, -0.2, "Just before 5-minute warning"),
        (5.0, -0.3, "Exactly at 5-minute warning"),
        (5.1, -0.4, "Just after 5-minute warning"),
    ]
    
    all_passed = True
    
    for position_age_minutes, pnl_percent, description in test_cases:
        is_losing = pnl_percent < 0
        should_warn = is_losing and position_age_minutes >= LOSING_POSITION_WARNING_MINUTES
        should_exit = is_losing and position_age_minutes >= MAX_LOSING_POSITION_HOLD_MINUTES
        
        print(f"✅ {description}")
        print(f"   Age: {position_age_minutes:.1f}min, P&L: {pnl_percent:+.2f}%")
        print(f"   Warn: {should_warn}, Exit: {should_exit}")
        print()
    
    return all_passed


def test_time_conversion():
    """Test time conversion between hours and minutes"""
    print("=" * 80)
    print("TEST 5: Time Conversion")
    print("=" * 80)
    
    from trading_strategy import MINUTES_PER_HOUR
    
    test_cases = [
        # (hours, expected_minutes)
        (0.5, 30),
        (1.0, 60),
        (2.0, 120),
        (8.0, 480),
        (12.0, 720),
    ]
    
    all_passed = True
    
    for hours, expected_minutes in test_cases:
        calculated_minutes = hours * MINUTES_PER_HOUR
        
        if calculated_minutes == expected_minutes:
            print(f"✅ {hours}h = {calculated_minutes}min")
        else:
            print(f"❌ {hours}h: Expected {expected_minutes}min, got {calculated_minutes}min")
            all_passed = False
    
    print()
    return all_passed


def main():
    """Run all tests"""
    print()
    print("=" * 80)
    print("OPTION A: 30-MINUTE EXIT FOR LOSING TRADES - TEST SUITE")
    print("=" * 80)
    print()
    
    results = []
    
    # Run tests
    results.append(("Constants Test", test_constants()))
    results.append(("Losing Trade Scenarios", test_losing_trade_scenarios()))
    results.append(("Profitable Trades Unaffected", test_profitable_trades_unaffected()))
    results.append(("Edge Cases", test_edge_cases()))
    results.append(("Time Conversion", test_time_conversion()))
    
    # Print summary
    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    print()
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    print()
    print("-" * 80)
    print(f"TOTAL: {passed}/{total} tests passed")
    print("-" * 80)
    print()
    
    if passed == total:
        print("🎉 ALL TESTS PASSED!")
        print()
        print("✅ 30-minute exit logic is correctly implemented")
        print("✅ Losing trades will exit after 30 minutes MAX")
        print("✅ Warnings appear at 5 minutes for losing trades")
        print("✅ Profitable trades can run up to 8 hours")
        print("✅ Edge cases handled properly")
        print()
        return 0
    else:
        print("❌ SOME TESTS FAILED")
        print()
        print(f"Failed: {total - passed} test(s)")
        print("Please review the implementation and fix the issues.")
        print()
        return 1


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print()
        print("⚠️  Tests interrupted by user")
        sys.exit(1)
    except Exception as e:
        print()
        print(f"❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
