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

# Import global Kraken nonce manager (FINAL FIX)
try:
    from bot.global_kraken_nonce import get_global_kraken_nonce, get_kraken_api_lock
except ImportError:
    try:
        from global_kraken_nonce import get_global_kraken_nonce, get_kraken_api_lock
    except ImportError:
        get_global_kraken_nonce = None
        get_kraken_api_lock = None

# Try to import Kraken API libraries
# These may not be available in all environments (e.g., test environments)
try:
    import krakenex
    from pykrakenapi import KrakenAPI
    KRAKEN_API_AVAILABLE = True
except ImportError:
    KRAKEN_API_AVAILABLE = False

logger = logging.getLogger('nija.kraken_copy')

# Safety Configuration
MAX_USER_RISK = 0.10  # 10% max per trade per user
SYSTEM_DISABLED = False  # Global kill switch

# NonceStore has been REMOVED as per FIX #1 - Use GlobalKrakenNonceManager instead
# All nonce generation now uses get_global_kraken_nonce() from bot/global_kraken_nonce.py
# This ensures thread-safe, monotonic nonces shared across all accounts


# Kraken Client Wrapper
class KrakenClient:
    """
    Thread-safe Kraken client with GLOBAL nonce management.
    
    FINAL FIX: Uses ONE global nonce source shared across all users.
    No per-account nonce stores needed.
    """
    
    def __init__(self, api_key: str, api_secret: str, account_identifier: str = "unknown"):
        """
        Initialize Kraken client with global nonce manager.
        
        Args:
            api_key: Kraken API key
            api_secret: Kraken API secret
            account_identifier: Human-readable identifier for logging
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.account_identifier = account_identifier
        self.lock = threading.RLock()
        
        # Initialize Kraken broker instance
        self.broker = None
    
    def _ensure_api_initialized(self):
        """
        Helper method to ensure Kraken API is initialized with global nonce manager.
        
        This method is called before each API operation to ensure:
        1. The krakenex API object is created
        2. The api._nonce method is overridden to use global nonce manager
        3. Reduces code duplication across multiple API methods
        """
        if not hasattr(self, 'api') or self.api is None:
            import krakenex
            self.api = krakenex.API()
            self.api.key = self.api_key
            self.api.secret = self.api_secret
            
            # CRITICAL FIX: Override the nonce method to use global nonce manager
            # This ensures ALL Kraken API calls use the same nonce source
            if get_global_kraken_nonce is not None:
                def _global_nonce():
                    """Generate nonce using global manager (nanosecond precision)."""
                    return str(get_global_kraken_nonce())
                
                self.api._nonce = _global_nonce
                logger.debug(f"✅ Global nonce manager installed for {self.account_identifier}")
            else:
                logger.warning(f"⚠️ Global nonce manager not available for {self.account_identifier}")
    
    def _nonce(self) -> int:
        """
        Generate next nonce using GLOBAL Kraken Nonce Manager.
        
        FINAL FIX: ONE global source for all users (master + users).
        - Nanosecond precision (19 digits)
        - Thread-safe
        - No collisions possible
        - No file persistence needed
        
        Returns:
            Next nonce value (nanoseconds since epoch)
        """
        if get_global_kraken_nonce is not None:
            # Use global nonce manager (FINAL FIX)
            return get_global_kraken_nonce()
        else:
            # Fallback to time-based nonce
            logger.warning(f"⚠️ Global nonce manager not available for {self.account_identifier}, using fallback")
            with self.lock:
                # Use nanoseconds for compatibility
                return int(time.time() * 1000000000)
    
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
        try:
            # Initialize API with global nonce manager
            self._ensure_api_initialized()
            
            # Use global API lock to serialize all Kraken calls (Option B)
            # This ensures only ONE API call happens at a time across ALL users
            if get_kraken_api_lock is not None:
                api_lock = get_kraken_api_lock()
            else:
                api_lock = self.lock  # Fallback to instance lock
            
            with api_lock:
                # Place order - nonce is automatically generated by api._nonce
                return self.api.query_private(
                    "AddOrder",
                    {
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
        try:
            # Initialize API with global nonce manager
            self._ensure_api_initialized()
            
            # Use global API lock to serialize all Kraken calls (Option B)
            # This ensures only ONE API call happens at a time across ALL users
            if get_kraken_api_lock is not None:
                api_lock = get_kraken_api_lock()
            else:
                api_lock = self.lock  # Fallback to instance lock
            
            with api_lock:
                # Get balance - nonce is automatically generated by api._nonce
                return self.api.query_private("Balance")
        except Exception as e:
            logger.error(f"❌ Balance check failed for {self.account_identifier}: {e}")
            return {"error": [str(e)]}


# Global Kraken Client Instances
# Global state for Kraken copy trading system
# NOTE: Using global variables for connection state is a known limitation
# Future improvement: Consider using a connection manager or dependency injection pattern
# for better testability and maintainability. For now, this follows the existing
# pattern in the codebase and provides the minimal change needed.
KRAKEN_MASTER: Optional[KrakenClient] = None
KRAKEN_USERS: List[Dict[str, Any]] = []

# FIX PART 1: Hard guard flag to prevent duplicate user initialization
# When True, initialize_kraken_users() will skip re-initialization
_USERS_INITIALIZED: bool = False


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
        
        # Create Kraken client (no nonce_store parameter - uses GlobalKrakenNonceManager)
        KRAKEN_MASTER = KrakenClient(
            api_key=api_key,
            api_secret=api_secret,
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
    global KRAKEN_USERS, _USERS_INITIALIZED
    
    # FIX PART 2: Block re-entry - prevent duplicate initialization
    if _USERS_INITIALIZED:
        logger.info("ℹ️  Kraken users already initialized — skipping user init phase")
        return len(KRAKEN_USERS)
    
    logger.info("👤 Initializing Kraken users from config files...")
    
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
            # Convention: 'first_last' user_id becomes 'FIRST' in env var name
            # e.g., 'daivon_frazier' → KRAKEN_USER_DAIVON_API_KEY
            # e.g., 'tania_gilbert' → KRAKEN_USER_TANIA_API_KEY
            # For user_ids without underscore (e.g., 'john'), uses the full name (KRAKEN_USER_JOHN_API_KEY)
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
            
            # Create Kraken client (no nonce_store parameter - uses GlobalKrakenNonceManager)
            client = KrakenClient(
                api_key=api_key,
                api_secret=api_secret,
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
        
        # FIX PART 2: Mark users as initialized to prevent duplicate initialization
        _USERS_INITIALIZED = True
        logger.info(f"✅ Kraken user initialization COMPLETE — {initialized_count} users ready")
        return initialized_count
        
    except Exception as e:
        # Reset flag on failure to allow retry
        _USERS_INITIALIZED = False
        logger.error(f"❌ Failed to initialize Kraken users: {e}")
        return 0


def _convert_symbol_to_kraken_format(symbol: str) -> str:
    """
    Convert standard symbol format to Kraken format.
    
    Args:
        symbol: Standard symbol (e.g., 'BTC-USD', 'ETH-USD')
    
    Returns:
        Kraken format symbol (e.g., 'XXBTZUSD', 'XETHZUSD')
    """
    # Remove dashes and convert to uppercase
    kraken_symbol = symbol.replace('-', '').upper()
    
    # Kraken uses X prefix for BTC (XBTZUSD instead of BTCUSD)
    if kraken_symbol.startswith('BTC'):
        kraken_symbol = kraken_symbol.replace('BTC', 'XBT', 1)
    
    return kraken_symbol


def get_price(pair: str) -> float:
    """
    Get current price for a trading pair.
    
    Args:
        pair: Trading pair (e.g., 'XXBTZUSD')
    
    Returns:
        Current price or 0.0 if error
    """
    try:
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
    global KRAKEN_MASTER, KRAKEN_USERS
    
    # CRITICAL CHECK: Verify MASTER is still initialized and connected
    # This prevents copy trading if master has gone offline
    if not KRAKEN_MASTER:
        logger.warning("⚠️  KRAKEN MASTER offline - skipping copy trading")
        logger.info("   ℹ️  Copy trading disabled until MASTER reconnects")
        return
    
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
            # Convert symbol to Kraken format using shared utility
            kraken_symbol = _convert_symbol_to_kraken_format(symbol)
            
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
    'initialize_copy_trading_system',
    'wrap_kraken_broker_for_copy_trading',
    'execute_master_trade',
    'copy_trade_to_kraken_users',
    'KRAKEN_MASTER',
    'KRAKEN_USERS',
    'MAX_USER_RISK',
    'SYSTEM_DISABLED'
]
