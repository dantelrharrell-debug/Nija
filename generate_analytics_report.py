#!/usr/bin/env python3
"""
NIJA Analytics Report Generator
================================

Generate comprehensive analytics reports for trading performance.

Usage:
    python generate_analytics_report.py
    python generate_analytics_report.py --detailed
    python generate_analytics_report.py --export-csv
    python generate_analytics_report.py --capital-hours 24

Author: NIJA Trading Systems
Date: February 7, 2026
"""

import sys
import os
import argparse
from pathlib import Path

# Add bot directory to path
sys.path.insert(0, str(Path(__file__).parent / 'bot'))

try:
    from bot.trade_analytics import get_analytics
except ImportError:
    from trade_analytics import get_analytics


def main():
    parser = argparse.ArgumentParser(description='Generate NIJA trading analytics reports')
    parser.add_argument('--detailed', action='store_true', help='Generate detailed report')
    parser.add_argument('--export-csv', action='store_true', help='Export trade history to CSV')
    parser.add_argument('--capital-hours', type=int, default=24, help='Hours of capital utilization history (default: 24)')
    parser.add_argument('--data-dir', type=str, default='./data', help='Data directory (default: ./data)')
    
    args = parser.parse_args()
    
    # Get analytics instance
    analytics = get_analytics(data_dir=args.data_dir)
    
    print("=" * 80)
    print("NIJA TRADING ANALYTICS REPORT")
    print("=" * 80)
    print()
    
    # 1. PnL Attribution
    print("1. PnL ATTRIBUTION")
    print("-" * 80)
    pnl_attr = analytics.get_pnl_attribution()
    
    print("\n   By Signal Type:")
    total_signal_pnl = sum(pnl_attr['by_signal'].values())
    for signal, pnl in sorted(pnl_attr['by_signal'].items(), key=lambda x: x[1], reverse=True):
        pct = (pnl / total_signal_pnl * 100) if total_signal_pnl != 0 else 0
        print(f"      {signal:20} ${pnl:>10.2f} ({pct:>5.1f}%)")
    print(f"      {'TOTAL':20} ${total_signal_pnl:>10.2f}")
    
    print("\n   By Strategy:")
    for strategy, pnl in sorted(pnl_attr['by_strategy'].items(), key=lambda x: x[1], reverse=True):
        print(f"      {strategy:20} ${pnl:>10.2f}")
    print()
    
    # 2. Reason Codes
    print("2. TRADE OUTCOME REASON CODES")
    print("-" * 80)
    reason_codes = analytics.get_reason_code_summary()
    
    print("\n   Entry Reasons (Top 10):")
    entry_sorted = sorted(
        reason_codes['entry_reasons'].items(),
        key=lambda x: x[1]['count'],
        reverse=True
    )[:10]
    for reason, data in entry_sorted:
        print(f"      {reason:35} {data['count']:>5} trades ({data['percentage']:>5.1f}%)")
    
    print("\n   Exit Reasons (Top 10):")
    exit_sorted = sorted(
        reason_codes['exit_reasons'].items(),
        key=lambda x: x[1]['count'],
        reverse=True
    )[:10]
    for reason, data in exit_sorted:
        print(f"      {reason:35} {data['count']:>5} trades ({data['percentage']:>5.1f}%)")
    print()
    
    # 3. Market Scan Performance
    print("3. MARKET SCAN PERFORMANCE")
    print("-" * 80)
    scan_perf = analytics.get_scan_performance()
    
    print(f"   Total Scan Cycles: {scan_perf['total_scan_cycles']}")
    print(f"   Total Markets Scanned: {scan_perf['total_markets_scanned']}")
    print(f"   Avg Markets/Scan: {scan_perf['avg_markets_per_scan']:.1f}")
    print(f"   Avg Scan Time: {scan_perf['avg_scan_time_seconds']:.2f}s")
    print(f"   Min Scan Time: {scan_perf['min_scan_time_seconds']:.2f}s")
    print(f"   Max Scan Time: {scan_perf['max_scan_time_seconds']:.2f}s")
    
    if scan_perf['estimated_full_scan_time'] > 0:
        est_time = scan_perf['estimated_full_scan_time']
        print(f"   Est. Time for 732 Markets: {est_time:.0f}s ({est_time/60:.1f}m)")
        
        # Check if 732 markets can be scanned efficiently
        if est_time < 150:  # 2.5 minutes
            print(f"   ✅ Can scan all 732 markets within one cycle (2.5min)")
        elif est_time < 3600:  # 1 hour
            cycles_needed = int(est_time / 150) + 1
            print(f"   ⚠️  Need {cycles_needed} cycles to scan all 732 markets ({est_time/60:.1f}m total)")
        else:
            print(f"   ❌ Scanning all 732 markets would take {est_time/3600:.1f} hours")
    print()
    
    # 4. Capital Utilization
    print("4. CAPITAL UTILIZATION")
    print("-" * 80)
    recent_capital = analytics.get_recent_capital_utilization(hours=args.capital_hours)
    
    if recent_capital:
        latest = recent_capital[-1]
        print(f"   Latest Snapshot ({args.capital_hours}h window):")
        print(f"      Total Capital: ${latest['total_capital_usd']:.2f}")
        print(f"      In Positions:  ${latest['capital_in_positions_usd']:.2f} ({latest['utilization_pct']:.1f}%)")
        print(f"      Idle Capital:  ${latest['idle_capital_usd']:.2f}")
        print(f"      Positions:     {latest['num_positions']}")
        if latest['num_positions'] > 0:
            print(f"      Avg Position:  ${latest['avg_position_size_usd']:.2f}")
            print(f"      Largest:       {latest['largest_position_symbol']} (${latest['largest_position_usd']:.2f})")
        print(f"      Unrealized P&L: ${latest['unrealized_pnl_usd']:.2f}")
        
        # Show utilization trend
        if len(recent_capital) > 1:
            print(f"\n   Utilization Trend (last {len(recent_capital)} snapshots):")
            for i, snap in enumerate(recent_capital[-5:], 1):  # Last 5 snapshots
                timestamp = snap['timestamp'][:19]  # Trim microseconds
                print(f"      {timestamp}: {snap['utilization_pct']:>5.1f}% ({snap['num_positions']} positions)")
    else:
        print("   No capital utilization data available")
    print()
    
    # 5. Session Statistics (if detailed mode)
    if args.detailed:
        print("5. SESSION STATISTICS")
        print("-" * 80)
        session_stats = analytics.get_session_stats()
        
        print(f"   Total Trades: {session_stats['trades_count']}")
        print(f"   Wins: {session_stats['wins']} | Losses: {session_stats['losses']}")
        print(f"   Win Rate: {session_stats['win_rate']:.1f}%")
        print()
        print(f"   💰 P&L:")
        print(f"      Total P&L: ${session_stats['total_pnl']:.2f}")
        print(f"      Total Fees: ${session_stats['total_fees']:.2f}")
        print(f"      Net After Fees: ${session_stats['total_pnl']:.2f}")
        print()
        print(f"   📈 Averages:")
        print(f"      Avg Profit per Trade: ${session_stats['avg_profit']:.4f}")
        print(f"      Avg Winning Trade: ${session_stats['avg_win']:.4f}")
        print(f"      Avg Losing Trade: ${session_stats['avg_loss']:.4f}")
        print(f"      Avg Trade Duration: {session_stats['avg_duration_min']:.1f}m")
        print()
        print(f"   🎯 Best/Worst:")
        print(f"      Best Trade: ${session_stats['best_trade']:.4f}")
        print(f"      Worst Trade: ${session_stats['worst_trade']:.4f}")
        if session_stats['profit_factor'] != float('inf'):
            print(f"      Profit Factor: {session_stats['profit_factor']:.2f}")
        print()
    
    # Export to CSV if requested
    if args.export_csv:
        csv_path = analytics.export_to_csv()
        print(f"📄 Trade history exported to: {csv_path}")
        print()
    
    print("=" * 80)
    print(f"Report generated at: {pnl_attr['timestamp']}")
    print("=" * 80)


if __name__ == '__main__':
    main()
