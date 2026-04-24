"""
APP STORE MODE - Apple App Review Safety Layer

This module implements a hard block against live trade execution when APP_STORE_MODE is enabled.
When this flag is true:
- All live trading is BLOCKED at the execution layer
- Dashboard and read-only APIs remain functional
- Apple reviewers can see UI, simulate trades, and read disclosures
- NO real orders can be placed to exchanges

This is a security and compliance layer for App Store review.
"""

import os
import logging
from typing import Tuple, Optional, Dict, Any
from enum import Enum

logger = logging.getLogger("nija.app_store_mode")


class AppStoreMode(Enum):
    """App Store mode status."""
    ENABLED = "enabled"    # App Store review mode - NO live execution
    DISABLED = "disabled"  # Normal mode - live execution allowed


class AppStoreSafetyLayer:
    """
    Safety layer that hard-blocks live execution when APP_STORE_MODE is enabled.
    
    This is a critical security feature for App Store compliance:
    - Prevents any real money trades during Apple review
    - Allows reviewers to see full UI and functionality
    - Enables simulation and read-only API access
    - Provides clear messaging about the block
    """
    
    def __init__(self):
        """Initialize App Store mode from environment."""
        self.mode = self._check_app_store_mode()
        self._log_initialization()
    
    def _check_app_store_mode(self) -> AppStoreMode:
        """
        Check if APP_STORE_MODE is enabled in environment.
        
        Returns:
            AppStoreMode: ENABLED if app store mode is active, DISABLED otherwise
        """
        # Check environment variable (must be explicitly set to 'true')
        mode_str = os.getenv('APP_STORE_MODE', 'false').lower().strip()
        
        # Only accept explicit 'true', '1', 'yes', or 'enabled'
        if mode_str in ['true', '1', 'yes', 'enabled']:
            return AppStoreMode.ENABLED
        
        return AppStoreMode.DISABLED
    
    def _log_initialization(self):
        """Log initialization status with clear visual indicators."""
        if self.is_enabled():
            logger.warning("=" * 80)
            logger.warning("🍎 APP STORE MODE: ENABLED")
            logger.warning("=" * 80)
            logger.warning("   ⚠️  ALL LIVE TRADING IS BLOCKED")
            logger.warning("   ✅ Dashboard and read-only APIs available")
            logger.warning("   ✅ Apple reviewers can view functionality")
            logger.warning("   ❌ NO real orders will be placed to exchanges")
            logger.warning("=" * 80)
        else:
            logger.info("🍎 APP Store Mode: DISABLED (live execution allowed)")
    
    def is_enabled(self) -> bool:
        """
        Check if App Store mode is currently enabled.
        
        Returns:
            bool: True if App Store mode is active (live execution blocked)
        """
        return self.mode == AppStoreMode.ENABLED
    
    def check_execution_allowed(self) -> Tuple[bool, Optional[str]]:
        """
        Check if live trade execution is allowed.
        
        This is the PRIMARY safety check that should be called before ANY
        order placement to an exchange.
        
        Returns:
            (allowed, reason): Tuple of (bool, str or None)
                - allowed: True if execution can proceed, False if blocked
                - reason: None if allowed, error message if blocked
        """
        if self.is_enabled():
            return False, (
                "🍎 APP STORE MODE ACTIVE: Live execution blocked. "
                "This is for Apple App Review compliance. "
                "Set APP_STORE_MODE=false in .env to enable live trading."
            )
        
        return True, None
    
    def block_execution_with_log(self, 
                                 operation: str,
                                 symbol: Optional[str] = None,
                                 side: Optional[str] = None,
                                 size: Optional[float] = None) -> Dict[str, Any]:
        """
        Block an execution attempt and log the details.
        
        This should be called when an execution is attempted but blocked
        by App Store mode. It logs the attempt and returns a safe response.
        
        Args:
            operation: Name of the operation (e.g., "place_market_order")
            symbol: Trading symbol if applicable
            side: Order side (buy/sell) if applicable
            size: Order size if applicable
        
        Returns:
            Dict: Safe response indicating the block
        """
        logger.warning("=" * 80)
        logger.warning("🍎 APP STORE MODE: EXECUTION BLOCKED")
        logger.warning("=" * 80)
        logger.warning(f"   Operation: {operation}")
        if symbol:
            logger.warning(f"   Symbol: {symbol}")
        if side:
            logger.warning(f"   Side: {side}")
        if size:
            logger.warning(f"   Size: {size}")
        logger.warning("   Reason: App Store review mode active")
        logger.warning("   Action: Returning simulated success response")
        logger.warning("=" * 80)
        
        # Return a simulated success response
        # This allows the UI to function but prevents real execution
        return {
            'status': 'simulated',
            'app_store_mode': True,
            'message': 'App Store mode active - execution simulated',
            'order_id': 'APP_STORE_SIMULATED',
            'symbol': symbol,
            'side': side,
            'size': size,
            'blocked': True,
        }
    
    def get_status(self) -> Dict[str, Any]:
        """
        Get current App Store mode status for API/dashboard display.
        
        Returns:
            Dict: Status information
        """
        return {
            'app_store_mode': self.is_enabled(),
            'live_execution_allowed': not self.is_enabled(),
            'mode': self.mode.value,
            'env_var': 'APP_STORE_MODE',
            'env_value': os.getenv('APP_STORE_MODE', 'not set'),
            'description': (
                'App Store review mode - live execution blocked'
                if self.is_enabled()
                else 'Normal mode - live execution allowed'
            ),
        }
    
    def get_reviewer_info(self) -> Dict[str, Any]:
        """
        Get information for Apple reviewers about available functionality.
        
        Returns:
            Dict: Information for reviewers
        """
        return {
            'app_store_mode': self.is_enabled(),
            'available_features': {
                'dashboard': True,
                'read_only_api': True,
                'account_balance': True,
                'position_viewing': True,
                'trade_history': True,
                'performance_metrics': True,
                'risk_disclosures': True,
                'simulation': True,
            },
            'blocked_features': {
                'live_trading': self.is_enabled(),
                'order_placement': self.is_enabled(),
                'position_opening': self.is_enabled(),
                'real_money_execution': self.is_enabled(),
            },
            'reviewer_message': (
                'App Store mode is ENABLED. You can view all UI elements, '
                'dashboard, and read-only APIs. Live trading is safely blocked. '
                'All risk disclosures are visible.'
                if self.is_enabled()
                else 'App Store mode is DISABLED. Live trading is enabled.'
            ),
        }


# Global App Store mode instance
_app_store_mode = AppStoreSafetyLayer()


def get_app_store_mode() -> AppStoreSafetyLayer:
    """
    Get the global App Store mode instance.
    
    Returns:
        AppStoreSafetyLayer: Global instance
    """
    return _app_store_mode


def is_app_store_mode_enabled() -> bool:
    """
    Quick check if App Store mode is enabled.
    
    Returns:
        bool: True if App Store mode is active
    """
    return _app_store_mode.is_enabled()


def check_execution_allowed() -> Tuple[bool, Optional[str]]:
    """
    Quick check if live execution is allowed.
    
    Returns:
        (allowed, reason): Tuple of (bool, str or None)
    """
    return _app_store_mode.check_execution_allowed()


__all__ = [
    'AppStoreMode',
    'AppStoreSafetyLayer',
    'get_app_store_mode',
    'is_app_store_mode_enabled',
    'check_execution_allowed',
]
