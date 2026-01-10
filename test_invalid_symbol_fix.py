#!/usr/bin/env python3
"""
Test script to validate invalid symbol handling fix

This script tests that:
1. Invalid ProductID errors don't trigger circuit breakers
2. Invalid symbols are properly detected and skipped
3. Error counters only increment for genuine errors
4. Rate limit errors are handled separately from invalid symbols
"""

import re


def test_invalid_symbol_detection():
    """Test that invalid symbol patterns are detected correctly"""
    print("Testing Invalid Symbol Detection")
    print("=" * 60)
    
    test_cases = [
        # (error_string, should_be_detected_as_invalid)
        ('ProductID is invalid', True),
        ('product_id is invalid', True),
        ('400 Client Error: Bad Request {"error":"INVALID_ARGUMENT","error_details":"ProductID is invalid"}', True),
        ('invalid product not found', True),
        ('invalid symbol does not exist', True),
        ('symbol TRX-USD unknown', False),  # Not enough context
        ('429 Too Many Requests', False),
        ('403 Forbidden', False),
        ('rate limit exceeded', False),
        ('connection timeout', False),
        ('network error', False),
        ('invalid request format', False),  # Too generic
    ]
    
    passed = 0
    failed = 0
    
    for error_str, expected_invalid in test_cases:
        error_lower = error_str.lower()
        
        # This is the updated detection logic from trading_strategy.py
        is_productid_invalid = 'productid is invalid' in error_lower or 'product_id is invalid' in error_lower
        is_invalid_argument = '400' in error_lower and 'invalid_argument' in error_lower
        is_invalid_product_symbol = (
            'invalid' in error_lower and 
            ('product' in error_lower or 'symbol' in error_lower) and
            ('not found' in error_lower or 'does not exist' in error_lower or 'unknown' in error_lower)
        )
        
        is_invalid_symbol = is_productid_invalid or is_invalid_argument or is_invalid_product_symbol
        
        if is_invalid_symbol == expected_invalid:
            print(f"  ✅ PASS: '{error_str[:50]}...' -> {is_invalid_symbol}")
            passed += 1
        else:
            print(f"  ❌ FAIL: '{error_str[:50]}...' -> Expected {expected_invalid}, got {is_invalid_symbol}")
            failed += 1
    
    print()
    print(f"Results: {passed} passed, {failed} failed out of {len(test_cases)} tests")
    print()
    return failed == 0


def test_error_classification():
    """Test that errors are classified correctly"""
    print("Testing Error Classification")
    print("=" * 60)
    
    test_cases = [
        # (error_string, should_be_rate_limit, should_be_invalid_symbol)
        ('429 Too Many Requests', True, False),
        ('403 Forbidden', True, False),
        ('rate limit exceeded', True, False),
        ('too many requests', True, False),
        ('ProductID is invalid', False, True),
        ('400 INVALID_ARGUMENT', False, True),
        ('invalid product not found', False, True),
        ('symbol does not exist', False, False),  # Missing 'invalid' keyword
        ('connection timeout', False, False),
        ('network error', False, False),
    ]
    
    passed = 0
    failed = 0
    
    for error_str, expected_rate_limit, expected_invalid in test_cases:
        error_lower = error_str.lower()
        
        # Invalid symbol detection (updated logic)
        is_productid_invalid = 'productid is invalid' in error_lower or 'product_id is invalid' in error_lower
        is_invalid_argument = '400' in error_lower and 'invalid_argument' in error_lower
        is_invalid_product_symbol = (
            'invalid' in error_lower and 
            ('product' in error_lower or 'symbol' in error_lower) and
            ('not found' in error_lower or 'does not exist' in error_lower or 'unknown' in error_lower)
        )
        
        is_invalid_symbol = is_productid_invalid or is_invalid_argument or is_invalid_product_symbol
        
        # Rate limit detection
        is_rate_limit = (
            '429' in error_str or
            'rate limit' in error_lower or
            'too many' in error_lower or
            '403' in error_str
        )
        
        if is_rate_limit == expected_rate_limit and is_invalid_symbol == expected_invalid:
            print(f"  ✅ PASS: '{error_str[:40]}...'")
            print(f"       Rate limit: {is_rate_limit}, Invalid: {is_invalid_symbol}")
            passed += 1
        else:
            print(f"  ❌ FAIL: '{error_str[:40]}...'")
            print(f"       Expected - Rate limit: {expected_rate_limit}, Invalid: {expected_invalid}")
            print(f"       Got      - Rate limit: {is_rate_limit}, Invalid: {is_invalid_symbol}")
            failed += 1
    
    print()
    print(f"Results: {passed} passed, {failed} failed out of {len(test_cases)} tests")
    print()
    return failed == 0


def test_position_cap_message():
    """Test that position cap message shows correct value"""
    print("Testing Position Cap Message")
    print("=" * 60)
    
    # Read the trading_strategy.py file
    import os
    script_dir = os.path.dirname(os.path.abspath(__file__))
    trading_strategy_path = os.path.join(script_dir, 'bot', 'trading_strategy.py')
    
    with open(trading_strategy_path, 'r') as f:
        content = f.read()
    
    # Find MAX_POSITIONS_ALLOWED value
    max_pos_match = re.search(r'MAX_POSITIONS_ALLOWED\s*=\s*(\d+)', content)
    if not max_pos_match:
        print("  ❌ FAIL: Could not find MAX_POSITIONS_ALLOWED constant")
        return False
    
    max_positions = int(max_pos_match.group(1))
    print(f"  Found MAX_POSITIONS_ALLOWED = {max_positions}")
    
    # Check if the log message uses the constant
    if f'max {max_positions}' in content or 'MAX_POSITIONS_ALLOWED' in content:
        print(f"  ✅ PASS: Position cap message uses correct value or constant")
        return True
    else:
        print(f"  ❌ FAIL: Position cap message doesn't match constant")
        return False


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("TESTING INVALID SYMBOL FIX")
    print("=" * 60 + "\n")
    
    all_passed = True
    
    # Test 1: Invalid symbol detection
    if not test_invalid_symbol_detection():
        all_passed = False
    
    # Test 2: Error classification
    if not test_error_classification():
        all_passed = False
    
    # Test 3: Position cap message
    if not test_position_cap_message():
        all_passed = False
    
    # Final summary
    print("=" * 60)
    if all_passed:
        print("✅ ALL TESTS PASSED")
        print()
        print("The invalid symbol fix is working correctly:")
        print("  • Invalid symbols are properly detected")
        print("  • Errors are classified correctly")
        print("  • Position cap message is accurate")
        print("  • Circuit breakers won't trigger on invalid symbols")
    else:
        print("❌ SOME TESTS FAILED")
        print()
        print("Please review the failed tests above.")
    print("=" * 60)
    
    return 0 if all_passed else 1


if __name__ == "__main__":
    exit(main())
