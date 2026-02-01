"""
Test script for broker-aware entry gating

Tests the new broker selection and eligibility checking:
1. Broker eligibility based on EXIT_ONLY mode
2. Broker eligibility based on balance minimums
3. Broker priority selection
4. Coinbase auto-downgrade when balance < $25
"""

import sys
sys.path.insert(0, '.')

from bot.broker_manager import BaseBroker, BrokerType, AccountType
from bot.trading_strategy import TradingStrategy, ENTRY_BROKER_PRIORITY, BROKER_MIN_BALANCE


class MockBroker(BaseBroker):
    """Mock broker for testing"""

    def __init__(self, broker_type: BrokerType, balance: float = 100.0, exit_only: bool = False):
        super().__init__(broker_type, AccountType.PLATFORM)
        self.balance = balance
        self.connected = True
        self.exit_only_mode = exit_only

    def connect(self):
        return True

    def get_account_balance(self):
        return self.balance

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


def test_broker_eligibility():
    """Test broker eligibility checking"""
    print("=" * 70)
    print("TEST 1: Broker Eligibility Checking")
    print("=" * 70)

    strategy = TradingStrategy()

    # Test 1a: Eligible broker (connected, not EXIT_ONLY, sufficient balance)
    broker = MockBroker(BrokerType.KRAKEN, balance=50.0, exit_only=False)
    is_eligible, reason = strategy._is_broker_eligible_for_entry(broker)
    print(f"✓ Test 1a: Eligible broker - {is_eligible}, Reason: {reason}")
    assert is_eligible == True, f"Should be eligible: {reason}"

    # Test 1b: Ineligible due to EXIT_ONLY mode
    broker = MockBroker(BrokerType.COINBASE, balance=50.0, exit_only=True)
    is_eligible, reason = strategy._is_broker_eligible_for_entry(broker)
    print(f"✓ Test 1b: EXIT_ONLY mode - {is_eligible}, Reason: {reason}")
    assert is_eligible == False, "Should be ineligible due to EXIT_ONLY mode"
    assert "EXIT-ONLY" in reason, f"Reason should mention EXIT-ONLY: {reason}"

    # Test 1c: Ineligible due to insufficient balance
    broker = MockBroker(BrokerType.COINBASE, balance=10.0, exit_only=False)
    is_eligible, reason = strategy._is_broker_eligible_for_entry(broker)
    print(f"✓ Test 1c: Insufficient balance - {is_eligible}, Reason: {reason}")
    assert is_eligible == False, "Should be ineligible due to insufficient balance"
    assert "minimum" in reason.lower(), f"Reason should mention minimum: {reason}"

    # Test 1d: Not connected
    broker = MockBroker(BrokerType.KRAKEN, balance=50.0, exit_only=False)
    broker.connected = False
    is_eligible, reason = strategy._is_broker_eligible_for_entry(broker)
    print(f"✓ Test 1d: Not connected - {is_eligible}, Reason: {reason}")
    assert is_eligible == False, "Should be ineligible if not connected"
    assert "not connected" in reason.lower(), f"Reason should mention not connected: {reason}"

    print("✅ All eligibility tests passed!")
    print()


def test_broker_priority_selection():
    """Test broker selection based on priority"""
    print("=" * 70)
    print("TEST 2: Broker Priority Selection")
    print("=" * 70)

    strategy = TradingStrategy()

    # Test 2a: KRAKEN should be selected first (highest priority)
    all_brokers = {
        BrokerType.KRAKEN: MockBroker(BrokerType.KRAKEN, balance=50.0, exit_only=False),
        BrokerType.COINBASE: MockBroker(BrokerType.COINBASE, balance=50.0, exit_only=False),
        BrokerType.BINANCE: MockBroker(BrokerType.BINANCE, balance=50.0, exit_only=False),
    }

    broker, name, status = strategy._select_entry_broker(all_brokers)
    print(f"✓ Test 2a: Multiple eligible brokers - Selected: {name}")
    assert broker.broker_type == BrokerType.KRAKEN, "Should select KRAKEN (highest priority)"
    assert name == "kraken", f"Name should be 'kraken', got: {name}"

    # Test 2b: If KRAKEN is EXIT_ONLY, should select next priority (OKX or BINANCE)
    all_brokers = {
        BrokerType.KRAKEN: MockBroker(BrokerType.KRAKEN, balance=50.0, exit_only=True),
        BrokerType.BINANCE: MockBroker(BrokerType.BINANCE, balance=50.0, exit_only=False),
        BrokerType.COINBASE: MockBroker(BrokerType.COINBASE, balance=50.0, exit_only=False),
    }

    broker, name, status = strategy._select_entry_broker(all_brokers)
    print(f"✓ Test 2b: KRAKEN EXIT_ONLY - Selected: {name}")
    assert broker.broker_type == BrokerType.BINANCE, "Should skip KRAKEN and select BINANCE"
    assert name == "binance", f"Name should be 'binance', got: {name}"

    # Test 2c: COINBASE should be last priority
    all_brokers = {
        BrokerType.KRAKEN: MockBroker(BrokerType.KRAKEN, balance=10.0, exit_only=False),  # Below minimum
        BrokerType.BINANCE: MockBroker(BrokerType.BINANCE, balance=5.0, exit_only=False),  # Below minimum
        BrokerType.COINBASE: MockBroker(BrokerType.COINBASE, balance=50.0, exit_only=False),
    }

    broker, name, status = strategy._select_entry_broker(all_brokers)
    print(f"✓ Test 2c: COINBASE as fallback - Selected: {name}")
    assert broker.broker_type == BrokerType.COINBASE, "Should select COINBASE when others are ineligible"

    # Test 2d: No eligible broker
    all_brokers = {
        BrokerType.KRAKEN: MockBroker(BrokerType.KRAKEN, balance=10.0, exit_only=False),  # Below minimum
        BrokerType.COINBASE: MockBroker(BrokerType.COINBASE, balance=10.0, exit_only=False),  # Below minimum
    }

    broker, name, status = strategy._select_entry_broker(all_brokers)
    print(f"✓ Test 2d: No eligible broker - Selected: {name}")
    assert broker is None, "Should return None when no eligible broker"
    assert name is None, "Should return None for name when no eligible broker"

    print("✅ All priority selection tests passed!")
    print()


def test_coinbase_auto_downgrade():
    """Test that Coinbase is automatically downgraded if balance < $25"""
    print("=" * 70)
    print("TEST 3: Coinbase Auto-Downgrade")
    print("=" * 70)

    strategy = TradingStrategy()

    # Test 3a: Coinbase with balance < $25 should not be eligible
    broker = MockBroker(BrokerType.COINBASE, balance=20.0, exit_only=False)
    is_eligible, reason = strategy._is_broker_eligible_for_entry(broker)
    print(f"✓ Test 3a: Coinbase balance $20 - {is_eligible}, Reason: {reason}")
    assert is_eligible == False, "Coinbase should be ineligible with balance < $25"
    assert "$25" in reason or "25.0" in reason, f"Reason should mention $25 minimum: {reason}"

    # Test 3b: Coinbase with balance >= $25 should be eligible
    broker = MockBroker(BrokerType.COINBASE, balance=30.0, exit_only=False)
    is_eligible, reason = strategy._is_broker_eligible_for_entry(broker)
    print(f"✓ Test 3b: Coinbase balance $30 - {is_eligible}, Reason: {reason}")
    assert is_eligible == True, f"Coinbase should be eligible with balance >= $25: {reason}"

    # Test 3c: When Coinbase has $20 but Kraken has $50, Kraken should be selected
    all_brokers = {
        BrokerType.KRAKEN: MockBroker(BrokerType.KRAKEN, balance=50.0, exit_only=False),
        BrokerType.COINBASE: MockBroker(BrokerType.COINBASE, balance=20.0, exit_only=False),
    }

    broker, name, status = strategy._select_entry_broker(all_brokers)
    print(f"✓ Test 3c: Kraken $50 vs Coinbase $20 - Selected: {name}")
    assert broker.broker_type == BrokerType.KRAKEN, "Should select KRAKEN over underfunded COINBASE"

    print("✅ All Coinbase auto-downgrade tests passed!")
    print()


if __name__ == "__main__":
    try:
        test_broker_eligibility()
        test_broker_priority_selection()
        test_coinbase_auto_downgrade()

        print("=" * 70)
        print("✅ ALL TESTS PASSED!")
        print("=" * 70)
    except Exception as e:
        print(f"❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
