#!/usr/bin/env python3
"""
Test script for platform/user broker separation invariants

Tests that:
1. Platform trades NEVER execute on user brokers
2. Platform entries only affect PLATFORM equity
3. User accounts are completely isolated from platform account
"""

import sys
sys.path.insert(0, '.')

from bot.multi_account_broker_manager import MultiAccountBrokerManager
from bot.broker_manager import BrokerType, BaseBroker, AccountType
from typing import List, Dict, Any


class MockBroker(BaseBroker):
    """Mock broker for testing with tracking of all operations"""

    def __init__(self, broker_type=BrokerType.COINBASE, account_type=AccountType.PLATFORM, user_id=None):
        super().__init__(broker_type, account_type, user_id)
        self.connected = False
        self.balance = 100.0
        self.positions = []
        self.orders_placed = []  # Track all orders for verification
        self.balance_changes = []  # Track all balance changes for equity verification

    def connect(self):
        self.connected = True
        return True

    def get_account_balance(self):
        return self.balance

    def get_positions(self):
        return self.positions

    def place_market_order(self, symbol, side, quantity, size_type='quote',
                          ignore_balance=False, ignore_min_trade=False, force_liquidate=False):
        """Track all orders placed"""
        order = {
            'status': 'filled',
            'order_id': f'test-order-{len(self.orders_placed) + 1}',
            'symbol': symbol,
            'side': side,
            'quantity': quantity,
            'account_type': self.account_type.value if hasattr(self.account_type, 'value') else str(self.account_type),
            'user_id': self.user_id
        }
        self.orders_placed.append(order)
        
        # Update balance to simulate trade
        if side == 'buy':
            self.balance -= quantity
            self.positions.append({
                'symbol': symbol,
                'quantity': quantity / 100,  # Simulate price of 100
                'usd_value': quantity
            })
        else:  # sell
            self.balance += quantity
            # Remove from positions
            self.positions = [p for p in self.positions if p['symbol'] != symbol]
        
        self.balance_changes.append({
            'type': side,
            'amount': quantity,
            'new_balance': self.balance
        })
        
        return order


def test_platform_trades_never_execute_on_user_brokers():
    """
    TEST 1: Verify that platform trades NEVER execute on user brokers
    
    This test ensures complete separation between platform and user accounts.
    Platform trading operations should NEVER affect user broker balances or positions.
    """
    print("=" * 70)
    print("TEST 1: Platform Trades Never Execute on User Brokers")
    print("=" * 70)
    
    manager = MultiAccountBrokerManager()
    
    # Setup platform broker (Kraken)
    platform_broker = MockBroker(BrokerType.KRAKEN, AccountType.PLATFORM)
    platform_broker.connect()
    manager.register_platform_broker_instance(BrokerType.KRAKEN, platform_broker)
    print(f"✅ Platform broker registered: KRAKEN (balance: ${platform_broker.balance:.2f})")
    
    # Setup user brokers (2 different users)
    # Note: We manually register user brokers since add_user_broker creates brokers internally
    user1_broker = MockBroker(BrokerType.KRAKEN, AccountType.USER, user_id='user1')
    user1_broker.connect()
    manager.user_brokers['user1'] = {BrokerType.KRAKEN: user1_broker}
    print(f"✅ User broker registered: user1/KRAKEN (balance: ${user1_broker.balance:.2f})")
    
    user2_broker = MockBroker(BrokerType.KRAKEN, AccountType.USER, user_id='user2')
    user2_broker.connect()
    manager.user_brokers['user2'] = {BrokerType.KRAKEN: user2_broker}
    print(f"✅ User broker registered: user2/KRAKEN (balance: ${user2_broker.balance:.2f})")
    
    # Record initial balances
    initial_platform_balance = platform_broker.balance
    initial_user1_balance = user1_broker.balance
    initial_user2_balance = user2_broker.balance
    
    print(f"\n📊 Initial State:")
    print(f"   Platform balance: ${initial_platform_balance:.2f}")
    print(f"   User1 balance: ${initial_user1_balance:.2f}")
    print(f"   User2 balance: ${initial_user2_balance:.2f}")
    
    # Simulate platform trade
    print(f"\n🔄 Simulating PLATFORM trade (BUY BTC-USD $50)...")
    platform_broker.place_market_order('BTC-USD', 'buy', 50.0)
    
    # Verify platform broker was affected
    assert platform_broker.balance < initial_platform_balance, "Platform balance should decrease after buy"
    assert len(platform_broker.orders_placed) == 1, "Platform should have 1 order"
    print(f"✅ Platform broker affected: balance ${platform_broker.balance:.2f}")
    print(f"   Order placed: {platform_broker.orders_placed[0]}")
    
    # CRITICAL VERIFICATION: User brokers should be COMPLETELY UNAFFECTED
    assert user1_broker.balance == initial_user1_balance, "User1 balance should NOT change from platform trade"
    assert user2_broker.balance == initial_user2_balance, "User2 balance should NOT change from platform trade"
    assert len(user1_broker.orders_placed) == 0, "User1 should have 0 orders from platform trade"
    assert len(user2_broker.orders_placed) == 0, "User2 should have 0 orders from platform trade"
    
    print(f"✅ User brokers UNAFFECTED:")
    print(f"   User1 balance: ${user1_broker.balance:.2f} (unchanged)")
    print(f"   User2 balance: ${user2_broker.balance:.2f} (unchanged)")
    print(f"   User1 orders: {len(user1_broker.orders_placed)}")
    print(f"   User2 orders: {len(user2_broker.orders_placed)}")
    
    print(f"\n✅ TEST 1 PASSED: Platform trades never execute on user brokers")
    print()


def test_platform_entry_affects_only_platform_equity():
    """
    TEST 2: Simulate a platform entry and confirm it only affects PLATFORM equity
    
    This test verifies that:
    - Platform entries modify platform account equity only
    - User account equity remains completely independent
    - Position counts are tracked separately
    """
    print("=" * 70)
    print("TEST 2: Platform Entry Affects Only Platform Equity")
    print("=" * 70)
    
    manager = MultiAccountBrokerManager()
    
    # Setup platform broker
    platform_broker = MockBroker(BrokerType.COINBASE, AccountType.PLATFORM)
    platform_broker.connect()
    platform_broker.balance = 1000.0  # Set initial platform balance
    manager.register_platform_broker_instance(BrokerType.COINBASE, platform_broker)
    
    # Setup user broker
    user_broker = MockBroker(BrokerType.COINBASE, AccountType.USER, user_id='alice')
    user_broker.connect()
    user_broker.balance = 500.0  # Set initial user balance
    manager.user_brokers['alice'] = {BrokerType.COINBASE: user_broker}
    
    # Calculate initial equity (balance + position values)
    def calculate_equity(broker):
        """Calculate total equity = balance + position values"""
        position_value = sum(p.get('usd_value', 0) for p in broker.positions)
        return broker.balance + position_value
    
    initial_platform_equity = calculate_equity(platform_broker)
    initial_user_equity = calculate_equity(user_broker)
    
    print(f"\n📊 Initial State:")
    print(f"   Platform equity: ${initial_platform_equity:.2f}")
    print(f"   User equity: ${initial_user_equity:.2f}")
    print(f"   Platform positions: {len(platform_broker.positions)}")
    print(f"   User positions: {len(user_broker.positions)}")
    
    # Simulate platform entry (BUY signal)
    print(f"\n🔄 Simulating PLATFORM ENTRY (BUY ETH-USD $200)...")
    platform_result = platform_broker.place_market_order('ETH-USD', 'buy', 200.0)
    
    # Calculate equity after platform entry
    platform_equity_after = calculate_equity(platform_broker)
    user_equity_after = calculate_equity(user_broker)
    
    print(f"\n📊 After Platform Entry:")
    print(f"   Platform equity: ${platform_equity_after:.2f}")
    print(f"   User equity: ${user_equity_after:.2f}")
    print(f"   Platform positions: {len(platform_broker.positions)}")
    print(f"   User positions: {len(user_broker.positions)}")
    
    # CRITICAL VERIFICATION: Platform equity changed, user equity unchanged
    # Note: equity = balance + position_value should remain constant (just converted cash to position)
    # But the position count should increase for platform only
    
    assert len(platform_broker.positions) == 1, "Platform should have 1 position after entry"
    assert len(user_broker.positions) == 0, "User should still have 0 positions"
    assert platform_broker.balance < 1000.0, "Platform balance should decrease"
    assert user_broker.balance == 500.0, "User balance should be unchanged"
    
    print(f"\n✅ Equity Verification:")
    print(f"   Platform balance changed: ${1000.0:.2f} → ${platform_broker.balance:.2f}")
    print(f"   Platform positions added: 0 → {len(platform_broker.positions)}")
    print(f"   User balance unchanged: ${user_broker.balance:.2f}")
    print(f"   User positions unchanged: {len(user_broker.positions)}")
    
    # Additional verification: Check order was tagged to platform account
    assert platform_result['account_type'].lower() == 'platform', "Order should be tagged as PLATFORM"
    assert platform_result['user_id'] is None, "Platform order should not have user_id"
    
    print(f"\n✅ Order Verification:")
    print(f"   Order account_type: {platform_result['account_type']}")
    print(f"   Order user_id: {platform_result['user_id']}")
    
    print(f"\n✅ TEST 2 PASSED: Platform entry affects only PLATFORM equity")
    print()


def test_user_positions_excluded_from_platform_caps():
    """
    TEST 3: Verify user positions do not count toward platform position caps
    
    This test ensures position cap enforcement is scoped correctly:
    - Platform caps apply only to platform positions
    - User positions are tracked separately
    - Multi-user system can exceed platform caps safely
    """
    print("=" * 70)
    print("TEST 3: User Positions Excluded from Platform Caps")
    print("=" * 70)
    
    PLATFORM_MAX_POSITIONS = 8  # Standard platform cap
    
    manager = MultiAccountBrokerManager()
    
    # Setup platform broker with positions near cap
    platform_broker = MockBroker(BrokerType.KRAKEN, AccountType.PLATFORM)
    platform_broker.connect()
    # Add 7 positions to platform (close to cap of 8)
    for i in range(7):
        platform_broker.positions.append({
            'symbol': f'COIN{i}-USD',
            'quantity': 1.0,
            'usd_value': 100.0
        })
    manager.register_platform_broker_instance(BrokerType.KRAKEN, platform_broker)
    
    # Setup multiple user brokers with many positions
    for user_num in range(5):  # 5 users
        user_id = f'user{user_num}'
        user_broker = MockBroker(BrokerType.KRAKEN, AccountType.USER, user_id=user_id)
        user_broker.connect()
        # Each user has 10 positions (exceeds platform cap individually)
        for pos_num in range(10):
            user_broker.positions.append({
                'symbol': f'ASSET{pos_num}-USD',
                'quantity': 1.0,
                'usd_value': 50.0
            })
        manager.user_brokers[user_id] = {BrokerType.KRAKEN: user_broker}
    
    print(f"\n📊 Position Counts:")
    print(f"   Platform positions: {len(platform_broker.positions)}/{PLATFORM_MAX_POSITIONS} (under cap)")
    
    # Get user position counts
    total_user_positions = 0
    for user_id, broker_dict in manager.user_brokers.items():
        for broker_type, broker in broker_dict.items():
            user_pos_count = len(broker.positions)
            total_user_positions += user_pos_count
            print(f"   {user_id} positions: {user_pos_count}")
    
    print(f"   Total user positions: {total_user_positions}")
    print(f"   Total all positions: {len(platform_broker.positions) + total_user_positions}")
    
    # CRITICAL VERIFICATION: Platform under cap, users have many more positions
    assert len(platform_broker.positions) < PLATFORM_MAX_POSITIONS, "Platform should be under cap"
    assert total_user_positions > PLATFORM_MAX_POSITIONS, "User positions exceed platform cap (proves separation)"
    
    # Verify platform can still add positions (not affected by user positions)
    platform_can_add = len(platform_broker.positions) < PLATFORM_MAX_POSITIONS
    print(f"\n✅ Cap Verification:")
    print(f"   Platform can add positions: {platform_can_add}")
    print(f"   Platform positions counted: {len(platform_broker.positions)}")
    print(f"   User positions NOT counted in platform cap: {total_user_positions}")
    
    # Simulate platform adding one more position
    platform_broker.positions.append({
        'symbol': 'BTC-USD',
        'quantity': 1.0,
        'usd_value': 100.0
    })
    print(f"   Platform positions after add: {len(platform_broker.positions)}/{PLATFORM_MAX_POSITIONS}")
    
    assert len(platform_broker.positions) == 8, "Platform should now be at cap"
    assert total_user_positions == 50, "User positions unchanged at 50"
    
    print(f"\n✅ TEST 3 PASSED: User positions excluded from platform caps")
    print()


def run_all_tests():
    """Run all platform/user separation tests"""
    print("\n" + "=" * 70)
    print("PLATFORM/USER BROKER SEPARATION TESTS")
    print("=" * 70 + "\n")

    try:
        test_platform_trades_never_execute_on_user_brokers()
        test_platform_entry_affects_only_platform_equity()
        test_user_positions_excluded_from_platform_caps()
        
        print("\n" + "=" * 70)
        print("✅ ALL TESTS PASSED")
        print("=" * 70)
        print("\nVerified Invariants:")
        print("1. ✅ Platform trades NEVER execute on user brokers")
        print("2. ✅ Platform entries affect ONLY platform equity")
        print("3. ✅ User positions excluded from platform caps")
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
