"""
NIJA YAML User Configuration Loader
=====================================

Loads user configuration from YAML files with embedded API credentials.

File structure:
- config/users/username.yaml (e.g., daivon_frazier.yaml, tania_gilbert.yaml)

Each file contains:
  broker: KRAKEN
  api_key: YOUR_API_KEY
  api_secret: YOUR_API_SECRET
  enabled: true
  copy_from_master: true

SECURITY NOTE:
- YAML files with API keys are excluded from git via .gitignore
- Never commit files containing real API credentials
"""

import os
import yaml
import logging
from typing import Dict, List, Optional
from pathlib import Path

logger = logging.getLogger("nija.yaml_user_loader")


class YamlUserConfig:
    """
    Represents a single user configuration loaded from YAML file.
    """
    
    def __init__(
        self,
        user_id: str,
        broker: str,
        api_key: str,
        api_secret: str,
        enabled: bool = True,
        copy_from_master: bool = True,
        risk_multiplier: float = 1.0
    ):
        """
        Initialize YAML user configuration.
        
        Args:
            user_id: Unique user identifier (e.g., 'daivon_frazier')
            broker: Brokerage type (e.g., 'kraken', 'alpaca', 'coinbase')
            api_key: User's API key
            api_secret: User's API secret
            enabled: Whether this account is active
            copy_from_master: Whether to copy trades from master
            risk_multiplier: Risk multiplier (default: 1.0)
        """
        self.user_id = user_id
        self.broker = broker.lower()
        self.api_key = api_key
        self.api_secret = api_secret
        self.enabled = enabled
        self.copy_from_master = copy_from_master
        self.risk_multiplier = risk_multiplier
        
        # For compatibility with existing code
        self.account_type = "retail"
        self.broker_type = self.broker
        self.role = "user"
        
        # Extract name from user_id (e.g., 'daivon_frazier' -> 'Daivon Frazier')
        self.name = ' '.join(word.capitalize() for word in user_id.split('_'))
        self.description = f"YAML user config for {self.name}"
    
    def __repr__(self):
        status = "enabled" if self.enabled else "disabled"
        return f"YamlUserConfig({self.user_id}, {self.broker}, {status})"
    
    @classmethod
    def from_dict(cls, user_id: str, data: Dict) -> 'YamlUserConfig':
        """Create YamlUserConfig from dictionary."""
        return cls(
            user_id=user_id,
            broker=data['broker'],
            api_key=data['api_key'],
            api_secret=data['api_secret'],
            enabled=data.get('enabled', True),
            copy_from_master=data.get('copy_from_master', True),
            risk_multiplier=data.get('risk_multiplier', 1.0)
        )
    
    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'broker': self.broker,
            'api_key': self.api_key,
            'api_secret': self.api_secret,
            'enabled': self.enabled,
            'copy_from_master': self.copy_from_master,
            'risk_multiplier': self.risk_multiplier
        }
    
    def has_valid_credentials(self) -> bool:
        """
        Check if API credentials are set and non-empty.
        
        Returns:
            bool: True if both API key and secret are set
        """
        return bool(self.api_key and self.api_secret and 
                   self.api_key.strip() and self.api_secret.strip() and
                   self.api_key != 'YOUR_API_KEY_HERE' and 
                   self.api_secret != 'YOUR_API_SECRET_HERE')


class YamlUserConfigLoader:
    """
    Loads user configuration files in YAML format with embedded credentials.
    
    Expected files:
    - config/users/daivon_frazier.yaml
    - config/users/tania_gilbert.yaml
    - etc.
    
    SECURITY:
    - Files are excluded from git via .gitignore pattern: config/users/*.yaml
    - Never commit real API credentials
    """
    
    # Users to attempt loading (optional - will load any .yaml files found)
    EXPECTED_USERS = ['daivon_frazier', 'tania_gilbert']
    
    def __init__(self, config_dir: Optional[str] = None):
        """
        Initialize YAML user config loader.
        
        Args:
            config_dir: Path to config directory (defaults to config/users)
        """
        if config_dir is None:
            # Default to config/users directory relative to this file
            self.config_dir = Path(__file__).parent / "users"
        else:
            self.config_dir = Path(config_dir)
        
        self.users: Dict[str, YamlUserConfig] = {}
        self.enabled_users: List[YamlUserConfig] = []
        
        logger.info(f"YamlUserConfigLoader initialized with config_dir: {self.config_dir}")
    
    def load_all_users(self, hard_fail: bool = False) -> bool:
        """
        Load all YAML user configuration files.
        
        Args:
            hard_fail: If True, raises exception if expected users are missing valid credentials
        
        Returns:
            bool: True if at least one user was loaded successfully
            
        Raises:
            FileNotFoundError: If hard_fail=True and expected users are missing
            ValueError: If hard_fail=True and user config is invalid
        """
        if not self.config_dir.exists():
            error_msg = f"Config directory not found: {self.config_dir}"
            if hard_fail:
                raise FileNotFoundError(error_msg)
            logger.warning(error_msg)
            return False
        
        logger.info("=" * 70)
        logger.info("📄 LOADING YAML USER CONFIGURATIONS")
        logger.info("=" * 70)
        
        # Find all .yaml files in the directory (excluding .example files)
        yaml_files = [f for f in self.config_dir.glob("*.yaml") if not f.name.endswith('.example')]
        
        if not yaml_files:
            logger.info("   ℹ️  No YAML user configuration files found")
            logger.info("=" * 70)
            return False
        
        missing_users = []
        invalid_users = []
        
        # Load each YAML file
        for yaml_file in yaml_files:
            # Extract user_id from filename (e.g., 'daivon_frazier.yaml' -> 'daivon_frazier')
            user_id = yaml_file.stem
            
            try:
                user_config = self._load_user_file(yaml_file, user_id, hard_fail=hard_fail)
                if user_config:
                    self.users[user_id] = user_config
                    
                    # Check if credentials are valid
                    if user_config.has_valid_credentials():
                        if user_config.enabled:
                            self.enabled_users.append(user_config)
                            logger.info(f"   ✅ {user_config.name} ({user_config.broker}) - ENABLED")
                        else:
                            logger.info(f"   ⚪ {user_config.name} ({user_config.broker}) - DISABLED")
                    else:
                        logger.warning(f"   ⚠️  {user_config.name} ({user_config.broker}) - INVALID/PLACEHOLDER CREDENTIALS")
                        if hard_fail and user_id in self.EXPECTED_USERS:
                            invalid_users.append((user_id, "Invalid or placeholder credentials"))
                else:
                    if user_id in self.EXPECTED_USERS:
                        missing_users.append(user_id)
            except Exception as e:
                logger.error(f"   ❌ {user_id}: {str(e)}")
                if hard_fail and user_id in self.EXPECTED_USERS:
                    invalid_users.append((user_id, str(e)))
        
        logger.info("=" * 70)
        
        # Hard fail if expected users are missing or invalid
        if hard_fail and (missing_users or invalid_users):
            error_parts = []
            
            if missing_users:
                error_parts.append(f"Missing users: {', '.join(missing_users)}")
            
            if invalid_users:
                invalid_details = [f"{uid} ({err})" for uid, err in invalid_users]
                error_parts.append(f"Invalid users: {', '.join(invalid_details)}")
            
            error_msg = "HARD FAIL: " + "; ".join(error_parts)
            logger.error("=" * 70)
            logger.error(f"🛑 {error_msg}")
            logger.error("=" * 70)
            logger.error("REQUIRED ACTIONS:")
            logger.error("1. Ensure all user YAML files exist in config/users/")
            logger.error("2. Verify API keys are set correctly in YAML files")
            logger.error("3. Restart the bot after fixing")
            logger.error("=" * 70)
            raise ValueError(error_msg)
        
        total_loaded = len(self.users)
        enabled_count = len(self.enabled_users)
        
        logger.info(f"✅ Loaded {total_loaded} user(s) from YAML, {enabled_count} enabled with valid credentials")
        logger.info("=" * 70)
        
        return total_loaded > 0
    
    def _load_user_file(
        self,
        filepath: Path,
        user_id: str,
        hard_fail: bool = False
    ) -> Optional[YamlUserConfig]:
        """
        Load a single YAML user configuration file.
        
        Args:
            filepath: Path to YAML file
            user_id: User identifier (extracted from filename)
            hard_fail: If True, raises exception on errors
            
        Returns:
            YamlUserConfig if loaded successfully, None otherwise
            
        Raises:
            FileNotFoundError: If hard_fail=True and file doesn't exist
            ValueError: If hard_fail=True and YAML is invalid
        """
        if not filepath.exists():
            error_msg = f"User YAML file not found: {filepath}"
            if hard_fail:
                raise FileNotFoundError(error_msg)
            logger.debug(error_msg)
            return None
        
        try:
            with open(filepath, 'r') as f:
                data = yaml.safe_load(f)
            
            if not isinstance(data, dict):
                error_msg = f"Invalid YAML format in {filepath.name}: expected dictionary"
                if hard_fail:
                    raise ValueError(error_msg)
                logger.warning(error_msg)
                return None
            
            # Validate required fields
            required_fields = ['broker', 'api_key', 'api_secret']
            missing = [f for f in required_fields if f not in data]
            if missing:
                error_msg = f"Missing required fields in {filepath.name}: {missing}"
                if hard_fail:
                    raise ValueError(error_msg)
                logger.warning(error_msg)
                return None
            
            # Create user config
            user_config = YamlUserConfig.from_dict(user_id, data)
            return user_config
        
        except yaml.YAMLError as e:
            error_msg = f"Invalid YAML in {filepath.name}: {e}"
            if hard_fail:
                raise ValueError(error_msg)
            logger.error(error_msg)
            return None
        except Exception as e:
            error_msg = f"Error loading {filepath.name}: {e}"
            if hard_fail:
                raise ValueError(error_msg)
            logger.error(error_msg)
            return None
    
    def get_enabled_users(self) -> List[YamlUserConfig]:
        """
        Get all enabled users with valid credentials.
        
        Returns:
            List of enabled YamlUserConfig objects
        """
        return self.enabled_users
    
    def get_user_by_id(self, user_id: str) -> Optional[YamlUserConfig]:
        """
        Get a specific user by their user_id.
        
        Args:
            user_id: User identifier
            
        Returns:
            YamlUserConfig if found, None otherwise
        """
        return self.users.get(user_id)
    
    def get_users_by_broker(self, broker: str) -> List[YamlUserConfig]:
        """
        Get all users for a specific brokerage.
        
        Args:
            broker: Brokerage type (e.g., 'kraken', 'alpaca')
            
        Returns:
            List of YamlUserConfig objects for that brokerage
        """
        return [u for u in self.users.values() if u.broker.lower() == broker.lower()]


# Global instance
_yaml_user_config_loader = None


def get_yaml_user_config_loader(hard_fail: bool = False) -> YamlUserConfigLoader:
    """
    Get global YAML user config loader instance.
    
    Args:
        hard_fail: If True, raises exception if expected users are missing
    
    Returns:
        YamlUserConfigLoader instance
        
    Raises:
        FileNotFoundError: If hard_fail=True and required files missing
        ValueError: If hard_fail=True and config is invalid
    """
    global _yaml_user_config_loader
    if _yaml_user_config_loader is None:
        _yaml_user_config_loader = YamlUserConfigLoader()
        _yaml_user_config_loader.load_all_users(hard_fail=hard_fail)
    return _yaml_user_config_loader


__all__ = [
    'YamlUserConfig',
    'YamlUserConfigLoader',
    'get_yaml_user_config_loader',
]
