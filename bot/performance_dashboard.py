"""
NIJA Performance Dashboard

Provides comprehensive performance analytics and investor reporting capabilities
for the NIJA trading bot. Includes portfolio summary, trade analytics, and
secure export functionality.

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

logger = logging.getLogger(__name__)


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
    
    Returns:
        PerformanceDashboard instance
    """
    global _dashboard_instance
    if _dashboard_instance is None:
        _dashboard_instance = PerformanceDashboard()
    return _dashboard_instance
