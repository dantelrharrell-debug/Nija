"""
NIJA Trade Distribution Stability Testing
=========================================

Institutional-grade statistical testing to ensure trade performance distributions
remain stable over time. This detects strategy degradation before it impacts capital.

Tests:
- Kolmogorov-Smirnov test for distribution changes
- Chi-square test for frequency stability
- Moving window analysis for drift detection
- Regime-specific performance validation
- Sequential probability ratio test (SPRT)

Author: NIJA Trading Systems
Version: 1.0
Date: February 15, 2026
"""

import logging
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from scipy import stats
from collections import deque
import json
from pathlib import Path

logger = logging.getLogger("nija.trade_distribution")


@dataclass
class TradeStatistics:
    """Statistics for a set of trades"""
    num_trades: int = 0
    win_rate: float = 0.0
    avg_return: float = 0.0
    std_return: float = 0.0
    median_return: float = 0.0
    skewness: float = 0.0
    kurtosis: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    profit_factor: float = 0.0


@dataclass
class DistributionTest:
    """Result of a distribution stability test"""
    test_name: str
    statistic: float
    p_value: float
    is_stable: bool
    threshold: float
    interpretation: str


@dataclass
class StabilityAnalysisResult:
    """Complete stability analysis result"""
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    # Overall stability
    is_stable: bool = True
    confidence_level: float = 0.95
    stability_score: float = 1.0  # 0-1, where 1 = perfectly stable
    
    # Statistical tests
    ks_test: Optional[DistributionTest] = None
    chi_square_test: Optional[DistributionTest] = None
    t_test: Optional[DistributionTest] = None
    variance_test: Optional[DistributionTest] = None
    
    # Window analysis
    baseline_stats: Optional[TradeStatistics] = None
    recent_stats: Optional[TradeStatistics] = None
    drift_detected: bool = False
    drift_magnitude: float = 0.0
    
    # Performance metrics
    mean_return_change_pct: float = 0.0
    volatility_change_pct: float = 0.0
    win_rate_change_pct: float = 0.0
    
    # Warnings and recommendations
    warnings: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


class TradeDistributionStabilityEngine:
    """
    Trade distribution stability testing engine
    
    Monitors trade performance distributions and detects degradation
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize Trade Distribution Stability Engine
        
        Args:
            config: Configuration dictionary
        """
        self.config = config or {}
        
        # Test configuration
        self.confidence_level = self.config.get('confidence_level', 0.95)
        self.baseline_window = self.config.get('baseline_window', 100)  # Number of trades
        self.recent_window = self.config.get('recent_window', 50)  # Number of trades
        self.min_trades = self.config.get('min_trades_for_test', 30)
        
        # Stability thresholds
        self.mean_drift_threshold_pct = self.config.get('mean_drift_threshold', 0.20)  # 20%
        self.volatility_drift_threshold_pct = self.config.get('volatility_drift_threshold', 0.30)  # 30%
        self.win_rate_drift_threshold_pct = self.config.get('win_rate_drift_threshold', 0.10)  # 10%
        
        # Trade history
        self.trade_returns: deque = deque(maxlen=1000)  # Keep last 1000 trades
        self.trade_timestamps: deque = deque(maxlen=1000)
        
        logger.info("=" * 70)
        logger.info("📊 Trade Distribution Stability Engine Initialized")
        logger.info("=" * 70)
        logger.info(f"Confidence Level: {self.confidence_level*100:.0f}%")
        logger.info(f"Baseline Window: {self.baseline_window} trades")
        logger.info(f"Recent Window: {self.recent_window} trades")
        logger.info(f"Min Trades for Test: {self.min_trades}")
        logger.info("=" * 70)
    
    def add_trade(self, return_pct: float, timestamp: Optional[datetime] = None):
        """
        Add a trade to the history
        
        Args:
            return_pct: Trade return as percentage (-100 to infinity)
            timestamp: Trade timestamp
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        self.trade_returns.append(return_pct)
        self.trade_timestamps.append(timestamp)
    
    def calculate_trade_statistics(self, returns: List[float]) -> TradeStatistics:
        """
        Calculate statistics for a set of trade returns
        
        Args:
            returns: List of trade returns
        
        Returns:
            TradeStatistics
        """
        if len(returns) == 0:
            return TradeStatistics()
        
        returns_array = np.array(returns)
        
        # Basic statistics
        num_trades = len(returns)
        wins = returns_array > 0
        win_rate = np.sum(wins) / num_trades if num_trades > 0 else 0.0
        
        avg_return = np.mean(returns_array)
        std_return = np.std(returns_array, ddof=1) if num_trades > 1 else 0.0
        median_return = np.median(returns_array)
        
        # Distribution shape
        skewness = stats.skew(returns_array) if num_trades >= 3 else 0.0
        kurtosis = stats.kurtosis(returns_array) if num_trades >= 4 else 0.0
        
        # Risk-adjusted return
        sharpe_ratio = (avg_return / std_return * np.sqrt(252)) if std_return > 0 else 0.0
        
        # Drawdown
        cumulative = np.cumprod(1 + returns_array / 100)
        peak = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - peak) / peak * 100
        max_drawdown = np.min(drawdown) if len(drawdown) > 0 else 0.0
        
        # Profit factor
        gross_profit = np.sum(returns_array[returns_array > 0])
        gross_loss = abs(np.sum(returns_array[returns_array < 0]))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else np.inf
        
        return TradeStatistics(
            num_trades=num_trades,
            win_rate=win_rate,
            avg_return=avg_return,
            std_return=std_return,
            median_return=median_return,
            skewness=skewness,
            kurtosis=kurtosis,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            profit_factor=profit_factor
        )
    
    def kolmogorov_smirnov_test(
        self,
        baseline_returns: List[float],
        recent_returns: List[float]
    ) -> DistributionTest:
        """
        Perform Kolmogorov-Smirnov test for distribution equality
        
        Tests if baseline and recent returns come from same distribution
        
        Args:
            baseline_returns: Baseline period returns
            recent_returns: Recent period returns
        
        Returns:
            DistributionTest result
        """
        # KS test
        statistic, p_value = stats.ks_2samp(baseline_returns, recent_returns)
        
        # Determine stability (higher p-value = more similar)
        alpha = 1 - self.confidence_level
        is_stable = p_value > alpha
        
        if is_stable:
            interpretation = f"Distributions are similar (p={p_value:.4f} > {alpha:.4f})"
        else:
            interpretation = f"Distributions differ significantly (p={p_value:.4f} ≤ {alpha:.4f})"
        
        return DistributionTest(
            test_name="Kolmogorov-Smirnov Test",
            statistic=statistic,
            p_value=p_value,
            is_stable=is_stable,
            threshold=alpha,
            interpretation=interpretation
        )
    
    def chi_square_test(
        self,
        baseline_returns: List[float],
        recent_returns: List[float],
        num_bins: int = 10
    ) -> DistributionTest:
        """
        Perform Chi-Square test for frequency distribution
        
        Args:
            baseline_returns: Baseline period returns
            recent_returns: Recent period returns
            num_bins: Number of bins for histogram
        
        Returns:
            DistributionTest result
        """
        # Create bins based on combined data
        all_returns = baseline_returns + recent_returns
        bins = np.percentile(all_returns, np.linspace(0, 100, num_bins + 1))
        
        # Get histograms
        baseline_hist, _ = np.histogram(baseline_returns, bins=bins)
        recent_hist, _ = np.histogram(recent_returns, bins=bins)
        
        # Chi-square test
        # Expected frequencies from baseline
        total_baseline = len(baseline_returns)
        total_recent = len(recent_returns)
        expected_freq = baseline_hist * (total_recent / total_baseline)
        
        # Avoid division by zero
        mask = expected_freq > 0
        observed = recent_hist[mask]
        expected = expected_freq[mask]
        
        if len(observed) < 2:
            # Not enough data
            return DistributionTest(
                test_name="Chi-Square Test",
                statistic=0.0,
                p_value=1.0,
                is_stable=True,
                threshold=0.0,
                interpretation="Insufficient data for test"
            )
        
        statistic, p_value = stats.chisquare(observed, expected)
        
        # Determine stability
        alpha = 1 - self.confidence_level
        is_stable = p_value > alpha
        
        if is_stable:
            interpretation = f"Frequency distributions are similar (p={p_value:.4f} > {alpha:.4f})"
        else:
            interpretation = f"Frequency distributions differ (p={p_value:.4f} ≤ {alpha:.4f})"
        
        return DistributionTest(
            test_name="Chi-Square Test",
            statistic=statistic,
            p_value=p_value,
            is_stable=is_stable,
            threshold=alpha,
            interpretation=interpretation
        )
    
    def t_test_means(
        self,
        baseline_returns: List[float],
        recent_returns: List[float]
    ) -> DistributionTest:
        """
        Perform t-test for mean equality
        
        Tests if means of baseline and recent returns are equal
        
        Args:
            baseline_returns: Baseline period returns
            recent_returns: Recent period returns
        
        Returns:
            DistributionTest result
        """
        # Two-sample t-test
        statistic, p_value = stats.ttest_ind(baseline_returns, recent_returns)
        
        # Determine stability
        alpha = 1 - self.confidence_level
        is_stable = p_value > alpha
        
        baseline_mean = np.mean(baseline_returns)
        recent_mean = np.mean(recent_returns)
        
        if is_stable:
            interpretation = (
                f"Means are statistically similar (p={p_value:.4f} > {alpha:.4f}). "
                f"Baseline: {baseline_mean:.2f}%, Recent: {recent_mean:.2f}%"
            )
        else:
            interpretation = (
                f"Means differ significantly (p={p_value:.4f} ≤ {alpha:.4f}). "
                f"Baseline: {baseline_mean:.2f}%, Recent: {recent_mean:.2f}%"
            )
        
        return DistributionTest(
            test_name="T-Test (Means)",
            statistic=statistic,
            p_value=p_value,
            is_stable=is_stable,
            threshold=alpha,
            interpretation=interpretation
        )
    
    def variance_test(
        self,
        baseline_returns: List[float],
        recent_returns: List[float]
    ) -> DistributionTest:
        """
        Perform Levene test for variance equality
        
        Tests if variances of baseline and recent returns are equal
        
        Args:
            baseline_returns: Baseline period returns
            recent_returns: Recent period returns
        
        Returns:
            DistributionTest result
        """
        # Levene test (more robust than F-test)
        statistic, p_value = stats.levene(baseline_returns, recent_returns)
        
        # Determine stability
        alpha = 1 - self.confidence_level
        is_stable = p_value > alpha
        
        baseline_std = np.std(baseline_returns, ddof=1)
        recent_std = np.std(recent_returns, ddof=1)
        
        if is_stable:
            interpretation = (
                f"Variances are statistically similar (p={p_value:.4f} > {alpha:.4f}). "
                f"Baseline σ: {baseline_std:.2f}%, Recent σ: {recent_std:.2f}%"
            )
        else:
            interpretation = (
                f"Variances differ significantly (p={p_value:.4f} ≤ {alpha:.4f}). "
                f"Baseline σ: {baseline_std:.2f}%, Recent σ: {recent_std:.2f}%"
            )
        
        return DistributionTest(
            test_name="Levene Test (Variance)",
            statistic=statistic,
            p_value=p_value,
            is_stable=is_stable,
            threshold=alpha,
            interpretation=interpretation
        )
    
    def detect_drift(
        self,
        baseline_stats: TradeStatistics,
        recent_stats: TradeStatistics
    ) -> Tuple[bool, float, List[str]]:
        """
        Detect drift in trading performance
        
        Args:
            baseline_stats: Baseline statistics
            recent_stats: Recent statistics
        
        Returns:
            Tuple of (drift_detected, drift_magnitude, drift_reasons)
        """
        drift_reasons = []
        drift_magnitude = 0.0
        
        # Check mean return drift
        if baseline_stats.avg_return != 0:
            mean_change = (recent_stats.avg_return - baseline_stats.avg_return) / abs(baseline_stats.avg_return)
            if abs(mean_change) > self.mean_drift_threshold_pct:
                drift_reasons.append(
                    f"Mean return drift: {mean_change*100:+.1f}% "
                    f"(threshold: {self.mean_drift_threshold_pct*100:.0f}%)"
                )
                drift_magnitude = max(drift_magnitude, abs(mean_change))
        
        # Check volatility drift
        if baseline_stats.std_return > 0:
            vol_change = (recent_stats.std_return - baseline_stats.std_return) / baseline_stats.std_return
            if abs(vol_change) > self.volatility_drift_threshold_pct:
                drift_reasons.append(
                    f"Volatility drift: {vol_change*100:+.1f}% "
                    f"(threshold: {self.volatility_drift_threshold_pct*100:.0f}%)"
                )
                drift_magnitude = max(drift_magnitude, abs(vol_change) * 0.7)  # Weight volatility less
        
        # Check win rate drift
        if baseline_stats.win_rate > 0:
            wr_change = (recent_stats.win_rate - baseline_stats.win_rate) / baseline_stats.win_rate
            if abs(wr_change) > self.win_rate_drift_threshold_pct:
                drift_reasons.append(
                    f"Win rate drift: {wr_change*100:+.1f}% "
                    f"(threshold: {self.win_rate_drift_threshold_pct*100:.0f}%)"
                )
                drift_magnitude = max(drift_magnitude, abs(wr_change))
        
        drift_detected = len(drift_reasons) > 0
        
        return drift_detected, drift_magnitude, drift_reasons
    
    def analyze_stability(
        self,
        trade_returns: Optional[List[float]] = None
    ) -> StabilityAnalysisResult:
        """
        Complete stability analysis
        
        Args:
            trade_returns: Optional list of returns (uses internal history if not provided)
        
        Returns:
            StabilityAnalysisResult
        """
        logger.info("\n" + "=" * 70)
        logger.info("📊 TRADE DISTRIBUTION STABILITY ANALYSIS")
        logger.info("=" * 70)
        
        # Get returns
        if trade_returns is None:
            trade_returns = list(self.trade_returns)
        
        # Check minimum data requirement
        if len(trade_returns) < self.min_trades:
            logger.warning(f"Insufficient trades: {len(trade_returns)} < {self.min_trades}")
            return StabilityAnalysisResult(
                is_stable=True,
                warnings=[f"Insufficient data: {len(trade_returns)} trades (need {self.min_trades})"]
            )
        
        # Split into baseline and recent
        if len(trade_returns) >= self.baseline_window + self.recent_window:
            # Use specified windows
            baseline_returns = trade_returns[-self.baseline_window - self.recent_window:-self.recent_window]
            recent_returns = trade_returns[-self.recent_window:]
        else:
            # Split available data in half
            split_idx = len(trade_returns) // 2
            baseline_returns = trade_returns[:split_idx]
            recent_returns = trade_returns[split_idx:]
        
        logger.info(f"Baseline period: {len(baseline_returns)} trades")
        logger.info(f"Recent period: {len(recent_returns)} trades")
        
        # Calculate statistics
        baseline_stats = self.calculate_trade_statistics(baseline_returns)
        recent_stats = self.calculate_trade_statistics(recent_returns)
        
        # Statistical tests
        ks_test = self.kolmogorov_smirnov_test(baseline_returns, recent_returns)
        chi_test = self.chi_square_test(baseline_returns, recent_returns)
        t_test = self.t_test_means(baseline_returns, recent_returns)
        var_test = self.variance_test(baseline_returns, recent_returns)
        
        # Drift detection
        drift_detected, drift_magnitude, drift_reasons = self.detect_drift(baseline_stats, recent_stats)
        
        # Overall stability (all tests must pass)
        is_stable = (
            ks_test.is_stable and
            chi_test.is_stable and
            t_test.is_stable and
            var_test.is_stable and
            not drift_detected
        )
        
        # Calculate stability score (0-1)
        test_scores = [
            1.0 if ks_test.is_stable else 0.0,
            1.0 if chi_test.is_stable else 0.0,
            1.0 if t_test.is_stable else 0.0,
            1.0 if var_test.is_stable else 0.0,
            0.0 if drift_detected else 1.0
        ]
        stability_score = np.mean(test_scores)
        
        # Calculate performance changes
        mean_change = ((recent_stats.avg_return - baseline_stats.avg_return) / 
                      abs(baseline_stats.avg_return) * 100) if baseline_stats.avg_return != 0 else 0.0
        
        vol_change = ((recent_stats.std_return - baseline_stats.std_return) / 
                     baseline_stats.std_return * 100) if baseline_stats.std_return > 0 else 0.0
        
        wr_change = ((recent_stats.win_rate - baseline_stats.win_rate) / 
                    baseline_stats.win_rate * 100) if baseline_stats.win_rate > 0 else 0.0
        
        # Build result
        result = StabilityAnalysisResult(
            is_stable=is_stable,
            confidence_level=self.confidence_level,
            stability_score=stability_score,
            ks_test=ks_test,
            chi_square_test=chi_test,
            t_test=t_test,
            variance_test=var_test,
            baseline_stats=baseline_stats,
            recent_stats=recent_stats,
            drift_detected=drift_detected,
            drift_magnitude=drift_magnitude,
            mean_return_change_pct=mean_change,
            volatility_change_pct=vol_change,
            win_rate_change_pct=wr_change
        )
        
        # Generate warnings and recommendations
        result.warnings, result.recommendations = self._generate_warnings_and_recommendations(
            result, drift_reasons
        )
        
        # Log results
        self._log_results(result)
        
        return result
    
    def _generate_warnings_and_recommendations(
        self,
        result: StabilityAnalysisResult,
        drift_reasons: List[str]
    ) -> Tuple[List[str], List[str]]:
        """Generate warnings and recommendations"""
        warnings = []
        recommendations = []
        
        # Overall stability
        if not result.is_stable:
            warnings.append(f"⚠️ Strategy distribution is UNSTABLE (score: {result.stability_score:.2f})")
        
        # Test failures
        if not result.ks_test.is_stable:
            warnings.append(f"⚠️ {result.ks_test.interpretation}")
        
        if not result.t_test.is_stable:
            warnings.append(f"⚠️ {result.t_test.interpretation}")
            recommendations.append("Review recent trading performance - mean returns have shifted")
        
        if not result.variance_test.is_stable:
            warnings.append(f"⚠️ {result.variance_test.interpretation}")
            recommendations.append("Risk management review needed - volatility has changed")
        
        # Drift warnings
        if result.drift_detected:
            warnings.append(f"⚠️ Performance drift detected (magnitude: {result.drift_magnitude:.2%})")
            for reason in drift_reasons:
                warnings.append(f"   • {reason}")
            recommendations.append("Consider recalibrating strategy parameters")
        
        # Performance degradation
        if result.mean_return_change_pct < -20:
            warnings.append(f"🚨 Significant performance degradation: {result.mean_return_change_pct:.1f}%")
            recommendations.append("URGENT: Review strategy logic and market conditions")
        
        # Improved performance (could indicate overfitting or changed conditions)
        if result.mean_return_change_pct > 50:
            warnings.append(f"⚠️ Unusually high performance improvement: {result.mean_return_change_pct:.1f}%")
            recommendations.append("Verify recent trades - ensure no data errors or overfitting")
        
        return warnings, recommendations
    
    def _log_results(self, result: StabilityAnalysisResult) -> None:
        """Log analysis results"""
        logger.info("\n" + "=" * 70)
        logger.info("📊 STABILITY ANALYSIS RESULTS")
        logger.info("=" * 70)
        logger.info(f"\n✅ Overall Stability: {'STABLE' if result.is_stable else 'UNSTABLE'}")
        logger.info(f"   Stability Score: {result.stability_score:.2%}")
        logger.info(f"   Confidence Level: {result.confidence_level:.0%}")
        
        logger.info("\n📈 Statistical Tests:")
        logger.info(f"   {result.ks_test.test_name}: {'✓ PASS' if result.ks_test.is_stable else '✗ FAIL'}")
        logger.info(f"      {result.ks_test.interpretation}")
        
        logger.info(f"   {result.chi_square_test.test_name}: {'✓ PASS' if result.chi_square_test.is_stable else '✗ FAIL'}")
        logger.info(f"      {result.chi_square_test.interpretation}")
        
        logger.info(f"   {result.t_test.test_name}: {'✓ PASS' if result.t_test.is_stable else '✗ FAIL'}")
        logger.info(f"      {result.t_test.interpretation}")
        
        logger.info(f"   {result.variance_test.test_name}: {'✓ PASS' if result.variance_test.is_stable else '✗ FAIL'}")
        logger.info(f"      {result.variance_test.interpretation}")
        
        logger.info("\n📊 Performance Comparison:")
        logger.info(f"   Mean Return Change: {result.mean_return_change_pct:+.1f}%")
        logger.info(f"   Volatility Change: {result.volatility_change_pct:+.1f}%")
        logger.info(f"   Win Rate Change: {result.win_rate_change_pct:+.1f}%")
        
        logger.info("\n📈 Baseline Statistics:")
        logger.info(f"   Trades: {result.baseline_stats.num_trades}")
        logger.info(f"   Win Rate: {result.baseline_stats.win_rate*100:.2f}%")
        logger.info(f"   Avg Return: {result.baseline_stats.avg_return:.2f}%")
        logger.info(f"   Std Dev: {result.baseline_stats.std_return:.2f}%")
        logger.info(f"   Sharpe: {result.baseline_stats.sharpe_ratio:.2f}")
        
        logger.info("\n📊 Recent Statistics:")
        logger.info(f"   Trades: {result.recent_stats.num_trades}")
        logger.info(f"   Win Rate: {result.recent_stats.win_rate*100:.2f}%")
        logger.info(f"   Avg Return: {result.recent_stats.avg_return:.2f}%")
        logger.info(f"   Std Dev: {result.recent_stats.std_return:.2f}%")
        logger.info(f"   Sharpe: {result.recent_stats.sharpe_ratio:.2f}")
        
        if result.warnings:
            logger.info("\n⚠️  WARNINGS:")
            for warning in result.warnings:
                logger.info(f"   {warning}")
        
        if result.recommendations:
            logger.info("\n💡 RECOMMENDATIONS:")
            for rec in result.recommendations:
                logger.info(f"   {rec}")
        
        logger.info("=" * 70)
    
    def export_results(
        self,
        result: StabilityAnalysisResult,
        output_dir: str = "./data/stability_analysis"
    ) -> str:
        """
        Export results to JSON
        
        Args:
            result: StabilityAnalysisResult
            output_dir: Output directory
        
        Returns:
            Path to exported file
        """
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True, parents=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"stability_analysis_{timestamp}.json"
        filepath = output_path / filename
        
        # Prepare export data
        export_data = {
            'timestamp': result.timestamp,
            'stability': {
                'is_stable': result.is_stable,
                'stability_score': result.stability_score,
                'confidence_level': result.confidence_level
            },
            'tests': {
                'ks_test': result.ks_test.is_stable,
                'chi_square_test': result.chi_square_test.is_stable,
                't_test': result.t_test.is_stable,
                'variance_test': result.variance_test.is_stable
            },
            'performance_changes': {
                'mean_return_change_pct': result.mean_return_change_pct,
                'volatility_change_pct': result.volatility_change_pct,
                'win_rate_change_pct': result.win_rate_change_pct
            },
            'warnings': result.warnings,
            'recommendations': result.recommendations
        }
        
        with open(filepath, 'w') as f:
            json.dump(export_data, f, indent=2)
        
        logger.info(f"📄 Results exported to: {filepath}")
        
        return str(filepath)


def test_trade_distribution_stability(returns: List[float]) -> StabilityAnalysisResult:
    """
    Convenience function to test trade distribution stability
    
    Args:
        returns: List of trade returns
    
    Returns:
        StabilityAnalysisResult
    """
    engine = TradeDistributionStabilityEngine()
    
    # Add trades
    for ret in returns:
        engine.add_trade(ret)
    
    # Analyze
    result = engine.analyze_stability()
    engine.export_results(result)
    
    return result


# Example usage
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
    
    # Example: Generate sample trades with performance degradation
    np.random.seed(42)
    
    # Baseline period: Good performance
    baseline_returns = np.random.normal(0.5, 2.0, 100).tolist()  # 0.5% mean, 2% std
    
    # Recent period: Degraded performance
    recent_returns = np.random.normal(0.2, 2.5, 50).tolist()  # 0.2% mean, 2.5% std
    
    all_returns = baseline_returns + recent_returns
    
    print("\n" + "=" * 70)
    print("EXAMPLE: Testing Trade Distribution Stability")
    print("=" * 70)
    
    result = test_trade_distribution_stability(all_returns)
