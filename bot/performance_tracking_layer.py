"""
NIJA Performance Tracking Layer

Live performance tracking separate from validation.
Tracks actual trading results in real-time.

Responsibilities:
- Real-time trade execution tracking
- Live P&L monitoring
- Position tracking
- Actual account balance tracking
- Real trading statistics

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
from collections import deque
import json
from pathlib import Path

try:
    from institutional_disclaimers import get_institutional_logger
except ImportError:
    from bot.institutional_disclaimers import get_institutional_logger

logger = get_institutional_logger(__name__)


@dataclass
class LiveTrade:
    """Record of a live trade execution"""
    timestamp: datetime
    symbol: str
    strategy: str
    side: str  # 'buy' or 'sell'
    entry_price: float
    exit_price: float
    quantity: float
    profit: float
    fees: float
    is_win: bool
    duration_seconds: float


class PerformanceTrackingLayer:
    """
    Performance Tracking Layer - Real-time trade and account tracking
    
    Tracks actual live trading performance separately from validation.
    """
    
    def __init__(self, data_dir: str = "./data/performance"):
        """Initialize performance tracking layer"""
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # Track last 100 trades for rolling statistics
        self.recent_trades: deque = deque(maxlen=100)
        self.all_trades: List[LiveTrade] = []
        
        # Account tracking
        self.initial_balance: Optional[float] = None
        self.current_balance: Optional[float] = None
        self.peak_balance: Optional[float] = None
        
        # Equity curve tracking
        self.equity_curve: List[Dict[str, Any]] = []
        
        # Load existing data
        self._load_historical_data()
        
        logger.info("✅ Performance Tracking Layer initialized")
    
    def set_initial_balance(self, balance: float):
        """Set the initial account balance"""
        self.initial_balance = balance
        self.current_balance = balance
        self.peak_balance = balance
        logger.info(f"Initial balance set: ${balance:,.2f}")
    
    def record_trade(self, 
                    symbol: str,
                    strategy: str,
                    side: str,
                    entry_price: float,
                    exit_price: float,
                    quantity: float,
                    profit: float,
                    fees: float,
                    duration_seconds: float = 0.0):
        """
        Record a live trade execution.
        
        Args:
            symbol: Trading pair symbol
            strategy: Strategy name that generated the trade
            side: 'buy' or 'sell'
            entry_price: Entry price
            exit_price: Exit price
            quantity: Position size
            profit: Net profit/loss
            fees: Trading fees paid
            duration_seconds: How long position was held
        """
        is_win = profit > 0
        
        trade = LiveTrade(
            timestamp=datetime.now(),
            symbol=symbol,
            strategy=strategy,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            quantity=quantity,
            profit=profit,
            fees=fees,
            is_win=is_win,
            duration_seconds=duration_seconds
        )
        
        self.recent_trades.append(trade)
        self.all_trades.append(trade)
        
        # Update balance
        if self.current_balance is not None:
            self.current_balance += profit
            
            # Update peak
            if self.current_balance > self.peak_balance:
                self.peak_balance = self.current_balance
            
            # Record equity point
            self.equity_curve.append({
                'timestamp': datetime.now().isoformat(),
                'balance': self.current_balance,
                'trade_count': len(self.all_trades)
            })
        
        logger.info(f"📊 Trade recorded: {symbol} {strategy} "
                   f"P&L=${profit:,.2f} (Fee=${fees:.2f})")
    
    def update_balance(self, new_balance: float):
        """
        Update current balance (for external balance updates).
        
        Args:
            new_balance: Current account balance
        """
        self.current_balance = new_balance
        
        if self.current_balance > self.peak_balance:
            self.peak_balance = self.current_balance
        
        # Record equity point
        self.equity_curve.append({
            'timestamp': datetime.now().isoformat(),
            'balance': self.current_balance,
            'trade_count': len(self.all_trades)
        })
    
    def get_win_rate_last_100(self) -> float:
        """
        Calculate win rate over last 100 trades.
        
        Returns:
            Win rate percentage
        """
        if not self.recent_trades:
            return 0.0
        
        winning_trades = sum(1 for t in self.recent_trades if t.is_win)
        return (winning_trades / len(self.recent_trades)) * 100.0
    
    def get_max_drawdown(self) -> float:
        """
        Calculate maximum drawdown.
        
        Returns:
            Max drawdown as percentage
        """
        if self.peak_balance is None or self.peak_balance == 0:
            return 0.0
        
        # Find the maximum drop from peak
        max_dd = 0.0
        running_peak = self.initial_balance or 0.0
        
        for point in self.equity_curve:
            balance = point['balance']
            if balance > running_peak:
                running_peak = balance
            
            drawdown = ((running_peak - balance) / running_peak) * 100.0
            max_dd = max(max_dd, drawdown)
        
        return max_dd
    
    def get_rolling_expectancy(self) -> float:
        """
        Calculate rolling expectancy over last 100 trades.
        
        Expectancy = (Win Rate * Avg Win) - (Loss Rate * Avg Loss)
        
        Returns:
            Rolling expectancy value
        """
        if not self.recent_trades:
            return 0.0
        
        winning_trades = [t for t in self.recent_trades if t.is_win]
        losing_trades = [t for t in self.recent_trades if not t.is_win]
        
        total = len(self.recent_trades)
        win_rate = len(winning_trades) / total if total > 0 else 0.0
        loss_rate = len(losing_trades) / total if total > 0 else 0.0
        
        avg_win = sum(t.profit for t in winning_trades) / len(winning_trades) if winning_trades else 0.0
        avg_loss = abs(sum(t.profit for t in losing_trades) / len(losing_trades)) if losing_trades else 0.0
        
        expectancy = (win_rate * avg_win) - (loss_rate * avg_loss)
        return expectancy
    
    def get_equity_curve(self) -> List[Dict[str, Any]]:
        """
        Get equity curve data.
        
        Returns:
            List of equity curve points
        """
        return self.equity_curve
    
    def get_statistics_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive performance statistics.
        
        Returns:
            Dictionary with performance statistics
        """
        return {
            'total_trades': len(self.all_trades),
            'win_rate_last_100': self.get_win_rate_last_100(),
            'max_drawdown_pct': self.get_max_drawdown(),
            'rolling_expectancy': self.get_rolling_expectancy(),
            'current_balance': self.current_balance,
            'initial_balance': self.initial_balance,
            'peak_balance': self.peak_balance,
            'total_return_pct': ((self.current_balance - self.initial_balance) / self.initial_balance * 100) 
                if self.initial_balance and self.initial_balance > 0 else 0.0,
            'equity_curve_points': len(self.equity_curve)
        }
    
    def export_statistics(self, filepath: Optional[str] = None) -> str:
        """
        Export statistics to JSON file.
        
        Args:
            filepath: Optional custom filepath (auto-generates if None)
            
        Returns:
            Path to exported file
        """
        if filepath is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filepath = str(self.data_dir / f"performance_stats_{timestamp}.json")
        
        stats = self.get_statistics_summary()
        stats['export_date'] = datetime.now().isoformat()
        stats['disclaimer'] = 'LIVE TRADING PERFORMANCE - PAST RESULTS DO NOT GUARANTEE FUTURE PERFORMANCE'
        
        with open(filepath, 'w') as f:
            json.dump(stats, f, indent=2)
        
        logger.info(f"📄 Statistics exported to {filepath}")
        return filepath
    
    def _load_historical_data(self):
        """Load historical performance data from disk"""
        trades_file = self.data_dir / "live_trades.json"
        
        if trades_file.exists():
            try:
                with open(trades_file, 'r') as f:
                    data = json.load(f)
                
                for trade_data in data.get('trades', []):
                    trade = LiveTrade(
                        timestamp=datetime.fromisoformat(trade_data['timestamp']),
                        symbol=trade_data['symbol'],
                        strategy=trade_data['strategy'],
                        side=trade_data['side'],
                        entry_price=trade_data['entry_price'],
                        exit_price=trade_data['exit_price'],
                        quantity=trade_data['quantity'],
                        profit=trade_data['profit'],
                        fees=trade_data['fees'],
                        is_win=trade_data['is_win'],
                        duration_seconds=trade_data.get('duration_seconds', 0.0)
                    )
                    self.all_trades.append(trade)
                    if len(self.recent_trades) < 100:
                        self.recent_trades.append(trade)
                
                # Load balance data
                if 'current_balance' in data:
                    self.current_balance = data['current_balance']
                if 'initial_balance' in data:
                    self.initial_balance = data['initial_balance']
                if 'peak_balance' in data:
                    self.peak_balance = data['peak_balance']
                
                logger.info(f"✅ Loaded {len(self.all_trades)} historical trades")
                
            except Exception as e:
                logger.error(f"Error loading historical data: {e}")
    
    def save_data(self):
        """Save performance data to disk"""
        trades_file = self.data_dir / "live_trades.json"
        
        try:
            data = {
                'last_updated': datetime.now().isoformat(),
                'current_balance': self.current_balance,
                'initial_balance': self.initial_balance,
                'peak_balance': self.peak_balance,
                'trades': [
                    {
                        'timestamp': t.timestamp.isoformat(),
                        'symbol': t.symbol,
                        'strategy': t.strategy,
                        'side': t.side,
                        'entry_price': t.entry_price,
                        'exit_price': t.exit_price,
                        'quantity': t.quantity,
                        'profit': t.profit,
                        'fees': t.fees,
                        'is_win': t.is_win,
                        'duration_seconds': t.duration_seconds
                    }
                    for t in self.all_trades
                ]
            }
            
            with open(trades_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.debug(f"Saved {len(self.all_trades)} trades to disk")
            
        except Exception as e:
            logger.error(f"Error saving performance data: {e}")


# Global singleton
_performance_layer: Optional[PerformanceTrackingLayer] = None


def get_performance_tracking_layer() -> PerformanceTrackingLayer:
    """
    Get or create the global performance tracking layer instance.
    
    Returns:
        PerformanceTrackingLayer instance
    """
    global _performance_layer
    
    if _performance_layer is None:
        _performance_layer = PerformanceTrackingLayer()
    
    return _performance_layer
