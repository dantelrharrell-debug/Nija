"""
NIJA Capital Tier Hierarchy - Position Architecture for $50 → $250k Scaling

This module implements a strict capital-tier based scaling model that solves:
1. Over-diversification at small account sizes (50-60 positions on $50 accounts)
2. No exposure compression (small accounts need FEWER, LARGER positions)
3. No deterministic position limits enforcement

Design Philosophy:
- Small accounts ($50-250): CONCENTRATION (1-3 positions, 40-80% each)
- Medium accounts ($250-5k): MODERATE (3-7 positions, 15-33% each)
- Large accounts ($5k+): DIVERSIFICATION (6-15 positions, 6-16% each)

Key Rules:
- Position count is HARD CAPPED per tier (not advisory)
- Position size minimums ensure profitability after fees
- Exposure compression: smaller accounts = fewer, larger positions
- Scaling progression: smooth growth from $50 to $250k+

Author: NIJA Trading Systems
Version: 1.0
Date: February 18, 2026
"""

import logging
from enum import Enum
from typing import Dict, Tuple, Optional
from dataclasses import dataclass

logger = logging.getLogger("nija.capital_tier_hierarchy")


class CapitalTier(Enum):
    """Capital tiers with associated balance ranges"""
    STARTER = "STARTER"      # $50-99: Learning mode
    SAVER = "SAVER"          # $100-249: Minimum viable trading
    INVESTOR = "INVESTOR"    # $250-999: Multi-position rotation
    INCOME = "INCOME"        # $1k-4,999: Designed trading capacity
    LIVABLE = "LIVABLE"      # $5k-24,999: Pro-style scaling
    BALLER = "BALLER"        # $25k+: Institutional behavior


@dataclass
class TierPositionRules:
    """
    Position architecture rules for each tier.
    
    Attributes:
        tier_name: Name of the tier
        balance_min: Minimum balance for this tier
        balance_max: Maximum balance for this tier
        max_positions: HARD LIMIT on concurrent positions
        min_position_size_usd: Minimum size per position (profitability threshold)
        target_position_pct: Target size as % of capital per position
        concentration_strategy: How to allocate capital (CONCENTRATED/MODERATE/DIVERSIFIED)
        exposure_compression_factor: Multiplier for position size vs diversification tradeoff
    """
    tier_name: str
    balance_min: float
    balance_max: float
    max_positions: int
    min_position_size_usd: float
    target_position_pct: float  # Target % per position
    concentration_strategy: str  # CONCENTRATED, MODERATE, DIVERSIFIED
    exposure_compression_factor: float  # Higher = more concentrated
    
    def calculate_optimal_position_count(self, balance: float) -> int:
        """
        Calculate optimal number of positions based on balance within tier.
        Returns lower count for smaller balances, scales up as balance grows.
        """
        if balance < self.balance_min:
            return 1
        
        # Calculate tier progression (0.0 to 1.0)
        if self.balance_max == float('inf'):
            tier_progress = min((balance - self.balance_min) / 50000, 1.0)  # Cap at 50k for BALLER
        else:
            tier_progress = (balance - self.balance_min) / (self.balance_max - self.balance_min)
        
        # Scale from 1 position to max_positions based on progression
        optimal_count = max(1, int(1 + (self.max_positions - 1) * tier_progress))
        
        return min(optimal_count, self.max_positions)
    
    def calculate_position_size_pct(self, balance: float, position_count: int) -> float:
        """
        Calculate target position size as % of balance.
        Uses exposure compression for small accounts.
        """
        if position_count <= 0:
            return 0.0
        
        # Base allocation: divide capital by position count
        base_pct = 1.0 / position_count
        
        # Apply concentration strategy
        if self.concentration_strategy == "CONCENTRATED":
            # Small accounts: use MORE than equal weight (concentrate capital)
            # e.g., with 2 positions, use 50-60% instead of 50%
            concentration_multiplier = 1.0 + (0.2 * self.exposure_compression_factor)
        elif self.concentration_strategy == "MODERATE":
            # Medium accounts: slight overweight on best signals
            concentration_multiplier = 1.0 + (0.1 * self.exposure_compression_factor)
        else:  # DIVERSIFIED
            # Large accounts: standard equal weighting
            concentration_multiplier = 1.0
        
        target_pct = base_pct * concentration_multiplier
        
        # Ensure minimum position size is met
        min_pct_needed = self.min_position_size_usd / balance if balance > 0 else 0
        target_pct = max(target_pct, min_pct_needed)
        
        # Cap at reasonable maximum (never more than 80% in one position)
        target_pct = min(target_pct, 0.80)
        
        return target_pct
    
    def validate_position_size(self, size_usd: float, balance: float) -> Tuple[bool, str]:
        """
        Validate if a position size meets tier requirements.
        
        Returns:
            (is_valid, reason_if_invalid)
        """
        # Check minimum size
        if size_usd < self.min_position_size_usd:
            return (False, f"Position ${size_usd:.2f} below tier minimum ${self.min_position_size_usd:.2f}")
        
        # Check maximum size (should not exceed 80% of balance)
        max_size = balance * 0.80
        if size_usd > max_size:
            return (False, f"Position ${size_usd:.2f} exceeds maximum ${max_size:.2f} (80% of balance)")
        
        return (True, "")


# ============================================================================
# TIER POSITION ARCHITECTURE
# ============================================================================
# Strict position rules for each capital tier
# Rules are ENFORCED, not advisory

TIER_POSITION_RULES: Dict[CapitalTier, TierPositionRules] = {
    # STARTER ($50-99): EXTREME CONCENTRATION
    # Problem: $50 split into 50 positions = $1 each = IMPOSSIBLE
    # Solution: 1-2 positions MAX, 50-80% each = $25-40 positions
    CapitalTier.STARTER: TierPositionRules(
        tier_name="STARTER",
        balance_min=50.0,
        balance_max=99.0,
        max_positions=2,  # HARD CAP: Maximum 2 positions
        min_position_size_usd=15.0,  # Minimum $15 per position (fee viability)
        target_position_pct=0.60,  # Target 60% per position (concentrated)
        concentration_strategy="CONCENTRATED",
        exposure_compression_factor=1.0  # Maximum concentration
    ),
    
    # SAVER ($100-249): HIGH CONCENTRATION
    # Problem: $150 split into 50 positions = $3 each = Below minimums
    # Solution: 2-3 positions MAX, 40-50% each = $50-75 positions
    CapitalTier.SAVER: TierPositionRules(
        tier_name="SAVER",
        balance_min=100.0,
        balance_max=249.0,
        max_positions=3,  # HARD CAP: Maximum 3 positions
        min_position_size_usd=15.0,  # Minimum $15 per position
        target_position_pct=0.45,  # Target 45% per position
        concentration_strategy="CONCENTRATED",
        exposure_compression_factor=0.9
    ),
    
    # INVESTOR ($250-999): MODERATE CONCENTRATION
    # Transition tier: Begin diversification but still concentrated
    # 3-5 positions, 20-33% each
    CapitalTier.INVESTOR: TierPositionRules(
        tier_name="INVESTOR",
        balance_min=250.0,
        balance_max=999.0,
        max_positions=5,  # HARD CAP: Maximum 5 positions
        min_position_size_usd=20.0,  # Minimum $20 per position
        target_position_pct=0.25,  # Target 25% per position
        concentration_strategy="MODERATE",
        exposure_compression_factor=0.7
    ),
    
    # INCOME ($1k-4,999): BALANCED DIVERSIFICATION
    # First tier where NIJA operates as designed
    # 5-7 positions, 14-20% each
    CapitalTier.INCOME: TierPositionRules(
        tier_name="INCOME",
        balance_min=1000.0,
        balance_max=4999.0,
        max_positions=7,  # HARD CAP: Maximum 7 positions
        min_position_size_usd=30.0,  # Minimum $30 per position
        target_position_pct=0.17,  # Target 17% per position (~1/6)
        concentration_strategy="MODERATE",
        exposure_compression_factor=0.5
    ),
    
    # LIVABLE ($5k-24,999): FULL DIVERSIFICATION
    # Pro-style scaling with multiple positions
    # 6-10 positions, 10-16% each
    CapitalTier.LIVABLE: TierPositionRules(
        tier_name="LIVABLE",
        balance_min=5000.0,
        balance_max=24999.0,
        max_positions=10,  # HARD CAP: Maximum 10 positions
        min_position_size_usd=50.0,  # Minimum $50 per position
        target_position_pct=0.12,  # Target 12% per position (~1/8)
        concentration_strategy="DIVERSIFIED",
        exposure_compression_factor=0.3
    ),
    
    # BALLER ($25k+): INSTITUTIONAL DIVERSIFICATION
    # Full capital deployment with risk management
    # 8-15 positions, 6-12% each
    CapitalTier.BALLER: TierPositionRules(
        tier_name="BALLER",
        balance_min=25000.0,
        balance_max=float('inf'),
        max_positions=15,  # HARD CAP: Maximum 15 positions
        min_position_size_usd=100.0,  # Minimum $100 per position
        target_position_pct=0.10,  # Target 10% per position
        concentration_strategy="DIVERSIFIED",
        exposure_compression_factor=0.2
    ),
}


class CapitalTierHierarchy:
    """
    Capital Tier Hierarchy Manager
    
    Provides tier-aware position management for $50 → $250k scaling:
    - Determines current tier from balance
    - Enforces position count limits
    - Calculates optimal position sizes
    - Validates entry attempts against tier rules
    """
    
    def __init__(self):
        """Initialize the capital tier hierarchy"""
        self.current_tier: Optional[CapitalTier] = None
        self.current_rules: Optional[TierPositionRules] = None
        self.last_balance: float = 0.0
        
        logger.info("📊 Capital Tier Hierarchy initialized - Position architecture active")
    
    def get_tier_from_balance(self, balance: float) -> CapitalTier:
        """
        Determine capital tier from current balance.
        
        Args:
            balance: Current account balance in USD
            
        Returns:
            CapitalTier enum value
        """
        for tier, rules in TIER_POSITION_RULES.items():
            if rules.balance_min <= balance <= rules.balance_max:
                return tier
        
        # Fallback: if balance is below all tiers, use STARTER
        if balance < TIER_POSITION_RULES[CapitalTier.STARTER].balance_min:
            return CapitalTier.STARTER
        
        # If balance exceeds all tiers, use BALLER
        return CapitalTier.BALLER
    
    def update_balance(self, balance: float) -> None:
        """
        Update current balance and tier.
        Logs tier changes.
        """
        previous_tier = self.current_tier
        self.last_balance = balance
        self.current_tier = self.get_tier_from_balance(balance)
        self.current_rules = TIER_POSITION_RULES[self.current_tier]
        
        # Log tier changes
        if previous_tier and previous_tier != self.current_tier:
            logger.info(f"🎉 TIER CHANGE: {previous_tier.value} → {self.current_tier.value} (balance: ${balance:.2f})")
        elif not previous_tier:
            logger.info(f"📊 Initial tier: {self.current_tier.value} (balance: ${balance:.2f})")
    
    def get_max_positions(self, balance: float) -> int:
        """
        Get HARD LIMIT on maximum concurrent positions for current balance.
        
        Args:
            balance: Current account balance
            
        Returns:
            Maximum number of concurrent positions allowed
        """
        tier = self.get_tier_from_balance(balance)
        rules = TIER_POSITION_RULES[tier]
        return rules.max_positions
    
    def get_optimal_position_count(self, balance: float) -> int:
        """
        Get OPTIMAL number of positions for current balance.
        This may be less than max_positions for small balances within a tier.
        
        Args:
            balance: Current account balance
            
        Returns:
            Optimal number of concurrent positions
        """
        tier = self.get_tier_from_balance(balance)
        rules = TIER_POSITION_RULES[tier]
        return rules.calculate_optimal_position_count(balance)
    
    def calculate_target_position_size(self, balance: float, current_position_count: int) -> float:
        """
        Calculate target position size in USD for next position.
        
        Args:
            balance: Current account balance
            current_position_count: Number of currently open positions
            
        Returns:
            Target position size in USD
        """
        tier = self.get_tier_from_balance(balance)
        rules = TIER_POSITION_RULES[tier]
        
        # If we're at max positions, return 0 (can't open more)
        if current_position_count >= rules.max_positions:
            return 0.0
        
        # Calculate positions we plan to have (current + 1)
        planned_positions = current_position_count + 1
        
        # Get target % for this position
        target_pct = rules.calculate_position_size_pct(balance, planned_positions)
        
        # Calculate USD size
        target_size = balance * target_pct
        
        # Ensure minimum
        target_size = max(target_size, rules.min_position_size_usd)
        
        return target_size
    
    def validate_new_position(self, balance: float, current_position_count: int, 
                            proposed_size_usd: float) -> Tuple[bool, str, str]:
        """
        Validate if a new position can be opened.
        
        Args:
            balance: Current account balance
            current_position_count: Number of currently open positions
            proposed_size_usd: Proposed size of new position in USD
            
        Returns:
            Tuple of (is_valid, rejection_code, rejection_message)
            
        Rejection codes:
            - TIER_MAX_POSITIONS: At maximum position count for tier
            - INSUFFICIENT_CAPITAL: Not enough capital for minimum position size
            - POSITION_TOO_SMALL: Position size below tier minimum
            - POSITION_TOO_LARGE: Position size exceeds 80% of balance
        """
        tier = self.get_tier_from_balance(balance)
        rules = TIER_POSITION_RULES[tier]
        
        # Check 1: Position count limit
        if current_position_count >= rules.max_positions:
            return (
                False,
                "TIER_MAX_POSITIONS",
                f"REJECTED: Tier {tier.value} allows maximum {rules.max_positions} positions (current: {current_position_count})"
            )
        
        # Check 2: Minimum capital available
        available_capital = balance * 0.80  # Only use up to 80% of balance
        if available_capital < rules.min_position_size_usd:
            return (
                False,
                "INSUFFICIENT_CAPITAL",
                f"REJECTED: Available capital ${available_capital:.2f} below tier minimum ${rules.min_position_size_usd:.2f}"
            )
        
        # Check 3: Position size validation
        is_valid, size_message = rules.validate_position_size(proposed_size_usd, balance)
        if not is_valid:
            if "below tier minimum" in size_message:
                return (False, "POSITION_TOO_SMALL", f"REJECTED: {size_message}")
            else:
                return (False, "POSITION_TOO_LARGE", f"REJECTED: {size_message}")
        
        # All checks passed
        return (True, "APPROVED", f"APPROVED: Position ${proposed_size_usd:.2f} for tier {tier.value}")
    
    def get_tier_info(self, balance: float) -> Dict:
        """
        Get comprehensive tier information for current balance.
        
        Args:
            balance: Current account balance
            
        Returns:
            Dictionary with tier information and limits
        """
        tier = self.get_tier_from_balance(balance)
        rules = TIER_POSITION_RULES[tier]
        optimal_count = rules.calculate_optimal_position_count(balance)
        
        return {
            'tier': tier.value,
            'balance': balance,
            'balance_range': (rules.balance_min, rules.balance_max),
            'max_positions': rules.max_positions,
            'optimal_positions': optimal_count,
            'min_position_size': rules.min_position_size_usd,
            'target_position_pct': rules.target_position_pct * 100,
            'concentration_strategy': rules.concentration_strategy,
            'compression_factor': rules.exposure_compression_factor
        }
    
    def log_tier_summary(self, balance: float, current_positions: int) -> None:
        """Log comprehensive tier summary"""
        info = self.get_tier_info(balance)
        
        logger.info("="*70)
        logger.info(f"CAPITAL TIER: {info['tier']}")
        logger.info(f"Balance: ${balance:.2f} (${info['balance_range'][0]:.0f} - ${info['balance_range'][1]:.0f})")
        logger.info(f"Positions: {current_positions}/{info['max_positions']} (optimal: {info['optimal_positions']})")
        logger.info(f"Min Position Size: ${info['min_position_size']:.2f}")
        logger.info(f"Target Size: {info['target_position_pct']:.1f}% per position")
        logger.info(f"Strategy: {info['concentration_strategy']} (compression: {info['compression_factor']:.1f})")
        logger.info("="*70)


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================
# Singleton instance for use across modules
_tier_hierarchy_instance: Optional[CapitalTierHierarchy] = None


def get_capital_tier_hierarchy() -> CapitalTierHierarchy:
    """Get or create the global CapitalTierHierarchy instance"""
    global _tier_hierarchy_instance
    if _tier_hierarchy_instance is None:
        _tier_hierarchy_instance = CapitalTierHierarchy()
    return _tier_hierarchy_instance


# ============================================================================
# CONVENIENCE FUNCTIONS
# ============================================================================

def get_max_positions_for_balance(balance: float) -> int:
    """Get maximum positions allowed for a given balance"""
    hierarchy = get_capital_tier_hierarchy()
    return hierarchy.get_max_positions(balance)


def get_optimal_positions_for_balance(balance: float) -> int:
    """Get optimal position count for a given balance"""
    hierarchy = get_capital_tier_hierarchy()
    return hierarchy.get_optimal_position_count(balance)


def validate_position_entry(balance: float, current_positions: int, size_usd: float) -> Tuple[bool, str, str]:
    """Validate if a position can be opened"""
    hierarchy = get_capital_tier_hierarchy()
    return hierarchy.validate_new_position(balance, current_positions, size_usd)


if __name__ == "__main__":
    # Demo: Show tier progression from $50 to $250k
    import logging
    logging.basicConfig(level=logging.INFO)
    
    hierarchy = CapitalTierHierarchy()
    
    test_balances = [50, 75, 100, 150, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000, 250000]
    
    print("\n" + "="*100)
    print("NIJA CAPITAL TIER HIERARCHY - Position Architecture Demo ($50 → $250k)")
    print("="*100 + "\n")
    
    for balance in test_balances:
        info = hierarchy.get_tier_info(balance)
        print(f"Balance: ${balance:>8,.0f} | Tier: {info['tier']:>8} | "
              f"Max Positions: {info['max_positions']:>2} | "
              f"Optimal: {info['optimal_positions']:>2} | "
              f"Min Size: ${info['min_position_size']:>5.0f} | "
              f"Target: {info['target_position_pct']:>5.1f}% | "
              f"Strategy: {info['concentration_strategy']:>13}")
    
    print("\n" + "="*100)
    print("Key Insight: Position count and size scale with capital tier")
    print("Small accounts: CONCENTRATED (few large positions)")
    print("Large accounts: DIVERSIFIED (many smaller positions)")
    print("="*100 + "\n")
