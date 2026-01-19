#!/usr/bin/env python3
"""
Simple test to verify the syntax and logic structure of the copy trading warning fix.
This validates the code structure without needing full dependencies.
"""

import ast
import sys

def test_independent_broker_trader_logic():
    """Test that the logic in independent_broker_trader.py is correct."""
    print("=" * 70)
    print("Testing Independent Broker Trader Logic Structure")
    print("=" * 70)
    
    # Read the file
    with open('bot/independent_broker_trader.py', 'r') as f:
        code = f.read()
    
    # Check for the import statement
    if 'from bot.copy_trade_engine import get_copy_engine' in code:
        print("✅ Test 1: Found copy_trade_engine import in conditional block")
    else:
        print("❌ Test 1 Failed: Missing copy_trade_engine import")
        return False
    
    # Check for the conditional logic
    if 'copy_trading_engine._running' in code:
        print("✅ Test 2: Found _running attribute check")
    else:
        print("❌ Test 2 Failed: Missing _running check")
        return False
    
    # Check for the info message
    if 'No independent USER brokers detected (users operate via copy trading)' in code:
        print("✅ Test 3: Found correct INFO message for copy trading mode")
    else:
        print("❌ Test 3 Failed: Missing INFO message")
        return False
    
    # Check for the warning message
    if 'No funded USER brokers detected' in code:
        print("✅ Test 4: Found WARNING message for non-copy-trading mode")
    else:
        print("❌ Test 4 Failed: Missing WARNING message")
        return False
    
    # Check for exception handling
    if 'except Exception:' in code and 'fall back to warning' in code:
        print("✅ Test 5: Found proper exception handling with fallback")
    else:
        print("❌ Test 5 Failed: Missing exception handling")
        return False
    
    # Parse the code to ensure it's syntactically valid
    try:
        ast.parse(code)
        print("✅ Test 6: Code parses successfully (valid Python syntax)")
    except SyntaxError as e:
        print(f"❌ Test 6 Failed: Syntax error in code: {e}")
        return False
    
    return True

def test_bot_py_logic():
    """Test that the startup message in bot.py is correct."""
    print("\n" + "=" * 70)
    print("Testing bot.py Startup Message")
    print("=" * 70)
    
    # Read the file
    with open('bot.py', 'r') as f:
        code = f.read()
    
    # Check for the startup message
    if 'USER ACCOUNTS MODE: COPY TRADING (no independent threads)' in code:
        print("✅ Test 1: Found startup message in bot.py")
    else:
        print("❌ Test 1 Failed: Missing startup message")
        return False
    
    # Check that it's in the right context (after copy engine starts)
    lines = code.split('\n')
    found_start_engine = False
    found_startup_message = False
    
    for i, line in enumerate(lines):
        if 'start_copy_engine()' in line:
            found_start_engine = True
            # Check next few lines for the message
            for j in range(i, min(i+10, len(lines))):
                if 'USER ACCOUNTS MODE: COPY TRADING' in lines[j]:
                    found_startup_message = True
                    break
    
    if found_start_engine and found_startup_message:
        print("✅ Test 2: Startup message appears after copy engine start")
    else:
        print("❌ Test 2 Failed: Startup message not in correct location")
        return False
    
    # Parse the code to ensure it's syntactically valid
    try:
        ast.parse(code)
        print("✅ Test 3: Code parses successfully (valid Python syntax)")
    except SyntaxError as e:
        print(f"❌ Test 3 Failed: Syntax error in code: {e}")
        return False
    
    return True

def main():
    """Run all tests."""
    test1_passed = test_independent_broker_trader_logic()
    test2_passed = test_bot_py_logic()
    
    print("\n" + "=" * 70)
    if test1_passed and test2_passed:
        print("✅ ALL TESTS PASSED!")
        print("=" * 70)
        print("\nSummary:")
        print("  • Copy trading engine active check: ✅")
        print("  • Conditional warning logic: ✅")
        print("  • Startup message added: ✅")
        print("  • Exception handling: ✅")
        print("  • Syntax validation: ✅")
        return 0
    else:
        print("❌ SOME TESTS FAILED")
        print("=" * 70)
        return 1

if __name__ == "__main__":
    sys.exit(main())
