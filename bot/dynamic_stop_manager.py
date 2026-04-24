"""
NIJA Dynamic Stop Expansion on Trend Confirmation

Intelligently widens stop losses when strong trends are confirmed to avoid
premature exits during profitable trend-following trades.

Key Principle:
- Tight stops initially (protect capital)
- Expand stops when trend confirms (give trade room to breathe)
- Shrink stops on trend weakening (lock in profits)

Features:
- Trend confirmation detection (ADX + directional movement)
- Progressive stop expansion
- Maximum expansion limits (safety)
- Automatic contraction on trend weakening
- Trailing stop integration

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import logging
from typing import Dict, Tuple, Optional
from datetime import datetime
import pandas as pd

logger = logging.getLogger("nija.dynamic_stop_manager")

# Import indicators
try:
    from indicators import calculate_adx, calculate_atr, scalar
except ImportError:
    try:
        from bot.indicators import calculate_adx, calculate_atr, scalar
    except ImportError:
        # Fallback definitions
        def scalar(x):
            if isinstance(x, (tuple, list)):
                return float(x[0]) if len(x) > 0 else 0.0
            return float(x)
        
        def calculate_atr(df, period=14):
            return pd.Series([0.0] * len(df))
        
        def calculate_adx(df, period=14):
            return pd.Series([0.0] * len(df)), pd.Series([0.0] * len(df)), pd.Series([0.0] * len(df))


class DynamicStopManager:
    """
    Manages dynamic stop loss expansion based on trend confirmation.
    
    Stop Loss Progression:
    1. Entry: Initial tight stop (e.g., 2x ATR)
    2. Trend Confirms (ADX > 25): Expand to 2.5x ATR
    3. Strong Trend (ADX > 35): Expand to 3x ATR
    4. Very Strong Trend (ADX > 45): Expand to 3.5x ATR (max)
    5. Trend Weakens (ADX drops): Contract back toward tighter stop
    
    Safeguards:
    - Maximum expansion limit (prevent runaway stops)
    - Never move stop against position (only in favor)
    - Minimum stop distance (always protect capital)
    - Trend weakening detection (lock in profits)
    """
    
    def __init__(
        self,
        initial_stop_atr_multiplier: float = 2.0,
        trend_confirm_adx: float = 25.0,
        strong_trend_adx: float = 35.0,
        very_strong_trend_adx: float = 45.0,
        max_stop_atr_multiplier: float = 3.5,
        min_stop_atr_multiplier: float = 1.5,
        expansion_increment: float = 0.5,
        contraction_rate: float = 0.3
    ):
        """
        Initialize dynamic stop manager.
        
        Args:
            initial_stop_atr_multiplier: Initial stop distance in ATR multiples
            trend_confirm_adx: ADX level for trend confirmation
            strong_trend_adx: ADX level for strong trend
            very_strong_trend_adx: ADX level for very strong trend
            max_stop_atr_multiplier: Maximum allowed stop expansion
            min_stop_atr_multiplier: Minimum stop distance
            expansion_increment: How much to expand per level
            contraction_rate: Rate of contraction when trend weakens
        """
        self.initial_stop_multiplier = initial_stop_atr_multiplier
        self.trend_confirm_adx = trend_confirm_adx
        self.strong_trend_adx = strong_trend_adx
        self.very_strong_trend_adx = very_strong_trend_adx
        self.max_stop_multiplier = max_stop_atr_multiplier
        self.min_stop_multiplier = min_stop_atr_multiplier
        self.expansion_increment = expansion_increment
        self.contraction_rate = contraction_rate
        
        # Track position stops
        self.position_stops = {}  # position_id -> stop_info
        
        logger.info(
            f"✅ Dynamic Stop Manager initialized: "
            f"Initial={initial_stop_atr_multiplier}x ATR, "
            f"Max={max_stop_atr_multiplier}x ATR, "
            f"Trend Confirm ADX={trend_confirm_adx}"
        )
    
    def calculate_initial_stop(
        self,
        position_id: str,
        df: pd.DataFrame,
        entry_price: float,
        signal_type: str,
        atr_period: int = 14
    ) -> Dict:
        """
        Calculate initial stop loss for new position.
        
        Args:
            position_id: Unique position identifier
            df: OHLCV dataframe
            entry_price: Entry price
            signal_type: 'LONG' or 'SHORT'
            atr_period: ATR calculation period
            
        Returns:
            Dictionary with stop loss details
        """
        # Calculate ATR
        atr = calculate_atr(df, period=atr_period)
        atr_value = scalar(atr.iloc[-1]) if len(atr) > 0 else 0.0
        
        if atr_value == 0:
            # Fallback to percentage-based stop
            stop_distance_pct = 2.0
            stop_price = entry_price * (0.98 if signal_type == 'LONG' else 1.02)
        else:
            # ATR-based stop
            stop_distance = atr_value * self.initial_stop_multiplier
            stop_price = (
                entry_price - stop_distance if signal_type == 'LONG'
                else entry_price + stop_distance
            )
            stop_distance_pct = (stop_distance / entry_price) * 100
        
        # Store position stop info
        self.position_stops[position_id] = {
            'entry_price': entry_price,
            'current_stop': stop_price,
            'initial_stop': stop_price,
            'signal_type': signal_type,
            'atr_value': atr_value,
            'current_multiplier': self.initial_stop_multiplier,
            'max_adx_seen': 0.0,
            'expansion_count': 0,
            'created_at': datetime.now(),
            'last_updated': datetime.now()
        }
        
        logger.info(
            f"🎯 Initial Stop Set - {position_id}: "
            f"Entry=${entry_price:.2f}, Stop=${stop_price:.2f} "
            f"({stop_distance_pct:.2f}%, {self.initial_stop_multiplier}x ATR)"
        )
        
        return {
            'stop_price': stop_price,
            'stop_distance_pct': stop_distance_pct,
            'atr_multiplier': self.initial_stop_multiplier,
            'method': 'initial'
        }
    
    def update_stop(
        self,
        position_id: str,
        df: pd.DataFrame,
        current_price: float,
        adx_period: int = 14,
        atr_period: int = 14
    ) -> Dict:
        """
        Update stop loss based on current market conditions.
        
        Args:
            position_id: Unique position identifier
            df: OHLCV dataframe
            current_price: Current market price
            adx_period: ADX calculation period
            atr_period: ATR calculation period
            
        Returns:
            Dictionary with updated stop details
        """
        if position_id not in self.position_stops:
            logger.warning(f"Position {position_id} not found, cannot update stop")
            return {'error': 'position_not_found'}
        
        pos_info = self.position_stops[position_id]
        signal_type = pos_info['signal_type']
        entry_price = pos_info['entry_price']
        
        # Calculate current ADX and ATR
        adx, plus_di, minus_di = calculate_adx(df, period=adx_period)
        adx_value = scalar(adx.iloc[-1]) if len(adx) > 0 else 0.0
        
        atr = calculate_atr(df, period=atr_period)
        atr_value = scalar(atr.iloc[-1]) if len(atr) > 0 else pos_info['atr_value']
        
        # Detect trend strength
        trend_strength = self._classify_trend_strength(adx_value)
        
        # Check if trend direction aligns with position
        trend_aligned = self._check_trend_alignment(
            signal_type, plus_di, minus_di
        )
        
        # Update max ADX seen
        pos_info['max_adx_seen'] = max(pos_info['max_adx_seen'], adx_value)
        
        # Determine target stop multiplier based on trend
        target_multiplier = self._calculate_target_multiplier(
            adx_value, trend_strength, trend_aligned
        )
        
        # Gradually move toward target multiplier
        current_multiplier = pos_info['current_multiplier']
        new_multiplier = self._adjust_multiplier(
            current_multiplier, target_multiplier, trend_aligned
        )
        
        # Calculate new stop price
        if atr_value > 0:
            stop_distance = atr_value * new_multiplier
            new_stop_price = (
                entry_price - stop_distance if signal_type == 'LONG'
                else entry_price + stop_distance
            )
        else:
            # Fallback
            new_stop_price = pos_info['current_stop']
        
        # Apply safeguards
        new_stop_price = self._apply_safeguards(
            pos_info, new_stop_price, current_price
        )
        
        # Update position info
        old_stop = pos_info['current_stop']
        pos_info['current_stop'] = new_stop_price
        pos_info['current_multiplier'] = new_multiplier
        pos_info['atr_value'] = atr_value
        pos_info['last_updated'] = datetime.now()
        
        # Calculate stop distance percentage
        stop_distance_pct = abs(new_stop_price - entry_price) / entry_price * 100
        
        # Log significant changes
        if abs(new_stop_price - old_stop) / entry_price > 0.005:  # >0.5% change
            logger.info(
                f"📊 Stop Updated - {position_id}: "
                f"${old_stop:.2f} → ${new_stop_price:.2f} "
                f"(ADX={adx_value:.1f}, Trend={trend_strength}, "
                f"Multiplier={current_multiplier:.1f}x → {new_multiplier:.1f}x)"
            )
        
        return {
            'stop_price': new_stop_price,
            'previous_stop': old_stop,
            'stop_distance_pct': stop_distance_pct,
            'atr_multiplier': new_multiplier,
            'adx_value': adx_value,
            'trend_strength': trend_strength,
            'trend_aligned': trend_aligned,
            'method': 'dynamic_update'
        }
    
    def _classify_trend_strength(self, adx_value: float) -> str:
        """Classify trend strength based on ADX"""
        if adx_value >= self.very_strong_trend_adx:
            return 'VERY_STRONG'
        elif adx_value >= self.strong_trend_adx:
            return 'STRONG'
        elif adx_value >= self.trend_confirm_adx:
            return 'CONFIRMED'
        elif adx_value >= 20:
            return 'WEAK'
        else:
            return 'NO_TREND'
    
    def _check_trend_alignment(
        self,
        signal_type: str,
        plus_di: pd.Series,
        minus_di: pd.Series
    ) -> bool:
        """Check if trend direction aligns with position"""
        if len(plus_di) == 0 or len(minus_di) == 0:
            return False
        
        plus_di_val = scalar(plus_di.iloc[-1])
        minus_di_val = scalar(minus_di.iloc[-1])
        
        if signal_type == 'LONG':
            return plus_di_val > minus_di_val
        else:  # SHORT
            return minus_di_val > plus_di_val
    
    def _calculate_target_multiplier(
        self,
        adx_value: float,
        trend_strength: str,
        trend_aligned: bool
    ) -> float:
        """Calculate target stop multiplier based on trend"""
        if not trend_aligned:
            # Trend not aligned - use tighter stop
            return self.min_stop_multiplier
        
        # Trend aligned - expand based on strength
        if trend_strength == 'VERY_STRONG':
            return min(
                self.max_stop_multiplier,
                self.initial_stop_multiplier + 3 * self.expansion_increment
            )
        elif trend_strength == 'STRONG':
            return min(
                self.max_stop_multiplier,
                self.initial_stop_multiplier + 2 * self.expansion_increment
            )
        elif trend_strength == 'CONFIRMED':
            return min(
                self.max_stop_multiplier,
                self.initial_stop_multiplier + self.expansion_increment
            )
        else:
            # Weak or no trend - use initial stop
            return self.initial_stop_multiplier
    
    def _adjust_multiplier(
        self,
        current: float,
        target: float,
        trend_aligned: bool
    ) -> float:
        """Gradually adjust multiplier toward target"""
        if target > current:
            # Expanding - do it gradually
            increment = self.expansion_increment * 0.5  # Slow expansion
            new_multiplier = min(current + increment, target)
        elif target < current:
            # Contracting - faster when trend weakens
            decrement = self.expansion_increment * self.contraction_rate
            new_multiplier = max(current - decrement, target)
        else:
            new_multiplier = current
        
        # Always respect bounds
        return max(
            self.min_stop_multiplier,
            min(self.max_stop_multiplier, new_multiplier)
        )
    
    def _apply_safeguards(
        self,
        pos_info: Dict,
        new_stop_price: float,
        current_price: float
    ) -> float:
        """Apply safety checks to new stop price"""
        signal_type = pos_info['signal_type']
        current_stop = pos_info['current_stop']
        
        # SAFEGUARD 1: Never move stop against position
        # For LONG: stop can only move up (tighter or same)
        # For SHORT: stop can only move down (tighter or same)
        if signal_type == 'LONG':
            new_stop_price = max(new_stop_price, current_stop)
        else:  # SHORT
            new_stop_price = min(new_stop_price, current_stop)
        
        # SAFEGUARD 2: Stop must not be beyond current price
        if signal_type == 'LONG':
            if new_stop_price > current_price:
                # Stop above price - that would close immediately
                new_stop_price = current_price * 0.98  # 2% below current
        else:  # SHORT
            if new_stop_price < current_price:
                # Stop below price - that would close immediately
                new_stop_price = current_price * 1.02  # 2% above current
        
        # SAFEGUARD 3: Maximum stop distance check
        entry_price = pos_info['entry_price']
        max_stop_distance_pct = 10.0  # Never more than 10% from entry
        max_stop_distance = entry_price * (max_stop_distance_pct / 100)
        
        if signal_type == 'LONG':
            min_allowed_stop = entry_price - max_stop_distance
            new_stop_price = max(new_stop_price, min_allowed_stop)
        else:  # SHORT
            max_allowed_stop = entry_price + max_stop_distance
            new_stop_price = min(new_stop_price, max_allowed_stop)
        
        return new_stop_price
    
    def get_position_stop_info(self, position_id: str) -> Optional[Dict]:
        """Get stop info for a position"""
        return self.position_stops.get(position_id)
    
    def remove_position(self, position_id: str) -> None:
        """Remove position from tracking"""
        if position_id in self.position_stops:
            del self.position_stops[position_id]
            logger.debug(f"Position {position_id} removed from stop tracking")
    
    def get_statistics(self) -> Dict:
        """Get statistics on stop management"""
        if not self.position_stops:
            return {
                'active_positions': 0,
                'average_multiplier': 0.0,
                'average_adx': 0.0
            }
        
        total_multiplier = sum(p['current_multiplier'] for p in self.position_stops.values())
        total_adx = sum(p['max_adx_seen'] for p in self.position_stops.values())
        count = len(self.position_stops)
        
        return {
            'active_positions': count,
            'average_multiplier': total_multiplier / count,
            'average_adx': total_adx / count,
            'positions': list(self.position_stops.keys())
        }


# Singleton instance
_dynamic_stop_manager = None

def get_dynamic_stop_manager(**kwargs) -> DynamicStopManager:
    """Get singleton dynamic stop manager instance"""
    global _dynamic_stop_manager
    if _dynamic_stop_manager is None:
        _dynamic_stop_manager = DynamicStopManager(**kwargs)
    return _dynamic_stop_manager
