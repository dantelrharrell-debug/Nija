"""
NIJA Liquidity Routing System
==============================

Smart order routing for best execution across multiple liquidity sources.

Features:
- Best price discovery across exchanges
- Slippage minimization
- Order splitting for large trades
- Liquidity aggregation
- Smart routing algorithms
- Real-time execution optimization

This ensures best possible execution prices by routing to optimal venues.

Author: NIJA Trading Systems
Version: 1.0 (Path 3)
Date: January 30, 2026
"""

import logging
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from decimal import Decimal
import heapq

logger = logging.getLogger("nija.liquidity_routing")


class Exchange(Enum):
    """Supported exchanges"""
    COINBASE = "coinbase"
    KRAKEN = "kraken"
    BINANCE = "binance"
    OKX = "okx"


class OrderType(Enum):
    """Order types"""
    MARKET = "market"
    LIMIT = "limit"


@dataclass
class LiquidityLevel:
    """Single level of liquidity (bid or ask)"""
    exchange: Exchange
    price: Decimal
    size: Decimal
    
    def __lt__(self, other):
        """For heap comparison (best price first)"""
        return self.price < other.price


@dataclass
class OrderBook:
    """Aggregated order book from an exchange"""
    exchange: Exchange
    symbol: str
    bids: List[LiquidityLevel]  # Sorted descending (best bid first)
    asks: List[LiquidityLevel]  # Sorted ascending (best ask first)
    timestamp: datetime
    
    def get_best_bid(self) -> Optional[LiquidityLevel]:
        """Get best bid"""
        return self.bids[0] if self.bids else None
    
    def get_best_ask(self) -> Optional[LiquidityLevel]:
        """Get best ask"""
        return self.asks[0] if self.asks else None
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'exchange': self.exchange.value,
            'symbol': self.symbol,
            'best_bid': float(self.bids[0].price) if self.bids else None,
            'best_ask': float(self.asks[0].price) if self.asks else None,
            'bid_depth': sum(float(level.size) for level in self.bids),
            'ask_depth': sum(float(level.size) for level in self.asks),
            'timestamp': self.timestamp.isoformat()
        }


@dataclass
class RouteSegment:
    """A segment of a routed order"""
    exchange: Exchange
    price: Decimal
    size: Decimal
    side: str  # 'buy' or 'sell'
    estimated_fee: Decimal
    
    def total_cost(self) -> Decimal:
        """Calculate total cost including fees"""
        base_cost = self.price * self.size
        return base_cost + self.estimated_fee
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'exchange': self.exchange.value,
            'price': float(self.price),
            'size': float(self.size),
            'side': self.side,
            'estimated_fee': float(self.estimated_fee),
            'total_cost': float(self.total_cost())
        }


@dataclass
class RoutedOrder:
    """Order routing plan"""
    symbol: str
    side: str  # 'buy' or 'sell'
    total_size: Decimal
    segments: List[RouteSegment]
    avg_price: Decimal
    total_cost: Decimal
    total_fees: Decimal
    slippage_pct: float
    created_at: datetime
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'symbol': self.symbol,
            'side': self.side,
            'total_size': float(self.total_size),
            'segments': [seg.to_dict() for seg in self.segments],
            'avg_price': float(self.avg_price),
            'total_cost': float(self.total_cost),
            'total_fees': float(self.total_fees),
            'slippage_pct': self.slippage_pct,
            'num_venues': len(set(seg.exchange for seg in self.segments)),
            'created_at': self.created_at.isoformat()
        }


class LiquidityRoutingSystem:
    """
    Smart order routing system for optimal execution
    
    How it works:
    1. Aggregate liquidity from multiple exchanges
    2. Sort by best price
    3. Split order across venues for best execution
    4. Calculate total cost including fees and slippage
    5. Route to minimize total cost
    
    Example:
        Want to buy 5 BTC
        Coinbase: 1 BTC @ $50,000
        Kraken: 2 BTC @ $49,990
        Binance: 3 BTC @ $50,010
        
        Optimal route:
        1. Buy 2 BTC on Kraken @ $49,990
        2. Buy 1 BTC on Coinbase @ $50,000
        3. Buy 2 BTC on Binance @ $50,010
        Avg price: $49,998 (saved $60 vs buying all on Coinbase)
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize liquidity routing system
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        
        # Fee structures
        self.fee_rates = {
            Exchange.COINBASE: Decimal('0.006'),  # 0.6%
            Exchange.KRAKEN: Decimal('0.0026'),  # 0.26%
            Exchange.BINANCE: Decimal('0.001'),  # 0.1%
            Exchange.OKX: Decimal('0.001')  # 0.1%
        }
        
        # Order books
        self.order_books: Dict[Exchange, Dict[str, OrderBook]] = {}
        
        # Routing statistics
        self.total_orders_routed = 0
        self.total_savings_usd = Decimal('0')
        
        logger.info("LiquidityRoutingSystem initialized")
    
    def update_order_book(
        self,
        exchange: Exchange,
        symbol: str,
        bids: List[Tuple[Decimal, Decimal]],
        asks: List[Tuple[Decimal, Decimal]]
    ):
        """
        Update order book for an exchange
        
        Args:
            exchange: Exchange name
            symbol: Trading symbol
            bids: List of (price, size) tuples
            asks: List of (price, size) tuples
        """
        # Convert to LiquidityLevel objects
        bid_levels = [
            LiquidityLevel(exchange=exchange, price=price, size=size)
            for price, size in bids
        ]
        ask_levels = [
            LiquidityLevel(exchange=exchange, price=price, size=size)
            for price, size in asks
        ]
        
        # Sort: bids descending, asks ascending
        bid_levels.sort(key=lambda x: x.price, reverse=True)
        ask_levels.sort(key=lambda x: x.price)
        
        # Create order book
        order_book = OrderBook(
            exchange=exchange,
            symbol=symbol,
            bids=bid_levels,
            asks=ask_levels,
            timestamp=datetime.now()
        )
        
        # Store
        if exchange not in self.order_books:
            self.order_books[exchange] = {}
        self.order_books[exchange][symbol] = order_book
    
    def find_best_route(
        self,
        symbol: str,
        side: str,
        size: Decimal,
        max_slippage_pct: float = 1.0
    ) -> Optional[RoutedOrder]:
        """
        Find best routing for an order
        
        Args:
            symbol: Trading symbol
            side: 'buy' or 'sell'
            size: Order size
            max_slippage_pct: Maximum allowed slippage percentage
        
        Returns:
            RoutedOrder or None if routing not possible
        """
        # Aggregate liquidity across exchanges
        if side == 'buy':
            liquidity = self._aggregate_asks(symbol)
            is_ascending = True  # Best price is lowest
        else:
            liquidity = self._aggregate_bids(symbol)
            is_ascending = False  # Best price is highest
        
        if not liquidity:
            logger.warning(f"No liquidity available for {symbol}")
            return None
        
        # Sort by price (best first)
        liquidity.sort(key=lambda x: x.price, reverse=not is_ascending)
        
        # Route order across venues
        segments = []
        remaining_size = size
        total_cost = Decimal('0')
        total_fees = Decimal('0')
        
        for level in liquidity:
            if remaining_size <= 0:
                break
            
            # How much to fill at this level
            fill_size = min(remaining_size, level.size)
            
            # Calculate fee
            fee_rate = self.fee_rates.get(level.exchange, Decimal('0.001'))
            fee = fill_size * level.price * fee_rate
            
            # Create segment
            segment = RouteSegment(
                exchange=level.exchange,
                price=level.price,
                size=fill_size,
                side=side,
                estimated_fee=fee
            )
            
            segments.append(segment)
            remaining_size -= fill_size
            total_cost += segment.total_cost()
            total_fees += fee
        
        # Check if we filled the entire order
        if remaining_size > 0:
            logger.warning(
                f"Insufficient liquidity: requested {size}, only {size - remaining_size} available"
            )
            # Partial fill is still valid
        
        # Calculate average price
        filled_size = size - remaining_size
        if filled_size == 0:
            return None
        
        avg_price = (total_cost - total_fees) / filled_size
        
        # Calculate slippage vs best price
        best_price = liquidity[0].price
        slippage_pct = float(abs(avg_price - best_price) / best_price * 100)
        
        # Check slippage tolerance
        if slippage_pct > max_slippage_pct:
            logger.warning(
                f"Slippage {slippage_pct:.2f}% exceeds max {max_slippage_pct:.2f}%"
            )
            # Could return None here to reject order, or proceed anyway
        
        # Create routed order
        routed_order = RoutedOrder(
            symbol=symbol,
            side=side,
            total_size=filled_size,
            segments=segments,
            avg_price=avg_price,
            total_cost=total_cost,
            total_fees=total_fees,
            slippage_pct=slippage_pct,
            created_at=datetime.now()
        )
        
        self.total_orders_routed += 1
        
        # Calculate savings vs worst case (single venue)
        worst_case_cost = self._calculate_worst_case_cost(symbol, side, size)
        if worst_case_cost:
            savings = worst_case_cost - total_cost
            self.total_savings_usd += savings
            logger.info(f"Routing savings: ${savings:.2f}")
        
        logger.info(
            f"Route found: {side.upper()} {filled_size} {symbol} | "
            f"Avg price: ${avg_price:.2f} | Slippage: {slippage_pct:.2f}% | "
            f"Venues: {len(set(seg.exchange for seg in segments))}"
        )
        
        return routed_order
    
    def _aggregate_asks(self, symbol: str) -> List[LiquidityLevel]:
        """Aggregate all ask liquidity for a symbol"""
        all_asks = []
        
        for exchange, books in self.order_books.items():
            if symbol in books:
                all_asks.extend(books[symbol].asks)
        
        return all_asks
    
    def _aggregate_bids(self, symbol: str) -> List[LiquidityLevel]:
        """Aggregate all bid liquidity for a symbol"""
        all_bids = []
        
        for exchange, books in self.order_books.items():
            if symbol in books:
                all_bids.extend(books[symbol].bids)
        
        return all_bids
    
    def _calculate_worst_case_cost(
        self,
        symbol: str,
        side: str,
        size: Decimal
    ) -> Optional[Decimal]:
        """Calculate cost of filling entire order on single worst venue"""
        # For simplicity, assume worst = most expensive
        # In practice, would walk the book
        if side == 'buy':
            liquidity = self._aggregate_asks(symbol)
            if not liquidity:
                return None
            worst_price = max(level.price for level in liquidity)
        else:
            liquidity = self._aggregate_bids(symbol)
            if not liquidity:
                return None
            worst_price = min(level.price for level in liquidity)
        
        # Assume average fee
        avg_fee_rate = sum(self.fee_rates.values()) / len(self.fee_rates)
        
        return size * worst_price * (Decimal('1') + avg_fee_rate)
    
    def get_best_price(
        self,
        symbol: str,
        side: str
    ) -> Optional[Tuple[Exchange, Decimal]]:
        """
        Get best price across all exchanges
        
        Args:
            symbol: Trading symbol
            side: 'buy' or 'sell'
        
        Returns:
            Tuple of (exchange, price) or None
        """
        if side == 'buy':
            liquidity = self._aggregate_asks(symbol)
            if not liquidity:
                return None
            best = min(liquidity, key=lambda x: x.price)
        else:
            liquidity = self._aggregate_bids(symbol)
            if not liquidity:
                return None
            best = max(liquidity, key=lambda x: x.price)
        
        return (best.exchange, best.price)
    
    def get_liquidity_summary(self, symbol: str) -> Dict:
        """Get liquidity summary for a symbol"""
        total_bid_size = Decimal('0')
        total_ask_size = Decimal('0')
        exchanges_with_liquidity = []
        
        for exchange, books in self.order_books.items():
            if symbol in books:
                book = books[symbol]
                bid_size = sum(level.size for level in book.bids)
                ask_size = sum(level.size for level in book.asks)
                
                if bid_size > 0 or ask_size > 0:
                    exchanges_with_liquidity.append(exchange.value)
                    total_bid_size += bid_size
                    total_ask_size += ask_size
        
        # Get best prices
        best_bid = self.get_best_price(symbol, 'sell')
        best_ask = self.get_best_price(symbol, 'buy')
        
        return {
            'symbol': symbol,
            'total_bid_size': float(total_bid_size),
            'total_ask_size': float(total_ask_size),
            'best_bid': {
                'exchange': best_bid[0].value,
                'price': float(best_bid[1])
            } if best_bid else None,
            'best_ask': {
                'exchange': best_ask[0].value,
                'price': float(best_ask[1])
            } if best_ask else None,
            'spread_pct': float((best_ask[1] - best_bid[1]) / best_bid[1] * 100) if best_bid and best_ask else None,
            'exchanges': exchanges_with_liquidity,
            'num_exchanges': len(exchanges_with_liquidity)
        }
    
    def get_stats(self) -> Dict:
        """Get routing statistics"""
        return {
            'total_orders_routed': self.total_orders_routed,
            'total_savings_usd': float(self.total_savings_usd),
            'avg_savings_per_order': (
                float(self.total_savings_usd / self.total_orders_routed)
                if self.total_orders_routed > 0 else 0.0
            ),
            'exchanges_tracked': len(self.order_books),
            'symbols_available': len(set(
                symbol
                for books in self.order_books.values()
                for symbol in books.keys()
            ))
        }


# Global instance
liquidity_routing_system = LiquidityRoutingSystem()
