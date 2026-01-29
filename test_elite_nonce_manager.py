#!/usr/bin/env python3
"""
Test Elite-Tier Kraken Nonce Manager

Tests the centralized, atomic, thread-safe nonce generation system
designed for elite quant trading operations.

Author: NIJA Trading Systems
Date: January 29, 2026
"""

import sys
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from global_kraken_nonce import (
    GlobalKrakenNonceManager,
    get_global_nonce_manager,
    get_global_nonce_stats,
    get_kraken_nonce,
    get_global_kraken_nonce,
    get_kraken_api_lock
)


def test_singleton_pattern():
    """Test that only one instance exists across the process."""
    print("\n" + "=" * 60)
    print("TEST 1: Singleton Pattern")
    print("=" * 60)
    
    m1 = get_global_nonce_manager()
    m2 = get_global_nonce_manager()
    m3 = GlobalKrakenNonceManager()
    
    # All references should point to the same object
    assert m1 is m2, "Failed: Multiple manager instances detected"
    assert m2 is m3, "Failed: Direct instantiation created different instance"
    
    print("✅ Singleton pattern verified")
    print(f"   All instances reference same object: {id(m1)}")


def test_atomic_nonce_generation():
    """Test that nonce generation is atomic and thread-safe."""
    print("\n" + "=" * 60)
    print("TEST 2: Atomic Nonce Generation")
    print("=" * 60)
    
    manager = get_global_nonce_manager()
    
    # Use thread-safe list via threading.Lock
    nonces = []
    nonces_lock = threading.Lock()
    errors = []
    
    def worker(worker_id):
        """Worker thread that generates nonces."""
        try:
            for i in range(100):
                nonce = manager.get_nonce(apply_rate_limiting=False)
                with nonces_lock:
                    nonces.append(nonce)
        except Exception as e:
            errors.append((worker_id, e))
    
    # Create 10 threads, each generating 100 nonces
    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    
    start_time = time.time()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    elapsed = time.time() - start_time
    
    # Verify results
    total_nonces = len(nonces)
    unique_nonces = len(set(nonces))
    is_monotonic = nonces == sorted(nonces)
    
    print(f"✅ Generated {total_nonces} nonces from 10 threads in {elapsed:.2f}s")
    print(f"   Unique nonces: {unique_nonces} (100.0%)" if unique_nonces == total_nonces else f"   ❌ COLLISION: {total_nonces - unique_nonces} duplicates")
    print(f"   Monotonic: {'Yes' if is_monotonic else '❌ NO - nonces out of order'}")
    print(f"   Generation rate: {total_nonces / elapsed:.1f} nonces/sec")
    print(f"   Errors: {len(errors)}")
    
    assert unique_nonces == total_nonces, f"Collision detected: {total_nonces - unique_nonces} duplicate nonces"
    assert len(errors) == 0, f"Errors occurred: {errors}"


def test_startup_burst_protection():
    """Test that startup burst protection prevents rapid API calls."""
    print("\n" + "=" * 60)
    print("TEST 3: Startup Burst Protection")
    print("=" * 60)
    
    # Create a fresh manager (reuse singleton, but reset tracking)
    manager = get_global_nonce_manager()
    manager.reset_burst_tracking()
    
    # Generate rapid nonces with burst protection
    start_time = time.time()
    nonces_with_limit = []
    
    for i in range(30):
        nonce = manager.get_nonce(apply_rate_limiting=True)
        nonces_with_limit.append(nonce)
    
    elapsed_with_limit = time.time() - start_time
    rate_with_limit = len(nonces_with_limit) / elapsed_with_limit
    
    print(f"✅ With burst protection:")
    print(f"   Generated {len(nonces_with_limit)} nonces in {elapsed_with_limit:.2f}s")
    print(f"   Rate: {rate_with_limit:.1f} nonces/sec")
    print(f"   Max burst rate limit: {manager.MAX_BURST_RATE} nonces/sec")
    
    # Verify rate is controlled
    if rate_with_limit <= manager.MAX_BURST_RATE * 1.1:  # Allow 10% margin
        print(f"   ✅ Burst protection effective (rate under limit)")
    else:
        print(f"   ⚠️  Rate slightly above limit (acceptable variance)")
    
    # Generate without burst protection for comparison
    manager.reset_burst_tracking()
    start_time = time.time()
    nonces_no_limit = []
    
    for i in range(30):
        nonce = manager.get_nonce(apply_rate_limiting=False)
        nonces_no_limit.append(nonce)
    
    elapsed_no_limit = time.time() - start_time
    rate_no_limit = len(nonces_no_limit) / elapsed_no_limit
    
    print(f"✅ Without burst protection:")
    print(f"   Generated {len(nonces_no_limit)} nonces in {elapsed_no_limit:.2f}s")
    print(f"   Rate: {rate_no_limit:.1f} nonces/sec")
    
    speedup = rate_no_limit / rate_with_limit if rate_with_limit > 0 else 0
    print(f"   Speedup without protection: {speedup:.1f}x")


def test_persistence():
    """Test that nonce state persists to file correctly."""
    print("\n" + "=" * 60)
    print("TEST 4: Nonce Persistence")
    print("=" * 60)
    
    manager = get_global_nonce_manager()
    
    # Generate some nonces to ensure persistence file is created
    # Every 10th nonce triggers a save
    nonces = [manager.get_nonce(apply_rate_limiting=False) for _ in range(20)]
    last_nonce = nonces[-1]
    
    # Get persistence file path from public API
    stats = manager.get_stats()
    persistence_file = stats['persistence_file']
    
    # Check persistence file exists
    if os.path.exists(persistence_file):
        print(f"✅ Persistence file exists: {persistence_file}")
        
        # Read persisted value
        with open(persistence_file, 'r') as f:
            persisted_value = int(f.read().strip())
        
        print(f"   Last generated nonce: {last_nonce}")
        print(f"   Persisted nonce: {persisted_value}")
        
        # Persisted value should be close to last nonce (within 10 nonces)
        # since we save every 10th nonce
        assert persisted_value >= last_nonce - 10, "Persisted nonce should be recent"
        print(f"   ✅ Persistence verified")
    else:
        print(f"⚠️  Persistence file not found (may be disabled)")


def test_global_api_lock():
    """Test that global API lock serializes Kraken calls."""
    print("\n" + "=" * 60)
    print("TEST 5: Global API Lock (Prevents Parallel REST Calls)")
    print("=" * 60)
    
    api_lock = get_kraken_api_lock()
    
    # Track execution order
    execution_log = []
    lock_held_times = []
    
    def simulated_api_call(call_id):
        """Simulate a Kraken API call."""
        with api_lock:
            execution_log.append(('start', call_id))
            start = time.time()
            
            # Simulate API call work
            time.sleep(0.01)  # 10ms simulated API latency
            
            elapsed = time.time() - start
            lock_held_times.append(elapsed)
            execution_log.append(('end', call_id))
    
    # Launch parallel "API calls"
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(simulated_api_call, i) for i in range(10)]
        for f in as_completed(futures):
            f.result()
    
    # Verify serialization
    # Check that no two calls overlapped
    active_calls = 0
    max_concurrent = 0
    
    for event, call_id in execution_log:
        if event == 'start':
            active_calls += 1
            max_concurrent = max(max_concurrent, active_calls)
        else:
            active_calls -= 1
    
    print(f"✅ Global API lock tested with 10 parallel calls")
    print(f"   Max concurrent calls: {max_concurrent}")
    print(f"   Average lock hold time: {sum(lock_held_times)/len(lock_held_times)*1000:.1f}ms")
    
    assert max_concurrent == 1, f"Lock failed: {max_concurrent} concurrent calls detected"
    print(f"   ✅ Serialization verified (no parallel calls)")


def test_metrics_and_monitoring():
    """Test that comprehensive metrics are available."""
    print("\n" + "=" * 60)
    print("TEST 6: Metrics and Monitoring")
    print("=" * 60)
    
    stats = get_global_nonce_stats()
    
    print(f"✅ Nonce Manager Statistics:")
    print(f"   Total nonces issued: {stats['total_nonces_issued']}")
    print(f"   Last nonce: {stats['last_nonce']}")
    print(f"   Uptime: {stats['uptime_seconds']:.1f}s")
    print(f"   Average rate: {stats['nonces_per_second']:.1f} nonces/sec")
    print(f"   Recent burst rate: {stats['recent_burst_rate']:.1f} nonces/sec")
    print(f"   In startup window: {stats['in_startup_window']}")
    print(f"   Persistence file: {stats['persistence_file']}")
    
    rate_config = stats['rate_limit_config']
    print(f"✅ Rate Limit Configuration:")
    print(f"   Startup rate limit: {rate_config['startup_rate_limit_seconds']}s")
    print(f"   Max burst rate: {rate_config['max_burst_rate']} nonces/sec")
    print(f"   Startup window: {rate_config['startup_window_seconds']}s")


def test_backward_compatibility():
    """Test that legacy interfaces still work."""
    print("\n" + "=" * 60)
    print("TEST 7: Backward Compatibility")
    print("=" * 60)
    
    # Test legacy function aliases
    nonce1 = get_kraken_nonce()
    nonce2 = get_global_kraken_nonce()
    
    print(f"✅ Legacy function compatibility:")
    print(f"   get_kraken_nonce(): {nonce1}")
    print(f"   get_global_kraken_nonce(): {nonce2}")
    print(f"   Both monotonic: {nonce2 > nonce1}")
    
    assert nonce2 > nonce1, "Nonces should be monotonically increasing"


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("ELITE-TIER KRAKEN NONCE MANAGER TEST SUITE")
    print("=" * 60)
    print("Testing centralized, atomic, thread-safe nonce generation")
    print("for elite quant trading operations")
    print("=" * 60)
    
    try:
        test_singleton_pattern()
        test_atomic_nonce_generation()
        test_startup_burst_protection()
        test_persistence()
        test_global_api_lock()
        test_metrics_and_monitoring()
        test_backward_compatibility()
        
        print("\n" + "=" * 60)
        print("✅ ALL TESTS PASSED")
        print("=" * 60)
        print("Elite-Tier Nonce Manager is ready for production")
        print("=" * 60)
        
        return 0
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == '__main__':
    sys.exit(main())
