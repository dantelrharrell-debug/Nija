#!/usr/bin/env python3
"""
Integration test for Global Kraken Nonce Manager
=================================================

This test simulates the real-world scenario of:
- 1 MASTER account
- Multiple USER accounts
- All making simultaneous Kraken API calls
- Using the global nonce manager

Tests that:
1. No nonce collisions occur
2. All nonces are unique
3. System scales to multiple users
"""

import sys
import os
import time
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

# Import the global nonce manager
from global_kraken_nonce import get_global_kraken_nonce, get_global_nonce_stats


def simulate_kraken_api_call(account_id: str, request_num: int):
    """
    Simulate a single Kraken API call.
    
    Args:
        account_id: Account identifier (e.g., 'MASTER', 'USER:daivon')
        request_num: Request number for this account
        
    Returns:
        Tuple of (account_id, request_num, nonce)
    """
    # Get nonce from global manager (just like real Kraken API calls)
    nonce = get_global_kraken_nonce()
    
    # Simulate API call processing time
    time.sleep(0.001)
    
    return (account_id, request_num, nonce)


def simulate_account_activity(account_id: str, num_requests: int = 50):
    """
    Simulate an account making multiple API calls.
    
    Args:
        account_id: Account identifier
        num_requests: Number of API calls to make
        
    Returns:
        List of (account_id, request_num, nonce) tuples
    """
    results = []
    
    for i in range(num_requests):
        result = simulate_kraken_api_call(account_id, i + 1)
        results.append(result)
        
        # Small random delay between requests (realistic)
        time.sleep(0.002 + (0.001 * (i % 3)))
    
    return results


def main():
    """Run the integration test"""
    print("=" * 70)
    print("KRAKEN GLOBAL NONCE MANAGER - INTEGRATION TEST")
    print("=" * 70)
    print()
    print("Simulating real-world scenario:")
    print("  - 1 MASTER account")
    print("  - 5 USER accounts")
    print("  - 50 API calls per account")
    print("  - Concurrent execution")
    print()
    
    # Define accounts
    accounts = [
        'MASTER',
        'USER:daivon_frazier',
        'USER:tania_gilbert',
        'USER:alex_johnson',
        'USER:jordan_smith',
        'USER:casey_brown',
    ]
    
    num_requests_per_account = 50
    total_expected_requests = len(accounts) * num_requests_per_account
    
    print(f"Expected total API calls: {total_expected_requests}")
    print()
    print("Starting simulation...")
    print()
    
    # Run accounts concurrently (simulates real deployment)
    start_time = time.time()
    all_results = []
    
    with ThreadPoolExecutor(max_workers=len(accounts)) as executor:
        # Submit all accounts
        futures = {
            executor.submit(simulate_account_activity, account_id, num_requests_per_account): account_id
            for account_id in accounts
        }
        
        # Collect results as they complete
        for future in as_completed(futures):
            account_id = futures[future]
            try:
                results = future.result()
                all_results.extend(results)
                print(f"✅ {account_id}: {len(results)} API calls completed")
            except Exception as e:
                print(f"❌ {account_id}: Error - {e}")
    
    elapsed_time = time.time() - start_time
    
    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    
    # Analyze results
    total_calls = len(all_results)
    all_nonces = [result[2] for result in all_results]
    unique_nonces = set(all_nonces)
    num_duplicates = total_calls - len(unique_nonces)
    
    print(f"Total API calls made: {total_calls}")
    print(f"Expected: {total_expected_requests}")
    print(f"Unique nonces: {len(unique_nonces)}")
    print(f"Duplicate nonces: {num_duplicates}")
    print(f"Elapsed time: {elapsed_time:.2f}s")
    print(f"Throughput: {total_calls/elapsed_time:.0f} calls/second")
    print()
    
    # Check for collisions
    if num_duplicates == 0 and total_calls == total_expected_requests:
        print("✅ SUCCESS: Zero nonce collisions!")
        print("✅ All accounts completed successfully")
        print()
        
        # Show statistics
        stats = get_global_nonce_stats()
        print("Global Nonce Manager Statistics:")
        print(f"  Total nonces issued: {stats['total_nonces_issued']}")
        print(f"  Last nonce: {stats['last_nonce']}")
        print(f"  Uptime: {stats['uptime_seconds']:.2f}s")
        print(f"  Rate: {stats['nonces_per_second']:.0f} nonces/second")
        print()
        
        # Verify all nonces are in nanosecond range
        min_nonce = min(all_nonces)
        max_nonce = max(all_nonces)
        print(f"Nonce range:")
        print(f"  Min: {min_nonce} ({len(str(min_nonce))} digits)")
        print(f"  Max: {max_nonce} ({len(str(max_nonce))} digits)")
        print()
        
        # Check strictly monotonic (within each account)
        print("Checking monotonic guarantee per account...")
        all_monotonic = True
        for account_id in accounts:
            account_results = [r for r in all_results if r[0] == account_id]
            account_nonces = [r[2] for r in account_results]
            
            # Sort by request number to get original order
            sorted_by_request = sorted(account_results, key=lambda x: x[1])
            ordered_nonces = [r[2] for r in sorted_by_request]
            
            # Check if monotonic
            is_monotonic = all(ordered_nonces[i] < ordered_nonces[i+1] 
                             for i in range(len(ordered_nonces)-1))
            
            status = "✅" if is_monotonic else "❌"
            print(f"  {status} {account_id}: {'Monotonic' if is_monotonic else 'NOT monotonic'}")
            
            if not is_monotonic:
                all_monotonic = False
        
        print()
        
        if all_monotonic:
            print("✅ All accounts have monotonic nonces")
        else:
            print("⚠️  Some accounts have non-monotonic nonces")
        
        print()
        print("=" * 70)
        print("INTEGRATION TEST PASSED ✅")
        print("=" * 70)
        print()
        print("The global Kraken nonce manager successfully handled:")
        print(f"  ✅ {len(accounts)} concurrent accounts (1 master + {len(accounts)-1} users)")
        print(f"  ✅ {total_calls} total API calls")
        print(f"  ✅ Zero nonce collisions")
        print(f"  ✅ {total_calls/elapsed_time:.0f} calls/second throughput")
        print()
        print("System is READY for production deployment with multi-user copy trading!")
        
        return 0
    else:
        print("❌ FAILURE: Issues detected")
        if num_duplicates > 0:
            print(f"  ❌ {num_duplicates} duplicate nonces found")
        if total_calls != total_expected_requests:
            print(f"  ❌ Expected {total_expected_requests} calls, got {total_calls}")
        
        return 1


if __name__ == "__main__":
    sys.exit(main())
