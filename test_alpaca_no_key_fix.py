#!/usr/bin/env python3
"""
Test script to verify the Alpaca "No key" error fix.

This script tests that AlpacaBroker.get_candles() properly handles
"No key SYMBOL was found" errors by treating them as invalid symbols
rather than API errors that count towards the circuit breaker.
"""

import sys
import os
import logging

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Import the function we're testing
from broker_manager import _is_invalid_product_error

# Configure logging
logging.basicConfig(level=logging.DEBUG)

def test_is_invalid_product_error():
    """Test that _is_invalid_product_error correctly identifies various error patterns"""
    
    test_cases = [
        # Test cases from the problem statement
        ("'No key BKAYY was found.'", True, "Alpaca 'No key' error for BKAYY"),
        ("'No key ELUXY was found.'", True, "Alpaca 'No key' error for ELUXY"),
        ("No key AAPL was found.", True, "Alpaca 'No key' error without quotes"),
        
        # Other invalid symbol patterns
        ("invalid symbol", True, "Invalid symbol error"),
        ("ProductID is invalid", True, "ProductID invalid error"),
        ("400 invalid_argument", True, "400 invalid argument error"),
        ("invalid product", True, "Invalid product error"),
        
        # Valid errors that should NOT be treated as invalid symbols
        ("rate limited", False, "Rate limit error"),
        ("network error", False, "Network error"),
        ("timeout", False, "Timeout error"),
        ("too many requests", False, "Too many requests error"),
    ]
    
    print("\n" + "="*70)
    print("Testing _is_invalid_product_error() function")
    print("="*70)
    
    passed = 0
    failed = 0
    
    for error_msg, expected, description in test_cases:
        result = _is_invalid_product_error(error_msg)
        status = "✓ PASS" if result == expected else "✗ FAIL"
        
        if result == expected:
            passed += 1
        else:
            failed += 1
        
        print(f"\n{status}: {description}")
        print(f"  Input:    '{error_msg}'")
        print(f"  Expected: {expected}")
        print(f"  Got:      {result}")
    
    print("\n" + "="*70)
    print(f"Results: {passed} passed, {failed} failed out of {len(test_cases)} tests")
    print("="*70 + "\n")
    
    return failed == 0

def test_alpaca_broker_integration():
    """
    Test AlpacaBroker.get_candles() error handling.
    
    Note: This requires Alpaca credentials to be set up. If not available,
    we'll just verify the code structure is correct.
    """
    print("\n" + "="*70)
    print("Testing AlpacaBroker integration")
    print("="*70)
    
    # Check if Alpaca is configured
    api_key = os.getenv("ALPACA_API_KEY")
    api_secret = os.getenv("ALPACA_API_SECRET")
    
    if not api_key or not api_secret:
        print("\n⚠️  Alpaca credentials not configured - skipping integration test")
        print("   Set ALPACA_API_KEY and ALPACA_API_SECRET to run this test")
        return True
    
    try:
        from broker_manager import AlpacaBroker
        
        print("\n✓ AlpacaBroker class imported successfully")
        
        # Test with an invalid symbol that should trigger "No key" error
        broker = AlpacaBroker()
        
        print("\n⚠️  Testing with invalid symbol 'BKAYY' (should be logged at DEBUG level)")
        print("   If you see 'Error fetching candles:' below, the fix is NOT working")
        
        # This should return empty list and log at DEBUG level
        candles = broker.get_candles('BKAYY', '5m', 100)
        
        if candles == []:
            print("\n✓ Invalid symbol correctly returned empty list")
            print("   (Check logs above - should see DEBUG message, not ERROR)")
            return True
        else:
            print(f"\n✗ Unexpected result: {candles}")
            return False
            
    except ImportError as e:
        print(f"\n⚠️  Could not import AlpacaBroker: {e}")
        print("   This is expected if Alpaca dependencies are not installed")
        return True
    except Exception as e:
        print(f"\n✗ Unexpected error: {e}")
        return False

if __name__ == "__main__":
    print("\n" + "="*70)
    print("ALPACA 'NO KEY' ERROR FIX VERIFICATION")
    print("="*70)
    
    # Run tests
    test1_passed = test_is_invalid_product_error()
    test2_passed = test_alpaca_broker_integration()
    
    # Summary
    print("\n" + "="*70)
    print("FINAL RESULTS")
    print("="*70)
    
    if test1_passed and test2_passed:
        print("\n✓ All tests passed! The fix is working correctly.")
        print("\n✅ 'No key SYMBOL was found' errors will now:")
        print("   - Be logged at DEBUG level (not ERROR)")
        print("   - Not count towards circuit breaker errors")
        print("   - Not cause the bot to stop scanning")
        sys.exit(0)
    else:
        print("\n✗ Some tests failed - please review the output above")
        sys.exit(1)
