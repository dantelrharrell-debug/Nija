"""
NIJA Investor Dashboard - Institutional Metrics Engine
======================================================

Professional-grade performance metrics and analytics for institutional investors.

Provides:
1. Risk-adjusted returns (Sharpe, Sortino, Calmar ratios)
2. Drawdown analysis and visualization
3. Trade attribution analysis
4. Strategy comparison and benchmarking
5. Real-time P&L tracking by strategy
6. Performance persistence analysis

This is the "Investor Layer" - demonstrating institutional-quality risk management.

Author: NIJA Trading Systems
Version: 1.0
Date: January 2026
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field
from collections import defaultdict, deque
import pandas as pd
import numpy as np

logger = logging.getLogger("nija.metrics")


@dataclass
class DrawdownPeriod:
    """Represents a drawdown period"""
    start_time: datetime
    end_time: Optional[datetime]
    peak_value: float
    trough_value: float
    current_value: float
    depth_pct: float
    duration_days: int = 0
    recovered: bool = False
    recovery_time: Optional[datetime] = None


@dataclass
class PerformanceMetrics:
    """Comprehensive performance metrics"""
    # Time period
    start_date: datetime
    end_date: datetime

    # Returns
    total_return: float = 0.0
    annualized_return: float = 0.0
    daily_returns: List[float] = field(default_factory=list)

    # Risk metrics
    volatility: float = 0.0  # Annualized
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    calmar_ratio: float = 0.0

    # Drawdown
    max_drawdown: float = 0.0
    current_drawdown: float = 0.0
    avg_drawdown: float = 0.0
    drawdown_periods: List[DrawdownPeriod] = field(default_factory=list)

    # Trade statistics
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    expectancy: float = 0.0

    # Trade quality
    avg_win: float = 0.0
    avg_loss: float = 0.0
    largest_win: float = 0.0
    largest_loss: float = 0.0
    avg_trade_duration: float = 0.0  # In hours

    # Consistency
    win_streak: int = 0
    loss_streak: int = 0
    profitable_days_pct: float = 0.0


class InvestorMetricsEngine:
    """
    Institutional-grade performance metrics and analytics
    """

    def __init__(self, initial_capital: float, config: Optional[Dict] = None):
        """
        Initialize metrics engine

        Args:
            initial_capital: Starting capital
            config: Optional configuration
        """
        self.initial_capital = initial_capital
        self.current_capital = initial_capital
        self.config = config or {}

        # Performance tracking
        self.equity_curve: deque = deque(maxlen=10000)
        self.daily_pnl: Dict[str, float] = {}  # date -> pnl

        # Strategy-specific tracking
        self.strategy_metrics: Dict[str, PerformanceMetrics] = {}
        self.strategy_equity: Dict[str, deque] = {}

        # Drawdown tracking
        self.peak_equity = initial_capital
        self.current_drawdown_period: Optional[DrawdownPeriod] = None
        self.all_drawdown_periods: List[DrawdownPeriod] = []

        # Risk-free rate for Sharpe calculation
        self.risk_free_rate = self.config.get('risk_free_rate', 0.02)  # 2% annual

        # Initialize with starting equity
        self.equity_curve.append({
            'timestamp': datetime.now(),
            'equity': initial_capital,
            'pnl': 0.0,
            'returns': 0.0
        })

        logger.info(f"Investor Metrics Engine initialized with ${initial_capital:,.2f}")

    def update_equity(self, new_equity: float, strategy_id: Optional[str] = None):
        """
        Update equity value

        Args:
            new_equity: New total equity value
            strategy_id: Optional strategy identifier for attribution
        """
        timestamp = datetime.now()
        prev_equity = self.current_capital

        pnl = new_equity - prev_equity
        returns = pnl / prev_equity if prev_equity > 0 else 0

        # Update overall equity
        self.current_capital = new_equity
        self.equity_curve.append({
            'timestamp': timestamp,
            'equity': new_equity,
            'pnl': pnl,
            'returns': returns
        })

        # Track daily P&L
        date_key = timestamp.strftime('%Y-%m-%d')
        self.daily_pnl[date_key] = self.daily_pnl.get(date_key, 0) + pnl

        # Update peak and drawdown
        if new_equity > self.peak_equity:
            self.peak_equity = new_equity

            # End current drawdown if recovering
            if self.current_drawdown_period and not self.current_drawdown_period.recovered:
                self.current_drawdown_period.recovered = True
                self.current_drawdown_period.recovery_time = timestamp
                self.current_drawdown_period.end_time = timestamp
                self.all_drawdown_periods.append(self.current_drawdown_period)
                self.current_drawdown_period = None
        else:
            # In drawdown
            drawdown_pct = (self.peak_equity - new_equity) / self.peak_equity

            if self.current_drawdown_period is None:
                # Start new drawdown period
                self.current_drawdown_period = DrawdownPeriod(
                    start_time=timestamp,
                    end_time=None,
                    peak_value=self.peak_equity,
                    trough_value=new_equity,
                    current_value=new_equity,
                    depth_pct=drawdown_pct
                )
            else:
                # Update existing drawdown
                self.current_drawdown_period.current_value = new_equity
                if new_equity < self.current_drawdown_period.trough_value:
                    self.current_drawdown_period.trough_value = new_equity
                self.current_drawdown_period.depth_pct = (
                    self.peak_equity - self.current_drawdown_period.trough_value
                ) / self.peak_equity
                self.current_drawdown_period.duration_days = (
                    timestamp - self.current_drawdown_period.start_time
                ).days

        # Strategy-specific tracking
        if strategy_id:
            if strategy_id not in self.strategy_equity:
                self.strategy_equity[strategy_id] = deque(maxlen=1000)

            self.strategy_equity[strategy_id].append({
                'timestamp': timestamp,
                'pnl': pnl,
                'returns': returns
            })

    def calculate_sharpe_ratio(self, returns: List[float],
                              periods_per_year: int = 252) -> float:
        """
        Calculate Sharpe ratio

        Args:
            returns: List of periodic returns
            periods_per_year: Number of periods per year (252 for daily, 12 for monthly)

        Returns:
            Sharpe ratio
        """
        if len(returns) < 2:
            return 0.0

        returns_array = np.array(returns)

        # Convert annual risk-free rate to period rate
        period_rf_rate = (1 + self.risk_free_rate) ** (1 / periods_per_year) - 1

        excess_returns = returns_array - period_rf_rate

        if np.std(excess_returns) == 0:
            return 0.0

        sharpe = np.mean(excess_returns) / np.std(excess_returns)

        # Annualize
        sharpe_annual = sharpe * np.sqrt(periods_per_year)

        return sharpe_annual

    def calculate_sortino_ratio(self, returns: List[float],
                               periods_per_year: int = 252) -> float:
        """
        Calculate Sortino ratio (only penalizes downside volatility)

        Args:
            returns: List of periodic returns
            periods_per_year: Number of periods per year

        Returns:
            Sortino ratio
        """
        if len(returns) < 2:
            return 0.0

        returns_array = np.array(returns)

        # Convert annual risk-free rate to period rate
        period_rf_rate = (1 + self.risk_free_rate) ** (1 / periods_per_year) - 1

        excess_returns = returns_array - period_rf_rate

        # Downside deviation (only negative returns)
        downside_returns = excess_returns[excess_returns < 0]

        if len(downside_returns) == 0:
            return 100.0  # Perfect - no downside

        downside_std = np.std(downside_returns)

        if downside_std == 0:
            return 0.0

        sortino = np.mean(excess_returns) / downside_std

        # Annualize
        sortino_annual = sortino * np.sqrt(periods_per_year)

        return sortino_annual

    def calculate_calmar_ratio(self, annualized_return: float,
                              max_drawdown: float) -> float:
        """
        Calculate Calmar ratio (return / max drawdown)

        Args:
            annualized_return: Annualized return
            max_drawdown: Maximum drawdown as decimal (e.g., 0.15 for 15%)

        Returns:
            Calmar ratio
        """
        # Avoid division by zero and very small drawdowns that would give misleading ratios
        MIN_DRAWDOWN = 0.001  # 0.1% minimum drawdown threshold
        if max_drawdown < MIN_DRAWDOWN:
            return 0.0

        return annualized_return / max_drawdown

    def get_performance_metrics(self, lookback_days: Optional[int] = None) -> PerformanceMetrics:
        """
        Calculate comprehensive performance metrics

        Args:
            lookback_days: Number of days to look back (None for all-time)

        Returns:
            PerformanceMetrics object
        """
        if not self.equity_curve:
            return PerformanceMetrics(
                start_date=datetime.now(),
                end_date=datetime.now()
            )

        # Filter equity curve if lookback specified
        if lookback_days:
            cutoff_time = datetime.now() - timedelta(days=lookback_days)
            equity_data = [e for e in self.equity_curve if e['timestamp'] > cutoff_time]
        else:
            equity_data = list(self.equity_curve)

        if not equity_data:
            return PerformanceMetrics(
                start_date=datetime.now(),
                end_date=datetime.now()
            )

        # Time period
        start_date = equity_data[0]['timestamp']
        end_date = equity_data[-1]['timestamp']
        days_elapsed = max((end_date - start_date).days, 1)

        # Returns
        start_equity = equity_data[0]['equity']
        end_equity = equity_data[-1]['equity']
        total_return = (end_equity - start_equity) / start_equity
        annualized_return = (1 + total_return) ** (365 / days_elapsed) - 1

        # Daily returns
        daily_returns = [e['returns'] for e in equity_data if e['returns'] != 0]

        # Risk metrics
        volatility = np.std(daily_returns) * np.sqrt(252) if daily_returns else 0
        sharpe_ratio = self.calculate_sharpe_ratio(daily_returns)
        sortino_ratio = self.calculate_sortino_ratio(daily_returns)

        # Drawdown
        equity_values = [e['equity'] for e in equity_data]
        peak_equity_series = pd.Series(equity_values).expanding().max()
        drawdown_series = (pd.Series(equity_values) - peak_equity_series) / peak_equity_series
        max_drawdown = abs(drawdown_series.min())
        current_drawdown = abs(drawdown_series.iloc[-1]) if len(drawdown_series) > 0 else 0
        avg_drawdown = abs(drawdown_series[drawdown_series < 0].mean()) if (drawdown_series < 0).any() else 0

        # Calmar ratio
        calmar_ratio = self.calculate_calmar_ratio(annualized_return, max_drawdown)

        # Create metrics object
        metrics = PerformanceMetrics(
            start_date=start_date,
            end_date=end_date,
            total_return=total_return,
            annualized_return=annualized_return,
            daily_returns=daily_returns,
            volatility=volatility,
            sharpe_ratio=sharpe_ratio,
            sortino_ratio=sortino_ratio,
            calmar_ratio=calmar_ratio,
            max_drawdown=max_drawdown,
            current_drawdown=current_drawdown,
            avg_drawdown=avg_drawdown,
            drawdown_periods=self.all_drawdown_periods.copy()
        )

        logger.debug(f"Performance metrics calculated: Sharpe={sharpe_ratio:.2f}, "
                    f"Max DD={max_drawdown*100:.1f}%, Return={total_return*100:.1f}%")

        return metrics

    def get_strategy_comparison(self) -> Dict[str, Dict]:
        """
        Compare performance across all strategies

        Returns:
            Dictionary of strategy_id -> performance metrics
        """
        comparison = {}

        for strategy_id, equity_data in self.strategy_equity.items():
            if not equity_data:
                continue

            # Calculate returns
            returns = [e['returns'] for e in equity_data]
            pnls = [e['pnl'] for e in equity_data]

            total_pnl = sum(pnls)
            total_trades = len(pnls)
            winning_trades = sum(1 for p in pnls if p > 0)

            win_rate = winning_trades / total_trades if total_trades > 0 else 0
            sharpe = self.calculate_sharpe_ratio(returns) if returns else 0

            comparison[strategy_id] = {
                'total_trades': total_trades,
                'total_pnl': total_pnl,
                'win_rate': win_rate,
                'sharpe_ratio': sharpe,
                'avg_pnl': total_pnl / total_trades if total_trades > 0 else 0
            }

        logger.info(f"📊 Strategy comparison: {len(comparison)} strategies analyzed")

        return comparison

    def get_trade_attribution(self, trades: List[Dict]) -> Dict[str, Any]:
        """
        Analyze trade attribution by various factors

        Args:
            trades: List of trade dictionaries with metadata

        Returns:
            Attribution analysis
        """
        attribution = {
            'by_strategy': defaultdict(float),
            'by_symbol': defaultdict(float),
            'by_regime': defaultdict(float),
            'by_time_of_day': defaultdict(float),
            'by_day_of_week': defaultdict(float)
        }

        for trade in trades:
            pnl = trade.get('pnl', 0)

            # By strategy
            strategy = trade.get('strategy_id', 'unknown')
            attribution['by_strategy'][strategy] += pnl

            # By symbol
            symbol = trade.get('symbol', 'unknown')
            attribution['by_symbol'][symbol] += pnl

            # By regime
            regime = trade.get('regime', 'unknown')
            attribution['by_regime'][regime] += pnl

            # By time of day
            entry_time = trade.get('entry_time')
            if entry_time:
                hour = entry_time.hour
                time_bucket = f"{hour:02d}:00"
                attribution['by_time_of_day'][time_bucket] += pnl

                # By day of week
                day_name = entry_time.strftime('%A')
                attribution['by_day_of_week'][day_name] += pnl

        # Convert to regular dict for JSON serialization
        attribution = {k: dict(v) for k, v in attribution.items()}

        return attribution

    def get_rolling_metrics(self, window_days: int = 30) -> Dict[str, List]:
        """
        Calculate rolling performance metrics

        Args:
            window_days: Rolling window in days

        Returns:
            Dictionary of metric -> list of values over time
        """
        if len(self.equity_curve) < window_days:
            return {}

        equity_df = pd.DataFrame(list(self.equity_curve))
        equity_df['date'] = pd.to_datetime(equity_df['timestamp']).dt.date

        # Group by date and get daily equity
        daily_equity = equity_df.groupby('date')['equity'].last()

        # Calculate rolling metrics
        rolling_returns = daily_equity.pct_change().rolling(window_days).mean() * 252  # Annualized
        rolling_volatility = daily_equity.pct_change().rolling(window_days).std() * np.sqrt(252)
        rolling_sharpe = (rolling_returns - self.risk_free_rate) / rolling_volatility

        # Rolling max drawdown
        rolling_max = daily_equity.rolling(window_days).max()
        rolling_drawdown = (daily_equity - rolling_max) / rolling_max
        rolling_max_dd = rolling_drawdown.rolling(window_days).min()

        rolling_metrics = {
            'dates': [d.isoformat() for d in daily_equity.index],
            'returns': rolling_returns.fillna(0).tolist(),
            'volatility': rolling_volatility.fillna(0).tolist(),
            'sharpe': rolling_sharpe.fillna(0).tolist(),
            'max_drawdown': rolling_max_dd.fillna(0).tolist()
        }

        return rolling_metrics

    def generate_investor_report(self) -> Dict[str, Any]:
        """
        Generate comprehensive investor-grade performance report

        Returns:
            Complete performance report
        """
        # Overall metrics
        overall = self.get_performance_metrics()

        # 30-day metrics
        recent = self.get_performance_metrics(lookback_days=30)

        # Strategy comparison
        strategy_comp = self.get_strategy_comparison()

        # Rolling metrics
        rolling = self.get_rolling_metrics(window_days=30)

        # Drawdown analysis
        drawdown_summary = {
            'current_drawdown_pct': overall.current_drawdown * 100,
            'max_drawdown_pct': overall.max_drawdown * 100,
            'avg_drawdown_pct': overall.avg_drawdown * 100,
            'total_drawdown_periods': len(overall.drawdown_periods),
            'longest_drawdown_days': max((dd.duration_days for dd in overall.drawdown_periods), default=0)
        }

        report = {
            'report_date': datetime.now().isoformat(),
            'account_summary': {
                'initial_capital': self.initial_capital,
                'current_capital': self.current_capital,
                'total_pnl': self.current_capital - self.initial_capital,
                'total_return_pct': ((self.current_capital / self.initial_capital) - 1) * 100
            },
            'overall_performance': {
                'total_return_pct': overall.total_return * 100,
                'annualized_return_pct': overall.annualized_return * 100,
                'sharpe_ratio': overall.sharpe_ratio,
                'sortino_ratio': overall.sortino_ratio,
                'calmar_ratio': overall.calmar_ratio,
                'volatility_pct': overall.volatility * 100
            },
            'recent_performance_30d': {
                'return_pct': recent.total_return * 100,
                'sharpe_ratio': recent.sharpe_ratio,
                'volatility_pct': recent.volatility * 100
            },
            'risk_metrics': drawdown_summary,
            'strategy_comparison': strategy_comp,
            'rolling_metrics': rolling
        }

        logger.info("📈 Investor report generated")
        logger.info(f"   Total Return: {overall.total_return*100:.2f}%")
        logger.info(f"   Sharpe Ratio: {overall.sharpe_ratio:.2f}")
        logger.info(f"   Max Drawdown: {overall.max_drawdown*100:.2f}%")

        return report


def create_metrics_engine(initial_capital: float,
                         config: Optional[Dict] = None) -> InvestorMetricsEngine:
    """
    Factory function to create metrics engine

    Args:
        initial_capital: Starting capital
        config: Optional configuration

    Returns:
        InvestorMetricsEngine instance
    """
    return InvestorMetricsEngine(initial_capital, config)
