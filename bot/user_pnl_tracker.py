"""
NIJA User PnL Tracker
=====================

Per-user profit and loss tracking with persistent storage.

Features:
- Individual PnL tracking per user
- Trade history with timestamps
- Daily, weekly, monthly statistics
- Win rate and performance metrics
- Persistent JSON storage
"""

import os
import json
import logging
import threading
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from pathlib import Path

logger = logging.getLogger('nija.pnl')

# Data directory for PnL files
_data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")


@dataclass
class Trade:
    """Individual trade record."""
    timestamp: str
    symbol: str
    side: str  # 'buy' or 'sell'
    quantity: float
    price: float
    size_usd: float
    pnl_usd: Optional[float] = None
    pnl_pct: Optional[float] = None
    strategy: str = "APEX_v7.1"
    broker: str = "unknown"


@dataclass
class DailyStats:
    """Daily performance statistics."""
    date: str
    trades_count: int
    winners: int
    losers: int
    total_pnl: float
    gross_profit: float
    gross_loss: float
    win_rate: float
    avg_win: float
    avg_loss: float
    largest_win: float
    largest_loss: float


class UserPnLTracker:
    """
    Tracks profit/loss and performance metrics per user.

    Provides detailed analytics including:
    - Total PnL (all-time)
    - Daily/Weekly/Monthly breakdowns
    - Win rate and trade statistics
    - Best/worst trades
    """

    def __init__(self):
        """Initialize the user PnL tracker."""
        # Per-user locks for thread-safety
        self._user_locks: Dict[str, threading.Lock] = {}

        # Per-user trade history
        self._user_trades: Dict[str, List[Trade]] = {}

        # Per-user statistics cache
        self._user_stats: Dict[str, Dict] = {}

        # Global lock for manager initialization
        self._manager_lock = threading.Lock()

        # Ensure data directory exists
        os.makedirs(_data_dir, exist_ok=True)

        logger.info("UserPnLTracker initialized")

    def _get_pnl_file(self, user_id: str) -> str:
        """
        Get the PnL file path for a specific user.

        Args:
            user_id: User identifier

        Returns:
            str: Path to user's PnL file
        """
        # Sanitize user_id for filesystem
        safe_user_id = user_id.replace('/', '_').replace('\\', '_')
        return os.path.join(_data_dir, f"pnl_{safe_user_id}.json")

    def _get_user_lock(self, user_id: str) -> threading.Lock:
        """
        Get or create a lock for a specific user.

        Args:
            user_id: User identifier

        Returns:
            threading.Lock: User's lock
        """
        with self._manager_lock:
            if user_id not in self._user_locks:
                self._user_locks[user_id] = threading.Lock()
            return self._user_locks[user_id]

    def _load_trades(self, user_id: str) -> List[Trade]:
        """
        Load trade history from user's file.

        Args:
            user_id: User identifier

        Returns:
            List[Trade]: Trade history
        """
        pnl_file = self._get_pnl_file(user_id)

        if not os.path.exists(pnl_file):
            return []

        try:
            with open(pnl_file, 'r') as f:
                data = json.load(f)
                trades = [Trade(**trade_data) for trade_data in data.get('trades', [])]
                return trades
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Could not load PnL file for {user_id}: {e}")
            return []

    def _save_trades(self, user_id: str, trades: List[Trade]):
        """
        Save trade history to user's file.

        Args:
            user_id: User identifier
            trades: List of trades to save
        """
        pnl_file = self._get_pnl_file(user_id)

        try:
            data = {
                'user_id': user_id,
                'trades': [asdict(trade) for trade in trades],
                'last_updated': datetime.now().isoformat()
            }

            # Write to temp file first, then rename for atomicity
            temp_file = pnl_file + '.tmp'
            with open(temp_file, 'w') as f:
                json.dump(data, f, indent=2)
            os.replace(temp_file, pnl_file)
        except IOError as e:
            logger.error(f"Could not save PnL file for {user_id}: {e}")

    def record_trade(
        self,
        user_id: str,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        size_usd: float,
        pnl_usd: Optional[float] = None,
        pnl_pct: Optional[float] = None,
        strategy: str = "APEX_v7.1",
        broker: str = "unknown"
    ):
        """
        Record a trade for a user.

        Args:
            user_id: User identifier
            symbol: Trading symbol
            side: 'buy' or 'sell'
            quantity: Quantity traded
            price: Execution price
            size_usd: Trade size in USD
            pnl_usd: Profit/loss in USD (for exits)
            pnl_pct: Profit/loss percentage (for exits)
            strategy: Strategy name
            broker: Broker name
        """
        lock = self._get_user_lock(user_id)

        with lock:
            # Load existing trades
            if user_id not in self._user_trades:
                self._user_trades[user_id] = self._load_trades(user_id)

            # Create new trade record
            trade = Trade(
                timestamp=datetime.now().isoformat(),
                symbol=symbol,
                side=side,
                quantity=quantity,
                price=price,
                size_usd=size_usd,
                pnl_usd=pnl_usd,
                pnl_pct=pnl_pct,
                strategy=strategy,
                broker=broker
            )

            # Add to history
            self._user_trades[user_id].append(trade)

            # Save to file
            self._save_trades(user_id, self._user_trades[user_id])

            # Invalidate stats cache
            self._user_stats.pop(user_id, None)

            # Log the trade
            if pnl_usd is not None:
                logger.info(f"📊 {user_id} {side.upper()} {symbol}: ${size_usd:.2f} | PnL: ${pnl_usd:+.2f} ({pnl_pct:+.2f}%)")
            else:
                logger.info(f"📊 {user_id} {side.upper()} {symbol}: ${size_usd:.2f}")

    def _calculate_stats(self, user_id: str) -> Dict:
        """
        Calculate statistics for a user.

        Args:
            user_id: User identifier

        Returns:
            dict: Statistics
        """
        lock = self._get_user_lock(user_id)

        with lock:
            # Load trades
            if user_id not in self._user_trades:
                self._user_trades[user_id] = self._load_trades(user_id)

            trades = self._user_trades[user_id]

            # Filter to completed trades (with PnL)
            completed_trades = [t for t in trades if t.pnl_usd is not None]

            if not completed_trades:
                return {
                    'user_id': user_id,
                    'total_trades': len(trades),
                    'completed_trades': 0,
                    'total_pnl': 0.0,
                    'win_rate': 0.0,
                    'avg_pnl': 0.0
                }

            # Calculate overall statistics
            total_pnl = sum(t.pnl_usd for t in completed_trades)
            winners = [t for t in completed_trades if t.pnl_usd > 0]
            losers = [t for t in completed_trades if t.pnl_usd < 0]

            win_rate = (len(winners) / len(completed_trades)) * 100 if completed_trades else 0.0
            avg_win = sum(t.pnl_usd for t in winners) / len(winners) if winners else 0.0
            avg_loss = sum(t.pnl_usd for t in losers) / len(losers) if losers else 0.0
            avg_pnl = total_pnl / len(completed_trades) if completed_trades else 0.0

            # Find best and worst trades
            best_trade = max(completed_trades, key=lambda t: t.pnl_usd) if completed_trades else None
            worst_trade = min(completed_trades, key=lambda t: t.pnl_usd) if completed_trades else None

            # Calculate time-based statistics
            now = datetime.now()
            today = now.date()
            week_ago = now - timedelta(days=7)
            month_ago = now - timedelta(days=30)

            daily_trades = [t for t in completed_trades if datetime.fromisoformat(t.timestamp).date() == today]
            weekly_trades = [t for t in completed_trades if datetime.fromisoformat(t.timestamp) >= week_ago]
            monthly_trades = [t for t in completed_trades if datetime.fromisoformat(t.timestamp) >= month_ago]

            stats = {
                'user_id': user_id,
                'total_trades': len(trades),
                'completed_trades': len(completed_trades),
                'open_positions': len(trades) - len(completed_trades),

                # Overall PnL
                'total_pnl': total_pnl,
                'avg_pnl': avg_pnl,

                # Win/Loss stats
                'winners': len(winners),
                'losers': len(losers),
                'win_rate': win_rate,
                'avg_win': avg_win,
                'avg_loss': avg_loss,
                'profit_factor': abs(avg_win / avg_loss) if avg_loss != 0 else 0.0,

                # Best/Worst
                'best_trade': {
                    'symbol': best_trade.symbol,
                    'pnl': best_trade.pnl_usd,
                    'date': best_trade.timestamp
                } if best_trade else None,
                'worst_trade': {
                    'symbol': worst_trade.symbol,
                    'pnl': worst_trade.pnl_usd,
                    'date': worst_trade.timestamp
                } if worst_trade else None,

                # Time-based
                'daily_pnl': sum(t.pnl_usd for t in daily_trades),
                'daily_trades': len(daily_trades),
                'weekly_pnl': sum(t.pnl_usd for t in weekly_trades),
                'weekly_trades': len(weekly_trades),
                'monthly_pnl': sum(t.pnl_usd for t in monthly_trades),
                'monthly_trades': len(monthly_trades),

                'last_updated': datetime.now().isoformat()
            }

            return stats

    def get_stats(self, user_id: str, force_refresh: bool = False) -> Dict:
        """
        Get statistics for a user.

        Args:
            user_id: User identifier
            force_refresh: Force recalculation of stats

        Returns:
            dict: Statistics
        """
        # Check cache
        if not force_refresh and user_id in self._user_stats:
            return self._user_stats[user_id]

        # Calculate and cache
        stats = self._calculate_stats(user_id)
        self._user_stats[user_id] = stats

        return stats

    def get_recent_trades(self, user_id: str, limit: int = 10) -> List[Dict]:
        """
        Get recent trades for a user.

        Args:
            user_id: User identifier
            limit: Maximum number of trades to return

        Returns:
            List[dict]: Recent trades
        """
        lock = self._get_user_lock(user_id)

        with lock:
            # Load trades
            if user_id not in self._user_trades:
                self._user_trades[user_id] = self._load_trades(user_id)

            trades = self._user_trades[user_id]

            # Return most recent trades
            recent = trades[-limit:] if len(trades) > limit else trades
            return [asdict(t) for t in reversed(recent)]

    def get_daily_breakdown(self, user_id: str, days: int = 7) -> List[DailyStats]:
        """
        Get daily breakdown of performance.

        Args:
            user_id: User identifier
            days: Number of days to include

        Returns:
            List[DailyStats]: Daily statistics
        """
        lock = self._get_user_lock(user_id)

        with lock:
            # Load trades
            if user_id not in self._user_trades:
                self._user_trades[user_id] = self._load_trades(user_id)

            trades = self._user_trades[user_id]
            completed_trades = [t for t in trades if t.pnl_usd is not None]

            # Group by date
            daily_data: Dict[str, List[Trade]] = {}
            for trade in completed_trades:
                date = datetime.fromisoformat(trade.timestamp).date().isoformat()
                if date not in daily_data:
                    daily_data[date] = []
                daily_data[date].append(trade)

            # Calculate stats for each day
            daily_stats = []
            for date, day_trades in sorted(daily_data.items(), reverse=True)[:days]:
                winners = [t for t in day_trades if t.pnl_usd > 0]
                losers = [t for t in day_trades if t.pnl_usd < 0]

                total_pnl = sum(t.pnl_usd for t in day_trades)
                gross_profit = sum(t.pnl_usd for t in winners)
                gross_loss = sum(t.pnl_usd for t in losers)

                stats = DailyStats(
                    date=date,
                    trades_count=len(day_trades),
                    winners=len(winners),
                    losers=len(losers),
                    total_pnl=total_pnl,
                    gross_profit=gross_profit,
                    gross_loss=gross_loss,
                    win_rate=(len(winners) / len(day_trades)) * 100 if day_trades else 0.0,
                    avg_win=gross_profit / len(winners) if winners else 0.0,
                    avg_loss=gross_loss / len(losers) if losers else 0.0,
                    largest_win=max((t.pnl_usd for t in winners), default=0.0),
                    largest_loss=min((t.pnl_usd for t in losers), default=0.0)
                )
                daily_stats.append(stats)

            return daily_stats


# Global singleton instance
_user_pnl_tracker: Optional[UserPnLTracker] = None
_init_lock = threading.Lock()


def get_user_pnl_tracker() -> UserPnLTracker:
    """
    Get the global user PnL tracker instance (singleton).

    Returns:
        UserPnLTracker: Global instance
    """
    global _user_pnl_tracker

    with _init_lock:
        if _user_pnl_tracker is None:
            _user_pnl_tracker = UserPnLTracker()
        return _user_pnl_tracker


__all__ = [
    'UserPnLTracker',
    'Trade',
    'DailyStats',
    'get_user_pnl_tracker',
]
