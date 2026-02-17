"""
NIJA Multi-Account Broker Manager
==================================

Manages separate trading accounts for:
- PLATFORM account: Nija system trading account
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
from types import MappingProxyType
import traceback
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

# Import account isolation manager for failure isolation
try:
    from bot.account_isolation_manager import get_isolation_manager, FailureType
except ImportError:
    try:
        from account_isolation_manager import get_isolation_manager, FailureType
    except ImportError:
        get_isolation_manager = None
        FailureType = None

logger = logging.getLogger('nija.multi_account')

# Root nija logger for flushing all handlers
# Child loggers (like 'nija.multi_account', 'nija.broker') propagate to this logger
# but don't have their own handlers, so we need to flush the root logger's handlers
_root_logger = logging.getLogger('nija')

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

    # CRITICAL FIX (Jan 19, 2026): Balance cache for Kraken sequential API calls
    # Railway Golden Rule #3: Kraken = sequential API calls with delay + caching
    # Problem: Sequential balance calls cause 1-1.2s delay per user
    # Solution: Cache balances per trading cycle to prevent repeated API calls
    BALANCE_CACHE_TTL = 120.0  # Cache balance for 2 minutes (one trading cycle)
    KRAKEN_BALANCE_CALL_DELAY = 1.1  # 1.1s delay between Kraken balance API calls

    def __init__(self):
        """Initialize multi-account broker manager."""
        # Platform account brokers - registered once globally and marked immutable
        self._platform_brokers: Dict[BrokerType, BaseBroker] = {}
        self._platform_brokers_locked: bool = False

        # User account brokers - structure: {user_id: {BrokerType: BaseBroker}}
        self.user_brokers: Dict[str, Dict[BrokerType, BaseBroker]] = {}

        # User configurations - structure: {user_id: UserConfig}
        # Stores user configs to check independent_trading and other settings
        self.user_configs: Dict[str, any] = {}

        # FIX #3: User portfolio states for total equity tracking
        # Structure: {(user_id, broker_type): UserPortfolioState}
        self.user_portfolios: Dict[Tuple[str, str], any] = {}

        # Track users with failed connections to avoid repeated attempts in same session
        # Structure: {(user_id, broker_type): error_reason}
        self._failed_user_connections: Dict[Tuple[str, BrokerType], str] = {}

        # Track users without credentials (not an error - credentials are optional)
        # Structure: {(user_id, broker_type): True}
        self._users_without_credentials: Dict[Tuple[str, BrokerType], bool] = {}

        # Track all user broker objects (even disconnected) to check credentials_configured flag
        # Structure: {(user_id, broker_type): BaseBroker}
        self._all_user_brokers: Dict[Tuple[str, BrokerType], BaseBroker] = {}

        # CRITICAL FIX (Jan 19, 2026): Balance cache to prevent repeated Kraken API calls
        # Structure: {(account_type, account_id, broker_type): (balance, timestamp)}
        # This prevents calling get_account_balance() multiple times per cycle for same user
        self._balance_cache: Dict[Tuple[str, str, BrokerType], Tuple[float, float]] = {}
        # Track last Kraken balance API call time for rate limiting
        self._last_kraken_balance_call: float = 0.0

        # User metadata storage for audit and reporting
        # Structure: {user_id: {'name': str, 'enabled': bool, 'brokers': {BrokerType: bool}}}
        self._user_metadata: Dict[str, Dict] = {}

        # Track Kraken copy trading status (DEPRECATED - kept for backward compatibility)
        # NOTE: Copy trading is deprecated. NIJA uses independent trading where all accounts
        # trade independently. This flag is set to True only if legacy copy trading module exists.
        # Expected value: False (copy trading module doesn't exist)
        self.kraken_copy_trading_active: bool = False

        # FIX #3: Initialize portfolio manager for user portfolio states
        try:
            from portfolio_state import get_portfolio_manager
            self.portfolio_manager = get_portfolio_manager()
            logger.info("✅ Portfolio manager initialized for user accounts")
        except ImportError:
            logger.warning("⚠️ Portfolio state module not available")
            self.portfolio_manager = None

        # ISOLATION MANAGER: Initialize account isolation manager for failure isolation
        # This ensures one account failure can NEVER affect another account
        self.isolation_manager = None
        if get_isolation_manager is not None:
            try:
                self.isolation_manager = get_isolation_manager()
                logger.info("✅ Account isolation manager initialized - failure isolation active")
            except Exception as e:
                logger.warning(f"⚠️ Could not initialize isolation manager: {e}")

        logger.info("=" * 70)
        logger.info("🔒 MULTI-ACCOUNT BROKER MANAGER INITIALIZED")
        logger.info("=" * 70)

    @property
    def platform_brokers(self) -> Dict[BrokerType, BaseBroker]:
        """
        Read-only access to platform brokers.
        
        Platform brokers must be registered via add_platform_broker() or
        register_platform_broker_instance() methods. Direct assignment is not allowed.
        
        Returns:
            Read-only mapping proxy of platform brokers (Dict[BrokerType, BaseBroker])
        """
        return MappingProxyType(self._platform_brokers)
    
    def _lock_platform_brokers(self):
        """
        Lock platform brokers to prevent further modifications.
        Called after initial broker registration is complete.
        """
        self._platform_brokers_locked = True
        logger.info("🔒 Platform brokers locked (immutable)")

    def register_platform_broker_instance(self, broker_type: BrokerType, broker: BaseBroker) -> bool:
        """
        Register an already-created broker instance for the platform account.
        
        This method is for cases where the broker is created externally with custom configuration.
        Enforces the same invariant: Platform brokers registered once, globally, and marked immutable.
        
        Args:
            broker_type: Type of broker being registered
            broker: Already-created BaseBroker instance
            
        Returns:
            True if successfully registered
            
        Raises:
            RuntimeError: If platform brokers are locked or broker already registered
        """
        # Enforce immutability: Cannot add brokers after locking
        if self._platform_brokers_locked:
            error_msg = f"❌ INVARIANT VIOLATION: Cannot register platform broker {broker_type.value} - platform brokers are locked (immutable)"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        # Enforce single registration: Check if already registered
        if broker_type in self._platform_brokers:
            error_msg = f"❌ INVARIANT VIOLATION: Platform broker {broker_type.value} already registered - duplicate registration not allowed"
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        # Register the broker instance
        self._platform_brokers[broker_type] = broker
        logger.info(f"✅ Platform broker instance registered: {broker_type.value}")
        logger.info(f"   Platform broker registered once, globally")
        return True

    def add_platform_broker(self, broker_type: BrokerType) -> Optional[BaseBroker]:
        """
        Add a broker for the master (Nija system) account.
        
        Enforces invariant: Platform brokers are registered once, globally, and marked immutable.

        Args:
            broker_type: Type of broker to add (COINBASE, KRAKEN, etc.)

        Returns:
            BaseBroker instance or None if failed
            
        Raises:
            RuntimeError: If platform brokers are locked or broker already registered
        """
        try:
            # Enforce immutability: Cannot add brokers after locking
            if self._platform_brokers_locked:
                error_msg = f"❌ INVARIANT VIOLATION: Cannot add platform broker {broker_type.value} - platform brokers are locked (immutable)"
                logger.error(error_msg)
                raise RuntimeError(error_msg)
            
            # Enforce single registration: Check if already registered
            if broker_type in self._platform_brokers:
                error_msg = f"❌ INVARIANT VIOLATION: Platform broker {broker_type.value} already registered - duplicate registration not allowed"
                logger.error(error_msg)
                raise RuntimeError(error_msg)
            
            broker = None

            if broker_type == BrokerType.COINBASE:
                broker = CoinbaseBroker()
            elif broker_type == BrokerType.KRAKEN:
                broker = KrakenBroker(account_type=AccountType.PLATFORM)
            elif broker_type == BrokerType.OKX:
                broker = OKXBroker()
            elif broker_type == BrokerType.ALPACA:
                broker = AlpacaBroker()
            else:
                logger.warning(f"⚠️  Unsupported broker type for platform: {broker_type.value}")
                return None

            # Connect the broker
            if broker.connect():
                self._platform_brokers[broker_type] = broker
                logger.info(f"✅ Platform broker added: {broker_type.value}")
                logger.info(f"   Platform broker registered once, globally")
                return broker
            else:
                logger.warning(f"⚠️  Failed to connect platform broker: {broker_type.value}")
                return None

        except Exception as e:
            logger.error(f"❌ Error adding platform broker {broker_type.value}: {e}")
            return None

    def add_user_broker(self, user_id: str, broker_type: BrokerType) -> Optional[BaseBroker]:
        """
        Add a broker for a user account with complete isolation.
        
        ISOLATION GUARANTEE: Failures in this operation will NOT affect other accounts.
        Each user account operates independently with its own error handling.

        Args:
            user_id: User identifier (e.g., 'tania_gilbert')
            broker_type: Type of broker to add

        Returns:
            BaseBroker instance (even if not connected) or None if broker type unsupported
        """
        try:
            # Register account with isolation manager before operation
            if self.isolation_manager:
                self.isolation_manager.register_account('user', user_id, broker_type.value)
                
                # Check if account can execute operations (circuit breaker check)
                can_execute, reason = self.isolation_manager.can_execute_operation(
                    'user', user_id, broker_type.value
                )
                if not can_execute:
                    logger.warning(f"⚠️  Cannot add broker for {user_id}/{broker_type.value}: {reason}")
                    # Return None but don't count as failure - account is quarantined
                    return None
            
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

            # Connect the broker (wrapped in isolation)
            connect_start = time.time()
            try:
                if broker.connect():
                    if user_id not in self.user_brokers:
                        self.user_brokers[user_id] = {}

                    self.user_brokers[user_id][broker_type] = broker
                    
                    # Record success with isolation manager
                    if self.isolation_manager:
                        operation_time_ms = (time.time() - connect_start) * 1000
                        self.isolation_manager.record_success(
                            'user', user_id, broker_type.value, operation_time_ms
                        )
                    
                    # Note: Success/failure messages are logged by the caller (connect_users_from_config)
                    # which has access to user.name for more user-friendly messages
                else:
                    # Connection failed - determine failure type and record
                    if self.isolation_manager:
                        # Check if it's an authentication error
                        if not broker.credentials_configured:
                            failure_type = FailureType.AUTHENTICATION_ERROR if FailureType else None
                        else:
                            failure_type = FailureType.NETWORK_ERROR if FailureType else None
                        
                        if failure_type:
                            self.isolation_manager.record_failure(
                                'user', user_id, broker_type.value,
                                Exception("Connection failed"),
                                failure_type
                            )
                    # Caller will log appropriate message
                    pass
                    
            except Exception as connect_error:
                # Connection attempt raised an exception - record failure
                logger.error(f"❌ Exception connecting {broker_type.value} for {user_id}: {connect_error}")
                
                if self.isolation_manager:
                    # Determine failure type from exception
                    error_str = str(connect_error).lower()
                    if 'auth' in error_str or 'credential' in error_str or 'permission' in error_str:
                        failure_type = FailureType.AUTHENTICATION_ERROR if FailureType else None
                    elif 'rate' in error_str or 'limit' in error_str:
                        failure_type = FailureType.RATE_LIMIT_ERROR if FailureType else None
                    elif 'network' in error_str or 'connection' in error_str or 'timeout' in error_str:
                        failure_type = FailureType.NETWORK_ERROR if FailureType else None
                    else:
                        failure_type = FailureType.UNKNOWN_ERROR if FailureType else None
                    
                    if failure_type:
                        self.isolation_manager.record_failure(
                            'user', user_id, broker_type.value,
                            connect_error,
                            failure_type
                        )

            return broker

        except Exception as e:
            # Top-level exception handler - ensures this account failure doesn't affect others
            logger.error(f"❌ Error adding user broker {broker_type.value} for {user_id}: {e}")
            logger.error(f"   ISOLATION: This failure is contained to {user_id} only")
            
            if self.isolation_manager and FailureType:
                self.isolation_manager.record_failure(
                    'user', user_id, broker_type.value,
                    e,
                    FailureType.UNKNOWN_ERROR
                )
            
            return None

    def get_platform_broker(self, broker_type: BrokerType) -> Optional[BaseBroker]:
        """
        Get a platform account broker.

        Args:
            broker_type: Type of broker to get

        Returns:
            BaseBroker instance or None if not found
        """
        return self._platform_brokers.get(broker_type)

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

    def is_platform_connected(self, broker_type: BrokerType) -> bool:
        """
        Check if a platform account is connected for a given broker type.

        Args:
            broker_type: Type of broker to check

        Returns:
            bool: True if platform is connected, False otherwise
        """
        try:
            # Validate broker_type parameter
            if broker_type is None:
                logger.error("❌ is_platform_connected called with broker_type=None")
                return False
                
            # Debug logging to diagnose false warnings
            broker_in_dict = broker_type in self.platform_brokers
            
            if not broker_in_dict:
                logger.debug(f"🔍 Platform broker check for {broker_type.value}: NOT in platform_brokers dict")
                # Format registered brokers efficiently without creating intermediate list
                registered = ', '.join(bt.value for bt in self.platform_brokers.keys()) if self.platform_brokers else 'none'
                logger.debug(f"   Registered platform brokers: {registered}")
                return False
            
            broker_obj = self.platform_brokers[broker_type]
            
            # Defensive check: Ensure broker object exists and has connected attribute
            if broker_obj is None:
                logger.debug(f"🔍 Platform broker check for {broker_type.value}: broker object is None")
                return False
            
            if not hasattr(broker_obj, 'connected'):
                logger.debug(f"🔍 Platform broker check for {broker_type.value}: broker has no 'connected' attribute")
                return False
            
            connected_status = broker_obj.connected
            logger.debug(f"🔍 Platform broker check for {broker_type.value}: broker={broker_obj.__class__.__name__}, connected={connected_status}")
            
            return connected_status
            
        except Exception:
            # Use logger.exception() to automatically include traceback
            # Safe fallback for broker name in case broker_type is malformed
            try:
                broker_name = broker_type.value
            except (AttributeError, TypeError):
                broker_name = str(broker_type) if broker_type else "Unknown"
            
            logger.exception(f"❌ Error checking platform broker connection for {broker_name}: This is unexpected - please report this error")
            return False

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

    def _get_cached_balance(self, account_type: str, account_id: str, broker_type: BrokerType, broker: BaseBroker) -> float:
        """
        Get balance with caching for Kraken to prevent repeated API calls.

        CRITICAL FIX (Jan 19, 2026): Railway Golden Rule #3 - Kraken sequential API calls
        Problem: Users not appearing funded because balance calls are sequential (1-1.2s delay each)
        Solution: Cache balances per trading cycle, add 1-1.2s delay between calls

        Args:
            account_type: 'platform' or 'user'
            account_id: Account identifier (e.g., 'platform', 'tania_gilbert')
            broker_type: Type of broker
            broker: Broker instance

        Returns:
            Balance in USD
        """
        cache_key = (account_type, account_id, broker_type)
        current_time = time.time()

        # Check if we have a valid cached balance
        if cache_key in self._balance_cache:
            cached_balance, cache_time = self._balance_cache[cache_key]
            age = current_time - cache_time

            if age < self.BALANCE_CACHE_TTL:
                logger.debug(f"Using cached balance for {account_type} {account_id} on {broker_type.value}: ${cached_balance:.2f} (age: {age:.1f}s)")
                return cached_balance

        # Need to fetch fresh balance from API
        # For Kraken, add delay between sequential calls to prevent rate limiting
        # NOTE: time.sleep() is intentional (Railway Golden Rule #3)
        # Kraken requires sequential API calls with delay to prevent nonce conflicts
        # This blocking operation is necessary for Railway deployment stability
        if broker_type == BrokerType.KRAKEN:
            time_since_last_call = current_time - self._last_kraken_balance_call
            if time_since_last_call < self.KRAKEN_BALANCE_CALL_DELAY:
                delay = self.KRAKEN_BALANCE_CALL_DELAY - time_since_last_call
                logger.debug(f"Kraken rate limit: waiting {delay:.2f}s before balance call")
                time.sleep(delay)  # Intentional blocking for Kraken rate limiting

            self._last_kraken_balance_call = time.time()

        # Fetch balance from broker API
        balance = broker.get_account_balance()

        # Cache the result
        self._balance_cache[cache_key] = (balance, time.time())
        logger.debug(f"Cached fresh balance for {account_type} {account_id} on {broker_type.value}: ${balance:.2f}")

        return balance

    def clear_balance_cache(self):
        """
        Clear the balance cache.

        Call this at the start of each trading cycle to force fresh balance fetches.
        This ensures balances are updated once per cycle but not more frequently.
        """
        self._balance_cache.clear()
        logger.debug("Balance cache cleared for new trading cycle")

    def get_platform_balance(self, broker_type: Optional[BrokerType] = None) -> float:
        """
        Get platform account balance.

        Args:
            broker_type: Specific broker or None for total across all brokers

        Returns:
            Balance in USD
        """
        if broker_type:
            broker = self._platform_brokers.get(broker_type)
            if not broker:
                return 0.0

            # CRITICAL FIX (Jan 19, 2026): Use cached balance for Kraken to prevent repeated API calls
            if broker_type == BrokerType.KRAKEN:
                return self._get_cached_balance('platform', 'platform', broker_type, broker)

            return broker.get_account_balance()

        # Total across all master brokers
        total = 0.0
        for broker_type, broker in self._platform_brokers.items():
            if broker.connected:
                if broker_type == BrokerType.KRAKEN:
                    total += self._get_cached_balance('platform', 'platform', broker_type, broker)
                else:
                    total += broker.get_account_balance()
        return total

    def get_user_balance(self, user_id: str, broker_type: Optional[BrokerType] = None) -> float:
        """
        Get user account balance with isolation guarantee.
        
        ISOLATION GUARANTEE: Balance fetch failures for one account will NOT affect other accounts.

        Args:
            user_id: User identifier
            broker_type: Specific broker or None for total across all brokers

        Returns:
            Balance in USD
        """
        user_brokers = self.user_brokers.get(user_id, {})

        if broker_type:
            broker = user_brokers.get(broker_type)
            if not broker:
                return 0.0

            # Check isolation manager before fetching balance
            if self.isolation_manager:
                can_execute, reason = self.isolation_manager.can_execute_operation(
                    'user', user_id, broker_type.value
                )
                if not can_execute:
                    logger.debug(f"Cannot fetch balance for {user_id}/{broker_type.value}: {reason}")
                    return 0.0

            try:
                # CRITICAL FIX (Jan 19, 2026): Use cached balance for Kraken to prevent repeated API calls
                if broker_type == BrokerType.KRAKEN:
                    balance = self._get_cached_balance('user', user_id, broker_type, broker)
                else:
                    balance = broker.get_account_balance()
                
                # Record success with isolation manager
                if self.isolation_manager:
                    self.isolation_manager.record_success('user', user_id, broker_type.value)
                
                return balance
                
            except Exception as e:
                logger.error(f"❌ Error fetching balance for {user_id}/{broker_type.value}: {e}")
                logger.error(f"   ISOLATION: This failure is contained to {user_id} only")
                
                # Record failure with isolation manager
                if self.isolation_manager and FailureType:
                    self.isolation_manager.record_failure(
                        'user', user_id, broker_type.value,
                        e,
                        FailureType.BALANCE_ERROR
                    )
                
                return 0.0

        # Total across all user brokers (isolation applied per broker)
        total = 0.0
        for broker_type, broker in user_brokers.items():
            if broker.connected:
                # Check isolation for this specific broker
                can_execute = True
                if self.isolation_manager:
                    can_execute, _ = self.isolation_manager.can_execute_operation(
                        'user', user_id, broker_type.value
                    )
                
                if can_execute:
                    try:
                        if broker_type == BrokerType.KRAKEN:
                            total += self._get_cached_balance('user', user_id, broker_type, broker)
                        else:
                            total += broker.get_account_balance()
                        
                        # Record success
                        if self.isolation_manager:
                            self.isolation_manager.record_success('user', user_id, broker_type.value)
                            
                    except Exception as e:
                        # Log error but continue with other brokers (isolation guarantee)
                        logger.error(f"❌ Error fetching balance for {user_id}/{broker_type.value}: {e}")
                        logger.error(f"   ISOLATION: Continuing with other brokers")
                        
                        if self.isolation_manager and FailureType:
                            self.isolation_manager.record_failure(
                                'user', user_id, broker_type.value,
                                e,
                                FailureType.BALANCE_ERROR
                            )
                        
                        # Continue to next broker - don't let one failure stop others
                        continue
        
        return total

    def update_user_portfolio(self, user_id: str, broker_type: BrokerType) -> Optional[any]:
        """
        Update portfolio state for a user account.

        FIX #3: Maintains user-specific portfolio state with total equity tracking.

        Args:
            user_id: User identifier
            broker_type: Broker type

        Returns:
            UserPortfolioState or None if not available
        """
        if not self.portfolio_manager:
            return None

        # Get user's broker
        broker = self.get_user_broker(user_id, broker_type)
        if not broker or not broker.connected:
            return None

        try:
            # Get current balance and positions
            balance = broker.get_account_balance()
            positions = broker.get_positions() if hasattr(broker, 'get_positions') else []

            # Get or create user portfolio state
            portfolio_key = (user_id, broker_type.value)
            if portfolio_key not in self.user_portfolios:
                # Initialize new user portfolio
                user_portfolio = self.portfolio_manager.initialize_user_portfolio(
                    user_id=user_id,
                    broker_type=broker_type.value,
                    available_cash=balance
                )
                self.user_portfolios[portfolio_key] = user_portfolio
            else:
                user_portfolio = self.user_portfolios[portfolio_key]

            # Update portfolio from broker data
            self.portfolio_manager.update_portfolio_from_broker(
                portfolio=user_portfolio,
                available_cash=balance,
                positions=positions
            )

            logger.debug(
                f"Updated portfolio for {user_id} ({broker_type.value}): "
                f"equity=${user_portfolio.total_equity:.2f}, positions={user_portfolio.position_count}"
            )

            return user_portfolio

        except Exception as e:
            logger.warning(f"Failed to update portfolio for {user_id} ({broker_type.value}): {e}")
            return None

    def get_user_portfolio(self, user_id: str, broker_type: BrokerType) -> Optional[any]:
        """
        Get portfolio state for a user.

        Args:
            user_id: User identifier
            broker_type: Broker type

        Returns:
            UserPortfolioState or None if not found
        """
        portfolio_key = (user_id, broker_type.value)
        return self.user_portfolios.get(portfolio_key)

    def get_all_balances(self) -> Dict:
        """
        Get balances for all accounts.

        CRITICAL FIX (Jan 23, 2026): Include ALL configured users and their brokers,
        even if credentials are not configured or connection failed.
        This ensures maximum visibility - users can see all accounts that are supposed to exist.

        Returns:
            dict with structure: {
                'platform': {broker_type: balance, ...},
                'users': {user_id: {broker_type: balance, ...}, ...}
            }
        """
        result = {
            'platform': {},
            'users': {}
        }

        # Platform balances
        for broker_type, broker in self._platform_brokers.items():
            if broker.connected:
                result['platform'][broker_type.value] = broker.get_account_balance()

        # User balances - include ALL users from metadata with ALL their brokers
        # CRITICAL FIX: Use metadata as source of truth for which users/brokers should exist
        for user_id, metadata in self._user_metadata.items():
            if user_id not in result['users']:
                result['users'][user_id] = {}

            # Add all brokers from metadata for this user
            for broker_type in metadata.get('brokers', {}).keys():
                broker_name = broker_type.value
                # Initialize with $0.00 - will be updated if we can get actual balance
                result['users'][user_id][broker_name] = 0.0

        # Then update with actual balances for connected users
        for user_id, user_brokers in self.user_brokers.items():
            if user_id not in result['users']:
                result['users'][user_id] = {}
            for broker_type, broker in user_brokers.items():
                if broker.connected:
                    try:
                        result['users'][user_id][broker_type.value] = broker.get_account_balance()
                    except Exception as e:
                        logger.debug(f"Could not get balance for {user_id}/{broker_type.value}: {e}")
                        # Keep the $0.00 default

        # Also try to get balances from _all_user_brokers (in case some are connected but not in user_brokers)
        for (user_id, broker_type), broker in self._all_user_brokers.items():
            if user_id not in result['users']:
                result['users'][user_id] = {}

            # Only update if broker is not already in results (avoid overwriting connected broker balances)
            # CRITICAL: Check if broker_type exists in result, not if balance is 0.0
            # This prevents overwriting legitimate $0.00 balances from connected brokers
            if broker_type.value not in result['users'][user_id]:
                try:
                    if broker.connected:
                        result['users'][user_id][broker_type.value] = broker.get_account_balance()
                    # If not connected, keep $0.00 (already set above or default)
                except Exception as e:
                    logger.debug(f"Could not get balance for {user_id}/{broker_type.value}: {e}")
                    # Keep the $0.00 default

        return result

    def _get_broker_credentials_status(self, broker: BaseBroker) -> bool:
        """
        Helper to safely check if broker has credentials configured.

        Args:
            broker: Broker instance to check

        Returns:
            True if credentials are configured, False otherwise
        """
        return getattr(broker, 'credentials_configured', False)

    def get_all_balances_with_status(self) -> Dict:
        """
        Get balances for all accounts with connection and credential status.

        CRITICAL FIX (Jan 23, 2026): Provide detailed status for all users to improve visibility.
        This helps users understand why they can't see their account balances.

        Returns:
            dict with structure: {
                'platform': {broker_type: {'balance': float, 'connected': bool}, ...},
                'users': {
                    user_id: {
                        broker_type: {
                            'balance': float,
                            'connected': bool,
                            'credentials_configured': bool
                        },
                        ...
                    },
                    ...
                }
            }
        """
        result = {
            'platform': {},
            'users': {}
        }

        # Platform balances with status
        for broker_type, broker in self._platform_brokers.items():
            result['platform'][broker_type.value] = {
                'balance': broker.get_account_balance() if broker.connected else 0.0,
                'connected': broker.connected
            }

        # User balances with status - include ALL users
        # First from metadata
        for user_id in self._user_metadata.keys():
            if user_id not in result['users']:
                result['users'][user_id] = {}

        # Then from connected users
        for user_id, user_brokers in self.user_brokers.items():
            if user_id not in result['users']:
                result['users'][user_id] = {}
            for broker_type, broker in user_brokers.items():
                result['users'][user_id][broker_type.value] = {
                    'balance': broker.get_account_balance() if broker.connected else 0.0,
                    'connected': broker.connected,
                    'credentials_configured': self._get_broker_credentials_status(broker)
                }

        # Finally from _all_user_brokers (disconnected users)
        for (user_id, broker_type), broker in self._all_user_brokers.items():
            if user_id not in result['users']:
                result['users'][user_id] = {}

            if broker_type.value not in result['users'][user_id]:
                result['users'][user_id][broker_type.value] = {
                    'balance': 0.0,  # Disconnected, so balance is 0 or unknown
                    'connected': broker.connected,
                    'credentials_configured': self._get_broker_credentials_status(broker)
                }

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

        # Platform account
        lines.append("\n🔷 PLATFORM ACCOUNT (Nija System)")
        lines.append("-" * 70)
        if self._platform_brokers:
            platform_total = 0.0
            for broker_type, broker in self._platform_brokers.items():
                if broker.connected:
                    balance = broker.get_account_balance()
                    platform_total += balance
                    lines.append(f"   {broker_type.value.upper()}: ${balance:,.2f}")
                else:
                    lines.append(f"   {broker_type.value.upper()}: Not connected")
            lines.append(f"   TOTAL PLATFORM: ${platform_total:,.2f}")
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

    def log_all_balances(self):
        """
        Log all account balances to the console.

        This is a convenience method for quick balance visibility.
        Calls get_status_report() and logs the output.
        """
        report = self.get_status_report()
        logger.info("\n" + report)

    def get_user_balance_summary(self) -> Dict:
        """
        Get a summary of all user balances for quick review.

        Returns:
            dict with structure: {
                'user_count': int,
                'total_capital': float,
                'average_balance': float,
                'users': [
                    {
                        'user_id': str,
                        'total': float,
                        'brokers': {broker: balance, ...}
                    },
                    ...
                ]
            }
        """
        balances = self.get_all_balances()
        user_balances = balances.get('users', {})

        users_list = []
        total_capital = 0.0

        for user_id, brokers in user_balances.items():
            user_total = sum(brokers.values())
            users_list.append({
                'user_id': user_id,
                'total': user_total,
                'brokers': brokers
            })
            total_capital += user_total

        # Sort by total balance (descending)
        users_list.sort(key=lambda x: x['total'], reverse=True)

        return {
            'user_count': len(users_list),
            'total_capital': total_capital,
            'average_balance': total_capital / len(users_list) if users_list else 0,
            'users': users_list
        }

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
        logger.info("ℹ️  Users are SECONDARY accounts - Platform accounts have priority")
        logger.info("=" * 70)

        connected_users = {}

        # Track last connection time for each broker type to add delays between sequential connections
        # This prevents nonce conflicts and server-side rate limiting issues, especially for Kraken
        last_connection_time = {}

        for user in enabled_users:
            # Store user config for later access (e.g., checking independent_trading flag)
            self.user_configs[user.user_id] = user

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

            # LEGACY CHECK: Skip if copy trading is active (deprecated feature)
            # NOTE: Copy trading is deprecated. This check is kept for backward compatibility.
            # In normal operation (independent trading), this will always be False and users connect normally.
            if broker_type == BrokerType.KRAKEN and self.kraken_copy_trading_active:
                logger.info("=" * 70)
                logger.info(f"✅ KRAKEN USER ALREADY ACTIVE VIA COPY TRADING: {user.name} ({user.user_id})")
                logger.info("=" * 70)
                continue
            # Check if Platform account is connected for this broker type
            # IMPORTANT: Platform accounts should connect first and be primary
            # User accounts are SECONDARY and should not connect if Platform isn't connected
            logger.debug(f"🔍 Checking platform connection for {broker_type.value}")
            logger.debug(f"   platform_brokers dict keys: {list(self.platform_brokers.keys())}")
            logger.debug(f"   {broker_type} in platform_brokers: {broker_type in self.platform_brokers}")
            platform_connected = self.is_platform_connected(broker_type)
            logger.debug(f"   is_platform_connected result: {platform_connected}")

            if not platform_connected:
                # CRITICAL FIX (Jan 17, 2026): ENFORCE connection order for Kraken copy trading
                # For Kraken, user accounts MUST NOT connect without master (prevents nonce conflicts & broken copy trading)
                # For other brokers, allow connection with warning (user may want standalone trading)
                logger.warning(f"⚠️  WARNING: User account connecting to {broker_type.value.upper()} WITHOUT Platform account!")
                logger.warning(f"   User: {user.name} ({user.user_id})")
                logger.warning(f"   Platform {broker_type.value.upper()} account is NOT connected")
                logger.warning("   🔧 RECOMMENDATION: Configure Platform account credentials first")
                logger.warning(f"      Platform should be PRIMARY, users should be SECONDARY")
                logger.warning("=" * 70)
                # Allow connection to proceed for non-Kraken brokers - user may want standalone trading
                # But log the warning so they know this is not the ideal setup

            # Add delay between sequential connections to the same broker type
            # This helps prevent nonce conflicts and API rate limiting, especially for Kraken
            if broker_type in last_connection_time:
                time_since_last = time.time() - last_connection_time[broker_type]
                if time_since_last < MIN_CONNECTION_DELAY:
                    delay = MIN_CONNECTION_DELAY - time_since_last
                    logger.info(f"⏱️  Waiting {delay:.1f}s before connecting next user to {broker_type.value.title()}...")
                    time.sleep(delay)

            logger.info(f"📊 Connecting {user.name} ({user.user_id}) to {broker_type.value.title()}...")
            if platform_connected:
                logger.info(f"   ✅ Platform {broker_type.value.upper()} is connected (correct priority)")
            else:
                logger.info(f"   ⚠️  Platform {broker_type.value.upper()} is NOT connected (user will be primary)")
            # Flush to ensure this message appears before connection attempt logs
            # CRITICAL FIX: Must flush the root 'nija' logger's handlers, not the child logger's
            # Child loggers (like 'nija.multi_account', 'nija.broker') propagate to parent but
            # don't have their own handlers. Flushing logger.handlers does nothing since it's empty.
            # We need to flush the parent 'nija' logger's handlers to ensure all logs are written.
            for handler in _root_logger.handlers:
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

                # Store/update user metadata for audit and reporting
                # Always update to ensure we have the latest user state
                if user.user_id not in self._user_metadata:
                    self._user_metadata[user.user_id] = {'brokers': {}}

                # Update user properties (may change between calls)
                self._user_metadata[user.user_id]['name'] = user.name
                self._user_metadata[user.user_id]['enabled'] = user.enabled

                if broker and broker.connected:
                    # Successfully connected
                    # Track connected user and broker connection status
                    if broker_type.value not in connected_users:
                        connected_users[broker_type.value] = []
                    connected_users[broker_type.value].append(user.user_id)

                    # Update metadata with connection status
                    self._user_metadata[user.user_id]['brokers'][broker_type] = True

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
                    # Update metadata with disconnected status
                    self._user_metadata[user.user_id]['brokers'][broker_type] = False
                    logger.info(f"   ⚪ {user.name} - credentials not configured (optional)")
                elif broker:
                    # Actual connection failure with configured credentials
                    logger.warning(f"   ⚠️  Failed to connect {user.name} to {broker_type.value.title()}")
                    # Track the failed connection to avoid repeated attempts
                    self._failed_user_connections[connection_key] = "connection_failed"
                    # Update metadata with disconnected status
                    self._user_metadata[user.user_id]['brokers'][broker_type] = False
                else:
                    # broker is None - unsupported broker type or exception
                    logger.warning(f"   ⚠️  Could not create broker for {user.name}")
                    self._failed_user_connections[connection_key] = "broker_creation_failed"
                    # Update metadata with disconnected status
                    self._user_metadata[user.user_id]['brokers'][broker_type] = False

            except Exception as e:
                # Initialize metadata if not already present (needed for exception case)
                if user.user_id not in self._user_metadata:
                    self._user_metadata[user.user_id] = {
                        'name': user.name,
                        'enabled': user.enabled,
                        'brokers': {}
                    }
                # Update metadata with disconnected status
                self._user_metadata[user.user_id]['brokers'][broker_type] = False

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
        logger.info("📊 ACCOUNT HIERARCHY REPORT")
        logger.info("=" * 70)
        logger.info("🎯 PLATFORM accounts are PRIMARY - User accounts are SECONDARY")
        logger.info("=" * 70)

        # Show Platform broker status
        logger.info("🔷 PLATFORM ACCOUNTS (Primary Trading Accounts):")
        if self._platform_brokers:
            for broker_type, broker in self._platform_brokers.items():
                status = "✅ CONNECTED" if broker.connected else "❌ NOT CONNECTED"
                logger.info(f"   • {broker_type.value.upper()}: {status}")
        else:
            logger.info("   ⚠️  No platform brokers connected")

        logger.info("")
        logger.info("👤 USER ACCOUNTS (Secondary Trading Accounts):")

        if connected_users:
            total_connected = sum(len(users) for users in connected_users.values())
            logger.info(f"   ✅ {total_connected} user(s) connected across {len(connected_users)} brokerage(s)")
            for brokerage, user_ids in connected_users.items():
                logger.info(f"   • {brokerage.upper()}: {len(user_ids)} user(s)")
        else:
            # Check if there are users without credentials vs actual failures
            total_without_creds = len(self._users_without_credentials)
            total_failed = len(self._failed_user_connections)

            if total_without_creds > 0 and total_failed == 0:
                # Only users without credentials - this is informational
                logger.info(f"   ⚪ No users connected ({total_without_creds} user(s) have no credentials configured)")
                logger.info("   User accounts are optional. To enable, configure API credentials in environment variables.")
            elif total_failed > 0:
                # Some actual connection failures
                logger.warning(f"   ⚠️  No users connected ({total_failed} connection failure(s), {total_without_creds} without credentials)")
            else:
                # No users configured at all
                logger.info("   ⚪ No user accounts configured")

        # Log warnings for problematic setups
        logger.info("")

        # Account architecture validation
        # All accounts (Platform + Users) trade independently using same NIJA logic
        # Platform is not a "master" - it's just another independent trading account
        users_without_platform = []
        for brokerage, user_ids in connected_users.items():
            try:
                # Safely convert brokerage string to BrokerType enum
                # connected_users keys are lowercase broker names from broker_type.value
                broker_type = BrokerType[brokerage.upper()]
                platform_connected = self.is_platform_connected(broker_type)
                if not platform_connected and user_ids:
                    users_without_platform.append(brokerage.upper())
            except KeyError:
                # Invalid broker type - this shouldn't happen, but handle gracefully
                logger.warning(f"⚠️  Unknown broker type in connected users: {brokerage}")
                continue

        if users_without_platform:
            # Platform account missing - recommend configuring it for stability
            # Platform trades independently (not as master), but its presence stabilizes system
            try:
                logger.info("ℹ️  ACCOUNT CONFIGURATION:")
                logger.info(f"   ℹ️  Platform account not connected on: {', '.join(users_without_platform)}")
                logger.info("   💡 RECOMMENDATION: Configure Platform account for optimal operation")
                logger.info("")
                logger.info("   Platform account provides:")
                logger.info("   • Stable system initialization")
                logger.info("   • Additional trading capacity (Platform trades independently)")
                logger.info("   • Cleaner logs and startup flow")
                logger.info("")
                # Flush output to ensure recommendations are visible
                for handler in _root_logger.handlers:
                    handler.flush()
                
                logger.info("   📋 TO CONFIGURE PLATFORM ACCOUNT:")
                for broker in users_without_platform:
                    logger.info(f"")
                    logger.info(f"   For {broker} Platform account:")
                    logger.info(f"   1. Get API credentials from the {broker} website")
                    if broker == "KRAKEN":
                        logger.info(f"      URL: https://www.kraken.com/u/security/api")
                        logger.info(f"   2. Set these environment variables:")
                        logger.info(f"      KRAKEN_PLATFORM_API_KEY=<your-api-key>")
                        logger.info(f"      KRAKEN_PLATFORM_API_SECRET=<your-api-secret>")
                    elif broker == "ALPACA":
                        logger.info(f"      URL: https://alpaca.markets/")
                        logger.info(f"   2. Set these environment variables:")
                        logger.info(f"      ALPACA_API_KEY=<your-api-key>")
                        logger.info(f"      ALPACA_API_SECRET=<your-api-secret>")
                        logger.info(f"      ALPACA_PAPER=true  # Set to false for live trading")
                    else:
                        logger.info(f"   2. Set environment variables:")
                        logger.info(f"      {broker}_PLATFORM_API_KEY=<your-api-key>")
                        logger.info(f"      {broker}_PLATFORM_API_SECRET=<your-api-secret>")
                    logger.info(f"   3. Restart the bot")
                    # Flush after each broker to ensure output is visible
                    for handler in _root_logger.handlers:
                        handler.flush()
                
                logger.info("")
                logger.info("   Note: Platform and Users all trade independently using same NIJA logic")
                logger.info("=" * 70)
                # Final flush to ensure all configuration messages are visible
                for handler in _root_logger.handlers:
                    handler.flush()
            except Exception as e:
                logger.error(f"⚠️  Error logging account configuration: {e}")
                logger.debug(traceback.format_exc())
        else:
            # All accounts connected and trading
            logger.info("✅ ACCOUNT STATUS:")
            logger.info("   ✅ Platform and User accounts connected - all trading independently")

        logger.info("=" * 70)
        # Flush final separator
        for handler in _root_logger.handlers:
            handler.flush()

        return connected_users

    def audit_user_accounts(self):
        """
        Audit and log all user accounts with broker status.

        This function displays:
        - PLATFORM-linked users
        - Any account with status=="ACTIVE" (enabled=True)
        - Shows connection status for each broker

        Output format is clean and investor-ready.
        Called at startup to ensure all active users are visible.
        """
        logger.info("=" * 70)
        logger.info("👥 USER ACCOUNT BALANCES AUDIT")
        logger.info("=" * 70)

        if not self._user_metadata:
            logger.info("   ⚪ No user accounts configured")
            logger.info("=" * 70)
            return

        # Collect all active users (enabled=True) with their broker statuses
        active_connected_count = 0

        for user_id, user_meta in self._user_metadata.items():
            user_name = user_meta.get('name', user_id)
            is_enabled = user_meta.get('enabled', True)
            brokers_status = user_meta.get('brokers', {})

            # Skip disabled users
            if not is_enabled:
                continue

            # Get actual broker connections from user_brokers
            user_broker_dict = self.user_brokers.get(user_id, {})

            # Track if this user has at least one active connection
            user_has_connection = False

            # Display all configured brokers for this user
            for broker_type, is_connected in brokers_status.items():
                broker_name = broker_type.value.upper()

                # Verify connection status from actual broker object
                if broker_type in user_broker_dict:
                    broker = user_broker_dict[broker_type]
                    if broker.connected:
                        logger.info(f"✅ {user_name} ({broker_name}): CONNECTED")
                        user_has_connection = True
                    else:
                        logger.info(f"⚪ {user_name} ({broker_name}): Not configured")
                else:
                    logger.info(f"⚪ {user_name} ({broker_name}): Not configured")

            # Count users with at least one connection
            if user_has_connection:
                active_connected_count += 1

        # Display summary
        if active_connected_count == 0:
            logger.info("")
            logger.info("   ⚪ No ACTIVE user accounts with broker connections")
        else:
            logger.info("")
            logger.info(f"✅ {active_connected_count} active user account(s) connected")

        logger.info("=" * 70)


# Global instance
multi_account_broker_manager = MultiAccountBrokerManager()
