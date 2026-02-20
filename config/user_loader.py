"""
NIJA User Configuration Loader

Loads user configurations from JSON files organized by account type AND brokerage.

File structure:
- Retail users: retail_kraken.json, retail_alpaca.json, retail_coinbase.json
- Investors: investor_kraken.json, investor_alpaca.json, investor_coinbase.json

The MASTER (NIJA system) controls all retail and investor accounts.
All accounts trade according to NIJA's strategy and parameters.

This allows adding new users/investors without modifying code - just edit the appropriate JSON file
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
    Represents a single user or investor configuration.
    """

    def __init__(self, user_id: str, name: str, account_type: str, broker_type: str, enabled: bool = True, description: str = "", copy_from_platform: bool = True, disabled_symbols: Optional[List[str]] = None, independent_trading: bool = False, active_trading: bool = True):
        """
        Initialize user/investor configuration.

        Args:
            user_id: Unique user identifier (e.g., 'daivon_frazier')
            name: Display name (e.g., 'Daivon Frazier')
            account_type: 'retail' or 'investor'
            broker_type: Brokerage type (e.g., 'kraken', 'alpaca', 'coinbase')
            enabled: Whether this account is active
            description: Optional description
            copy_from_platform: Whether to copy trades from master (default: True)
            disabled_symbols: List of symbols to disable for this user (default: None)
            independent_trading: Whether user should run independent trading thread (default: False)
            active_trading: Allow new trade entries for this user (default: True). Set False during
                            recovery to stop new entries while existing positions are closed out.
        """
        self.user_id = user_id
        self.name = name
        self.account_type = account_type
        self.broker_type = broker_type
        self.enabled = enabled
        self.description = description
        self.copy_from_platform = copy_from_platform
        self.disabled_symbols = disabled_symbols or []
        self.independent_trading = independent_trading
        self.active_trading = active_trading

    def __repr__(self):
        status = "enabled" if self.enabled else "disabled"
        return f"UserConfig({self.user_id}, {self.account_type}, {self.broker_type}, {status})"

    @classmethod
    def from_dict(cls, data: Dict) -> 'UserConfig':
        """Create UserConfig from dictionary."""
        return cls(
            user_id=data['user_id'],
            name=data['name'],
            account_type=data['account_type'],
            broker_type=data['broker_type'],
            enabled=data.get('enabled', True),
            description=data.get('description', ''),
            copy_from_platform=data.get('copy_from_platform', True),
            disabled_symbols=data.get('disabled_symbols', []),
            independent_trading=data.get('independent_trading', False),
            active_trading=data.get('active_trading', True)
        )

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'user_id': self.user_id,
            'name': self.name,
            'account_type': self.account_type,
            'broker_type': self.broker_type,
            'enabled': self.enabled,
            'description': self.description,
            'copy_from_platform': self.copy_from_platform,
            'disabled_symbols': self.disabled_symbols,
            'independent_trading': self.independent_trading,
            'active_trading': self.active_trading
        }


class UserConfigLoader:
    """
    Loads user configurations from account-type and brokerage-specific JSON files.

    File structure:
    - config/users/retail_kraken.json - Retail users on Kraken
    - config/users/retail_alpaca.json - Retail users on Alpaca
    - config/users/retail_coinbase.json - Retail users on Coinbase
    - config/users/investor_kraken.json - Investors on Kraken
    - config/users/investor_alpaca.json - Investors on Alpaca
    - config/users/investor_coinbase.json - Investors on Coinbase

    The MASTER (NIJA) controls all these accounts.
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

        self.users_by_type: Dict[str, List[UserConfig]] = {}  # retail or investor
        self.users_by_broker: Dict[str, List[UserConfig]] = {}  # kraken, alpaca, etc.
        self.users_by_type_and_broker: Dict[str, Dict[str, List[UserConfig]]] = {}  # {retail: {kraken: [...]}}
        self.all_users: List[UserConfig] = []

        logger.info(f"UserConfigLoader initialized with config_dir: {self.config_dir}")

    def load_all_users(self) -> bool:
        """
        Load all user configurations from all account type and brokerage files.

        Returns:
            bool: True if at least one user was loaded successfully
        """
        if not self.config_dir.exists():
            logger.warning(f"Config directory not found: {self.config_dir}")
            logger.warning("Creating default config directory...")
            self.config_dir.mkdir(parents=True, exist_ok=True)
            return False

        logger.info("=" * 70)
        logger.info("📂 LOADING USER/INVESTOR CONFIGURATIONS")
        logger.info("=" * 70)
        logger.info("🎯 Independent account group loaded (no trade copying)")
        logger.info("=" * 70)

        # Account types and brokerages
        account_types = ['retail', 'investor']
        brokerages = ['kraken', 'alpaca', 'coinbase']

        total_loaded = 0

        for account_type in account_types:
            if account_type not in self.users_by_type_and_broker:
                self.users_by_type_and_broker[account_type] = {}

            for brokerage in brokerages:
                filename = f"{account_type}_{brokerage}.json"
                filepath = self.config_dir / filename

                users = self._load_user_file(filepath, account_type, brokerage)

                if users:
                    # Store by type+broker
                    self.users_by_type_and_broker[account_type][brokerage] = users

                    # Store by type
                    if account_type not in self.users_by_type:
                        self.users_by_type[account_type] = []
                    self.users_by_type[account_type].extend(users)

                    # Store by broker
                    if brokerage not in self.users_by_broker:
                        self.users_by_broker[brokerage] = []
                    self.users_by_broker[brokerage].extend(users)

                    # Add to all users
                    self.all_users.extend(users)
                    total_loaded += len(users)

        logger.info("=" * 70)
        logger.info(f"✅ Loaded {total_loaded} account(s) - each trading independently")

        # Log summary by account type
        for account_type in account_types:
            users = self.users_by_type.get(account_type, [])
            if users:
                enabled_count = sum(1 for u in users if u.enabled)
                logger.info(f"   • {account_type.upper()}: {enabled_count}/{len(users)} enabled")

        # Log summary by broker
        logger.info("")
        logger.info("Distribution by brokerage:")
        for brokerage in brokerages:
            users = self.users_by_broker.get(brokerage, [])
            if users:
                enabled_count = sum(1 for u in users if u.enabled)
                logger.info(f"   • {brokerage.upper()}: {enabled_count}/{len(users)} enabled")

        logger.info("=" * 70)

        return total_loaded > 0

    def _load_user_file(self, filepath: Path, account_type: str, brokerage: str) -> List[UserConfig]:
        """
        Load users from a single account type + brokerage JSON file.

        Args:
            filepath: Path to JSON file
            account_type: Account type (retail or investor)
            brokerage: Brokerage name (kraken, alpaca, coinbase)

        Returns:
            List of UserConfig objects
        """
        if not filepath.exists():
            logger.debug(f"   ⚪ {filepath.name}: File not found (creating empty)")
            # Create empty file
            try:
                with open(filepath, 'w') as f:
                    json.dump([], f, indent=2)
            except Exception as e:
                logger.debug(f"   ⚠️  Could not create {filepath.name}: {e}")
            return []

        try:
            with open(filepath, 'r') as f:
                data = json.load(f)

            if not isinstance(data, list):
                logger.warning(f"   ❌ {filepath.name}: Invalid format (expected JSON array)")
                return []

            if not data:
                # Empty file is OK, just skip
                return []

            users = []
            for idx, user_data in enumerate(data):
                try:
                    # Validate required fields
                    required_fields = ['user_id', 'name', 'account_type', 'broker_type']
                    missing = [f for f in required_fields if f not in user_data]
                    if missing:
                        logger.warning(f"   ⚠️  {filepath.name}[{idx}]: Missing fields: {missing}")
                        continue

                    # Validate account_type matches file
                    if user_data['account_type'] != account_type:
                        logger.warning(
                            f"   ⚠️  {filepath.name}[{idx}]: account_type '{user_data['account_type']}' "
                            f"doesn't match file '{account_type}'"
                        )
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

                    status = "✅" if user.enabled else "⚪"
                    logger.info(f"   {status} {account_type.upper()}/{brokerage.upper()}: {user.name}")

                except Exception as e:
                    logger.warning(f"   ⚠️  {filepath.name}[{idx}]: Error loading user: {e}")
                    continue

            return users

        except json.JSONDecodeError as e:
            logger.error(f"   ❌ {filepath.name}: Invalid JSON: {e}")
            return []
        except Exception as e:
            logger.error(f"   ❌ {filepath.name}: Error loading file: {e}")
            return []

    def get_users_by_type(self, account_type: str) -> List[UserConfig]:
        """
        Get all users by account type (retail or investor).

        Args:
            account_type: 'retail' or 'investor'

        Returns:
            List of UserConfig objects for that account type
        """
        return self.users_by_type.get(account_type.lower(), [])

    def get_enabled_users_by_type(self, account_type: str) -> List[UserConfig]:
        """
        Get enabled users by account type.

        Args:
            account_type: 'retail' or 'investor'

        Returns:
            List of enabled UserConfig objects for that account type
        """
        users = self.get_users_by_type(account_type)
        return [u for u in users if u.enabled]

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
        Get all enabled users across all account types and brokerages.

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
        lines.append("USER/INVESTOR CONFIGURATION SUMMARY")
        lines.append("=" * 70)
        lines.append("🎯 All accounts controlled by MASTER (NIJA)")
        lines.append("=" * 70)

        if not self.all_users:
            lines.append("No users/investors configured")
            lines.append("=" * 70)
            return "\n".join(lines)

        total_enabled = sum(1 for u in self.all_users if u.enabled)
        lines.append(f"Total accounts: {len(self.all_users)}")
        lines.append(f"Enabled accounts: {total_enabled}")
        lines.append("")

        # By account type
        lines.append("BY ACCOUNT TYPE:")
        for account_type in sorted(self.users_by_type.keys()):
            users = self.users_by_type[account_type]
            enabled_users = [u for u in users if u.enabled]

            lines.append(f"  {account_type.upper()}:")
            lines.append(f"    Total: {len(users)}, Enabled: {len(enabled_users)}")

            for user in users:
                status = "✅" if user.enabled else "⚪"
                lines.append(f"      {status} {user.name} ({user.broker_type})")

        lines.append("")

        # By brokerage
        lines.append("BY BROKERAGE:")
        for brokerage in sorted(self.users_by_broker.keys()):
            users = self.users_by_broker[brokerage]
            enabled_users = [u for u in users if u.enabled]

            lines.append(f"  {brokerage.upper()}: {len(enabled_users)}/{len(users)} enabled")

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
