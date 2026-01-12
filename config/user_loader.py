"""
NIJA User Configuration Loader

Loads user configurations from JSON files organized by brokerage.
Each brokerage has its own user file (e.g., kraken_users.json, alpaca_users.json).

This allows adding new users without modifying code - just edit the JSON file
and restart the bot.
"""

import os
import json
import logging
from typing import Dict, List, Optional
from pathlib import Path

logger = logging.getLogger("nija.user_loader")


class UserConfig:
    """
    Represents a single user configuration.
    """
    
    def __init__(self, user_id: str, name: str, broker_type: str, enabled: bool = True, description: str = ""):
        """
        Initialize user configuration.
        
        Args:
            user_id: Unique user identifier (e.g., 'daivon_frazier')
            name: Display name (e.g., 'Daivon Frazier')
            broker_type: Brokerage type (e.g., 'kraken', 'alpaca')
            enabled: Whether this user account is active
            description: Optional description
        """
        self.user_id = user_id
        self.name = name
        self.broker_type = broker_type
        self.enabled = enabled
        self.description = description
    
    def __repr__(self):
        status = "enabled" if self.enabled else "disabled"
        return f"UserConfig({self.user_id}, {self.broker_type}, {status})"
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'UserConfig':
        """Create UserConfig from dictionary."""
        return cls(
            user_id=data['user_id'],
            name=data['name'],
            broker_type=data['broker_type'],
            enabled=data.get('enabled', True),
            description=data.get('description', '')
        )
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'user_id': self.user_id,
            'name': self.name,
            'broker_type': self.broker_type,
            'enabled': self.enabled,
            'description': self.description
        }


class UserConfigLoader:
    """
    Loads user configurations from brokerage-specific JSON files.
    
    File structure:
    - config/users/kraken_users.json
    - config/users/alpaca_users.json
    - config/users/coinbase_users.json
    """
    
    def __init__(self, config_dir: Optional[str] = None):
        """
        Initialize user config loader.
        
        Args:
            config_dir: Path to config directory (defaults to config/users)
        """
        if config_dir is None:
            # Default to config/users directory relative to this file
            self.config_dir = Path(__file__).parent / "users"
        else:
            self.config_dir = Path(config_dir)
        
        self.users_by_broker: Dict[str, List[UserConfig]] = {}
        self.all_users: List[UserConfig] = []
        
        logger.info(f"UserConfigLoader initialized with config_dir: {self.config_dir}")
    
    def load_all_users(self) -> bool:
        """
        Load all user configurations from all brokerage files.
        
        Returns:
            bool: True if at least one user was loaded successfully
        """
        if not self.config_dir.exists():
            logger.warning(f"Config directory not found: {self.config_dir}")
            logger.warning("Creating default config directory...")
            self.config_dir.mkdir(parents=True, exist_ok=True)
            return False
        
        logger.info("=" * 70)
        logger.info("📂 LOADING USER CONFIGURATIONS")
        logger.info("=" * 70)
        
        # Supported brokerages
        brokerages = ['kraken', 'alpaca', 'coinbase']
        total_loaded = 0
        
        for brokerage in brokerages:
            filename = f"{brokerage}_users.json"
            filepath = self.config_dir / filename
            
            users = self._load_brokerage_users(filepath, brokerage)
            if users:
                self.users_by_broker[brokerage] = users
                self.all_users.extend(users)
                total_loaded += len(users)
        
        logger.info("=" * 70)
        logger.info(f"✅ Loaded {total_loaded} total user(s) from {len(self.users_by_broker)} brokerage(s)")
        
        # Log summary
        for brokerage, users in self.users_by_broker.items():
            enabled_count = sum(1 for u in users if u.enabled)
            logger.info(f"   • {brokerage.upper()}: {enabled_count}/{len(users)} enabled")
        
        logger.info("=" * 70)
        
        return total_loaded > 0
    
    def _load_brokerage_users(self, filepath: Path, brokerage: str) -> List[UserConfig]:
        """
        Load users from a single brokerage JSON file.
        
        Args:
            filepath: Path to JSON file
            brokerage: Brokerage name (for validation)
            
        Returns:
            List of UserConfig objects
        """
        if not filepath.exists():
            logger.debug(f"   ⚪ {filepath.name}: File not found (skipping)")
            return []
        
        try:
            with open(filepath, 'r') as f:
                data = json.load(f)
            
            if not isinstance(data, list):
                logger.warning(f"   ❌ {filepath.name}: Invalid format (expected JSON array)")
                return []
            
            users = []
            for idx, user_data in enumerate(data):
                try:
                    # Validate required fields
                    required_fields = ['user_id', 'name', 'broker_type']
                    missing = [f for f in required_fields if f not in user_data]
                    if missing:
                        logger.warning(f"   ⚠️  {filepath.name}[{idx}]: Missing fields: {missing}")
                        continue
                    
                    # Validate broker_type matches file
                    if user_data['broker_type'] != brokerage:
                        logger.warning(
                            f"   ⚠️  {filepath.name}[{idx}]: broker_type '{user_data['broker_type']}' "
                            f"doesn't match file '{brokerage}'"
                        )
                        continue
                    
                    user = UserConfig.from_dict(user_data)
                    users.append(user)
                    
                    status = "✅ enabled" if user.enabled else "⚪ disabled"
                    logger.info(f"   {status}: {user.name} ({user.user_id})")
                
                except Exception as e:
                    logger.warning(f"   ⚠️  {filepath.name}[{idx}]: Error loading user: {e}")
                    continue
            
            if not users:
                logger.debug(f"   ⚪ {filepath.name}: No valid users found")
            
            return users
        
        except json.JSONDecodeError as e:
            logger.error(f"   ❌ {filepath.name}: Invalid JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"   ❌ {filepath.name}: Error loading file: {e}")
            return []
    
    def get_users_by_broker(self, broker_type: str) -> List[UserConfig]:
        """
        Get all users for a specific brokerage.
        
        Args:
            broker_type: Brokerage type (e.g., 'kraken', 'alpaca')
            
        Returns:
            List of UserConfig objects for that brokerage
        """
        return self.users_by_broker.get(broker_type.lower(), [])
    
    def get_enabled_users_by_broker(self, broker_type: str) -> List[UserConfig]:
        """
        Get enabled users for a specific brokerage.
        
        Args:
            broker_type: Brokerage type (e.g., 'kraken', 'alpaca')
            
        Returns:
            List of enabled UserConfig objects for that brokerage
        """
        users = self.get_users_by_broker(broker_type)
        return [u for u in users if u.enabled]
    
    def get_all_enabled_users(self) -> List[UserConfig]:
        """
        Get all enabled users across all brokerages.
        
        Returns:
            List of all enabled UserConfig objects
        """
        return [u for u in self.all_users if u.enabled]
    
    def get_user_by_id(self, user_id: str) -> Optional[UserConfig]:
        """
        Get a specific user by their user_id.
        
        Args:
            user_id: User identifier
            
        Returns:
            UserConfig if found, None otherwise
        """
        for user in self.all_users:
            if user.user_id == user_id:
                return user
        return None
    
    def get_enabled_brokerages(self) -> List[str]:
        """
        Get list of brokerages that have at least one enabled user.
        
        Returns:
            List of brokerage names
        """
        enabled_brokerages = []
        for brokerage, users in self.users_by_broker.items():
            if any(u.enabled for u in users):
                enabled_brokerages.append(brokerage)
        return enabled_brokerages
    
    def get_summary(self) -> str:
        """
        Get a summary of loaded user configurations.
        
        Returns:
            Formatted summary string
        """
        lines = []
        lines.append("=" * 70)
        lines.append("USER CONFIGURATION SUMMARY")
        lines.append("=" * 70)
        
        if not self.all_users:
            lines.append("No users configured")
            lines.append("=" * 70)
            return "\n".join(lines)
        
        total_enabled = sum(1 for u in self.all_users if u.enabled)
        lines.append(f"Total users: {len(self.all_users)}")
        lines.append(f"Enabled users: {total_enabled}")
        lines.append("")
        
        for brokerage in sorted(self.users_by_broker.keys()):
            users = self.users_by_broker[brokerage]
            enabled_users = [u for u in users if u.enabled]
            
            lines.append(f"{brokerage.upper()}:")
            lines.append(f"  Total: {len(users)}, Enabled: {len(enabled_users)}")
            
            for user in users:
                status = "✅" if user.enabled else "⚪"
                lines.append(f"    {status} {user.name} ({user.user_id})")
            lines.append("")
        
        lines.append("=" * 70)
        return "\n".join(lines)


# Global instance
_user_config_loader = None


def get_user_config_loader() -> UserConfigLoader:
    """
    Get global user config loader instance.
    
    Returns:
        UserConfigLoader instance
    """
    global _user_config_loader
    if _user_config_loader is None:
        _user_config_loader = UserConfigLoader()
        _user_config_loader.load_all_users()
    return _user_config_loader


__all__ = [
    'UserConfig',
    'UserConfigLoader',
    'get_user_config_loader',
]
