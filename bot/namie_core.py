"""
NIJA Adaptive Market Intelligence Engine (NAMIE) 🧠
====================================================

The unified adaptive engine that multiplies trading performance by:
- Auto-switching strategies based on market regime
- Preventing chop losses through intelligent filtering
- Boosting win rate via regime-optimized entry criteria
- Increasing R:R through adaptive profit targets

Core Components:
1. Regime Classification - Multi-layered market regime detection
2. Volatility Clustering - Dynamic volatility pattern recognition
3. Trend Strength Scoring - Quantitative trend assessment (0-100)
4. Auto Strategy Switching - Intelligent strategy selection per regime
5. Chop Detection - Advanced sideways market filtering

Author: NIJA Trading Systems
Version: 1.0 - NAMIE Core Engine
Date: January 30, 2026
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

# Import existing regime detection components
try:
    from bot.market_regime_detector import MarketRegime, RegimeDetector
    from bot.bayesian_regime_detector import BayesianRegimeDetector, RegimeProbabilities
    from bot.regime_strategy_selector import RegimeBasedStrategySelector, TradingStrategy
    from bot.volatility_adaptive_sizer import VolatilityAdaptiveSizer, VolatilityRegime
except ImportError:
    from market_regime_detector import MarketRegime, RegimeDetector
    from bayesian_regime_detector import BayesianRegimeDetector, RegimeProbabilities
    from regime_strategy_selector import RegimeBasedStrategySelector, TradingStrategy
    from volatility_adaptive_sizer import VolatilityAdaptiveSizer, VolatilityRegime

logger = logging.getLogger("nija.namie")


class TrendStrength(Enum):
    """Trend strength classifications (0-100 scale)"""
    VERY_WEAK = "very_weak"      # 0-20: No clear trend
    WEAK = "weak"                # 20-40: Weak trend
    MODERATE = "moderate"        # 40-60: Moderate trend
    STRONG = "strong"            # 60-80: Strong trend
    VERY_STRONG = "very_strong"  # 80-100: Very strong trend


class ChopCondition(Enum):
    """Choppy market conditions"""
    NONE = "none"                # Clean trend, no chop
    MILD = "mild"                # Some chop, tradable
    MODERATE = "moderate"        # Moderate chop, caution
    SEVERE = "severe"            # Severe chop, avoid trading
    EXTREME = "extreme"          # Extreme chop, halt trading


@dataclass
class NAMIESignal:
    """Unified NAMIE intelligence signal"""
    timestamp: datetime = field(default_factory=datetime.utcnow)
    
    # Regime Classification
    regime: MarketRegime = MarketRegime.RANGING
    regime_confidence: float = 0.0  # 0-1
    regime_probabilities: Optional[RegimeProbabilities] = None
    
    # Volatility Analysis
    volatility_regime: VolatilityRegime = VolatilityRegime.NORMAL
    volatility_cluster: str = "stable"  # stable, expanding, contracting
    atr_pct: float = 0.0
    
    # Trend Analysis
    trend_strength: int = 0  # 0-100 score
    trend_strength_category: TrendStrength = TrendStrength.VERY_WEAK
    trend_direction: str = "neutral"  # up, down, neutral
    
    # Chop Detection
    chop_condition: ChopCondition = ChopCondition.NONE
    chop_score: float = 0.0  # 0-100 (higher = more choppy)
    
    # Strategy Selection
    optimal_strategy: TradingStrategy = TradingStrategy.NONE
    strategy_confidence: float = 0.0  # 0-1
    alternative_strategies: List[Tuple[TradingStrategy, float]] = field(default_factory=list)
    
    # Trading Recommendations
    should_trade: bool = False
    trade_reason: str = ""
    position_size_multiplier: float = 1.0
    min_entry_score_required: int = 3
    
    # Metrics
    metrics: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Convert signal to dictionary for logging/storage"""
        return {
            'timestamp': self.timestamp.isoformat(),
            'regime': self.regime.value,
            'regime_confidence': self.regime_confidence,
            'volatility_regime': self.volatility_regime.value,
            'volatility_cluster': self.volatility_cluster,
            'trend_strength': self.trend_strength,
            'trend_direction': self.trend_direction,
            'chop_condition': self.chop_condition.value,
            'chop_score': self.chop_score,
            'optimal_strategy': self.optimal_strategy.value,
            'should_trade': self.should_trade,
            'trade_reason': self.trade_reason,
            'position_size_multiplier': self.position_size_multiplier,
        }


class NAMIECore:
    """
    NIJA Adaptive Market Intelligence Engine - Core Orchestrator
    
    Unifies all regime detection, volatility analysis, and strategy selection
    into a single intelligent system that adapts to market conditions in real-time.
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize NAMIE Core Engine
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        
        # Initialize component modules
        self.regime_detector = RegimeDetector(self.config)
        self.bayesian_detector = BayesianRegimeDetector(self.config)
        self.strategy_selector = RegimeBasedStrategySelector(self.config)
        self.volatility_sizer = VolatilityAdaptiveSizer(self.config)
        
        # NAMIE configuration
        self.min_regime_confidence = self.config.get('min_regime_confidence', 0.6)
        self.min_trend_strength = self.config.get('min_trend_strength', 40)
        self.max_chop_score = self.config.get('max_chop_score', 60)
        
        # Performance tracking
        self.performance_by_regime = {
            MarketRegime.TRENDING: {'wins': 0, 'losses': 0, 'total_pnl': 0.0},
            MarketRegime.RANGING: {'wins': 0, 'losses': 0, 'total_pnl': 0.0},
            MarketRegime.VOLATILE: {'wins': 0, 'losses': 0, 'total_pnl': 0.0},
        }
        
        logger.info("🧠 NAMIE Core Engine initialized")
        logger.info(f"   Min regime confidence: {self.min_regime_confidence}")
        logger.info(f"   Min trend strength: {self.min_trend_strength}")
        logger.info(f"   Max chop score: {self.max_chop_score}")
    
    def analyze_market(
        self,
        df: pd.DataFrame,
        indicators: Dict,
        symbol: str = "UNKNOWN"
    ) -> NAMIESignal:
        """
        Perform comprehensive market analysis and generate NAMIE signal
        
        Args:
            df: Price DataFrame with OHLCV data
            indicators: Dictionary of calculated technical indicators
            symbol: Trading symbol (for logging)
        
        Returns:
            NAMIESignal with comprehensive market intelligence
        """
        logger.debug(f"🧠 NAMIE analyzing {symbol}...")
        
        # Step 1: Regime Classification (Multi-layered)
        regime, regime_metrics = self._classify_regime(df, indicators)
        
        # Step 2: Volatility Analysis
        volatility_regime, volatility_cluster, atr_pct = self._analyze_volatility(df, indicators)
        
        # Step 3: Trend Strength Scoring
        trend_strength, trend_category, trend_direction = self._score_trend_strength(df, indicators)
        
        # Step 4: Chop Detection
        chop_condition, chop_score = self._detect_chop(df, indicators, regime)
        
        # Step 5: Strategy Selection
        optimal_strategy, strategy_confidence, alternatives = self._select_strategy(
            regime, volatility_regime, trend_strength, chop_score
        )
        
        # Step 6: Trading Decision
        should_trade, trade_reason, position_multiplier, min_entry_score = self._make_trading_decision(
            regime, regime_metrics['confidence'], trend_strength, chop_score, optimal_strategy
        )
        
        # Build NAMIE Signal
        signal = NAMIESignal(
            regime=regime,
            regime_confidence=regime_metrics['confidence'],
            regime_probabilities=regime_metrics.get('probabilities'),
            volatility_regime=volatility_regime,
            volatility_cluster=volatility_cluster,
            atr_pct=atr_pct,
            trend_strength=trend_strength,
            trend_strength_category=trend_category,
            trend_direction=trend_direction,
            chop_condition=chop_condition,
            chop_score=chop_score,
            optimal_strategy=optimal_strategy,
            strategy_confidence=strategy_confidence,
            alternative_strategies=alternatives,
            should_trade=should_trade,
            trade_reason=trade_reason,
            position_size_multiplier=position_multiplier,
            min_entry_score_required=min_entry_score,
            metrics=regime_metrics
        )
        
        logger.info(
            f"🧠 NAMIE [{symbol}]: Regime={regime.value} ({regime_metrics['confidence']:.0%}), "
            f"Trend={trend_strength}/100, Chop={chop_score:.0f}, "
            f"Strategy={optimal_strategy.value}, Trade={'✅ YES' if should_trade else '❌ NO'}"
        )
        
        return signal
    
    def _classify_regime(self, df: pd.DataFrame, indicators: Dict) -> Tuple[MarketRegime, Dict]:
        """
        Multi-layered regime classification using both deterministic and probabilistic methods
        
        Returns:
            Tuple of (regime, metrics_dict)
        """
        # Deterministic regime detection
        regime_det, metrics_det = self.regime_detector.detect_regime(df, indicators)
        
        # Bayesian probabilistic regime detection
        regime_bayes = self.bayesian_detector.detect_regime(df, indicators)
        
        # Combine both approaches for highest confidence
        # If both agree, use that regime with high confidence
        # If they disagree, use Bayesian probability distribution
        if regime_det == regime_bayes.regime:
            final_regime = regime_det
            confidence = min(0.95, metrics_det['confidence'] * 1.2)  # Boost confidence when both agree
        else:
            # Use Bayesian probabilities to decide
            final_regime = regime_bayes.regime
            confidence = regime_bayes.confidence
        
        metrics = {
            'regime': final_regime.value,
            'confidence': confidence,
            'adx': metrics_det['adx'],
            'atr': metrics_det['atr'],
            'atr_pct': metrics_det['atr_pct'],
            'price_volatility': metrics_det['price_volatility'],
            'probabilities': regime_bayes.probabilities,
            'transition_detected': regime_bayes.transition_detected,
        }
        
        return final_regime, metrics
    
    def _analyze_volatility(self, df: pd.DataFrame, indicators: Dict) -> Tuple[VolatilityRegime, str, float]:
        """
        Analyze volatility regime and clustering patterns
        
        Returns:
            Tuple of (volatility_regime, cluster_pattern, atr_percentage)
        """
        atr = float(indicators.get('atr', pd.Series([0])).iloc[-1])
        current_price = float(df['close'].iloc[-1])
        atr_pct = (atr / current_price) if current_price > 0 else 0
        
        # Calculate ATR average for regime classification
        atr_series = indicators.get('atr', pd.Series([atr]))
        if len(atr_series) >= 20:
            atr_avg = atr_series.iloc[-20:].mean()
        else:
            atr_avg = atr
        
        # Classify volatility regime
        if atr_avg > 0:
            atr_ratio = atr / atr_avg
        else:
            atr_ratio = 1.0
        
        if atr_ratio > 2.5:
            vol_regime = VolatilityRegime.EXTREME_HIGH
        elif atr_ratio > 1.5:
            vol_regime = VolatilityRegime.HIGH
        elif atr_ratio > 1.2:
            vol_regime = VolatilityRegime.NORMAL
        elif atr_ratio > 0.8:
            vol_regime = VolatilityRegime.NORMAL
        elif atr_ratio > 0.5:
            vol_regime = VolatilityRegime.LOW
        else:
            vol_regime = VolatilityRegime.EXTREME_LOW
        
        # Detect volatility clustering pattern
        if len(atr_series) >= 10:
            recent_atr = atr_series.iloc[-5:].mean()
            older_atr = atr_series.iloc[-10:-5].mean()
            
            if recent_atr > older_atr * 1.3:
                cluster = "expanding"  # Volatility increasing
            elif recent_atr < older_atr * 0.7:
                cluster = "contracting"  # Volatility decreasing
            else:
                cluster = "stable"  # Volatility stable
        else:
            cluster = "stable"
        
        return vol_regime, cluster, atr_pct
    
    def _score_trend_strength(self, df: pd.DataFrame, indicators: Dict) -> Tuple[int, TrendStrength, str]:
        """
        Calculate comprehensive trend strength score (0-100)
        
        Returns:
            Tuple of (score, category, direction)
        """
        score_components = []
        
        # Component 1: ADX (0-25 points)
        adx = float(indicators.get('adx', pd.Series([0])).iloc[-1])
        if adx >= 50:
            adx_score = 25
        elif adx >= 40:
            adx_score = 22
        elif adx >= 30:
            adx_score = 18
        elif adx >= 25:
            adx_score = 15
        elif adx >= 20:
            adx_score = 10
        else:
            adx_score = max(0, adx / 2)
        score_components.append(adx_score)
        
        # Component 2: EMA Alignment (0-25 points)
        ema9 = float(indicators.get('ema9', pd.Series([0])).iloc[-1])
        ema21 = float(indicators.get('ema21', pd.Series([0])).iloc[-1])
        ema50 = float(indicators.get('ema50', pd.Series([0])).iloc[-1])
        
        if ema9 > ema21 > ema50:  # Perfect uptrend alignment
            ema_score = 25
            direction = "up"
        elif ema9 < ema21 < ema50:  # Perfect downtrend alignment
            ema_score = 25
            direction = "down"
        elif ema9 > ema21 or ema21 > ema50:  # Partial alignment
            ema_score = 15
            direction = "up" if ema9 > ema50 else "neutral"
        elif ema9 < ema21 or ema21 < ema50:  # Partial alignment
            ema_score = 15
            direction = "down" if ema9 < ema50 else "neutral"
        else:
            ema_score = 5
            direction = "neutral"
        score_components.append(ema_score)
        
        # Component 3: MACD Strength (0-20 points)
        macd_hist = indicators.get('macd_histogram', pd.Series([0]))
        if len(macd_hist) >= 2:
            current_hist = float(macd_hist.iloc[-1])
            prev_hist = float(macd_hist.iloc[-2])
            
            # Score based on histogram magnitude and momentum
            hist_magnitude = abs(current_hist)
            hist_momentum = 1 if (current_hist > prev_hist and current_hist > 0) or \
                              (current_hist < prev_hist and current_hist < 0) else 0.5
            
            macd_score = min(20, hist_magnitude * 100 * hist_momentum)
        else:
            macd_score = 0
        score_components.append(macd_score)
        
        # Component 4: Price Momentum (0-15 points)
        if len(df) >= 10:
            current_price = float(df['close'].iloc[-1])
            price_10_ago = float(df['close'].iloc[-10])
            momentum_pct = abs((current_price - price_10_ago) / price_10_ago) if price_10_ago > 0 else 0
            
            # Convert to score (0-15 based on 0-5% momentum)
            momentum_score = min(15, momentum_pct * 300)
        else:
            momentum_score = 0
        score_components.append(momentum_score)
        
        # Component 5: Volume Confirmation (0-15 points)
        if 'volume' in df.columns and len(df) >= 5:
            current_vol = float(df['volume'].iloc[-1])
            avg_vol = df['volume'].iloc[-5:].mean()
            
            if current_vol > avg_vol * 1.5:
                vol_score = 15
            elif current_vol > avg_vol:
                vol_score = 10
            else:
                vol_score = 5
        else:
            vol_score = 5
        score_components.append(vol_score)
        
        # Calculate total score (0-100)
        total_score = int(sum(score_components))
        total_score = min(100, max(0, total_score))
        
        # Categorize strength
        if total_score >= 80:
            category = TrendStrength.VERY_STRONG
        elif total_score >= 60:
            category = TrendStrength.STRONG
        elif total_score >= 40:
            category = TrendStrength.MODERATE
        elif total_score >= 20:
            category = TrendStrength.WEAK
        else:
            category = TrendStrength.VERY_WEAK
        
        logger.debug(
            f"Trend Strength: {total_score}/100 ({category.value}) - "
            f"ADX:{adx_score:.0f}, EMA:{ema_score:.0f}, MACD:{macd_score:.0f}, "
            f"Momentum:{momentum_score:.0f}, Volume:{vol_score:.0f}"
        )
        
        return total_score, category, direction
    
    def _detect_chop(self, df: pd.DataFrame, indicators: Dict, regime: MarketRegime) -> Tuple[ChopCondition, float]:
        """
        Detect choppy/sideways market conditions (chop score 0-100)
        
        High chop = dangerous for trend-following strategies
        
        Returns:
            Tuple of (chop_condition, chop_score)
        """
        chop_factors = []
        
        # Factor 1: ADX (low ADX = high chop)
        adx = float(indicators.get('adx', pd.Series([0])).iloc[-1])
        if adx < 15:
            adx_chop = 30
        elif adx < 20:
            adx_chop = 20
        elif adx < 25:
            adx_chop = 10
        else:
            adx_chop = 0
        chop_factors.append(adx_chop)
        
        # Factor 2: Price Range Compression
        if len(df) >= 20:
            recent_high = df['high'].iloc[-20:].max()
            recent_low = df['low'].iloc[-20:].min()
            current_price = float(df['close'].iloc[-1])
            
            price_range_pct = ((recent_high - recent_low) / current_price) if current_price > 0 else 0
            
            # Narrow range indicates chop
            if price_range_pct < 0.02:  # Less than 2% range
                range_chop = 25
            elif price_range_pct < 0.05:  # Less than 5% range
                range_chop = 15
            else:
                range_chop = 0
            chop_factors.append(range_chop)
        else:
            chop_factors.append(0)
        
        # Factor 3: EMA Convergence (EMAs close together = chop)
        ema9 = float(indicators.get('ema9', pd.Series([0])).iloc[-1])
        ema21 = float(indicators.get('ema21', pd.Series([0])).iloc[-1])
        ema50 = float(indicators.get('ema50', pd.Series([0])).iloc[-1])
        
        if ema21 > 0:
            ema_spread_9_21 = abs(ema9 - ema21) / ema21
            ema_spread_21_50 = abs(ema21 - ema50) / ema21
            
            avg_spread = (ema_spread_9_21 + ema_spread_21_50) / 2
            
            if avg_spread < 0.005:  # Less than 0.5% spread
                ema_chop = 25
            elif avg_spread < 0.01:  # Less than 1% spread
                ema_chop = 15
            else:
                ema_chop = 0
            chop_factors.append(ema_chop)
        else:
            chop_factors.append(0)
        
        # Factor 4: MACD Weakness
        macd_hist = indicators.get('macd_histogram', pd.Series([0]))
        if len(macd_hist) >= 5:
            recent_hist = macd_hist.iloc[-5:]
            hist_std = recent_hist.std()
            hist_mean = abs(recent_hist.mean())
            
            # Low MACD activity = chop
            if hist_std < 0.01 and hist_mean < 0.01:
                macd_chop = 20
            else:
                macd_chop = 0
            chop_factors.append(macd_chop)
        else:
            chop_factors.append(0)
        
        # Calculate total chop score
        chop_score = min(100, sum(chop_factors))
        
        # Categorize chop condition
        if chop_score >= 75:
            condition = ChopCondition.EXTREME
        elif chop_score >= 60:
            condition = ChopCondition.SEVERE
        elif chop_score >= 40:
            condition = ChopCondition.MODERATE
        elif chop_score >= 20:
            condition = ChopCondition.MILD
        else:
            condition = ChopCondition.NONE
        
        logger.debug(f"Chop Detection: {chop_score:.0f}/100 ({condition.value})")
        
        return condition, chop_score
    
    def _select_strategy(
        self,
        regime: MarketRegime,
        volatility_regime: VolatilityRegime,
        trend_strength: int,
        chop_score: float
    ) -> Tuple[TradingStrategy, float, List[Tuple[TradingStrategy, float]]]:
        """
        Select optimal trading strategy based on market conditions
        
        Returns:
            Tuple of (strategy, confidence, alternatives_list)
        """
        # Use regime-based strategy selector
        selection_result = self.strategy_selector.select_strategy(
            regime=regime,
            trend_strength=trend_strength,
            volatility=volatility_regime,
            chop_score=chop_score
        )
        
        strategy = selection_result.selected_strategy
        confidence = 0.8  # Base confidence
        
        # Adjust confidence based on conditions
        if chop_score > 60:
            confidence *= 0.6  # Low confidence in choppy markets
        elif trend_strength > 70:
            confidence *= 1.2  # High confidence in strong trends
        
        confidence = min(1.0, max(0.0, confidence))
        
        alternatives = selection_result.alternative_strategies or []
        
        return strategy, confidence, alternatives
    
    def _make_trading_decision(
        self,
        regime: MarketRegime,
        regime_confidence: float,
        trend_strength: int,
        chop_score: float,
        strategy: TradingStrategy
    ) -> Tuple[bool, str, float, int]:
        """
        Make final trading decision based on all factors
        
        Returns:
            Tuple of (should_trade, reason, position_multiplier, min_entry_score)
        """
        reasons = []
        should_trade = True
        
        # Check 1: Regime confidence
        if regime_confidence < self.min_regime_confidence:
            should_trade = False
            reasons.append(f"Low regime confidence ({regime_confidence:.0%} < {self.min_regime_confidence:.0%})")
        
        # Check 2: Trend strength
        if trend_strength < self.min_trend_strength:
            should_trade = False
            reasons.append(f"Weak trend ({trend_strength} < {self.min_trend_strength})")
        
        # Check 3: Chop detection
        if chop_score > self.max_chop_score:
            should_trade = False
            reasons.append(f"Excessive chop ({chop_score:.0f} > {self.max_chop_score})")
        
        # Check 4: Strategy selection
        if strategy == TradingStrategy.NONE:
            should_trade = False
            reasons.append("No suitable strategy for current conditions")
        
        # Calculate position size multiplier based on regime
        regime_params = self.regime_detector.get_regime_parameters(regime)
        position_multiplier = regime_params['position_size_multiplier']
        
        # Adjust multiplier based on chop score
        if chop_score > 40:
            chop_penalty = 1.0 - ((chop_score - 40) / 100)  # Reduce up to 60% in extreme chop
            position_multiplier *= max(0.4, chop_penalty)
        
        # Get minimum entry score required
        min_entry_score = regime_params['min_entry_score']
        
        # Build reason
        if should_trade:
            reason = f"✅ Trade approved - {regime.value} regime, {strategy.value} strategy"
        else:
            reason = "❌ Trade blocked - " + "; ".join(reasons)
        
        return should_trade, reason, position_multiplier, min_entry_score
    
    def update_performance(self, regime: MarketRegime, win: bool, pnl: float):
        """
        Update performance tracking for regime-based learning
        
        Args:
            regime: Market regime when trade was executed
            win: Whether trade was profitable
            pnl: Profit/loss amount
        """
        if regime in self.performance_by_regime:
            stats = self.performance_by_regime[regime]
            if win:
                stats['wins'] += 1
            else:
                stats['losses'] += 1
            stats['total_pnl'] += pnl
            
            total_trades = stats['wins'] + stats['losses']
            win_rate = stats['wins'] / total_trades if total_trades > 0 else 0
            
            logger.info(
                f"📊 Performance Update [{regime.value}]: "
                f"W/L={stats['wins']}/{stats['losses']} ({win_rate:.1%}), "
                f"PnL=${stats['total_pnl']:.2f}"
            )
    
    def get_performance_summary(self) -> Dict:
        """
        Get comprehensive performance summary by regime
        
        Returns:
            Dictionary with performance metrics per regime
        """
        summary = {}
        for regime, stats in self.performance_by_regime.items():
            total_trades = stats['wins'] + stats['losses']
            win_rate = stats['wins'] / total_trades if total_trades > 0 else 0
            avg_pnl = stats['total_pnl'] / total_trades if total_trades > 0 else 0
            
            summary[regime.value] = {
                'trades': total_trades,
                'wins': stats['wins'],
                'losses': stats['losses'],
                'win_rate': win_rate,
                'total_pnl': stats['total_pnl'],
                'avg_pnl_per_trade': avg_pnl,
            }
        
        return summary


# Global instance for easy access
_namie_instance = None


def get_namie_engine(config: Dict = None) -> NAMIECore:
    """
    Get or create global NAMIE engine instance
    
    Args:
        config: Optional configuration dictionary
    
    Returns:
        NAMIECore instance
    """
    global _namie_instance
    if _namie_instance is None:
        _namie_instance = NAMIECore(config)
    return _namie_instance
