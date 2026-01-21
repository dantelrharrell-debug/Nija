"""
NIJA Apex Strategy v7.1 - Main Strategy Implementation
========================================================

High-probability trading strategy with:
- Market filters (ADX, VWAP, EMA, MACD, volume)
- Precise entry triggers
- Dynamic risk management
- Multi-stage exits
- Trailing stop system
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple
from datetime import datetime
import logging

# Import Apex modules
from apex_indicators import (
    calculate_adx,
    calculate_atr,
    calculate_enhanced_macd,
    calculate_vwap,
    calculate_rsi,
    calculate_ema_alignment,
    find_swing_low,
    find_swing_high,
    is_volume_above_threshold,
    is_bullish_reversal_candle,
    is_bearish_reversal_candle,
)
from apex_config import (
    MARKET_FILTER,
    INDICATORS,
    ENTRY_TRIGGERS,
    STOP_LOSS,
    EXIT_LOGIC,
    EXECUTION,
)
from apex_risk_manager import ApexRiskManager
from apex_filters import ApexSmartFilters
from apex_trailing_system import ApexTrailingSystem
from apex_ai_engine import ApexAIEngine

# Import scalar helper for indicator conversions
try:
    from indicators import scalar
except ImportError:
    # Fallback if indicators.py is not available
    def scalar(x):
        if isinstance(x, (tuple, list)):
            return float(x[0])
        return float(x)

logger = logging.getLogger("nija.apex")


class ApexStrategyV7:
    """
    NIJA Apex Strategy v7.1
    
    Advanced trading strategy with market filters, high-probability entries,
    dynamic risk management, and intelligent exit logic.
    """
    
    def __init__(self, account_balance: float, enable_ai: bool = False):
        """
        Initialize Apex Strategy v7.1
        
        Args:
            account_balance: Current account balance
            enable_ai: Enable AI momentum engine (requires trained model)
        """
        self.account_balance = account_balance
        self.risk_manager = ApexRiskManager(account_balance)
        self.smart_filters = ApexSmartFilters()
        self.trailing_system = ApexTrailingSystem()
        self.ai_engine = ApexAIEngine() if enable_ai else None
        
        logger.info(f"Apex Strategy v7.1 initialized with balance: ${account_balance:,.2f}")
        logger.info(f"AI Engine: {'Enabled' if enable_ai else 'Disabled'}")
    
    def update_balance(self, new_balance: float):
        """Update account balance"""
        self.account_balance = new_balance
        self.risk_manager.update_account_balance(new_balance)
    
    def calculate_all_indicators(self, df: pd.DataFrame) -> Dict:
        """
        Calculate all required indicators
        
        Args:
            df: DataFrame with OHLCV data
            
        Returns:
            dict: All calculated indicators
        """
        min_candles = EXECUTION['min_candles_required']
        if len(df) < min_candles:
            logger.warning(f"Insufficient data: {len(df)} candles (need {min_candles}+)")
            return None
        
        # Calculate indicators
        adx, plus_di, minus_di = calculate_adx(df, INDICATORS['adx_period'])
        atr = calculate_atr(df, INDICATORS['atr_period'])
        vwap = calculate_vwap(df)
        rsi = calculate_rsi(df, INDICATORS['rsi_period'])
        
        macd_line, signal_line, histogram, hist_direction = calculate_enhanced_macd(
            df,
            INDICATORS['macd_fast'],
            INDICATORS['macd_slow'],
            INDICATORS['macd_signal']
        )
        
        ema_data = calculate_ema_alignment(df)
        
        indicators = {
            'adx': scalar(adx.iloc[-1]),
            'plus_di': scalar(plus_di.iloc[-1]),
            'minus_di': scalar(minus_di.iloc[-1]),
            'atr': scalar(atr.iloc[-1]),
            'vwap': scalar(vwap.iloc[-1]),
            'rsi': scalar(rsi.iloc[-1]),
            'macd_line': scalar(macd_line.iloc[-1]),
            'macd_signal': scalar(signal_line.iloc[-1]),
            'macd_histogram': scalar(histogram.iloc[-1]),
            'macd_direction': scalar(hist_direction.iloc[-1]),
            'ema9': scalar(ema_data['ema9'].iloc[-1]),
            'ema21': scalar(ema_data['ema21'].iloc[-1]),
            'ema_bullish_alignment': ema_data['bullish_alignment'],
            'ema_bearish_alignment': ema_data['bearish_alignment'],
        }
        
        # Add EMA50 if available
        if 'ema50' in ema_data:
            indicators['ema50'] = scalar(ema_data['ema50'].iloc[-1])
        
        return indicators
    
    def check_market_filter(self, df: pd.DataFrame, indicators: Dict) -> Tuple[bool, str, str]:
        """
        Check if market conditions are suitable for trading
        
        Args:
            df: DataFrame with OHLCV data
            indicators: Calculated indicators
            
        Returns:
            tuple: (passes_filter, trend_direction, reason)
        """
        adx = indicators['adx']
        plus_di = indicators['plus_di']
        minus_di = indicators['minus_di']
        
        # 1. Check ADX threshold (trend strength)
        if adx < MARKET_FILTER['adx_threshold']:
            return False, 'NEUTRAL', f"ADX too low ({adx:.1f} < {MARKET_FILTER['adx_threshold']})"
        
        # 2. Determine trend direction
        trend_direction = self.risk_manager.get_trend_direction(plus_di, minus_di)
        
        if trend_direction == 'NEUTRAL' and MARKET_FILTER['trend_required']:
            return False, 'NEUTRAL', "No clear trend direction"
        
        # 3. Check volume
        volume_ok = is_volume_above_threshold(df, MARKET_FILTER['volume_threshold'])
        if not volume_ok:
            return False, trend_direction, "Volume below threshold"
        
        # 4. Check smart filters
        any_blocked, blocking_reasons = self.smart_filters.check_all_filters(
            df, adx, candle_open_time=None, current_time=None
        )
        
        if any_blocked:
            return False, trend_direction, f"Smart filter blocked: {blocking_reasons}"
        
        return True, trend_direction, "Market filter passed"
    
    def check_long_entry(self, df: pd.DataFrame, indicators: Dict) -> Tuple[bool, int, list]:
        """
        Check long entry conditions
        
        Args:
            df: DataFrame with OHLCV data
            indicators: Calculated indicators
            
        Returns:
            tuple: (should_enter, score, conditions_met)
        """
        current_price = df['close'].iloc[-1]
        conditions_met = []
        score = 0
        
        # Condition 1: Price pulls to EMA21 or VWAP
        pullback_threshold = ENTRY_TRIGGERS['pullback_threshold']
        distance_to_ema21 = abs(current_price - indicators['ema21']) / current_price
        distance_to_vwap = abs(current_price - indicators['vwap']) / current_price
        
        if distance_to_ema21 <= pullback_threshold or distance_to_vwap <= pullback_threshold:
            conditions_met.append("Price at EMA21/VWAP")
            score += 1
        
        # Condition 2: RSI in bullish zone
        rsi = indicators['rsi']
        rsi_min = INDICATORS['rsi_bullish_min']
        rsi_max = INDICATORS['rsi_bullish_max']
        
        if rsi_min <= rsi <= rsi_max:
            conditions_met.append(f"RSI bullish ({rsi:.1f})")
            score += 1
        
        # Condition 3: Bullish reversal candle
        if is_bullish_reversal_candle(df):
            conditions_met.append("Bullish reversal candle")
            score += 1
        
        # Condition 4: MACD histogram uptick
        if indicators['macd_histogram'] > 0 and indicators['macd_direction'] > 0:
            conditions_met.append("MACD uptick")
            score += 1
        
        # Condition 5: Volume confirmation
        if is_volume_above_threshold(df, MARKET_FILTER['volume_threshold']):
            conditions_met.append("Volume confirmed")
            score += 1
        
        # Check minimum conditions
        required = ENTRY_TRIGGERS['long']['required_conditions']
        should_enter = score >= required
        
        return should_enter, score, conditions_met
    
    def check_short_entry(self, df: pd.DataFrame, indicators: Dict) -> Tuple[bool, int, list]:
        """
        Check short entry conditions
        
        Args:
            df: DataFrame with OHLCV data
            indicators: Calculated indicators
            
        Returns:
            tuple: (should_enter, score, conditions_met)
        """
        current_price = df['close'].iloc[-1]
        conditions_met = []
        score = 0
        
        # Condition 1: Price pulls to EMA21 or VWAP
        pullback_threshold = ENTRY_TRIGGERS['pullback_threshold']
        distance_to_ema21 = abs(current_price - indicators['ema21']) / current_price
        distance_to_vwap = abs(current_price - indicators['vwap']) / current_price
        
        if distance_to_ema21 <= pullback_threshold or distance_to_vwap <= pullback_threshold:
            conditions_met.append("Price at EMA21/VWAP")
            score += 1
        
        # Condition 2: RSI in bearish zone
        rsi = indicators['rsi']
        rsi_min = INDICATORS['rsi_bearish_min']
        rsi_max = INDICATORS['rsi_bearish_max']
        
        if rsi_min <= rsi <= rsi_max:
            conditions_met.append(f"RSI bearish ({rsi:.1f})")
            score += 1
        
        # Condition 3: Bearish reversal candle
        if is_bearish_reversal_candle(df):
            conditions_met.append("Bearish reversal candle")
            score += 1
        
        # Condition 4: MACD histogram downtick
        if indicators['macd_histogram'] < 0 and indicators['macd_direction'] < 0:
            conditions_met.append("MACD downtick")
            score += 1
        
        # Condition 5: Volume confirmation
        if is_volume_above_threshold(df, MARKET_FILTER['volume_threshold']):
            conditions_met.append("Volume confirmed")
            score += 1
        
        # Check minimum conditions
        required = ENTRY_TRIGGERS['short']['required_conditions']
        should_enter = score >= required
        
        return should_enter, score, conditions_met
    
    def calculate_stop_loss(self, df: pd.DataFrame, indicators: Dict, side: str) -> float:
        """
        Calculate stop loss using swing points + ATR buffer
        
        Args:
            df: DataFrame with OHLCV data
            indicators: Calculated indicators
            side: 'long' or 'short'
            
        Returns:
            float: Stop loss price
        """
        entry_price = df['close'].iloc[-1]
        atr = indicators['atr']
        atr_buffer = atr * STOP_LOSS['atr_multiplier']
        
        if side == 'long':
            # Find swing low
            swing_low = find_swing_low(df, STOP_LOSS['swing_lookback'])
            stop_loss = swing_low - atr_buffer
            
            # Ensure minimum/maximum stop distance
            min_stop = entry_price * (1 - STOP_LOSS['max_stop_distance'])
            max_stop = entry_price * (1 - STOP_LOSS['min_stop_distance'])
            stop_loss = max(min_stop, min(stop_loss, max_stop))
            
        else:  # short
            # Find swing high
            swing_high = find_swing_high(df, STOP_LOSS['swing_lookback'])
            stop_loss = swing_high + atr_buffer
            
            # Ensure minimum/maximum stop distance
            min_stop = entry_price * (1 + STOP_LOSS['min_stop_distance'])
            max_stop = entry_price * (1 + STOP_LOSS['max_stop_distance'])
            stop_loss = min(max_stop, max(stop_loss, min_stop))
        
        return stop_loss
    
    def analyze_entry_opportunity(
        self,
        df: pd.DataFrame,
        symbol: str
    ) -> Dict:
        """
        Analyze potential entry opportunity for a symbol
        
        Args:
            df: DataFrame with OHLCV data
            symbol: Trading symbol
            
        Returns:
            dict: Analysis results with entry recommendation
        """
        # Calculate indicators
        indicators = self.calculate_all_indicators(df)
        
        if indicators is None:
            return {
                'symbol': symbol,
                'should_enter': False,
                'reason': 'Insufficient data',
            }
        
        # Check market filter
        passes_filter, trend_direction, filter_reason = self.check_market_filter(df, indicators)
        
        if not passes_filter:
            return {
                'symbol': symbol,
                'should_enter': False,
                'reason': filter_reason,
                'trend_direction': trend_direction,
                'adx': indicators['adx'],
            }
        
        # Check AI score if enabled
        if self.ai_engine and self.ai_engine.is_enabled():
            ai_result = self.ai_engine.calculate_momentum_score(df, indicators)
            if not ai_result['meets_threshold']:
                return {
                    'symbol': symbol,
                    'should_enter': False,
                    'reason': ai_result['reason'],
                    'ai_score': ai_result['score'],
                }
        
        # Check entry conditions based on trend direction
        if trend_direction == 'UP':
            should_enter, score, conditions = self.check_long_entry(df, indicators)
            side = 'long'
        elif trend_direction == 'DOWN':
            should_enter, score, conditions = self.check_short_entry(df, indicators)
            side = 'short'
        else:
            return {
                'symbol': symbol,
                'should_enter': False,
                'reason': 'No clear trend direction',
            }
        
        if not should_enter:
            return {
                'symbol': symbol,
                'should_enter': False,
                'reason': f'Entry conditions not met ({score}/{ENTRY_TRIGGERS[side]["required_conditions"]})',
                'score': score,
                'conditions': conditions,
            }
        
        # Check risk limits
        can_open, risk_reason = self.risk_manager.can_open_position()
        if not can_open:
            return {
                'symbol': symbol,
                'should_enter': False,
                'reason': risk_reason,
            }
        
        # Calculate trade parameters
        entry_price = df['close'].iloc[-1]
        stop_loss = self.calculate_stop_loss(df, indicators, side)
        
        # Assess trend quality
        trend_quality = self.risk_manager.assess_trend_quality(
            indicators['adx'],
            indicators['plus_di'],
            indicators['minus_di']
        )
        
        # Calculate position size
        position_size_usd, position_size_pct, risk_amount = self.risk_manager.calculate_position_size(
            trend_quality,
            entry_price,
            stop_loss
        )
        
        # Calculate take profit levels
        tp_levels = self.risk_manager.calculate_take_profit_levels(
            entry_price,
            stop_loss,
            side
        )
        
        return {
            'symbol': symbol,
            'should_enter': True,
            'side': side,
            'entry_price': entry_price,
            'stop_loss': stop_loss,
            'take_profit_levels': tp_levels,
            'position_size_usd': position_size_usd,
            'position_size_pct': position_size_pct,
            'risk_amount': risk_amount,
            'trend_direction': trend_direction,
            'trend_quality': trend_quality,
            'adx': indicators['adx'],
            'score': score,
            'conditions_met': conditions,
            'atr': indicators['atr'],
        }
    
    def update_position(
        self,
        position_id: str,
        df: pd.DataFrame,
        position: Dict
    ) -> Dict:
        """
        Update position with trailing stops and exit signals
        
        Args:
            position_id: Unique position identifier
            df: Current DataFrame with OHLCV data
            position: Position dict with entry details
            
        Returns:
            dict: Updated position with exit recommendations
        """
        indicators = self.calculate_all_indicators(df)
        if indicators is None:
            return {'action': 'hold', 'reason': 'Insufficient data'}
        
        current_price = df['close'].iloc[-1]
        entry_price = position['entry_price']
        stop_loss = position['stop_loss']
        side = position['side']
        atr = indicators['atr']
        
        # Calculate R-multiple
        r_multiple = self.risk_manager.calculate_r_multiple(
            entry_price,
            current_price,
            stop_loss
        )
        
        # Update trailing stop
        trailing_result = self.trailing_system.update_trailing_stop(
            position_id,
            current_price,
            entry_price,
            stop_loss,
            atr,
            side,
            r_multiple
        )
        
        # Check for exit signals
        exit_signal = self.trailing_system.get_exit_signals(
            position_id,
            r_multiple,
            current_price,
            stop_loss,
            side
        )
        
        # Check trend break
        if EXIT_LOGIC['trend_break']['enabled']:
            trend_broken = self.trailing_system.check_trend_break(df, side)
            if trend_broken:
                return {
                    'action': 'exit',
                    'exit_percentage': 1.0,
                    'reason': 'Trend break (EMA cross)',
                    'new_stop': trailing_result['new_stop'],
                }
        
        # Check opposite signal
        if EXIT_LOGIC['opposite_signal']:
            if side == 'long':
                opposite_enter, _, _ = self.check_short_entry(df, indicators)
            else:
                opposite_enter, _, _ = self.check_long_entry(df, indicators)
            
            if opposite_enter:
                return {
                    'action': 'exit',
                    'exit_percentage': 1.0,
                    'reason': 'Opposite signal detected',
                    'new_stop': trailing_result['new_stop'],
                }
        
        # Return exit signal if any
        if exit_signal['should_exit']:
            return {
                'action': 'exit',
                'exit_percentage': exit_signal['exit_percentage'],
                'reason': exit_signal['reason'],
                'new_stop': trailing_result['new_stop'],
            }
        
        # Otherwise, just update stop
        return {
            'action': 'update_stop',
            'new_stop': trailing_result['new_stop'],
            'r_multiple': r_multiple,
            'action_taken': trailing_result['action_taken'],
        }
