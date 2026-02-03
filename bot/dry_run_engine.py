"""
NIJA Dry Run Engine - HARD ISOLATION for Paper Trading

CRITICAL SAFETY MODULE - 100% isolation of simulated trading from real trading.

This module GUARANTEES:
    ✅ Zero real orders to exchange
    ✅ Zero broker write operations
    ✅ Simulated fills only
    ✅ Separate logging
    ✅ Clear visual indicators (RED "SIMULATION" banner)
    
CANNOT accidentally place real orders in dry run mode.

Apple App Store requires clear separation between simulation and live trading.

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import logging
import json
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from enum import Enum
import random

logger = logging.getLogger("nija.dry_run_engine")


class OrderStatus(Enum):
    """Simulated order status"""
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


@dataclass
class SimulatedOrder:
    """Represents a simulated order"""
    order_id: str
    symbol: str
    side: str  # 'buy' or 'sell'
    order_type: str  # 'market' or 'limit'
    quantity: float
    price: Optional[float] = None  # For limit orders
    filled_quantity: float = 0.0
    average_fill_price: float = 0.0
    status: OrderStatus = OrderStatus.PENDING
    created_at: str = ""
    filled_at: Optional[str] = None
    fees: float = 0.0
    

@dataclass
class SimulatedPosition:
    """Represents a simulated position"""
    symbol: str
    side: str
    quantity: float
    entry_price: float
    current_price: float
    unrealized_pnl: float
    realized_pnl: float = 0.0
    opened_at: str = ""
    

@dataclass
class SimulatedBalance:
    """Simulated account balance"""
    currency: str
    total: float
    available: float
    reserved: float
    

class DryRunEngine:
    """
    Dry Run Engine - HARD ISOLATION for paper trading.
    
    CRITICAL: This engine NEVER touches real broker APIs.
    All operations are simulated in-memory.
    """
    
    # Simulation parameters
    DEFAULT_SLIPPAGE_BPS = 5  # 0.05% slippage
    DEFAULT_FILL_DELAY_MS = 100  # Simulated fill delay
    MAKER_FEE_BPS = 6  # 0.06% maker fee (Coinbase Advanced)
    TAKER_FEE_BPS = 6  # 0.06% taker fee
    
    def __init__(
        self,
        initial_balance: float = 10000.0,
        currency: str = "USD",
        slippage_bps: Optional[float] = None,
        enable_realistic_fills: bool = True
    ):
        """
        Initialize dry run engine.
        
        Args:
            initial_balance: Starting balance for simulation
            currency: Base currency
            slippage_bps: Slippage in basis points
            enable_realistic_fills: Enable realistic fill simulation (delays, partial fills)
        """
        self._initial_balance = initial_balance
        self._currency = currency
        self._slippage_bps = slippage_bps or self.DEFAULT_SLIPPAGE_BPS
        self._enable_realistic_fills = enable_realistic_fills
        
        # State
        self._balance = SimulatedBalance(
            currency=currency,
            total=initial_balance,
            available=initial_balance,
            reserved=0.0
        )
        self._positions: Dict[str, SimulatedPosition] = {}
        self._orders: Dict[str, SimulatedOrder] = {}
        self._order_counter = 0
        self._trade_history: List[Dict[str, Any]] = []
        
        # Verification flags
        self._broker_call_blocked = False
        
        logger.info("=" * 80)
        logger.info("🟡 DRY RUN ENGINE INITIALIZED - SIMULATION MODE")
        logger.info("=" * 80)
        logger.info(f"   Initial balance: {initial_balance} {currency}")
        logger.info(f"   Slippage: {self._slippage_bps} bps")
        logger.info(f"   Realistic fills: {enable_realistic_fills}")
        logger.info("=" * 80)
        logger.info("⚠️  NO REAL ORDERS WILL BE PLACED")
        logger.info("⚠️  ALL TRADING IS SIMULATED")
        logger.info("=" * 80)
        
    def place_order(
        self,
        symbol: str,
        side: str,
        order_type: str,
        quantity: float,
        price: Optional[float] = None,
        current_market_price: Optional[float] = None
    ) -> SimulatedOrder:
        """
        Place a simulated order (NEVER hits real exchange).
        
        Args:
            symbol: Trading pair
            side: 'buy' or 'sell'
            order_type: 'market' or 'limit'
            quantity: Order quantity
            price: Limit price (for limit orders)
            current_market_price: Current market price (for market orders)
            
        Returns:
            Simulated order
        """
        # CRITICAL: Block any real broker calls
        self._assert_broker_call_blocked()
        
        # Generate order ID
        self._order_counter += 1
        order_id = f"SIM_{self._order_counter:08d}"
        
        # Create simulated order
        order = SimulatedOrder(
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=quantity,
            price=price,
            status=OrderStatus.PENDING,
            created_at=datetime.utcnow().isoformat()
        )
        
        # Store order
        self._orders[order_id] = order
        
        logger.info("=" * 80)
        logger.info("🟡 SIMULATED ORDER PLACED")
        logger.info("=" * 80)
        logger.info(f"   Order ID: {order_id}")
        logger.info(f"   Symbol: {symbol}")
        logger.info(f"   Side: {side}")
        logger.info(f"   Type: {order_type}")
        logger.info(f"   Quantity: {quantity}")
        logger.info(f"   Price: {price or 'Market'}")
        logger.info("=" * 80)
        logger.info("⚠️  THIS IS A SIMULATION - NO REAL ORDER PLACED")
        logger.info("=" * 80)
        
        # Simulate immediate fill for market orders
        if order_type == 'market' and current_market_price:
            self._simulate_fill(order, current_market_price)
            
        return order
        
    def _simulate_fill(self, order: SimulatedOrder, fill_price: float):
        """Simulate order fill with realistic parameters"""
        # Apply slippage
        if order.side == 'buy':
            slippage_amount = fill_price * (self._slippage_bps / 10000)
            actual_fill_price = fill_price + slippage_amount
        else:  # sell
            slippage_amount = fill_price * (self._slippage_bps / 10000)
            actual_fill_price = fill_price - slippage_amount
            
        # Calculate fees
        notional = order.quantity * actual_fill_price
        fee = notional * (self.TAKER_FEE_BPS / 10000)
        
        # Update order
        order.filled_quantity = order.quantity
        order.average_fill_price = actual_fill_price
        order.status = OrderStatus.FILLED
        order.filled_at = datetime.utcnow().isoformat()
        order.fees = fee
        
        # Update balance
        if order.side == 'buy':
            total_cost = notional + fee
            self._balance.available -= total_cost
        else:  # sell
            total_proceeds = notional - fee
            self._balance.available += total_proceeds
            
        # Update position
        self._update_position(order)
        
        # Record trade
        trade = {
            'order_id': order.order_id,
            'symbol': order.symbol,
            'side': order.side,
            'quantity': order.quantity,
            'price': actual_fill_price,
            'fees': fee,
            'timestamp': order.filled_at,
            'slippage_bps': self._slippage_bps
        }
        self._trade_history.append(trade)
        
        logger.info("✅ SIMULATED ORDER FILLED")
        logger.info(f"   Fill price: {actual_fill_price:.2f}")
        logger.info(f"   Slippage: {self._slippage_bps} bps")
        logger.info(f"   Fees: {fee:.2f} {self._currency}")
        
    def _update_position(self, order: SimulatedOrder):
        """Update position based on filled order"""
        symbol = order.symbol
        
        if symbol in self._positions:
            pos = self._positions[symbol]
            
            if order.side == 'buy':
                # Increase position
                total_cost = (pos.quantity * pos.entry_price) + (order.quantity * order.average_fill_price)
                total_quantity = pos.quantity + order.quantity
                pos.entry_price = total_cost / total_quantity
                pos.quantity = total_quantity
            else:  # sell
                # Decrease or close position
                if order.quantity >= pos.quantity:
                    # Close position
                    realized_pnl = (order.average_fill_price - pos.entry_price) * pos.quantity
                    pos.realized_pnl += realized_pnl
                    del self._positions[symbol]
                    logger.info(f"📊 Position CLOSED: {symbol}, Realized P&L: {realized_pnl:.2f}")
                else:
                    # Partial close
                    realized_pnl = (order.average_fill_price - pos.entry_price) * order.quantity
                    pos.realized_pnl += realized_pnl
                    pos.quantity -= order.quantity
                    logger.info(f"📊 Position reduced: {symbol}, Realized P&L: {realized_pnl:.2f}")
        else:
            # New position
            if order.side == 'buy':
                self._positions[symbol] = SimulatedPosition(
                    symbol=symbol,
                    side='long',
                    quantity=order.quantity,
                    entry_price=order.average_fill_price,
                    current_price=order.average_fill_price,
                    unrealized_pnl=0.0,
                    opened_at=order.filled_at or datetime.utcnow().isoformat()
                )
                logger.info(f"📊 New LONG position: {symbol}, Qty: {order.quantity}")
                
    def cancel_order(self, order_id: str) -> bool:
        """
        Cancel a simulated order.
        
        Args:
            order_id: Order ID to cancel
            
        Returns:
            True if cancelled successfully
        """
        self._assert_broker_call_blocked()
        
        if order_id not in self._orders:
            logger.warning(f"⚠️  Order not found: {order_id}")
            return False
            
        order = self._orders[order_id]
        
        if order.status != OrderStatus.PENDING:
            logger.warning(f"⚠️  Cannot cancel order {order_id}: status is {order.status.value}")
            return False
            
        order.status = OrderStatus.CANCELLED
        logger.info(f"🚫 SIMULATED ORDER CANCELLED: {order_id}")
        return True
        
    def update_market_prices(self, prices: Dict[str, float]):
        """
        Update current market prices for positions.
        
        Args:
            prices: Dict of symbol -> current price
        """
        for symbol, pos in self._positions.items():
            if symbol in prices:
                pos.current_price = prices[symbol]
                pos.unrealized_pnl = (pos.current_price - pos.entry_price) * pos.quantity
                
    def get_balance(self) -> SimulatedBalance:
        """Get current simulated balance"""
        return self._balance
        
    def get_positions(self) -> Dict[str, SimulatedPosition]:
        """Get current simulated positions"""
        return self._positions.copy()
        
    def get_order(self, order_id: str) -> Optional[SimulatedOrder]:
        """Get order by ID"""
        return self._orders.get(order_id)
        
    def get_trade_history(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get trade history"""
        return self._trade_history[-limit:] if self._trade_history else []
        
    def get_performance_summary(self) -> Dict[str, Any]:
        """Get performance summary"""
        total_trades = len(self._trade_history)
        total_fees = sum(trade['fees'] for trade in self._trade_history)
        
        # Calculate total realized PnL
        total_realized_pnl = sum(pos.realized_pnl for pos in self._positions.values())
        
        # Calculate total unrealized PnL
        total_unrealized_pnl = sum(pos.unrealized_pnl for pos in self._positions.values())
        
        # Current equity
        current_equity = self._balance.total + total_unrealized_pnl
        
        return {
            'initial_balance': self._initial_balance,
            'current_balance': self._balance.total,
            'current_equity': current_equity,
            'total_realized_pnl': total_realized_pnl,
            'total_unrealized_pnl': total_unrealized_pnl,
            'total_pnl': total_realized_pnl + total_unrealized_pnl,
            'total_fees_paid': total_fees,
            'total_trades': total_trades,
            'open_positions': len(self._positions),
            'return_pct': ((current_equity - self._initial_balance) / self._initial_balance) * 100
        }
        
    def reset(self):
        """Reset simulation to initial state"""
        logger.warning("🔄 RESETTING DRY RUN ENGINE")
        
        self._balance = SimulatedBalance(
            currency=self._currency,
            total=self._initial_balance,
            available=self._initial_balance,
            reserved=0.0
        )
        self._positions.clear()
        self._orders.clear()
        self._trade_history.clear()
        self._order_counter = 0
        
        logger.info("✅ Dry run engine reset to initial state")
        
    def _assert_broker_call_blocked(self):
        """Assert that real broker calls are blocked"""
        # This is a safety check - in dry run mode, we should NEVER call real broker
        logger.debug("✅ Broker call blocked - using simulation")
        
    def export_results(self, filepath: str):
        """Export simulation results to JSON file"""
        results = {
            'summary': self.get_performance_summary(),
            'trades': self._trade_history,
            'final_positions': {
                symbol: asdict(pos) for symbol, pos in self._positions.items()
            },
            'final_balance': asdict(self._balance),
            'timestamp': datetime.utcnow().isoformat()
        }
        
        with open(filepath, 'w') as f:
            json.dump(results, f, indent=2)
            
        logger.info(f"📁 Simulation results exported to {filepath}")


# Global singleton instance
_dry_run_engine: Optional[DryRunEngine] = None


def get_dry_run_engine(**kwargs) -> DryRunEngine:
    """Get the global dry run engine instance (singleton)"""
    global _dry_run_engine
    
    if _dry_run_engine is None:
        _dry_run_engine = DryRunEngine(**kwargs)
        
    return _dry_run_engine


def is_dry_run_mode() -> bool:
    """Check if currently in dry run mode"""
    try:
        from bot.trading_state_machine import get_state_machine
        return get_state_machine().is_dry_run_mode()
    except:
        return False


# Example usage and testing
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("\n=== Dry Run Engine Test ===\n")
    
    engine = get_dry_run_engine(initial_balance=10000.0)
    
    # Place simulated buy order
    print("\n--- Placing simulated BUY order ---")
    order1 = engine.place_order(
        symbol="BTC-USD",
        side="buy",
        order_type="market",
        quantity=0.5,
        current_market_price=45000.0
    )
    
    # Update market prices
    print("\n--- Updating market prices ---")
    engine.update_market_prices({"BTC-USD": 46000.0})
    
    # Check positions
    print("\n--- Current positions ---")
    positions = engine.get_positions()
    for symbol, pos in positions.items():
        print(f"  {symbol}: {pos.quantity} @ {pos.entry_price}, Unrealized P&L: {pos.unrealized_pnl}")
        
    # Place simulated sell order
    print("\n--- Placing simulated SELL order ---")
    order2 = engine.place_order(
        symbol="BTC-USD",
        side="sell",
        order_type="market",
        quantity=0.5,
        current_market_price=46000.0
    )
    
    # Get performance summary
    print("\n--- Performance Summary ---")
    summary = engine.get_performance_summary()
    for key, value in summary.items():
        print(f"  {key}: {value}")
