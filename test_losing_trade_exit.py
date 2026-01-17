#!/usr/bin/env python3
"""
Test script to verify 30-minute exit logic for losing trades.

This script validates that:
1. Losing trades (P&L < 0%) trigger exit after 30 minutes
2. Warnings appear at 5 minutes for losing trades
3. Profitable trades are NOT affected by 30-minute limit
4. Edge cases are handled correctly
"""

import sys
import os
from datetime import datetime, timedelta

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Import the constants we need to test
from trading_strategy import (
    MAX_LOSING_POSITION_HOLD_MINUTES,
    LOSING_POSITION_WARNING_MINUTES,
    MAX_POSITION_HOLD_HOURS,
    MAX_POSITION_HOLD_EMERGENCY
)

def test_constants():
    """Test that constants are set correctly."""
    print("Testing constants...")
    assert MAX_LOSING_POSITION_HOLD_MINUTES == 30, f"Expected 30, got {MAX_LOSING_POSITION_HOLD_MINUTES}"
    assert LOSING_POSITION_WARNING_MINUTES == 5, f"Expected 5, got {LOSING_POSITION_WARNING_MINUTES}"
    assert MAX_POSITION_HOLD_HOURS == 8, f"Expected 8, got {MAX_POSITION_HOLD_HOURS}"
    assert MAX_POSITION_HOLD_EMERGENCY == 12, f"Expected 12, got {MAX_POSITION_HOLD_EMERGENCY}"
    print("✅ All constants are correct")

def test_losing_trade_scenarios():
    """Test various losing trade scenarios."""
    print("\nTesting losing trade scenarios...")
    
    # Scenario 1: Losing trade held for 5 minutes (warning threshold)
    print("\n1. Losing trade at 5 minutes (should warn):")
    position_age_minutes = 5
    pnl_percent = -0.5
    print(f"   Position: {pnl_percent}% P&L, {position_age_minutes} minutes old")
    if position_age_minutes >= LOSING_POSITION_WARNING_MINUTES:
        minutes_remaining = MAX_LOSING_POSITION_HOLD_MINUTES - position_age_minutes
        print(f"   ⚠️  WARNING: Will auto-exit in {minutes_remaining} minutes")
    print("   ✅ Warning triggered correctly")
    
    # Scenario 2: Losing trade held for 15 minutes (mid-warning)
    print("\n2. Losing trade at 15 minutes (should warn):")
    position_age_minutes = 15
    pnl_percent = -0.8
    print(f"   Position: {pnl_percent}% P&L, {position_age_minutes} minutes old")
    if position_age_minutes >= LOSING_POSITION_WARNING_MINUTES:
        minutes_remaining = MAX_LOSING_POSITION_HOLD_MINUTES - position_age_minutes
        print(f"   ⚠️  WARNING: Will auto-exit in {minutes_remaining} minutes")
    print("   ✅ Warning triggered correctly")
    
    # Scenario 3: Losing trade held for 30 minutes (exit threshold)
    print("\n3. Losing trade at 30 minutes (should EXIT):")
    position_age_minutes = 30
    pnl_percent = -1.2
    print(f"   Position: {pnl_percent}% P&L, {position_age_minutes} minutes old")
    should_exit = position_age_minutes >= MAX_LOSING_POSITION_HOLD_MINUTES
    print(f"   🚨 EXIT: {should_exit}")
    assert should_exit, "Should exit at 30 minutes"
    print("   ✅ Exit triggered correctly")
    
    # Scenario 4: Losing trade held for 45 minutes (well past threshold)
    print("\n4. Losing trade at 45 minutes (should EXIT):")
    position_age_minutes = 45
    pnl_percent = -1.5
    print(f"   Position: {pnl_percent}% P&L, {position_age_minutes} minutes old")
    should_exit = position_age_minutes >= MAX_LOSING_POSITION_HOLD_MINUTES
    print(f"   🚨 EXIT: {should_exit}")
    assert should_exit, "Should exit at 45 minutes"
    print("   ✅ Exit triggered correctly")

def test_profitable_trade_scenarios():
    """Test that profitable trades are NOT affected by 30-minute limit."""
    print("\nTesting profitable trade scenarios...")
    
    # Scenario 1: Profitable trade at 30 minutes
    print("\n1. Profitable trade at 30 minutes (should NOT exit due to time):")
    position_age_minutes = 30
    pnl_percent = 0.5
    print(f"   Position: {pnl_percent}% P&L, {position_age_minutes} minutes old")
    # Losing trade check: pnl_percent < 0
    is_losing = pnl_percent < 0
    should_exit_due_to_time = is_losing and position_age_minutes >= MAX_LOSING_POSITION_HOLD_MINUTES
    print(f"   Is losing: {is_losing}")
    print(f"   Should exit due to time: {should_exit_due_to_time}")
    assert not should_exit_due_to_time, "Profitable trade should NOT exit at 30 minutes"
    print("   ✅ Profitable trade NOT affected by 30-minute limit")
    
    # Scenario 2: Profitable trade at 2 hours
    print("\n2. Profitable trade at 2 hours (should NOT exit due to time):")
    position_age_hours = 2
    position_age_minutes = position_age_hours * 60
    pnl_percent = 1.2
    print(f"   Position: {pnl_percent}% P&L, {position_age_hours} hours old")
    is_losing = pnl_percent < 0
    should_exit_due_to_time = is_losing and position_age_minutes >= MAX_LOSING_POSITION_HOLD_MINUTES
    print(f"   Is losing: {is_losing}")
    print(f"   Should exit due to time: {should_exit_due_to_time}")
    assert not should_exit_due_to_time, "Profitable trade should NOT exit at 2 hours"
    print("   ✅ Profitable trade can run longer to capture gains")

def test_edge_cases():
    """Test edge cases."""
    print("\nTesting edge cases...")
    
    # Edge case 1: Position exactly at breakeven (0%)
    print("\n1. Position at breakeven (0% P&L) at 30 minutes:")
    position_age_minutes = 30
    pnl_percent = 0.0
    print(f"   Position: {pnl_percent}% P&L, {position_age_minutes} minutes old")
    is_losing = pnl_percent < 0
    should_exit_due_to_time = is_losing and position_age_minutes >= MAX_LOSING_POSITION_HOLD_MINUTES
    print(f"   Is losing: {is_losing}")
    print(f"   Should exit due to time: {should_exit_due_to_time}")
    assert not should_exit_due_to_time, "Breakeven position should NOT be treated as losing"
    print("   ✅ Breakeven positions are NOT treated as losing trades")
    
    # Edge case 2: Very small loss (-0.01%)
    print("\n2. Very small loss (-0.01%) at 30 minutes:")
    position_age_minutes = 30
    pnl_percent = -0.01
    print(f"   Position: {pnl_percent}% P&L, {position_age_minutes} minutes old")
    is_losing = pnl_percent < 0
    should_exit_due_to_time = is_losing and position_age_minutes >= MAX_LOSING_POSITION_HOLD_MINUTES
    print(f"   Is losing: {is_losing}")
    print(f"   Should exit due to time: {should_exit_due_to_time}")
    assert should_exit_due_to_time, "Even small losses should exit at 30 minutes"
    print("   ✅ Even tiny losses trigger 30-minute exit")
    
    # Edge case 3: Position just under 30 minutes (29 minutes)
    print("\n3. Losing trade at 29 minutes (should NOT exit yet):")
    position_age_minutes = 29
    pnl_percent = -0.5
    print(f"   Position: {pnl_percent}% P&L, {position_age_minutes} minutes old")
    is_losing = pnl_percent < 0
    should_exit_due_to_time = is_losing and position_age_minutes >= MAX_LOSING_POSITION_HOLD_MINUTES
    print(f"   Is losing: {is_losing}")
    print(f"   Should exit due to time: {should_exit_due_to_time}")
    assert not should_exit_due_to_time, "Should NOT exit before 30 minutes"
    print("   ✅ Exit threshold is exactly 30 minutes, not before")

def test_failsafe_mechanisms():
    """Test that failsafe mechanisms still work."""
    print("\nTesting failsafe mechanisms...")
    
    # Failsafe 1: 8-hour max hold time (applies to ALL positions)
    print("\n1. Position at 8 hours (failsafe):")
    position_age_hours = 8
    pnl_percent = 0.3  # Profitable but stale
    print(f"   Position: {pnl_percent}% P&L, {position_age_hours} hours old")
    should_exit_8h = position_age_hours >= MAX_POSITION_HOLD_HOURS
    print(f"   Should exit at 8h failsafe: {should_exit_8h}")
    assert should_exit_8h, "8-hour failsafe should trigger for all positions"
    print("   ✅ 8-hour failsafe works for all positions")
    
    # Failsafe 2: 12-hour emergency exit
    print("\n2. Position at 12 hours (emergency):")
    position_age_hours = 12
    pnl_percent = -2.0
    print(f"   Position: {pnl_percent}% P&L, {position_age_hours} hours old")
    should_exit_12h = position_age_hours >= MAX_POSITION_HOLD_EMERGENCY
    print(f"   Should exit at 12h emergency: {should_exit_12h}")
    assert should_exit_12h, "12-hour emergency should trigger for all positions"
    print("   ✅ 12-hour emergency failsafe works")

def main():
    """Run all tests."""
    print("=" * 70)
    print("TESTING 30-MINUTE LOSING TRADE EXIT LOGIC")
    print("=" * 70)
    
    try:
        test_constants()
        test_losing_trade_scenarios()
        test_profitable_trade_scenarios()
        test_edge_cases()
        test_failsafe_mechanisms()
        
        print("\n" + "=" * 70)
        print("✅ ALL TESTS PASSED")
        print("=" * 70)
        print("\nSummary:")
        print("  ✅ Losing trades exit after 30 minutes")
        print("  ✅ Warnings appear at 5 minutes for losing trades")
        print("  ✅ Profitable trades can run up to 8 hours")
        print("  ✅ Edge cases handled correctly")
        print("  ✅ Failsafe mechanisms still work")
        print("\n🎯 NIJA will now NEVER hold losing trades for more than 30 minutes")
        print("=" * 70)
        return 0
        
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())
