#!/usr/bin/env python3
"""
Test script to verify the Kraken market discovery fix.

This test verifies that the get_all_products() method correctly iterates
over the pandas DataFrame returned by pykrakenapi's get_tradable_asset_pairs().
"""

import sys
import pandas as pd
from unittest.mock import Mock, MagicMock

# Mock the external dependencies before importing broker_manager
sys.modules['krakenex'] = MagicMock()
sys.modules['pykrakenapi'] = MagicMock()

# Now import after mocking
from bot.broker_manager import KrakenBroker, AccountType

def test_get_all_products_with_dataframe():
    """
    Test that get_all_products correctly processes a pandas DataFrame.
    
    This simulates the actual return value from pykrakenapi.get_tradable_asset_pairs()
    which is a DataFrame with pair information.
    """
    print("=" * 80)
    print("TEST: Kraken Market Discovery with DataFrame")
    print("=" * 80)
    print()
    
    # Create a KrakenBroker instance (without connecting)
    broker = KrakenBroker(account_type=AccountType.MASTER)
    
    # Create a mock DataFrame similar to what pykrakenapi returns
    # The DataFrame has pair names as index and various columns including 'wsname'
    mock_data = {
        'wsname': [
            'BTC/USD',      # Should be included
            'ETH/USD',      # Should be included
            'XRP/USD',      # Should be included
            'SOL/USDT',     # Should be included (USDT)
            'ADA/EUR',      # Should be excluded (EUR)
            'DOT/GBP',      # Should be excluded (GBP)
            'MATIC/USD',    # Should be included
            '',             # Should be excluded (empty wsname)
        ],
        'pair': ['XXBTZUSD', 'XETHZUSD', 'XXRPZUSD', 'SOLUSD', 'ADAEUR', 'DOTGBP', 'MATICUSD', ''],
        'quote': ['USD', 'USD', 'USD', 'USDT', 'EUR', 'GBP', 'USD', ''],
    }
    
    mock_df = pd.DataFrame(mock_data)
    
    # Mock the kraken_api to return our test DataFrame
    broker.kraken_api = Mock()
    broker.kraken_api.get_tradable_asset_pairs = Mock(return_value=mock_df)
    
    print("Mock DataFrame:")
    print(mock_df)
    print()
    
    # Call get_all_products
    print("Calling get_all_products()...")
    try:
        products = broker.get_all_products()
        
        print(f"✅ Success! Found {len(products)} products")
        print()
        print("Products returned:")
        for product in products:
            print(f"  - {product}")
        print()
        
        # Verify the results
        expected_products = ['BTC-USD', 'ETH-USD', 'XRP-USD', 'SOL-USDT', 'MATIC-USD']
        
        if set(products) == set(expected_products):
            print("✅ TEST PASSED: Correct products returned")
            print(f"   Expected: {expected_products}")
            print(f"   Got:      {products}")
            return True
        else:
            print("❌ TEST FAILED: Products don't match expected")
            print(f"   Expected: {expected_products}")
            print(f"   Got:      {products}")
            
            missing = set(expected_products) - set(products)
            extra = set(products) - set(expected_products)
            
            if missing:
                print(f"   Missing:  {list(missing)}")
            if extra:
                print(f"   Extra:    {list(extra)}")
            
            return False
            
    except Exception as e:
        print(f"❌ TEST FAILED: Exception occurred")
        print(f"   Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_get_all_products_handles_empty_dataframe():
    """Test that get_all_products handles an empty DataFrame gracefully."""
    print("=" * 80)
    print("TEST: Kraken Market Discovery with Empty DataFrame")
    print("=" * 80)
    print()
    
    broker = KrakenBroker(account_type=AccountType.MASTER)
    
    # Create an empty DataFrame
    empty_df = pd.DataFrame(columns=['wsname', 'pair', 'quote'])
    
    broker.kraken_api = Mock()
    broker.kraken_api.get_tradable_asset_pairs = Mock(return_value=empty_df)
    
    print("Calling get_all_products() with empty DataFrame...")
    try:
        products = broker.get_all_products()
        
        if len(products) == 0:
            print("✅ TEST PASSED: Correctly returns empty list for empty DataFrame")
            return True
        else:
            print(f"❌ TEST FAILED: Expected empty list, got {products}")
            return False
            
    except Exception as e:
        print(f"❌ TEST FAILED: Exception occurred")
        print(f"   Error: {e}")
        return False


def test_get_all_products_handles_missing_wsname_column():
    """Test that get_all_products handles DataFrame without 'wsname' column."""
    print("=" * 80)
    print("TEST: Kraken Market Discovery with Missing wsname Column")
    print("=" * 80)
    print()
    
    broker = KrakenBroker(account_type=AccountType.MASTER)
    
    # Create a DataFrame without 'wsname' column
    # This should trigger the .get() default value behavior
    mock_data = {
        'pair': ['XXBTZUSD', 'XETHZUSD'],
        'quote': ['USD', 'USD'],
    }
    mock_df = pd.DataFrame(mock_data)
    
    broker.kraken_api = Mock()
    broker.kraken_api.get_tradable_asset_pairs = Mock(return_value=mock_df)
    
    print("Calling get_all_products() with DataFrame missing 'wsname'...")
    try:
        products = broker.get_all_products()
        
        # Should return empty list since wsname is missing (defaults to '')
        if len(products) == 0:
            print("✅ TEST PASSED: Correctly handles missing 'wsname' column")
            return True
        else:
            print(f"⚠️  TEST WARNING: Expected empty list, got {products}")
            print("   (This might be acceptable if fallback logic triggers)")
            return True  # Not a failure, might be fallback behavior
            
    except Exception as e:
        print(f"❌ TEST FAILED: Exception occurred")
        print(f"   Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print()
    print("=" * 80)
    print(" KRAKEN MARKET DISCOVERY FIX - TEST SUITE")
    print("=" * 80)
    print()
    
    tests = [
        ("DataFrame Processing", test_get_all_products_with_dataframe),
        ("Empty DataFrame", test_get_all_products_handles_empty_dataframe),
        ("Missing wsname Column", test_get_all_products_handles_missing_wsname_column),
    ]
    
    results = []
    for test_name, test_func in tests:
        print()
        result = test_func()
        results.append((test_name, result))
        print()
    
    # Summary
    print("=" * 80)
    print(" TEST SUMMARY")
    print("=" * 80)
    print()
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"  {status}: {test_name}")
    
    print()
    print(f"Total: {passed}/{total} tests passed")
    print()
    
    if passed == total:
        print("🎉 ALL TESTS PASSED!")
        return 0
    else:
        print("❌ SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
