# risk_manager.py
"""
NIJA Risk Management Module
Dynamic position sizing and risk calculations for Apex Strategy v7.1
"""

import pandas as pd
from typing import Dict, Tuple


class RiskManager:
    """
    Manages position sizing, stop loss, and take profit calculations
    with dynamic adjustments based on trend strength (ADX)
    """
    
    def __init__(self, min_position_pct=0.02, max_position_pct=0.10):
        """
        Initialize Risk Manager
        
        Args:
            min_position_pct: Minimum position size as % of account (default 2%)
            max_position_pct: Maximum position size as % of account (default 10%)
        """
        self.min_position_pct = min_position_pct
        self.max_position_pct = max_position_pct
    
    def calculate_position_size(self, account_balance: float, adx: float, 
                               signal_strength: int = 3) -> float:
        """
        Calculate position size based on ADX (trend strength)
        
        ADX-based allocation:
        - ADX < 20: No trade (weak trend)
        - ADX 20-25: 2% (weak trending)
        - ADX 25-30: 4% (moderate trending)
        - ADX 30-40: 6% (strong trending)
        - ADX 40-50: 8% (very strong trending)
        - ADX > 50: 10% (extremely strong trending)
        
        Args:
            account_balance: Current account balance in USD
            adx: Current ADX value
            signal_strength: Entry signal strength (1-5, default 3)
        
        Returns:
            Position size in USD
        """
        # No trade if ADX < 20
        if adx < 20:
            return 0.0
        
        # Base allocation from ADX
        if adx < 25:
            base_pct = 0.02  # 2%
        elif adx < 30:
            base_pct = 0.04  # 4%
        elif adx < 40:
            base_pct = 0.06  # 6%
        elif adx < 50:
            base_pct = 0.08  # 8%
        else:
            base_pct = 0.10  # 10%
        
        # Adjust for signal strength (optional multiplier)
        # Strong signals (4-5) get slight boost, weak signals (1-2) get reduction
        if signal_strength >= 4:
            multiplier = 1.0  # Full allocation for strong signals
        elif signal_strength == 3:
            multiplier = 0.9  # 90% for moderate signals
        else:
            multiplier = 0.8  # 80% for weak signals
        
        final_pct = base_pct * multiplier
        
        # Clamp to min/max
        final_pct = max(self.min_position_pct, min(final_pct, self.max_position_pct))
        
        return account_balance * final_pct
    
    def calculate_stop_loss(self, entry_price: float, side: str, 
                            swing_level: float, atr: float) -> float:
        """
        Calculate stop loss based on swing low/high plus ATR buffer
        
        Args:
            entry_price: Entry price
            side: 'long' or 'short'
            swing_level: Swing low (for long) or swing high (for short)
            atr: Current ATR(14) value
        
        Returns:
            Stop loss price
        """
        atr_buffer = atr * 0.5  # 0.5 * ATR buffer
        
        if side == 'long':
            # Stop below swing low with ATR buffer
            stop_loss = swing_level - atr_buffer
        else:  # short
            # Stop above swing high with ATR buffer
            stop_loss = swing_level + atr_buffer
        
        return stop_loss
    
    def calculate_take_profit_levels(self, entry_price: float, stop_loss: float,
                                     side: str) -> Dict[str, float]:
        """
        Calculate take profit levels based on R-multiples
        
        Args:
            entry_price: Entry price
            stop_loss: Stop loss price
            side: 'long' or 'short'
        
        Returns:
            Dictionary with TP1 (1R), TP2 (2R), TP3 (3R) levels
        """
        # Calculate R (risk per share)
        if side == 'long':
            risk = entry_price - stop_loss
            tp1 = entry_price + (risk * 1.0)  # 1R
            tp2 = entry_price + (risk * 2.0)  # 2R
            tp3 = entry_price + (risk * 3.0)  # 3R
        else:  # short
            risk = stop_loss - entry_price
            tp1 = entry_price - (risk * 1.0)  # 1R
            tp2 = entry_price - (risk * 2.0)  # 2R
            tp3 = entry_price - (risk * 3.0)  # 3R
        
        return {
            'tp1': tp1,
            'tp2': tp2,
            'tp3': tp3,
            'risk': risk
        }
    
    def calculate_trailing_stop(self, current_price: float, entry_price: float,
                                side: str, atr: float, breakeven_mode: bool = False) -> float:
        """
        Calculate trailing stop after TP1 is hit
        
        Uses ATR(14) * 1.5 for trailing distance
        
        Args:
            current_price: Current market price
            entry_price: Original entry price
            side: 'long' or 'short'
            atr: Current ATR(14) value
            breakeven_mode: If True, don't trail below/above breakeven
        
        Returns:
            Trailing stop price
        """
        trailing_distance = atr * 1.5
        
        if side == 'long':
            trailing_stop = current_price - trailing_distance
            if breakeven_mode:
                trailing_stop = max(trailing_stop, entry_price)
        else:  # short
            trailing_stop = current_price + trailing_distance
            if breakeven_mode:
                trailing_stop = min(trailing_stop, entry_price)
        
        return trailing_stop
    
    def find_swing_low(self, df: pd.DataFrame, lookback: int = 10) -> float:
        """
        Find recent swing low for stop loss placement
        
        Args:
            df: DataFrame with 'low' column
            lookback: Number of candles to look back (default 10)
        
        Returns:
            Swing low price
        """
        if len(df) < lookback:
            return df['low'].iloc[-1]
        
        return df['low'].iloc[-lookback:].min()
    
    def find_swing_high(self, df: pd.DataFrame, lookback: int = 10) -> float:
        """
        Find recent swing high for stop loss placement
        
        Args:
            df: DataFrame with 'high' column
            lookback: Number of candles to look back (default 10)
        
        Returns:
            Swing high price
        """
        if len(df) < lookback:
            return df['high'].iloc[-1]
        
        return df['high'].iloc[-lookback:].max()
