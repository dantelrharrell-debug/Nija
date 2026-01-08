"""
NIJA Execution Engine - Layer 2 (LIMITED)

This layer handles broker connections, order execution, and user-specific permissions.
Access is controlled through user authentication and permission scoping.

Components:
- Broker adapters (Coinbase, Binance, Alpaca, OKX, Kraken)
- Rate limiting and API throttling
- Position sizing caps and validation
- User permission enforcement
- Order execution and routing

Access Control:
- Requires user authentication
- Enforces user-specific trading limits
- Validates permissions before each action
- Logs all trading activity per user
"""

import logging
from typing import Dict, Optional, List
from datetime import datetime

logger = logging.getLogger("nija.execution")


class UserPermissions:
    """
    User-specific trading permissions and limits.
    """
    
    def __init__(
        self,
        user_id: str,
        allowed_pairs: Optional[List[str]] = None,
        max_position_size_usd: float = 100.0,
        max_daily_loss_usd: float = 50.0,
        max_positions: int = 3,
        trade_only: bool = True,
        enabled: bool = True
    ):
        """
        Initialize user permissions.
        
        Args:
            user_id: Unique user identifier
            allowed_pairs: List of allowed trading pairs (None = all allowed)
            max_position_size_usd: Maximum position size in USD
            max_daily_loss_usd: Maximum daily loss in USD
            max_positions: Maximum concurrent positions
            trade_only: If True, user can only trade (no strategy modification)
            enabled: If False, user trading is disabled
        """
        self.user_id = user_id
        self.allowed_pairs = allowed_pairs  # None means all pairs allowed
        self.max_position_size_usd = max_position_size_usd
        self.max_daily_loss_usd = max_daily_loss_usd
        self.max_positions = max_positions
        self.trade_only = trade_only  # Cannot modify strategy
        self.enabled = enabled
        self.created_at = datetime.now()
        
    def can_trade_pair(self, pair: str) -> bool:
        """Check if user can trade this pair."""
        if not self.enabled:
            return False
        if self.allowed_pairs is None:
            return True
        return pair in self.allowed_pairs
    
    def validate_position_size(self, size_usd: float) -> bool:
        """Validate position size against user limits."""
        return size_usd <= self.max_position_size_usd
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            'user_id': self.user_id,
            'allowed_pairs': self.allowed_pairs,
            'max_position_size_usd': self.max_position_size_usd,
            'max_daily_loss_usd': self.max_daily_loss_usd,
            'max_positions': self.max_positions,
            'trade_only': self.trade_only,
            'enabled': self.enabled,
            'created_at': self.created_at.isoformat()
        }


class PermissionValidator:
    """
    Validates user permissions before executing trades.
    """
    
    def __init__(self):
        self.user_permissions: Dict[str, UserPermissions] = {}
        logger.info("Permission validator initialized")
    
    def register_user(self, permissions: UserPermissions):
        """Register user permissions."""
        self.user_permissions[permissions.user_id] = permissions
        logger.info(f"User {permissions.user_id} registered with permissions: {permissions.to_dict()}")
    
    def validate_trade(
        self,
        user_id: str,
        pair: str,
        position_size_usd: float
    ) -> tuple[bool, Optional[str]]:
        """
        Validate if user can execute this trade.
        
        Returns:
            (is_valid, error_message)
        """
        # Check if user is registered
        if user_id not in self.user_permissions:
            return False, f"User {user_id} not registered"
        
        perms = self.user_permissions[user_id]
        
        # Check if trading is enabled
        if not perms.enabled:
            return False, "Trading disabled for this user"
        
        # Check if pair is allowed
        if not perms.can_trade_pair(pair):
            return False, f"Trading pair {pair} not allowed for this user"
        
        # Check position size
        if not perms.validate_position_size(position_size_usd):
            return False, f"Position size ${position_size_usd:.2f} exceeds limit ${perms.max_position_size_usd:.2f}"
        
        return True, None
    
    def get_user_permissions(self, user_id: str) -> Optional[UserPermissions]:
        """Get user permissions."""
        return self.user_permissions.get(user_id)


# Global permission validator instance
_permission_validator = PermissionValidator()


def get_permission_validator() -> PermissionValidator:
    """Get global permission validator instance."""
    return _permission_validator


__all__ = [
    'UserPermissions',
    'PermissionValidator',
    'get_permission_validator',
]
