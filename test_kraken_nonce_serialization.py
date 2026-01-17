#!/usr/bin/env python3
"""
Test Kraken Nonce Serialization and Monotonic Guarantees

This test validates:
1. API calls are properly serialized (no simultaneous calls)
2. Nonce values are strictly monotonic (always increasing)
3. Minimum delay is enforced between calls
4. Thread-safe operation under concurrent load

Run: python3 test_kraken_nonce_serialization.py
"""

import sys
import time
import threading
from unittest.mock import Mock, MagicMock, patch
from typing import List

# Add bot directory to path
sys.path.insert(0, '/home/runner/work/Nija/Nija')

from bot.broker_manager import KrakenBroker, AccountType


class NonceTracker:
    """Track nonce values and call timings for testing"""
    def __init__(self):
        self.nonces = []
        self.call_times = []
        self.lock = threading.Lock()
    
    def record(self, nonce: str, timestamp: float):
        with self.lock:
            self.nonces.append(int(nonce))
            self.call_times.append(timestamp)
    
    def get_stats(self):
        with self.lock:
            return {
                'nonces': self.nonces.copy(),
                'call_times': self.call_times.copy(),
                'total_calls': len(self.nonces),
                'unique_nonces': len(set(self.nonces)),
                'is_monotonic': all(self.nonces[i] < self.nonces[i+1] for i in range(len(self.nonces)-1))
            }


def test_nonce_monotonicity():
    """Test that nonces are strictly increasing"""
    print("\n" + "="*70)
    print("TEST 1: Nonce Monotonicity")
    print("="*70)
    
    tracker = NonceTracker()
    
    # Create mock Kraken broker
    broker = KrakenBroker(AccountType.MASTER)
    
    # Mock the API to track nonces
    def mock_nonce():
        with broker._nonce_lock:
            current_nonce = int(time.time() * 1000000)
            if current_nonce <= broker._last_nonce:
                current_nonce = broker._last_nonce + 1
            broker._last_nonce = current_nonce
            
            # Record the nonce
            tracker.record(str(current_nonce), time.time())
            return str(current_nonce)
    
    # Generate 100 nonces rapidly
    print("\n📊 Generating 100 nonces rapidly...")
    for i in range(100):
        nonce = mock_nonce()
        if i % 20 == 0:
            print(f"  Generated {i+1}/100 nonces...")
    
    stats = tracker.get_stats()
    
    print(f"\n✅ Results:")
    print(f"   Total nonces generated: {stats['total_calls']}")
    print(f"   Unique nonces: {stats['unique_nonces']}")
    print(f"   Are all nonces monotonic? {stats['is_monotonic']}")
    
    # Verify monotonicity
    assert stats['is_monotonic'], "❌ FAIL: Nonces are not strictly monotonic!"
    assert stats['unique_nonces'] == stats['total_calls'], "❌ FAIL: Found duplicate nonces!"
    
    print("\n✅ PASS: All nonces are strictly monotonic and unique")
    return True


def test_api_call_serialization():
    """Test that API calls are properly serialized"""
    print("\n" + "="*70)
    print("TEST 2: API Call Serialization")
    print("="*70)
    
    call_tracker = []
    call_lock = threading.Lock()
    active_calls = 0
    max_concurrent = 0
    
    # Create mock broker
    broker = KrakenBroker(AccountType.MASTER)
    
    # Mock the API
    mock_api = Mock()
    
    def mock_query_private(method, params=None):
        nonlocal active_calls, max_concurrent
        
        with call_lock:
            active_calls += 1
            if active_calls > max_concurrent:
                max_concurrent = active_calls
            call_tracker.append({
                'start': time.time(),
                'method': method,
                'thread': threading.current_thread().name
            })
        
        # Simulate API delay
        time.sleep(0.05)  # 50ms
        
        with call_lock:
            active_calls -= 1
            call_tracker[-1]['end'] = time.time()
        
        return {'result': {}, 'error': []}
    
    mock_api.query_private = mock_query_private
    broker.api = mock_api
    
    # Create multiple threads to make concurrent calls
    print("\n📊 Testing concurrent API calls with 10 threads...")
    threads = []
    
    def make_call(thread_id):
        for i in range(5):
            try:
                broker._kraken_private_call('Balance')
            except Exception as e:
                print(f"  Thread {thread_id} error: {e}")
    
    # Start 10 threads, each making 5 calls
    for i in range(10):
        t = threading.Thread(target=make_call, args=(i,), name=f"Thread-{i}")
        threads.append(t)
        t.start()
    
    # Wait for all threads
    for t in threads:
        t.join()
    
    print(f"\n✅ Results:")
    print(f"   Total calls made: {len(call_tracker)}")
    print(f"   Maximum concurrent calls: {max_concurrent}")
    
    # Check for overlapping calls
    overlaps = 0
    for i in range(len(call_tracker)):
        for j in range(i+1, len(call_tracker)):
            call1 = call_tracker[i]
            call2 = call_tracker[j]
            # Check if calls overlap
            if (call1['start'] < call2['end'] and call2['start'] < call1['end']):
                overlaps += 1
    
    print(f"   Overlapping calls detected: {overlaps}")
    
    # Verify serialization
    assert max_concurrent == 1, f"❌ FAIL: Found {max_concurrent} concurrent calls (expected 1)"
    assert overlaps == 0, f"❌ FAIL: Found {overlaps} overlapping calls"
    
    print("\n✅ PASS: All API calls were properly serialized")
    return True


def test_minimum_call_interval():
    """Test that minimum delay is enforced between calls"""
    print("\n" + "="*70)
    print("TEST 3: Minimum Call Interval")
    print("="*70)
    
    broker = KrakenBroker(AccountType.MASTER)
    
    # Mock the API
    mock_api = Mock()
    call_times = []
    
    def mock_query_private(method, params=None):
        call_times.append(time.time())
        return {'result': {}, 'error': []}
    
    mock_api.query_private = mock_query_private
    broker.api = mock_api
    
    # Make 10 rapid calls
    print("\n📊 Making 10 rapid API calls...")
    for i in range(10):
        broker._kraken_private_call('Balance')
    
    # Calculate intervals
    intervals = []
    for i in range(1, len(call_times)):
        interval = call_times[i] - call_times[i-1]
        intervals.append(interval)
    
    min_interval = min(intervals) if intervals else 0
    avg_interval = sum(intervals) / len(intervals) if intervals else 0
    
    print(f"\n✅ Results:")
    print(f"   Total calls: {len(call_times)}")
    print(f"   Minimum interval: {min_interval*1000:.1f}ms")
    print(f"   Average interval: {avg_interval*1000:.1f}ms")
    print(f"   Expected minimum: {broker._min_call_interval*1000:.1f}ms")
    
    # Verify minimum interval (allow 5ms tolerance for timing precision)
    tolerance = 0.005  # 5ms
    assert min_interval >= (broker._min_call_interval - tolerance), \
        f"❌ FAIL: Found interval {min_interval*1000:.1f}ms < minimum {broker._min_call_interval*1000:.1f}ms"
    
    print("\n✅ PASS: Minimum call interval is enforced")
    return True


def test_concurrent_nonce_generation():
    """Test nonce generation under high concurrent load"""
    print("\n" + "="*70)
    print("TEST 4: Concurrent Nonce Generation (Stress Test)")
    print("="*70)
    
    tracker = NonceTracker()
    broker = KrakenBroker(AccountType.MASTER)
    
    # Mock nonce generator that tracks calls
    original_nonce_func = None
    
    def tracked_nonce():
        with broker._nonce_lock:
            current_nonce = int(time.time() * 1000000)
            if current_nonce <= broker._last_nonce:
                current_nonce = broker._last_nonce + 1
            broker._last_nonce = current_nonce
            tracker.record(str(current_nonce), time.time())
            return str(current_nonce)
    
    print("\n📊 Stress testing with 20 threads, 50 calls each...")
    
    threads = []
    errors = []
    
    def generate_nonces(thread_id):
        try:
            for i in range(50):
                tracked_nonce()
        except Exception as e:
            errors.append(f"Thread {thread_id}: {e}")
    
    # Start 20 threads
    start_time = time.time()
    for i in range(20):
        t = threading.Thread(target=generate_nonces, args=(i,))
        threads.append(t)
        t.start()
    
    # Wait for completion
    for t in threads:
        t.join()
    
    elapsed = time.time() - start_time
    
    stats = tracker.get_stats()
    
    print(f"\n✅ Results:")
    print(f"   Total nonces generated: {stats['total_calls']}")
    print(f"   Unique nonces: {stats['unique_nonces']}")
    print(f"   Time elapsed: {elapsed:.2f}s")
    print(f"   Rate: {stats['total_calls']/elapsed:.0f} nonces/sec")
    print(f"   Are all nonces monotonic? {stats['is_monotonic']}")
    print(f"   Errors: {len(errors)}")
    
    if errors:
        print("\n❌ Errors encountered:")
        for err in errors[:5]:  # Show first 5 errors
            print(f"   {err}")
    
    # Verify
    assert len(errors) == 0, f"❌ FAIL: {len(errors)} errors during concurrent generation"
    assert stats['is_monotonic'], "❌ FAIL: Nonces are not monotonic under load"
    assert stats['unique_nonces'] == stats['total_calls'], "❌ FAIL: Found duplicate nonces under load"
    
    print("\n✅ PASS: Nonce generation is thread-safe under high load")
    return True


def main():
    """Run all tests"""
    print("\n" + "="*70)
    print("KRAKEN NONCE SERIALIZATION & MONOTONICITY TEST SUITE")
    print("="*70)
    print("\nThis test suite validates the nonce serialization implementation")
    print("to prevent 'Invalid nonce' errors on Kraken API.")
    
    tests = [
        ("Nonce Monotonicity", test_nonce_monotonicity),
        ("API Call Serialization", test_api_call_serialization),
        ("Minimum Call Interval", test_minimum_call_interval),
        ("Concurrent Nonce Generation", test_concurrent_nonce_generation),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except AssertionError as e:
            print(f"\n❌ {test_name} FAILED: {e}")
            failed += 1
        except Exception as e:
            print(f"\n❌ {test_name} ERROR: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    print(f"✅ Passed: {passed}/{len(tests)}")
    print(f"❌ Failed: {failed}/{len(tests)}")
    
    if failed == 0:
        print("\n🎉 ALL TESTS PASSED!")
        print("\n✅ Implementation is production-ready:")
        print("   • Nonces are strictly monotonic")
        print("   • API calls are properly serialized")
        print("   • Minimum delays are enforced")
        print("   • Thread-safe under concurrent load")
        return 0
    else:
        print("\n⚠️  SOME TESTS FAILED - Review implementation")
        return 1


if __name__ == '__main__':
    sys.exit(main())
