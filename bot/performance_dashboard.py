"""
NIJA Performance Dashboard

Investor-grade performance dashboard providing:
- Real-time NAV tracking
- Equity curves
- Drawdown curves
- Sharpe ratio tracking
- Monthly performance reports
- Strategy performance breakdown

This is the capital-raising infrastructure component.

Author: NIJA Trading Systems
Version: 1.0
Date: January 29, 2026
"""

import logging
from typing import Dict, List, Optional, Tuple
from datetime import datetime, timedelta
from pathlib import Path
import json

try:
    from performance_metrics import (
        PerformanceMetricsCalculator,
        PerformanceSnapshot,
        get_performance_calculator
    )
    from strategy_portfolio_manager import (
        StrategyPortfolioManager,
        get_portfolio_manager
    )
except ImportError:
    from bot.performance_metrics import (
        PerformanceMetricsCalculator,
        PerformanceSnapshot,
        get_performance_calculator
    )
    from bot.strategy_portfolio_manager import (
        StrategyPortfolioManager,
        get_portfolio_manager
    )

logger = logging.getLogger("nija.performance_dashboard")


class PerformanceDashboard:
    """
    Investor-grade performance dashboard
    
    Provides comprehensive performance tracking and reporting
    suitable for investor presentations and capital raising.
    
    Features:
    - Daily NAV calculation
    - Equity curve generation
    - Drawdown curve visualization
    - Sharpe ratio tracking
    - Monthly performance reports
    - Strategy-level performance breakdown
    - Portfolio diversification metrics
    """
    
    def __init__(self, initial_capital: float, user_id: str = "default"):
        """
        Initialize performance dashboard
        
        Args:
            initial_capital: Starting capital amount
            user_id: User identifier for multi-user systems
        """
        self.initial_capital = initial_capital
        self.user_id = user_id
        
        # Initialize components
        self.metrics_calculator = get_performance_calculator(initial_capital)
        self.portfolio_manager = get_portfolio_manager(initial_capital)
        
        # Tracking state
        self.last_snapshot_time: Optional[datetime] = None
        self.snapshot_interval = timedelta(hours=1)  # Take snapshots every hour
        
        logger.info(f"✅ Performance Dashboard initialized for user {user_id} "
                   f"with ${initial_capital:,.2f}")
    
    def update_snapshot(self, cash: float, positions_value: float, 
                       unrealized_pnl: float, realized_pnl_today: float,
                       total_trades: int, winning_trades: int, 
                       losing_trades: int) -> None:
        """
        Update performance snapshot with current portfolio state
        
        Args:
            cash: Available cash
            positions_value: Market value of open positions
            unrealized_pnl: Unrealized profit/loss
            realized_pnl_today: Realized P&L for today
            total_trades: Cumulative total trades
            winning_trades: Cumulative winning trades
            losing_trades: Cumulative losing trades
        """
        now = datetime.now()
        
        # Check if it's time for a new snapshot
        if (self.last_snapshot_time is None or 
            now - self.last_snapshot_time >= self.snapshot_interval):
            
            # Calculate NAV
            nav = self.metrics_calculator.calculate_nav(cash, positions_value, unrealized_pnl)
            equity = cash + positions_value
            
            # Create snapshot
            snapshot = PerformanceSnapshot(
                timestamp=now,
                nav=nav,
                equity=equity,
                cash=cash,
                positions_value=positions_value,
                unrealized_pnl=unrealized_pnl,
                realized_pnl_today=realized_pnl_today,
                total_trades=total_trades,
                winning_trades=winning_trades,
                losing_trades=losing_trades
            )
            
            # Record snapshot
            self.metrics_calculator.record_snapshot(snapshot)
            self.last_snapshot_time = now
            
            logger.debug(f"📊 Updated snapshot: NAV=${nav:,.2f}, Equity=${equity:,.2f}")
    
    def get_current_metrics(self) -> Dict:
        """
        Get current performance metrics
        
        Returns:
            Dictionary with current performance metrics
        """
        metrics = self.metrics_calculator.calculate_metrics()
        
        return {
            # Returns
            'total_return_pct': metrics.total_return_pct,
            'daily_return_pct': metrics.daily_return_pct,
            'monthly_return_pct': metrics.monthly_return_pct,
            'annualized_return_pct': metrics.annualized_return_pct,
            'cagr_pct': metrics.cagr_pct,
            
            # Risk metrics
            'sharpe_ratio': metrics.sharpe_ratio,
            'sortino_ratio': metrics.sortino_ratio,
            'calmar_ratio': metrics.calmar_ratio,
            'max_drawdown_pct': metrics.max_drawdown_pct,
            'current_drawdown_pct': metrics.current_drawdown_pct,
            
            # Trade statistics
            'total_trades': metrics.total_trades,
            'winning_trades': metrics.winning_trades,
            'losing_trades': metrics.losing_trades,
            'win_rate_pct': metrics.win_rate_pct,
            'avg_win': metrics.avg_win,
            'avg_loss': metrics.avg_loss,
            'profit_factor': metrics.profit_factor,
            
            # Time metrics
            'days_trading': metrics.days_trading,
            'avg_trades_per_day': metrics.avg_trades_per_day,
            'longest_winning_streak': metrics.longest_winning_streak,
            'longest_losing_streak': metrics.longest_losing_streak,
            
            # Volatility
            'daily_volatility_pct': metrics.daily_volatility_pct,
            'annualized_volatility_pct': metrics.annualized_volatility_pct
        }
    
    def get_equity_curve(self, days: Optional[int] = None) -> List[Dict]:
        """
        Get equity curve data
        
        Args:
            days: Number of days to include (None for all data)
        
        Returns:
            List of dictionaries with timestamp and equity
        """
        start_date = None
        if days:
            start_date = datetime.now() - timedelta(days=days)
        
        df = self.metrics_calculator.get_equity_curve(start_date=start_date)
        
        return [
            {
                'timestamp': row['timestamp'].isoformat(),
                'equity': float(row['equity'])
            }
            for _, row in df.iterrows()
        ]
    
    def get_drawdown_curve(self, days: Optional[int] = None) -> List[Dict]:
        """
        Get drawdown curve data
        
        Args:
            days: Number of days to include (None for all data)
        
        Returns:
            List of dictionaries with timestamp and drawdown_pct
        """
        start_date = None
        if days:
            start_date = datetime.now() - timedelta(days=days)
        
        df = self.metrics_calculator.get_drawdown_curve(start_date=start_date)
        
        return [
            {
                'timestamp': row['timestamp'].isoformat(),
                'drawdown_pct': float(row['drawdown_pct'])
            }
            for _, row in df.iterrows()
        ]
    
    def get_monthly_report(self, year: int, month: int) -> Dict:
        """
        Generate monthly performance report
        
        Args:
            year: Year for report
            month: Month for report (1-12)
        
        Returns:
            Dictionary with monthly performance data
        """
        report = self.metrics_calculator.generate_monthly_report(year, month)
        
        # Add portfolio information
        portfolio_summary = self.portfolio_manager.get_portfolio_summary()
        report['portfolio'] = portfolio_summary
        
        return report
    
    def get_all_monthly_reports(self) -> List[Dict]:
        """
        Get all available monthly reports
        
        Returns:
            List of monthly report dictionaries
        """
        if not self.metrics_calculator.snapshots:
            return []
        
        # Get date range from snapshots
        start_date = self.metrics_calculator.snapshots[0].timestamp
        end_date = self.metrics_calculator.snapshots[-1].timestamp
        
        reports = []
        current = start_date.replace(day=1)
        
        while current <= end_date:
            report = self.get_monthly_report(current.year, current.month)
            if 'error' not in report:
                reports.append(report)
            
            # Move to next month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
        
        return reports
    
    def get_strategy_performance(self) -> Dict:
        """
        Get performance breakdown by strategy
        
        Returns:
            Dictionary with strategy-level performance
        """
        return self.portfolio_manager.get_portfolio_summary()
    
    def get_diversification_metrics(self) -> Dict:
        """
        Get portfolio diversification metrics
        
        Returns:
            Dictionary with diversification metrics
        """
        diversification_score = self.portfolio_manager.get_diversification_score()
        
        # Calculate correlation matrix
        correlation_matrix = self.portfolio_manager.calculate_correlation_matrix()
        
        return {
            'diversification_score': diversification_score,
            'strategy_count': len([s for s in self.portfolio_manager.strategies.values() if s.enabled]),
            'correlation_matrix': correlation_matrix.tolist() if correlation_matrix.size > 0 else [],
            'strategy_names': self.portfolio_manager.strategy_names_ordered
        }
    
    def get_investor_summary(self) -> Dict:
        """
        Get comprehensive investor summary
        
        This is the main report for investors and stakeholders.
        
        Returns:
            Dictionary with comprehensive performance summary
        """
        current_metrics = self.get_current_metrics()
        portfolio_summary = self.get_strategy_performance()
        diversification = self.get_diversification_metrics()
        
        # Calculate additional investor-focused metrics
        if self.metrics_calculator.snapshots:
            latest_snapshot = self.metrics_calculator.snapshots[-1]
            current_nav = latest_snapshot.nav
            current_equity = latest_snapshot.equity
        else:
            current_nav = self.initial_capital
            current_equity = self.initial_capital
        
        # Get max drawdown details
        max_dd, dd_start, dd_end = self.metrics_calculator.calculate_max_drawdown()
        
        return {
            'user_id': self.user_id,
            'reporting_date': datetime.now().isoformat(),
            
            # Capital metrics
            'initial_capital': self.initial_capital,
            'current_nav': current_nav,
            'current_equity': current_equity,
            'total_return_pct': current_metrics['total_return_pct'],
            'total_return_usd': current_equity - self.initial_capital,
            
            # Performance metrics
            'annualized_return_pct': current_metrics['annualized_return_pct'],
            'monthly_avg_return_pct': current_metrics['monthly_return_pct'],
            'sharpe_ratio': current_metrics['sharpe_ratio'],
            'sortino_ratio': current_metrics['sortino_ratio'],
            
            # Risk metrics
            'max_drawdown_pct': max_dd,
            'max_drawdown_start': dd_start.isoformat() if dd_start else None,
            'max_drawdown_end': dd_end.isoformat() if dd_end else None,
            'current_drawdown_pct': current_metrics['current_drawdown_pct'],
            'annualized_volatility_pct': current_metrics['annualized_volatility_pct'],
            
            # Trading activity
            'total_trades': current_metrics['total_trades'],
            'win_rate_pct': current_metrics['win_rate_pct'],
            'days_trading': current_metrics['days_trading'],
            'avg_trades_per_day': current_metrics['avg_trades_per_day'],
            
            # Portfolio composition
            'active_strategies': portfolio_summary['active_strategies'],
            'diversification_score': diversification['diversification_score'],
            'strategy_allocations': portfolio_summary['allocations'],
            'current_regime': portfolio_summary['current_regime'],
            
            # Strategy performance
            'strategy_performance': portfolio_summary['strategy_performance']
        }
    
    def export_investor_report(self, output_dir: str = "./reports") -> str:
        """
        Export comprehensive investor report to file
        
        Args:
            output_dir: Directory to save report
        
        Returns:
            Path to saved report file
        """
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True, parents=True)
        
        # Generate report
        report = self.get_investor_summary()
        
        # Add equity and drawdown curves
        report['equity_curve'] = self.get_equity_curve()
        report['drawdown_curve'] = self.get_drawdown_curve()
        report['monthly_reports'] = self.get_all_monthly_reports()
        
        # Save to file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"investor_report_{self.user_id}_{timestamp}.json"
        filepath = output_path / filename
        
        with open(filepath, 'w') as f:
            json.dump(report, f, indent=2, default=str)
        
        logger.info(f"📄 Exported investor report to {filepath}")
        
        return str(filepath)
    
    def save_state(self) -> None:
        """Save all dashboard state to disk"""
        self.metrics_calculator.save_data()
        self.portfolio_manager.save_state()
        
        logger.debug("Saved dashboard state")


# Singleton instance
_dashboard: Optional[PerformanceDashboard] = None


def get_performance_dashboard(initial_capital: float = 1000.0,
                              user_id: str = "default",
                              reset: bool = False) -> PerformanceDashboard:
    """
    Get or create the performance dashboard singleton
    
    Args:
        initial_capital: Initial capital (only used on first creation)
        user_id: User identifier
        reset: Force reset and create new instance
    
    Returns:
        PerformanceDashboard instance
    """
    global _dashboard
    
    if _dashboard is None or reset:
        _dashboard = PerformanceDashboard(initial_capital, user_id)
    
    return _dashboard
