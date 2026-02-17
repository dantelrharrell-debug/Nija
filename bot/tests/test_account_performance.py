#!/usr/bin/env python3
"""
Test Per-Account Performance Tracking
======================================

Tests to verify:
1. Trade history is tracked separately per account
2. Expectancy calculated separately per account
3. Drawdown tracked separately per account
4. No aggregation across accounts
5. No cross-contamination between accounts

Author: NIJA Trading Systems
Date: February 17, 2026
"""

import sys
import os

# Add the bot directory to the path
bot_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, bot_dir)

from datetime import datetime, timedelta
from account_performance_tracker import (
    AccountPerformanceTracker,
    TradeRecord,
    get_performance_tracker
)


def test_separate_trade_histories():
    """Test 1: Trade histories are tracked separately per account"""
    print("="*70)
    print("TEST 1: Separate Trade Histories Per Account")
    print("="*70)
    
    tracker = AccountPerformanceTracker(data_dir="/tmp/test_performance")
    
    # Record trades for account 1
    trade1_account1 = TradeRecord(
        trade_id="TRADE-1",
        account_id="PLATFORM",
        symbol="BTC-USD",
        side="buy",
        entry_price=45000.0,
        exit_price=46000.0,
        quantity=0.01,
        size_usd=450.0,
        pnl=10.0,
        pnl_pct=2.22,
        fees=2.0,
        net_pnl=8.0,
        entry_time=datetime.now() - timedelta(hours=2),
        exit_time=datetime.now(),
        hold_time_seconds=7200,
        is_win=True
    )
    tracker.record_trade(trade1_account1)
    
    trade2_account1 = TradeRecord(
        trade_id="TRADE-2",
        account_id="PLATFORM",
        symbol="ETH-USD",
        side="buy",
        entry_price=3000.0,
        exit_price=2950.0,
        quantity=0.1,
        size_usd=300.0,
        pnl=-5.0,
        pnl_pct=-1.67,
        fees=1.5,
        net_pnl=-6.5,
        entry_time=datetime.now() - timedelta(hours=1),
        exit_time=datetime.now(),
        hold_time_seconds=3600,
        is_win=False
    )
    tracker.record_trade(trade2_account1)
    
    # Record trades for account 2
    trade1_account2 = TradeRecord(
        trade_id="TRADE-3",
        account_id="USER_abc123",
        symbol="SOL-USD",
        side="buy",
        entry_price=100.0,
        exit_price=105.0,
        quantity=1.0,
        size_usd=100.0,
        pnl=5.0,
        pnl_pct=5.0,
        fees=0.5,
        net_pnl=4.5,
        entry_time=datetime.now() - timedelta(hours=3),
        exit_time=datetime.now(),
        hold_time_seconds=10800,
        is_win=True
    )
    tracker.record_trade(trade1_account2)
    
    # Verify trade counts
    platform_trades = tracker.get_trade_history("PLATFORM")
    user_trades = tracker.get_trade_history("USER_abc123")
    
    print(f"\n📊 Trade History Counts:")
    print(f"   PLATFORM: {len(platform_trades)} trades")
    print(f"   USER_abc123: {len(user_trades)} trades")
    
    assert len(platform_trades) == 2, f"Expected 2 trades for PLATFORM, got {len(platform_trades)}"
    assert len(user_trades) == 1, f"Expected 1 trade for USER_abc123, got {len(user_trades)}"
    
    # Verify trades belong to correct accounts
    for trade in platform_trades:
        assert trade.account_id == "PLATFORM", f"Trade {trade.trade_id} has wrong account_id"
    
    for trade in user_trades:
        assert trade.account_id == "USER_abc123", f"Trade {trade.trade_id} has wrong account_id"
    
    print("\n✅ TEST 1 PASSED: Trade histories are separate per account")
    print()


def test_separate_expectancy_calculation():
    """Test 2: Expectancy calculated separately per account"""
    print("="*70)
    print("TEST 2: Separate Expectancy Calculation Per Account")
    print("="*70)
    
    tracker = AccountPerformanceTracker(data_dir="/tmp/test_performance")
    
    # Get metrics for both accounts
    platform_metrics = tracker.get_metrics("PLATFORM")
    user_metrics = tracker.get_metrics("USER_abc123")
    
    print(f"\n📊 Expectancy Metrics:")
    print(f"\n   PLATFORM:")
    print(f"      Total Trades: {platform_metrics.total_trades}")
    print(f"      Win Rate: {platform_metrics.win_rate:.1f}%")
    print(f"      Average Win: ${platform_metrics.average_win:.2f}")
    print(f"      Average Loss: ${platform_metrics.average_loss:.2f}")
    print(f"      Expectancy: ${platform_metrics.expectancy:.2f} per dollar risked")
    print(f"      Expectancy/Trade: ${platform_metrics.expectancy_per_trade:.2f} per trade")
    
    print(f"\n   USER_abc123:")
    print(f"      Total Trades: {user_metrics.total_trades}")
    print(f"      Win Rate: {user_metrics.win_rate:.1f}%")
    print(f"      Average Win: ${user_metrics.average_win:.2f}")
    print(f"      Average Loss: ${user_metrics.average_loss:.2f}")
    print(f"      Expectancy: ${user_metrics.expectancy:.2f} per dollar risked")
    print(f"      Expectancy/Trade: ${user_metrics.expectancy_per_trade:.2f} per trade")
    
    # Verify expectancies are calculated independently
    # PLATFORM: 1 win ($8), 1 loss ($6.5) = 50% WR
    # Expectancy = (0.5 * 8.0) - (0.5 * 6.5) = 4.0 - 3.25 = 0.75
    assert platform_metrics.total_trades == 2, "Wrong trade count for PLATFORM"
    assert platform_metrics.win_rate == 50.0, f"Expected 50% WR for PLATFORM, got {platform_metrics.win_rate:.1f}%"
    
    # USER_abc123: 1 win ($4.5) = 100% WR
    # Expectancy = (1.0 * 4.5) - (0.0 * 0) = 4.5
    assert user_metrics.total_trades == 1, "Wrong trade count for USER_abc123"
    assert user_metrics.win_rate == 100.0, f"Expected 100% WR for USER_abc123, got {user_metrics.win_rate:.1f}%"
    
    # Verify expectancies are different (not aggregated)
    assert platform_metrics.expectancy != user_metrics.expectancy, "Expectancies should be different per account"
    
    print("\n✅ TEST 2 PASSED: Expectancy calculated separately per account")
    print()


def test_separate_drawdown_tracking():
    """Test 3: Drawdown tracked separately per account"""
    print("="*70)
    print("TEST 3: Separate Drawdown Tracking Per Account")
    print("="*70)
    
    tracker = AccountPerformanceTracker(data_dir="/tmp/test_performance")
    
    # Update balances for PLATFORM
    tracker.update_balance("PLATFORM", 1000.0)  # Peak
    tracker.update_balance("PLATFORM", 950.0)   # -5% drawdown
    tracker.update_balance("PLATFORM", 900.0)   # -10% drawdown
    tracker.update_balance("PLATFORM", 920.0)   # Recovering
    
    # Update balances for USER_abc123
    tracker.update_balance("USER_abc123", 500.0)  # Peak
    tracker.update_balance("USER_abc123", 475.0)  # -5% drawdown
    tracker.update_balance("USER_abc123", 490.0)  # Recovering
    
    # Get metrics
    platform_metrics = tracker.get_metrics("PLATFORM")
    user_metrics = tracker.get_metrics("USER_abc123")
    
    print(f"\n📉 Drawdown Metrics:")
    print(f"\n   PLATFORM:")
    print(f"      Peak Balance: ${platform_metrics.peak_balance:.2f}")
    print(f"      Current Balance: ${platform_metrics.current_balance:.2f}")
    print(f"      Current Drawdown: ${platform_metrics.current_drawdown:.2f} ({(platform_metrics.current_drawdown/platform_metrics.peak_balance*100) if platform_metrics.peak_balance > 0 else 0:.1f}%)")
    print(f"      Max Drawdown: ${platform_metrics.max_drawdown:.2f} ({platform_metrics.max_drawdown_pct:.1f}%)")
    
    print(f"\n   USER_abc123:")
    print(f"      Peak Balance: ${user_metrics.peak_balance:.2f}")
    print(f"      Current Balance: ${user_metrics.current_balance:.2f}")
    print(f"      Current Drawdown: ${user_metrics.current_drawdown:.2f} ({(user_metrics.current_drawdown/user_metrics.peak_balance*100) if user_metrics.peak_balance > 0 else 0:.1f}%)")
    print(f"      Max Drawdown: ${user_metrics.max_drawdown:.2f} ({user_metrics.max_drawdown_pct:.1f}%)")
    
    # Verify drawdowns are tracked separately
    assert platform_metrics.peak_balance == 1000.0, "Wrong peak for PLATFORM"
    assert platform_metrics.current_balance == 920.0, "Wrong current balance for PLATFORM"
    assert platform_metrics.max_drawdown == 100.0, f"Expected $100 max DD for PLATFORM, got ${platform_metrics.max_drawdown:.2f}"
    
    assert user_metrics.peak_balance == 500.0, "Wrong peak for USER_abc123"
    assert user_metrics.current_balance == 490.0, "Wrong current balance for USER_abc123"
    assert user_metrics.max_drawdown == 25.0, f"Expected $25 max DD for USER_abc123, got ${user_metrics.max_drawdown:.2f}"
    
    # Verify drawdowns are different (not aggregated)
    assert platform_metrics.max_drawdown != user_metrics.max_drawdown, "Drawdowns should be different per account"
    
    print("\n✅ TEST 3 PASSED: Drawdown tracked separately per account")
    print()


def test_no_cross_contamination():
    """Test 4: Verify no cross-contamination between accounts"""
    print("="*70)
    print("TEST 4: No Cross-Contamination Between Accounts")
    print("="*70)
    
    tracker = AccountPerformanceTracker(data_dir="/tmp/test_performance")
    
    # Verify no cross-contamination
    results = tracker.verify_no_aggregation()
    
    print(f"\n🔍 Cross-Contamination Check:")
    for account_id, result in results.items():
        print(f"   {result}")
    
    # All results should be "Clean"
    for account_id, result in results.items():
        assert "Clean" in result or "✅" in result, f"Cross-contamination detected for {account_id}: {result}"
    
    print("\n✅ TEST 4 PASSED: No cross-contamination between accounts")
    print()


def test_no_aggregation_warning():
    """Test 5: Verify metrics are never aggregated"""
    print("="*70)
    print("TEST 5: No Aggregation Across Accounts")
    print("="*70)
    
    tracker = AccountPerformanceTracker(data_dir="/tmp/test_performance")
    
    # Get all metrics
    all_metrics = tracker.get_all_metrics()
    
    print(f"\n⚠️ CRITICAL: Metrics are NEVER aggregated across accounts")
    print(f"\n📊 All Account Metrics:")
    
    total_trades_sum = 0
    for account_id, metrics in all_metrics.items():
        print(f"\n   {account_id}:")
        print(f"      Total Trades: {metrics.total_trades}")
        print(f"      Net P&L: ${metrics.net_pnl:.2f}")
        print(f"      Expectancy: ${metrics.expectancy:.2f}")
        print(f"      Max Drawdown: ${metrics.max_drawdown:.2f}")
        
        total_trades_sum += metrics.total_trades
    
    print(f"\n⚠️ Note: The sum of trades ({total_trades_sum}) is for reference only.")
    print(f"   Each account's metrics should ALWAYS be analyzed independently.")
    print(f"   Aggregating metrics across accounts is PROHIBITED.")
    
    # Verify each account has its own metrics object
    account_ids = list(all_metrics.keys())
    if len(account_ids) >= 2:
        acc1 = account_ids[0]
        acc2 = account_ids[1]
        
        # Metrics objects should be different
        assert id(all_metrics[acc1]) != id(all_metrics[acc2]), "Metrics objects should be separate instances"
        
        # Verify different values (unless coincidentally same)
        metrics_differ = (
            all_metrics[acc1].total_trades != all_metrics[acc2].total_trades or
            all_metrics[acc1].net_pnl != all_metrics[acc2].net_pnl or
            all_metrics[acc1].expectancy != all_metrics[acc2].expectancy
        )
        
        if metrics_differ:
            print(f"\n   ✅ Verified: {acc1} and {acc2} have different metrics (as expected)")
    
    print("\n✅ TEST 5 PASSED: Metrics are never aggregated")
    print()


def test_account_summary_print():
    """Test 6: Print comprehensive account summary"""
    print("="*70)
    print("TEST 6: Account Summary Printing")
    print("="*70)
    
    tracker = AccountPerformanceTracker(data_dir="/tmp/test_performance")
    
    # Print summary for PLATFORM
    tracker.print_account_summary("PLATFORM")
    
    # Print summary for USER_abc123
    tracker.print_account_summary("USER_abc123")
    
    print("\n✅ TEST 6 PASSED: Account summaries printed successfully")
    print()


def run_all_tests():
    """Run all performance tracking tests"""
    print("\n" + "="*70)
    print("PER-ACCOUNT PERFORMANCE TRACKING TESTS")
    print("="*70 + "\n")
    
    try:
        test_separate_trade_histories()
        test_separate_expectancy_calculation()
        test_separate_drawdown_tracking()
        test_no_cross_contamination()
        test_no_aggregation_warning()
        test_account_summary_print()
        
        print("\n" + "="*70)
        print("✅ ALL TESTS PASSED")
        print("="*70)
        print("\n📋 Verified Behavior:")
        print("1. ✅ Trade histories tracked separately per account")
        print("2. ✅ Expectancy calculated separately per account")
        print("3. ✅ Drawdown tracked separately per account")
        print("4. ✅ No cross-contamination between accounts")
        print("5. ✅ Metrics NEVER aggregated across accounts")
        print("6. ✅ Comprehensive summaries available per account")
        print("\n⚠️ CRITICAL RULE:")
        print("   Each account's performance MUST be analyzed independently.")
        print("   NEVER aggregate trade histories or metrics across accounts.")
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
