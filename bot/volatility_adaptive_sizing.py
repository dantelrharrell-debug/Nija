"""
NIJA Volatility-Adaptive Position Sizing

Dynamically adjusts position sizes based on current market volatility.
Uses ATR (Average True Range) to normalize position sizes across different
volatility regimes.

Key Principle: 
- Low volatility → Larger position sizes (less risk per dollar)
- High volatility → Smaller position sizes (more risk per dollar)
- Goal: Maintain consistent risk exposure regardless of market conditions

Features:
- ATR-based volatility measurement
- Normalized position sizing
- Volatility regime detection
- Dynamic size scaling
- Risk-parity position allocation

Author: NIJA Trading Systems
Version: 1.0
Date: February 2026
"""

import logging
from typing import Dict, Tuple, Optional
import pandas as pd
import numpy as np

logger = logging.getLogger("nija.volatility_adaptive_sizing")

# Import indicators
try:
    from indicators import calculate_atr, scalar
except ImportError:
    try:
        from bot.indicators import calculate_atr, scalar
    except ImportError:
        # Fallback definitions
        def scalar(x):
            if isinstance(x, (tuple, list)):
                return float(x[0]) if len(x) > 0 else 0.0
            return float(x)
        
        def calculate_atr(df, period=14):
            return pd.Series([0.0] * len(df))


class VolatilityAdaptiveSizer:
    """
    Adjusts position sizes based on market volatility.
    
    Methodology:
    1. Calculate ATR as percentage of price (volatility measure)
    2. Normalize volatility against historical baseline
    3. Scale position size inversely with volatility
    4. Apply bounds to prevent extreme positions
    
    Example:
    - Asset A: ATR = 1% (low volatility) → Position size = 10% of capital
    - Asset B: ATR = 5% (high volatility) → Position size = 2% of capital
    Both positions have similar risk exposure in dollar terms.
    """
    
    def __init__(
        self,
        base_position_pct: float = 0.05,
        target_volatility_pct: float = 2.0,
        min_position_pct: float = 0.02,
        max_position_pct: float = 0.15,
        atr_period: int = 14,
        volatility_lookback: int = 50
    ):
        """
        Initialize volatility-adaptive sizer.
        
        Args:
            base_position_pct: Base position size (e.g., 0.05 = 5%)
            target_volatility_pct: Target volatility level (e.g., 2.0 = 2% ATR)
            min_position_pct: Minimum position size cap
            max_position_pct: Maximum position size cap
            atr_period: ATR calculation period
            volatility_lookback: Periods to lookback for volatility regime
        """
        self.base_position_pct = base_position_pct
        self.target_volatility_pct = target_volatility_pct
        self.min_position_pct = min_position_pct
        self.max_position_pct = max_position_pct
        self.atr_period = atr_period
        self.volatility_lookback = volatility_lookback
        
        logger.info(
            f"✅ Volatility-Adaptive Sizing initialized: "
            f"Base={base_position_pct*100:.1f}%, Target Vol={target_volatility_pct:.1f}%, "
            f"Range={min_position_pct*100:.1f}%-{max_position_pct*100:.1f}%"
        )
    
    def calculate_position_size(
        self,
        df: pd.DataFrame,
        account_balance: float,
        current_price: float,
        base_size_pct: Optional[float] = None
    ) -> Tuple[float, Dict]:
        """
        Calculate volatility-adjusted position size.
        
        Args:
            df: OHLCV dataframe
            account_balance: Current account balance
            current_price: Current market price
            base_size_pct: Override base position size (optional)
            
        Returns:
            Tuple of (position_size_usd, details_dict)
        """
        # Use provided base size or default
        base_pct = base_size_pct if base_size_pct is not None else self.base_position_pct
        
        # Calculate current ATR
        if len(df) < self.atr_period:
            logger.warning("Insufficient data for ATR calculation, using base size")
            position_size_usd = account_balance * base_pct
            return position_size_usd, {
                'method': 'fallback',
                'base_pct': base_pct,
                'adjusted_pct': base_pct,
                'volatility_pct': 0.0,
                'volatility_multiplier': 1.0
            }
        
        atr = calculate_atr(df, period=self.atr_period)
        atr_value = scalar(atr.iloc[-1])
        
        # Calculate ATR as percentage of price
        atr_pct = (atr_value / current_price) * 100
        
        # Detect volatility regime
        volatility_regime = self._detect_volatility_regime(df, atr_pct)
        
        # Calculate volatility multiplier (inverse relationship)
        # volatility_multiplier = target_volatility / current_volatility
        # Higher volatility → smaller multiplier → smaller position
        # Lower volatility → larger multiplier → larger position
        if atr_pct > 0:
            volatility_multiplier = self.target_volatility_pct / atr_pct
        else:
            volatility_multiplier = 1.0
        
        # Apply multiplier to base position size
        adjusted_pct = base_pct * volatility_multiplier
        
        # Apply regime-based adjustments
        adjusted_pct = self._apply_regime_adjustment(adjusted_pct, volatility_regime)
        
        # Clamp to min/max bounds
        adjusted_pct = max(self.min_position_pct, min(self.max_position_pct, adjusted_pct))
        
        # Calculate position size in USD
        position_size_usd = account_balance * adjusted_pct
        
        details = {
            'method': 'volatility_adaptive',
            'base_pct': base_pct,
            'adjusted_pct': adjusted_pct,
            'volatility_pct': atr_pct,
            'volatility_multiplier': volatility_multiplier,
            'volatility_regime': volatility_regime,
            'position_size_usd': position_size_usd,
            'atr_value': atr_value
        }
        
        logger.debug(
            f"📐 Volatility-Adaptive Sizing: {base_pct*100:.1f}% → {adjusted_pct*100:.1f}% "
            f"(ATR={atr_pct:.2f}%, Regime={volatility_regime}, Multiplier={volatility_multiplier:.2f}x)"
        )
        
        return position_size_usd, details
    
    def _detect_volatility_regime(self, df: pd.DataFrame, current_atr_pct: float) -> str:
        """
        Detect current volatility regime.
        
        Args:
            df: OHLCV dataframe
            current_atr_pct: Current ATR as percentage
            
        Returns:
            Volatility regime: 'LOW', 'NORMAL', 'HIGH', 'EXTREME'
        """
        if len(df) < self.volatility_lookback:
            return 'NORMAL'
        
        # Calculate historical ATR percentages
        recent_df = df.tail(self.volatility_lookback)
        atr_series = calculate_atr(recent_df, period=self.atr_period)
        
        if len(atr_series) == 0:
            return 'NORMAL'
        
        # Calculate ATR percentages for lookback period
        atr_pcts = []
        for i in range(len(recent_df)):
            if i < len(atr_series) and not pd.isna(atr_series.iloc[i]):
                close_price = recent_df.iloc[i]['close']
                if close_price > 0:
                    atr_pct = (scalar(atr_series.iloc[i]) / close_price) * 100
                    atr_pcts.append(atr_pct)
        
        if not atr_pcts:
            return 'NORMAL'
        
        # Calculate percentiles
        atr_array = np.array(atr_pcts)
        p25 = np.percentile(atr_array, 25)
        p75 = np.percentile(atr_array, 75)
        p90 = np.percentile(atr_array, 90)
        
        # Classify regime
        if current_atr_pct > p90:
            return 'EXTREME'
        elif current_atr_pct > p75:
            return 'HIGH'
        elif current_atr_pct < p25:
            return 'LOW'
        else:
            return 'NORMAL'
    
    def _apply_regime_adjustment(self, adjusted_pct: float, regime: str) -> float:
        """
        Apply additional adjustments based on volatility regime.
        
        Args:
            adjusted_pct: Base adjusted position percentage
            regime: Volatility regime
            
        Returns:
            Further adjusted position percentage
        """
        # Additional safety factor for extreme regimes
        if regime == 'EXTREME':
            # Extra conservative in extreme volatility
            return adjusted_pct * 0.8
        elif regime == 'HIGH':
            # Slightly more conservative in high volatility
            return adjusted_pct * 0.9
        elif regime == 'LOW':
            # Can be slightly more aggressive in low volatility
            return adjusted_pct * 1.1
        else:
            # No adjustment for normal regime
            return adjusted_pct
    
    def calculate_stop_distance(
        self,
        df: pd.DataFrame,
        current_price: float,
        base_stop_multiplier: float = 2.0
    ) -> Tuple[float, Dict]:
        """
        Calculate volatility-adjusted stop loss distance.
        
        Args:
            df: OHLCV dataframe
            current_price: Current market price
            base_stop_multiplier: Base ATR multiplier for stop (default 2.0)
            
        Returns:
            Tuple of (stop_distance_pct, details_dict)
        """
        if len(df) < self.atr_period:
            # Fallback to 2% stop
            return 2.0, {'method': 'fallback'}
        
        # Calculate ATR
        atr = calculate_atr(df, period=self.atr_period)
        atr_value = scalar(atr.iloc[-1])
        
        # Calculate stop distance as multiple of ATR
        stop_distance = atr_value * base_stop_multiplier
        stop_distance_pct = (stop_distance / current_price) * 100
        
        # Clamp to reasonable range (0.5% - 10%)
        stop_distance_pct = max(0.5, min(10.0, stop_distance_pct))
        
        details = {
            'method': 'atr_based',
            'atr_value': atr_value,
            'atr_pct': (atr_value / current_price) * 100,
            'multiplier': base_stop_multiplier,
            'stop_distance_pct': stop_distance_pct
        }
        
        return stop_distance_pct, details
    
    def calculate_portfolio_heat(
        self,
        open_positions: list,
        account_balance: float
    ) -> Dict:
        """
        Calculate total portfolio volatility exposure (portfolio heat).
        
        Args:
            open_positions: List of position dicts with 'size', 'atr_pct'
            account_balance: Current account balance
            
        Returns:
            Dictionary with portfolio heat metrics
        """
        if not open_positions:
            return {
                'total_exposure_pct': 0.0,
                'volatility_weighted_exposure': 0.0,
                'position_count': 0,
                'average_position_volatility': 0.0
            }
        
        total_notional = 0.0
        volatility_weighted_notional = 0.0
        total_volatility = 0.0
        
        for pos in open_positions:
            position_size = pos.get('size', 0)
            atr_pct = pos.get('atr_pct', 2.0)  # Default 2% if not provided
            
            total_notional += position_size
            # Weight by volatility: high volatility positions count more toward risk
            volatility_weighted_notional += position_size * (atr_pct / 2.0)
            total_volatility += atr_pct
        
        total_exposure_pct = (total_notional / account_balance * 100) if account_balance > 0 else 0
        vol_weighted_exposure = (volatility_weighted_notional / account_balance * 100) if account_balance > 0 else 0
        avg_volatility = total_volatility / len(open_positions) if open_positions else 0
        
        return {
            'total_exposure_pct': total_exposure_pct,
            'volatility_weighted_exposure': vol_weighted_exposure,
            'position_count': len(open_positions),
            'average_position_volatility': avg_volatility,
            'total_notional': total_notional
        }


# Singleton instance
_volatility_adaptive_sizer = None

def get_volatility_adaptive_sizer(**kwargs) -> VolatilityAdaptiveSizer:
    """Get singleton volatility adaptive sizer instance"""
    global _volatility_adaptive_sizer
    if _volatility_adaptive_sizer is None:
        _volatility_adaptive_sizer = VolatilityAdaptiveSizer(**kwargs)
    return _volatility_adaptive_sizer
