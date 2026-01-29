"""
NIJA Position Pyramiding System
================================

GOD-TIER ENHANCEMENT #2: Intelligent position scaling during high-conviction
trend continuation. Increases position size when:
1. Initial position is profitable
2. Trend strength remains high or increases
3. Risk metrics support additional exposure
4. Momentum confirms continuation

This maximizes profit extraction from strong trends while maintaining
strict risk management.

Author: NIJA Trading Systems
Version: 1.0 - God-Tier Edition
Date: January 2026
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple, List, Optional
from enum import Enum
from datetime import datetime
import logging

logger = logging.getLogger("nija.pyramiding")


class PyramidLevel(Enum):
    """Pyramid position levels"""
    INITIAL = "initial"     # First entry
    SCALE_1 = "scale_1"     # First add-on
    SCALE_2 = "scale_2"     # Second add-on
    SCALE_3 = "scale_3"     # Third add-on (max)


class ConvictionLevel(Enum):
    """Conviction level for scaling decisions"""
    LOW = "low"             # Don't scale
    MEDIUM = "medium"       # Scale cautiously (50% of initial)
    HIGH = "high"           # Scale normally (75% of initial)
    EXTREME = "extreme"     # Scale aggressively (100% of initial)


class PositionPyramidingSystem:
    """
    Intelligent position pyramiding system for trend continuation
    
    Key Features:
    - Only scales into winning positions
    - Requires strong trend confirmation
    - Maintains risk-adjusted position sizing
    - Moves stop loss to protect pyramided position
    - Maximum 3 scale-ins (4 total entries including initial)
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize Position Pyramiding System
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        
        # Pyramiding configuration
        self.max_pyramid_levels = self.config.get('max_pyramid_levels', 3)  # Max 3 add-ons
        self.min_profit_to_scale = self.config.get('min_profit_to_scale', 0.01)  # 1% profit minimum
        self.scale_size_ratios = {
            ConvictionLevel.LOW: 0.0,       # No scaling
            ConvictionLevel.MEDIUM: 0.50,   # 50% of initial position
            ConvictionLevel.HIGH: 0.75,     # 75% of initial position
            ConvictionLevel.EXTREME: 1.00,  # 100% of initial position
        }
        
        # Trend continuation requirements
        self.min_adx_for_scaling = self.config.get('min_adx_for_scaling', 30)  # Strong trend
        self.min_adx_increase = self.config.get('min_adx_increase', 2)  # ADX rising
        
        # Risk management for pyramiding
        self.max_total_exposure_mult = self.config.get('max_total_exposure_mult', 2.5)  # Max 2.5x initial
        self.stop_loss_trail_on_scale = True  # Move stop loss up on each scale
        
        # Pullback requirements (scale on pullbacks, not breakouts)
        self.max_pullback_for_scale = self.config.get('max_pullback_for_scale', 0.005)  # 0.5% max pullback
        
        logger.info("✅ Position Pyramiding System initialized")
        logger.info(f"   Max pyramid levels: {self.max_pyramid_levels}")
        logger.info(f"   Min profit to scale: {self.min_profit_to_scale*100:.1f}%")
        logger.info(f"   ADX requirement: {self.min_adx_for_scaling}+")
    
    def can_scale_position(
        self,
        position: Dict,
        current_price: float,
        df: pd.DataFrame,
        indicators: Dict,
        account_balance: float,
        current_exposure: float
    ) -> Tuple[bool, str, ConvictionLevel]:
        """
        Determine if position can be scaled (add-on entry)
        
        Args:
            position: Current position dictionary with entry info
            current_price: Current market price
            df: Price DataFrame with OHLCV data
            indicators: Dictionary of calculated indicators
            account_balance: Total account balance
            current_exposure: Current % of capital deployed
            
        Returns:
            Tuple of (can_scale, reason, conviction_level)
        """
        # 1. Check if we've maxed out pyramid levels
        current_level = position.get('pyramid_level', 0)
        if current_level >= self.max_pyramid_levels:
            return False, f"Max pyramid levels reached ({self.max_pyramid_levels})", ConvictionLevel.LOW
        
        # 2. Check if position is profitable enough
        entry_price = position.get('entry_price', 0)
        side = position.get('side', 'BUY')
        
        if side.upper() in ['BUY', 'LONG']:
            profit_pct = (current_price - entry_price) / entry_price
            in_profit = profit_pct >= self.min_profit_to_scale
        else:  # SHORT
            profit_pct = (entry_price - current_price) / entry_price
            in_profit = profit_pct >= self.min_profit_to_scale
        
        if not in_profit:
            return False, f"Position not profitable enough ({profit_pct*100:.2f}% < {self.min_profit_to_scale*100:.1f}%)", ConvictionLevel.LOW
        
        # 3. Assess trend continuation conviction
        conviction, conviction_metrics = self._assess_scale_conviction(
            position=position,
            current_price=current_price,
            df=df,
            indicators=indicators
        )
        
        if conviction == ConvictionLevel.LOW:
            return False, f"Low conviction for scaling: {conviction_metrics.get('reason', 'unknown')}", conviction
        
        # 4. Check risk limits
        initial_position_size = position.get('initial_size_usd', 0)
        current_total_size = position.get('total_size_usd', initial_position_size)
        
        # Calculate proposed new size after scaling
        scale_ratio = self.scale_size_ratios[conviction]
        scale_size = initial_position_size * scale_ratio
        proposed_total_size = current_total_size + scale_size
        
        # Check if we exceed max exposure multiplier
        max_allowed_size = initial_position_size * self.max_total_exposure_mult
        if proposed_total_size > max_allowed_size:
            return False, f"Would exceed max exposure ({proposed_total_size:.0f} > {max_allowed_size:.0f})", conviction
        
        # Check total account exposure
        proposed_exposure = current_exposure + (scale_size / account_balance)
        max_account_exposure = self.config.get('max_account_exposure', 0.80)
        if proposed_exposure > max_account_exposure:
            return False, f"Would exceed account exposure limit ({proposed_exposure*100:.1f}% > {max_account_exposure*100:.0f}%)", conviction
        
        # 5. All checks passed
        reason = (
            f"Scale approved: Profit={profit_pct*100:.2f}%, "
            f"Conviction={conviction.value}, "
            f"ADX={conviction_metrics.get('adx', 0):.1f}"
        )
        
        logger.info(f"✅ {reason}")
        
        return True, reason, conviction
    
    def _assess_scale_conviction(
        self,
        position: Dict,
        current_price: float,
        df: pd.DataFrame,
        indicators: Dict
    ) -> Tuple[ConvictionLevel, Dict]:
        """
        Assess conviction level for scaling decision
        
        Conviction based on:
        1. Trend strength (ADX)
        2. Trend continuation (ADX rising)
        3. Momentum confirmation (MACD)
        4. Pullback quality (scaling on pullback, not chase)
        5. Volume confirmation
        
        Args:
            position: Current position dictionary
            current_price: Current market price
            df: Price DataFrame
            indicators: Dictionary of indicators
            
        Returns:
            Tuple of (ConvictionLevel, metrics dict)
        """
        side = position.get('side', 'BUY')
        entry_price = position.get('entry_price', 0)
        last_scale_adx = position.get('last_scale_adx', 0)
        
        # Get current indicators
        adx = float(indicators.get('adx', pd.Series([0])).iloc[-1])
        adx_prev = float(indicators.get('adx', pd.Series([0])).iloc[-2]) if len(indicators.get('adx', [])) > 1 else adx
        
        plus_di = float(indicators.get('plus_di', pd.Series([0])).iloc[-1]) if 'plus_di' in indicators else 0
        minus_di = float(indicators.get('minus_di', pd.Series([0])).iloc[-1]) if 'minus_di' in indicators else 0
        
        macd_hist = indicators.get('histogram', pd.Series([0]))
        macd_current = float(macd_hist.iloc[-1]) if len(macd_hist) > 0 else 0
        macd_prev = float(macd_hist.iloc[-2]) if len(macd_hist) > 1 else macd_current
        
        # Score each conviction factor (0-1 scale)
        scores = {}
        
        # 1. Trend strength (ADX)
        if adx >= 40:
            scores['trend_strength'] = 1.0
        elif adx >= self.min_adx_for_scaling:
            scores['trend_strength'] = 0.7
        elif adx >= 25:
            scores['trend_strength'] = 0.4
        else:
            scores['trend_strength'] = 0.0
        
        # 2. Trend continuation (ADX rising)
        adx_change = adx - adx_prev
        adx_increase_from_last_scale = adx - last_scale_adx if last_scale_adx > 0 else adx_change
        
        if adx_increase_from_last_scale >= self.min_adx_increase:
            scores['trend_continuation'] = 1.0
        elif adx_change > 0:
            scores['trend_continuation'] = 0.6
        else:
            scores['trend_continuation'] = 0.0
        
        # 3. Directional confirmation (DI spread)
        if side.upper() in ['BUY', 'LONG']:
            di_correct_direction = plus_di > minus_di
            di_spread = plus_di - minus_di
        else:  # SHORT
            di_correct_direction = minus_di > plus_di
            di_spread = minus_di - plus_di
        
        if di_correct_direction and di_spread > 10:
            scores['direction_confirmation'] = 1.0
        elif di_correct_direction:
            scores['direction_confirmation'] = 0.6
        else:
            scores['direction_confirmation'] = 0.0
        
        # 4. Momentum confirmation (MACD histogram)
        if side.upper() in ['BUY', 'LONG']:
            macd_confirms = macd_current > 0 and macd_current > macd_prev
        else:  # SHORT
            macd_confirms = macd_current < 0 and macd_current < macd_prev
        
        scores['momentum_confirmation'] = 1.0 if macd_confirms else 0.3
        
        # 5. Pullback quality (scaling on pullback, not breakout)
        recent_high = df['high'].tail(10).max()
        recent_low = df['low'].tail(10).min()
        
        if side.upper() in ['BUY', 'LONG']:
            # For longs, we want to scale on pullbacks from recent highs
            pullback_from_high = (recent_high - current_price) / recent_high
            is_good_pullback = 0.002 <= pullback_from_high <= self.max_pullback_for_scale
        else:  # SHORT
            # For shorts, we want to scale on pullbacks from recent lows
            pullback_from_low = (current_price - recent_low) / recent_low
            is_good_pullback = 0.002 <= pullback_from_low <= self.max_pullback_for_scale
        
        scores['pullback_quality'] = 1.0 if is_good_pullback else 0.4
        
        # 6. Volume confirmation
        if len(df) >= 20:
            current_volume = df['volume'].iloc[-1]
            avg_volume = df['volume'].tail(20).mean()
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
            
            if volume_ratio >= 1.2:
                scores['volume_confirmation'] = 1.0
            elif volume_ratio >= 0.8:
                scores['volume_confirmation'] = 0.7
            else:
                scores['volume_confirmation'] = 0.3
        else:
            scores['volume_confirmation'] = 0.5
        
        # Calculate overall conviction score (weighted average)
        weights = {
            'trend_strength': 0.25,
            'trend_continuation': 0.25,
            'direction_confirmation': 0.20,
            'momentum_confirmation': 0.15,
            'pullback_quality': 0.10,
            'volume_confirmation': 0.05,
        }
        
        overall_score = sum(scores[k] * weights[k] for k in scores.keys())
        
        # Map overall score to conviction level
        if overall_score >= 0.80:
            conviction = ConvictionLevel.EXTREME
        elif overall_score >= 0.65:
            conviction = ConvictionLevel.HIGH
        elif overall_score >= 0.50:
            conviction = ConvictionLevel.MEDIUM
        else:
            conviction = ConvictionLevel.LOW
        
        # Compile metrics
        metrics = {
            'adx': adx,
            'adx_change': adx_change,
            'plus_di': plus_di,
            'minus_di': minus_di,
            'di_spread': di_spread,
            'macd_current': macd_current,
            'scores': scores,
            'overall_score': overall_score,
            'conviction': conviction.value,
            'reason': self._format_conviction_reason(scores, overall_score)
        }
        
        return conviction, metrics
    
    def _format_conviction_reason(self, scores: Dict, overall_score: float) -> str:
        """Format human-readable reason for conviction level"""
        passed = [k for k, v in scores.items() if v >= 0.6]
        failed = [k for k, v in scores.items() if v < 0.6]
        
        if len(passed) >= 4:
            return f"Strong signals ({len(passed)}/6 factors positive)"
        elif len(passed) >= 3:
            return f"Good signals ({len(passed)}/6 factors positive)"
        else:
            return f"Weak signals ({', '.join(failed[:2])} insufficient)"
    
    def calculate_scale_size(
        self,
        position: Dict,
        conviction: ConvictionLevel,
        account_balance: float
    ) -> Dict:
        """
        Calculate the size for scale-in entry
        
        Args:
            position: Current position dictionary
            conviction: Conviction level for this scale
            account_balance: Total account balance
            
        Returns:
            Dictionary with scale size details
        """
        initial_size = position.get('initial_size_usd', 0)
        scale_ratio = self.scale_size_ratios[conviction]
        
        scale_size_usd = initial_size * scale_ratio
        scale_size_pct = (scale_size_usd / account_balance) if account_balance > 0 else 0
        
        # Calculate new total position size
        current_total_size = position.get('total_size_usd', initial_size)
        new_total_size = current_total_size + scale_size_usd
        
        # Calculate new average entry price
        current_avg_entry = position.get('average_entry_price', position.get('entry_price', 0))
        current_quantity = position.get('total_quantity', 0)
        
        result = {
            'scale_size_usd': scale_size_usd,
            'scale_size_pct': scale_size_pct,
            'scale_ratio': scale_ratio,
            'conviction': conviction.value,
            'new_total_size_usd': new_total_size,
            'current_avg_entry': current_avg_entry,
        }
        
        logger.info(f"📊 Scale-In Calculation:")
        logger.info(f"   Conviction: {conviction.value.upper()}")
        logger.info(f"   Scale Size: ${scale_size_usd:.2f} ({scale_ratio*100:.0f}% of initial)")
        logger.info(f"   New Total: ${new_total_size:.2f}")
        
        return result
    
    def update_stop_loss_on_scale(
        self,
        position: Dict,
        scale_entry_price: float,
        atr: float
    ) -> float:
        """
        Calculate new stop loss after scaling position
        
        Move stop loss to protect pyramided position while giving room to breathe.
        
        Args:
            position: Current position dictionary
            scale_entry_price: Price of the scale-in entry
            atr: Current ATR value
            
        Returns:
            New stop loss price
        """
        side = position.get('side', 'BUY')
        current_stop = position.get('stop_loss', 0)
        
        # Move stop loss to breakeven or slight profit on oldest entry
        initial_entry = position.get('entry_price', 0)
        
        # Calculate stop based on scale entry minus ATR buffer
        atr_buffer = atr * 1.0  # 1x ATR from scale entry
        
        if side.upper() in ['BUY', 'LONG']:
            # For longs, move stop up but not above scale entry
            new_stop = max(
                current_stop,  # Never move stop down
                initial_entry,  # At least breakeven on initial
                scale_entry_price - atr_buffer  # Give room from scale entry
            )
        else:  # SHORT
            # For shorts, move stop down but not below scale entry
            new_stop = min(
                current_stop,  # Never move stop up (worse)
                initial_entry,  # At least breakeven on initial
                scale_entry_price + atr_buffer  # Give room from scale entry
            )
        
        logger.info(f"🛡️  Stop Loss Update:")
        logger.info(f"   Previous: ${current_stop:.4f}")
        logger.info(f"   New: ${new_stop:.4f}")
        logger.info(f"   Scale Entry: ${scale_entry_price:.4f}")
        
        return new_stop
    
    def get_pyramiding_summary(self, position: Dict) -> str:
        """
        Generate human-readable summary of pyramiding status
        
        Args:
            position: Position dictionary with pyramiding info
            
        Returns:
            Formatted summary string
        """
        pyramid_level = position.get('pyramid_level', 0)
        initial_size = position.get('initial_size_usd', 0)
        total_size = position.get('total_size_usd', initial_size)
        avg_entry = position.get('average_entry_price', position.get('entry_price', 0))
        
        lines = [
            "\n" + "=" * 70,
            "POSITION PYRAMIDING STATUS",
            "=" * 70,
            f"Pyramid Level: {pyramid_level}/{self.max_pyramid_levels}",
            f"Initial Size: ${initial_size:.2f}",
            f"Total Size: ${total_size:.2f} ({total_size/initial_size:.2f}x initial)",
            f"Average Entry: ${avg_entry:.4f}",
            f"Scale-ins Remaining: {self.max_pyramid_levels - pyramid_level}",
            "=" * 70,
        ]
        
        return "\n".join(lines)


def get_pyramiding_system(config: Dict = None) -> PositionPyramidingSystem:
    """
    Factory function to create PositionPyramidingSystem instance
    
    Args:
        config: Optional configuration dictionary
        
    Returns:
        PositionPyramidingSystem instance
    """
    return PositionPyramidingSystem(config)


# Example usage and testing
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
    
    # Create sample data
    dates = pd.date_range('2024-01-01', periods=100, freq='5T')
    df = pd.DataFrame({
        'timestamp': dates,
        'close': np.random.randn(100).cumsum() + 100,
        'high': np.random.randn(100).cumsum() + 102,
        'low': np.random.randn(100).cumsum() + 98,
        'volume': np.random.randint(1000, 10000, 100)
    })
    
    # Mock indicators for strong trend
    indicators = {
        'adx': pd.Series(np.linspace(30, 38, 100)),  # Rising ADX
        'plus_di': pd.Series(np.ones(100) * 35),
        'minus_di': pd.Series(np.ones(100) * 15),
        'histogram': pd.Series(np.linspace(0.1, 0.5, 100)),  # Rising MACD
    }
    
    # Create pyramiding system
    pyramid = get_pyramiding_system()
    
    # Simulate initial position
    position = {
        'side': 'BUY',
        'entry_price': 100.0,
        'initial_size_usd': 1000.0,
        'total_size_usd': 1000.0,
        'average_entry_price': 100.0,
        'pyramid_level': 0,
        'stop_loss': 98.0,
        'last_scale_adx': 0,
    }
    
    # Test scaling at profitable price
    current_price = 102.0  # 2% profit
    can_scale, reason, conviction = pyramid.can_scale_position(
        position=position,
        current_price=current_price,
        df=df,
        indicators=indicators,
        account_balance=10000.0,
        current_exposure=0.10
    )
    
    print(f"\n{'='*70}")
    print(f"Can Scale: {can_scale}")
    print(f"Reason: {reason}")
    print(f"Conviction: {conviction.value}")
    
    if can_scale:
        # Calculate scale size
        scale_info = pyramid.calculate_scale_size(
            position=position,
            conviction=conviction,
            account_balance=10000.0
        )
        
        print(f"\nScale Info: {scale_info}")
        
        # Update stop loss
        new_stop = pyramid.update_stop_loss_on_scale(
            position=position,
            scale_entry_price=current_price,
            atr=1.5
        )
        
        # Print summary
        position['pyramid_level'] += 1
        position['total_size_usd'] += scale_info['scale_size_usd']
        print(pyramid.get_pyramiding_summary(position))
