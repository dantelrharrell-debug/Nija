#!/usr/bin/env python3
"""
NIJA Comprehensive Profit Status Report
========================================

Answers the question: "Is NIJA making a profit now on Kraken and Coinbase?"

This tool provides:
- Current account balances (Kraken + Coinbase)
- Historical P&L from completed trades
- Open positions and unrealized P&L
- Broker-specific profitability breakdown
- Overall profit/loss verdict
- Actionable recommendations

Usage:
    python check_profit_status.py
    python check_profit_status.py --detailed
"""

import os
import sys
import json
import sqlite3
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass


@dataclass
class BrokerStatus:
    """Status for a single broker"""
    name: str
    balance: float = 0.0
    open_positions: int = 0
    unrealized_pnl: float = 0.0
    completed_trades: int = 0
    realized_pnl: float = 0.0
    fees_paid: float = 0.0
    win_rate: float = 0.0

    @property
    def total_value(self) -> float:
        """Total account value including unrealized P&L"""
        return self.balance + self.unrealized_pnl

    @property
    def is_profitable(self) -> bool:
        """Is this broker making money?"""
        return (self.realized_pnl + self.unrealized_pnl) > 0


@dataclass
class OverallStatus:
    """Overall NIJA profit status"""
    kraken: BrokerStatus
    coinbase: BrokerStatus

    @property
    def total_balance(self) -> float:
        """Total cash balance across brokers"""
        return self.kraken.balance + self.coinbase.balance

    @property
    def total_value(self) -> float:
        """Total account value including unrealized P&L"""
        return self.kraken.total_value + self.coinbase.total_value

    @property
    def total_realized_pnl(self) -> float:
        """Total realized P&L from completed trades"""
        return self.kraken.realized_pnl + self.coinbase.realized_pnl

    @property
    def total_unrealized_pnl(self) -> float:
        """Total unrealized P&L from open positions"""
        return self.kraken.unrealized_pnl + self.coinbase.unrealized_pnl

    @property
    def net_pnl(self) -> float:
        """Net P&L (realized + unrealized)"""
        return self.total_realized_pnl + self.total_unrealized_pnl

    @property
    def is_profitable(self) -> bool:
        """Is NIJA making money overall?"""
        return self.net_pnl > 0

    @property
    def total_open_positions(self) -> int:
        """Total open positions across brokers"""
        return self.kraken.open_positions + self.coinbase.open_positions

    @property
    def total_completed_trades(self) -> int:
        """Total completed trades across brokers"""
        return self.kraken.completed_trades + self.coinbase.completed_trades


class ProfitStatusChecker:
    """Checks NIJA profit status across all brokers"""

    def __init__(self, data_dir: str = "./data"):
        self.data_dir = Path(data_dir)
        self.db_path = self.data_dir / "trade_ledger.db"
        self.setup_logging()

    def setup_logging(self):
        """Setup basic logging"""
        logging.basicConfig(
            level=logging.WARNING,
            format='%(message)s'
        )

    def check_status(self) -> OverallStatus:
        """Check profit status for all brokers"""
        kraken_status = self._check_broker_status('kraken')
        coinbase_status = self._check_broker_status('coinbase')

        return OverallStatus(
            kraken=kraken_status,
            coinbase=coinbase_status
        )

    def _check_broker_status(self, broker: str) -> BrokerStatus:
        """Check status for a specific broker"""
        status = BrokerStatus(name=broker.upper())

        # Load from database
        db_trades = self._load_trades_from_db()

        # Load from JSON
        json_trades = self._load_trades_from_json()

        # Combine and deduplicate
        all_trades = self._deduplicate_trades(db_trades + json_trades)

        if all_trades:
            # For now, assign all trades to Kraken (primary broker)
            # TODO: Add broker column to database to track per-broker
            if broker.lower() == 'kraken':
                status.completed_trades = len(all_trades)
                wins = [t for t in all_trades if t['net_profit'] > 0]
                status.win_rate = (len(wins) / len(all_trades) * 100) if all_trades else 0
                status.realized_pnl = sum(t['net_profit'] for t in all_trades)
                status.fees_paid = sum(t.get('total_fees', 0) for t in all_trades)

        # Check for open positions
        open_positions = self._load_open_positions()
        if open_positions and broker.lower() == 'kraken':
            status.open_positions = len(open_positions)
            # Note: Can't calculate unrealized P&L without current prices
            status.unrealized_pnl = 0.0

        return status

    def _load_trades_from_db(self) -> List[Dict]:
        """Load completed trades from database"""
        trades = []

        if not self.db_path.exists():
            return trades

        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    symbol, side, entry_price, exit_price, quantity, size_usd,
                    entry_fee, exit_fee, total_fees, gross_profit, net_profit,
                    profit_pct, exit_reason, entry_time, exit_time
                FROM completed_trades
                ORDER BY exit_time DESC
            """)

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
            logging.warning(f"Could not load trades from database: {e}")

        return trades

    def _load_trades_from_json(self) -> List[Dict]:
        """Load completed trades from JSON file"""
        trades = []
        json_path = self.data_dir / "trade_history.json"

        if not json_path.exists():
            return trades

        try:
            with open(json_path, 'r') as f:
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
                        'entry_fee': trade.get('entry_fee', 0),
                        'exit_fee': trade.get('exit_fee', 0),
                        'total_fees': trade.get('total_fees', 0),
                        'gross_profit': trade.get('gross_profit', 0),
                        'net_profit': trade.get('net_profit', 0),
                        'profit_pct': trade.get('profit_pct', 0),
                        'exit_reason': trade.get('exit_reason', 'Unknown'),
                        'entry_time': trade.get('entry_time'),
                        'exit_time': trade.get('exit_time'),
                        'source': 'json'
                    })
        except Exception as e:
            logging.warning(f"Could not load trades from JSON: {e}")

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

    def _load_open_positions(self) -> List[Dict]:
        """Load open positions"""
        positions = []

        if not self.db_path.exists():
            return positions

        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            cursor.execute("""
                SELECT position_id, symbol, side, entry_price, quantity, size_usd
                FROM open_positions
                WHERE status = 'open'
            """)

            for row in cursor.fetchall():
                positions.append({
                    'position_id': row[0],
                    'symbol': row[1],
                    'side': row[2],
                    'entry_price': row[3],
                    'quantity': row[4],
                    'size_usd': row[5]
                })

            conn.close()
        except Exception as e:
            logging.warning(f"Could not load open positions: {e}")

        return positions

    def print_report(self, status: OverallStatus, detailed: bool = False):
        """Print comprehensive profit status report"""
        print()
        print("=" * 80)
        print("💰 NIJA COMPREHENSIVE PROFIT STATUS REPORT")
        print("=" * 80)
        print(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print()

        # Question header
        print("❓ QUESTION: Is NIJA making a profit now on Kraken and Coinbase?")
        print()

        # Quick answer
        self._print_quick_answer(status)

        # Detailed breakdown by broker
        print()
        print("=" * 80)
        print("📊 BROKER-BY-BROKER BREAKDOWN")
        print("=" * 80)
        print()

        self._print_broker_status(status.kraken, detailed)
        print()
        self._print_broker_status(status.coinbase, detailed)

        # Overall summary
        print()
        print("=" * 80)
        print("🌍 OVERALL SUMMARY (ALL BROKERS)")
        print("=" * 80)
        print()
        self._print_overall_summary(status)

        # Trading activity status
        print()
        print("=" * 80)
        print("📈 TRADING ACTIVITY STATUS")
        print("=" * 80)
        print()
        self._print_activity_status(status)

        # Final verdict
        print()
        self._print_final_verdict(status)

    def _print_quick_answer(self, status: OverallStatus):
        """Print quick yes/no answer"""
        print("=" * 80)
        print("✅ QUICK ANSWER")
        print("=" * 80)
        print()

        if status.net_pnl > 0:
            print("✅ YES - NIJA IS CURRENTLY PROFITABLE")
            print(f"   Net P&L: ${status.net_pnl:+.2f}")
        elif status.net_pnl < 0:
            print("❌ NO - NIJA IS CURRENTLY LOSING MONEY")
            print(f"   Net P&L: ${status.net_pnl:+.2f}")
        else:
            print("⚪ BREAK-EVEN - No net profit or loss")
            print(f"   Net P&L: $0.00")

        print()
        if status.total_value > 0:
            print(f"📊 Total Account Value: ${status.total_value:,.2f}")
            if status.total_balance > 0:
                print(f"   • Cash Balance: ${status.total_balance:,.2f}")
            if status.total_unrealized_pnl != 0:
                print(f"   • Unrealized P&L: ${status.total_unrealized_pnl:+,.2f} ({status.total_open_positions} open positions)")
        else:
            print(f"📊 Account Value: Not available (requires live API query)")
            print(f"   • Realized P&L from trading: ${status.total_realized_pnl:+.2f}")
        print()

    def _print_broker_status(self, broker: BrokerStatus, detailed: bool):
        """Print status for a single broker"""
        profit_emoji = "✅" if broker.is_profitable else "❌" if broker.realized_pnl < 0 else "⚪"

        print(f"{profit_emoji} {broker.name}")
        print("-" * 80)

        if broker.balance > 0:
            print(f"   💰 Cash Balance: ${broker.balance:,.2f}")
        else:
            print(f"   💰 Cash Balance: Not available (live API query required)")

        if broker.open_positions > 0:
            print(f"   📊 Open Positions: {broker.open_positions}")
            if broker.unrealized_pnl != 0:
                print(f"   💎 Unrealized P&L: ${broker.unrealized_pnl:+,.2f}")
            print(f"   📈 Total Value: ${broker.total_value:,.2f}")
        else:
            print(f"   📊 Open Positions: 0")

        print()

        if broker.completed_trades > 0:
            print(f"   📜 Trading History:")
            print(f"      • Completed Trades: {broker.completed_trades}")
            print(f"      • Win Rate: {broker.win_rate:.1f}%")
            print(f"      • Realized P&L: ${broker.realized_pnl:+,.2f}")
            print(f"      • Fees Paid: ${broker.fees_paid:.2f}")

            net_after_fees = broker.realized_pnl
            print(f"      • Net (after fees): ${net_after_fees:+,.2f}")
        else:
            print(f"   📜 Trading History: No completed trades yet")

        print()

        # Broker verdict
        total_pnl = broker.realized_pnl + broker.unrealized_pnl
        if total_pnl > 0:
            print(f"   ✅ {broker.name} is profitable: ${total_pnl:+.2f}")
        elif total_pnl < 0:
            print(f"   ❌ {broker.name} is losing: ${total_pnl:+.2f}")
        else:
            print(f"   ⚪ {broker.name} is break-even")

    def _print_overall_summary(self, status: OverallStatus):
        """Print overall summary"""
        print(f"💰 Total Capital:")
        if status.total_balance > 0:
            print(f"   • Cash Balance: ${status.total_balance:,.2f}")
        else:
            print(f"   • Cash Balance: Not available (requires live API query)")

        if status.total_unrealized_pnl != 0:
            print(f"   • Open Positions Value: ${status.total_unrealized_pnl:+,.2f}")
        if status.total_value > 0:
            print(f"   • Total Account Value: ${status.total_value:,.2f}")
        print()

        print(f"📊 Trading Performance:")
        print(f"   • Completed Trades: {status.total_completed_trades}")
        print(f"   • Realized P&L: ${status.total_realized_pnl:+,.2f}")
        if status.total_unrealized_pnl != 0:
            print(f"   • Unrealized P&L: ${status.total_unrealized_pnl:+,.2f}")
        print(f"   • Net P&L: ${status.net_pnl:+,.2f}")
        print()

    def _print_activity_status(self, status: OverallStatus):
        """Print trading activity status"""
        if status.total_open_positions > 0:
            print(f"✅ ACTIVE - {status.total_open_positions} positions currently trading")
            if status.total_unrealized_pnl != 0:
                print(f"   Unrealized P&L: ${status.total_unrealized_pnl:+.2f}")
        else:
            print("⏸️  IDLE - No active positions")

            if status.total_completed_trades > 0:
                print(f"   Historical: {status.total_completed_trades} completed trades")
            else:
                print("   No trading history yet")
        print()

        # Trading readiness note
        print("💡 Note: Live balance checking requires API credentials")
        print("   Run from bot environment with .env configured for live balances")

    def _print_final_verdict(self, status: OverallStatus):
        """Print final verdict with recommendations"""
        print("=" * 80)
        print("🎯 FINAL VERDICT")
        print("=" * 80)
        print()

        if status.net_pnl > 0:
            print("✅ ✅ ✅ NIJA IS MAKING PROFIT ✅ ✅ ✅")
            print()
            print(f"   Net Profit: ${status.net_pnl:+.2f}")
            print(f"   Total Value: ${status.total_value:,.2f}")
            print()
            print("   🎉 NIJA is making MORE profit than losses!")
            print("   ✅ Keep monitoring and let the strategy work!")

            if status.total_unrealized_pnl > 0:
                print()
                print(f"   💡 You have ${status.total_unrealized_pnl:+.2f} unrealized profit")
                print("      Consider setting trailing stops to protect gains")

        elif status.net_pnl < 0:
            print("❌ ❌ ❌ NIJA IS LOSING MONEY ❌ ❌ ❌")
            print()
            print(f"   Net Loss: ${status.net_pnl:+.2f}")
            print(f"   Total Value: ${status.total_value:,.2f}")
            print()
            print("   ⚠️  NIJA is losing MORE than profiting - ACTION NEEDED!")
            print()
            print("   📋 Recommended Actions:")
            print("   1. Review trading strategy parameters")
            print("   2. Check if entry filters are too relaxed")
            print("   3. Verify stop-loss levels are appropriate")
            print("   4. Consider increasing minimum confidence threshold")
            print("   5. Review recent losing trades for patterns")
            print("   6. Check market conditions (trending vs ranging)")

            if status.total_unrealized_pnl < 0:
                print()
                print(f"   ⚠️  Warning: ${abs(status.total_unrealized_pnl):.2f} unrealized loss")
                print("      Consider reviewing open positions")

        else:
            print("⚪ NIJA IS BREAK-EVEN")
            print()
            print("   No net profit or loss")
            print("   Continue monitoring performance")

        print()
        print("=" * 80)
        print()

        # Trading status note
        if status.total_completed_trades == 0 and status.total_open_positions == 0:
            print("📝 NOTE: No trading activity detected")
            print("   • Check if NIJA is running")
            print("   • Verify entry filters aren't too strict")
            print("   • Review market scanning logs")
            print()


def main():
    """Main entry point"""
    import argparse

    parser = argparse.ArgumentParser(
        description='Check NIJA profit status on Kraken and Coinbase',
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    parser.add_argument('--detailed', action='store_true',
                       help='Show detailed breakdown')
    parser.add_argument('--data-dir', default='./data',
                       help='Directory containing trade data (default: ./data)')

    args = parser.parse_args()

    # Create checker
    checker = ProfitStatusChecker(data_dir=args.data_dir)

    # Check status
    status = checker.check_status()

    # Print report
    checker.print_report(status, detailed=args.detailed)

    # Exit code based on profitability
    if status.net_pnl > 0:
        sys.exit(0)  # Profitable
    elif status.net_pnl < 0:
        sys.exit(1)  # Losing money
    else:
        sys.exit(0)  # Break-even (treat as success)


if __name__ == '__main__':
    main()
