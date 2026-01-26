#!/usr/bin/env python3
"""
NIJA Profitability Analysis Tool
=================================

Comprehensive analysis of trading performance to determine if NIJA is:
- Making more profit than losses (✅ GOOD)
- Losing more than profiting (❌ ACTION REQUIRED)

This tool analyzes:
- Completed trades from SQLite database
- Trade history from JSON files
- Win rate, average wins/losses
- Total P&L and fees

Usage:
    python analyze_profitability.py
    python analyze_profitability.py --detailed
    python analyze_profitability.py --export-csv
"""

import sqlite3
import json
import sys
import argparse
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional
from dataclasses import dataclass


@dataclass
class TradeStats:
    """Trade statistics container"""
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    breakeven_trades: int = 0
    total_pnl: float = 0.0
    total_fees: float = 0.0
    win_rate: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    profit_factor: float = 0.0


class ProfitabilityAnalyzer:
    """Analyzes NIJA trading profitability"""
    
    def __init__(self, data_dir: str = "./data"):
        self.data_dir = Path(data_dir)
        self.db_path = self.data_dir / "trade_ledger.db"
        self.json_path = self.data_dir / "trade_history.json"
        
    def load_trades(self) -> List[Dict]:
        """Load all completed trades from database and JSON"""
        all_trades = []
        
        # Load from SQLite database
        if self.db_path.exists():
            all_trades.extend(self._load_from_database())
        
        # Load from JSON
        if self.json_path.exists():
            all_trades.extend(self._load_from_json())
        
        # Remove duplicates (prefer database over JSON)
        return self._deduplicate_trades(all_trades)
    
    def _load_from_database(self) -> List[Dict]:
        """Load completed trades from SQLite database"""
        trades = []
        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT 
                    symbol, side, entry_price, exit_price, quantity, size_usd,
                    entry_fee, exit_fee, total_fees, gross_profit, net_profit, 
                    profit_pct, exit_reason, entry_time, exit_time
                FROM completed_trades
                ORDER BY exit_time DESC
            ''')
            
            for row in cursor.fetchall():
                trades.append({
                    'symbol': row[0],
                    'side': row[1],
                    'entry_price': row[2],
                    'exit_price': row[3],
                    'quantity': row[4],
                    'size_usd': row[5],
                    'entry_fee': row[6] or 0,
                    'exit_fee': row[7] or 0,
                    'total_fees': row[8] or 0,
                    'gross_profit': row[9] or 0,
                    'net_profit': row[10] or 0,
                    'profit_pct': row[11] or 0,
                    'exit_reason': row[12],
                    'entry_time': row[13],
                    'exit_time': row[14],
                    'source': 'database'
                })
            
            conn.close()
        except Exception as e:
            print(f"Warning: Could not load database trades: {e}")
        
        return trades
    
    def _load_from_json(self) -> List[Dict]:
        """Load completed trades from JSON file"""
        trades = []
        try:
            with open(self.json_path, 'r') as f:
                json_trades = json.load(f)
            
            for trade in json_trades:
                if trade.get('exit_price'):  # Only completed trades
                    trades.append({
                        'symbol': trade.get('symbol'),
                        'side': trade.get('side'),
                        'entry_price': trade.get('entry_price', 0),
                        'exit_price': trade.get('exit_price', 0),
                        'quantity': trade.get('quantity', 0),
                        'size_usd': trade.get('size_usd', 0),
                        'total_fees': trade.get('total_fees', 0),
                        'gross_profit': trade.get('gross_profit', 0),
                        'net_profit': trade.get('net_profit', 0),
                        'profit_pct': trade.get('profit_pct', 0),
                        'exit_reason': trade.get('exit_reason', 'Unknown'),
                        'exit_time': trade.get('exit_time'),
                        'source': 'json'
                    })
        except Exception as e:
            print(f"Warning: Could not load JSON trades: {e}")
        
        return trades
    
    def _deduplicate_trades(self, trades: List[Dict]) -> List[Dict]:
        """Remove duplicate trades, preferring database over JSON"""
        seen = set()
        unique_trades = []
        
        # Sort to prioritize database entries
        sorted_trades = sorted(trades, key=lambda t: (t.get('exit_time', ''), 0 if t['source'] == 'database' else 1))
        
        for trade in sorted_trades:
            key = f"{trade['symbol']}_{trade.get('exit_time', '')}"
            if key not in seen:
                seen.add(key)
                unique_trades.append(trade)
        
        return unique_trades
    
    def calculate_stats(self, trades: List[Dict]) -> TradeStats:
        """Calculate comprehensive trading statistics"""
        if not trades:
            return TradeStats()
        
        stats = TradeStats()
        stats.total_trades = len(trades)
        
        wins = [t for t in trades if t['net_profit'] > 0]
        losses = [t for t in trades if t['net_profit'] < 0]
        breakeven = [t for t in trades if t['net_profit'] == 0]
        
        stats.winning_trades = len(wins)
        stats.losing_trades = len(losses)
        stats.breakeven_trades = len(breakeven)
        
        stats.total_pnl = sum(t['net_profit'] for t in trades)
        stats.total_fees = sum(t.get('total_fees', 0) for t in trades)
        
        stats.win_rate = (len(wins) / len(trades) * 100) if trades else 0
        
        stats.avg_win = sum(t['net_profit'] for t in wins) / len(wins) if wins else 0
        stats.avg_loss = sum(t['net_profit'] for t in losses) / len(losses) if losses else 0
        
        stats.largest_win = max((t['net_profit'] for t in trades), default=0)
        stats.largest_loss = min((t['net_profit'] for t in trades), default=0)
        
        total_wins = sum(t['net_profit'] for t in wins)
        total_losses = abs(sum(t['net_profit'] for t in losses))
        stats.profit_factor = total_wins / total_losses if total_losses > 0 else float('inf')
        
        return stats
    
    def print_report(self, trades: List[Dict], detailed: bool = False):
        """Print comprehensive profitability report"""
        print('=' * 80)
        print('🤖 NIJA PROFITABILITY ANALYSIS REPORT')
        print('=' * 80)
        print(f'Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S UTC")}')
        print()
        
        if not trades:
            self._print_no_trades_report()
            return
        
        stats = self.calculate_stats(trades)
        
        # Summary
        print(f'📊 Trade Summary:')
        print(f'   Total Completed Trades: {stats.total_trades}')
        print(f'   • Winning Trades: {stats.winning_trades} ({stats.win_rate:.1f}% win rate)')
        print(f'   • Losing Trades: {stats.losing_trades} ({stats.losing_trades/stats.total_trades*100:.1f}%)')
        print(f'   • Break-even Trades: {stats.breakeven_trades}')
        print()
        
        # Financial Summary
        print('💰 Financial Summary:')
        print(f'   • Total Net P&L: ${stats.total_pnl:.2f}')
        print(f'   • Total Fees Paid: ${stats.total_fees:.2f}')
        print(f'   • Average Win: ${stats.avg_win:.2f}')
        print(f'   • Average Loss: ${stats.avg_loss:.2f}')
        print(f'   • Largest Win: ${stats.largest_win:.2f}')
        print(f'   • Largest Loss: ${stats.largest_loss:.2f}')
        if stats.profit_factor != float('inf'):
            print(f'   • Profit Factor: {stats.profit_factor:.2f}')
        print()
        
        # Recent trades
        if detailed:
            self._print_detailed_trades(trades)
        else:
            self._print_recent_trades(trades, limit=10)
        
        # Final verdict
        self._print_verdict(stats)
    
    def _print_no_trades_report(self):
        """Print report when no trades are found"""
        print('⚠️  NO COMPLETED TRADES FOUND')
        print()
        print('Status: UNABLE TO DETERMINE PROFITABILITY')
        print()
        print('Possible Reasons:')
        print('  • NIJA has not closed any positions yet')
        print('  • All current trades are still open (unrealized P&L)')
        print('  • Trade tracking may not be properly configured')
        print()
        
        # Check for open positions
        if self.db_path.exists():
            try:
                conn = sqlite3.connect(str(self.db_path))
                cursor = conn.cursor()
                cursor.execute('SELECT COUNT(*) FROM open_positions')
                open_count = cursor.fetchone()[0]
                conn.close()
                
                if open_count > 0:
                    print(f'Note: {open_count} positions are currently OPEN')
                    print('      Wait for positions to close to see profitability')
                    print()
            except:
                pass
        
        print('Recommendation:')
        print('  1. Review open positions for unrealized gains/losses')
        print('  2. Check profit-taking configuration')
        print('  3. Monitor for position exits')
        print()
    
    def _print_recent_trades(self, trades: List[Dict], limit: int = 10):
        """Print recent trades summary"""
        print(f'Recent Trades (Last {min(limit, len(trades))}):')
        print('-' * 80)
        
        for trade in trades[:limit]:
            emoji = '🟢' if trade['net_profit'] > 0 else '🔴' if trade['net_profit'] < 0 else '⚪'
            print(f"{emoji} {trade['symbol']} {trade['side']}")
            print(f"   Entry: ${trade['entry_price']:.4f} → Exit: ${trade['exit_price']:.4f}")
            print(f"   Net P&L: ${trade['net_profit']:.2f} ({trade['profit_pct']:.2f}%)")
            print(f"   Reason: {trade['exit_reason']}")
            print()
    
    def _print_detailed_trades(self, trades: List[Dict]):
        """Print all trades with full details"""
        print('All Completed Trades (Detailed):')
        print('-' * 80)
        
        for i, trade in enumerate(trades, 1):
            emoji = '🟢' if trade['net_profit'] > 0 else '🔴' if trade['net_profit'] < 0 else '⚪'
            print(f"{i}. {emoji} {trade['symbol']} {trade['side']}")
            print(f"   Entry: ${trade['entry_price']:.6f} | Exit: ${trade['exit_price']:.6f}")
            print(f"   Size: ${trade['size_usd']:.2f} | Quantity: {trade['quantity']:.6f}")
            print(f"   Gross P&L: ${trade['gross_profit']:.2f}")
            print(f"   Fees: ${trade.get('total_fees', 0):.4f}")
            print(f"   Net P&L: ${trade['net_profit']:.2f} ({trade['profit_pct']:.2f}%)")
            print(f"   Reason: {trade['exit_reason']}")
            print(f"   Time: {trade.get('exit_time', 'N/A')}")
            print()
    
    def _print_verdict(self, stats: TradeStats):
        """Print final profitability verdict"""
        print('=' * 80)
        print('🎯 FINAL VERDICT')
        print('=' * 80)
        print()
        
        if stats.total_pnl > 0:
            print('✅ ✅ ✅ NIJA IS PROFITABLE ✅ ✅ ✅')
            print()
            print(f'   Net Profit: ${stats.total_pnl:.2f}')
            print(f'   Win Rate: {stats.win_rate:.1f}%')
            print()
            print('   NIJA is making MORE profit than losses.')
            print('   ✅ Everything is FINE for now!')
            print()
        elif stats.total_pnl < 0:
            print('❌ ❌ ❌ NIJA IS LOSING MONEY ❌ ❌ ❌')
            print()
            print(f'   Net Loss: ${stats.total_pnl:.2f}')
            print(f'   Win Rate: {stats.win_rate:.1f}%')
            print()
            print('   NIJA is losing MORE than profiting.')
            print('   ⚠️  ACTION REQUIRED!')
            print()
            print('   Recommended Actions:')
            print('   1. Review and adjust trading strategy parameters')
            print('   2. Tighten stop-loss levels (reduce max loss per trade)')
            print('   3. Widen profit targets (increase reward-to-risk ratio)')
            print('   4. Review market conditions and entry filters')
            print('   5. Consider reducing position sizes')
            print('   6. Analyze losing trades for common patterns')
            print()
        else:
            print('⚪ NIJA IS BREAK-EVEN')
            print()
            print('   No net profit or loss')
            print('   Continue monitoring performance')
            print()
        
        print('=' * 80)
    
    def export_csv(self, trades: List[Dict], filename: Optional[str] = None) -> str:
        """Export trades to CSV file"""
        if not filename:
            filename = f"nija_trades_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        
        csv_path = self.data_dir / filename
        
        with open(csv_path, 'w') as f:
            f.write("symbol,side,entry_price,exit_price,quantity,size_usd,")
            f.write("entry_fee,exit_fee,total_fees,gross_profit,net_profit,profit_pct,")
            f.write("exit_reason,entry_time,exit_time\n")
            
            for trade in trades:
                f.write(f"{trade['symbol']},{trade['side']},")
                f.write(f"{trade['entry_price']:.6f},{trade['exit_price']:.6f},")
                f.write(f"{trade['quantity']:.6f},{trade['size_usd']:.2f},")
                f.write(f"{trade.get('entry_fee', 0):.4f},{trade.get('exit_fee', 0):.4f},")
                f.write(f"{trade.get('total_fees', 0):.4f},")
                f.write(f"{trade['gross_profit']:.4f},{trade['net_profit']:.4f},{trade['profit_pct']:.2f},")
                f.write(f"{trade['exit_reason']},{trade.get('entry_time', '')},{trade.get('exit_time', '')}\n")
        
        print(f"✅ Trades exported to: {csv_path}")
        return str(csv_path)


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description='Analyze NIJA trading profitability',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  python analyze_profitability.py              # Basic report
  python analyze_profitability.py --detailed   # Detailed report with all trades
  python analyze_profitability.py --export-csv # Export trades to CSV
        '''
    )
    
    parser.add_argument('--detailed', action='store_true',
                       help='Show detailed information for all trades')
    parser.add_argument('--export-csv', action='store_true',
                       help='Export trades to CSV file')
    parser.add_argument('--data-dir', default='./data',
                       help='Directory containing trade data (default: ./data)')
    
    args = parser.parse_args()
    
    # Create analyzer
    analyzer = ProfitabilityAnalyzer(data_dir=args.data_dir)
    
    # Load trades
    trades = analyzer.load_trades()
    
    # Print report
    analyzer.print_report(trades, detailed=args.detailed)
    
    # Export if requested
    if args.export_csv and trades:
        analyzer.export_csv(trades)
        print()
    
    # Exit code based on profitability
    if not trades:
        sys.exit(2)  # No trades - cannot determine
    
    stats = analyzer.calculate_stats(trades)
    if stats.total_pnl < 0:
        sys.exit(1)  # Losing money - action required
    else:
        sys.exit(0)  # Profitable or break-even


if __name__ == '__main__':
    main()
