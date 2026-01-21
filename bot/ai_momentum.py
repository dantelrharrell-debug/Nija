"""
NIJA Apex Strategy v7.1 - AI Momentum Scoring Module

Extensible AI-powered momentum scoring system (skeleton for future ML integration).

Future capabilities:
- Machine learning-based momentum prediction
- Multi-timeframe pattern recognition
- Sentiment analysis integration
- Adaptive signal weighting based on market regime
"""

import numpy as np
from typing import Dict, List, Optional
import logging

logger = logging.getLogger("nija.ai_momentum")

# Import scalar helper for indicator conversions
try:
    from indicators import scalar
except ImportError:
    # Fallback if indicators.py is not available
    def scalar(x):
        if isinstance(x, (tuple, list)):
            return float(x[0])
        return float(x)


class AIRegimedDetector:
    """
    Market regime detection using statistical methods.
    
    In future, this would integrate with ML models to detect:
    - Trending vs ranging markets
    - Volatility regimes (low/medium/high)
    - Market sentiment (risk-on vs risk-off)
    """
    
    def __init__(self):
        """Initialize regime detector."""
        logger.info("AI Regime Detector initialized (rule-based mode)")
    
    def detect_regime(self, df, adx_value: float, atr_pct: float) -> Dict:
        """
        Detect current market regime.
        
        Args:
            df: DataFrame with OHLCV data
            adx_value: Current ADX value
            atr_pct: Current ATR as percentage of price
        
        Returns:
            dict: {
                'regime': str ('trending_bullish', 'trending_bearish', 'ranging', 'volatile'),
                'confidence': float (0-1),
                'characteristics': dict
            }
        """
        if len(df) < 50:
            return {
                'regime': 'unknown',
                'confidence': 0.0,
                'characteristics': {}
            }
        
        # Calculate regime characteristics
        ema_20 = df['close'].ewm(span=20, adjust=False).mean().iloc[-1]
        current_price = df['close'].iloc[-1]
        price_vs_ema = (current_price - ema_20) / ema_20 if ema_20 > 0 else 0
        
        # Convert indicators to scalar to handle tuples/lists
        adx_value = scalar(adx_value)
        atr_pct = scalar(atr_pct)
        
        # Determine regime
        if adx_value > 25 and price_vs_ema > 0.01:
            regime = 'trending_bullish'
            confidence = min(adx_value / 50, 1.0)
        elif adx_value > 25 and price_vs_ema < -0.01:
            regime = 'trending_bearish'
            confidence = min(adx_value / 50, 1.0)
        elif adx_value < 20:
            regime = 'ranging'
            confidence = 1.0 - (adx_value / 20)
        elif atr_pct > 0.03:
            regime = 'volatile'
            confidence = min(atr_pct / 0.05, 1.0)
        else:
            regime = 'transitioning'
            confidence = 0.5
        
        characteristics = {
            'adx': adx_value,
            'atr_pct': atr_pct,
            'price_vs_ema20': price_vs_ema,
            'trend_strength': 'strong' if adx_value > 30 else 'moderate' if adx_value > 20 else 'weak'
        }
        
        return {
            'regime': regime,
            'confidence': confidence,
            'characteristics': characteristics
        }


class MomentumScorer:
    """
    AI-enhanced momentum scoring system.
    
    Combines traditional technical indicators with statistical analysis
    to generate momentum scores. Future versions will integrate ML models.
    """
    
    def __init__(self, use_ml: bool = False):
        """
        Initialize momentum scorer.
        
        Args:
            use_ml: Enable ML-based scoring (default: False, not implemented)
        """
        self.use_ml = use_ml
        self.regime_detector = AIRegimedDetector()
        
        if use_ml:
            logger.warning("ML mode requested but not yet implemented. Using rule-based scoring.")
        else:
            logger.info("Momentum scorer initialized (rule-based mode)")
    
    def calculate_momentum_score(self, indicators: Dict, market_data: Dict) -> Dict:
        """
        Calculate comprehensive momentum score.
        
        Args:
            indicators: Dict of technical indicators
            market_data: Dict of market data and context
        
        Returns:
            dict: {
                'score': float (0-100),
                'direction': str ('bullish', 'bearish', 'neutral'),
                'confidence': float (0-1),
                'components': dict of sub-scores
            }
        """
        components = {}
        
        # Trend component (0-25 points)
        trend_score = self._calculate_trend_score(indicators)
        components['trend'] = trend_score
        
        # Momentum component (0-25 points)
        momentum_score = self._calculate_momentum_component(indicators)
        components['momentum'] = momentum_score
        
        # Volume component (0-25 points)
        volume_score = self._calculate_volume_score(indicators)
        components['volume'] = volume_score
        
        # Volatility component (0-25 points)
        volatility_score = self._calculate_volatility_score(indicators)
        components['volatility'] = volatility_score
        
        # Calculate total score
        total_score = sum(components.values())
        
        # Determine direction and confidence
        if total_score > 60:
            direction = 'bullish'
            confidence = (total_score - 50) / 50
        elif total_score < 40:
            direction = 'bearish'
            confidence = (50 - total_score) / 50
        else:
            direction = 'neutral'
            confidence = 1.0 - abs(total_score - 50) / 50
        
        return {
            'score': total_score,
            'direction': direction,
            'confidence': min(confidence, 1.0),
            'components': components
        }
    
    def _calculate_trend_score(self, indicators: Dict) -> float:
        """Calculate trend strength score (0-25)."""
        score = 0.0
        
        # EMA alignment
        if indicators.get('ema_alignment', {}).get('bullish_aligned'):
            score += 10.0
        elif indicators.get('ema_alignment', {}).get('bearish_aligned'):
            score += 10.0
        
        # ADX strength
        adx = scalar(indicators.get('adx', 0))
        if adx > 25:
            score += min((adx - 25) / 25 * 10, 10)
        
        # Price vs VWAP
        price_vs_vwap = indicators.get('price_vs_vwap', 0)
        if abs(price_vs_vwap) > 0.005:
            score += min(abs(price_vs_vwap) * 1000, 5)
        
        return min(score, 25.0)
    
    def _calculate_momentum_component(self, indicators: Dict) -> float:
        """Calculate momentum score (0-25)."""
        score = 0.0
        
        # MACD histogram
        macd = indicators.get('macd', {})
        if macd.get('histogram_increasing'):
            score += 10.0
        
        # RSI momentum
        rsi = scalar(indicators.get('rsi', 50))
        if 40 < rsi < 60:
            score += 5.0
        elif 30 < rsi < 70:
            score += 3.0
        
        # Momentum candle
        momentum_candle = indicators.get('momentum_candle', {})
        if momentum_candle.get('is_bullish_momentum') or momentum_candle.get('is_bearish_momentum'):
            score += 10.0
        
        return min(score, 25.0)
    
    def _calculate_volume_score(self, indicators: Dict) -> float:
        """Calculate volume score (0-25)."""
        volume_ratio = indicators.get('volume_ratio', 0)
        
        if volume_ratio >= 2.0:
            return 25.0
        elif volume_ratio >= 1.5:
            return 20.0
        elif volume_ratio >= 1.0:
            return 15.0
        elif volume_ratio >= 0.7:
            return 10.0
        elif volume_ratio >= 0.5:
            return 5.0
        else:
            return 0.0
    
    def _calculate_volatility_score(self, indicators: Dict) -> float:
        """Calculate volatility appropriateness score (0-25)."""
        atr_pct = indicators.get('atr_pct', 0)
        
        # Optimal ATR range: 0.5% - 2.0%
        if 0.005 <= atr_pct <= 0.02:
            return 25.0
        elif atr_pct < 0.005:
            # Too low volatility
            return max(0, atr_pct / 0.005 * 25)
        else:
            # Too high volatility
            return max(0, 25 - (atr_pct - 0.02) / 0.03 * 25)


class AdaptiveSignalWeighter:
    """
    Adaptive signal weighting based on market conditions.
    
    Adjusts importance of different signals based on current market regime.
    Future ML integration would learn optimal weights from historical data.
    """
    
    def __init__(self):
        """Initialize adaptive weighter."""
        logger.info("Adaptive signal weighter initialized")
        
        # Default signal weights (can be adjusted by regime)
        self.base_weights = {
            'vwap_alignment': 0.20,
            'ema_alignment': 0.20,
            'rsi_signal': 0.15,
            'macd_signal': 0.15,
            'volume_confirmation': 0.15,
            'momentum_candle': 0.15
        }
    
    def get_regime_adjusted_weights(self, regime: str) -> Dict[str, float]:
        """
        Get signal weights adjusted for market regime.
        
        Args:
            regime: Market regime string
        
        Returns:
            dict: Adjusted signal weights
        """
        weights = self.base_weights.copy()
        
        if regime == 'trending_bullish' or regime == 'trending_bearish':
            # In strong trends, emphasize trend-following signals
            weights['vwap_alignment'] = 0.25
            weights['ema_alignment'] = 0.25
            weights['momentum_candle'] = 0.20
            weights['rsi_signal'] = 0.10
            weights['macd_signal'] = 0.10
            weights['volume_confirmation'] = 0.10
        
        elif regime == 'ranging':
            # In ranging markets, emphasize mean-reversion signals
            weights['rsi_signal'] = 0.25
            weights['vwap_alignment'] = 0.20
            weights['volume_confirmation'] = 0.20
            weights['ema_alignment'] = 0.15
            weights['macd_signal'] = 0.15
            weights['momentum_candle'] = 0.05
        
        elif regime == 'volatile':
            # In volatile markets, emphasize volume and momentum
            weights['volume_confirmation'] = 0.30
            weights['momentum_candle'] = 0.25
            weights['macd_signal'] = 0.20
            weights['vwap_alignment'] = 0.10
            weights['ema_alignment'] = 0.10
            weights['rsi_signal'] = 0.05
        
        return weights
    
    def calculate_weighted_signal_score(self, signals: Dict[str, bool],
                                        regime: str = 'neutral') -> float:
        """
        Calculate weighted signal score based on regime.
        
        Args:
            signals: Dict of signal names to boolean values
            regime: Current market regime
        
        Returns:
            float: Weighted score (0-100)
        """
        weights = self.get_regime_adjusted_weights(regime)
        
        total_score = 0.0
        for signal_name, signal_value in signals.items():
            if signal_name in weights:
                if signal_value:
                    total_score += weights[signal_name] * 100
        
        return min(total_score, 100.0)


# Placeholder for future ML model integration
class MLMomentumPredictor:
    """
    Machine learning-based momentum predictor (placeholder for future implementation).
    
    Future capabilities:
    - LSTM/Transformer models for price prediction
    - Random Forest for pattern classification
    - Gradient Boosting for momentum scoring
    - Online learning for continuous adaptation
    """
    
    def __init__(self):
        """Initialize ML predictor."""
        logger.info("ML Momentum Predictor initialized (placeholder mode)")
        self.model = None
    
    def train(self, historical_data, labels):
        """Train ML model on historical data."""
        logger.warning("ML training not yet implemented")
        pass
    
    def predict_momentum(self, features) -> Dict:
        """Predict momentum using ML model."""
        logger.warning("ML prediction not yet implemented")
        return {
            'prediction': 0.5,
            'confidence': 0.0,
            'model': 'placeholder'
        }
