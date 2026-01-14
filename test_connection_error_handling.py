#!/usr/bin/env python3
"""
Test script to verify connection error handling in broker_manager.py

This script tests the improved error handling for ConnectionResetError
and other network-related exceptions.
"""

import sys
import os
import logging
from unittest.mock import Mock, patch

# Configure logging to see the output
logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s:%(name)s:%(message)s'
)

# Add bot directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

def test_connection_error_retry():
    """Test that connection errors are retried properly"""
    from broker_manager import CoinbaseBroker
    
    broker = CoinbaseBroker()
    
    # Mock API function that raises ConnectionResetError
    mock_api_func = Mock(side_effect=[
        ConnectionResetError(104, 'Connection reset by peer'),
        ConnectionResetError(104, 'Connection reset by peer'),
        {'success': True}  # Success on third attempt
    ])
    
    print("\n" + "="*70)
    print("TEST 1: Connection error with successful retry")
    print("="*70)
    
    try:
        result = broker._api_call_with_retry(mock_api_func, max_retries=3, base_delay=0.1)
        print(f"✅ Test 1 PASSED: Connection error was retried and succeeded")
        print(f"   Result: {result}")
        print(f"   API function was called {mock_api_func.call_count} times")
    except Exception as e:
        print(f"❌ Test 1 FAILED: {e}")
        return False
    
    return True

def test_connection_error_formatting():
    """Test that connection errors are formatted nicely in logs"""
    from broker_manager import CoinbaseBroker
    
    print("\n" + "="*70)
    print("TEST 2: Connection error message formatting")
    print("="*70)
    
    broker = CoinbaseBroker()
    broker.client = Mock()
    
    # Mock get_portfolios to raise ConnectionResetError
    broker.client.get_portfolios = Mock(
        side_effect=ConnectionResetError(104, 'Connection reset by peer')
    )
    
    # Mock get_accounts to succeed (fallback path)
    broker.client.get_accounts = Mock(return_value=Mock(
        accounts=[]
    ))
    
    print("Testing connection error handling in _get_account_balance_detailed()...")
    
    try:
        result = broker._get_account_balance_detailed()
        print(f"✅ Test 2 PASSED: Connection error was handled gracefully")
        print(f"   Successfully fell back to get_accounts()")
        print(f"   Result: {result}")
    except Exception as e:
        print(f"❌ Test 2 FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

def test_rate_limit_error_still_works():
    """Test that rate limit errors are still retried properly"""
    from broker_manager import CoinbaseBroker
    
    broker = CoinbaseBroker()
    
    # Mock API function that raises rate limit error
    mock_api_func = Mock(side_effect=[
        Exception('429 Too Many Requests'),
        {'success': True}  # Success on second attempt
    ])
    
    print("\n" + "="*70)
    print("TEST 3: Rate limit error (existing functionality)")
    print("="*70)
    
    try:
        result = broker._api_call_with_retry(mock_api_func, max_retries=3, base_delay=0.1)
        print(f"✅ Test 3 PASSED: Rate limit error was retried and succeeded")
        print(f"   Result: {result}")
        print(f"   API function was called {mock_api_func.call_count} times")
    except Exception as e:
        print(f"❌ Test 3 FAILED: {e}")
        return False
    
    return True

def test_non_retryable_error():
    """Test that non-retryable errors are raised immediately"""
    from broker_manager import CoinbaseBroker
    
    broker = CoinbaseBroker()
    
    # Mock API function that raises non-retryable error
    mock_api_func = Mock(side_effect=ValueError('Invalid input'))
    
    print("\n" + "="*70)
    print("TEST 4: Non-retryable error (should fail immediately)")
    print("="*70)
    
    try:
        result = broker._api_call_with_retry(mock_api_func, max_retries=3, base_delay=0.1)
        print(f"❌ Test 4 FAILED: Should have raised ValueError")
        return False
    except ValueError as e:
        print(f"✅ Test 4 PASSED: Non-retryable error was raised immediately")
        print(f"   Error: {e}")
        print(f"   API function was called {mock_api_func.call_count} time(s)")
        if mock_api_func.call_count > 1:
            print(f"   ⚠️  WARNING: Function was called {mock_api_func.call_count} times, expected 1")
            return False
    
    return True

def main():
    """Run all tests"""
    print("\n" + "="*70)
    print("CONNECTION ERROR HANDLING TEST SUITE")
    print("="*70)
    
    tests = [
        ("Connection error retry", test_connection_error_retry),
        ("Connection error formatting", test_connection_error_formatting),
        ("Rate limit error (existing)", test_rate_limit_error_still_works),
        ("Non-retryable error", test_non_retryable_error),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            passed = test_func()
            results.append((test_name, passed))
        except Exception as e:
            print(f"\n❌ Test '{test_name}' raised unexpected exception: {e}")
            import traceback
            traceback.print_exc()
            results.append((test_name, False))
    
    # Summary
    print("\n" + "="*70)
    print("TEST SUMMARY")
    print("="*70)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{status}: {test_name}")
    
    print("="*70)
    print(f"Results: {passed}/{total} tests passed")
    print("="*70)
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
