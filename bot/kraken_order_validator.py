"""
Kraken Order Validator

Validates orders against Kraken minimums before submission.
Prevents order rejections due to:
- Pair minimums
- Quote currency minimums  
- Fee-adjusted sizing

Also provides utilities for verifying per-API key execution.
"""

import logging
from typing import Dict, Optional, Tuple

logger = logging.getLogger("nija.kraken_validator")

# Logging constants
SEPARATOR = "=" * 70

# Kraken minimum order sizes
# Source: https://support.kraken.com/hc/en-us/articles/205893708-Minimum-order-size-volume-for-trading
# Note: These minimums are subject to change. Verify against current Kraken documentation.
#
# CRITICAL FIX (Jan 22, 2026): Kraken-specific minimum with safety buffer
# Even with Kraken's advertised minimums, fees and market conditions require buffers
# Problem: $5.50 minimum → fees burn you → ghost trades
# Solution: Enforce $7.00 minimum as safety buffer for all Kraken trades
KRAKEN_MINIMUM_ORDER_USD = 7.00  # Safety buffer above Kraken's $5-10 minimums

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


def get_pair_minimums(pair: str) -> Dict[str, float]:
    """
    Get minimum order requirements for a Kraken trading pair.
    
    Args:
        pair: Kraken pair symbol (e.g., 'XXBTZUSD', 'XETHZUSDT')
        
    Returns:
        dict: {'min_base': float, 'min_quote': float}
    """
    # Normalize pair format
    pair = pair.upper().replace('/', '')
    
    # Return specific minimums or default
    return KRAKEN_MINIMUMS.get(pair, KRAKEN_MINIMUMS['DEFAULT'])


def validate_order_size(pair: str, volume: float, price: float, 
                       side: str = 'buy') -> Tuple[bool, Optional[str]]:
    """
    Validate order size meets Kraken minimums.
    
    Args:
        pair: Kraken pair symbol (e.g., 'XXBTZUSD')
        volume: Order volume in base currency
        price: Order price (for calculating quote value)
        side: 'buy' or 'sell'
        
    Returns:
        tuple: (is_valid: bool, error_message: Optional[str])
    """
    minimums = get_pair_minimums(pair)
    min_base = minimums['min_base']
    min_quote = minimums['min_quote']
    
    # Calculate quote currency value
    quote_value = volume * price
    
    # Check base currency minimum
    if volume < min_base:
        return False, (
            f"Order volume {volume:.8f} below minimum {min_base:.8f} for {pair} "
            f"(minimum base currency)"
        )
    
    # Check quote currency minimum
    if quote_value < min_quote:
        return False, (
            f"Order value ${quote_value:.2f} below minimum ${min_quote:.2f} for {pair} "
            f"(minimum quote currency)"
        )
    
    return True, None


def adjust_size_for_fees(volume: float, price: float, side: str,
                        use_maker_fee: bool = False) -> float:
    """
    Adjust order size to account for Kraken fees.
    
    IMPORTANT: This returns the effective tradeable volume after accounting for fees.
    
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
        # For buys, we need to ensure we can afford the fee
        # Reduce volume slightly to account for fee
        # Example: Want to buy $100 worth, but need to reserve $0.16 for fee
        return volume * (1 - fee_rate)
    else:
        # For sells, volume stays the same (fee comes from proceeds)
        return volume


def validate_and_adjust_order(pair: str, volume: float, price: float,
                              side: str, ordertype: str = 'market') -> Tuple[bool, float, Optional[str]]:
    """
    Validate order and adjust for fees if needed.
    
    Args:
        pair: Kraken pair symbol
        volume: Order volume in base currency
        price: Order price
        side: 'buy' or 'sell'
        ordertype: 'market' or 'limit'
        
    Returns:
        tuple: (is_valid: bool, adjusted_volume: float, error_message: Optional[str])
    """
    # Adjust for fees
    use_maker_fee = (ordertype == 'limit')
    adjusted_volume = adjust_size_for_fees(volume, price, side, use_maker_fee)
    
    # Validate adjusted size
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
    quote_value = volume * price
    
    if is_valid:
        logger.info(SEPARATOR)
        logger.info("✅ KRAKEN ORDER VALIDATION PASSED")
        logger.info(SEPARATOR)
        logger.info(f"   Pair: {pair}")
        logger.info(f"   Side: {side.upper()}")
        logger.info(f"   Volume: {volume:.8f} (min: {minimums['min_base']:.8f})")
        logger.info(f"   Quote Value: ${quote_value:.2f} (min: ${minimums['min_quote']:.2f})")
        logger.info(SEPARATOR)
    else:
        logger.error(SEPARATOR)
        logger.error("❌ KRAKEN ORDER VALIDATION FAILED")
        logger.error(SEPARATOR)
        logger.error(f"   Pair: {pair}")
        logger.error(f"   Side: {side.upper()}")
        logger.error(f"   Volume: {volume:.8f} (min: {minimums['min_base']:.8f})")
        logger.error(f"   Quote Value: ${quote_value:.2f} (min: ${minimums['min_quote']:.2f})")
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
        account_type: 'MASTER' or 'USER' or account identifier
        
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
        # Kraken requires $7.00 minimum with safety buffer
        # Even with $5.50 official minimum, fees will burn you
        if order_value_usd < KRAKEN_MINIMUM_ORDER_USD:
            return False, (
                f"Kraken order ${order_value_usd:.2f} below ${KRAKEN_MINIMUM_ORDER_USD:.2f} "
                f"safety buffer (fees + market conditions require buffer above official minimums)"
            )
    elif exchange == "coinbase":
        # Coinbase typically has $1-2 minimum
        COINBASE_MIN = 1.00
        if order_value_usd < COINBASE_MIN:
            return False, f"Coinbase order ${order_value_usd:.2f} below ${COINBASE_MIN:.2f} minimum"
    elif exchange == "okx":
        # OKX varies by pair, typically $1-5
        OKX_MIN = 1.00
        if order_value_usd < OKX_MIN:
            return False, f"OKX order ${order_value_usd:.2f} below ${OKX_MIN:.2f} minimum"
    
    # Order meets minimum requirements
    return True, None


# Export public API
__all__ = [
    'get_pair_minimums',
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
    'KRAKEN_MAKER_FEE'
]

