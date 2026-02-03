"""
Test script for platform broker registration invariant

Tests that platform brokers are:
1. Registered once, globally
2. Marked as immutable after initial registration
3. Protected against duplicate registration
"""

import sys
sys.path.insert(0, '.')

from bot.multi_account_broker_manager import MultiAccountBrokerManager
from bot.broker_manager import BrokerType, BaseBroker, AccountType


class MockBroker(BaseBroker):
    """Mock broker for testing"""

    def __init__(self, broker_type=BrokerType.COINBASE):
        super().__init__(broker_type)
        self.connected = False

    def connect(self):
        self.connected = True
        return True

    def get_account_balance(self):
        return 100.0

    def get_positions(self):
        return []

    def place_market_order(self, symbol, side, quantity, size_type='quote',
                          ignore_balance=False, ignore_min_trade=False, force_liquidate=False):
        return {
            'status': 'filled',
            'order_id': 'test-order-123',
            'symbol': symbol,
            'side': side,
            'quantity': quantity
        }


def test_duplicate_registration_prevention():
    """Test that duplicate platform broker registration is prevented"""
    print("=" * 70)
    print("TEST 1: Duplicate Registration Prevention")
    print("=" * 70)

    manager = MultiAccountBrokerManager()
    
    # Create and register a broker
    broker1 = MockBroker(BrokerType.KRAKEN)
    broker1.connect()
    
    # First registration should succeed
    result = manager.register_platform_broker_instance(BrokerType.KRAKEN, broker1)
    assert result == True, "First registration should succeed"
    print("✅ Test 1a PASSED: First registration successful")
    
    # Second registration of the same broker type should fail
    broker2 = MockBroker(BrokerType.KRAKEN)
    broker2.connect()
    
    try:
        manager.register_platform_broker_instance(BrokerType.KRAKEN, broker2)
        assert False, "Should have raised RuntimeError for duplicate registration"
    except RuntimeError as e:
        assert "already registered" in str(e).lower(), "Error message should mention duplicate"
        assert "INVARIANT VIOLATION" in str(e), "Error should indicate invariant violation"
        print("✅ Test 1b PASSED: Duplicate registration correctly prevented")
        print(f"   Error message: {e}")
    
    print()


def test_immutability_after_lock():
    """Test that platform brokers cannot be added after locking"""
    print("=" * 70)
    print("TEST 2: Immutability After Lock")
    print("=" * 70)

    manager = MultiAccountBrokerManager()
    
    # Register a broker
    broker1 = MockBroker(BrokerType.KRAKEN)
    broker1.connect()
    manager.register_platform_broker_instance(BrokerType.KRAKEN, broker1)
    print("✅ Test 2a: Broker registered before lock")
    
    # Lock platform brokers
    manager._lock_platform_brokers()
    print("✅ Test 2b: Platform brokers locked")
    
    # Attempt to register another broker should fail
    broker2 = MockBroker(BrokerType.OKX)
    broker2.connect()
    
    try:
        manager.register_platform_broker_instance(BrokerType.OKX, broker2)
        assert False, "Should have raised RuntimeError when locked"
    except RuntimeError as e:
        assert "locked" in str(e).lower(), "Error message should mention lock"
        assert "INVARIANT VIOLATION" in str(e), "Error should indicate invariant violation"
        print("✅ Test 2c PASSED: Registration correctly prevented after lock")
        print(f"   Error message: {e}")
    
    print()


def test_read_only_property():
    """Test that platform_brokers property provides read-only access"""
    print("=" * 70)
    print("TEST 3: Read-Only Property Access")
    print("=" * 70)

    manager = MultiAccountBrokerManager()
    
    # Register a broker
    broker1 = MockBroker(BrokerType.KRAKEN)
    broker1.connect()
    manager.register_platform_broker_instance(BrokerType.KRAKEN, broker1)
    
    # Access via property should return a copy
    brokers_copy1 = manager.platform_brokers
    brokers_copy2 = manager.platform_brokers
    
    # Verify it's a copy (different object IDs)
    assert id(brokers_copy1) != id(brokers_copy2), "Property should return a copy each time"
    print("✅ Test 3a PASSED: Property returns copy (not reference)")
    
    # Verify the broker is in the copy
    assert BrokerType.KRAKEN in brokers_copy1, "Copy should contain registered broker"
    assert brokers_copy1[BrokerType.KRAKEN] == broker1, "Copy should have same broker instance"
    print("✅ Test 3b PASSED: Copy contains correct broker data")
    
    # Modifying the copy should not affect internal state
    brokers_copy1[BrokerType.OKX] = MockBroker(BrokerType.OKX)
    
    # Verify internal state unchanged
    assert BrokerType.OKX not in manager.platform_brokers, "Modifying copy should not affect internal state"
    print("✅ Test 3c PASSED: Modifying copy does not affect internal state")
    
    print()


def test_single_registration_globally():
    """Test that each broker type can only be registered once globally"""
    print("=" * 70)
    print("TEST 4: Single Registration Globally")
    print("=" * 70)

    manager = MultiAccountBrokerManager()
    
    # Register multiple different broker types
    broker_types = [BrokerType.KRAKEN, BrokerType.OKX, BrokerType.ALPACA]
    
    for broker_type in broker_types:
        broker = MockBroker(broker_type)
        broker.connect()
        result = manager.register_platform_broker_instance(broker_type, broker)
        assert result == True, f"Registration of {broker_type.value} should succeed"
        print(f"✅ {broker_type.value} registered successfully")
    
    # Verify all are registered
    for broker_type in broker_types:
        broker = manager.get_platform_broker(broker_type)
        assert broker is not None, f"{broker_type.value} should be retrievable"
        assert broker.connected == True, f"{broker_type.value} should be connected"
    
    print("✅ Test 4 PASSED: Multiple different brokers registered globally")
    print()


def test_retrieval_methods():
    """Test broker retrieval methods work correctly"""
    print("=" * 70)
    print("TEST 5: Broker Retrieval Methods")
    print("=" * 70)

    manager = MultiAccountBrokerManager()
    
    # Register a broker
    broker = MockBroker(BrokerType.KRAKEN)
    broker.connect()
    manager.register_platform_broker_instance(BrokerType.KRAKEN, broker)
    
    # Test get_platform_broker
    retrieved = manager.get_platform_broker(BrokerType.KRAKEN)
    assert retrieved is broker, "get_platform_broker should return registered instance"
    print("✅ Test 5a PASSED: get_platform_broker returns correct instance")
    
    # Test is_platform_connected
    assert manager.is_platform_connected(BrokerType.KRAKEN) == True, "Should report connected"
    print("✅ Test 5b PASSED: is_platform_connected reports correct status")
    
    # Test for non-existent broker
    retrieved_none = manager.get_platform_broker(BrokerType.OKX)
    assert retrieved_none is None, "Non-existent broker should return None"
    print("✅ Test 5c PASSED: Non-existent broker returns None")
    
    assert manager.is_platform_connected(BrokerType.OKX) == False, "Non-existent should not be connected"
    print("✅ Test 5d PASSED: Non-existent broker reported as not connected")
    
    print()


def run_all_tests():
    """Run all tests"""
    print("\n" + "=" * 70)
    print("PLATFORM BROKER INVARIANT TESTS")
    print("=" * 70 + "\n")

    try:
        test_duplicate_registration_prevention()
        test_immutability_after_lock()
        test_read_only_property()
        test_single_registration_globally()
        test_retrieval_methods()
        
        print("\n" + "=" * 70)
        print("✅ ALL TESTS PASSED")
        print("=" * 70)
        return True
        
    except AssertionError as e:
        print("\n" + "=" * 70)
        print(f"❌ TEST FAILED: {e}")
        print("=" * 70)
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print("\n" + "=" * 70)
        print(f"❌ UNEXPECTED ERROR: {e}")
        print("=" * 70)
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
