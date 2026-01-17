"""
NIJA Kraken Copy Trading Engine
================================

Implements MASTER → USERS copy trading for Kraken accounts.

Architecture:
    Kraken MASTER
     ├─ Strategy decides trade
     ├─ MASTER places real order
     ├─ Emits trade signal
     └─ Copy Engine
          ├─ Loops Kraken USERS
          ├─ Scales position size
          └─ Places SAME order on each user account

Features:
    ✅ Trades appear in MASTER Kraken UI
    ✅ Trades appear in EVERY USER Kraken UI
    ✅ Safe nonce + isolation per account
    ✅ Position size scaling based on balance ratio
    ✅ Per-user risk limits (10% max)
    ✅ Global kill switch
    
Integration:
    Call initialize_copy_trading_system() at bot startup.
    The system will automatically intercept Kraken MASTER trades
    and copy them to all configured user accounts.
"""

import logging
import threading
import time
import os
from typing import Dict, List, Optional, Any
import json
from pathlib import Path

# Import broker classes
try:
    from bot.broker_manager import KrakenBroker, AccountType, BrokerType
except ImportError:
    from broker_manager import KrakenBroker, AccountType, BrokerType

logger = logging.getLogger('nija.kraken_copy')

# Safety Configuration
MAX_USER_RISK = 0.10  # 10% max per trade per user
SYSTEM_DISABLED = False  # Global kill switch

# Nonce Store Implementation
class NonceStore:
    """
    Thread-safe nonce storage with file persistence.
    Each account (master + each user) has its own nonce file.
    """
    
    def __init__(self, account_identifier: str):
        """
        Initialize nonce store for a specific account.
        
        Args:
            account_identifier: Unique identifier (e.g., 'master', 'user_daivon')
        """
        self.account_identifier = account_identifier
        self.lock = threading.RLock()  # Use RLock for reentrant locking
        
        # Create nonce file path in bot directory
        bot_dir = Path(__file__).parent
        self.nonce_file = bot_dir / f"kraken_nonce_{account_identifier}.txt"
        
        # Initialize with current time if file doesn't exist
        if not self.nonce_file.exists():
            initial_nonce = int(time.time() * 1000000)
            self.set(initial_nonce)
    
    def get(self) -> int:
        """
        Get the last nonce from file.
        
        Returns:
            Last nonce value (microseconds since epoch)
        """
        with self.lock:
            try:
                if self.nonce_file.exists():
                    with open(self.nonce_file, 'r') as f:
                        content = f.read().strip()
                        if content:
                            return int(content)
            except (ValueError, IOError) as e:
                logger.debug(f"Could not read nonce for {self.account_identifier}: {e}")
            
            # Return 0 if file doesn't exist or is invalid
            return 0
    
    def set(self, nonce: int):
        """
        Set the nonce value to file.
        
        Args:
            nonce: New nonce value to persist
        """
        with self.lock:
            try:
                with open(self.nonce_file, 'w') as f:
                    f.write(str(nonce))
            except IOError as e:
                logger.debug(f"Could not write nonce for {self.account_identifier}: {e}")
    
    def increment_and_get(self) -> int:
        """
        Atomically increment and return the next nonce.
        
        Returns:
            Next nonce value (guaranteed to be monotonically increasing)
        """
        with self.lock:
            last_nonce = self.get()
            now = int(time.time() * 1000000)
            next_nonce = max(now, last_nonce + 1)
            self.set(next_nonce)
            return next_nonce


# Kraken Client Wrapper
class KrakenClient:
    """
    Thread-safe Kraken client with isolated nonce management.
    Each account MUST have its own client instance.
    """
    
    def __init__(self, api_key: str, api_secret: str, nonce_store: NonceStore, 
                 account_identifier: str = "unknown"):
        """
        Initialize Kraken client with dedicated nonce store.
        
        Args:
            api_key: Kraken API key
            api_secret: Kraken API secret
            nonce_store: NonceStore instance for this account
            account_identifier: Human-readable identifier for logging
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.nonce_store = nonce_store
        self.account_identifier = account_identifier
        self.lock = threading.RLock()  # Use RLock for reentrant locking
        
        # Initialize Kraken broker instance
        # Note: We're wrapping the existing KrakenBroker for consistency
        self.broker = None
    
    def _nonce(self) -> int:
        """
        Generate next nonce with thread-safe monotonic increment.
        
        Returns:
            Next nonce value
        """
        with self.lock:
            last = self.nonce_store.get()
            now = int(time.time() * 1000000)
            nonce = max(now, last + 1)
            self.nonce_store.set(nonce)
            return nonce
    
    def place_order(self, pair: str, side: str, volume: float, 
                    ordertype: str = "market") -> Dict[str, Any]:
        """
        Place order on Kraken with thread-safe nonce handling.
        
        Args:
            pair: Trading pair (e.g., 'XXBTZUSD', 'XETHZUSD')
            side: 'buy' or 'sell'
            volume: Order size (in base currency for market orders)
            ordertype: Order type ('market' or 'limit')
        
        Returns:
            API response dict with 'result' or 'error'
        """
        with self.lock:
            try:
                import krakenex
                
                # Initialize API connection if not already done
                if not hasattr(self, 'api'):
                    self.api = krakenex.API()
                    self.api.key = self.api_key
                    self.api.secret = self.api_secret
                
                # Generate nonce
                nonce = self._nonce()
                
                # Place order
                return self.api.query_private(
                    "AddOrder",
                    {
                        "nonce": nonce,
                        "pair": pair,
                        "type": side,
                        "ordertype": ordertype,
                        "volume": str(volume)
                    }
                )
            except Exception as e:
                logger.error(f"❌ Order failed for {self.account_identifier}: {e}")
                return {"error": [str(e)]}
    
    def get_balance(self) -> Dict[str, Any]:
        """
        Get account balance.
        
        Returns:
            API response dict with 'result' containing balances
        """
        with self.lock:
            try:
                import krakenex
                
                # Initialize API connection if not already done
                if not hasattr(self, 'api'):
                    self.api = krakenex.API()
                    self.api.key = self.api_key
                    self.api.secret = self.api_secret
                
                # Generate nonce
                nonce = self._nonce()
                
                # Get balance
                return self.api.query_private("Balance", {"nonce": nonce})
            except Exception as e:
                logger.error(f"❌ Balance check failed for {self.account_identifier}: {e}")
                return {"error": [str(e)]}


# Global Kraken Client Instances
KRAKEN_MASTER: Optional[KrakenClient] = None
KRAKEN_USERS: List[Dict[str, Any]] = []


def initialize_kraken_master() -> bool:
    """
    Initialize KRAKEN_MASTER client from environment variables.
    
    Returns:
        True if successful, False otherwise
    """
    global KRAKEN_MASTER
    
    try:
        # Get master credentials
        api_key = os.getenv("KRAKEN_MASTER_API_KEY", "")
        api_secret = os.getenv("KRAKEN_MASTER_API_SECRET", "")
        
        # Fallback to legacy credentials
        if not api_key:
            api_key = os.getenv("KRAKEN_API_KEY", "")
        if not api_secret:
            api_secret = os.getenv("KRAKEN_API_SECRET", "")
        
        if not api_key or not api_secret:
            logger.warning("⚠️  Kraken master credentials not configured")
            return False
        
        # Create nonce store for master
        master_nonce_store = NonceStore("master")
        
        # Create Kraken client
        KRAKEN_MASTER = KrakenClient(
            api_key=api_key,
            api_secret=api_secret,
            nonce_store=master_nonce_store,
            account_identifier="MASTER"
        )
        
        logger.info("✅ Kraken MASTER client initialized")
        return True
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize Kraken MASTER: {e}")
        return False


def initialize_kraken_users() -> int:
    """
    Initialize KRAKEN_USERS list from retail_kraken.json config.
    
    Returns:
        Number of users successfully initialized
    """
    global KRAKEN_USERS
    
    try:
        # Load user config
        config_path = Path(__file__).parent.parent / "config" / "users" / "retail_kraken.json"
        
        if not config_path.exists():
            logger.warning(f"⚠️  User config not found: {config_path}")
            return 0
        
        with open(config_path, 'r') as f:
            users_config = json.load(f)
        
        if not isinstance(users_config, list):
            logger.error("❌ Invalid user config format (expected list)")
            return 0
        
        # Initialize each user
        initialized_count = 0
        for user in users_config:
            user_id = user.get('user_id', '')
            name = user.get('name', 'Unknown')
            enabled = user.get('enabled', False)
            
            if not enabled:
                logger.info(f"⏭️  Skipping disabled user: {name} ({user_id})")
                continue
            
            # Get environment variable names
            if '_' in user_id:
                user_env_name = user_id.split('_')[0].upper()
            else:
                user_env_name = user_id.upper()
            
            key_var = f"KRAKEN_USER_{user_env_name}_API_KEY"
            secret_var = f"KRAKEN_USER_{user_env_name}_API_SECRET"
            
            api_key = os.getenv(key_var, "")
            api_secret = os.getenv(secret_var, "")
            
            if not api_key or not api_secret:
                logger.warning(f"⚠️  Credentials not configured for {name}: {key_var}, {secret_var}")
                continue
            
            # Create nonce store for user
            user_nonce_store = NonceStore(f"user_{user_id}")
            
            # Create Kraken client
            client = KrakenClient(
                api_key=api_key,
                api_secret=api_secret,
                nonce_store=user_nonce_store,
                account_identifier=f"USER:{user_id}"
            )
            
            # Get user balance
            balance_result = client.get_balance()
            if 'error' in balance_result and balance_result['error']:
                logger.error(f"❌ Failed to get balance for {name}: {balance_result['error']}")
                continue
            
            # Calculate USD balance
            balances = balance_result.get('result', {})
            usd_balance = float(balances.get('ZUSD', 0))
            usdt_balance = float(balances.get('USDT', 0))
            total_balance = usd_balance + usdt_balance
            
            # Add user to list
            KRAKEN_USERS.append({
                "id": user_id,
                "name": name,
                "client": client,
                "balance": total_balance
            })
            
            logger.info(f"✅ Initialized user: {name} ({user_id}) - Balance: ${total_balance:.2f}")
            initialized_count += 1
        
        logger.info(f"✅ Initialized {initialized_count} Kraken users for copy trading")
        return initialized_count
        
    except Exception as e:
        logger.error(f"❌ Failed to initialize Kraken users: {e}")
        return 0


def get_price(pair: str) -> float:
    """
    Get current price for a trading pair.
    
    Args:
        pair: Trading pair (e.g., 'XXBTZUSD')
    
    Returns:
        Current price or 0.0 if error
    """
    try:
        import krakenex
        from pykrakenapi import KrakenAPI
        
        # Use public API (no auth needed)
        api = krakenex.API()
        k = KrakenAPI(api)
        
        # Get ticker
        ticker = k.get_ticker_information(pair)
        
        # Get last price
        if not ticker.empty and 'c' in ticker.columns:
            # 'c' column contains [last_price, last_volume]
            last_price = float(ticker['c'].iloc[0][0])
            return last_price
        
        logger.warning(f"⚠️  Could not get price for {pair}")
        return 0.0
        
    except Exception as e:
        logger.error(f"❌ Error getting price for {pair}: {e}")
        return 0.0


def execute_master_trade(pair: str, side: str, usd_size: float) -> bool:
    """
    Execute trade on MASTER account and trigger copy trading to users.
    
    Args:
        pair: Kraken trading pair (e.g., 'XXBTZUSD')
        side: 'buy' or 'sell'
        usd_size: Order size in USD
    
    Returns:
        True if master trade successful, False otherwise
    """
    global KRAKEN_MASTER, KRAKEN_USERS
    
    # Check kill switch
    if SYSTEM_DISABLED:
        logger.warning("⚠️  SYSTEM DISABLED - No trades will be executed")
        return False
    
    # Validate MASTER initialized
    if not KRAKEN_MASTER:
        logger.error("❌ Kraken MASTER not initialized")
        return False
    
    try:
        # Get master balance
        balance_result = KRAKEN_MASTER.get_balance()
        if 'error' in balance_result and balance_result['error']:
            logger.error(f"❌ Failed to get MASTER balance: {balance_result['error']}")
            return False
        
        balances = balance_result.get('result', {})
        usd_balance = float(balances.get('ZUSD', 0))
        usdt_balance = float(balances.get('USDT', 0))
        master_balance = usd_balance + usdt_balance
        
        # Get current price
        price = get_price(pair)
        if price <= 0:
            logger.error(f"❌ Could not get price for {pair}")
            return False
        
        # Calculate volume (base currency)
        volume = usd_size / price
        
        # Place master order
        logger.info("=" * 70)
        logger.info(f"🟢 EXECUTING MASTER TRADE | {pair} | {side.upper()} | ${usd_size:.2f}")
        logger.info("=" * 70)
        
        result = KRAKEN_MASTER.place_order(
            pair=pair,
            side=side,
            volume=volume
        )
        
        # Check for errors
        if 'error' in result and result['error']:
            error_msgs = ', '.join(result['error'])
            logger.error(f"❌ MASTER TRADE FAILED: {error_msgs}")
            return False
        
        # Extract order ID
        order_result = result.get('result', {})
        txid = order_result.get('txid', [])
        order_id = txid[0] if txid else "unknown"
        
        logger.info(f"✅ MASTER KRAKEN TRADE EXECUTED")
        logger.info(f"   Pair: {pair}")
        logger.info(f"   Side: {side.upper()}")
        logger.info(f"   Order ID: {order_id}")
        logger.info(f"   Size: ${usd_size:.2f} ({volume:.8f} {pair.split('Z')[0]})")
        logger.info("=" * 70)
        
        # Create master trade object for copy engine
        master_trade = {
            "pair": pair,
            "side": side,
            "volume": volume,
            "usd_size": usd_size,
            "master_balance": master_balance,
            "price": price,
            "order_id": order_id
        }
        
        # Trigger copy trading to users
        copy_trade_to_kraken_users(master_trade)
        
        return True
        
    except Exception as e:
        logger.error(f"❌ MASTER trade execution failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def copy_trade_to_kraken_users(master_trade: Dict[str, Any]):
    """
    Copy a master trade to all Kraken user accounts.
    
    Args:
        master_trade: Dict containing trade details from master execution
    """
    global KRAKEN_USERS
    
    if not KRAKEN_USERS:
        logger.info("ℹ️  No Kraken users configured for copy trading")
        return
    
    logger.info("")
    logger.info("=" * 70)
    logger.info(f"🔄 COPY TRADING TO {len(KRAKEN_USERS)} USERS")
    logger.info("=" * 70)
    
    success_count = 0
    fail_count = 0
    
    for user in KRAKEN_USERS:
        try:
            user_id = user['id']
            user_name = user['name']
            user_balance = user['balance']
            client = user['client']
            
            # Calculate scaled position size based on balance ratio
            user_size = (
                master_trade["usd_size"] 
                * (user_balance / master_trade["master_balance"])
            )
            
            # Apply MAX_USER_RISK safety limit
            max_allowed_size = user_balance * MAX_USER_RISK
            if user_size > max_allowed_size:
                logger.warning(
                    f"⚠️  User {user_name}: Scaled size ${user_size:.2f} exceeds "
                    f"MAX_USER_RISK (10% = ${max_allowed_size:.2f}), capping to max"
                )
                user_size = max_allowed_size
            
            # Calculate user volume
            user_volume = user_size / master_trade["price"]
            
            # Place user order
            logger.info(f"   🔄 Copying to {user_name} ({user_id})...")
            logger.info(f"      Balance: ${user_balance:.2f}")
            logger.info(f"      Size: ${user_size:.2f} ({user_volume:.8f})")
            
            result = client.place_order(
                pair=master_trade["pair"],
                side=master_trade["side"],
                volume=user_volume
            )
            
            # Check for errors
            if 'error' in result and result['error']:
                error_msgs = ', '.join(result['error'])
                logger.error(f"      ❌ COPY FAILED: {error_msgs}")
                fail_count += 1
                continue
            
            # Extract order ID
            order_result = result.get('result', {})
            txid = order_result.get('txid', [])
            order_id = txid[0] if txid else "unknown"
            
            logger.info(f"      ✅ COPY SUCCESS | Order ID: {order_id}")
            success_count += 1
            
        except Exception as e:
            logger.error(f"      ❌ COPY FAIL | user={user.get('id', 'unknown')} | {e}")
            fail_count += 1
    
    logger.info("=" * 70)
    logger.info(f"📊 COPY TRADING SUMMARY")
    logger.info(f"   Success: {success_count}/{len(KRAKEN_USERS)}")
    logger.info(f"   Failed: {fail_count}/{len(KRAKEN_USERS)}")
    logger.info("=" * 70)
    logger.info("")


def initialize_copy_trading_system() -> bool:
    """
    Initialize the complete Kraken copy trading system.
    
    Returns:
        True if initialization successful, False otherwise
    """
    logger.info("")
    logger.info("=" * 70)
    logger.info("🚀 INITIALIZING KRAKEN COPY TRADING SYSTEM")
    logger.info("=" * 70)
    
    # Initialize master
    master_ok = initialize_kraken_master()
    if not master_ok:
        logger.error("❌ Failed to initialize Kraken MASTER - copy trading disabled")
        return False
    
    # Initialize users
    user_count = initialize_kraken_users()
    if user_count == 0:
        logger.warning("⚠️  No Kraken users initialized - trades will execute on MASTER only")
    
    logger.info("=" * 70)
    logger.info("✅ KRAKEN COPY TRADING SYSTEM READY")
    logger.info(f"   MASTER: Initialized")
    logger.info(f"   USERS: {user_count} ready for copy trading")
    logger.info("=" * 70)
    logger.info("")
    
    return True


def wrap_kraken_broker_for_copy_trading(kraken_broker):
    """
    Wrap a KrakenBroker instance to enable copy trading on all orders.
    
    This function monkey-patches the broker's place_market_order method
    to automatically trigger copy trading after master orders execute.
    
    Args:
        kraken_broker: KrakenBroker instance (must be MASTER account)
    
    Returns:
        The same broker instance (modified in-place)
    """
    # Only wrap MASTER accounts
    if not hasattr(kraken_broker, 'account_type'):
        logger.warning("⚠️  Cannot wrap broker - missing account_type attribute")
        return kraken_broker
    
    try:
        from bot.broker_manager import AccountType
    except ImportError:
        from broker_manager import AccountType
    
    if kraken_broker.account_type != AccountType.MASTER:
        logger.warning(f"⚠️  Not wrapping non-MASTER broker: {kraken_broker.account_identifier}")
        return kraken_broker
    
    # Store original method
    original_place_market_order = kraken_broker.place_market_order
    
    def place_market_order_with_copy(symbol: str, side: str, quantity: float) -> Dict:
        """
        Wrapped place_market_order that triggers copy trading.
        
        Args:
            symbol: Trading pair (e.g., 'BTC-USD' or 'XBTUSDT')
            side: 'buy' or 'sell'
            quantity: Order size (in USD for buys, base currency for sells)
        
        Returns:
            dict: Order result from master execution
        """
        # Execute on master first
        result = original_place_market_order(symbol, side, quantity)
        
        # Only copy if master order succeeded
        if result.get('status') == 'filled':
            # Convert symbol to Kraken format
            kraken_symbol = symbol.replace('-', '').upper()
            if kraken_symbol.startswith('BTC'):
                kraken_symbol = kraken_symbol.replace('BTC', 'XBT', 1)
            
            # Get master balance
            try:
                master_balance = kraken_broker.get_account_balance()
                
                # Get price from result or calculate from quantity
                price = result.get('filled_price', 0)
                if price <= 0:
                    # Fallback: get current price
                    price = get_price(kraken_symbol)
                
                if price > 0:
                    # Calculate USD size
                    if side == 'buy':
                        usd_size = quantity  # For buys, quantity is already in USD
                    else:
                        # For sells, quantity is in base currency
                        usd_size = quantity * price
                    
                    # Create master trade object
                    master_trade = {
                        "pair": kraken_symbol,
                        "side": side,
                        "volume": quantity,
                        "usd_size": usd_size,
                        "master_balance": master_balance,
                        "price": price,
                        "order_id": result.get('order_id', 'unknown')
                    }
                    
                    # Trigger copy trading
                    logger.info(f"🔄 Master order filled - triggering copy trading for {symbol}")
                    copy_trade_to_kraken_users(master_trade)
                else:
                    logger.warning(f"⚠️  Cannot copy trade - price unavailable for {symbol}")
                    
            except Exception as copy_err:
                logger.error(f"❌ Copy trading failed for {symbol}: {copy_err}")
                # Don't fail the master order if copy trading fails
        
        return result
    
    # Replace method
    kraken_broker.place_market_order = place_market_order_with_copy
    
    logger.info(f"✅ Kraken broker wrapped for copy trading: {kraken_broker.account_identifier}")
    return kraken_broker


# Export public API
__all__ = [
    'KrakenClient',
    'NonceStore',
    'initialize_copy_trading_system',
    'wrap_kraken_broker_for_copy_trading',
    'execute_master_trade',
    'copy_trade_to_kraken_users',
    'KRAKEN_MASTER',
    'KRAKEN_USERS',
    'MAX_USER_RISK',
    'SYSTEM_DISABLED'
]
