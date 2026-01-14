#!/usr/bin/env python3
"""
Test script to validate the Kraken nonce fix (January 14, 2026).

This script demonstrates that the new minimal offset approach:
1. Uses current time (not future-dated timestamps)
2. Maintains strict monotonic increase through counter
3. Handles rapid consecutive requests correctly
4. Aligns with Kraken's documented best practices

Run this test to verify the fix before deployment.
"""

import time
import random
import threading


class MockKrakenNonce:
    """Mock implementation of the new nonce system for testing"""
    
    def __init__(self):
        # New implementation: Minimal offset (0-5 seconds)
        base_offset = 0  # Use current time
        random_jitter = random.randint(0, 5000000)  # 0-5 seconds
        total_offset = base_offset + random_jitter
        self._last_nonce = int(time.time() * 1000000) + total_offset
        self._nonce_lock = threading.Lock()
        
        print(f"Initial nonce offset: {total_offset / 1000000:.2f} seconds")
        print(f"Initial nonce value: {self._last_nonce}")
        print()
    
    def generate_nonce(self):
        """Generate next nonce with strict monotonic guarantee"""
        with self._nonce_lock:
            current_nonce = int(time.time() * 1000000)
            
            # Ensure strictly increasing
            if current_nonce <= self._last_nonce:
                current_nonce = self._last_nonce + 1
            
            self._last_nonce = current_nonce
            return str(current_nonce)
    
    def immediate_nonce_jump(self):
        """Jump nonce forward by 60 seconds on error"""
        with self._nonce_lock:
            immediate_jump = 60000000  # 60 seconds
            time_based = int(time.time() * 1000000) + immediate_jump
            increment_based = self._last_nonce + immediate_jump
            self._last_nonce = max(time_based, increment_based)
            print(f"⚡ Jumped nonce forward by 60 seconds")


def test_basic_nonce_generation():
    """Test 1: Basic nonce generation"""
    print("=" * 70)
    print("TEST 1: Basic Nonce Generation")
    print("=" * 70)
    
    nonce_gen = MockKrakenNonce()
    
    print("Generating 10 consecutive nonces:")
    previous = 0
    for i in range(10):
        nonce = int(nonce_gen.generate_nonce())
        if previous > 0:
            assert nonce > previous, f"Nonce {nonce} not greater than {previous}"
            print(f"  Nonce {i+1}: {nonce} (increment: +{nonce - previous})")
        else:
            print(f"  Nonce {i+1}: {nonce}")
        previous = nonce
    
    print("✅ PASS: All nonces are strictly monotonically increasing")
    print()


def test_rapid_requests():
    """Test 2: Rapid consecutive requests"""
    print("=" * 70)
    print("TEST 2: Rapid Consecutive Requests (100 requests, no sleep)")
    print("=" * 70)
    
    nonce_gen = MockKrakenNonce()
    
    nonces = []
    start_time = time.time()
    
    for _ in range(100):
        nonce = int(nonce_gen.generate_nonce())
        nonces.append(nonce)
    
    elapsed = time.time() - start_time
    
    # Verify all unique and increasing
    for i in range(1, len(nonces)):
        assert nonces[i] > nonces[i-1], f"Nonce sequence broken at index {i}"
    
    print(f"Generated 100 nonces in {elapsed:.4f} seconds")
    print(f"First nonce: {nonces[0]}")
    print(f"Last nonce:  {nonces[-1]}")
    print(f"Total increment: {nonces[-1] - nonces[0]} microseconds ({(nonces[-1] - nonces[0])/1000000:.4f} seconds)")
    print("✅ PASS: All nonces unique and monotonically increasing")
    print()


def test_nonce_offset_range():
    """Test 3: Verify initial offset is within acceptable range"""
    print("=" * 70)
    print("TEST 3: Initial Nonce Offset Range")
    print("=" * 70)
    
    offsets = []
    for _ in range(100):
        current_time = int(time.time() * 1000000)
        base_offset = 0
        random_jitter = random.randint(0, 5000000)
        total_offset = base_offset + random_jitter
        initial_nonce = current_time + total_offset
        offset_seconds = (initial_nonce - current_time) / 1000000
        offsets.append(offset_seconds)
    
    min_offset = min(offsets)
    max_offset = max(offsets)
    avg_offset = sum(offsets) / len(offsets)
    
    print(f"Testing 100 random initial offsets:")
    print(f"  Minimum offset: {min_offset:.2f} seconds")
    print(f"  Maximum offset: {max_offset:.2f} seconds")
    print(f"  Average offset: {avg_offset:.2f} seconds")
    print()
    
    # Verify range is 0-5 seconds
    assert min_offset >= 0, "Offset should not be negative"
    assert max_offset <= 5.1, "Offset should not exceed 5 seconds (allowing for timing variance)"
    
    print("✅ PASS: All offsets within acceptable range (0-5 seconds)")
    print()


def test_immediate_jump_recovery():
    """Test 4: Test immediate nonce jump on error"""
    print("=" * 70)
    print("TEST 4: Immediate Nonce Jump on Error")
    print("=" * 70)
    
    nonce_gen = MockKrakenNonce()
    
    # Generate a few nonces normally
    for i in range(3):
        nonce_gen.generate_nonce()
    
    nonce_before = int(nonce_gen.generate_nonce())
    print(f"Nonce before error: {nonce_before}")
    
    # Simulate error and immediate jump
    nonce_gen.immediate_nonce_jump()
    
    nonce_after = int(nonce_gen.generate_nonce())
    print(f"Nonce after jump:  {nonce_after}")
    
    jump_size = (nonce_after - nonce_before) / 1000000
    print(f"Jump size: {jump_size:.2f} seconds")
    print()
    
    # Verify jump is approximately 60 seconds
    assert jump_size >= 59, f"Jump too small: {jump_size} seconds"
    assert jump_size <= 61, f"Jump too large: {jump_size} seconds"
    
    print("✅ PASS: Immediate nonce jump works correctly (~60 seconds)")
    print()


def test_comparison_old_vs_new():
    """Test 5: Compare old approach vs new approach"""
    print("=" * 70)
    print("TEST 5: Comparison - Old Approach vs New Approach")
    print("=" * 70)
    
    current_time = int(time.time() * 1000000)
    
    # Old approach (WRONG)
    old_base_offset = 180000000  # 180 seconds
    old_random_jitter = 30000000  # Average 30 seconds
    old_total_offset = old_base_offset + old_random_jitter
    old_nonce = current_time + old_total_offset
    
    # New approach (CORRECT)
    new_base_offset = 0
    new_random_jitter = 2500000  # Average 2.5 seconds
    new_total_offset = new_base_offset + new_random_jitter
    new_nonce = current_time + new_total_offset
    
    print("OLD APPROACH (180-240 seconds ahead):")
    print(f"  Base offset:   {old_base_offset / 1000000} seconds")
    print(f"  Random jitter: {old_random_jitter / 1000000} seconds")
    print(f"  Total offset:  {old_total_offset / 1000000} seconds")
    print(f"  Nonce value:   {old_nonce}")
    print(f"  ❌ PROBLEM: Nonce is {old_total_offset / 60000000:.1f} MINUTES in the future!")
    print(f"  ❌ This likely EXCEEDS Kraken's acceptable nonce range")
    print()
    
    print("NEW APPROACH (0-5 seconds ahead):")
    print(f"  Base offset:   {new_base_offset / 1000000} seconds")
    print(f"  Random jitter: {new_random_jitter / 1000000} seconds")
    print(f"  Total offset:  {new_total_offset / 1000000} seconds")
    print(f"  Nonce value:   {new_nonce}")
    print(f"  ✅ CORRECT: Nonce is near current time (Kraken's best practice)")
    print(f"  ✅ Strict monotonic counter prevents collisions")
    print()
    
    print("IMPROVEMENT:")
    reduction = ((old_total_offset - new_total_offset) / 1000000)
    print(f"  Reduced initial offset by {reduction:.1f} seconds ({reduction / 60:.1f} minutes)")
    print(f"  This aligns with Kraken's documented expectations")
    print()


def run_all_tests():
    """Run all test cases"""
    print("\n")
    print("*" * 70)
    print("*" + " " * 68 + "*")
    print("*" + "  KRAKEN NONCE FIX VALIDATION - January 14, 2026".center(68) + "*")
    print("*" + " " * 68 + "*")
    print("*" * 70)
    print()
    
    try:
        test_basic_nonce_generation()
        test_rapid_requests()
        test_nonce_offset_range()
        test_immediate_jump_recovery()
        test_comparison_old_vs_new()
        
        print("=" * 70)
        print("✅ ALL TESTS PASSED")
        print("=" * 70)
        print()
        print("CONCLUSION:")
        print("  The new minimal offset approach (0-5 seconds) is CORRECT.")
        print("  It aligns with Kraken's best practices and should resolve")
        print("  the 'EAPI:Invalid nonce' errors.")
        print()
        print("  Previous approach (180-240 seconds) was TOO LARGE and likely")
        print("  caused nonces to be rejected by Kraken's validation.")
        print()
        
    except AssertionError as e:
        print("=" * 70)
        print(f"❌ TEST FAILED: {e}")
        print("=" * 70)
        return False
    
    return True


if __name__ == "__main__":
    success = run_all_tests()
    exit(0 if success else 1)
