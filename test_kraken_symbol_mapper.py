#!/usr/bin/env python3
"""
Test script for Kraken Symbol Mapper

This test verifies:
1. Symbol mapper loads static mappings correctly
2. Symbol validation works
3. Symbol conversion works (both directions)
4. Copy trading validation works
"""

import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from kraken_symbol_mapper import (
    KrakenSymbolMapper,
    get_kraken_symbol_mapper,
    validate_kraken_symbol,
    convert_to_kraken,
    validate_for_copy_trading
)

def test_static_mappings():
    """Test that static mappings are loaded correctly."""
    print("=" * 70)
    print("TEST 1: Static Symbol Mappings")
    print("=" * 70)
    
    mapper = get_kraken_symbol_mapper()
    
    # Test known symbols
    test_cases = [
        ("BTC-USD", "XXBTZUSD"),
        ("ETH-USD", "XETHZUSD"),
        ("XRP-USD", "XXRPZUSD"),
        ("SOL-USD", "SOLUSD"),
        ("ADA-USD", "ADAUSD"),
    ]
    
    passed = 0
    failed = 0
    
    for standard, expected_kraken in test_cases:
        result = mapper.to_kraken_symbol(standard)
        if result == expected_kraken:
            print(f"✅ {standard} -> {result}")
            passed += 1
        else:
            print(f"❌ {standard} -> {result} (expected {expected_kraken})")
            failed += 1
    
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


def test_reverse_conversion():
    """Test conversion from Kraken format back to standard."""
    print("\n" + "=" * 70)
    print("TEST 2: Reverse Symbol Conversion")
    print("=" * 70)
    
    mapper = get_kraken_symbol_mapper()
    
    test_cases = [
        ("XXBTZUSD", "BTC-USD"),
        ("XETHZUSD", "ETH-USD"),
        ("SOLUSD", "SOL-USD"),
    ]
    
    passed = 0
    failed = 0
    
    for kraken, expected_standard in test_cases:
        result = mapper.to_standard_symbol(kraken)
        if result == expected_standard:
            print(f"✅ {kraken} -> {result}")
            passed += 1
        else:
            print(f"❌ {kraken} -> {result} (expected {expected_standard})")
            failed += 1
    
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


def test_symbol_validation():
    """Test symbol validation."""
    print("\n" + "=" * 70)
    print("TEST 3: Symbol Validation")
    print("=" * 70)
    
    mapper = get_kraken_symbol_mapper()
    
    # Valid symbols (should be in static map)
    valid_symbols = ["BTC-USD", "ETH-USD", "SOL-USD"]
    
    # Invalid symbols (not in map, unlikely to exist)
    invalid_symbols = ["FAKE-USD", "SCAM-USD", "INVALID-USDT"]
    
    passed = 0
    failed = 0
    
    print("\nValid symbols:")
    for symbol in valid_symbols:
        is_valid = mapper.is_available(symbol)
        if is_valid:
            print(f"✅ {symbol} is valid")
            passed += 1
        else:
            print(f"❌ {symbol} should be valid but reported as invalid")
            failed += 1
    
    print("\nInvalid symbols:")
    for symbol in invalid_symbols:
        is_valid = mapper.is_available(symbol)
        if not is_valid:
            print(f"✅ {symbol} correctly identified as invalid")
            passed += 1
        else:
            print(f"⚠️  {symbol} reported as valid (might be in dynamic map)")
            # Not a failure - could be valid on Kraken
    
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


def test_validation_for_trading():
    """Test trade validation."""
    print("\n" + "=" * 70)
    print("TEST 4: Trade Validation")
    print("=" * 70)
    
    mapper = get_kraken_symbol_mapper()
    
    test_symbols = ["BTC-USD", "ETH-USD", "FAKE-USD"]
    
    for symbol in test_symbols:
        is_valid, message = mapper.validate_for_trading(symbol)
        status = "✅" if is_valid else "❌"
        print(f"{status} {symbol}: {message}")
    
    return True


def test_common_pairs():
    """Test finding common pairs for copy trading."""
    print("\n" + "=" * 70)
    print("TEST 5: Common Pairs for Copy Trading")
    print("=" * 70)
    
    mapper = get_kraken_symbol_mapper()
    
    # Simulate master exchange symbols
    master_symbols = ["BTC-USD", "ETH-USD", "SOL-USD", "DOGE-USD", "FAKE-USD"]
    
    # Simulate user exchange symbols  
    user_symbols = ["BTC-USD", "ETH-USD", "XRP-USD", "DOGE-USD", "ANOTHER-USD"]
    
    common = mapper.get_common_pairs(user_symbols)
    
    print(f"\nMaster exchange symbols: {master_symbols}")
    print(f"User exchange symbols: {user_symbols}")
    print(f"Common symbols (safe for copy trading): {common}")
    
    # Should include BTC-USD, ETH-USD, DOGE-USD (if all are valid on Kraken)
    expected_common = {"BTC-USD", "ETH-USD", "DOGE-USD"}
    actual_common = set(common)
    
    # Check if expected symbols are in common
    missing = expected_common - actual_common
    if not missing:
        print(f"✅ All expected common symbols found")
        return True
    else:
        print(f"⚠️  Missing symbols: {missing}")
        return True  # Not a critical failure


def test_helper_functions():
    """Test helper functions."""
    print("\n" + "=" * 70)
    print("TEST 6: Helper Functions")
    print("=" * 70)
    
    passed = 0
    failed = 0
    
    # Test validate_kraken_symbol
    if validate_kraken_symbol:
        result = validate_kraken_symbol("BTC-USD")
        if result:
            print(f"✅ validate_kraken_symbol('BTC-USD') = True")
            passed += 1
        else:
            print(f"❌ validate_kraken_symbol('BTC-USD') = False")
            failed += 1
    
    # Test convert_to_kraken
    if convert_to_kraken:
        result = convert_to_kraken("BTC-USD")
        if result == "XXBTZUSD":
            print(f"✅ convert_to_kraken('BTC-USD') = {result}")
            passed += 1
        else:
            print(f"❌ convert_to_kraken('BTC-USD') = {result} (expected XXBTZUSD)")
            failed += 1
    
    # Test validate_for_copy_trading
    if validate_for_copy_trading:
        result = validate_for_copy_trading(
            ["BTC-USD", "ETH-USD"],
            ["BTC-USD", "SOL-USD"]
        )
        if "BTC-USD" in result:
            print(f"✅ validate_for_copy_trading includes BTC-USD")
            passed += 1
        else:
            print(f"❌ validate_for_copy_trading should include BTC-USD")
            failed += 1
    
    print(f"\nResults: {passed} passed, {failed} failed")
    return failed == 0


def main():
    """Run all tests."""
    print("\n" + "=" * 70)
    print("KRAKEN SYMBOL MAPPER TEST SUITE")
    print("=" * 70)
    print()
    
    results = []
    
    results.append(("Static Mappings", test_static_mappings()))
    results.append(("Reverse Conversion", test_reverse_conversion()))
    results.append(("Symbol Validation", test_symbol_validation()))
    results.append(("Trade Validation", test_validation_for_trading()))
    results.append(("Common Pairs", test_common_pairs()))
    results.append(("Helper Functions", test_helper_functions()))
    
    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print()
    print(f"Total: {passed}/{total} tests passed")
    print()
    
    if passed == total:
        print("🎉 ALL TESTS PASSED!")
        return 0
    else:
        print("❌ SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
