"""
NIJA Adaptive Leverage System
==============================

Dynamic leverage calculator that adjusts leverage based on:
1. Market volatility (ATR-based)
2. Win rate and recent performance
3. Drawdown protection
4. Risk-adjusted returns

Automatically REDUCES leverage when:
- Volatility increases (protect capital)
- Win rate declines (defensive mode)
- Drawdown approaches limits

Automatically INCREASES leverage when:
- Volatility is low and stable
- Win rate is high (>65%)
- Profit momentum is strong

SAFETY FIRST: Maximum leverage caps and circuit breakers included.

Author: NIJA Trading Systems
Version: 2.0 - Elite Profit Engine
Date: January 29, 2026
"""

import logging
from typing import Dict, Optional
from dataclasses import dataclass
from enum import Enum
import pandas as pd

logger = logging.getLogger("nija.adaptive_leverage")


class LeverageMode(Enum):
    """Leverage operating modes"""
    CONSERVATIVE = "conservative"  # 1x-2x leverage
    MODERATE = "moderate"  # 1x-3x leverage
    AGGRESSIVE = "aggressive"  # 1x-5x leverage
    DISABLED = "disabled"  # No leverage (1x only)


@dataclass
class LeverageState:
    """Current leverage state"""
    current_leverage: float
    max_allowed: float
    min_allowed: float
    confidence: float
    reason: str
    risk_score: float  # 0.0 (low risk) to 1.0 (high risk)


class AdaptiveLeverageSystem:
    """
    Dynamically adjusts trading leverage based on market conditions
    and performance metrics

    IMPORTANT SAFETY FEATURES:
    - Hard maximum leverage cap (default 5x)
    - Automatic leverage reduction during drawdowns
    - Performance-based adjustment
    - Volatility-aware scaling
    - Circuit breaker for losses
    """

    def __init__(self, config: Dict = None):
        """
        Initialize Adaptive Leverage System

        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}

        # Leverage mode
        mode_str = self.config.get('leverage_mode', 'conservative')
        self.mode = LeverageMode(mode_str.lower())

        # Leverage limits based on mode
        leverage_limits = {
            LeverageMode.DISABLED: (1.0, 1.0),  # No leverage
            LeverageMode.CONSERVATIVE: (1.0, 2.0),  # 1x-2x
            LeverageMode.MODERATE: (1.0, 3.0),  # 1x-3x
            LeverageMode.AGGRESSIVE: (1.0, 5.0),  # 1x-5x
        }

        self.min_leverage, self.max_leverage = leverage_limits[self.mode]

        # Hard safety cap (never exceed this regardless of mode)
        self.absolute_max_leverage = self.config.get('absolute_max_leverage', 5.0)
        self.max_leverage = min(self.max_leverage, self.absolute_max_leverage)

        # Performance tracking
        self.total_trades = 0
        self.winning_trades = 0
        self.total_profit = 0.0
        self.peak_balance = 0.0
        self.current_balance = 0.0

        # Risk thresholds
        self.max_drawdown_pct = self.config.get('max_drawdown_pct', 0.15)  # 15% max drawdown
        self.min_win_rate = self.config.get('min_win_rate', 0.50)  # 50% minimum win rate

        # Volatility thresholds
        self.high_volatility_threshold = 0.03  # 3% ATR/price = high volatility
        self.low_volatility_threshold = 0.015  # 1.5% ATR/price = low volatility

        # Current leverage
        self.current_leverage = 1.0  # Always start at 1x (no leverage)

        logger.info("=" * 70)
        logger.info("⚡ Adaptive Leverage System Initialized")
        logger.info("=" * 70)
        logger.info(f"Mode: {self.mode.value.upper()}")
        logger.info(f"Leverage Range: {self.min_leverage:.1f}x - {self.max_leverage:.1f}x")
        logger.info(f"Starting Leverage: {self.current_leverage:.1f}x")
        logger.info(f"Safety Cap: {self.absolute_max_leverage:.1f}x")
        logger.info("=" * 70)

    def calculate_adaptive_leverage(
        self,
        df: pd.DataFrame,
        indicators: Dict,
        base_capital: float,
        current_balance: float
    ) -> LeverageState:
        """
        Calculate optimal leverage based on current conditions

        Args:
            df: Price DataFrame
            indicators: Dictionary with indicators (ATR, etc.)
            base_capital: Original starting capital
            current_balance: Current account balance

        Returns:
            LeverageState with recommended leverage
        """
        # Update balance tracking
        self.current_balance = current_balance
        if current_balance > self.peak_balance:
            self.peak_balance = current_balance

        # If leverage is disabled, return 1x
        if self.mode == LeverageMode.DISABLED:
            return LeverageState(
                current_leverage=1.0,
                max_allowed=1.0,
                min_allowed=1.0,
                confidence=1.0,
                reason="Leverage disabled (safety mode)",
                risk_score=0.0
            )

        # Calculate component scores
        volatility_score = self._calculate_volatility_score(df, indicators)
        performance_score = self._calculate_performance_score(base_capital)
        risk_score = self._calculate_risk_score(base_capital)

        # Weighted combination (volatility is most important)
        combined_score = (
            volatility_score * 0.40 +  # 40% weight on volatility
            performance_score * 0.35 +  # 35% weight on performance
            (1.0 - risk_score) * 0.25  # 25% weight on low risk
        )

        # Map score to leverage (0.0 score = min leverage, 1.0 score = max leverage)
        leverage_range = self.max_leverage - self.min_leverage
        calculated_leverage = self.min_leverage + (combined_score * leverage_range)

        # Apply circuit breakers
        calculated_leverage = self._apply_circuit_breakers(
            calculated_leverage,
            risk_score,
            base_capital
        )

        # Ensure within bounds
        calculated_leverage = max(self.min_leverage, min(self.max_leverage, calculated_leverage))

        # Smooth transition (don't jump leverage too quickly)
        smoothed_leverage = self._smooth_leverage_transition(calculated_leverage)

        # Update current leverage
        self.current_leverage = smoothed_leverage

        # Calculate confidence
        confidence = self._calculate_confidence(combined_score, risk_score)

        # Generate reason
        reason = self._generate_leverage_reason(
            volatility_score,
            performance_score,
            risk_score
        )

        state = LeverageState(
            current_leverage=smoothed_leverage,
            max_allowed=self.max_leverage,
            min_allowed=self.min_leverage,
            confidence=confidence,
            reason=reason,
            risk_score=risk_score
        )

        logger.info(f"⚡ Adaptive Leverage: {smoothed_leverage:.2f}x")
        logger.info(f"   Volatility Score: {volatility_score:.2f}, Performance: {performance_score:.2f}, Risk: {risk_score:.2f}")
        logger.info(f"   Confidence: {confidence:.2f}, Reason: {reason}")

        return state

    def _calculate_volatility_score(self, df: pd.DataFrame, indicators: Dict) -> float:
        """
        Calculate volatility score (0.0 = high volatility, 1.0 = low volatility)

        Higher score = lower volatility = safe to use more leverage
        """
        atr_series = indicators.get('atr', pd.Series([0]))
        if len(atr_series) == 0:
            return 0.5  # Neutral

        current_atr = float(atr_series.iloc[-1])
        current_price = float(df['close'].iloc[-1])

        if current_price == 0:
            return 0.5

        # Calculate ATR as % of price
        atr_pct = current_atr / current_price

        # Score calculation (inverse relationship)
        if atr_pct >= self.high_volatility_threshold:
            # High volatility = low score = reduce leverage
            score = 0.2
        elif atr_pct <= self.low_volatility_threshold:
            # Low volatility = high score = can increase leverage
            score = 1.0
        else:
            # Linear interpolation between thresholds
            range_size = self.high_volatility_threshold - self.low_volatility_threshold
            position = (self.high_volatility_threshold - atr_pct) / range_size
            score = 0.2 + (position * 0.8)

        return max(0.0, min(1.0, score))

    def _calculate_performance_score(self, base_capital: float) -> float:
        """
        Calculate performance score based on win rate and profit

        Returns:
            Score from 0.0 (poor performance) to 1.0 (excellent performance)
        """
        if self.total_trades == 0:
            return 0.5  # No history, use neutral score

        # Win rate component (0.0 - 0.6)
        win_rate = self.winning_trades / self.total_trades

        if win_rate >= 0.70:  # 70%+ win rate = excellent
            win_rate_score = 1.0
        elif win_rate >= 0.60:  # 60-70% = good
            win_rate_score = 0.8
        elif win_rate >= 0.50:  # 50-60% = acceptable
            win_rate_score = 0.6
        elif win_rate >= 0.40:  # 40-50% = marginal
            win_rate_score = 0.4
        else:  # <40% = poor
            win_rate_score = 0.2

        # Profitability component (0.0 - 0.4)
        if base_capital > 0:
            roi = self.total_profit / base_capital

            if roi >= 0.20:  # 20%+ ROI = excellent
                profit_score = 1.0
            elif roi >= 0.10:  # 10-20% ROI = good
                profit_score = 0.7
            elif roi >= 0.05:  # 5-10% ROI = acceptable
                profit_score = 0.5
            elif roi > 0:  # Positive but small
                profit_score = 0.3
            else:  # Negative
                profit_score = 0.1
        else:
            profit_score = 0.5

        # Combine (weighted average)
        combined_score = (win_rate_score * 0.6) + (profit_score * 0.4)

        return max(0.0, min(1.0, combined_score))

    def _calculate_risk_score(self, base_capital: float) -> float:
        """
        Calculate risk score (0.0 = low risk, 1.0 = high risk)

        Higher risk score = reduce leverage
        """
        if base_capital == 0 or self.peak_balance == 0:
            return 0.5  # Neutral

        # Calculate current drawdown
        drawdown = (self.peak_balance - self.current_balance) / self.peak_balance
        drawdown = max(0.0, drawdown)  # No negative drawdowns

        # Risk score based on drawdown proximity to limit
        if drawdown >= self.max_drawdown_pct:
            # At or exceeding max drawdown = maximum risk
            risk_score = 1.0
        elif drawdown >= self.max_drawdown_pct * 0.75:
            # 75% of max drawdown = high risk
            risk_score = 0.8
        elif drawdown >= self.max_drawdown_pct * 0.50:
            # 50% of max drawdown = moderate risk
            risk_score = 0.6
        elif drawdown >= self.max_drawdown_pct * 0.25:
            # 25% of max drawdown = low-moderate risk
            risk_score = 0.4
        else:
            # Minimal drawdown = low risk
            risk_score = 0.2

        return max(0.0, min(1.0, risk_score))

    def _apply_circuit_breakers(
        self,
        leverage: float,
        risk_score: float,
        base_capital: float
    ) -> float:
        """
        Apply safety circuit breakers to reduce leverage in dangerous conditions

        Args:
            leverage: Calculated leverage
            risk_score: Current risk score
            base_capital: Original capital

        Returns:
            Adjusted leverage
        """
        # Circuit breaker 1: High risk = reduce to minimum leverage
        if risk_score >= 0.9:
            logger.warning("⚠️  CIRCUIT BREAKER: High risk detected, reducing to minimum leverage")
            return self.min_leverage

        # Circuit breaker 2: Approaching drawdown limit
        if self.peak_balance > 0:
            drawdown = (self.peak_balance - self.current_balance) / self.peak_balance
            if drawdown >= self.max_drawdown_pct * 0.90:  # 90% of max drawdown
                logger.warning(f"⚠️  CIRCUIT BREAKER: Near max drawdown ({drawdown*100:.1f}%), reducing leverage")
                leverage = min(leverage, self.min_leverage + 0.5)  # Cap at 1.5x max

        # Circuit breaker 3: Poor win rate
        if self.total_trades >= 10:  # Need minimum sample size
            win_rate = self.winning_trades / self.total_trades
            if win_rate < self.min_win_rate:
                logger.warning(f"⚠️  CIRCUIT BREAKER: Low win rate ({win_rate*100:.1f}%), capping leverage")
                leverage = min(leverage, self.min_leverage + 0.5)

        # Circuit breaker 4: Recent losing streak
        # (Would need trade history tracking - simplified here)

        return leverage

    def _smooth_leverage_transition(self, target_leverage: float) -> float:
        """
        Smooth leverage transitions to avoid sudden jumps

        Args:
            target_leverage: Target leverage

        Returns:
            Smoothed leverage
        """
        max_change_per_update = 0.25  # Maximum 0.25x change per update

        difference = target_leverage - self.current_leverage

        if abs(difference) <= max_change_per_update:
            return target_leverage
        elif difference > 0:
            # Increasing leverage gradually
            return self.current_leverage + max_change_per_update
        else:
            # Decreasing leverage (can be faster for safety)
            return self.current_leverage - max_change_per_update

    def _calculate_confidence(self, combined_score: float, risk_score: float) -> float:
        """
        Calculate confidence in leverage recommendation

        Args:
            combined_score: Combined performance/volatility score
            risk_score: Risk score

        Returns:
            Confidence (0.0 - 1.0)
        """
        # High combined score + low risk = high confidence
        confidence = combined_score * (1.0 - risk_score)

        # Boost confidence if we have enough trade history
        if self.total_trades >= 20:
            confidence = min(1.0, confidence * 1.1)
        elif self.total_trades < 5:
            # Low confidence without history
            confidence = confidence * 0.7

        return max(0.0, min(1.0, confidence))

    def _generate_leverage_reason(
        self,
        volatility_score: float,
        performance_score: float,
        risk_score: float
    ) -> str:
        """Generate human-readable reason for leverage decision"""
        reasons = []

        # Volatility reason
        if volatility_score >= 0.8:
            reasons.append("low volatility")
        elif volatility_score <= 0.4:
            reasons.append("high volatility")

        # Performance reason
        if performance_score >= 0.7:
            reasons.append("strong performance")
        elif performance_score <= 0.4:
            reasons.append("weak performance")

        # Risk reason
        if risk_score >= 0.7:
            reasons.append("high risk/drawdown")
        elif risk_score <= 0.3:
            reasons.append("low risk")

        if not reasons:
            return "Neutral market conditions"

        return ", ".join(reasons).capitalize()

    def record_trade_result(self, profit: float, is_win: bool):
        """
        Record trade result for performance tracking

        Args:
            profit: Net profit/loss from trade
            is_win: True if trade was profitable
        """
        self.total_trades += 1
        if is_win:
            self.winning_trades += 1
        self.total_profit += profit

        logger.info(f"📊 Trade Recorded: P/L=${profit:.2f}, Total Trades={self.total_trades}, "
                   f"Win Rate={(self.winning_trades/self.total_trades*100):.1f}%")

    def get_effective_position_size(
        self,
        base_position_size: float,
        leverage: Optional[float] = None
    ) -> float:
        """
        Calculate effective position size with leverage

        Args:
            base_position_size: Position size without leverage
            leverage: Optional leverage override (uses current if not provided)

        Returns:
            Effective position size with leverage applied
        """
        leverage = leverage or self.current_leverage
        return base_position_size * leverage

    def reset_performance_tracking(self):
        """Reset performance tracking (use with caution)"""
        self.total_trades = 0
        self.winning_trades = 0
        self.total_profit = 0.0
        self.peak_balance = self.current_balance
        logger.warning("⚠️  Performance tracking reset")


def get_adaptive_leverage_system(config: Dict = None) -> AdaptiveLeverageSystem:
    """
    Factory function to create AdaptiveLeverageSystem

    Args:
        config: Optional configuration

    Returns:
        AdaptiveLeverageSystem instance
    """
    return AdaptiveLeverageSystem(config)


# Example usage
if __name__ == "__main__":
    import logging
    import numpy as np

    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

    # Create sample data
    dates = pd.date_range('2024-01-01', periods=100, freq='1H')
    df = pd.DataFrame({
        'close': np.random.randn(100).cumsum() + 100,
        'high': np.random.randn(100).cumsum() + 102,
        'low': np.random.randn(100).cumsum() + 98,
    })

    # Mock indicators
    indicators = {
        'atr': pd.Series([1.5] * 100),  # 1.5 ATR
    }

    # Create leverage system
    config = {'leverage_mode': 'moderate'}
    leverage_system = get_adaptive_leverage_system(config)

    # Simulate some trades
    leverage_system.record_trade_result(profit=50.0, is_win=True)
    leverage_system.record_trade_result(profit=30.0, is_win=True)
    leverage_system.record_trade_result(profit=-20.0, is_win=False)

    # Calculate leverage
    state = leverage_system.calculate_adaptive_leverage(
        df=df,
        indicators=indicators,
        base_capital=10000.0,
        current_balance=10060.0
    )

    print(f"\n✅ Leverage State:")
    print(f"  Current Leverage: {state.current_leverage:.2f}x")
    print(f"  Range: {state.min_allowed:.1f}x - {state.max_allowed:.1f}x")
    print(f"  Confidence: {state.confidence:.2f}")
    print(f"  Risk Score: {state.risk_score:.2f}")
    print(f"  Reason: {state.reason}")

    # Test effective position size
    base_position = 500.0
    effective_position = leverage_system.get_effective_position_size(base_position)
    print(f"\n  Base Position: ${base_position:.2f}")
    print(f"  With Leverage ({state.current_leverage:.2f}x): ${effective_position:.2f}")
