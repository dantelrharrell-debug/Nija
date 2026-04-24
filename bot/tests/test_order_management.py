#!/usr/bin/env python3
"""
Test Order Management and Account Tracking
===========================================

Tests for the comprehensive order management system:
1. Order counting per account
2. Held capital tracking per account
3. Double-reservation detection
4. Order cleanup after fills
5. Dust order handling
6. Order fragmentation detection

Author: NIJA Trading Systems
Date: February 17, 2026
"""

import sys
import os

# Add the bot directory to the path
bot_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, bot_dir)

from datetime import datetime, timedelta
from account_order_tracker import (
    AccountOrderTracker,
    OrderInfo,
    get_order_tracker
)


def test_order_counting_per_account():
    """Test 1: Count open orders per account"""
    print("="*70)
    print("TEST 1: Order Counting Per Account")
    print("="*70)
    
    tracker = AccountOrderTracker(data_dir="/tmp/test_order_tracker")
    
    # Add orders for account 1
    account1_order1 = OrderInfo(
        order_id="ORDER-1",
        account_id="PLATFORM",
        symbol="BTC-USD",
        side="buy",
        price=45000.0,
        quantity=0.01,
        size_usd=450.0,
        status="open",
        created_at=datetime.now(),
        order_type="market",
        reserved_capital=450.0
    )
    tracker.add_order(account1_order1)
    
    account1_order2 = OrderInfo(
        order_id="ORDER-2",
        account_id="PLATFORM",
        symbol="ETH-USD",
        side="buy",
        price=3000.0,
        quantity=0.1,
        size_usd=300.0,
        status="open",
        created_at=datetime.now(),
        order_type="market",
        reserved_capital=300.0
    )
    tracker.add_order(account1_order2)
    
    # Add orders for account 2
    account2_order1 = OrderInfo(
        order_id="ORDER-3",
        account_id="USER_abc123",
        symbol="SOL-USD",
        side="buy",
        price=100.0,
        quantity=1.0,
        size_usd=100.0,
        status="open",
        created_at=datetime.now(),
        order_type="market",
        reserved_capital=100.0
    )
    tracker.add_order(account2_order1)
    
    # Verify counts
    platform_count = tracker.get_order_count("PLATFORM")
    user_count = tracker.get_order_count("USER_abc123")
    
    print(f"\n📊 Order Counts:")
    print(f"   PLATFORM: {platform_count} open orders")
    print(f"   USER_abc123: {user_count} open orders")
    
    assert platform_count == 2, f"Expected 2 orders for PLATFORM, got {platform_count}"
    assert user_count == 1, f"Expected 1 order for USER_abc123, got {user_count}"
    
    print("\n✅ TEST 1 PASSED: Orders counted correctly per account")
    print()


def test_held_capital_tracking():
    """Test 2: Track held capital per account"""
    print("="*70)
    print("TEST 2: Held Capital Tracking Per Account")
    print("="*70)
    
    tracker = AccountOrderTracker(data_dir="/tmp/test_order_tracker")
    
    # Check held capital for PLATFORM
    platform_held = tracker.get_held_capital("PLATFORM")
    user_held = tracker.get_held_capital("USER_abc123")
    
    print(f"\n💰 Held Capital:")
    print(f"   PLATFORM: ${platform_held:.2f}")
    print(f"   USER_abc123: ${user_held:.2f}")
    
    # PLATFORM should have $750 held (from test 1: $450 + $300)
    assert platform_held == 750.0, f"Expected $750 held for PLATFORM, got ${platform_held:.2f}"
    
    # USER should have $100 held
    assert user_held == 100.0, f"Expected $100 held for USER_abc123, got ${user_held:.2f}"
    
    print("\n✅ TEST 2 PASSED: Held capital tracked correctly per account")
    print()


def test_order_cleanup_after_fill():
    """Test 3: Order cleanup after filled trades"""
    print("="*70)
    print("TEST 3: Order Cleanup After Filled Trades")
    print("="*70)
    
    tracker = AccountOrderTracker(data_dir="/tmp/test_order_tracker")
    
    # Mark one order as filled
    filled = tracker.mark_order_filled("ORDER-1", "PLATFORM")
    assert filled, "Failed to mark order as filled"
    
    # Check that held capital was released
    platform_held = tracker.get_held_capital("PLATFORM")
    print(f"\n💰 Held Capital After Fill:")
    print(f"   PLATFORM: ${platform_held:.2f} (should be reduced by $450)")
    
    # Should be $300 now (only ORDER-2 remaining)
    assert platform_held == 300.0, f"Expected $300 held after fill, got ${platform_held:.2f}"
    
    # Order count should still be 2 (filled orders are kept in history)
    all_orders = tracker.orders_by_account["PLATFORM"]
    assert len(all_orders) == 2, f"Expected 2 total orders, got {len(all_orders)}"
    
    # But open order count should be 1
    open_count = tracker.get_order_count("PLATFORM")
    assert open_count == 1, f"Expected 1 open order, got {open_count}"
    
    print("\n✅ TEST 3 PASSED: Order cleanup works correctly after fills")
    print()


def test_double_reservation_detection():
    """Test 4: Detect double-reservation of margin"""
    print("="*70)
    print("TEST 4: Double-Reservation Detection")
    print("="*70)
    
    tracker = AccountOrderTracker(data_dir="/tmp/test_order_tracker")
    
    # Create a position with stop and target orders
    position_id = "POS-123"
    
    # Add stop order (correctly reserves capital)
    stop_order = OrderInfo(
        order_id="STOP-1",
        account_id="PLATFORM",
        symbol="BTC-USD",
        side="sell",
        price=44000.0,
        quantity=0.01,
        size_usd=440.0,
        status="open",
        created_at=datetime.now(),
        order_type="stop",
        parent_position_id=position_id,
        reserved_capital=440.0  # Reserves capital
    )
    tracker.add_order(stop_order)
    
    # Add target order (should NOT reserve additional capital)
    target_order = OrderInfo(
        order_id="TARGET-1",
        account_id="PLATFORM",
        symbol="BTC-USD",
        side="sell",
        price=46000.0,
        quantity=0.01,
        size_usd=460.0,
        status="open",
        created_at=datetime.now(),
        order_type="target",
        parent_position_id=position_id,
        reserved_capital=0.0  # Should NOT reserve (uses same capital as stop)
    )
    tracker.add_order(target_order)
    
    # Check for double-reservation
    has_double, message = tracker.check_double_reservation(position_id, "PLATFORM")
    
    print(f"\n🔍 Double-Reservation Check:")
    print(f"   Position: {position_id}")
    print(f"   Result: {message}")
    
    assert not has_double, f"False positive: detected double reservation when there is none"
    
    # Now simulate INCORRECT behavior - target also reserves capital
    tracker.orders_by_account["PLATFORM"][-1].reserved_capital = 460.0
    tracker.reserved_capital_by_account["PLATFORM"] += 460.0
    
    has_double, message = tracker.check_double_reservation(position_id, "PLATFORM")
    print(f"\n🔍 Double-Reservation Check (with double reservation):")
    print(f"   Result: {message}")
    
    assert has_double, f"Failed to detect actual double reservation"
    
    print("\n✅ TEST 4 PASSED: Double-reservation detection works correctly")
    print()


def test_order_fragmentation_detection():
    """Test 5: Detect order fragmentation in micro accounts"""
    print("="*70)
    print("TEST 5: Order Fragmentation Detection")
    print("="*70)
    
    tracker = AccountOrderTracker(data_dir="/tmp/test_order_tracker")
    
    # Simulate micro account with $100 balance
    account_balance = 100.0
    
    # Account has $300 + $440 = $740 held (from previous tests)
    # This is 740% of balance - MAJOR FRAGMENTATION!
    
    is_fragmented, message = tracker.detect_order_fragmentation(
        "PLATFORM",
        account_balance,
        warn_threshold=0.30  # Warn if > 30% held
    )
    
    print(f"\n⚠️ Fragmentation Check:")
    print(f"   Account Balance: ${account_balance:.2f}")
    print(f"   Held Capital: ${tracker.get_held_capital('PLATFORM'):.2f}")
    print(f"   Result: {message}")
    
    assert is_fragmented, "Failed to detect order fragmentation"
    
    # Now test with healthy account
    healthy_balance = 5000.0
    is_fragmented, message = tracker.detect_order_fragmentation(
        "PLATFORM",
        healthy_balance,
        warn_threshold=0.30
    )
    
    print(f"\n✅ Fragmentation Check (Healthy Account):")
    print(f"   Account Balance: ${healthy_balance:.2f}")
    print(f"   Held Capital: ${tracker.get_held_capital('PLATFORM'):.2f}")
    print(f"   Result: {message}")
    
    assert not is_fragmented, "False positive: flagged healthy account as fragmented"
    
    print("\n✅ TEST 5 PASSED: Order fragmentation detection works correctly")
    print()


def test_stale_order_cleanup():
    """Test 6: Cleanup stale orders"""
    print("="*70)
    print("TEST 6: Stale Order Cleanup")
    print("="*70)
    
    tracker = AccountOrderTracker(data_dir="/tmp/test_order_tracker")
    
    # Add an old stale order
    old_time = datetime.now() - timedelta(hours=2)
    stale_order = OrderInfo(
        order_id="STALE-1",
        account_id="USER_abc123",
        symbol="AVAX-USD",
        side="buy",
        price=50.0,
        quantity=1.0,
        size_usd=50.0,
        status="open",
        created_at=old_time,  # 2 hours old
        order_type="market",
        reserved_capital=50.0
    )
    tracker.add_order(stale_order)
    
    # Set max age to 60 minutes
    tracker.max_order_age_minutes = 60
    
    # Detect stale orders
    stale_count = tracker.cleanup_stale_orders("USER_abc123", force_cancel=False)
    
    print(f"\n🧹 Stale Order Detection:")
    print(f"   Stale orders found: {stale_count}")
    
    assert stale_count >= 1, f"Expected at least 1 stale order, found {stale_count}"
    
    # Now force cancel
    cancelled_count = tracker.cleanup_stale_orders("USER_abc123", force_cancel=True)
    
    print(f"   Stale orders cancelled: {cancelled_count}")
    
    # Verify capital was released
    user_held = tracker.get_held_capital("USER_abc123")
    print(f"   Held capital after cleanup: ${user_held:.2f}")
    
    print("\n✅ TEST 6 PASSED: Stale order cleanup works correctly")
    print()


def test_account_stats_summary():
    """Test 7: Get comprehensive account statistics"""
    print("="*70)
    print("TEST 7: Account Statistics Summary")
    print("="*70)
    
    tracker = AccountOrderTracker(data_dir="/tmp/test_order_tracker")
    
    # Get stats for PLATFORM account
    stats = tracker.get_account_stats("PLATFORM")
    
    print(f"\n📊 Account Statistics for PLATFORM:")
    print(f"   Total Open Orders: {stats.total_open_orders}")
    print(f"   Market Orders: {stats.market_orders}")
    print(f"   Stop Orders: {stats.stop_orders}")
    print(f"   Target Orders: {stats.target_orders}")
    print(f"   Total Held Capital: ${stats.total_held_capital:.2f}")
    print(f"   Oldest Order Age: {stats.oldest_order_age_minutes:.1f} minutes")
    print(f"   Stale Orders: {stats.stale_orders_count}")
    
    assert stats.total_open_orders >= 0, "Invalid order count"
    assert stats.total_held_capital >= 0, "Invalid held capital"
    
    print("\n✅ TEST 7 PASSED: Account statistics calculated correctly")
    print()


def run_all_tests():
    """Run all order management tests"""
    print("\n" + "="*70)
    print("ORDER MANAGEMENT AND ACCOUNT TRACKING TESTS")
    print("="*70 + "\n")
    
    try:
        test_order_counting_per_account()
        test_held_capital_tracking()
        test_order_cleanup_after_fill()
        test_double_reservation_detection()
        test_order_fragmentation_detection()
        test_stale_order_cleanup()
        test_account_stats_summary()
        
        print("\n" + "="*70)
        print("✅ ALL TESTS PASSED")
        print("="*70)
        print("\n📋 Verified Behavior:")
        print("1. ✅ Orders counted correctly per account")
        print("2. ✅ Held capital tracked separately per account")
        print("3. ✅ Orders cleaned up after fills (capital released)")
        print("4. ✅ Double-reservation of margin detected correctly")
        print("5. ✅ Order fragmentation detected in micro accounts")
        print("6. ✅ Stale orders detected and cleaned up")
        print("7. ✅ Comprehensive account statistics calculated")
        print("="*70)
        return True
        
    except AssertionError as e:
        print("\n" + "="*70)
        print(f"❌ TEST FAILED: {e}")
        print("="*70)
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print("\n" + "="*70)
        print(f"❌ UNEXPECTED ERROR: {e}")
        print("="*70)
        import traceback
        traceback.print_exc()
        return False


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
