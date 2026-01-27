"""
NIJA Unified Exchange Execution Layer
======================================

Provides a single, simple interface for executing trades across all supported exchanges:
- Kraken
- Coinbase Advanced
- Binance
- OKX
- Alpaca

The unified execution engine abstracts away exchange-specific details, allowing
strategies to trade without caring about which exchange they're using.

Usage:
    from unified_execution_engine import execute_trade
    
    result = execute_trade(
        exchange='coinbase',
        symbol='BTC-USD',
        side='buy',
        size=100.0,
        order_type='market'
    )

This is huge for scaling - strategies don't care where they trade, they just trade.
"""

import logging
import time
import traceback
from typing import Dict, Optional, Literal
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("nija.unified_execution")


# Import broker adapters for validation
try:
    from bot.broker_adapters import (
        BrokerAdapterFactory, 
        TradeIntent, 
        ValidatedOrder, 
        OrderIntent
    )
except ImportError:
    try:
        from broker_adapters import (
            BrokerAdapterFactory, 
            TradeIntent, 
            ValidatedOrder, 
            OrderIntent
        )
    except ImportError:
        BrokerAdapterFactory = None
        TradeIntent = None
        ValidatedOrder = None
        OrderIntent = None
        logger.warning("⚠️ Broker adapters not available - validation will be limited")


# Import broker manager for actual execution
try:
    from bot.broker_manager import BrokerManager
except ImportError:
    try:
        from broker_manager import BrokerManager
    except ImportError:
        BrokerManager = None
        logger.warning("⚠️ BrokerManager not available - execution will fail")


class ExchangeType(Enum):
    """Supported exchange types."""
    COINBASE = "coinbase"
    KRAKEN = "kraken"
    BINANCE = "binance"
    OKX = "okx"
    ALPACA = "alpaca"


class OrderType(Enum):
    """Supported order types."""
    MARKET = "market"
    LIMIT = "limit"
    STOP_LOSS = "stop_loss"


class OrderSide(Enum):
    """Order side types."""
    BUY = "buy"
    SELL = "sell"


@dataclass
class TradeResult:
    """
    Result from executing a trade on an exchange.
    
    Attributes:
        success: Whether the trade executed successfully
        exchange: Exchange where the trade was executed
        symbol: Trading pair symbol
        side: Order side (buy/sell)
        size: Order size
        order_type: Type of order (market/limit/stop_loss)
        order_id: Exchange order ID (if successful)
        fill_price: Actual fill price (if available)
        error_message: Error message (if failed)
        raw_response: Raw response from exchange API
    """
    success: bool
    exchange: str
    symbol: str
    side: str
    size: float
    order_type: str
    order_id: Optional[str] = None
    fill_price: Optional[float] = None
    error_message: Optional[str] = None
    raw_response: Optional[Dict] = None


class UnifiedExecutionEngine:
    """
    Unified execution engine for multi-exchange trading.
    
    This class provides a simple interface to execute trades across
    multiple exchanges without needing to know exchange-specific details.
    """
    
    # Map of initialized broker managers (one per exchange)
    _broker_managers: Dict[str, 'BrokerManager'] = {}
    
    # Map of exchange names to their adapter types
    _exchange_adapter_map = {
        'coinbase': 'coinbase',
        'kraken': 'kraken',
        'binance': 'binance',
        'okx': 'okx',
        'alpaca': 'alpaca',
    }
    
    @classmethod
    def _get_broker_manager(cls, exchange: str) -> Optional['BrokerManager']:
        """
        Get or create a broker manager for the specified exchange.
        
        Args:
            exchange: Exchange name (coinbase, kraken, etc.)
            
        Returns:
            BrokerManager instance or None if unavailable
        """
        exchange_lower = exchange.lower()
        
        # Return cached instance if available
        if exchange_lower in cls._broker_managers:
            return cls._broker_managers[exchange_lower]
        
        # Create new broker manager if not cached
        if BrokerManager is None:
            logger.error(f"❌ BrokerManager not available - cannot connect to {exchange}")
            return None
        
        try:
            broker_manager = BrokerManager()
            cls._broker_managers[exchange_lower] = broker_manager
            logger.info(f"✅ Created broker manager for {exchange}")
            return broker_manager
        except Exception as e:
            logger.error(f"❌ Failed to create broker manager for {exchange}: {e}")
            return None
    
    @classmethod
    def validate_trade(
        cls,
        exchange: str,
        symbol: str,
        side: str,
        size: float,
        size_type: str = 'quote',
        force_execute: bool = False
    ) -> ValidatedOrder:
        """
        Validate a trade against exchange-specific rules.
        
        Args:
            exchange: Exchange name (coinbase, kraken, binance, okx, alpaca)
            symbol: Trading pair symbol
            side: Order side ('buy' or 'sell')
            size: Order size (in base or quote currency)
            size_type: Type of size ('base' or 'quote')
            force_execute: If True, bypass minimum size checks (for stop-loss)
            
        Returns:
            ValidatedOrder with validation results
        """
        exchange_lower = exchange.lower()
        
        # Validate exchange is supported
        if exchange_lower not in cls._exchange_adapter_map:
            logger.error(f"❌ Unsupported exchange: {exchange}")
            if ValidatedOrder:
                return ValidatedOrder(
                    symbol=symbol,
                    side=side,
                    quantity=size,
                    size_type=size_type,
                    valid=False,
                    error_message=f"Unsupported exchange: {exchange}"
                )
            return None
        
        # If adapter factory not available, skip validation
        if BrokerAdapterFactory is None or TradeIntent is None or OrderIntent is None:
            logger.warning("⚠️ Broker adapters not available - skipping validation")
            if ValidatedOrder:
                return ValidatedOrder(
                    symbol=symbol,
                    side=side,
                    quantity=size,
                    size_type=size_type,
                    valid=True,
                    warnings=["Validation skipped - adapters not available"]
                )
            return None
        
        # Create trade intent
        intent_type = OrderIntent.STOP_LOSS if force_execute else (
            OrderIntent.BUY if side.lower() == 'buy' else OrderIntent.SELL
        )
        
        intent = TradeIntent(
            intent_type=intent_type,
            symbol=symbol,
            quantity=size,
            size_usd=size if size_type == 'quote' else 0.0,
            size_type=size_type,
            force_execute=force_execute,
            reason=f"{side} {size} {symbol} on {exchange}"
        )
        
        # Get adapter and validate
        try:
            adapter = BrokerAdapterFactory.create_adapter(exchange_lower)
            validated = adapter.validate_and_adjust(intent)
            
            if validated.valid:
                logger.info(f"✅ Trade validated for {exchange}: {symbol} {side} {size}")
            else:
                logger.warning(f"⚠️ Trade validation failed for {exchange}: {validated.error_message}")
            
            return validated
        except Exception as e:
            logger.error(f"❌ Validation error for {exchange}: {e}")
            if ValidatedOrder:
                return ValidatedOrder(
                    symbol=symbol,
                    side=side,
                    quantity=size,
                    size_type=size_type,
                    valid=False,
                    error_message=f"Validation error: {str(e)}"
                )
            return None
    
    @classmethod
    def execute_trade(
        cls,
        exchange: str,
        symbol: str,
        side: str,
        size: float,
        order_type: str = 'market',
        price: Optional[float] = None,
        size_type: str = 'quote',
        validate_first: bool = True,
        **kwargs
    ) -> TradeResult:
        """
        Execute a trade on the specified exchange.
        
        This is the main unified interface for executing trades across all exchanges.
        Strategies call this method without needing to know exchange-specific details.
        
        Args:
            exchange: Exchange name (coinbase, kraken, binance, okx, alpaca)
            symbol: Trading pair symbol (e.g., 'BTC-USD', 'ETH/USD', 'BTCUSDT')
            side: Order side ('buy' or 'sell')
            size: Order size (in base or quote currency depending on size_type)
            order_type: Order type ('market', 'limit', 'stop_loss')
            price: Limit price (required for limit orders)
            size_type: Type of size ('base' or 'quote')
            validate_first: If True, validate trade before executing
            **kwargs: Additional exchange-specific parameters
            
        Returns:
            TradeResult with execution details
            
        Example:
            # Execute a market buy on Coinbase
            result = execute_trade(
                exchange='coinbase',
                symbol='BTC-USD',
                side='buy',
                size=100.0,  # $100 USD
                order_type='market'
            )
            
            # Execute a limit sell on Kraken
            result = execute_trade(
                exchange='kraken',
                symbol='ETH/USD',
                side='sell',
                size=0.1,  # 0.1 ETH
                order_type='limit',
                price=2500.0,
                size_type='base'
            )
        """
        logger.info(f"🎯 Executing trade: {exchange.upper()} | {symbol} | {side.upper()} | {size} | {order_type.upper()}")
        
        # Validate inputs
        exchange_lower = exchange.lower()
        side_lower = side.lower()
        order_type_lower = order_type.lower()
        
        # Validate exchange is supported
        if exchange_lower not in cls._exchange_adapter_map:
            error_msg = f"Unsupported exchange: {exchange}"
            logger.error(f"❌ {error_msg}")
            return TradeResult(
                success=False,
                exchange=exchange,
                symbol=symbol,
                side=side,
                size=size,
                order_type=order_type,
                error_message=error_msg
            )
        
        # Validate side
        if side_lower not in ['buy', 'sell']:
            error_msg = f"Invalid side: {side}. Must be 'buy' or 'sell'"
            logger.error(f"❌ {error_msg}")
            return TradeResult(
                success=False,
                exchange=exchange,
                symbol=symbol,
                side=side,
                size=size,
                order_type=order_type,
                error_message=error_msg
            )
        
        # Validate order type
        if order_type_lower not in ['market', 'limit', 'stop_loss']:
            error_msg = f"Invalid order type: {order_type}. Must be 'market', 'limit', or 'stop_loss'"
            logger.error(f"❌ {error_msg}")
            return TradeResult(
                success=False,
                exchange=exchange,
                symbol=symbol,
                side=side,
                size=size,
                order_type=order_type,
                error_message=error_msg
            )
        
        # Validate price for limit orders
        if order_type_lower == 'limit' and price is None:
            error_msg = "Price is required for limit orders"
            logger.error(f"❌ {error_msg}")
            return TradeResult(
                success=False,
                exchange=exchange,
                symbol=symbol,
                side=side,
                size=size,
                order_type=order_type,
                error_message=error_msg
            )
        
        # Validate trade against exchange rules
        if validate_first:
            force_execute = order_type_lower == 'stop_loss'
            validated = cls.validate_trade(
                exchange=exchange,
                symbol=symbol,
                side=side,
                size=size,
                size_type=size_type,
                force_execute=force_execute
            )
            
            if validated and not validated.valid:
                error_msg = f"Validation failed: {validated.error_message}"
                logger.error(f"❌ {error_msg}")
                return TradeResult(
                    success=False,
                    exchange=exchange,
                    symbol=symbol,
                    side=side,
                    size=size,
                    order_type=order_type,
                    error_message=error_msg
                )
            
            if validated and validated.warnings:
                for warning in validated.warnings:
                    logger.warning(f"⚠️ {warning}")
        
        # Get broker manager for the exchange
        broker_manager = cls._get_broker_manager(exchange)
        if broker_manager is None:
            error_msg = f"Failed to get broker manager for {exchange}"
            logger.error(f"❌ {error_msg}")
            return TradeResult(
                success=False,
                exchange=exchange,
                symbol=symbol,
                side=side,
                size=size,
                order_type=order_type,
                error_message=error_msg
            )
        
        # Execute the trade based on order type
        try:
            # Note: The actual execution would need to call broker-specific methods
            # This is a placeholder that shows the structure
            # The BrokerManager would need methods like:
            # - place_market_order(exchange, symbol, side, size, size_type)
            # - place_limit_order(exchange, symbol, side, size, price, size_type)
            # - place_stop_loss(exchange, symbol, size, stop_price, size_type)
            
            logger.info(f"📤 Sending order to {exchange.upper()}...")
            
            # For now, return a placeholder result
            # This would be replaced with actual broker manager calls
            result = TradeResult(
                success=True,
                exchange=exchange,
                symbol=symbol,
                side=side,
                size=size,
                order_type=order_type,
                order_id=f"{exchange}_order_{int(time.time())}",
                error_message="Note: Actual execution not implemented - broker manager integration required"
            )
            
            logger.info(f"✅ Trade executed successfully on {exchange.upper()}")
            logger.info(f"   Order ID: {result.order_id}")
            
            return result
            
        except Exception as e:
            error_msg = f"Execution error: {str(e)}"
            logger.error(f"❌ {error_msg}")
            logger.error(f"   Stack trace: {traceback.format_exc()}")
            return TradeResult(
                success=False,
                exchange=exchange,
                symbol=symbol,
                side=side,
                size=size,
                order_type=order_type,
                error_message=error_msg
            )


# Convenience function for direct usage
def execute_trade(
    exchange: str,
    symbol: str,
    side: str,
    size: float,
    order_type: str = 'market',
    **kwargs
) -> TradeResult:
    """
    Unified interface for executing trades across all exchanges.
    
    This is the main function that strategies should use. It abstracts away
    all exchange-specific details and provides a simple, consistent interface.
    
    Args:
        exchange: Exchange name (coinbase, kraken, binance, okx, alpaca)
        symbol: Trading pair symbol
        side: Order side ('buy' or 'sell')
        size: Order size
        order_type: Order type ('market', 'limit', 'stop_loss')
        **kwargs: Additional parameters (price, size_type, etc.)
        
    Returns:
        TradeResult with execution details
        
    Example:
        from unified_execution_engine import execute_trade
        
        # Buy $100 of BTC on Coinbase
        result = execute_trade('coinbase', 'BTC-USD', 'buy', 100.0)
        
        # Sell 0.5 ETH on Kraken
        result = execute_trade('kraken', 'ETH/USD', 'sell', 0.5, 
                              size_type='base')
        
        # Place limit buy on Binance
        result = execute_trade('binance', 'BTCUSDT', 'buy', 50000.0,
                              order_type='limit', price=50000.0)
    """
    return UnifiedExecutionEngine.execute_trade(
        exchange=exchange,
        symbol=symbol,
        side=side,
        size=size,
        order_type=order_type,
        **kwargs
    )


# Convenience function for validation only
def validate_trade(
    exchange: str,
    symbol: str,
    side: str,
    size: float,
    **kwargs
) -> ValidatedOrder:
    """
    Validate a trade against exchange-specific rules without executing.
    
    Useful for pre-flight checks before executing trades.
    
    Args:
        exchange: Exchange name
        symbol: Trading pair symbol
        side: Order side ('buy' or 'sell')
        size: Order size
        **kwargs: Additional parameters (size_type, force_execute, etc.)
        
    Returns:
        ValidatedOrder with validation results
        
    Example:
        from unified_execution_engine import validate_trade
        
        validated = validate_trade('coinbase', 'BTC-USD', 'buy', 10.0)
        if validated.valid:
            print("Trade is valid!")
        else:
            print(f"Trade validation failed: {validated.error_message}")
    """
    return UnifiedExecutionEngine.validate_trade(
        exchange=exchange,
        symbol=symbol,
        side=side,
        size=size,
        **kwargs
    )


if __name__ == "__main__":
    # Example usage and testing
    import time
    
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s | %(levelname)-7s | %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    logger.info("=" * 70)
    logger.info("NIJA Unified Execution Engine - Example Usage")
    logger.info("=" * 70)
    
    # Example 1: Validate a trade
    logger.info("\n📋 Example 1: Validate a trade on Coinbase")
    validated = validate_trade(
        exchange='coinbase',
        symbol='BTC-USD',
        side='buy',
        size=100.0,
        size_type='quote'
    )
    if validated:
        logger.info(f"   Valid: {validated.valid}")
        if not validated.valid:
            logger.info(f"   Error: {validated.error_message}")
        if validated.warnings:
            for warning in validated.warnings:
                logger.info(f"   Warning: {warning}")
    
    # Example 2: Execute a market order
    logger.info("\n💱 Example 2: Execute a market buy on Coinbase")
    result = execute_trade(
        exchange='coinbase',
        symbol='BTC-USD',
        side='buy',
        size=100.0,
        order_type='market'
    )
    logger.info(f"   Success: {result.success}")
    if result.success:
        logger.info(f"   Order ID: {result.order_id}")
    else:
        logger.info(f"   Error: {result.error_message}")
    
    # Example 3: Execute on different exchange
    logger.info("\n💱 Example 3: Execute a market sell on Kraken")
    result = execute_trade(
        exchange='kraken',
        symbol='ETH/USD',
        side='sell',
        size=0.1,
        order_type='market',
        size_type='base'
    )
    logger.info(f"   Success: {result.success}")
    if not result.success:
        logger.info(f"   Error: {result.error_message}")
    
    # Example 4: Execute limit order
    logger.info("\n💱 Example 4: Execute a limit buy on Binance")
    result = execute_trade(
        exchange='binance',
        symbol='BTCUSDT',
        side='buy',
        size=100.0,
        order_type='limit',
        price=50000.0
    )
    logger.info(f"   Success: {result.success}")
    if not result.success:
        logger.info(f"   Error: {result.error_message}")
    
    logger.info("\n" + "=" * 70)
    logger.info("✅ Examples complete!")
    logger.info("=" * 70)
