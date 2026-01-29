"""
NIJA Dynamic Risk-On / Risk-Off Capital Allocator
=================================================

Dynamically shifts capital allocation based on market regime detection:
- RISK-ON: Favorable market conditions, increase exposure
- RISK-OFF: Defensive positioning, reduce exposure
- NEUTRAL: Balanced allocation

Features:
- Real-time market regime detection
- Multi-factor regime scoring
- Dynamic exposure adjustment
- Safe capital preservation in risk-off periods
- Aggressive deployment in risk-on periods

Author: NIJA Trading Systems
Version: 1.0
Date: January 29, 2026
"""

import logging
import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger("nija.risk_regime")


class MarketRegime(Enum):
    """Market regime classifications"""
    RISK_ON = "risk_on"  # Bullish, high risk appetite
    RISK_OFF = "risk_off"  # Defensive, low risk appetite
    NEUTRAL = "neutral"  # Balanced, moderate risk


@dataclass
class RegimeSignal:
    """Signal indicating market regime"""
    regime: MarketRegime
    confidence: float  # 0-1, how confident we are in this regime
    score: float  # Raw regime score (-100 to +100, negative=risk-off, positive=risk-on)
    factors: Dict[str, float]  # Individual factor contributions
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass
class CapitalAllocation:
    """Capital allocation recommendation based on regime"""
    regime: MarketRegime
    total_capital: float
    recommended_exposure_pct: float  # Percentage of capital to deploy (0-1)
    deployed_capital: float  # Amount to deploy
    reserve_capital: float  # Amount to keep in reserve
    position_sizing_multiplier: float  # Multiplier for position sizes (0.5-2.0)
    max_positions: int  # Maximum concurrent positions
    reasoning: str


@dataclass
class RiskRegimeResult:
    """Result of risk regime analysis"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    regime_signal: RegimeSignal = None
    allocation: CapitalAllocation = None
    historical_regimes: List[RegimeSignal] = field(default_factory=list)
    summary: str = ""


class RiskOnRiskOffAllocator:
    """
    Dynamic capital allocator based on risk-on/risk-off regime detection

    Automatically shifts capital allocation between aggressive (risk-on)
    and defensive (risk-off) based on multi-factor market analysis.
    """

    def __init__(self, config: Dict = None):
        """
        Initialize Risk-On/Risk-Off Allocator

        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}

        # Regime detection parameters
        self.regime_factors = {
            'trend_strength': self.config.get('trend_strength_weight', 0.25),  # ADX, trend quality
            'momentum': self.config.get('momentum_weight', 0.20),  # RSI, price momentum
            'volatility': self.config.get('volatility_weight', 0.20),  # ATR, volatility regime
            'volume': self.config.get('volume_weight', 0.15),  # Volume trends
            'market_breadth': self.config.get('market_breadth_weight', 0.20),  # How many assets trending
        }

        # Exposure levels for each regime
        self.exposure_levels = {
            MarketRegime.RISK_ON: {
                'exposure_pct': self.config.get('risk_on_exposure', 0.80),  # 80% deployed
                'position_multiplier': self.config.get('risk_on_multiplier', 1.5),  # 1.5x position sizes
                'max_positions': self.config.get('risk_on_max_positions', 15),
                'reserve_pct': 0.20,  # 20% reserve
            },
            MarketRegime.NEUTRAL: {
                'exposure_pct': self.config.get('neutral_exposure', 0.60),  # 60% deployed
                'position_multiplier': self.config.get('neutral_multiplier', 1.0),  # Normal position sizes
                'max_positions': self.config.get('neutral_max_positions', 10),
                'reserve_pct': 0.40,  # 40% reserve
            },
            MarketRegime.RISK_OFF: {
                'exposure_pct': self.config.get('risk_off_exposure', 0.30),  # 30% deployed
                'position_multiplier': self.config.get('risk_off_multiplier', 0.5),  # 0.5x position sizes
                'max_positions': self.config.get('risk_off_max_positions', 5),
                'reserve_pct': 0.70,  # 70% reserve
            },
        }

        # Regime transition thresholds
        self.risk_on_threshold = self.config.get('risk_on_threshold', 40)  # Score > 40 = risk-on
        self.risk_off_threshold = self.config.get('risk_off_threshold', -40)  # Score < -40 = risk-off
        self.min_regime_duration = self.config.get('min_regime_duration', 3)  # Minimum periods before changing

        # Historical regime tracking
        self.regime_history: List[RegimeSignal] = []
        self.current_regime: Optional[MarketRegime] = None
        self.regime_duration = 0  # How many periods in current regime

        logger.info("=" * 70)
        logger.info("⚡ Risk-On/Risk-Off Capital Allocator Initialized")
        logger.info("=" * 70)
        logger.info("Regime Detection Factors:")
        for factor, weight in self.regime_factors.items():
            logger.info(f"  {factor}: {weight*100:.0f}%")
        logger.info("")
        logger.info("Exposure Levels:")
        for regime, levels in self.exposure_levels.items():
            logger.info(f"  {regime.value.upper()}:")
            logger.info(f"    Exposure: {levels['exposure_pct']*100:.0f}%")
            logger.info(f"    Position Multiplier: {levels['position_multiplier']:.1f}x")
            logger.info(f"    Max Positions: {levels['max_positions']}")
        logger.info("=" * 70)

    def detect_regime(
        self,
        market_data: Dict[str, Dict],
        portfolio_metrics: Optional[Dict] = None
    ) -> RegimeSignal:
        """
        Detect current market regime based on multiple factors

        Args:
            market_data: Dictionary of symbol -> market metrics (adx, rsi, atr, volume, etc.)
            portfolio_metrics: Optional portfolio-level metrics

        Returns:
            RegimeSignal indicating detected regime
        """
        if not market_data:
            logger.warning("No market data provided for regime detection")
            return RegimeSignal(
                regime=MarketRegime.NEUTRAL,
                confidence=0.0,
                score=0.0,
                factors={}
            )

        # Calculate individual factor scores
        factor_scores = {}

        # Factor 1: Trend Strength (based on ADX)
        adx_values = [data.get('adx', 0) for data in market_data.values()]
        avg_adx = np.mean(adx_values) if adx_values else 0

        if avg_adx >= 35:
            factor_scores['trend_strength'] = 100  # Very strong trends
        elif avg_adx >= 25:
            factor_scores['trend_strength'] = 60  # Moderate trends
        elif avg_adx >= 20:
            factor_scores['trend_strength'] = 20  # Weak trends
        else:
            factor_scores['trend_strength'] = -50  # No trends (choppy)

        # Factor 2: Momentum (based on RSI)
        rsi_values = [data.get('rsi', 50) for data in market_data.values()]
        avg_rsi = np.mean(rsi_values) if rsi_values else 50

        # Count bullish vs bearish RSI
        bullish_count = sum(1 for rsi in rsi_values if rsi > 50)
        bearish_count = sum(1 for rsi in rsi_values if rsi <= 50)
        total_count = len(rsi_values)

        if bullish_count / total_count >= 0.7:
            factor_scores['momentum'] = 100  # Strong bullish momentum
        elif bullish_count / total_count >= 0.6:
            factor_scores['momentum'] = 50  # Moderate bullish
        elif bearish_count / total_count >= 0.7:
            factor_scores['momentum'] = -100  # Strong bearish momentum
        elif bearish_count / total_count >= 0.6:
            factor_scores['momentum'] = -50  # Moderate bearish
        else:
            factor_scores['momentum'] = 0  # Mixed/neutral

        # Factor 3: Volatility (based on ATR)
        atr_values = [data.get('atr', 0) for data in market_data.values()]
        prices = [data.get('price', 1) for data in market_data.values()]

        # Calculate ATR as % of price
        atr_pct_values = []
        for atr, price in zip(atr_values, prices):
            if price > 0:
                atr_pct_values.append((atr / price) * 100)

        avg_atr_pct = np.mean(atr_pct_values) if atr_pct_values else 0

        if avg_atr_pct >= 4.0:
            factor_scores['volatility'] = -80  # Very high volatility = risk-off
        elif avg_atr_pct >= 3.0:
            factor_scores['volatility'] = -40  # High volatility
        elif avg_atr_pct >= 2.0:
            factor_scores['volatility'] = 40  # Moderate volatility (good for trading)
        elif avg_atr_pct >= 1.0:
            factor_scores['volatility'] = 60  # Low-moderate volatility
        else:
            factor_scores['volatility'] = -20  # Very low volatility (choppy)

        # Factor 4: Volume (based on volume trends)
        volume_ratios = [data.get('volume_ratio', 1.0) for data in market_data.values()]
        avg_volume_ratio = np.mean(volume_ratios) if volume_ratios else 1.0

        if avg_volume_ratio >= 1.5:
            factor_scores['volume'] = 80  # High volume = strong conviction
        elif avg_volume_ratio >= 1.2:
            factor_scores['volume'] = 40  # Above average volume
        elif avg_volume_ratio >= 0.8:
            factor_scores['volume'] = 0  # Normal volume
        else:
            factor_scores['volume'] = -60  # Low volume = weak conviction

        # Factor 5: Market Breadth (how many assets are trending up)
        trending_up = sum(1 for data in market_data.values() if data.get('trend_direction', 0) > 0)
        trending_down = sum(1 for data in market_data.values() if data.get('trend_direction', 0) < 0)
        total_assets = len(market_data)

        if trending_up / total_assets >= 0.7:
            factor_scores['market_breadth'] = 100  # Broad rally
        elif trending_up / total_assets >= 0.6:
            factor_scores['market_breadth'] = 50  # Moderate breadth
        elif trending_down / total_assets >= 0.7:
            factor_scores['market_breadth'] = -100  # Broad decline
        elif trending_down / total_assets >= 0.6:
            factor_scores['market_breadth'] = -50  # Moderate decline
        else:
            factor_scores['market_breadth'] = 0  # Mixed market

        # Calculate weighted total score
        total_score = sum(
            factor_scores.get(factor, 0) * self.regime_factors.get(factor, 0)
            for factor in self.regime_factors
        )

        # Determine regime based on score
        if total_score >= self.risk_on_threshold:
            regime = MarketRegime.RISK_ON
            confidence = min(1.0, (total_score - self.risk_on_threshold) / 60)
        elif total_score <= self.risk_off_threshold:
            regime = MarketRegime.RISK_OFF
            confidence = min(1.0, abs(total_score - self.risk_off_threshold) / 60)
        else:
            regime = MarketRegime.NEUTRAL
            confidence = 0.6  # Moderate confidence in neutral

        # Apply regime persistence (avoid rapid switching)
        if self.current_regime is not None and regime != self.current_regime:
            if self.regime_duration < self.min_regime_duration:
                logger.info(
                    f"Regime change detected ({self.current_regime.value} → {regime.value}) "
                    f"but duration too short ({self.regime_duration} < {self.min_regime_duration}), "
                    f"maintaining current regime"
                )
                regime = self.current_regime
                confidence *= 0.7  # Reduce confidence when maintaining

        signal = RegimeSignal(
            regime=regime,
            confidence=confidence,
            score=total_score,
            factors=factor_scores
        )

        # Update tracking
        self.regime_history.append(signal)
        if self.current_regime == regime:
            self.regime_duration += 1
        else:
            self.current_regime = regime
            self.regime_duration = 1

        # Keep only last 100 regime signals
        if len(self.regime_history) > 100:
            self.regime_history = self.regime_history[-100:]

        logger.info("=" * 70)
        logger.info("⚡ Market Regime Detection")
        logger.info("=" * 70)
        logger.info(f"Regime: {regime.value.upper()}")
        logger.info(f"Confidence: {confidence:.2f}")
        logger.info(f"Score: {total_score:+.1f}")
        logger.info(f"Duration: {self.regime_duration} periods")
        logger.info("")
        logger.info("Factor Contributions:")
        for factor, score in factor_scores.items():
            weight = self.regime_factors.get(factor, 0)
            weighted_score = score * weight
            logger.info(f"  {factor:20s}: {score:+6.1f} (weight: {weight:.2f}) = {weighted_score:+6.1f}")
        logger.info("=" * 70)

        return signal

    def calculate_allocation(
        self,
        regime_signal: RegimeSignal,
        total_capital: float
    ) -> CapitalAllocation:
        """
        Calculate capital allocation based on detected regime

        Args:
            regime_signal: Detected market regime
            total_capital: Total available capital

        Returns:
            CapitalAllocation with deployment recommendations
        """
        regime = regime_signal.regime
        levels = self.exposure_levels[regime]

        # Calculate deployment amounts
        exposure_pct = levels['exposure_pct']
        deployed_capital = total_capital * exposure_pct
        reserve_capital = total_capital * levels['reserve_pct']

        # Generate reasoning
        reasoning_map = {
            MarketRegime.RISK_ON: (
                f"RISK-ON regime detected (score: {regime_signal.score:+.1f}, confidence: {regime_signal.confidence:.2f}). "
                f"Markets showing strong trends and positive momentum. "
                f"Deploying {exposure_pct*100:.0f}% of capital with {levels['position_multiplier']:.1f}x position sizing. "
                f"Maximum {levels['max_positions']} concurrent positions."
            ),
            MarketRegime.NEUTRAL: (
                f"NEUTRAL regime detected (score: {regime_signal.score:+.1f}, confidence: {regime_signal.confidence:.2f}). "
                f"Markets showing mixed signals. "
                f"Deploying {exposure_pct*100:.0f}% of capital with normal position sizing. "
                f"Maximum {levels['max_positions']} concurrent positions."
            ),
            MarketRegime.RISK_OFF: (
                f"RISK-OFF regime detected (score: {regime_signal.score:+.1f}, confidence: {regime_signal.confidence:.2f}). "
                f"Markets showing weakness or high volatility. "
                f"Deploying only {exposure_pct*100:.0f}% of capital with {levels['position_multiplier']:.1f}x position sizing. "
                f"Maximum {levels['max_positions']} concurrent positions. "
                f"Preserving {levels['reserve_pct']*100:.0f}% in reserve."
            ),
        }

        allocation = CapitalAllocation(
            regime=regime,
            total_capital=total_capital,
            recommended_exposure_pct=exposure_pct,
            deployed_capital=deployed_capital,
            reserve_capital=reserve_capital,
            position_sizing_multiplier=levels['position_multiplier'],
            max_positions=levels['max_positions'],
            reasoning=reasoning_map[regime]
        )

        logger.info("💰 Capital Allocation:")
        logger.info(f"  Total Capital: ${total_capital:,.2f}")
        logger.info(f"  Deployed: ${deployed_capital:,.2f} ({exposure_pct*100:.0f}%)")
        logger.info(f"  Reserve: ${reserve_capital:,.2f} ({levels['reserve_pct']*100:.0f}%)")
        logger.info(f"  Position Sizing: {levels['position_multiplier']:.1f}x")
        logger.info(f"  Max Positions: {levels['max_positions']}")

        return allocation

    def analyze_and_allocate(
        self,
        market_data: Dict[str, Dict],
        total_capital: float,
        portfolio_metrics: Optional[Dict] = None
    ) -> RiskRegimeResult:
        """
        Complete analysis: detect regime and calculate allocation

        Args:
            market_data: Market metrics for multiple symbols
            total_capital: Total available capital
            portfolio_metrics: Optional portfolio metrics

        Returns:
            RiskRegimeResult with regime and allocation
        """
        # Detect regime
        regime_signal = self.detect_regime(market_data, portfolio_metrics)

        # Calculate allocation
        allocation = self.calculate_allocation(regime_signal, total_capital)

        # Generate summary
        summary = self._generate_summary(regime_signal, allocation)

        return RiskRegimeResult(
            regime_signal=regime_signal,
            allocation=allocation,
            historical_regimes=self.regime_history.copy(),
            summary=summary
        )

    def _generate_summary(
        self,
        regime_signal: RegimeSignal,
        allocation: CapitalAllocation
    ) -> str:
        """Generate human-readable summary"""
        lines = [
            "\n⚡ RISK REGIME ANALYSIS SUMMARY",
            "=" * 70,
            f"Market Regime: {regime_signal.regime.value.upper()}",
            f"Confidence: {regime_signal.confidence:.2%}",
            f"Regime Score: {regime_signal.score:+.1f}",
            f"Duration: {self.regime_duration} periods",
            "",
            "💰 Capital Allocation:",
            f"  Total Capital: ${allocation.total_capital:,.2f}",
            f"  Deployed: ${allocation.deployed_capital:,.2f} ({allocation.recommended_exposure_pct*100:.0f}%)",
            f"  Reserve: ${allocation.reserve_capital:,.2f}",
            f"  Position Sizing: {allocation.position_sizing_multiplier:.1f}x normal",
            f"  Max Positions: {allocation.max_positions}",
            "",
            "📊 Factor Analysis:",
        ]

        # Show top positive and negative factors
        sorted_factors = sorted(
            regime_signal.factors.items(),
            key=lambda x: x[1],
            reverse=True
        )

        lines.append("  Positive Factors:")
        positive_factors = [(f, s) for f, s in sorted_factors if s > 0][:3]
        if positive_factors:
            for factor, score in positive_factors:
                lines.append(f"    {factor}: {score:+.1f}")
        else:
            lines.append("    None")

        lines.append("  Negative Factors:")
        negative_factors = [(f, s) for f, s in sorted_factors if s < 0][:3]
        if negative_factors:
            for factor, score in negative_factors:
                lines.append(f"    {factor}: {score:+.1f}")
        else:
            lines.append("    None")

        lines.append("")
        lines.append(f"Strategy: {allocation.reasoning}")

        return "\n".join(lines)

    def get_regime_history(self, lookback: int = 20) -> List[RegimeSignal]:
        """Get recent regime history"""
        return self.regime_history[-lookback:] if lookback > 0 else self.regime_history.copy()

    def get_regime_stats(self) -> Dict:
        """Get statistics about regime changes"""
        if not self.regime_history:
            return {}

        regime_counts = {
            MarketRegime.RISK_ON: 0,
            MarketRegime.NEUTRAL: 0,
            MarketRegime.RISK_OFF: 0,
        }

        for signal in self.regime_history:
            regime_counts[signal.regime] += 1

        total = len(self.regime_history)

        return {
            'total_periods': total,
            'current_regime': self.current_regime.value if self.current_regime else 'unknown',
            'regime_duration': self.regime_duration,
            'risk_on_pct': (regime_counts[MarketRegime.RISK_ON] / total * 100) if total > 0 else 0,
            'neutral_pct': (regime_counts[MarketRegime.NEUTRAL] / total * 100) if total > 0 else 0,
            'risk_off_pct': (regime_counts[MarketRegime.RISK_OFF] / total * 100) if total > 0 else 0,
        }


def create_risk_regime_allocator(config: Dict = None) -> RiskOnRiskOffAllocator:
    """
    Factory function to create RiskOnRiskOffAllocator instance

    Args:
        config: Optional configuration

    Returns:
        RiskOnRiskOffAllocator instance
    """
    return RiskOnRiskOffAllocator(config)


# Example usage
if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

    # Create allocator
    allocator = create_risk_regime_allocator()

    # Mock market data (risk-on scenario)
    market_data = {
        'BTC-USD': {
            'adx': 35,
            'rsi': 65,
            'atr': 1200,
            'price': 42000,
            'volume_ratio': 1.4,
            'trend_direction': 1,  # Up
        },
        'ETH-USD': {
            'adx': 30,
            'rsi': 60,
            'atr': 80,
            'price': 2200,
            'volume_ratio': 1.3,
            'trend_direction': 1,  # Up
        },
        'SOL-USD': {
            'adx': 28,
            'rsi': 58,
            'atr': 4,
            'price': 105,
            'volume_ratio': 1.2,
            'trend_direction': 1,  # Up
        },
    }

    # Analyze and get allocation
    result = allocator.analyze_and_allocate(
        market_data=market_data,
        total_capital=100000
    )

    print(result.summary)

    # Get regime stats
    stats = allocator.get_regime_stats()
    print("\nRegime Statistics:")
    for key, value in stats.items():
        print(f"  {key}: {value}")
