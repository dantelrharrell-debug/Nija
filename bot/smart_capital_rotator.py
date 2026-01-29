"""
NIJA Smart Capital Rotation System
===================================

Dynamically rotates capital between different strategy types based on
real-time market regime detection:

1. SCALP Strategy - Fast in/out trades in ranging markets
2. MOMENTUM Strategy - Ride strong directional moves
3. TREND Strategy - Follow sustained trends with larger positions

The system:
- Detects current market regime (trending/ranging/volatile)
- Classifies optimal strategy type for conditions
- Allocates capital proportionally to strategy effectiveness
- Rebalances dynamically as market conditions change

Author: NIJA Trading Systems
Version: 2.0 - Elite Profit Engine
Date: January 29, 2026
"""

import logging
from typing import Dict, List, Tuple
from enum import Enum
from dataclasses import dataclass
import pandas as pd

logger = logging.getLogger("nija.capital_rotation")


class StrategyType(Enum):
    """Trading strategy classifications"""
    SCALP = "scalp"  # Quick trades, small profits, high frequency
    MOMENTUM = "momentum"  # Ride strong moves, medium duration
    TREND = "trend"  # Follow sustained trends, longer duration


class MarketCondition(Enum):
    """Market condition types"""
    STRONG_TREND = "strong_trend"  # ADX > 30, clear direction
    WEAK_TREND = "weak_trend"  # ADX 20-30, moderate direction
    RANGING = "ranging"  # ADX < 20, consolidation
    VOLATILE_CHOPPY = "volatile_choppy"  # High volatility, no clear direction
    LOW_VOLATILITY = "low_volatility"  # Low ATR, tight range


@dataclass
class StrategyAllocation:
    """Capital allocation for a strategy"""
    strategy: StrategyType
    allocation_pct: float  # Percentage of total capital (0.0 - 1.0)
    confidence: float  # Confidence in this allocation (0.0 - 1.0)
    reason: str  # Explanation for allocation


class SmartCapitalRotator:
    """
    Manages dynamic capital rotation between strategy types
    based on real-time market conditions
    """

    def __init__(self, total_capital: float, config: Dict = None):
        """
        Initialize Smart Capital Rotator

        Args:
            total_capital: Total available capital for allocation
            config: Optional configuration dictionary
        """
        self.total_capital = total_capital
        self.config = config or {}

        # Allocation constraints
        self.min_allocation = self.config.get('min_strategy_allocation', 0.10)  # 10% minimum per strategy
        self.max_allocation = self.config.get('max_strategy_allocation', 0.70)  # 70% maximum per strategy

        # Current allocations (initialize equally)
        self.current_allocations = {
            StrategyType.SCALP: 0.33,
            StrategyType.MOMENTUM: 0.33,
            StrategyType.TREND: 0.34,
        }

        # Strategy performance tracking
        self.strategy_performance = {
            StrategyType.SCALP: {'wins': 0, 'losses': 0, 'profit': 0.0},
            StrategyType.MOMENTUM: {'wins': 0, 'losses': 0, 'profit': 0.0},
            StrategyType.TREND: {'wins': 0, 'losses': 0, 'profit': 0.0},
        }

        # Market condition to optimal strategy mapping
        self.optimal_strategies = {
            MarketCondition.STRONG_TREND: [
                (StrategyType.TREND, 0.60),  # 60% to trend following
                (StrategyType.MOMENTUM, 0.30),  # 30% to momentum
                (StrategyType.SCALP, 0.10),  # 10% to scalping
            ],
            MarketCondition.WEAK_TREND: [
                (StrategyType.MOMENTUM, 0.50),  # 50% to momentum
                (StrategyType.TREND, 0.30),  # 30% to trend
                (StrategyType.SCALP, 0.20),  # 20% to scalping
            ],
            MarketCondition.RANGING: [
                (StrategyType.SCALP, 0.60),  # 60% to scalping
                (StrategyType.MOMENTUM, 0.25),  # 25% to momentum
                (StrategyType.TREND, 0.15),  # 15% to trend
            ],
            MarketCondition.VOLATILE_CHOPPY: [
                (StrategyType.SCALP, 0.50),  # 50% to scalping (quick in/out)
                (StrategyType.MOMENTUM, 0.30),  # 30% to momentum
                (StrategyType.TREND, 0.20),  # 20% to trend
            ],
            MarketCondition.LOW_VOLATILITY: [
                (StrategyType.SCALP, 0.45),  # 45% to scalping
                (StrategyType.TREND, 0.35),  # 35% to trend
                (StrategyType.MOMENTUM, 0.20),  # 20% to momentum
            ],
        }

        logger.info("=" * 70)
        logger.info("🔄 Smart Capital Rotation System Initialized")
        logger.info("=" * 70)
        logger.info(f"Total Capital: ${total_capital:,.2f}")
        logger.info(f"Initial Allocation: Equal (33% each strategy)")
        logger.info("=" * 70)

    def detect_market_condition(self, df: pd.DataFrame, indicators: Dict) -> Tuple[MarketCondition, Dict]:
        """
        Detect current market condition

        Args:
            df: Price DataFrame with OHLCV data
            indicators: Dictionary of calculated indicators (ADX, ATR, etc.)

        Returns:
            Tuple of (MarketCondition, metrics_dict)
        """
        # Extract key indicators
        adx = float(indicators.get('adx', pd.Series([0])).iloc[-1])
        atr = float(indicators.get('atr', pd.Series([0])).iloc[-1])
        current_price = float(df['close'].iloc[-1])

        # Calculate ATR as percentage of price (normalized volatility)
        atr_pct = (atr / current_price) * 100 if current_price > 0 else 0

        # Calculate price range (last 20 periods)
        if len(df) >= 20:
            price_range = df['close'].iloc[-20:].max() - df['close'].iloc[-20:].min()
            price_range_pct = (price_range / df['close'].iloc[-20:].mean()) * 100
        else:
            price_range_pct = 0

        # Classify market condition
        if adx >= 30:
            condition = MarketCondition.STRONG_TREND
        elif adx >= 20:
            condition = MarketCondition.WEAK_TREND
        elif adx < 20 and atr_pct < 2.0:
            condition = MarketCondition.LOW_VOLATILITY
        elif adx < 20 and atr_pct >= 3.0:
            condition = MarketCondition.VOLATILE_CHOPPY
        else:
            condition = MarketCondition.RANGING

        metrics = {
            'adx': adx,
            'atr': atr,
            'atr_pct': atr_pct,
            'price_range_pct': price_range_pct,
            'condition': condition.value,
        }

        logger.info(f"🔍 Market Condition Detected: {condition.value.upper()}")
        logger.info(f"   ADX: {adx:.1f}, ATR%: {atr_pct:.2f}%, Range%: {price_range_pct:.2f}%")

        return condition, metrics

    def calculate_optimal_allocation(
        self,
        market_condition: MarketCondition,
        performance_weight: float = 0.3
    ) -> Dict[StrategyType, StrategyAllocation]:
        """
        Calculate optimal capital allocation based on market conditions
        and strategy performance

        Args:
            market_condition: Current market condition
            performance_weight: Weight given to historical performance (0.0-1.0)

        Returns:
            Dictionary mapping StrategyType to StrategyAllocation
        """
        # Get base allocations for current market condition
        base_allocations = dict(self.optimal_strategies[market_condition])

        # Calculate performance scores (0.0 - 1.0)
        performance_scores = self._calculate_performance_scores()

        # Blend base allocations with performance scores
        blended_allocations = {}
        total_allocation = 0.0

        for strategy in StrategyType:
            # Get base allocation
            base_alloc = base_allocations.get(strategy, 0.33)

            # Get performance score
            perf_score = performance_scores.get(strategy, 0.5)

            # Blend: (1-weight)*base + weight*performance
            blended = (1 - performance_weight) * base_alloc + performance_weight * perf_score

            # Apply min/max constraints
            blended = max(self.min_allocation, min(self.max_allocation, blended))

            blended_allocations[strategy] = blended
            total_allocation += blended

        # Normalize to sum to 1.0
        if total_allocation > 0:
            for strategy in blended_allocations:
                blended_allocations[strategy] /= total_allocation

        # Create StrategyAllocation objects
        allocations = {}
        for strategy, allocation_pct in blended_allocations.items():
            allocations[strategy] = StrategyAllocation(
                strategy=strategy,
                allocation_pct=allocation_pct,
                confidence=self._calculate_confidence(strategy, market_condition),
                reason=self._get_allocation_reason(strategy, market_condition, allocation_pct)
            )

        return allocations

    def _calculate_performance_scores(self) -> Dict[StrategyType, float]:
        """
        Calculate performance scores for each strategy (0.0 - 1.0)

        Returns:
            Dictionary mapping StrategyType to performance score
        """
        scores = {}

        for strategy, perf in self.strategy_performance.items():
            total_trades = perf['wins'] + perf['losses']

            if total_trades == 0:
                # No history, use neutral score
                scores[strategy] = 0.5
            else:
                # Win rate component (0.0 - 0.6)
                win_rate = perf['wins'] / total_trades
                win_rate_score = min(0.6, win_rate * 0.6)

                # Profit component (0.0 - 0.4)
                # Normalize profit to 0-0.4 range
                max_profit = max(self.strategy_performance[s]['profit'] for s in StrategyType)
                if max_profit > 0:
                    profit_score = (perf['profit'] / max_profit) * 0.4
                else:
                    profit_score = 0.2  # Neutral

                scores[strategy] = win_rate_score + profit_score

        return scores

    def _calculate_confidence(self, strategy: StrategyType, condition: MarketCondition) -> float:
        """
        Calculate confidence in strategy allocation

        Args:
            strategy: Strategy type
            condition: Market condition

        Returns:
            Confidence score (0.0 - 1.0)
        """
        # Base confidence from market condition mapping
        optimal_strategies = self.optimal_strategies[condition]
        base_confidence = 0.5

        for opt_strategy, allocation in optimal_strategies:
            if opt_strategy == strategy:
                base_confidence = allocation  # Higher allocation = higher confidence
                break

        # Adjust based on strategy performance
        perf = self.strategy_performance[strategy]
        total_trades = perf['wins'] + perf['losses']

        if total_trades >= 10:
            win_rate = perf['wins'] / total_trades
            # Boost confidence if high win rate
            if win_rate >= 0.65:
                base_confidence = min(1.0, base_confidence * 1.2)
            elif win_rate <= 0.45:
                base_confidence = max(0.2, base_confidence * 0.8)

        return min(1.0, max(0.0, base_confidence))

    def _get_allocation_reason(
        self,
        strategy: StrategyType,
        condition: MarketCondition,
        allocation_pct: float
    ) -> str:
        """
        Generate human-readable reason for allocation

        Args:
            strategy: Strategy type
            condition: Market condition
            allocation_pct: Allocation percentage

        Returns:
            Reason string
        """
        reasons = {
            (StrategyType.TREND, MarketCondition.STRONG_TREND):
                "Strong trend detected - ideal for trend following",
            (StrategyType.MOMENTUM, MarketCondition.WEAK_TREND):
                "Moderate trend - momentum strategies work well",
            (StrategyType.SCALP, MarketCondition.RANGING):
                "Ranging market - scalping strategy optimal",
            (StrategyType.SCALP, MarketCondition.VOLATILE_CHOPPY):
                "Volatile choppy market - quick scalps safer",
            (StrategyType.SCALP, MarketCondition.LOW_VOLATILITY):
                "Low volatility - scalping small moves",
        }

        # Try to get specific reason
        reason = reasons.get((strategy, condition),
                           f"{strategy.value.capitalize()} strategy for {condition.value} conditions")

        # Add allocation percentage
        return f"{reason} ({allocation_pct*100:.0f}% allocation)"

    def rotate_capital(
        self,
        df: pd.DataFrame,
        indicators: Dict,
        smooth_transition: bool = True
    ) -> Dict[StrategyType, float]:
        """
        Execute capital rotation based on current market conditions

        Args:
            df: Price DataFrame
            indicators: Dictionary of indicators
            smooth_transition: If True, gradually transition allocations

        Returns:
            Dictionary mapping StrategyType to capital amount
        """
        # Detect market condition
        condition, metrics = self.detect_market_condition(df, indicators)

        # Calculate optimal allocation
        allocations = self.calculate_optimal_allocation(condition, performance_weight=0.3)

        # Prepare new allocations
        new_allocations = {}
        for strategy, alloc in allocations.items():
            new_allocations[strategy] = alloc.allocation_pct

        # Smooth transition (gradual shift vs immediate)
        if smooth_transition:
            transition_speed = 0.3  # 30% move toward target each rotation
            for strategy in StrategyType:
                current = self.current_allocations[strategy]
                target = new_allocations[strategy]
                # Move 30% toward target
                new_allocations[strategy] = current + (target - current) * transition_speed

        # Update current allocations
        self.current_allocations = new_allocations

        # Calculate actual capital amounts
        capital_amounts = {}
        for strategy, pct in new_allocations.items():
            capital_amounts[strategy] = self.total_capital * pct

        # Log rotation
        logger.info("=" * 70)
        logger.info("💰 Capital Rotation Executed")
        logger.info("=" * 70)
        logger.info(f"Market Condition: {condition.value.upper()}")
        for strategy in StrategyType:
            alloc = allocations[strategy]
            capital = capital_amounts[strategy]
            logger.info(f"{strategy.value.upper():10s}: ${capital:>10,.2f} ({alloc.allocation_pct*100:>5.1f}%) - {alloc.reason}")
        logger.info("=" * 70)

        return capital_amounts

    def record_trade_result(
        self,
        strategy: StrategyType,
        profit: float,
        is_win: bool
    ):
        """
        Record trade result for performance tracking

        Args:
            strategy: Strategy that generated the trade
            profit: Net profit/loss from trade
            is_win: True if trade was profitable
        """
        perf = self.strategy_performance[strategy]

        if is_win:
            perf['wins'] += 1
        else:
            perf['losses'] += 1

        perf['profit'] += profit

        total_trades = perf['wins'] + perf['losses']
        win_rate = (perf['wins'] / total_trades * 100) if total_trades > 0 else 0

        logger.info(f"📊 {strategy.value.upper()} Performance Updated:")
        logger.info(f"   Trades: {total_trades}, Win Rate: {win_rate:.1f}%, Profit: ${perf['profit']:.2f}")

    def get_strategy_capital(self, strategy: StrategyType) -> float:
        """
        Get current capital allocation for a strategy

        Args:
            strategy: Strategy type

        Returns:
            Capital amount in USD
        """
        return self.total_capital * self.current_allocations[strategy]

    def update_total_capital(self, new_capital: float):
        """
        Update total capital (e.g., after profit/loss)

        Args:
            new_capital: New total capital amount
        """
        old_capital = self.total_capital
        self.total_capital = new_capital
        logger.info(f"💰 Total Capital Updated: ${old_capital:,.2f} → ${new_capital:,.2f}")

    def get_rotation_report(self, df: pd.DataFrame, indicators: Dict) -> str:
        """
        Generate detailed capital rotation report

        Args:
            df: Price DataFrame
            indicators: Dictionary of indicators

        Returns:
            Formatted report string
        """
        condition, metrics = self.detect_market_condition(df, indicators)
        allocations = self.calculate_optimal_allocation(condition)

        report = [
            "\n" + "=" * 90,
            "SMART CAPITAL ROTATION REPORT",
            "=" * 90,
            f"Total Capital: ${self.total_capital:,.2f}",
            f"Market Condition: {condition.value.upper()}",
            "",
            "📊 Market Metrics:",
            f"  ADX: {metrics['adx']:.1f}",
            f"  ATR%: {metrics['atr_pct']:.2f}%",
            f"  Price Range%: {metrics['price_range_pct']:.2f}%",
            "",
            "💰 Current Capital Allocation:",
            "-" * 90,
        ]

        for strategy in StrategyType:
            current_pct = self.current_allocations[strategy]
            current_capital = self.total_capital * current_pct
            alloc = allocations[strategy]
            perf = self.strategy_performance[strategy]
            total_trades = perf['wins'] + perf['losses']
            win_rate = (perf['wins'] / total_trades * 100) if total_trades > 0 else 0

            report.append(f"  {strategy.value.upper():10s}: ${current_capital:>12,.2f} ({current_pct*100:>5.1f}%) "
                         f"| Target: {alloc.allocation_pct*100:>5.1f}% | Confidence: {alloc.confidence:.2f}")
            report.append(f"               Performance: {total_trades} trades, {win_rate:.1f}% WR, ${perf['profit']:+,.2f} profit")
            report.append(f"               Reason: {alloc.reason}")
            report.append("")

        report.append("=" * 90)

        return "\n".join(report)


def get_smart_capital_rotator(total_capital: float, config: Dict = None) -> SmartCapitalRotator:
    """
    Factory function to create SmartCapitalRotator instance

    Args:
        total_capital: Total capital for rotation
        config: Optional configuration

    Returns:
        SmartCapitalRotator instance
    """
    return SmartCapitalRotator(total_capital, config)


# Example usage
if __name__ == "__main__":
    import logging
    import numpy as np

    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

    # Create sample data
    dates = pd.date_range('2024-01-01', periods=100, freq='1H')
    df = pd.DataFrame({
        'timestamp': dates,
        'close': np.random.randn(100).cumsum() + 100,
        'high': np.random.randn(100).cumsum() + 102,
        'low': np.random.randn(100).cumsum() + 98,
    })

    # Mock indicators
    indicators = {
        'adx': pd.Series([32.5] * 100),  # Strong trend
        'atr': pd.Series([1.5] * 100),
    }

    # Create rotator
    rotator = get_smart_capital_rotator(total_capital=10000.0)

    # Execute rotation
    capital_amounts = rotator.rotate_capital(df, indicators)

    # Simulate some trades
    rotator.record_trade_result(StrategyType.TREND, profit=150.0, is_win=True)
    rotator.record_trade_result(StrategyType.MOMENTUM, profit=-50.0, is_win=False)
    rotator.record_trade_result(StrategyType.SCALP, profit=25.0, is_win=True)

    # Print report
    print(rotator.get_rotation_report(df, indicators))
