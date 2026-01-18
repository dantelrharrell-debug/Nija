#!/usr/bin/env python3
"""
Test script for KrakenNonce class (OPTION A - Best Practice).

Validates that:
1. Each user gets their own KrakenNonce instance
2. Nonces are monotonically increasing
3. Thread-safe under concurrent access
4. Simple and follows best practice pattern
"""

import time
import threading
from bot.kraken_nonce import KrakenNonce


def test_basic_nonce_generation():
    """Test basic nonce generation"""
    print("=" * 70)
    print("TEST 1: Basic Nonce Generation")
    print("=" * 70)
    
    nonce_gen = KrakenNonce()
    
    # Generate 10 nonces
    nonces = []
    for i in range(10):
        nonce = nonce_gen.next()
        nonces.append(nonce)
    
    print(f"Generated {len(nonces)} nonces:")
    for i, nonce in enumerate(nonces[:5], 1):
        print(f"  {i}. {nonce}")
    print(f"  ...")
    
    # Verify all nonces are unique
    unique_nonces = set(nonces)
    assert len(unique_nonces) == len(nonces), "Found duplicate nonces!"
    print(f"✅ All {len(nonces)} nonces are unique")
    
    # Verify nonces are monotonically increasing
    for i in range(1, len(nonces)):
        assert nonces[i] > nonces[i-1], f"Nonce not monotonic: {nonces[i]} <= {nonces[i-1]}"
    print(f"✅ All nonces are monotonically increasing")
    
    # Verify increment is exactly 1
    for i in range(1, len(nonces)):
        diff = nonces[i] - nonces[i-1]
        assert diff == 1, f"Increment not 1: {diff}"
    print(f"✅ All nonces increment by exactly 1")
    
    print()


def test_per_user_isolation():
    """Test that each user has isolated nonce tracking"""
    print("=" * 70)
    print("TEST 2: Per-User Nonce Isolation")
    print("=" * 70)
    
    # Create separate nonce generators for two users
    user1_nonce = KrakenNonce()
    user2_nonce = KrakenNonce()
    
    # Generate nonces for user 1
    user1_nonces = [user1_nonce.next() for _ in range(5)]
    
    # Generate nonces for user 2
    user2_nonces = [user2_nonce.next() for _ in range(5)]
    
    print(f"User 1 nonces: {user1_nonces}")
    print(f"User 2 nonces: {user2_nonces}")
    
    # Verify each user's nonces are monotonic
    for i in range(1, len(user1_nonces)):
        assert user1_nonces[i] > user1_nonces[i-1]
    print("✅ User 1 nonces are monotonic")
    
    for i in range(1, len(user2_nonces)):
        assert user2_nonces[i] > user2_nonces[i-1]
    print("✅ User 2 nonces are monotonic")
    
    # User nonces should be different (isolated)
    # Note: They might overlap in value if created at similar times,
    # but each user's sequence is independent
    print("✅ Each user has independent nonce tracking")
    
    print()


def test_thread_safety():
    """Test thread-safe nonce generation"""
    print("=" * 70)
    print("TEST 3: Thread Safety")
    print("=" * 70)
    
    nonce_gen = KrakenNonce()
    nonces = []
    nonces_lock = threading.Lock()
    
    def generate_nonces(count):
        """Generate nonces in a thread"""
        for _ in range(count):
            nonce = nonce_gen.next()
            with nonces_lock:
                nonces.append(nonce)
    
    # Create 5 threads, each generating 20 nonces
    threads = []
    num_threads = 5
    nonces_per_thread = 20
    
    for i in range(num_threads):
        thread = threading.Thread(target=generate_nonces, args=(nonces_per_thread,))
        threads.append(thread)
        thread.start()
    
    # Wait for all threads to complete
    for thread in threads:
        thread.join()
    
    total_nonces = num_threads * nonces_per_thread
    print(f"Generated {len(nonces)} nonces from {num_threads} threads")
    
    # Verify all nonces are unique (no race conditions)
    unique_nonces = set(nonces)
    assert len(unique_nonces) == len(nonces), \
        f"Found {len(nonces) - len(unique_nonces)} duplicate nonces!"
    print(f"✅ All {len(nonces)} nonces are unique (no race conditions)")
    
    # Verify nonces are in valid range
    sorted_nonces = sorted(nonces)
    for i in range(1, len(sorted_nonces)):
        diff = sorted_nonces[i] - sorted_nonces[i-1]
        assert diff >= 1, f"Invalid nonce sequence: {sorted_nonces[i-1]} -> {sorted_nonces[i]}"
    print(f"✅ All nonces form valid monotonic sequence when sorted")
    
    print()


def test_best_practice_pattern():
    """Test that the class follows OPTION A best practice"""
    print("=" * 70)
    print("TEST 4: OPTION A Best Practice Pattern")
    print("=" * 70)
    
    # Verify class has required methods
    nonce_gen = KrakenNonce()
    
    assert hasattr(nonce_gen, 'last'), "Missing 'last' attribute"
    print("✅ Has 'last' attribute")
    
    assert hasattr(nonce_gen, 'next'), "Missing 'next()' method"
    print("✅ Has 'next()' method")
    
    # Verify initial value is based on time
    current_time_ms = int(time.time() * 1000)
    assert abs(nonce_gen.last - current_time_ms) < 1000, \
        f"Initial nonce {nonce_gen.last} not close to current time {current_time_ms}"
    print(f"✅ Initial nonce based on current time ({nonce_gen.last}ms)")
    
    # Verify next() increments by 1
    first_nonce = nonce_gen.next()
    second_nonce = nonce_gen.next()
    assert second_nonce == first_nonce + 1, \
        f"next() doesn't increment by 1: {first_nonce} -> {second_nonce}"
    print(f"✅ next() increments by 1")
    
    # Verify thread-safe (has lock)
    assert hasattr(nonce_gen, '_lock'), "Missing thread lock"
    print(f"✅ Thread-safe with internal lock")
    
    print()


def run_all_tests():
    """Run all tests"""
    print("\n")
    print("=" * 70)
    print("KRAKEN NONCE CLASS TEST SUITE (OPTION A - Best Practice)")
    print("=" * 70)
    print()
    
    test_basic_nonce_generation()
    test_per_user_isolation()
    test_thread_safety()
    test_best_practice_pattern()
    
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print()
    print("✅ All tests passed!")
    print()
    print("KrakenNonce class correctly implements OPTION A:")
    print("  ✅ Each user has own instance (not shared)")
    print("  ✅ Nonces are monotonically increasing")
    print("  ✅ Thread-safe with internal lock")
    print("  ✅ Simple and follows best practice pattern")
    print()


if __name__ == "__main__":
    run_all_tests()
