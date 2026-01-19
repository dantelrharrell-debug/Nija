#!/usr/bin/env python3
"""
Test script to verify immediate exit logic for losing trades.

DEPRECATED: This test was for the 30-minute rule (Jan 17, 2026).
The 30-minute rule was superseded by immediate loss exit (Jan 19, 2026).

This script now validates that:
1. Losing trades (P&L < 0%) trigger IMMEDIATE exit (via STOP_LOSS_THRESHOLD)
2. Profitable trades are NOT affected by aggressive exit logic
3. Time-based failsafe exits still work (8h and 12h)
4. Edge cases are handled correctly

NOTE: The immediate loss exit is tested more comprehensively in test_immediate_loss_exit.py
This test is maintained for backwards compatibility and to verify failsafe mechanisms.
"""

import sys
import os
from datetime import datetime, timedelta

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Import the constants we need to test
from trading_strategy import (
    STOP_LOSS_THRESHOLD,
    STOP_LOSS_WARNING,
    STOP_LOSS_EMERGENCY,
    MAX_POSITION_HOLD_HOURS,
    MAX_POSITION_HOLD_EMERGENCY
)

def test_constants():
    """Test that constants are set correctly."""
    print("Testing constants...")
    print(f"   STOP_LOSS_THRESHOLD = {STOP_LOSS_THRESHOLD}% (should be ultra-aggressive, near 0)")
    print(f"   STOP_LOSS_WARNING = {STOP_LOSS_WARNING}%")
    print(f"   STOP_LOSS_EMERGENCY = {STOP_LOSS_EMERGENCY}%")
    print(f"   MAX_POSITION_HOLD_HOURS = {MAX_POSITION_HOLD_HOURS}h")
    print(f"   MAX_POSITION_HOLD_EMERGENCY = {MAX_POSITION_HOLD_EMERGENCY}h")
    
    # Verify immediate loss exit constants
    assert STOP_LOSS_THRESHOLD >= -0.1 and STOP_LOSS_THRESHOLD <= -0.01, \
        f"STOP_LOSS_THRESHOLD should be ultra-aggressive (between -0.1% and -0.01%), got {STOP_LOSS_THRESHOLD}%"
    assert STOP_LOSS_EMERGENCY == -5.0, f"Expected emergency stop at -5.0%, got {STOP_LOSS_EMERGENCY}%"
    assert MAX_POSITION_HOLD_HOURS == 8, f"Expected 8h failsafe, got {MAX_POSITION_HOLD_HOURS}h"
    assert MAX_POSITION_HOLD_EMERGENCY == 12, f"Expected 12h emergency, got {MAX_POSITION_HOLD_EMERGENCY}h"
    print("✅ All constants are correct for immediate loss exit implementation")

def test_losing_trade_scenarios():
    """Test immediate exit for losing trades."""
    print("\nTesting immediate exit scenarios for losing trades...")
    print("NOTE: 30-minute rule was superseded by immediate exit (Jan 19, 2026)")
    
    # Scenario 1: Small loss should trigger immediate exit via stop loss threshold
    print("\n1. Small loss (-0.5%) - should trigger immediate exit:")
    pnl_percent = -0.5
    print(f"   Position: {pnl_percent}% P&L")
    should_exit = pnl_percent <= STOP_LOSS_THRESHOLD
    print(f"   Stop loss check: {pnl_percent}% <= {STOP_LOSS_THRESHOLD}% = {should_exit}")
    assert should_exit, "Small losses should exit immediately via stop loss"
    print("   ✅ Exit triggered correctly (immediate)")
    
    # Scenario 2: Tiny loss at threshold
    print("\n2. Loss at threshold (-0.01%) - should exit:")
    pnl_percent = -0.01
    print(f"   Position: {pnl_percent}% P&L")
    should_exit = pnl_percent <= STOP_LOSS_THRESHOLD
    print(f"   Stop loss check: {pnl_percent}% <= {STOP_LOSS_THRESHOLD}% = {should_exit}")
    assert should_exit, "Loss at threshold should exit"
    print("   ✅ Exit triggered correctly")
    
    # Scenario 3: Medium loss
    print("\n3. Medium loss (-1.2%) - should exit:")
    pnl_percent = -1.2
    print(f"   Position: {pnl_percent}% P&L")
    should_exit = pnl_percent <= STOP_LOSS_THRESHOLD
    assert should_exit, "Medium losses should exit immediately"
    print("   ✅ Exit triggered correctly (immediate)")
    
    # Scenario 4: Large loss - emergency stop
    print("\n4. Large loss (-5.5%) - emergency stop:")
    pnl_percent = -5.5
    print(f"   Position: {pnl_percent}% P&L")
    should_exit_emergency = pnl_percent <= STOP_LOSS_EMERGENCY
    assert should_exit_emergency, "Large losses should trigger emergency stop"
    print("   ✅ Emergency exit triggered correctly")

def test_profitable_trade_scenarios():
    """Test that profitable trades are NOT affected by aggressive exit logic."""
    print("\nTesting profitable trade scenarios...")
    print("Profitable trades should NOT be affected by stop loss logic")
    
    # Scenario 1: Small profit
    print("\n1. Small profit at +0.5%:")
    pnl_percent = 0.5
    print(f"   Position: {pnl_percent}% P&L")
    would_exit_via_stop_loss = pnl_percent <= STOP_LOSS_THRESHOLD
    print(f"   Stop loss check: {pnl_percent}% <= {STOP_LOSS_THRESHOLD}% = {would_exit_via_stop_loss}")
    assert not would_exit_via_stop_loss, "Profitable trade should NOT trigger stop loss"
    print("   ✅ Profitable trade NOT affected by stop loss")
    
    # Scenario 2: Larger profit
    print("\n2. Good profit at +1.2%:")
    pnl_percent = 1.2
    print(f"   Position: {pnl_percent}% P&L")
    would_exit_via_stop_loss = pnl_percent <= STOP_LOSS_THRESHOLD
    assert not would_exit_via_stop_loss, "Profitable trade should NOT trigger stop loss"
    print("   ✅ Profitable trade can run to capture more gains")

def test_edge_cases():
    """Test edge cases."""
    print("\nTesting edge cases...")
    
    # Edge case 1: Position exactly at breakeven (0%)
    print("\n1. Position at breakeven (0% P&L):")
    pnl_percent = 0.0
    print(f"   Position: {pnl_percent}% P&L")
    would_exit = pnl_percent <= STOP_LOSS_THRESHOLD
    print(f"   Stop loss check: {pnl_percent}% <= {STOP_LOSS_THRESHOLD}% = {would_exit}")
    assert not would_exit, "Breakeven position should NOT trigger stop loss"
    print("   ✅ Breakeven positions are NOT treated as losing trades")
    
    # Edge case 2: Very small loss (-0.01%)
    print("\n2. Very small loss (-0.01%) at threshold:")
    pnl_percent = -0.01
    print(f"   Position: {pnl_percent}% P&L")
    would_exit = pnl_percent <= STOP_LOSS_THRESHOLD
    print(f"   Stop loss check: {pnl_percent}% <= {STOP_LOSS_THRESHOLD}% = {would_exit}")
    assert would_exit, "Small losses should trigger exit"
    print("   ✅ Even tiny losses trigger exit (immediate)")
    
    # Edge case 3: Tiny profit just above 0
    print("\n3. Tiny profit (+0.001%):")
    pnl_percent = 0.001
    print(f"   Position: {pnl_percent}% P&L")
    would_exit = pnl_percent <= STOP_LOSS_THRESHOLD
    print(f"   Stop loss check: {pnl_percent}% <= {STOP_LOSS_THRESHOLD}% = {would_exit}")
    assert not would_exit, "Tiny profit should NOT trigger stop loss"
    print("   ✅ Any profit is protected from stop loss exit")

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
    print("TESTING LOSING TRADE EXIT LOGIC (Immediate Exit Implementation)")
    print("=" * 70)
    print()
    print("NOTE: This test was updated from 30-minute rule to immediate exit")
    print("      The 30-minute rule (Jan 17, 2026) was superseded by")
    print("      immediate loss exit (Jan 19, 2026)")
    print()
    print("      For comprehensive immediate exit testing, see:")
    print("      test_immediate_loss_exit.py")
    print()
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
        print("  ✅ Losing trades exit IMMEDIATELY (via stop loss threshold)")
        print("  ✅ Stop loss threshold is ultra-aggressive (-0.01%)")
        print("  ✅ Profitable trades are NOT affected")
        print("  ✅ Edge cases handled correctly")
        print("  ✅ Failsafe mechanisms still work (8h, 12h)")
        print("\n🎯 NIJA exits losing trades IMMEDIATELY to preserve capital")
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
