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
            broker_name: Name of broker ('coinbase', 'binance', 'alpaca', 'okx')
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
        elif broker_name == 'alpaca':
            return AlpacaBrokerAdapter(**kwargs)
        elif broker_name == 'okx':
            return OKXBrokerAdapter(**kwargs)
        else:
            raise ValueError(f"Unsupported broker: {broker_name}")
