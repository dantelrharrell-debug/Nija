# nija_strategy.py
"""
Position sizing utilities for NIJA.
Assumptions:
- `client` implements get_spot_price(product_id: str) -> float (USD per BTC)
- We will use USD-denominated sizing, then convert to BTC amount before sending the order.
"""

from decimal import Decimal, ROUND_DOWN

# Configurable sizing constants
MIN_PCT = Decimal('0.02')   # 2%
MAX_PCT = Decimal('0.10')   # 10%
HARD_MIN_USD = Decimal('1.00')   # Coinbase typical min order (adjust if needed)
# minimum BTC amount we'll try to place (exchange-specific; change if you know actual min)
MIN_BTC_AMOUNT = Decimal('0.000001')  # ~0.000001 BTC (0.000001 = 100 sats) safe default

# number of decimal places for BTC amount when placing orders
BTC_DECIMALS = 8

def calculate_usd_order_size(account_equity_usd: float) -> Decimal:
    """Calculate USD order size using your min/max % rules and enforcing hard minimum."""
    equity = Decimal(str(account_equity_usd))
    min_by_pct = (equity * MIN_PCT).quantize(Decimal('0.01'), rounding=ROUND_DOWN)
    max_by_pct = (equity * MAX_PCT).quantize(Decimal('0.01'), rounding=ROUND_DOWN)

    # base size is at least the percent minimum
    size = min_by_pct

    # ensure we at least meet HARD_MIN_USD
    if size < HARD_MIN_USD:
        size = HARD_MIN_USD

    # but do not exceed the maximum allowed by pct
    if size > max_by_pct:
        size = max_by_pct

    # final size should never exceed equity
    if size > equity:
        size = equity

    return size.quantize(Decimal('0.01'), rounding=ROUND_DOWN)


def usd_to_btc_amount(usd_amount: Decimal, btc_price_usd: float) -> Decimal:
    """Convert USD to BTC amount and quantize to allowed BTC decimal places.
       Returns Decimal BTC amount.
    """
    price = Decimal(str(btc_price_usd))
    if price <= 0:
        raise ValueError("Invalid BTC price for conversion.")

    raw_btc = (usd_amount / price)
    quant = Decimal('1e-{0}'.format(BTC_DECIMALS))
    btc_amount = raw_btc.quantize(quant, rounding=ROUND_DOWN)

    # enforce min BTC amount
    if btc_amount < MIN_BTC_AMOUNT:
        # Too small to place; return 0 to indicate we shouldn't send order
        return Decimal('0')

    return btc_amount


def build_order_payload(account_equity_usd: float, client, product_id: str = 'BTC-USD') -> dict:
    """
    Returns a payload dict ready for nija_client.create_order:
    {
        'side': 'buy'|'sell',
        'product_id': 'BTC-USD',
        'size_btc': Decimal(...),
        'usd_size': Decimal(...)
    }
    If returned size_btc == 0, caller should skip order (too small).
    """
    usd_size = calculate_usd_order_size(account_equity_usd)

    # get last price from client
    btc_price = client.get_spot_price(product_id)  # implement this in nija_client wrapper
    size_btc = usd_to_btc_amount(usd_size, btc_price)

    payload = {
        'usd_size': usd_size,       # Decimal
        'size_btc': size_btc,      # Decimal (0 if too small)
        'price_usd': Decimal(str(btc_price)),
        'product_id': product_id
    }
    return payload
