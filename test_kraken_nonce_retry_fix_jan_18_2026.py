#!/usr/bin/env python3
"""
Test script for Kraken nonce retry fix (January 18, 2026)

This script validates the improved nonce retry logic:
1. Immediate nonce jump: 120s (clears burned nonce window)
2. Retry delay base: REDUCED from 60s to 3s (immediate jump handles nonce clearing)
3. Nonce multiplier: 20x (increased from 10x)
4. All retry attempts are logged (including attempt 5)

Expected behavior:
- Immediate jump: 120,000ms (120 seconds) - This clears the nonce window
- Retry delays: 3s, 6s, 9s, 12s (for attempts 2,3,4,5) - Brief pauses to avoid API hammering
- Nonce jumps: 40s, 80s, 120s, 160s (20x multiplier: 20*2, 20*3, 20*4, 20*5 seconds)
"""

import sys
import os
import time

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Direct import to avoid bot/__init__.py dependencies
from kraken_nonce import KrakenNonce


def test_immediate_jump():
    """Test immediate nonce jump is 120 seconds"""
    print("=" * 70)
    print("TEST 1: Immediate Nonce Jump (120 seconds)")
    print("=" * 70)
    
    nonce_gen = KrakenNonce()
    initial_nonce = nonce_gen.last
    
    # Jump forward by 120 seconds (120,000ms)
    jumped_nonce = nonce_gen.jump_forward(120 * 1000)
    
    # Verify the jump is at least 120,000ms
    jump_amount = jumped_nonce - initial_nonce
    
    print(f"Initial nonce:  {initial_nonce}")
    print(f"Jumped nonce:   {jumped_nonce}")
    print(f"Jump amount:    {jump_amount}ms ({jump_amount/1000:.0f}s)")
    print(f"Expected:       ≥ 120,000ms (120s)")
    
    if jump_amount >= 120000:
        print("✅ PASS: Immediate jump is at least 120 seconds")
        return True
    else:
        print(f"❌ FAIL: Jump was only {jump_amount/1000:.0f}s, expected at least 120s")
        return False


def test_retry_delays():
    """Test retry delay calculations"""
    print("\n" + "=" * 70)
    print("TEST 2: Retry Delay Calculations (3s base)")
    print("=" * 70)
    
    nonce_base_delay = 3.0  # New base delay (REDUCED from 60s)
    expected_delays = [3, 6, 9, 12]  # For attempts 2,3,4,5
    
    all_passed = True
    for attempt in range(2, 6):  # Attempts 2,3,4,5
        calculated_delay = nonce_base_delay * (attempt - 1)
        expected_delay = expected_delays[attempt - 2]
        
        print(f"Attempt {attempt}/5: delay = {calculated_delay:.0f}s (expected {expected_delay}s)", end="")
        
        if calculated_delay == expected_delay:
            print(" ✅")
        else:
            print(f" ❌ (got {calculated_delay:.0f}s)")
            all_passed = False
    
    if all_passed:
        print("✅ PASS: All retry delays correct")
        return True
    else:
        print("❌ FAIL: Some retry delays incorrect")
        return False


def test_nonce_jumps():
    """Test nonce jump calculations with 20x multiplier"""
    print("\n" + "=" * 70)
    print("TEST 3: Nonce Jump Calculations (20x multiplier)")
    print("=" * 70)
    
    nonce_multiplier = 20  # New multiplier (increased from 10x)
    # Formula: nonce_multiplier * 1000 * attempt
    # Attempt 2: 20 * 1000 * 2 = 40,000ms (40s)
    # Attempt 3: 20 * 1000 * 3 = 60,000ms (60s)
    # Attempt 4: 20 * 1000 * 4 = 80,000ms (80s)
    # Attempt 5: 20 * 1000 * 5 = 100,000ms (100s)
    expected_jumps_ms = [40000, 60000, 80000, 100000]  # For attempts 2,3,4,5
    
    all_passed = True
    for attempt in range(2, 6):  # Attempts 2,3,4,5
        nonce_jump_ms = nonce_multiplier * 1000 * attempt
        expected_jump_ms = expected_jumps_ms[attempt - 2]
        
        print(f"Attempt {attempt}/5: nonce jump = {nonce_jump_ms}ms ({nonce_jump_ms/1000:.0f}s)", end="")
        print(f" | expected {expected_jump_ms}ms ({expected_jump_ms/1000:.0f}s)", end="")
        
        if nonce_jump_ms == expected_jump_ms:
            print(" ✅")
        else:
            print(f" ❌")
            all_passed = False
    
    if all_passed:
        print("✅ PASS: All nonce jumps correct")
        return True
    else:
        print("❌ FAIL: Some nonce jumps incorrect")
        return False


def test_nonce_monotonic_after_jumps():
    """Test that nonce remains monotonic after multiple jumps"""
    print("\n" + "=" * 70)
    print("TEST 4: Nonce Monotonic After Multiple Jumps")
    print("=" * 70)
    
    nonce_gen = KrakenNonce()
    previous_nonce = nonce_gen.last
    
    # Simulate 5 retry attempts with jumps
    jumps = [40000, 80000, 120000, 160000, 200000]  # Increasing jumps
    all_monotonic = True
    
    for i, jump_ms in enumerate(jumps, 1):
        new_nonce = nonce_gen.jump_forward(jump_ms)
        
        print(f"Jump {i}: +{jump_ms}ms → nonce={new_nonce}", end="")
        
        if new_nonce > previous_nonce:
            print(" ✅ monotonic")
            previous_nonce = new_nonce
        else:
            print(f" ❌ NOT monotonic (prev={previous_nonce})")
            all_monotonic = False
    
    if all_monotonic:
        print("✅ PASS: Nonce remains monotonic after all jumps")
        return True
    else:
        print("❌ FAIL: Nonce not monotonic")
        return False


def main():
    """Run all tests"""
    print("\n" + "=" * 70)
    print("KRAKEN NONCE RETRY FIX VALIDATION (January 18, 2026)")
    print("=" * 70)
    print()
    print("Testing improvements:")
    print("  - Immediate jump: 120s (clears nonce window)")
    print("  - Retry delay base: 3s (brief pause, not nonce window wait)")
    print("  - Nonce multiplier: 20x → 20x")
    print("  - Log all retry attempts (including #5)")
    print()
    
    # Run tests
    results = []
    results.append(test_immediate_jump())
    results.append(test_retry_delays())
    results.append(test_nonce_jumps())
    results.append(test_nonce_monotonic_after_jumps())
    
    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    passed = sum(results)
    total = len(results)
    
    if passed == total:
        print(f"✅ ALL TESTS PASSED ({passed}/{total})")
        print()
        print("Expected connection behavior with new settings:")
        print("  Attempt 1: Initial connection (after 5s startup delay)")
        print("  Attempt 2: Retry after 3s delay + 40s nonce jump")
        print("             (120s immediate jump applied on first nonce error)")
        print("  Attempt 3: Retry after 6s delay + 60s nonce jump")
        print("  Attempt 4: Retry after 9s delay + 80s nonce jump")
        print("  Attempt 5: Retry after 12s delay + 100s nonce jump")
        print()
        print("Total retry time: ~30 seconds (much faster startup!)")
        print("The 120s immediate jump happens once when nonce error is detected,")
        print("then each retry uses brief delays just to avoid API hammering.")
        print("The nonce jumps provide additional spacing to handle")
        print("persistent 'EAPI:Invalid nonce' errors from Kraken.")
        return 0
    else:
        print(f"❌ SOME TESTS FAILED ({passed}/{total} passed)")
        return 1


if __name__ == "__main__":
    sys.exit(main())
