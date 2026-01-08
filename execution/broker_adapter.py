"""
NIJA Execution Layer - Broker Adapter with User Permissions

Wraps broker integrations with user permission checks and rate limiting.
This module sits between the core strategy and the actual broker APIs.
"""

import logging
from typing import Dict, Optional, Any
from datetime import datetime

from auth import get_api_key_manager
from config import get_config_manager
from controls import get_hard_controls

logger = logging.getLogger("nija.execution.broker_adapter")


class SecureBrokerAdapter:
    """
    Secure broker adapter that enforces user permissions and rate limits.
    """
    
    def __init__(self, user_id: str, broker_name: str):
        """
        Initialize secure broker adapter.
        
        Args:
            user_id: User identifier
            broker_name: Broker name (coinbase, binance, alpaca, etc.)
        """
        self.user_id = user_id
        self.broker_name = broker_name
        self.api_key_manager = get_api_key_manager()
        self.config_manager = get_config_manager()
        self.hard_controls = get_hard_controls()
        self.broker_client = None
        self._load_broker_client()
        logger.info(f"Initialized secure broker adapter for user {user_id} on {broker_name}")
    
    def _load_broker_client(self):
        """Load and authenticate broker client."""
        # Get user's encrypted API keys
        credentials = self.api_key_manager.get_user_api_key(self.user_id, self.broker_name)
        
        if not credentials:
            logger.warning(f"No credentials found for user {self.user_id} on {self.broker_name}")
            return
        
        # Import and initialize appropriate broker client
        try:
            if self.broker_name == 'coinbase':
                from bot.broker_manager import BrokerManager
                # Initialize Coinbase client with user's credentials
                # TODO: Implement user-specific credential injection
                logger.info(f"Loaded Coinbase client for user {self.user_id}")
                
            elif self.broker_name == 'binance':
                # TODO: Implement Binance client
                logger.info(f"Loaded Binance client for user {self.user_id}")
                
            elif self.broker_name == 'alpaca':
                # TODO: Implement Alpaca client
                logger.info(f"Loaded Alpaca client for user {self.user_id}")
                
            else:
                logger.warning(f"Unsupported broker: {self.broker_name}")
        
        except Exception as e:
            logger.error(f"Failed to load broker client: {e}")
            self.hard_controls.record_api_error(self.user_id)
    
    def _validate_trade_request(
        self,
        pair: str,
        position_size_usd: float,
        account_balance: float
    ) -> tuple[bool, Optional[str]]:
        """
        Validate trade request against all controls.
        
        Returns:
            (is_valid, error_message)
        """
        # Check kill switches
        can_trade, error = self.hard_controls.can_trade(self.user_id)
        if not can_trade:
            return False, error
        
        # Check daily trade limit
        can_trade, error = self.hard_controls.check_daily_trade_limit(self.user_id)
        if not can_trade:
            return False, error
        
        # Get user config
        user_config = self.config_manager.get_user_config(self.user_id)
        
        # Check if pair is allowed
        if not user_config.can_trade_pair(pair):
            return False, f"Trading pair {pair} not allowed"
        
        # Validate position size against hard controls
        valid, error = self.hard_controls.validate_position_size(
            self.user_id,
            position_size_usd,
            account_balance
        )
        if not valid:
            return False, error
        
        # Validate against user config
        valid, error = user_config.validate_position_size(position_size_usd)
        if not valid:
            return False, error
        
        # Check daily loss limit
        max_daily_loss = user_config.get('max_total_exposure', 500.0) * 0.1  # 10% of max exposure
        valid, error = self.hard_controls.check_daily_loss_limit(
            self.user_id,
            max_daily_loss
        )
        if not valid:
            return False, error
        
        return True, None
    
    def place_order(
        self,
        pair: str,
        side: str,
        size_usd: float,
        order_type: str = 'market',
        **kwargs
    ) -> Optional[Dict]:
        """
        Place order with permission validation.
        
        Args:
            pair: Trading pair
            side: 'buy' or 'sell'
            size_usd: Order size in USD
            order_type: 'market' or 'limit'
            **kwargs: Additional order parameters
            
        Returns:
            dict: Order result or None if failed
        """
        # Get account balance (placeholder - implement actual balance fetch)
        account_balance = 1000.0  # TODO: Fetch actual balance
        
        # Validate trade request
        valid, error = self._validate_trade_request(pair, size_usd, account_balance)
        if not valid:
            logger.warning(f"Trade validation failed for user {self.user_id}: {error}")
            return {
                'success': False,
                'error': error,
                'user_id': self.user_id,
                'pair': pair,
                'size_usd': size_usd
            }
        
        # Execute order (placeholder - implement actual order execution)
        logger.info(f"User {self.user_id} placing {side} order: {pair} ${size_usd:.2f}")
        
        # TODO: Implement actual order execution through broker client
        # For now, return success placeholder
        return {
            'success': True,
            'user_id': self.user_id,
            'pair': pair,
            'side': side,
            'size_usd': size_usd,
            'order_type': order_type,
            'timestamp': datetime.now().isoformat()
        }
    
    def get_account_balance(self) -> Dict[str, float]:
        """
        Get account balance.
        
        Returns:
            dict: Balance information
        """
        # TODO: Implement actual balance fetch from broker
        return {
            'total_balance': 0.0,
            'available_balance': 0.0,
            'currency': 'USD'
        }
    
    def get_positions(self) -> list:
        """
        Get open positions.
        
        Returns:
            list: Open positions
        """
        # TODO: Implement actual position fetch from broker
        return []
    
    def close_position(self, pair: str) -> Optional[Dict]:
        """
        Close position.
        
        Args:
            pair: Trading pair
            
        Returns:
            dict: Close result or None if failed
        """
        logger.info(f"User {self.user_id} closing position: {pair}")
        
        # TODO: Implement actual position close through broker
        return {
            'success': True,
            'user_id': self.user_id,
            'pair': pair,
            'timestamp': datetime.now().isoformat()
        }


__all__ = [
    'SecureBrokerAdapter',
]
