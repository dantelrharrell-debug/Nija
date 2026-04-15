# nija_apex_strategy_v8.py
"""
NIJA APEX STRATEGY v8.0 - AI-Enhanced Profitability Upgrade
Unified algorithmic trading strategy with ML-driven signals and adaptive risk management

Major Enhancements (v8.0):
1. AI/ML Integration - Pluggable ML models with live data logging
2. Adaptive Risk Management - Dynamic sizing based on AI confidence and streaks
3. Smart Filters - Time-of-day and volatility regime filtering
4. Trading Journal - Comprehensive trade logging for analysis
5. Enhanced Profitability - Targeting $50-$250/day through optimized execution

Author: NIJA Trading Systems
Version: 8.0
Date: December 2024
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List
import logging

from indicators import (
    calculate_vwap, calculate_ema, calculate_rsi, calculate_macd,
    calculate_atr, calculate_adx, scalar
)
from risk_manager import AdaptiveRiskManager
from execution_engine import ExecutionEngine
from ai_ml_base import EnhancedAIEngine, RuleBasedModel
from trade_journal import TradeJournal
from smart_filters import SmartFilterAggregator

logger = logging.getLogger("nija")


class NIJAApexStrategyV8:
    """
    NIJA Apex Strategy v8.0 - AI-Enhanced Trading System

    Core Features:
    1. AI Signal Generation - ML-powered momentum and regime detection
    2. Adaptive Position Sizing - Based on confidence, streaks, volatility
    3. Smart Entry/Exit Filters - Time-of-day and volatility regime filtering
    4. Comprehensive Logging - Trade journal for performance analysis
    5. Maximum Profitability - Optimized for $50-$250/day target

    Configuration:
    - min_position_pct: Minimum position size (default 2%)
    - max_position_pct: Maximum position size (default 10%)
    - max_total_exposure: Maximum portfolio exposure (default 30%)
    - enable_ai: Use AI for signal generation (default True)
    - enable_smart_filters: Use time/volatility filters (default True)
    - enable_journal: Log trades to journal (default True)
    """

    def __init__(self, broker_client=None, config: Optional[Dict] = None):
        """
        Initialize NIJA Apex Strategy v8.0

        Args:
            broker_client: Broker API client (Coinbase, Alpaca, Binance, etc.)
            config: Strategy configuration dictionary
        """
        self.broker_client = broker_client
        self.config = config or {}

        # Initialize core components
        self.risk_manager = AdaptiveRiskManager(
            min_position_pct=self.config.get('min_position_pct', 0.02),
            max_position_pct=self.config.get('max_position_pct', 0.20),  # UPDATED Jan 21, 2026: OPTION 2 - Increased to 20% (was 10%)
            max_total_exposure=self.config.get('max_total_exposure', 0.30)
        )
        self.execution_engine = ExecutionEngine(broker_client)

        # Initialize AI engine
        enable_ai = self.config.get('enable_ai', True)
        if enable_ai:
            # TODO: Replace RuleBasedModel with trained ML model when ready
            ml_model = RuleBasedModel()
            self.ai_engine = EnhancedAIEngine(
                model=ml_model,
                enable_logging=self.config.get('enable_ml_logging', True)
            )
        else:
            self.ai_engine = None

        # Initialize smart filters
        enable_filters = self.config.get('enable_smart_filters', True)
        if enable_filters:
            self.smart_filters = SmartFilterAggregator(
                enable_time_filter=self.config.get('enable_time_filter', True),
                enable_volatility_filter=self.config.get('enable_volatility_filter', True),
                enable_news_filter=self.config.get('enable_news_filter', False)
            )
        else:
            self.smart_filters = None

        # Initialize trade journal
        enable_journal = self.config.get('enable_journal', True)
        if enable_journal:
            journal_dir = self.config.get('journal_dir', './data/trade_journal')
            self.trade_journal = TradeJournal(journal_dir=journal_dir)
        else:
            self.trade_journal = None

        # Strategy parameters
        self.min_adx = self.config.get('min_adx', 20)
        self.volume_threshold = self.config.get('volume_threshold', 0.5)
        self.min_time_activity = self.config.get('min_time_activity', 0.5)

        # Track active positions for exposure management
        self.active_positions = {}

        logger.info(f"NIJA Apex Strategy v8.0 initialized - AI: {enable_ai}, "
                   f"Smart Filters: {enable_filters}, Journal: {enable_journal}")

    def analyze_market(self, df: pd.DataFrame, symbol: str) -> Dict:
        """
        Comprehensive market analysis using all indicators and AI.

        Args:
            df: OHLCV DataFrame
            symbol: Trading symbol

        Returns:
            dict: Complete market analysis with signals and scores
        """
        # Calculate all technical indicators
        indicators = self._calculate_indicators(df)

        # Get AI signal if enabled
        ai_signal = None
        if self.ai_engine:
            ai_signal = self.ai_engine.predict_signal(df, indicators, symbol)

        # Apply smart filters
        filter_results = None
        if self.smart_filters:
            atr_pct = indicators.get('atr_pct', 0.01)
            historical_atr = df['close'].pct_change().rolling(20).std() if len(df) >= 20 else None
            filter_results = self.smart_filters.evaluate_trade_filters(
                atr_pct=atr_pct,
                historical_atr=historical_atr,
                min_time_activity=self.min_time_activity
            )

        # Basic market filter (trend direction)
        market_allowed, trend_direction, trend_reason = self._check_market_filter(df, indicators)

        # Compile analysis
        analysis = {
            'indicators': indicators,
            'ai_signal': ai_signal,
            'filter_results': filter_results,
            'market_allowed': market_allowed,
            'trend_direction': trend_direction,
            'trend_reason': trend_reason,
            'timestamp': datetime.now()
        }

        return analysis

    def _calculate_indicators(self, df: pd.DataFrame) -> Dict:
        """
        Calculate all technical indicators.

        Args:
            df: OHLCV DataFrame

        Returns:
            dict: All calculated indicators
        """
        indicators = {}

        try:
            # Trend indicators
            indicators['vwap'] = calculate_vwap(df)
            indicators['ema_9'] = calculate_ema(df, period=9)
            indicators['ema_21'] = calculate_ema(df, period=21)
            indicators['ema_50'] = calculate_ema(df, period=50)

            # Momentum indicators
            indicators['rsi'] = calculate_rsi(df, period=14)
            # FIX: calculate_macd returns tuple (macd_line, signal_line, histogram), not dict
            macd_line, signal_line, histogram = calculate_macd(df)
            indicators['macd'] = macd_line
            indicators['signal'] = signal_line
            indicators['histogram'] = histogram

            # Volatility indicators
            indicators['atr'] = calculate_atr(df, period=14)
            # FIX: calculate_adx returns tuple (adx, plus_di, minus_di), unpack properly
            adx_series, plus_di, minus_di = calculate_adx(df, period=14)
            indicators['adx'] = adx_series
            indicators['plus_di'] = plus_di
            indicators['minus_di'] = minus_di

            # Derived metrics
            current_price = df['close'].iloc[-1]
            atr_value = indicators['atr'].iloc[-1] if hasattr(indicators['atr'], 'iloc') else indicators['atr']
            indicators['atr_pct'] = atr_value / current_price if current_price > 0 else 0

            # Volume ratio
            if len(df) >= 20:
                avg_volume = df['volume'].iloc[-20:].mean()
                current_volume = df['volume'].iloc[-1]
                indicators['volume_ratio'] = current_volume / avg_volume if avg_volume > 0 else 0
            else:
                indicators['volume_ratio'] = 1.0

        except Exception as e:
            logger.error(f"Error calculating indicators: {e}")

        return indicators

    def _check_market_filter(self, df: pd.DataFrame, indicators: Dict) -> Tuple[bool, str, str]:
        """
        Check if market conditions allow trading (trend filter).

        Args:
            df: OHLCV DataFrame
            indicators: Calculated indicators

        Returns:
            Tuple of (allowed, direction, reason)
        """
        try:
            current_price = df['close'].iloc[-1]
            vwap = indicators['vwap'].iloc[-1]
            ema9 = indicators['ema_9'].iloc[-1]
            ema21 = indicators['ema_21'].iloc[-1]
            ema50 = indicators['ema_50'].iloc[-1]
            macd_hist = indicators['histogram'].iloc[-1]
            adx = scalar(indicators['adx'].iloc[-1] if hasattr(indicators['adx'], 'iloc') else indicators['adx'])

            # ADX filter
            if adx < self.min_adx:
                return False, 'none', f'ADX too low ({adx:.1f})'

            # Volume filter
            volume_ratio = indicators.get('volume_ratio', 0)
            if volume_ratio < self.volume_threshold:
                return False, 'none', f'Volume too low ({volume_ratio*100:.0f}%)'

            # Uptrend conditions
            uptrend = (
                current_price > vwap and
                ema9 > ema21 > ema50 and
                macd_hist > 0
            )

            # HARD GUARD: Ensure numeric OHLCV before any indicator math
            try:
                required_cols = ['open', 'high', 'low', 'close', 'volume']
                if not all(col in df.columns for col in required_cols):
                    logger.error("Missing OHLCV columns; cannot calculate indicators (V8)")
                    return {}
                df[required_cols] = df[required_cols].astype(float)
                logger.info(
                    f"DEBUG[V8] candle types → close={type(df['close'].iloc[-1])}, "
                    f"open={type(df['open'].iloc[-1])}, volume={type(df['volume'].iloc[-1])}"
                )
            except Exception as e:
                logger.error(f"Failed to normalize candle types (V8): {e}")
                return {}

            downtrend = (
                current_price < vwap and
                ema9 < ema21 < ema50 and
                macd_hist < 0
            )

            if uptrend:
                return True, 'uptrend', f'Uptrend confirmed (ADX={adx:.1f})'
            elif downtrend:
                return True, 'downtrend', f'Downtrend confirmed (ADX={adx:.1f})'
            else:
                return False, 'none', 'Mixed trend signals'

        except Exception as e:
            logger.error(f"Error in market filter: {e}")
            return False, 'none', f'Error: {str(e)}'

    def generate_entry_signal(self, df: pd.DataFrame, symbol: str) -> Optional[Dict]:
        """
        Generate entry signal using AI and all filters.

        Args:
            df: OHLCV DataFrame
            symbol: Trading symbol

        Returns:
            dict: Entry signal details or None if no signal
        """
        # Run comprehensive market analysis
        analysis = self.analyze_market(df, symbol)

        # Check if market conditions allow trading
        if not analysis['market_allowed']:
            logger.debug(f"{symbol}: Market filter blocked - {analysis['trend_reason']}")
            return None

        # Check smart filters
        if analysis['filter_results'] and not analysis['filter_results']['should_trade']:
            reasons = ', '.join(analysis['filter_results']['reasons'])
            logger.debug(f"{symbol}: Smart filters blocked - {reasons}")
            return None

        # Get AI signal
        ai_signal = analysis['ai_signal']
        if not ai_signal:
            logger.debug(f"{symbol}: No AI signal generated")
            return None

        # Require minimum AI confidence
        min_confidence = self.config.get('min_ai_confidence', 0.6)
        if ai_signal['confidence'] < min_confidence:
            logger.debug(f"{symbol}: AI confidence too low ({ai_signal['confidence']:.2f})")
            return None

        # Determine entry side based on AI signal and trend
        trend_direction = analysis['trend_direction']
        ai_direction = ai_signal['signal']

        # Align AI signal with trend
        if trend_direction == 'uptrend' and ai_direction == 'long':
            side = 'long'
        elif trend_direction == 'downtrend' and ai_direction == 'short':
            side = 'short'
        else:
            logger.debug(f"{symbol}: AI signal ({ai_direction}) doesn't align with trend ({trend_direction})")
            return None

        # Additional entry conditions check
        entry_conditions = self._check_entry_conditions(df, analysis['indicators'], side)
        if not entry_conditions['valid']:
            logger.debug(f"{symbol}: Entry conditions not met - {entry_conditions['reason']}")
            return None

        # Create entry signal
        entry_signal = {
            'symbol': symbol,
            'side': side,
            'ai_signal': ai_signal,
            'confidence': ai_signal['confidence'],
            'score': ai_signal['score'],
            'indicators': analysis['indicators'],
            'filter_results': analysis['filter_results'],
            'entry_conditions': entry_conditions,
            'timestamp': datetime.now()
        }

        logger.info(f"Entry signal generated: {symbol} {side} - "
                   f"AI Score: {ai_signal['score']:.1f}, "
                   f"Confidence: {ai_signal['confidence']:.2f}")

        return entry_signal

    def _check_entry_conditions(self, df: pd.DataFrame, indicators: Dict,
                                side: str) -> Dict:
        """
        Check specific entry conditions for the trade.

        Args:
            df: OHLCV DataFrame
            indicators: Calculated indicators
            side: 'long' or 'short'

        Returns:
            dict: {'valid': bool, 'reason': str, 'score': int}
        """
        conditions = {}

        try:
            current = df.iloc[-1]
            previous = df.iloc[-2]
            current_price = current['close']

            ema21 = indicators['ema_21'].iloc[-1]
            vwap = indicators['vwap'].iloc[-1]
            rsi = scalar(indicators['rsi'].iloc[-1] if hasattr(indicators['rsi'], 'iloc') else indicators['rsi'])
            macd_hist = indicators['histogram'].iloc[-1]
            macd_hist_prev = indicators['histogram'].iloc[-2]

            if side == 'long':
                # Long entry conditions
                # 1. Near support (EMA21 or VWAP)
                near_support = (
                    abs(current_price - ema21) / ema21 < 0.01 or
                    abs(current_price - vwap) / vwap < 0.01
                )
                conditions['near_support'] = near_support

                # 2. RSI in buy zone
                conditions['rsi_ok'] = 30 < rsi < 70

                # 3. MACD improving
                conditions['macd_improving'] = macd_hist > macd_hist_prev

                # 4. Bullish candle
                conditions['bullish_candle'] = current['close'] > current['open']

            else:  # short
                # Short entry conditions
                # 1. Near resistance (EMA21 or VWAP)
                near_resistance = (
                    abs(current_price - ema21) / ema21 < 0.01 or
                    abs(current_price - vwap) / vwap < 0.01
                )
                conditions['near_resistance'] = near_resistance

                # 2. RSI in sell zone
                conditions['rsi_ok'] = 30 < rsi < 70

                # 3. MACD deteriorating
                conditions['macd_deteriorating'] = macd_hist < macd_hist_prev

                # 4. Bearish candle
                conditions['bearish_candle'] = current['close'] < current['open']

            # Score and validate
            score = sum(conditions.values())
            valid = score >= 2  # At least 2/4 conditions

            passed = [k for k, v in conditions.items() if v]
            reason = f"Entry score: {score}/4 ({', '.join(passed)})"

            return {'valid': valid, 'reason': reason, 'score': score, 'conditions': conditions}

        except Exception as e:
            logger.error(f"Error checking entry conditions: {e}")
            return {'valid': False, 'reason': f'Error: {str(e)}', 'score': 0}

    def execute_entry(self, entry_signal: Dict, account_balance: float) -> Optional[Dict]:
        """
        Execute entry trade with adaptive position sizing.

        Args:
            entry_signal: Entry signal from generate_entry_signal()
            account_balance: Current account balance

        Returns:
            dict: Trade record or None if failed
        """
        try:
            symbol = entry_signal['symbol']
            side = entry_signal['side']
            indicators = entry_signal['indicators']

            # Get dataframe from the signal (need full df for swing levels)
            # In real usage, this should be passed in or stored
            # For now, we'll create a minimal df from indicators
            df = pd.DataFrame({
                'close': [indicators.get('close_price', 0)],
                'high': [indicators.get('close_price', 0) * 1.01],
                'low': [indicators.get('close_price', 0) * 0.99]
            })

            # Get current price and ATR
            current_price = df['close'].iloc[-1]
            atr = scalar(indicators['atr'].iloc[-1] if hasattr(indicators['atr'], 'iloc') else indicators['atr'])
            atr_pct = indicators['atr_pct']
            adx = scalar(indicators['adx'].iloc[-1] if hasattr(indicators['adx'], 'iloc') else indicators['adx'])

            # Calculate adaptive position size
            ai_confidence = entry_signal['confidence']
            signal_strength = entry_signal['entry_conditions']['score']

            position_size, size_breakdown = self.risk_manager.calculate_position_size(
                account_balance=account_balance,
                adx=adx,
                signal_strength=signal_strength,
                ai_confidence=ai_confidence,
                volatility_pct=atr_pct
            )

            # Apply smart filter multiplier if available
            if entry_signal.get('filter_results'):
                filter_multiplier = entry_signal['filter_results']['adjustments']['position_size_multiplier']
                position_size *= filter_multiplier
                logger.info(f"Applied filter multiplier: {filter_multiplier:.2f}x")

            if position_size < 10:  # Minimum $10 position
                logger.warning(f"Position size too small: ${position_size:.2f}")
                return None

            # Calculate stop loss and take profit
            # Need full DataFrame for swing level calculation
            if side == 'long':
                swing_low = self.risk_manager.find_swing_low(df)
                stop_loss = self.risk_manager.calculate_stop_loss(current_price, 'long', swing_low, atr)
            else:
                swing_high = self.risk_manager.find_swing_high(df)
                stop_loss = self.risk_manager.calculate_stop_loss(current_price, 'short', swing_high, atr)

            take_profit_levels = self.risk_manager.calculate_take_profit_levels(
                current_price, stop_loss, side
            )

            # Log entry to journal
            trade_id = f"{symbol}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

            if self.trade_journal:
                market_conditions = {
                    'regime': entry_signal['filter_results'].get('volatility_filter', {}).get('regime', 'unknown') if entry_signal.get('filter_results') else 'unknown',
                    'volatility': atr_pct,
                    'session': entry_signal['filter_results'].get('time_filter', {}).get('session', 'unknown') if entry_signal.get('filter_results') else 'unknown'
                }

                self.trade_journal.log_entry(
                    trade_id=trade_id,
                    symbol=symbol,
                    side=side,
                    entry_price=current_price,
                    position_size=position_size,
                    stop_loss=stop_loss,
                    take_profit_levels=take_profit_levels,
                    features=entry_signal['ai_signal']['features'],
                    ai_signal=entry_signal['ai_signal'],
                    market_conditions=market_conditions,
                    notes=f"Size breakdown: {size_breakdown}"
                )

            # Execute via execution engine
            position = self.execution_engine.execute_entry(
                symbol=symbol,
                side=side,
                position_size=position_size,
                entry_price=current_price,
                stop_loss=stop_loss,
                take_profit_levels=take_profit_levels
            )

            if position:
                # Update exposure tracking
                position_pct = size_breakdown.get('final_pct', position_size / account_balance)
                self.risk_manager.update_exposure(position_pct, action='add')
                self.active_positions[trade_id] = {
                    'position': position,
                    'signal_id': entry_signal['ai_signal'].get('signal_id', ''),
                    'entry_time': datetime.now(),
                    'position_pct': position_pct
                }

                logger.info(f"Entry executed: {trade_id} - {symbol} {side} @ {current_price:.2f}, "
                           f"Size: ${position_size:.2f}, SL: {stop_loss:.2f}, "
                           f"TP: {take_profit_levels['tp1']:.2f}/{take_profit_levels['tp2']:.2f}/{take_profit_levels['tp3']:.2f}")

            return position

        except Exception as e:
            logger.error(f"Error executing entry: {e}")
            return None

    def check_exit_signal(self, trade_id: str, df: pd.DataFrame) -> Optional[Dict]:
        """
        Check if position should be exited.

        Args:
            trade_id: Trade identifier
            df: Current OHLCV data

        Returns:
            dict: Exit details or None if no exit
        """
        if trade_id not in self.active_positions:
            return None

        trade = self.active_positions[trade_id]
        position = trade['position']
        current_price = df['close'].iloc[-1]

        # Check stop loss
        if position['side'] == 'long':
            if current_price <= position['stop_loss']:
                return {
                    'exit_price': current_price,
                    'exit_reason': 'Stop loss hit',
                    'partial': False
                }
        else:  # short
            if current_price >= position['stop_loss']:
                return {
                    'exit_price': current_price,
                    'exit_reason': 'Stop loss hit',
                    'partial': False
                }

        # Check take profit levels
        if position['side'] == 'long':
            if not position.get('tp1_hit') and current_price >= position['tp1']:
                return {
                    'exit_price': current_price,
                    'exit_reason': 'TP1 hit',
                    'partial': True,
                    'exit_pct': 0.5
                }
            elif not position.get('tp2_hit') and current_price >= position['tp2']:
                return {
                    'exit_price': current_price,
                    'exit_reason': 'TP2 hit',
                    'partial': True,
                    'exit_pct': 0.25
                }
            elif current_price >= position['tp3']:
                return {
                    'exit_price': current_price,
                    'exit_reason': 'TP3 hit',
                    'partial': False
                }

        # TODO: Add trailing stop logic
        # TODO: Add AI-based exit signals

        return None

    def execute_exit(self, trade_id: str, exit_details: Dict) -> bool:
        """
        Execute exit trade and log to journal.

        Args:
            trade_id: Trade identifier
            exit_details: Exit details from check_exit_signal()

        Returns:
            bool: Success status
        """
        if trade_id not in self.active_positions:
            return False

        try:
            trade = self.active_positions[trade_id]
            position = trade['position']

            # Execute exit via execution engine
            success = self.execution_engine.execute_exit(
                symbol=position['symbol'],
                exit_price=exit_details['exit_price'],
                size_pct=exit_details.get('exit_pct', 1.0),
                reason=exit_details['exit_reason']
            )

            if success and self.trade_journal:
                # Log to journal
                exit_record = self.trade_journal.log_exit(
                    trade_id=trade_id,
                    exit_price=exit_details['exit_price'],
                    exit_reason=exit_details['exit_reason'],
                    partial_exit=exit_details.get('partial', False),
                    exit_pct=exit_details.get('exit_pct', 1.0)
                )

                if exit_record and not exit_details.get('partial'):
                    # Full exit - record trade outcome and update risk manager
                    outcome = exit_record['outcome']
                    pnl = exit_record['pnl_dollars']
                    hold_time = exit_record['hold_minutes']

                    self.risk_manager.record_trade(outcome, pnl, hold_time)

                    # Log to AI engine if available
                    if self.ai_engine and trade.get('signal_id'):
                        self.ai_engine.log_trade_outcome(
                            signal_id=trade['signal_id'],
                            outcome=outcome,
                            pnl=pnl,
                            duration_minutes=hold_time,
                            exit_reason=exit_details['exit_reason']
                        )

                    # Update exposure
                    self.risk_manager.update_exposure(trade['position_pct'], action='remove')

                    # Remove from active positions
                    del self.active_positions[trade_id]

                    logger.info(f"Exit executed: {trade_id} - {exit_details['exit_reason']}, "
                               f"P&L: ${pnl:.2f}, Outcome: {outcome}")

            return success

        except Exception as e:
            logger.error(f"Error executing exit: {e}")
            return False

    def get_performance_summary(self, days: int = 7) -> Dict:
        """
        Get performance summary from trade journal.

        Args:
            days: Number of days to analyze

        Returns:
            dict: Performance metrics
        """
        if not self.trade_journal:
            return {'error': 'Trade journal not enabled'}

        return self.trade_journal.calculate_performance_metrics(days)

    def print_performance_summary(self, days: int = 7) -> None:
        """
        Print human-readable performance summary.

        Args:
            days: Number of days to summarize
        """
        if self.trade_journal:
            self.trade_journal.print_summary(days)
        else:
            print("Trade journal not enabled")
