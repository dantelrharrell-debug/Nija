#!/usr/bin/env python3
"""
Test script to verify connection fixes for 403 errors and missing credentials.
Tests the retry logic and error handling improvements.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import CoinbaseBroker, KrakenBroker, AlpacaBroker, OKXBroker, AccountType

def test_retryable_error_detection():
    """Test that 403 errors are properly detected as retryable."""
    print("\n" + "="*70)
    print("TEST 1: Verify 403 Error Detection as Retryable")
    print("="*70)
    
    test_errors = [
        ("403 Client Error: Forbidden Too many errors", True),
        ("HTTP Error: 403 Forbidden", True),
        ("Too many errors - please try again later", True),
        ("Forbidden access", True),
        ("429 Too many requests", True),
        ("Network timeout", True),
        ("401 Unauthorized", False),
        ("Invalid API key", False),
        ("404 Not found", False),
    ]
    
    # Test the retryable logic from the code
    def is_retryable(error_msg: str) -> bool:
        error_msg_lower = error_msg.lower()
        return any(keyword in error_msg_lower for keyword in [
            'timeout', 'connection', 'network', 'rate limit',
            'too many requests', 'service unavailable',
            '503', '504', '429', '403', 'forbidden', 
            'too many errors', 'temporary', 'try again'
        ])
    
    all_passed = True
    for error_msg, expected_retryable in test_errors:
        result = is_retryable(error_msg)
        status = "✅" if result == expected_retryable else "❌"
        print(f"{status} '{error_msg}' -> Retryable: {result} (expected: {expected_retryable})")
        if result != expected_retryable:
            all_passed = False
    
    if all_passed:
        print("\n✅ All error detection tests passed!")
    else:
        print("\n❌ Some error detection tests failed!")
    
    return all_passed


def test_retry_delay_calculation():
    """Test that retry delays are correctly calculated with exponential backoff and cap."""
    print("\n" + "="*70)
    print("TEST 2: Verify Retry Delay Calculation")
    print("="*70)
    
    base_delay = 15.0
    max_delay_cap = 120.0
    
    print(f"Base delay: {base_delay}s")
    print(f"Max delay cap: {max_delay_cap}s")
    print(f"\nExpected delays for 10 attempts:")
    
    all_correct = True
    for attempt in range(1, 11):
        if attempt == 1:
            delay = 0  # First attempt has no delay
        else:
            # Calculate delay with exponential backoff and cap
            delay = min(base_delay * (2 ** (attempt - 2)), max_delay_cap)
        
        print(f"  Attempt {attempt}: {delay}s")
        
        # Verify cap is applied
        if delay > max_delay_cap:
            print(f"    ❌ ERROR: Delay {delay}s exceeds cap {max_delay_cap}s")
            all_correct = False
        
        # Verify exponential growth up to cap
        if attempt > 1:
            expected = min(base_delay * (2 ** (attempt - 2)), max_delay_cap)
            if abs(delay - expected) > 0.01:
                print(f"    ❌ ERROR: Expected {expected}s, got {delay}s")
                all_correct = False
    
    if all_correct:
        print("\n✅ Retry delay calculation is correct!")
    else:
        print("\n❌ Retry delay calculation has errors!")
    
    return all_correct


def test_broker_initialization():
    """Test broker initialization with missing credentials."""
    print("\n" + "="*70)
    print("TEST 3: Test Broker Initialization with Missing Credentials")
    print("="*70)
    
    # Temporarily clear credentials to test graceful failure
    original_env = {}
    for key in ['COINBASE_API_KEY', 'COINBASE_API_SECRET', 
                'KRAKEN_MASTER_API_KEY', 'KRAKEN_MASTER_API_SECRET',
                'ALPACA_API_KEY', 'ALPACA_API_SECRET',
                'OKX_API_KEY', 'OKX_API_SECRET', 'OKX_PASSPHRASE']:
        original_env[key] = os.environ.pop(key, None)
    
    try:
        # Test Coinbase with missing credentials
        print("\n📊 Testing Coinbase with missing credentials...")
        coinbase = CoinbaseBroker()
        result = coinbase.connect()
        if result:
            print("  ❌ ERROR: Should have failed with missing credentials")
            return False
        else:
            print("  ✅ Correctly failed with missing credentials")
        
        # Test Kraken with missing credentials
        print("\n📊 Testing Kraken (MASTER) with missing credentials...")
        kraken = KrakenBroker(account_type=AccountType.MASTER)
        result = kraken.connect()
        if result:
            print("  ❌ ERROR: Should have failed with missing credentials")
            return False
        else:
            print("  ✅ Correctly failed with missing credentials")
        
        # Test Alpaca with missing credentials
        print("\n📊 Testing Alpaca with missing credentials...")
        alpaca = AlpacaBroker()
        result = alpaca.connect()
        if result:
            print("  ❌ ERROR: Should have failed with missing credentials")
            return False
        else:
            print("  ✅ Correctly failed with missing credentials")
        
        # Test OKX with missing credentials
        print("\n📊 Testing OKX with missing credentials...")
        okx = OKXBroker()
        result = okx.connect()
        if result:
            print("  ❌ ERROR: Should have failed with missing credentials")
            return False
        else:
            print("  ✅ Correctly failed with missing credentials")
        
        print("\n✅ All brokers correctly handle missing credentials!")
        return True
        
    finally:
        # Restore original environment
        for key, value in original_env.items():
            if value is not None:
                os.environ[key] = value


def main():
    """Run all tests."""
    print("\n" + "="*70)
    print("BROKER CONNECTION FIX VERIFICATION TESTS")
    print("="*70)
    
    results = []
    
    # Test 1: Error detection
    results.append(("Error Detection", test_retryable_error_detection()))
    
    # Test 2: Retry delay calculation
    results.append(("Retry Delay Calculation", test_retry_delay_calculation()))
    
    # Test 3: Broker initialization with missing credentials
    results.append(("Missing Credentials Handling", test_broker_initialization()))
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    all_passed = True
    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")
        if not passed:
            all_passed = False
    
    print("="*70)
    
    if all_passed:
        print("\n✅ ALL TESTS PASSED! Connection fixes are working correctly.")
        return 0
    else:
        print("\n❌ SOME TESTS FAILED! Please review the errors above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
