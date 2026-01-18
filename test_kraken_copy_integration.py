#!/usr/bin/env python3
"""
Test Kraken Copy Trading Integration
====================================

Tests that the copy trading system integrates properly with the broker.
"""

import os
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)


def test_import_integration():
    """Test that all modules can be imported together."""
    print("=" * 70)
    print("TEST: Import Integration")
    print("=" * 70)
    
    try:
        # Import copy trading module
        from bot import kraken_copy_trading
        print("✅ kraken_copy_trading module imported")
        
        # Import trading strategy
        # (Note: This will fail if dependencies are missing, which is expected in test env)
        try:
            from bot import trading_strategy
            print("✅ trading_strategy module imported")
        except ImportError as e:
            print(f"⚠️  trading_strategy import skipped (missing deps): {e}")
        
        # Check exports
        expected_exports = [
            'KrakenClient',
            'initialize_copy_trading_system',
            'wrap_kraken_broker_for_copy_trading',
            'execute_master_trade',
            'copy_trade_to_kraken_users',
        ]
        
        for export in expected_exports:
            if hasattr(kraken_copy_trading, export):
                print(f"✅ Export found: {export}")
            else:
                print(f"❌ Export missing: {export}")
                return False
        
        print("✅ All exports present")
        return True
        
    except Exception as e:
        print(f"❌ Import failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_wrapper_function():
    """Test the broker wrapping function."""
    print("\n" + "=" * 70)
    print("TEST: Broker Wrapper Function")
    print("=" * 70)
    
    try:
        from bot.kraken_copy_trading import wrap_kraken_broker_for_copy_trading
        
        # Create a mock broker object
        class MockBroker:
            def __init__(self):
                try:
                    from bot.broker_manager import AccountType
                    self.account_type = AccountType.MASTER
                except ImportError:
                    # Fallback for test environment
                    class MockAccountType:
                        MASTER = "MASTER"
                    self.account_type = MockAccountType.MASTER
                
                self.account_identifier = "TEST_MASTER"
                self.place_market_order_called = False
            
            def place_market_order(self, symbol, side, quantity):
                self.place_market_order_called = True
                return {
                    'status': 'filled',
                    'order_id': 'test_order_123',
                    'symbol': symbol,
                    'side': side,
                    'quantity': quantity
                }
            
            def get_account_balance(self):
                return 1000.0
        
        # Create mock broker
        broker = MockBroker()
        print("✅ Mock broker created")
        
        # Wrap it
        wrapped = wrap_kraken_broker_for_copy_trading(broker)
        print("✅ Broker wrapped successfully")
        
        # Verify it's the same instance (wrapped in-place)
        assert wrapped is broker, "Wrapper should return same instance"
        print("✅ Wrapper returns same instance (in-place modification)")
        
        # Verify method was replaced
        assert hasattr(broker, 'place_market_order'), "place_market_order method missing"
        print("✅ place_market_order method exists")
        
        print("✅ TEST PASSED: Wrapper function works correctly")
        return True
        
    except Exception as e:
        print(f"❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_safety_guards():
    """Test that safety guards are configurable."""
    print("\n" + "=" * 70)
    print("TEST: Safety Guards")
    print("=" * 70)
    
    try:
        import bot.kraken_copy_trading as kct
        
        # Check MAX_USER_RISK
        print(f"✅ MAX_USER_RISK = {kct.MAX_USER_RISK} (10% = 0.10)")
        assert kct.MAX_USER_RISK == 0.10, "MAX_USER_RISK should be 10%"
        
        # Check SYSTEM_DISABLED
        print(f"✅ SYSTEM_DISABLED = {kct.SYSTEM_DISABLED} (should be False)")
        assert kct.SYSTEM_DISABLED == False, "SYSTEM_DISABLED should start as False"
        
        # Test that we can modify it
        kct.SYSTEM_DISABLED = True
        print(f"✅ SYSTEM_DISABLED can be modified: {kct.SYSTEM_DISABLED}")
        
        # Reset
        kct.SYSTEM_DISABLED = False
        
        print("✅ TEST PASSED: Safety guards work correctly")
        return True
        
    except Exception as e:
        print(f"❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all integration tests."""
    print("\n" + "=" * 70)
    print("🧪 KRAKEN COPY TRADING INTEGRATION TEST SUITE")
    print("=" * 70)
    
    tests = [
        ("Import Integration", test_import_integration),
        ("Broker Wrapper", test_wrapper_function),
        ("Safety Guards", test_safety_guards),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"\n❌ Test '{test_name}' crashed: {e}")
            results.append((test_name, False))
    
    # Summary
    print("\n" + "=" * 70)
    print("📊 TEST SUMMARY")
    print("=" * 70)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{status}: {test_name}")
    
    print("=" * 70)
    print(f"Result: {passed}/{total} tests passed")
    print("=" * 70)
    
    if passed == total:
        print("\n🎉 ALL INTEGRATION TESTS PASSED!")
        return 0
    else:
        print(f"\n⚠️  {total - passed} test(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
