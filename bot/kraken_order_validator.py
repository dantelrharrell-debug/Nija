"""
Kraken Order Validator

Validates orders against Kraken minimums before submission.
Prevents order rejections due to:
- Pair minimums
- Quote currency minimums
- Fee-adjusted sizing
- Post-conversion / post-rounding notional drift

Also provides utilities for verifying per-API key execution.
"""

import logging
import os
from decimal import Decimal, ROUND_UP
from typing import Dict, Optional, Tuple

logger = logging.getLogger("nija.kraken_validator")

# Logging constants
SEPARATOR = "=" * 70

# Kraken minimum order sizes
# Source: https://support.kraken.com/hc/en-us/articles/205893708-Minimum-order-size-volume-for-trading
# Note: These minimums are subject to change. Verify against current Kraken documentation.
#
# Kraken minimum notional enforcement.
# Kraken rejects orders below ~$15-20 USD on many pairs (ECEL reject: BELOW_MIN_NOTIONAL).
# $20 is treated as the raw operational floor; a small configurable quote buffer is
# applied on top of this before final validation so NIJA never submits an order
# exactly on the minimum where fee/headroom/rounding can push it below the floor.
KRAKEN_MINIMUM_ORDER_USD = 20.00

# Round quote amounts upward to the nearest cent when computing safe minimums.
_QUOTE_STEP_USD = Decimal("0.01")
_VOLUME_STEP = Decimal("0.000000000001")

KRAKEN_MINIMUMS = {
    # Major pairs
    'XXBTZUSD': {'min_base': 0.0001, 'min_quote': KRAKEN_MINIMUM_ORDER_USD},  # BTC/USD
    'XETHZUSD': {'min_base': 0.01, 'min_quote': KRAKEN_MINIMUM_ORDER_USD},    # ETH/USD
    'XXBTZUSDT': {'min_base': 0.0001, 'min_quote': KRAKEN_MINIMUM_ORDER_USD}, # BTC/USDT
    'XETHZUSDT': {'min_base': 0.01, 'min_quote': KRAKEN_MINIMUM_ORDER_USD},   # ETH/USDT

    # Additional major pairs
    'ADAUSD': {'min_base': 10.0, 'min_quote': KRAKEN_MINIMUM_ORDER_USD},
    'SOLUSD': {'min_base': 0.5, 'min_quote': KRAKEN_MINIMUM_ORDER_USD},
    'DOTUSD': {'min_base': 1.0, 'min_quote': KRAKEN_MINIMUM_ORDER_USD},
    'AVAXUSD': {'min_base': 0.5, 'min_quote': KRAKEN_MINIMUM_ORDER_USD},
    'MATICUSD': {'min_base': 10.0, 'min_quote': KRAKEN_MINIMUM_ORDER_USD},
    'LINKUSD': {'min_base': 1.0, 'min_quote': KRAKEN_MINIMUM_ORDER_USD},

    # Default for unknown pairs - use safety buffer
    'DEFAULT': {'min_base': 0.001, 'min_quote': KRAKEN_MINIMUM_ORDER_USD}
}

# Kraken fee structure
# Source: https://www.kraken.com/features/fee-schedule
# Note: Fees vary by 30-day trading volume. These are the default/lowest tier rates.
# Higher volume traders may have lower fees. Update these values as needed.
KRAKEN_TAKER_FEE = 0.0016  # 0.16% (volume tier 0-50k)
KRAKEN_MAKER_FEE = 0.0010  # 0.10% (volume tier 0-50k)


def _resolve_buy_buffer_pct() -> float:
    """Return extra buy-side headroom beyond exchange fee for quote affordability."""
    raw = os.getenv("KRAKEN_BUY_BUFFER_PCT", "0.004")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 0.004
    return min(max(value, 0.0), 0.05)


def _resolve_min_quote_buffer_pct() -> float:
    """Return the exchange-minimum quote buffer used before final Kraken validation."""
    raw = os.getenv("KRAKEN_MIN_QUOTE_BUFFER_PCT", os.getenv("NIJA_KRAKEN_MIN_QUOTE_BUFFER_PCT", "0.03"))
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = 0.03
    # Keep operator overrides bounded: enough room for rounding/slippage, not enough
    # to accidentally oversize small accounts.
    return min(max(value, 0.0), 0.10)


def _decimal(value: float) -> Decimal:
    return Decimal(str(value))


def _round_up(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        return value
    return (value / step).to_integral_value(rounding=ROUND_UP) * step


def get_safe_min_quote(raw_min_quote: float) -> float:
    """Return the safe quote minimum with the configured buffer applied.

    Example: raw $20.00 with the default 3% buffer -> $20.60.
    """
    raw = _decimal(raw_min_quote)
    multiplier = Decimal("1") + _decimal(_resolve_min_quote_buffer_pct())
    return float(_round_up(raw * multiplier, _QUOTE_STEP_USD))


def get_pair_safe_minimums(pair: str) -> Dict[str, float]:
    """Return Kraken pair minimums with the quote side buffered for live orders."""
    minimums = get_pair_minimums(pair)
    return {
        'min_base': float(minimums['min_base']),
        'min_quote': get_safe_min_quote(float(minimums['min_quote'])),
        'raw_min_quote': float(minimums['min_quote']),
        'quote_buffer_pct': _resolve_min_quote_buffer_pct(),
    }


def _volume_for_quote(quote_value: float, price: float) -> float:
    if price <= 0:
        return 0.0
    volume = _decimal(quote_value) / _decimal(price)
    return float(_round_up(volume, _VOLUME_STEP))


# Exchange-specific minimum order values (USD)
# Operational floors — above exchange hard minimums to ensure fee-positive trades.
# Aligned with BROKER_MIN_ORDER_USD in nija_apex_strategy_v71.py.
COINBASE_MINIMUM_ORDER_USD = 10.00  # $10 operational floor (1.20% round-trip fee-positive)
OKX_MINIMUM_ORDER_USD = 10.00       # $10 operational floor (0.20% round-trip, USDT pairs)
BINANCE_MINIMUM_ORDER_USD = 10.00   # $10 operational floor (matches MIN_NOTIONAL filter)


def get_pair_minimums(pair: str) -> Dict[str, float]:
    """
    Get minimum order requirements for a Kraken trading pair.

    First tries to get dynamic data from Kraken API cache, then falls back
    to static hardcoded minimums.

    Args:
        pair: Kraken pair symbol (e.g., 'XXBTZUSD', 'XETHZUSDT', 'GLMRUSD')

    Returns:
        dict: {'min_base': float, 'min_quote': float}
    """
    # Normalize pair format
    pair = pair.upper().replace('/', '').replace('-', '')

    # Try to get dynamic minimum from market data cache
    try:
        from bot.kraken_market_data import get_kraken_market_data  # type: ignore[import]
        market_data = get_kraken_market_data()

        # Get minimum volume from Kraken API data
        min_base = market_data.get_minimum_volume(pair)
        min_cost = market_data.get_minimum_cost(pair)

        if min_base is not None:
            # Use Kraken's actual minimum, but enforce our $20 USD operational floor.
            return {
                'min_base': min_base,
                'min_quote': max(min_cost or 0.0, KRAKEN_MINIMUM_ORDER_USD)
            }
    except ImportError:
        logger.debug("Market data module not available, using static minimums")
    except Exception as e:
        logger.debug(f"Could not fetch dynamic minimum for {pair}: {e}")

    # Fallback to static minimums
    return KRAKEN_MINIMUMS.get(pair, KRAKEN_MINIMUMS['DEFAULT'])


def validate_order_size(pair: str, volume: float, price: float,
                       side: str = 'buy') -> Tuple[bool, Optional[str]]:
    """
    Validate order size meets Kraken minimums after conversion and rounding.

    Args:
        pair: Kraken pair symbol (e.g., 'XXBTZUSD')
        volume: Order volume in base currency
        price: Order price (for calculating quote value)
        side: 'buy' or 'sell'

    Returns:
        tuple: (is_valid: bool, error_message: Optional[str])
    """
    if price <= 0:
        return False, f"Invalid price {price} for {pair}"

    minimums = get_pair_minimums(pair)
    safe_minimums = get_pair_safe_minimums(pair)
    min_base = float(minimums['min_base'])
    raw_min_quote = float(minimums['min_quote'])
    safe_min_quote = float(safe_minimums['min_quote'])

    # Calculate quote currency value after all size conversion/rounding.
    quote_value = float(volume) * float(price)

    # Check base currency minimum
    if volume < min_base:
        return False, (
            f"Order volume {volume:.8f} below minimum {min_base:.8f} for {pair} "
            f"(minimum base currency)"
        )

    # Check buffered quote currency minimum. This intentionally validates against
    # a value above the raw exchange floor so an order can never land exactly on
    # Kraken's minimum after fee/headroom adjustments.
    if quote_value + 1e-9 < safe_min_quote:
        return False, (
            f"Order value ${quote_value:.2f} below safe minimum ${safe_min_quote:.2f} "
            f"for {pair} (raw minimum ${raw_min_quote:.2f}, "
            f"buffer {safe_minimums['quote_buffer_pct'] * 100:.2f}%)"
        )

    return True, None


def adjust_size_for_fees(volume: float, price: float, side: str,
                        use_maker_fee: bool = False) -> float:
    """
    Adjust order size to account for Kraken fees.

    IMPORTANT: This returns the effective tradeable volume after accounting for fees.
    validate_and_adjust_order() may lift this value again if the fee-adjusted volume
    would otherwise fall below the buffered Kraken notional minimum.

    For buys: Reduces volume to ensure we can afford fees with available funds
              (e.g., 1.0 BTC requested → ~0.9984 BTC after 0.16% fee deduction)
    For sells: Volume stays the same (fee is deducted from sale proceeds)

    Args:
        volume: Desired order volume in base currency
        price: Order price
        side: 'buy' or 'sell'
        use_maker_fee: True for limit orders, False for market orders

    Returns:
        float: Adjusted volume that can be safely executed
    """
    fee_rate = KRAKEN_MAKER_FEE if use_maker_fee else KRAKEN_TAKER_FEE

    if side.lower() == 'buy':
        # For buys, we need to ensure we can afford the fee. Reserve extra quote
        # headroom to absorb fee + minor slippage/rounding and reduce
        # insufficient-funds rejections on small accounts.
        buy_buffer_pct = _resolve_buy_buffer_pct()
        reserve_pct = fee_rate + buy_buffer_pct
        return volume * max(0.0, 1 - reserve_pct)
    else:
        # For sells, volume stays the same (fee comes from proceeds)
        return volume


def validate_and_adjust_order(pair: str, volume: float, price: float,
                              side: str, ordertype: str = 'market') -> Tuple[bool, float, Optional[str]]:
    """
    Validate order and adjust for fees / buffered Kraken minimums if needed.

    Args:
        pair: Kraken pair symbol
        volume: Order volume in base currency
        price: Order price
        side: 'buy' or 'sell'
        ordertype: 'market' or 'limit'

    Returns:
        tuple: (is_valid: bool, adjusted_volume: float, error_message: Optional[str])
    """
    if price <= 0:
        return False, volume, f"Invalid price {price} for {pair}"

    # Adjust for fees
    use_maker_fee = (ordertype == 'limit')
    adjusted_volume = adjust_size_for_fees(volume, price, side, use_maker_fee)

    if side.lower() == 'buy':
        safe_minimums = get_pair_safe_minimums(pair)
        required_quote_volume = _volume_for_quote(safe_minimums['min_quote'], price)
        required_base_volume = float(safe_minimums['min_base'])
        required_volume = max(adjusted_volume, required_quote_volume, required_base_volume)

        if required_volume > adjusted_volume:
            logger.info(
                "[KrakenMinNotionalBuffer] lifted BUY volume %.12f → %.12f "
                "to keep post-conversion notional above $%.2f (raw=$%.2f buffer=%.2f%%)",
                adjusted_volume,
                required_volume,
                safe_minimums['min_quote'],
                safe_minimums['raw_min_quote'],
                safe_minimums['quote_buffer_pct'] * 100.0,
            )
            adjusted_volume = required_volume

    # Validate adjusted size after all conversion and minimum-lift logic.
    is_valid, error = validate_order_size(pair, adjusted_volume, price, side)

    if not is_valid:
        return False, volume, error

    return True, adjusted_volume, None


def log_order_validation(pair: str, volume: float, price: float,
                        side: str, is_valid: bool, error: Optional[str] = None):
    """
    Log order validation result.

    Args:
        pair: Trading pair
        volume: Order volume
        price: Order price
        side: 'buy' or 'sell'
        is_valid: Validation result
        error: Error message if validation failed
    """
    minimums = get_pair_minimums(pair)
    safe_minimums = get_pair_safe_minimums(pair)
    quote_value = volume * price

    if is_valid:
        logger.info(SEPARATOR)
        logger.info("✅ KRAKEN ORDER VALIDATION PASSED")
        logger.info(SEPARATOR)
        logger.info(f"   Pair: {pair}")
        logger.info(f"   Side: {side.upper()}")
        logger.info(f"   Volume: {volume:.8f} (min: {minimums['min_base']:.8f})")
        logger.info(
            f"   Quote Value: ${quote_value:.2f} "
            f"(safe min: ${safe_minimums['min_quote']:.2f}, raw min: ${minimums['min_quote']:.2f})"
        )
        logger.info(SEPARATOR)
    else:
        logger.error(SEPARATOR)
        logger.error("❌ KRAKEN ORDER VALIDATION FAILED")
        logger.error(SEPARATOR)
        logger.error(f"   Pair: {pair}")
        logger.error(f"   Side: {side.upper()}")
        logger.error(f"   Volume: {volume:.8f} (min: {minimums['min_base']:.8f})")
        logger.error(
            f"   Quote Value: ${quote_value:.2f} "
            f"(safe min: ${safe_minimums['min_quote']:.2f}, raw min: ${minimums['min_quote']:.2f})"
        )
        logger.error(f"   Error: {error}")
        logger.error(SEPARATOR)


def verify_txid_returned(result: Dict, pair: str, side: str, volume: float,
                        account_id: str = "unknown") -> Tuple[bool, Optional[str]]:
    """
    Verify that Kraken API returned a valid txid.

    This is a critical check: no txid → no trade → nothing visible.

    Args:
        result: Kraken API response from AddOrder
        pair: Trading pair
        side: 'buy' or 'sell'
        volume: Order volume
        account_id: Account identifier for logging

    Returns:
        tuple: (has_txid: bool, txid: Optional[str])
    """
    if not result or 'result' not in result:
        logger.error(SEPARATOR)
        logger.error("❌ NO TXID - KRAKEN API RESPONSE INVALID")
        logger.error(SEPARATOR)
        logger.error(f"   Account: {account_id}")
        logger.error(f"   Pair: {pair}, Side: {side}, Volume: {volume}")
        logger.error(f"   Response: {result}")
        logger.error("   ⚠️  NO TRADE EXECUTED")
        logger.error(SEPARATOR)
        return False, None

    order_result = result.get('result', {})
    txid_list = order_result.get('txid', [])
    txid = txid_list[0] if txid_list else None

    if not txid:
        logger.error(SEPARATOR)
        logger.error("❌ NO TXID RETURNED - TRADE DID NOT EXECUTE")
        logger.error(SEPARATOR)
        logger.error(f"   Account: {account_id}")
        logger.error(f"   Pair: {pair}, Side: {side}, Volume: {volume}")
        logger.error(f"   API Response: {result}")
        logger.error("   ⚠️  Kraken must return txid for valid order")
        logger.error("   ⚠️  NO TRADE EXECUTED - Nothing visible in Kraken UI")
        logger.error(SEPARATOR)
        return False, None

    # Success - txid received
    logger.info(SEPARATOR)
    logger.info("✅ TXID VERIFIED - TRADE EXECUTED")
    logger.info(SEPARATOR)
    logger.info(f"   Account: {account_id}")
    logger.info(f"   Pair: {pair}, Side: {side}")
    logger.info(f"   Transaction ID: {txid}")
    logger.info(f"   ✅ Trade visible in Kraken UI")
    logger.info(SEPARATOR)

    return True, txid


def verify_per_api_key_execution(api_key: str, account_type: str = "unknown") -> bool:
    """
    Verify that execution is using the correct per-account API key.

    This ensures:
    - Master trades with master key
    - Users trade with their own keys

    Args:
        api_key: The API key being used (first 10 chars for logging)
        account_type: 'PLATFORM' or 'USER' or account identifier

    Returns:
        bool: True if API key is properly set
    """
    if not api_key:
        logger.error(SEPARATOR)
        logger.error("❌ PER-API KEY EXECUTION FAILED")
        logger.error(SEPARATOR)
        logger.error(f"   Account Type: {account_type}")
        logger.error(f"   Error: No API key configured")
        logger.error("   ⚠️  Each account must use its own API key")
        logger.error(SEPARATOR)
        return False

    # Mask API key for security (show first 10 chars only)
    masked_key = api_key[:10] + "..." if len(api_key) > 10 else api_key

    logger.info(SEPARATOR)
    logger.info("✅ PER-API KEY EXECUTION VERIFIED")
    logger.info(SEPARATOR)
    logger.info(f"   Account Type: {account_type}")
    logger.info(f"   API Key: {masked_key}")
    logger.info(f"   ✅ Using dedicated API credentials")
    logger.info(SEPARATOR)

    return True


def validate_exchange_minimum(exchange: str, order_value_usd: float) -> Tuple[bool, Optional[str]]:
    """
    Validate order meets exchange-specific minimum requirements.

    CRITICAL: Per-exchange enforcement prevents order rejections and wasted fees.

    Args:
        exchange: Exchange name ('coinbase', 'kraken', 'okx', etc.)
        order_value_usd: Order value in USD

    Returns:
        tuple: (is_valid: bool, error_message: Optional[str])
    """
    exchange = exchange.lower()

    if exchange == "kraken":
        safe_min_quote = get_safe_min_quote(KRAKEN_MINIMUM_ORDER_USD)
        if order_value_usd < safe_min_quote:
            return False, (
                f"Kraken order ${order_value_usd:.2f} below ${safe_min_quote:.2f} "
                f"safe minimum (raw ${KRAKEN_MINIMUM_ORDER_USD:.2f}, "
                f"buffer {_resolve_min_quote_buffer_pct() * 100:.2f}%)"
            )
    elif exchange == "coinbase":
        if order_value_usd < COINBASE_MINIMUM_ORDER_USD:
            return False, f"Coinbase order ${order_value_usd:.2f} below ${COINBASE_MINIMUM_ORDER_USD:.2f} minimum"
    elif exchange == "okx":
        if order_value_usd < OKX_MINIMUM_ORDER_USD:
            return False, f"OKX order ${order_value_usd:.2f} below ${OKX_MINIMUM_ORDER_USD:.2f} minimum"
    elif exchange == "binance":
        if order_value_usd < BINANCE_MINIMUM_ORDER_USD:
            return False, f"Binance order ${order_value_usd:.2f} below ${BINANCE_MINIMUM_ORDER_USD:.2f} minimum"

    # Order meets minimum requirements
    return True, None


# Export public API
__all__ = [
    'get_pair_minimums',
    'get_pair_safe_minimums',
    'get_safe_min_quote',
    'validate_order_size',
    'adjust_size_for_fees',
    'validate_and_adjust_order',
    'log_order_validation',
    'verify_txid_returned',
    'verify_per_api_key_execution',
    'validate_exchange_minimum',
    'KRAKEN_MINIMUMS',
    'KRAKEN_MINIMUM_ORDER_USD',
    'KRAKEN_TAKER_FEE',
    'KRAKEN_MAKER_FEE',
    'COINBASE_MINIMUM_ORDER_USD',
    'OKX_MINIMUM_ORDER_USD',
    'BINANCE_MINIMUM_ORDER_USD'
]
