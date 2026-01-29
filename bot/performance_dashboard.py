"""
NIJA Performance Dashboard

Provides comprehensive performance analytics and investor reporting capabilities
for the NIJA trading bot. Includes portfolio summary, trade analytics, and
secure export functionality.

Author: NIJA Trading Systems
Provides performance tracking and reporting for trading accounts.
Includes secure export functionality with path traversal protection.

Author: NIJA Trading Systems
Date: January 29, 2026
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
import pandas as pd

# Import path validation utilities for security
from bot.path_validator import validate_output_path, PathValidationError
from typing import Dict, Any, Optional

from bot.path_validator import PathValidator

logger = logging.getLogger(__name__)
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
    Performance dashboard for trading analytics and investor reporting.

    Provides comprehensive portfolio metrics, trade analytics, and secure
    export capabilities with built-in path traversal protection.
    """

    def __init__(self):
        """Initialize the performance dashboard"""
        self.logger = logger
        # Default safe base directory for reports
        self._default_report_dir = Path("./reports").resolve()

    def get_portfolio_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive portfolio summary.

        Returns:
            Dictionary containing portfolio metrics
        """
        # TODO: Implement actual portfolio data collection
        # For now, return placeholder data
        return {
            'total_value': 10000.0,
            'total_pnl': 1500.0,
            'total_pnl_percentage': 15.0,
            'open_positions': 5,
            'closed_trades': 42,
            'win_rate': 65.5,
            'sharpe_ratio': 1.8,
            'max_drawdown': -5.2,
            'total_trades': 47,
            'strategy_performance': {
                'apex_v71': {
                    'trades': 30,
                    'win_rate': 68.0,
                    'pnl': 1200.0
                },
                'dual_rsi': {
                    'trades': 17,
                    'win_rate': 62.0,
                    'pnl': 300.0
                }
            },
            'last_updated': datetime.now().isoformat()
        }

    def get_trade_analytics(self) -> Dict[str, Any]:
        """
        Get detailed trade analytics.

        Returns:
            Dictionary containing trade analytics
        """
        # TODO: Implement actual trade analytics
        return {
            'average_win': 250.0,
            'average_loss': -120.0,
            'profit_factor': 2.08,
            'expectancy': 35.0,
            'largest_win': 850.0,
            'largest_loss': -380.0,
            'average_trade_duration': '4.5 hours',
            'best_performing_asset': 'BTC-USD',
            'most_traded_asset': 'ETH-USD'
        }

    def get_risk_metrics(self) -> Dict[str, Any]:
        """
        Get risk management metrics.

        Returns:
            Dictionary containing risk metrics
        """
        # TODO: Implement actual risk metrics
        return {
            'current_drawdown': -2.1,
            'max_drawdown': -5.2,
            'var_95': -3.5,
            'current_leverage': 1.2,
            'risk_per_trade': 1.0,
            'total_exposure': 8500.0,
            'available_capital': 1500.0
        }

    def get_investor_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive investor summary report.

        Combines portfolio metrics, trade analytics, and risk metrics
        into a single comprehensive report for investors.

        Returns:
            Dictionary containing complete investor summary
        """
        return {
            'report_date': datetime.now().isoformat(),
            'portfolio': self.get_portfolio_summary(),
            'analytics': self.get_trade_analytics(),
            'risk': self.get_risk_metrics(),
            'generated_by': 'NIJA Performance Dashboard v1.0'
    Performance dashboard for tracking and reporting trading metrics.

    Features:
    - Portfolio performance tracking
    - Trade analytics
    - Secure report export with path validation
    """

    def __init__(self, user_id: str):
        """
        Initialize performance dashboard.

        Args:
            user_id: User identifier
        """
        # Sanitize user_id to prevent path traversal
        self.user_id = user_id.replace('/', '_').replace('\\', '_').replace('..', '')
        self.metrics = {}

    def get_performance_summary(self) -> Dict[str, Any]:
        """
        Get comprehensive performance summary.

        Returns:
            Dictionary containing performance metrics
        """
        return {
            'user_id': self.user_id,
            'timestamp': datetime.now().isoformat(),
            'portfolio_value': 0.0,
            'total_pnl': 0.0,
            'win_rate': 0.0,
            'sharpe_ratio': 0.0,
            'max_drawdown': 0.0,
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'average_win': 0.0,
            'average_loss': 0.0,
            'profit_factor': 0.0,
            'strategy_performance': {}
        }

    def export_investor_report(self, output_dir: str = "./reports") -> str:
        """
        Export comprehensive investor report to file with secure path handling.

        This method implements multiple security controls to prevent path traversal:
        1. Validates and sanitizes the output_dir parameter
        2. Ensures the path stays within intended directory
        3. Uses secure path resolution

        Args:
            output_dir: Directory to save report (validated and sanitized)

        Returns:
            Path to saved report file

        Raises:
            ValueError: If path validation fails
        """
        # SECURITY: Validate and create secure path
        # This prevents path traversal attacks like "../../../etc/passwd"
        try:
            output_path = PathValidator.secure_path(
                base_dir="./reports",
                user_path=output_dir,
                allow_subdirs=True
            )
        except ValueError as e:
            logger.error(f"Path validation failed for output_dir={output_dir}: {e}")
            # Fallback to safe default
            output_path = Path("./reports")

        # Create directory if it doesn't exist
        output_path.mkdir(exist_ok=True, parents=True)

        # Generate report
        report = self._generate_investor_report()

        # Create secure filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"investor_report_{self.user_id}_{timestamp}.json"

        # SECURITY: Validate filename
        if not PathValidator.validate_filename(filename):
            filename = PathValidator.sanitize_filename(filename)

        filepath = output_path / filename

        # Write report to file
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
        Export comprehensive investor report to file.

        This method includes security measures to prevent path traversal attacks.
        The output_dir parameter is validated to ensure it doesn't escape the
        intended directory structure.

        Args:
            output_dir: Directory to save the report (validated for security)

        Returns:
            Path to saved report file

        Raises:
            PathValidationError: If output_dir validation fails
            OSError: If file write operation fails
        """
        # SECURITY FIX: Validate output_dir to prevent path traversal
        try:
            # Validate the output directory against a safe base path
            # This prevents attacks like output_dir="../../../etc"
            output_path = validate_output_path(
                base_dir=self._default_report_dir,
                user_provided_path=output_dir,
                allow_create=True
            )
        except PathValidationError as e:
            self.logger.error(f"Path validation failed for output_dir: {e}")
            raise
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

        # Create filename with timestamp
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"investor_report_{timestamp}.json"

        # Construct safe file path
        filepath = output_path / filename

        # Write report to file
        try:
            with open(filepath, 'w') as f:
                json.dump(report, f, indent=2, default=str)

            self.logger.info(f"Investor report exported to: {filepath}")
            return str(filepath)

        except (OSError, PermissionError) as e:
            self.logger.error(f"Failed to write report file: {e}")
            raise OSError(f"Failed to export report: {e}")

    def export_csv_report(self, output_dir: str = "./reports") -> str:
        """
        Export trade data as CSV file.

        Args:
            output_dir: Directory to save the CSV (validated for security)

        Returns:
            Path to saved CSV file

        Raises:
            PathValidationError: If output_dir validation fails
        """
        # SECURITY FIX: Validate output_dir
        try:
            output_path = validate_output_path(
                base_dir=self._default_report_dir,
                user_provided_path=output_dir,
                allow_create=True
            )
        except PathValidationError as e:
            self.logger.error(f"Path validation failed for output_dir: {e}")
            raise

        # TODO: Get actual trade data
        # For now, create sample data
        trade_data = {
            'timestamp': [datetime.now().isoformat()] * 5,
            'symbol': ['BTC-USD', 'ETH-USD', 'SOL-USD', 'BTC-USD', 'ETH-USD'],
            'side': ['buy', 'buy', 'sell', 'sell', 'buy'],
            'quantity': [0.1, 2.0, 10.0, 0.05, 1.5],
            'price': [45000, 3000, 120, 46000, 3100],
            'pnl': [100, 50, -20, 150, 30]
        }

        df = pd.DataFrame(trade_data)

        # Create filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"trades_{timestamp}.csv"
        filepath = output_path / filename

        # Export to CSV
        try:
            df.to_csv(filepath, index=False)
            self.logger.info(f"CSV report exported to: {filepath}")
            return str(filepath)
        except Exception as e:
            self.logger.error(f"Failed to write CSV file: {e}")
            raise OSError(f"Failed to export CSV: {e}")


# Singleton instance
_dashboard_instance: Optional[PerformanceDashboard] = None


def get_performance_dashboard() -> PerformanceDashboard:
    """
    Get the singleton performance dashboard instance.
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

    def _generate_investor_report(self) -> Dict[str, Any]:
        """
        Generate comprehensive investor report data.

        Returns:
            Dictionary containing report data
        """
        return {
            'report_type': 'investor_report',
            'generated_at': datetime.now().isoformat(),
            'user_id': self.user_id,
            'performance_summary': self.get_performance_summary(),
            'risk_metrics': {
                'max_drawdown': 0.0,
                'volatility': 0.0,
                'beta': 0.0,
                'var_95': 0.0
            },
            'trade_history': {
                'total_trades': 0,
                'recent_trades': []
            },
            'portfolio_allocation': {},
            'strategy_breakdown': {}
        }


# Global cache for dashboard instances
_dashboard_cache: Dict[str, PerformanceDashboard] = {}


def get_performance_dashboard(user_id: str = "default") -> PerformanceDashboard:
    """
    Get or create performance dashboard instance for a user.

    Args:
        user_id: User identifier (defaults to "default")

    Returns:
        PerformanceDashboard instance
    """
    # Sanitize user_id
    safe_user_id = user_id.replace('/', '_').replace('\\', '_').replace('..', '')

    if safe_user_id not in _dashboard_cache:
        _dashboard_cache[safe_user_id] = PerformanceDashboard(safe_user_id)

    return _dashboard_cache[safe_user_id]
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
    global _dashboard_instance
    if _dashboard_instance is None:
        _dashboard_instance = PerformanceDashboard()
    return _dashboard_instance
    global _dashboard

    if _dashboard is None or reset:
        _dashboard = PerformanceDashboard(initial_capital, user_id)

    return _dashboard
