#!/usr/bin/env python3
"""
Monitor Paper Trading Performance
Shows simulated account balance, positions, and P&L
"""
import sys
import os

# Add bot directory to path
sys.path.insert(0, os.path.dirname(__file__))

from paper_trading import get_paper_account

def main():
    """Display paper trading account summary"""
    paper = get_paper_account()

    # Print full summary
    paper.print_summary()

    # Show open positions
    if paper.positions:
        print("📊 OPEN POSITIONS:")
        print("-" * 60)
        for pos_id, pos in paper.positions.items():
            symbol = pos['symbol']
            size = pos['size']
            entry = pos['entry_price']
            current = pos['current_price']
            pnl = pos['unrealized_pnl']
            pnl_pct = (pnl / (size * entry)) * 100

            print(f"{symbol:12} | Size: {size:10.6f} | Entry: ${entry:8.2f} | Current: ${current:8.2f}")
            print(f"{'':12} | P&L: ${pnl:+8.2f} ({pnl_pct:+.2f}%) | Stop: ${pos['stop_loss']:.2f}")
            print("-" * 60)

    # Show recent trades
    recent_trades = [t for t in paper.trades if 'CLOSE' in t.get('action', '')][-10:]
    if recent_trades:
        print("\n📜 RECENT CLOSED TRADES (Last 10):")
        print("-" * 60)
        for trade in recent_trades:
            symbol = trade['symbol']
            action = trade['action']
            price = trade['price']
            pnl = trade.get('pnl', 0)
            reason = trade.get('reason', 'N/A')
            timestamp = trade['timestamp'][:19]  # Remove microseconds

            pnl_indicator = "✅" if pnl > 0 else "❌"
            print(f"{pnl_indicator} {symbol:12} | {action:10} @ ${price:8.2f} | P&L: ${pnl:+8.2f} | {reason}")
            print(f"{'':14}   {timestamp}")
            print("-" * 60)

if __name__ == "__main__":
    main()
