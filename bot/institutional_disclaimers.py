"""
NIJA Institutional-Grade Disclaimers

Centralized disclaimer management for institutional-grade compliance.
Provides standardized disclaimers for all NIJA logging, reporting, and output.

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import logging
from typing import Optional

# Primary institutional disclaimer
VALIDATION_DISCLAIMER = """
╔════════════════════════════════════════════════════════════════════════════╗
║                      MATHEMATICAL VALIDATION ONLY                          ║
║          DOES NOT REPRESENT HISTORICAL OR FORWARD PERFORMANCE              ║
╚════════════════════════════════════════════════════════════════════════════╝
"""

PERFORMANCE_DISCLAIMER = """
PERFORMANCE DISCLAIMER:
Past performance is not indicative of future results. All trading involves risk.
Backtested and simulated results are hypothetical and may not reflect actual trading.
"""

RISK_DISCLAIMER = """
RISK DISCLAIMER:
Trading cryptocurrencies carries substantial risk of loss. Only trade with capital
you can afford to lose. This software is provided for educational and research
purposes only.
"""


class InstitutionalLogger:
    """
    Institutional-grade logger wrapper that adds disclaimers to output.
    
    Wraps standard Python logger to automatically include validation disclaimers
    in appropriate contexts.
    """
    
    def __init__(self, name: str, base_logger: Optional[logging.Logger] = None):
        """
        Initialize institutional logger.
        
        Args:
            name: Logger name
            base_logger: Optional base logger to wrap (creates new if None)
        """
        self.name = name
        self.logger = base_logger or logging.getLogger(name)
        self._disclaimer_shown = False
    
    def show_validation_disclaimer(self):
        """Display the primary validation disclaimer"""
        if not self._disclaimer_shown:
            self.logger.info(VALIDATION_DISCLAIMER)
            self._disclaimer_shown = True
    
    def info(self, msg: str, *args, show_disclaimer: bool = False, **kwargs):
        """Log info message with optional disclaimer"""
        if show_disclaimer:
            self.show_validation_disclaimer()
        self.logger.info(msg, *args, **kwargs)
    
    def warning(self, msg: str, *args, **kwargs):
        """Log warning message"""
        self.logger.warning(msg, *args, **kwargs)
    
    def error(self, msg: str, *args, **kwargs):
        """Log error message"""
        self.logger.error(msg, *args, **kwargs)
    
    def debug(self, msg: str, *args, **kwargs):
        """Log debug message"""
        self.logger.debug(msg, *args, **kwargs)
    
    def critical(self, msg: str, *args, **kwargs):
        """Log critical message"""
        self.logger.critical(msg, *args, **kwargs)


def get_institutional_logger(name: str) -> InstitutionalLogger:
    """
    Get an institutional-grade logger.
    
    Args:
        name: Logger name
        
    Returns:
        InstitutionalLogger instance
    """
    return InstitutionalLogger(name)


def print_validation_banner():
    """Print the validation banner to console"""
    print(VALIDATION_DISCLAIMER)


def print_all_disclaimers():
    """Print all disclaimers to console"""
    print(VALIDATION_DISCLAIMER)
    print(PERFORMANCE_DISCLAIMER)
    print(RISK_DISCLAIMER)


# Auto-display banner when module is imported in main execution
if __name__ != "__main__":
    # Only show in non-test context
    import sys
    if not any('test' in arg.lower() for arg in sys.argv):
        # Display banner once at module import for institutional compliance
        logger = logging.getLogger("nija.institutional")
        logger.info(VALIDATION_DISCLAIMER)
