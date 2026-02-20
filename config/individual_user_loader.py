"""
NIJA Individual User Configuration Loader
==========================================

Loads individual user configuration files with hard fail on missing users.
Auto-enables users if their API keys exist in environment variables.

File structure:
- config/users/daivon_frazier.json
- config/users/tania_gilbert.json
- etc.

Each file contains a single user configuration with format:
{
  "name": "User Name",
  "broker": "kraken",
  "role": "user",
  "enabled": true,
  "copy_from_platform": true,
  "risk_multiplier": 1.0
}
"""

import os
import json
import logging
from typing import Dict, List, Optional
from pathlib import Path

# Import environment detection
try:
    from config.environment import is_production_environment
except ImportError:
    try:
        from .environment import is_production_environment
    except ImportError:
        # Fallback if environment detection not available
        def is_production_environment():
            return False

logger = logging.getLogger("nija.individual_user_loader")


class IndividualUserConfig:
    """
    Represents a single user configuration loaded from individual file.
    """

    def __init__(
        self,
        user_id: str,
        name: str,
        broker: str,
        role: str = "user",
        enabled: bool = True,
        copy_from_platform: bool = True,
        risk_multiplier: float = 1.0,
        independent_trading: bool = False,
        active_trading: bool = True
    ):
        """
        Initialize individual user configuration.

        Args:
            user_id: Unique user identifier (e.g., 'daivon_frazier')
            name: Display name (e.g., 'Daivon Frazier')
            broker: Brokerage type (e.g., 'kraken', 'alpaca', 'coinbase')
            role: User role (default: 'user')
            enabled: Whether this account is active
            copy_from_platform: Whether to copy trades from master
            risk_multiplier: Risk multiplier (default: 1.0)
            independent_trading: Whether user should run independent trading thread (default: False)
            active_trading: Allow new trade entries for this user (default: True). Set False during
                            recovery to stop new entries while existing positions are closed out.
        """
        self.user_id = user_id
        self.name = name
        self.broker = broker
        self.role = role
        self.enabled = enabled
        self.copy_from_platform = copy_from_platform
        self.risk_multiplier = risk_multiplier
        self.independent_trading = independent_trading
        self.active_trading = active_trading

        # For compatibility with existing code
        self.account_type = "retail"  # Default to retail
        self.broker_type = broker
        self.description = f"Individual user config for {name}"

    def __repr__(self):
        status = "enabled" if self.enabled else "disabled"
        return f"IndividualUserConfig({self.user_id}, {self.broker}, {status})"

    @classmethod
    def from_dict(cls, user_id: str, data: Dict) -> 'IndividualUserConfig':
        """Create IndividualUserConfig from dictionary."""
        return cls(
            user_id=user_id,
            name=data['name'],
            broker=data['broker'],
            role=data.get('role', 'user'),
            enabled=data.get('enabled', True),
            copy_from_platform=data.get('copy_from_platform', True),
            risk_multiplier=data.get('risk_multiplier', 1.0),
            independent_trading=data.get('independent_trading', False),
            active_trading=data.get('active_trading', True)
        )

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'name': self.name,
            'broker': self.broker,
            'role': self.role,
            'enabled': self.enabled,
            'copy_from_platform': self.copy_from_platform,
            'risk_multiplier': self.risk_multiplier,
            'independent_trading': self.independent_trading,
            'active_trading': self.active_trading
        }

    def has_api_keys(self) -> bool:
        """
        Check if API keys exist for this user in environment variables.

        Returns:
            bool: True if both API key and secret are set
        """
        # Extract firstname from user_id (e.g., 'daivon_frazier' -> 'DAIVON')
        # Validate format: expects 'firstname_lastname' or just 'firstname'
        parts = self.user_id.split('_')
        if not parts or not parts[0]:
            logger.warning(f"Invalid user_id format: {self.user_id} (expected 'firstname' or 'firstname_lastname')")
            return False

        firstname = parts[0].upper()
        broker_upper = self.broker.upper()

        # Build environment variable names
        api_key_var = f"{broker_upper}_USER_{firstname}_API_KEY"
        api_secret_var = f"{broker_upper}_USER_{firstname}_API_SECRET"

        # Check if both exist and are not empty
        api_key = os.getenv(api_key_var, "").strip()
        api_secret = os.getenv(api_secret_var, "").strip()

        return bool(api_key and api_secret)


class IndividualUserConfigLoader:
    """
    Loads individual user configuration files with hard fail on missing users.

    Expected files:
    - config/users/daivon_frazier.json
    - config/users/tania_gilbert.json

    HARD FAIL MODE:
    - If required users are missing, raises exception
    - No silent fallback
    - Auto-enables users if API keys exist
    """

    # Required users that must exist
    REQUIRED_USERS = ['daivon_frazier', 'tania_gilbert']

    def __init__(self, config_dir: Optional[str] = None):
        """
        Initialize individual user config loader.

        Args:
            config_dir: Path to config directory (defaults to config/users)
        """
        if config_dir is None:
            # Default to config/users directory relative to this file
            self.config_dir = Path(__file__).parent / "users"
        else:
            self.config_dir = Path(config_dir)

        self.users: Dict[str, IndividualUserConfig] = {}
        self.enabled_users: List[IndividualUserConfig] = []

        logger.info(f"IndividualUserConfigLoader initialized with config_dir: {self.config_dir}")

    def load_all_users(self, hard_fail: bool = True, require_api_keys: bool = True) -> bool:
        """
        Load all individual user configuration files.

        Args:
            hard_fail: If True, raises exception if required users are missing
            require_api_keys: If True (with hard_fail), also requires API keys to be set

        Returns:
            bool: True if at least one user was loaded successfully

        Raises:
            FileNotFoundError: If hard_fail=True and required users are missing
            ValueError: If hard_fail=True and user config is invalid or API keys missing
        """
        if not self.config_dir.exists():
            error_msg = f"Config directory not found: {self.config_dir}"
            if hard_fail:
                raise FileNotFoundError(error_msg)
            logger.warning(error_msg)
            return False

        mode_str = "HARD FAIL" if hard_fail else "SOFT FAIL"
        logger.info("=" * 70)
        logger.info(f"👤 LOADING INDIVIDUAL USER CONFIGURATIONS ({mode_str} MODE)")
        logger.info("=" * 70)

        missing_users = []
        invalid_users = []

        # Load each required user
        for user_id in self.REQUIRED_USERS:
            filename = f"{user_id}.json"
            filepath = self.config_dir / filename

            try:
                user_config = self._load_user_file(filepath, user_id, hard_fail=hard_fail)
                if user_config:
                    self.users[user_id] = user_config

                    # Auto-enable if API keys exist
                    if user_config.has_api_keys():
                        if not user_config.enabled:
                            logger.info(f"   🔧 AUTO-ENABLING {user_id} (API keys found)")
                            user_config.enabled = True
                        self.enabled_users.append(user_config)
                        logger.info(f"   ✅ {user_config.name} ({user_config.broker}) - ENABLED")
                    else:
                        logger.warning(f"   ⚠️  {user_config.name} ({user_config.broker}) - NO API KEYS")
                        if hard_fail and require_api_keys:
                            invalid_users.append((user_id, "Missing API keys in environment"))
                else:
                    missing_users.append(user_id)
            except Exception as e:
                logger.error(f"   ❌ {user_id}: {str(e)}")
                if hard_fail:
                    invalid_users.append((user_id, str(e)))
                missing_users.append(user_id)

        logger.info("=" * 70)

        # Hard fail if required users are missing or invalid
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
            logger.error("1. Ensure all user config files exist in config/users/")
            logger.error("2. Verify API keys are set in environment variables")
            logger.error("3. Restart the bot after fixing")
            logger.error("=" * 70)
            raise ValueError(error_msg)

        total_loaded = len(self.users)
        enabled_count = len(self.enabled_users)

        logger.info(f"✅ Loaded {total_loaded} user(s), {enabled_count} enabled")
        logger.info("=" * 70)

        return total_loaded > 0

    def _load_user_file(
        self,
        filepath: Path,
        user_id: str,
        hard_fail: bool = True
    ) -> Optional[IndividualUserConfig]:
        """
        Load a single individual user configuration file.

        Args:
            filepath: Path to JSON file
            user_id: User identifier (used as filename)
            hard_fail: If True, raises exception on errors

        Returns:
            IndividualUserConfig if loaded successfully, None otherwise

        Raises:
            FileNotFoundError: If hard_fail=True and file doesn't exist
            ValueError: If hard_fail=True and JSON is invalid
        """
        if not filepath.exists():
            error_msg = f"User config file not found: {filepath}"
            if hard_fail:
                raise FileNotFoundError(error_msg)
            logger.debug(error_msg)
            return None

        try:
            with open(filepath, 'r') as f:
                data = json.load(f)

            # Validate required fields
            required_fields = ['name', 'broker']
            missing = [f for f in required_fields if f not in data]
            if missing:
                error_msg = f"Missing required fields in {filepath.name}: {missing}"
                if hard_fail:
                    raise ValueError(error_msg)
                logger.warning(error_msg)
                return None

            # Create user config
            user_config = IndividualUserConfig.from_dict(user_id, data)
            return user_config

        except json.JSONDecodeError as e:
            error_msg = f"Invalid JSON in {filepath.name}: {e}"
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

    def get_enabled_users(self) -> List[IndividualUserConfig]:
        """
        Get all enabled users.

        Returns:
            List of enabled IndividualUserConfig objects
        """
        return self.enabled_users

    def get_user_by_id(self, user_id: str) -> Optional[IndividualUserConfig]:
        """
        Get a specific user by their user_id.

        Args:
            user_id: User identifier

        Returns:
            IndividualUserConfig if found, None otherwise
        """
        return self.users.get(user_id)

    def get_users_by_broker(self, broker: str) -> List[IndividualUserConfig]:
        """
        Get all users for a specific brokerage.

        Args:
            broker: Brokerage type (e.g., 'kraken', 'alpaca')

        Returns:
            List of IndividualUserConfig objects for that brokerage
        """
        return [u for u in self.users.values() if u.broker.lower() == broker.lower()]


# Global instance
_individual_user_config_loader = None


def get_individual_user_config_loader(hard_fail: bool = None, require_api_keys: bool = True) -> IndividualUserConfigLoader:
    """
    Get global individual user config loader instance.

    Args:
        hard_fail: If True, raises exception if required users are missing.
                   If None (default), automatically determined based on environment:
                   - Production: hard_fail=True (strict validation required)
                   - Development: hard_fail=False (lenient for local testing)
        require_api_keys: If True (with hard_fail), also requires API keys to be set

    Returns:
        IndividualUserConfigLoader instance

    Raises:
        FileNotFoundError: If hard_fail=True and required files missing
        ValueError: If hard_fail=True and config is invalid or API keys missing
    """
    global _individual_user_config_loader
    if _individual_user_config_loader is None:
        # Auto-detect environment if not explicitly specified
        if hard_fail is None:
            hard_fail = is_production_environment()
            if hard_fail:
                logger.info("🔒 Production environment detected - enforcing strict user credential validation")
        
        _individual_user_config_loader = IndividualUserConfigLoader()
        _individual_user_config_loader.load_all_users(hard_fail=hard_fail, require_api_keys=require_api_keys)
    return _individual_user_config_loader


__all__ = [
    'IndividualUserConfig',
    'IndividualUserConfigLoader',
    'get_individual_user_config_loader',
]
