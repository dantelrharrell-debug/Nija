"""
NIJA Paper Trading Simulator
Mirrors live trading logic but tracks simulated positions locally
"""
import json
import os
from datetime import datetime
from typing import Dict, List, Optional

class PaperTradingAccount:
    """Simulates a trading account with virtual money"""

    def __init__(self, initial_balance: float = 10000.0):
        self.initial_balance = initial_balance
        self.balance = initial_balance
        self.positions: Dict[str, Dict] = {}
        self.trades: List[Dict] = []
        self.daily_pnl = 0.0
        self.total_pnl = 0.0
        self.data_file = "paper_trading_data.json"
        self._load_state()

    def _load_state(self):
        """Load paper trading state from disk"""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r') as f:
                    data = json.load(f)
                    self.balance = data.get('balance', self.initial_balance)
                    self.positions = data.get('positions', {})
                    self.trades = data.get('trades', [])
                    self.total_pnl = data.get('total_pnl', 0.0)
            except Exception as e:
                print(f"⚠️ Could not load paper trading state: {e}")

    def _save_state(self):
        """Save paper trading state to disk"""
        try:
            with open(self.data_file, 'w') as f:
                json.dump({
                    'balance': self.balance,
                    'positions': self.positions,
                    'trades': self.trades,
                    'total_pnl': self.total_pnl,
                    'last_updated': datetime.utcnow().isoformat()
                }, f, indent=2)
        except Exception as e:
            print(f"⚠️ Could not save paper trading state: {e}")

    def open_position(self, symbol: str, size: float, entry_price: float,
                     stop_loss: float, side: str = 'long', position_id: str = None) -> str:
        """Open a simulated position"""
        if position_id is None:
            position_id = f"{symbol}-paper-{len(self.positions) + 1}"

        position_value = size * entry_price

        # Check if enough balance
        if position_value > self.balance:
            print(f"⚠️ PAPER: Insufficient balance (${self.balance:.2f}) for ${position_value:.2f} position")
            return None

        # Create position
        self.positions[position_id] = {
            'symbol': symbol,
            'size': size,
            'entry_price': entry_price,
            'current_price': entry_price,
            'stop_loss': stop_loss,
            'side': side,
            'entry_time': datetime.utcnow().isoformat(),
            'unrealized_pnl': 0.0,
            'realized_pnl': 0.0,
            'remaining_pct': 100.0
        }

        # Reduce balance (allocated to position)
        self.balance -= position_value

        # Record trade
        self.trades.append({
            'position_id': position_id,
            'action': 'OPEN',
            'symbol': symbol,
            'size': size,
            'price': entry_price,
            'side': side,
            'timestamp': datetime.utcnow().isoformat()
        })

        self._save_state()

        print(f"📄 PAPER: Opened {side.upper()} {size} {symbol} @ ${entry_price:.2f}")
        return position_id

    def update_position(self, position_id: str, current_price: float):
        """Update position with current market price"""
        if position_id not in self.positions:
            return

        pos = self.positions[position_id]
        pos['current_price'] = current_price

        # Calculate unrealized P&L
        if pos['side'] == 'long':
            pnl = (current_price - pos['entry_price']) * pos['size']
        else:  # short
            pnl = (pos['entry_price'] - current_price) * pos['size']

        pos['unrealized_pnl'] = pnl

        # Check stop loss
        if pos['side'] == 'long' and current_price <= pos['stop_loss']:
            self.close_position(position_id, current_price, reason="STOP_LOSS")
        elif pos['side'] == 'short' and current_price >= pos['stop_loss']:
            self.close_position(position_id, current_price, reason="STOP_LOSS")

    def close_position(self, position_id: str, exit_price: float,
                      close_pct: float = 100.0, reason: str = "MANUAL") -> float:
        """Close position (fully or partially)"""
        if position_id not in self.positions:
            return 0.0

        pos = self.positions[position_id]
        close_size = pos['size'] * (close_pct / 100.0)

        # Calculate realized P&L
        if pos['side'] == 'long':
            pnl = (exit_price - pos['entry_price']) * close_size
        else:  # short
            pnl = (pos['entry_price'] - exit_price) * close_size

        # Update balance
        position_value = close_size * exit_price
        self.balance += position_value
        self.total_pnl += pnl
        self.daily_pnl += pnl

        # Record trade
        self.trades.append({
            'position_id': position_id,
            'action': f'CLOSE_{close_pct}%',
            'symbol': pos['symbol'],
            'size': close_size,
            'price': exit_price,
            'pnl': pnl,
            'reason': reason,
            'timestamp': datetime.utcnow().isoformat()
        })

        # Update or remove position
        if close_pct >= 100.0:
            print(f"📄 PAPER: Closed {pos['symbol']} @ ${exit_price:.2f} | P&L: ${pnl:+.2f} ({reason})")
            del self.positions[position_id]
        else:
            pos['size'] -= close_size
            pos['remaining_pct'] -= close_pct
            pos['realized_pnl'] += pnl
            print(f"📄 PAPER: Partial close {close_pct}% {pos['symbol']} @ ${exit_price:.2f} | P&L: ${pnl:+.2f}")

        self._save_state()
        return pnl

    def get_equity(self) -> float:
        """Calculate total account equity (balance + unrealized P&L)"""
        unrealized = sum(pos['unrealized_pnl'] for pos in self.positions.values())
        return self.balance + unrealized

    def get_stats(self) -> Dict:
        """Get account statistics"""
        winning_trades = [t for t in self.trades if t.get('pnl', 0) > 0]
        losing_trades = [t for t in self.trades if t.get('pnl', 0) < 0]

        return {
            'balance': self.balance,
            'equity': self.get_equity(),
            'total_pnl': self.total_pnl,
            'daily_pnl': self.daily_pnl,
            'total_trades': len([t for t in self.trades if 'CLOSE' in t['action']]),
            'winning_trades': len(winning_trades),
            'losing_trades': len(losing_trades),
            'win_rate': len(winning_trades) / max(len(winning_trades) + len(losing_trades), 1) * 100,
            'open_positions': len(self.positions)
        }

    def reset_daily_pnl(self):
        """Reset daily P&L counter (call at start of new trading day)"""
        self.daily_pnl = 0.0
        self._save_state()

    def print_summary(self):
        """Print account summary"""
        stats = self.get_stats()
        print("\n" + "=" * 60)
        print("📄 PAPER TRADING ACCOUNT SUMMARY")
        print("=" * 60)
        print(f"Balance:          ${stats['balance']:,.2f}")
        print(f"Equity:           ${stats['equity']:,.2f}")
        print(f"Total P&L:        ${stats['total_pnl']:+,.2f}")
        print(f"Daily P&L:        ${stats['daily_pnl']:+,.2f}")
        print(f"Total Trades:     {stats['total_trades']}")
        print(f"Win Rate:         {stats['win_rate']:.1f}%")
        print(f"Open Positions:   {stats['open_positions']}")
        print("=" * 60 + "\n")


# Singleton instance
_paper_account = None

def get_paper_account(initial_balance: float = 10000.0) -> PaperTradingAccount:
    """Get or create paper trading account singleton"""
    global _paper_account
    if _paper_account is None:
        _paper_account = PaperTradingAccount(initial_balance)
    return _paper_account
