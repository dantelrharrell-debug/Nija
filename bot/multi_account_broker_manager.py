"""
NIJA Multi-Account Broker Manager
==================================

Manages separate trading accounts for:
- MASTER account: Nija system trading account
- USER accounts: Individual user/investor accounts

Each account trades independently with its own:
- API credentials
- Trading balance
- Position tracking
- Risk limits
"""

import logging
import sys
import time
from typing import Dict, List, Optional, Tuple
from enum import Enum

# Import broker classes
try:
    from bot.broker_manager import (
        BrokerType, AccountType, BaseBroker,
        CoinbaseBroker, KrakenBroker, OKXBroker, AlpacaBroker
    )
except ImportError:
    from broker_manager import (
        BrokerType, AccountType, BaseBroker,
        CoinbaseBroker, KrakenBroker, OKXBroker, AlpacaBroker
    )

logger = logging.getLogger('nija.multi_account')

# Minimum delay between sequential connections to the same broker type
# This helps prevent nonce conflicts and API rate limiting, especially for Kraken
# CRITICAL (Jan 14, 2026): Increased from 2.0s to 5.0s to further reduce Kraken nonce conflicts
# Each Kraken broker instance initializes with a random 0-5 second nonce offset.
# A 5-second delay ensures the nonce ranges don't overlap even in worst case.
MIN_CONNECTION_DELAY = 5.0  # seconds


class MultiAccountBrokerManager:
    """
    Manages brokers for multiple accounts (master + users).
    
    Each account can have connections to multiple exchanges.
    Accounts are completely isolated from each other.
    """
    
    # Maximum length for error messages stored in failed connection tracking
    # Prevents excessive memory usage from very long error strings
    MAX_ERROR_MESSAGE_LENGTH = 50
    
    def __init__(self):
        """Initialize multi-account broker manager."""
        # Master account brokers
        self.master_brokers: Dict[BrokerType, BaseBroker] = {}
        
        # User account brokers - structure: {user_id: {BrokerType: BaseBroker}}
        self.user_brokers: Dict[str, Dict[BrokerType, BaseBroker]] = {}
        
        # Track users with failed connections to avoid repeated attempts in same session
        # Structure: {(user_id, broker_type): error_reason}
        self._failed_user_connections: Dict[Tuple[str, BrokerType], str] = {}
        
        # Track users without credentials (not an error - credentials are optional)
        # Structure: {(user_id, broker_type): True}
        self._users_without_credentials: Dict[Tuple[str, BrokerType], bool] = {}
        
        # Track all user broker objects (even disconnected) to check credentials_configured flag
        # Structure: {(user_id, broker_type): BaseBroker}
        self._all_user_brokers: Dict[Tuple[str, BrokerType], BaseBroker] = {}
        
        logger.info("=" * 70)
        logger.info("🔒 MULTI-ACCOUNT BROKER MANAGER INITIALIZED")
        logger.info("=" * 70)
    
    def add_master_broker(self, broker_type: BrokerType) -> Optional[BaseBroker]:
        """
        Add a broker for the master (Nija system) account.
        
        Args:
            broker_type: Type of broker to add (COINBASE, KRAKEN, etc.)
            
        Returns:
            BaseBroker instance or None if failed
        """
        try:
            broker = None
            
            if broker_type == BrokerType.COINBASE:
                broker = CoinbaseBroker()
            elif broker_type == BrokerType.KRAKEN:
                broker = KrakenBroker(account_type=AccountType.MASTER)
            elif broker_type == BrokerType.OKX:
                broker = OKXBroker()
            elif broker_type == BrokerType.ALPACA:
                broker = AlpacaBroker()
            else:
                logger.warning(f"⚠️  Unsupported broker type for master: {broker_type.value}")
                return None
            
            # Connect the broker
            if broker.connect():
                self.master_brokers[broker_type] = broker
                logger.info(f"✅ Master broker added: {broker_type.value}")
                return broker
            else:
                logger.warning(f"⚠️  Failed to connect master broker: {broker_type.value}")
                return None
                
        except Exception as e:
            logger.error(f"❌ Error adding master broker {broker_type.value}: {e}")
            return None
    
    def add_user_broker(self, user_id: str, broker_type: BrokerType) -> Optional[BaseBroker]:
        """
        Add a broker for a user account.
        
        Args:
            user_id: User identifier (e.g., 'tania_gilbert')
            broker_type: Type of broker to add
            
        Returns:
            BaseBroker instance (even if not connected) or None if broker type unsupported
        """
        try:
            broker = None
            
            if broker_type == BrokerType.KRAKEN:
                broker = KrakenBroker(account_type=AccountType.USER, user_id=user_id)
            elif broker_type == BrokerType.ALPACA:
                broker = AlpacaBroker(account_type=AccountType.USER, user_id=user_id)
            else:
                logger.warning(f"⚠️  Unsupported broker type for user: {broker_type.value}")
                logger.warning(f"   Only KRAKEN and ALPACA are currently supported for user accounts")
                return None
            
            # Store broker object in all_user_brokers for credential checking, even if connection fails
            connection_key = (user_id, broker_type)
            self._all_user_brokers[connection_key] = broker
            
            # Connect the broker
            if broker.connect():
                if user_id not in self.user_brokers:
                    self.user_brokers[user_id] = {}
                
                self.user_brokers[user_id][broker_type] = broker
                # Note: Success/failure messages are logged by the caller (connect_users_from_config)
                # which has access to user.name for more user-friendly messages
            else:
                # Connection failed, but return broker object so caller can check credentials_configured
                pass  # Caller will log appropriate message
            
            return broker
                
        except Exception as e:
            logger.error(f"❌ Error adding user broker {broker_type.value} for {user_id}: {e}")
            return None
    
    def get_master_broker(self, broker_type: BrokerType) -> Optional[BaseBroker]:
        """
        Get a master account broker.
        
        Args:
            broker_type: Type of broker to get
            
        Returns:
            BaseBroker instance or None if not found
        """
        return self.master_brokers.get(broker_type)
    
    def get_user_broker(self, user_id: str, broker_type: BrokerType) -> Optional[BaseBroker]:
        """
        Get a user account broker.
        
        Args:
            user_id: User identifier
            broker_type: Type of broker to get
            
        Returns:
            BaseBroker instance or None if not found
        """
        user_brokers = self.user_brokers.get(user_id, {})
        return user_brokers.get(broker_type)
    
    def user_has_credentials(self, user_id: str, broker_type: BrokerType) -> bool:
        """
        Check if a user has credentials configured for a broker type.
        
        Args:
            user_id: User identifier
            broker_type: Type of broker
            
        Returns:
            bool: True if credentials are configured, False if not or unknown
        """
        connection_key = (user_id, broker_type)
        
        # If explicitly tracked as no credentials, return False
        if connection_key in self._users_without_credentials:
            return False
        
        # Check if we have a broker object (even if disconnected) to check credentials
        # This is the primary and most reliable check since all brokers inherit credentials_configured from BaseBroker
        if connection_key in self._all_user_brokers:
            broker = self._all_user_brokers[connection_key]
            return broker.credentials_configured
        
        # Check if broker exists in user_brokers (only added when connected)
        # If connected, credentials must have been configured
        if user_id in self.user_brokers and broker_type in self.user_brokers[user_id]:
            broker = self.user_brokers[user_id][broker_type]
            return broker.credentials_configured
        
        # Unknown state - default to False (no credentials)
        # This is the safe default: if we don't know, assume no credentials
        return False
    
    def get_master_balance(self, broker_type: Optional[BrokerType] = None) -> float:
        """
        Get master account balance.
        
        Args:
            broker_type: Specific broker or None for total across all brokers
            
        Returns:
            Balance in USD
        """
        if broker_type:
            broker = self.master_brokers.get(broker_type)
            return broker.get_account_balance() if broker else 0.0
        
        # Total across all master brokers
        total = 0.0
        for broker in self.master_brokers.values():
            if broker.connected:
                total += broker.get_account_balance()
        return total
    
    def get_user_balance(self, user_id: str, broker_type: Optional[BrokerType] = None) -> float:
        """
        Get user account balance.
        
        Args:
            user_id: User identifier
            broker_type: Specific broker or None for total across all brokers
            
        Returns:
            Balance in USD
        """
        user_brokers = self.user_brokers.get(user_id, {})
        
        if broker_type:
            broker = user_brokers.get(broker_type)
            return broker.get_account_balance() if broker else 0.0
        
        # Total across all user brokers
        total = 0.0
        for broker in user_brokers.values():
            if broker.connected:
                total += broker.get_account_balance()
        return total
    
    def get_all_balances(self) -> Dict:
        """
        Get balances for all accounts.
        
        Returns:
            dict with structure: {
                'master': {broker_type: balance, ...},
                'users': {user_id: {broker_type: balance, ...}, ...}
            }
        """
        result = {
            'master': {},
            'users': {}
        }
        
        # Master balances
        for broker_type, broker in self.master_brokers.items():
            if broker.connected:
                result['master'][broker_type.value] = broker.get_account_balance()
        
        # User balances
        for user_id, user_brokers in self.user_brokers.items():
            result['users'][user_id] = {}
            for broker_type, broker in user_brokers.items():
                if broker.connected:
                    result['users'][user_id][broker_type.value] = broker.get_account_balance()
        
        return result
    
    def get_status_report(self) -> str:
        """
        Generate a status report showing all accounts and balances.
        
        Returns:
            Formatted status report string
        """
        lines = []
        lines.append("=" * 70)
        lines.append("NIJA MULTI-ACCOUNT STATUS REPORT")
        lines.append("=" * 70)
        
        # Master account
        lines.append("\n🔷 MASTER ACCOUNT (Nija System)")
        lines.append("-" * 70)
        if self.master_brokers:
            master_total = 0.0
            for broker_type, broker in self.master_brokers.items():
                if broker.connected:
                    balance = broker.get_account_balance()
                    master_total += balance
                    lines.append(f"   {broker_type.value.upper()}: ${balance:,.2f}")
                else:
                    lines.append(f"   {broker_type.value.upper()}: Not connected")
            lines.append(f"   TOTAL MASTER: ${master_total:,.2f}")
        else:
            lines.append("   No master brokers configured")
        
        # User accounts
        lines.append("\n🔷 USER ACCOUNTS")
        lines.append("-" * 70)
        if self.user_brokers:
            for user_id, user_brokers in self.user_brokers.items():
                lines.append(f"\n   User: {user_id}")
                user_total = 0.0
                for broker_type, broker in user_brokers.items():
                    if broker.connected:
                        balance = broker.get_account_balance()
                        user_total += balance
                        lines.append(f"      {broker_type.value.upper()}: ${balance:,.2f}")
                    else:
                        lines.append(f"      {broker_type.value.upper()}: Not connected")
                lines.append(f"      TOTAL USER: ${user_total:,.2f}")
        else:
            lines.append("   No user brokers configured")
        
        lines.append("\n" + "=" * 70)
        
        return "\n".join(lines)
    
    def connect_users_from_config(self) -> Dict[str, List[str]]:
        """
        Connect all users from configuration files.
        
        Loads user configurations from config/users/*.json files and connects
        each enabled user to their specified brokerage.
        
        Returns:
            dict: Summary of connected users by brokerage
                  Format: {brokerage: [user_ids]}
        """
        # Import user loader
        try:
            from config.user_loader import get_user_config_loader
        except ImportError:
            try:
                import sys
                import os
                sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                from config.user_loader import get_user_config_loader
            except ImportError:
                logger.error("❌ Failed to import user_loader - cannot load user configurations")
                return {}
        
        # Load user configurations
        user_loader = get_user_config_loader()
        enabled_users = user_loader.get_all_enabled_users()
        
        if not enabled_users:
            logger.info("⚪ No enabled users found in configuration files")
            return {}
        
        logger.info("=" * 70)
        logger.info("👤 CONNECTING USERS FROM CONFIG FILES")
        logger.info("=" * 70)
        
        connected_users = {}
        
        # Track last connection time for each broker type to add delays between sequential connections
        # This prevents nonce conflicts and server-side rate limiting issues, especially for Kraken
        last_connection_time = {}
        
        for user in enabled_users:
            # Convert broker_type string to BrokerType enum
            try:
                if user.broker_type.upper() == 'KRAKEN':
                    broker_type = BrokerType.KRAKEN
                elif user.broker_type.upper() == 'ALPACA':
                    broker_type = BrokerType.ALPACA
                elif user.broker_type.upper() == 'COINBASE':
                    broker_type = BrokerType.COINBASE
                else:
                    logger.warning(f"⚠️  Unsupported broker type '{user.broker_type}' for {user.name}")
                    continue
            except Exception as e:
                logger.warning(f"⚠️  Error mapping broker type for {user.name}: {e}")
                continue
            
            # Add delay between sequential connections to the same broker type
            # This helps prevent nonce conflicts and API rate limiting, especially for Kraken
            if broker_type in last_connection_time:
                time_since_last = time.time() - last_connection_time[broker_type]
                if time_since_last < MIN_CONNECTION_DELAY:
                    delay = MIN_CONNECTION_DELAY - time_since_last
                    logger.info(f"⏱️  Waiting {delay:.1f}s before connecting next user to {broker_type.value.title()}...")
                    time.sleep(delay)
            
            logger.info(f"📊 Connecting {user.name} ({user.user_id}) to {broker_type.value.title()}...")
            # Flush to ensure this message appears before connection attempt logs
            # CRITICAL FIX: Must flush the root 'nija' logger's handlers, not the child logger's
            # Child loggers (like 'nija.multi_account', 'nija.broker') propagate to parent but
            # don't have their own handlers. Flushing logger.handlers does nothing since it's empty.
            # We need to flush the parent 'nija' logger's handlers to ensure all logs are written.
            root_nija_logger = logging.getLogger("nija")
            for handler in root_nija_logger.handlers:
                handler.flush()
            
            # SMART CACHE MANAGEMENT: Clear failed connection cache to allow retry
            # This allows automatic reconnection when credentials are added/fixed without requiring bot restart
            connection_key = (user.user_id, broker_type)
            if connection_key in self._failed_user_connections:
                # Always retry on each connect_users_from_config() call - if credentials were fixed,
                # connection will succeed; if still broken, it will fail again and be re-cached.
                # This gives users automatic retry on every bot restart without manual intervention.
                reason = self._failed_user_connections[connection_key]
                logger.info(f"   🔄 Clearing previous connection failure cache for {user.name} ({reason})")
                logger.info(f"   Will retry connection - credentials may have been added/fixed")
                del self._failed_user_connections[connection_key]
            
            try:
                broker = self.add_user_broker(user.user_id, broker_type)
                
                if broker and broker.connected:
                    # Successfully connected
                    # Track connected user
                    if broker_type.value not in connected_users:
                        connected_users[broker_type.value] = []
                    connected_users[broker_type.value].append(user.user_id)
                    
                    logger.info(f"   ✅ {user.name} connected to {broker_type.value.title()}")
                    
                    # Try to get and log balance
                    try:
                        balance = broker.get_account_balance()
                        logger.info(f"   💰 {user.name} balance: ${balance:,.2f}")
                    except Exception as bal_err:
                        logger.warning(f"   ⚠️  Could not get balance for {user.name}: {bal_err}")
                elif broker and not broker.credentials_configured:
                    # Credentials not configured - this is expected, not an error
                    # The broker's connect() method already logged informational messages
                    # Track this so we can show proper status later
                    self._users_without_credentials[connection_key] = True
                    logger.info(f"   ⚪ {user.name} - credentials not configured (optional)")
                elif broker:
                    # Actual connection failure with configured credentials
                    logger.warning(f"   ⚠️  Failed to connect {user.name} to {broker_type.value.title()}")
                    # Track the failed connection to avoid repeated attempts
                    self._failed_user_connections[connection_key] = "connection_failed"
                else:
                    # broker is None - unsupported broker type or exception
                    logger.warning(f"   ⚠️  Could not create broker for {user.name}")
                    self._failed_user_connections[connection_key] = "broker_creation_failed"
            
            except Exception as e:
                logger.warning(f"   ⚠️  Error connecting {user.name}: {e}")
                # Track the failed connection to avoid repeated attempts
                # Truncate error message to prevent excessive memory usage, add ellipsis if truncated
                error_str = str(e)
                if len(error_str) > self.MAX_ERROR_MESSAGE_LENGTH:
                    error_msg = error_str[:self.MAX_ERROR_MESSAGE_LENGTH - 3] + '...'
                else:
                    error_msg = error_str
                self._failed_user_connections[connection_key] = error_msg
                import traceback
                logger.debug(traceback.format_exc())
            
            # Track connection time for this broker type
            last_connection_time[broker_type] = time.time()
        
        # Log summary
        logger.info("=" * 70)
        if connected_users:
            total_connected = sum(len(users) for users in connected_users.values())
            logger.info(f"✅ Connected {total_connected} user(s) across {len(connected_users)} brokerage(s)")
            for brokerage, user_ids in connected_users.items():
                logger.info(f"   • {brokerage.upper()}: {len(user_ids)} user(s)")
        else:
            # Check if there are users without credentials vs actual failures
            total_without_creds = len(self._users_without_credentials)
            total_failed = len(self._failed_user_connections)
            
            if total_without_creds > 0 and total_failed == 0:
                # Only users without credentials - this is informational
                logger.info(f"⚪ No users connected ({total_without_creds} user(s) have no credentials configured)")
                logger.info("   User accounts are optional. To enable, configure API credentials in environment variables.")
            elif total_failed > 0:
                # Some actual connection failures
                logger.warning(f"⚠️  No users connected ({total_failed} connection failure(s), {total_without_creds} without credentials)")
            else:
                # No users configured at all
                logger.info("⚪ No user accounts configured")
        logger.info("=" * 70)
        
        return connected_users


# Global instance
multi_account_broker_manager = MultiAccountBrokerManager()
