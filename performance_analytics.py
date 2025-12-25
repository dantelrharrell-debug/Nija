#!/usr/bin/env python3
"""
NIJA Performance Analytics & Reporting

Generates detailed performance reports from trading history.
- Daily/weekly/monthly summaries
- Trade analysis
- Win rate tracking
- Profit factor calculations
- Best/worst trades
- Performance charts (text-based)

Author: NIJA Trading Systems
Version: 1.0
Date: December 19, 2025
"""

import json
import sys
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from typing import List, Dict, Any, Optional
import logging

logging.basicConfig(level=logging.INFO, format='%(message)s')
logger = logging.getLogger(__name__)


class PerformanceAnalytics:
    """Analyze and report on trading performance"""
    
    def __init__(self, data_dir: str = "/usr/src/app/data"):
        self.data_dir = Path(data_dir)
        self.trades = self._load_trades()
        self.metrics = self._load_metrics()
    
    def _load_trades(self) -> List[Dict]:
        """Load trade history from JSON"""
        trade_file = self.data_dir / "trade_history.json"
        if not trade_file.exists():
            logger.warning(f"No trade history found at {trade_file}")
            return []
        
        try:
            with open(trade_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading trades: {e}")
            return []
    
    def _load_metrics(self) -> Dict:
        """Load metrics from monitoring system"""
        metrics_file = Path("/tmp/nija_monitoring/metrics.json")
        if not metrics_file.exists():
            return {}
        
        try:
            with open(metrics_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading metrics: {e}")
            return {}
    
    def generate_daily_report(self, date: Optional[str] = None) -> str:
        """Generate daily performance report"""
        if date is None:
            date = datetime.now().strftime("%Y-%m-%d")
        
        # Filter trades for this day
        daily_trades = [t for t in self.trades 
                       if t.get('entry_time', '').startswith(date)]
        
        if not daily_trades:
            return f"\n📅 Daily Report for {date}\n{'='*70}\nNo trades executed today.\n"
        
        # Calculate metrics
        total = len(daily_trades)
        wins = sum(1 for t in daily_trades if t.get('net_profit', 0) > 0)
        losses = total - wins
        win_rate = (wins / total * 100) if total > 0 else 0
        
        total_profit = sum(t.get('net_profit', 0) for t in daily_trades)
        total_fees = sum(t.get('total_fees', 0) for t in daily_trades)
        
        gross_wins = sum(t.get('net_profit', 0) for t in daily_trades if t.get('net_profit', 0) > 0)
        gross_losses = abs(sum(t.get('net_profit', 0) for t in daily_trades if t.get('net_profit', 0) < 0))
        
        profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else float('inf')
        
        best_trade = max(daily_trades, key=lambda t: t.get('net_profit', 0))
        worst_trade = min(daily_trades, key=lambda t: t.get('net_profit', 0))
        
        # Build report
        report = f"""
╔══════════════════════════════════════════════════════════════════╗
║               DAILY PERFORMANCE REPORT - {date}              ║
╚══════════════════════════════════════════════════════════════════╝

📊 SUMMARY:
   Total Trades:        {total}
   Wins / Losses:       {wins} / {losses}
   Win Rate:            {win_rate:.1f}%
   Profit Factor:       {profit_factor:.2f}

💰 PROFIT & LOSS:
   Gross Wins:          ${gross_wins:.2f}
   Gross Losses:        ${gross_losses:.2f}
   Total Fees:          ${total_fees:.2f}
   Net P&L:             ${total_profit:+.2f}

🏆 BEST TRADE:
   Symbol:              {best_trade.get('symbol', 'N/A')}
   Direction:           {best_trade.get('direction', 'N/A')}
   Entry:               ${best_trade.get('entry_price', 0):.2f}
   Exit:                ${best_trade.get('exit_price', 0):.2f}
   Profit:              ${best_trade.get('net_profit', 0):.2f}

📉 WORST TRADE:
   Symbol:              {worst_trade.get('symbol', 'N/A')}
   Direction:           {worst_trade.get('direction', 'N/A')}
   Entry:               ${worst_trade.get('entry_price', 0):.2f}
   Exit:                ${worst_trade.get('exit_price', 0):.2f}
   Loss:                ${worst_trade.get('net_profit', 0):.2f}

═══════════════════════════════════════════════════════════════════
"""
        return report
    
    def generate_weekly_report(self) -> str:
        """Generate weekly performance report"""
        # Last 7 days
        end_date = datetime.now()
        start_date = end_date - timedelta(days=7)
        
        weekly_trades = [t for t in self.trades 
                        if start_date <= datetime.fromisoformat(t.get('entry_time', '')) <= end_date]
        
        if not weekly_trades:
            return "\n📅 Weekly Report\n" + "="*70 + "\nNo trades in the last 7 days.\n"
        
        # Group by day
        by_day = defaultdict(list)
        for trade in weekly_trades:
            day = trade.get('entry_time', '')[:10]
            by_day[day].append(trade)
        
        # Calculate totals
        total = len(weekly_trades)
        wins = sum(1 for t in weekly_trades if t.get('net_profit', 0) > 0)
        win_rate = (wins / total * 100) if total > 0 else 0
        total_profit = sum(t.get('net_profit', 0) for t in weekly_trades)
        
        report = f"""
╔══════════════════════════════════════════════════════════════════╗
║                    WEEKLY PERFORMANCE REPORT                     ║
║        {start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}                     ║
╚══════════════════════════════════════════════════════════════════╝

📊 WEEK SUMMARY:
   Total Trades:        {total}
   Win Rate:            {win_rate:.1f}%
   Net P&L:             ${total_profit:+.2f}
   Average/Trade:       ${(total_profit/total if total > 0 else 0):.2f}

📅 DAILY BREAKDOWN:
"""
        
        for day in sorted(by_day.keys()):
            day_trades = by_day[day]
            day_profit = sum(t.get('net_profit', 0) for t in day_trades)
            day_wins = sum(1 for t in day_trades if t.get('net_profit', 0) > 0)
            
            report += f"   {day}: {len(day_trades)} trades, {day_wins}W/{len(day_trades)-day_wins}L, ${day_profit:+.2f}\n"
        
        report += "\n" + "="*70 + "\n"
        return report
    
    def generate_symbol_analysis(self) -> str:
        """Analyze performance by symbol"""
        if not self.trades:
            return "\nNo trades to analyze.\n"
        
        # Group by symbol
        by_symbol = defaultdict(lambda: {'trades': [], 'profit': 0, 'wins': 0})
        
        for trade in self.trades:
            symbol = trade.get('symbol', 'UNKNOWN')
            profit = trade.get('net_profit', 0)
            
            by_symbol[symbol]['trades'].append(trade)
            by_symbol[symbol]['profit'] += profit
            if profit > 0:
                by_symbol[symbol]['wins'] += 1
        
        # Sort by profit
        sorted_symbols = sorted(by_symbol.items(), 
                               key=lambda x: x[1]['profit'], 
                               reverse=True)
        
        report = """
╔══════════════════════════════════════════════════════════════════╗
║                  PERFORMANCE BY SYMBOL                           ║
╚══════════════════════════════════════════════════════════════════╝

"""
        report += f"{'Symbol':<12} {'Trades':<8} {'Wins':<6} {'Win%':<8} {'Net P&L':<12}\n"
        report += "-" * 70 + "\n"
        
        for symbol, data in sorted_symbols[:15]:  # Top 15
            total = len(data['trades'])
            wins = data['wins']
            win_rate = (wins / total * 100) if total > 0 else 0
            profit = data['profit']
            
            report += f"{symbol:<12} {total:<8} {wins:<6} {win_rate:>6.1f}% {profit:>+11.2f}\n"
        
        report += "="*70 + "\n"
        return report
    
    def generate_full_report(self) -> str:
        """Generate comprehensive performance report"""
        report = """
╔══════════════════════════════════════════════════════════════════╗
║           NIJA BOT - COMPREHENSIVE PERFORMANCE REPORT            ║
╚══════════════════════════════════════════════════════════════════╝
"""
        
        if not self.trades:
            return report + "\nNo trading history available.\n"
        
        # Overall metrics
        total = len(self.trades)
        wins = sum(1 for t in self.trades if t.get('net_profit', 0) > 0)
        losses = total - wins
        win_rate = (wins / total * 100) if total > 0 else 0
        
        total_profit = sum(t.get('net_profit', 0) for t in self.trades)
        total_fees = sum(t.get('total_fees', 0) for t in self.trades)
        
        gross_wins = sum(t.get('net_profit', 0) for t in self.trades if t.get('net_profit', 0) > 0)
        gross_losses = abs(sum(t.get('net_profit', 0) for t in self.trades if t.get('net_profit', 0) < 0))
        
        profit_factor = (gross_wins / gross_losses) if gross_losses > 0 else float('inf')
        
        avg_win = (gross_wins / wins) if wins > 0 else 0
        avg_loss = (gross_losses / losses) if losses > 0 else 0
        
        # Find best/worst
        if self.trades:
            best_trade = max(self.trades, key=lambda t: t.get('net_profit', 0))
            worst_trade = min(self.trades, key=lambda t: t.get('net_profit', 0))
        
        report += f"""
📊 OVERALL STATISTICS:
   Total Trades:        {total}
   Wins / Losses:       {wins} / {losses}
   Win Rate:            {win_rate:.1f}%
   Profit Factor:       {profit_factor:.2f}

💰 PROFIT & LOSS:
   Gross Profit:        ${gross_wins:.2f}
   Gross Loss:          ${gross_losses:.2f}
   Total Fees:          ${total_fees:.2f}
   Net P&L:             ${total_profit:+.2f}
   
   Average Win:         ${avg_win:.2f}
   Average Loss:        ${avg_loss:.2f}
   Best Trade:          ${best_trade.get('net_profit', 0):.2f} ({best_trade.get('symbol', 'N/A')})
   Worst Trade:         ${worst_trade.get('net_profit', 0):.2f} ({worst_trade.get('symbol', 'N/A')})

═══════════════════════════════════════════════════════════════════
"""
        
        # Add symbol analysis
        report += self.generate_symbol_analysis()
        
        # Add weekly summary
        report += self.generate_weekly_report()
        
        return report
    
    def export_csv_report(self, filename: Optional[str] = None):
        """Export detailed CSV report"""
        if filename is None:
            filename = f"performance_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        output_path = Path(filename)
        
        # CSV header
        csv_lines = ["Symbol,Entry Time,Exit Time,Direction,Entry Price,Exit Price,Size,Net Profit,Fees,Duration\n"]
        
        for trade in self.trades:
            line = (
                f"{trade.get('symbol', '')},"
                f"{trade.get('entry_time', '')},"
                f"{trade.get('exit_time', '')},"
                f"{trade.get('direction', '')},"
                f"{trade.get('entry_price', 0):.2f},"
                f"{trade.get('exit_price', 0):.2f},"
                f"{trade.get('position_size', 0):.2f},"
                f"{trade.get('net_profit', 0):.2f},"
                f"{trade.get('total_fees', 0):.2f},"
                f"{trade.get('duration_seconds', 0)}\n"
            )
            csv_lines.append(line)
        
        output_path.write_text(''.join(csv_lines))
        logger.info(f"✅ CSV report exported to: {output_path}")


def main():
    """Run performance analytics"""
    analytics = PerformanceAnalytics()
    
    # Generate full report
    report = analytics.generate_full_report()
    print(report)
    
    # Export CSV
    analytics.export_csv_report()


if __name__ == "__main__":
    main()
