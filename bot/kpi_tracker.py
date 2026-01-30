"""
NIJA KPI (Key Performance Indicator) Tracker

Real-time tracking and calculation of critical trading performance metrics.
Provides comprehensive KPI monitoring for the NIJA trading bot.

Key Performance Indicators:
- Win Rate (%)
- Profit Factor
- Sharpe Ratio
- Sortino Ratio
- Maximum Drawdown (%)
- Average Win/Loss
- Trade Frequency
- Risk-Adjusted Returns
- Total Return (%)
- Daily/Weekly/Monthly Returns

Author: NIJA Trading Systems
Version: 1.0
Date: January 30, 2026
"""

import logging
import json
import numpy as np
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, asdict
from collections import deque
import threading

logger = logging.getLogger(__name__)


@dataclass
class KPISnapshot:
    """Single point-in-time KPI snapshot"""
    timestamp: str
    
    # Return metrics
    total_return_pct: float
    daily_return_pct: float
    weekly_return_pct: float
    monthly_return_pct: float
    
    # Risk metrics
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    current_drawdown_pct: float
    
    # Trade statistics
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate_pct: float
    profit_factor: float
    avg_win: float
    avg_loss: float
    
    # Position metrics
    active_positions: int
    total_exposure_pct: float
    
    # Time metrics
    trades_per_day: float
    avg_hold_time_hours: float
    
    # Account metrics
    account_value: float
    cash_balance: float
    unrealized_pnl: float
    realized_pnl_total: float


class KPITracker:
    """
    Real-time KPI tracking and calculation
    
    Responsibilities:
    - Calculate all key performance indicators
    - Track performance over time
    - Persist KPI history
    - Provide real-time KPI access
    - Alert on KPI thresholds
    """
    
    def __init__(
        self,
        initial_capital: float,
        data_dir: str = "./data/kpi",
        history_size: int = 1000,
        risk_free_rate: float = 0.02
    ):
        """
        Initialize KPI Tracker
        
        Args:
            initial_capital: Starting capital amount
            data_dir: Directory to store KPI data
            history_size: Number of snapshots to keep in memory
            risk_free_rate: Annual risk-free rate for Sharpe calculation (default: 2%)
        """
        self.initial_capital = initial_capital
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.risk_free_rate = risk_free_rate
        
        # KPI history (in-memory circular buffer)
        self.kpi_history: deque = deque(maxlen=history_size)
        
        # Trade history for calculations
        self.trade_history: List[Dict[str, Any]] = []
        
        # Current state
        self.current_capital = initial_capital
        self.peak_capital = initial_capital
        self.current_positions: List[Dict[str, Any]] = []
        
        # Performance tracking
        self.daily_returns: List[float] = []
        self.equity_curve: List[Tuple[datetime, float]] = []
        
        # Thread safety
        self._lock = threading.Lock()
        
        # Load existing data if available
        self._load_state()
        
        logger.info(f"✅ KPI Tracker initialized with ${initial_capital:,.2f} initial capital")
    
    def update(
        self,
        account_value: float,
        cash_balance: float,
        positions: List[Dict[str, Any]],
        unrealized_pnl: float = 0.0,
        realized_pnl_total: float = 0.0
    ) -> KPISnapshot:
        """
        Update KPIs with current account state
        
        Args:
            account_value: Total account value
            cash_balance: Available cash
            positions: List of active positions
            unrealized_pnl: Total unrealized P&L
            realized_pnl_total: Cumulative realized P&L
            
        Returns:
            Current KPI snapshot
        """
        with self._lock:
            self.current_capital = account_value
            self.current_positions = positions
            
            # Update peak capital for drawdown calculation
            if account_value > self.peak_capital:
                self.peak_capital = account_value
            
            # Add to equity curve
            self.equity_curve.append((datetime.now(), account_value))
            
            # Calculate daily return if we have history
            if len(self.equity_curve) > 1:
                prev_value = self.equity_curve[-2][1]
                daily_return = ((account_value - prev_value) / prev_value) * 100
                self.daily_returns.append(daily_return)
            
            # Calculate all KPIs
            snapshot = self._calculate_kpis(
                account_value=account_value,
                cash_balance=cash_balance,
                positions=positions,
                unrealized_pnl=unrealized_pnl,
                realized_pnl_total=realized_pnl_total
            )
            
            # Add to history
            self.kpi_history.append(snapshot)
            
            # Persist state periodically (every 10 updates)
            if len(self.kpi_history) % 10 == 0:
                self._save_state()
            
            return snapshot
    
    def record_trade(
        self,
        symbol: str,
        entry_price: float,
        exit_price: float,
        quantity: float,
        side: str,
        pnl: float,
        entry_time: datetime,
        exit_time: datetime,
        fees: float = 0.0
    ):
        """
        Record a completed trade
        
        Args:
            symbol: Trading pair symbol
            entry_price: Entry price
            exit_price: Exit price
            quantity: Position size
            side: 'long' or 'short'
            pnl: Realized profit/loss
            entry_time: Trade entry timestamp
            exit_time: Trade exit timestamp
            fees: Trading fees paid
        """
        with self._lock:
            trade = {
                'symbol': symbol,
                'entry_price': entry_price,
                'exit_price': exit_price,
                'quantity': quantity,
                'side': side,
                'pnl': pnl,
                'pnl_after_fees': pnl - fees,
                'entry_time': entry_time.isoformat(),
                'exit_time': exit_time.isoformat(),
                'hold_time_hours': (exit_time - entry_time).total_seconds() / 3600,
                'fees': fees,
                'timestamp': datetime.now().isoformat()
            }
            
            self.trade_history.append(trade)
            logger.info(f"📊 Trade recorded: {symbol} {side} P&L: ${pnl:,.2f}")
    
    def _calculate_kpis(
        self,
        account_value: float,
        cash_balance: float,
        positions: List[Dict[str, Any]],
        unrealized_pnl: float,
        realized_pnl_total: float
    ) -> KPISnapshot:
        """Calculate all KPIs from current state"""
        
        # Return metrics
        total_return_pct = ((account_value - self.initial_capital) / self.initial_capital) * 100
        
        # Calculate period returns
        daily_return_pct = self.daily_returns[-1] if self.daily_returns else 0.0
        weekly_return_pct = self._calculate_period_return(days=7)
        monthly_return_pct = self._calculate_period_return(days=30)
        
        # Trade statistics
        winning_trades = sum(1 for t in self.trade_history if t['pnl_after_fees'] > 0)
        losing_trades = sum(1 for t in self.trade_history if t['pnl_after_fees'] < 0)
        total_trades = len(self.trade_history)
        
        win_rate_pct = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
        
        # Average win/loss
        wins = [t['pnl_after_fees'] for t in self.trade_history if t['pnl_after_fees'] > 0]
        losses = [abs(t['pnl_after_fees']) for t in self.trade_history if t['pnl_after_fees'] < 0]
        
        avg_win = np.mean(wins) if wins else 0.0
        avg_loss = np.mean(losses) if losses else 0.0
        
        # Profit factor
        total_wins = sum(wins) if wins else 0.0
        total_losses = sum(losses) if losses else 0.0
        profit_factor = (total_wins / total_losses) if total_losses > 0 else float('inf')
        
        # Risk metrics
        sharpe_ratio = self._calculate_sharpe_ratio()
        sortino_ratio = self._calculate_sortino_ratio()
        
        # Drawdown
        max_drawdown_pct = ((self.peak_capital - account_value) / self.peak_capital * 100) if self.peak_capital > 0 else 0.0
        current_drawdown_pct = ((self.peak_capital - account_value) / self.peak_capital * 100) if self.peak_capital > 0 else 0.0
        
        # Position metrics
        active_positions = len(positions)
        total_exposure = sum(p.get('value', 0) for p in positions)
        total_exposure_pct = (total_exposure / account_value * 100) if account_value > 0 else 0.0
        
        # Time metrics
        if self.equity_curve:
            days_trading = (datetime.now() - self.equity_curve[0][0]).days + 1
            trades_per_day = total_trades / days_trading if days_trading > 0 else 0.0
        else:
            trades_per_day = 0.0
        
        avg_hold_time = np.mean([t['hold_time_hours'] for t in self.trade_history]) if self.trade_history else 0.0
        
        return KPISnapshot(
            timestamp=datetime.now().isoformat(),
            total_return_pct=total_return_pct,
            daily_return_pct=daily_return_pct,
            weekly_return_pct=weekly_return_pct,
            monthly_return_pct=monthly_return_pct,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            max_drawdown_pct=max_drawdown_pct,
            current_drawdown_pct=current_drawdown_pct,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate_pct=win_rate_pct,
            profit_factor=profit_factor,
            avg_win=avg_win,
            avg_loss=avg_loss,
            active_positions=active_positions,
            total_exposure_pct=total_exposure_pct,
            trades_per_day=trades_per_day,
            avg_hold_time_hours=avg_hold_time,
            account_value=account_value,
            cash_balance=cash_balance,
            unrealized_pnl=unrealized_pnl,
            realized_pnl_total=realized_pnl_total
        )
    
    def _calculate_period_return(self, days: int) -> float:
        """Calculate return over a specific period"""
        if len(self.equity_curve) < 2:
            return 0.0
        
        cutoff_time = datetime.now() - timedelta(days=days)
        
        # Find the earliest value within the period
        period_values = [v for t, v in self.equity_curve if t >= cutoff_time]
        
        if len(period_values) < 2:
            return 0.0
        
        start_value = period_values[0]
        end_value = period_values[-1]
        
        return ((end_value - start_value) / start_value) * 100
    
    def _calculate_sharpe_ratio(self) -> float:
        """Calculate Sharpe ratio from daily returns"""
        if len(self.daily_returns) < 2:
            return 0.0
        
        returns_array = np.array(self.daily_returns) / 100  # Convert to decimal
        
        # Annualize
        daily_risk_free = self.risk_free_rate / 252  # 252 trading days
        excess_returns = returns_array - daily_risk_free
        
        if len(excess_returns) == 0 or np.std(excess_returns) == 0:
            return 0.0
        
        sharpe = np.mean(excess_returns) / np.std(excess_returns)
        
        # Annualize
        return sharpe * np.sqrt(252)
    
    def _calculate_sortino_ratio(self) -> float:
        """Calculate Sortino ratio (penalizes only downside volatility)"""
        if len(self.daily_returns) < 2:
            return 0.0
        
        returns_array = np.array(self.daily_returns) / 100  # Convert to decimal
        
        # Annualize
        daily_risk_free = self.risk_free_rate / 252
        excess_returns = returns_array - daily_risk_free
        
        # Calculate downside deviation (only negative returns)
        downside_returns = excess_returns[excess_returns < 0]
        
        if len(downside_returns) == 0:
            return float('inf')  # No downside = infinite Sortino
        
        downside_std = np.std(downside_returns)
        
        if downside_std == 0:
            return 0.0
        
        sortino = np.mean(excess_returns) / downside_std
        
        # Annualize
        return sortino * np.sqrt(252)
    
    def get_current_kpis(self) -> Optional[KPISnapshot]:
        """Get most recent KPI snapshot"""
        with self._lock:
            if self.kpi_history:
                return self.kpi_history[-1]
            return None
    
    def get_kpi_history(self, hours: int = 24) -> List[KPISnapshot]:
        """
        Get KPI history for the specified time period
        
        Args:
            hours: Number of hours of history to retrieve
            
        Returns:
            List of KPI snapshots
        """
        with self._lock:
            cutoff_time = datetime.now() - timedelta(hours=hours)
            
            return [
                kpi for kpi in self.kpi_history
                if datetime.fromisoformat(kpi.timestamp) >= cutoff_time
            ]
    
    def get_kpi_summary(self) -> Dict[str, Any]:
        """Get summary of current KPIs in dict format"""
        current = self.get_current_kpis()
        
        if not current:
            return {
                'status': 'no_data',
                'message': 'No KPI data available yet'
            }
        
        return {
            'status': 'active',
            'timestamp': current.timestamp,
            'returns': {
                'total': current.total_return_pct,
                'daily': current.daily_return_pct,
                'weekly': current.weekly_return_pct,
                'monthly': current.monthly_return_pct
            },
            'risk_metrics': {
                'sharpe_ratio': current.sharpe_ratio,
                'sortino_ratio': current.sortino_ratio,
                'max_drawdown': current.max_drawdown_pct,
                'current_drawdown': current.current_drawdown_pct
            },
            'trade_stats': {
                'total_trades': current.total_trades,
                'winning_trades': current.winning_trades,
                'losing_trades': current.losing_trades,
                'win_rate': current.win_rate_pct,
                'profit_factor': current.profit_factor,
                'avg_win': current.avg_win,
                'avg_loss': current.avg_loss
            },
            'position_metrics': {
                'active_positions': current.active_positions,
                'total_exposure': current.total_exposure_pct
            },
            'account': {
                'value': current.account_value,
                'cash': current.cash_balance,
                'unrealized_pnl': current.unrealized_pnl,
                'realized_pnl': current.realized_pnl_total
            }
        }
    
    def _save_state(self):
        """Save KPI state to disk"""
        try:
            state_file = self.data_dir / "kpi_state.json"
            
            state = {
                'initial_capital': self.initial_capital,
                'current_capital': self.current_capital,
                'peak_capital': self.peak_capital,
                'kpi_history': [asdict(kpi) for kpi in self.kpi_history],
                'trade_history': self.trade_history,
                'daily_returns': self.daily_returns,
                'equity_curve': [(t.isoformat(), v) for t, v in self.equity_curve],
                'last_updated': datetime.now().isoformat()
            }
            
            with open(state_file, 'w') as f:
                json.dump(state, f, indent=2)
            
            logger.debug(f"KPI state saved to {state_file}")
            
        except Exception as e:
            logger.error(f"Error saving KPI state: {e}")
    
    def _load_state(self):
        """Load KPI state from disk"""
        try:
            state_file = self.data_dir / "kpi_state.json"
            
            if not state_file.exists():
                logger.info("No existing KPI state found, starting fresh")
                return
            
            with open(state_file, 'r') as f:
                state = json.load(f)
            
            self.initial_capital = state.get('initial_capital', self.initial_capital)
            self.current_capital = state.get('current_capital', self.initial_capital)
            self.peak_capital = state.get('peak_capital', self.initial_capital)
            self.trade_history = state.get('trade_history', [])
            self.daily_returns = state.get('daily_returns', [])
            
            # Restore equity curve
            equity_data = state.get('equity_curve', [])
            self.equity_curve = [(datetime.fromisoformat(t), v) for t, v in equity_data]
            
            # Restore KPI history
            kpi_data = state.get('kpi_history', [])
            for kpi_dict in kpi_data:
                self.kpi_history.append(KPISnapshot(**kpi_dict))
            
            logger.info(f"✅ KPI state loaded: {len(self.trade_history)} trades, {len(self.kpi_history)} snapshots")
            
        except Exception as e:
            logger.error(f"Error loading KPI state: {e}")


# Global singleton instance
_kpi_tracker: Optional[KPITracker] = None


def get_kpi_tracker(initial_capital: float = 10000.0) -> KPITracker:
    """
    Get or create global KPI tracker instance
    
    Args:
        initial_capital: Starting capital (only used on first creation)
        
    Returns:
        KPITracker instance
    """
    global _kpi_tracker
    
    if _kpi_tracker is None:
        _kpi_tracker = KPITracker(initial_capital=initial_capital)
    
    return _kpi_tracker


def reset_kpi_tracker():
    """Reset global KPI tracker (use with caution)"""
    global _kpi_tracker
    _kpi_tracker = None
    logger.warning("⚠️ KPI Tracker reset")
