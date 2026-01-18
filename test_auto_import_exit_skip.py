#!/usr/bin/env python3
"""
Test: Auto-imported positions should skip exit signals in the same cycle

This test validates that positions auto-imported in the current cycle are NOT
immediately evaluated for exits based on RSI/EMA signals, which would defeat
the purpose of auto-import.

Expected Behavior:
1. Position detected without entry price tracking
2. Position auto-imported with current price as entry (P&L = $0)
3. Exit signals (RSI overbought, momentum reversal, etc.) are SKIPPED in same cycle
4. Position is retained and will be evaluated in next cycle

Problem from Logs:
    2026-01-17 23:43:52 | INFO |    ✅ AUTO-IMPORTED: LTC-USD @ $74.80 (P&L will start from $0)
    2026-01-17 23:43:52 | INFO |       Position now tracked - will use profit targets in next cycle
    2026-01-17 23:43:52 | INFO |       Position verified in tracker - aggressive exits disabled
    2026-01-17 23:43:52 | INFO |    📈 RSI OVERBOUGHT EXIT: LTC-USD (RSI=55.6)
                                       ^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
                                       THIS SHOULD NOT HAPPEN!
"""

import sys
import os
from pathlib import Path

# Add bot directory to path
bot_dir = Path(__file__).parent / "bot"
sys.path.insert(0, str(bot_dir))

def test_auto_import_logic_in_code():
    """
    Verify that the code has the necessary guards to prevent
    auto-imported positions from being exited in the same cycle.
    """
    print("\n" + "="*80)
    print("TEST: Auto-Import Exit Skip Logic")
    print("="*80)
    
    # Read the trading_strategy.py file
    strategy_file = bot_dir / "trading_strategy.py"
    
    if not strategy_file.exists():
        print(f"❌ ERROR: {strategy_file} not found")
        return False
    
    with open(strategy_file, 'r') as f:
        code = f.read()
    
    # Test 1: Check that just_auto_imported flag is declared
    print("\n1. Checking for 'just_auto_imported' flag declaration...")
    if "just_auto_imported = False" in code:
        print("   ✅ PASS: 'just_auto_imported' flag is declared")
    else:
        print("   ❌ FAIL: 'just_auto_imported' flag is NOT declared")
        return False
    
    # Test 2: Check that flag is set when auto-import succeeds
    print("\n2. Checking that flag is set on successful auto-import...")
    if "just_auto_imported = True" in code:
        print("   ✅ PASS: Flag is set to True after auto-import")
    else:
        print("   ❌ FAIL: Flag is NOT set after auto-import")
        return False
    
    # Test 3: Check that there's a guard to skip exits when flag is True
    print("\n3. Checking for exit skip guard when just_auto_imported is True...")
    if "if just_auto_imported:" in code and "continue" in code:
        print("   ✅ PASS: Guard exists to skip exits for auto-imported positions")
    else:
        print("   ❌ FAIL: No guard to skip exits for auto-imported positions")
        return False
    
    # Test 4: Verify the guard is placed BEFORE the RSI overbought exit
    print("\n4. Checking guard placement (before RSI overbought exit)...")
    just_imported_idx = code.find("if just_auto_imported:")
    rsi_overbought_idx = code.find("RSI OVERBOUGHT EXIT")
    
    if just_imported_idx != -1 and rsi_overbought_idx != -1:
        if just_imported_idx < rsi_overbought_idx:
            print("   ✅ PASS: Guard is placed BEFORE RSI overbought exit")
        else:
            print("   ❌ FAIL: Guard is placed AFTER RSI overbought exit (wrong order)")
            return False
    else:
        print("   ❌ FAIL: Could not find guard or RSI exit in code")
        return False
    
    # Test 5: Verify the guard is placed BEFORE momentum reversal exit
    print("\n5. Checking guard placement (before momentum reversal exit)...")
    momentum_reversal_idx = code.find("MOMENTUM REVERSAL EXIT")
    
    if just_imported_idx != -1 and momentum_reversal_idx != -1:
        if just_imported_idx < momentum_reversal_idx:
            print("   ✅ PASS: Guard is placed BEFORE momentum reversal exit")
        else:
            print("   ❌ FAIL: Guard is placed AFTER momentum reversal exit (wrong order)")
            return False
    else:
        print("   ❌ FAIL: Could not find guard or momentum reversal exit in code")
        return False
    
    # Test 6: Verify the guard is placed BEFORE profit protection exit
    print("\n6. Checking guard placement (before profit protection exit)...")
    profit_protection_idx = code.find("PROFIT PROTECTION EXIT")
    
    if just_imported_idx != -1 and profit_protection_idx != -1:
        if just_imported_idx < profit_protection_idx:
            print("   ✅ PASS: Guard is placed BEFORE profit protection exit")
        else:
            print("   ❌ FAIL: Guard is placed AFTER profit protection exit (wrong order)")
            return False
    else:
        print("   ❌ FAIL: Could not find guard or profit protection exit in code")
        return False
    
    # Test 7: Verify logging messages
    print("\n7. Checking for informative logging messages...")
    if "SKIPPING EXITS" in code and "was just auto-imported this cycle" in code:
        print("   ✅ PASS: Clear logging when skipping exits for auto-imported positions")
    else:
        print("   ❌ FAIL: Missing or unclear logging for exit skip")
        return False
    
    # Test 8: Check that the log message mentions "next cycle"
    print("\n8. Checking that log mentions evaluating in 'next cycle'...")
    if "Will evaluate exit signals in next cycle" in code or "next cycle after P&L develops" in code:
        print("   ✅ PASS: Log message mentions next cycle evaluation")
    else:
        print("   ❌ FAIL: Log message doesn't mention next cycle")
        return False
    
    return True


def test_problem_scenario():
    """
    Test the specific scenario from the problem statement:
    - LTC-USD auto-imported at $74.80
    - RSI = 55.6 (overbought)
    - Should NOT trigger "RSI OVERBOUGHT EXIT" in same cycle
    """
    print("\n" + "="*80)
    print("TEST: Problem Scenario Validation")
    print("="*80)
    
    print("\nScenario: Position auto-imported with RSI=55.6 (overbought)")
    print("Expected: NO exit in same cycle")
    print("Actual behavior will be tested in integration test")
    
    # Read the code to understand the flow
    strategy_file = bot_dir / "trading_strategy.py"
    with open(strategy_file, 'r') as f:
        lines = f.readlines()
    
    # Find the auto-import success block
    auto_import_found = False
    flag_set = False
    skip_guard_found = False
    
    for i, line in enumerate(lines):
        if "auto_import_success:" in line and "if" in line:
            auto_import_found = True
            print(f"\n✅ Found auto-import success block at line {i+1}")
        
        if auto_import_found and "just_auto_imported = True" in line:
            flag_set = True
            print(f"✅ Found flag set at line {i+1}: {line.strip()}")
        
        if "if just_auto_imported:" in line:
            skip_guard_found = True
            print(f"✅ Found skip guard at line {i+1}: {line.strip()}")
            # Print next few lines to show the skip logic
            for j in range(1, 4):
                if i+j < len(lines):
                    print(f"   Line {i+j+1}: {lines[i+j].strip()}")
            break
    
    if auto_import_found and flag_set and skip_guard_found:
        print("\n✅ PASS: All components in place to prevent same-cycle exit")
        return True
    else:
        print("\n❌ FAIL: Missing components")
        if not auto_import_found:
            print("   - Auto-import success block not found")
        if not flag_set:
            print("   - Flag not set after auto-import")
        if not skip_guard_found:
            print("   - Skip guard not found before exits")
        return False


def main():
    """Run all tests"""
    print("\n" + "="*80)
    print("AUTO-IMPORT EXIT SKIP TEST SUITE")
    print("="*80)
    print("\nProblem: Positions auto-imported at current price (P&L=$0) are being")
    print("         immediately exited based on RSI/EMA signals in the same cycle.")
    print("\nSolution: Add 'just_auto_imported' flag to skip all exit signals in")
    print("          the cycle where position is auto-imported.")
    
    test_results = []
    
    # Run tests
    test_results.append(("Code Logic Test", test_auto_import_logic_in_code()))
    test_results.append(("Problem Scenario Test", test_problem_scenario()))
    
    # Print summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    passed = sum(1 for _, result in test_results if result)
    total = len(test_results)
    
    for test_name, result in test_results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nResults: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✅ ALL TESTS PASSED")
        print("\nExpected Logs After Fix:")
        print("  1. ⚠️  No entry price tracked for LTC-USD - attempting auto-import")
        print("  2. ✅ AUTO-IMPORTED: LTC-USD @ $74.80 (P&L will start from $0)")
        print("  3. ⏭️  SKIPPING EXITS: LTC-USD was just auto-imported this cycle")
        print("  4. (Position retained for next cycle)")
        print("\nNext Cycle:")
        print("  1. LTC-USD found in tracker with entry=$74.80")
        print("  2. Calculate P&L vs current price")
        print("  3. Apply normal exit rules (profit targets, stop loss, RSI signals)")
        return 0
    else:
        print("\n❌ SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
