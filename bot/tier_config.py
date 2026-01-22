"""
NIJA Tier Configuration and Trade Size Minimums

This module defines tier-based minimum trade sizes and stablecoin routing policies.

Tier Structure (OFFICIAL - Updated Jan 22, 2026):
- STARTER ($50-$99): Entry level learning
- SAVER ($100-$249): Capital preservation + learning
- INVESTOR ($250-$999): Consistent participation
- INCOME ($1,000-$4,999): Serious retail trading
- LIVABLE ($5,000-$24,999): Professional-level execution
- BALLER ($25,000+): Capital deployment

Author: NIJA Trading Systems
Version: 4.0 (OFFICIAL FUNDING TIERS - 6 TIERS)
Date: January 22, 2026
"""

import os
from enum import Enum
from typing import Dict, Tuple, Optional
from dataclasses import dataclass
import logging

logger = logging.getLogger("nija.tier_config")


class TradingTier(Enum):
    """User trading tiers with associated capital ranges."""
    STARTER = "STARTER"
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
# OFFICIAL FUNDING TIERS (Final Version - Jan 22, 2026)
# These are the official capital ranges to be used everywhere in NIJA
TIER_CONFIGS: Dict[TradingTier, TierConfig] = {
    TradingTier.STARTER: TierConfig(
        name="STARTER",
        capital_min=50.0,
        capital_max=99.0,
        risk_per_trade_pct=(10.0, 15.0),
        trade_size_min=10.0,
        trade_size_max=25.0,
        max_positions=1,
        description="Entry level learning",
        min_visible_size=10.0
    ),
    TradingTier.SAVER: TierConfig(
        name="SAVER",
        capital_min=100.0,
        capital_max=249.0,
        risk_per_trade_pct=(7.0, 10.0),
        trade_size_min=15.0,
        trade_size_max=40.0,
        max_positions=2,
        description="Capital preservation + learning",
        min_visible_size=15.0
    ),
    TradingTier.INVESTOR: TierConfig(
        name="INVESTOR",
        capital_min=250.0,
        capital_max=999.0,
        risk_per_trade_pct=(5.0, 7.0),
        trade_size_min=20.0,
        trade_size_max=75.0,
        max_positions=3,
        description="Consistent participation",
        min_visible_size=20.0
    ),
    TradingTier.INCOME: TierConfig(
        name="INCOME",
        capital_min=1000.0,
        capital_max=4999.0,
        risk_per_trade_pct=(3.0, 5.0),
        trade_size_min=30.0,
        trade_size_max=150.0,
        max_positions=5,
        description="Serious retail trading",
        min_visible_size=30.0
    ),
    TradingTier.LIVABLE: TierConfig(
        name="LIVABLE",
        capital_min=5000.0,
        capital_max=24999.0,
        risk_per_trade_pct=(2.0, 3.0),
        trade_size_min=50.0,
        trade_size_max=300.0,
        max_positions=6,
        description="Professional-level execution",
        min_visible_size=50.0
    ),
    TradingTier.BALLER: TierConfig(
        name="BALLER",
        capital_min=25000.0,
        capital_max=float('inf'),
        risk_per_trade_pct=(1.0, 2.0),
        trade_size_min=100.0,
        trade_size_max=1000.0,
        max_positions=8,
        description="Capital deployment",
        min_visible_size=100.0
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


def get_tier_from_balance(balance: float, override_tier: str = None, is_master: bool = False) -> TradingTier:
    """
    Determine trading tier based on account balance.
    
    IMPORTANT: Master account is ALWAYS BALLER tier regardless of balance.
    
    Can be overridden by setting MASTER_ACCOUNT_TIER environment variable.
    This is useful for small accounts that need higher tier risk management.
    
    Args:
        balance: Account balance in USD
        override_tier: Optional tier name to force (e.g., "INVESTOR")
        is_master: If True, forces BALLER tier (master account always uses BALLER)
    
    Returns:
        TradingTier enum
    """
    # CRITICAL: Master account is ALWAYS BALLER tier
    if is_master:
        logger.info(f"🎯 Master account: Using BALLER tier (balance: ${balance:.2f})")
        logger.info(f"   Note: Master account always uses BALLER tier regardless of balance")
        return TradingTier.BALLER
    
    # Check for environment variable override first
    env_tier = override_tier or os.getenv('MASTER_ACCOUNT_TIER', '').upper()
    if env_tier:
        # Special handling: If set to "BALLER" or "MASTER", force BALLER tier
        if env_tier in ('BALLER', 'MASTER'):
            logger.info(f"🎯 Tier override: Using BALLER tier (balance: ${balance:.2f})")
            return TradingTier.BALLER
        
        # Validate tier name before attempting to use it
        valid_tiers = [tier.name for tier in TradingTier]
        if env_tier not in valid_tiers:
            logger.warning(f"⚠️ Invalid MASTER_ACCOUNT_TIER: {env_tier}. Valid options: {', '.join(valid_tiers)}")
            logger.warning(f"   Using balance-based tier instead.")
        else:
            try:
                forced_tier = TradingTier[env_tier]
                logger.info(f"🎯 Tier override active: Using {env_tier} tier (balance: ${balance:.2f})")
                logger.info(f"   Note: Balance-based tier would be {get_tier_from_balance_internal(balance).value}")
                return forced_tier
            except KeyError:
                # Should not happen due to validation above, but keep for safety
                logger.warning(f"⚠️ Failed to apply tier override: {env_tier}. Using balance-based tier.")
    
    return get_tier_from_balance_internal(balance)


def get_tier_from_balance_internal(balance: float) -> TradingTier:
    """
    Internal function to determine trading tier based on account balance only.
    
    Args:
        balance: Account balance in USD
    
    Returns:
        TradingTier enum
    """
    if balance < TIER_CONFIGS[TradingTier.STARTER].capital_min:
        logger.warning(f"Balance ${balance:.2f} below minimum for STARTER tier (${TIER_CONFIGS[TradingTier.STARTER].capital_min:.2f})")
        return TradingTier.STARTER
    
    # Check tiers in reverse order (highest first) to handle boundaries correctly
    tier_order = [
        TradingTier.BALLER,
        TradingTier.LIVABLE,
        TradingTier.INCOME,
        TradingTier.INVESTOR,
        TradingTier.SAVER,
        TradingTier.STARTER
    ]
    
    for tier in tier_order:
        config = TIER_CONFIGS[tier]
        if balance >= config.capital_min:
            return tier
    
    # Fallback (should not reach here)
    return TradingTier.STARTER


def get_tier_config(tier: TradingTier) -> TierConfig:
    """
    Get configuration for a trading tier.
    
    Args:
        tier: TradingTier enum
    
    Returns:
        TierConfig dataclass
    """
    return TIER_CONFIGS[tier]


def get_max_trade_size(tier: TradingTier, balance: float, is_master: bool = False) -> float:
    """
    Get maximum trade size for a tier based on balance.
    
    MASTER ACCOUNT OVERRIDE:
    Master accounts with BALLER tier get flexible maximums at low balances.
    
    Args:
        tier: Trading tier
        balance: Account balance
        is_master: If True, applies master account rules
    
    Returns:
        Maximum trade size in USD
    """
    config = get_tier_config(tier)
    
    # MASTER BALLER tier with low balance: use dynamic maximums
    if is_master and tier == TradingTier.BALLER and balance < 25000.0:
        if balance < 100.0:
            flexible_max = balance * 0.50  # 50% max for very small balances
        elif balance < 1000.0:
            flexible_max = balance * 0.40  # 40% max for small balances
        else:
            flexible_max = balance * 0.25  # 25% max for larger balances
        return min(flexible_max, config.trade_size_max)
    
    return config.trade_size_max


def get_min_trade_size(tier: TradingTier, balance: float, is_master: bool = False) -> float:
    """
    Get minimum trade size for a tier based on balance.
    
    MASTER ACCOUNT OVERRIDE:
    Master accounts with BALLER tier get flexible minimums at low balances.
    
    Args:
        tier: Trading tier
        balance: Account balance
        is_master: If True, applies master account rules
    
    Returns:
        Minimum trade size in USD
    """
    config = get_tier_config(tier)
    
    # MASTER BALLER tier with low balance: use dynamic minimums
    if is_master and tier == TradingTier.BALLER and balance < 25000.0:
        if balance < 100.0:
            flexible_min = max(balance * 0.15, 2.0)  # 15% min or $2
        elif balance < 1000.0:
            flexible_min = balance * 0.10  # 10% min
        else:
            flexible_min = balance * 0.05  # 5% min
        return min(flexible_min, config.trade_size_min)
    
    return config.trade_size_min


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


def validate_trade_size(trade_size: float, tier: TradingTier, balance: float, 
                       is_master: bool = False) -> Tuple[bool, str]:
    """
    Validate if a trade size is appropriate for the tier.
    
    MASTER ACCOUNT OVERRIDE:
    Master accounts using BALLER tier can trade with lower minimums when balance is low.
    This allows master to maintain full control even with small funded accounts.
    
    Args:
        trade_size: Proposed trade size in USD
        tier: Trading tier
        balance: Account balance
        is_master: If True, applies master account flexibility rules
    
    Returns:
        Tuple of (is_valid, reason)
    """
    config = get_tier_config(tier)
    
    # MASTER ACCOUNT SPECIAL HANDLING FOR BALLER TIER
    # If master account with BALLER tier and low balance, use dynamic minimums
    if is_master and tier == TradingTier.BALLER and balance < 25000.0:
        # For master accounts under $25k, use flexible minimums based on balance
        # This keeps master in full control while ensuring safety
        
        # At low balances, allow 15-50% position sizing for master control
        if balance < 100.0:
            # Very small balances: 15-50% range
            effective_min = max(balance * 0.15, 2.0)  # 15% min or $2
            effective_max = balance * 0.50  # 50% max
        elif balance < 1000.0:
            # Small balances: 10-40% range  
            effective_min = balance * 0.10  # 10% min
            effective_max = balance * 0.40  # 40% max
        else:
            # Larger balances approaching tier minimum: 5-25% range
            effective_min = balance * 0.05  # 5% min
            effective_max = balance * 0.25  # 25% max
        
        # Ensure we don't exceed tier absolute maximums
        effective_max = min(effective_max, config.trade_size_max)
        
        logger.info(f"🎯 MASTER BALLER tier with low balance (${balance:.2f})")
        logger.info(f"   Adjusted limits: ${effective_min:.2f} - ${effective_max:.2f}")
        
        if trade_size < effective_min:
            return (False, f"Trade size ${trade_size:.2f} below minimum ${effective_min:.2f}")
        
        if trade_size > effective_max:
            return (False, f"Trade size ${trade_size:.2f} exceeds maximum ${effective_max:.2f}")
    else:
        # Standard tier validation for non-master or properly funded accounts
        if trade_size < config.trade_size_min:
            return (False, f"Trade size ${trade_size:.2f} below tier minimum ${config.trade_size_min:.2f}")
        
        if trade_size > config.trade_size_max:
            return (False, f"Trade size ${trade_size:.2f} exceeds tier maximum ${config.trade_size_max:.2f}")
    
    # Check if trade size is reasonable relative to balance
    # For master with low balance, allow up to 25% risk (more flexible)
    max_risk_pct = 25.0 if (is_master and balance < 1000.0) else config.risk_per_trade_pct[1]
    
    risk_pct = (trade_size / balance) * 100 if balance > 0 else 0
    if risk_pct > max_risk_pct:
        return (False, f"Trade size {risk_pct:.1f}% of balance exceeds max risk {max_risk_pct:.1f}%")
    
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
