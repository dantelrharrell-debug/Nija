"""
NIJA Liquidity & Volume Gating System
======================================

Tier-based liquidity and volume requirements to ensure trades are executed
in sufficiently liquid markets. Higher tiers have stricter requirements.

Features:
- Tier-specific minimum volume requirements
- Volume stability checks (current vs average)
- Spread analysis (bid-ask spread)
- Market depth verification
- Liquidity score calculation
- Dynamic gate thresholds

This prevents small-cap, illiquid markets from being traded at higher
capital levels where slippage and execution risk become significant.

Author: NIJA Trading Systems
Version: 1.0
Date: February 18, 2026
"""

import logging
from typing import Dict, Tuple, Optional
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("nija.liquidity_volume_gate")


class LiquidityTier(Enum):
    """Liquidity tiers with associated requirements"""
    MICRO = "micro"  # < $1M daily volume
    SMALL = "small"  # $1M - $5M
    MEDIUM = "medium"  # $5M - $20M
    LARGE = "large"  # $20M - $100M
    INSTITUTIONAL = "institutional"  # > $100M


@dataclass
class LiquidityRequirements:
    """Liquidity requirements for a trading tier"""
    tier_name: str
    min_volume_24h: float  # Minimum 24h volume in USD
    min_volume_multiplier: float  # Multiplier vs average
    max_spread_bps: float  # Maximum bid-ask spread in basis points
    min_market_depth: float  # Minimum market depth in USD
    min_liquidity_score: float  # Minimum overall liquidity score (0-1)
    
    def __str__(self):
        return (
            f"{self.tier_name}: "
            f"Vol≥${self.min_volume_24h:,.0f}, "
            f"Spread≤{self.max_spread_bps:.0f}bps, "
            f"Depth≥${self.min_market_depth:,.0f}"
        )


# Tier-based liquidity requirements
TIER_LIQUIDITY_REQUIREMENTS = {
    "STARTER": LiquidityRequirements(
        tier_name="STARTER",
        min_volume_24h=500_000,  # $500K minimum
        min_volume_multiplier=0.5,
        max_spread_bps=50,  # 0.5% spread
        min_market_depth=10_000,
        min_liquidity_score=0.3
    ),
    "SAVER": LiquidityRequirements(
        tier_name="SAVER",
        min_volume_24h=1_000_000,  # $1M minimum
        min_volume_multiplier=0.6,
        max_spread_bps=40,
        min_market_depth=25_000,
        min_liquidity_score=0.4
    ),
    "INVESTOR": LiquidityRequirements(
        tier_name="INVESTOR",
        min_volume_24h=2_000_000,  # $2M minimum
        min_volume_multiplier=0.7,
        max_spread_bps=30,
        min_market_depth=50_000,
        min_liquidity_score=0.5
    ),
    "INCOME": LiquidityRequirements(
        tier_name="INCOME",
        min_volume_24h=5_000_000,  # $5M minimum
        min_volume_multiplier=0.8,
        max_spread_bps=20,
        min_market_depth=100_000,
        min_liquidity_score=0.6
    ),
    "LIVABLE": LiquidityRequirements(
        tier_name="LIVABLE",
        min_volume_24h=10_000_000,  # $10M minimum
        min_volume_multiplier=0.9,
        max_spread_bps=15,
        min_market_depth=250_000,
        min_liquidity_score=0.7
    ),
    "BALLER": LiquidityRequirements(
        tier_name="BALLER",
        min_volume_24h=25_000_000,  # $25M minimum
        min_volume_multiplier=1.0,
        max_spread_bps=10,
        min_market_depth=500_000,
        min_liquidity_score=0.8
    )
}


@dataclass
class LiquidityCheck:
    """Result of liquidity gate check"""
    passed: bool
    liquidity_score: float
    liquidity_tier: LiquidityTier
    violations: list
    warnings: list
    details: Dict
    
    def get_summary(self) -> str:
        """Get human-readable summary"""
        status = "✅ PASSED" if self.passed else "❌ FAILED"
        summary = f"{status} - Liquidity Score: {self.liquidity_score:.2f} ({self.liquidity_tier.value})"
        
        if self.violations:
            summary += f"\nViolations: {', '.join(self.violations)}"
        if self.warnings:
            summary += f"\nWarnings: {', '.join(self.warnings)}"
            
        return summary


class LiquidityVolumeGate:
    """
    Liquidity and volume gating system for tier-based trading.
    
    Ensures trades are only executed in markets with sufficient liquidity
    to handle the position size without excessive slippage or execution risk.
    
    Key checks:
    1. Minimum 24h volume requirement
    2. Volume stability (current vs historical average)
    3. Bid-ask spread analysis
    4. Market depth verification
    5. Overall liquidity scoring
    """
    
    def __init__(self, tier: str = "INVESTOR"):
        """
        Initialize liquidity gate for a specific tier.
        
        Args:
            tier: Trading tier (STARTER, SAVER, INVESTOR, etc.)
        """
        self.tier = tier
        self.requirements = TIER_LIQUIDITY_REQUIREMENTS.get(
            tier,
            TIER_LIQUIDITY_REQUIREMENTS["INVESTOR"]  # Default fallback
        )
        
        logger.info("=" * 70)
        logger.info("🚪 Liquidity & Volume Gate Initialized")
        logger.info("=" * 70)
        logger.info(f"Tier: {tier}")
        logger.info(f"Requirements: {self.requirements}")
        logger.info("=" * 70)
    
    def check_liquidity(
        self,
        symbol: str,
        market_data: Dict,
        position_size_usd: Optional[float] = None
    ) -> LiquidityCheck:
        """
        Check if market passes liquidity requirements for tier.
        
        Args:
            symbol: Trading symbol
            market_data: Market data dictionary with:
                - volume_24h: 24-hour volume in USD
                - avg_volume: Historical average volume
                - bid: Current bid price
                - ask: Current ask price
                - price: Mid price
                - market_depth_bid: Market depth on bid side (optional)
                - market_depth_ask: Market depth on ask side (optional)
            position_size_usd: Proposed position size in USD (optional)
            
        Returns:
            LiquidityCheck result
        """
        violations = []
        warnings = []
        details = {}
        
        # Extract market data
        volume_24h = market_data.get('volume_24h', 0.0)
        avg_volume = market_data.get('avg_volume', volume_24h)
        bid = market_data.get('bid', 0.0)
        ask = market_data.get('ask', 0.0)
        price = market_data.get('price', (bid + ask) / 2 if bid and ask else 0.0)
        
        # 1. Check minimum 24h volume
        if volume_24h < self.requirements.min_volume_24h:
            violations.append(
                f"Volume ${volume_24h:,.0f} < ${self.requirements.min_volume_24h:,.0f}"
            )
        details['volume_24h'] = volume_24h
        details['volume_requirement'] = self.requirements.min_volume_24h
        
        # 2. Check volume stability
        if avg_volume > 0:
            volume_ratio = volume_24h / avg_volume
            if volume_ratio < self.requirements.min_volume_multiplier:
                violations.append(
                    f"Volume ratio {volume_ratio:.2f} < {self.requirements.min_volume_multiplier:.2f}"
                )
            elif volume_ratio < 0.8:
                warnings.append(f"Volume {volume_ratio:.1%} of average")
            details['volume_ratio'] = volume_ratio
        
        # 3. Check bid-ask spread
        if bid > 0 and ask > 0 and price > 0:
            spread = ask - bid
            spread_bps = (spread / price) * 10_000
            
            if spread_bps > self.requirements.max_spread_bps:
                violations.append(
                    f"Spread {spread_bps:.1f}bps > {self.requirements.max_spread_bps:.1f}bps"
                )
            elif spread_bps > self.requirements.max_spread_bps * 0.8:
                warnings.append(f"Wide spread: {spread_bps:.1f}bps")
            
            details['spread_bps'] = spread_bps
            details['spread_requirement'] = self.requirements.max_spread_bps
        
        # 4. Check market depth (if available)
        market_depth_bid = market_data.get('market_depth_bid', 0.0)
        market_depth_ask = market_data.get('market_depth_ask', 0.0)
        total_depth = market_depth_bid + market_depth_ask
        
        if total_depth > 0:
            if total_depth < self.requirements.min_market_depth:
                violations.append(
                    f"Market depth ${total_depth:,.0f} < ${self.requirements.min_market_depth:,.0f}"
                )
            details['market_depth'] = total_depth
            details['depth_requirement'] = self.requirements.min_market_depth
        
        # 5. Position size vs volume check
        if position_size_usd and volume_24h > 0:
            position_volume_ratio = position_size_usd / volume_24h
            
            # Warn if position is >5% of daily volume
            if position_volume_ratio > 0.05:
                warnings.append(
                    f"Position {position_volume_ratio:.1%} of daily volume (high impact)"
                )
            
            # Fail if position is >10% of daily volume
            if position_volume_ratio > 0.10:
                violations.append(
                    f"Position {position_volume_ratio:.1%} of daily volume (excessive impact)"
                )
            
            details['position_volume_ratio'] = position_volume_ratio
        
        # 6. Calculate liquidity score (0-1)
        liquidity_score = self._calculate_liquidity_score(
            volume_24h=volume_24h,
            volume_ratio=details.get('volume_ratio', 1.0),
            spread_bps=details.get('spread_bps', 0.0),
            market_depth=total_depth
        )
        details['liquidity_score'] = liquidity_score
        
        # Check if score meets minimum
        if liquidity_score < self.requirements.min_liquidity_score:
            violations.append(
                f"Liquidity score {liquidity_score:.2f} < {self.requirements.min_liquidity_score:.2f}"
            )
        
        # Determine liquidity tier
        liquidity_tier = self._classify_liquidity_tier(volume_24h)
        
        # Determine if passed
        passed = len(violations) == 0
        
        # Create result
        result = LiquidityCheck(
            passed=passed,
            liquidity_score=liquidity_score,
            liquidity_tier=liquidity_tier,
            violations=violations,
            warnings=warnings,
            details=details
        )
        
        # Log result
        if not passed:
            logger.warning(f"❌ {symbol} FAILED liquidity gate: {result.get_summary()}")
        elif warnings:
            logger.info(f"⚠️  {symbol} passed with warnings: {result.get_summary()}")
        else:
            logger.debug(f"✅ {symbol} passed liquidity gate: {result.get_summary()}")
        
        return result
    
    def _calculate_liquidity_score(
        self,
        volume_24h: float,
        volume_ratio: float,
        spread_bps: float,
        market_depth: float
    ) -> float:
        """
        Calculate overall liquidity score (0-1).
        
        Components:
        - Volume level (30%)
        - Volume stability (25%)
        - Spread tightness (25%)
        - Market depth (20%)
        
        Returns:
            Liquidity score from 0 (illiquid) to 1 (highly liquid)
        """
        score = 0.0
        
        # Volume level score (0-0.30)
        volume_score = min(1.0, volume_24h / (self.requirements.min_volume_24h * 5))
        score += volume_score * 0.30
        
        # Volume stability score (0-0.25)
        stability_score = min(1.0, volume_ratio / self.requirements.min_volume_multiplier)
        score += stability_score * 0.25
        
        # Spread score (0-0.25)
        if spread_bps > 0:
            spread_score = max(0.0, 1.0 - (spread_bps / (self.requirements.max_spread_bps * 2)))
            score += spread_score * 0.25
        else:
            score += 0.25  # Perfect spread if 0
        
        # Market depth score (0-0.20)
        if market_depth > 0:
            depth_score = min(1.0, market_depth / (self.requirements.min_market_depth * 3))
            score += depth_score * 0.20
        else:
            # If no depth data, assume 50% score
            score += 0.10
        
        return min(1.0, score)
    
    def _classify_liquidity_tier(self, volume_24h: float) -> LiquidityTier:
        """
        Classify market into liquidity tier based on volume.
        
        Args:
            volume_24h: 24-hour volume in USD
            
        Returns:
            LiquidityTier classification
        """
        if volume_24h >= 100_000_000:
            return LiquidityTier.INSTITUTIONAL
        elif volume_24h >= 20_000_000:
            return LiquidityTier.LARGE
        elif volume_24h >= 5_000_000:
            return LiquidityTier.MEDIUM
        elif volume_24h >= 1_000_000:
            return LiquidityTier.SMALL
        else:
            return LiquidityTier.MICRO
    
    def get_requirements_report(self) -> str:
        """
        Generate report of current tier requirements.
        
        Returns:
            Formatted requirements report
        """
        lines = [
            "\n" + "=" * 70,
            f"LIQUIDITY GATE REQUIREMENTS - {self.tier}",
            "=" * 70,
            f"Minimum 24h Volume:     ${self.requirements.min_volume_24h:>15,.0f}",
            f"Volume Multiplier:      {self.requirements.min_volume_multiplier:>15.2f}x",
            f"Max Bid-Ask Spread:     {self.requirements.max_spread_bps:>15.1f} bps",
            f"Minimum Market Depth:   ${self.requirements.min_market_depth:>15,.0f}",
            f"Min Liquidity Score:    {self.requirements.min_liquidity_score:>15.2f}",
            "=" * 70 + "\n"
        ]
        return "\n".join(lines)
    
    def update_tier(self, new_tier: str):
        """
        Update to a new tier with different requirements.
        
        Args:
            new_tier: New trading tier
        """
        old_tier = self.tier
        self.tier = new_tier
        self.requirements = TIER_LIQUIDITY_REQUIREMENTS.get(
            new_tier,
            TIER_LIQUIDITY_REQUIREMENTS["INVESTOR"]
        )
        
        logger.info(f"📊 Liquidity gate updated: {old_tier} → {new_tier}")
        logger.info(f"New requirements: {self.requirements}")


def create_liquidity_gate(tier: str = "INVESTOR") -> LiquidityVolumeGate:
    """
    Factory function to create liquidity gate.
    
    Args:
        tier: Trading tier
        
    Returns:
        LiquidityVolumeGate instance
    """
    return LiquidityVolumeGate(tier)


def get_tier_requirements(tier: str) -> LiquidityRequirements:
    """
    Get liquidity requirements for a tier.
    
    Args:
        tier: Trading tier
        
    Returns:
        LiquidityRequirements for the tier
    """
    return TIER_LIQUIDITY_REQUIREMENTS.get(
        tier,
        TIER_LIQUIDITY_REQUIREMENTS["INVESTOR"]
    )


if __name__ == "__main__":
    # Test/demonstration
    logging.basicConfig(
        level=logging.INFO,
        format='%(levelname)s - %(message)s'
    )
    
    # Test with different tiers
    for tier in ["SAVER", "INVESTOR", "INCOME", "BALLER"]:
        print(f"\n{'='*70}")
        print(f"Testing tier: {tier}")
        print(f"{'='*70}")
        
        gate = create_liquidity_gate(tier)
        print(gate.get_requirements_report())
        
        # Test market data
        market_data = {
            'volume_24h': 8_000_000,
            'avg_volume': 10_000_000,
            'bid': 50_000,
            'ask': 50_010,
            'price': 50_005,
            'market_depth_bid': 150_000,
            'market_depth_ask': 175_000
        }
        
        result = gate.check_liquidity("BTC-USD", market_data, position_size_usd=5000)
        print(f"\n{result.get_summary()}")
        print(f"\nDetails:")
        for key, value in result.details.items():
            print(f"  {key}: {value}")
