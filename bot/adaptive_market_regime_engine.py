"""
NIJA Adaptive Market Regime Engine
===================================

Advanced market regime detection and strategy switching engine.

Features:
- Multi-dimensional regime classification (trend, chop, volatility spike)
- Real-time regime transition detection
- Dynamic strategy swapping per regime
- Regime persistence tracking
- Confidence-based regime filtering

Regimes Detected:
- STRONG_TREND: ADX > 30, clear direction, sustained momentum
- WEAK_TREND: ADX 20-30, developing trend
- RANGING: ADX < 20, choppy price action
- VOLATILITY_SPIKE: Sudden volatility expansion (ATR spike > 2x average)
- CONSOLIDATION: Low volatility, tight range
- CRISIS: Extreme volatility + correlation breakdown

Author: NIJA Trading Systems
Version: 2.0 (Enhanced for Path 1)
Date: January 30, 2026
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple, Optional, List
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging
from collections import deque

logger = logging.getLogger("nija.adaptive_regime")


class RegimeType(Enum):
    """Enhanced market regime classifications"""
    STRONG_TREND = "strong_trend"  # ADX > 30, clear direction
    WEAK_TREND = "weak_trend"  # ADX 20-30
    RANGING = "ranging"  # ADX < 20, choppy
    VOLATILITY_SPIKE = "volatility_spike"  # Sudden volatility expansion
    CONSOLIDATION = "consolidation"  # Low volatility, tight range
    CRISIS = "crisis"  # Extreme volatility


class StrategyMode(Enum):
    """Trading strategies mapped to regimes"""
    TREND_FOLLOWING = "trend_following"
    MEAN_REVERSION = "mean_reversion"
    BREAKOUT = "breakout"
    DEFENSIVE = "defensive"
    SCALPING = "scalping"


@dataclass
class RegimeState:
    """Current market regime state"""
    regime: RegimeType
    confidence: float  # 0.0 to 1.0
    duration_bars: int  # How many bars in this regime
    previous_regime: Optional[RegimeType] = None
    transition_time: Optional[datetime] = None
    metrics: Dict[str, float] = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return {
            'regime': self.regime.value,
            'confidence': self.confidence,
            'duration_bars': self.duration_bars,
            'previous_regime': self.previous_regime.value if self.previous_regime else None,
            'transition_time': self.transition_time.isoformat() if self.transition_time else None,
            'metrics': self.metrics
        }


class AdaptiveMarketRegimeEngine:
    """
    Advanced regime detection engine with dynamic strategy switching
    
    Key Enhancements:
    1. Volatility spike detection (ATR expansion)
    2. Regime transition smoothing (avoid whipsaw)
    3. Multi-timeframe regime confirmation
    4. Strategy recommendation per regime
    5. Regime persistence tracking
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize adaptive regime engine
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        
        # Regime detection thresholds
        self.strong_trend_adx = self.config.get('strong_trend_adx', 30)
        self.weak_trend_adx = self.config.get('weak_trend_adx', 20)
        self.ranging_adx = self.config.get('ranging_adx', 20)
        
        # Volatility spike detection
        self.volatility_spike_multiplier = self.config.get('volatility_spike_multiplier', 2.0)
        self.consolidation_atr_threshold = self.config.get('consolidation_atr_threshold', 0.015)  # 1.5%
        self.crisis_volatility_threshold = self.config.get('crisis_volatility_threshold', 0.08)  # 8%
        
        # Regime persistence (minimum bars before regime change)
        self.min_regime_duration = self.config.get('min_regime_duration', 3)
        self.confidence_threshold = self.config.get('confidence_threshold', 0.6)
        
        # State tracking
        self.current_state: Optional[RegimeState] = None
        self.regime_history: deque = deque(maxlen=100)  # Last 100 regime changes
        self.atr_history: deque = deque(maxlen=20)  # Track ATR for spike detection
        
        # Strategy mapping
        self.regime_to_strategy = {
            RegimeType.STRONG_TREND: StrategyMode.TREND_FOLLOWING,
            RegimeType.WEAK_TREND: StrategyMode.TREND_FOLLOWING,
            RegimeType.RANGING: StrategyMode.MEAN_REVERSION,
            RegimeType.VOLATILITY_SPIKE: StrategyMode.BREAKOUT,
            RegimeType.CONSOLIDATION: StrategyMode.SCALPING,
            RegimeType.CRISIS: StrategyMode.DEFENSIVE
        }
        
        logger.info("AdaptiveMarketRegimeEngine initialized")
    
    def detect_regime(
        self,
        df: pd.DataFrame,
        indicators: Dict,
        current_time: datetime = None
    ) -> Tuple[RegimeState, StrategyMode]:
        """
        Detect current market regime with enhanced classification
        
        Args:
            df: Price DataFrame with OHLCV data
            indicators: Dictionary of calculated indicators
            current_time: Optional timestamp for transition tracking
        
        Returns:
            Tuple of (RegimeState, recommended StrategyMode)
        """
        if current_time is None:
            current_time = datetime.now()
        
        # Extract indicator values
        adx = float(indicators.get('adx', pd.Series([0])).iloc[-1])
        atr = float(indicators.get('atr', pd.Series([0])).iloc[-1])
        current_price = float(df['close'].iloc[-1])
        
        # Calculate derived metrics
        atr_pct = (atr / current_price) if current_price > 0 else 0
        
        # Track ATR for spike detection
        self.atr_history.append(atr_pct)
        
        # Calculate price volatility
        if len(df) >= 20:
            price_volatility = df['close'].iloc[-20:].std() / df['close'].iloc[-20:].mean()
        else:
            price_volatility = 0
        
        # Detect volatility spike
        is_volatility_spike = self._detect_volatility_spike(atr_pct)
        
        # Classify regime
        regime = self._classify_regime(
            adx=adx,
            atr_pct=atr_pct,
            price_volatility=price_volatility,
            is_volatility_spike=is_volatility_spike,
            df=df
        )
        
        # Calculate confidence
        confidence = self._calculate_confidence(regime, adx, atr_pct, price_volatility)
        
        # Check if regime should change (apply persistence filter)
        regime, confidence = self._apply_regime_persistence(regime, confidence)
        
        # Build metrics
        metrics = {
            'adx': adx,
            'atr': atr,
            'atr_pct': atr_pct,
            'price_volatility': price_volatility,
            'is_volatility_spike': is_volatility_spike,
            'avg_atr_20': np.mean(self.atr_history) if len(self.atr_history) > 0 else 0
        }
        
        # Update state
        if self.current_state is None or self.current_state.regime != regime:
            # Regime transition
            previous_regime = self.current_state.regime if self.current_state else None
            self.regime_history.append({
                'time': current_time,
                'from': previous_regime.value if previous_regime else None,
                'to': regime.value,
                'confidence': confidence
            })
            
            self.current_state = RegimeState(
                regime=regime,
                confidence=confidence,
                duration_bars=1,
                previous_regime=previous_regime,
                transition_time=current_time,
                metrics=metrics
            )
            
            logger.info(
                f"Regime transition: {previous_regime.value if previous_regime else 'None'} "
                f"→ {regime.value} (confidence: {confidence:.2f})"
            )
        else:
            # Same regime, increment duration
            self.current_state.duration_bars += 1
            self.current_state.confidence = confidence
            self.current_state.metrics = metrics
        
        # Get recommended strategy
        strategy = self.get_recommended_strategy(regime)
        
        logger.debug(
            f"Regime: {regime.value} | Strategy: {strategy.value} | "
            f"Confidence: {confidence:.2f} | Duration: {self.current_state.duration_bars} bars | "
            f"ADX: {adx:.1f} | ATR%: {atr_pct*100:.2f}%"
        )
        
        return self.current_state, strategy
    
    def _classify_regime(
        self,
        adx: float,
        atr_pct: float,
        price_volatility: float,
        is_volatility_spike: bool,
        df: pd.DataFrame
    ) -> RegimeType:
        """
        Classify market regime based on multiple indicators
        
        Args:
            adx: ADX value
            atr_pct: ATR as percentage of price
            price_volatility: Price volatility (std/mean)
            is_volatility_spike: Whether volatility spike detected
            df: Price DataFrame
        
        Returns:
            RegimeType
        """
        # CRISIS: Extreme volatility
        if price_volatility > self.crisis_volatility_threshold:
            return RegimeType.CRISIS
        
        # VOLATILITY_SPIKE: Sudden expansion
        if is_volatility_spike:
            return RegimeType.VOLATILITY_SPIKE
        
        # STRONG_TREND: High ADX
        if adx >= self.strong_trend_adx:
            return RegimeType.STRONG_TREND
        
        # WEAK_TREND: Medium ADX
        if adx >= self.weak_trend_adx:
            return RegimeType.WEAK_TREND
        
        # CONSOLIDATION: Very low volatility
        if atr_pct < self.consolidation_atr_threshold:
            # Check if price range is tight
            if len(df) >= 20:
                recent_high = df['high'].iloc[-20:].max()
                recent_low = df['low'].iloc[-20:].min()
                recent_close = df['close'].iloc[-1]
                range_pct = (recent_high - recent_low) / recent_close if recent_close > 0 else 0
                
                if range_pct < 0.03:  # Less than 3% range over 20 bars
                    return RegimeType.CONSOLIDATION
        
        # RANGING: Default for low ADX
        return RegimeType.RANGING
    
    def _detect_volatility_spike(self, current_atr_pct: float) -> bool:
        """
        Detect volatility spike (ATR expansion)
        
        Args:
            current_atr_pct: Current ATR as percentage
        
        Returns:
            True if volatility spike detected
        """
        if len(self.atr_history) < 10:
            return False
        
        # Calculate average ATR over last 20 bars
        avg_atr = np.mean(self.atr_history)
        
        # Detect spike: Current ATR is 2x+ average
        if current_atr_pct > avg_atr * self.volatility_spike_multiplier:
            logger.warning(
                f"Volatility spike detected: Current ATR {current_atr_pct*100:.2f}% "
                f"vs Avg {avg_atr*100:.2f}% ({current_atr_pct/avg_atr:.1f}x)"
            )
            return True
        
        return False
    
    def _calculate_confidence(
        self,
        regime: RegimeType,
        adx: float,
        atr_pct: float,
        price_volatility: float
    ) -> float:
        """
        Calculate confidence in regime classification (0.0 to 1.0)
        
        Args:
            regime: Detected regime
            adx: ADX value
            atr_pct: ATR percentage
            price_volatility: Price volatility
        
        Returns:
            Confidence score 0.0-1.0
        """
        if regime == RegimeType.STRONG_TREND:
            # Higher confidence with higher ADX
            if adx >= 40:
                return 0.95
            elif adx >= 35:
                return 0.85
            elif adx >= 30:
                return 0.75
            else:
                return 0.65
        
        elif regime == RegimeType.WEAK_TREND:
            # Moderate confidence for weak trends
            if 22 <= adx <= 28:
                return 0.70
            else:
                return 0.60
        
        elif regime == RegimeType.RANGING:
            # Higher confidence with lower ADX
            if adx <= 10:
                return 0.90
            elif adx <= 15:
                return 0.80
            else:
                return 0.70
        
        elif regime == RegimeType.VOLATILITY_SPIKE:
            # Confidence based on spike magnitude
            if len(self.atr_history) > 0:
                avg_atr = np.mean(self.atr_history)
                spike_ratio = atr_pct / avg_atr if avg_atr > 0 else 1
                if spike_ratio >= 3.0:
                    return 0.95
                elif spike_ratio >= 2.5:
                    return 0.85
                else:
                    return 0.75
            return 0.70
        
        elif regime == RegimeType.CONSOLIDATION:
            # Higher confidence with lower volatility
            if atr_pct < 0.01:  # Less than 1%
                return 0.85
            else:
                return 0.75
        
        elif regime == RegimeType.CRISIS:
            # High confidence in crisis (extreme volatility is clear)
            return 0.95
        
        return 0.50  # Default
    
    def _apply_regime_persistence(
        self,
        new_regime: RegimeType,
        confidence: float
    ) -> Tuple[RegimeType, float]:
        """
        Apply regime persistence filter to avoid whipsaw regime changes
        
        Args:
            new_regime: Newly detected regime
            confidence: Confidence in new regime
        
        Returns:
            Tuple of (final_regime, final_confidence)
        """
        # No current state, accept new regime
        if self.current_state is None:
            return new_regime, confidence
        
        current_regime = self.current_state.regime
        
        # Same regime, no change needed
        if new_regime == current_regime:
            return new_regime, confidence
        
        # Different regime detected
        # Require minimum duration in current regime before allowing change
        if self.current_state.duration_bars < self.min_regime_duration:
            # Stay in current regime unless new regime has very high confidence
            if confidence >= 0.90:
                logger.info(
                    f"Regime change allowed (high confidence {confidence:.2f}) "
                    f"despite short duration ({self.current_state.duration_bars} bars)"
                )
                return new_regime, confidence
            else:
                # Stay in current regime
                logger.debug(
                    f"Regime change filtered (duration {self.current_state.duration_bars} < "
                    f"{self.min_regime_duration}, confidence {confidence:.2f} < 0.90)"
                )
                return current_regime, self.current_state.confidence
        
        # Require minimum confidence for regime change
        if confidence < self.confidence_threshold:
            logger.debug(
                f"Regime change filtered (confidence {confidence:.2f} < {self.confidence_threshold})"
            )
            return current_regime, self.current_state.confidence
        
        # All checks passed, allow regime change
        return new_regime, confidence
    
    def get_recommended_strategy(self, regime: RegimeType) -> StrategyMode:
        """
        Get recommended trading strategy for a regime
        
        Args:
            regime: Market regime
        
        Returns:
            StrategyMode
        """
        return self.regime_to_strategy.get(regime, StrategyMode.DEFENSIVE)
    
    def get_regime_parameters(self, regime: RegimeType) -> Dict:
        """
        Get trading parameters optimized for a regime
        
        Args:
            regime: Market regime
        
        Returns:
            Dictionary of regime-specific parameters
        """
        params = {
            RegimeType.STRONG_TREND: {
                'position_size_multiplier': 1.3,  # Aggressive sizing
                'min_entry_score': 3,
                'trailing_stop_distance': 2.0,  # Wide stops
                'take_profit_multiplier': 1.5,  # Higher targets
                'max_positions': 5,
                'long_rsi_min': 25,
                'long_rsi_max': 45,
                'short_rsi_min': 55,
                'short_rsi_max': 75,
            },
            RegimeType.WEAK_TREND: {
                'position_size_multiplier': 1.0,
                'min_entry_score': 4,
                'trailing_stop_distance': 1.5,
                'take_profit_multiplier': 1.2,
                'max_positions': 4,
                'long_rsi_min': 25,
                'long_rsi_max': 50,
                'short_rsi_min': 50,
                'short_rsi_max': 75,
            },
            RegimeType.RANGING: {
                'position_size_multiplier': 0.8,  # Conservative sizing
                'min_entry_score': 4,
                'trailing_stop_distance': 1.0,  # Tight stops
                'take_profit_multiplier': 0.8,  # Quick profits
                'max_positions': 6,
                'long_rsi_min': 20,
                'long_rsi_max': 50,
                'short_rsi_min': 50,
                'short_rsi_max': 80,
            },
            RegimeType.VOLATILITY_SPIKE: {
                'position_size_multiplier': 0.6,  # Reduced sizing
                'min_entry_score': 4,
                'trailing_stop_distance': 2.5,  # Very wide stops
                'take_profit_multiplier': 1.0,
                'max_positions': 3,
                'long_rsi_min': 30,
                'long_rsi_max': 40,
                'short_rsi_min': 60,
                'short_rsi_max': 70,
            },
            RegimeType.CONSOLIDATION: {
                'position_size_multiplier': 1.1,  # Slightly larger for scalps
                'min_entry_score': 3,
                'trailing_stop_distance': 0.8,  # Very tight stops
                'take_profit_multiplier': 0.6,  # Quick scalps
                'max_positions': 8,
                'long_rsi_min': 25,
                'long_rsi_max': 45,
                'short_rsi_min': 55,
                'short_rsi_max': 75,
            },
            RegimeType.CRISIS: {
                'position_size_multiplier': 0.3,  # Minimal sizing
                'min_entry_score': 5,  # Extremely selective
                'trailing_stop_distance': 3.0,  # Extra wide stops
                'take_profit_multiplier': 0.5,  # Take any profit
                'max_positions': 1,  # Minimal exposure
                'long_rsi_min': 35,
                'long_rsi_max': 40,
                'short_rsi_min': 60,
                'short_rsi_max': 65,
            }
        }
        
        return params.get(regime, params[RegimeType.RANGING])
    
    def get_state(self) -> Optional[RegimeState]:
        """Get current regime state"""
        return self.current_state
    
    def get_regime_history(self, limit: int = 10) -> List[Dict]:
        """
        Get recent regime transitions
        
        Args:
            limit: Maximum number of transitions to return
        
        Returns:
            List of regime transition dictionaries
        """
        history_list = list(self.regime_history)
        return history_list[-limit:] if len(history_list) > limit else history_list


# Global instance
adaptive_regime_engine = AdaptiveMarketRegimeEngine()
