"""
NIJA Tier Configuration and Trade Size Minimums

This module defines tier-based minimum trade sizes and stablecoin routing policies.

Tier Structure (OFFICIAL - Updated Jan 23, 2026):
- STARTER ($50-$99): Entry level learning (copy trading recommended)
- SAVER ($100-$249): Absolute minimum where fees, min order size, and risk cap coexist
- INVESTOR ($250-$999): Allows multi-position rotation without hitting risk blocks
- INCOME ($1,000-$4,999): First tier where NIJA trades as designed
- LIVABLE ($5,000-$24,999): Enables pro-style scaling + streak logic
- BALLER ($25,000+): Capital deployment mode (institutional behavior)

⚠️ HARD RULE: Accounts below $100 should use copy trading mode for best results.
Below $100: Fees dominate, exchanges may reject orders, tier enforcement blocks entries.

Author: NIJA Trading Systems
Version: 4.1 (OFFICIAL FUNDING TIERS - $100 MINIMUM RECOMMENDED)
Date: January 23, 2026
"""

import os
from enum import Enum
from typing import Dict, Tuple, Optional, Any
from dataclasses import dataclass
from datetime import datetime
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


@dataclass
class PlatformFundingRules:
    """
    Hard minimum funding requirements for platform accounts per tier.

    These rules ensure platform accounts have sufficient capital to:
    - Execute trades without hitting exchange minimums
    - Maintain position management without lockouts
    - Provide stable signals to copy traders
    - Handle fees and slippage appropriately

    Unlike regular tier minimums (which are balance-based), master funding rules
    define the ABSOLUTE MINIMUM capital a platform account needs at each tier to
    function safely without locking out users.
    """
    tier: TradingTier
    absolute_minimum: float  # Hard floor - master CANNOT operate below this
    recommended_minimum: float  # Recommended minimum for stable operation
    micro_platform_mode: bool  # If True, enables special micro-platform optimizations
    max_trade_size_pct: float  # Maximum % of balance per trade
    min_trade_size_usd: float  # Minimum trade size in USD
    max_positions: int  # Maximum concurrent positions
    requires_copy_trading: bool  # If True, best used with copy trading
    warning_message: str  # Warning to display for this tier

    def validate_funding(self, balance: float) -> Tuple[bool, str]:
        """
        Validate if balance meets minimum funding requirements.

        Args:
            balance: Platform account balance

        Returns:
            Tuple of (is_valid, message)
        """
        if balance < self.absolute_minimum:
            return (False, f"Balance ${balance:.2f} below absolute minimum ${self.absolute_minimum:.2f} for {self.tier.value} tier")

        if balance < self.recommended_minimum:
            return (True, f"Balance ${balance:.2f} meets minimum but below recommended ${self.recommended_minimum:.2f}")

        return (True, f"Balance ${balance:.2f} meets all requirements for {self.tier.value} tier")


# Tier configurations based on RISK_PROFILES_GUIDE.md
# OFFICIAL FUNDING TIERS (Final Version - Jan 23, 2026)
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
        description="Entry level learning (copy trading recommended)",
        min_visible_size=10.0
    ),
    TradingTier.SAVER: TierConfig(
        name="SAVER",
        capital_min=100.0,
        capital_max=249.0,
        risk_per_trade_pct=(10.0, 10.0),  # Fixed at 10% for "Starter-Safe" profile (min=max for tier lock)
        trade_size_min=10.0,  # Minimum $10 (matches Kraken + fee requirements)
        trade_size_max=40.0,
        max_positions=1,  # Single position focus for small accounts
        description="Absolute minimum where fees, min order size, and risk cap coexist",
        min_visible_size=10.0
    ),
    TradingTier.INVESTOR: TierConfig(
        name="INVESTOR",
        capital_min=250.0,
        capital_max=999.0,
        risk_per_trade_pct=(5.0, 7.0),
        trade_size_min=20.0,
        trade_size_max=75.0,
        max_positions=3,
        description="Allows multi-position rotation without hitting risk blocks",
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
        description="First tier where NIJA trades as designed",
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
        description="Enables pro-style scaling + streak logic",
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
        description="Capital deployment mode (institutional behavior)",
        min_visible_size=100.0
    ),
}


# ============================================================================
# PLATFORM ACCOUNT FUNDING RULES
# ============================================================================
# Hard minimum funding requirements for platform accounts
# These ensure platform accounts have enough capital to:
# - Execute meaningful trades
# - Avoid exchange rejection (e.g., Kraken $10 minimum)
# - Provide stable copy trading signals
# - Handle fees without position lockouts
#
# Design Philosophy:
# - MICRO_PLATFORM ($25-$50): Ultra-safe, single position, copy trading optimized
# - STARTER ($50-$99): Learning mode, copy trading recommended
# - SAVER+ ($100+): Full feature operation
# ============================================================================

PLATFORM_FUNDING_RULES: Dict[str, PlatformFundingRules] = {
    # MICRO_PLATFORM: Special tier for $25-$50 accounts
    # Optimized for copy trading with minimal capital
    'MICRO_PLATFORM': PlatformFundingRules(
        tier=TradingTier.STARTER,
        absolute_minimum=25.0,  # Absolute floor: $25
        recommended_minimum=50.0,  # Recommended: $50 for safety
        micro_platform_mode=True,  # Enable micro-platform optimizations
        max_trade_size_pct=40.0,  # Max 40% per trade (conservative)
        min_trade_size_usd=5.0,  # Minimum $5 trades (below Kraken min, Coinbase only)
        max_positions=1,  # Single position only
        requires_copy_trading=False,  # Can operate independently with care
        warning_message=(
            "⚠️ MICRO-PLATFORM MODE ($25-$50): "
            "Use Coinbase (not Kraken). Single position only. "
            "Best for copy trading. Fees will impact profitability."
        )
    ),

    # STARTER: $50-$99 learning tier
    'STARTER': PlatformFundingRules(
        tier=TradingTier.STARTER,
        absolute_minimum=50.0,  # Hard minimum: $50
        recommended_minimum=100.0,  # Recommended: $100 for stable operation
        micro_platform_mode=False,
        max_trade_size_pct=30.0,  # Max 30% per trade
        min_trade_size_usd=10.0,  # Minimum $10 (Kraken compatible)
        max_positions=1,  # Single position
        requires_copy_trading=True,  # Copy trading highly recommended
        warning_message=(
            "⚠️ STARTER PLATFORM ($50-$99): "
            "Below $100 impacts reliability. Copy trading recommended. "
            "Consider upgrading to SAVER tier ($100+)."
        )
    ),

    # SAVER: $100-$249 minimum viable master
    'SAVER': PlatformFundingRules(
        tier=TradingTier.SAVER,
        absolute_minimum=100.0,  # Hard minimum: $100
        recommended_minimum=100.0,  # Same as absolute (this is the floor)
        micro_platform_mode=False,
        max_trade_size_pct=25.0,  # Max 25% per trade
        min_trade_size_usd=10.0,  # Minimum $10
        max_positions=1,  # Single position for safety
        requires_copy_trading=False,  # Can operate independently
        warning_message=(
            "✅ SAVER PLATFORM ($100-$249): "
            "Minimum viable platform account. Single position trading. "
            "Suitable for small-scale copy trading."
        )
    ),

    # INVESTOR: $250-$999 multi-position master
    'INVESTOR': PlatformFundingRules(
        tier=TradingTier.INVESTOR,
        absolute_minimum=250.0,  # Hard minimum: $250
        recommended_minimum=250.0,
        micro_platform_mode=False,
        max_trade_size_pct=22.0,  # Max 22% per trade (tier floor)
        min_trade_size_usd=20.0,  # Minimum $20
        max_positions=3,  # Can handle rotation
        requires_copy_trading=False,
        warning_message=(
            "✅ INVESTOR PLATFORM ($250-$999): "
            "Full multi-position support. Rotation enabled. "
            "Stable for copy trading."
        )
    ),

    # INCOME: $1,000-$4,999 designed operation
    'INCOME': PlatformFundingRules(
        tier=TradingTier.INCOME,
        absolute_minimum=1000.0,  # Hard minimum: $1,000
        recommended_minimum=1000.0,
        micro_platform_mode=False,
        max_trade_size_pct=15.0,  # Max 15% per trade
        min_trade_size_usd=30.0,  # Minimum $30
        max_positions=5,
        requires_copy_trading=False,
        warning_message=(
            "✅ INCOME PLATFORM ($1,000-$4,999): "
            "First tier where NIJA operates as designed. "
            "Professional-grade platform account."
        )
    ),

    # LIVABLE: $5,000-$24,999 pro-style master
    'LIVABLE': PlatformFundingRules(
        tier=TradingTier.LIVABLE,
        absolute_minimum=5000.0,  # Hard minimum: $5,000
        recommended_minimum=5000.0,
        micro_platform_mode=False,
        max_trade_size_pct=10.0,  # Max 10% per trade
        min_trade_size_usd=50.0,  # Minimum $50
        max_positions=6,
        requires_copy_trading=False,
        warning_message=(
            "✅ LIVABLE PLATFORM ($5,000-$24,999): "
            "Pro-style scaling and streak logic. "
            "Institutional-quality platform account."
        )
    ),

    # BALLER: $25,000+ institutional master
    'BALLER': PlatformFundingRules(
        tier=TradingTier.BALLER,
        absolute_minimum=25000.0,  # Hard minimum: $25,000
        recommended_minimum=25000.0,
        micro_platform_mode=False,
        max_trade_size_pct=5.0,  # Max 5% per trade (very conservative)
        min_trade_size_usd=100.0,  # Minimum $100
        max_positions=8,
        requires_copy_trading=False,
        warning_message=(
            "✅ BALLER PLATFORM ($25,000+): "
            "Capital deployment mode. Institutional behavior. "
            "Elite-tier platform account."
        )
    ),
}


# Stablecoin routing policy
STABLECOIN_PAIRS = ["USDT", "USDC", "DAI", "BUSD"]

# HARD MINIMUM BALANCE FOR LIVE TRADING
# Below this amount, fees dominate and Kraken/Coinbase may reject orders
MINIMUM_LIVE_TRADING_BALANCE = 100.0


class StablecoinPolicy(Enum):
    """Stablecoin routing policies."""
    ROUTE_TO_KRAKEN = "route_to_kraken"  # Route all stablecoin trades to Kraken (lower fees)
    BLOCK_ALL = "block_all"  # Block all stablecoin trades
    ALLOW_ALL = "allow_all"  # Allow stablecoin trades on any broker


# Default stablecoin policy: Route to Kraken for lower fees
DEFAULT_STABLECOIN_POLICY = StablecoinPolicy.ROUTE_TO_KRAKEN


def get_tier_from_balance(balance: float, override_tier: str = None, is_platform: bool = False) -> TradingTier:
    """
    Determine trading tier based on account balance.

    IMPORTANT: Platform account is ALWAYS BALLER tier regardless of balance.

    Can be overridden by setting PLATFORM_ACCOUNT_TIER environment variable.
    This is useful for small accounts that need higher tier risk management.

    Args:
        balance: Account balance in USD
        override_tier: Optional tier name to force (e.g., "INVESTOR")
        is_platform: If True, forces BALLER tier (platform account always uses BALLER)

    Returns:
        TradingTier enum
    """
    # CRITICAL: Platform account is ALWAYS BALLER tier
    if is_platform:
        logger.info(f"🎯 Platform account: Using BALLER tier (balance: ${balance:.2f})")
        logger.info(f"   Note: Platform account always uses BALLER tier regardless of balance")
        return TradingTier.BALLER

    # Check for environment variable override first
    env_tier = override_tier or os.getenv('PLATFORM_ACCOUNT_TIER', '').upper()
    if env_tier:
        # Special handling: If set to "BALLER" or "MASTER", force BALLER tier
        if env_tier in ('BALLER', 'PLATFORM'):
            logger.info(f"🎯 Tier override: Using BALLER tier (balance: ${balance:.2f})")
            return TradingTier.BALLER

        # Validate tier name before attempting to use it
        valid_tiers = [tier.name for tier in TradingTier]
        if env_tier not in valid_tiers:
            logger.warning(f"⚠️ Invalid PLATFORM_ACCOUNT_TIER: {env_tier}. Valid options: {', '.join(valid_tiers)}")
            logger.warning(f"   Using balance-based tier instead.")
        else:
            try:
                forced_tier = TradingTier[env_tier]
                logger.info(f"🎯 Tier override: Using {env_tier} tier (balance: ${balance:.2f})")
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


def get_max_trade_size(tier: TradingTier, balance: float, is_platform: bool = False) -> float:
    """
    Get maximum trade size for a tier based on balance.

    PLATFORM ACCOUNT OVERRIDE:
    Platform accounts with BALLER tier get flexible maximums at low balances.

    Args:
        tier: Trading tier
        balance: Account balance
        is_platform: If True, applies platform account rules

    Returns:
        Maximum trade size in USD
    """
    config = get_tier_config(tier)

    # PLATFORM BALLER tier with low balance: use dynamic maximums
    if is_master and tier == TradingTier.BALLER and balance < 25000.0:
        if balance < 100.0:
            flexible_max = balance * 0.50  # 50% max for very small balances
        elif balance < 1000.0:
            flexible_max = balance * 0.40  # 40% max for small balances
        else:
            flexible_max = balance * 0.25  # 25% max for larger balances
        return min(flexible_max, config.trade_size_max)

    return config.trade_size_max


def get_min_trade_size(tier: TradingTier, balance: float, is_platform: bool = False,
                       exchange: str = 'coinbase') -> float:
    """
    Get minimum trade size for a tier based on balance.

    PLATFORM ACCOUNT OVERRIDE:
    Platform accounts with BALLER tier get flexible minimums at low balances.

    EXCHANGE-SPECIFIC MINIMUMS:
    - Kraken: $10.50 (accounts for $10 minimum + fees)
    - Coinbase: $2.00

    Args:
        tier: Trading tier
        balance: Account balance
        is_platform: If True, applies platform account rules
        exchange: Exchange name for minimum validation

    Returns:
        Minimum trade size in USD
    """
    config = get_tier_config(tier)

    # Get exchange-specific minimum
    from position_sizer import get_exchange_min_trade_size
    exchange_min = get_exchange_min_trade_size(exchange)

    # PLATFORM BALLER tier with low balance: use dynamic minimums
    if is_master and tier == TradingTier.BALLER and balance < 25000.0:
        if balance < 100.0:
            flexible_min = max(balance * 0.15, exchange_min)  # 15% or exchange min
        elif balance < 1000.0:
            flexible_min = max(balance * 0.10, exchange_min)  # 10% or exchange min
        else:
            flexible_min = max(balance * 0.05, exchange_min)  # 5% or exchange min
        return min(flexible_min, config.trade_size_min)

    # For regular users, use the greater of tier min or exchange min
    return max(config.trade_size_min, exchange_min)


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


def auto_resize_trade(trade_size: float, tier: TradingTier, balance: float,
                     is_platform: bool = False, exchange: str = 'coinbase') -> Tuple[float, str]:
    """
    Auto-resize trade to fit within tier limits instead of rejecting.

    This is a smarter approach than blocking trades - instead of rejecting trades
    that exceed limits, we automatically resize them to the maximum safe size.

    Example:
        Requested: $11.25
        Allowed max (15%): $9.37
        Executed size: $9.37 (auto-resized)

    Args:
        trade_size: Requested trade size in USD
        tier: Trading tier
        balance: Account balance
        is_platform: If True, applies platform account flexibility rules
        exchange: Exchange name for minimum validation

    Returns:
        Tuple of (resized_trade_size, reason)
        - If no resize needed: (original_size, "valid")
        - If resized: (new_size, "resized from X to Y")
        - If below minimum: (0.0, "below minimum")
    """
    config = get_tier_config(tier)

    # Get exchange-specific minimum
    try:
        from bot.position_sizer import get_exchange_min_trade_size
        exchange_min = get_exchange_min_trade_size(exchange)
    except ImportError:
        try:
            from position_sizer import get_exchange_min_trade_size
            exchange_min = get_exchange_min_trade_size(exchange)
        except ImportError:
            # Fallback to hardcoded minimums
            exchange_min = 10.50 if exchange.lower() == 'kraken' else 2.00

    # Calculate tier-based maximum
    if is_master and tier == TradingTier.BALLER and balance < 25000.0:
        # Platform account with low balance - use flexible max
        max_risk_pct = 50.0 if balance < 100.0 else 25.0
        tier_max = balance * (max_risk_pct / 100.0)
        tier_max = max(tier_max, exchange_min)
    else:
        # Standard tier maximum
        tier_max = config.trade_size_max

        # Also check max risk percentage
        max_risk_pct = 25.0 if (is_master and balance < 1000.0) else config.risk_per_trade_pct[1]
        max_by_risk = balance * (max_risk_pct / 100.0)

        # Use the more restrictive limit
        tier_max = min(tier_max, max_by_risk)

    # Calculate tier minimum
    # PLATFORM BALLER tier with low balance: use flexible minimums (same logic as get_min_trade_size)
    if is_master and tier == TradingTier.BALLER and balance < 25000.0:
        if balance < 100.0:
            flexible_min = max(balance * 0.15, exchange_min)  # 15% or exchange min
        elif balance < 1000.0:
            flexible_min = max(balance * 0.10, exchange_min)  # 10% or exchange min
        else:
            flexible_min = max(balance * 0.05, exchange_min)  # 5% or exchange min
        tier_min = min(flexible_min, config.trade_size_min)
    else:
        tier_min = max(config.trade_size_min, exchange_min)

        # Small balance exception - allow lower minimums if max risk < tier min
        max_risk_by_pct = balance * (config.risk_per_trade_pct[1] / 100.0)
        if max_risk_by_pct < tier_min and not is_platform:
            tier_min = max(exchange_min, max_risk_by_pct)

    original_size = trade_size

    # Check if trade is below minimum
    if trade_size < tier_min:
        return (0.0, f"Trade ${trade_size:.2f} below minimum ${tier_min:.2f} (cannot resize up)")

    # Check if trade exceeds maximum - AUTO-RESIZE
    if trade_size > tier_max:
        resized_size = tier_max
        logger.info(f"📏 AUTO-RESIZE: ${original_size:.2f} → ${resized_size:.2f} (tier max: {tier.value})")
        return (resized_size, f"Auto-resized from ${original_size:.2f} to ${resized_size:.2f} (tier limit)")

    # Trade is within limits
    return (trade_size, "valid")


def validate_trade_size(trade_size: float, tier: TradingTier, balance: float,
                       is_platform: bool = False, exchange: str = 'coinbase') -> Tuple[bool, str]:
    """
    Validate if a trade size is appropriate for the tier.

    DEPRECATED (v4.1, Jan 2026): Will be removed in v5.0 (March 2026)

    Migration Path:
    ---------------
    Use auto_resize_trade() instead for smarter trade handling:

    Old (rejects):
        is_valid, reason = validate_trade_size(size, tier, balance)
        if not is_valid:
            return error

    New (auto-resizes):
        resized_size, reason = auto_resize_trade(size, tier, balance)
        if resized_size == 0.0:
            return error  # Below minimum
        # Use resized_size for trade execution

    PLATFORM ACCOUNT OVERRIDE:
    Platform accounts using BALLER tier can trade with lower minimums when balance is low.
    This allows master to maintain full control even with small funded accounts.

    EXCHANGE-SPECIFIC MINIMUMS:
    - Kraken: $10.50 minimum (accounts for $10 Kraken minimum + fees)
    - Coinbase: $2.00 minimum
    - Other exchanges: $2.00 default

    Args:
        trade_size: Proposed trade size in USD
        tier: Trading tier
        balance: Account balance
        is_platform: If True, applies platform account flexibility rules
        exchange: Exchange name (kraken, coinbase, etc.) for minimum validation

    Returns:
        Tuple of (is_valid, reason)
    """
    config = get_tier_config(tier)

    # Get exchange-specific minimum
    from position_sizer import get_exchange_min_trade_size
    exchange_min = get_exchange_min_trade_size(exchange)

    # PLATFORM ACCOUNT SPECIAL HANDLING FOR BALLER TIER
    # If platform account with BALLER tier and low balance, use dynamic minimums
    if is_master and tier == TradingTier.BALLER and balance < 25000.0:
        # For platform accounts under $25k, use flexible minimums based on balance
        # This keeps master in full control while ensuring safety

        # At low balances, allow 15-50% position sizing for master control
        if balance < 100.0:
            # Very small balances: 15-50% range
            effective_min = max(balance * 0.15, exchange_min)  # Use exchange min or 15%
            effective_max = balance * 0.50  # 50% max
        elif balance < 1000.0:
            # Small balances: 10-40% range
            effective_min = max(balance * 0.10, exchange_min)  # Use exchange min or 10%
            effective_max = balance * 0.40  # 40% max
        else:
            # Larger balances approaching tier minimum: 5-25% range
            effective_min = max(balance * 0.05, exchange_min)  # Use exchange min or 5%
            effective_max = balance * 0.25  # 25% max

        # Ensure we don't exceed tier absolute maximums
        effective_max = min(effective_max, config.trade_size_max)

        logger.info(f"🎯 PLATFORM BALLER tier with low balance (${balance:.2f})")
        logger.info(f"   Exchange: {exchange} (min: ${exchange_min:.2f})")
        logger.info(f"   Adjusted limits: ${effective_min:.2f} - ${effective_max:.2f}")

        if trade_size < effective_min:
            return (False, f"Trade size ${trade_size:.2f} below minimum ${effective_min:.2f} ({exchange} minimum)")

        if trade_size > effective_max:
            return (False, f"Trade size ${trade_size:.2f} exceeds maximum ${effective_max:.2f}")
    else:
        # Standard tier validation for non-master or properly funded accounts
        # Also check exchange minimum for regular users
        tier_min = max(config.trade_size_min, exchange_min)

        # SMALL BALANCE EXCEPTION: For balances where max risk% < tier minimum,
        # allow trades at the max risk% even if below tier minimum
        # Example: $62.49 balance, 15% max = $9.37, but tier min is $10.00
        # In this case, allow $9.37 as it's the maximum allowed by risk limits
        max_risk_by_pct = balance * (config.risk_per_trade_pct[1] / 100.0)

        logger.debug(f"Tier validation: balance=${balance:.2f}, trade=${trade_size:.2f}, "
                    f"tier_min=${tier_min:.2f}, max_risk={config.risk_per_trade_pct[1]:.1f}% (${max_risk_by_pct:.2f})")

        # If the max allowed risk is less than tier minimum, use that instead
        # This ensures small accounts aren't blocked from trading entirely
        # Use same 0.01% tolerance as percentage check for consistency
        if max_risk_by_pct < tier_min and trade_size <= max_risk_by_pct + 0.01:
            # Trade is within risk limits but below tier minimum - allow it
            logger.debug(f"Small balance exception: Allowing ${trade_size:.2f} < ${tier_min:.2f} tier minimum (max risk: ${max_risk_by_pct:.2f})")
            effective_min = exchange_min  # Only enforce exchange minimum
        else:
            effective_min = tier_min

        if trade_size < effective_min:
            if effective_min == exchange_min and exchange_min > config.trade_size_min:
                return (False, f"Trade size ${trade_size:.2f} below {exchange} minimum ${exchange_min:.2f}")
            else:
                return (False, f"Trade size ${trade_size:.2f} below tier minimum ${config.trade_size_min:.2f}")

        if trade_size > config.trade_size_max:
            return (False, f"Trade size ${trade_size:.2f} exceeds tier maximum ${config.trade_size_max:.2f}")

    # Check if trade size is reasonable relative to balance
    # For master with low balance, allow up to 25% risk (more flexible)
    max_risk_pct = 25.0 if (is_master and balance < 1000.0) else config.risk_per_trade_pct[1]

    risk_pct = (trade_size / balance) * 100 if balance > 0 else 0
    # Add small tolerance (0.01%) for floating point precision
    if risk_pct > max_risk_pct + 0.01:
        return (False, f"Trade size {risk_pct:.1f}% of balance exceeds max risk {max_risk_pct:.1f}%")

    return (True, "valid")


def can_trade_live(balance: float, allow_copy_trading: bool = False) -> Tuple[bool, str]:
    """
    Validate if an account can trade live based on balance.

    CRITICAL RULE: Accounts below $100 should NOT trade live independently.

    Below $100:
    - Fees dominate (1.4% round-trip on Coinbase)
    - Kraken rejects orders (minimum $10 + fees)
    - Tier enforcement blocks entries
    - Users think bot is broken (it's not)

    Args:
        balance: Account balance in USD
        allow_copy_trading: If True, allows balances below $100 for copy trading mode

    Returns:
        Tuple of (can_trade, reason)
        - can_trade: True if account can trade live
        - reason: Explanation of decision
    """
    if balance < MINIMUM_LIVE_TRADING_BALANCE:
        if allow_copy_trading:
            # Copy trading mode allows lower balances with proper risk management
            logger.warning(f"⚠️ Balance ${balance:.2f} below recommended ${MINIMUM_LIVE_TRADING_BALANCE:.2f}")
            logger.warning(f"   Copy trading mode enabled - proceeding with caution")
            return (True, f"copy_trading_mode_enabled")
        else:
            # Independent trading requires minimum balance
            logger.error(f"❌ INSUFFICIENT BALANCE: ${balance:.2f} < ${MINIMUM_LIVE_TRADING_BALANCE:.2f} minimum")
            logger.error(f"   Below $100:")
            logger.error(f"   - Fees dominate (1.4% round-trip)")
            logger.error(f"   - Kraken rejects orders")
            logger.error(f"   - Tier enforcement blocks entries")
            logger.error(f"   Please fund account to at least ${MINIMUM_LIVE_TRADING_BALANCE:.2f}")
            return (False, f"balance_below_minimum")

    return (True, "sufficient_balance")


# ============================================================================
# PLATFORM ACCOUNT FUNDING VALIDATION
# ============================================================================

def get_platform_funding_tier(balance: float) -> str:
    """
    Determine the appropriate master funding tier based on balance.

    This is different from regular tier assignment. Master funding tiers
    determine what operational capabilities the platform account has.

    Args:
        balance: Platform account balance in USD

    Returns:
        Platform funding tier name: 'MICRO_PLATFORM', 'STARTER', 'SAVER', etc.
    """
    if balance < 25.0:
        logger.error(f"❌ Platform balance ${balance:.2f} below absolute minimum $25.00")
        return None
    elif balance < 50.0:
        return 'MICRO_PLATFORM'
    elif balance < 100.0:
        return 'STARTER'
    elif balance < 250.0:
        return 'SAVER'
    elif balance < 1000.0:
        return 'INVESTOR'
    elif balance < 5000.0:
        return 'INCOME'
    elif balance < 25000.0:
        return 'LIVABLE'
    else:
        return 'BALLER'


def validate_platform_minimum_funding(balance: float, log_warnings: bool = True) -> Tuple[bool, str, Optional[PlatformFundingRules]]:
    """
    Validate if platform account meets minimum funding requirements.

    This enforces HARD MINIMUMS for platform accounts to prevent:
    - Exchange order rejections
    - Position lockouts
    - Unreliable copy trading signals
    - Fee-dominated trading

    Args:
        balance: Platform account balance in USD
        log_warnings: If True, logs warnings for funding issues

    Returns:
        Tuple of (is_valid, message, funding_rules)
        - is_valid: True if balance meets absolute minimum
        - message: Explanation of funding status
        - funding_rules: PlatformFundingRules object for this tier (or None if invalid)
    """
    # Get master funding tier
    funding_tier_name = get_platform_funding_tier(balance)

    if funding_tier_name is None:
        msg = f"❌ CRITICAL: Master balance ${balance:.2f} below absolute minimum $25.00. Cannot operate."
        if log_warnings:
            logger.error(msg)
            logger.error("   Platform accounts require at least $25 to function.")
            logger.error("   Recommended: $50+ for STARTER, $100+ for stable operation")
        return (False, msg, None)

    # Get funding rules for this tier
    funding_rules = PLATFORM_FUNDING_RULES[funding_tier_name]

    # Validate against funding rules
    is_valid, validation_msg = funding_rules.validate_funding(balance)

    if log_warnings:
        if not is_valid:
            logger.error(f"❌ {validation_msg}")
            logger.error(f"   {funding_rules.warning_message}")
        elif balance < funding_rules.recommended_minimum:
            logger.warning(f"⚠️  {validation_msg}")
            logger.warning(f"   {funding_rules.warning_message}")
            if funding_rules.requires_copy_trading:
                logger.warning(f"   💡 This tier works best with copy trading enabled")
        else:
            logger.info(f"✅ {validation_msg}")
            logger.info(f"   {funding_rules.warning_message}")

        # Log operational constraints
        logger.info(f"📋 Platform Operational Limits ({funding_tier_name}):")
        logger.info(f"   Max Trade Size: {funding_rules.max_trade_size_pct:.1f}% of balance")
        logger.info(f"   Min Trade Size: ${funding_rules.min_trade_size_usd:.2f}")
        logger.info(f"   Max Positions: {funding_rules.max_positions}")
        if funding_rules.micro_platform_mode:
            logger.info(f"   🔧 MICRO-PLATFORM MODE ACTIVE")
            logger.info(f"      - Use Coinbase only (Kraken $10 min not compatible)")
            logger.info(f"      - Single position enforced")
            logger.info(f"      - Best used for copy trading")

    return (is_valid, validation_msg, funding_rules)


def get_platform_trade_limits(balance: float, exchange: str = 'coinbase') -> Dict:
    """
    Get platform account trade limits based on balance and funding tier.

    Returns conservative limits that prevent lockouts and ensure stable operation.

    Args:
        balance: Platform account balance in USD
        exchange: Exchange name for minimum validation

    Returns:
        Dictionary with:
            - tier_name: Master funding tier name
            - min_trade_size: Minimum trade size in USD
            - max_trade_size: Maximum trade size in USD
            - max_positions: Maximum concurrent positions
            - micro_platform_mode: Whether micro-platform optimizations are active
            - warning_message: Important operational warnings
    """
    is_valid, msg, funding_rules = validate_platform_minimum_funding(balance, log_warnings=False)

    if not is_valid or funding_rules is None:
        # Return ultra-conservative limits for invalid/below minimum
        return {
            'tier_name': 'INVALID',
            'min_trade_size': 10.0,
            'max_trade_size': 0.0,  # Cannot trade
            'max_positions': 0,
            'micro_platform_mode': False,
            'warning_message': msg,
            'is_valid': False
        }

    # Calculate max trade size based on percentage limit
    max_trade_size = balance * (funding_rules.max_trade_size_pct / 100.0)

    # Get exchange minimum
    try:
        from bot.position_sizer import get_exchange_min_trade_size
        exchange_min = get_exchange_min_trade_size(exchange)
    except ImportError:
        try:
            from position_sizer import get_exchange_min_trade_size
            exchange_min = get_exchange_min_trade_size(exchange)
        except ImportError:
            # Fallback
            exchange_min = 10.50 if exchange.lower() == 'kraken' else 2.00

    # Use the greater of funding rule minimum or exchange minimum
    min_trade_size = max(funding_rules.min_trade_size_usd, exchange_min)

    # For micro-platform mode on Kraken, warn about incompatibility
    warning = funding_rules.warning_message
    if funding_rules.micro_platform_mode and exchange.lower() == 'kraken':
        warning += " ⚠️ KRAKEN NOT COMPATIBLE WITH MICRO-PLATFORM (use Coinbase)."
        min_trade_size = 10.50  # Kraken enforces this

    return {
        'tier_name': get_platform_funding_tier(balance),
        'min_trade_size': min_trade_size,
        'max_trade_size': max_trade_size,
        'max_positions': funding_rules.max_positions,
        'micro_platform_mode': funding_rules.micro_platform_mode,
        'warning_message': warning,
        'is_valid': is_valid
    }


def is_micro_master(balance: float) -> bool:
    """
    Check if platform account is in micro-platform mode ($25-$49).

    Args:
        balance: Platform account balance

    Returns:
        True if micro-platform mode should be active
    """
    tier = get_platform_funding_tier(balance)
    return tier == 'MICRO_PLATFORM' if tier else False


def log_tier_floors() -> None:
    """
    Log all tier floor configurations at startup for visibility.
    
    This helps verify that tier floor enforcement is configured correctly,
    especially after the INVESTOR tier 22% floor fix (Jan 30, 2026).
    
    Called during risk manager initialization to provide startup diagnostics.
    """
    logger.info("=" * 80)
    logger.info("                    TIER FLOOR CONFIGURATION")
    logger.info("=" * 80)
    logger.info("")
    logger.info("📊 Tier Floors (Position Size Minimums):")
    logger.info("   These floors ensure position sizes don't fall below tier-appropriate levels,")
    logger.info("   even with fee-aware adjustments or quality multipliers.")
    logger.info("")
    
    # Define tier order for display
    tier_order = ['MICRO_PLATFORM', 'STARTER', 'SAVER', 'INVESTOR', 'INCOME', 'LIVABLE', 'BALLER']
    
    for tier_name in tier_order:
        if tier_name in PLATFORM_FUNDING_RULES:
            rules = PLATFORM_FUNDING_RULES[tier_name]
            
            # Format capital range
            capital_min = rules.absolute_minimum
            if tier_name == 'BALLER':
                capital_range = f"${capital_min:,.0f}+"
            elif tier_name == 'MICRO_PLATFORM':
                capital_range = f"${capital_min:.0f}-$50"
            else:
                # Infer max from next tier's min
                next_tier_idx = tier_order.index(tier_name) + 1
                if next_tier_idx < len(tier_order):
                    next_tier = PLATFORM_FUNDING_RULES.get(tier_order[next_tier_idx])
                    if next_tier:
                        capital_max = next_tier.absolute_minimum - 0.01
                        capital_range = f"${capital_min:.0f}-${capital_max:.0f}"
                    else:
                        capital_range = f"${capital_min:.0f}+"
                else:
                    capital_range = f"${capital_min:.0f}+"
            
            # Highlight INVESTOR tier (recent fix)
            highlight = " ← Tier floor fix (Jan 30, 2026)" if tier_name == 'INVESTOR' else ""
            
            # Format tier name with padding
            tier_display = f"{tier_name:12}"
            capital_display = f"{capital_range:18}"
            floor_display = f"{rules.max_trade_size_pct:5.1f}% floor"
            
            logger.info(f"   {tier_display} {capital_display} {floor_display}{highlight}")
    
    logger.info("")
    logger.info("ℹ️  Tier floors prevent LOW_CAPITAL mode and quality multipliers from")
    logger.info("   reducing position sizes below tier-appropriate minimums.")
    logger.info("   This ensures exchange minimums are met and prevents undersized positions.")
    logger.info("=" * 80)
    logger.info("")


def emit_tier_floor_metrics() -> Dict[str, float]:
    """
    Emit tier floor metrics to monitoring system.
    
    Returns tier floor data as a dictionary that can be sent to metrics systems
    like Prometheus, StatsD, Datadog, etc.
    
    This should be called once at startup to register tier floor gauges.
    
    Returns:
        Dict mapping metric names to values
    """
    metrics = {}
    
    tier_order = ['MICRO_PLATFORM', 'STARTER', 'SAVER', 'INVESTOR', 'INCOME', 'LIVABLE', 'BALLER']
    
    for tier_name in tier_order:
        if tier_name in PLATFORM_FUNDING_RULES:
            rules = PLATFORM_FUNDING_RULES[tier_name]
            
            # Create metric name (lowercase, underscores)
            metric_base = f"nija_tier_floor_{tier_name.lower()}"
            
            # Emit floor percentage as gauge
            metrics[f"{metric_base}_pct"] = rules.max_trade_size_pct
            
            # Emit capital range
            metrics[f"{metric_base}_capital_min"] = rules.absolute_minimum
            
            # Emit max positions
            metrics[f"{metric_base}_max_positions"] = float(rules.max_positions)
    
    logger.info(f"📊 Emitted {len(metrics)} tier floor metrics to monitoring system")
    
    return metrics


def assert_expected_tier_floors() -> None:
    """
    Assert that tier floors match expected values in ALL environments.
    
    This validates critical tier floor configurations at startup,
    particularly the INVESTOR tier 22% floor fix (Jan 30, 2026).
    
    IMPORTANT: Assertions run in ALL environments (dev, staging, production).
    This ensures low-capital protection is enforced everywhere and provides
    stronger safety guarantees that Apple reviewers expect.
    
    Raises:
        AssertionError: If any tier floor doesn't match expected value
    """
    import os
    
    # Get environment for logging purposes
    environment = os.getenv('ENVIRONMENT', 'development').lower()
    
    logger.info(f"🔍 Validating tier floor configuration ({environment} environment)...")
    
    # Expected tier floors (updated Jan 30, 2026)
    expected_floors = {
        'MICRO_PLATFORM': 40.0,
        'STARTER': 30.0,
        'SAVER': 25.0,
        'INVESTOR': 22.0,  # CRITICAL: Recent fix from 20% to 22% (Jan 30, 2026)
        'INCOME': 15.0,
        'LIVABLE': 10.0,
        'BALLER': 5.0,
    }
    
    errors = []
    
    for tier_name, expected_floor in expected_floors.items():
        if tier_name not in PLATFORM_FUNDING_RULES:
            errors.append(f"Missing tier configuration: {tier_name}")
            continue
        
        actual_floor = PLATFORM_FUNDING_RULES[tier_name].max_trade_size_pct
        
        if actual_floor != expected_floor:
            errors.append(
                f"Tier {tier_name}: Expected {expected_floor}% floor, got {actual_floor}%"
            )
    
    if errors:
        error_msg = "❌ TIER FLOOR VALIDATION FAILED:\n" + "\n".join(f"  • {e}" for e in errors)
        logger.error(error_msg)
        raise AssertionError(error_msg)
    
    logger.info("✅ All tier floors validated successfully (low-capital protection enforced)")
    logger.info(f"   INVESTOR tier confirmed at 22% floor (Jan 30, 2026 fix)")


def get_tier_floors_for_api() -> Dict[str, Any]:
    """
    Get tier floor data formatted for API/dashboard consumption.
    
    Returns tier floor information in a structured format suitable
    for JSON serialization and display in dashboards.
    
    Returns:
        Dict with tier floor data for all tiers
    """
    tier_order = ['MICRO_PLATFORM', 'STARTER', 'SAVER', 'INVESTOR', 'INCOME', 'LIVABLE', 'BALLER']
    
    tiers = []
    
    for tier_name in tier_order:
        if tier_name in PLATFORM_FUNDING_RULES:
            rules = PLATFORM_FUNDING_RULES[tier_name]
            
            # Determine capital range
            if tier_name == 'BALLER':
                capital_min = rules.absolute_minimum
                capital_max = None
                capital_range = f"${capital_min:,.0f}+"
            elif tier_name == 'MICRO_PLATFORM':
                capital_min = rules.absolute_minimum
                capital_max = 50.0
                capital_range = f"${capital_min:.0f}-${capital_max:.0f}"
            else:
                # Infer max from next tier's min
                next_tier_idx = tier_order.index(tier_name) + 1
                capital_min = rules.absolute_minimum
                if next_tier_idx < len(tier_order):
                    next_tier = PLATFORM_FUNDING_RULES.get(tier_order[next_tier_idx])
                    if next_tier:
                        capital_max = next_tier.absolute_minimum - 0.01
                    else:
                        capital_max = None
                else:
                    capital_max = None
                
                if capital_max:
                    capital_range = f"${capital_min:.0f}-${capital_max:.0f}"
                else:
                    capital_range = f"${capital_min:.0f}+"
            
            tier_data = {
                'name': tier_name,
                'capital_min': capital_min,
                'capital_max': capital_max,
                'capital_range': capital_range,
                'floor_pct': rules.max_trade_size_pct,
                'max_positions': rules.max_positions,
                'min_trade_size_usd': rules.min_trade_size_usd,
                'micro_platform_mode': rules.micro_platform_mode,
                'requires_copy_trading': rules.requires_copy_trading,
                'description': rules.warning_message.split('.')[0],  # First sentence
            }
            
            # Add special note for INVESTOR tier
            if tier_name == 'INVESTOR':
                tier_data['notes'] = 'Tier floor fix implemented Jan 30, 2026 (20% → 22%)'
            
            tiers.append(tier_data)
    
    return {
        'tiers': tiers,
        'generated_at': datetime.now().isoformat(),  # When this response was created
        'last_modified': '2026-01-30',  # When tier config was last updated
        'version': '1.1',  # Version tracking
        'explanation': (
            'Tier floors ensure position sizes don\'t fall below tier-appropriate levels, '
            'even with fee-aware adjustments or quality multipliers. '
            'This ensures exchange minimums are met and prevents undersized positions.'
        )
    }


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

    # Test master funding validation
    print("\n\n" + "="*70)
    print("PLATFORM ACCOUNT FUNDING VALIDATION TESTS")
    print("="*70)

    test_platform_balances = [20, 30, 55, 95, 120, 300, 1500, 30000]
    for platform_balance in test_platform_balances:
        print(f"\n{'='*70}")
        print(f"Testing Platform Balance: ${platform_balance:.2f}")
        print(f"{'='*70}")

        # Validate funding
        is_valid, msg, funding_rules = validate_platform_minimum_funding(
            platform_balance,
            log_warnings=True
        )

        # Get trade limits
        limits = get_platform_trade_limits(platform_balance, exchange='kraken')
        print(f"\n📊 Trade Limits:")
        print(f"   Min Trade: ${limits['min_trade_size']:.2f}")
        print(f"   Max Trade: ${limits['max_trade_size']:.2f}")
        print(f"   Max Positions: {limits['max_positions']}")
        print(f"   Micro-Master: {limits['micro_platform_mode']}")
        print(f"   Valid: {limits['is_valid']}")
