"""
NIJA User Configuration Management

Manages user-specific trading configurations and preferences.

Configuration Types:
- Trading pair whitelists/blacklists
- Position size limits
- Risk tolerance settings
- Drawdown limits
- Strategy preferences (within allowed parameters)
"""

import logging
import json
from typing import Dict, Optional, List
from datetime import datetime

logger = logging.getLogger("nija.config")


class UserConfig:
    """
    User-specific trading configuration.
    """

    def __init__(self, user_id: str):
        """
        Initialize user configuration.

        Args:
            user_id: User identifier
        """
        self.user_id = user_id
        self.config = self._get_default_config()
        self.created_at = datetime.now()
        self.updated_at = datetime.now()

    def _get_default_config(self) -> Dict:
        """Get default configuration."""
        return {
            # Trading pair settings
            'allowed_pairs': None,  # None = all pairs allowed
            'blocked_pairs': [],    # Pairs to explicitly block

            # Position limits (USD)
            'min_position_size': 10.0,
            'max_position_size': 100.0,
            'max_total_exposure': 500.0,

            # Position count limits
            'max_concurrent_positions': 3,

            # Risk settings (percentage)
            'max_position_risk_pct': 2.0,      # Max 2% risk per trade
            'max_daily_loss_pct': 10.0,        # Max 10% daily loss
            'max_drawdown_pct': 20.0,          # Max 20% drawdown before auto-stop

            # Strategy settings (limited customization)
            'risk_level': 'medium',  # low, medium, high
            'enable_trailing_stops': True,
            'enable_take_profit': True,

            # Notification settings
            'notify_on_trade': True,
            'notify_on_profit_target': True,
            'notify_on_stop_loss': True,
            'notify_on_daily_limit': True,
        }

    def get(self, key: str, default=None):
        """Get configuration value."""
        return self.config.get(key, default)

    def set(self, key: str, value) -> bool:
        """
        Set configuration value.

        Args:
            key: Configuration key
            value: New value

        Returns:
            bool: True if successful
        """
        if key in self.config:
            self.config[key] = value
            self.updated_at = datetime.now()
            logger.info(f"User {self.user_id} updated config: {key} = {value}")
            return True
        else:
            logger.warning(f"User {self.user_id} attempted to set unknown config key: {key}")
            return False

    def validate_position_size(self, size_usd: float) -> tuple[bool, Optional[str]]:
        """
        Validate position size against user limits.

        Returns:
            (is_valid, error_message)
        """
        min_size = self.get('min_position_size')
        max_size = self.get('max_position_size')

        if size_usd < min_size:
            return False, f"Position size ${size_usd:.2f} below minimum ${min_size:.2f}"

        if size_usd > max_size:
            return False, f"Position size ${size_usd:.2f} exceeds maximum ${max_size:.2f}"

        return True, None

    def can_trade_pair(self, pair: str) -> bool:
        """Check if pair is allowed for trading."""
        # Check blacklist first
        if pair in self.get('blocked_pairs', []):
            return False

        # Check whitelist
        allowed = self.get('allowed_pairs')
        if allowed is None:
            return True  # All pairs allowed

        return pair in allowed

    def to_dict(self) -> Dict:
        """Export configuration as dictionary."""
        return {
            'user_id': self.user_id,
            'config': self.config,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'UserConfig':
        """Create UserConfig from dictionary."""
        user_config = cls(data['user_id'])
        user_config.config = data['config']
        user_config.created_at = datetime.fromisoformat(data['created_at'])
        user_config.updated_at = datetime.fromisoformat(data['updated_at'])
        return user_config


class ConfigManager:
    """
    Manages user configurations.
    """

    def __init__(self):
        self.configs: Dict[str, UserConfig] = {}
        logger.info("Config manager initialized")

    def get_user_config(self, user_id: str) -> UserConfig:
        """
        Get user configuration (creates if doesn't exist).

        Args:
            user_id: User identifier

        Returns:
            UserConfig instance
        """
        if user_id not in self.configs:
            self.configs[user_id] = UserConfig(user_id)
            logger.info(f"Created new config for user {user_id}")

        return self.configs[user_id]

    def update_user_config(self, user_id: str, updates: Dict) -> bool:
        """
        Update user configuration.

        Args:
            user_id: User identifier
            updates: Dictionary of configuration updates

        Returns:
            bool: True if successful
        """
        config = self.get_user_config(user_id)

        for key, value in updates.items():
            if not config.set(key, value):
                logger.warning(f"Failed to set config {key} for user {user_id}")
                return False

        return True

    def delete_user_config(self, user_id: str) -> bool:
        """Delete user configuration."""
        if user_id in self.configs:
            del self.configs[user_id]
            logger.info(f"Deleted config for user {user_id}")
            return True
        return False


# Global config manager instance
_config_manager = ConfigManager()


def get_config_manager() -> ConfigManager:
    """Get global config manager instance."""
    return _config_manager


# Import user loader
try:
    from config.user_loader import UserConfig as UserConfigData, UserConfigLoader, get_user_config_loader
except ImportError:
    try:
        from .user_loader import UserConfig as UserConfigData, UserConfigLoader, get_user_config_loader
    except ImportError:
        # Fallback if user_loader not available
        UserConfigData = None
        UserConfigLoader = None
        get_user_config_loader = None

# Import individual user loader (with hard fail support)
try:
    from config.individual_user_loader import (
        IndividualUserConfig,
        IndividualUserConfigLoader,
        get_individual_user_config_loader
    )
except ImportError:
    try:
        from .individual_user_loader import (
            IndividualUserConfig,
            IndividualUserConfigLoader,
            get_individual_user_config_loader
        )
    except ImportError:
        # Fallback if individual_user_loader not available
        IndividualUserConfig = None
        IndividualUserConfigLoader = None
        get_individual_user_config_loader = None


__all__ = [
    'UserConfig',
    'ConfigManager',
    'get_config_manager',
    'UserConfigData',
    'UserConfigLoader',
    'get_user_config_loader',
    'IndividualUserConfig',
    'IndividualUserConfigLoader',
    'get_individual_user_config_loader',
]
