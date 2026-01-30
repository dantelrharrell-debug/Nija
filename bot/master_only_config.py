"""
NIJA MASTER_ONLY Configuration
A+ Setups Only - Focus on BTC, ETH, SOL

This configuration is for traders who want to:
- Trade independently (no copy trading)
- Focus on top-tier cryptocurrencies only
- Use strict A+ setup criteria
- Maintain conservative risk management
- Work with small account sizes ($74+)

Growth Path: $74 → $100 → $150 → $250 → $500

Author: NIJA Trading Systems
Version: 1.0
Date: January 30, 2026
"""

import os
from typing import List, Dict, Optional

# ============================================================================
# TRADING MODE CONFIGURATION
# ============================================================================

# Master-only mode: Trade independently without copy trading
COPY_TRADING_MODE = "INDEPENDENT"
PRO_MODE = True  # Enable position rotation for capital efficiency

# ============================================================================
# POSITION MANAGEMENT
# ============================================================================

# Maximum concurrent positions - strict limit for focused trading
MAX_POSITIONS = 2

# Position sizing
MIN_TRADE_SIZE_USD = 5.00  # Minimum trade size
LEVERAGE_ENABLED = False  # No leverage trading

# ============================================================================
# RISK MANAGEMENT
# ============================================================================

# Risk per trade: 3-5% range
# This provides aggressive growth while maintaining capital preservation
RISK_PER_TRADE_MIN_PCT = 3.0  # Minimum risk per trade (3%)
RISK_PER_TRADE_MAX_PCT = 5.0  # Maximum risk per trade (5%)

# Default risk (midpoint of range)
DEFAULT_RISK_PER_TRADE_PCT = 4.0  # 4% per trade

# Account-level risk limits
MAX_DAILY_LOSS_PCT = 10.0  # Maximum daily loss (10%)
MAX_TOTAL_EXPOSURE_PCT = 35.0  # Maximum total exposure (35%)

# ============================================================================
# ASSET WHITELIST - A+ SETUPS ONLY
# ============================================================================

# Only trade these top-tier cryptocurrencies
# These assets have:
# - High liquidity
# - Reliable price action
# - Proven track record
# - Strong market structure
WHITELISTED_ASSETS = [
    "BTC-USD",   # Bitcoin - King of crypto
    "ETH-USD",   # Ethereum - Smart contract platform leader
    "SOL-USD",   # Solana - High-performance blockchain
]

# Kraken format variants (if using Kraken)
WHITELISTED_ASSETS_KRAKEN = [
    "XXBTZUSD",  # BTC on Kraken
    "XETHZUSD",  # ETH on Kraken
    "SOLUSD",    # SOL on Kraken
]

# Coinbase format (standard)
WHITELISTED_ASSETS_COINBASE = [
    "BTC-USD",
    "ETH-USD",
    "SOL-USD",
]

def get_whitelisted_symbols(broker: str = "coinbase") -> List[str]:
    """
    Get whitelisted symbols for specific broker.
    
    Args:
        broker: Broker name ("coinbase", "kraken", etc.)
        
    Returns:
        List of whitelisted symbols in broker-specific format
    """
    broker = broker.lower()
    
    if broker == "kraken":
        return WHITELISTED_ASSETS_KRAKEN
    elif broker == "coinbase":
        return WHITELISTED_ASSETS_COINBASE
    else:
        # Default to standard format
        return WHITELISTED_ASSETS


def is_whitelisted_symbol(symbol: str, broker: str = "coinbase") -> bool:
    """
    Check if a symbol is whitelisted for trading.
    
    Args:
        symbol: Symbol to check (e.g., "BTC-USD")
        broker: Broker name for format checking
        
    Returns:
        True if symbol is whitelisted, False otherwise
    """
    whitelisted = get_whitelisted_symbols(broker)
    
    # Check direct match
    if symbol in whitelisted:
        return True
    
    # Check normalized match (handle different formats)
    normalized_symbol = symbol.upper().replace("-", "").replace("/", "")
    for allowed in whitelisted:
        normalized_allowed = allowed.upper().replace("-", "").replace("/", "")
        if normalized_symbol == normalized_allowed:
            return True
    
    return False


# ============================================================================
# QUALITY FILTERS - A+ SETUP CRITERIA
# ============================================================================

# Entry score requirements (higher = more strict)
MIN_ENTRY_SCORE = 8  # Require very high confidence (A+ setups only)

# Technical indicator requirements for A+ setups
A_PLUS_CRITERIA = {
    # RSI requirements (dual RSI strategy)
    "rsi_9_oversold": 30,      # RSI_9 must be below 30 for oversold
    "rsi_14_oversold": 35,     # RSI_14 must be below 35 for oversold
    "rsi_divergence_required": False,  # Divergence not required but adds to score
    
    # Trend requirements
    "min_adx": 25,             # ADX must be above 25 (strong trend)
    "require_ema_alignment": True,  # Price must align with EMAs
    
    # Volume requirements
    "min_volume_multiplier": 1.0,  # Volume must be 100%+ of average
    
    # Volatility requirements
    "min_atr_pct": 0.015,      # ATR must be at least 1.5% (sufficient movement)
    "max_atr_pct": 0.10,       # ATR must not exceed 10% (too volatile)
    
    # Market structure
    "require_clean_chart": True,  # No choppy/ranging conditions
    "block_news_events": False,   # Trade through news (setups override)
}

# Exit criteria for A+ setups
EXIT_CRITERIA = {
    # Profit targets
    "quick_profit_target_pct": 2.0,    # 2% quick profit target
    "standard_profit_target_pct": 5.0,  # 5% standard profit target
    "extended_profit_target_pct": 10.0, # 10% extended profit target
    
    # Stop losses
    "initial_stop_loss_pct": 2.5,   # 2.5% initial stop loss
    "trailing_stop_pct": 1.5,        # 1.5% trailing stop (activated after profit)
    
    # Time-based exits
    "max_hold_time_hours": 48,       # Exit if position held > 48 hours
    "min_hold_time_minutes": 15,     # Don't exit before 15 minutes (avoid chop)
}

# ============================================================================
# GROWTH MILESTONES
# ============================================================================

# Capital growth targets
GROWTH_PATH = {
    "start": 74,
    "milestone_1": 100,   # First milestone: +35% ($26 profit)
    "milestone_2": 150,   # Second milestone: +50% ($50 profit from $100)
    "milestone_3": 250,   # Third milestone: +67% ($100 profit from $150)
    "milestone_4": 500,   # Fourth milestone: +100% ($250 profit from $250)
}

def get_next_milestone(current_balance: float) -> Optional[Dict]:
    """
    Get the next growth milestone.
    
    Args:
        current_balance: Current account balance
        
    Returns:
        Dict with milestone info or None if at final milestone
    """
    for milestone_name, target in [
        ("milestone_1", GROWTH_PATH["milestone_1"]),
        ("milestone_2", GROWTH_PATH["milestone_2"]),
        ("milestone_3", GROWTH_PATH["milestone_3"]),
        ("milestone_4", GROWTH_PATH["milestone_4"]),
    ]:
        if current_balance < target:
            profit_needed = target - current_balance
            percent_gain = (profit_needed / current_balance) * 100 if current_balance > 0 else 0
            return {
                "name": milestone_name,
                "target": target,
                "current": current_balance,
                "profit_needed": profit_needed,
                "percent_gain": percent_gain,
            }
    
    return None  # At or past final milestone


# ============================================================================
# ENVIRONMENT VARIABLE EXPORT
# ============================================================================

def get_env_config() -> Dict[str, str]:
    """
    Get environment variable configuration for MASTER_ONLY mode.
    
    Returns:
        Dict of environment variable names and values
    """
    return {
        'COPY_TRADING_MODE': COPY_TRADING_MODE,
        'PRO_MODE': str(PRO_MODE).lower(),
        'MAX_CONCURRENT_POSITIONS': str(MAX_POSITIONS),
        'MIN_CASH_TO_BUY': str(MIN_TRADE_SIZE_USD),
        'LEVERAGE_ENABLED': str(LEVERAGE_ENABLED).lower(),
    }


# ============================================================================
# USAGE INSTRUCTIONS
# ============================================================================

USAGE_INSTRUCTIONS = """
MASTER_ONLY Mode - A+ Setups Configuration

To activate this configuration:

1. Update your .env file:
   COPY_TRADING_MODE=INDEPENDENT
   PRO_MODE=true
   MAX_CONCURRENT_POSITIONS=2
   MIN_CASH_TO_BUY=5.00

2. The bot will automatically:
   - Only trade BTC, ETH, SOL
   - Require A+ setup criteria (min score 8)
   - Risk 3-5% per trade (default 4%)
   - Maintain maximum 2 positions
   - Block low-liquidity altcoins

3. Growth Path Tracking:
   Start: $74
   → $100 (First milestone: +35%)
   → $150 (Second milestone: +50%)
   → $250 (Third milestone: +67%)
   → $500 (Fourth milestone: +100%)

4. Risk Management:
   - 3-5% risk per trade
   - 10% max daily loss
   - 35% max total exposure
   - No leverage

For questions or support, see documentation at:
- MASTER_ONLY_GUIDE.md
- RISK_PROFILES_GUIDE.md
"""

if __name__ == "__main__":
    print(USAGE_INSTRUCTIONS)
    print("\nEnvironment Configuration:")
    for key, value in get_env_config().items():
        print(f"  {key}={value}")
    
    print("\nWhitelisted Assets:")
    for symbol in WHITELISTED_ASSETS:
        print(f"  ✓ {symbol}")
    
    print("\nA+ Setup Criteria:")
    print(f"  • Min Entry Score: {MIN_ENTRY_SCORE}/10")
    print(f"  • Min ADX: {A_PLUS_CRITERIA['min_adx']}")
    print(f"  • Min Volume: {A_PLUS_CRITERIA['min_volume_multiplier']*100}% of average")
    print(f"  • Clean chart required: {A_PLUS_CRITERIA['require_clean_chart']}")
    
    print("\nGrowth Path:")
    for name, value in GROWTH_PATH.items():
        print(f"  {name}: ${value}")
