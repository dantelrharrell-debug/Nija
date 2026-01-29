"""
NIJA Regime-Based Strategy Selection System
===========================================

Automatically selects and runs optimal trading strategy based on detected
market regime:

- TREND Strategy: For strong trending markets (high ADX)
- MEAN-REVERSION Strategy: For choppy/ranging markets (low ADX, bounded price action)
- BREAKOUT Strategy: For volatility expansion and consolidation breakouts

Instead of "one strategy fits all", this system adapts to market conditions
in real-time for maximum edge.

Author: NIJA Trading Systems
Version: 1.0
Date: January 29, 2026
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger("nija.regime_strategy")


class TradingStrategy(Enum):
    """Trading strategy types"""
    TREND = "trend"  # Trend following
    MEAN_REVERSION = "mean_reversion"  # Range-bound mean reversion
    BREAKOUT = "breakout"  # Volatility expansion / consolidation breakouts
    MOMENTUM = "momentum"  # Momentum continuation
    NONE = "none"  # No strategy (high uncertainty)


class MarketRegimeType(Enum):
    """Market regime classifications"""
    STRONG_TREND = "strong_trend"  # ADX > 30, clear direction
    WEAK_TREND = "weak_trend"  # ADX 20-30
    RANGING = "ranging"  # ADX < 20, choppy
    CONSOLIDATION = "consolidation"  # Low volatility, tight range
    VOLATILITY_EXPANSION = "volatility_expansion"  # Breaking out of consolidation
    HIGH_VOLATILITY = "high_volatility"  # High ATR, chaotic


@dataclass
class RegimeDetection:
    """Market regime detection result"""
    regime: MarketRegimeType
    optimal_strategy: TradingStrategy
    confidence: float  # 0-1
    metrics: Dict[str, float]
    reasoning: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class StrategyParameters:
    """Parameters for a trading strategy"""
    strategy: TradingStrategy
    entry_conditions: Dict
    exit_conditions: Dict
    position_sizing: Dict
    risk_management: Dict
    description: str


@dataclass
class StrategySelectionResult:
    """Result of strategy selection"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    regime_detection: RegimeDetection = None
    selected_strategy: TradingStrategy = TradingStrategy.NONE
    strategy_params: Optional[StrategyParameters] = None
    alternative_strategies: List[Tuple[TradingStrategy, float]] = field(default_factory=list)
    summary: str = ""


class RegimeBasedStrategySelector:
    """
    Regime-based strategy selection system

    Detects market regime and automatically selects the optimal
    trading strategy for current conditions.
    """

    def __init__(self, config: Dict = None):
        """
        Initialize Regime-Based Strategy Selector

        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}

        # Regime detection thresholds
        self.thresholds = {
            'strong_trend_adx': self.config.get('strong_trend_adx', 30),
            'weak_trend_adx': self.config.get('weak_trend_adx', 20),
            'high_volatility_atr_pct': self.config.get('high_volatility_atr_pct', 4.0),
            'low_volatility_atr_pct': self.config.get('low_volatility_atr_pct', 1.0),
            'consolidation_bb_width_pct': self.config.get('consolidation_bb_width_pct', 2.0),
        }

        # Strategy to regime mapping
        self.regime_strategy_map = {
            MarketRegimeType.STRONG_TREND: TradingStrategy.TREND,
            MarketRegimeType.WEAK_TREND: TradingStrategy.MOMENTUM,
            MarketRegimeType.RANGING: TradingStrategy.MEAN_REVERSION,
            MarketRegimeType.CONSOLIDATION: TradingStrategy.BREAKOUT,
            MarketRegimeType.VOLATILITY_EXPANSION: TradingStrategy.BREAKOUT,
            MarketRegimeType.HIGH_VOLATILITY: TradingStrategy.MEAN_REVERSION,  # Counter-trend in chaos
        }

        # Strategy parameters templates
        self.strategy_templates = self._initialize_strategy_templates()

        # Historical regime tracking
        self.regime_history: List[RegimeDetection] = []
        self.current_regime: Optional[MarketRegimeType] = None
        self.current_strategy: Optional[TradingStrategy] = None

        logger.info("=" * 70)
        logger.info("🎯 Regime-Based Strategy Selector Initialized")
        logger.info("=" * 70)
        logger.info("Regime Detection Thresholds:")
        for key, value in self.thresholds.items():
            logger.info(f"  {key}: {value}")
        logger.info("")
        logger.info("Regime → Strategy Mapping:")
        for regime, strategy in self.regime_strategy_map.items():
            logger.info(f"  {regime.value}: {strategy.value.upper()}")
        logger.info("=" * 70)

    def _initialize_strategy_templates(self) -> Dict[TradingStrategy, StrategyParameters]:
        """Initialize strategy parameter templates"""
        return {
            TradingStrategy.TREND: StrategyParameters(
                strategy=TradingStrategy.TREND,
                entry_conditions={
                    'min_adx': 25,
                    'rsi_range': (30, 70),
                    'pullback_to_ema': True,
                    'trend_confirmation': True,
                },
                exit_conditions={
                    'trailing_stop_atr': 2.0,
                    'profit_target_rr': 3.0,
                    'time_stop_hours': 24,
                },
                position_sizing={
                    'base_pct': 0.05,
                    'adr_scaling': True,
                    'trend_strength_multiplier': True,
                },
                risk_management={
                    'stop_loss_atr': 1.5,
                    'max_drawdown_exit': 0.02,
                },
                description="Trend following strategy for strong directional markets"
            ),

            TradingStrategy.MEAN_REVERSION: StrategyParameters(
                strategy=TradingStrategy.MEAN_REVERSION,
                entry_conditions={
                    'max_adx': 20,
                    'rsi_oversold': 30,
                    'rsi_overbought': 70,
                    'bollinger_band_touch': True,
                    'volume_confirmation': False,  # Less important in ranging markets
                },
                exit_conditions={
                    'mean_reversion_target': 'vwap',
                    'profit_target_pct': 0.01,  # Quick 1% targets
                    'time_stop_hours': 4,  # Quick in/out
                },
                position_sizing={
                    'base_pct': 0.03,
                    'smaller_positions': True,  # More positions, smaller size
                },
                risk_management={
                    'stop_loss_atr': 1.0,  # Tight stops
                    'max_loss_per_trade': 0.005,  # 0.5% max loss
                },
                description="Mean reversion strategy for range-bound markets"
            ),

            TradingStrategy.BREAKOUT: StrategyParameters(
                strategy=TradingStrategy.BREAKOUT,
                entry_conditions={
                    'consolidation_detected': True,
                    'volume_surge': 1.5,  # 50% above average
                    'range_breakout': True,
                    'bollinger_squeeze': True,
                },
                exit_conditions={
                    'volatility_trail': True,
                    'profit_target_rr': 2.5,
                    'breakdown_exit': True,  # Exit if breaks back into range
                },
                position_sizing={
                    'base_pct': 0.06,
                    'aggressive_on_confirmation': True,
                },
                risk_management={
                    'stop_loss_below_consolidation': True,
                    'max_risk_pct': 0.015,  # 1.5% max risk
                },
                description="Breakout strategy for volatility expansion from consolidation"
            ),

            TradingStrategy.MOMENTUM: StrategyParameters(
                strategy=TradingStrategy.MOMENTUM,
                entry_conditions={
                    'min_adx': 20,
                    'rsi_momentum': (50, 80),  # Trending but not overbought
                    'macd_histogram_rising': True,
                    'price_above_ema': True,
                },
                exit_conditions={
                    'momentum_reversal': True,
                    'trailing_stop_pct': 0.03,
                    'profit_target_rr': 2.0,
                },
                position_sizing={
                    'base_pct': 0.05,
                    'momentum_strength_multiplier': True,
                },
                risk_management={
                    'stop_loss_atr': 1.2,
                    'partial_profit_taking': True,
                },
                description="Momentum continuation strategy for moderate trends"
            ),
        }

    def detect_regime(
        self,
        df: pd.DataFrame,
        indicators: Dict
    ) -> RegimeDetection:
        """
        Detect current market regime based on multiple factors

        Args:
            df: Price DataFrame with OHLCV data
            indicators: Dictionary of calculated indicators

        Returns:
            RegimeDetection with regime and optimal strategy
        """
        # Extract key metrics
        current_price = float(df['close'].iloc[-1])

        # ADX (trend strength)
        adx = float(indicators.get('adx', pd.Series([0])).iloc[-1])

        # ATR (volatility)
        atr = float(indicators.get('atr', pd.Series([0])).iloc[-1])
        atr_pct = (atr / current_price * 100) if current_price > 0 else 0

        # Bollinger Bands (range)
        bb_upper = float(indicators.get('bb_upper', pd.Series([current_price])).iloc[-1])
        bb_lower = float(indicators.get('bb_lower', pd.Series([current_price])).iloc[-1])
        bb_width_pct = ((bb_upper - bb_lower) / current_price * 100) if current_price > 0 else 0

        # Price range (last 20 periods)
        if len(df) >= 20:
            price_range = df['close'].iloc[-20:].max() - df['close'].iloc[-20:].min()
            price_range_pct = (price_range / df['close'].iloc[-20:].mean() * 100)
        else:
            price_range_pct = 0

        # RSI (momentum)
        rsi = float(indicators.get('rsi', pd.Series([50])).iloc[-1])

        # Volume
        if 'volume' in df.columns and len(df) >= 10:
            current_volume = float(df['volume'].iloc[-1])
            avg_volume = float(df['volume'].iloc[-10:].mean())
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0
        else:
            volume_ratio = 1.0

        # Collect metrics
        metrics = {
            'adx': adx,
            'atr_pct': atr_pct,
            'bb_width_pct': bb_width_pct,
            'price_range_pct': price_range_pct,
            'rsi': rsi,
            'volume_ratio': volume_ratio,
        }

        # Regime classification logic
        regime, confidence, reasoning = self._classify_regime(metrics)

        # Get optimal strategy for regime
        optimal_strategy = self.regime_strategy_map.get(regime, TradingStrategy.NONE)

        detection = RegimeDetection(
            regime=regime,
            optimal_strategy=optimal_strategy,
            confidence=confidence,
            metrics=metrics,
            reasoning=reasoning
        )

        # Update tracking
        self.regime_history.append(detection)
        self.current_regime = regime
        self.current_strategy = optimal_strategy

        # Keep only last 100 detections
        if len(self.regime_history) > 100:
            self.regime_history = self.regime_history[-100:]

        logger.info("=" * 70)
        logger.info("🎯 REGIME DETECTION")
        logger.info("=" * 70)
        logger.info(f"Detected Regime: {regime.value.upper()}")
        logger.info(f"Optimal Strategy: {optimal_strategy.value.upper()}")
        logger.info(f"Confidence: {confidence:.2%}")
        logger.info("")
        logger.info("Market Metrics:")
        for metric, value in metrics.items():
            logger.info(f"  {metric}: {value:.2f}")
        logger.info("")
        logger.info(f"Reasoning: {reasoning}")
        logger.info("=" * 70)

        return detection

    def _classify_regime(self, metrics: Dict[str, float]) -> Tuple[MarketRegimeType, float, str]:
        """
        Classify market regime based on metrics

        Returns:
            Tuple of (regime, confidence, reasoning)
        """
        adx = metrics['adx']
        atr_pct = metrics['atr_pct']
        bb_width_pct = metrics['bb_width_pct']
        price_range_pct = metrics['price_range_pct']
        volume_ratio = metrics['volume_ratio']

        # Strong Trend: High ADX, reasonable volatility
        if adx >= self.thresholds['strong_trend_adx']:
            confidence = min(1.0, (adx - 30) / 20 + 0.7)  # 0.7-1.0
            reasoning = f"Strong trend (ADX={adx:.1f} > {self.thresholds['strong_trend_adx']})"
            return MarketRegimeType.STRONG_TREND, confidence, reasoning

        # Volatility Expansion: Breaking out with high volume
        if (atr_pct > self.thresholds['high_volatility_atr_pct'] and
            volume_ratio > 1.5 and
            bb_width_pct > 3.0):
            confidence = 0.75
            reasoning = f"Volatility expansion (ATR={atr_pct:.2f}%, Volume={volume_ratio:.2f}x)"
            return MarketRegimeType.VOLATILITY_EXPANSION, confidence, reasoning

        # High Volatility: Chaotic, high ATR
        if atr_pct > self.thresholds['high_volatility_atr_pct']:
            confidence = 0.70
            reasoning = f"High volatility (ATR={atr_pct:.2f}% > {self.thresholds['high_volatility_atr_pct']}%)"
            return MarketRegimeType.HIGH_VOLATILITY, confidence, reasoning

        # Consolidation: Low volatility, tight range
        if (atr_pct < self.thresholds['low_volatility_atr_pct'] and
            bb_width_pct < self.thresholds['consolidation_bb_width_pct']):
            confidence = 0.75
            reasoning = f"Consolidation (ATR={atr_pct:.2f}%, BB Width={bb_width_pct:.2f}%)"
            return MarketRegimeType.CONSOLIDATION, confidence, reasoning

        # Weak Trend: Moderate ADX
        if adx >= self.thresholds['weak_trend_adx']:
            confidence = 0.65
            reasoning = f"Weak trend (ADX={adx:.1f}, {self.thresholds['weak_trend_adx']}-{self.thresholds['strong_trend_adx']})"
            return MarketRegimeType.WEAK_TREND, confidence, reasoning

        # Ranging: Low ADX, moderate volatility
        confidence = 0.60
        reasoning = f"Ranging market (ADX={adx:.1f} < {self.thresholds['weak_trend_adx']})"
        return MarketRegimeType.RANGING, confidence, reasoning

    def select_strategy(
        self,
        df: pd.DataFrame,
        indicators: Dict,
        force_detection: bool = False
    ) -> StrategySelectionResult:
        """
        Detect regime and select optimal strategy

        Args:
            df: Price DataFrame
            indicators: Indicator dictionary
            force_detection: Force new regime detection

        Returns:
            StrategySelectionResult with selected strategy and parameters
        """
        # Detect regime
        detection = self.detect_regime(df, indicators)

        # Get selected strategy
        selected_strategy = detection.optimal_strategy

        # Get strategy parameters
        strategy_params = self.strategy_templates.get(selected_strategy)

        # Calculate alternative strategies (with confidence scores)
        alternatives = []
        for strategy in TradingStrategy:
            if strategy != selected_strategy and strategy != TradingStrategy.NONE:
                # Simple scoring: 100% for primary, lower for others
                score = 0.3  # Base alternative score
                alternatives.append((strategy, score))

        # Sort alternatives by score
        alternatives.sort(key=lambda x: x[1], reverse=True)

        # Generate summary
        summary = self._generate_summary(detection, selected_strategy, strategy_params)

        result = StrategySelectionResult(
            regime_detection=detection,
            selected_strategy=selected_strategy,
            strategy_params=strategy_params,
            alternative_strategies=alternatives,
            summary=summary
        )

        logger.info(summary)

        return result

    def _generate_summary(
        self,
        detection: RegimeDetection,
        strategy: TradingStrategy,
        params: Optional[StrategyParameters]
    ) -> str:
        """Generate human-readable summary"""
        lines = [
            "\n🎯 STRATEGY SELECTION SUMMARY",
            "=" * 70,
            f"Market Regime: {detection.regime.value.upper()}",
            f"Selected Strategy: {strategy.value.upper()}",
            f"Confidence: {detection.confidence:.2%}",
            "",
            f"Reasoning: {detection.reasoning}",
        ]

        if params:
            lines.append("")
            lines.append(f"Strategy Description:")
            lines.append(f"  {params.description}")
            lines.append("")
            lines.append("Entry Conditions:")
            for key, value in list(params.entry_conditions.items())[:3]:
                lines.append(f"  {key}: {value}")
            lines.append("")
            lines.append("Risk Management:")
            for key, value in params.risk_management.items():
                lines.append(f"  {key}: {value}")

        return "\n".join(lines)

    def get_regime_stats(self) -> Dict:
        """Get statistics about regime history"""
        if not self.regime_history:
            return {}

        regime_counts = {}
        strategy_counts = {}

        for detection in self.regime_history:
            regime = detection.regime.value
            strategy = detection.optimal_strategy.value

            regime_counts[regime] = regime_counts.get(regime, 0) + 1
            strategy_counts[strategy] = strategy_counts.get(strategy, 0) + 1

        total = len(self.regime_history)

        return {
            'total_detections': total,
            'current_regime': self.current_regime.value if self.current_regime else 'none',
            'current_strategy': self.current_strategy.value if self.current_strategy else 'none',
            'regime_distribution': {k: (v/total*100) for k, v in regime_counts.items()},
            'strategy_distribution': {k: (v/total*100) for k, v in strategy_counts.items()},
        }


def create_regime_strategy_selector(config: Dict = None) -> RegimeBasedStrategySelector:
    """
    Factory function to create RegimeBasedStrategySelector instance

    Args:
        config: Optional configuration

    Returns:
        RegimeBasedStrategySelector instance
    """
    return RegimeBasedStrategySelector(config)


# Example usage
if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

    # Create selector
    selector = create_regime_strategy_selector()

    # Mock data - trending market
    dates = pd.date_range('2024-01-01', periods=100, freq='1H')
    trending_df = pd.DataFrame({
        'timestamp': dates,
        'close': np.cumsum(np.random.randn(100) * 0.5) + 100,
        'high': np.cumsum(np.random.randn(100) * 0.5) + 102,
        'low': np.cumsum(np.random.randn(100) * 0.5) + 98,
        'volume': np.random.randint(1000, 5000, 100),
    })

    trending_indicators = {
        'adx': pd.Series([35.0] * 100),  # Strong trend
        'atr': pd.Series([1.5] * 100),
        'bb_upper': pd.Series([102.0] * 100),
        'bb_lower': pd.Series([98.0] * 100),
        'rsi': pd.Series([60.0] * 100),
    }

    print("\n" + "=" * 70)
    print("SCENARIO 1: Trending Market")
    print("=" * 70)

    result1 = selector.select_strategy(trending_df, trending_indicators)
    print(result1.summary)

    # Mock data - ranging market
    ranging_indicators = {
        'adx': pd.Series([15.0] * 100),  # Low ADX
        'atr': pd.Series([0.8] * 100),
        'bb_upper': pd.Series([101.0] * 100),
        'bb_lower': pd.Series([99.0] * 100),
        'rsi': pd.Series([50.0] * 100),
    }

    print("\n" + "=" * 70)
    print("SCENARIO 2: Ranging Market")
    print("=" * 70)

    result2 = selector.select_strategy(trending_df, ranging_indicators)
    print(result2.summary)

    # Get stats
    stats = selector.get_regime_stats()
    print("\nRegime Statistics:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
