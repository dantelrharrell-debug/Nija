"""
Advanced Execution Optimization
================================

Order slicing + maker/taker fee optimization for institutional-grade execution.

This module implements advanced execution techniques that can save 0.2-0.5% per trade:
1. Order Slicing (TWAP/VWAP): Split large orders to reduce market impact
2. Maker/Taker Optimization: Choose order types to minimize fees
3. Spread Capture: Use limit orders when conditions allow
4. Liquidity Timing: Execute when spreads are tight

Integrates with existing ExecutionEngine and ExecutionIntelligence.

Author: NIJA Trading Systems
Version: 1.0
Date: January 29, 2026
"""

import logging
import time
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
import numpy as np

logger = logging.getLogger("nija.execution_optimizer")


class OrderSliceStrategy(Enum):
    """Order slicing strategies"""
    TWAP = "twap"  # Time-weighted average price
    VWAP = "vwap"  # Volume-weighted average price
    ADAPTIVE = "adaptive"  # Adaptive based on market conditions
    IMMEDIATE = "immediate"  # No slicing (market order)


class FeeOptimizationMode(Enum):
    """Fee optimization modes"""
    MAKER_ONLY = "maker_only"  # Only use maker orders (limit orders)
    TAKER_ALLOWED = "taker_allowed"  # Allow taker if needed
    ADAPTIVE = "adaptive"  # Choose based on urgency and spread
    LOWEST_COST = "lowest_cost"  # Always choose lowest total cost


@dataclass
class OrderSlice:
    """
    A single slice of a larger order
    
    Attributes:
        slice_id: Unique ID for this slice
        symbol: Trading pair
        side: 'buy' or 'sell'
        size: Size in base currency
        order_type: 'market' or 'limit'
        limit_price: Limit price (if limit order)
        execution_time: When to execute this slice
        status: 'pending', 'executing', 'filled', 'failed'
        filled_price: Actual fill price
        filled_size: Actual filled size
        fees: Fees paid
    """
    slice_id: str
    symbol: str
    side: str
    size: float
    order_type: str
    limit_price: Optional[float] = None
    execution_time: datetime = field(default_factory=datetime.now)
    status: str = 'pending'
    filled_price: Optional[float] = None
    filled_size: float = 0.0
    fees: float = 0.0


@dataclass
class ExecutionPlan:
    """
    Complete execution plan for an order
    
    Attributes:
        symbol: Trading pair
        side: 'buy' or 'sell'
        total_size: Total size to execute
        slicing_strategy: How to slice the order
        fee_optimization: Fee optimization mode
        slices: List of order slices
        estimated_cost: Estimated total cost
        estimated_fees: Estimated total fees
        urgency: Urgency level (0-1, higher = more urgent)
        created_at: When plan was created
    """
    symbol: str
    side: str
    total_size: float
    slicing_strategy: OrderSliceStrategy
    fee_optimization: FeeOptimizationMode
    slices: List[OrderSlice] = field(default_factory=list)
    estimated_cost: float = 0.0
    estimated_fees: float = 0.0
    urgency: float = 0.5
    created_at: datetime = field(default_factory=datetime.now)


class ExecutionOptimizer:
    """
    Advanced Execution Optimizer
    
    Implements order slicing and fee optimization to minimize execution costs.
    
    Key Features:
    1. TWAP/VWAP order slicing for large orders
    2. Maker/taker fee optimization
    3. Spread-aware limit order placement
    4. Adaptive execution based on market conditions
    5. Real-time execution cost tracking
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize Execution Optimizer
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        
        # Fee schedule (Coinbase Advanced Trade as default)
        self.maker_fee = self.config.get('maker_fee', 0.004)  # 0.4%
        self.taker_fee = self.config.get('taker_fee', 0.006)  # 0.6%
        
        # Order slicing parameters
        self.min_slice_size_usd = self.config.get('min_slice_size_usd', 100)  # $100 min
        self.max_slices = self.config.get('max_slices', 10)  # Max 10 slices
        self.slice_interval_seconds = self.config.get('slice_interval_seconds', 60)  # 1 min between slices
        
        # Maker/taker optimization parameters
        self.max_spread_for_maker = self.config.get('max_spread_for_maker', 0.002)  # 0.2% max spread
        self.maker_timeout_seconds = self.config.get('maker_timeout_seconds', 300)  # 5 min max wait
        self.urgency_threshold = self.config.get('urgency_threshold', 0.7)  # Above this, use taker
        
        # Tracking
        self.active_plans: Dict[str, ExecutionPlan] = {}
        self.execution_history: List[Dict] = []
        
        logger.info("=" * 70)
        logger.info("⚡ Execution Optimizer Initialized")
        logger.info("=" * 70)
        logger.info(f"Maker Fee: {self.maker_fee*100:.2f}%")
        logger.info(f"Taker Fee: {self.taker_fee*100:.2f}%")
        logger.info(f"Slice Interval: {self.slice_interval_seconds}s")
        logger.info(f"Max Slices: {self.max_slices}")
        logger.info("=" * 70)
    
    def create_execution_plan(
        self,
        symbol: str,
        side: str,
        size: float,
        current_price: float,
        spread_pct: float,
        urgency: float = 0.5,
        market_conditions: Optional[Dict] = None
    ) -> ExecutionPlan:
        """
        Create optimal execution plan for an order
        
        Args:
            symbol: Trading pair
            side: 'buy' or 'sell'
            size: Size in base currency
            current_price: Current market price
            spread_pct: Current bid-ask spread (%)
            urgency: Urgency (0-1, higher = faster execution needed)
            market_conditions: Additional market data
            
        Returns:
            ExecutionPlan with optimized slicing and fee strategy
        """
        market_conditions = market_conditions or {}
        
        # Calculate order value
        order_value_usd = size * current_price
        
        # Determine slicing strategy
        slicing_strategy = self._select_slicing_strategy(
            order_value_usd, urgency, market_conditions
        )
        
        # Determine fee optimization mode
        fee_optimization = self._select_fee_optimization(
            spread_pct, urgency, market_conditions
        )
        
        # Create execution plan
        plan = ExecutionPlan(
            symbol=symbol,
            side=side,
            total_size=size,
            slicing_strategy=slicing_strategy,
            fee_optimization=fee_optimization,
            urgency=urgency
        )
        
        # Generate order slices
        self._generate_slices(plan, current_price, spread_pct)
        
        # Estimate costs
        self._estimate_execution_cost(plan, current_price)
        
        # Store plan
        plan_id = f"{symbol}_{side}_{datetime.now().timestamp()}"
        self.active_plans[plan_id] = plan
        
        logger.info("=" * 70)
        logger.info("📋 EXECUTION PLAN CREATED")
        logger.info("=" * 70)
        logger.info(f"Symbol: {symbol}")
        logger.info(f"Side: {side.upper()}")
        logger.info(f"Size: {size}")
        logger.info(f"Value: ${order_value_usd:,.2f}")
        logger.info(f"Slicing: {slicing_strategy.value.upper()}")
        logger.info(f"Fee Optimization: {fee_optimization.value.upper()}")
        logger.info(f"Num Slices: {len(plan.slices)}")
        logger.info(f"Estimated Fees: ${plan.estimated_fees:.2f} ({plan.estimated_fees/order_value_usd*100:.3f}%)")
        logger.info("=" * 70)
        
        return plan
    
    def _select_slicing_strategy(
        self,
        order_value_usd: float,
        urgency: float,
        market_conditions: Dict
    ) -> OrderSliceStrategy:
        """
        Select optimal order slicing strategy
        
        Args:
            order_value_usd: Order value in USD
            urgency: Urgency level (0-1)
            market_conditions: Market data
            
        Returns:
            Best OrderSliceStrategy
        """
        # Small orders: no slicing needed
        if order_value_usd < self.min_slice_size_usd * 2:
            return OrderSliceStrategy.IMMEDIATE
        
        # High urgency: immediate execution
        if urgency > self.urgency_threshold:
            return OrderSliceStrategy.IMMEDIATE
        
        # Large orders with low urgency: use TWAP
        if order_value_usd > 10000 and urgency < 0.5:
            return OrderSliceStrategy.TWAP
        
        # Medium orders: adaptive slicing
        return OrderSliceStrategy.ADAPTIVE
    
    def _select_fee_optimization(
        self,
        spread_pct: float,
        urgency: float,
        market_conditions: Dict
    ) -> FeeOptimizationMode:
        """
        Select optimal fee optimization mode
        
        Args:
            spread_pct: Current spread (%)
            urgency: Urgency level (0-1)
            market_conditions: Market data
            
        Returns:
            Best FeeOptimizationMode
        """
        # High urgency: allow taker orders
        if urgency > self.urgency_threshold:
            return FeeOptimizationMode.TAKER_ALLOWED
        
        # Tight spread: try maker orders
        if spread_pct <= self.max_spread_for_maker:
            return FeeOptimizationMode.MAKER_ONLY
        
        # Default: adaptive based on conditions
        return FeeOptimizationMode.ADAPTIVE
    
    def _generate_slices(
        self,
        plan: ExecutionPlan,
        current_price: float,
        spread_pct: float
    ) -> None:
        """
        Generate order slices based on execution plan
        
        Args:
            plan: Execution plan to populate
            current_price: Current market price
            spread_pct: Current spread
        """
        if plan.slicing_strategy == OrderSliceStrategy.IMMEDIATE:
            # Single order, immediate execution
            order_type, limit_price = self._determine_order_type(
                plan.side, current_price, spread_pct, plan.fee_optimization
            )
            
            plan.slices.append(OrderSlice(
                slice_id=f"{plan.symbol}_slice_0",
                symbol=plan.symbol,
                side=plan.side,
                size=plan.total_size,
                order_type=order_type,
                limit_price=limit_price,
                execution_time=datetime.now()
            ))
        
        elif plan.slicing_strategy == OrderSliceStrategy.TWAP:
            # Time-weighted slicing
            num_slices = min(self.max_slices, max(2, int(plan.total_size * current_price / self.min_slice_size_usd)))
            slice_size = plan.total_size / num_slices
            
            for i in range(num_slices):
                execution_time = datetime.now() + timedelta(seconds=i * self.slice_interval_seconds)
                order_type, limit_price = self._determine_order_type(
                    plan.side, current_price, spread_pct, plan.fee_optimization
                )
                
                plan.slices.append(OrderSlice(
                    slice_id=f"{plan.symbol}_slice_{i}",
                    symbol=plan.symbol,
                    side=plan.side,
                    size=slice_size,
                    order_type=order_type,
                    limit_price=limit_price,
                    execution_time=execution_time
                ))
        
        else:  # ADAPTIVE or VWAP
            # Adaptive slicing: larger first slice, smaller subsequent
            num_slices = min(5, max(2, int(plan.total_size * current_price / self.min_slice_size_usd)))
            
            # Use geometric distribution: 40%, 30%, 20%, 10%
            weights = [0.4, 0.3, 0.2, 0.1][:num_slices]
            weights = np.array(weights) / sum(weights)  # Normalize
            
            for i, weight in enumerate(weights):
                slice_size = plan.total_size * weight
                execution_time = datetime.now() + timedelta(seconds=i * self.slice_interval_seconds)
                order_type, limit_price = self._determine_order_type(
                    plan.side, current_price, spread_pct, plan.fee_optimization
                )
                
                plan.slices.append(OrderSlice(
                    slice_id=f"{plan.symbol}_slice_{i}",
                    symbol=plan.symbol,
                    side=plan.side,
                    size=slice_size,
                    order_type=order_type,
                    limit_price=limit_price,
                    execution_time=execution_time
                ))
    
    def _determine_order_type(
        self,
        side: str,
        current_price: float,
        spread_pct: float,
        fee_mode: FeeOptimizationMode
    ) -> Tuple[str, Optional[float]]:
        """
        Determine order type and limit price
        
        Args:
            side: 'buy' or 'sell'
            current_price: Current price
            spread_pct: Current spread
            fee_mode: Fee optimization mode
            
        Returns:
            Tuple of (order_type, limit_price)
        """
        # Calculate fee savings from maker vs taker
        fee_savings_pct = self.taker_fee - self.maker_fee  # ~0.2%
        
        if fee_mode == FeeOptimizationMode.TAKER_ALLOWED:
            # Use market order
            return 'market', None
        
        elif fee_mode == FeeOptimizationMode.MAKER_ONLY:
            # Use limit order at favorable price
            if side == 'buy':
                # Place limit buy at bid (or slightly above)
                limit_price = current_price * (1 - spread_pct / 2)
            else:
                # Place limit sell at ask (or slightly below)
                limit_price = current_price * (1 + spread_pct / 2)
            
            return 'limit', limit_price
        
        else:  # ADAPTIVE or LOWEST_COST
            # Choose based on spread vs fee savings
            # If spread < fee savings: use maker
            # If spread > fee savings: use taker (market order faster, similar cost)
            
            if spread_pct <= fee_savings_pct:
                # Tight spread: use maker
                if side == 'buy':
                    limit_price = current_price * (1 - spread_pct / 2)
                else:
                    limit_price = current_price * (1 + spread_pct / 2)
                return 'limit', limit_price
            else:
                # Wide spread: use taker
                return 'market', None
    
    def _estimate_execution_cost(self, plan: ExecutionPlan, current_price: float) -> None:
        """
        Estimate total execution cost and fees
        
        Args:
            plan: Execution plan
            current_price: Current price
        """
        total_cost = 0.0
        total_fees = 0.0
        
        for slice in plan.slices:
            slice_value = slice.size * current_price
            
            # Estimate fee based on order type
            if slice.order_type == 'market':
                fee = slice_value * self.taker_fee
            else:  # limit
                fee = slice_value * self.maker_fee
            
            total_fees += fee
            
            # Add slippage estimate for market orders
            if slice.order_type == 'market':
                # Assume 0.1% slippage for market orders
                slippage = slice_value * 0.001
                total_cost += slippage
        
        plan.estimated_cost = total_cost
        plan.estimated_fees = total_fees
    
    def optimize_single_order(
        self,
        symbol: str,
        side: str,
        size: float,
        current_price: float,
        spread_pct: float,
        urgency: float = 0.5
    ) -> Dict:
        """
        Get optimized order parameters for a single order
        
        Args:
            symbol: Trading pair
            side: 'buy' or 'sell'
            size: Order size
            current_price: Current price
            spread_pct: Current spread (%)
            urgency: Urgency (0-1)
            
        Returns:
            Dictionary with optimized order parameters
        """
        # Determine if we should use maker or taker
        fee_savings_pct = self.taker_fee - self.maker_fee
        
        # High urgency: use market order
        if urgency > self.urgency_threshold:
            return {
                'order_type': 'market',
                'limit_price': None,
                'estimated_fee_pct': self.taker_fee,
                'reasoning': 'High urgency - market order for immediate execution'
            }
        
        # Tight spread: use limit order for maker fee
        if spread_pct <= self.max_spread_for_maker:
            if side == 'buy':
                limit_price = current_price * (1 - spread_pct / 2)
            else:
                limit_price = current_price * (1 + spread_pct / 2)
            
            return {
                'order_type': 'limit',
                'limit_price': limit_price,
                'estimated_fee_pct': self.maker_fee,
                'reasoning': f'Tight spread ({spread_pct*100:.2f}%) - limit order for maker fee savings'
            }
        
        # Wide spread: compare total cost
        spread_cost = spread_pct / 2  # Cost of crossing spread
        taker_total_cost = self.taker_fee + 0.001  # Taker fee + slippage
        maker_total_cost = self.maker_fee + spread_cost  # Maker fee + half spread
        
        if maker_total_cost < taker_total_cost:
            if side == 'buy':
                limit_price = current_price * (1 - spread_pct / 2)
            else:
                limit_price = current_price * (1 + spread_pct / 2)
            
            return {
                'order_type': 'limit',
                'limit_price': limit_price,
                'estimated_fee_pct': self.maker_fee,
                'reasoning': f'Maker total cost ({maker_total_cost*100:.3f}%) < taker ({taker_total_cost*100:.3f}%)'
            }
        else:
            return {
                'order_type': 'market',
                'limit_price': None,
                'estimated_fee_pct': self.taker_fee,
                'reasoning': f'Taker total cost ({taker_total_cost*100:.3f}%) < maker ({maker_total_cost*100:.3f}%)'
            }
    
    def get_stats(self) -> Dict:
        """
        Get optimizer statistics
        
        Returns:
            Dictionary with statistics
        """
        total_fees_saved = 0.0
        total_executed = len(self.execution_history)
        
        for execution in self.execution_history:
            # Calculate fees saved vs always using taker
            baseline_fee = execution.get('order_value', 0) * self.taker_fee
            actual_fee = execution.get('actual_fee', 0)
            total_fees_saved += (baseline_fee - actual_fee)
        
        return {
            'active_plans': len(self.active_plans),
            'total_executed': total_executed,
            'total_fees_saved': total_fees_saved,
            'avg_fee_savings_per_trade': total_fees_saved / total_executed if total_executed > 0 else 0,
        }


# Singleton instance
_execution_optimizer_instance = None


def get_execution_optimizer(config: Dict = None) -> ExecutionOptimizer:
    """
    Get singleton Execution Optimizer instance
    
    Args:
        config: Optional configuration (only used on first call)
        
    Returns:
        ExecutionOptimizer instance
    """
    global _execution_optimizer_instance
    
    if _execution_optimizer_instance is None:
        _execution_optimizer_instance = ExecutionOptimizer(config)
    
    return _execution_optimizer_instance
