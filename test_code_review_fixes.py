#!/usr/bin/env python3
"""
Test to verify the public 'active' property was added correctly to CopyTradeEngine.
"""

import ast
import sys

def test_active_property():
    """Test that the 'active' property exists in CopyTradeEngine."""
    print("=" * 70)
    print("Testing CopyTradeEngine 'active' Property")
    print("=" * 70)
    
    # Read the file
    with open('bot/copy_trade_engine.py', 'r') as f:
        code = f.read()
    
    # Check for the @property decorator
    if '@property' in code:
        print("✅ Test 1: Found @property decorator")
    else:
        print("❌ Test 1 Failed: Missing @property decorator")
        return False
    
    # Check for the active property definition
    if 'def active(self)' in code:
        print("✅ Test 2: Found 'active' property method")
    else:
        print("❌ Test 2 Failed: Missing 'active' property method")
        return False
    
    # Check that it returns _running
    if 'return self._running' in code:
        print("✅ Test 3: Property returns _running attribute")
    else:
        print("❌ Test 3 Failed: Property doesn't return _running")
        return False
    
    # Check for documentation
    if 'Check if the copy trade engine is currently active' in code:
        print("✅ Test 4: Property has proper documentation")
    else:
        print("❌ Test 4 Failed: Missing documentation")
        return False
    
    # Parse to check syntax
    try:
        ast.parse(code)
        print("✅ Test 5: Code is syntactically valid")
    except SyntaxError as e:
        print(f"❌ Test 5 Failed: Syntax error: {e}")
        return False
    
    return True

def test_import_at_top():
    """Test that copy_trade_engine import is at the top of independent_broker_trader.py."""
    print("\n" + "=" * 70)
    print("Testing Import Location in independent_broker_trader.py")
    print("=" * 70)
    
    # Read the file
    with open('bot/independent_broker_trader.py', 'r') as f:
        lines = f.readlines()
    
    # Find where imports end (before first function/class definition)
    import_section_end = 0
    for i, line in enumerate(lines):
        if line.startswith('def ') or line.startswith('class '):
            import_section_end = i
            break
        if 'logger = logging.getLogger' in line:
            import_section_end = i
            break
    
    # Check if copy_trade_engine import is in the import section
    found_import = False
    for i in range(import_section_end):
        if 'from bot.copy_trade_engine import get_copy_engine' in lines[i] or \
           'from copy_trade_engine import get_copy_engine' in lines[i]:
            found_import = True
            print(f"✅ Test 1: Found import at line {i+1} (in import section)")
            break
    
    if not found_import:
        print("❌ Test 1 Failed: Import not found in import section")
        return False
    
    return True

def test_uses_active_property():
    """Test that independent_broker_trader.py uses .active instead of ._running."""
    print("\n" + "=" * 70)
    print("Testing Usage of 'active' Property")
    print("=" * 70)
    
    # Read the file
    with open('bot/independent_broker_trader.py', 'r') as f:
        code = f.read()
    
    # Check that it uses .active
    if 'copy_trading_engine.active' in code:
        print("✅ Test 1: Code uses .active property")
    else:
        print("❌ Test 1 Failed: Code doesn't use .active property")
        return False
    
    # Check that it doesn't use ._running (in the context of copy_trading_engine)
    # This is a bit tricky because other code might use ._running
    lines = code.split('\n')
    found_bad_usage = False
    for i, line in enumerate(lines):
        if 'copy_trading_engine._running' in line:
            print(f"❌ Test 2 Failed: Found ._running usage at line {i+1}")
            found_bad_usage = True
    
    if not found_bad_usage:
        print("✅ Test 2: Code doesn't access private ._running attribute")
    else:
        return False
    
    return True

def main():
    """Run all tests."""
    test1 = test_active_property()
    test2 = test_import_at_top()
    test3 = test_uses_active_property()
    
    print("\n" + "=" * 70)
    if test1 and test2 and test3:
        print("✅ ALL CODE REVIEW FIXES IMPLEMENTED!")
        print("=" * 70)
        print("\nSummary:")
        print("  • Added public 'active' property to CopyTradeEngine: ✅")
        print("  • Moved import to top of file: ✅")
        print("  • Using public property instead of private attribute: ✅")
        print("  • Proper encapsulation: ✅")
        return 0
    else:
        print("❌ SOME FIXES INCOMPLETE")
        print("=" * 70)
        return 1

if __name__ == "__main__":
    sys.exit(main())
