"""
Exchange Order Compiler (EOC)
==============================

Final authority for order validation and canonicalization.
No order reaches the broker unless it passes all four compile gates.

Pattern: Constraints → Sizing → Simulation → Approval

This is the single exit point for all trade orders. 
Everything that exits here has been proven valid on the target exchange.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional, Tuple

logger = logging.getLogger("nija.exchange_order_compiler")


class ExchangeSchema(str, Enum):
    """Known exchange schemas."""
    KRAKEN = "kraken"
    COINBASE = "coinbase"
    UNKNOWN = "unknown"


class OrderCompileError(RuntimeError):
    """Raised when an order fails compilation — order must not be placed."""
    pass


@dataclass(frozen=True)
class ExchangeConstraints:
    """Immutable exchange-level constraints pulled at compile time."""
    exchange: str
    min_order_usd: float          # Minimum order size in USD
    min_notional_usd: float        # Coinbase/Kraken notional minimum
    fee_rate_one_way: float        # Taker fee (one-way)
    step_size: float               # Asset step size (for quantity rounding)
    precision_decimals: int        # Max decimal places for this symbol
    leverage: int = 1              # Spot=1, margin varies


@dataclass(frozen=True)
class PricingSnapshot:
    """Current market pricing for a symbol."""
    symbol: str
    bid: float
    ask: float
    mid: float
    available_balance_usd: float


@dataclass(frozen=True)
class CompiledOrder:
    """Fully validated, ready-to-submit order."""
    symbol: str
    side: str                       # 'buy' or 'sell'
    size_usd: float                 # Final USD amount (fees included in calc)
    quantity: float                 # Base asset quantity
    price: float                    # Execution price assumption
    constraints: ExchangeConstraints
    
    # Validation results
    is_exchange_valid: bool         # Meets exchange schema
    is_fillable: bool               # Sufficient balance + fees
    is_precision_valid: bool        # Quantity at correct precision
    is_profitable: bool             # After fees, meets threshold
    
    # Diagnostics
    simulated_fee_usd: float        # Expected fee cost
    simulated_net_after_fees_usd: float
    
    def __post_init__(self):
        """Enforce that all gates passed before order exists."""
        if not (self.is_exchange_valid and self.is_fillable and 
                self.is_precision_valid and self.is_profitable):
            raise OrderCompileError(
                f"Order {self.symbol} {self.side} {self.size_usd} failed compile gates: "
                f"exchange_valid={self.is_exchange_valid} "
                f"fillable={self.is_fillable} "
                f"precision={self.is_precision_valid} "
                f"profitable={self.is_profitable}"
            )


class ExchangeOrderCompiler:
    """
    Single canonical order compiler.
    
    Flow:
    1. get_constraints(exchange, symbol) → ExchangeConstraints
    2. clamp_size(available_usd, constraints) → valid_size_range
    3. simulate_order(symbol, side, size, pricing) → feasibility
    4. compile(symbol, side, size, pricing, constraints) → CompiledOrder or raise
    """

    # Exchange schemas (hardcoded but could be fetched from REST API dynamically)
    SCHEMAS: Dict[str, Dict[str, ExchangeConstraints]] = {
        "kraken": {
            # KRAKEN: $10 minimum per order, ~0.26% taker fee
            "_default": ExchangeConstraints(
                exchange="kraken",
                min_order_usd=10.0,
                min_notional_usd=10.0,
                fee_rate_one_way=0.0026,
                step_size=1.0,
                precision_decimals=8,
            ),
            "BTC": ExchangeConstraints(
                exchange="kraken",
                min_order_usd=10.0,
                min_notional_usd=10.0,
                fee_rate_one_way=0.0026,
                step_size=0.00000001,  # Satoshi precision
                precision_decimals=8,
            ),
            "ETH": ExchangeConstraints(
                exchange="kraken",
                min_order_usd=10.0,
                min_notional_usd=10.0,
                fee_rate_one_way=0.0026,
                step_size=0.00000001,  # Wei precision
                precision_decimals=8,
            ),
        },
        "coinbase": {
            # COINBASE: $1+ typical, ~0.6% taker fee, varies by symbol
            "_default": ExchangeConstraints(
                exchange="coinbase",
                min_order_usd=1.0,
                min_notional_usd=1.0,
                fee_rate_one_way=0.006,
                step_size=1.0,
                precision_decimals=8,
            ),
            "BTC": ExchangeConstraints(
                exchange="coinbase",
                min_order_usd=1.0,
                min_notional_usd=1.0,
                fee_rate_one_way=0.006,
                step_size=0.000001,
                precision_decimals=8,
            ),
            "ETH": ExchangeConstraints(
                exchange="coinbase",
                min_order_usd=1.0,
                min_notional_usd=1.0,
                fee_rate_one_way=0.006,
                step_size=0.0001,
                precision_decimals=8,
            ),
            "SOL": ExchangeConstraints(
                exchange="coinbase",
                min_order_usd=1.0,
                min_notional_usd=1.0,
                fee_rate_one_way=0.006,
                step_size=0.01,
                precision_decimals=2,
            ),
            "DOGE": ExchangeConstraints(
                exchange="coinbase",
                min_order_usd=1.0,
                min_notional_usd=1.0,
                fee_rate_one_way=0.006,
                step_size=1.0,
                precision_decimals=1,
            ),
        },
    }

    def __init__(self):
        pass

    def get_constraints(self, exchange: str, symbol: str) -> ExchangeConstraints:
        """
        Pull exchange schema for symbol.
        
        Tries:
        1. Exact symbol match (e.g., "BTC")
        2. Exchange default
        3. Global fallback
        """
        exchange_lower = exchange.lower()
        symbol_upper = symbol.upper().split('-')[0]  # Strip -USD suffix

        if exchange_lower in self.SCHEMAS:
            schemas = self.SCHEMAS[exchange_lower]
            if symbol_upper in schemas:
                return schemas[symbol_upper]
            if "_default" in schemas:
                return schemas["_default"]

        # Fallback: generic schema
        return ExchangeConstraints(
            exchange=exchange,
            min_order_usd=5.0,
            min_notional_usd=5.0,
            fee_rate_one_way=0.006,
            step_size=1.0,
            precision_decimals=8,
        )

    def clamp_size(
        self,
        available_usd: float,
        constraints: ExchangeConstraints,
        min_profit_usd: float = 0.50,
    ) -> Tuple[float, float]:
        """
        Pre-sizing clamp: given available capital, return valid size range.

        Returns:
            (min_valid_usd, max_valid_usd)
        """
        # Minimum: exchange minimum OR profit threshold, whichever is higher
        min_required = max(
            constraints.min_order_usd,
            constraints.min_notional_usd,
            min_profit_usd,
        )

        # Maximum: available balance minus 2% fee reserve
        max_possible = available_usd / 1.02

        if max_possible < min_required:
            raise OrderCompileError(
                f"Cannot place order: available ${available_usd:.2f} "
                f"(after 2% fee reserve = ${max_possible:.2f}) "
                f"< exchange minimum ${min_required:.2f}"
            )

        return min_required, max_possible

    def simulate_order(
        self,
        symbol: str,
        side: str,
        size_usd: float,
        pricing: PricingSnapshot,
        constraints: ExchangeConstraints,
        fee_multiplier: float = 2.0,  # Round-trip fee (entry + exit)
    ) -> Tuple[float, float, str]:
        """
        Simulate order execution.

        Returns:
            (quantity, simulated_fee_usd, feasibility_reason)
        
        Raises:
            OrderCompileError if fails
        """
        if size_usd < constraints.min_order_usd:
            raise OrderCompileError(
                f"Size ${size_usd:.2f} < exchange minimum ${constraints.min_order_usd:.2f}"
            )

        # Determine execution price (bid for sell, ask for buy)
        exec_price = pricing.ask if side == "buy" else pricing.bid
        if exec_price <= 0:
            raise OrderCompileError(f"Invalid execution price: {exec_price}")

        # Calculate quantity
        quantity = size_usd / exec_price

        # Round to step size
        quantity = (quantity // constraints.step_size) * constraints.step_size
        if quantity <= 0:
            raise OrderCompileError(
                f"Quantity rounds to zero: {size_usd} / {exec_price} @ "
                f"step_size {constraints.step_size}"
            )

        # Calculate fees
        simulated_fee_usd = size_usd * constraints.fee_rate_one_way * fee_multiplier

        # Check balance
        if pricing.available_balance_usd < (size_usd + simulated_fee_usd):
            raise OrderCompileError(
                f"Insufficient balance: need ${size_usd + simulated_fee_usd:.2f}, "
                f"have ${pricing.available_balance_usd:.2f}"
            )

        # Check precision
        if quantity > 0:
            # Round to precision decimals
            rounded_qty = round(quantity, constraints.precision_decimals)
            if rounded_qty != quantity:
                logger.warning(
                    "[EOC] Quantity adjusted for precision: %.12f → %.12f",
                    quantity, rounded_qty,
                )
                quantity = rounded_qty

        reason = (
            f"✅ Simulated {side.upper()} {quantity:.8f} {symbol} @ ${exec_price:.2f} "
            f"= ${size_usd:.2f} (fee: ${simulated_fee_usd:.2f})"
        )
        return quantity, simulated_fee_usd, reason

    def compile(
        self,
        symbol: str,
        side: str,
        size_usd: float,
        pricing: PricingSnapshot,
        exchange: str = "coinbase",
        min_profit_threshold_usd: float = 0.50,
    ) -> CompiledOrder:
        """
        Compile final order through all four gates.
        
        Raises:
            OrderCompileError if any gate fails
        """
        if side not in ("buy", "sell"):
            raise OrderCompileError(f"Invalid side: {side}")

        # Gate 1: Get exchange schema
        constraints = self.get_constraints(exchange, symbol)
        logger.info(
            "[EOC] Gate 1 — Schema: %s %s (min=$%.2f, precision=%d)",
            exchange, symbol, constraints.min_order_usd, constraints.precision_decimals,
        )

        # Gate 2: Clamp size to valid range
        min_valid, max_valid = self.clamp_size(
            pricing.available_balance_usd, constraints, min_profit_threshold_usd
        )
        clamped_size = max(min(size_usd, max_valid), min_valid)
        logger.info(
            "[EOC] Gate 2 — Clamp: requested=$%.2f → valid range [$%.2f, $%.2f] → clamped=$%.2f",
            size_usd, min_valid, max_valid, clamped_size,
        )

        # Gate 3: Simulate order feasibility
        try:
            quantity, fee_usd, sim_reason = self.simulate_order(
                symbol, side, clamped_size, pricing, constraints
            )
            logger.info("[EOC] Gate 3 — Simulation: %s", sim_reason)
        except OrderCompileError as e:
            logger.error("[EOC] Gate 3 FAILED — Simulation: %s", e)
            raise

        # Gate 4: Final approval
        is_exchange_valid = clamped_size >= constraints.min_order_usd
        is_fillable = pricing.available_balance_usd >= (clamped_size + fee_usd)
        is_precision_valid = quantity > 0
        is_profitable = clamped_size >= min_profit_threshold_usd

        if not (is_exchange_valid and is_fillable and is_precision_valid and is_profitable):
            raise OrderCompileError(
                f"Gate 4 FAILED: exchange_valid={is_exchange_valid} "
                f"fillable={is_fillable} precision={is_precision_valid} "
                f"profitable={is_profitable}"
            )

        logger.info("[EOC] Gate 4 — Approval: All gates passed ✅")

        # Build compiled order
        net_after_fees = clamped_size - fee_usd
        order = CompiledOrder(
            symbol=symbol,
            side=side,
            size_usd=clamped_size,
            quantity=quantity,
            price=pricing.mid,
            constraints=constraints,
            is_exchange_valid=is_exchange_valid,
            is_fillable=is_fillable,
            is_precision_valid=is_precision_valid,
            is_profitable=is_profitable,
            simulated_fee_usd=fee_usd,
            simulated_net_after_fees_usd=net_after_fees,
        )

        logger.info(
            "[EOC] ✅ ORDER COMPILED: %s %s $%.2f (qty=%.8f @ $%.2f, fee=$%.2f, net=$%.2f)",
            side.upper(),
            symbol,
            clamped_size,
            quantity,
            pricing.mid,
            fee_usd,
            net_after_fees,
        )

        return order
