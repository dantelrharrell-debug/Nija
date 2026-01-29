"""
NIJA Performance Metrics Calculator

Investor-grade performance metrics including:
- Daily NAV (Net Asset Value)
- Equity curves
- Drawdown curves
- Sharpe ratio tracking
- Monthly performance reports

Author: NIJA Trading Systems
Version: 1.0
Date: January 29, 2026
"""

import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
import json

logger = logging.getLogger("nija.performance_metrics")


@dataclass
class PerformanceSnapshot:
    """Single point-in-time performance snapshot"""
    timestamp: datetime
    nav: float  # Net Asset Value
    equity: float  # Total equity (cash + positions)
    cash: float  # Available cash
    positions_value: float  # Value of open positions
    unrealized_pnl: float  # Unrealized profit/loss
    realized_pnl_today: float  # Realized P&L for the day
    total_trades: int  # Cumulative trades
    winning_trades: int  # Cumulative winning trades
    losing_trades: int  # Cumulative losing trades


@dataclass
class PerformanceMetrics:
    """Comprehensive performance metrics"""
    # Returns
    total_return_pct: float
    daily_return_pct: float
    monthly_return_pct: float
    annualized_return_pct: float
    
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
    avg_win: float
    avg_loss: float
    profit_factor: float
    
    # Time metrics
    days_trading: int
    avg_trades_per_day: float
    longest_winning_streak: int
    longest_losing_streak: int
    
    # Volatility
    daily_volatility_pct: float
    annualized_volatility_pct: float


class PerformanceMetricsCalculator:
    """
    Calculate investor-grade performance metrics
    
    Responsibilities:
    - Track daily NAV (Net Asset Value)
    - Calculate equity curves
    - Generate drawdown curves
    - Compute Sharpe and Sortino ratios
    - Produce monthly performance reports
    """
    
    def __init__(self, initial_capital: float, data_dir: str = "./data/performance"):
        """
        Initialize performance metrics calculator
        
        Args:
            initial_capital: Starting capital amount
            data_dir: Directory to store performance data
        """
        self.initial_capital = initial_capital
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True, parents=True)
        
        # Performance tracking
        self.snapshots: List[PerformanceSnapshot] = []
        self.daily_returns: List[float] = []
        self.equity_curve: List[Tuple[datetime, float]] = []
        self.drawdown_curve: List[Tuple[datetime, float]] = []
        
        # State
        self.peak_equity = initial_capital
        self.current_equity = initial_capital
        
        # Load existing data
        self._load_historical_data()
        
        logger.info(f"✅ Performance Metrics Calculator initialized with ${initial_capital:,.2f}")
    
    def record_snapshot(self, snapshot: PerformanceSnapshot) -> None:
        """
        Record a performance snapshot
        
        Args:
            snapshot: Performance snapshot to record
        """
        self.snapshots.append(snapshot)
        self.current_equity = snapshot.equity
        
        # Update equity curve
        self.equity_curve.append((snapshot.timestamp, snapshot.equity))
        
        # Update peak and calculate drawdown
        if snapshot.equity > self.peak_equity:
            self.peak_equity = snapshot.equity
        
        drawdown_pct = ((self.peak_equity - snapshot.equity) / self.peak_equity * 100) if self.peak_equity > 0 else 0.0
        self.drawdown_curve.append((snapshot.timestamp, drawdown_pct))
        
        # Calculate daily return if we have previous data
        if len(self.snapshots) > 1:
            prev_snapshot = self.snapshots[-2]
            if prev_snapshot.equity > 0:
                daily_return = ((snapshot.equity - prev_snapshot.equity) / prev_snapshot.equity) * 100
                self.daily_returns.append(daily_return)
        
        logger.debug(f"Recorded snapshot: NAV=${snapshot.nav:,.2f}, Equity=${snapshot.equity:,.2f}")
    
    def calculate_nav(self, cash: float, positions_value: float, unrealized_pnl: float = 0.0) -> float:
        """
        Calculate Net Asset Value
        
        Args:
            cash: Available cash
            positions_value: Market value of positions
            unrealized_pnl: Unrealized profit/loss (optional, may be included in positions_value)
        
        Returns:
            Net Asset Value
        """
        # NAV = Cash + Positions Market Value
        # Note: positions_value should already include unrealized P&L
        nav = cash + positions_value
        return nav
    
    def get_equity_curve(self, start_date: Optional[datetime] = None, 
                         end_date: Optional[datetime] = None) -> pd.DataFrame:
        """
        Get equity curve as pandas DataFrame
        
        Args:
            start_date: Optional start date filter
            end_date: Optional end date filter
        
        Returns:
            DataFrame with timestamp and equity columns
        """
        if not self.equity_curve:
            return pd.DataFrame(columns=['timestamp', 'equity'])
        
        df = pd.DataFrame(self.equity_curve, columns=['timestamp', 'equity'])
        
        if start_date:
            df = df[df['timestamp'] >= start_date]
        if end_date:
            df = df[df['timestamp'] <= end_date]
        
        return df
    
    def get_drawdown_curve(self, start_date: Optional[datetime] = None,
                           end_date: Optional[datetime] = None) -> pd.DataFrame:
        """
        Get drawdown curve as pandas DataFrame
        
        Args:
            start_date: Optional start date filter
            end_date: Optional end date filter
        
        Returns:
            DataFrame with timestamp and drawdown_pct columns
        """
        if not self.drawdown_curve:
            return pd.DataFrame(columns=['timestamp', 'drawdown_pct'])
        
        df = pd.DataFrame(self.drawdown_curve, columns=['timestamp', 'drawdown_pct'])
        
        if start_date:
            df = df[df['timestamp'] >= start_date]
        if end_date:
            df = df[df['timestamp'] <= end_date]
        
        return df
    
    def calculate_sharpe_ratio(self, risk_free_rate: float = 0.02) -> float:
        """
        Calculate Sharpe ratio
        
        Args:
            risk_free_rate: Annual risk-free rate (default: 2%)
        
        Returns:
            Sharpe ratio (annualized)
        """
        if len(self.daily_returns) < 2:
            return 0.0
        
        returns_array = np.array(self.daily_returns)
        
        # Convert to decimal
        returns_decimal = returns_array / 100.0
        
        # Calculate excess returns
        daily_risk_free = risk_free_rate / 252  # Assume 252 trading days
        excess_returns = returns_decimal - daily_risk_free
        
        # Calculate Sharpe ratio
        if np.std(excess_returns) == 0:
            return 0.0
        
        sharpe = np.mean(excess_returns) / np.std(excess_returns)
        
        # Annualize (assuming 252 trading days)
        sharpe_annualized = sharpe * np.sqrt(252)
        
        return sharpe_annualized
    
    def calculate_sortino_ratio(self, risk_free_rate: float = 0.02) -> float:
        """
        Calculate Sortino ratio (like Sharpe but only penalizes downside volatility)
        
        Args:
            risk_free_rate: Annual risk-free rate (default: 2%)
        
        Returns:
            Sortino ratio (annualized)
        """
        if len(self.daily_returns) < 2:
            return 0.0
        
        returns_array = np.array(self.daily_returns)
        returns_decimal = returns_array / 100.0
        
        daily_risk_free = risk_free_rate / 252
        excess_returns = returns_decimal - daily_risk_free
        
        # Calculate downside deviation (only negative returns)
        negative_returns = excess_returns[excess_returns < 0]
        
        if len(negative_returns) == 0 or np.std(negative_returns) == 0:
            return 0.0
        
        downside_deviation = np.std(negative_returns)
        sortino = np.mean(excess_returns) / downside_deviation
        
        # Annualize
        sortino_annualized = sortino * np.sqrt(252)
        
        return sortino_annualized
    
    def calculate_max_drawdown(self) -> Tuple[float, Optional[datetime], Optional[datetime]]:
        """
        Calculate maximum drawdown and its dates
        
        Returns:
            Tuple of (max_drawdown_pct, start_date, end_date)
        """
        if not self.drawdown_curve:
            return 0.0, None, None
        
        max_dd = 0.0
        max_dd_date = None
        
        for timestamp, dd_pct in self.drawdown_curve:
            if dd_pct > max_dd:
                max_dd = dd_pct
                max_dd_date = timestamp
        
        # Find start of max drawdown period
        start_date = None
        if max_dd_date:
            for i, (timestamp, dd_pct) in enumerate(self.drawdown_curve):
                if timestamp >= max_dd_date:
                    break
                if dd_pct == 0:  # Previous peak
                    start_date = timestamp
        
        return max_dd, start_date, max_dd_date
    
    def calculate_metrics(self) -> PerformanceMetrics:
        """
        Calculate comprehensive performance metrics
        
        Returns:
            PerformanceMetrics object with all metrics
        """
        if not self.snapshots:
            # Return zero metrics if no data
            return PerformanceMetrics(
                total_return_pct=0.0, daily_return_pct=0.0, monthly_return_pct=0.0,
                annualized_return_pct=0.0, sharpe_ratio=0.0, sortino_ratio=0.0,
                max_drawdown_pct=0.0, current_drawdown_pct=0.0, total_trades=0,
                winning_trades=0, losing_trades=0, win_rate_pct=0.0, avg_win=0.0,
                avg_loss=0.0, profit_factor=0.0, days_trading=0, avg_trades_per_day=0.0,
                longest_winning_streak=0, longest_losing_streak=0,
                daily_volatility_pct=0.0, annualized_volatility_pct=0.0
            )
        
        latest = self.snapshots[-1]
        
        # Calculate returns
        total_return_pct = ((self.current_equity - self.initial_capital) / self.initial_capital * 100) if self.initial_capital > 0 else 0.0
        
        daily_return_pct = self.daily_returns[-1] if self.daily_returns else 0.0
        
        # Calculate days trading
        if len(self.snapshots) > 1:
            days_trading = (self.snapshots[-1].timestamp - self.snapshots[0].timestamp).days
            days_trading = max(days_trading, 1)  # At least 1 day
        else:
            days_trading = 1
        
        # Annualized return
        if days_trading > 0:
            annualized_return_pct = (((self.current_equity / self.initial_capital) ** (365 / days_trading)) - 1) * 100
        else:
            annualized_return_pct = 0.0
        
        # Monthly return (approximate)
        monthly_return_pct = annualized_return_pct / 12
        
        # Risk metrics
        sharpe_ratio = self.calculate_sharpe_ratio()
        sortino_ratio = self.calculate_sortino_ratio()
        max_drawdown_pct, _, _ = self.calculate_max_drawdown()
        current_drawdown_pct = ((self.peak_equity - self.current_equity) / self.peak_equity * 100) if self.peak_equity > 0 else 0.0
        
        # Trade statistics
        total_trades = latest.total_trades
        winning_trades = latest.winning_trades
        losing_trades = latest.losing_trades
        win_rate_pct = (winning_trades / total_trades * 100) if total_trades > 0 else 0.0
        
        # Calculate average win/loss and profit factor
        # Note: These would need to be calculated from trade history
        # For now, using approximations
        avg_win = 0.0
        avg_loss = 0.0
        profit_factor = 0.0
        
        # Streaks
        longest_winning_streak = 0
        longest_losing_streak = 0
        
        # Volatility
        daily_volatility_pct = np.std(self.daily_returns) if len(self.daily_returns) > 1 else 0.0
        annualized_volatility_pct = daily_volatility_pct * np.sqrt(252)
        
        # Average trades per day
        avg_trades_per_day = total_trades / days_trading if days_trading > 0 else 0.0
        
        return PerformanceMetrics(
            total_return_pct=total_return_pct,
            daily_return_pct=daily_return_pct,
            monthly_return_pct=monthly_return_pct,
            annualized_return_pct=annualized_return_pct,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            max_drawdown_pct=max_drawdown_pct,
            current_drawdown_pct=current_drawdown_pct,
            total_trades=total_trades,
            winning_trades=winning_trades,
            losing_trades=losing_trades,
            win_rate_pct=win_rate_pct,
            avg_win=avg_win,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
            days_trading=days_trading,
            avg_trades_per_day=avg_trades_per_day,
            longest_winning_streak=longest_winning_streak,
            longest_losing_streak=longest_losing_streak,
            daily_volatility_pct=daily_volatility_pct,
            annualized_volatility_pct=annualized_volatility_pct
        )
    
    def generate_monthly_report(self, year: int, month: int) -> Dict:
        """
        Generate monthly performance report
        
        Args:
            year: Year for report
            month: Month for report (1-12)
        
        Returns:
            Dictionary with monthly performance data
        """
        # Filter snapshots for the month
        start_date = datetime(year, month, 1)
        if month == 12:
            end_date = datetime(year + 1, 1, 1)
        else:
            end_date = datetime(year, month + 1, 1)
        
        month_snapshots = [
            s for s in self.snapshots 
            if start_date <= s.timestamp < end_date
        ]
        
        if not month_snapshots:
            return {
                'year': year,
                'month': month,
                'error': 'No data available for this month'
            }
        
        # Calculate monthly metrics
        start_equity = month_snapshots[0].equity
        end_equity = month_snapshots[-1].equity
        monthly_return = ((end_equity - start_equity) / start_equity * 100) if start_equity > 0 else 0.0
        
        total_trades_month = month_snapshots[-1].total_trades - month_snapshots[0].total_trades
        winning_trades_month = month_snapshots[-1].winning_trades - month_snapshots[0].winning_trades
        losing_trades_month = month_snapshots[-1].losing_trades - month_snapshots[0].losing_trades
        
        win_rate = (winning_trades_month / total_trades_month * 100) if total_trades_month > 0 else 0.0
        
        # Get max drawdown for the month
        month_drawdowns = [dd for ts, dd in self.drawdown_curve if start_date <= ts < end_date]
        max_dd_month = max(month_drawdowns) if month_drawdowns else 0.0
        
        return {
            'year': year,
            'month': month,
            'start_equity': start_equity,
            'end_equity': end_equity,
            'monthly_return_pct': monthly_return,
            'total_trades': total_trades_month,
            'winning_trades': winning_trades_month,
            'losing_trades': losing_trades_month,
            'win_rate_pct': win_rate,
            'max_drawdown_pct': max_dd_month,
            'trading_days': len(month_snapshots)
        }
    
    def _load_historical_data(self) -> None:
        """Load historical performance data from disk"""
        snapshots_file = self.data_dir / "snapshots.json"
        
        if not snapshots_file.exists():
            logger.info("No historical performance data found")
            return
        
        try:
            with open(snapshots_file, 'r') as f:
                data = json.load(f)
                
            # Reconstruct snapshots
            for item in data:
                snapshot = PerformanceSnapshot(
                    timestamp=datetime.fromisoformat(item['timestamp']),
                    nav=item['nav'],
                    equity=item['equity'],
                    cash=item['cash'],
                    positions_value=item['positions_value'],
                    unrealized_pnl=item['unrealized_pnl'],
                    realized_pnl_today=item['realized_pnl_today'],
                    total_trades=item['total_trades'],
                    winning_trades=item['winning_trades'],
                    losing_trades=item['losing_trades']
                )
                self.record_snapshot(snapshot)
            
            logger.info(f"✅ Loaded {len(self.snapshots)} historical performance snapshots")
            
        except Exception as e:
            logger.error(f"Error loading historical data: {e}")
    
    def save_data(self) -> None:
        """Save performance data to disk"""
        snapshots_file = self.data_dir / "snapshots.json"
        
        try:
            data = []
            for snapshot in self.snapshots:
                data.append({
                    'timestamp': snapshot.timestamp.isoformat(),
                    'nav': snapshot.nav,
                    'equity': snapshot.equity,
                    'cash': snapshot.cash,
                    'positions_value': snapshot.positions_value,
                    'unrealized_pnl': snapshot.unrealized_pnl,
                    'realized_pnl_today': snapshot.realized_pnl_today,
                    'total_trades': snapshot.total_trades,
                    'winning_trades': snapshot.winning_trades,
                    'losing_trades': snapshot.losing_trades
                })
            
            with open(snapshots_file, 'w') as f:
                json.dump(data, f, indent=2)
            
            logger.debug(f"Saved {len(self.snapshots)} performance snapshots")
            
        except Exception as e:
            logger.error(f"Error saving performance data: {e}")


# Singleton instance
_performance_calculator: Optional[PerformanceMetricsCalculator] = None


def get_performance_calculator(initial_capital: float = 1000.0, 
                               reset: bool = False) -> PerformanceMetricsCalculator:
    """
    Get or create the performance metrics calculator singleton
    
    Args:
        initial_capital: Initial capital (only used on first creation)
        reset: Force reset and create new instance
    
    Returns:
        PerformanceMetricsCalculator instance
    """
    global _performance_calculator
    
    if _performance_calculator is None or reset:
        _performance_calculator = PerformanceMetricsCalculator(initial_capital)
    
    return _performance_calculator
