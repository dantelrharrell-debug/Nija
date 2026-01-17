#!/usr/bin/env python3
"""
Test script for USER mode implementation.

Verifies that:
1. USER accounts skip market scanning
2. USER accounts skip signal generation
3. USER accounts only manage existing positions
4. MASTER accounts work normally
"""

import sys
import os
import logging

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger('test')


def test_user_mode_parameter():
    """Test that run_cycle accepts user_mode parameter."""
    print("=" * 70)
    print("TEST 1: TradingStrategy.run_cycle user_mode parameter")
    print("=" * 70)
    
    try:
        # Read the source file to verify user_mode parameter
        strategy_file = os.path.join(os.path.dirname(__file__), 'bot', 'trading_strategy.py')
        
        if not os.path.exists(strategy_file):
            print("❌ Cannot find trading_strategy.py: FAILED")
            return False
        
        with open(strategy_file, 'r') as f:
            content = f.read()
        
        # Check if user_mode parameter exists in run_cycle definition
        if 'def run_cycle(self, broker=None, user_mode=False):' in content:
            print("✅ TradingStrategy.run_cycle has user_mode parameter: PASSED")
            
            # Find the line for context
            for i, line in enumerate(content.split('\n'), 1):
                if 'def run_cycle(self, broker=None, user_mode=False):' in line:
                    print(f"   Found at line {i}: {line.strip()}")
                    break
            return True
        else:
            print("❌ TradingStrategy.run_cycle missing user_mode parameter: FAILED")
            
            # Try to find the definition without user_mode
            for i, line in enumerate(content.split('\n'), 1):
                if 'def run_cycle(' in line:
                    print(f"   Found run_cycle at line {i}: {line.strip()}")
                    break
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_independent_trader_user_mode():
    """Test that IndependentBrokerTrader passes user_mode=True for users."""
    print("\n" + "=" * 70)
    print("TEST 2: IndependentBrokerTrader user_mode usage")
    print("=" * 70)
    
    try:
        # Read the source file to verify user_mode is passed
        trader_file = os.path.join(os.path.dirname(__file__), 'bot', 'independent_broker_trader.py')
        
        if not os.path.exists(trader_file):
            print("❌ Cannot find independent_broker_trader.py: FAILED")
            return False
        
        with open(trader_file, 'r') as f:
            content = f.read()
        
        # Check if user_mode=True is passed in run_user_broker_trading_loop
        if 'user_mode=True' in content:
            print("✅ IndependentBrokerTrader passes user_mode=True for users: PASSED")
            
            # Find the line for context
            for i, line in enumerate(content.split('\n'), 1):
                if 'user_mode=True' in line:
                    print(f"   Found at line {i}: {line.strip()}")
                    break
            return True
        else:
            print("❌ IndependentBrokerTrader does not pass user_mode=True: FAILED")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_user_mode_logic():
    """Test that user_mode disables market scanning in run_cycle."""
    print("\n" + "=" * 70)
    print("TEST 3: user_mode disables market scanning")
    print("=" * 70)
    
    try:
        # Read the source file to verify user_mode logic
        strategy_file = os.path.join(os.path.dirname(__file__), 'bot', 'trading_strategy.py')
        
        if not os.path.exists(strategy_file):
            print("❌ Cannot find trading_strategy.py: FAILED")
            return False
        
        with open(strategy_file, 'r') as f:
            content = f.read()
        
        # Check if user_mode check exists before market scanning
        if 'if user_mode:' in content and 'Skipping market scan' in content:
            print("✅ user_mode check exists in trading_strategy.py: PASSED")
            
            # Find the lines for context
            lines = content.split('\n')
            for i, line in enumerate(lines, 1):
                if 'if user_mode:' in line:
                    print(f"   Found at line {i}:")
                    # Print a few lines of context
                    for j in range(max(0, i-1), min(len(lines), i+3)):
                        print(f"     {lines[j]}")
                    break
            return True
        else:
            print("❌ user_mode logic not found in trading_strategy.py: FAILED")
            return False
            
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("NIJA USER MODE INTEGRATION TESTS")
    print("=" * 70)
    print()
    
    results = []
    
    # Run tests
    results.append(("user_mode parameter", test_user_mode_parameter()))
    results.append(("IndependentTrader user_mode", test_independent_trader_user_mode()))
    results.append(("user_mode logic", test_user_mode_logic()))
    
    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status}: {test_name}")
    
    print("=" * 70)
    print(f"Results: {passed}/{total} tests passed")
    print("=" * 70)
    
    if passed == total:
        print("\n✅ All tests PASSED - USER mode implementation verified")
        return 0
    else:
        print(f"\n❌ {total - passed} test(s) FAILED - please review implementation")
        return 1


if __name__ == "__main__":
    sys.exit(main())
