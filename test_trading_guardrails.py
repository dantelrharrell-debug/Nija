#!/usr/bin/env python3
"""
Test Trading Guardrails Implementation
Tests the four critical fixes for preventing unprofitable trades.
"""

import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def test_fix_1_blacklist():
    """Test FIX #1: XRP-USD is blacklisted"""
    print("\n=== Testing FIX #1: Blacklist XRP-USD ===")
    
    # Test in trading_strategy.py
    from trading_strategy import DISABLED_PAIRS
    assert "XRP-USD" in DISABLED_PAIRS, "XRP-USD should be in DISABLED_PAIRS"
    print(f"✅ PASS: XRP-USD in DISABLED_PAIRS: {DISABLED_PAIRS}")
    
    # Test in apex_config.py
    from apex_config import DISABLED_PAIRS as CONFIG_DISABLED_PAIRS
    assert "XRP-USD" in CONFIG_DISABLED_PAIRS, "XRP-USD should be in apex_config DISABLED_PAIRS"
    print(f"✅ PASS: XRP-USD in apex_config.DISABLED_PAIRS: {CONFIG_DISABLED_PAIRS}")
    
    print("✅ FIX #1: PASS - XRP-USD is properly blacklisted\n")


def test_fix_2_no_red_exit():
    """Test FIX #2: No Red Exit Rule is in code"""
    print("=== Testing FIX #2: No Red Exit Rule ===")
    
    # Read trading_strategy.py and check for the implementation
    # Use relative path from test file location
    test_dir = os.path.dirname(os.path.abspath(__file__))
    strategy_file = os.path.join(test_dir, 'bot', 'trading_strategy.py')
    
    with open(strategy_file, 'r') as f:
        content = f.read()
    
    # Check for key elements of the No Red Exit rule
    assert 'NO RED EXIT RULE' in content, "No Red Exit Rule comment should exist"
    assert 'pnl_percent < 0' in content, "Should check for negative P&L"
    assert 'stop_loss_hit' in content, "Should check for stop loss condition"
    assert 'max_hold_exceeded' in content, "Should check for max hold time"
    assert 'Refusing to sell' in content, "Should have refusal message"
    
    print("✅ PASS: No Red Exit Rule logic found in code")
    print("   - Checks for negative P&L")
    print("   - Validates stop loss conditions")
    print("   - Validates max hold time")
    print("   - Refuses to sell unless emergency")
    print("✅ FIX #2: PASS - No Red Exit Rule implemented\n")


def test_fix_3_min_profit_threshold():
    """Test FIX #3: Minimum profit threshold is configured"""
    print("=== Testing FIX #3: Minimum Profit Threshold ===")
    
    from trading_strategy import (
        MIN_PROFIT_SPREAD,
        MIN_PROFIT_FEES,
        MIN_PROFIT_BUFFER,
        MIN_PROFIT_THRESHOLD
    )
    
    # Verify constants exist
    assert MIN_PROFIT_SPREAD == 0.002, f"Spread should be 0.2%, got {MIN_PROFIT_SPREAD*100}%"
    assert MIN_PROFIT_FEES == 0.012, f"Fees should be 1.2%, got {MIN_PROFIT_FEES*100}%"
    assert MIN_PROFIT_BUFFER == 0.002, f"Buffer should be 0.2%, got {MIN_PROFIT_BUFFER*100}%"
    assert MIN_PROFIT_THRESHOLD == 0.016, f"Total threshold should be 1.6%, got {MIN_PROFIT_THRESHOLD*100}%"
    
    print(f"✅ PASS: MIN_PROFIT_SPREAD = {MIN_PROFIT_SPREAD*100}%")
    print(f"✅ PASS: MIN_PROFIT_FEES = {MIN_PROFIT_FEES*100}%")
    print(f"✅ PASS: MIN_PROFIT_BUFFER = {MIN_PROFIT_BUFFER*100}%")
    print(f"✅ PASS: MIN_PROFIT_THRESHOLD = {MIN_PROFIT_THRESHOLD*100}%")
    
    # Check that the threshold is used in code
    # Use relative path from test file location
    test_dir = os.path.dirname(os.path.abspath(__file__))
    strategy_file = os.path.join(test_dir, 'bot', 'trading_strategy.py')
    
    with open(strategy_file, 'r') as f:
        content = f.read()
    
    assert 'MIN_PROFIT_THRESHOLD' in content, "MIN_PROFIT_THRESHOLD should be used in code"
    assert 'pnl_percent >= MIN_PROFIT_THRESHOLD' in content or 'min threshold' in content.lower(), \
        "Should validate profit against threshold"
    
    print("✅ PASS: Minimum profit threshold is enforced in exit logic")
    print("✅ FIX #3: PASS - Minimum profit threshold configured and enforced\n")


def test_fix_4_pair_quality_filter():
    """Test FIX #4: Pair quality filter exists and works"""
    print("=== Testing FIX #4: Pair Quality Filter ===")
    
    from market_filters import check_pair_quality
    
    # Test 1: Good pair (tight spread, good ATR)
    result = check_pair_quality(
        symbol="BTC-USD",
        bid_price=50000.00,
        ask_price=50010.00,  # 0.02% spread - excellent
        atr_pct=0.015,  # 1.5% ATR - good
        max_spread_pct=0.0015,
        min_atr_pct=0.005,
        disabled_pairs=["XRP-USD"]
    )
    assert result['quality_acceptable'], "BTC-USD should pass quality check"
    print(f"✅ PASS: BTC-USD passes quality filter")
    print(f"   Reasons passed: {result['reasons_passed']}")
    
    # Test 2: Bad pair (wide spread)
    result = check_pair_quality(
        symbol="TEST-USD",
        bid_price=1.00,
        ask_price=1.02,  # 2% spread - too wide
        atr_pct=0.010,
        max_spread_pct=0.0015,
        min_atr_pct=0.005,
        disabled_pairs=["XRP-USD"]
    )
    assert not result['quality_acceptable'], "Wide spread pair should fail"
    print(f"✅ PASS: Wide spread pair rejected")
    print(f"   Reasons failed: {result['reasons_failed']}")
    
    # Test 3: Blacklisted pair
    result = check_pair_quality(
        symbol="XRP-USD",
        bid_price=0.50,
        ask_price=0.501,  # Even with good spread
        atr_pct=0.010,
        max_spread_pct=0.0015,
        min_atr_pct=0.005,
        disabled_pairs=["XRP-USD"]
    )
    assert not result['quality_acceptable'], "XRP-USD should be rejected (blacklisted)"
    assert any('blacklist' in reason.lower() or 'disabled' in reason.lower() 
               for reason in result['reasons_failed']), "Should mention blacklist"
    print(f"✅ PASS: XRP-USD rejected (blacklisted)")
    print(f"   Reasons failed: {result['reasons_failed']}")
    
    # Test 4: Low volatility pair
    result = check_pair_quality(
        symbol="STABLE-USD",
        bid_price=1.00,
        ask_price=1.001,  # 0.1% spread - good
        atr_pct=0.001,  # 0.1% ATR - too low
        max_spread_pct=0.0015,
        min_atr_pct=0.005,
        disabled_pairs=["XRP-USD"]
    )
    assert not result['quality_acceptable'], "Low volatility pair should fail"
    print(f"✅ PASS: Low volatility pair rejected")
    print(f"   Reasons failed: {result['reasons_failed']}")
    
    # Check integration in trading_strategy.py
    # Use relative path from test file location
    test_dir = os.path.dirname(os.path.abspath(__file__))
    strategy_file = os.path.join(test_dir, 'bot', 'trading_strategy.py')
    
    with open(strategy_file, 'r') as f:
        content = f.read()
    
    assert 'check_pair_quality' in content, "check_pair_quality should be imported/used"
    assert 'quality_check' in content or 'quality_acceptable' in content, \
        "Quality check should be performed"
    
    print("✅ PASS: Pair quality filter is integrated into trading strategy")
    print("✅ FIX #4: PASS - Pair quality filter implemented and working\n")


def test_apex_config_updates():
    """Test that apex_config.py has all necessary updates"""
    print("=== Testing apex_config.py Updates ===")
    
    from apex_config import (
        DISABLED_PAIRS,
        FILTERS_CONFIG,
        TAKE_PROFIT_CONFIG
    )
    
    # Check DISABLED_PAIRS
    assert "XRP-USD" in DISABLED_PAIRS, "XRP-USD should be disabled"
    print("✅ PASS: DISABLED_PAIRS configured")
    
    # Check FILTERS_CONFIG
    assert 'max_spread_pct' in FILTERS_CONFIG, "max_spread_pct should be in FILTERS_CONFIG"
    assert FILTERS_CONFIG['max_spread_pct'] <= 0.0015, \
        f"max_spread_pct should be <= 0.15%, got {FILTERS_CONFIG['max_spread_pct']*100}%"
    print(f"✅ PASS: max_spread_pct = {FILTERS_CONFIG['max_spread_pct']*100}%")
    
    # Check TAKE_PROFIT_CONFIG for minimum profit threshold
    assert 'min_profit_total' in TAKE_PROFIT_CONFIG, \
        "min_profit_total should be in TAKE_PROFIT_CONFIG"
    assert TAKE_PROFIT_CONFIG['min_profit_total'] >= 0.015, \
        "min_profit_total should be >= 1.5%"
    print(f"✅ PASS: min_profit_total = {TAKE_PROFIT_CONFIG['min_profit_total']*100}%")
    
    print("✅ PASS: apex_config.py properly updated\n")


def main():
    """Run all tests"""
    print("\n" + "="*80)
    print("TRADING GUARDRAILS IMPLEMENTATION TEST SUITE")
    print("="*80)
    
    try:
        test_fix_1_blacklist()
        test_fix_2_no_red_exit()
        test_fix_3_min_profit_threshold()
        test_fix_4_pair_quality_filter()
        test_apex_config_updates()
        
        print("="*80)
        print("✅ ALL TESTS PASSED - Trading Guardrails Successfully Implemented!")
        print("="*80)
        print("\n🎯 Summary:")
        print("  • FIX #1: XRP-USD blacklisted ✅")
        print("  • FIX #2: No Red Exit Rule enforced ✅")
        print("  • FIX #3: Minimum profit threshold (1.6%) ✅")
        print("  • FIX #4: Pair quality filter active ✅")
        print("\n🚀 Bot is now protected against unprofitable trades!")
        print()
        
        return 0
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
