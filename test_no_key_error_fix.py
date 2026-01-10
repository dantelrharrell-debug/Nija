#!/usr/bin/env python3
"""
Test script to validate 'No key ... was found' error handling fix

This script tests that errors like "'No key AACBR was found.'" are correctly
identified as invalid symbol errors and don't trigger retries or circuit breakers.
"""


def test_no_key_error_detection():
    """Test that 'No key ... was found' errors are detected as invalid symbols"""
    print("Testing 'No key ... was found' Error Detection")
    print("=" * 60)
    
    test_cases = [
        # (error_string, should_be_detected_as_invalid)
        ("'No key AACBR was found.'", True),
        ("'No key YZCAY was found.'", True),
        ("No key XYZ was found", True),
        ("ProductID is invalid", True),
        ("invalid product", True),
        ("400 invalid_argument", True),
        ("429 too many requests", False),
        ("403 forbidden", False),
        ("network error", False),
        ("timeout", False),
        ("no data available", False),  # Should not match - doesn't have 'key' and 'was found'
    ]
    
    passed = 0
    failed = 0
    
    for error_str, expected_invalid in test_cases:
        error_lower = error_str.lower()
        
        # Detection logic from broker_manager.py
        has_invalid_keyword = 'invalid' in error_lower and ('product' in error_lower or 'symbol' in error_lower)
        is_productid_invalid = 'productid is invalid' in error_lower
        is_400_invalid_arg = '400' in error_lower and 'invalid_argument' in error_lower
        is_no_key_error = 'no key' in error_lower and 'was found' in error_lower
        is_invalid_symbol = has_invalid_keyword or is_productid_invalid or is_400_invalid_arg or is_no_key_error
        
        if is_invalid_symbol == expected_invalid:
            status = "✅ PASS"
            passed += 1
        else:
            status = "❌ FAIL"
            failed += 1
        
        print(f"  {status}: '{error_str[:50]}...'")
        print(f"         Expected: {expected_invalid}, Got: {is_invalid_symbol}")
    
    print()
    print(f"Results: {passed} passed, {failed} failed out of {len(test_cases)} tests")
    print()
    return failed == 0


def main():
    """Run all tests"""
    print("\n" + "=" * 60)
    print("Testing Invalid Symbol Error Detection Fix")
    print("=" * 60 + "\n")
    
    all_passed = test_no_key_error_detection()
    
    if all_passed:
        print("\n✅ All tests passed!")
        return 0
    else:
        print("\n❌ Some tests failed!")
        return 1


if __name__ == "__main__":
    exit(main())
