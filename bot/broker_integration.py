"""
NIJA Apex Strategy v7.1 - Broker Integration Module

Extensible broker integration framework supporting multiple exchanges:
- Coinbase Advanced Trade
- Binance
- Alpaca

Each broker implements a common interface for unified trading logic.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple
from datetime import datetime
import logging
import threading
import traceback

# Import global Kraken nonce manager (FINAL FIX)
try:
    from bot.global_kraken_nonce import get_global_kraken_nonce, get_kraken_api_lock
except ImportError:
    try:
        from global_kraken_nonce import get_global_kraken_nonce, get_kraken_api_lock
    except ImportError:
        get_global_kraken_nonce = None
        get_kraken_api_lock = None

# Import stdout suppression utility for pykrakenapi
try:
    from bot.stdout_utils import suppress_pykrakenapi_prints
except ImportError:
    try:
        from stdout_utils import suppress_pykrakenapi_prints
    except ImportError:
        # Fallback: Define locally if import fails
        import sys
        import io
        from contextlib import contextmanager
        
        @contextmanager
        def suppress_pykrakenapi_prints():
            original_stdout = sys.stdout
            try:
                sys.stdout = io.StringIO()
                yield
            finally:
                sys.stdout = original_stdout

logger = logging.getLogger("nija.broker")



class BrokerInterface(ABC):
    """
    Abstract base class for broker integrations.
    All broker adapters must implement these methods.
    """
    
    @abstractmethod
    def connect(self) -> bool:
        """
        Establish connection to broker API.
        
        Returns:
            bool: True if connection successful
        """
        pass
    
    @abstractmethod
    def get_account_balance(self) -> Dict[str, float]:
        """
        Get account balance information.
        
        Returns:
            dict: {
                'total_balance': float,
                'available_balance': float,
                'currency': str
            }
        """
        pass
    
    @abstractmethod
    def get_market_data(self, symbol: str, timeframe: str = '5m',
                       limit: int = 100) -> Optional[Dict]:
        """
        Get market data (OHLCV candles) for symbol.
        
        Args:
            symbol: Trading symbol
            timeframe: Candle timeframe (e.g., '1m', '5m', '1h')
            limit: Number of candles to retrieve
        
        Returns:
            dict: {
                'symbol': str,
                'timeframe': str,
                'candles': list of dicts with OHLCV data
            }
        """
        pass
    
    @abstractmethod
    def place_market_order(self, symbol: str, side: str, size: float,
                          size_type: str = 'quote') -> Optional[Dict]:
        """
        Place market order.
        
        Args:
            symbol: Trading symbol
            side: 'buy' or 'sell'
            size: Order size
            size_type: 'quote' (USD value) or 'base' (asset quantity)
        
        Returns:
            dict: {
                'order_id': str,
                'symbol': str,
                'side': str,
                'size': float,
                'filled_price': float,
                'status': str,
                'timestamp': datetime
            }
        """
        pass
    
    @abstractmethod
    def place_limit_order(self, symbol: str, side: str, size: float,
                         price: float, size_type: str = 'quote') -> Optional[Dict]:
        """
        Place limit order.
        
        Args:
            symbol: Trading symbol
            side: 'buy' or 'sell'
            size: Order size
            price: Limit price
            size_type: 'quote' (USD value) or 'base' (asset quantity)
        
        Returns:
            dict: Order details (same as place_market_order)
        """
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel an open order.
        
        Args:
            order_id: Order ID to cancel
        
        Returns:
            bool: True if cancelled successfully
        """
        pass
    
    @abstractmethod
    def get_open_positions(self) -> List[Dict]:
        """
        Get all open positions.
        
        Returns:
            list: List of position dicts with keys:
                - symbol: str
                - size: float
                - entry_price: float
                - current_price: float
                - pnl: float
                - pnl_pct: float
        """
        pass
    
    @abstractmethod
    def get_order_status(self, order_id: str) -> Optional[Dict]:
        """
        Get status of an order.
        
        Args:
            order_id: Order ID
        
        Returns:
            dict: Order status details
        """
        pass
    
    def get_real_entry_price(self, symbol: str) -> Optional[float]:
        """
        ✅ FIX 1: Attempt to get real entry price from broker order history.
        
        This is an optional method that brokers can implement to provide
        real entry prices from their order history. If not available,
        returns None (caller should use fallback logic).
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Real entry price if available, None otherwise
        """
        # Default implementation - brokers can override
        return None



class CoinbaseBrokerAdapter(BrokerInterface):
    """
    Coinbase Advanced Trade API adapter.
    
    Integrates with existing Coinbase client in the codebase.
    """
    
    def __init__(self, api_key: str = None, api_secret: str = None):
        """
        Initialize Coinbase broker adapter.
        
        Args:
            api_key: Coinbase API key (loaded from environment if None)
            api_secret: Coinbase API secret (loaded from environment if None)
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.client = None
        logger.info("Coinbase broker adapter initialized")
    
    def connect(self) -> bool:
        """Connect to Coinbase Advanced Trade API."""
        try:
            # TODO: Implement actual connection using existing broker_manager
            # Example:
            # from broker_manager import BrokerManager
            # self.client = BrokerManager()
            logger.info("Connecting to Coinbase Advanced Trade API...")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to Coinbase: {e}")
            return False
    
    def get_account_balance(self) -> Dict[str, float]:
        """Get Coinbase account balance."""
        # TODO: Implement using existing broker_manager methods
        logger.info("Fetching Coinbase account balance...")
        return {
            'total_balance': 0.0,
            'available_balance': 0.0,
            'currency': 'USD'
        }
    
    def get_market_data(self, symbol: str, timeframe: str = '5m',
                       limit: int = 100) -> Optional[Dict]:
        """Get market data from Coinbase."""
        # TODO: Implement using existing Coinbase candle fetching
        logger.info(f"Fetching market data for {symbol} ({timeframe})...")
        return None
    
    def place_market_order(self, symbol: str, side: str, size: float,
                          size_type: str = 'quote') -> Optional[Dict]:
        """Place market order on Coinbase."""
        # TODO: Implement using existing broker_manager order methods
        logger.info(f"Placing Coinbase market {side} order: {symbol} size={size}")
        return None
    
    def place_limit_order(self, symbol: str, side: str, size: float,
                         price: float, size_type: str = 'quote') -> Optional[Dict]:
        """Place limit order on Coinbase."""
        logger.info(f"Placing Coinbase limit {side} order: {symbol} @ {price}")
        return None
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel order on Coinbase."""
        logger.info(f"Cancelling Coinbase order: {order_id}")
        return False
    
    def get_open_positions(self) -> List[Dict]:
        """Get open positions from Coinbase."""
        # TODO: Implement using existing position tracking
        return []
    
    def get_order_status(self, order_id: str) -> Optional[Dict]:
        """Get order status from Coinbase."""
        logger.info(f"Checking Coinbase order status: {order_id}")
        return None


class BinanceBrokerAdapter(BrokerInterface):
    """
    Binance API adapter (skeleton for future implementation).
    
    Supports both spot and futures trading.
    """
    
    def __init__(self, api_key: str = None, api_secret: str = None,
                 testnet: bool = False):
        """
        Initialize Binance broker adapter.
        
        Args:
            api_key: Binance API key
            api_secret: Binance API secret
            testnet: Use Binance testnet (default: False)
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.testnet = testnet
        self.client = None
        logger.info(f"Binance broker adapter initialized (testnet={testnet})")
    
    def connect(self) -> bool:
        """Connect to Binance API."""
        logger.info("Connecting to Binance API...")
        # TODO: Implement Binance client initialization
        # Example:
        # from binance.client import Client
        # self.client = Client(self.api_key, self.api_secret, testnet=self.testnet)
        return False
    
    def get_account_balance(self) -> Dict[str, float]:
        """Get Binance account balance."""
        logger.info("Fetching Binance account balance...")
        return {
            'total_balance': 0.0,
            'available_balance': 0.0,
            'currency': 'USDT'
        }
    
    def get_market_data(self, symbol: str, timeframe: str = '5m',
                       limit: int = 100) -> Optional[Dict]:
        """Get market data from Binance."""
        logger.info(f"Fetching Binance market data for {symbol}...")
        return None
    
    def place_market_order(self, symbol: str, side: str, size: float,
                          size_type: str = 'quote') -> Optional[Dict]:
        """Place market order on Binance."""
        logger.info(f"Placing Binance market {side} order: {symbol}")
        return None
    
    def place_limit_order(self, symbol: str, side: str, size: float,
                         price: float, size_type: str = 'quote') -> Optional[Dict]:
        """Place limit order on Binance."""
        logger.info(f"Placing Binance limit {side} order: {symbol} @ {price}")
        return None
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel order on Binance."""
        logger.info(f"Cancelling Binance order: {order_id}")
        return False
    
    def get_open_positions(self) -> List[Dict]:
        """Get open positions from Binance."""
        return []
    
    def get_order_status(self, order_id: str) -> Optional[Dict]:
        """Get order status from Binance."""
        logger.info(f"Checking Binance order status: {order_id}")
        return None


class AlpacaBrokerAdapter(BrokerInterface):
    """
    Alpaca API adapter for stock/crypto trading (skeleton for future implementation).
    """
    
    def __init__(self, api_key: str = None, api_secret: str = None,
                 paper: bool = True):
        """
        Initialize Alpaca broker adapter.
        
        Args:
            api_key: Alpaca API key
            api_secret: Alpaca API secret
            paper: Use paper trading (default: True)
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.paper = paper
        self.client = None
        logger.info(f"Alpaca broker adapter initialized (paper={paper})")
    
    def connect(self) -> bool:
        """Connect to Alpaca API."""
        logger.info("Connecting to Alpaca API...")
        # TODO: Implement Alpaca client initialization
        # Example:
        # from alpaca.trading.client import TradingClient
        # self.client = TradingClient(self.api_key, self.api_secret, paper=self.paper)
        return False
    
    def get_account_balance(self) -> Dict[str, float]:
        """Get Alpaca account balance."""
        logger.info("Fetching Alpaca account balance...")
        return {
            'total_balance': 0.0,
            'available_balance': 0.0,
            'currency': 'USD'
        }
    
    def get_market_data(self, symbol: str, timeframe: str = '5m',
                       limit: int = 100) -> Optional[Dict]:
        """Get market data from Alpaca."""
        logger.info(f"Fetching Alpaca market data for {symbol}...")
        return None
    
    def place_market_order(self, symbol: str, side: str, size: float,
                          size_type: str = 'quote') -> Optional[Dict]:
        """Place market order on Alpaca."""
        logger.info(f"Placing Alpaca market {side} order: {symbol}")
        return None
    
    def place_limit_order(self, symbol: str, side: str, size: float,
                         price: float, size_type: str = 'quote') -> Optional[Dict]:
        """Place limit order on Alpaca."""
        logger.info(f"Placing Alpaca limit {side} order: {symbol} @ {price}")
        return None
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel order on Alpaca."""
        logger.info(f"Cancelling Alpaca order: {order_id}")
        return False
    
    def get_open_positions(self) -> List[Dict]:
        """Get open positions from Alpaca."""
        return []
    
    def get_order_status(self, order_id: str) -> Optional[Dict]:
        """Get order status from Alpaca."""
        logger.info(f"Checking Alpaca order status: {order_id}")
        return None


class KrakenBrokerAdapter(BrokerInterface):
    """
    Kraken Pro API adapter for cryptocurrency spot trading.
    
    Supports spot trading with USD/USDT pairs.
    Documentation: https://docs.kraken.com/rest/
    """
    
    # Class-level flag to track if detailed permission error instructions have been logged
    # This prevents spamming the logs with duplicate permission error messages
    # The detailed instructions are logged ONCE GLOBALLY across all adapter instances
    # Thread-safe: uses lock for concurrent access protection
    _permission_error_details_logged = False
    _permission_errors_lock = threading.Lock()
    
    def __init__(self, api_key: str = None, api_secret: str = None):
        """
        Initialize Kraken broker adapter.
        
        Args:
            api_key: Kraken API key
            api_secret: Kraken API private key
        """
        import os
        
        # Use explicit credentials if both are provided, otherwise use environment variables
        if api_key and api_secret:
            # Explicit credentials provided - use them directly
            self.api_key = api_key
            self.api_secret = api_secret
            logger.info("Kraken broker adapter initialized with explicit credentials")
        else:
            # Load from environment variables
            # Prioritize KRAKEN_MASTER_API_KEY, fallback to legacy KRAKEN_API_KEY
            master_key = os.getenv("KRAKEN_MASTER_API_KEY")
            master_secret = os.getenv("KRAKEN_MASTER_API_SECRET")
            legacy_key = os.getenv("KRAKEN_API_KEY")
            legacy_secret = os.getenv("KRAKEN_API_SECRET")
            
            # Use master credentials if both are available, otherwise try legacy
            if master_key and master_secret:
                self.api_key = master_key
                self.api_secret = master_secret
                logger.info("Kraken broker adapter initialized with KRAKEN_MASTER_API_KEY")
            elif legacy_key and legacy_secret:
                self.api_key = legacy_key
                self.api_secret = legacy_secret
                logger.info("Kraken broker adapter initialized with legacy KRAKEN_API_KEY")
            else:
                # No credentials available
                self.api_key = None
                self.api_secret = None
                logger.warning("Kraken broker adapter initialized without credentials")
        
        self.api = None
        self.kraken_api = None
    
    def _kraken_api_call(self, method: str, params: dict = None):
        """
        Helper method to make Kraken API calls with global serialization lock.
        
        This method wraps all query_private calls with the global API lock
        to ensure only ONE Kraken API call happens at a time across all accounts.
        
        Args:
            method: Kraken API method name
            params: Optional parameters dict
            
        Returns:
            API response
        """
        # Suppress pykrakenapi's print() statements
        with suppress_pykrakenapi_prints():
            if get_kraken_api_lock is not None:
                api_lock = get_kraken_api_lock()
                with api_lock:
                    if params:
                        return self.api.query_private(method, params)
                    else:
                        return self.api.query_private(method)
            else:
                # Fallback: direct call without global lock
                if params:
                    return self.api.query_private(method, params)
                else:
                    return self.api.query_private(method)
    
    def connect(self) -> bool:
        """Connect to Kraken API."""
        try:
            import krakenex
            from pykrakenapi import KrakenAPI
            
            if not self.api_key or not self.api_secret:
                logger.error("Kraken credentials not found")
                return False
            
            self.api = krakenex.API(key=self.api_key, secret=self.api_secret)
            
            # FINAL FIX: Override nonce generator to use GLOBAL Kraken Nonce Manager
            # ONE global source for all users (master + users)
            if get_global_kraken_nonce is not None:
                def _global_nonce():
                    """Generate nonce using global manager (nanosecond precision)."""
                    return str(get_global_kraken_nonce())
                
                self.api._nonce = _global_nonce
                logger.debug("✅ Global Kraken Nonce Manager installed for KrakenBrokerAdapter")
            else:
                logger.warning("⚠️ Global nonce manager not available, using krakenex default")
            
            self.kraken_api = KrakenAPI(self.api)
            
            # Test connection - use helper method for serialized API call
            balance = self._kraken_api_call('Balance')
            
            if balance and 'error' in balance and balance['error']:
                error_msgs = ', '.join(balance['error'])
                
                # Check if it's a permission error
                is_permission_error = any(keyword in error_msgs.lower() for keyword in [
                    'permission denied', 'egeneral:permission', 
                    'eapi:invalid permission', 'insufficient permission'
                ])
                
                if is_permission_error:
                    logger.error(f"❌ Kraken connection test failed: {error_msgs}")
                    
                    # Thread-safe check and update of global flag
                    with KrakenBrokerAdapter._permission_errors_lock:
                        # Only log detailed permission error instructions ONCE GLOBALLY
                        # After the first Kraken permission error, subsequent errors
                        # get a brief reference message instead of full instructions
                        # This prevents log spam when multiple adapters have permission errors
                        if not KrakenBrokerAdapter._permission_error_details_logged:
                            KrakenBrokerAdapter._permission_error_details_logged = True
                            should_log_details = True
                        else:
                            should_log_details = False
                    
                    if should_log_details:
                        logger.error("   ⚠️  API KEY PERMISSION ERROR")
                        logger.error("   Your Kraken API key does not have the required permissions.")
                        logger.warning("")
                        logger.warning("   To fix this issue:")
                        logger.warning("   1. Go to https://www.kraken.com/u/security/api")
                        logger.warning("   2. Find your API key and edit its permissions")
                        logger.warning("   3. Enable these permissions:")
                        logger.warning("      ✅ Query Funds (required to check balance)")
                        logger.warning("      ✅ Query Open Orders & Trades (required for position tracking)")
                        logger.warning("      ✅ Query Closed Orders & Trades (required for trade history)")
                        logger.warning("      ✅ Create & Modify Orders (required to place trades)")
                        logger.warning("      ✅ Cancel/Close Orders (required for stop losses)")
                        logger.warning("   4. Save changes and restart the bot")
                        logger.warning("")
                        logger.warning("   For security, do NOT enable 'Withdraw Funds' permission")
                        logger.warning("   See KRAKEN_PERMISSION_ERROR_FIX.md for detailed instructions")
                    else:
                        logger.error("   ⚠️  API KEY PERMISSION ERROR")
                        logger.error("   Your Kraken API key does not have the required permissions.")
                        logger.error("   Fix: Enable 'Query Funds', 'Query/Create/Cancel Orders' permissions at:")
                        logger.error("   https://www.kraken.com/u/security/api")
                        logger.error("   📖 See KRAKEN_PERMISSION_ERROR_FIX.md for detailed instructions")
                else:
                    logger.error(f"Kraken connection test failed: {error_msgs}")
                
                return False
            
            if balance and 'result' in balance:
                logger.info("✅ Kraken connected")
                return True
            
            return False
                
        except ImportError:
            logger.error("Kraken SDK not installed. Install with: pip install krakenex pykrakenapi")
            return False
        except Exception as e:
            logger.error(f"Failed to connect to Kraken: {e}")
            return False
    
    def get_account_balance(self) -> Dict[str, float]:
        """Get Kraken account balance with proper error handling."""
        try:
            if not self.api:
                return {
                    'total_balance': 0.0,
                    'available_balance': 0.0,
                    'currency': 'USD',
                    'error': True,
                    'error_message': 'API not connected'
                }
            
            # Use helper method for serialized API call
            balance = self._kraken_api_call('Balance')
            
            # Check for API errors
            if balance and 'error' in balance and balance['error']:
                error_msgs = ', '.join(balance['error'])
                logger.error(f"Kraken API error fetching balance: {error_msgs}")
                return {
                    'total_balance': 0.0,
                    'available_balance': 0.0,
                    'currency': 'USD',
                    'error': True,
                    'error_message': f'API error: {error_msgs}'
                }
            
            if balance and 'result' in balance:
                result = balance['result']
                usd_balance = float(result.get('ZUSD', 0))
                usdt_balance = float(result.get('USDT', 0))
                total = usd_balance + usdt_balance
                
                logger.info(f"Kraken balance: USD ${usd_balance:.2f} + USDT ${usdt_balance:.2f} = ${total:.2f}")
                
                return {
                    'total_balance': total,
                    'available_balance': total,
                    'currency': 'USD',
                    'error': False
                }
            
            # Unexpected response format
            return {
                'total_balance': 0.0,
                'available_balance': 0.0,
                'currency': 'USD',
                'error': True,
                'error_message': 'Unexpected API response format'
            }
            
        except Exception as e:
            logger.error(f"Error fetching Kraken balance: {e}")
            return {
                'total_balance': 0.0,
                'available_balance': 0.0,
                'currency': 'USD',
                'error': True,
                'error_message': str(e)
            }
    
    def get_market_data(self, symbol: str, timeframe: str = '5m',
                       limit: int = 100) -> Optional[Dict]:
        """Get market data from Kraken."""
        try:
            if not self.kraken_api:
                return None
            
            # Convert symbol format to Kraken format
            kraken_symbol = symbol.replace('-', '').upper()
            if kraken_symbol.startswith('BTC'):
                kraken_symbol = kraken_symbol.replace('BTC', 'XBT', 1)
            
            # Map timeframe to Kraken interval (in minutes)
            interval_map = {
                "1m": 1, "5m": 5, "15m": 15, "30m": 30,
                "1h": 60, "4h": 240, "1d": 1440
            }
            
            kraken_interval = interval_map.get(timeframe.lower(), 5)
            
            # Fetch OHLC data
            ohlc, last = self.kraken_api.get_ohlc_data(
                kraken_symbol,
                interval=kraken_interval,
                ascending=True
            )
            
            # Convert to standard format
            candles = []
            for idx, row in ohlc.tail(limit).iterrows():
                candles.append({
                    'timestamp': int(idx.timestamp()),
                    'open': float(row['open']),
                    'high': float(row['high']),
                    'low': float(row['low']),
                    'close': float(row['close']),
                    'volume': float(row['volume'])
                })
            
            logger.info(f"Fetched {len(candles)} candles for {kraken_symbol} from Kraken")
            
            return {
                'symbol': kraken_symbol,
                'timeframe': timeframe,
                'candles': candles
            }
            
        except Exception as e:
            logger.error(f"Error fetching Kraken market data: {e}")
            return None
    
    def place_market_order(self, symbol: str, side: str, size: float,
                          size_type: str = 'quote') -> Optional[Dict]:
        """Place market order on Kraken."""
        try:
            if not self.api:
                return None
            
            # ✅ FIX 3: HARD SYMBOL ALLOWLIST FOR KRAKEN
            # Kraken only supports */USD and */USDT pairs
            # Skip unsupported symbols (BUSD, etc.) to prevent silent order rejection
            if not (symbol.endswith('/USD') or symbol.endswith('/USDT') or 
                    symbol.endswith('-USD') or symbol.endswith('-USDT')):
                logger.info(f"⏭️ Kraken skip unsupported symbol {symbol}")
                logger.info(f"   💡 Kraken only supports */USD and */USDT pairs")
                return {
                    'order_id': None,
                    'symbol': symbol,
                    'side': side,
                    'size': size,
                    'filled_price': 0.0,
                    'status': 'error',
                    'error': 'UNSUPPORTED_SYMBOL',
                    'message': 'Kraken only supports */USD and */USDT pairs',
                    'timestamp': datetime.now()
                }
            
            # Convert symbol format
            kraken_symbol = symbol.replace('-', '').upper()
            if kraken_symbol.startswith('BTC'):
                kraken_symbol = kraken_symbol.replace('BTC', 'XBT', 1)
            
            # Place market order
            order_params = {
                'pair': kraken_symbol,
                'type': side.lower(),
                'ordertype': 'market',
                'volume': str(size)
            }
            
            # Use helper method for serialized API call
            result = self._kraken_api_call('AddOrder', order_params)
            
            # ✅ FIX 4: ENHANCED ORDER LOGGING WITH FILL DETAILS
            if result and 'result' in result:
                order_result = result['result']
                txid = order_result.get('txid', [])
                order_id = txid[0] if txid else None
                
                logger.info(f"Kraken market {side} order placed: {kraken_symbol} (ID: {order_id})")
                
                # ✅ REQUIREMENT #2: Attempt to fetch order fill details
                # Query the order to get filled price and volume
                filled_price = 0.0
                filled_volume = size
                
                if order_id:
                    try:
                        # Give the order a moment to fill
                        # Configurable delay to balance confirmation accuracy vs execution speed
                        import time
                        order_query_delay = 0.5  # seconds - can be adjusted based on broker response time
                        time.sleep(order_query_delay)
                        
                        # Query order details to get filled price
                        order_query = self._kraken_api_call('QueryOrders', {'txid': order_id})
                        
                        if order_query and 'result' in order_query:
                            order_details = order_query['result'].get(order_id, {})
                            filled_price = float(order_details.get('price', 0.0))
                            filled_volume = float(order_details.get('vol_exec', size))
                            order_status = order_details.get('status', 'unknown')
                            
                            # ✅ ORDER CONFIRMATION LOGGING (REQUIREMENT #2)
                            logger.info(f"   ✅ ORDER CONFIRMED:")
                            logger.info(f"      • Order ID: {order_id}")
                            logger.info(f"      • Filled Volume: {filled_volume:.8f} {kraken_symbol[:3]}")
                            logger.info(f"      • Filled Price: ${filled_price:.2f}")
                            logger.info(f"      • Status: {order_status}")
                            
                            # Note: Balance delta requires fetching balance before/after
                            # We can calculate approximate delta from filled volume * price
                            if side.lower() == 'sell':
                                balance_delta = filled_volume * filled_price
                                logger.info(f"      • Balance Delta (approx): +${balance_delta:.2f}")
                            else:
                                balance_delta = -(filled_volume * filled_price)
                                logger.info(f"      • Balance Delta (approx): ${balance_delta:.2f}")
                    except Exception as query_err:
                        logger.warning(f"   ⚠️  Could not query order details: {query_err}")
                
                return {
                    'order_id': order_id,
                    'symbol': kraken_symbol,
                    'side': side,
                    'size': size,
                    'filled_price': filled_price,
                    'filled_volume': filled_volume,
                    'status': 'filled',
                    'timestamp': datetime.now()
                }
            
            # Order failed - log comprehensive error details
            error_msg = result.get('error', ['Unknown error'])[0] if result else 'No response'
            logger.error(f"❌ ORDER FAILED [kraken] {symbol}: {error_msg}")
            logger.error(f"   Side: {side}, Size: {size}, Type: {size_type}")
            logger.error(f"   Full result: {result}")
            
            return {
                'order_id': None,
                'symbol': symbol,
                'side': side,
                'size': size,
                'filled_price': 0.0,
                'status': 'error',
                'error': error_msg,
                'timestamp': datetime.now()
            }
            
        except Exception as e:
            # ✅ FIX 4: LOG ALL ORDER EXCEPTIONS
            logger.error(f"❌ ORDER FAILED [kraken] {symbol}: {e}")
            logger.error(f"   Exception type: {type(e).__name__}")
            logger.error(f"   Side: {side}, Size: {size}")
            logger.error(f"   Traceback: {traceback.format_exc()}")
            
            return {
                'order_id': None,
                'symbol': symbol,
                'side': side,
                'size': size,
                'filled_price': 0.0,
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now()
            }
    
    def place_limit_order(self, symbol: str, side: str, size: float,
                         price: float, size_type: str = 'quote') -> Optional[Dict]:
        """Place limit order on Kraken."""
        try:
            if not self.api:
                return None
            
            # Convert symbol format
            kraken_symbol = symbol.replace('-', '').upper()
            if kraken_symbol.startswith('BTC'):
                kraken_symbol = kraken_symbol.replace('BTC', 'XBT', 1)
            
            # Place limit order
            order_params = {
                'pair': kraken_symbol,
                'type': side.lower(),
                'ordertype': 'limit',
                'price': str(price),
                'volume': str(size)
            }
            
            # Use helper method for serialized API call
            result = self._kraken_api_call('AddOrder', order_params)
            
            if result and 'result' in result:
                order_result = result['result']
                txid = order_result.get('txid', [])
                order_id = txid[0] if txid else None
                
                logger.info(f"Kraken limit {side} order placed: {kraken_symbol} @ ${price} (ID: {order_id})")
                
                return {
                    'order_id': order_id,
                    'symbol': kraken_symbol,
                    'side': side,
                    'size': size,
                    'filled_price': price,
                    'status': 'open',
                    'timestamp': datetime.now()
                }
            
            error_msg = result.get('error', ['Unknown error'])[0] if result else 'No response'
            logger.error(f"Kraken limit order failed: {error_msg}")
            return None
            
        except Exception as e:
            logger.error(f"Kraken limit order error: {e}")
            return None
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel order on Kraken."""
        try:
            if not self.api:
                return False
            
            # Use helper method for serialized API call
            result = self._kraken_api_call('CancelOrder', {'txid': order_id})
            
            if result and 'result' in result and 'count' in result['result']:
                count = result['result']['count']
                logger.info(f"Cancelled {count} Kraken order(s): {order_id}")
                return count > 0
            
            return False
            
        except Exception as e:
            logger.error(f"Kraken cancel order error: {e}")
            return False
    
    def get_open_positions(self) -> List[Dict]:
        """Get open positions from Kraken."""
        try:
            if not self.api:
                return []
            
            # Use helper method for serialized API call
            balance = self._kraken_api_call('Balance')
            
            if balance and 'result' in balance:
                result = balance['result']
                positions = []
                
                for asset, amount in result.items():
                    balance_val = float(amount)
                    
                    # Skip USD/USDT and zero balances
                    if asset in ['ZUSD', 'USDT'] or balance_val <= 0:
                        continue
                    
                    # Convert Kraken asset codes
                    currency = asset
                    if currency.startswith('X') and len(currency) == 4:
                        currency = currency[1:]
                    if currency == 'XBT':
                        currency = 'BTC'
                    
                    positions.append({
                        'symbol': f'{currency}USD',
                        'size': balance_val,
                        'entry_price': 0.0,
                        'current_price': 0.0,
                        'pnl': 0.0,
                        'pnl_pct': 0.0
                    })
                
                return positions
            
            return []
            
        except Exception as e:
            logger.error(f"Error fetching Kraken positions: {e}")
            return []
    
    def get_order_status(self, order_id: str) -> Optional[Dict]:
        """Get order status from Kraken."""
        try:
            if not self.api:
                return None
            
            # Use helper method for serialized API call
            result = self._kraken_api_call('QueryOrders', {'txid': order_id})
            
            if result and 'result' in result:
                orders = result['result']
                if order_id in orders:
                    order = orders[order_id]
                    logger.info(f"Kraken order status: {order_id} - {order.get('status', 'unknown')}")
                    return order
            
            return None
            
        except Exception as e:
            logger.error(f"Kraken get order status error: {e}")
            return None
    
    def get_real_entry_price(self, symbol: str) -> Optional[float]:
        """
        ✅ FIX 1: Try to get real entry price from Kraken order history.
        
        This method attempts to fetch the actual entry price from the broker's
        order history. If not available, returns None (caller should use fallback).
        
        Args:
            symbol: Trading symbol
            
        Returns:
            Real entry price if available, None otherwise
        """
        try:
            if not self.api:
                return None
            
            # Convert symbol format to Kraken format
            kraken_symbol = symbol.replace('-', '').upper()
            if kraken_symbol.startswith('BTC'):
                kraken_symbol = kraken_symbol.replace('BTC', 'XBT', 1)
            
            # Query closed orders (last 50)
            # Use helper method for serialized API call
            result = self._kraken_api_call('ClosedOrders', {'trades': True})
            
            if result and 'result' in result and 'closed' in result['result']:
                closed_orders = result['result']['closed']
                
                # Find most recent buy order for this symbol
                for order_id, order_data in sorted(
                    closed_orders.items(),
                    key=lambda x: x[1].get('opentm', 0),
                    reverse=True  # Most recent first
                ):
                    if order_data.get('descr', {}).get('pair') == kraken_symbol:
                        if order_data.get('descr', {}).get('type') == 'buy':
                            # Found a buy order - extract average price
                            avg_price = float(order_data.get('price', 0))
                            if avg_price > 0:
                                logger.debug(f"Found real entry price for {symbol}: ${avg_price:.2f}")
                                return avg_price
            
            # No entry price found in recent orders
            logger.debug(f"No real entry price found for {symbol} in Kraken order history")
            return None
            
        except Exception as e:
            logger.debug(f"Error fetching real entry price for {symbol}: {e}")
            return None



class OKXBrokerAdapter(BrokerInterface):
    """
    OKX Exchange API adapter for cryptocurrency spot and futures trading.
    
    Supports:
    - Spot trading (USDT pairs)
    - Futures/Perpetual contracts
    - Testnet for paper trading
    - Advanced order types
    
    Documentation: https://www.okx.com/docs-v5/en/
    """
    
    def __init__(self, api_key: str = None, api_secret: str = None,
                 passphrase: str = None, testnet: bool = False):
        """
        Initialize OKX broker adapter.
        
        Args:
            api_key: OKX API key
            api_secret: OKX API secret
            passphrase: OKX API passphrase
            testnet: Use OKX testnet (default: False)
        """
        import os
        self.api_key = api_key or os.getenv("OKX_API_KEY")
        self.api_secret = api_secret or os.getenv("OKX_API_SECRET")
        self.passphrase = passphrase or os.getenv("OKX_PASSPHRASE")
        self.testnet = testnet or os.getenv("OKX_USE_TESTNET", "false").lower() in ["true", "1", "yes"]
        self.account_api = None
        self.market_api = None
        self.trade_api = None
        logger.info(f"OKX broker adapter initialized (testnet={self.testnet})")
    
    def connect(self) -> bool:
        """Connect to OKX API."""
        try:
            from okx.api import Account, Market, Trade
            
            if not self.api_key or not self.api_secret or not self.passphrase:
                logger.error("OKX credentials not found")
                return False
            
            # API flag: "1" for testnet, "0" for live
            flag = "1" if self.testnet else "0"
            
            # Initialize OKX API clients
            self.account_api = Account(self.api_key, self.api_secret, 
                                       self.passphrase, flag)
            self.market_api = Market(self.api_key, self.api_secret,
                                     self.passphrase, flag)
            self.trade_api = Trade(self.api_key, self.api_secret,
                                   self.passphrase, flag)
            
            # Test connection
            result = self.account_api.get_balance()
            
            if result and result.get('code') == '0':
                env_type = "testnet" if self.testnet else "live"
                logger.info(f"✅ OKX connected ({env_type})")
                return True
            else:
                error_msg = result.get('msg', 'Unknown error') if result else 'No response'
                logger.error(f"OKX connection test failed: {error_msg}")
                return False
                
        except ImportError:
            logger.error("OKX SDK not installed or incompatible version. Install with: pip install okx==2.1.2")
            return False
        except Exception as e:
            logger.error(f"Failed to connect to OKX: {e}")
            return False
    
    def get_account_balance(self) -> Dict[str, float]:
        """Get OKX account balance."""
        try:
            if not self.account_api:
                return {
                    'total_balance': 0.0,
                    'available_balance': 0.0,
                    'currency': 'USDT'
                }
            
            result = self.account_api.get_balance()
            
            if result and result.get('code') == '0':
                data = result.get('data', [])
                if data and len(data) > 0:
                    # Get total equity
                    total_eq = float(data[0].get('totalEq', 0))
                    
                    # Find USDT available balance
                    details = data[0].get('details', [])
                    usdt_available = 0.0
                    
                    for detail in details:
                        if detail.get('ccy') == 'USDT':
                            usdt_available = float(detail.get('availBal', 0))
                            break
                    
                    logger.info(f"OKX balance: Total ${total_eq:.2f}, Available USDT: ${usdt_available:.2f}")
                    
                    return {
                        'total_balance': total_eq,
                        'available_balance': usdt_available,
                        'currency': 'USDT'
                    }
            
            return {
                'total_balance': 0.0,
                'available_balance': 0.0,
                'currency': 'USDT'
            }
            
        except Exception as e:
            logger.error(f"Error fetching OKX balance: {e}")
            return {
                'total_balance': 0.0,
                'available_balance': 0.0,
                'currency': 'USDT'
            }
    
    def get_market_data(self, symbol: str, timeframe: str = '5m',
                       limit: int = 100) -> Optional[Dict]:
        """Get market data from OKX."""
        try:
            if not self.market_api:
                return None
            
            # Convert symbol format (BTC-USD -> BTC-USDT)
            okx_symbol = symbol.replace('-USD', '-USDT') if '-USD' in symbol else symbol
            
            # Map timeframe to OKX format
            timeframe_map = {
                "1m": "1m", "5m": "5m", "15m": "15m",
                "1h": "1H", "4h": "4H", "1d": "1D"
            }
            okx_timeframe = timeframe_map.get(timeframe.lower(), "5m")
            
            # Fetch candles
            result = self.market_api.get_candles(
                instId=okx_symbol,
                bar=okx_timeframe,
                limit=str(min(limit, 100))
            )
            
            if result and result.get('code') == '0':
                data = result.get('data', [])
                candles = []
                
                for candle in data:
                    candles.append({
                        'timestamp': int(candle[0]),
                        'open': float(candle[1]),
                        'high': float(candle[2]),
                        'low': float(candle[3]),
                        'close': float(candle[4]),
                        'volume': float(candle[5])
                    })
                
                logger.info(f"Fetched {len(candles)} candles for {okx_symbol} from OKX")
                
                return {
                    'symbol': okx_symbol,
                    'timeframe': timeframe,
                    'candles': candles
                }
            
            return None
            
        except Exception as e:
            logger.error(f"Error fetching OKX market data: {e}")
            return None
    
    def place_market_order(self, symbol: str, side: str, size: float,
                          size_type: str = 'quote') -> Optional[Dict]:
        """Place market order on OKX."""
        try:
            if not self.trade_api:
                return None
            
            # Convert symbol format
            okx_symbol = symbol.replace('-USD', '-USDT') if '-USD' in symbol else symbol
            
            # Place order
            result = self.trade_api.place_order(
                instId=okx_symbol,
                tdMode='cash',  # Spot trading
                side=side.lower(),
                ordType='market',
                sz=str(size)
            )
            
            if result and result.get('code') == '0':
                data = result.get('data', [])
                if data and len(data) > 0:
                    order_id = data[0].get('ordId')
                    logger.info(f"OKX market {side} order placed: {okx_symbol} (ID: {order_id})")
                    
                    return {
                        'order_id': order_id,
                        'symbol': okx_symbol,
                        'side': side,
                        'size': size,
                        'filled_price': 0.0,  # Would need to fetch order details
                        'status': 'filled',
                        'timestamp': datetime.now()
                    }
            
            error_msg = result.get('msg', 'Unknown error') if result else 'No response'
            logger.error(f"OKX order failed: {error_msg}")
            return None
            
        except Exception as e:
            logger.error(f"OKX order error: {e}")
            return None
    
    def place_limit_order(self, symbol: str, side: str, size: float,
                         price: float, size_type: str = 'quote') -> Optional[Dict]:
        """Place limit order on OKX."""
        try:
            if not self.trade_api:
                return None
            
            # Convert symbol format
            okx_symbol = symbol.replace('-USD', '-USDT') if '-USD' in symbol else symbol
            
            # Place limit order
            result = self.trade_api.place_order(
                instId=okx_symbol,
                tdMode='cash',
                side=side.lower(),
                ordType='limit',
                px=str(price),
                sz=str(size)
            )
            
            if result and result.get('code') == '0':
                data = result.get('data', [])
                if data and len(data) > 0:
                    order_id = data[0].get('ordId')
                    logger.info(f"OKX limit {side} order placed: {okx_symbol} @ ${price} (ID: {order_id})")
                    
                    return {
                        'order_id': order_id,
                        'symbol': okx_symbol,
                        'side': side,
                        'size': size,
                        'filled_price': price,
                        'status': 'open',
                        'timestamp': datetime.now()
                    }
            
            error_msg = result.get('msg', 'Unknown error') if result else 'No response'
            logger.error(f"OKX limit order failed: {error_msg}")
            return None
            
        except Exception as e:
            logger.error(f"OKX limit order error: {e}")
            return None
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel order on OKX."""
        try:
            if not self.trade_api:
                return False
            
            # Note: OKX needs both ordId and instId to cancel
            # This is a simplified version - you'd need to track instId
            logger.warning("OKX order cancellation requires instrument ID - not implemented")
            return False
            
        except Exception as e:
            logger.error(f"OKX cancel order error: {e}")
            return False
    
    def get_open_positions(self) -> List[Dict]:
        """Get open positions from OKX."""
        try:
            if not self.account_api:
                return []
            
            result = self.account_api.get_balance()
            
            if result and result.get('code') == '0':
                positions = []
                data = result.get('data', [])
                
                if data and len(data) > 0:
                    details = data[0].get('details', [])
                    
                    for detail in details:
                        ccy = detail.get('ccy')
                        available = float(detail.get('availBal', 0))
                        
                        # Only non-zero, non-USDT balances
                        if ccy != 'USDT' and available > 0:
                            positions.append({
                                'symbol': f'{ccy}-USDT',
                                'size': available,
                                'entry_price': 0.0,  # Would need trade history
                                'current_price': 0.0,  # Would need ticker
                                'pnl': 0.0,
                                'pnl_pct': 0.0
                            })
                
                return positions
            
            return []
            
        except Exception as e:
            logger.error(f"Error fetching OKX positions: {e}")
            return []
    
    def get_order_status(self, order_id: str) -> Optional[Dict]:
        """Get order status from OKX."""
        logger.info(f"Checking OKX order status: {order_id}")
        # TODO: Implement using trade_api.get_order()
        return None


class BrokerFactory:
    """
    Factory class for creating broker adapters.
    """
    
    @staticmethod
    def create_broker(broker_name: str, **kwargs) -> BrokerInterface:
        """
        Create a broker adapter instance.
        
        Args:
            broker_name: Name of broker ('coinbase', 'binance', 'kraken', 'alpaca', 'okx')
            **kwargs: Broker-specific configuration
        
        Returns:
            BrokerInterface: Broker adapter instance
        
        Raises:
            ValueError: If broker_name is not supported
        """
        broker_name = broker_name.lower()
        
        if broker_name == 'coinbase':
            return CoinbaseBrokerAdapter(**kwargs)
        elif broker_name == 'binance':
            return BinanceBrokerAdapter(**kwargs)
        elif broker_name == 'kraken':
            return KrakenBrokerAdapter(**kwargs)
        elif broker_name == 'alpaca':
            return AlpacaBrokerAdapter(**kwargs)
        elif broker_name == 'okx':
            return OKXBrokerAdapter(**kwargs)
        else:
            raise ValueError(f"Unsupported broker: {broker_name}")
