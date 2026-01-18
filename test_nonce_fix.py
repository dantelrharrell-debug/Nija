#!/usr/bin/env python3
"""
Test script to verify Kraken nonce fix (Jan 18, 2026)

This script tests that:
1. Nonces are generated in milliseconds (not microseconds)
2. Old microsecond nonces are properly converted to milliseconds
3. Nonce values are reasonable and monotonically increasing
"""

import sys
import os
import time

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import get_kraken_nonce, get_kraken_nonce_file
from kraken_nonce import KrakenNonce

def test_nonce_precision():
    """Test that nonces are in milliseconds, not microseconds."""
    print("=" * 70)
    print("TEST 1: Nonce Precision")
    print("=" * 70)
    
    # Get current time in both formats
    current_time_ms = int(time.time() * 1000)
    current_time_us = int(time.time() * 1000000)
    
    print(f"Current time (milliseconds): {current_time_ms}")
    print(f"Current time (microseconds): {current_time_us}")
    print(f"Difference: {current_time_us / current_time_ms}x")
    
    # Test get_kraken_nonce
    test_account = "test_nonce_fix"
    nonce = get_kraken_nonce(test_account)
    
    print(f"\nGenerated nonce: {nonce}")
    print(f"Nonce digits: {len(str(nonce))}")
    
    # Verify it's in milliseconds (13 digits) not microseconds (16 digits)
    if len(str(nonce)) <= 14:  # Allow some wiggle room for year 2038+
        print("✅ PASS: Nonce is in milliseconds (13-14 digits)")
    else:
        print(f"❌ FAIL: Nonce has {len(str(nonce))} digits (expected 13-14 for milliseconds)")
        return False
    
    # Verify nonce is close to current time
    diff_ms = abs(nonce - current_time_ms)
    print(f"\nDifference from current time: {diff_ms}ms ({diff_ms/1000:.2f}s)")
    
    if diff_ms < 60000:  # Within 60 seconds
        print("✅ PASS: Nonce is within 60s of current time")
    else:
        print(f"❌ FAIL: Nonce is {diff_ms/1000:.2f}s away from current time")
        return False
    
    # Clean up test file
    nonce_file = get_kraken_nonce_file(test_account)
    if os.path.exists(nonce_file):
        os.remove(nonce_file)
    
    return True

def test_microsecond_conversion():
    """Test that old microsecond nonces are converted to milliseconds."""
    print("\n" + "=" * 70)
    print("TEST 2: Microsecond to Millisecond Conversion")
    print("=" * 70)
    
    test_account = "test_conversion"
    nonce_file = get_kraken_nonce_file(test_account)
    
    # Write a microsecond nonce to file
    old_microsecond_nonce = int(time.time() * 1000000)
    with open(nonce_file, 'w') as f:
        f.write(str(old_microsecond_nonce))
    
    print(f"Written microsecond nonce to file: {old_microsecond_nonce}")
    print(f"Nonce digits: {len(str(old_microsecond_nonce))}")
    
    # Load it back - should be converted to milliseconds
    converted_nonce = get_kraken_nonce(test_account)
    
    print(f"\nLoaded nonce (should be converted): {converted_nonce}")
    print(f"Nonce digits: {len(str(converted_nonce))}")
    
    # Verify conversion happened
    if len(str(converted_nonce)) <= 14:
        print("✅ PASS: Old microsecond nonce was converted to milliseconds")
    else:
        print(f"❌ FAIL: Nonce still has {len(str(converted_nonce))} digits (not converted)")
        os.remove(nonce_file)
        return False
    
    # Verify the conversion is approximately correct
    expected_ms = int(old_microsecond_nonce / 1000)
    if abs(converted_nonce - expected_ms) < 1000:  # Within 1 second
        print(f"✅ PASS: Converted value is correct ({converted_nonce} ≈ {expected_ms})")
    else:
        print(f"❌ FAIL: Converted value {converted_nonce} differs from expected {expected_ms}")
        os.remove(nonce_file)
        return False
    
    # Clean up
    os.remove(nonce_file)
    return True

def test_kraken_nonce_class():
    """Test that KrakenNonce class generates millisecond nonces."""
    print("\n" + "=" * 70)
    print("TEST 3: KrakenNonce Class")
    print("=" * 70)
    
    # Create KrakenNonce instance
    nonce_gen = KrakenNonce()
    
    print(f"Initial nonce: {nonce_gen.last}")
    print(f"Nonce digits: {len(str(nonce_gen.last))}")
    
    # Verify initial nonce is in milliseconds
    if len(str(nonce_gen.last)) <= 14:
        print("✅ PASS: KrakenNonce uses milliseconds")
    else:
        print(f"❌ FAIL: KrakenNonce has {len(str(nonce_gen.last))} digits")
        return False
    
    # Generate a few nonces
    nonce1 = nonce_gen.next()
    nonce2 = nonce_gen.next()
    nonce3 = nonce_gen.next()
    
    print(f"\nGenerated nonces:")
    print(f"  {nonce1}")
    print(f"  {nonce2}")
    print(f"  {nonce3}")
    
    # Verify they're monotonically increasing
    if nonce1 < nonce2 < nonce3:
        print("✅ PASS: Nonces are monotonically increasing")
    else:
        print("❌ FAIL: Nonces are not monotonically increasing")
        return False
    
    # Verify increments are small (should be +1 each time)
    if (nonce2 - nonce1) <= 10 and (nonce3 - nonce2) <= 10:
        print("✅ PASS: Nonce increments are reasonable")
    else:
        print(f"❌ FAIL: Nonce increments are too large ({nonce2-nonce1}, {nonce3-nonce2})")
        return False
    
    return True

def main():
    """Run all nonce tests."""
    print("\n" + "=" * 70)
    print("KRAKEN NONCE FIX VERIFICATION (Jan 18, 2026)")
    print("=" * 70)
    print("\nTesting nonce generation and conversion to ensure millisecond precision...\n")
    
    results = []
    
    # Run tests
    results.append(("Nonce Precision", test_nonce_precision()))
    results.append(("Microsecond Conversion", test_microsecond_conversion()))
    results.append(("KrakenNonce Class", test_kraken_nonce_class()))
    
    # Summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print(f"\nTotal: {passed}/{total} tests passed")
    
    if passed == total:
        print("\n✅ All tests passed! Nonce fix is working correctly.")
        return 0
    else:
        print(f"\n❌ {total - passed} test(s) failed. Nonce fix needs attention.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
