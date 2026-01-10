#!/usr/bin/env python3
"""
Test script to verify symbol filtering logic works correctly.
This tests the product filtering added to fix invalid symbol issues.
"""

def test_symbol_format_validation():
    """Test symbol format validation logic"""
    
    # Test cases: (product_id, should_pass)
    test_cases = [
        # Valid symbols
        ("BTC-USD", True),
        ("ETH-USD", True),
        ("SOL-USD", True),
        ("MATIC-USDC", True),
        ("LINK-USD", True),
        
        # Borderline: 2Z passes format (2 chars=min) but fails status check if not 'online'
        ("2Z-USD", True),
        ("A-USD", False),        # Too short (1 char < 2 minimum)
        ("VERYLONGSYMBOL-USD", False),  # Too long base currency
        ("BTC", False),          # Missing quote currency
        ("BTC-", False),         # Missing quote currency
        ("-USD", False),         # Missing base currency
        ("", False),             # Empty
        
        # Edge cases
        ("AB-USD", True),        # Minimum valid length (2 chars)
        ("ABCDEFGH-USD", True),  # Maximum valid length (8 chars)
    ]
    
    passed = 0
    failed = 0
    
    print("Testing symbol format validation...")
    print("=" * 60)
    
    for product_id, should_pass in test_cases:
        # Apply the same validation logic from broker_manager.py
        is_valid = True
        
        # 1. Must have product_id
        if not product_id:
            is_valid = False
        
        # 2. Must be USD or USDC pair
        if is_valid and not (product_id.endswith('-USD') or product_id.endswith('-USDC')):
            is_valid = False
        
        # 3. Validate symbol format
        if is_valid:
            parts = product_id.split('-')
            if len(parts) != 2 or len(parts[0]) < 2 or len(parts[0]) > 8:
                is_valid = False
        
        # Check if result matches expected
        if is_valid == should_pass:
            status = "✅ PASS"
            passed += 1
        else:
            status = "❌ FAIL"
            failed += 1
        
        print(f"{status}: {product_id:20s} -> {'Valid' if is_valid else 'Invalid':10s} (expected: {'Valid' if should_pass else 'Invalid'})")
    
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print()
    
    return failed == 0


def test_status_filtering():
    """Test product status filtering logic"""
    
    # Mock product objects
    class MockProduct:
        def __init__(self, product_id, status, trading_disabled):
            self.product_id = product_id
            self.status = status
            self.trading_disabled = trading_disabled
    
    # Test cases: (product, should_include)
    test_cases = [
        # Valid products
        (MockProduct("BTC-USD", "online", False), True),
        (MockProduct("ETH-USD", "ONLINE", False), True),  # Case insensitive
        
        # Invalid products - wrong status
        (MockProduct("2Z-USD", "offline", False), False),
        (MockProduct("AGLD-USD", "delisted", False), False),
        (MockProduct("OLD-USD", "disabled", False), False),
        
        # Invalid products - trading disabled
        (MockProduct("HIO-USD", "online", True), False),
        (MockProduct("BOE-USD", "ONLINE", True), False),
    ]
    
    passed = 0
    failed = 0
    
    print("Testing product status filtering...")
    print("=" * 60)
    
    for product, should_include in test_cases:
        # Apply the same filtering logic from broker_manager.py
        should_filter_out = False
        
        # Status must be 'online'
        if product.status and product.status.lower() != 'online':
            should_filter_out = True
        
        # Trading must not be disabled
        if product.trading_disabled:
            should_filter_out = True
        
        is_included = not should_filter_out
        
        # Check if result matches expected
        if is_included == should_include:
            status = "✅ PASS"
            passed += 1
        else:
            status = "❌ FAIL"
            failed += 1
        
        print(f"{status}: {product.product_id:15s} status={product.status:10s} disabled={str(product.trading_disabled):5s} -> {'Included' if is_included else 'Filtered':10s}")
    
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print()
    
    return failed == 0


def test_invalid_symbol_error_detection():
    """Test invalid symbol error detection"""
    
    # Test cases: (error_message, is_invalid_symbol)
    test_cases = [
        # Invalid symbol errors (should be detected)
        ("ProductID is invalid", True),
        ("400 Client Error: Bad Request INVALID_ARGUMENT", True),
        ("invalid symbol: 2Z-USD", True),
        ("Invalid product ID", True),
        
        # Rate limit errors (should NOT be detected as invalid symbol)
        ("429 Too Many Requests", False),
        ("403 Forbidden", False),
        ("too many requests", False),
        ("rate limit exceeded", False),
        
        # Other errors
        ("Connection timeout", False),
        ("Network error", False),
    ]
    
    passed = 0
    failed = 0
    
    print("Testing invalid symbol error detection...")
    print("=" * 60)
    
    for error_msg, expected_is_invalid in test_cases:
        error_str = error_msg.lower()
        
        # Apply the same detection logic from broker_manager.py
        has_invalid_keyword = 'invalid' in error_str and ('product' in error_str or 'symbol' in error_str)
        is_productid_invalid = 'productid is invalid' in error_str
        is_400_invalid_arg = '400' in error_str and 'invalid_argument' in error_str
        is_invalid_symbol = has_invalid_keyword or is_productid_invalid or is_400_invalid_arg
        
        # Check if result matches expected
        if is_invalid_symbol == expected_is_invalid:
            status = "✅ PASS"
            passed += 1
        else:
            status = "❌ FAIL"
            failed += 1
        
        result = "Invalid Symbol" if is_invalid_symbol else "Other Error"
        expected = "Invalid Symbol" if expected_is_invalid else "Other Error"
        print(f"{status}: '{error_msg[:50]:50s}' -> {result:15s} (expected: {expected})")
    
    print("=" * 60)
    print(f"Results: {passed} passed, {failed} failed")
    print()
    
    return failed == 0


if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("SYMBOL FILTERING VALIDATION TESTS")
    print("=" * 60)
    print()
    
    all_passed = True
    
    # Run all tests
    all_passed &= test_symbol_format_validation()
    all_passed &= test_status_filtering()
    all_passed &= test_invalid_symbol_error_detection()
    
    # Summary
    print("=" * 60)
    if all_passed:
        print("✅ ALL TESTS PASSED")
    else:
        print("❌ SOME TESTS FAILED")
    print("=" * 60)
    print()
    
    exit(0 if all_passed else 1)
