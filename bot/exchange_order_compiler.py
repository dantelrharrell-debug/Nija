"""
Exchange Order Compiler (EOC)
==============================

Final authority for order validation and canonicalization.
No order reaches the broker unless it passes all compile gates.

Pattern: Constraints → Sizing → Simulation → Approval

This is the single exit point for all trade orders.
Everything that exits here has been proven valid on the target exchange.
"""

import logging
import os
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_UP
from enum import Enum
from typing import Dict, Tuple

logger = logging.getLogger("nija.exchange_order_compiler")

_QUOTE_STEP_USD = Decimal("0.01")


class ExchangeSchema(str, Enum):
    """Known exchange schemas."""
    KRAKEN = "kraken"
    COINBASE = "coinbase"
    OKX = "okx"
    UNKNOWN = "unknown"


class OrderCompileError(RuntimeError):
    """Raised when an order fails compilation — order must not be placed."""
    pass


@dataclass(frozen=True)
class ExchangeConstraints:
    """Immutable exchange-level constraints pulled at compile time."""
    exchange: str
    min_order_usd: float          # Minimum order size in USD
    min_notional_usd: float       # Exchange notional minimum
    fee_rate_one_way: float       # Taker fee (one-way)
    step_size: float              # Asset step size (for quantity rounding)
    precision_decimals: int       # Max decimal places for this symbol
    leverage: int = 1             # Spot=1, margin varies


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

    The compiler intentionally validates post-rounding notional against a buffered
    exchange minimum. This prevents the exact live failure where a $20 Kraken
    order converts to a volume whose fee/headroom/precision-adjusted notional is
    fractionally below Kraken's $20 operational floor.
    """

    # Exchange schemas (hardcoded but could be fetched from REST API dynamically)
    SCHEMAS: Dict[str, Dict[str, ExchangeConstraints]] = {
        "kraken": {
            # KRAKEN: use $20 operational floor plus buffered sizing at compile time.
            "_default": ExchangeConstraints(
                exchange="kraken",
                min_order_usd=20.0,
                min_notional_usd=20.0,
                fee_rate_one_way=0.0026,
                step_size=0.00000001,
                precision_decimals=8,
            ),
            "BTC": ExchangeConstraints(
                exchange="kraken",
                min_order_usd=20.0,
                min_notional_usd=20.0,
                fee_rate_one_way=0.0026,
                step_size=0.00000001,
                precision_decimals=8,
            ),
            "XBT": ExchangeConstraints(
                exchange="kraken",
                min_order_usd=20.0,
                min_notional_usd=20.0,
                fee_rate_one_way=0.0026,
                step_size=0.00000001,
                precision_decimals=8,
            ),
            "ETH": ExchangeConstraints(
                exchange="kraken",
                min_order_usd=20.0,
                min_notional_usd=20.0,
                fee_rate_one_way=0.0026,
                step_size=0.00000001,
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
                step_size=0.00000001,
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
        "okx": {
            # OKX: $1 minimum per order, 0.1% taker fee (maker 0.08%)
            "_default": ExchangeConstraints(
                exchange="okx",
                min_order_usd=1.0,
                min_notional_usd=1.0,
                fee_rate_one_way=0.001,
                step_size=0.00000001,
                precision_decimals=8,
            ),
            "BTC": ExchangeConstraints(
                exchange="okx",
                min_order_usd=1.0,
                min_notional_usd=1.0,
                fee_rate_one_way=0.001,
                step_size=0.00000001,
                precision_decimals=8,
            ),
            "ETH": ExchangeConstraints(
                exchange="okx",
                min_order_usd=1.0,
                min_notional_usd=1.0,
                fee_rate_one_way=0.001,
                step_size=0.00000001,
                precision_decimals=8,
            ),
        },
    }

    def __init__(self):
        pass

    @staticmethod
    def _decimal(value: float) -> Decimal:
        return Decimal(str(value))

    @staticmethod
    def _round_usd_up(value: Decimal) -> Decimal:
        return (value / _QUOTE_STEP_USD).to_integral_value(rounding=ROUND_UP) * _QUOTE_STEP_USD

    @staticmethod
    def _resolve_min_quote_buffer_pct(exchange: str) -> float:
        if str(exchange).lower() != "kraken":
            return 0.0
        raw = os.getenv("KRAKEN_MIN_QUOTE_BUFFER_PCT", os.getenv("NIJA_KRAKEN_MIN_QUOTE_BUFFER_PCT", "0.03"))
        try:
            value = float(raw)
        except (TypeError, ValueError):
            value = 0.03
        return min(max(value, 0.0), 0.10)

    def _safe_min_notional_usd(self, constraints: ExchangeConstraints) -> float:
        raw_min = max(float(constraints.min_order_usd), float(constraints.min_notional_usd))
        buffer_pct = self._resolve_min_quote_buffer_pct(constraints.exchange)
        if buffer_pct <= 0:
            return raw_min
        return float(self._round_usd_up(self._decimal(raw_min) * (Decimal("1") + self._decimal(buffer_pct))))

    @staticmethod
    def _round_quantity_down(quantity: float, constraints: ExchangeConstraints) -> float:
        if quantity <= 0:
            return 0.0
        step = Decimal(str(constraints.step_size or 0))
        if step <= 0:
            rounded = Decimal(str(quantity))
        else:
            rounded = (Decimal(str(quantity)) / step).to_integral_value(rounding=ROUND_DOWN) * step
        quant = Decimal("1").scaleb(-max(0, int(constraints.precision_decimals)))
        rounded = rounded.quantize(quant, rounding=ROUND_DOWN)
        return float(rounded)

    def _quantity_for_notional(self, size_usd: float, exec_price: float, constraints: ExchangeConstraints) -> float:
        if exec_price <= 0:
            raise OrderCompileError(f"Invalid execution price: {exec_price}")
        raw_qty = float(self._decimal(size_usd) / self._decimal(exec_price))
        return self._round_quantity_down(raw_qty, constraints)

    def get_constraints(self, exchange: str, symbol: str) -> ExchangeConstraints:
        """
        Pull exchange schema for symbol.

        Tries:
        1. Exact symbol match (e.g., "BTC")
        2. Exchange default
        3. Global fallback
        """
        exchange_lower = str(exchange or "").lower()
        symbol_upper = str(symbol or "").upper().replace("/", "-").split('-')[0]
        if symbol_upper == "XBT":
            symbol_upper = "BTC"

        if exchange_lower in self.SCHEMAS:
            schemas = self.SCHEMAS[exchange_lower]
            if symbol_upper in schemas:
                return schemas[symbol_upper]
            if "_default" in schemas:
                return schemas["_default"]

        # Fallback: generic schema
        return ExchangeConstraints(
            exchange=exchange or "unknown",
            min_order_usd=5.0,
            min_notional_usd=5.0,
            fee_rate_one_way=0.006,
            step_size=0.00000001,
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
        # Minimum: buffered exchange minimum OR profit threshold, whichever is higher.
        min_required = max(
            self._safe_min_notional_usd(constraints),
            float(min_profit_usd),
        )

        # Maximum: available balance minus 2% fee reserve
        max_possible = float(available_usd) / 1.02

        if max_possible < min_required:
            raise OrderCompileError(
                f"Cannot place order: available ${available_usd:.2f} "
                f"(after 2% fee reserve = ${max_possible:.2f}) "
                f"< buffered exchange minimum ${min_required:.2f}"
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
    ) -> Tuple[float, float, str, float]:
        """
        Simulate order execution.

        Returns:
            (quantity, simulated_fee_usd, feasibility_reason, notional_after_rounding)

        Raises:
            OrderCompileError if fails
        """
        safe_min = self._safe_min_notional_usd(constraints)
        if size_usd < safe_min:
            raise OrderCompileError(
                f"Size ${size_usd:.2f} < buffered exchange minimum ${safe_min:.2f}"
            )

        # Determine execution price (bid for sell, ask for buy)
        exec_price = pricing.ask if side == "buy" else pricing.bid
        if exec_price <= 0:
            raise OrderCompileError(f"Invalid execution price: {exec_price}")

        quantity = self._quantity_for_notional(size_usd, exec_price, constraints)
        if quantity <= 0:
            raise OrderCompileError(
                f"Quantity rounds to zero: {size_usd} / {exec_price} @ "
                f"step_size {constraints.step_size}"
            )

        notional_after_rounding = quantity * exec_price
        if notional_after_rounding + 1e-9 < safe_min:
            # Lift the quote size just enough to survive precision rounding, then
            # calculate quantity again. This is the final guard against an order
            # landing exactly on Kraken's minimum.
            lifted_size = float(self._round_usd_up(self._decimal(safe_min + float(constraints.step_size) * exec_price)))
            quantity = self._quantity_for_notional(lifted_size, exec_price, constraints)
            notional_after_rounding = quantity * exec_price
            size_usd = max(size_usd, lifted_size)
            logger.info(
                "[EOC] Lifted order notional after rounding: qty=%.12f notional=$%.4f safe_min=$%.2f",
                quantity,
                notional_after_rounding,
                safe_min,
            )
            if notional_after_rounding + 1e-9 < safe_min:
                raise OrderCompileError(
                    f"Post-rounding notional ${notional_after_rounding:.2f} "
                    f"< buffered exchange minimum ${safe_min:.2f}"
                )

        # Calculate fees on the final quote size.
        simulated_fee_usd = size_usd * constraints.fee_rate_one_way * fee_multiplier

        # Check balance — buys require available cash; sells draw from held inventory
        # (not cash), so the cash-balance check is skipped to avoid rejecting valid exits.
        if side == "buy" and pricing.available_balance_usd < (size_usd + simulated_fee_usd):
            raise OrderCompileError(
                f"Insufficient balance: need ${size_usd + simulated_fee_usd:.2f}, "
                f"have ${pricing.available_balance_usd:.2f}"
            )

        reason = (
            f"✅ Simulated {side.upper()} {quantity:.8f} {symbol} @ ${exec_price:.2f} "
            f"= ${notional_after_rounding:.2f} after rounding (fee: ${simulated_fee_usd:.2f})"
        )
        return quantity, simulated_fee_usd, reason, notional_after_rounding

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
        Compile final order through all gates.

        Raises:
            OrderCompileError if any gate fails
        """
        if side not in ("buy", "sell"):
            raise OrderCompileError(f"Invalid side: {side}")

        # Gate 1: Get exchange schema
        constraints = self.get_constraints(exchange, symbol)
        safe_min = self._safe_min_notional_usd(constraints)
        logger.info(
            "[EOC] Gate 1 — Schema: %s %s (raw_min=$%.2f, safe_min=$%.2f, precision=%d)",
            exchange,
            symbol,
            max(constraints.min_order_usd, constraints.min_notional_usd),
            safe_min,
            constraints.precision_decimals,
        )

        # Gate 2: Clamp size to valid range
        min_valid, max_valid = self.clamp_size(
            pricing.available_balance_usd, constraints, min_profit_threshold_usd
        )
        clamped_size = max(min(float(size_usd), max_valid), min_valid)
        logger.info(
            "[EOC] Gate 2 — Clamp: requested=$%.2f → valid range [$%.2f, $%.2f] → clamped=$%.2f",
            size_usd, min_valid, max_valid, clamped_size,
        )

        # Gate 3: Simulate order feasibility
        try:
            quantity, fee_usd, sim_reason, notional_after_rounding = self.simulate_order(
                symbol, side, clamped_size, pricing, constraints
            )
            clamped_size = max(clamped_size, notional_after_rounding)
            logger.info("[EOC] Gate 3 — Simulation: %s", sim_reason)
        except OrderCompileError as e:
            logger.error("[EOC] Gate 3 FAILED — Simulation: %s", e)
            raise

        # Gate 4: Final approval
        is_exchange_valid = notional_after_rounding + 1e-9 >= safe_min
        # Sells draw from held inventory, not cash — always considered fillable at gate level.
        is_fillable = side == "sell" or pricing.available_balance_usd >= (clamped_size + fee_usd)
        is_precision_valid = quantity > 0
        is_profitable = clamped_size >= min_profit_threshold_usd

        if not (is_exchange_valid and is_fillable and is_precision_valid and is_profitable):
            raise OrderCompileError(
                f"Gate 4 FAILED: exchange_valid={is_exchange_valid} "
                f"fillable={is_fillable} precision={is_precision_valid} "
                f"profitable={is_profitable} notional_after_rounding=${notional_after_rounding:.2f} "
                f"safe_min=${safe_min:.2f}"
            )

        logger.info("[EOC] Gate 4 — Approval: All gates passed ✅")

        # Build compiled order
        net_after_fees = clamped_size - fee_usd
        exec_price = pricing.ask if side == "buy" else pricing.bid
        order = CompiledOrder(
            symbol=symbol,
            side=side,
            size_usd=clamped_size,
            quantity=quantity,
            price=exec_price,
            constraints=constraints,
            is_exchange_valid=is_exchange_valid,
            is_fillable=is_fillable,
            is_precision_valid=is_precision_valid,
            is_profitable=is_profitable,
            simulated_fee_usd=fee_usd,
            simulated_net_after_fees_usd=net_after_fees,
        )

        logger.info(
            "[EOC] ✅ ORDER COMPILED: %s %s $%.2f (qty=%.8f @ $%.8f, fee=$%.2f, net=$%.2f)",
            side.upper(),
            symbol,
            clamped_size,
            quantity,
            exec_price,
            fee_usd,
            net_after_fees,
        )

        return order
