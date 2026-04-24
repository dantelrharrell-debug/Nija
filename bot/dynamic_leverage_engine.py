"""
NIJA Dynamic Leverage Engine
=============================

Volatility-aware and drawdown-gated leverage system for futures trading.

Features:
- Volatility-based leverage calculation
- Drawdown protection
- Risk-adjusted position sizing
- Automatic leverage reduction in adverse conditions
- Support for futures markets (optional)

This system dynamically adjusts leverage based on:
1. Current market volatility
2. Account drawdown level
3. Win rate performance
4. Regime conditions

Safe leverage increases returns without excessive risk.

Author: NIJA Trading Systems
Version: 1.0 (Path 1)
Date: January 30, 2026
"""

import numpy as np
from typing import Dict, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
import logging

logger = logging.getLogger("nija.dynamic_leverage")


class LeverageMode(Enum):
    """Leverage operating modes"""
    CONSERVATIVE = "conservative"  # 1-3x
    MODERATE = "moderate"  # 1-5x
    AGGRESSIVE = "aggressive"  # 1-10x
    DISABLED = "disabled"  # No leverage (1x)


@dataclass
class LeverageState:
    """Current leverage state"""
    current_leverage: float
    max_leverage: float
    mode: LeverageMode
    volatility_factor: float
    drawdown_factor: float
    performance_factor: float
    timestamp: datetime
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'current_leverage': self.current_leverage,
            'max_leverage': self.max_leverage,
            'mode': self.mode.value,
            'volatility_factor': self.volatility_factor,
            'drawdown_factor': self.drawdown_factor,
            'performance_factor': self.performance_factor,
            'timestamp': self.timestamp.isoformat()
        }


class DynamicLeverageEngine:
    """
    Dynamic leverage calculation engine
    
    Key Features:
    1. Volatility-Aware Leverage
       - High volatility → Lower leverage
       - Low volatility → Higher leverage
       
    2. Drawdown-Gated Leverage
       - Small drawdown → Normal leverage
       - Large drawdown → Reduced leverage
       - Maximum drawdown → Leverage disabled
       
    3. Performance-Based Adjustment
       - High win rate → Can increase leverage
       - Low win rate → Reduce leverage
       
    4. Regime-Based Limits
       - Strong trend → Higher leverage allowed
       - Choppy/volatile → Lower leverage
    
    Example:
        Base leverage: 5x
        High volatility (ATR 4%): Reduce to 3x
        Medium drawdown (15%): Reduce to 2x
        Final leverage: 2x
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize dynamic leverage engine
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        
        # Leverage limits by mode
        # NOTE: All modes are hard-capped at 3x per the first-30-day risk policy.
        self.leverage_limits = {
            LeverageMode.CONSERVATIVE: {
                'min': 1.0,
                'max': 3.0,
                'base': 1.5
            },
            LeverageMode.MODERATE: {
                'min': 1.0,
                'max': 3.0,
                'base': 2.5
            },
            LeverageMode.AGGRESSIVE: {
                'min': 1.0,
                'max': 3.0,   # Hard cap: no 10x / 20x — max 3x
                'base': 3.0
            },
            LeverageMode.DISABLED: {
                'min': 1.0,
                'max': 1.0,
                'base': 1.0
            }
        }
        
        # Operating mode
        mode_str = self.config.get('mode', 'moderate')
        self.mode = LeverageMode(mode_str)
        
        # Volatility thresholds
        self.low_volatility_threshold = self.config.get('low_volatility_threshold', 0.02)  # 2%
        self.high_volatility_threshold = self.config.get('high_volatility_threshold', 0.05)  # 5%
        
        # Drawdown thresholds
        self.max_drawdown_for_leverage = self.config.get('max_drawdown_for_leverage', 0.25)  # 25%
        self.drawdown_reduction_start = self.config.get('drawdown_reduction_start', 0.10)  # 10%
        
        # Performance thresholds
        self.min_win_rate_for_max_leverage = self.config.get('min_win_rate_for_max_leverage', 0.60)  # 60%
        self.min_trades_for_performance = self.config.get('min_trades_for_performance', 20)
        
        # State
        self.current_state: Optional[LeverageState] = None

        # Hard maximum across all modes
        self.HARD_MAX_LEVERAGE = 3.0

        logger.info("=" * 70)
        logger.info("⚡ DynamicLeverageEngine initialized")
        logger.info("=" * 70)
        logger.info(f"   Mode         : {self.mode.value}")
        logger.info(f"   🔒 Max Leverage: {self.HARD_MAX_LEVERAGE}x (hard cap — no 10x / 20x)")
        logger.info("=" * 70)
    
    def calculate_leverage(
        self,
        volatility_pct: float,
        current_drawdown_pct: float,
        win_rate: float = None,
        total_trades: int = 0,
        regime_type: str = None,
        current_time: datetime = None
    ) -> LeverageState:
        """
        Calculate optimal leverage based on current conditions
        
        Args:
            volatility_pct: Current market volatility (ATR %)
            current_drawdown_pct: Current account drawdown (0.0-1.0)
            win_rate: Optional win rate (0.0-1.0)
            total_trades: Total number of trades
            regime_type: Optional market regime
            current_time: Optional timestamp
        
        Returns:
            LeverageState
        """
        if current_time is None:
            current_time = datetime.now()
        
        # Get base leverage for mode
        limits = self.leverage_limits[self.mode]
        base_leverage = limits['base']
        max_leverage = limits['max']
        min_leverage = limits['min']
        
        # Calculate volatility factor (0.0 to 1.0, lower = reduce leverage more)
        volatility_factor = self._calculate_volatility_factor(volatility_pct)
        
        # Calculate drawdown factor (0.0 to 1.0, lower = reduce leverage more)
        drawdown_factor = self._calculate_drawdown_factor(current_drawdown_pct)
        
        # Calculate performance factor (0.8 to 1.2)
        performance_factor = self._calculate_performance_factor(win_rate, total_trades)
        
        # Apply regime adjustment
        regime_multiplier = self._get_regime_multiplier(regime_type)
        
        # Calculate final leverage
        leverage = base_leverage * volatility_factor * drawdown_factor * performance_factor * regime_multiplier
        
        # Clamp to mode limits then enforce absolute hard cap (3x)
        leverage = max(min_leverage, min(max_leverage, leverage))
        leverage = min(leverage, self.HARD_MAX_LEVERAGE)
        
        # Create state
        self.current_state = LeverageState(
            current_leverage=leverage,
            max_leverage=min(max_leverage, self.HARD_MAX_LEVERAGE),
            mode=self.mode,
            volatility_factor=volatility_factor,
            drawdown_factor=drawdown_factor,
            performance_factor=performance_factor,
            timestamp=current_time
        )
        
        logger.info(
            f"⚡ Leverage: {leverage:.2f}x (hard cap: {self.HARD_MAX_LEVERAGE}x) | "
            f"Volatility: {volatility_pct*100:.2f}% (factor: {volatility_factor:.2f}) | "
            f"Drawdown: {current_drawdown_pct*100:.2f}% (factor: {drawdown_factor:.2f}) | "
            f"Performance: {performance_factor:.2f}"
        )
        
        return self.current_state
    
    def _calculate_volatility_factor(self, volatility_pct: float) -> float:
        """
        Calculate volatility adjustment factor
        
        Low volatility → 1.0 (no reduction)
        Medium volatility → 0.7-1.0 (some reduction)
        High volatility → 0.3-0.7 (significant reduction)
        
        Args:
            volatility_pct: Current volatility (ATR %)
        
        Returns:
            Factor 0.3 to 1.0
        """
        if volatility_pct <= self.low_volatility_threshold:
            # Low volatility: No reduction, can even increase
            return 1.0
        
        elif volatility_pct <= self.high_volatility_threshold:
            # Medium volatility: Linear reduction
            # Map [low_threshold, high_threshold] → [1.0, 0.7]
            range_pct = (volatility_pct - self.low_volatility_threshold) / (
                self.high_volatility_threshold - self.low_volatility_threshold
            )
            factor = 1.0 - (0.3 * range_pct)
            return max(0.7, factor)
        
        else:
            # High volatility: Strong reduction
            # Map [high_threshold, 2*high_threshold] → [0.7, 0.3]
            excess = volatility_pct - self.high_volatility_threshold
            max_excess = self.high_volatility_threshold  # Another 5%
            excess_ratio = min(1.0, excess / max_excess)
            factor = 0.7 - (0.4 * excess_ratio)
            return max(0.3, factor)
    
    def _calculate_drawdown_factor(self, drawdown_pct: float) -> float:
        """
        Calculate drawdown adjustment factor
        
        No drawdown → 1.0 (no reduction)
        Small drawdown (< 10%) → 1.0 (no reduction)
        Medium drawdown (10-25%) → 0.5-1.0 (graduated reduction)
        Large drawdown (> 25%) → 0.0 (leverage disabled)
        
        Args:
            drawdown_pct: Current drawdown (0.0-1.0)
        
        Returns:
            Factor 0.0 to 1.0
        """
        # No drawdown or small drawdown
        if drawdown_pct <= self.drawdown_reduction_start:
            return 1.0
        
        # Exceeded max drawdown: Disable leverage
        if drawdown_pct >= self.max_drawdown_for_leverage:
            logger.warning(
                f"Drawdown {drawdown_pct*100:.1f}% exceeds max {self.max_drawdown_for_leverage*100:.1f}%: "
                f"Leverage DISABLED"
            )
            return 0.0
        
        # Medium drawdown: Graduated reduction
        # Map [10%, 25%] → [1.0, 0.5]
        reduction_range = self.max_drawdown_for_leverage - self.drawdown_reduction_start
        drawdown_in_range = drawdown_pct - self.drawdown_reduction_start
        reduction_ratio = drawdown_in_range / reduction_range
        
        factor = 1.0 - (0.5 * reduction_ratio)
        return max(0.5, factor)
    
    def _calculate_performance_factor(
        self,
        win_rate: Optional[float],
        total_trades: int
    ) -> float:
        """
        Calculate performance-based adjustment factor
        
        High win rate (>60%) → 1.2 (can increase leverage)
        Normal win rate (45-60%) → 1.0 (no adjustment)
        Low win rate (<45%) → 0.8 (reduce leverage)
        
        Args:
            win_rate: Win rate (0.0-1.0) or None
            total_trades: Total number of trades
        
        Returns:
            Factor 0.8 to 1.2
        """
        # Not enough data
        if win_rate is None or total_trades < self.min_trades_for_performance:
            return 1.0  # Neutral
        
        # High win rate: Can increase leverage
        if win_rate >= self.min_win_rate_for_max_leverage:
            # Map [60%, 75%] → [1.0, 1.2]
            if win_rate >= 0.75:
                return 1.2
            else:
                bonus = (win_rate - 0.60) / 0.15  # 0.0 to 1.0
                return 1.0 + (0.2 * bonus)
        
        # Low win rate: Reduce leverage
        elif win_rate < 0.45:
            # Map [30%, 45%] → [0.8, 1.0]
            if win_rate <= 0.30:
                return 0.8
            else:
                penalty = (0.45 - win_rate) / 0.15  # 0.0 to 1.0
                return 1.0 - (0.2 * penalty)
        
        # Normal win rate: No adjustment
        else:
            return 1.0
    
    def _get_regime_multiplier(self, regime_type: Optional[str]) -> float:
        """
        Get regime-based leverage multiplier
        
        Args:
            regime_type: Market regime type
        
        Returns:
            Multiplier 0.7 to 1.2
        """
        if regime_type is None:
            return 1.0
        
        regime_type = regime_type.lower()
        
        # Strong trend: Can increase leverage
        if 'strong_trend' in regime_type or 'trending' in regime_type:
            return 1.2
        
        # Weak trend: Normal leverage
        elif 'weak_trend' in regime_type:
            return 1.0
        
        # Ranging: Slight reduction
        elif 'ranging' in regime_type or 'consolidation' in regime_type:
            return 0.9
        
        # Volatile/Crisis: Significant reduction
        elif 'volatile' in regime_type or 'crisis' in regime_type or 'spike' in regime_type:
            return 0.7
        
        # Unknown: Neutral
        else:
            return 1.0
    
    def calculate_position_size_with_leverage(
        self,
        base_position_size_usd: float,
        leverage: float = None
    ) -> Tuple[float, float]:
        """
        Calculate leveraged position size
        
        Args:
            base_position_size_usd: Base position size without leverage
            leverage: Optional leverage (uses current state if None)
        
        Returns:
            Tuple of (leveraged_size, margin_required)
        """
        if leverage is None:
            if self.current_state:
                leverage = self.current_state.current_leverage
            else:
                leverage = 1.0
        
        leveraged_size = base_position_size_usd * leverage
        margin_required = leveraged_size / leverage if leverage > 0 else leveraged_size
        
        return leveraged_size, margin_required
    
    def get_safe_leverage_for_volatility(self, volatility_pct: float) -> float:
        """
        Get safe leverage based only on volatility
        
        Args:
            volatility_pct: Market volatility (ATR %)
        
        Returns:
            Recommended leverage
        """
        limits = self.leverage_limits[self.mode]
        base = limits['base']
        
        volatility_factor = self._calculate_volatility_factor(volatility_pct)
        leverage = base * volatility_factor
        
        return max(limits['min'], min(limits['max'], leverage))
    
    def should_use_leverage(self, drawdown_pct: float) -> bool:
        """
        Check if leverage should be used at all
        
        Args:
            drawdown_pct: Current drawdown
        
        Returns:
            True if leverage can be used
        """
        # Disabled mode: Never use leverage
        if self.mode == LeverageMode.DISABLED:
            return False
        
        # Excessive drawdown: Disable leverage
        if drawdown_pct >= self.max_drawdown_for_leverage:
            return False
        
        return True
    
    def set_mode(self, mode: LeverageMode):
        """
        Change leverage mode
        
        Args:
            mode: New LeverageMode
        """
        self.mode = mode
        logger.info(f"Leverage mode changed to: {mode.value}")
    
    def get_state(self) -> Optional[LeverageState]:
        """Get current leverage state"""
        return self.current_state
    
    def get_stats(self) -> Dict:
        """Get leverage statistics"""
        state = self.current_state
        
        if state:
            return {
                'mode': self.mode.value,
                'current_leverage': state.current_leverage,
                'max_leverage': state.max_leverage,
                'volatility_factor': state.volatility_factor,
                'drawdown_factor': state.drawdown_factor,
                'performance_factor': state.performance_factor,
                'last_update': state.timestamp.isoformat()
            }
        else:
            return {
                'mode': self.mode.value,
                'current_leverage': 1.0,
                'max_leverage': self.leverage_limits[self.mode]['max'],
                'volatility_factor': 1.0,
                'drawdown_factor': 1.0,
                'performance_factor': 1.0,
                'last_update': None
            }


# Global instance
dynamic_leverage_engine = DynamicLeverageEngine()
