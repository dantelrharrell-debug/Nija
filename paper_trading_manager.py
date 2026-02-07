#!/usr/bin/env python3
"""
NIJA Paper Trading Manager CLI

Command-line tool for managing paper trading with analytics.
Implements the 3-phase process:
1. Run paper trading with analytics ON
2. Kill losers ruthlessly  
3. Lock profit-ready definition

Usage:
    # Start paper trading with analytics
    python paper_trading_manager.py --start
    
    # Check status and generate report
    python paper_trading_manager.py --report
    
    # Identify underperformers
    python paper_trading_manager.py --analyze
    
    # Kill underperformers (bottom 25%)
    python paper_trading_manager.py --kill-losers
    
    # Check profit-ready status
    python paper_trading_manager.py --check-ready
    
    # Set custom profit-ready criteria
    python paper_trading_manager.py --set-criteria --min-return 10 --max-drawdown 12

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import argparse
import json
import logging
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

# Add bot directory to path
sys.path.insert(0, str(Path(__file__).parent))

from bot.paper_trading_analytics import (
    get_analytics,
    TradeAnalytics,
    SignalType,
    ExitReason,
    ProfitReadyCriteria
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("nija.paper_manager")


class PaperTradingManager:
    """Manager for paper trading analytics operations"""
    
    def __init__(self, data_dir: str = "./data/paper_analytics"):
        """
        Initialize manager
        
        Args:
            data_dir: Directory for analytics data
        """
        self.analytics = get_analytics(data_dir)
        self.data_dir = Path(data_dir)
    
    def generate_report(self, output_file: Optional[str] = None) -> None:
        """
        Generate and display comprehensive analytics report
        
        Args:
            output_file: Optional file to save JSON report
        """
        report = self.analytics.generate_report()
        
        if 'error' in report:
            print(f"\n❌ {report['error']}")
            print(f"   {report['message']}\n")
            return
        
        # Print summary
        print("\n" + "="*80)
        print("📊 PAPER TRADING ANALYTICS REPORT")
        print("="*80)
        
        summary = report['summary']
        print(f"\n💰 OVERALL PERFORMANCE")
        print(f"   Total Trades:        {summary['total_trades']}")
        print(f"   Total P&L:           ${summary['total_pnl']:+,.2f}")
        print(f"   Win Rate:            {summary['win_rate']:.1f}%")
        print(f"   Avg P&L per Trade:   ${summary['avg_pnl_per_trade']:+,.2f}")
        
        # Signal performance
        print(f"\n📡 SIGNAL TYPE PERFORMANCE")
        print(f"   {'Signal Type':<25} {'Trades':<10} {'Win%':<10} {'PF':<10} {'P&L':<15} {'Status'}")
        print(f"   {'-'*80}")
        
        for signal_type, perf in sorted(
            report['signal_performance'].items(),
            key=lambda x: x[1]['profit_factor'],
            reverse=True
        ):
            status = "✅ ENABLED" if perf['enabled'] else "🚫 DISABLED"
            print(f"   {signal_type:<25} {perf['total_trades']:<10} "
                  f"{perf['win_rate']:<10.1f} {perf['profit_factor']:<10.2f} "
                  f"${perf['total_pnl']:+<14,.2f} {status}")
        
        # Exit performance
        print(f"\n🚪 EXIT STRATEGY PERFORMANCE")
        print(f"   {'Exit Reason':<25} {'Trades':<10} {'Win%':<10} {'PF':<10} {'P&L':<15} {'Allocation'}")
        print(f"   {'-'*80}")
        
        for exit_reason, perf in sorted(
            report['exit_performance'].items(),
            key=lambda x: x[1]['profit_factor'],
            reverse=True
        ):
            allocation = f"{perf['capital_allocation_pct']:.0f}%"
            print(f"   {exit_reason:<25} {perf['total_trades']:<10} "
                  f"{perf['win_rate']:<10.1f} {perf['profit_factor']:<10.2f} "
                  f"${perf['total_pnl']:+<14,.2f} {allocation}")
        
        # Profit-ready status
        print(f"\n🎯 PROFIT-READY STATUS")
        status = report['profit_ready_status']
        print(f"   {status['message']}")
        
        if status['criteria_met']:
            print(f"\n   Criteria Status:")
            for criterion, met in status['criteria_met'].items():
                icon = "✅" if met else "❌"
                value = status['criteria_values'].get(criterion, 'N/A')
                if isinstance(value, float):
                    value_str = f"{value:.2f}"
                else:
                    value_str = str(value)
                print(f"   {icon} {criterion:<25} {value_str}")
        
        if report.get('disabled_signals'):
            print(f"\n🚫 DISABLED SIGNALS:")
            for signal in report['disabled_signals']:
                print(f"   - {signal}")
        
        print("="*80 + "\n")
        
        # Save to file if requested
        if output_file:
            output_path = self.data_dir / output_file
            with open(output_path, 'w') as f:
                json.dump(report, f, indent=2)
            print(f"📄 Report saved to: {output_path}\n")
    
    def analyze_performance(self) -> None:
        """Analyze and identify top and bottom performers"""
        print("\n" + "="*80)
        print("🔍 PERFORMANCE ANALYSIS")
        print("="*80)
        
        # Identify underperformers (bottom 25%)
        print("\n📉 UNDERPERFORMERS (Bottom 25%)")
        underperformers = self.analytics.identify_underperformers(percentile=25.0)
        
        if underperformers['signals']:
            print(f"\n   Underperforming Signals:")
            for signal in underperformers['signals']:
                perf = self.analytics.signal_performance[signal]
                print(f"   - {signal:<25} Win Rate: {perf.win_rate:.1f}% | "
                      f"PF: {perf.profit_factor:.2f} | P&L: ${perf.total_pnl:+.2f}")
        else:
            print(f"\n   No underperforming signals identified")
        
        if underperformers['exits']:
            print(f"\n   Underperforming Exits:")
            for exit_reason in underperformers['exits']:
                perf = self.analytics.exit_performance[exit_reason]
                print(f"   - {exit_reason:<25} Win Rate: {perf.win_rate:.1f}% | "
                      f"PF: {perf.profit_factor:.2f} | P&L: ${perf.total_pnl:+.2f}")
        else:
            print(f"\n   No underperforming exits identified")
        
        # Identify top performers (top 25%)
        print("\n📈 TOP PERFORMERS (Top 25%)")
        top_performers = self.analytics.promote_top_performers(percentile=75.0)
        
        if top_performers['signals']:
            print(f"\n   Top Performing Signals:")
            for signal in top_performers['signals']:
                perf = self.analytics.signal_performance[signal]
                print(f"   - {signal:<25} Win Rate: {perf.win_rate:.1f}% | "
                      f"PF: {perf.profit_factor:.2f} | P&L: ${perf.total_pnl:+.2f}")
        else:
            print(f"\n   No top performing signals identified yet")
        
        if top_performers['exits']:
            print(f"\n   Top Performing Exits:")
            for exit_reason in top_performers['exits']:
                perf = self.analytics.exit_performance[exit_reason]
                print(f"   - {exit_reason:<25} Win Rate: {perf.win_rate:.1f}% | "
                      f"PF: {perf.profit_factor:.2f} | P&L: ${perf.total_pnl:+.2f}")
        else:
            print(f"\n   No top performing exits identified yet")
        
        print("="*80 + "\n")
    
    def kill_losers(self, auto_confirm: bool = False) -> None:
        """
        Disable underperforming signals and reduce allocation for weak exits
        
        Args:
            auto_confirm: Skip confirmation prompt
        """
        print("\n" + "="*80)
        print("⚔️  KILL LOSERS - Disable Underperformers")
        print("="*80)
        
        # Identify underperformers
        underperformers = self.analytics.identify_underperformers(percentile=25.0)
        
        if not underperformers['signals'] and not underperformers['exits']:
            print("\n✅ No underperformers to disable. All strategies performing well!")
            print("="*80 + "\n")
            return
        
        # Show what will be disabled
        print("\nThe following will be disabled/reduced:")
        
        if underperformers['signals']:
            print(f"\n🚫 Signals to DISABLE:")
            for signal in underperformers['signals']:
                perf = self.analytics.signal_performance[signal]
                print(f"   - {signal} (Win Rate: {perf.win_rate:.1f}%, PF: {perf.profit_factor:.2f})")
        
        if underperformers['exits']:
            print(f"\n📉 Exits to REDUCE (50% allocation):")
            for exit_reason in underperformers['exits']:
                perf = self.analytics.exit_performance[exit_reason]
                print(f"   - {exit_reason} (Win Rate: {perf.win_rate:.1f}%, PF: {perf.profit_factor:.2f})")
        
        # Confirm
        if not auto_confirm:
            response = input("\n⚠️  Proceed with disabling underperformers? (yes/no): ")
            if response.lower() not in ['yes', 'y']:
                print("❌ Operation cancelled")
                print("="*80 + "\n")
                return
        
        # Disable signals
        if underperformers['signals']:
            self.analytics.disable_underperformers(underperformers['signals'])
            print(f"\n✅ Disabled {len(underperformers['signals'])} underperforming signal(s)")
        
        # Reduce exit allocations
        if underperformers['exits']:
            self.analytics.reduce_exit_allocation(underperformers['exits'], reduction_pct=50.0)
            print(f"✅ Reduced allocation for {len(underperformers['exits'])} underperforming exit(s)")
        
        print("\n💡 Recommendation: Monitor performance over next 20-50 trades")
        print("="*80 + "\n")
    
    def check_profit_ready(self) -> None:
        """Check and display profit-ready status"""
        print("\n" + "="*80)
        print("🎯 PROFIT-READY CRITERIA VALIDATION")
        print("="*80)
        
        status = self.analytics.validate_profit_ready()
        
        print(f"\n{status.message}")
        
        print(f"\nCriteria Evaluation:")
        print(f"   {'Criterion':<30} {'Status':<10} {'Value'}")
        print(f"   {'-'*70}")
        
        for criterion, met in status.criteria_met.items():
            icon = "✅" if met else "❌"
            value = status.criteria_values.get(criterion, 'N/A')
            if isinstance(value, float):
                value_str = f"{value:.2f}"
            else:
                value_str = str(value)
            print(f"   {criterion:<30} {icon:<10} {value_str}")
        
        if status.is_ready:
            print(f"\n🎉 CONGRATULATIONS! Your bot is profit-ready!")
            print(f"   You can now scale to live trading with confidence.")
        else:
            print(f"\n⏳ Keep collecting data and optimizing.")
            failed = [k for k, v in status.criteria_met.items() if not v]
            print(f"   Still need to meet: {', '.join(failed)}")
        
        print("="*80 + "\n")
    
    def set_criteria(self, **kwargs) -> None:
        """
        Update profit-ready criteria
        
        Args:
            **kwargs: Criteria parameters to update
        """
        current = self.analytics.profit_criteria
        
        # Map CLI arguments to criteria fields
        mapping = {
            'min_return': 'min_total_return_pct',
            'min_trades': 'min_trades',
            'max_trades': 'max_trades',
            'max_drawdown': 'max_drawdown_pct',
            'min_sharpe': 'min_sharpe_ratio',
            'min_win_rate': 'min_win_rate',
            'min_profit_factor': 'min_profit_factor',
            'max_scan_time': 'max_scan_time_seconds',
            'min_utilization': 'min_utilization_pct',
            'max_utilization': 'max_utilization_pct',
            'min_days': 'min_days_trading'
        }
        
        updated = False
        for cli_arg, field_name in mapping.items():
            if cli_arg in kwargs and kwargs[cli_arg] is not None:
                setattr(current, field_name, kwargs[cli_arg])
                updated = True
                print(f"✅ Updated {field_name}: {kwargs[cli_arg]}")
        
        if updated:
            self.analytics._save_data()
            print(f"\n💾 Criteria saved successfully")
        else:
            print(f"\n⚠️  No criteria updated")
    
    def show_current_criteria(self) -> None:
        """Display current profit-ready criteria"""
        criteria = self.analytics.profit_criteria
        
        print("\n" + "="*80)
        print("⚙️  CURRENT PROFIT-READY CRITERIA")
        print("="*80)
        
        print(f"\n📊 Return Criteria:")
        print(f"   Minimum Total Return:     {criteria.min_total_return_pct:.1f}%")
        print(f"   Minimum Trades:           {criteria.min_trades}")
        print(f"   Maximum Trades:           {criteria.max_trades}")
        
        print(f"\n🛡️  Risk Criteria:")
        print(f"   Maximum Drawdown:         {criteria.max_drawdown_pct:.1f}%")
        print(f"   Minimum Sharpe Ratio:     {criteria.min_sharpe_ratio:.2f}")
        
        print(f"\n🎯 Performance Criteria:")
        print(f"   Minimum Win Rate:         {criteria.min_win_rate:.1f}%")
        print(f"   Minimum Profit Factor:    {criteria.min_profit_factor:.2f}")
        
        print(f"\n⚡ Operational Criteria:")
        print(f"   Maximum Scan Time:        {criteria.max_scan_time_seconds:.1f} seconds")
        print(f"   Min Capital Utilization:  {criteria.min_utilization_pct:.1f}%")
        print(f"   Max Capital Utilization:  {criteria.max_utilization_pct:.1f}%")
        
        print(f"\n⏱️  Time Criteria:")
        print(f"   Minimum Days Trading:     {criteria.min_days_trading} days")
        
        print("="*80 + "\n")


def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description='NIJA Paper Trading Manager - Analytics and Performance Optimization',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate full analytics report
  python paper_trading_manager.py --report
  
  # Analyze top and bottom performers
  python paper_trading_manager.py --analyze
  
  # Disable underperformers (interactive)
  python paper_trading_manager.py --kill-losers
  
  # Check if ready for live trading
  python paper_trading_manager.py --check-ready
  
  # Set custom criteria
  python paper_trading_manager.py --set-criteria --min-return 10 --max-drawdown 12
  
  # Show current criteria
  python paper_trading_manager.py --show-criteria
        """
    )
    
    # Main actions
    parser.add_argument('--report', action='store_true',
                       help='Generate comprehensive analytics report')
    parser.add_argument('--analyze', action='store_true',
                       help='Analyze top and bottom performers')
    parser.add_argument('--kill-losers', action='store_true',
                       help='Disable underperforming signals and reduce weak exit allocations')
    parser.add_argument('--check-ready', action='store_true',
                       help='Check profit-ready criteria validation')
    parser.add_argument('--set-criteria', action='store_true',
                       help='Update profit-ready criteria')
    parser.add_argument('--show-criteria', action='store_true',
                       help='Show current profit-ready criteria')
    
    # Options
    parser.add_argument('--output', type=str,
                       help='Save report to JSON file')
    parser.add_argument('--data-dir', type=str, default='./data/paper_analytics',
                       help='Data directory for analytics (default: ./data/paper_analytics)')
    parser.add_argument('--auto-confirm', action='store_true',
                       help='Skip confirmation prompts')
    
    # Criteria parameters
    parser.add_argument('--min-return', type=float,
                       help='Minimum total return percentage')
    parser.add_argument('--min-trades', type=int,
                       help='Minimum number of trades')
    parser.add_argument('--max-trades', type=int,
                       help='Maximum trades before decision required')
    parser.add_argument('--max-drawdown', type=float,
                       help='Maximum drawdown percentage')
    parser.add_argument('--min-sharpe', type=float,
                       help='Minimum Sharpe ratio')
    parser.add_argument('--min-win-rate', type=float,
                       help='Minimum win rate percentage')
    parser.add_argument('--min-profit-factor', type=float,
                       help='Minimum profit factor')
    parser.add_argument('--max-scan-time', type=float,
                       help='Maximum scan time in seconds')
    parser.add_argument('--min-utilization', type=float,
                       help='Minimum capital utilization percentage')
    parser.add_argument('--max-utilization', type=float,
                       help='Maximum capital utilization percentage')
    parser.add_argument('--min-days', type=int,
                       help='Minimum days of trading data')
    
    args = parser.parse_args()
    
    # Create manager
    manager = PaperTradingManager(data_dir=args.data_dir)
    
    # Execute requested action
    if args.report:
        manager.generate_report(output_file=args.output)
    
    elif args.analyze:
        manager.analyze_performance()
    
    elif args.kill_losers:
        manager.kill_losers(auto_confirm=args.auto_confirm)
    
    elif args.check_ready:
        manager.check_profit_ready()
    
    elif args.set_criteria:
        criteria_kwargs = {
            'min_return': args.min_return,
            'min_trades': args.min_trades,
            'max_trades': args.max_trades,
            'max_drawdown': args.max_drawdown,
            'min_sharpe': args.min_sharpe,
            'min_win_rate': args.min_win_rate,
            'min_profit_factor': args.min_profit_factor,
            'max_scan_time': args.max_scan_time,
            'min_utilization': args.min_utilization,
            'max_utilization': args.max_utilization,
            'min_days': args.min_days
        }
        manager.set_criteria(**criteria_kwargs)
    
    elif args.show_criteria:
        manager.show_current_criteria()
    
    else:
        parser.print_help()


if __name__ == '__main__':
    main()
