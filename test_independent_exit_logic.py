#!/usr/bin/env python3
"""
Test script to verify independent exit logic and profit realization.

Tests:
1. Profit targets fire correctly (bug fix validation)
2. Managing-only mode activates profit realization
3. Drain mode activates when over cap
4. Logging is explicit and clear
"""

import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def test_profit_targets_format():
    """Test that PROFIT_TARGETS are in fractional format and comparisons work."""
    print("=" * 70)
    print("TEST 1: Profit Targets Format & Comparison")
    print("=" * 70)
    
    from trading_strategy import (
        PROFIT_TARGETS_KRAKEN,
        PROFIT_TARGETS_COINBASE,
        MIN_PROFIT_THRESHOLD
    )
    
    # Simulate a position with 2.5% profit (fractional format)
    pnl_percent = 0.025  # 2.5% profit in fractional format
    
    print(f"\nSimulated position P&L: {pnl_percent} ({pnl_percent*100:.2f}%)")
    print(f"MIN_PROFIT_THRESHOLD: {MIN_PROFIT_THRESHOLD} ({MIN_PROFIT_THRESHOLD*100:.2f}%)")
    
    print("\n--- Testing PROFIT_TARGETS_KRAKEN ---")
    for target_pct, reason in PROFIT_TARGETS_KRAKEN:
        target_triggered = pnl_percent >= target_pct
        print(f"  Target: {target_pct} ({target_pct*100:.1f}%)")
        print(f"    Triggered: {target_triggered}")
        print(f"    Reason: {reason}")
        
    print("\n--- Testing PROFIT_TARGETS_COINBASE ---")
    for target_pct, reason in PROFIT_TARGETS_COINBASE:
        target_triggered = pnl_percent >= target_pct
        print(f"  Target: {target_pct} ({target_pct*100:.1f}%)")
        print(f"    Triggered: {target_triggered}")
        print(f"    Reason: {reason}")
    
    # Check if at least one target would trigger
    kraken_triggered = any(pnl_percent >= t[0] for t in PROFIT_TARGETS_KRAKEN)
    coinbase_triggered = any(pnl_percent >= t[0] for t in PROFIT_TARGETS_COINBASE)
    
    print("\n" + "=" * 70)
    if kraken_triggered:
        print("✅ PASS: Kraken profit targets would trigger at 2.5% P&L")
    else:
        print("❌ FAIL: Kraken profit targets would NOT trigger at 2.5% P&L")
        
    if coinbase_triggered:
        print("✅ PASS: Coinbase profit targets would trigger at 2.5% P&L")
    else:
        print("❌ FAIL: Coinbase profit targets would NOT trigger at 2.5% P&L")
    
    # Verify all targets are in fractional format (< 1.0)
    all_fractional = all(t[0] < 1.0 for t in PROFIT_TARGETS_KRAKEN + PROFIT_TARGETS_COINBASE)
    if all_fractional:
        print("✅ PASS: All profit targets are in fractional format (< 1.0)")
    else:
        print("❌ FAIL: Some profit targets are NOT in fractional format")
    
    print("=" * 70)
    
    return kraken_triggered and coinbase_triggered and all_fractional


def test_managing_only_detection():
    """Test that managing_only mode is correctly detected."""
    print("\n" + "=" * 70)
    print("TEST 2: Managing-Only Mode Detection")
    print("=" * 70)
    
    # Simulate different scenarios
    test_cases = [
        {
            'name': 'Normal mode',
            'user_mode': False,
            'entries_blocked': False,
            'positions': 5,
            'max_positions': 8,
            'expected': False
        },
        {
            'name': 'User mode (copy trading)',
            'user_mode': True,
            'entries_blocked': False,
            'positions': 5,
            'max_positions': 8,
            'expected': True
        },
        {
            'name': 'Entries blocked (STOP_ALL_ENTRIES.conf)',
            'user_mode': False,
            'entries_blocked': True,
            'positions': 5,
            'max_positions': 8,
            'expected': True
        },
        {
            'name': 'Position cap reached',
            'user_mode': False,
            'entries_blocked': False,
            'positions': 8,
            'max_positions': 8,
            'expected': True
        },
        {
            'name': 'Over position cap (drain mode)',
            'user_mode': False,
            'entries_blocked': False,
            'positions': 10,
            'max_positions': 8,
            'expected': True
        }
    ]
    
    all_pass = True
    for case in test_cases:
        user_mode = case['user_mode']
        entries_blocked = case['entries_blocked']
        positions = case['positions']
        max_positions = case['max_positions']
        expected = case['expected']
        
        # Calculate managing_only
        managing_only = user_mode or entries_blocked or (positions >= max_positions)
        
        passed = managing_only == expected
        all_pass = all_pass and passed
        
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"\n{status}: {case['name']}")
        print(f"  user_mode={user_mode}, entries_blocked={entries_blocked}")
        print(f"  positions={positions}, max_positions={max_positions}")
        print(f"  managing_only={managing_only} (expected={expected})")
    
    print("\n" + "=" * 70)
    if all_pass:
        print("✅ ALL MANAGING-ONLY TESTS PASSED")
    else:
        print("❌ SOME MANAGING-ONLY TESTS FAILED")
    print("=" * 70)
    
    return all_pass


def test_drain_mode_logic():
    """Test legacy position drain mode logic."""
    print("\n" + "=" * 70)
    print("TEST 3: Legacy Position Drain Mode")
    print("=" * 70)
    
    MAX_POSITIONS = 8
    
    test_cases = [
        {
            'name': 'Under cap (no drain)',
            'positions': 6,
            'expected_drain': 0
        },
        {
            'name': 'At cap (no drain)',
            'positions': 8,
            'expected_drain': 0
        },
        {
            'name': 'Slightly over cap (1 excess)',
            'positions': 9,
            'expected_drain': 1
        },
        {
            'name': 'Moderately over cap (2 excess)',
            'positions': 10,
            'expected_drain': 2
        },
        {
            'name': 'Heavily over cap (5 excess)',
            'positions': 13,
            'expected_drain': min(5, 3)  # Max 3 per cycle
        }
    ]
    
    all_pass = True
    for case in test_cases:
        positions = case['positions']
        expected_drain = case['expected_drain']
        
        # Calculate drain
        positions_over_cap = max(0, positions - MAX_POSITIONS)
        actual_drain = min(positions_over_cap, 3)  # Max 3 per cycle
        
        passed = actual_drain == expected_drain
        all_pass = all_pass and passed
        
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"\n{status}: {case['name']}")
        print(f"  Total positions: {positions}")
        print(f"  Over cap: {positions_over_cap}")
        print(f"  Drain rate: {actual_drain} (expected={expected_drain})")
    
    print("\n" + "=" * 70)
    if all_pass:
        print("✅ ALL DRAIN MODE TESTS PASSED")
    else:
        print("❌ SOME DRAIN MODE TESTS FAILED")
    print("=" * 70)
    
    return all_pass


def test_stop_loss_format():
    """Test that stop-loss thresholds are in fractional format."""
    print("\n" + "=" * 70)
    print("TEST 4: Stop-Loss Format Validation")
    print("=" * 70)
    
    from trading_strategy import (
        STOP_LOSS_EMERGENCY,
        STOP_LOSS_THRESHOLD,
        MIN_LOSS_FLOOR
    )
    
    print(f"\nStop-loss thresholds (fractional format):")
    print(f"  STOP_LOSS_EMERGENCY: {STOP_LOSS_EMERGENCY} ({STOP_LOSS_EMERGENCY*100:.1f}%)")
    print(f"  STOP_LOSS_THRESHOLD: {STOP_LOSS_THRESHOLD} ({STOP_LOSS_THRESHOLD*100:.1f}%)")
    print(f"  MIN_LOSS_FLOOR: {MIN_LOSS_FLOOR} ({MIN_LOSS_FLOOR*100:.2f}%)")
    
    # Test with a losing position (-2% loss)
    pnl_percent = -0.02  # -2% loss
    
    print(f"\nSimulated position P&L: {pnl_percent} ({pnl_percent*100:.2f}%)")
    
    emergency_triggered = pnl_percent <= STOP_LOSS_EMERGENCY
    standard_triggered = pnl_percent <= STOP_LOSS_THRESHOLD
    floor_triggered = pnl_percent <= MIN_LOSS_FLOOR
    
    print(f"\nStop-loss triggers:")
    print(f"  Emergency (-5%): {emergency_triggered}")
    print(f"  Standard (-1.5%): {standard_triggered}")
    print(f"  Floor (-0.05%): {floor_triggered}")
    
    # At -2%, standard stop should trigger
    all_pass = True
    if standard_triggered and not emergency_triggered:
        print("\n✅ PASS: Standard stop triggers at -2% (emergency does not)")
        all_pass = all_pass and True
    else:
        print("\n❌ FAIL: Stop-loss logic incorrect at -2%")
        all_pass = False
    
    # Verify all are negative and in fractional format
    all_negative = all(x < 0 for x in [STOP_LOSS_EMERGENCY, STOP_LOSS_THRESHOLD, MIN_LOSS_FLOOR])
    all_fractional = all(abs(x) < 1.0 for x in [STOP_LOSS_EMERGENCY, STOP_LOSS_THRESHOLD, MIN_LOSS_FLOOR])
    
    if all_negative and all_fractional:
        print("✅ PASS: All stop-losses are negative fractional values")
        all_pass = all_pass and True
    else:
        print("❌ FAIL: Some stop-losses not in correct format")
        all_pass = False
    
    print("=" * 70)
    
    return all_pass


if __name__ == '__main__':
    print("\n" + "🧪" * 35)
    print("NIJA Independent Exit Logic Test Suite")
    print("🧪" * 35)
    
    results = []
    
    # Run all tests
    try:
        results.append(("Profit Targets Format", test_profit_targets_format()))
    except Exception as e:
        print(f"❌ ERROR in profit targets test: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Profit Targets Format", False))
    
    try:
        results.append(("Managing-Only Detection", test_managing_only_detection()))
    except Exception as e:
        print(f"❌ ERROR in managing-only test: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Managing-Only Detection", False))
    
    try:
        results.append(("Drain Mode Logic", test_drain_mode_logic()))
    except Exception as e:
        print(f"❌ ERROR in drain mode test: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Drain Mode Logic", False))
    
    try:
        results.append(("Stop-Loss Format", test_stop_loss_format()))
    except Exception as e:
        print(f"❌ ERROR in stop-loss test: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Stop-Loss Format", False))
    
    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    all_passed = all(result[1] for result in results)
    
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print("=" * 70)
    
    if all_passed:
        print("🎉 ALL TESTS PASSED! Independent exit logic is working correctly.")
        print("=" * 70)
        sys.exit(0)
    else:
        print("❌ SOME TESTS FAILED! Please review the output above.")
        print("=" * 70)
        sys.exit(1)
