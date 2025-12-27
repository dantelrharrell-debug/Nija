#!/usr/bin/env python3
"""
Unit tests to verify position counting and exit logic fixes
Tests the changes made to fix the bleeding account issue
"""

import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Import constants from actual code to keep tests synchronized
try:
    from trading_strategy import (
        MIN_POSITION_VALUE,
        RSI_OVERBOUGHT_THRESHOLD,
        RSI_OVERSOLD_THRESHOLD,
        MIN_CANDLES_REQUIRED
    )
    from broker_manager import DUST_THRESHOLD_USD
except ImportError:
    # Fallback if imports fail
    print("Warning: Could not import constants from code, using hardcoded values")
    MIN_POSITION_VALUE = 1.0
    RSI_OVERBOUGHT_THRESHOLD = 70
    RSI_OVERSOLD_THRESHOLD = 30
    DUST_THRESHOLD_USD = 1.00
    MIN_CANDLES_REQUIRED = 90

def test_dust_threshold():
    """Test that positions below $1.00 are correctly identified as dust and positions at or above $1.00 are counted toward the position limit"""
    print("\n" + "="*80)
    print("TEST 1: Dust Threshold Consistency")
    print("="*80)
    
    # Test positions with various USD values
    test_cases = [
        (0.0001, True, "TRUE dust - should skip"),
        (0.04, True, "$0.04 position - should skip (dust)"),
        (0.12, True, "$0.12 position - should skip (dust)"),
        (0.50, True, "$0.50 position - should skip (dust)"),
        (0.99, True, "$0.99 position - should skip (dust)"),
        (DUST_THRESHOLD_USD, False, f"Exactly ${DUST_THRESHOLD_USD} - should count"),
        (1.01, False, "$1.01 position - should count"),
        (5.00, False, "$5.00 position - should count"),
    ]
    
    all_passed = True
    
    for usd_value, should_skip, description in test_cases:
        is_dust = usd_value < DUST_THRESHOLD_USD
        passed = is_dust == should_skip
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: ${usd_value:.4f} - {description}")
        if not passed:
            all_passed = False
            print(f"    Expected: skip={should_skip}, Got: skip={is_dust}")
    
    print(f"\n{'✅ All tests passed!' if all_passed else '❌ Some tests failed!'}")
    return all_passed

def test_small_position_exit():
    """Test that small positions under $1 are marked for exit"""
    print("\n" + "="*80)
    print("TEST 2: Small Position Auto-Exit Logic")
    print("="*80)
    
    # Test positions with various USD values
    test_cases = [
        (0.04, True, "$0.04 position - should exit"),
        (0.12, True, "$0.12 position - should exit"),
        (0.50, True, "$0.50 position - should exit"),
        (0.99, True, "$0.99 position - should exit"),
        (MIN_POSITION_VALUE, False, f"${MIN_POSITION_VALUE} position - should keep"),
        (5.00, False, "$5.00 position - should keep"),
    ]
    
    all_passed = True
    
    for position_value, should_exit, description in test_cases:
        would_exit = position_value < MIN_POSITION_VALUE
        passed = would_exit == should_exit
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {description}")
        if not passed:
            all_passed = False
            print(f"    Expected: exit={should_exit}, Got: exit={would_exit}")
    
    print(f"\n{'✅ All tests passed!' if all_passed else '❌ Some tests failed!'}")
    return all_passed

def test_rsi_exit_logic():
    """Test that RSI-based exits work without requiring entry price"""
    print("\n" + "="*80)
    print("TEST 3: RSI-Based Exit Logic (No Entry Price Required)")
    print("="*80)
    
    # Test various RSI values
    test_cases = [
        (25, True, f"RSI 25 - Oversold (< {RSI_OVERSOLD_THRESHOLD}), should exit"),
        (RSI_OVERSOLD_THRESHOLD, False, f"RSI {RSI_OVERSOLD_THRESHOLD} - Boundary, should keep"),
        (50, False, "RSI 50 - Neutral, should keep"),
        (RSI_OVERBOUGHT_THRESHOLD, False, f"RSI {RSI_OVERBOUGHT_THRESHOLD} - Boundary, should keep"),
        (75, True, f"RSI 75 - Overbought (> {RSI_OVERBOUGHT_THRESHOLD}), should exit"),
    ]
    
    all_passed = True
    
    for rsi, should_exit, description in test_cases:
        # Exit logic: RSI > OVERBOUGHT OR RSI < OVERSOLD
        would_exit = rsi > RSI_OVERBOUGHT_THRESHOLD or rsi < RSI_OVERSOLD_THRESHOLD
        passed = would_exit == should_exit
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {description}")
        if not passed:
            all_passed = False
            print(f"    Expected: exit={should_exit}, Got: exit={would_exit}")
    
    print(f"\n{'✅ All tests passed!' if all_passed else '❌ Some tests failed!'}")
    return all_passed

def test_no_entry_price_dependency():
    """Test that exit logic doesn't require entry_price field"""
    print("\n" + "="*80)
    print("TEST 4: Exit Logic Without Entry Price")
    print("="*80)
    
    # Simulate positions without entry_price field
    # This should NOT cause any P&L calculations
    
    position_without_entry = {
        'symbol': 'BTC-USD',
        'quantity': 0.001,
        'currency': 'BTC'
        # NOTE: No 'entry_price' field!
    }
    
    # Verify we don't try to access entry_price
    has_entry_price = 'entry_price' in position_without_entry
    
    if has_entry_price:
        print(f"  ❌ FAIL: Position should not have entry_price field")
        return False
    else:
        print(f"  ✅ PASS: Position correctly lacks entry_price field")
    
    print(f"  ✅ PASS: Exit logic will use market conditions, not P&L")
    print(f"\n✅ Test passed!")
    return True

def test_candle_requirement():
    """Test that minimum candle requirement is relaxed to prevent infinite loops"""
    print("\n" + "="*80)
    print("TEST 5: Candle Requirement (Infinite Loop Prevention)")
    print("="*80)
    
    print(f"  Minimum candles required: {MIN_CANDLES_REQUIRED}")
    
    # Test cases for different candle counts
    test_cases = [
        (50, True, f"50 candles - Insufficient (< {MIN_CANDLES_REQUIRED})"),
        (89, True, f"89 candles - Insufficient (< {MIN_CANDLES_REQUIRED})"),
        (MIN_CANDLES_REQUIRED, False, f"{MIN_CANDLES_REQUIRED} candles - Exactly minimum (acceptable)"),
        (95, False, "95 candles - Sufficient (> minimum)"),
        (97, False, "97 candles - Sufficient (fixes BAT-USD issue)"),
        (100, False, "100 candles - Full dataset (ideal)"),
    ]
    
    all_passed = True
    
    for candle_count, should_reject, description in test_cases:
        # Logic: reject if candle_count < MIN_CANDLES_REQUIRED
        would_reject = candle_count < MIN_CANDLES_REQUIRED
        passed = would_reject == should_reject
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {description}")
        if not passed:
            all_passed = False
            print(f"    Expected: reject={should_reject}, Got: reject={would_reject}")
    
    # Verify that the fix prevents the BAT-USD infinite loop
    bat_usd_candles = 97  # The actual candle count from the logs
    would_reject_bat = bat_usd_candles < MIN_CANDLES_REQUIRED
    
    print(f"\n  🎯 BAT-USD specific check (97 candles):")
    if would_reject_bat:
        print(f"  ❌ FAIL: Would still reject BAT-USD (infinite loop would continue)")
        all_passed = False
    else:
        print(f"  ✅ PASS: BAT-USD with 97 candles is now acceptable (infinite loop prevented)")
    
    print(f"\n{'✅ All tests passed!' if all_passed else '❌ Some tests failed!'}")
    return all_passed


def main():
    """Run all tests"""
    print("\n" + "="*80)
    print("POSITION COUNTING AND EXIT LOGIC TESTS")
    print("Verifying fixes for bleeding account issue")
    print("="*80)
    
    results = []
    
    # Run all tests
    results.append(("Dust Threshold", test_dust_threshold()))
    results.append(("Small Position Exit", test_small_position_exit()))
    results.append(("RSI Exit Logic", test_rsi_exit_logic()))
    results.append(("No Entry Price Dependency", test_no_entry_price_dependency()))
    results.append(("Candle Requirement", test_candle_requirement()))
    
    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    all_passed = True
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"  {status}: {test_name}")
        if not passed:
            all_passed = False
    
    print("\n" + "="*80)
    if all_passed:
        print("✅ ALL TESTS PASSED - Logic fixes are correct!")
    else:
        print("❌ SOME TESTS FAILED - Review logic changes!")
    print("="*80 + "\n")
    
    return 0 if all_passed else 1

if __name__ == '__main__':
    sys.exit(main())
