#!/usr/bin/env python3
"""
Test Script: Verify Brokers Operate Independently
==================================================

This script verifies that the fix for independent broker operation works correctly.
It tests that:
1. Multiple brokers can be added without Coinbase taking priority
2. Each broker is treated equally
3. The primary broker is set correctly (first one, not always Coinbase)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'bot'))

from broker_manager import BrokerManager, BrokerType, BaseBroker


class MockBroker(BaseBroker):
    """Mock broker for testing"""
    
    def __init__(self, broker_type: BrokerType):
        super().__init__(broker_type)
        self.connected = True  # Simulate successful connection
    
    def connect(self) -> bool:
        return True
    
    def get_account_balance(self) -> float:
        return 100.0
    
    def get_positions(self):
        return []
    
    def place_market_order(self, symbol: str, side: str, quantity: float, size_type: str = 'quote'):
        return {"status": "success", "symbol": symbol, "side": side, "quantity": quantity}


def test_no_coinbase_priority():
    """Test that Coinbase doesn't automatically become primary"""
    print("\n" + "="*70)
    print("TEST 1: Coinbase Should NOT Auto-Override Primary Broker")
    print("="*70)
    
    manager = BrokerManager()
    
    # Add Kraken first
    kraken = MockBroker(BrokerType.KRAKEN)
    manager.add_broker(kraken)
    
    # Verify Kraken is primary (first broker)
    primary = manager.get_primary_broker()
    assert primary is not None, "Primary broker should be set"
    assert primary.broker_type == BrokerType.KRAKEN, "Kraken should be primary (first broker)"
    print(f"✅ Step 1: Kraken added first and is primary: {primary.broker_type.value}")
    
    # Add Coinbase - it should NOT override Kraken as primary
    coinbase = MockBroker(BrokerType.COINBASE)
    manager.add_broker(coinbase)
    
    # Verify Kraken is STILL primary (not overridden by Coinbase)
    primary = manager.get_primary_broker()
    assert primary is not None, "Primary broker should still be set"
    assert primary.broker_type == BrokerType.KRAKEN, "Kraken should STILL be primary (not overridden by Coinbase)"
    print(f"✅ Step 2: After adding Coinbase, primary is STILL: {primary.broker_type.value}")
    
    # Verify both brokers are in the manager
    assert BrokerType.KRAKEN in manager.brokers, "Kraken should be in brokers"
    assert BrokerType.COINBASE in manager.brokers, "Coinbase should be in brokers"
    print(f"✅ Step 3: Both brokers available: {manager.get_connected_brokers()}")
    
    print("\n✅ TEST 1 PASSED: Coinbase does NOT auto-override primary broker")
    print("="*70)


def test_brokers_independent():
    """Test that each broker operates independently"""
    print("\n" + "="*70)
    print("TEST 2: Each Broker Operates Independently")
    print("="*70)
    
    manager = BrokerManager()
    
    # Add multiple brokers
    okx = MockBroker(BrokerType.OKX)
    binance = MockBroker(BrokerType.BINANCE)
    coinbase = MockBroker(BrokerType.COINBASE)
    
    manager.add_broker(okx)
    manager.add_broker(binance)
    manager.add_broker(coinbase)
    
    # Verify OKX is primary (first added)
    primary = manager.get_primary_broker()
    assert primary.broker_type == BrokerType.OKX, "OKX should be primary (first broker)"
    print(f"✅ Step 1: Primary broker is first added: {primary.broker_type.value}")
    
    # Verify all brokers are accessible
    assert len(manager.brokers) == 3, "All 3 brokers should be in manager"
    print(f"✅ Step 2: All brokers accessible: {manager.get_connected_brokers()}")
    
    # Verify each broker can be accessed independently
    okx_broker = manager.brokers.get(BrokerType.OKX)
    binance_broker = manager.brokers.get(BrokerType.BINANCE)
    coinbase_broker = manager.brokers.get(BrokerType.COINBASE)
    
    assert okx_broker is okx, "OKX broker should be retrievable"
    assert binance_broker is binance, "Binance broker should be retrievable"
    assert coinbase_broker is coinbase, "Coinbase broker should be retrievable"
    print(f"✅ Step 3: Each broker can be accessed independently")
    
    print("\n✅ TEST 2 PASSED: Each broker operates independently")
    print("="*70)


def test_explicit_primary_setting():
    """Test that primary broker can be explicitly set"""
    print("\n" + "="*70)
    print("TEST 3: Primary Broker Can Be Explicitly Set")
    print("="*70)
    
    manager = BrokerManager()
    
    # Add brokers
    kraken = MockBroker(BrokerType.KRAKEN)
    coinbase = MockBroker(BrokerType.COINBASE)
    
    manager.add_broker(kraken)
    manager.add_broker(coinbase)
    
    # Verify Kraken is primary (first added)
    primary = manager.get_primary_broker()
    assert primary.broker_type == BrokerType.KRAKEN, "Kraken should be primary initially"
    print(f"✅ Step 1: Initial primary: {primary.broker_type.value}")
    
    # Explicitly set Coinbase as primary
    result = manager.set_primary_broker(BrokerType.COINBASE)
    assert result is True, "Setting primary should succeed"
    
    # Verify Coinbase is now primary
    primary = manager.get_primary_broker()
    assert primary.broker_type == BrokerType.COINBASE, "Coinbase should be primary after explicit set"
    print(f"✅ Step 2: After explicit set_primary_broker(): {primary.broker_type.value}")
    
    # Set back to Kraken
    manager.set_primary_broker(BrokerType.KRAKEN)
    primary = manager.get_primary_broker()
    assert primary.broker_type == BrokerType.KRAKEN, "Kraken should be primary again"
    print(f"✅ Step 3: After setting back to Kraken: {primary.broker_type.value}")
    
    print("\n✅ TEST 3 PASSED: Primary broker can be explicitly controlled")
    print("="*70)


def main():
    """Run all tests"""
    print("\n" + "="*70)
    print("TESTING INDEPENDENT BROKER OPERATION")
    print("="*70)
    print("\nVerifying that Coinbase no longer controls other brokerages...")
    
    try:
        test_no_coinbase_priority()
        test_brokers_independent()
        test_explicit_primary_setting()
        
        print("\n" + "="*70)
        print("✅ ALL TESTS PASSED")
        print("="*70)
        print("\nBrokers now operate independently!")
        print("- Coinbase does NOT auto-override other brokers")
        print("- Each broker can be accessed independently")
        print("- Primary broker can be explicitly controlled")
        print("- First broker added becomes primary (backward compatible)")
        print("\n" + "="*70)
        
        return 0
    
    except AssertionError as e:
        print(f"\n❌ TEST FAILED: {e}")
        return 1
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
