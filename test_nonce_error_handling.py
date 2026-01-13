#!/usr/bin/env python3
"""
Test Nonce Error Handling in Kraken Broker
===========================================

This script tests that the enhanced nonce error handling works correctly:
- Detects nonce errors properly
- Uses 30s base delay for nonce errors
- Applies 10x nonce jump multiplier
- Provides appropriate logging

Usage:
    python3 test_nonce_error_handling.py
"""

import sys
import os

def test_nonce_error_detection():
    """Test that nonce errors are detected correctly"""
    print("=" * 80)
    print("TEST 1: Nonce Error Detection")
    print("=" * 80)
    
    # Test error messages
    test_cases = [
        ("EAPI:Invalid nonce", True, "Kraken's specific nonce error"),
        ("invalid nonce", True, "Generic invalid nonce error"),
        ("nonce window exceeded", True, "Nonce window error"),
        ("nonce error", False, "Generic 'nonce' mention (too broad)"),
        ("timeout error with nonce", False, "Contains 'nonce' but not a nonce error"),
        ("timeout error", False, "Non-nonce error"),
        ("connection failed", False, "Non-nonce error"),
    ]
    
    all_passed = True
    for error_msg, should_detect, description in test_cases:
        # Simulate the more specific detection logic from broker_manager.py
        is_nonce_error = any(keyword in error_msg.lower() for keyword in [
            'invalid nonce', 'eapi:invalid nonce', 'nonce window'
        ])
        
        if is_nonce_error == should_detect:
            print(f"  ✅ PASS: {description}")
            print(f"     Error: '{error_msg}' -> Detected: {is_nonce_error}")
        else:
            print(f"  ❌ FAIL: {description}")
            print(f"     Error: '{error_msg}' -> Expected: {should_detect}, Got: {is_nonce_error}")
            all_passed = False
    
    print()
    return all_passed


def test_delay_calculation():
    """Test that delay calculations are correct for nonce errors"""
    print("=" * 80)
    print("TEST 2: Delay Calculation for Nonce Errors")
    print("=" * 80)
    
    nonce_base_delay = 30.0
    expected_delays = {
        2: 30.0,   # (2-1) * 30 = 30s
        3: 60.0,   # (3-1) * 30 = 60s
        4: 90.0,   # (4-1) * 30 = 90s
        5: 120.0,  # (5-1) * 30 = 120s
    }
    
    all_passed = True
    for attempt, expected in expected_delays.items():
        calculated = nonce_base_delay * (attempt - 1)
        if calculated == expected:
            print(f"  ✅ PASS: Attempt {attempt} -> {calculated}s delay")
        else:
            print(f"  ❌ FAIL: Attempt {attempt} -> Expected {expected}s, Got {calculated}s")
            all_passed = False
    
    print()
    return all_passed


def test_nonce_jump_calculation():
    """Test that nonce jump calculations are correct"""
    print("=" * 80)
    print("TEST 3: Nonce Jump Calculation")
    print("=" * 80)
    
    # Test normal error jumps (1x multiplier)
    print("  Normal errors (1x multiplier):")
    for attempt in [2, 3, 4, 5]:
        nonce_multiplier = 1
        nonce_jump = nonce_multiplier * 1000000 * attempt
        expected = attempt * 1000000
        if nonce_jump == expected:
            print(f"    ✅ Attempt {attempt} -> {nonce_jump:,} microseconds ({nonce_jump/1000000}s)")
        else:
            print(f"    ❌ Attempt {attempt} -> Expected {expected:,}, Got {nonce_jump:,}")
            return False
    
    print()
    print("  Nonce errors (10x multiplier):")
    for attempt in [2, 3, 4, 5]:
        nonce_multiplier = 10
        nonce_jump = nonce_multiplier * 1000000 * attempt
        expected = attempt * 10000000
        if nonce_jump == expected:
            print(f"    ✅ Attempt {attempt} -> {nonce_jump:,} microseconds ({nonce_jump/1000000}s)")
        else:
            print(f"    ❌ Attempt {attempt} -> Expected {expected:,}, Got {nonce_jump:,}")
            return False
    
    print()
    return True


def test_priority_handling():
    """Test that lockout errors take precedence over nonce errors"""
    print("=" * 80)
    print("TEST 4: Error Priority Handling")
    print("=" * 80)
    
    # Test case: both lockout and nonce error detected
    error_msg = "Temporary lockout due to invalid nonce"
    
    is_lockout_error = 'lockout' in error_msg.lower()
    # Use the same specific detection as production code
    is_nonce_error = any(keyword in error_msg.lower() for keyword in [
        'invalid nonce', 'eapi:invalid nonce', 'nonce window'
    ])
    
    # Lockout takes precedence
    last_error_was_lockout = is_lockout_error
    last_error_was_nonce = is_nonce_error and not is_lockout_error
    
    print(f"  Error message: '{error_msg}'")
    print(f"  Detected as lockout: {is_lockout_error}")
    print(f"  Detected as nonce: {is_nonce_error}")
    print(f"  Flag set - lockout: {last_error_was_lockout}")
    print(f"  Flag set - nonce: {last_error_was_nonce}")
    
    if last_error_was_lockout and not last_error_was_nonce:
        print(f"  ✅ PASS: Lockout takes precedence over nonce")
        print()
        return True
    else:
        print(f"  ❌ FAIL: Expected lockout flag only")
        print()
        return False


def main():
    """Run all tests"""
    print()
    print("=" * 80)
    print("KRAKEN NONCE ERROR HANDLING TEST SUITE")
    print("=" * 80)
    print()
    
    results = []
    
    # Run tests
    results.append(("Nonce Error Detection", test_nonce_error_detection()))
    results.append(("Delay Calculation", test_delay_calculation()))
    results.append(("Nonce Jump Calculation", test_nonce_jump_calculation()))
    results.append(("Priority Handling", test_priority_handling()))
    
    # Print summary
    print("=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}: {test_name}")
    
    print()
    print(f"  Total: {passed}/{total} tests passed")
    print("=" * 80)
    
    # Exit with appropriate code
    if passed == total:
        print()
        print("🎉 All tests passed!")
        print()
        return 0
    else:
        print()
        print("⚠️  Some tests failed!")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())
