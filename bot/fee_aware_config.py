"""
NIJA Fee-Aware Configuration
Critical profitability settings to overcome Coinbase fees

PROBLEM: Coinbase fees (2-4% per side = 6-8% round-trip) destroy profitability 
         on small positions (<$50).

SOLUTION: 
1. Increase minimum position size to $50-100
2. Increase profit targets to cover fees
3. Use limit orders (0.6% vs 3% fees)
4. Reduce trade frequency
5. Only trade high-probability setups

Author: NIJA Trading Systems
Version: 1.0 - PROFITABILITY FOCUSED
Date: December 19, 2025
"""

# ============================================================================
# FEE STRUCTURE (Coinbase Advanced Trade)
# ============================================================================
COINBASE_MARKET_ORDER_FEE = 0.006  # 0.6% (actual taker fee)
COINBASE_LIMIT_ORDER_FEE = 0.004   # 0.4% (actual maker fee)
COINBASE_SPREAD_COST = 0.002       # ~0.2% average spread

# Total round-trip costs:
MARKET_ORDER_ROUND_TRIP = (COINBASE_MARKET_ORDER_FEE * 2) + COINBASE_SPREAD_COST  # 1.4%
LIMIT_ORDER_ROUND_TRIP = (COINBASE_LIMIT_ORDER_FEE * 2) + COINBASE_SPREAD_COST    # 1.0%

# ============================================================================
# MINIMUM VIABLE POSITION SIZING
# ============================================================================
# At different balance levels, what's the minimum trade size?
# UPDATED: Added capital preservation buffer to prevent fund depletion

# For $10.50-50 balance: Trade with 60% positions (leave 40% reserve)
MIN_BALANCE_TO_TRADE = 10.50  # $10.50 minimum to leave room for Coinbase fees
MICRO_BALANCE_THRESHOLD = 50.0
MICRO_BALANCE_POSITION_PCT = 0.60  # 60% max per position (leave 40% buffer)

# For $50-100: Trade with 50% positions (leave 50% reserve for safety)
SMALL_BALANCE_THRESHOLD = 100.0
SMALL_BALANCE_POSITION_PCT = 0.50  # 50% max per position (leave 50% buffer)

# For $100-500: Trade with 40% positions (leave 60% reserve)
MEDIUM_BALANCE_THRESHOLD = 500.0
MEDIUM_BALANCE_POSITION_PCT = 0.40  # 40% max per position (leave 60% buffer)

# For $500+: Normal position sizing (20-25% with reserves)
NORMAL_MIN_POSITION_PCT = 0.10  # 10%
NORMAL_MAX_POSITION_PCT = 0.20  # 20% (reduced from 25%, more conservative)

# ============================================================================
# PROFIT TARGETS (Must exceed fees)
# ============================================================================
# For micro-balances ($10-50), fees are ~2-4% per side, need higher targets
MICRO_BALANCE_MIN_PROFIT_TARGET = 0.035  # 3.5% minimum for tiny positions

# Market orders need 1.4% to break even, add buffer:
MARKET_ORDER_MIN_PROFIT_TARGET = 0.025  # 2.5% minimum target

# Limit orders need 1.0% to break even, add buffer:
LIMIT_ORDER_MIN_PROFIT_TARGET = 0.020   # 2.0% minimum target

# Trailing stop activation (only trail after this profit)
TRAILING_ACTIVATION_MIN = LIMIT_ORDER_MIN_PROFIT_TARGET  # 2.0%

# Take profit levels (scaled above fee threshold)
TP1_TARGET = 0.030  # 3.0% - covers fees + small profit
TP2_TARGET = 0.050  # 5.0% - meaningful profit
TP3_TARGET = 0.080  # 8.0% - excellent trade

# ============================================================================
# STOP LOSS (Tighter to preserve capital)
# ============================================================================
# With small capital, can't afford big losses
MAX_LOSS_SMALL_BALANCE = 0.015   # 1.5% max loss for balances < $100
MAX_LOSS_NORMAL_BALANCE = 0.020  # 2.0% max loss for balances > $100

# Stop loss placement (as % below entry for longs, above for shorts)
STOP_LOSS_SMALL_BALANCE = 0.02   # 2% stop for small accounts
STOP_LOSS_NORMAL = 0.025         # 2.5% stop for normal accounts

# ============================================================================
# TRADE FREQUENCY (Reduce to minimize fees)
# ============================================================================
# Don't overtrade - each trade costs fees
MIN_SECONDS_BETWEEN_TRADES = 300  # 5 minutes minimum between trades
MAX_TRADES_PER_HOUR = 6           # Maximum 6 trades/hour (vs unlimited before)
MAX_TRADES_PER_DAY = 30           # Maximum 30 trades/day (vs 100+ before)

# ============================================================================
# SIGNAL QUALITY FILTERS (Only high-probability trades)
# ============================================================================
# PROFITABILITY FIX: Balanced approach - 3/5 allows good setups while filtering weak ones
MIN_SIGNAL_STRENGTH = 3           # Require 3/5 strength (balanced for crypto volatility)
MIN_ADX_SMALL_BALANCE = 20        # Industry standard for crypto trending
MIN_ADX_NORMAL = 20               # Same ADX threshold for consistency

# RSI tighter ranges for better entries
RSI_OVERSOLD_BUY = 35             # Buy when RSI > 35 (vs 30 before)
RSI_OVERBOUGHT_SELL = 65          # Sell when RSI < 65 (vs 70 before)

# Volume must be significant (balanced - not too strict)
MIN_VOLUME_MULTIPLIER = 0.5       # 50% of average volume (reasonable liquidity)

# ============================================================================
# ORDER TYPE PREFERENCES (Minimize fees)
# ============================================================================
PREFER_LIMIT_ORDERS = True        # Use limit orders when possible
LIMIT_ORDER_OFFSET_PCT = 0.001    # Place limit 0.1% from current price
LIMIT_ORDER_TIMEOUT_SECONDS = 60  # Cancel if not filled in 60s

# When to use market orders (emergency only):
USE_MARKET_ORDERS_ONLY_FOR_EXITS = True  # Only use market for stop losses

# ============================================================================
# POSITION MANAGEMENT
# ============================================================================
# Maximum open positions (reduce to focus capital)
MAX_OPEN_POSITIONS_SMALL = 1      # Only 1 position if balance < $100
MAX_OPEN_POSITIONS_MEDIUM = 2     # Max 2 positions if balance < $500
MAX_OPEN_POSITIONS_NORMAL = 3     # Max 3 positions if balance > $500

# Maximum total exposure (updated with capital preservation)
MAX_TOTAL_EXPOSURE_SMALL = 0.60   # 60% max for small accounts (leave 40% reserve)
MAX_TOTAL_EXPOSURE_NORMAL = 0.40  # 40% max for normal accounts (leave 60% reserve)

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_position_size_pct(account_balance: float) -> float:
    """
    Get recommended position size % based on account balance.
    
    Args:
        account_balance: Current account balance in USD
    
    Returns:
        Position size as decimal (e.g., 0.50 = 50%)
    """
    if account_balance < MIN_BALANCE_TO_TRADE:
        return 0.0  # Don't trade
    elif account_balance < MICRO_BALANCE_THRESHOLD:
        return MICRO_BALANCE_POSITION_PCT  # 90% for $10-50
    elif account_balance < SMALL_BALANCE_THRESHOLD:
        return SMALL_BALANCE_POSITION_PCT  # 80% for $50-100
    elif account_balance < MEDIUM_BALANCE_THRESHOLD:
        return MEDIUM_BALANCE_POSITION_PCT  # 50% for $100-500
    else:
        return NORMAL_MAX_POSITION_PCT  # 25% for $500+


def get_min_profit_target(use_limit_order: bool = True, account_balance: float = 100.0) -> float:
    """
    Get minimum profit target to overcome fees.
    
    Args:
        use_limit_order: True if using limit orders, False for market
        account_balance: Current account balance (affects fee ratio)
    
    Returns:
        Minimum profit target as decimal (e.g., 0.02 = 2%)
    """
    # Micro-balances need higher targets due to higher fee ratios
    if account_balance < MICRO_BALANCE_THRESHOLD:
        return MICRO_BALANCE_MIN_PROFIT_TARGET  # 3.5%
    
    if use_limit_order:
        return LIMIT_ORDER_MIN_PROFIT_TARGET
    else:
        return MARKET_ORDER_MIN_PROFIT_TARGET


def calculate_min_position_size(account_balance: float) -> float:
    """
    Calculate minimum position size in USD.
    
    Args:
        account_balance: Current account balance
    
    Returns:
        Minimum position size in USD
    """
    position_pct = get_position_size_pct(account_balance)
    return account_balance * position_pct


def should_trade(account_balance: float, trades_today: int, 
                last_trade_time: float = 0) -> tuple[bool, str]:
    """
    Check if we should allow trading based on profitability rules.
    
    Args:
        account_balance: Current balance
        trades_today: Number of trades executed today
        last_trade_time: Timestamp of last trade
    
    Returns:
        Tuple of (allow_trade: bool, reason: str)
    """
    import time
    
    # Check 1: Minimum balance
    if account_balance < MIN_BALANCE_TO_TRADE:
        return False, f"Balance ${account_balance:.2f} below minimum ${MIN_BALANCE_TO_TRADE}"
    
    # Check 2: Daily trade limit
    if trades_today >= MAX_TRADES_PER_DAY:
        return False, f"Reached daily limit ({MAX_TRADES_PER_DAY} trades)"
    
    # Check 3: Time between trades
    if last_trade_time > 0:
        seconds_since_last = time.time() - last_trade_time
        if seconds_since_last < MIN_SECONDS_BETWEEN_TRADES:
            wait_time = int(MIN_SECONDS_BETWEEN_TRADES - seconds_since_last)
            return False, f"Wait {wait_time}s before next trade"
    
    return True, "OK to trade"


def get_fee_adjusted_targets(entry_price: float, side: str, 
                            use_limit_order: bool = True) -> dict:
    """
    Calculate fee-adjusted profit targets and stop loss.
    
    Args:
        entry_price: Entry price
        side: 'BUY' or 'SELL'
        use_limit_order: True for limit orders (lower fees)
    
    Returns:
        Dict with tp1, tp2, tp3, stop_loss prices
    """
    min_target = get_min_profit_target(use_limit_order)
    
    if side == 'BUY':
        return {
            'tp1': entry_price * (1 + TP1_TARGET),
            'tp2': entry_price * (1 + TP2_TARGET),
            'tp3': entry_price * (1 + TP3_TARGET),
            'stop_loss': entry_price * (1 - STOP_LOSS_NORMAL),
            'trailing_activation': entry_price * (1 + TRAILING_ACTIVATION_MIN),
            'min_profit_target': entry_price * (1 + min_target)
        }
    else:  # SELL
        return {
            'tp1': entry_price * (1 - TP1_TARGET),
            'tp2': entry_price * (1 - TP2_TARGET),
            'tp3': entry_price * (1 - TP3_TARGET),
            'stop_loss': entry_price * (1 + STOP_LOSS_NORMAL),
            'trailing_activation': entry_price * (1 - TRAILING_ACTIVATION_MIN),
            'min_profit_target': entry_price * (1 - min_target)
        }


# ============================================================================
# CONFIGURATION SUMMARY
# ============================================================================
def print_config_summary():
    """Print configuration summary for verification"""
    print("\n" + "="*70)
    print("NIJA FEE-AWARE CONFIGURATION - PROFITABILITY FOCUSED")
    print("="*70)
    print(f"\n💰 POSITION SIZING:")
    print(f"   Minimum balance to trade: ${MIN_BALANCE_TO_TRADE}")
    print(f"   Small balance (<$100): {SMALL_BALANCE_POSITION_PCT*100}% per trade")
    print(f"   Medium balance ($100-500): {MEDIUM_BALANCE_POSITION_PCT*100}% per trade")
    print(f"   Normal balance (>$500): {NORMAL_MIN_POSITION_PCT*100}-{NORMAL_MAX_POSITION_PCT*100}%")
    
    print(f"\n📊 PROFIT TARGETS (Fee-Aware):")
    print(f"   Minimum (limit orders): {LIMIT_ORDER_MIN_PROFIT_TARGET*100}%")
    print(f"   TP1: {TP1_TARGET*100}%")
    print(f"   TP2: {TP2_TARGET*100}%")
    print(f"   TP3: {TP3_TARGET*100}%")
    
    print(f"\n🛑 RISK MANAGEMENT:")
    print(f"   Stop loss: {STOP_LOSS_NORMAL*100}%")
    print(f"   Max trades/day: {MAX_TRADES_PER_DAY}")
    print(f"   Min time between trades: {MIN_SECONDS_BETWEEN_TRADES}s")
    
    print(f"\n💸 FEE STRUCTURE:")
    print(f"   Limit order round-trip: {LIMIT_ORDER_ROUND_TRIP*100:.1f}%")
    print(f"   Market order round-trip: {MARKET_ORDER_ROUND_TRIP*100:.1f}%")
    print(f"   Prefer limit orders: {PREFER_LIMIT_ORDERS}")
    
    print(f"\n🎯 SIGNAL QUALITY:")
    print(f"   Minimum signal strength: {MIN_SIGNAL_STRENGTH}/5")
    print(f"   Minimum ADX: {MIN_ADX_SMALL_BALANCE} (small), {MIN_ADX_NORMAL} (normal)")
    print(f"   Volume multiplier: {MIN_VOLUME_MULTIPLIER}x")
    
    print("="*70 + "\n")


if __name__ == "__main__":
    print_config_summary()
