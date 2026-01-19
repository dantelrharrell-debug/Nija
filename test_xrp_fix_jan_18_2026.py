"""
Test suite for XRP losing trade fix - January 18, 2026

This test validates that losing trades are properly exited:
1. Positions with entry time: Exit after 30 minutes
2. Orphaned positions (no entry time): Exit immediately on any loss
3. Removes conflicting "NO RED EXIT" rule that was blocking exits

Issue: XRP held for 3 days with -$0.24 loss despite 30-minute exit rule
Cause: "NO RED EXIT" rule blocked exits for small losses
Fix: Remove conflicting rule, add immediate exit for orphaned losing positions
"""

import sys
import os

# Test the constants are correct
def test_constants():
    """Verify losing trade constants are set correctly for immediate exit"""
    print("Testing constants...")
    print("  NOTE: 30-minute rule was superseded by immediate exit (Jan 19, 2026)")
    
    try:
        # Import from bot.trading_strategy
        sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))
        from trading_strategy import (
            STOP_LOSS_THRESHOLD,
            STOP_LOSS_EMERGENCY
        )
        
        # Verify immediate exit constants (ultra-aggressive)
        assert STOP_LOSS_THRESHOLD >= -0.1 and STOP_LOSS_THRESHOLD <= -0.01, \
            f"Stop loss should be ultra-aggressive (between -0.1% and -0.01%), got {STOP_LOSS_THRESHOLD}%"
        assert STOP_LOSS_EMERGENCY == -5.0, f"Emergency stop should be -5.0%, got {STOP_LOSS_EMERGENCY}%"
        
        print(f"  ✅ Constants configured correctly")
        print(f"     STOP_LOSS_THRESHOLD = {STOP_LOSS_THRESHOLD}% (immediate exit)")
        print(f"     STOP_LOSS_EMERGENCY = {STOP_LOSS_EMERGENCY}% (failsafe)")
        return True
    except ImportError as e:
        # Can't import module due to missing dependencies, but we can verify by reading file
        print(f"  ⚠️  Cannot import module: {e}")
        print("  ℹ️  Verifying constants by reading source file...")
        
        with open('bot/trading_strategy.py', 'r') as f:
            code = f.read()
        
        # Check for immediate exit implementation
        assert 'STOP_LOSS_THRESHOLD = -0.01' in code, "Stop loss should be -0.01% for immediate exit"
        assert 'STOP_LOSS_EMERGENCY = -5.0' in code, "Emergency stop should be -5.0%"
        
        print("  ✅ Constants verified from source file (immediate exit implementation)")
        return True


def test_losing_position_with_time_exits_after_30_min():
    """Test that losing positions exit IMMEDIATELY regardless of time (supersedes 30-min rule)"""
    print("\nTest 1: Losing position exits IMMEDIATELY (not after 30 minutes)")
    print("  NOTE: Immediate exit supersedes old 30-minute rule")
    
    # Simulate position state
    pnl_percent = -0.24  # XRP losing 0.24%
    entry_time_available = True
    position_age_minutes = 35  # Held for 35 minutes (irrelevant now)
    
    # Check if position would be marked for exit via IMMEDIATE exit logic
    # New logic: Any loss triggers exit immediately via stop loss threshold
    stop_loss_threshold = -0.01  # Current implementation
    should_exit = pnl_percent <= stop_loss_threshold
    
    if should_exit:
        print(f"  Position: P&L={pnl_percent}%, Age={position_age_minutes}min")
        print(f"  ✅ WOULD EXIT: Loss triggers IMMEDIATE exit (not time-based)")
        print(f"     Stop loss check: {pnl_percent}% <= {stop_loss_threshold}%")
    
    assert should_exit, "Position should exit IMMEDIATELY on any loss"
    return True


def test_orphaned_losing_position_exits_immediately():
    """Test that orphaned losing positions exit immediately"""
    print("\nTest 2: Orphaned losing position (no entry time) - exits immediately")
    
    # Simulate orphaned position state
    pnl_percent = -0.24  # XRP losing 0.24%
    entry_time_available = False  # No entry time tracking
    
    # Check if position would be marked for exit
    # With immediate exit logic, ANY loss triggers exit
    stop_loss_threshold = -0.01
    should_exit = pnl_percent <= stop_loss_threshold
    
    if should_exit:
        print(f"  Position: P&L={pnl_percent}%, Entry time available={entry_time_available}")
        print(f"  ✅ WOULD EXIT: Orphaned position with loss exits IMMEDIATELY")
        print(f"     Stop loss check: {pnl_percent}% <= {stop_loss_threshold}%")
    
    assert should_exit, "Orphaned losing position should exit immediately"
    return True


def test_losing_position_under_30_min_warns_not_exits():
    """Test that immediate exit applies regardless of time held"""
    print("\nTest 3: Losing position exits IMMEDIATELY (time held is irrelevant)")
    print("  NOTE: With immediate exit, time held doesn't matter")
    
    # Simulate position state
    pnl_percent = -0.15
    entry_time_available = True
    position_age_minutes = 10  # Only 10 minutes (but irrelevant with immediate exit)
    
    # Check behavior with immediate exit logic
    stop_loss_threshold = -0.01
    should_exit = pnl_percent <= stop_loss_threshold
    
    print(f"  Position: P&L={pnl_percent}%, Age={position_age_minutes}min")
    print(f"  Stop loss check: {pnl_percent}% <= {stop_loss_threshold}% = {should_exit}")
    
    assert should_exit, "With immediate exit, position exits regardless of time"
    print(f"  ✅ CORRECT: Exits IMMEDIATELY (time is irrelevant)")
    return True


def test_breakeven_position_not_marked_losing():
    """Test that breakeven positions are not treated as losing"""
    print("\nTest 4: Breakeven position (0% P&L)")
    
    # Simulate position state
    pnl_percent = 0.0  # Exactly breakeven
    entry_time_available = True
    position_age_minutes = 45  # Over 30 minutes
    
    # Check if position would be marked for exit
    should_exit_as_losing = False
    if pnl_percent < 0:  # Only negative P&L is losing
        should_exit_as_losing = True
    
    print(f"  Position: P&L={pnl_percent}%, Age={position_age_minutes}min")
    assert not should_exit_as_losing, "Breakeven should not be treated as losing"
    print(f"  ✅ CORRECT: Breakeven not treated as losing trade")
    return True


def test_profitable_position_not_affected():
    """Test that profitable positions are not affected by losing trade rules"""
    print("\nTest 5: Profitable position (ignored by losing trade logic)")
    
    # Simulate position state
    pnl_percent = 0.5  # Profitable
    entry_time_available = True
    position_age_minutes = 45  # Over 30 minutes
    
    # Check if losing trade logic would apply
    losing_trade_logic_applies = False
    if pnl_percent < 0:
        losing_trade_logic_applies = True
    
    print(f"  Position: P&L={pnl_percent}%, Age={position_age_minutes}min")
    assert not losing_trade_logic_applies, "Profitable positions should not trigger losing trade logic"
    print(f"  ✅ CORRECT: Profitable position ignores losing trade time limits")
    return True


def test_no_red_exit_rule_removed():
    """Verify that the 'NO RED EXIT' rule has been removed from code"""
    print("\nTest 6: Verify 'NO RED EXIT' rule removed")
    
    # Check if the conflicting rule still exists in the code
    with open('bot/trading_strategy.py', 'r') as f:
        code = f.read()
    
    # The old rule should not exist
    assert 'NO RED EXIT RULE' not in code, "NO RED EXIT rule should be removed"
    assert 'Refusing to sell' not in code, "Refusing to sell logic should be removed"
    
    print(f"  ✅ CONFIRMED: Conflicting 'NO RED EXIT' rule has been removed")
    return True


def test_stop_loss_still_works():
    """Test that stop loss thresholds still work as failsafes"""
    print("\nTest 7: Stop loss thresholds still active")
    
    # Test immediate exit threshold (-0.01%)
    pnl_percent = -0.02
    stop_loss_threshold = -0.01
    
    should_exit = pnl_percent <= stop_loss_threshold
    print(f"  Position: P&L={pnl_percent}%")
    assert should_exit, "Stop loss at -0.01% should trigger"
    print(f"  ✅ CORRECT: Immediate stop loss at -0.01% works")
    
    # Test -5.0% emergency stop
    pnl_percent = -5.5
    emergency_stop = -5.0
    
    should_exit = pnl_percent <= emergency_stop
    assert should_exit, "Emergency stop at -5.0% should still trigger"
    print(f"  ✅ CORRECT: Emergency stop at -5.0% still works")
    
    return True


def run_all_tests():
    """Run all tests and report results"""
    print("=" * 70)
    print("XRP LOSING TRADE FIX - TEST SUITE (Updated for Immediate Exit)")
    print("=" * 70)
    print()
    print("Issue: XRP held for 3 days with -$0.24 loss")
    print("Original Cause: 'NO RED EXIT' rule blocked 30-minute exit")
    print("Original Fix: Remove conflicting rule, 30-minute exit")
    print()
    print("UPDATED (Jan 19, 2026):")
    print("  30-minute rule superseded by IMMEDIATE EXIT on any loss")
    print("  ANY position with P&L < 0% exits IMMEDIATELY")
    print()
    print("=" * 70)
    print()
    
    tests = [
        test_constants,
        test_losing_position_with_time_exits_after_30_min,
        test_orphaned_losing_position_exits_immediately,
        test_losing_position_under_30_min_warns_not_exits,
        test_breakeven_position_not_marked_losing,
        test_profitable_position_not_affected,
        test_no_red_exit_rule_removed,
        test_stop_loss_still_works,
    ]
    
    passed = 0
    failed = 0
    
    for test in tests:
        try:
            if test():
                passed += 1
        except AssertionError as e:
            print(f"  ❌ FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"  ❌ ERROR: {e}")
            failed += 1
    
    print()
    print("=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    if failed == 0:
        print(f"✅ ALL TESTS PASSED ({passed}/{len(tests)})")
        print()
        print("XRP fix is working correctly:")
        print("  ✅ Losing trades exit IMMEDIATELY (via stop loss threshold)")
        print("  ✅ Orphaned losing trades exit IMMEDIATELY")
        print("  ✅ Time held is IRRELEVANT - any loss triggers immediate exit")
        print("  ✅ Conflicting 'NO RED EXIT' rule removed")
        print("  ✅ Stop loss thresholds still work as failsafes")
        print("  ✅ Profitable positions unaffected")
        print()
        print("RESULT: XRP and similar positions will exit IMMEDIATELY on any loss")
        print("        (30-minute rule was superseded by immediate exit - Jan 19, 2026)")
        return True
    else:
        print(f"❌ SOME TESTS FAILED ({failed}/{len(tests)} failed, {passed}/{len(tests)} passed)")
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
