"""
NIJA APEX STRATEGY v7.1
Unified algorithmic trading strategy with advanced market filters and risk management

Author: NIJA Trading Systems
Version: 7.1
Date: December 2024

ENHANCEMENTS:
- Enhanced entry scoring system (0-100 weighted score)
- Market regime detection and adaptive strategy switching
- Regime-based position sizing and thresholds
"""

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple, List
import logging
import os

from indicators import (
    calculate_vwap, calculate_ema, calculate_rsi, calculate_macd,
    calculate_atr, calculate_adx, scalar
)
from risk_manager import RiskManager
from execution_engine import ExecutionEngine

# Initialize logger before any imports that might fail
logger = logging.getLogger("nija")

# Import exchange capabilities for SHORT entry validation and fee-aware profit targets
try:
    from exchange_capabilities import can_short, get_broker_capabilities, get_min_profit_target
    EXCHANGE_CAPABILITIES_AVAILABLE = True
except ImportError:
    EXCHANGE_CAPABILITIES_AVAILABLE = False
    logger.warning("Exchange capabilities module not available - SHORT validation and fee-aware targets disabled")

# Import position sizer for minimum position validation
try:
    from position_sizer import MIN_POSITION_USD
except ImportError:
    MIN_POSITION_USD = 2.0  # Default to $2 minimum (lowered from $5 on Jan 21, 2026)
    logger.warning("Could not import MIN_POSITION_USD from position_sizer, using default $2.00")

# Import small account constants from fee_aware_config
try:
    from fee_aware_config import (
        SMALL_ACCOUNT_THRESHOLD,
        SMALL_ACCOUNT_MAX_POSITION_PCT
    )
except ImportError:
    SMALL_ACCOUNT_THRESHOLD = 100.0  # Fallback
    SMALL_ACCOUNT_MAX_POSITION_PCT = 0.20  # Fallback
    logger.warning("Could not import small account constants from fee_aware_config, using defaults")

# Broker-specific minimum position sizes (Jan 24, 2026)
KRAKEN_MIN_POSITION_USD = 10.0  # Kraken requires $10 minimum trade size per exchange rules

# Trade quality thresholds (Jan 29, 2026 - EMERGENCY RELAXATION)
# CRITICAL ISSUE: 0.75 confidence threshold blocking ALL signals (0 signals found)
# Balance: $52.70 and dropping - need to re-enable trading immediately
# Strategy: Lower threshold temporarily, monitor quality, adjust based on win rate
MIN_CONFIDENCE = 0.50  # EMERGENCY: Lowered from 0.75 to 0.50 to re-enable signal generation
MAX_ENTRY_SCORE = 5.0  # Maximum entry signal score used for confidence normalization

# Import emergency liquidation for capital preservation (FIX 3)
try:
    from emergency_liquidation import EmergencyLiquidator
    EMERGENCY_LIQUIDATION_AVAILABLE = True
except ImportError:
    EMERGENCY_LIQUIDATION_AVAILABLE = False
    logger.warning("Emergency liquidation module not available")

# Import enhanced entry scoring and regime detection
try:
    from enhanced_entry_scoring import EnhancedEntryScorer
    from market_regime_detector import RegimeDetector, MarketRegime
    ENHANCED_SCORING_AVAILABLE = True
except ImportError:
    ENHANCED_SCORING_AVAILABLE = False
    logger.warning("Enhanced scoring and regime detection modules not available - using basic scoring")


class NIJAApexStrategyV71:
    """
    NIJA Apex Strategy v7.1 - Unified Algorithmic Trading System
    
    Features:
    1. Market Filter (uptrend/downtrend using VWAP, EMA9/21/50, MACD, ADX>20, Volume)
    2. Entry Logic (pullback to EMA21/VWAP, RSI, candlestick patterns, MACD tick, volume)
    3. Enhanced Entry Scoring (0-100 weighted multi-factor scoring)
    4. Market Regime Detection (trending/ranging/volatile)
    5. Adaptive Strategy Switching (regime-based parameters)
    6. Dynamic Risk Management (ADX-based position sizing 2-10%, ATR stop loss)
    7. Exit Logic (opposite signal, trailing stop, trend break)
    8. Smart Filters (news, volume, candle timing)
    9. Optional: AI Momentum Scoring (skeleton)
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
        
        # PROFIT OPTIMIZATION: Load enhanced configuration if not provided
        # Check if a comprehensive config was provided by looking for key optimization settings
        has_comprehensive_config = (
            'use_enhanced_scoring' in self.config or 
            'use_regime_detection' in self.config or 
            'enable_stepped_exits' in self.config
        )
        
        if not has_comprehensive_config:  # If basic/empty config, use optimized defaults
            try:
                from profit_optimization_config import get_profit_optimization_config
                self.config = get_profit_optimization_config()
                logger.info("🚀 Loaded profit optimization configuration")
            except ImportError:
                logger.warning("⚠️  Profit optimization config not available, using defaults")
        
        # PROFIT-TAKING ENFORCEMENT: Always enabled, cannot be disabled
        # This ensures profit-taking works 24/7 on all accounts, brokerages, and tiers
        self.config['enable_take_profit'] = True
        
        # Initialize components with optimized parameters
        self.risk_manager = RiskManager(
            min_position_pct=self.config.get('min_position_pct', 0.02),
            max_position_pct=self.config.get('max_position_pct', 0.10)  # OPTIMIZED: 10% max for more positions (was 20%)
        )
        self.execution_engine = ExecutionEngine(broker_client)
        
        # Initialize enhanced scoring and regime detection
        # PROFIT OPTIMIZATION: Enable by default if available
        enable_enhanced = self.config.get('use_enhanced_scoring', True)  # Default to True
        enable_regime = self.config.get('use_regime_detection', True)  # Default to True
        
        if ENHANCED_SCORING_AVAILABLE and (enable_enhanced or enable_regime):
            self.entry_scorer = EnhancedEntryScorer(self.config)
            self.regime_detector = RegimeDetector(self.config)
            self.use_enhanced_scoring = True
            logger.info("✅ Enhanced entry scoring and regime detection enabled")
        else:
            self.entry_scorer = None
            self.regime_detector = None
            self.use_enhanced_scoring = False
            if not ENHANCED_SCORING_AVAILABLE:
                logger.warning("⚠️  Enhanced scoring modules not available - using legacy scoring")
            else:
                logger.info("ℹ️  Enhanced scoring disabled by configuration")
        
        # Strategy parameters - PROFITABILITY FIX: Balanced for crypto markets
        # EMERGENCY RELAXATION (Jan 29, 2026 - FOURTH RELAXATION): Bot STILL finding ZERO signals after three relaxations
        # Analysis: 18-24/30 markets filtered by smart filters, 6-12 with no entry signal, 0 signals found
        # Issue: volume_min_threshold 0.5% still too high, need to allow ultra-low volume markets
        # Balance: $52.70 and dropping - CRITICAL need for signal generation
        self.min_adx = self.config.get('min_adx', 6)  # FURTHER LOWERED from 8 to 6 - allow extremely weak trends (was 15 → 12 → 8 → 6)
        self.volume_threshold = self.config.get('volume_threshold', 0.05)  # FURTHER LOWERED from 0.1 to 0.05 - 5% of 5-candle avg (was 0.3 → 0.2 → 0.1 → 0.05)
        self.volume_min_threshold = self.config.get('volume_min_threshold', 0.001)  # CRITICAL FIX: Lowered from 0.005 to 0.001 - only filter completely dead markets (was 0.05 → 0.02 → 0.005 → 0.001)
        self.min_trend_confirmation = self.config.get('min_trend_confirmation', 1)  # LOWERED from 2/5 to 1/5 - single indicator confirmation enough
        self.candle_exclusion_seconds = self.config.get('candle_exclusion_seconds', 0)  # DISABLED candle timing filter - was blocking too many opportunities (was 6 → 3 → 1 → 0)
        self.news_buffer_minutes = self.config.get('news_buffer_minutes', 5)
        
        # PROFIT OPTIMIZATION: Stepped profit-taking configuration
        self.enable_stepped_exits = self.config.get('enable_stepped_exits', True)
        self.stepped_exit_levels = self.config.get('stepped_exits', {
            0.015: 0.10,  # Exit 10% at 1.5% profit
            0.025: 0.15,  # Exit 15% at 2.5% profit
            0.035: 0.25,  # Exit 25% at 3.5% profit
            0.050: 0.50,  # Exit 50% at 5.0% profit
        })
        
        # AI Momentum Scoring (optional, skeleton for future)
        self.ai_momentum_enabled = self.config.get('ai_momentum_enabled', False)
        
        # Track last candle time for timing filter (per-symbol to avoid cross-market contamination)
        self.last_candle_times = {}  # symbol -> timestamp
        
        # Track current regime for logging
        self.current_regime = None
        
        logger.info("=" * 70)
        logger.info("NIJA Apex Strategy v7.1 - PROFIT OPTIMIZED")
        logger.info("✅ PROFIT-TAKING: ALWAYS ENABLED (cannot be disabled)")
        logger.info("✅ Multi-broker support: Coinbase, Kraken, Binance, OKX, Alpaca")
        logger.info("✅ All tiers supported: SAVER, INVESTOR, INCOME, LIVABLE, BALLER")
        if self.use_enhanced_scoring:
            logger.info("✅ Enhanced entry scoring: ENABLED (0-100 weighted scoring)")
            logger.info("✅ Regime detection: ENABLED (trending/ranging/volatile)")
            min_score = self.config.get('min_score_threshold', 75)
            logger.info(f"✅ Minimum entry score: {min_score}/100 (quality threshold)")
        if self.enable_stepped_exits:
            logger.info("✅ Stepped profit-taking: ENABLED (partial exits at multiple levels)")
            logger.info(f"   Exit levels: {len(self.stepped_exit_levels)} profit targets")
        logger.info(f"✅ Position sizing: {self.config.get('min_position_pct', 0.02)*100:.0f}%-{self.config.get('max_position_pct', 0.10)*100:.0f}% (capital efficient)")
        logger.info("=" * 70)
    
    def _get_broker_name(self) -> str:
        """
        Get broker name from broker_client.
        
        Returns:
            str: Broker name (e.g., 'kraken', 'coinbase') or 'unknown'
        """
        if not self.broker_client or not hasattr(self.broker_client, 'broker_type'):
            return 'unknown'
        
        broker_type = self.broker_client.broker_type
        if hasattr(broker_type, 'value'):
            # It's an Enum
            return broker_type.value.lower()
        elif isinstance(broker_type, str):
            # It's already a string
            return broker_type.lower()
        else:
            # Fallback to string representation
            return str(broker_type).lower()
    
    def _get_broker_fee_aware_target(self, symbol: str, use_limit_order: bool = True) -> float:
        """
        Get minimum profit target for current broker/symbol to overcome fees.
        
        Formula: min_profit_target = broker_fee * 2.5
        
        This ensures trades are profitable after fees with a safety buffer.
        
        Args:
            symbol: Trading symbol
            use_limit_order: True for maker fees, False for taker fees
            
        Returns:
            Minimum profit target as decimal (e.g., 0.035 = 3.5%)
        """
        if not EXCHANGE_CAPABILITIES_AVAILABLE:
            # Fallback to conservative default if capabilities not available
            return 0.025  # 2.5% default target
        
        broker_name = self._get_broker_name()
        try:
            min_target = get_min_profit_target(broker_name, symbol, use_limit_order)
            logger.debug(f"Fee-aware profit target for {broker_name}/{symbol}: {min_target*100:.2f}%")
            return min_target
        except Exception as e:
            logger.warning(f"Could not get fee-aware target for {broker_name}/{symbol}: {e}")
            return 0.025  # 2.5% fallback
    
    def _get_broker_capabilities(self, symbol: str):
        """
        Get exchange capabilities for current broker and symbol.
        
        Args:
            symbol: Trading symbol
            
        Returns:
            ExchangeCapabilities object or None
        """
        if not EXCHANGE_CAPABILITIES_AVAILABLE:
            return None
        
        broker_name = self._get_broker_name()
        try:
            return get_broker_capabilities(broker_name, symbol)
        except Exception as e:
            logger.warning(f"Could not get capabilities for {broker_name}/{symbol}: {e}")
            return None
    
    def update_broker_client(self, new_broker_client):
        """
        Update the broker client for this strategy and its execution engine.
        
        This is critical when switching between multiple brokers (e.g., KRAKEN to COINBASE)
        to ensure that the execution engine uses the correct broker for placing orders.
        
        CRITICAL FIX (Jan 26, 2026): Prevents broker mismatch where trades are calculated
        for one broker's balance but executed on another broker. This was causing significant
        losses when KRAKEN detected a trade with $57.31 balance but execution used COINBASE's
        $24.16 balance instead.
        
        Args:
            new_broker_client: The new broker client to use
        """
        if new_broker_client:
            self.broker_client = new_broker_client
            if hasattr(self, 'execution_engine') and self.execution_engine:
                self.execution_engine.broker_client = new_broker_client
                logger.debug(f"Updated execution engine broker to {self._get_broker_name()}")
    
    def _validate_trade_quality(self, position_size: float, score: float) -> Dict:
        """
        Validate trade quality based on position size and confidence threshold.
        
        Args:
            position_size: Calculated position size in USD
            score: Entry signal quality score (higher = better)
            
        Returns:
            Dictionary with 'valid' (bool), 'reason' (str), and 'confidence' (float)
        """
        # Normalize position_size in case it's a tuple
        position_size = scalar(position_size)
        
        # Check broker-specific minimum position size (FIX: Jan 24, 2026)
        # Kraken requires $10 minimum, others typically $2
        broker_name = self._get_broker_name()
        broker_minimum = KRAKEN_MIN_POSITION_USD if broker_name == 'kraken' else MIN_POSITION_USD
        
        if float(position_size) < broker_minimum:
            logger.info(f"   ⏭️  Skipping trade: Position ${position_size:.2f} below {broker_name} minimum ${broker_minimum:.2f}")
            return {
                'valid': False,
                'reason': f'Position too small: ${position_size:.2f} < ${broker_minimum:.2f} minimum for {broker_name} (increase account size for better trading)',
                'confidence': 0.0
            }
        
        # Calculate and check confidence threshold (0.60 minimum)
        # Score is a quality metric (higher = better setup)
        # Normalize score to 0-1 range for confidence check
        confidence = min(score / MAX_ENTRY_SCORE, 1.0)
        # FIX: Guard against tuple returns (defensive programming)
        confidence = scalar(confidence)
        
        if float(confidence) < MIN_CONFIDENCE:
            logger.info(f"   ⏭️  Skipping trade: Confidence {confidence:.2f} below minimum {MIN_CONFIDENCE:.2f}")
            return {
                'valid': False,
                'reason': f'Confidence too low: {confidence:.2f} < {MIN_CONFIDENCE:.2f} (weak entry signal)',
                'confidence': confidence
            }
        
        logger.info(f"   ✅ Trade approved: Size=${position_size:.2f}, Confidence={confidence:.2f}")
        return {
            'valid': True,
            'reason': 'Trade quality validated',
            'confidence': confidence
        }
    
    def check_market_filter(self, df: pd.DataFrame, indicators: Dict) -> Tuple[bool, str, str]:
        """
        Market Filter: Only allow trades if uptrend or downtrend conditions are met
        
        Required conditions:
        - VWAP alignment (price above for uptrend, below for downtrend)
        - EMA sequence (9 > 21 > 50 for uptrend, 9 < 21 < 50 for downtrend)
        - MACD histogram alignment (positive for uptrend, negative for downtrend)
        - ADX > min_adx (configurable, default 6 - FOURTH emergency relaxation for signal generation)
        - Volume (market filter) > volume_threshold of 5-candle average (configurable, default 5%)
        - Volume (smart filter) > volume_min_threshold of 20-candle average (configurable, default 0.1%)
        
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
        adx = scalar(indicators['adx'].iloc[-1])
        
        # Volume check (5-candle average)
        avg_volume_5 = df['volume'].iloc[-5:].mean()
        current_volume = df['volume'].iloc[-1]
        volume_ratio = current_volume / avg_volume_5 if avg_volume_5 > 0 else 0
        
        # ADX filter - relaxed for ULTRA AGGRESSIVE mode (15-day goal)
        if self.min_adx > 0 and float(adx) < self.min_adx:
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
        
        # QUALITY FIX: Check trend conditions - configurable threshold via min_trend_confirmation
        # Lowered from 4/5 to 2/5 (Jan 26, 2026) to allow more trading opportunities
        # This filters out marginal setups (0-1/5) while still allowing quality trades (2+/5)
        uptrend_score = sum(uptrend_conditions.values())
        downtrend_score = sum(downtrend_conditions.values())
        
        # Log details for debugging
        logger.debug(f"Market filter - Uptrend: {uptrend_score}/5, Downtrend: {downtrend_score}/5")
        logger.debug(f"  Price vs VWAP: {current_price:.4f} vs {vwap:.4f}")
        logger.debug(f"  EMA sequence: {ema9:.4f} vs {ema21:.4f} vs {ema50:.4f}")
        logger.debug(f"  MACD histogram: {macd_hist:.6f}, ADX: {adx:.1f}, Vol ratio: {volume_ratio:.2f}")
        
        # RELAXED FILTERS (Jan 26, 2026): Lower to 2/5 conditions to allow more trading opportunities
        # Previous: 3/5 required was too strict for low-capital accounts in current market conditions
        # 2/5 allows quality setups while still filtering out complete junk (0-1/5)
        if uptrend_score >= self.min_trend_confirmation:
            return True, 'uptrend', f'Uptrend confirmed ({uptrend_score}/5 - ADX={adx:.1f}, Vol={volume_ratio*100:.0f}%)'
        elif downtrend_score >= self.min_trend_confirmation:
            return True, 'downtrend', f'Downtrend confirmed ({downtrend_score}/5 - ADX={adx:.1f}, Vol={volume_ratio*100:.0f}%)'
        else:
            logger.debug(f"  → Rejected: Insufficient confirmation")
            return False, 'none', f'Insufficient trend confirmation (Up:{uptrend_score}/5, Down:{downtrend_score}/5 - need {self.min_trend_confirmation}/5)'
    
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
        rsi = scalar(indicators['rsi'].iloc[-1])
        rsi_prev = scalar(indicators['rsi'].iloc[-2])
        macd_hist = indicators['histogram'].iloc[-1]
        macd_hist_prev = indicators['histogram'].iloc[-2]
        
        conditions = {}
        
        # 1. Pullback to EMA21 or VWAP (EMERGENCY RELAXATION Jan 29: 2.0% tolerance for crypto volatility - was 1.0%)
        near_ema21 = abs(current_price - ema21) / ema21 < 0.02
        near_vwap = abs(current_price - vwap) / vwap < 0.02
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
        signal = score >= 2  # EMERGENCY RELAXATION (Jan 29): 2/5 required - allow more opportunities (was 5/5 → 3/5 → 2/5)
        
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
        rsi = scalar(indicators['rsi'].iloc[-1])
        rsi_prev = scalar(indicators['rsi'].iloc[-2])
        macd_hist = indicators['histogram'].iloc[-1]
        macd_hist_prev = indicators['histogram'].iloc[-2]
        
        conditions = {}
        
        # 1. Pullback to EMA21 or VWAP (EMERGENCY RELAXATION Jan 29: 2.0% tolerance for crypto volatility - was 1.0%)
        near_ema21 = abs(current_price - ema21) / ema21 < 0.02
        near_vwap = abs(current_price - vwap) / vwap < 0.02
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
        signal = score >= 2  # EMERGENCY RELAXATION (Jan 29): 2/5 required - allow more opportunities (was 5/5 → 3/5 → 2/5)
        
        reason = f"Short score: {score}/5 ({', '.join([k for k, v in conditions.items() if v])})" if conditions else "Short score: 0/5"
        
        if score > 0:
            logger.debug(f"  Short entry check: {reason}")
        
        return signal, score, reason
    
    def check_smart_filters(self, df: pd.DataFrame, current_time: datetime, symbol: str = None) -> Tuple[bool, str]:
        """
        Smart Filters to avoid bad trades
        
        Filters:
        1. No trades 5 min before/after major news (stub - placeholder for News API)
        2. No trades if volume < 0.5% avg (20-candle rolling average - emergency relaxation to find opportunities)
        3. No trading during first 1 second of a new candle (per-symbol tracking)
        
        Args:
            df: Price DataFrame
            current_time: Current datetime
            symbol: Trading symbol (required for candle timing filter)
        
        Returns:
            Tuple of (allowed, reason)
        """
        # Filter 1: News filter (stub - placeholder for future News API integration)
        # TODO: Integrate with News API (e.g., Benzinga, Alpha Vantage, etc.)
        # For now, this is a placeholder that always passes
        news_clear = True  # Stub: would check upcoming news events here
        
        # Filter 2: Volume filter - threshold is configurable via volume_min_threshold (default 0.1%)
        # EMERGENCY RELAXATION (Jan 29, 2026 - FOURTH RELAXATION): Lowered from 0.5% to 0.1% to allow ultra-low volume markets
        avg_volume = df['volume'].rolling(window=20).mean().iloc[-1]
        current_volume = df['volume'].iloc[-1]
        volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0
        
        if volume_ratio < self.volume_min_threshold:
            logger.debug(f'   🔇 Smart filter (volume): {volume_ratio*100:.1f}% < {self.volume_min_threshold*100:.0f}% threshold')
            return False, f'Volume too low ({volume_ratio*100:.1f}% of avg) - threshold: {self.volume_min_threshold*100:.0f}%'
        
        # Filter 3: Candle timing filter (DISABLED)
        # EMERGENCY RELAXATION (Jan 29, 2026 - FOURTH RELAXATION): DISABLED (set to 0) - was blocking too many opportunities
        # Detect new candle by comparing timestamps
        # CRITICAL FIX (Jan 27, 2026): Use per-symbol tracking to avoid cross-market contamination
        # Previously used single instance variable causing all markets to block each other
        if len(df) >= 2 and symbol is not None:
            # Check if we have a proper datetime index
            if hasattr(df.index, 'to_pydatetime'):
                # We have a datetime index - apply the candle timing filter
                current_candle_time = df.index[-1]
                last_candle_time = self.last_candle_times.get(symbol)
                
                # If we have timestamp data, check if we're in first 3 seconds
                if last_candle_time != current_candle_time:
                    # New candle detected - store time and check elapsed time
                    if last_candle_time is None:
                        # First run for this symbol - allow trade
                        self.last_candle_times[symbol] = current_candle_time
                    else:
                        # Calculate time since candle started
                        # Normalize to timezone-naive datetime to avoid timezone mismatch issues
                        candle_dt = current_candle_time.to_pydatetime()
                        if candle_dt.tzinfo is not None:
                            candle_dt = candle_dt.replace(tzinfo=None)
                        if current_time.tzinfo is not None:
                            current_time_naive = current_time.replace(tzinfo=None)
                        else:
                            current_time_naive = current_time
                        time_since_candle = (current_time_naive - candle_dt).total_seconds()
                        
                        self.last_candle_times[symbol] = current_candle_time
                        
                        # Block trade if we're in first N seconds of new candle
                        if time_since_candle < self.candle_exclusion_seconds:
                            logger.debug(f'   🔇 Smart filter (candle timing): {time_since_candle:.0f}s < {self.candle_exclusion_seconds}s threshold')
                            return False, f'First {self.candle_exclusion_seconds}s of new candle - waiting for stability'
            else:
                # No datetime index available - skip candle timing filter
                # This prevents blocking all trades when timestamp data isn't in the DataFrame index
                logger.debug('   ℹ️  Candle timing filter skipped (no datetime index available)')
        elif symbol is None:
            # No symbol provided - skip candle timing filter to avoid errors
            logger.debug('   ℹ️  Candle timing filter skipped (no symbol provided)')
        
        return True, 'All smart filters passed'
    
    def _get_risk_score(self, score: float, metadata: Dict) -> float:
        """
        Get the appropriate score for risk calculations
        
        Args:
            score: Enhanced score (if available) or legacy score
            metadata: Metadata dictionary from enhanced scoring
            
        Returns:
            Score to use for risk calculations (legacy 0-5 scale)
        """
        if self.use_enhanced_scoring and metadata:
            return metadata.get('legacy_score', score)
        return score
    
    def check_entry_with_enhanced_scoring(self, df: pd.DataFrame, indicators: Dict, 
                                         side: str, account_balance: float) -> Tuple[bool, float, str, Dict]:
        """
        Check entry conditions using enhanced scoring system
        
        This method combines:
        - Legacy 5-point entry logic (for backward compatibility)
        - Enhanced 0-100 weighted scoring system
        - Market regime detection and adaptive thresholds
        
        Args:
            df: Price DataFrame
            indicators: Dictionary of calculated indicators
            side: 'long' or 'short'
            account_balance: Current account balance
            
        Returns:
            Tuple of (should_enter, score, reason, metadata)
        """
        # Get legacy score first (0-5 points)
        if side == 'long':
            legacy_signal, legacy_score, legacy_reason = self.check_long_entry(df, indicators)
        else:
            legacy_signal, legacy_score, legacy_reason = self.check_short_entry(df, indicators)
        
        # If enhanced scoring not available, use legacy only
        if not self.use_enhanced_scoring:
            return legacy_signal, legacy_score, legacy_reason, {'legacy_score': legacy_score}
        
        # Calculate enhanced score (0-100)
        enhanced_score, score_breakdown = self.entry_scorer.calculate_entry_score(df, indicators, side)
        
        # Detect market regime
        regime, regime_metrics = self.regime_detector.detect_regime(df, indicators)
        self.current_regime = regime
        
        # Get regime-specific parameters
        regime_params = self.regime_detector.get_regime_parameters(regime)
        
        # Adjust score threshold based on regime
        should_enter_enhanced = self.entry_scorer.should_enter_trade(enhanced_score)
        
        # Combined decision: Both legacy and enhanced must agree
        should_enter = legacy_signal and should_enter_enhanced
        
        # Build comprehensive reason
        reason = f"{side.upper()} | Regime:{regime.value} | Legacy:{legacy_score}/5 | Enhanced:{enhanced_score:.1f}/100 | {score_breakdown['quality']}"
        
        # Metadata for logging and analysis
        metadata = {
            'legacy_score': legacy_score,
            'enhanced_score': enhanced_score,
            'score_breakdown': score_breakdown,
            'regime': regime.value,
            'regime_confidence': regime_metrics['confidence'],
            'regime_params': regime_params,
            'should_enter_legacy': legacy_signal,
            'should_enter_enhanced': should_enter_enhanced,
            'combined_decision': should_enter
        }
        
        if should_enter:
            logger.info(f"  ✅ {reason}")
            logger.info(f"     Trend:{score_breakdown['trend_strength']:.1f} "
                       f"Momentum:{score_breakdown['momentum']:.1f} "
                       f"Price:{score_breakdown['price_action']:.1f} "
                       f"Volume:{score_breakdown['volume']:.1f} "
                       f"Structure:{score_breakdown['market_structure']:.1f}")
        else:
            logger.debug(f"  ❌ {reason}")
        
        return should_enter, enhanced_score, reason, metadata
    
    def adjust_position_size_for_regime(self, base_position_size: float, 
                                       regime: 'MarketRegime', score: float) -> float:
        """
        Adjust position size based on market regime and entry score
        
        Args:
            base_position_size: Base position size from risk manager
            regime: Current market regime
            score: Enhanced entry score (0-100)
            
        Returns:
            Adjusted position size
        """
        if not self.use_enhanced_scoring:
            return base_position_size
        
        # Regime-based adjustment
        regime_adjusted = self.regime_detector.adjust_position_size(regime, base_position_size)
        
        # Score-based adjustment (higher scores = larger positions)
        if score >= 80:  # Excellent setup
            score_multiplier = 1.2
        elif score >= 70:  # Good setup
            score_multiplier = 1.0
        elif score >= 60:  # Fair setup
            score_multiplier = 0.9
        else:  # Marginal setup
            score_multiplier = 0.7
        
        # Combine adjustments
        final_size = regime_adjusted * score_multiplier
        
        logger.debug(f"Position size adjustment: ${base_position_size:.2f} -> ${final_size:.2f} "
                    f"(regime:{regime.value}, score:{score:.1f})")
        
        return final_size
    
    def check_exit_conditions(self, symbol: str, df: pd.DataFrame, 
                             indicators: Dict, current_price: float) -> Tuple[bool, str]:
        """
        Exit Logic
        
        Conditions:
        0. **EMERGENCY LIQUIDATION** (FIX 3): PnL <= -1% → IMMEDIATE SELL
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
        
        # FIX 3: EMERGENCY LIQUIDATION CHECK (HIGHEST PRIORITY)
        # If PnL <= -1%, force immediate liquidation with NO QUESTIONS
        # This bypasses ALL other checks and filters
        if EMERGENCY_LIQUIDATION_AVAILABLE:
            try:
                liquidator = EmergencyLiquidator()
                if liquidator.should_force_liquidate(position, current_price):
                    # CRITICAL: Return True to trigger immediate exit
                    # The execution will bypass all normal checks
                    return True, '🚨 EMERGENCY LIQUIDATION: PnL <= -1% (capital preservation override)'
            except Exception as e:
                logger.error(f"Error checking emergency liquidation: {e}")
        
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
            logger.debug(
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
            filters_ok, filter_reason = self.check_smart_filters(df, current_time, symbol)
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
                logger.debug(f"📊 Managing position: {symbol} @ ${current_price:.4f}")
                
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
                
                # PRIORITY 1: Check stepped profit exits (more aggressive, fee-aware)
                # This takes profits gradually as position becomes profitable
                stepped_exit = self.execution_engine.check_stepped_profit_exits(symbol, current_price)
                if stepped_exit:
                    return {
                        'action': 'partial_exit',
                        'reason': f"Stepped profit exit at {stepped_exit['profit_level']} (NET: {stepped_exit['net_profit_pct']*100:.1f}%)",
                        'position': position,
                        'exit_size': stepped_exit['exit_size'],
                        'exit_pct': stepped_exit['exit_pct'],
                        'current_price': current_price
                    }
                
                # PRIORITY 2: Check traditional take profit levels (backup)
                tp_level = self.execution_engine.check_take_profit_hit(symbol, current_price)
                if tp_level:
                    return {
                        'action': f'take_profit_{tp_level}',
                        'reason': f'{tp_level.upper()} reached',
                        'position': position
                    }
                
                # Update trailing stop
                atr = scalar(indicators['atr'].iloc[-1])
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
            adx = scalar(indicators['adx'].iloc[-1])
            
            # EARLY FILTER: Check if we can afford minimum position size for this broker
            # This avoids wasting computation on trades that will be rejected anyway
            broker_name = self._get_broker_name()
            
            # Kraken requires $10 minimum, others typically allow smaller sizes
            min_required_balance = KRAKEN_MIN_POSITION_USD if broker_name == 'kraken' else MIN_POSITION_USD
            
            # Calculate maximum possible position size
            # For small accounts (<$100), use 20% to meet broker minimums
            # For larger accounts, use configured max (typically 10%)
            if account_balance < SMALL_ACCOUNT_THRESHOLD:
                max_position_pct = SMALL_ACCOUNT_MAX_POSITION_PCT
            else:
                max_position_pct = self.risk_manager.max_position_pct
            
            max_position_size = account_balance * max_position_pct
            
            # If even our maximum possible position is below minimum, skip analysis entirely
            if max_position_size < min_required_balance:
                logger.info(f"   ❌ {symbol}: Account too small for {broker_name}")
                logger.info(f"      Balance: ${account_balance:.2f} | Max position: ${max_position_size:.2f} ({max_position_pct*100:.0f}%)")
                logger.info(f"      Required minimum: ${min_required_balance:.2f}")
                # Guard against division by zero
                if max_position_pct > 0:
                    min_balance_needed = min_required_balance / max_position_pct
                    logger.info(f"      💡 Need ${min_balance_needed:.2f}+ balance to trade on {broker_name}")
                else:
                    logger.info(f"      💡 Need larger balance to trade on {broker_name}")
                return {
                    'action': 'hold',
                    'reason': f'Account too small for {broker_name} minimum (${min_required_balance:.2f})'
                }
            
            if trend == 'uptrend':
                # Use enhanced scoring if available, otherwise legacy
                if self.use_enhanced_scoring:
                    long_signal, score, reason, metadata = self.check_entry_with_enhanced_scoring(
                        df, indicators, 'long', account_balance
                    )
                else:
                    long_signal, score, reason = self.check_long_entry(df, indicators)
                    metadata = {}
                
                if long_signal:
                    # Calculate position size
                    # CRITICAL (Rule #3): account_balance is now TOTAL EQUITY (cash + positions)
                    # from broker.get_account_balance() which returns total equity, not just cash
                    risk_score = self._get_risk_score(score, metadata)
                    
                    # Get broker context for intelligent minimum position adjustments
                    broker_name = self._get_broker_name()
                    broker_min = KRAKEN_MIN_POSITION_USD if broker_name == 'kraken' else MIN_POSITION_USD
                    
                    position_size, size_breakdown = self.risk_manager.calculate_position_size(
                        account_balance, adx, risk_score,
                        broker_name=broker_name,
                        broker_min_position=broker_min
                    )
                    # Normalize position_size (defensive programming - ensures scalar even if tuple unpacking changes)
                    position_size = scalar(position_size)
                    
                    # Adjust position size based on regime and score
                    if self.use_enhanced_scoring and self.current_regime:
                        position_size = self.adjust_position_size_for_regime(
                            position_size, self.current_regime, score
                        )
                    
                    if float(position_size) == 0:
                        return {
                            'action': 'hold',
                            'reason': f'Position size = 0 (ADX={adx:.1f} < {self.min_adx})'
                        }
                    
                    # Validate trade quality (position size and confidence)
                    validation = self._validate_trade_quality(position_size, risk_score)
                    if not validation['valid']:
                        return {
                            'action': 'hold',
                            'reason': validation['reason']
                        }
                    
                    # Calculate stop loss and take profit
                    swing_low = self.risk_manager.find_swing_low(df, lookback=10)
                    atr = scalar(indicators['atr'].iloc[-1])
                    stop_loss = self.risk_manager.calculate_stop_loss(
                        current_price, 'long', swing_low, atr
                    )
                    
                    # ✅ FEE-AWARE PROFIT TARGETS (Phase 4)
                    # Get broker-specific round-trip fee and use it for dynamic profit targets
                    broker_capabilities = self._get_broker_capabilities(symbol)
                    broker_fee = broker_capabilities.get_round_trip_fee(use_limit_order=True) if broker_capabilities else None
                    
                    tp_levels = self.risk_manager.calculate_take_profit_levels(
                        current_price, stop_loss, 'long', broker_fee_pct=broker_fee, use_limit_order=True
                    )
                    
                    # Adjust TP levels based on regime if enhanced scoring is enabled
                    if self.use_enhanced_scoring and self.current_regime:
                        tp_levels = self.regime_detector.adjust_take_profit_levels(
                            self.current_regime, tp_levels
                        )
                    
                    result = {
                        'action': 'enter_long',
                        'reason': reason,
                        'entry_price': current_price,
                        'position_size': position_size,
                        'stop_loss': stop_loss,
                        'take_profit': tp_levels,
                        'score': score,
                        'adx': adx
                    }
                    
                    # Add metadata if available
                    if metadata:
                        result['metadata'] = metadata
                    
                    return result
            
            elif trend == 'downtrend':
                # ✅ BROKER-AWARE SHORT EXECUTION (HIGH-IMPACT OPTIMIZATION)
                # Check if this broker/symbol supports shorting BEFORE analyzing
                # This prevents wasted computational cycles on blocked trades
                # Effect: Increases win rate, capital utilization, compounding speed
                if EXCHANGE_CAPABILITIES_AVAILABLE:
                    if not can_short(broker_name, symbol):
                        logger.debug(f"   {symbol}: Skipping SHORT analysis - {broker_name} does not support shorting for {symbol}")
                        logger.debug(f"      Market mode: SPOT (long-only) | For shorting use FUTURES/PERPS")
                        return {
                            'action': 'hold',
                            'reason': f'{broker_name} does not support shorting for {symbol} (SPOT market - long-only)'
                        }
                else:
                    # If exchange capabilities not available, log warning but allow (risky)
                    logger.warning(f"⚠️  Exchange capability check unavailable - analyzing SHORT for {symbol} (risky!)")
                
                # Use enhanced scoring if available, otherwise legacy
                if self.use_enhanced_scoring:
                    short_signal, score, reason, metadata = self.check_entry_with_enhanced_scoring(
                        df, indicators, 'short', account_balance
                    )
                else:
                    short_signal, score, reason = self.check_short_entry(df, indicators)
                    metadata = {}
                
                if short_signal:
                    # Calculate position size
                    # CRITICAL (Rule #3): account_balance is now TOTAL EQUITY (cash + positions)
                    # from broker.get_account_balance() which returns total equity, not just cash
                    risk_score = self._get_risk_score(score, metadata)
                    
                    # Get broker context for intelligent minimum position adjustments
                    broker_name = self._get_broker_name()
                    broker_min = KRAKEN_MIN_POSITION_USD if broker_name == 'kraken' else MIN_POSITION_USD
                    
                    position_size, size_breakdown = self.risk_manager.calculate_position_size(
                        account_balance, adx, risk_score,
                        broker_name=broker_name,
                        broker_min_position=broker_min
                    )
                    # Normalize position_size (defensive programming - ensures scalar even if tuple unpacking changes)
                    position_size = scalar(position_size)
                    
                    # Adjust position size based on regime and score
                    if self.use_enhanced_scoring and self.current_regime:
                        position_size = self.adjust_position_size_for_regime(
                            position_size, self.current_regime, score
                        )
                    
                    if float(position_size) == 0:
                        return {
                            'action': 'hold',
                            'reason': f'Position size = 0 (ADX={adx:.1f} < {self.min_adx})'
                        }
                    
                    # Validate trade quality (position size and confidence)
                    validation = self._validate_trade_quality(position_size, risk_score)
                    if not validation['valid']:
                        return {
                            'action': 'hold',
                            'reason': validation['reason']
                        }
                    
                    # Calculate stop loss and take profit
                    swing_high = self.risk_manager.find_swing_high(df, lookback=10)
                    atr = scalar(indicators['atr'].iloc[-1])
                    stop_loss = self.risk_manager.calculate_stop_loss(
                        current_price, 'short', swing_high, atr
                    )
                    
                    # ✅ FEE-AWARE PROFIT TARGETS (Phase 4)
                    # Get broker-specific round-trip fee and use it for dynamic profit targets
                    broker_capabilities = self._get_broker_capabilities(symbol)
                    broker_fee = broker_capabilities.get_round_trip_fee(use_limit_order=True) if broker_capabilities else None
                    
                    tp_levels = self.risk_manager.calculate_take_profit_levels(
                        current_price, stop_loss, 'short', broker_fee_pct=broker_fee, use_limit_order=True
                    )
                    
                    # Adjust TP levels based on regime if enhanced scoring is enabled
                    if self.use_enhanced_scoring and self.current_regime:
                        tp_levels = self.regime_detector.adjust_take_profit_levels(
                            self.current_regime, tp_levels
                        )
                    
                    result = {
                        'action': 'enter_short',
                        'reason': reason,
                        'entry_price': current_price,
                        'position_size': position_size,
                        'stop_loss': stop_loss,
                        'take_profit': tp_levels,
                        'score': score,
                        'adx': adx
                    }
                    
                    # Add metadata if available
                    if metadata:
                        result['metadata'] = metadata
                    
                    return result
            
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
                # EXCHANGE CAPABILITY CHECK: Verify broker supports shorting for this symbol
                # This prevents SHORT entries on exchanges that don't support them (e.g., Kraken spot)
                broker_name = self._get_broker_name()
                
                # Check if this broker/symbol combination supports shorting
                if EXCHANGE_CAPABILITIES_AVAILABLE:
                    if not can_short(broker_name, symbol):
                        logger.warning(f"⚠️  SHORT entry BLOCKED: {broker_name} does not support shorting for {symbol}")
                        logger.warning(f"   Strategy signal: enter_short @ {action_data['entry_price']:.2f}")
                        logger.warning(f"   Exchange: {broker_name} (spot markets don't support shorting)")
                        logger.warning(f"   Symbol: {symbol}")
                        logger.warning(f"   ℹ️  Note: SHORT works on futures/perpetuals (e.g., BTC-PERP)")
                        return False
                else:
                    logger.warning(f"⚠️  Exchange capability check unavailable - allowing SHORT (risky!)")
                
                # Execute SHORT entry
                position = self.execution_engine.execute_entry(
                    symbol=symbol,
                    side='short',
                    position_size=action_data['position_size'],
                    entry_price=action_data['entry_price'],
                    stop_loss=action_data['stop_loss'],
                    take_profit_levels=action_data['take_profit']
                )
                if position:
                    logger.info(f"✅ Short entry executed: {symbol} @ {action_data['entry_price']:.2f} (broker: {broker_name})")
                    return True
            
            elif action == 'exit':
                success = self.execution_engine.execute_exit(
                    symbol=symbol,
                    exit_price=action_data.get('current_price', action_data['position']['entry_price']),
                    size_pct=1.0,
                    reason=action_data['reason']
                )
                return success
            
            elif action == 'partial_exit':
                # Stepped profit exit (fee-aware gradual profit-taking)
                success = self.execution_engine.execute_exit(
                    symbol=symbol,
                    exit_price=action_data.get('current_price'),
                    size_pct=action_data['exit_pct'],
                    reason=action_data['reason']
                )
                if success:
                    logger.info(f"✅ Partial exit executed: {symbol} - {action_data['exit_pct']*100:.0f}% @ ${action_data['current_price']:.4f}")
                    logger.info(f"   Reason: {action_data['reason']}")
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
            rsi = scalar(indicators['rsi'].iloc[-1])
            adx = scalar(indicators['adx'].iloc[-1])
            macd_hist = indicators['histogram'].iloc[-1]
            
            # Normalize to 0-1 range
            rsi_score = abs(rsi - 50) / 50  # Distance from neutral
            adx_score = min(adx / 50, 1.0)  # Trend strength
            macd_score = 0.5  # Placeholder
            
            # Weighted average
            momentum_score = (rsi_score * 0.3 + adx_score * 0.5 + macd_score * 0.2)
            
            return momentum_score
        
        return 0.5  # Neutral score when disabled
