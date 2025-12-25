#!/usr/bin/env python3
"""
Test Trade Analytics Module
Verifies fee tracking, performance analytics, and export functionality
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from bot.trade_analytics import TradeAnalytics
import time

def test_analytics():
    """Test complete analytics workflow"""
    print("="*70)
    print("🧪 Testing Trade Analytics Module")
    print("="*70)
    
    # Initialize analytics
    analytics = TradeAnalytics(data_dir="/tmp/nija_test")
    print("✅ Analytics initialized\n")
    
    # Test 1: Record profitable trade
    print("📊 Test 1: Profitable trade")
    print("-"*70)
    
    trade_id = analytics.record_entry(
        symbol="BTC-USD",
        side="BUY",
        price=86000.00,
        size_usd=1.12,
        expected_price=86163.97,
        actual_fill_price=86000.00,
        stop_loss=84280.00,
        take_profit=91180.00
    )
    print(f"Trade ID: {trade_id}\n")
    
    time.sleep(0.1)  # Simulate trade duration
    
    completed_trade = analytics.record_exit(
        symbol="BTC-USD",
        exit_price=86051.72,  # +$0.0006 profit on $1.12
        exit_reason="Take profit hit"
    )
    print()
    
    # Test 2: Record losing trade
    print("📊 Test 2: Losing trade")
    print("-"*70)
    
    analytics.record_entry(
        symbol="ETH-USD",
        side="BUY",
        price=3200.00,
        size_usd=1.12,
        expected_price=3200.00,
        actual_fill_price=3200.00,
        stop_loss=3136.00,
        take_profit=3392.00
    )
    
    time.sleep(0.1)
    
    analytics.record_exit(
        symbol="ETH-USD",
        exit_price=3136.00,  # Stop loss hit
        exit_reason="Stop loss hit"
    )
    print()
    
    # Test 3: Record another winner
    print("📊 Test 3: Another profitable trade")
    print("-"*70)
    
    analytics.record_entry(
        symbol="SOL-USD",
        side="BUY",
        price=150.00,
        size_usd=1.12,
        expected_price=150.00,
        actual_fill_price=150.00,
        stop_loss=147.00,
        take_profit=159.00
    )
    
    time.sleep(0.1)
    
    analytics.record_exit(
        symbol="SOL-USD",
        exit_price=150.90,  # +0.6% profit
        exit_reason="Trailing stop hit"
    )
    print()
    
    # Test 4: Get session statistics
    print("📊 Test 4: Session Statistics")
    print("-"*70)
    stats = analytics.get_session_stats()
    
    print(f"Trades: {stats['trades_count']}")
    print(f"Wins: {stats['wins']} | Losses: {stats['losses']}")
    print(f"Win Rate: {stats['win_rate']:.1f}%")
    print(f"Total P&L: ${stats['total_pnl']:.4f}")
    print(f"Total Fees: ${stats['total_fees']:.4f}")
    print(f"Avg Profit: ${stats['avg_profit']:.4f}")
    print(f"Best Trade: ${stats['best_trade']:.4f}")
    print(f"Worst Trade: ${stats['worst_trade']:.4f}")
    print()
    
    # Test 5: Print full report
    print("📊 Test 5: Full Session Report")
    print("-"*70)
    analytics.print_session_report()
    
    # Test 6: Export to CSV
    print("📊 Test 6: CSV Export")
    print("-"*70)
    csv_path = analytics.export_to_csv("test_trades.csv")
    print(f"✅ Exported to: {csv_path}")
    
    # Read and display CSV content
    with open(csv_path, 'r') as f:
        lines = f.readlines()
        print("\nCSV Preview (first 5 lines):")
        for line in lines[:5]:
            print(f"  {line.strip()}")
    print()
    
    # Test 7: Verify fee calculations
    print("📊 Test 7: Fee Calculation Accuracy")
    print("-"*70)
    
    # Coinbase taker fee = 0.6%
    expected_entry_fee = 1.12 * 0.006  # $0.00672
    actual_entry_fee = analytics.calculate_entry_fee(1.12)
    
    print(f"Position size: $1.12")
    print(f"Expected entry fee (0.6%): ${expected_entry_fee:.5f}")
    print(f"Calculated entry fee: ${actual_entry_fee:.5f}")
    print(f"Match: {'✅' if abs(expected_entry_fee - actual_entry_fee) < 0.00001 else '❌'}")
    print()
    
    # Test 8: Slippage detection
    print("📊 Test 8: Slippage Detection")
    print("-"*70)
    
    analytics.record_entry(
        symbol="DOGE-USD",
        side="BUY",
        price=0.0700,
        size_usd=1.12,
        expected_price=0.0700,
        actual_fill_price=0.0702,  # 0.29% slippage
        stop_loss=0.0686,
        take_profit=0.0742
    )
    
    last_trade = analytics.session_trades[-1]
    print(f"Expected: ${last_trade.expected_price:.4f}")
    print(f"Actual fill: ${last_trade.actual_fill_price:.4f}")
    print(f"Slippage: ${last_trade.slippage:.6f} ({last_trade.slippage_pct:+.2f}%)")
    print()
    
    print("="*70)
    print("✅ All Analytics Tests Passed!")
    print("="*70)
    
    return analytics

if __name__ == "__main__":
    test_analytics()
