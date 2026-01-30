"""
NIJA Best Practice Production Configuration
============================================

Optimal production settings for capital optimization based on extensive
backtesting and real-world performance.

These values represent institutional-grade risk management parameters
that balance growth potential with capital preservation.

Author: NIJA Trading Systems
Version: 1.0
Date: January 30, 2026
"""

# ============================================================================
# ACCOUNT REQUIREMENTS
# ============================================================================

# Minimum account balance required to trade
# Below this threshold, trading is disabled to prevent overtrading with
# insufficient capital for proper risk management
MIN_BALANCE_REQUIRED = 75.00  # $75 minimum account balance

# ============================================================================
# POSITION SIZING
# ============================================================================

# Minimum trade size in USD
# Ensures positions are large enough to:
# 1. Cover trading fees profitably
# 2. Allow meaningful profit potential
# 3. Meet exchange minimum requirements
MIN_TRADE_SIZE = 10.00  # $10 minimum per trade

# Position risk as percentage of account (0.0 - 1.0)
# This is the base risk percentage applied per position
# Higher values = more aggressive, faster growth but higher volatility
# Lower values = more conservative, slower growth but smoother equity curve
POSITION_RISK = 0.20  # 20% base position risk

# Maximum number of concurrent positions
# Controls portfolio diversification and concentration risk
# More positions = more diversification but harder to manage
# Fewer positions = more concentrated but easier to monitor
MAX_POSITIONS = 8  # Maximum 8 concurrent positions

# ============================================================================
# DERIVED PARAMETERS
# ============================================================================

# Maximum risk per position (as percentage)
# This ensures each position doesn't exceed safe risk levels
MAX_RISK_PER_POSITION = POSITION_RISK / MAX_POSITIONS  # 2.5% per position
# With 8 max positions at 20% total risk = 2.5% risk per position

# Minimum position size as percentage of account
# Based on minimum trade size and typical account balance
MIN_POSITION_PCT = MIN_TRADE_SIZE / MIN_BALANCE_REQUIRED  # ~13.3% minimum

# ============================================================================
# RISK-REWARD PARAMETERS
# ============================================================================

# Target risk-reward ratios for different account sizes
RISK_REWARD_TARGETS = {
    'small_account': 3.0,   # < $500: Target 1:3 R:R
    'medium_account': 3.5,  # $500-$2000: Target 1:3.5 R:R
    'large_account': 4.0,   # > $2000: Target 1:4 R:R
}

# Account size thresholds
SMALL_ACCOUNT_THRESHOLD = 500.00
MEDIUM_ACCOUNT_THRESHOLD = 2000.00

# ============================================================================
# COMPOUNDING PARAMETERS
# ============================================================================

# Reinvestment percentages based on account performance
COMPOUNDING_STRATEGY = {
    'initial': 0.75,      # 75% reinvestment rate to start
    'proven': 0.85,       # 85% after proving profitability
    'scaling': 0.90,      # 90% when scaling up
    'max': 0.95,          # 95% maximum reinvestment
}

# Performance thresholds for compounding tier upgrades
COMPOUNDING_THRESHOLDS = {
    'proven_trades': 20,      # Minimum trades to unlock "proven" tier
    'proven_win_rate': 0.55,  # 55% win rate required
    'scaling_profit': 0.25,   # 25% profit to unlock "scaling" tier
}

# ============================================================================
# DRAWDOWN PROTECTION
# ============================================================================

# Drawdown thresholds as percentages
DRAWDOWN_CAUTION = 0.05    # 5% - Reduce position size to 75%
DRAWDOWN_WARNING = 0.10    # 10% - Reduce position size to 50%
DRAWDOWN_DANGER = 0.15     # 15% - Reduce position size to 25%
DRAWDOWN_HALT = 0.20       # 20% - Halt all trading

# ============================================================================
# KELLY CRITERION SETTINGS
# ============================================================================

# Kelly fraction (percentage of full Kelly to use)
# Full Kelly can be aggressive; fractional Kelly reduces volatility
KELLY_FRACTION = 0.25  # Use 25% of full Kelly recommendation

# Minimum trades required before using Kelly Criterion
# Below this, fall back to fixed fractional sizing
KELLY_MIN_TRADES = 20

# ============================================================================
# VOLATILITY TARGETING
# ============================================================================

# Target daily volatility for position sizing
# Positions are scaled to maintain this volatility target
TARGET_DAILY_VOLATILITY = 0.02  # 2% daily target volatility

# Volatility lookback period (days)
VOLATILITY_LOOKBACK_DAYS = 20

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_account_tier(balance: float) -> str:
    """
    Determine account size tier
    
    Args:
        balance: Current account balance
    
    Returns:
        Account tier: 'small', 'medium', or 'large'
    """
    if balance < SMALL_ACCOUNT_THRESHOLD:
        return 'small_account'
    elif balance < MEDIUM_ACCOUNT_THRESHOLD:
        return 'medium_account'
    else:
        return 'large_account'


def get_target_risk_reward(balance: float) -> float:
    """
    Get target risk-reward ratio for account size
    
    Args:
        balance: Current account balance
    
    Returns:
        Target risk-reward ratio
    """
    tier = get_account_tier(balance)
    return RISK_REWARD_TARGETS[tier]


def can_trade(balance: float) -> tuple[bool, str]:
    """
    Check if account meets minimum requirements for trading
    
    Args:
        balance: Current account balance
    
    Returns:
        Tuple of (can_trade, reason)
    """
    if balance < MIN_BALANCE_REQUIRED:
        return (
            False,
            f"Balance ${balance:.2f} below minimum ${MIN_BALANCE_REQUIRED:.2f}"
        )
    return (True, "Account meets minimum requirements")


def get_compounding_tier(trades: int, win_rate: float, profit_pct: float) -> str:
    """
    Determine compounding tier based on performance
    
    Args:
        trades: Total number of trades executed
        win_rate: Win rate (0-1)
        profit_pct: Total profit percentage (0-1)
    
    Returns:
        Compounding tier: 'initial', 'proven', or 'scaling'
    """
    if trades < COMPOUNDING_THRESHOLDS['proven_trades']:
        return 'initial'
    
    if win_rate < COMPOUNDING_THRESHOLDS['proven_win_rate']:
        return 'initial'
    
    if profit_pct >= COMPOUNDING_THRESHOLDS['scaling_profit']:
        return 'scaling'
    
    return 'proven'


def get_reinvestment_rate(trades: int, win_rate: float, profit_pct: float) -> float:
    """
    Get appropriate reinvestment rate based on performance
    
    Args:
        trades: Total number of trades executed
        win_rate: Win rate (0-1)
        profit_pct: Total profit percentage (0-1)
    
    Returns:
        Reinvestment rate (0-1)
    """
    tier = get_compounding_tier(trades, win_rate, profit_pct)
    return COMPOUNDING_STRATEGY[tier]


def get_max_position_size(balance: float) -> float:
    """
    Calculate maximum position size for account
    
    Args:
        balance: Current account balance
    
    Returns:
        Maximum position size in USD
    """
    # Maximum position risk
    max_risk_usd = balance * MAX_RISK_PER_POSITION
    
    # Ensure minimum trade size
    return max(max_risk_usd, MIN_TRADE_SIZE)


def validate_position_size(position_size: float, balance: float) -> tuple[bool, str]:
    """
    Validate that a position size meets requirements
    
    Args:
        position_size: Proposed position size in USD
        balance: Current account balance
    
    Returns:
        Tuple of (is_valid, reason)
    """
    # Check minimum trade size
    if position_size < MIN_TRADE_SIZE:
        return (
            False,
            f"Position ${position_size:.2f} below minimum ${MIN_TRADE_SIZE:.2f}"
        )
    
    # Check maximum position risk
    max_size = get_max_position_size(balance)
    if position_size > max_size:
        return (
            False,
            f"Position ${position_size:.2f} exceeds maximum ${max_size:.2f} "
            f"({MAX_RISK_PER_POSITION*100:.1f}% of balance)"
        )
    
    return (True, "Position size valid")


# ============================================================================
# CONFIGURATION PRESETS
# ============================================================================

# Conservative preset (capital preservation focus)
CONSERVATIVE_CONFIG = {
    'position_risk': 0.10,  # 10% total risk
    'max_positions': 5,     # Fewer positions
    'target_rr': 3.0,       # 1:3 minimum
    'kelly_fraction': 0.20, # More conservative Kelly
    'reinvest_pct': 0.70,   # Lower reinvestment
}

# Balanced preset (recommended for most users)
BALANCED_CONFIG = {
    'position_risk': POSITION_RISK,  # 20% total risk
    'max_positions': MAX_POSITIONS,  # 8 positions
    'target_rr': 3.5,                # 1:3.5 target
    'kelly_fraction': KELLY_FRACTION,# 25% Kelly
    'reinvest_pct': 0.75,            # 75% reinvestment
}

# Aggressive preset (maximum growth focus)
AGGRESSIVE_CONFIG = {
    'position_risk': 0.30,  # 30% total risk
    'max_positions': 10,    # More positions
    'target_rr': 4.0,       # 1:4 minimum
    'kelly_fraction': 0.35, # More aggressive Kelly
    'reinvest_pct': 0.90,   # Higher reinvestment
}


if __name__ == "__main__":
    # Demonstrate configuration usage
    print("=" * 70)
    print("NIJA BEST PRACTICE PRODUCTION CONFIGURATION")
    print("=" * 70)
    print()
    
    # Account requirements
    print("ACCOUNT REQUIREMENTS:")
    print(f"  Minimum Balance: ${MIN_BALANCE_REQUIRED:.2f}")
    print(f"  Minimum Trade Size: ${MIN_TRADE_SIZE:.2f}")
    print()
    
    # Position sizing
    print("POSITION SIZING:")
    print(f"  Base Position Risk: {POSITION_RISK*100:.0f}%")
    print(f"  Max Positions: {MAX_POSITIONS}")
    print(f"  Risk Per Position: {MAX_RISK_PER_POSITION*100:.1f}%")
    print()
    
    # Example for different account sizes
    test_balances = [100, 500, 1000, 5000]
    
    print("EXAMPLES BY ACCOUNT SIZE:")
    for balance in test_balances:
        tier = get_account_tier(balance)
        can_trade_flag, reason = can_trade(balance)
        target_rr = get_target_risk_reward(balance)
        max_pos = get_max_position_size(balance)
        
        print(f"\n  ${balance:.2f} Account ({tier}):")
        print(f"    Can Trade: {can_trade_flag}")
        if not can_trade_flag:
            print(f"    Reason: {reason}")
        else:
            print(f"    Target R:R: 1:{target_rr:.1f}")
            print(f"    Max Position: ${max_pos:.2f}")
            print(f"    Positions Allowed: {min(MAX_POSITIONS, int(balance / max_pos))}")
    
    # Compounding examples
    print("\n" + "=" * 70)
    print("COMPOUNDING TIER EXAMPLES:")
    
    scenarios = [
        (10, 0.60, 0.05, "New trader"),
        (25, 0.58, 0.15, "Proven trader"),
        (50, 0.62, 0.30, "Scaling trader"),
    ]
    
    for trades, win_rate, profit, desc in scenarios:
        tier = get_compounding_tier(trades, win_rate, profit)
        reinvest = get_reinvestment_rate(trades, win_rate, profit)
        
        print(f"\n  {desc}:")
        print(f"    Trades: {trades} | Win Rate: {win_rate*100:.0f}% | Profit: {profit*100:.0f}%")
        print(f"    Tier: {tier}")
        print(f"    Reinvestment: {reinvest*100:.0f}%")
    
    print("\n" + "=" * 70)
