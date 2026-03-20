"""
NIJA Trade Frequency Optimizer
===============================

Dynamically optimizes trade frequency to maximize high-probability signals:

1. **Signal Density Scoring** - Identifies periods with more quality setups
2. **Multi-Timeframe Analysis** - Combines signals from multiple timeframes
3. **Adaptive Sampling** - Increases scan frequency during optimal conditions
4. **Quality Over Quantity** - Filters for high-probability setups

Key Features:
- Detect high-opportunity windows (London-NY overlap, trend starts, etc.)
- Multi-timeframe signal confluence
- Dynamic scan interval adjustment
- Signal quality scoring

Author: NIJA Trading Systems
Version: 2.0 - Elite Profit Engine
Date: January 29, 2026
"""

import logging
from typing import Dict, List, Tuple
from enum import Enum
from datetime import datetime, time
import pandas as pd
import numpy as np

logger = logging.getLogger("nija.frequency_optimizer")


class TimeframeType(Enum):
    """Timeframe classifications"""
    M1 = "1m"  # 1 minute
    M5 = "5m"  # 5 minutes
    M15 = "15m"  # 15 minutes
    H1 = "1h"  # 1 hour
    H4 = "4h"  # 4 hours


class OpportunityWindow(Enum):
    """Trading opportunity windows"""
    PEAK = "peak"  # Peak opportunity (fastest scanning)
    HIGH = "high"  # High opportunity
    NORMAL = "normal"  # Normal opportunity
    LOW = "low"  # Low opportunity
    MINIMAL = "minimal"  # Minimal opportunity (slowest scanning)


class SignalQuality(Enum):
    """Signal quality classifications"""
    EXCELLENT = "excellent"  # 85+ score
    GOOD = "good"  # 70-85 score
    FAIR = "fair"  # 60-70 score
    MARGINAL = "marginal"  # 50-60 score
    POOR = "poor"  # <50 score


class TradeFrequencyOptimizer:
    """
    Optimizes trade frequency to maximize high-probability signals
    """

    def __init__(self, config: Dict = None):
        """
        Initialize Trade Frequency Optimizer

        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}

        # Base scan interval (seconds)
        self.base_scan_interval = self.config.get('base_scan_interval', 150)  # 2.5 minutes default

        # Scan interval multipliers per opportunity window
        self.interval_multipliers = {
            OpportunityWindow.PEAK: 0.50,  # 50% faster (75 seconds)
            OpportunityWindow.HIGH: 0.75,  # 25% faster (112.5 seconds)
            OpportunityWindow.NORMAL: 1.00,  # Normal speed (150 seconds)
            OpportunityWindow.LOW: 1.50,  # 50% slower (225 seconds)
            OpportunityWindow.MINIMAL: 2.00,  # 100% slower (300 seconds)
        }

        # Signal quality thresholds
        self.excellent_threshold = 85
        self.good_threshold = 70
        self.fair_threshold = 60
        self.marginal_threshold = 50

        # Multi-timeframe weights
        self.timeframe_weights = {
            TimeframeType.M5: 0.40,  # 40% weight - primary timeframe
            TimeframeType.M15: 0.35,  # 35% weight - trend confirmation
            TimeframeType.H1: 0.25,  # 25% weight - larger context
        }

        # Opportunity window detection
        self.peak_hours_utc = [(13, 16)]  # London-NY overlap
        self.high_hours_utc = [(8, 13), (16, 21)]  # London and NY sessions
        self.low_hours_utc = [(0, 8)]  # Asia session

        # Signal history for density calculation
        self.signal_history: List[Dict] = []
        self.max_history_length = 100

        logger.info("=" * 70)
        logger.info("🎯 Trade Frequency Optimizer Initialized")
        logger.info("=" * 70)
        logger.info(f"Base Scan Interval: {self.base_scan_interval}s")
        logger.info(f"Multi-Timeframe: {', '.join([t.value for t in self.timeframe_weights.keys()])}")
        logger.info("=" * 70)

    def detect_opportunity_window(self, current_time: datetime = None) -> OpportunityWindow:
        """
        Detect current trading opportunity window

        Args:
            current_time: Current datetime (UTC)

        Returns:
            OpportunityWindow enum
        """
        current_time = current_time or datetime.utcnow()
        hour = current_time.hour
        weekday = current_time.weekday()

        # Weekend = minimal opportunity
        if weekday >= 5:
            return OpportunityWindow.MINIMAL

        # Check if in peak hours
        for start_hour, end_hour in self.peak_hours_utc:
            if start_hour <= hour < end_hour:
                return OpportunityWindow.PEAK

        # Check if in high hours
        for start_hour, end_hour in self.high_hours_utc:
            if start_hour <= hour < end_hour:
                return OpportunityWindow.HIGH

        # Check if in low hours
        for start_hour, end_hour in self.low_hours_utc:
            if start_hour <= hour < end_hour:
                return OpportunityWindow.LOW

        # Default to normal
        return OpportunityWindow.NORMAL

    def calculate_signal_density(self, lookback_minutes: int = 60) -> float:
        """
        Calculate signal density (signals per hour)

        Args:
            lookback_minutes: Minutes to look back

        Returns:
            Signals per hour rate
        """
        if not self.signal_history:
            return 0.0

        # Filter to recent signals
        cutoff_time = datetime.now().timestamp() - (lookback_minutes * 60)
        recent_signals = [
            s for s in self.signal_history
            if s.get('timestamp', 0) >= cutoff_time
        ]

        # Calculate signals per hour
        if lookback_minutes > 0:
            signals_per_hour = (len(recent_signals) / lookback_minutes) * 60
        else:
            signals_per_hour = 0.0

        return signals_per_hour

    def calculate_multi_timeframe_score(
        self,
        signals_by_timeframe: Dict[TimeframeType, Dict]
    ) -> Tuple[float, Dict]:
        """
        Calculate combined signal score from multiple timeframes

        Args:
            signals_by_timeframe: Dict mapping TimeframeType to signal dict

        Returns:
            Tuple of (combined_score, breakdown)
        """
        weighted_scores = []
        breakdown = {}

        for timeframe, weight in self.timeframe_weights.items():
            signal = signals_by_timeframe.get(timeframe, {})
            score = signal.get('score', 0)

            weighted_score = score * weight
            weighted_scores.append(weighted_score)

            breakdown[timeframe.value] = {
                'score': score,
                'weight': weight,
                'weighted_score': weighted_score
            }

        combined_score = sum(weighted_scores)

        return combined_score, breakdown

    def classify_signal_quality(self, score: float) -> SignalQuality:
        """
        Classify signal quality based on score

        Args:
            score: Signal score (0-100)

        Returns:
            SignalQuality enum
        """
        if score >= self.excellent_threshold:
            return SignalQuality.EXCELLENT
        elif score >= self.good_threshold:
            return SignalQuality.GOOD
        elif score >= self.fair_threshold:
            return SignalQuality.FAIR
        elif score >= self.marginal_threshold:
            return SignalQuality.MARGINAL
        else:
            return SignalQuality.POOR

    def should_take_signal(
        self,
        score: float,
        min_quality: SignalQuality = SignalQuality.FAIR
    ) -> bool:
        """
        Determine if signal meets minimum quality threshold

        Args:
            score: Signal score
            min_quality: Minimum required quality

        Returns:
            True if signal meets threshold
        """
        quality_thresholds = {
            SignalQuality.EXCELLENT: self.excellent_threshold,
            SignalQuality.GOOD: self.good_threshold,
            SignalQuality.FAIR: self.fair_threshold,
            SignalQuality.MARGINAL: self.marginal_threshold,
            SignalQuality.POOR: 0,
        }

        min_score = quality_thresholds[min_quality]
        return score >= min_score

    def get_optimal_scan_interval(
        self,
        current_time: datetime = None,
        volatility_regime: str = "normal",
        signal_density: float = None,
        account_balance: float = None,
        broker_name: str = "coinbase",
    ) -> int:
        """
        Calculate optimal scan interval based on conditions.

        Extended (Mar 2026) with balance-relative adjustment:
        Accounts that have very little capital relative to the broker minimum
        benefit from slower scanning (fewer wasted API calls), while well-funded
        accounts benefit from faster scanning to catch more opportunities.

        Args:
            current_time:      Current datetime
            volatility_regime: Current volatility regime
            signal_density:    Recent signal density (signals per hour)
            account_balance:   Current account balance in USD (optional).
                               When provided, the balance/broker_min ratio is
                               used to further tune the interval.
            broker_name:       Broker name used to look up the minimum order
                               size (default 'coinbase').

        Returns:
            Optimal scan interval in seconds
        """
        # Get base interval from opportunity window
        opportunity_window = self.detect_opportunity_window(current_time)
        multiplier = self.interval_multipliers[opportunity_window]

        # Adjust for volatility (high volatility = faster scanning)
        if volatility_regime == "high" or volatility_regime == "extreme_high":
            multiplier *= 0.85  # 15% faster
        elif volatility_regime == "low" or volatility_regime == "extreme_low":
            multiplier *= 1.15  # 15% slower

        # Adjust for signal density (more signals = faster scanning)
        if signal_density is not None:
            if signal_density >= 8:  # 8+ signals/hour = very active
                multiplier *= 0.90  # 10% faster
            elif signal_density <= 2:  # <2 signals/hour = quiet
                multiplier *= 1.10  # 10% slower

        # ── Balance-relative adjustment (Mar 2026) ────────────────────────
        # Use the adaptive minimum sizer's scan-interval helper when an account
        # balance is supplied.  This prevents idle accounts from being over-
        # scanned and ensures well-capitalised accounts are scanned quickly.
        if account_balance is not None and account_balance > 0:
            try:
                try:
                    from bot.adaptive_minimum_sizing import get_adaptive_minimum_sizer
                except ImportError:
                    from adaptive_minimum_sizing import get_adaptive_minimum_sizer
                sizer = get_adaptive_minimum_sizer()
                balance_adj = sizer.get_scan_interval_adjustment(
                    account_balance,
                    broker_name,
                    base_interval_seconds=self.base_scan_interval,
                )
                # Blend: weight = 0.4 balance-adj, 0.6 existing signal/vol logic
                balance_multiplier = balance_adj["multiplier"]
                multiplier = multiplier * 0.60 + balance_multiplier * 0.40
                logger.debug(
                    f"Balance-relative interval adjustment: "
                    f"balance=${account_balance:.0f} broker={broker_name} "
                    f"balance_mult={balance_multiplier:.2f} "
                    f"blended_mult={multiplier:.2f}"
                )
            except Exception as _e:
                logger.debug(f"Balance-relative scan adjustment unavailable: {_e}")

        # Calculate final interval
        interval = int(self.base_scan_interval * multiplier)

        # Ensure reasonable bounds (30 seconds to 5 minutes)
        interval = max(30, min(300, interval))

        return interval

    def get_balance_trade_capacity(
        self,
        account_balance: float,
        broker_name: str = "coinbase",
        confidence: float = 1.0,
    ) -> Dict:
        """
        Return trade-capacity information for the current balance.

        Delegates to ``AdaptiveMinimumSizer.get_trade_capacity`` and returns the
        result as a plain dict so callers do not need to import the sizer directly.

        Args:
            account_balance: Available cash balance (USD).
            broker_name:     Exchange / broker name.
            confidence:      Expected signal confidence (affects adaptive_min).

        Returns:
            Dict with ``adaptive_min``, ``max_concurrent``, ``idle_risk``,
            ``utilisation_pct``, and ``recommendation``.
        """
        try:
            try:
                from bot.adaptive_minimum_sizing import get_adaptive_minimum_sizer
            except ImportError:
                from adaptive_minimum_sizing import get_adaptive_minimum_sizer
            sizer = get_adaptive_minimum_sizer()
            broker_min = sizer.get_broker_minimum(broker_name)
            return sizer.get_trade_capacity(account_balance, broker_min, confidence)
        except Exception as _e:
            logger.warning(f"Trade capacity check unavailable: {_e}")
            return {
                "adaptive_min": 0.0,
                "max_concurrent": 0,
                "idle_risk": account_balance <= 0,
                "utilisation_pct": 0.0,
                "recommendation": "Adaptive minimum sizing module not available.",
            }

    def is_account_idle_risk(
        self,
        account_balance: float,
        broker_name: str = "coinbase",
        confidence: float = 1.0,
    ) -> bool:
        """
        Return True if the account balance is too low to open even one trade at
        the adaptive minimum size for the given broker and confidence level.

        When True the caller should consider:
        * Depositing more funds.
        * Consolidating capital from other brokers.
        * Reducing the target broker's effective minimum (e.g. switch brokers).

        Args:
            account_balance: Available cash balance (USD).
            broker_name:     Broker name.
            confidence:      Expected signal confidence.

        Returns:
            bool – True if account is at idle risk.
        """
        capacity = self.get_balance_trade_capacity(account_balance, broker_name, confidence)
        return capacity.get("idle_risk", False)

    def record_signal(
        self,
        score: float,
        timeframe: str,
        symbol: str,
        side: str,
        taken: bool = False
    ):
        """
        Record a generated signal for density tracking

        Args:
            score: Signal score
            timeframe: Timeframe of signal
            symbol: Trading symbol
            side: 'long' or 'short'
            taken: Whether signal was taken
        """
        signal_record = {
            'timestamp': datetime.now().timestamp(),
            'score': score,
            'timeframe': timeframe,
            'symbol': symbol,
            'side': side,
            'taken': taken,
            'quality': self.classify_signal_quality(score).value
        }

        self.signal_history.append(signal_record)

        # Trim history
        if len(self.signal_history) > self.max_history_length:
            self.signal_history = self.signal_history[-self.max_history_length:]

        logger.debug(f"📊 Signal recorded: {symbol} {side.upper()} @ {score:.1f} ({signal_record['quality']})")

    def get_signal_statistics(self, lookback_hours: int = 24) -> Dict:
        """
        Get signal statistics for lookback period

        Args:
            lookback_hours: Hours to analyze

        Returns:
            Dictionary with signal statistics
        """
        cutoff_time = datetime.now().timestamp() - (lookback_hours * 3600)
        recent_signals = [
            s for s in self.signal_history
            if s.get('timestamp', 0) >= cutoff_time
        ]

        if not recent_signals:
            return {
                'total_signals': 0,
                'signals_per_hour': 0.0,
                'avg_score': 0.0,
                'quality_distribution': {},
                'taken_rate': 0.0,
            }

        # Calculate statistics
        total = len(recent_signals)
        signals_per_hour = total / lookback_hours
        avg_score = sum(s['score'] for s in recent_signals) / total

        # Quality distribution
        quality_counts = {}
        for signal in recent_signals:
            quality = signal['quality']
            quality_counts[quality] = quality_counts.get(quality, 0) + 1

        quality_distribution = {
            q: (count / total * 100)
            for q, count in quality_counts.items()
        }

        # Taken rate
        taken_count = sum(1 for s in recent_signals if s.get('taken', False))
        taken_rate = (taken_count / total * 100) if total > 0 else 0

        return {
            'total_signals': total,
            'signals_per_hour': signals_per_hour,
            'avg_score': avg_score,
            'quality_distribution': quality_distribution,
            'taken_rate': taken_rate,
        }

    def get_frequency_report(self, current_time: datetime = None) -> str:
        """
        Generate trade frequency optimization report

        Args:
            current_time: Current datetime

        Returns:
            Formatted report string
        """
        current_time = current_time or datetime.utcnow()
        opportunity_window = self.detect_opportunity_window(current_time)
        optimal_interval = self.get_optimal_scan_interval(current_time)
        signal_density = self.calculate_signal_density(60)
        stats_24h = self.get_signal_statistics(24)

        report = [
            "\n" + "=" * 90,
            "TRADE FREQUENCY OPTIMIZATION REPORT",
            "=" * 90,
            f"Current Time: {current_time.strftime('%Y-%m-%d %H:%M:%S')} UTC",
            f"Opportunity Window: {opportunity_window.value.upper()}",
            "",
            "🎯 SCANNING OPTIMIZATION",
            "-" * 90,
            f"  Base Interval:     {self.base_scan_interval:>12,}s",
            f"  Optimal Interval:  {optimal_interval:>12,}s",
            f"  Multiplier:        {optimal_interval/self.base_scan_interval:>12.2f}x",
            "",
            "📊 SIGNAL DENSITY (Last Hour)",
            "-" * 90,
            f"  Signals/Hour:      {signal_density:>12.1f}",
            "",
            "📈 24-HOUR STATISTICS",
            "-" * 90,
            f"  Total Signals:     {stats_24h['total_signals']:>12,}",
            f"  Signals/Hour:      {stats_24h['signals_per_hour']:>12.1f}",
            f"  Avg Score:         {stats_24h['avg_score']:>12.1f}",
            f"  Taken Rate:        {stats_24h['taken_rate']:>12.1f}%",
            "",
        ]

        # Add quality distribution
        if stats_24h['quality_distribution']:
            report.append("  Quality Distribution:")
            for quality, pct in sorted(stats_24h['quality_distribution'].items()):
                report.append(f"    {quality.capitalize():15s}: {pct:>6.1f}%")

        report.append("=" * 90)

        return "\n".join(report)


def get_trade_frequency_optimizer(config: Dict = None) -> TradeFrequencyOptimizer:
    """
    Factory function to create TradeFrequencyOptimizer

    Args:
        config: Optional configuration

    Returns:
        TradeFrequencyOptimizer instance
    """
    return TradeFrequencyOptimizer(config)


# Example usage
if __name__ == "__main__":
    import logging

    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

    # Create optimizer
    optimizer = get_trade_frequency_optimizer()

    # Simulate some signals
    print("\n📡 Simulating signal generation...\n")

    optimizer.record_signal(score=85.0, timeframe='5m', symbol='BTC-USD', side='long', taken=True)
    optimizer.record_signal(score=72.0, timeframe='15m', symbol='ETH-USD', side='long', taken=True)
    optimizer.record_signal(score=55.0, timeframe='5m', symbol='SOL-USD', side='short', taken=False)
    optimizer.record_signal(score=90.0, timeframe='1h', symbol='BTC-USD', side='long', taken=True)

    # Test multi-timeframe analysis
    signals = {
        TimeframeType.M5: {'score': 85.0, 'side': 'long'},
        TimeframeType.M15: {'score': 78.0, 'side': 'long'},
        TimeframeType.H1: {'score': 82.0, 'side': 'long'},
    }

    combined_score, breakdown = optimizer.calculate_multi_timeframe_score(signals)
    print(f"\n✅ Multi-Timeframe Analysis:")
    print(f"  Combined Score: {combined_score:.1f}/100")
    for tf, details in breakdown.items():
        print(f"  {tf}: {details['score']:.1f} x {details['weight']:.0%} = {details['weighted_score']:.1f}")

    # Print report
    print(optimizer.get_frequency_report())

    # Get optimal scan interval
    interval = optimizer.get_optimal_scan_interval()
    print(f"\n🎯 Optimal Scan Interval: {interval}s ({interval/60:.1f} minutes)")
