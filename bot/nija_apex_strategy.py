"""
NIJA Apex Strategy v7.1 - Core Strategy Class

Production-ready trading system with:
1. Strict market-state filtering (VWAP, EMA alignment, MACD, ADX, volume)
2. Multi-confirmation entry/exit logic
3. Multi-stage dynamic risk management
4. Aggressive capital protection
5. Smart filters (news, low-volume, candle timing)
6. Extensible architecture for AI and multi-broker support
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import logging

# Import NIJA Apex modules
from indicators_apex import (
    calculate_atr, calculate_adx, calculate_macd_histogram_analysis,
    detect_momentum_candle, check_ema_alignment, check_volume_confirmation,
    detect_vwap_pullback, detect_ema21_pullback
)
from market_filters import (
    detect_choppy_market, check_minimum_volume, check_candle_timing,
    NewsEventFilter, apply_all_filters
)
from risk_management import RiskManager
from ai_momentum import MomentumScorer, AIRegimedDetector, AdaptiveSignalWeighter

# Import existing NIJA modules
from indicators import calculate_vwap, calculate_rsi, calculate_ema

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


class NijaApexStrategyV71:
    """
    NIJA Apex Strategy v7.1 - Unified Production Trading System

    Features:
    - Strict market-state filtering
    - High-probability multi-confirmation entries
    - Dynamic ADX-weighted position sizing
    - ATR-based stop-loss with tiered take-profits
    - Trailing stop activation post-TP1
    - Max drawdown and risk controls
    - News and low-volume filtering
    - Extensible for AI momentum scoring
    """

    def __init__(self, account_balance: float, config: Optional[Dict] = None):
        """
        Initialize NIJA Apex Strategy v7.1.

        Args:
            account_balance: Starting account balance in USD
            config: Optional configuration dict (uses defaults if None)
        """
        self.account_balance = account_balance

        # Load configuration
        self.config = self._load_default_config()
        if config:
            self.config.update(config)

        # Initialize components
        self.risk_manager = RiskManager(
            account_balance=account_balance,
            max_risk_per_trade=self.config['max_risk_per_trade'],
            max_daily_loss=self.config['max_daily_loss'],
            max_total_exposure=self.config['max_total_exposure'],
            max_drawdown=self.config['max_drawdown']
        )

        self.news_filter = NewsEventFilter(
            cooldown_minutes=self.config['news_cooldown_minutes']
        )

        self.momentum_scorer = MomentumScorer(use_ml=False)
        self.regime_detector = AIRegimedDetector()
        self.signal_weighter = AdaptiveSignalWeighter()

        # State tracking
        self.open_positions = []
        self.trade_history = []

        logger.info(f"NIJA Apex Strategy v7.1 initialized with balance: ${account_balance:.2f}")

    def _load_default_config(self) -> Dict:
        """Load default strategy configuration."""
        return {
            # Market state filtering
            'min_adx': 20,  # Minimum ADX for trend strength
            'min_volume_multiplier': 1.5,  # Minimum volume vs 20-period average

            # Entry requirements
            'min_signal_score': 4,  # Minimum confirmations for entry (out of 6)
            'require_ema_alignment': True,
            'require_vwap_alignment': True,

            # Risk management
            'max_risk_per_trade': 0.02,  # 2% max risk per trade
            'max_daily_loss': 0.025,  # 2.5% max daily loss
            'max_total_exposure': 0.30,  # 30% max total exposure
            'max_drawdown': 0.10,  # 10% max account drawdown

            # Position sizing
            'base_position_size': 0.03,  # 3% base position
            'max_position_size': 0.10,  # 10% max position

            # Stop-loss and take-profit
            'atr_stop_multiplier': 1.5,  # Stop = 1.5x ATR
            'min_stop_pct': 0.003,  # Minimum 0.3% stop
            'tp1_pct': 0.008,  # TP1 at +0.8%
            'tp2_pct': 0.015,  # TP2 at +1.5%
            'tp3_pct': 0.025,  # TP3 at +2.5%
            'trailing_pct': 0.005,  # Trailing stop at 0.5%

            # Filters
            'news_cooldown_minutes': 3,
            'candle_timing_seconds': 5,  # Avoid first 5 seconds of candle

            # AI/ML features
            'use_ai_momentum': False,  # Not yet implemented
            'use_regime_detection': True
        }

    def analyze_market_state(self, df: pd.DataFrame) -> Dict:
        """
        Analyze market state for trading suitability.

        Checks:
        - Trend strength (ADX)
        - EMA alignment
        - VWAP position
        - MACD histogram
        - Volume

        Args:
            df: DataFrame with OHLCV data

        Returns:
            dict: Market state analysis with 'is_tradeable' boolean
        """
        if len(df) < 50:
            return {
                'is_tradeable': False,
                'reason': 'Insufficient data for analysis',
                'details': {}
            }

        # Calculate indicators
        df['vwap'] = calculate_vwap(df)
        df['rsi'] = calculate_rsi(df, period=14)
        df['atr'] = calculate_atr(df, period=14)
        adx, plus_di, minus_di = calculate_adx(df, period=14)
        df['adx'] = adx
        df['plus_di'] = plus_di
        df['minus_di'] = minus_di

        current_price = df['close'].iloc[-1]
        current_adx = scalar(df['adx'].iloc[-1])
        current_atr = scalar(df['atr'].iloc[-1])
        atr_pct = current_atr / current_price if current_price > 0 else 0

        # Check EMA alignment
        ema_check = check_ema_alignment(df)

        # Check VWAP alignment
        vwap = df['vwap'].iloc[-1]
        vwap_aligned_bullish = current_price > vwap
        vwap_aligned_bearish = current_price < vwap

        # Check for choppy market
        chop_result = detect_choppy_market(df, adx_threshold=self.config['min_adx'])

        # Check volume
        volume_check = check_minimum_volume(
            df,
            min_volume_multiplier=self.config['min_volume_multiplier']
        )

        # Determine if market is tradeable
        is_tradeable = (
            not chop_result['is_choppy'] and
            volume_check['volume_sufficient'] and
            current_adx >= self.config['min_adx']
        )

        # Detect market regime
        regime = self.regime_detector.detect_regime(df, current_adx, atr_pct)

        return {
            'is_tradeable': is_tradeable,
            'reason': chop_result['reason'] if chop_result['is_choppy'] else 'Market conditions favorable',
            'details': {
                'adx': current_adx,
                'atr_pct': atr_pct,
                'ema_alignment': ema_check,
                'vwap_aligned_bullish': vwap_aligned_bullish,
                'vwap_aligned_bearish': vwap_aligned_bearish,
                'volume_sufficient': volume_check['volume_sufficient'],
                'volume_ratio': volume_check['volume_ratio'],
                'regime': regime
            }
        }

    def generate_entry_signal(self, df: pd.DataFrame, market_state: Dict) -> Dict:
        """
        Generate entry signal with multi-confirmation logic.

        Confirmations checked:
        1. VWAP alignment (price above/below VWAP)
        2. EMA alignment (EMA9 > EMA21 > EMA50 for long)
        3. RSI favorable (30-70 range, not extreme)
        4. MACD histogram increasing
        5. Volume confirmation (>1.5x average)
        6. Momentum candle or pullback setup

        Args:
            df: DataFrame with OHLCV and indicators
            market_state: Market state analysis from analyze_market_state()

        Returns:
            dict: {
                'signal': str ('long', 'short', 'none'),
                'score': int (0-6 confirmations),
                'confidence': float (0-1),
                'details': dict
            }
        """
        if not market_state['is_tradeable']:
            return {
                'signal': 'none',
                'score': 0,
                'confidence': 0.0,
                'details': {'reason': 'Market not tradeable'}
            }

        # Calculate additional indicators
        macd_analysis = calculate_macd_histogram_analysis(df)
        momentum_candle = detect_momentum_candle(df)
        vwap_pullback = detect_vwap_pullback(df)
        ema21_pullback = detect_ema21_pullback(df)
        volume_conf = check_volume_confirmation(df, threshold=1.5)

        current_price = df['close'].iloc[-1]
        vwap = scalar(df['vwap'].iloc[-1])
        rsi = scalar(df['rsi'].iloc[-1])

        details = market_state['details']

        # Count confirmations for LONG
        long_confirmations = 0
        long_reasons = []

        if current_price > vwap:
            long_confirmations += 1
            long_reasons.append('Price above VWAP')

        if details['ema_alignment']['bullish_aligned']:
            long_confirmations += 1
            long_reasons.append('Bullish EMA alignment')

        if 30 < rsi < 70:
            long_confirmations += 1
            long_reasons.append('RSI in favorable range')

        if macd_analysis['histogram_increasing'].iloc[-1]:
            long_confirmations += 1
            long_reasons.append('MACD histogram increasing')

        if volume_conf['volume_confirmed']:
            long_confirmations += 1
            long_reasons.append('Strong volume confirmation')

        if momentum_candle['is_bullish_momentum'] or vwap_pullback['bullish_pullback'] or ema21_pullback['bullish_pullback']:
            long_confirmations += 1
            long_reasons.append('Momentum candle or pullback setup')

        # Count confirmations for SHORT
        short_confirmations = 0
        short_reasons = []

        if current_price < vwap:
            short_confirmations += 1
            short_reasons.append('Price below VWAP')

        if details['ema_alignment']['bearish_aligned']:
            short_confirmations += 1
            short_reasons.append('Bearish EMA alignment')

        if 30 < rsi < 70:
            short_confirmations += 1
            short_reasons.append('RSI in favorable range')

        if macd_analysis['histogram'].iloc[-1] < 0 and not macd_analysis['histogram_increasing'].iloc[-1]:
            short_confirmations += 1
            short_reasons.append('MACD histogram decreasing')

        if volume_conf['volume_confirmed']:
            short_confirmations += 1
            short_reasons.append('Strong volume confirmation')

        if momentum_candle['is_bearish_momentum'] or vwap_pullback['bearish_pullback'] or ema21_pullback['bearish_pullback']:
            short_confirmations += 1
            short_reasons.append('Momentum candle or pullback setup')

        # Determine signal
        min_score = self.config['min_signal_score']

        if long_confirmations >= min_score and long_confirmations > short_confirmations:
            signal = 'long'
            score = long_confirmations
            confidence = score / 6.0
            reasons = long_reasons
        elif short_confirmations >= min_score and short_confirmations > long_confirmations:
            signal = 'short'
            score = short_confirmations
            confidence = score / 6.0
            reasons = short_reasons
        else:
            signal = 'none'
            score = max(long_confirmations, short_confirmations)
            confidence = 0.0
            reasons = ['Insufficient confirmations for entry']

        return {
            'signal': signal,
            'score': score,
            'confidence': confidence,
            'details': {
                'long_confirmations': long_confirmations,
                'short_confirmations': short_confirmations,
                'reasons': reasons,
                'macd_analysis': macd_analysis,
                'momentum_candle': momentum_candle,
                'volume_confirmation': volume_conf
            }
        }

    def apply_filters(self, df: pd.DataFrame) -> Dict:
        """
        Apply all market filters before entry.

        Args:
            df: DataFrame with OHLCV and indicators

        Returns:
            dict: Filter results with 'can_trade' boolean
        """
        return apply_all_filters(
            df,
            adx_threshold=self.config['min_adx'],
            min_volume_multiplier=self.config['min_volume_multiplier'],
            seconds_to_avoid=self.config['candle_timing_seconds'],
            news_filter=self.news_filter
        )

    def calculate_position_parameters(self, df: pd.DataFrame, entry_signal: Dict) -> Dict:
        """
        Calculate position size, stop-loss, and take-profits.

        Args:
            df: DataFrame with OHLCV and indicators
            entry_signal: Entry signal from generate_entry_signal()

        Returns:
            dict: Position parameters
        """
        current_price = df['close'].iloc[-1]
        atr = scalar(df['atr'].iloc[-1])
        adx = scalar(df['adx'].iloc[-1])

        # Calculate position size with ADX weighting
        position_calc = self.risk_manager.calculate_position_size_adx_weighted(
            signal_strength=entry_signal['score'],
            adx_value=adx,
            base_size_pct=self.config['base_position_size'],
            max_size_pct=self.config['max_position_size']
        )

        # Calculate stop-loss with ATR
        stop_calc = self.risk_manager.calculate_stop_loss_atr(
            entry_price=current_price,
            atr_value=atr,
            direction=entry_signal['signal'],
            atr_multiplier=self.config['atr_stop_multiplier'],
            min_stop_pct=self.config['min_stop_pct']
        )

        # Calculate tiered take-profits
        tp_calc = self.risk_manager.calculate_tiered_take_profits(
            entry_price=current_price,
            direction=entry_signal['signal'],
            tp1_pct=self.config['tp1_pct'],
            tp2_pct=self.config['tp2_pct'],
            tp3_pct=self.config['tp3_pct']
        )

        return {
            'entry_price': current_price,
            'position_size_usd': position_calc['position_size_usd'],
            'position_size_pct': position_calc['position_size_pct'],
            'stop_loss': stop_calc['stop_price'],
            'stop_distance_pct': stop_calc['stop_distance_pct'],
            'take_profits': tp_calc,
            'adx_multiplier': position_calc['adx_multiplier'],
            'signal_multiplier': position_calc['signal_multiplier']
        }

    def should_enter_trade(self, df: pd.DataFrame) -> Tuple[bool, Optional[Dict]]:
        """
        Main decision function: Should we enter a trade?

        Args:
            df: DataFrame with OHLCV data

        Returns:
            tuple: (should_enter: bool, trade_plan: dict or None)
        """
        # Step 1: Analyze market state
        market_state = self.analyze_market_state(df)

        if not market_state['is_tradeable']:
            logger.info(f"Market not tradeable: {market_state['reason']}")
            return False, None

        # Step 2: Apply filters
        filter_results = self.apply_filters(df)

        if not filter_results['can_trade']:
            logger.info(f"Filters failed: {filter_results['filters_failed']}")
            return False, None

        # Step 3: Generate entry signal
        entry_signal = self.generate_entry_signal(df, market_state)

        if entry_signal['signal'] == 'none':
            logger.info(f"No entry signal (score: {entry_signal['score']}/{self.config['min_signal_score']})")
            return False, None

        # Step 4: Calculate position parameters
        position_params = self.calculate_position_parameters(df, entry_signal)

        # Step 5: Check risk limits
        risk_check = self.risk_manager.can_open_position(position_params['position_size_usd'])

        if not risk_check['can_open']:
            logger.info(f"Risk check failed: {risk_check['reason']}")
            return False, None

        # All checks passed - prepare trade plan
        trade_plan = {
            'signal': entry_signal['signal'],
            'score': entry_signal['score'],
            'confidence': entry_signal['confidence'],
            'entry_price': position_params['entry_price'],
            'position_size_usd': position_params['position_size_usd'],
            'position_size_pct': position_params['position_size_pct'],
            'stop_loss': position_params['stop_loss'],
            'take_profits': position_params['take_profits'],
            'market_state': market_state,
            'entry_reasons': entry_signal['details']['reasons'],
            'timestamp': datetime.utcnow()
        }

        logger.info(f"TRADE SIGNAL: {entry_signal['signal'].upper()} | Score: {entry_signal['score']}/6 | Size: {position_params['position_size_pct']*100:.1f}%")

        return True, trade_plan
