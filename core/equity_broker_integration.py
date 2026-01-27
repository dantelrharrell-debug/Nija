"""
NIJA Equity Broker Integration

Integrates with stock brokers for equity trading:
- Alpaca (primary)
- Interactive Brokers
- TD Ameritrade (future)

This provides a unified interface for stock/ETF trading similar
to the existing crypto broker integration.

Author: NIJA Trading Systems
Version: 1.0
Date: January 27, 2026
"""

import logging
import os
from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger("nija.equity_broker")


class EquityBroker(Enum):
    """Supported equity brokers."""
    ALPACA = "alpaca"
    INTERACTIVE_BROKERS = "interactive_brokers"
    TD_AMERITRADE = "td_ameritrade"
    TRADIER = "tradier"


class OrderSide(Enum):
    """Order side."""
    BUY = "buy"
    SELL = "sell"


class OrderType(Enum):
    """Order type."""
    MARKET = "market"
    LIMIT = "limit"
    STOP = "stop"
    STOP_LIMIT = "stop_limit"


@dataclass
class EquityPosition:
    """Represents an equity position."""
    symbol: str
    quantity: float
    entry_price: float
    current_price: float
    market_value: float
    unrealized_pnl: float
    broker: EquityBroker


class BaseEquityBroker(ABC):
    """
    Base class for equity broker integrations.
    
    All equity brokers must implement these methods.
    """
    
    def __init__(self, api_key: str, api_secret: str, paper_trading: bool = True):
        """
        Initialize equity broker.
        
        Args:
            api_key: API key
            api_secret: API secret
            paper_trading: Whether to use paper trading mode
        """
        self.api_key = api_key
        self.api_secret = api_secret
        self.paper_trading = paper_trading
        self.authenticated = False
    
    @abstractmethod
    def authenticate(self) -> bool:
        """Authenticate with broker."""
        pass
    
    @abstractmethod
    def get_account_balance(self) -> float:
        """Get account balance in USD."""
        pass
    
    @abstractmethod
    def get_buying_power(self) -> float:
        """Get available buying power."""
        pass
    
    @abstractmethod
    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        limit_price: Optional[float] = None
    ) -> Dict:
        """Place an order."""
        pass
    
    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        pass
    
    @abstractmethod
    def get_positions(self) -> List[EquityPosition]:
        """Get all open positions."""
        pass
    
    @abstractmethod
    def get_position(self, symbol: str) -> Optional[EquityPosition]:
        """Get position for a specific symbol."""
        pass
    
    @abstractmethod
    def get_quote(self, symbol: str) -> Dict:
        """Get current quote for a symbol."""
        pass


class AlpacaBroker(BaseEquityBroker):
    """
    Alpaca broker integration.
    
    Alpaca is the primary equity broker for NIJA.
    - Commission-free trading
    - Good API documentation
    - Paper trading support
    - Real-time market data
    """
    
    def __init__(
        self,
        api_key: Optional[str] = None,
        api_secret: Optional[str] = None,
        paper_trading: bool = True
    ):
        """
        Initialize Alpaca broker.
        
        Args:
            api_key: Alpaca API key (or use ALPACA_API_KEY env var)
            api_secret: Alpaca API secret (or use ALPACA_API_SECRET env var)
            paper_trading: Whether to use paper trading
        """
        api_key = api_key or os.getenv('ALPACA_API_KEY')
        api_secret = api_secret or os.getenv('ALPACA_API_SECRET')
        
        super().__init__(api_key or "", api_secret or "", paper_trading)
        
        self.base_url = (
            "https://paper-api.alpaca.markets" if paper_trading
            else "https://api.alpaca.markets"
        )
        
        # Try to import alpaca-trade-api
        try:
            import alpaca_trade_api as tradeapi
            self.tradeapi = tradeapi
            self.api = None  # Will be initialized in authenticate()
        except ImportError:
            logger.warning("alpaca-trade-api not installed. Install with: pip install alpaca-trade-api")
            self.tradeapi = None
            self.api = None
    
    def authenticate(self) -> bool:
        """Authenticate with Alpaca."""
        if not self.api_key or not self.api_secret:
            logger.error("Alpaca API credentials not provided")
            return False
        
        if self.tradeapi is None:
            logger.error("alpaca-trade-api library not available")
            return False
        
        try:
            self.api = self.tradeapi.REST(
                self.api_key,
                self.api_secret,
                self.base_url,
                api_version='v2'
            )
            
            # Test authentication by getting account
            account = self.api.get_account()
            self.authenticated = True
            
            logger.info(
                f"Alpaca authenticated: paper={self.paper_trading}, "
                f"equity=${float(account.equity):.2f}"
            )
            return True
            
        except Exception as e:
            logger.error(f"Alpaca authentication failed: {e}")
            return False
    
    def get_account_balance(self) -> float:
        """Get account equity (total balance)."""
        if not self.authenticated or not self.api:
            return 0.0
        
        try:
            account = self.api.get_account()
            return float(account.equity)
        except Exception as e:
            logger.error(f"Failed to get Alpaca balance: {e}")
            return 0.0
    
    def get_buying_power(self) -> float:
        """Get available buying power."""
        if not self.authenticated or not self.api:
            return 0.0
        
        try:
            account = self.api.get_account()
            return float(account.buying_power)
        except Exception as e:
            logger.error(f"Failed to get Alpaca buying power: {e}")
            return 0.0
    
    def place_order(
        self,
        symbol: str,
        side: OrderSide,
        quantity: float,
        order_type: OrderType = OrderType.MARKET,
        limit_price: Optional[float] = None
    ) -> Dict:
        """
        Place an order on Alpaca.
        
        Args:
            symbol: Stock symbol (e.g., "AAPL", "SPY")
            side: BUY or SELL
            quantity: Number of shares
            order_type: MARKET or LIMIT
            limit_price: Limit price (required for LIMIT orders)
            
        Returns:
            Order details dictionary
        """
        if not self.authenticated or not self.api:
            return {"success": False, "error": "Not authenticated"}
        
        try:
            # Convert enums to Alpaca format
            alpaca_side = "buy" if side == OrderSide.BUY else "sell"
            alpaca_type = "market" if order_type == OrderType.MARKET else "limit"
            
            # Place order
            order = self.api.submit_order(
                symbol=symbol,
                qty=quantity,
                side=alpaca_side,
                type=alpaca_type,
                time_in_force='day',
                limit_price=limit_price
            )
            
            logger.info(f"Alpaca order placed: {symbol} {alpaca_side} {quantity} @ {alpaca_type}")
            
            return {
                "success": True,
                "order_id": order.id,
                "symbol": symbol,
                "side": side,
                "quantity": quantity,
                "status": order.status
            }
            
        except Exception as e:
            logger.error(f"Alpaca order failed: {e}")
            return {"success": False, "error": str(e)}
    
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an order."""
        if not self.authenticated or not self.api:
            return False
        
        try:
            self.api.cancel_order(order_id)
            logger.info(f"Alpaca order cancelled: {order_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to cancel Alpaca order: {e}")
            return False
    
    def get_positions(self) -> List[EquityPosition]:
        """Get all open positions."""
        if not self.authenticated or not self.api:
            return []
        
        try:
            positions = self.api.list_positions()
            
            return [
                EquityPosition(
                    symbol=pos.symbol,
                    quantity=float(pos.qty),
                    entry_price=float(pos.avg_entry_price),
                    current_price=float(pos.current_price),
                    market_value=float(pos.market_value),
                    unrealized_pnl=float(pos.unrealized_pl),
                    broker=EquityBroker.ALPACA
                )
                for pos in positions
            ]
        except Exception as e:
            logger.error(f"Failed to get Alpaca positions: {e}")
            return []
    
    def get_position(self, symbol: str) -> Optional[EquityPosition]:
        """Get position for a specific symbol."""
        positions = self.get_positions()
        for pos in positions:
            if pos.symbol == symbol:
                return pos
        return None
    
    def get_quote(self, symbol: str) -> Dict:
        """Get current quote for a symbol."""
        if not self.authenticated or not self.api:
            return {}
        
        try:
            quote = self.api.get_latest_trade(symbol)
            
            return {
                "symbol": symbol,
                "price": float(quote.price),
                "timestamp": quote.timestamp,
                "size": float(quote.size)
            }
        except Exception as e:
            logger.error(f"Failed to get Alpaca quote for {symbol}: {e}")
            return {}


class EquityBrokerManager:
    """
    Manager for equity broker connections.
    
    Similar to bot/broker_manager.py but for stocks.
    """
    
    def __init__(self):
        """Initialize equity broker manager."""
        self.brokers: Dict[EquityBroker, BaseEquityBroker] = {}
        self.active_broker: Optional[EquityBroker] = None
        
    def add_broker(self, broker_type: EquityBroker, broker: BaseEquityBroker):
        """
        Add a broker.
        
        Args:
            broker_type: Broker type
            broker: Broker instance
        """
        self.brokers[broker_type] = broker
        
        # Set as active if it's the first broker
        if self.active_broker is None:
            self.active_broker = broker_type
            
        logger.info(f"Added equity broker: {broker_type.value}")
    
    def set_active_broker(self, broker_type: EquityBroker):
        """Set active broker."""
        if broker_type in self.brokers:
            self.active_broker = broker_type
            logger.info(f"Active equity broker set to: {broker_type.value}")
        else:
            logger.error(f"Broker not found: {broker_type.value}")
    
    def get_active_broker(self) -> Optional[BaseEquityBroker]:
        """Get active broker instance."""
        if self.active_broker and self.active_broker in self.brokers:
            return self.brokers[self.active_broker]
        return None
    
    def get_total_balance(self) -> float:
        """Get total balance across all equity brokers."""
        total = 0.0
        for broker in self.brokers.values():
            total += broker.get_account_balance()
        return total
    
    def get_all_positions(self) -> List[EquityPosition]:
        """Get all positions across all brokers."""
        all_positions = []
        for broker in self.brokers.values():
            all_positions.extend(broker.get_positions())
        return all_positions


# Global equity broker manager instance
_equity_broker_manager = None


def get_equity_broker_manager() -> EquityBrokerManager:
    """Get global equity broker manager instance."""
    global _equity_broker_manager
    if _equity_broker_manager is None:
        _equity_broker_manager = EquityBrokerManager()
    return _equity_broker_manager
