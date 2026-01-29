"""
NIJA Regime Transition Detector
================================

GOD-TIER ENHANCEMENT #4: Early detection of market regime shifts before
traditional indicators flip. Provides advance warning of:
1. Trend to range transitions
2. Range to trend breakouts
3. Volatility regime shifts
4. Momentum exhaustion signals

This allows proactive position management and strategy adjustment before
regime changes are fully realized, avoiding late exits and missed opportunities.

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

logger = logging.getLogger("nija.regime_transition")


class RegimeState(Enum):
    """Market regime states"""
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    VOLATILE = "volatile"


class TransitionType(Enum):
    """Types of regime transitions"""
    TREND_TO_RANGE = "trend_to_range"          # Trend losing strength
    RANGE_TO_TREND = "range_to_trend"          # Breakout brewing
    VOLATILITY_SPIKE = "volatility_spike"      # Vol expansion
    VOLATILITY_COLLAPSE = "volatility_collapse" # Vol compression
    MOMENTUM_EXHAUSTION = "momentum_exhaustion" # Trend fatigue
    NONE = "none"                              # No transition detected


class TransitionSignal(Enum):
    """Signal strength for transitions"""
    NONE = "none"           # No signal
    WEAK = "weak"           # Early warning (10-20% probability)
    MODERATE = "moderate"   # Developing (30-50% probability)
    STRONG = "strong"       # High confidence (60-80% probability)
    CRITICAL = "critical"   # Imminent (80%+ probability)


class RegimeTransitionDetector:
    """
    Detect regime transitions before they fully materialize
    
    Key Features:
    - Leading indicators for regime changes
    - Multi-factor transition probability scoring
    - Early warning signals (before ADX/RSI flip)
    - Momentum divergence detection
    - Volatility regime shift prediction
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize Regime Transition Detector
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        
        # Transition detection parameters
        self.lookback_period = self.config.get('lookback_period', 20)
        self.divergence_threshold = self.config.get('divergence_threshold', 0.15)
        
        # ADX transition thresholds
        self.adx_weakening_threshold = -2.0  # ADX dropping by 2+ points
        self.adx_strengthening_threshold = 3.0  # ADX rising by 3+ points
        
        # Momentum exhaustion thresholds
        self.extreme_rsi_high = 80  # RSI exhaustion level (uptrend)
        self.extreme_rsi_low = 20   # RSI exhaustion level (downtrend)
        
        # Volatility shift thresholds
        self.vol_expansion_threshold = 1.5  # 50% increase in ATR
        self.vol_compression_threshold = 0.7  # 30% decrease in ATR
        
        # Probability scoring weights
        self.factor_weights = {
            'adx_momentum': 0.25,
            'price_momentum_divergence': 0.25,
            'volatility_change': 0.20,
            'volume_divergence': 0.15,
            'range_compression': 0.10,
            'momentum_exhaustion': 0.05,
        }
        
        logger.info("✅ Regime Transition Detector initialized")
        logger.info(f"   Lookback period: {self.lookback_period}")
        logger.info(f"   Divergence threshold: {self.divergence_threshold*100:.0f}%")
    
    def detect_transition(
        self,
        df: pd.DataFrame,
        indicators: Dict,
        current_regime: RegimeState
    ) -> Dict:
        """
        Detect potential regime transitions
        
        Args:
            df: Price DataFrame with OHLCV data
            indicators: Dictionary of calculated indicators
            current_regime: Current market regime
            
        Returns:
            Dictionary with transition analysis
        """
        # 1. Analyze each transition factor
        adx_analysis = self._analyze_adx_momentum(indicators)
        divergence_analysis = self._analyze_momentum_divergence(df, indicators)
        volatility_analysis = self._analyze_volatility_shift(indicators)
        volume_analysis = self._analyze_volume_divergence(df)
        range_analysis = self._analyze_range_compression(df)
        exhaustion_analysis = self._analyze_momentum_exhaustion(indicators)
        
        # 2. Identify primary transition type
        transition_type, transition_confidence = self._identify_transition_type(
            adx_analysis=adx_analysis,
            divergence_analysis=divergence_analysis,
            volatility_analysis=volatility_analysis,
            range_analysis=range_analysis,
            exhaustion_analysis=exhaustion_analysis,
            current_regime=current_regime
        )
        
        # 3. Calculate transition probability
        probability_score = self._calculate_transition_probability(
            adx_analysis=adx_analysis,
            divergence_analysis=divergence_analysis,
            volatility_analysis=volatility_analysis,
            volume_analysis=volume_analysis,
            range_analysis=range_analysis,
            exhaustion_analysis=exhaustion_analysis
        )
        
        # 4. Determine signal strength
        signal_strength = self._determine_signal_strength(probability_score, transition_confidence)
        
        # 5. Generate actionable recommendations
        recommendations = self._generate_recommendations(
            transition_type=transition_type,
            signal_strength=signal_strength,
            current_regime=current_regime,
            probability_score=probability_score
        )
        
        # Compile results
        result = {
            'transition_type': transition_type.value,
            'signal_strength': signal_strength.value,
            'probability_score': probability_score,
            'current_regime': current_regime.value,
            'recommendations': recommendations,
            'factors': {
                'adx_momentum': adx_analysis,
                'divergence': divergence_analysis,
                'volatility': volatility_analysis,
                'volume': volume_analysis,
                'range_compression': range_analysis,
                'momentum_exhaustion': exhaustion_analysis,
            },
            'timestamp': datetime.now(),
        }
        
        if signal_strength != TransitionSignal.NONE:
            logger.warning(f"⚠️  Regime Transition Signal: {transition_type.value.upper()}")
            logger.warning(f"   Signal Strength: {signal_strength.value.upper()}")
            logger.warning(f"   Probability: {probability_score*100:.1f}%")
            logger.warning(f"   Recommendations: {', '.join(recommendations)}")
        
        return result
    
    def _analyze_adx_momentum(self, indicators: Dict) -> Dict:
        """
        Analyze ADX momentum for trend weakening/strengthening
        
        Early warning: ADX changes before regime fully shifts
        
        Args:
            indicators: Dictionary of indicators
            
        Returns:
            ADX momentum analysis
        """
        adx_series = indicators.get('adx', pd.Series([0]))
        if len(adx_series) < 5:
            return {'change': 0, 'rate_of_change': 0, 'signal': 'none'}
        
        adx_current = float(adx_series.iloc[-1])
        adx_5_ago = float(adx_series.iloc[-6]) if len(adx_series) >= 6 else adx_current
        
        # Calculate ADX change and rate of change
        adx_change = adx_current - adx_5_ago
        adx_rate = adx_change / 5  # Per period
        
        # Classify signal
        if adx_change <= self.adx_weakening_threshold:
            signal = 'weakening'  # Trend losing strength
        elif adx_change >= self.adx_strengthening_threshold:
            signal = 'strengthening'  # Trend gaining strength
        else:
            signal = 'stable'
        
        return {
            'current_adx': adx_current,
            'change': adx_change,
            'rate_of_change': adx_rate,
            'signal': signal,
        }
    
    def _analyze_momentum_divergence(
        self,
        df: pd.DataFrame,
        indicators: Dict
    ) -> Dict:
        """
        Detect momentum divergence between price and indicators
        
        Divergence is a leading signal of potential reversals/regime changes.
        
        Args:
            df: Price DataFrame
            indicators: Dictionary of indicators
            
        Returns:
            Divergence analysis
        """
        if len(df) < self.lookback_period:
            return {'detected': False, 'type': 'none', 'severity': 0}
        
        recent_df = df.tail(self.lookback_period)
        close = recent_df['close']
        
        # Get MACD histogram and RSI
        macd_hist = indicators.get('histogram', pd.Series([0]))
        rsi = indicators.get('rsi', pd.Series([50]))
        
        if len(macd_hist) < self.lookback_period or len(rsi) < self.lookback_period:
            return {'detected': False, 'type': 'none', 'severity': 0}
        
        recent_macd = macd_hist.tail(self.lookback_period)
        recent_rsi = rsi.tail(self.lookback_period)
        
        # Detect bullish divergence (price lower lows, indicators higher lows)
        price_slope = self._calculate_slope(close)
        macd_slope = self._calculate_slope(recent_macd)
        rsi_slope = self._calculate_slope(recent_rsi)
        
        # Divergence detection
        bullish_divergence = price_slope < -0.001 and (macd_slope > 0 or rsi_slope > 0)
        bearish_divergence = price_slope > 0.001 and (macd_slope < 0 or rsi_slope < 0)
        
        if bullish_divergence:
            divergence_type = 'bullish'
            severity = abs(price_slope - max(macd_slope, rsi_slope))
        elif bearish_divergence:
            divergence_type = 'bearish'
            severity = abs(price_slope - min(macd_slope, rsi_slope))
        else:
            divergence_type = 'none'
            severity = 0
        
        detected = bullish_divergence or bearish_divergence
        
        return {
            'detected': detected,
            'type': divergence_type,
            'severity': min(1.0, severity / 0.1),  # Normalize to 0-1
            'price_slope': price_slope,
            'macd_slope': macd_slope,
            'rsi_slope': rsi_slope,
        }
    
    def _calculate_slope(self, series: pd.Series) -> float:
        """Calculate simple linear slope of series"""
        if len(series) < 2:
            return 0.0
        
        x = np.arange(len(series))
        y = series.values
        
        # Simple linear regression
        if len(x) > 1:
            slope = np.polyfit(x, y, 1)[0]
            # Normalize by mean to get percentage slope
            mean_val = np.mean(y)
            if mean_val != 0:
                slope = slope / mean_val
        else:
            slope = 0.0
        
        return slope
    
    def _analyze_volatility_shift(self, indicators: Dict) -> Dict:
        """
        Detect volatility regime shifts (expansion or compression)
        
        Args:
            indicators: Dictionary of indicators
            
        Returns:
            Volatility shift analysis
        """
        atr_series = indicators.get('atr', pd.Series([0]))
        if len(atr_series) < 20:
            return {'shift_detected': False, 'shift_type': 'none', 'magnitude': 0}
        
        atr_current = float(atr_series.iloc[-1])
        atr_avg = float(atr_series.iloc[-20:-1].mean())
        
        if atr_avg == 0:
            return {'shift_detected': False, 'shift_type': 'none', 'magnitude': 0}
        
        atr_ratio = atr_current / atr_avg
        
        # Detect shifts
        if atr_ratio >= self.vol_expansion_threshold:
            shift_type = 'expansion'
            shift_detected = True
        elif atr_ratio <= self.vol_compression_threshold:
            shift_type = 'compression'
            shift_detected = True
        else:
            shift_type = 'stable'
            shift_detected = False
        
        magnitude = abs(atr_ratio - 1.0)
        
        return {
            'shift_detected': shift_detected,
            'shift_type': shift_type,
            'magnitude': magnitude,
            'atr_ratio': atr_ratio,
            'current_atr': atr_current,
            'avg_atr': atr_avg,
        }
    
    def _analyze_volume_divergence(self, df: pd.DataFrame) -> Dict:
        """
        Detect volume divergence from price action
        
        Args:
            df: Price DataFrame
            
        Returns:
            Volume divergence analysis
        """
        if len(df) < 20:
            return {'detected': False, 'severity': 0}
        
        recent_df = df.tail(20)
        
        # Calculate price momentum
        price_change = (recent_df['close'].iloc[-1] - recent_df['close'].iloc[0]) / recent_df['close'].iloc[0]
        
        # Calculate volume trend
        volume_recent = recent_df['volume'].tail(5).mean()
        volume_older = recent_df['volume'].head(10).mean()
        
        if volume_older == 0:
            return {'detected': False, 'severity': 0}
        
        volume_ratio = volume_recent / volume_older
        
        # Detect divergence: price moving but volume declining (weak move)
        volume_declining = volume_ratio < 0.8
        price_moving = abs(price_change) > 0.02
        
        detected = volume_declining and price_moving
        severity = abs(1.0 - volume_ratio) if detected else 0
        
        return {
            'detected': detected,
            'severity': severity,
            'volume_ratio': volume_ratio,
            'price_change': price_change,
        }
    
    def _analyze_range_compression(self, df: pd.DataFrame) -> Dict:
        """
        Detect range compression (potential breakout signal)
        
        Args:
            df: Price DataFrame
            
        Returns:
            Range compression analysis
        """
        if len(df) < 20:
            return {'detected': False, 'compression_ratio': 0}
        
        recent_df = df.tail(20)
        
        # Calculate range compression
        recent_range = (recent_df['high'].tail(5).max() - recent_df['low'].tail(5).min())
        older_range = (recent_df['high'].head(10).max() - recent_df['low'].head(10).min())
        
        if older_range == 0:
            return {'detected': False, 'compression_ratio': 0}
        
        compression_ratio = recent_range / older_range
        
        # Compression detected if recent range is < 60% of older range
        detected = compression_ratio < 0.6
        
        return {
            'detected': detected,
            'compression_ratio': compression_ratio,
            'recent_range': recent_range,
            'older_range': older_range,
        }
    
    def _analyze_momentum_exhaustion(self, indicators: Dict) -> Dict:
        """
        Detect momentum exhaustion (extreme RSI with weakening)
        
        Args:
            indicators: Dictionary of indicators
            
        Returns:
            Momentum exhaustion analysis
        """
        rsi_series = indicators.get('rsi', pd.Series([50]))
        if len(rsi_series) < 5:
            return {'detected': False, 'type': 'none'}
        
        rsi_current = float(rsi_series.iloc[-1])
        rsi_prev = float(rsi_series.iloc[-2])
        rsi_change = rsi_current - rsi_prev
        
        # Uptrend exhaustion: RSI > 80 and starting to decline
        uptrend_exhaustion = rsi_current > self.extreme_rsi_high and rsi_change < -1
        
        # Downtrend exhaustion: RSI < 20 and starting to rise
        downtrend_exhaustion = rsi_current < self.extreme_rsi_low and rsi_change > 1
        
        if uptrend_exhaustion:
            exhaustion_type = 'uptrend'
            detected = True
        elif downtrend_exhaustion:
            exhaustion_type = 'downtrend'
            detected = True
        else:
            exhaustion_type = 'none'
            detected = False
        
        return {
            'detected': detected,
            'type': exhaustion_type,
            'rsi_current': rsi_current,
            'rsi_change': rsi_change,
        }
    
    def _identify_transition_type(
        self,
        adx_analysis: Dict,
        divergence_analysis: Dict,
        volatility_analysis: Dict,
        range_analysis: Dict,
        exhaustion_analysis: Dict,
        current_regime: RegimeState
    ) -> Tuple[TransitionType, float]:
        """
        Identify the primary transition type
        
        Returns:
            Tuple of (TransitionType, confidence 0-1)
        """
        # Trend to range transition
        if adx_analysis['signal'] == 'weakening' and current_regime in [RegimeState.TRENDING_UP, RegimeState.TRENDING_DOWN]:
            return TransitionType.TREND_TO_RANGE, 0.7
        
        # Range to trend breakout
        if adx_analysis['signal'] == 'strengthening' and range_analysis['detected']:
            return TransitionType.RANGE_TO_TREND, 0.8
        
        # Volatility spike
        if volatility_analysis['shift_detected'] and volatility_analysis['shift_type'] == 'expansion':
            return TransitionType.VOLATILITY_SPIKE, 0.75
        
        # Volatility collapse
        if volatility_analysis['shift_detected'] and volatility_analysis['shift_type'] == 'compression':
            return TransitionType.VOLATILITY_COLLAPSE, 0.75
        
        # Momentum exhaustion
        if exhaustion_analysis['detected'] or (divergence_analysis['detected'] and divergence_analysis['severity'] > 0.6):
            return TransitionType.MOMENTUM_EXHAUSTION, 0.65
        
        return TransitionType.NONE, 0.0
    
    def _calculate_transition_probability(
        self,
        adx_analysis: Dict,
        divergence_analysis: Dict,
        volatility_analysis: Dict,
        volume_analysis: Dict,
        range_analysis: Dict,
        exhaustion_analysis: Dict
    ) -> float:
        """
        Calculate overall transition probability score (0-1)
        
        Weighted combination of all factors.
        """
        scores = {}
        
        # ADX momentum score
        adx_signal = adx_analysis['signal']
        if adx_signal == 'weakening':
            scores['adx_momentum'] = 0.8
        elif adx_signal == 'strengthening':
            scores['adx_momentum'] = 0.8
        else:
            scores['adx_momentum'] = 0.2
        
        # Divergence score
        if divergence_analysis['detected']:
            scores['price_momentum_divergence'] = divergence_analysis['severity']
        else:
            scores['price_momentum_divergence'] = 0.0
        
        # Volatility change score
        if volatility_analysis['shift_detected']:
            scores['volatility_change'] = min(1.0, volatility_analysis['magnitude'])
        else:
            scores['volatility_change'] = 0.0
        
        # Volume divergence score
        if volume_analysis['detected']:
            scores['volume_divergence'] = min(1.0, volume_analysis['severity'])
        else:
            scores['volume_divergence'] = 0.0
        
        # Range compression score
        if range_analysis['detected']:
            scores['range_compression'] = 1.0 - range_analysis['compression_ratio']
        else:
            scores['range_compression'] = 0.0
        
        # Momentum exhaustion score
        scores['momentum_exhaustion'] = 1.0 if exhaustion_analysis['detected'] else 0.0
        
        # Calculate weighted average
        total_score = sum(
            scores[factor] * weight
            for factor, weight in self.factor_weights.items()
        )
        
        return total_score
    
    def _determine_signal_strength(
        self,
        probability_score: float,
        transition_confidence: float
    ) -> TransitionSignal:
        """
        Determine signal strength based on probability and confidence
        
        Args:
            probability_score: Transition probability (0-1)
            transition_confidence: Confidence in transition type (0-1)
            
        Returns:
            TransitionSignal enum
        """
        # Combine probability and confidence
        combined_score = (probability_score * 0.7 + transition_confidence * 0.3)
        
        if combined_score >= 0.80:
            return TransitionSignal.CRITICAL
        elif combined_score >= 0.60:
            return TransitionSignal.STRONG
        elif combined_score >= 0.40:
            return TransitionSignal.MODERATE
        elif combined_score >= 0.20:
            return TransitionSignal.WEAK
        else:
            return TransitionSignal.NONE
    
    def _generate_recommendations(
        self,
        transition_type: TransitionType,
        signal_strength: TransitionSignal,
        current_regime: RegimeState,
        probability_score: float
    ) -> List[str]:
        """
        Generate actionable recommendations based on transition signals
        
        Returns:
            List of recommendation strings
        """
        recommendations = []
        
        if signal_strength == TransitionSignal.NONE:
            return ["No regime transition detected - continue current strategy"]
        
        # Recommendations based on transition type
        if transition_type == TransitionType.TREND_TO_RANGE:
            recommendations.append("Tighten profit targets - trend weakening")
            recommendations.append("Reduce position sizes for new entries")
            if signal_strength in [TransitionSignal.STRONG, TransitionSignal.CRITICAL]:
                recommendations.append("Consider exiting trend-following positions")
        
        elif transition_type == TransitionType.RANGE_TO_TREND:
            recommendations.append("Prepare for breakout opportunity")
            recommendations.append("Watch for volume confirmation")
            if signal_strength in [TransitionSignal.STRONG, TransitionSignal.CRITICAL]:
                recommendations.append("Position for trend-following entries")
        
        elif transition_type == TransitionType.VOLATILITY_SPIKE:
            recommendations.append("Reduce position sizes - volatility increasing")
            recommendations.append("Widen stop losses to avoid whipsaws")
            recommendations.append("Consider taking partial profits")
        
        elif transition_type == TransitionType.VOLATILITY_COLLAPSE:
            recommendations.append("Tighten stops - volatility compressing")
            recommendations.append("Watch for breakout setup")
        
        elif transition_type == TransitionType.MOMENTUM_EXHAUSTION:
            recommendations.append("Momentum exhaustion detected")
            recommendations.append("Take profits on extended positions")
            if signal_strength in [TransitionSignal.STRONG, TransitionSignal.CRITICAL]:
                recommendations.append("Prepare for potential reversal")
        
        return recommendations


def get_regime_transition_detector(config: Dict = None) -> RegimeTransitionDetector:
    """
    Factory function to create RegimeTransitionDetector instance
    
    Args:
        config: Optional configuration dictionary
        
    Returns:
        RegimeTransitionDetector instance
    """
    return RegimeTransitionDetector(config)


# Example usage and testing
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.WARNING, format='%(levelname)s - %(message)s')
    
    # Create sample data (simulating trend weakening)
    dates = pd.date_range('2024-01-01', periods=100, freq='5T')
    df = pd.DataFrame({
        'timestamp': dates,
        'close': np.concatenate([
            np.linspace(100, 110, 50),  # Uptrend
            np.linspace(110, 109, 50)   # Weakening
        ]),
        'high': np.concatenate([
            np.linspace(101, 111, 50),
            np.linspace(111, 110, 50)
        ]),
        'low': np.concatenate([
            np.linspace(99, 109, 50),
            np.linspace(109, 108, 50)
        ]),
        'volume': np.concatenate([
            np.random.randint(5000, 10000, 50),  # High volume
            np.random.randint(2000, 5000, 50)    # Declining volume
        ])
    })
    
    # Mock indicators showing trend weakening
    indicators = {
        'adx': pd.Series(np.concatenate([
            np.linspace(35, 40, 50),  # Strengthening
            np.linspace(40, 32, 50)   # Weakening
        ])),
        'rsi': pd.Series(np.concatenate([
            np.linspace(60, 75, 50),  # Overbought
            np.linspace(75, 65, 50)   # Declining
        ])),
        'histogram': pd.Series(np.concatenate([
            np.linspace(0.2, 0.8, 50),   # Positive momentum
            np.linspace(0.8, 0.3, 50)    # Declining momentum
        ])),
        'atr': pd.Series(np.ones(100) * 0.5),
    }
    
    # Create detector
    detector = get_regime_transition_detector()
    
    # Detect transition
    result = detector.detect_transition(
        df=df,
        indicators=indicators,
        current_regime=RegimeState.TRENDING_UP
    )
    
    print(f"\n{'='*70}")
    print(f"REGIME TRANSITION ANALYSIS")
    print(f"{'='*70}")
    print(f"Current Regime: {result['current_regime'].upper()}")
    print(f"Transition Type: {result['transition_type'].upper()}")
    print(f"Signal Strength: {result['signal_strength'].upper()}")
    print(f"Probability: {result['probability_score']*100:.1f}%")
    print(f"\nRecommendations:")
    for rec in result['recommendations']:
        print(f"  • {rec}")
    print(f"\nKey Factors:")
    print(f"  ADX Signal: {result['factors']['adx_momentum']['signal']}")
    print(f"  Divergence: {result['factors']['divergence']['type']}")
    print(f"  Volatility: {result['factors']['volatility']['shift_type']}")
    print(f"{'='*70}")
