"""
NIJA Institutional-Grade Disclaimers

Centralized disclaimer management for institutional-grade compliance.
Provides standardized disclaimers for all NIJA logging, reporting, and output.

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import logging
import os
import threading
import time
from typing import Optional

try:
    from config.environment import is_production_environment
except ImportError:
    def is_production_environment() -> bool:
        env = os.getenv("ENVIRONMENT", "").lower()
        return env in ("production", "prod")

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


COMPLIANCE_LOGGER_NAME = "nija.bootstrap"
DEFAULT_DISCLOSURE_INTERVAL_HOURS = 6.0
_DISCLOSURE_LOCK = threading.Lock()
_LAST_DISCLOSURE_TIMESTAMP = 0.0
_FIRST_BOOT_THIS_PROCESS = True


def _get_disclosure_interval_seconds() -> float:
    raw = os.getenv("NIJA_DISCLOSURE_INTERVAL_HOURS", "").strip()
    if not raw:
        return DEFAULT_DISCLOSURE_INTERVAL_HOURS * 3600
    try:
        return max(0.0, float(raw)) * 3600
    except ValueError:
        return DEFAULT_DISCLOSURE_INTERVAL_HOURS * 3600


def _should_emit_disclosure() -> bool:
    global _LAST_DISCLOSURE_TIMESTAMP, _FIRST_BOOT_THIS_PROCESS
    if not is_production_environment():
        return True

    now = time.time()
    interval_seconds = _get_disclosure_interval_seconds()
    with _DISCLOSURE_LOCK:
        if _FIRST_BOOT_THIS_PROCESS:
            _FIRST_BOOT_THIS_PROCESS = False
            _LAST_DISCLOSURE_TIMESTAMP = now
            return True
        if interval_seconds <= 0:
            return False
        if now - _LAST_DISCLOSURE_TIMESTAMP >= interval_seconds:
            _LAST_DISCLOSURE_TIMESTAMP = now
            return True
    return False


def _get_compliance_logger() -> logging.Logger:
    return logging.getLogger(COMPLIANCE_LOGGER_NAME)


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
    
    def show_validation_disclaimer(self):
        """Display the primary validation disclaimer"""
        if _should_emit_disclosure():
            self.logger.info(VALIDATION_DISCLAIMER)
    
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
    if _should_emit_disclosure():
        _get_compliance_logger().info(VALIDATION_DISCLAIMER)


def print_all_disclaimers():
    """Print all disclaimers to console"""
    if _should_emit_disclosure():
        logger = _get_compliance_logger()
        logger.info(VALIDATION_DISCLAIMER)
        logger.info(PERFORMANCE_DISCLAIMER)
        logger.info(RISK_DISCLAIMER)


# Auto-display banner when module is imported in main execution
if __name__ != "__main__":
    # Only show in non-test context
    import sys
    if not any('test' in arg.lower() for arg in sys.argv):
        # Display banner once at module import for institutional compliance
        if _should_emit_disclosure():
            _get_compliance_logger().info(VALIDATION_DISCLAIMER)
