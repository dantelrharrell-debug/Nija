"""
NIJA Tier Configuration and Trade Size Minimums

This module defines tier-based minimum trade sizes and stablecoin routing policies.

Tier Structure:
- SAVER ($25-$99): Learn system, protect capital
- INVESTOR ($100-$249): Build consistency (DEFAULT)
- INCOME ($250-$999): Core retail power tier
- LIVABLE ($1k-$5k): Stable returns, serious users
- BALLER ($5k+): Scale capital, precision deployment

Author: NIJA Trading Systems
Version: 1.0
Date: January 2026
"""

from enum import Enum
from typing import Dict, Tuple, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger("nija.tier_config")


class TradingTier(Enum):
    """User trading tiers with associated capital ranges."""
    SAVER = "SAVER"
    INVESTOR = "INVESTOR"
    INCOME = "INCOME"
    LIVABLE = "LIVABLE"
    BALLER = "BALLER"


@dataclass
class TierConfig:
    """Configuration for a trading tier."""
    name: str
    capital_min: float
    capital_max: float
    risk_per_trade_pct: Tuple[float, float]  # (min, max)
    trade_size_min: float  # Minimum trade size in USD
    trade_size_max: float  # Maximum trade size in USD
    max_positions: int
    description: str
    
    # Minimum VISIBLE trade size (for user display)
    # Trades smaller than this are executed but not shown prominently
    min_visible_size: float = 10.0


# Tier configurations based on RISK_PROFILES_GUIDE.md
TIER_CONFIGS: Dict[TradingTier, TierConfig] = {
    TradingTier.SAVER: TierConfig(
        name="SAVER",
        capital_min=25.0,
        capital_max=99.0,
        risk_per_trade_pct=(10.0, 15.0),
        trade_size_min=2.0,
        trade_size_max=5.0,
        max_positions=1,
        description="Learn the system, protect capital",
        min_visible_size=2.0  # Show all trades for learning
    ),
    TradingTier.INVESTOR: TierConfig(
        name="INVESTOR",
        capital_min=100.0,
        capital_max=249.0,
        risk_per_trade_pct=(7.0, 10.0),
        trade_size_min=10.0,
        trade_size_max=25.0,
        max_positions=3,
        description="Build consistency, reduce randomness",
        min_visible_size=10.0  # Default tier - show all trades
    ),
    TradingTier.INCOME: TierConfig(
        name="INCOME",
        capital_min=250.0,
        capital_max=999.0,
        risk_per_trade_pct=(4.0, 7.0),
        trade_size_min=15.0,
        trade_size_max=50.0,
        max_positions=5,
        description="Core retail power tier - generate returns",
        min_visible_size=15.0  # Show trades >= $15
    ),
    TradingTier.LIVABLE: TierConfig(
        name="LIVABLE",
        capital_min=1000.0,
        capital_max=5000.0,
        risk_per_trade_pct=(2.0, 4.0),
        trade_size_min=25.0,
        trade_size_max=100.0,
        max_positions=6,
        description="Stable returns, serious users",
        min_visible_size=25.0  # Show trades >= $25
    ),
    TradingTier.BALLER: TierConfig(
        name="BALLER",
        capital_min=5000.0,
        capital_max=float('inf'),
        risk_per_trade_pct=(1.0, 2.0),
        trade_size_min=50.0,
        trade_size_max=500.0,
        max_positions=8,
        description="Scale capital, precision deployment",
        min_visible_size=50.0  # Show trades >= $50
    ),
}


# Stablecoin routing policy
STABLECOIN_PAIRS = ["USDT", "USDC", "DAI", "BUSD"]


class StablecoinPolicy(Enum):
    """Stablecoin routing policies."""
    ROUTE_TO_KRAKEN = "route_to_kraken"  # Route all stablecoin trades to Kraken (lower fees)
    BLOCK_ALL = "block_all"  # Block all stablecoin trades
    ALLOW_ALL = "allow_all"  # Allow stablecoin trades on any broker


# Default stablecoin policy: Route to Kraken for lower fees
DEFAULT_STABLECOIN_POLICY = StablecoinPolicy.ROUTE_TO_KRAKEN


def get_tier_from_balance(balance: float) -> TradingTier:
    """
    Determine trading tier based on account balance.
    
    Args:
        balance: Account balance in USD
    
    Returns:
        TradingTier enum
    """
    if balance < TIER_CONFIGS[TradingTier.SAVER].capital_min:
        logger.warning(f"Balance ${balance:.2f} below minimum for SAVER tier (${TIER_CONFIGS[TradingTier.SAVER].capital_min:.2f})")
        return TradingTier.SAVER
    
    for tier, config in TIER_CONFIGS.items():
        if config.capital_min <= balance <= config.capital_max:
            return tier
    
    # If balance exceeds all tiers, return BALLER
    return TradingTier.BALLER


def get_tier_config(tier: TradingTier) -> TierConfig:
    """
    Get configuration for a trading tier.
    
    Args:
        tier: TradingTier enum
    
    Returns:
        TierConfig dataclass
    """
    return TIER_CONFIGS[tier]


def get_min_trade_size(tier: TradingTier, balance: float) -> float:
    """
    Get minimum trade size for a tier based on balance.
    
    Args:
        tier: Trading tier
        balance: Account balance
    
    Returns:
        Minimum trade size in USD
    """
    config = get_tier_config(tier)
    return config.trade_size_min


def get_max_trade_size(tier: TradingTier, balance: float) -> float:
    """
    Get maximum trade size for a tier based on balance.
    
    Args:
        tier: Trading tier
        balance: Account balance
    
    Returns:
        Maximum trade size in USD
    """
    config = get_tier_config(tier)
    return config.trade_size_max


def get_min_visible_size(tier: TradingTier) -> float:
    """
    Get minimum visible trade size for a tier.
    
    Trades smaller than this are executed but not shown prominently in UI.
    
    Args:
        tier: Trading tier
    
    Returns:
        Minimum visible size in USD
    """
    config = get_tier_config(tier)
    return config.min_visible_size


def is_stablecoin_pair(symbol: str) -> bool:
    """
    Check if a trading pair uses a stablecoin quote currency.
    
    Args:
        symbol: Trading pair (e.g., "ETH-USDT", "BTC/USDC")
    
    Returns:
        True if pair uses stablecoin quote
    """
    symbol_upper = symbol.upper()
    for stablecoin in STABLECOIN_PAIRS:
        if symbol_upper.endswith(stablecoin) or f"-{stablecoin}" in symbol_upper or f"/{stablecoin}" in symbol_upper:
            return True
    return False


def get_stablecoin_broker(symbol: str, 
                          preferred_broker: str,
                          policy: StablecoinPolicy = DEFAULT_STABLECOIN_POLICY) -> Tuple[Optional[str], str]:
    """
    Determine which broker should handle a stablecoin trade.
    
    Args:
        symbol: Trading pair
        preferred_broker: User's preferred broker
        policy: Stablecoin routing policy
    
    Returns:
        Tuple of (broker_name or None if blocked, reason)
    """
    if not is_stablecoin_pair(symbol):
        # Not a stablecoin pair, use preferred broker
        return (preferred_broker, "not_stablecoin")
    
    if policy == StablecoinPolicy.BLOCK_ALL:
        return (None, "stablecoin_trades_blocked")
    
    if policy == StablecoinPolicy.ROUTE_TO_KRAKEN:
        if preferred_broker.lower() == "kraken":
            return (preferred_broker, "already_kraken")
        else:
            return ("kraken", "routed_to_kraken_for_lower_fees")
    
    if policy == StablecoinPolicy.ALLOW_ALL:
        return (preferred_broker, "stablecoin_allowed")
    
    # Default: route to Kraken
    return ("kraken", "default_stablecoin_routing")


def should_show_trade_in_feed(trade_size: float, tier: TradingTier) -> bool:
    """
    Determine if a trade should be shown prominently in the activity feed.
    
    Args:
        trade_size: Trade size in USD
        tier: User's trading tier
    
    Returns:
        True if trade should be shown prominently
    """
    min_visible = get_min_visible_size(tier)
    return trade_size >= min_visible


def get_tier_summary() -> Dict[str, Dict]:
    """
    Get summary of all tier configurations.
    
    Returns:
        Dict mapping tier name to config dict
    """
    summary = {}
    for tier, config in TIER_CONFIGS.items():
        summary[tier.value] = {
            'name': config.name,
            'capital_range': f"${config.capital_min:.0f}-${config.capital_max:.0f}",
            'risk_per_trade': f"{config.risk_per_trade_pct[0]:.0f}%-{config.risk_per_trade_pct[1]:.0f}%",
            'trade_size': f"${config.trade_size_min:.0f}-${config.trade_size_max:.0f}",
            'max_positions': config.max_positions,
            'min_visible_size': f"${config.min_visible_size:.0f}",
            'description': config.description
        }
    return summary


def validate_trade_size(trade_size: float, tier: TradingTier, balance: float) -> Tuple[bool, str]:
    """
    Validate if a trade size is appropriate for the tier.
    
    Args:
        trade_size: Proposed trade size in USD
        tier: Trading tier
        balance: Account balance
    
    Returns:
        Tuple of (is_valid, reason)
    """
    config = get_tier_config(tier)
    
    if trade_size < config.trade_size_min:
        return (False, f"Trade size ${trade_size:.2f} below tier minimum ${config.trade_size_min:.2f}")
    
    if trade_size > config.trade_size_max:
        return (False, f"Trade size ${trade_size:.2f} exceeds tier maximum ${config.trade_size_max:.2f}")
    
    # Check if trade size is reasonable relative to balance
    risk_pct = (trade_size / balance) * 100 if balance > 0 else 0
    if risk_pct > config.risk_per_trade_pct[1]:
        return (False, f"Trade size {risk_pct:.1f}% of balance exceeds tier max risk {config.risk_per_trade_pct[1]:.1f}%")
    
    return (True, "valid")


# Example usage logger
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    # Test tier detection
    test_balances = [50, 150, 500, 2500, 10000]
    for balance in test_balances:
        tier = get_tier_from_balance(balance)
        config = get_tier_config(tier)
        print(f"\nBalance: ${balance:.2f}")
        print(f"  Tier: {tier.value}")
        print(f"  Trade Size: ${config.trade_size_min:.2f}-${config.trade_size_max:.2f}")
        print(f"  Min Visible: ${config.min_visible_size:.2f}")
    
    # Test stablecoin routing
    print("\n\nStablecoin Routing Tests:")
    test_pairs = ["BTC-USD", "ETH-USDT", "SOL/USDC", "XRP-EUR"]
    for pair in test_pairs:
        is_stable = is_stablecoin_pair(pair)
        broker, reason = get_stablecoin_broker(pair, "coinbase")
        print(f"\n{pair}:")
        print(f"  Is stablecoin: {is_stable}")
        print(f"  Broker: {broker}")
        print(f"  Reason: {reason}")
    
    # Show tier summary
    print("\n\nTier Summary:")
    import json
    print(json.dumps(get_tier_summary(), indent=2))
