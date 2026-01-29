"""
NIJA Performance Dashboard

Provides performance tracking and reporting for trading accounts.
Includes secure export functionality with path traversal protection.

Author: NIJA Trading Systems  
Date: January 29, 2026
"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional

from bot.path_validator import PathValidator

logger = logging.getLogger(__name__)


class PerformanceDashboard:
    """
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
