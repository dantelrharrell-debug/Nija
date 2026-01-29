"""
NIJA Enhanced Capital Scaling with Recommended Bands

Implements institutional-grade capital scaling with:
- Recommended capital deployment bands based on market conditions
- Strict drawdown-based throttling (3%, 6%, 10% levels)
- Aggressive scaling only when risk is lowest

This is how professional funds protect capital.

Author: NIJA Trading Systems
Version: 2.0
Date: January 29, 2026
"""

import logging
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger("nija.enhanced_scaling")


class MarketCondition(Enum):
    """Market condition classifications"""
    STRONG_TREND_LOW_DD = "strong_trend_low_dd"  # Strong trend + low drawdown
    NEUTRAL = "neutral"  # Normal conditions
    ELEVATED_VOL = "elevated_vol"  # High volatility
    DRAWDOWN_MODERATE = "drawdown_moderate"  # Drawdown 3-6%
    DRAWDOWN_SEVERE = "drawdown_severe"  # Drawdown 6-10%
    DRAWDOWN_CRITICAL = "drawdown_critical"  # Drawdown > 10%


@dataclass
class CapitalScalingBands:
    """Recommended capital scaling bands"""
    # Strong trend + low drawdown: Aggressive scaling
    strong_trend_min: float = 1.25
    strong_trend_max: float = 1.6
    
    # Neutral conditions: Normal scaling
    neutral: float = 1.0
    
    # Elevated volatility: Conservative scaling
    elevated_vol_min: float = 0.6
    elevated_vol_max: float = 0.8
    
    # Drawdown > 4%: Defensive scaling
    drawdown_min: float = 0.3
    drawdown_max: float = 0.5


class EnhancedCapitalScaler:
    """
    Enhanced capital scaler with institutional-grade risk management
    
    Implements:
    1. Market condition-based capital bands
    2. Strict drawdown-based throttling
    3. Aggressive scaling only when risk is lowest
    
    This is exactly how professional funds protect capital.
    """
    
    def __init__(self, base_capital: float, 
                 scaling_bands: Optional[CapitalScalingBands] = None):
        """
        Initialize enhanced capital scaler
        
        Args:
            base_capital: Base capital amount
            scaling_bands: Custom scaling bands (optional)
        """
        self.base_capital = base_capital
        self.scaling_bands = scaling_bands or CapitalScalingBands()
        
        # State tracking
        self.peak_capital = base_capital
        self.current_capital = base_capital
        self.current_drawdown_pct = 0.0
        
        logger.info(f"✅ Enhanced Capital Scaler initialized with ${base_capital:,.2f}")
    
    def update_capital(self, current_capital: float) -> None:
        """
        Update current capital and recalculate drawdown
        
        Args:
            current_capital: Current capital amount
        """
        self.current_capital = current_capital
        
        # Update peak
        if current_capital > self.peak_capital:
            self.peak_capital = current_capital
        
        # Calculate drawdown
        if self.peak_capital > 0:
            self.current_drawdown_pct = ((self.peak_capital - current_capital) / self.peak_capital) * 100
        else:
            self.current_drawdown_pct = 0.0
        
        logger.debug(f"Capital updated: ${current_capital:,.2f}, DD: {self.current_drawdown_pct:.2f}%")
    
    def apply_drawdown_throttling(self, exposure: float) -> float:
        """
        Apply strict drawdown-based throttling
        
        Critical protection levels:
        - DD > 3%: exposure *= 0.75
        - DD > 6%: exposure *= 0.40
        - DD > 10%: exposure *= 0.20
        
        This is exactly how funds protect capital.
        
        Args:
            exposure: Base exposure amount
        
        Returns:
            Throttled exposure amount
        """
        dd = self.current_drawdown_pct
        original_exposure = exposure
        
        # Apply throttling based on drawdown levels
        if dd > 10.0:
            # Critical drawdown: Reduce to 20%
            exposure *= 0.20
            logger.warning(f"🚨 CRITICAL DRAWDOWN ({dd:.2f}%) - Exposure reduced to 20%")
        elif dd > 6.0:
            # Severe drawdown: Reduce to 40%
            exposure *= 0.40
            logger.warning(f"⚠️  SEVERE DRAWDOWN ({dd:.2f}%) - Exposure reduced to 40%")
        elif dd > 3.0:
            # Moderate drawdown: Reduce to 75%
            exposure *= 0.75
            logger.info(f"⚡ Moderate drawdown ({dd:.2f}%) - Exposure reduced to 75%")
        
        if exposure != original_exposure:
            logger.info(f"Drawdown throttling: ${original_exposure:,.2f} → ${exposure:,.2f} "
                       f"({(exposure/original_exposure)*100:.1f}%)")
        
        return exposure
    
    def classify_market_condition(self, is_trending: bool, 
                                  volatility_pct: float) -> MarketCondition:
        """
        Classify current market condition
        
        Args:
            is_trending: Whether market is in strong trend
            volatility_pct: Current volatility percentage
        
        Returns:
            Market condition classification
        """
        dd = self.current_drawdown_pct
        
        # Drawdown takes priority
        if dd > 10.0:
            return MarketCondition.DRAWDOWN_CRITICAL
        elif dd > 6.0:
            return MarketCondition.DRAWDOWN_SEVERE
        elif dd > 3.0:
            return MarketCondition.DRAWDOWN_MODERATE
        elif dd > 4.0:
            # Drawdown > 4% but < 6%
            return MarketCondition.DRAWDOWN_MODERATE
        
        # Strong trend + low drawdown: Aggressive
        if is_trending and dd < 2.0:
            return MarketCondition.STRONG_TREND_LOW_DD
        
        # Elevated volatility
        if volatility_pct > 40.0:
            return MarketCondition.ELEVATED_VOL
        
        # Default to neutral
        return MarketCondition.NEUTRAL
    
    def get_capital_multiplier(self, condition: MarketCondition) -> float:
        """
        Get capital multiplier for market condition
        
        Args:
            condition: Market condition
        
        Returns:
            Capital multiplier (e.g., 1.25 = 125% of base)
        """
        bands = self.scaling_bands
        
        if condition == MarketCondition.STRONG_TREND_LOW_DD:
            # Strong trend + low DD: Aggressive (1.25x - 1.6x)
            return (bands.strong_trend_min + bands.strong_trend_max) / 2
        
        elif condition == MarketCondition.NEUTRAL:
            # Neutral: Normal (1.0x)
            return bands.neutral
        
        elif condition == MarketCondition.ELEVATED_VOL:
            # Elevated vol: Conservative (0.6x - 0.8x)
            return (bands.elevated_vol_min + bands.elevated_vol_max) / 2
        
        elif condition in [MarketCondition.DRAWDOWN_MODERATE, 
                          MarketCondition.DRAWDOWN_SEVERE,
                          MarketCondition.DRAWDOWN_CRITICAL]:
            # Drawdown > 4%: Defensive (0.3x - 0.5x)
            return (bands.drawdown_min + bands.drawdown_max) / 2
        
        return 1.0
    
    def calculate_optimal_exposure(self, base_position_size: float,
                                   is_trending: bool,
                                   volatility_pct: float) -> Tuple[float, MarketCondition, float]:
        """
        Calculate optimal exposure with all scaling factors
        
        Combines:
        1. Market condition-based scaling bands
        2. Drawdown-based throttling
        3. Capital protection
        
        Args:
            base_position_size: Base position size
            is_trending: Whether market is trending
            volatility_pct: Current volatility
        
        Returns:
            Tuple of (optimal_exposure, market_condition, multiplier)
        """
        # Classify market condition
        condition = self.classify_market_condition(is_trending, volatility_pct)
        
        # Get capital multiplier for condition
        multiplier = self.get_capital_multiplier(condition)
        
        # Apply multiplier
        exposure = base_position_size * multiplier
        
        # Apply drawdown throttling (CRITICAL)
        exposure = self.apply_drawdown_throttling(exposure)
        
        logger.info(f"📊 Optimal Exposure: ${exposure:,.2f}")
        logger.info(f"   Condition: {condition.value}")
        logger.info(f"   Base Multiplier: {multiplier:.2f}x")
        logger.info(f"   Drawdown: {self.current_drawdown_pct:.2f}%")
        
        return exposure, condition, multiplier
    
    def get_scaling_summary(self) -> Dict:
        """
        Get comprehensive scaling summary
        
        Returns:
            Dictionary with scaling metrics
        """
        return {
            'base_capital': self.base_capital,
            'current_capital': self.current_capital,
            'peak_capital': self.peak_capital,
            'current_drawdown_pct': self.current_drawdown_pct,
            'scaling_bands': {
                'strong_trend': f"{self.scaling_bands.strong_trend_min:.2f}x - {self.scaling_bands.strong_trend_max:.2f}x",
                'neutral': f"{self.scaling_bands.neutral:.2f}x",
                'elevated_vol': f"{self.scaling_bands.elevated_vol_min:.2f}x - {self.scaling_bands.elevated_vol_max:.2f}x",
                'drawdown': f"{self.scaling_bands.drawdown_min:.2f}x - {self.scaling_bands.drawdown_max:.2f}x"
            },
            'throttling_levels': {
                '3_pct': '0.75x (75% exposure)',
                '6_pct': '0.40x (40% exposure)',
                '10_pct': '0.20x (20% exposure)'
            }
        }


# Singleton instance
_enhanced_scaler: Optional[EnhancedCapitalScaler] = None


def get_enhanced_scaler(base_capital: float = 10000.0,
                       reset: bool = False) -> EnhancedCapitalScaler:
    """
    Get or create enhanced capital scaler singleton
    
    Args:
        base_capital: Base capital (only used on first creation)
        reset: Force reset and create new instance
    
    Returns:
        EnhancedCapitalScaler instance
    """
    global _enhanced_scaler
    
    if _enhanced_scaler is None or reset:
        _enhanced_scaler = EnhancedCapitalScaler(base_capital)
    
    return _enhanced_scaler
