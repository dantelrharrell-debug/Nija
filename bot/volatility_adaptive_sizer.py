"""
NIJA Volatility-Adaptive Position Sizing
=========================================

Dynamic position sizing based on:
1. ATR (Average True Range) - volatility measurement
2. Volatility clusters - periods of high/low volatility
3. Session liquidity - trading hours and volume patterns

The system automatically scales position sizes:
- REDUCE size during high volatility (protect capital)
- INCREASE size during low volatility (capitalize on stability)
- ADJUST for liquidity conditions (avoid slippage)

Author: NIJA Trading Systems
Version: 2.0 - Elite Profit Engine
Date: January 29, 2026
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple
from datetime import datetime, time
from enum import Enum
import logging

logger = logging.getLogger("nija.volatility_sizer")


class VolatilityRegime(Enum):
    """Volatility regime classifications"""
    EXTREME_HIGH = "extreme_high"  # ATR > 2.5x average
    HIGH = "high"  # ATR > 1.5x average
    NORMAL = "normal"  # ATR within 0.8x - 1.2x average
    LOW = "low"  # ATR < 0.8x average
    EXTREME_LOW = "extreme_low"  # ATR < 0.5x average


class SessionType(Enum):
    """Trading session classifications"""
    ASIA = "asia"  # Low liquidity, wider spreads
    LONDON = "london"  # High liquidity
    NY = "ny"  # Highest liquidity
    OVERLAP = "overlap"  # London-NY overlap (peak liquidity)
    OFF_HOURS = "off_hours"  # Weekend/off-hours


class VolatilityAdaptiveSizer:
    """
    Dynamically adjust position sizes based on volatility and liquidity conditions
    """

    def __init__(self, config: Dict = None):
        """
        Initialize Volatility-Adaptive Position Sizer

        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}

        # Base position sizing parameters
        self.base_position_pct = self.config.get('base_position_pct', 0.05)  # 5% default
        self.min_position_pct = self.config.get('min_position_pct', 0.02)  # 2% minimum
        self.max_position_pct = self.config.get('max_position_pct', 0.10)  # 10% maximum

        # Volatility regime thresholds (multipliers of average ATR)
        self.extreme_high_threshold = 2.5
        self.high_threshold = 1.5
        self.normal_lower_threshold = 0.8
        self.normal_upper_threshold = 1.2
        self.low_threshold = 0.8
        self.extreme_low_threshold = 0.5

        # Position size multipliers per volatility regime
        self.volatility_multipliers = {
            VolatilityRegime.EXTREME_HIGH: 0.40,  # Reduce to 40% of base (60% reduction)
            VolatilityRegime.HIGH: 0.65,  # Reduce to 65% of base (35% reduction)
            VolatilityRegime.NORMAL: 1.00,  # Normal position size
            VolatilityRegime.LOW: 1.25,  # Increase to 125% of base (25% increase)
            VolatilityRegime.EXTREME_LOW: 1.50,  # Increase to 150% of base (50% increase)
        }

        # Session liquidity multipliers
        self.session_multipliers = {
            SessionType.OVERLAP: 1.20,  # London-NY overlap - highest liquidity
            SessionType.NY: 1.10,  # NY session - high liquidity
            SessionType.LONDON: 1.05,  # London session - good liquidity
            SessionType.ASIA: 0.85,  # Asia session - lower liquidity
            SessionType.OFF_HOURS: 0.70,  # Off hours - lowest liquidity
        }

        # ATR lookback for average calculation
        self.atr_lookback = self.config.get('atr_lookback', 20)

        logger.info("VolatilityAdaptiveSizer initialized")
        logger.info(f"  Base position: {self.base_position_pct*100:.1f}%")
        logger.info(f"  Range: {self.min_position_pct*100:.1f}% - {self.max_position_pct*100:.1f}%")

    def calculate_adaptive_position_size(
        self,
        df: pd.DataFrame,
        indicators: Dict,
        available_balance: float,
        current_time: datetime = None
    ) -> Dict:
        """
        Calculate volatility-adaptive position size

        Args:
            df: Price DataFrame with OHLCV data
            indicators: Dictionary of calculated indicators (must include 'atr')
            available_balance: Available trading balance in USD
            current_time: Current timestamp (optional, defaults to now)

        Returns:
            Dictionary with position sizing details
        """
        current_time = current_time or datetime.now()

        # 1. Analyze volatility regime
        volatility_regime, volatility_metrics = self._analyze_volatility_regime(df, indicators)

        # 2. Detect trading session
        session_type = self._detect_trading_session(current_time)

        # 3. Calculate base position
        base_position = available_balance * self.base_position_pct

        # 4. Apply volatility multiplier
        volatility_multiplier = self.volatility_multipliers[volatility_regime]
        volatility_adjusted = base_position * volatility_multiplier

        # 5. Apply session liquidity multiplier
        session_multiplier = self.session_multipliers[session_type]
        final_position = volatility_adjusted * session_multiplier

        # 6. Apply min/max constraints
        min_position = available_balance * self.min_position_pct
        max_position = available_balance * self.max_position_pct
        final_position = max(min_position, min(max_position, final_position))

        # 7. Calculate position as percentage of balance
        final_position_pct = final_position / available_balance if available_balance > 0 else 0

        # 8. Compile results
        result = {
            'position_size_usd': final_position,
            'position_pct': final_position_pct,
            'base_position_usd': base_position,
            'volatility_regime': volatility_regime.value,
            'volatility_multiplier': volatility_multiplier,
            'session_type': session_type.value,
            'session_multiplier': session_multiplier,
            'combined_multiplier': volatility_multiplier * session_multiplier,
            'metrics': volatility_metrics,
        }

        logger.info(f"📊 Adaptive Position Sizing:")
        logger.info(f"   Volatility: {volatility_regime.value.upper()} ({volatility_multiplier:.2f}x)")
        logger.info(f"   Session: {session_type.value.upper()} ({session_multiplier:.2f}x)")
        logger.info(f"   Base: ${base_position:.2f} → Final: ${final_position:.2f}")
        logger.info(f"   Position: {final_position_pct*100:.2f}% of ${available_balance:.2f}")

        return result

    def _analyze_volatility_regime(
        self,
        df: pd.DataFrame,
        indicators: Dict
    ) -> Tuple[VolatilityRegime, Dict]:
        """
        Analyze current volatility regime

        Args:
            df: Price DataFrame
            indicators: Dictionary with 'atr' indicator

        Returns:
            Tuple of (VolatilityRegime, metrics_dict)
        """
        # Get current ATR
        atr_series = indicators.get('atr', pd.Series([0]))
        if len(atr_series) == 0:
            return VolatilityRegime.NORMAL, {}

        current_atr = float(atr_series.iloc[-1])

        # Calculate average ATR over lookback period
        lookback = min(self.atr_lookback, len(atr_series))
        avg_atr = float(atr_series.iloc[-lookback:].mean())

        # Avoid division by zero
        if avg_atr == 0:
            return VolatilityRegime.NORMAL, {}

        # Calculate ATR ratio (current / average)
        atr_ratio = current_atr / avg_atr

        # Calculate volatility clusters (std dev of ATR)
        atr_std = float(atr_series.iloc[-lookback:].std())
        volatility_cluster_score = atr_std / avg_atr if avg_atr > 0 else 0

        # Classify regime based on ATR ratio
        if atr_ratio >= self.extreme_high_threshold:
            regime = VolatilityRegime.EXTREME_HIGH
        elif atr_ratio >= self.high_threshold:
            regime = VolatilityRegime.HIGH
        elif atr_ratio >= self.normal_lower_threshold and atr_ratio <= self.normal_upper_threshold:
            regime = VolatilityRegime.NORMAL
        elif atr_ratio >= self.extreme_low_threshold:
            regime = VolatilityRegime.LOW
        else:
            regime = VolatilityRegime.EXTREME_LOW

        # Compile metrics
        metrics = {
            'current_atr': current_atr,
            'avg_atr': avg_atr,
            'atr_ratio': atr_ratio,
            'atr_std': atr_std,
            'volatility_cluster_score': volatility_cluster_score,
            'regime': regime.value,
        }

        return regime, metrics

    def _detect_trading_session(self, current_time: datetime) -> SessionType:
        """
        Detect current trading session based on UTC time

        Trading Sessions (UTC):
        - Asia: 00:00 - 08:00 UTC
        - London: 08:00 - 16:00 UTC
        - NY: 13:00 - 21:00 UTC
        - Overlap (London-NY): 13:00 - 16:00 UTC
        - Off-hours: Weekends

        Args:
            current_time: Current datetime (should be UTC)

        Returns:
            SessionType enum
        """
        # Check if weekend
        if current_time.weekday() >= 5:  # Saturday = 5, Sunday = 6
            return SessionType.OFF_HOURS

        # Get hour in UTC
        hour = current_time.hour

        # Detect session
        if 13 <= hour < 16:
            return SessionType.OVERLAP  # London-NY overlap (peak liquidity)
        elif 13 <= hour < 21:
            return SessionType.NY  # NY session
        elif 8 <= hour < 16:
            return SessionType.LONDON  # London session
        elif 0 <= hour < 8:
            return SessionType.ASIA  # Asia session
        else:
            return SessionType.OFF_HOURS  # Off hours

    def get_volatility_report(self, df: pd.DataFrame, indicators: Dict) -> str:
        """
        Generate volatility analysis report

        Args:
            df: Price DataFrame
            indicators: Dictionary with indicators

        Returns:
            Formatted report string
        """
        regime, metrics = self._analyze_volatility_regime(df, indicators)
        session = self._detect_trading_session(datetime.now())

        report = [
            "\n" + "=" * 70,
            "VOLATILITY ANALYSIS REPORT",
            "=" * 70,
            f"Volatility Regime: {regime.value.upper()}",
            f"Trading Session: {session.value.upper()}",
            "",
            "📊 Metrics:",
            f"  Current ATR: ${metrics.get('current_atr', 0):.4f}",
            f"  Average ATR: ${metrics.get('avg_atr', 0):.4f}",
            f"  ATR Ratio: {metrics.get('atr_ratio', 0):.2f}x",
            f"  Volatility Cluster Score: {metrics.get('volatility_cluster_score', 0):.3f}",
            "",
            "🎯 Position Size Adjustments:",
            f"  Volatility Multiplier: {self.volatility_multipliers[regime]:.2f}x",
            f"  Session Multiplier: {self.session_multipliers[session]:.2f}x",
            f"  Combined: {self.volatility_multipliers[regime] * self.session_multipliers[session]:.2f}x",
            "=" * 70,
        ]

        return "\n".join(report)


def get_volatility_adaptive_sizer(config: Dict = None) -> VolatilityAdaptiveSizer:
    """
    Factory function to create VolatilityAdaptiveSizer instance

    Args:
        config: Optional configuration dictionary

    Returns:
        VolatilityAdaptiveSizer instance
    """
    return VolatilityAdaptiveSizer(config)


# Example usage and testing
if __name__ == "__main__":
    import logging
    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

    # Create sample data
    dates = pd.date_range('2024-01-01', periods=100, freq='1H')
    df = pd.DataFrame({
        'timestamp': dates,
        'close': np.random.randn(100).cumsum() + 100,
        'high': np.random.randn(100).cumsum() + 102,
        'low': np.random.randn(100).cumsum() + 98,
        'volume': np.random.randint(1000, 10000, 100)
    })

    # Calculate ATR
    from indicators import calculate_atr
    df['atr'] = calculate_atr(df, period=14)

    indicators = {'atr': df['atr']}

    # Create sizer
    sizer = get_volatility_adaptive_sizer()

    # Calculate position size
    result = sizer.calculate_adaptive_position_size(
        df=df,
        indicators=indicators,
        available_balance=10000.0,
        current_time=datetime.now()
    )

    print("\n✅ Position Sizing Result:")
    print(f"  Position Size: ${result['position_size_usd']:.2f}")
    print(f"  Position %: {result['position_pct']*100:.2f}%")
    print(f"  Volatility Regime: {result['volatility_regime']}")
    print(f"  Session: {result['session_type']}")

    # Print report
    print(sizer.get_volatility_report(df, indicators))
