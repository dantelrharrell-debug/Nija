"""
NIJA Market Regime Detector
============================

Detects market regimes to optimize trading strategy parameters:
- TRENDING: Strong directional movement (ADX > 25)
- RANGING: Sideways consolidation (ADX < 20)
- VOLATILE: High volatility choppy market (ADX 20-25, high ATR)

Each regime uses different entry thresholds and position sizing strategies.
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple
from enum import Enum
import logging

logger = logging.getLogger("nija.regime")


class MarketRegime(Enum):
    """Market regime types"""
    TRENDING = "trending"
    RANGING = "ranging"
    VOLATILE = "volatile"


class RegimeDetector:
    """
    Detect market regime based on technical indicators
    
    Regime Classification:
    - TRENDING: ADX > 25, clear directional movement
    - RANGING: ADX < 20, price oscillating in range
    - VOLATILE: ADX 20-25, high ATR/price ratio (>3%)
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize regime detector
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        
        # Regime thresholds
        self.trending_adx_min = self.config.get('trending_adx_min', 25)
        self.ranging_adx_max = self.config.get('ranging_adx_max', 20)
        self.volatile_atr_threshold = self.config.get('volatile_atr_threshold', 0.03)  # 3% ATR/price
        
        # Regime-specific parameters
        self.regime_params = {
            MarketRegime.TRENDING: {
                'min_entry_score': 3,  # Require 3/5 conditions
                'position_size_multiplier': 1.2,  # Increase position size by 20%
                'trailing_stop_distance': 1.5,  # Wider trailing stop (1.5x ATR)
                'take_profit_multiplier': 1.5,  # Higher profit targets
            },
            MarketRegime.RANGING: {
                'min_entry_score': 4,  # Require 4/5 conditions (more selective)
                'position_size_multiplier': 0.8,  # Reduce position size by 20%
                'trailing_stop_distance': 1.0,  # Tighter trailing stop (1.0x ATR)
                'take_profit_multiplier': 0.8,  # Lower profit targets (take profits faster)
            },
            MarketRegime.VOLATILE: {
                'min_entry_score': 4,  # Require 4/5 conditions (more selective)
                'position_size_multiplier': 0.7,  # Reduce position size by 30%
                'trailing_stop_distance': 2.0,  # Wider trailing stop (2.0x ATR)
                'take_profit_multiplier': 1.0,  # Normal profit targets
            }
        }
        
        logger.info("MarketRegimeDetector initialized")
    
    def detect_regime(self, df: pd.DataFrame, indicators: Dict) -> Tuple[MarketRegime, Dict]:
        """
        Detect current market regime
        
        Args:
            df: Price DataFrame with OHLCV data
            indicators: Dictionary of calculated indicators
            
        Returns:
            Tuple of (regime, metrics)
        """
        # Get current indicator values
        adx = float(indicators.get('adx', pd.Series([0])).iloc[-1])
        atr = float(indicators.get('atr', pd.Series([0])).iloc[-1])
        current_price = float(df['close'].iloc[-1])
        
        # Calculate ATR as percentage of price
        atr_pct = (atr / current_price) if current_price > 0 else 0
        
        # Calculate price volatility (std dev of last 20 closes)
        price_volatility = df['close'].iloc[-20:].std() / df['close'].iloc[-20:].mean() if len(df) >= 20 else 0
        
        # Detect regime
        regime = self._classify_regime(adx, atr_pct, price_volatility)
        
        # Calculate additional metrics
        metrics = {
            'adx': adx,
            'atr': atr,
            'atr_pct': atr_pct,
            'price_volatility': price_volatility,
            'regime': regime.value,
            'confidence': self._calculate_regime_confidence(adx, atr_pct, regime)
        }
        
        logger.debug(f"Regime detected: {regime.value} (ADX={adx:.1f}, ATR%={atr_pct*100:.2f}%, Volatility={price_volatility*100:.2f}%)")
        
        return regime, metrics
    
    def _classify_regime(self, adx: float, atr_pct: float, price_volatility: float) -> MarketRegime:
        """
        Classify market regime based on indicators
        
        Args:
            adx: ADX value
            atr_pct: ATR as percentage of price
            price_volatility: Price volatility (std/mean)
            
        Returns:
            MarketRegime enum
        """
        # TRENDING: Strong directional movement
        if adx >= self.trending_adx_min:
            return MarketRegime.TRENDING
        
        # RANGING: Low ADX, consolidating
        elif adx < self.ranging_adx_max and atr_pct < self.volatile_atr_threshold:
            return MarketRegime.RANGING
        
        # VOLATILE: Medium ADX with high volatility
        else:
            return MarketRegime.VOLATILE
    
    def _calculate_regime_confidence(self, adx: float, atr_pct: float, regime: MarketRegime) -> float:
        """
        Calculate confidence in regime classification (0.0 to 1.0)
        
        Args:
            adx: ADX value
            atr_pct: ATR as percentage of price
            regime: Detected regime
            
        Returns:
            Confidence score 0.0-1.0
        """
        if regime == MarketRegime.TRENDING:
            # Confidence increases with ADX above threshold
            if adx >= 40:
                return 1.0
            elif adx >= 30:
                return 0.8
            elif adx >= 25:
                return 0.6
            else:
                return 0.4
        
        elif regime == MarketRegime.RANGING:
            # Confidence increases as ADX decreases
            if adx <= 10:
                return 1.0
            elif adx <= 15:
                return 0.8
            elif adx <= 20:
                return 0.6
            else:
                return 0.4
        
        else:  # VOLATILE
            # Confidence based on how far we are from clear regimes
            trending_distance = abs(adx - self.trending_adx_min)
            ranging_distance = abs(adx - self.ranging_adx_max)
            min_distance = min(trending_distance, ranging_distance)
            
            # Higher confidence when we're clearly between regimes
            if min_distance >= 5:
                return 0.8
            elif min_distance >= 3:
                return 0.6
            else:
                return 0.4
    
    def get_regime_parameters(self, regime: MarketRegime) -> Dict:
        """
        Get trading parameters for a given regime
        
        Args:
            regime: Market regime
            
        Returns:
            Dictionary of regime-specific parameters
        """
        return self.regime_params.get(regime, self.regime_params[MarketRegime.VOLATILE])
    
    def adjust_entry_score_threshold(self, regime: MarketRegime, base_score: int) -> Tuple[bool, int]:
        """
        Adjust entry score threshold based on regime
        
        Args:
            regime: Current market regime
            base_score: Calculated entry score (0-5)
            
        Returns:
            Tuple of (should_enter, min_required_score)
        """
        params = self.get_regime_parameters(regime)
        min_score = params['min_entry_score']
        
        should_enter = base_score >= min_score
        
        return should_enter, min_score
    
    def adjust_position_size(self, regime: MarketRegime, base_position_size: float) -> float:
        """
        Adjust position size based on regime
        
        Args:
            regime: Current market regime
            base_position_size: Base position size in USD
            
        Returns:
            Adjusted position size
        """
        params = self.get_regime_parameters(regime)
        multiplier = params['position_size_multiplier']
        
        adjusted_size = base_position_size * multiplier
        
        logger.debug(f"Position size adjusted for {regime.value}: ${base_position_size:.2f} -> ${adjusted_size:.2f} ({multiplier}x)")
        
        return adjusted_size
    
    def get_trailing_stop_distance(self, regime: MarketRegime, atr: float) -> float:
        """
        Get trailing stop distance based on regime
        
        Args:
            regime: Current market regime
            atr: Average True Range
            
        Returns:
            Trailing stop distance
        """
        params = self.get_regime_parameters(regime)
        multiplier = params['trailing_stop_distance']
        
        return atr * multiplier
    
    def adjust_take_profit_levels(self, regime: MarketRegime, base_tp_levels: Dict) -> Dict:
        """
        Adjust take profit levels based on regime
        
        Args:
            regime: Current market regime
            base_tp_levels: Base take profit levels dictionary
            
        Returns:
            Adjusted take profit levels
        """
        params = self.get_regime_parameters(regime)
        multiplier = params['take_profit_multiplier']
        
        adjusted_tp = {}
        for level, price in base_tp_levels.items():
            if isinstance(price, (int, float)):
                # Adjust numeric TP levels
                adjusted_tp[level] = price * (1 + (multiplier - 1))
            else:
                adjusted_tp[level] = price
        
        return adjusted_tp


# Global instance
regime_detector = RegimeDetector()
