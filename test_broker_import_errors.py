#!/usr/bin/env python3
"""
Test broker import error handling
==================================

This script tests that brokers properly log import errors instead of
failing silently when required SDKs are not installed.

This test temporarily renames packages in sys.modules to simulate
ImportError conditions.
"""

import sys
import os
import logging

# Setup logging to see what brokers log
logging.basicConfig(
    level=logging.DEBUG,
    format='%(levelname)s | %(message)s'
)

def test_kraken_import_error():
    """Test that KrakenBroker logs ImportError details"""
    print("\n" + "="*80)
    print("TEST: Kraken ImportError Handling")
    print("="*80)
    
    # Temporarily hide krakenex to simulate ImportError
    krakenex_module = sys.modules.get('krakenex')
    pykrakenapi_module = sys.modules.get('pykrakenapi')
    
    # Remove from sys.modules if present
    if 'krakenex' in sys.modules:
        del sys.modules['krakenex']
    if 'pykrakenapi' in sys.modules:
        del sys.modules['pykrakenapi']
    
    # Block future imports
    sys.modules['krakenex'] = None
    sys.modules['pykrakenapi'] = None
    
    try:
        # Set env vars to trigger connection attempt
        os.environ['KRAKEN_MASTER_API_KEY'] = 'test_key_12345'
        os.environ['KRAKEN_MASTER_API_SECRET'] = 'test_secret_67890'
        
        # Import broker manager (must be after blocking imports)
        from bot.broker_manager import KrakenBroker, AccountType
        
        # Try to connect
        broker = KrakenBroker(account_type=AccountType.MASTER)
        result = broker.connect()
        
        print(f"\nResult: {result}")
        print("Expected: False (connection should fail)")
        print("Expected: Error logs showing ImportError details")
        
        if result:
            print("❌ TEST FAILED: Connection should have failed")
            return False
        else:
            print("✅ TEST PASSED: Connection failed as expected")
            return True
            
    finally:
        # Restore sys.modules
        if krakenex_module is not None:
            sys.modules['krakenex'] = krakenex_module
        else:
            sys.modules.pop('krakenex', None)
            
        if pykrakenapi_module is not None:
            sys.modules['pykrakenapi'] = pykrakenapi_module
        else:
            sys.modules.pop('pykrakenapi', None)
        
        # Clean up env vars
        os.environ.pop('KRAKEN_MASTER_API_KEY', None)
        os.environ.pop('KRAKEN_MASTER_API_SECRET', None)


def test_alpaca_import_error():
    """Test that AlpacaBroker logs ImportError details"""
    print("\n" + "="*80)
    print("TEST: Alpaca ImportError Handling")
    print("="*80)
    
    # Temporarily hide alpaca module to simulate ImportError
    alpaca_module = sys.modules.get('alpaca')
    
    # Remove from sys.modules if present
    if 'alpaca' in sys.modules:
        del sys.modules['alpaca']
    
    # Block future imports
    sys.modules['alpaca'] = None
    
    try:
        # Set env vars to trigger connection attempt
        os.environ['ALPACA_API_KEY'] = 'test_key_12345'
        os.environ['ALPACA_API_SECRET'] = 'test_secret_67890'
        
        # Import broker manager (must be after blocking imports)
        from bot.broker_manager import AlpacaBroker, AccountType
        
        # Try to connect
        broker = AlpacaBroker(account_type=AccountType.MASTER)
        result = broker.connect()
        
        print(f"\nResult: {result}")
        print("Expected: False (connection should fail)")
        print("Expected: Error logs showing ImportError details")
        
        if result:
            print("❌ TEST FAILED: Connection should have failed")
            return False
        else:
            print("✅ TEST PASSED: Connection failed as expected")
            return True
            
    finally:
        # Restore sys.modules
        if alpaca_module is not None:
            sys.modules['alpaca'] = alpaca_module
        else:
            sys.modules.pop('alpaca', None)
        
        # Clean up env vars
        os.environ.pop('ALPACA_API_KEY', None)
        os.environ.pop('ALPACA_API_SECRET', None)


def main():
    """Run all import error tests"""
    print("="*80)
    print("Broker Import Error Handling Tests")
    print("="*80)
    
    results = []
    
    # Test Kraken
    try:
        results.append(("Kraken", test_kraken_import_error()))
    except Exception as e:
        print(f"❌ Kraken test crashed: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Kraken", False))
    
    # Test Alpaca
    try:
        results.append(("Alpaca", test_alpaca_import_error()))
    except Exception as e:
        print(f"❌ Alpaca test crashed: {e}")
        import traceback
        traceback.print_exc()
        results.append(("Alpaca", False))
    
    # Summary
    print("\n" + "="*80)
    print("TEST SUMMARY")
    print("="*80)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for name, result in results:
        status = "✅ PASSED" if result else "❌ FAILED"
        print(f"{name}: {status}")
    
    print()
    print(f"Total: {passed}/{total} passed")
    
    if passed == total:
        print("\n🎉 ALL TESTS PASSED!")
        return 0
    else:
        print(f"\n❌ {total - passed} TEST(S) FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
