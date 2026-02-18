#!/usr/bin/env python3
"""
Capital Minimum Lock System
============================

Enforces minimum capital requirements for independent trading.
Accounts under $100 are restricted to copy-only mode.

NEW REQUIREMENT (Step 4):
- Accounts under $100 → copy-only mode
- Disable independent trading for micro accounts
- Micro accounts distort everything

Integrates with existing capital tier system (bot/capital_tier_scaling.py).
"""

import logging
from typing import Dict, Optional, Tuple
from enum import Enum

logger = logging.getLogger("nija.capital_lock")


class TradingMode(Enum):
    """Trading mode for account"""
    INDEPENDENT = "INDEPENDENT"  # Full independent trading
    COPY_ONLY = "COPY_ONLY"      # Can only copy platform trades
    DISABLED = "DISABLED"         # No trading allowed


class CapitalMinimumLock:
    """
    Enforces minimum capital requirements for trading modes.
    
    Rules:
    - Accounts >= $100: Independent trading allowed
    - Accounts < $100: Copy-only mode (no independent trading)
    - Accounts < $10: Trading disabled
    """
    
    # Capital thresholds
    MINIMUM_INDEPENDENT_CAPITAL = 100.0  # $100 minimum for independent trading
    MINIMUM_COPY_CAPITAL = 10.0          # $10 minimum for copy trading
    
    def __init__(self, broker_integration):
        """
        Initialize capital minimum lock system.
        
        Args:
            broker_integration: Broker integration instance
        """
        self.broker = broker_integration
        
        logger.info("🔒 CAPITAL MINIMUM LOCK SYSTEM INITIALIZED")
        logger.info(f"   Independent Trading Minimum: ${self.MINIMUM_INDEPENDENT_CAPITAL:.2f}")
        logger.info(f"   Copy Trading Minimum: ${self.MINIMUM_COPY_CAPITAL:.2f}")
    
    def get_account_balance(self, account_id: Optional[str] = None) -> float:
        """
        Get account balance in USD.
        
        Args:
            account_id: Account ID (None for platform account)
            
        Returns:
            Account balance in USD
        """
        try:
            if account_id:
                balance = self.broker.get_balance(account_id)
            else:
                balance = self.broker.get_balance()
            
            return float(balance.get('total_usd', 0))
        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            return 0.0
    
    def get_trading_mode(self, account_id: Optional[str] = None) -> TradingMode:
        """
        Determine trading mode based on account balance.
        
        Args:
            account_id: Account ID (None for platform account)
            
        Returns:
            TradingMode enum value
        """
        balance = self.get_account_balance(account_id)
        
        if balance >= self.MINIMUM_INDEPENDENT_CAPITAL:
            return TradingMode.INDEPENDENT
        elif balance >= self.MINIMUM_COPY_CAPITAL:
            return TradingMode.COPY_ONLY
        else:
            return TradingMode.DISABLED
    
    def can_trade_independently(self, account_id: Optional[str] = None) -> Tuple[bool, str]:
        """
        Check if account can trade independently.
        
        Args:
            account_id: Account ID (None for platform account)
            
        Returns:
            Tuple of (allowed: bool, reason: str)
        """
        balance = self.get_account_balance(account_id)
        mode = self.get_trading_mode(account_id)
        
        if mode == TradingMode.INDEPENDENT:
            return True, f"Independent trading allowed (balance: ${balance:.2f})"
        elif mode == TradingMode.COPY_ONLY:
            return False, f"Copy-only mode: balance ${balance:.2f} < ${self.MINIMUM_INDEPENDENT_CAPITAL:.2f}"
        else:
            return False, f"Trading disabled: balance ${balance:.2f} < ${self.MINIMUM_COPY_CAPITAL:.2f}"
    
    def can_copy_trade(self, account_id: Optional[str] = None) -> Tuple[bool, str]:
        """
        Check if account can copy trade.
        
        Args:
            account_id: Account ID (None for platform account)
            
        Returns:
            Tuple of (allowed: bool, reason: str)
        """
        balance = self.get_account_balance(account_id)
        mode = self.get_trading_mode(account_id)
        
        if mode in [TradingMode.INDEPENDENT, TradingMode.COPY_ONLY]:
            return True, f"Copy trading allowed (balance: ${balance:.2f})"
        else:
            return False, f"Copy trading disabled: balance ${balance:.2f} < ${self.MINIMUM_COPY_CAPITAL:.2f}"
    
    def validate_trade(self, account_id: Optional[str] = None, 
                       is_copy_trade: bool = False) -> Tuple[bool, str]:
        """
        Validate if a trade is allowed for the account.
        
        Args:
            account_id: Account ID (None for platform account)
            is_copy_trade: True if this is a copy trade
            
        Returns:
            Tuple of (allowed: bool, reason: str)
        """
        balance = self.get_account_balance(account_id)
        mode = self.get_trading_mode(account_id)
        
        # Platform account always allowed
        if account_id is None:
            return True, "Platform account - no restrictions"
        
        # Check mode
        if mode == TradingMode.DISABLED:
            return False, f"Trading disabled: balance ${balance:.2f} < ${self.MINIMUM_COPY_CAPITAL:.2f}"
        
        if mode == TradingMode.COPY_ONLY and not is_copy_trade:
            return False, f"Copy-only mode: independent trading requires ${self.MINIMUM_INDEPENDENT_CAPITAL:.2f} (current: ${balance:.2f})"
        
        return True, "Trade allowed"
    
    def get_account_restrictions(self, account_id: Optional[str] = None) -> Dict:
        """
        Get detailed account restrictions.
        
        Args:
            account_id: Account ID (None for platform account)
            
        Returns:
            Dict with restriction details
        """
        balance = self.get_account_balance(account_id)
        mode = self.get_trading_mode(account_id)
        
        can_independent, independent_reason = self.can_trade_independently(account_id)
        can_copy, copy_reason = self.can_copy_trade(account_id)
        
        return {
            'account_id': account_id or 'platform',
            'balance_usd': balance,
            'trading_mode': mode.value,
            'independent_trading': {
                'allowed': can_independent,
                'reason': independent_reason,
                'minimum_required': self.MINIMUM_INDEPENDENT_CAPITAL
            },
            'copy_trading': {
                'allowed': can_copy,
                'reason': copy_reason,
                'minimum_required': self.MINIMUM_COPY_CAPITAL
            },
            'capital_needed_for_independent': max(0, self.MINIMUM_INDEPENDENT_CAPITAL - balance)
        }
    
    def log_trade_attempt(self, account_id: Optional[str], is_copy_trade: bool,
                         allowed: bool, reason: str):
        """
        Log a trade attempt for audit purposes.
        
        Args:
            account_id: Account ID
            is_copy_trade: Whether this is a copy trade
            allowed: Whether trade was allowed
            reason: Reason for allow/deny decision
        """
        trade_type = "COPY" if is_copy_trade else "INDEPENDENT"
        status = "✅ ALLOWED" if allowed else "❌ BLOCKED"
        
        logger.info(f"{status}: {trade_type} trade for account {account_id or 'platform'}")
        logger.info(f"   Reason: {reason}")


def enforce_capital_minimum(func):
    """
    Decorator to enforce capital minimum on trading functions.
    
    Usage:
        @enforce_capital_minimum
        def place_trade(self, symbol, size, account_id=None):
            # Trade logic
            pass
    """
    def wrapper(self, *args, **kwargs):
        # Extract account_id from kwargs or args
        account_id = kwargs.get('account_id')
        if not account_id and len(args) > 2:
            account_id = args[2]
        
        # Check if this is a copy trade
        is_copy_trade = kwargs.get('is_copy_trade', False)
        
        # Get capital lock
        try:
            from bot.broker_integration import get_broker
            broker = get_broker('coinbase')  # Or get from context
            capital_lock = CapitalMinimumLock(broker)
            
            # Validate trade
            allowed, reason = capital_lock.validate_trade(account_id, is_copy_trade)
            
            if not allowed:
                capital_lock.log_trade_attempt(account_id, is_copy_trade, False, reason)
                raise ValueError(f"Trade blocked: {reason}")
            
            capital_lock.log_trade_attempt(account_id, is_copy_trade, True, reason)
            
        except ImportError:
            logger.warning("Capital lock system not available, allowing trade")
        
        # Execute trade
        return func(self, *args, **kwargs)
    
    return wrapper


# Integration with existing trading strategy
class CapitalMinimumAwareTrading:
    """
    Example integration with trading strategy.
    
    Shows how to integrate capital minimum lock with existing trading code.
    """
    
    def __init__(self, broker_integration):
        self.broker = broker_integration
        self.capital_lock = CapitalMinimumLock(broker_integration)
    
    @enforce_capital_minimum
    def execute_trade(self, symbol: str, size: float, 
                     account_id: Optional[str] = None,
                     is_copy_trade: bool = False):
        """
        Execute a trade with capital minimum enforcement.
        
        Args:
            symbol: Trading symbol
            size: Trade size
            account_id: Account ID (None for platform)
            is_copy_trade: Whether this is a copy trade
        """
        # Trade execution logic
        logger.info(f"Executing trade: {symbol} size {size}")
        # ... actual trade execution
    
    def get_account_info(self, account_id: Optional[str] = None) -> Dict:
        """Get account restrictions and info"""
        return self.capital_lock.get_account_restrictions(account_id)


# Example usage
def example_usage():
    """Example: How to use capital minimum lock"""
    from bot.broker_integration import get_broker
    
    broker = get_broker('coinbase')
    capital_lock = CapitalMinimumLock(broker)
    
    # Check user account
    user_account_id = "user123"
    
    # Get restrictions
    restrictions = capital_lock.get_account_restrictions(user_account_id)
    print(f"Account Mode: {restrictions['trading_mode']}")
    print(f"Balance: ${restrictions['balance_usd']:.2f}")
    print(f"Independent Trading: {restrictions['independent_trading']['allowed']}")
    print(f"Copy Trading: {restrictions['copy_trading']['allowed']}")
    
    # Validate a trade
    allowed, reason = capital_lock.validate_trade(user_account_id, is_copy_trade=False)
    print(f"Independent Trade Allowed: {allowed}")
    print(f"Reason: {reason}")
    
    # Validate a copy trade
    allowed, reason = capital_lock.validate_trade(user_account_id, is_copy_trade=True)
    print(f"Copy Trade Allowed: {allowed}")
    print(f"Reason: {reason}")


if __name__ == '__main__':
    # Run example
    example_usage()
