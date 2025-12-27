# nija_apex_strategy_v71.py
"""
NIJA APEX STRATEGY v7.1
Unified algorithmic trading strategy with advanced market filters and risk management

Author: NIJA Trading Systems
Version: 7.1
Date: December 2024
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List
import logging
import os

from indicators import (
    calculate_vwap, calculate_ema, calculate_rsi, calculate_macd,
    calculate_atr, calculate_adx
)
from risk_manager import RiskManager
from execution_engine import ExecutionEngine

logger = logging.getLogger("nija")


class NIJAApexStrategyV71:
    """
    NIJA Apex Strategy v7.1 - Unified Algorithmic Trading System
    
    Features:
    1. Market Filter (uptrend/downtrend using VWAP, EMA9/21/50, MACD, ADX>20, Volume)
    2. Entry Logic (pullback to EMA21/VWAP, RSI, candlestick patterns, MACD tick, volume)
    3. Dynamic Risk Management (ADX-based position sizing 2-10%, ATR stop loss)
    4. Exit Logic (opposite signal, trailing stop, trend break)
    5. Smart Filters (news, volume, candle timing)
    6. Optional: AI Momentum Scoring (skeleton)
    """
    
    def __init__(self, broker_client=None, config: Optional[Dict] = None):
        """
        Initialize NIJA Apex Strategy v7.1
        
        Args:
            broker_client: Broker API client (Coinbase, Alpaca, Binance, etc.)
            config: Strategy configuration dictionary
        """
        self.broker_client = broker_client
        self.config = config or {}
        
        # Initialize components
        self.risk_manager = RiskManager(
            min_position_pct=self.config.get('min_position_pct', 0.02),
            max_position_pct=self.config.get('max_position_pct', 0.05)  # Reduced from 10% to 5% for tighter position sizing
        )
        self.execution_engine = ExecutionEngine(broker_client)
        
        # Strategy parameters - PROFITABILITY FIX: Balanced for crypto markets
        self.min_adx = self.config.get('min_adx', 20)  # Industry standard for crypto - strong enough to avoid chop
        self.volume_threshold = self.config.get('volume_threshold', 0.5)  # 50% of 5-candle avg - reasonable liquidity
        self.volume_min_threshold = self.config.get('volume_min_threshold', 0.25)  # 25% minimum - avoid dead markets
        self.candle_exclusion_seconds = self.config.get('candle_exclusion_seconds', 6)
        self.news_buffer_minutes = self.config.get('news_buffer_minutes', 5)
        
        # AI Momentum Scoring (optional, skeleton for future)
        self.ai_momentum_enabled = self.config.get('ai_momentum_enabled', False)
        
        # Track last candle time for timing filter
        self.last_candle_time = None
        
        logger.info("NIJA Apex Strategy v7.1 initialized")
    
    def check_market_filter(self, df: pd.DataFrame, indicators: Dict) -> Tuple[bool, str, str]:
        """
        Market Filter: Only allow trades if uptrend or downtrend conditions are met
        
        Required conditions:
        - VWAP alignment (price above for uptrend, below for downtrend)
        - EMA sequence (9 > 21 > 50 for uptrend, 9 < 21 < 50 for downtrend)
        - MACD histogram alignment (positive for uptrend, negative for downtrend)
        - ADX > 20 (sufficient trend strength)
        - Volume > 50% of 5-candle average
        
        Args:
            df: Price DataFrame
            indicators: Dictionary of calculated indicators
        
        Returns:
            Tuple of (allow_trade, direction, reason)
            - allow_trade: True if market conditions permit trading
            - direction: 'uptrend', 'downtrend', or 'none'
            - reason: Explanation string
        """
        # Get current values
        current_price = df['close'].iloc[-1]
        vwap = indicators['vwap'].iloc[-1]
        ema9 = indicators['ema_9'].iloc[-1]
        ema21 = indicators['ema_21'].iloc[-1]
        ema50 = indicators['ema_50'].iloc[-1]
        macd_hist = indicators['histogram'].iloc[-1]
        adx = indicators['adx'].iloc[-1]
        
        # Volume check (5-candle average)
        avg_volume_5 = df['volume'].iloc[-5:].mean()
        current_volume = df['volume'].iloc[-1]
        volume_ratio = current_volume / avg_volume_5 if avg_volume_5 > 0 else 0
        
        # ADX filter - relaxed for ULTRA AGGRESSIVE mode (15-day goal)
        if self.min_adx > 0 and adx < self.min_adx:
            return False, 'none', f'ADX too low ({adx:.1f} < {self.min_adx})'
        
        # Volume filter - relaxed for ULTRA AGGRESSIVE mode (15-day goal)
        if self.volume_threshold > 0 and volume_ratio < self.volume_threshold:
            return False, 'none', f'Volume too low ({volume_ratio*100:.1f}% of 5-candle avg)'
        
        # Check for uptrend
        uptrend_conditions = {
            'vwap': current_price > vwap,
            'ema_sequence': ema9 > ema21 > ema50,
            'macd_positive': macd_hist > 0,
            'adx_strong': adx > self.min_adx,
            'volume_ok': volume_ratio >= self.volume_threshold
        }
        
        # Check for downtrend
        downtrend_conditions = {
            'vwap': current_price < vwap,
            'ema_sequence': ema9 < ema21 < ema50,
            'macd_negative': macd_hist < 0,
            'adx_strong': adx > self.min_adx,
            'volume_ok': volume_ratio >= self.volume_threshold
        }
        
        # PROFITABILITY FIX: Require 3 of 5 conditions (balanced approach)
        # 3/5 allows good opportunities while filtering weak markets
        uptrend_score = sum(uptrend_conditions.values())
        downtrend_score = sum(downtrend_conditions.values())
        
        # Log details for debugging
        logger.debug(f"Market filter - Uptrend: {uptrend_score}/5, Downtrend: {downtrend_score}/5")
        logger.debug(f"  Price vs VWAP: {current_price:.4f} vs {vwap:.4f}")
        logger.debug(f"  EMA sequence: {ema9:.4f} vs {ema21:.4f} vs {ema50:.4f}")
        logger.debug(f"  MACD histogram: {macd_hist:.6f}, ADX: {adx:.1f}, Vol ratio: {volume_ratio:.2f}")
        
        if uptrend_score >= 3:  # PROFITABILITY FIX: 3/5 filters for better trade opportunities
            return True, 'uptrend', f'Uptrend confirmed ({uptrend_score}/5 - ADX={adx:.1f}, Vol={volume_ratio*100:.0f}%)'
        elif downtrend_score >= 3:  # PROFITABILITY FIX: 3/5 filters for better trade opportunities
            return True, 'downtrend', f'Downtrend confirmed ({downtrend_score}/5 - ADX={adx:.1f}, Vol={volume_ratio*100:.0f}%)'
        else:
            logger.debug(f"  → Rejected: Mixed signals")
            return False, 'none', f'Mixed signals (Up:{uptrend_score}/5, Down:{downtrend_score}/5)'
    
    def check_long_entry(self, df: pd.DataFrame, indicators: Dict) -> Tuple[bool, int, str]:
        """
        Long Entry Logic
        
        Conditions:
        1. Pullback to EMA21 or VWAP (price within 0.5% of either)
        2. RSI bullish pullback (30-70 range, showing recovery)
        3. Bullish engulfing or hammer candlestick pattern
        4. MACD histogram ticking up (current > previous)
        5. Volume >= 60% of last 2 candles average
        
        Args:
            df: Price DataFrame
            indicators: Dictionary of calculated indicators
        
        Returns:
            Tuple of (signal, score, reason)
        """
        current = df.iloc[-1]
        previous = df.iloc[-2]
        
        current_price = current['close']
        vwap = indicators['vwap'].iloc[-1]
        ema21 = indicators['ema_21'].iloc[-1]
        rsi = indicators['rsi'].iloc[-1]
        rsi_prev = indicators['rsi'].iloc[-2]
        macd_hist = indicators['histogram'].iloc[-1]
        macd_hist_prev = indicators['histogram'].iloc[-2]
        
        conditions = {}
        
        # 1. Pullback to EMA21 or VWAP (PROFITABILITY FIX: 1.0% tolerance for crypto volatility)
        near_ema21 = abs(current_price - ema21) / ema21 < 0.01
        near_vwap = abs(current_price - vwap) / vwap < 0.01
        conditions['pullback'] = near_ema21 or near_vwap
        
        # 2. RSI bullish pullback (PROFITABILITY FIX: Wider range 30-70 for crypto volatility)
        conditions['rsi_pullback'] = 30 < rsi < 70 and rsi > rsi_prev
        
        # 3. Bullish candlestick patterns
        body = current['close'] - current['open']
        prev_body = previous['close'] - previous['open']
        
        # Bullish engulfing
        bullish_engulfing = (
            prev_body < 0 and  # Previous was bearish
            body > 0 and  # Current is bullish
            current['close'] > previous['open'] and
            current['open'] < previous['close']
        )
        
        # Hammer (small body, long lower wick)
        total_range = current['high'] - current['low']
        lower_wick = current['open'] - current['low'] if body > 0 else current['close'] - current['low']
        hammer = (
            body > 0 and
            lower_wick > body * 2 and
            total_range > 0 and
            lower_wick / total_range > 0.6
        )
        
        conditions['candlestick'] = bullish_engulfing or hammer
        
        # 4. MACD histogram ticking up
        conditions['macd_tick_up'] = macd_hist > macd_hist_prev
        
        # 5. Volume confirmation (>= 60% of last 2 candles avg)
        avg_volume_2 = df['volume'].iloc[-3:-1].mean()
        conditions['volume'] = current['volume'] >= avg_volume_2 * 0.6
        
        # Calculate score
        score = sum(conditions.values())
        signal = score >= 3  # PROFITABILITY FIX: 3/5 conditions allows good setups while filtering weak ones
        
        reason = f"Long score: {score}/5 ({', '.join([k for k, v in conditions.items() if v])})" if conditions else "Long score: 0/5"
        
        if score > 0:
            logger.debug(f"  Long entry check: {reason}")
        
        return signal, score, reason
    
    def check_short_entry(self, df: pd.DataFrame, indicators: Dict) -> Tuple[bool, int, str]:
        """
        Short Entry Logic (mirror of long with bearish elements)
        
        Conditions:
        1. Pullback to EMA21 or VWAP (price within 0.5% of either)
        2. RSI bearish pullback (30-70 range, showing decline)
        3. Bearish engulfing or shooting star candlestick pattern
        4. MACD histogram ticking down (current < previous)
        5. Volume >= 60% of last 2 candles average
        
        Args:
            df: Price DataFrame
            indicators: Dictionary of calculated indicators
        
        Returns:
            Tuple of (signal, score, reason)
        """
        current = df.iloc[-1]
        previous = df.iloc[-2]
        
        current_price = current['close']
        vwap = indicators['vwap'].iloc[-1]
        ema21 = indicators['ema_21'].iloc[-1]
        rsi = indicators['rsi'].iloc[-1]
        rsi_prev = indicators['rsi'].iloc[-2]
        macd_hist = indicators['histogram'].iloc[-1]
        macd_hist_prev = indicators['histogram'].iloc[-2]
        
        conditions = {}
        
        # 1. Pullback to EMA21 or VWAP (PROFITABILITY FIX: 1.0% tolerance for crypto volatility)
        near_ema21 = abs(current_price - ema21) / ema21 < 0.01
        near_vwap = abs(current_price - vwap) / vwap < 0.01
        conditions['pullback'] = near_ema21 or near_vwap
        
        # 2. RSI bearish pullback (PROFITABILITY FIX: Wider range 30-70 for crypto volatility)
        conditions['rsi_pullback'] = 30 < rsi < 70 and rsi < rsi_prev
        
        # 3. Bearish candlestick patterns
        body = current['close'] - current['open']
        prev_body = previous['close'] - previous['open']
        
        # Bearish engulfing
        bearish_engulfing = (
            prev_body > 0 and  # Previous was bullish
            body < 0 and  # Current is bearish
            current['close'] < previous['open'] and
            current['open'] > previous['close']
        )
        
        # Shooting star (small body, long upper wick)
        total_range = current['high'] - current['low']
        upper_wick = current['high'] - current['open'] if body < 0 else current['high'] - current['close']
        shooting_star = (
            body < 0 and
            upper_wick > abs(body) * 2 and
            total_range > 0 and
            upper_wick / total_range > 0.6
        )
        
        conditions['candlestick'] = bearish_engulfing or shooting_star
        
        # 4. MACD histogram ticking down
        conditions['macd_tick_down'] = macd_hist < macd_hist_prev
        
        # 5. Volume confirmation
        avg_volume_2 = df['volume'].iloc[-3:-1].mean()
        conditions['volume'] = current['volume'] >= avg_volume_2 * 0.6
        
        # Calculate score
        score = sum(conditions.values())
        signal = score >= 3  # PROFITABILITY FIX: 3/5 conditions allows good setups while filtering weak ones
        
        reason = f"Short score: {score}/5 ({', '.join([k for k, v in conditions.items() if v])})" if conditions else "Short score: 0/5"
        
        if score > 0:
            logger.debug(f"  Short entry check: {reason}")
        
        return signal, score, reason
    
    def check_smart_filters(self, df: pd.DataFrame, current_time: datetime) -> Tuple[bool, str]:
        """
        Smart Filters to avoid bad trades
        
        Filters:
        1. No trades 5 min before/after major news (stub - placeholder for News API)
        2. No trades if volume < 30% avg
        3. No trading during first 6 seconds of a new candle
        
        Args:
            df: Price DataFrame
            current_time: Current datetime
        
        Returns:
            Tuple of (allowed, reason)
        """
        # Filter 1: News filter (stub - placeholder for future News API integration)
        # TODO: Integrate with News API (e.g., Benzinga, Alpha Vantage, etc.)
        # For now, this is a placeholder that always passes
        news_clear = True  # Stub: would check upcoming news events here
        
        # Filter 2: Volume filter (< 20% avg = no trade) - Lowered threshold for better trade opportunities
        avg_volume = df['volume'].rolling(window=20).mean().iloc[-1]
        current_volume = df['volume'].iloc[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        
        if volume_ratio < self.volume_min_threshold:
            return False, f'Volume too low ({volume_ratio*100:.1f}% of avg) - threshold: {self.volume_min_threshold*100:.0f}%'
        
        # Filter 3: Candle timing filter (first 6 seconds)
        # Detect new candle by comparing timestamps
        if len(df) >= 2:
            current_candle_time = df.index[-1] if hasattr(df, 'index') else current_time
            
            # If we have timestamp data, check if we're in first 6 seconds
            if self.last_candle_time != current_candle_time:
                # New candle detected - store time and check elapsed time
                if self.last_candle_time is None:
                    # First run - allow trade
                    self.last_candle_time = current_candle_time
                else:
                    # Calculate time since candle started
                    if hasattr(df.index, 'to_pydatetime'):
                        # Pandas datetime index
                        time_since_candle = (current_time - current_candle_time.to_pydatetime()).total_seconds()
                    else:
                        # Estimate: if this is a fresh candle check, assume we're early
                        time_since_candle = 0
                    
                    self.last_candle_time = current_candle_time
                    
                    # Block trade if we're in first N seconds of new candle
                    if time_since_candle < self.candle_exclusion_seconds:
                        return False, f'First {self.candle_exclusion_seconds}s of new candle - waiting for stability'
        
        return True, 'All smart filters passed'
    
    def check_exit_conditions(self, symbol: str, df: pd.DataFrame, 
                             indicators: Dict, current_price: float) -> Tuple[bool, str]:
        """
        Exit Logic
        
        Conditions:
        1. Opposite signal detected
        2. Trailing stop hit
        3. Trend break (EMA9/21 cross)
        
        Args:
            symbol: Trading symbol
            df: Price DataFrame
            indicators: Dictionary of calculated indicators
            current_price: Current market price
        
        Returns:
            Tuple of (should_exit, reason)
        """
        position = self.execution_engine.get_position(symbol)
        if not position:
            return False, 'No position'
        
        side = position['side']
        ema9 = indicators['ema_9'].iloc[-1]
        ema21 = indicators['ema_21'].iloc[-1]
        
        # 1. Check for opposite signal
        if side == 'long':
            short_signal, _, reason = self.check_short_entry(df, indicators)
            if short_signal:
                return True, f'Opposite signal: {reason}'
        else:  # short
            long_signal, _, reason = self.check_long_entry(df, indicators)
            if long_signal:
                return True, f'Opposite signal: {reason}'
        
        # 2. Check trailing stop
        if self.execution_engine.check_stop_loss_hit(symbol, current_price):
            return True, f'Trailing stop hit @ {position["stop_loss"]:.2f}'
        
        # 3. Check trend break (EMA9/21 cross)
        ema9_prev = indicators['ema_9'].iloc[-2]
        ema21_prev = indicators['ema_21'].iloc[-2]
        
        if side == 'long':
            # Bearish cross: EMA9 crosses below EMA21
            if ema9 < ema21 and ema9_prev >= ema21_prev:
                return True, 'Trend break: EMA9 crossed below EMA21'
        else:  # short
            # Bullish cross: EMA9 crosses above EMA21
            if ema9 > ema21 and ema9_prev <= ema21_prev:
                return True, 'Trend break: EMA9 crossed above EMA21'
        
        return False, 'No exit conditions met'
    
    def calculate_indicators(self, df: pd.DataFrame) -> Dict:
        """
        Calculate all required indicators
        
        Args:
            df: Price DataFrame with columns: open, high, low, close, volume
        
        Returns:
            Dictionary of indicators
        """
        # HARD GUARD: Force numeric types before any math to avoid str/int errors
        try:
            required_cols = ['open', 'high', 'low', 'close', 'volume']
            if not all(col in df.columns for col in required_cols):
                logger.warning("Missing OHLCV columns; cannot calculate indicators")
                return {}
            df[required_cols] = df[required_cols].astype(float)
            # Debug: confirm types are floats
            logger.info(
                f"DEBUG candle types → close={type(df['close'].iloc[-1])}, "
                f"open={type(df['open'].iloc[-1])}, volume={type(df['volume'].iloc[-1])}"
            )
        except Exception as e:
            logger.warning(f"Failed to normalize candle types before indicators: {e}")
            return {}
        indicators = {
            'vwap': calculate_vwap(df),
            'ema_9': calculate_ema(df, 9),
            'ema_21': calculate_ema(df, 21),
            'ema_50': calculate_ema(df, 50),
            'rsi': calculate_rsi(df, 14),
        }
        
        macd_line, signal_line, histogram = calculate_macd(df)
        indicators['macd_line'] = macd_line
        indicators['signal_line'] = signal_line
        indicators['histogram'] = histogram
        
        indicators['atr'] = calculate_atr(df, 14)
        adx, plus_di, minus_di = calculate_adx(df, 14)
        indicators['adx'] = adx
        indicators['plus_di'] = plus_di
        indicators['minus_di'] = minus_di
        
        return indicators
    
    def analyze_market(self, df: pd.DataFrame, symbol: str, 
                       account_balance: float) -> Dict:
        """
        Main analysis function - combines all components
        
        Args:
            df: Price DataFrame
            symbol: Trading symbol
            account_balance: Current account balance
        
        Returns:
            Dictionary with analysis results and recommended action
        """
        try:
            # Require minimum data
            if len(df) < 100:
                logger.debug(f"   {symbol}: Insufficient data ({len(df)} candles)")
                return {
                    'action': 'hold',
                    'reason': f'Insufficient data ({len(df)} candles, need 100+)'
                }
            
            # Calculate indicators
            indicators = self.calculate_indicators(df)
            
            # Check smart filters
            current_time = datetime.now()
            filters_ok, filter_reason = self.check_smart_filters(df, current_time)
            if not filters_ok:
                logger.debug(f"   {symbol}: Smart filter blocked - {filter_reason}")
                return {
                    'action': 'hold',
                    'reason': filter_reason
                }
            
            # Check market filter
            allow_trade, trend, market_reason = self.check_market_filter(df, indicators)
            if not allow_trade:
                logger.debug(f"   {symbol}: Market filter blocked - {market_reason}")
                return {
                    'action': 'hold',
                    'reason': market_reason
                }
            
            # Check if we have an existing position
            position = self.execution_engine.get_position(symbol)
            current_price = df['close'].iloc[-1]
            
            if position:
                # Manage existing position
                should_exit, exit_reason = self.check_exit_conditions(
                    symbol, df, indicators, current_price
                )
                
                if should_exit:
                    return {
                        'action': 'exit',
                        'reason': exit_reason,
                        'position': position,
                        'current_price': current_price
                    }
                
                # Check take profit levels
                tp_level = self.execution_engine.check_take_profit_hit(symbol, current_price)
                if tp_level:
                    return {
                        'action': f'take_profit_{tp_level}',
                        'reason': f'{tp_level.upper()} reached',
                        'position': position
                    }
                
                # Update trailing stop
                atr = indicators['atr'].iloc[-1]
                if position.get('tp1_hit', False):
                    new_stop = self.risk_manager.calculate_trailing_stop(
                        current_price, position['entry_price'],
                        position['side'], atr, breakeven_mode=True
                    )
                    self.execution_engine.update_stop_loss(symbol, new_stop)
                
                return {
                    'action': 'hold',
                    'reason': 'Position being managed',
                    'position': position
                }
            
            # No position - check for entry
            adx = indicators['adx'].iloc[-1]
            
            if trend == 'uptrend':
                long_signal, score, reason = self.check_long_entry(df, indicators)
                if long_signal:
                    # Calculate position size
                    position_size = self.risk_manager.calculate_position_size(
                        account_balance, adx, score
                    )
                    
                    if position_size == 0:
                        return {
                            'action': 'hold',
                            'reason': f'Position size = 0 (ADX={adx:.1f} < {self.min_adx})'
                        }
                    
                    # Calculate stop loss and take profit
                    swing_low = self.risk_manager.find_swing_low(df, lookback=10)
                    atr = indicators['atr'].iloc[-1]
                    stop_loss = self.risk_manager.calculate_stop_loss(
                        current_price, 'long', swing_low, atr
                    )
                    tp_levels = self.risk_manager.calculate_take_profit_levels(
                        current_price, stop_loss, 'long'
                    )
                    
                    return {
                        'action': 'enter_long',
                        'reason': reason,
                        'entry_price': current_price,
                        'position_size': position_size,
                        'stop_loss': stop_loss,
                        'take_profit': tp_levels,
                        'score': score,
                        'adx': adx
                    }
            
            elif trend == 'downtrend':
                short_signal, score, reason = self.check_short_entry(df, indicators)
                if short_signal:
                    # Calculate position size
                    position_size = self.risk_manager.calculate_position_size(
                        account_balance, adx, score
                    )
                    
                    if position_size == 0:
                        return {
                            'action': 'hold',
                            'reason': f'Position size = 0 (ADX={adx:.1f} < {self.min_adx})'
                        }
                    
                    # Calculate stop loss and take profit
                    swing_high = self.risk_manager.find_swing_high(df, lookback=10)
                    atr = indicators['atr'].iloc[-1]
                    stop_loss = self.risk_manager.calculate_stop_loss(
                        current_price, 'short', swing_high, atr
                    )
                    tp_levels = self.risk_manager.calculate_take_profit_levels(
                        current_price, stop_loss, 'short'
                    )
                    
                    return {
                        'action': 'enter_short',
                        'reason': reason,
                        'entry_price': current_price,
                        'position_size': position_size,
                        'stop_loss': stop_loss,
                        'take_profit': tp_levels,
                        'score': score,
                        'adx': adx
                    }
            
            return {
                'action': 'hold',
                'reason': f'No entry signal ({trend})'
            }
            
        except Exception as e:
            logger.error(f"Analysis error: {e}")
            return {
                'action': 'hold',
                'reason': f'Error: {str(e)}'
            }
    
    def execute_action(self, action_data: Dict, symbol: str) -> bool:
        """
        Execute the recommended action
        
        Args:
            action_data: Dictionary from analyze_market()
            symbol: Trading symbol
        
        Returns:
            True if action executed successfully
        """
        action = action_data.get('action')
        
        try:
            # EMERGENCY: Check if entries are blocked via STOP_ALL_ENTRIES.conf
            stop_entries_file = os.path.join(os.path.dirname(__file__), '..', 'STOP_ALL_ENTRIES.conf')
            entries_blocked = os.path.exists(stop_entries_file)
            
            if entries_blocked and ('enter_long' in action or 'enter_short' in action):
                logger.error("🛑 BUY BLOCKED: STOP_ALL_ENTRIES.conf active")
                logger.error(f"   Position cap may be exceeded. Fix required before new entries allowed.")
                return False
            
            if action == 'enter_long':
                position = self.execution_engine.execute_entry(
                    symbol=symbol,
                    side='long',
                    position_size=action_data['position_size'],
                    entry_price=action_data['entry_price'],
                    stop_loss=action_data['stop_loss'],
                    take_profit_levels=action_data['take_profit']
                )
                if position:
                    logger.info(f"Long entry executed: {symbol} @ {action_data['entry_price']:.2f}")
                    return True
            
            elif action == 'enter_short':
                position = self.execution_engine.execute_entry(
                    symbol=symbol,
                    side='short',
                    position_size=action_data['position_size'],
                    entry_price=action_data['entry_price'],
                    stop_loss=action_data['stop_loss'],
                    take_profit_levels=action_data['take_profit']
                )
                if position:
                    logger.info(f"Short entry executed: {symbol} @ {action_data['entry_price']:.2f}")
                    return True
            
            elif action == 'exit':
                success = self.execution_engine.execute_exit(
                    symbol=symbol,
                    exit_price=action_data.get('current_price', action_data['position']['entry_price']),
                    size_pct=1.0,
                    reason=action_data['reason']
                )
                return success
            
            elif action.startswith('take_profit_'):
                # Partial exits based on TP level
                if action == 'take_profit_tp1':
                    # Exit 50%, move stop to breakeven
                    success = self.execution_engine.execute_exit(
                        symbol=symbol,
                        exit_price=action_data['position']['tp1'],
                        size_pct=0.5,
                        reason='TP1 hit'
                    )
                    if success:
                        # Move stop to breakeven
                        self.execution_engine.update_stop_loss(
                            symbol, action_data['position']['entry_price']
                        )
                    return success
                
                elif action == 'take_profit_tp2':
                    # Exit another 25% (75% total out)
                    return self.execution_engine.execute_exit(
                        symbol=symbol,
                        exit_price=action_data['position']['tp2'],
                        size_pct=0.5,  # 50% of remaining
                        reason='TP2 hit'
                    )
                
                elif action == 'take_profit_tp3':
                    # Exit remaining position
                    return self.execution_engine.execute_exit(
                        symbol=symbol,
                        exit_price=action_data['position']['tp3'],
                        size_pct=1.0,
                        reason='TP3 hit'
                    )
            
            return False
            
        except Exception as e:
            logger.error(f"Execution error: {e}")
            return False
    
    # ============================================================
    # AI MOMENTUM SCORING (SKELETON - PLACEHOLDER FOR FUTURE)
    # ============================================================
    
    def calculate_ai_momentum_score(self, df: pd.DataFrame, 
                                    indicators: Dict) -> float:
        """
        AI-powered momentum scoring system (skeleton)
        
        Future implementation ideas:
        - Machine learning model trained on historical price patterns
        - Sentiment analysis from news/social media
        - Market regime detection (trending vs ranging)
        - Volume profile analysis
        - Order flow analysis
        
        Args:
            df: Price DataFrame
            indicators: Dictionary of calculated indicators
        
        Returns:
            Momentum score (0.0 to 1.0)
        """
        # TODO: Implement AI/ML model here
        # Placeholder: simple weighted combination of indicators
        
        if self.ai_momentum_enabled:
            # Example: weighted scoring
            rsi = indicators['rsi'].iloc[-1]
            adx = indicators['adx'].iloc[-1]
            macd_hist = indicators['histogram'].iloc[-1]
            
            # Normalize to 0-1 range
            rsi_score = abs(rsi - 50) / 50  # Distance from neutral
            adx_score = min(adx / 50, 1.0)  # Trend strength
            macd_score = 0.5  # Placeholder
            
            # Weighted average
            momentum_score = (rsi_score * 0.3 + adx_score * 0.5 + macd_score * 0.2)
            
            return momentum_score
        
        return 0.5  # Neutral score when disabled
