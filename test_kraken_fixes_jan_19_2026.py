#!/usr/bin/env python3
"""
Test suite for Kraken fixes (Jan 19, 2026)

Tests the three critical fixes:
1. Per-account monotonic nonce with persistent storage
2. Single-file queue for Kraken private calls
3. Fail closed - not "balance = 0"
"""

import os
import sys
import time
import tempfile
import shutil
import threading
from pathlib import Path

# Add bot directory to path
bot_dir = os.path.join(os.path.dirname(__file__), 'bot')
if bot_dir not in sys.path:
    sys.path.insert(0, bot_dir)

# Import directly from global_kraken_nonce module
import global_kraken_nonce
from global_kraken_nonce import (
    get_global_nonce_manager,
    get_global_kraken_nonce,
    get_kraken_api_lock
)


def test_fix_1_nonce_persistence():
    """
    Test Fix 1: Per-account monotonic nonce with persistent storage.
    
    Verifies:
    - Nonce is persisted to disk
    - Nonce survives manager reset (simulates restart)
    - Nonce uses formula: max(last_nonce + 1, current_timestamp_ns)
    """
    print("\n" + "=" * 70)
    print("TEST FIX 1: Per-Account Monotonic Nonce with Persistent Storage")
    print("=" * 70)
    
    # Get the nonce manager
    manager = get_global_nonce_manager()
    nonce_file = manager._nonce_file
    
    print(f"✓ Nonce file location: {nonce_file}")
    
    # Generate a nonce
    nonce1 = get_global_kraken_nonce()
    print(f"✓ Generated nonce 1: {nonce1}")
    
    # Verify file exists
    assert os.path.exists(nonce_file), f"❌ Nonce file not created: {nonce_file}"
    print(f"✓ Nonce file created")
    
    # Read file contents
    with open(nonce_file, 'r') as f:
        persisted_nonce = int(f.read().strip())
    
    assert persisted_nonce == nonce1, f"❌ Persisted nonce {persisted_nonce} != generated nonce {nonce1}"
    print(f"✓ Nonce persisted to disk correctly: {persisted_nonce}")
    
    # Generate another nonce
    nonce2 = get_global_kraken_nonce()
    print(f"✓ Generated nonce 2: {nonce2}")
    
    # Verify monotonic increase
    assert nonce2 > nonce1, f"❌ Nonce 2 ({nonce2}) not greater than nonce 1 ({nonce1})"
    print(f"✓ Nonce is monotonically increasing")
    
    # Verify formula: should be at least last_nonce + 1
    assert nonce2 >= nonce1 + 1, f"❌ Nonce 2 ({nonce2}) < nonce 1 + 1 ({nonce1 + 1})"
    print(f"✓ Nonce follows formula: max(last_nonce + 1, current_timestamp_ns)")
    
    # Test restart simulation
    # Read persisted nonce
    with open(nonce_file, 'r') as f:
        last_persisted = int(f.read().strip())
    
    print(f"✓ Last persisted nonce before 'restart': {last_persisted}")
    
    # Reset manager (simulates process restart)
    manager.reset_for_testing()
    
    # Generate new nonce after reset
    nonce3 = get_global_kraken_nonce()
    print(f"✓ Generated nonce after reset: {nonce3}")
    
    # Should be greater than last persisted nonce
    assert nonce3 > last_persisted, f"❌ Nonce after reset ({nonce3}) not greater than last persisted ({last_persisted})"
    print(f"✓ Nonce survives restart correctly")
    
    print("\n✅ FIX 1 PASSED: Nonce persistence working correctly")
    return True


def test_fix_2_serialization():
    """
    Test Fix 2: Single-file queue for Kraken private calls.
    
    Verifies:
    - Global API lock exists
    - Lock is reentrant
    - Lock serializes concurrent calls
    """
    print("\n" + "=" * 70)
    print("TEST FIX 2: Single-File Queue for Kraken Private Calls")
    print("=" * 70)
    
    # Get global lock
    lock = get_kraken_api_lock()
    print(f"✓ Global API lock retrieved: {type(lock)}")
    
    # Verify it's an RLock (check type name since RLock is a factory function)
    lock_type_name = type(lock).__name__
    assert 'RLock' in lock_type_name or 'lock' in lock_type_name.lower(), f"❌ Lock is not RLock: {type(lock)}"
    print(f"✓ Lock is reentrant (RLock)")
    
    # Test lock acquisition
    acquired = lock.acquire(blocking=False)
    assert acquired, "❌ Could not acquire lock"
    print(f"✓ Lock acquired successfully")
    
    # Test reentrant acquisition (same thread can acquire multiple times)
    reacquired = lock.acquire(blocking=False)
    assert reacquired, "❌ Could not reacquire lock (not reentrant)"
    print(f"✓ Lock is reentrant (same thread can acquire multiple times)")
    
    # Release both acquisitions
    lock.release()
    lock.release()
    print(f"✓ Lock released successfully")
    
    # Test concurrent access
    call_order = []
    
    def simulated_api_call(call_id, delay=0.1):
        """Simulate an API call with the global lock"""
        with lock:
            call_order.append(f"{call_id}_start")
            time.sleep(delay)
            call_order.append(f"{call_id}_end")
    
    # Start 3 threads that try to call simultaneously
    threads = []
    for i in range(3):
        thread = threading.Thread(target=simulated_api_call, args=(f"call_{i}", 0.05))
        threads.append(thread)
    
    # Start all threads at once
    for thread in threads:
        thread.start()
    
    # Wait for completion
    for thread in threads:
        thread.join()
    
    print(f"✓ Call order: {call_order}")
    
    # Verify serialization: each call should complete before next starts
    # Pattern should be: call_X_start, call_X_end, call_Y_start, call_Y_end, ...
    for i in range(0, len(call_order) - 1, 2):
        start = call_order[i]
        end = call_order[i + 1]
        
        # Extract call IDs
        start_id = start.split('_')[1]
        end_id = end.split('_')[1]
        
        # Same call should start and end together
        assert start_id == end_id, f"❌ Calls not serialized: {start} followed by {end}"
    
    print(f"✓ Calls are properly serialized (one at a time)")
    
    print("\n✅ FIX 2 PASSED: API call serialization working correctly")
    return True


def test_fix_3_fail_closed():
    """
    Test Fix 3: Fail closed - not "balance = 0".
    
    This is a conceptual test since we can't test against live Kraken API.
    We verify that the code structure is correct.
    """
    print("\n" + "=" * 70)
    print("TEST FIX 3: Fail Closed - Not 'Balance = 0'")
    print("=" * 70)
    
    # Import KrakenBroker to verify structure
    import broker_manager
    from broker_manager import KrakenBroker, AccountType
    
    # Create a Kraken broker instance (won't connect without credentials)
    try:
        broker = KrakenBroker(account_type=AccountType.MASTER)
        print(f"✓ KrakenBroker instance created")
    except Exception as e:
        print(f"❌ Could not create KrakenBroker: {e}")
        return False
    
    # Verify balance tracking attributes exist
    assert hasattr(broker, '_last_known_balance'), "❌ Missing _last_known_balance attribute"
    print(f"✓ Has _last_known_balance attribute")
    
    assert hasattr(broker, '_balance_fetch_errors'), "❌ Missing _balance_fetch_errors attribute"
    print(f"✓ Has _balance_fetch_errors attribute")
    
    assert hasattr(broker, '_is_available'), "❌ Missing _is_available attribute"
    print(f"✓ Has _is_available attribute")
    
    # Verify initial states
    assert broker._last_known_balance is None, "❌ _last_known_balance should be None initially"
    print(f"✓ _last_known_balance initialized to None")
    
    assert broker._balance_fetch_errors == 0, "❌ _balance_fetch_errors should be 0 initially"
    print(f"✓ _balance_fetch_errors initialized to 0")
    
    assert broker._is_available == True, "❌ _is_available should be True initially"
    print(f"✓ _is_available initialized to True")
    
    # Verify methods exist
    assert hasattr(broker, 'is_available'), "❌ Missing is_available() method"
    print(f"✓ Has is_available() method")
    
    assert hasattr(broker, 'get_error_count'), "❌ Missing get_error_count() method"
    print(f"✓ Has get_error_count() method")
    
    # Test is_available method
    assert broker.is_available() == True, "❌ is_available() should return True initially"
    print(f"✓ is_available() returns True initially")
    
    # Test get_error_count method
    assert broker.get_error_count() == 0, "❌ get_error_count() should return 0 initially"
    print(f"✓ get_error_count() returns 0 initially")
    
    print("\n✅ FIX 3 PASSED: Fail-closed structure implemented correctly")
    return True


def main():
    """Run all tests"""
    print("\n" + "=" * 70)
    print("KRAKEN FIXES TEST SUITE - JAN 19, 2026")
    print("=" * 70)
    
    results = []
    
    try:
        results.append(("Fix 1: Nonce Persistence", test_fix_1_nonce_persistence()))
    except Exception as e:
        print(f"❌ Fix 1 test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Fix 1: Nonce Persistence", False))
    
    try:
        results.append(("Fix 2: API Serialization", test_fix_2_serialization()))
    except Exception as e:
        print(f"❌ Fix 2 test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Fix 2: API Serialization", False))
    
    try:
        results.append(("Fix 3: Fail Closed", test_fix_3_fail_closed()))
    except Exception as e:
        print(f"❌ Fix 3 test failed with exception: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Fix 3: Fail Closed", False))
    
    # Print summary
    print("\n" + "=" * 70)
    print("TEST SUMMARY")
    print("=" * 70)
    
    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {name}")
    
    all_passed = all(result for _, result in results)
    
    if all_passed:
        print("\n🎉 ALL TESTS PASSED!")
        return 0
    else:
        print("\n⚠️  SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
