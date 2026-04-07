"""
NIJA Position Sizer
===================

Calculates appropriate position sizes for user accounts based on platform account trades.
Uses equity-based scaling to ensure users trade proportionally to their account size.

Formula:
    user_size = platform_size * (user_balance / platform_balance)

This ensures:
- Users with smaller accounts take smaller positions (risk management)
- Users with larger accounts take larger positions (capital efficiency)
- All users maintain same risk/reward ratio as platform account
"""

import logging
import math
from typing import Dict, Optional

logger = logging.getLogger('nija.position_sizer')

# Minimum position sizes (exchange-specific)
# These prevent creating dust positions that can't be sold
# Updated Apr 2026: Unified to GLOBAL_MIN_TRADE from trading_strategy.py

# Import the single source-of-truth minimum from trading_strategy.
# Fall back to 5.0 if the import is unavailable (e.g. standalone test runs).
try:
    from bot.trading_strategy import GLOBAL_MIN_TRADE as _GLOBAL_MIN_TRADE
except ImportError:
    try:
        from trading_strategy import GLOBAL_MIN_TRADE as _GLOBAL_MIN_TRADE
    except ImportError:
        _GLOBAL_MIN_TRADE = 5.0  # fallback

# KRAKEN: The exchange hard-rejects orders under $10 regardless of GLOBAL_MIN_TRADE.
# KRAKEN_MIN_TRADE_USD is intentionally a separate constant from GLOBAL_MIN_TRADE because
# it represents an immutable exchange-level constraint, not a configurable policy floor.
# The fee buffer (+$0.50) covers ~0.4–0.6% taker fees so the net filled value stays ≥$10.
# If GLOBAL_MIN_TRADE is ever raised above 10.50 the higher value takes precedence.
_KRAKEN_EXCHANGE_FLOOR = 10.50   # Kraken hard minimum: $10 + ~$0.50 fee buffer
KRAKEN_MIN_TRADE_USD = max(_KRAKEN_EXCHANGE_FLOOR, _GLOBAL_MIN_TRADE)  # never below exchange floor

# COINBASE / default: aligned to GLOBAL_MIN_TRADE
COINBASE_MIN_TRADE_USD = _GLOBAL_MIN_TRADE

# Default minimum for other exchanges
MIN_POSITION_USD = _GLOBAL_MIN_TRADE  # Minimum USD value for any position (avoids dust + rejections)

# Exchange-specific minimums (with fee buffers)
EXCHANGE_MIN_TRADE_USD = {
    'kraken': KRAKEN_MIN_TRADE_USD,      # $10.50 (accounts for Kraken $10 min + fees)
    'coinbase': COINBASE_MIN_TRADE_USD,  # GLOBAL_MIN_TRADE
    'okx': _GLOBAL_MIN_TRADE,           # aligned to GLOBAL_MIN_TRADE
    'binance': _GLOBAL_MIN_TRADE,       # aligned to GLOBAL_MIN_TRADE
}

# Per-symbol exchange minimums — some assets have higher notional floors on
# specific exchanges.  These take precedence over the exchange-level defaults
# when the symbol's base currency matches.
SYMBOL_MIN_TRADE_USD: dict = {
    # Coinbase/general — symbols that have known higher rejection thresholds
    'MOVR': 5.0,   # Moonriver — exchange floor makes sub-$5 orders fail
    'HBAR': 5.0,   # Hedera — sub-$5 orders frequently rejected
    'DOT':  5.0,   # Polkadot — sub-$5 orders frequently rejected
    'BAND': 5.0,
    'NMR':  5.0,
    'RLC':  5.0,
}

MIN_BASE_SIZES = {
    # Coinbase minimum order sizes in base currency (updated Mar 2026).
    # Where Coinbase publishes an explicit minimum, that value is used;
    # otherwise a conservative estimate is applied.
    # NOTE: USD values in comments are approximate at Mar 2026 prices.

    # ── Tier 1: Major, high-price assets ───────────────────────────────────
    'BTC':   0.000001,  # ~$0.06 at $60k BTC  (Coinbase: 0.000001)
    'ETH':   0.0001,    # ~$0.30 at $3k ETH
    'BNB':   0.001,     # ~$0.60 at $600 BNB

    # ── Tier 2: Mid-range assets ($50–$500) ────────────────────────────────
    'SOL':   0.01,      # ~$1.50 at $150 SOL
    'AVAX':  0.01,      # ~$0.30 at $30 AVAX
    'LINK':  0.01,      # ~$0.15 at $15 LINK
    'DOT':   0.01,      # ~$0.07 at $7 DOT
    'LTC':   0.001,     # ~$0.08 at $80 LTC
    'BCH':   0.001,     # ~$0.50 at $500 BCH
    'UNI':   0.01,      # ~$0.10 at $10 UNI
    'AAVE':  0.001,     # ~$0.10 at $100 AAVE
    'ATOM':  0.01,      # ~$0.10 at $10 ATOM
    'FIL':   0.01,      # ~$0.05 at $5 FIL
    'ICP':   0.01,      # ~$0.10 at $10 ICP

    # ── Tier 3: Sub-$5 assets ──────────────────────────────────────────────
    'XRP':   1.0,       # ~$0.50 at $0.50 XRP
    'ADA':   1.0,       # ~$0.40 at $0.40 ADA
    'DOGE':  1.0,       # ~$0.15 at $0.15 DOGE
    'MATIC': 1.0,       # ~$0.70 at $0.70 MATIC
    'XLM':   1.0,       # ~$0.10 at $0.10 XLM
    'ALGO':  1.0,       # ~$0.15 at $0.15 ALGO
    'VET':   1.0,       # ~$0.03 at $0.03 VET
    'HBAR':  1.0,       # ~$0.07 at $0.07 HBAR
    'EOS':   1.0,       # ~$0.75 at $0.75 EOS
    'TRX':   1.0,       # ~$0.10 at $0.10 TRX
    'CHZ':   1.0,       # ~$0.10 at $0.10 CHZ

    # ── Tier 4: Very low-price assets (need large base qty) ───────────────
    # These coins require a larger minimum unit count due to their small
    # per-unit price; using the generic 0.0001 fallback would silently allow
    # dust orders that Coinbase rejects.
    'XDC':   100.0,     # ~$5 at $0.05 XDC  (Coinbase explicit minimum)
    'SHIB':  1_000_000, # ~$25 at $0.000025 SHIB
    'PEPE':  1_000_000, # ~$10 at $0.00001 PEPE
    'BONK':  1_000_000, # ~$25 at $0.000025 BONK
    'MANA':  1.0,       # ~$0.40 at $0.40 MANA (Decentraland)
}


def _extract_base_currency(symbol: str) -> str:
    """Extract the base currency from a trading pair symbol.

    Handles dash-style (``"BTC-USD"``, ``"BTC/USD"``) and compact
    (``"BTCUSD"``) formats.  Quote suffixes are stripped in longest-first
    order so that ``"USDCUSD"`` → ``"USDC"`` rather than ``"USDC"`` being
    stripped as ``"USD"``.

    Args:
        symbol: Trading pair in any common format.

    Returns:
        Base currency ticker string (e.g. ``"BTC"``).
    """
    if '-' in symbol or '/' in symbol:
        return symbol.split('-')[0].split('/')[0]
    # Compact format: strip known quote suffixes longest-first to avoid
    # partial matches (e.g. USDC before USD).
    for suffix in ('USDT', 'USDC', 'USD', 'BTC', 'ETH'):
        if symbol.endswith(suffix) and len(symbol) > len(suffix):
            return symbol[: -len(suffix)]
    return symbol


def get_min_base_size(symbol: str) -> float:
    """Return the minimum base-currency order quantity for *symbol*.

    Handles both dash-style (``"BTC-USD"``, ``"BTC/USD"``) and compact
    (``"BTCUSD"``) formats so callers don't need to normalise beforehand.
    Falls back to ``0.0001`` when the base currency is not listed.

    Args:
        symbol: Trading pair in any common format.

    Returns:
        Minimum order size in base currency units.
    """
    return MIN_BASE_SIZES.get(_extract_base_currency(symbol), 0.0001)


def get_exchange_min_trade_size(exchange: str = 'coinbase', symbol: str = '') -> float:
    """
    Get minimum trade size for a specific exchange (with fee buffer included).

    Also checks per-symbol overrides in SYMBOL_MIN_TRADE_USD so that assets
    with known higher rejection thresholds (MOVR, HBAR, DOT, …) always return
    the correct floor regardless of the exchange default.

    Args:
        exchange: Exchange name (kraken, coinbase, okx, binance, etc.)
        symbol:   Optional trading pair (e.g. ``"HBAR-USD"``).  When supplied
                  the per-symbol minimum is checked and the larger of the two
                  values is returned.

    Returns:
        Minimum trade size in USD (includes fee buffer)
    """
    exchange_lower = exchange.lower()
    exchange_min = EXCHANGE_MIN_TRADE_USD.get(exchange_lower, MIN_POSITION_USD)

    if symbol:
        base = _extract_base_currency(symbol)
        symbol_min = SYMBOL_MIN_TRADE_USD.get(base, 0.0)
        return max(exchange_min, symbol_min)

    return exchange_min


def calculate_user_position_size(
    platform_size: float,
    platform_balance: float,
    user_balance: float,
    size_type: str = 'quote',
    symbol: str = None,
    min_position_usd: float = MIN_POSITION_USD
) -> Dict:
    """
    Calculate appropriate position size for a user account.

    Args:
        platform_size: Size of the platform account's trade
        platform_balance: Total balance of platform account
        user_balance: Total balance of user account
        size_type: "quote" (USD amount) or "base" (crypto amount)
        symbol: Trading pair symbol (e.g., "BTC-USD") - used for minimum size validation
        min_position_usd: Minimum position size in USD (default: $1.00)

    Returns:
        Dictionary with:
            - 'size': Calculated position size for user
            - 'size_type': Same as input size_type
            - 'valid': True if position meets minimum requirements
            - 'reason': Explanation if position is invalid
            - 'scale_factor': Ratio of user_balance to platform_balance

    Example:
        Master: $10,000 balance, $500 BTC trade
        User: $1,000 balance
        Result: $50 BTC trade (10% of master size, matching 10% account ratio)
    """
    try:
        # Validate inputs
        if platform_balance <= 0:
            logger.error(f"❌ Invalid platform_balance: {platform_balance}")
            return {
                'size': 0,
                'size_type': size_type,
                'valid': False,
                'reason': f'Invalid master balance: {platform_balance}',
                'scale_factor': 0
            }

        if user_balance <= 0:
            logger.warning(f"⚠️  User has zero or negative balance: {user_balance}")
            return {
                'size': 0,
                'size_type': size_type,
                'valid': False,
                'reason': f'User balance too low: ${user_balance:.2f}',
                'scale_factor': 0
            }

        if platform_size <= 0:
            logger.error(f"❌ Invalid platform_size: {platform_size}")
            return {
                'size': 0,
                'size_type': size_type,
                'valid': False,
                'reason': f'Invalid master size: {platform_size}',
                'scale_factor': 0
            }

        # Calculate scale factor (user equity as % of master equity)
        scale_factor = user_balance / platform_balance

        # Calculate scaled position size
        user_size = platform_size * scale_factor

        logger.info(f"📊 Position Sizing Calculation:")
        logger.info(f"   Platform: ${platform_balance:.2f} balance, {platform_size} size ({size_type})")
        logger.info(f"   User: ${user_balance:.2f} balance")
        logger.info(f"   Scale Factor: {scale_factor:.4f} ({scale_factor*100:.2f}%)")
        logger.info(f"   Calculated User Size: {user_size} ({size_type})")

        # Validate minimum position size
        if size_type == 'quote':
            # For USD-denominated trades, check against minimum USD
            if user_size < min_position_usd:
                logger.warning(f"   ⚠️  Position too small: ${user_size:.2f} < ${min_position_usd:.2f} minimum")
                return {
                    'size': user_size,
                    'size_type': size_type,
                    'valid': False,
                    'reason': f'Position too small: ${user_size:.2f} < ${min_position_usd:.2f} minimum',
                    'scale_factor': scale_factor
                }

        elif size_type == 'base' and symbol:
            # For crypto-denominated trades, check against exchange minimums
            min_base = get_min_base_size(symbol)
            base_currency = _extract_base_currency(symbol)

            if user_size < min_base:
                logger.warning(f"   ⚠️  Position too small: {user_size} {base_currency} < {min_base} minimum")
                return {
                    'size': user_size,
                    'size_type': size_type,
                    'valid': False,
                    'reason': f'Position too small: {user_size} < {min_base} {base_currency} minimum',
                    'scale_factor': scale_factor
                }

        logger.info(f"   ✅ Position size valid: {user_size} ({size_type})")

        return {
            'size': user_size,
            'size_type': size_type,
            'valid': True,
            'reason': 'Position size valid',
            'scale_factor': scale_factor
        }

    except Exception as e:
        logger.error(f"❌ Error calculating position size: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            'size': 0,
            'size_type': size_type,
            'valid': False,
            'reason': f'Calculation error: {e}',
            'scale_factor': 0
        }




def calculate_position_size(
    account_balance: float,
    entry_price: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    atr_pct: float,
    win_rate: float = 0.55,
    broker: str = "kraken",
    max_risk_pct: float = 0.01,    # 1% base risk per trade
    max_position_pct: float = 0.40, # 40% hard cap
) -> float:
    """
    Optimal position size in USD combining four complementary models.

    Models applied (most conservative wins):
      1. Risk-based sizing     — risk exactly ``max_risk_pct`` of balance on the
                                 effective stop (stop + execution friction).
      2. Volatility scalar     — reduce size when ATR > 2%; hold size when calm.
      3. Conservative Kelly    — fraction of balance suggested by the Kelly
                                 criterion, capped at 25% to avoid overbetting.
      4. Hard cap              — never exceed ``max_position_pct`` of balance.

    A trade is **vetoed** (returns 0.0) when the expected net profit after fees,
    spread, and slippage is less than 1.2 %.  This eliminates "death by fees"
    on thin entries.

    Parameters
    ----------
    account_balance : float
        Current trading balance in USD.
    entry_price : float
        Expected fill price (used for base-currency conversion if needed).
    stop_loss_pct : float
        Hard stop distance as a decimal (e.g. 0.02 = 2 %).
    take_profit_pct : float
        Primary take-profit target as a decimal (e.g. 0.035 = 3.5 %).
    atr_pct : float
        Current ATR expressed as a fraction of price (e.g. 0.02 = 2 %).
    win_rate : float
        Estimated win rate for Kelly calculation (default 55 %).
    broker : str
        Broker name — used to look up exchange-specific minimum trade size.
    max_risk_pct : float
        Maximum fraction of balance to risk on one trade (default 1 %).
    max_position_pct : float
        Hard ceiling on position size as a fraction of balance (default 40 %).

    Returns
    -------
    float
        Position size in USD rounded down to 2 decimal places.
        Returns 0.0 when the trade is vetoed by the cost model.
    """
    # ── 1. Broker constraints ─────────────────────────────────────────
    BROKER_MIN_TRADE: Dict[str, float] = {
        "kraken":   10.5,
        "coinbase": 1.0,
        "binance":  10.0,
        "okx":      1.0,
    }
    min_trade = BROKER_MIN_TRADE.get(broker.lower(), 10.0)

    # ── 2. Execution cost model ───────────────────────────────────────
    fee_rate   = 0.0026 * 2  # taker round-trip ≈ 0.52 %
    spread     = 0.004        # bid/ask spread  ≈ 0.40 %
    slippage   = 0.002        # market impact   ≈ 0.20 %
    total_cost = fee_rate + spread + slippage   # ≈ 1.12 %

    # ── 3. Validate trade viability ───────────────────────────────────
    expected_net_profit = take_profit_pct - total_cost
    if expected_net_profit <= 0.012:
        # Require at least 1.2 % real profit after friction — veto otherwise.
        logger.info(
            "calculate_position_size: trade VETOED — net profit %.2f %% ≤ 1.20 %% "
            "(tp=%.2f %%, cost=%.2f %%)",
            expected_net_profit * 100, take_profit_pct * 100, total_cost * 100,
        )
        return 0.0

    # ── 4. Risk-based sizing ──────────────────────────────────────────
    risk_amount  = account_balance * max_risk_pct
    effective_sl = stop_loss_pct + total_cost  # widen SL for friction
    if effective_sl <= 0:
        return 0.0
    position_size_risk = risk_amount / effective_sl

    # ── 5. Volatility scalar (ATR-based) ─────────────────────────────
    # Normalise around a 2 % ATR reference; high ATR → smaller size.
    if atr_pct > 0:
        volatility_scalar = min(1.0, 0.02 / atr_pct)
    else:
        volatility_scalar = 1.0
    position_size_vol = position_size_risk * volatility_scalar

    # ── 6. Conservative Kelly fraction ───────────────────────────────
    edge     = (win_rate * take_profit_pct) - ((1.0 - win_rate) * stop_loss_pct)
    variance = take_profit_pct ** 2
    kelly_fraction    = max(0.0, min(edge / variance if variance > 0 else 0.0, 0.25))
    position_size_kelly = account_balance * kelly_fraction

    # ── 7. Combine models — take the most conservative ────────────────
    raw_size = min(
        position_size_vol,
        position_size_kelly,
        account_balance * max_position_pct,
    )

    # ── 8. Enforce broker minimum ─────────────────────────────────────
    final_size = max(raw_size, min_trade)

    # ── 9. Final hard cap ─────────────────────────────────────────────
    cap = account_balance * max_position_pct
    if final_size > cap:
        final_size = cap

    # ── 10. Round down to 2 decimal places for exchange precision ─────
    final_size = math.floor(final_size * 100) / 100

    logger.debug(
        "calculate_position_size: balance=$%.2f tp=%.2f%% sl=%.2f%% atr=%.2f%% "
        "→ risk=$%.2f vol=$%.2f kelly=$%.2f → final=$%.2f",
        account_balance, take_profit_pct * 100, stop_loss_pct * 100, atr_pct * 100,
        position_size_risk, position_size_vol, position_size_kelly, final_size,
    )
    return final_size


def validate_position_size(
    size: float,
    size_type: str,
    symbol: str = None,
    min_position_usd: float = MIN_POSITION_USD
) -> Dict:
    """
    Validate if a position size meets minimum requirements.

    Args:
        size: Position size to validate
        size_type: "quote" (USD) or "base" (crypto)
        symbol: Trading pair symbol (e.g., "BTC-USD")
        min_position_usd: Minimum position value in USD

    Returns:
        Dictionary with 'valid' (bool) and 'reason' (str)
    """
    try:
        if size <= 0:
            return {'valid': False, 'reason': 'Size must be positive'}

        if size_type == 'quote':
            if size < min_position_usd:
                return {
                    'valid': False,
                    'reason': f'Size ${size:.2f} below minimum ${min_position_usd:.2f}'
                }

        elif size_type == 'base' and symbol:
            min_base = get_min_base_size(symbol)
            base_currency = _extract_base_currency(symbol)

            if size < min_base:
                return {
                    'valid': False,
                    'reason': f'Size {size} {base_currency} below minimum {min_base}'
                }

        return {'valid': True, 'reason': 'Valid position size'}

    except Exception as e:
        logger.error(f"❌ Error validating position size: {e}")
        return {'valid': False, 'reason': f'Validation error: {e}'}


def round_to_exchange_precision(
    size: float,
    symbol: str,
    size_type: str = 'quote'
) -> float:
    """
    Round position size to exchange-specific precision requirements.

    Args:
        size: Position size to round
        symbol: Trading pair symbol (e.g., "BTC-USD")
        size_type: "quote" (USD) or "base" (crypto)

    Returns:
        Rounded position size
    """
    try:
        if size_type == 'quote':
            # USD amounts typically use 2 decimal places
            return round(size, 2)

        elif size_type == 'base' and symbol:
            # Crypto amounts vary by currency
            base_currency = symbol.split('-')[0] if '-' in symbol else symbol

            # Precision map based on typical exchange requirements
            precision_map = {
                'BTC': 8,
                'ETH': 6,
                'SOL': 4,
                'XRP': 2,
                'ADA': 2,
                'DOGE': 2,
                'AVAX': 4,
                'DOT': 4,
                'LINK': 4,
                'LTC': 8,
            }

            precision = precision_map.get(base_currency, 4)  # Default to 4 decimals
            return round(size, precision)

        # Fallback: return original size
        return size

    except Exception as e:
        logger.warning(f"⚠️  Error rounding position size: {e}, returning original")
        return size
