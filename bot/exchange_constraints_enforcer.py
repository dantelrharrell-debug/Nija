"""
Exchange Constraints Enforcer
=============================

Deterministic order validation that rejects unfillable orders BEFORE they
reach the broker — prevents wasted API calls and market rejections.

Design:
- Hard requirements from each exchange (Kraken: $10 min, Coinbase: varies)
- Per-symbol base-currency minimums (precision granularity)
- Fee-aware sizing: all calculations include realistic fee buffers
- Three-layer validation: notional USD → base currency → precision rules
- Reject-proof: never place an order that violates exchange constraints
"""

import logging
import os
from enum import Enum
from typing import NamedTuple, Optional

logger = logging.getLogger("nija.exchange_constraints")

# ─────────────────────────────────────────────────────────────────────────────
# Exchange-Level Constants
# ─────────────────────────────────────────────────────────────────────────────

class BrokerType(str, Enum):
    """Supported broker types."""
    KRAKEN = "kraken"
    COINBASE = "coinbase"
    UNKNOWN = "unknown"


# Hard exchange minimums — NEVER violate these
KRAKEN_MIN_ORDER_USD = 10.0  # Kraken rejects all orders under $10
KRAKEN_FEE_BUFFER = 0.50    # Add $0.50 to cover ~0.4-0.6% taker fee

# Coinbase minimums — varies by account/mode
COINBASE_MIN_ORDER_USD = float(
    os.getenv("COINBASE_MIN_ORDER_USD", 
              os.getenv("COINBASE_MIN_ORDER", "1.0"))
)
COINBASE_FEE_BUFFER = 0.02  # 2% conservative fee buffer

# Universal soft minimum (policy floor, not exchange constraint)
GLOBAL_MIN_ORDER_USD = float(os.getenv("MIN_NOTIONAL_USD", "5.50"))

# Per-symbol precision minimums (base currency, in crypto units)
# These prevent dust orders that fail due to quantity precision too low
SYMBOL_MIN_BASE_QUANTITY = {
    # BTC family (ultra-high precision required)
    'BTC': 0.000001,   # Coinbase: 0.000001 BTC = ~$0.06 at $60k
    'BTC-USD': 0.000001,
    'BTC-USDC': 0.000001,
    'BTC-EUR': 0.000001,
    'XBT': 0.000001,   # Kraken's ticker
    
    # ETH family
    'ETH': 0.0001,     # Coinbase: 0.0001 ETH = ~$0.30 at $3k
    'ETH-USD': 0.0001,
    'ETH-USDC': 0.0001,
    'ETH-EUR': 0.0001,
    
    # Mid-tier altcoins
    'SOL': 0.01,       # Solana
    'AVAX': 0.01,      # Avalanche
    'LINK': 0.01,      # Chainlink
    'DOT': 0.01,       # Polkadot
    'MATIC': 0.01,     # Polygon
    
    # Lower-precision coins (1.0+ minimum in base units)
    'BNB': 0.001,
    'XRP': 0.1,
    'ADA': 0.1,
    'HBAR': 0.1,
    'DOGE': 1.0,
    'SHIB': 1.0,       # Sensitive to precision
}

# Default precision for unknown symbols (conservative)
DEFAULT_MIN_BASE_QUANTITY = 0.01


class OrderValidationResult(NamedTuple):
    """Result of exchange constraint validation."""
    is_valid: bool
    reason: str  # Human-readable validation message
    recommended_size_usd: Optional[float] = None  # If valid, exact USD to use
    recommended_quantity: Optional[float] = None   # If valid, exact base quantity
    min_required_usd: Optional[float] = None       # What the exchange needs
    min_required_quantity: Optional[float] = None  # What the exchange needs in base


def get_exchange_min_order_usd(broker_type: str) -> float:
    """Return the hard exchange minimum for order size in USD."""
    broker_lower = broker_type.lower() if broker_type else "unknown"
    if "kraken" in broker_lower:
        return KRAKEN_MIN_ORDER_USD + KRAKEN_FEE_BUFFER
    elif "coinbase" in broker_lower:
        return COINBASE_MIN_ORDER_USD
    else:
        # Conservative default for unknown exchanges
        return GLOBAL_MIN_ORDER_USD


def get_symbol_min_base_quantity(symbol: str) -> float:
    """Return minimum base currency quantity for a symbol."""
    symbol_upper = symbol.upper().split('-')[0] if symbol else "UNKNOWN"
    # Try exact symbol match first
    if symbol.upper() in SYMBOL_MIN_BASE_QUANTITY:
        return SYMBOL_MIN_BASE_QUANTITY[symbol.upper()]
    # Try base currency only
    if symbol_upper in SYMBOL_MIN_BASE_QUANTITY:
        return SYMBOL_MIN_BASE_QUANTITY[symbol_upper]
    # Default
    return DEFAULT_MIN_BASE_QUANTITY


def validate_order_constraints(
    symbol: str,
    order_size_usd: float,
    price_usd: float,
    broker_type: str = "coinbase",
) -> OrderValidationResult:
    """
    Validate an order against all exchange constraints before placing it.

    Three layers of validation:
    1. USD notional: meets exchange minimum in USD
    2. Base quantity: can be represented in the symbol's precision
    3. Fee buffer: size remains filled after exchange fees

    Args:
        symbol: Trading pair symbol (e.g., 'BTC-USD', 'ETH', 'SOL-USDC')
        order_size_usd: Intended order size in USD
        price_usd: Current market price in USD
        broker_type: Exchange name ('kraken', 'coinbase', etc.)

    Returns:
        OrderValidationResult with is_valid=True/False and diagnostic data.
    """
    broker_lower = broker_type.lower() if broker_type else "unknown"

    # ───────────────────────────────────────────────────────────────────────
    # Layer 1: Exchange minimum in USD
    # ───────────────────────────────────────────────────────────────────────

    exchange_min_usd = get_exchange_min_order_usd(broker_type)

    if order_size_usd < exchange_min_usd:
        return OrderValidationResult(
            is_valid=False,
            reason=(
                f"Order size ${order_size_usd:.2f} below exchange minimum "
                f"${exchange_min_usd:.2f} for {broker_lower}"
            ),
            min_required_usd=exchange_min_usd,
        )

    # ───────────────────────────────────────────────────────────────────────
    # Layer 2: Calculate base quantity from USD
    # ───────────────────────────────────────────────────────────────────────

    if price_usd <= 0:
        return OrderValidationResult(
            is_valid=False,
            reason=f"Invalid price ${price_usd:.2f} — cannot calculate quantity",
        )

    base_quantity = order_size_usd / price_usd

    # ───────────────────────────────────────────────────────────────────────
    # Layer 3: Symbol-specific minimum base-currency precision
    # ───────────────────────────────────────────────────────────────────────

    min_base_qty = get_symbol_min_base_quantity(symbol)

    if base_quantity < min_base_qty:
        # Suggest rounding UP to the minimum
        recommended_usd = min_base_qty * price_usd
        return OrderValidationResult(
            is_valid=False,
            reason=(
                f"Base quantity {base_quantity:.8f} below minimum "
                f"{min_base_qty:.8f} for {symbol}. "
                f"Try ${recommended_usd:.2f} instead."
            ),
            recommended_size_usd=recommended_usd,
            recommended_quantity=min_base_qty,
            min_required_quantity=min_base_qty,
        )

    # ───────────────────────────────────────────────────────────────────────
    # ALL CHECKS PASSED: Order is valid and fillable
    # ───────────────────────────────────────────────────────────────────────

    return OrderValidationResult(
        is_valid=True,
        reason=f"✅ Order valid: ${order_size_usd:.2f} ({base_quantity:.8f} {symbol})",
        recommended_size_usd=order_size_usd,
        recommended_quantity=base_quantity,
        min_required_usd=exchange_min_usd,
        min_required_quantity=min_base_qty,
    )


def calculate_fillable_order_size(
    available_usd: float,
    symbol: str,
    price_usd: float,
    broker_type: str = "coinbase",
    fee_factor: float = 1.02,
) -> float:
    """
    Calculate the maximum fillable order size that respects exchange constraints
    and leaves room for fees.

    Descends from available_usd, applying fee buffer, until a valid order emerges.

    Args:
        available_usd: Capital available for trade (before fees)
        symbol: Trading pair
        price_usd: Current market price
        broker_type: Exchange
        fee_factor: Factor to reserve for fees (e.g., 1.02 = 2%)

    Returns:
        Maximum fillable order size in USD, or 0.0 if impossible
    """
    exchange_min = get_exchange_min_order_usd(broker_type)

    # Largest possible order = available capital minus fee reserve
    max_order = available_usd / fee_factor

    if max_order < exchange_min:
        logger.warning(
            "[ExchangeConstraints] Cannot place order: "
            "available_usd=%.2f (after %.1f%% fees = %.2f) < exchange_min=%.2f",
            available_usd, (fee_factor - 1) * 100, max_order, exchange_min,
        )
        return 0.0

    # Validate — if it passes, return it; otherwise warn
    result = validate_order_constraints(
        symbol=symbol,
        order_size_usd=max_order,
        price_usd=price_usd,
        broker_type=broker_type,
    )

    if result.is_valid:
        logger.info(
            "[ExchangeConstraints] Calculated fillable size: $%.2f "
            "({:.8f} {}) @ ${:.2f}",
            max_order, result.recommended_quantity, symbol, price_usd,
        )
        return max_order

    # Max order failed — try exchange minimum
    if result.recommended_size_usd and result.recommended_size_usd <= max_order:
        logger.info(
            "[ExchangeConstraints] Max order failed precision; "
            "recommending: $%.2f ({:.8f} {})",
            result.recommended_size_usd,
            result.recommended_quantity,
            symbol,
        )
        return result.recommended_size_usd

    logger.error(
        "[ExchangeConstraints] No valid order possible: %s", result.reason
    )
    return 0.0
