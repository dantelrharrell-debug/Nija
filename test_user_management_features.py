#!/usr/bin/env python3
"""
Test script for the new user management features.

Tests:
- User nonce management
- User PnL tracking
- User risk management
- Trade webhook notifications
- Dashboard API (optional)
"""

import sys
import os

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.user_nonce_manager import get_user_nonce_manager
from bot.user_pnl_tracker import get_user_pnl_tracker
from bot.user_risk_manager import get_user_risk_manager
from bot.trade_webhook_notifier import get_webhook_notifier
from controls import get_hard_controls


def test_nonce_manager():
    """Test user nonce management."""
    print("\n" + "="*70)
    print("Testing User Nonce Manager")
    print("="*70)
    
    manager = get_user_nonce_manager()
    
    # Test nonce generation
    user_id = "test_user_1"
    nonce1 = manager.get_nonce(user_id)
    print(f"✅ Generated nonce for {user_id}: {nonce1}")
    
    # Test monotonic increase
    nonce2 = manager.get_nonce(user_id)
    assert nonce2 > nonce1, "Nonce should be monotonically increasing"
    print(f"✅ Second nonce is higher: {nonce2}")
    
    # Test error recording
    manager.record_nonce_error(user_id)
    manager.record_nonce_error(user_id)
    print(f"✅ Recorded nonce errors")
    
    # Test stats
    stats = manager.get_stats(user_id)
    print(f"✅ Nonce stats: {stats}")
    
    print("✅ User Nonce Manager: PASSED\n")


def test_pnl_tracker():
    """Test user PnL tracking."""
    print("\n" + "="*70)
    print("Testing User PnL Tracker")
    print("="*70)
    
    tracker = get_user_pnl_tracker()
    
    user_id = "test_user_2"
    
    # Record entry
    tracker.record_trade(
        user_id=user_id,
        symbol="BTC-USD",
        side="buy",
        quantity=0.001,
        price=50000.0,
        size_usd=50.0,
        strategy="APEX_v7.1",
        broker="coinbase"
    )
    print(f"✅ Recorded entry trade for {user_id}")
    
    # Record exit with profit
    tracker.record_trade(
        user_id=user_id,
        symbol="BTC-USD",
        side="sell",
        quantity=0.001,
        price=51000.0,
        size_usd=51.0,
        pnl_usd=1.0,
        pnl_pct=2.0,
        strategy="APEX_v7.1",
        broker="coinbase"
    )
    print(f"✅ Recorded exit trade with profit for {user_id}")
    
    # Get stats
    stats = tracker.get_stats(user_id)
    print(f"✅ PnL stats: Total PnL=${stats['total_pnl']:.2f}, Win Rate={stats['win_rate']:.1f}%")
    
    # Get recent trades
    recent = tracker.get_recent_trades(user_id, limit=5)
    print(f"✅ Recent trades: {len(recent)} trades")
    
    print("✅ User PnL Tracker: PASSED\n")


def test_risk_manager():
    """Test user risk management."""
    print("\n" + "="*70)
    print("Testing User Risk Manager")
    print("="*70)
    
    manager = get_user_risk_manager()
    
    user_id = "test_user_3"
    
    # Update balance
    manager.update_balance(user_id, 1000.0)
    print(f"✅ Set balance for {user_id}: $1000")
    
    # Check if can trade
    can_trade, reason = manager.can_trade(user_id, 50.0)
    print(f"✅ Can trade check: {can_trade} ({reason})")
    
    # Record winning trade
    manager.record_trade(user_id, 5.0)
    print(f"✅ Recorded winning trade: +$5")
    
    # Record losing trade
    manager.record_trade(user_id, -10.0)
    print(f"✅ Recorded losing trade: -$10")
    
    # Get state
    state = manager.get_state(user_id)
    print(f"✅ Risk state: Daily PnL=${state.daily_pnl:.2f}, Trades={state.daily_trades}")
    
    # Get limits
    limits = manager.get_limits(user_id)
    print(f"✅ Risk limits: Max position={limits.max_position_pct*100:.0f}%, Max daily loss=${limits.max_daily_loss_usd}")
    
    print("✅ User Risk Manager: PASSED\n")


def test_webhook_notifier():
    """Test webhook notifications."""
    print("\n" + "="*70)
    print("Testing Trade Webhook Notifier")
    print("="*70)
    
    notifier = get_webhook_notifier()
    
    user_id = "test_user_4"
    
    # Configure webhook (using a test URL - won't actually send)
    notifier.configure_webhook(
        user_id=user_id,
        webhook_url="https://httpbin.org/post",
        enabled=False  # Disabled for testing
    )
    print(f"✅ Configured webhook for {user_id}")
    
    # Get config
    config = notifier.get_config(user_id)
    print(f"✅ Webhook config: URL={config.webhook_url}, Enabled={config.enabled}")
    
    # Test notification (won't send since disabled)
    notifier.notify_trade_entry(
        user_id=user_id,
        symbol="ETH-USD",
        side="buy",
        quantity=0.1,
        price=3000.0,
        size_usd=300.0
    )
    print(f"✅ Sent entry notification (webhook disabled)")
    
    # Get stats
    stats = notifier.get_stats()
    print(f"✅ Webhook stats: {stats}")
    
    print("✅ Trade Webhook Notifier: PASSED\n")


def test_hard_controls():
    """Test hard controls integration."""
    print("\n" + "="*70)
    print("Testing Hard Controls Integration")
    print("="*70)
    
    controls = get_hard_controls()
    
    user_id = "test_user_5"
    
    # Initialize user
    from controls import KillSwitchStatus
    controls.user_kill_switches[user_id] = KillSwitchStatus.ACTIVE
    
    # Test can trade
    can_trade, reason = controls.can_trade(user_id)
    print(f"✅ Can trade check: {can_trade}")
    
    # Test API error recording
    disabled = controls.record_api_error(user_id, "test_error")
    print(f"✅ Recorded API error, disabled={disabled}")
    
    # Test global kill switch
    print(f"✅ Global kill switch status: {controls.global_kill_switch.value}")
    
    print("✅ Hard Controls: PASSED\n")


def main():
    """Run all tests."""
    print("\n" + "="*70)
    print("NIJA Advanced User Management Features - Test Suite")
    print("="*70)
    
    try:
        test_nonce_manager()
        test_pnl_tracker()
        test_risk_manager()
        test_webhook_notifier()
        test_hard_controls()
        
        print("\n" + "="*70)
        print("✅ ALL TESTS PASSED")
        print("="*70 + "\n")
        
        return 0
    
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
