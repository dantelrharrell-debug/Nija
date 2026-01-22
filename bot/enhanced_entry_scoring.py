"""
NIJA Enhanced Entry Scoring System
===================================

Multi-factor weighted scoring system for trade entry decisions.
Considers:
- Trend strength (ADX, EMA alignment)
- Momentum (RSI, MACD)
- Price action (candlestick patterns, support/resistance)
- Volume confirmation
- Market structure (swing highs/lows)

Score Range: 0-100
- 0-40: No trade (weak setup)
- 40-60: Marginal (proceed with caution, reduced size)
- 60-80: Good (standard position size)
- 80-100: Excellent (increased position size)
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple
import logging

try:
    from indicators import scalar
except ImportError:
    def scalar(x):
        if isinstance(x, (tuple, list)):
            if len(x) == 0:
                raise ValueError("Cannot convert empty tuple/list to scalar")
            return float(x[0])
        return float(x)

logger = logging.getLogger("nija.scoring")


class EnhancedEntryScorer:
    """
    Enhanced entry scoring system with weighted factors
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize entry scorer
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        
        # Score thresholds (out of 100)
        self.min_score_threshold = self.config.get('min_score_threshold', 60)  # Minimum to enter trade
        self.excellent_score_threshold = self.config.get('excellent_score_threshold', 80)  # Excellent setup
        
        # Weights for different factors (must sum to 100)
        self.weights = {
            'trend_strength': 25,      # ADX, EMA alignment
            'momentum': 20,             # RSI, MACD direction
            'price_action': 20,         # Candlestick patterns
            'volume': 15,               # Volume confirmation
            'market_structure': 20,     # Support/resistance, swing points
        }
        
        logger.info("EnhancedEntryScorer initialized")
    
    def calculate_entry_score(self, df: pd.DataFrame, indicators: Dict, side: str) -> Tuple[float, Dict]:
        """
        Calculate comprehensive entry score (0-100)
        
        Args:
            df: Price DataFrame with OHLCV data
            indicators: Dictionary of calculated indicators
            side: 'long' or 'short'
            
        Returns:
            Tuple of (total_score, score_breakdown)
        """
        scores = {}
        
        # 1. Trend Strength Score (0-25 points)
        scores['trend_strength'] = self._score_trend_strength(df, indicators, side)
        
        # 2. Momentum Score (0-20 points)
        scores['momentum'] = self._score_momentum(df, indicators, side)
        
        # 3. Price Action Score (0-20 points)
        scores['price_action'] = self._score_price_action(df, indicators, side)
        
        # 4. Volume Score (0-15 points)
        scores['volume'] = self._score_volume(df, indicators)
        
        # 5. Market Structure Score (0-20 points)
        scores['market_structure'] = self._score_market_structure(df, indicators, side)
        
        # Calculate total weighted score
        total_score = sum(scores.values())
        
        # Prepare breakdown with percentages
        breakdown = {
            **scores,
            'total': total_score,
            'quality': self._classify_score(total_score)
        }
        
        logger.debug(f"{side.upper()} entry score: {total_score:.1f}/100 ({breakdown['quality']}) - " +
                    f"Trend:{scores['trend_strength']:.1f} Momentum:{scores['momentum']:.1f} " +
                    f"Price:{scores['price_action']:.1f} Volume:{scores['volume']:.1f} " +
                    f"Structure:{scores['market_structure']:.1f}")
        
        return total_score, breakdown
    
    def _score_trend_strength(self, df: pd.DataFrame, indicators: Dict, side: str) -> float:
        """
        Score trend strength (0-25 points)
        
        Factors:
        - ADX strength (0-10 points)
        - EMA alignment (0-10 points)
        - VWAP alignment (0-5 points)
        """
        score = 0.0
        
        # Get indicator values
        adx = scalar(indicators.get('adx', pd.Series([0])).iloc[-1])
        current_price = df['close'].iloc[-1]
        
        # ADX strength (0-10 points)
        if adx >= 40:
            score += 10.0
        elif adx >= 30:
            score += 8.0
        elif adx >= 25:
            score += 6.0
        elif adx >= 20:
            score += 4.0
        else:
            score += 2.0
        
        # EMA alignment (0-10 points)
        ema9 = indicators.get('ema_9', pd.Series([current_price])).iloc[-1]
        ema21 = indicators.get('ema_21', pd.Series([current_price])).iloc[-1]
        ema50 = indicators.get('ema_50', pd.Series([current_price])).iloc[-1]
        
        if side == 'long':
            # Perfect bullish alignment: price > EMA9 > EMA21 > EMA50
            if current_price > ema9 > ema21 > ema50:
                score += 10.0
            elif current_price > ema9 > ema21:
                score += 7.0
            elif current_price > ema9:
                score += 4.0
        else:  # short
            # Perfect bearish alignment: price < EMA9 < EMA21 < EMA50
            if current_price < ema9 < ema21 < ema50:
                score += 10.0
            elif current_price < ema9 < ema21:
                score += 7.0
            elif current_price < ema9:
                score += 4.0
        
        # VWAP alignment (0-5 points)
        vwap = indicators.get('vwap', pd.Series([current_price])).iloc[-1]
        
        if side == 'long':
            if current_price > vwap:
                # Distance from VWAP indicates strength
                distance_pct = (current_price - vwap) / vwap
                if distance_pct > 0.02:  # More than 2% above
                    score += 5.0
                elif distance_pct > 0.01:  # More than 1% above
                    score += 3.0
                else:
                    score += 2.0
        else:  # short
            if current_price < vwap:
                distance_pct = (vwap - current_price) / vwap
                if distance_pct > 0.02:
                    score += 5.0
                elif distance_pct > 0.01:
                    score += 3.0
                else:
                    score += 2.0
        
        return min(score, self.weights['trend_strength'])
    
    def _score_momentum(self, df: pd.DataFrame, indicators: Dict, side: str) -> float:
        """
        Score momentum (0-20 points)
        
        Factors:
        - RSI position and direction (0-10 points)
        - MACD histogram direction and strength (0-10 points)
        """
        score = 0.0
        
        # RSI scoring (0-10 points)
        rsi_series = indicators.get('rsi', pd.Series([50]))
        rsi = scalar(rsi_series.iloc[-1])
        rsi_prev = scalar(rsi_series.iloc[-2]) if len(rsi_series) >= 2 else rsi
        
        if side == 'long':
            # RSI in bullish range (40-70) and rising
            if 40 < rsi < 70:
                score += 5.0
                if rsi > rsi_prev:  # Rising
                    score += 5.0
                elif rsi > rsi_prev - 2:  # Slightly declining but still good
                    score += 3.0
            elif 30 < rsi <= 40:  # Oversold bounce potential
                score += 7.0
            elif rsi >= 70:  # Overbought - risky
                score += 2.0
        else:  # short
            # RSI in bearish range (30-60) and falling
            if 30 < rsi < 60:
                score += 5.0
                if rsi < rsi_prev:  # Falling
                    score += 5.0
                elif rsi < rsi_prev + 2:
                    score += 3.0
            elif 60 <= rsi < 70:  # Overbought reversal potential
                score += 7.0
            elif rsi <= 30:  # Oversold - risky
                score += 2.0
        
        # MACD histogram scoring (0-10 points)
        macd_hist_series = indicators.get('histogram', pd.Series([0]))
        macd_hist = macd_hist_series.iloc[-1]
        macd_hist_prev = macd_hist_series.iloc[-2] if len(macd_hist_series) >= 2 else macd_hist
        
        if side == 'long':
            if macd_hist > 0:  # Positive histogram
                score += 5.0
                if macd_hist > macd_hist_prev:  # Increasing
                    score += 5.0
                else:
                    score += 2.0
            elif macd_hist > macd_hist_prev:  # Negative but improving
                score += 3.0
        else:  # short
            if macd_hist < 0:  # Negative histogram
                score += 5.0
                if macd_hist < macd_hist_prev:  # Decreasing
                    score += 5.0
                else:
                    score += 2.0
            elif macd_hist < macd_hist_prev:  # Positive but weakening
                score += 3.0
        
        return min(score, self.weights['momentum'])
    
    def _score_price_action(self, df: pd.DataFrame, indicators: Dict, side: str) -> float:
        """
        Score price action patterns (0-20 points)
        
        Factors:
        - Candlestick patterns (0-10 points)
        - Pullback to support/resistance (0-10 points)
        """
        score = 0.0
        
        current = df.iloc[-1]
        previous = df.iloc[-2] if len(df) >= 2 else current
        
        body = current['close'] - current['open']
        prev_body = previous['close'] - previous['open']
        total_range = current['high'] - current['low']
        
        # Candlestick patterns (0-10 points)
        if side == 'long':
            # Bullish engulfing
            if (prev_body < 0 and body > 0 and 
                current['close'] > previous['open'] and 
                current['open'] < previous['close']):
                score += 10.0
            
            # Hammer
            elif total_range > 0:
                lower_wick = current['open'] - current['low'] if body > 0 else current['close'] - current['low']
                if body > 0 and lower_wick > abs(body) * 2 and lower_wick / total_range > 0.6:
                    score += 8.0
            
            # Strong bullish candle
            elif body > 0 and abs(body) / total_range > 0.7:
                score += 6.0
            
            # Regular bullish candle
            elif body > 0:
                score += 4.0
        
        else:  # short
            # Bearish engulfing
            if (prev_body > 0 and body < 0 and 
                current['close'] < previous['open'] and 
                current['open'] > previous['close']):
                score += 10.0
            
            # Shooting star
            elif total_range > 0:
                upper_wick = current['high'] - current['open'] if body < 0 else current['high'] - current['close']
                if body < 0 and upper_wick > abs(body) * 2 and upper_wick / total_range > 0.6:
                    score += 8.0
            
            # Strong bearish candle
            elif body < 0 and abs(body) / total_range > 0.7:
                score += 6.0
            
            # Regular bearish candle
            elif body < 0:
                score += 4.0
        
        # Pullback to EMA/VWAP (0-10 points)
        current_price = current['close']
        ema21 = indicators.get('ema_21', pd.Series([current_price])).iloc[-1]
        vwap = indicators.get('vwap', pd.Series([current_price])).iloc[-1]
        
        # Check if price is near support (for long) or resistance (for short)
        near_ema21 = abs(current_price - ema21) / ema21 < 0.01
        near_vwap = abs(current_price - vwap) / vwap < 0.01
        
        if near_ema21 or near_vwap:
            score += 10.0
        elif abs(current_price - ema21) / ema21 < 0.02 or abs(current_price - vwap) / vwap < 0.02:
            score += 5.0
        
        return min(score, self.weights['price_action'])
    
    def _score_volume(self, df: pd.DataFrame, indicators: Dict) -> float:
        """
        Score volume confirmation (0-15 points)
        
        Factors:
        - Current volume vs average
        - Volume trend
        """
        score = 0.0
        
        current_volume = df['volume'].iloc[-1]
        
        # Compare to 5-period average
        if len(df) >= 5:
            avg_volume_5 = df['volume'].iloc[-5:].mean()
            volume_ratio = current_volume / avg_volume_5 if avg_volume_5 > 0 else 0
            
            if volume_ratio >= 1.5:  # 50% above average
                score += 15.0
            elif volume_ratio >= 1.2:  # 20% above average
                score += 10.0
            elif volume_ratio >= 0.8:  # Close to average
                score += 5.0
            elif volume_ratio >= 0.5:  # Below average
                score += 2.0
        
        return min(score, self.weights['volume'])
    
    def _score_market_structure(self, df: pd.DataFrame, indicators: Dict, side: str) -> float:
        """
        Score market structure (0-20 points)
        
        Factors:
        - Swing high/low proximity
        - Support/resistance levels
        - Higher highs / Lower lows pattern
        """
        score = 0.0
        
        if len(df) < 10:
            return 0.0
        
        current_price = df['close'].iloc[-1]
        
        # Find recent swing high and low
        lookback = min(20, len(df))
        recent_high = df['high'].iloc[-lookback:].max()
        recent_low = df['low'].iloc[-lookback:].min()
        
        if side == 'long':
            # Score based on distance from swing low (support)
            distance_from_low = (current_price - recent_low) / recent_low
            
            if distance_from_low < 0.02:  # Very close to support (within 2%)
                score += 15.0
            elif distance_from_low < 0.05:  # Close to support (within 5%)
                score += 10.0
            elif distance_from_low < 0.10:  # Moderate distance
                score += 5.0
            
            # Check for higher lows pattern
            if len(df) >= 20:
                lows = df['low'].iloc[-20:]
                # Simple check: last 3 swing lows are increasing
                if lows.iloc[-10:].min() > lows.iloc[-20:-10].min():
                    score += 5.0
        
        else:  # short
            # Score based on distance from swing high (resistance)
            distance_from_high = (recent_high - current_price) / recent_high
            
            if distance_from_high < 0.02:  # Very close to resistance
                score += 15.0
            elif distance_from_high < 0.05:  # Close to resistance
                score += 10.0
            elif distance_from_high < 0.10:  # Moderate distance
                score += 5.0
            
            # Check for lower highs pattern
            if len(df) >= 20:
                highs = df['high'].iloc[-20:]
                if highs.iloc[-10:].max() < highs.iloc[-20:-10].max():
                    score += 5.0
        
        return min(score, self.weights['market_structure'])
    
    def _classify_score(self, score: float) -> str:
        """
        Classify score into quality categories
        
        Args:
            score: Total score (0-100)
            
        Returns:
            Quality classification string
        """
        if score >= self.excellent_score_threshold:
            return "Excellent"
        elif score >= 70:
            return "Good"
        elif score >= self.min_score_threshold:
            return "Fair"
        elif score >= 40:
            return "Marginal"
        else:
            return "Weak"
    
    def should_enter_trade(self, score: float) -> bool:
        """
        Determine if trade should be entered based on score
        
        Args:
            score: Entry score (0-100)
            
        Returns:
            True if score meets minimum threshold
        """
        return score >= self.min_score_threshold


# Global instance
entry_scorer = EnhancedEntryScorer()
