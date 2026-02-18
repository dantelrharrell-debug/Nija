"""
NIJA Alpha Validation Framework
================================

Real funds build in this order:
1. Alpha discovery (this module)
2. Robust statistical validation
3. Regime testing  
4. Monte Carlo stress testing
5. Then capital scaling architecture (already exists)
6. Then risk throttles (already exists)

This module implements steps 1-4 that must be proven BEFORE using 
the existing capital scaling and risk management infrastructure.

Philosophy:
Prove edge exists. Then scale edge. Never scale unproven strategies.

Author: NIJA Trading Systems
Version: 1.0
Date: February 18, 2026
"""

import logging
import json
import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from enum import Enum

logger = logging.getLogger("nija.alpha_validation")


class AlphaStatus(Enum):
    """Alpha validation status"""
    PROVEN = "proven"                    # All 4 steps passed
    STATISTICAL_FAIL = "statistical_fail"  # Failed step 2
    REGIME_FAIL = "regime_fail"          # Failed step 3
    STRESS_FAIL = "stress_fail"          # Failed step 4
    INSUFFICIENT_DATA = "insufficient_data"


@dataclass
class AlphaDiscovery:
    """
    Step 1: Alpha Discovery
    
    Identifies if strategy has raw alpha (positive expectancy)
    before any advanced testing.
    """
    total_trades: int
    win_rate: float
    avg_win: float
    avg_loss: float
    profit_factor: float  # Gross profit / Gross loss
    expectancy: float     # Average $ per trade
    
    # Raw performance
    total_return: float
    max_drawdown: float
    
    def has_alpha(self) -> bool:
        """
        Check if raw alpha exists
        
        Requirements:
        - Win rate > 50% OR profit factor > 1.5
        - Positive expectancy
        - Total return > 0
        """
        has_edge = (self.win_rate > 0.50) or (self.profit_factor > 1.5)
        return has_edge and self.expectancy > 0 and self.total_return > 0


@dataclass
class StatisticalValidation:
    """
    Step 2: Robust Statistical Validation
    
    Proves alpha is statistically significant and robust to costs.
    """
    # Sharpe ratios
    sharpe_raw: float
    sharpe_after_costs: float
    
    # Sortino (downside-adjusted Sharpe)
    sortino_ratio: float
    
    # Calmar (return / max drawdown)
    calmar_ratio: float
    
    # Statistical significance
    t_statistic: float
    p_value: float
    
    # Cost analysis
    avg_cost_per_trade: float
    total_costs: float
    net_return_after_costs: float
    
    def is_statistically_valid(self, min_sharpe: float = 1.0) -> bool:
        """
        Check if statistically valid
        
        Requirements:
        - Sharpe ≥ 1.0 after costs (institutional minimum)
        - Positive Sortino (handles downside properly)
        - p-value < 0.05 (statistically significant)
        - Net return > 0 after costs
        """
        return (
            self.sharpe_after_costs >= min_sharpe and
            self.sortino_ratio > 0 and
            self.p_value < 0.05 and
            self.net_return_after_costs > 0
        )


@dataclass  
class RegimeTesting:
    """
    Step 3: Regime Testing
    
    Validates strategy performs across all market conditions.
    """
    bull_sharpe: float
    bull_win_rate: float
    bull_trades: int
    
    bear_sharpe: float
    bear_win_rate: float
    bear_trades: int
    
    sideways_sharpe: float
    sideways_win_rate: float
    sideways_trades: int
    
    # Overall regime robustness
    worst_regime_sharpe: float
    regime_consistency: float  # Std dev of Sharpe across regimes (lower is better)
    
    def passes_regime_test(self, min_sharpe: float = 0.5, min_trades_per_regime: int = 30) -> bool:
        """
        Check if passes regime testing
        
        Requirements:
        - Positive Sharpe in ALL regimes
        - Minimum trades per regime (sufficient data)
        - Worst regime Sharpe ≥ 0.5 (acceptable minimum)
        """
        sufficient_data = (
            self.bull_trades >= min_trades_per_regime and
            self.bear_trades >= min_trades_per_regime and
            self.sideways_trades >= min_trades_per_regime
        )
        
        all_positive = (
            self.bull_sharpe > 0 and
            self.bear_sharpe > 0 and
            self.sideways_sharpe > 0
        )
        
        worst_acceptable = self.worst_regime_sharpe >= min_sharpe
        
        return sufficient_data and all_positive and worst_acceptable


@dataclass
class MonteCarloStress:
    """
    Step 4: Monte Carlo Stress Testing
    
    Validates strategy survives adverse conditions through simulation.
    """
    num_simulations: int
    
    # Survivability metrics
    probability_of_ruin: float      # Prob of losing >50% capital
    probability_of_10pct_loss: float  # Prob of losing >10%
    
    # Distribution of outcomes
    median_return: float
    percentile_5: float   # 5th percentile (worst outcomes)
    percentile_95: float  # 95th percentile (best outcomes)
    
    # Worst-case stress
    worst_drawdown: float
    worst_return: float
    
    # Recovery analysis
    avg_recovery_time_days: float
    max_recovery_time_days: float
    
    def passes_stress_test(
        self, 
        max_prob_ruin: float = 0.05,
        max_prob_10pct_loss: float = 0.20,
        max_worst_drawdown: float = -0.30
    ) -> bool:
        """
        Check if passes Monte Carlo stress test
        
        Requirements:
        - Probability of ruin < 5%
        - Probability of 10% loss < 20%
        - Worst drawdown > -30% (survives worst case)
        - 5th percentile positive (even bad luck is survivable)
        """
        return (
            self.probability_of_ruin < max_prob_ruin and
            self.probability_of_10pct_loss < max_prob_10pct_loss and
            self.worst_drawdown > max_worst_drawdown and
            self.percentile_5 > -0.10  # Even worst 5% doesn't lose >10%
        )


@dataclass
class AlphaValidationResult:
    """
    Complete alpha validation result (Steps 1-4)
    
    Strategy is ready for capital scaling ONLY if all 4 steps pass.
    """
    status: AlphaStatus
    
    # Step 1: Alpha Discovery
    alpha_discovery: AlphaDiscovery
    step1_passed: bool
    
    # Step 2: Statistical Validation
    statistical_validation: StatisticalValidation
    step2_passed: bool
    
    # Step 3: Regime Testing
    regime_testing: RegimeTesting
    step3_passed: bool
    
    # Step 4: Monte Carlo Stress
    monte_carlo_stress: MonteCarloStress
    step4_passed: bool
    
    # Overall result
    ready_for_capital_scaling: bool
    validation_timestamp: datetime
    validation_message: str
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        return {
            'status': self.status.value,
            'step1_passed': self.step1_passed,
            'step2_passed': self.step2_passed,
            'step3_passed': self.step3_passed,
            'step4_passed': self.step4_passed,
            'ready_for_capital_scaling': self.ready_for_capital_scaling,
            'validation_timestamp': self.validation_timestamp.isoformat(),
            'validation_message': self.validation_message,
            'alpha_discovery': asdict(self.alpha_discovery),
            'statistical_validation': asdict(self.statistical_validation),
            'regime_testing': asdict(self.regime_testing),
            'monte_carlo_stress': asdict(self.monte_carlo_stress)
        }


class AlphaValidationFramework:
    """
    Complete Alpha Validation Framework
    
    Implements the 4-step validation sequence that MUST pass
    before capital scaling infrastructure is activated.
    
    Sequence:
    1. Alpha Discovery - Does raw edge exist?
    2. Statistical Validation - Is it statistically significant after costs?
    3. Regime Testing - Does it work in all market conditions?
    4. Monte Carlo Stress - Does it survive adverse scenarios?
    
    Only after ALL 4 pass should capital scaling be enabled.
    """
    
    def __init__(self, results_dir: str = "./data/alpha_validation"):
        """
        Initialize Alpha Validation Framework
        
        Args:
            results_dir: Directory to store validation results
        """
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(exist_ok=True, parents=True)
        
        logger.info("=" * 80)
        logger.info("ALPHA VALIDATION FRAMEWORK")
        logger.info("=" * 80)
        logger.info("Real funds build in this order:")
        logger.info("  1. Alpha discovery")
        logger.info("  2. Robust statistical validation")
        logger.info("  3. Regime testing")
        logger.info("  4. Monte Carlo stress testing")
        logger.info("  5. Then capital scaling (already built)")
        logger.info("  6. Then risk throttles (already built)")
        logger.info("")
        logger.info("This framework validates steps 1-4 BEFORE scaling capital.")
        logger.info("=" * 80)
    
    def validate_strategy(
        self,
        trade_returns: List[float],
        trade_pnls: List[float],
        regime_labels: List[str],
        entry_costs: Optional[List[float]] = None,
        initial_capital: float = 100000.0
    ) -> AlphaValidationResult:
        """
        Run complete 4-step alpha validation
        
        Args:
            trade_returns: List of trade returns (as decimals, e.g., 0.02 = 2%)
            trade_pnls: List of trade P&Ls in dollars
            regime_labels: Market regime for each trade ('bull', 'bear', 'sideways')
            entry_costs: Optional list of entry costs per trade
            initial_capital: Initial capital for simulations
            
        Returns:
            AlphaValidationResult with complete validation
        """
        logger.info("Starting 4-step alpha validation...")
        
        # Convert to numpy arrays
        returns = np.array(trade_returns)
        pnls = np.array(trade_pnls)
        
        # Step 1: Alpha Discovery
        logger.info("\n[STEP 1/4] Alpha Discovery...")
        alpha_discovery = self._step1_alpha_discovery(returns, pnls)
        step1_passed = alpha_discovery.has_alpha()
        logger.info(f"  Result: {'✅ PASS' if step1_passed else '❌ FAIL'}")
        
        if not step1_passed:
            return self._create_failed_result(
                AlphaStatus.STATISTICAL_FAIL,
                alpha_discovery, None, None, None,
                step1_passed, False, False, False,
                "Failed Step 1: No alpha discovered"
            )
        
        # Step 2: Statistical Validation
        logger.info("\n[STEP 2/4] Robust Statistical Validation...")
        statistical_validation = self._step2_statistical_validation(returns, pnls, entry_costs)
        step2_passed = statistical_validation.is_statistically_valid()
        logger.info(f"  Result: {'✅ PASS' if step2_passed else '❌ FAIL'}")
        
        if not step2_passed:
            return self._create_failed_result(
                AlphaStatus.STATISTICAL_FAIL,
                alpha_discovery, statistical_validation, None, None,
                step1_passed, step2_passed, False, False,
                f"Failed Step 2: Sharpe {statistical_validation.sharpe_after_costs:.2f} < 1.0 after costs"
            )
        
        # Step 3: Regime Testing
        logger.info("\n[STEP 3/4] Regime Testing...")
        regime_testing = self._step3_regime_testing(returns, regime_labels)
        step3_passed = regime_testing.passes_regime_test()
        logger.info(f"  Result: {'✅ PASS' if step3_passed else '❌ FAIL'}")
        
        if not step3_passed:
            return self._create_failed_result(
                AlphaStatus.REGIME_FAIL,
                alpha_discovery, statistical_validation, regime_testing, None,
                step1_passed, step2_passed, step3_passed, False,
                f"Failed Step 3: Worst regime Sharpe {regime_testing.worst_regime_sharpe:.2f}"
            )
        
        # Step 4: Monte Carlo Stress Testing
        logger.info("\n[STEP 4/4] Monte Carlo Stress Testing...")
        monte_carlo_stress = self._step4_monte_carlo_stress(returns, initial_capital)
        step4_passed = monte_carlo_stress.passes_stress_test()
        logger.info(f"  Result: {'✅ PASS' if step4_passed else '❌ FAIL'}")
        
        if not step4_passed:
            return self._create_failed_result(
                AlphaStatus.STRESS_FAIL,
                alpha_discovery, statistical_validation, regime_testing, monte_carlo_stress,
                step1_passed, step2_passed, step3_passed, step4_passed,
                f"Failed Step 4: Probability of ruin {monte_carlo_stress.probability_of_ruin:.2%}"
            )
        
        # All steps passed!
        result = AlphaValidationResult(
            status=AlphaStatus.PROVEN,
            alpha_discovery=alpha_discovery,
            step1_passed=step1_passed,
            statistical_validation=statistical_validation,
            step2_passed=step2_passed,
            regime_testing=regime_testing,
            step3_passed=step3_passed,
            monte_carlo_stress=monte_carlo_stress,
            step4_passed=step4_passed,
            ready_for_capital_scaling=True,
            validation_timestamp=datetime.now(),
            validation_message="✅ ALL 4 STEPS PASSED - READY FOR CAPITAL SCALING"
        )
        
        # Save and log result
        self._save_result(result)
        self._log_result(result)
        
        return result
    
    def _step1_alpha_discovery(self, returns: np.ndarray, pnls: np.ndarray) -> AlphaDiscovery:
        """
        Step 1: Alpha Discovery
        
        Checks if strategy has raw alpha (positive expectancy).
        """
        total_trades = len(returns)
        wins = returns > 0
        losses = returns <= 0
        
        win_rate = np.sum(wins) / total_trades if total_trades > 0 else 0
        
        avg_win = np.mean(returns[wins]) if np.sum(wins) > 0 else 0
        avg_loss = np.mean(returns[losses]) if np.sum(losses) > 0 else 0
        
        gross_profit = np.sum(pnls[wins]) if np.sum(wins) > 0 else 0
        gross_loss = abs(np.sum(pnls[losses])) if np.sum(losses) > 0 else 0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0
        
        expectancy = np.mean(pnls)
        
        # Calculate total return
        cumulative = np.cumprod(1 + returns)
        total_return = cumulative[-1] - 1 if len(cumulative) > 0 else 0
        
        # Calculate max drawdown
        running_max = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - running_max) / running_max
        max_drawdown = np.min(drawdown) if len(drawdown) > 0 else 0
        
        return AlphaDiscovery(
            total_trades=total_trades,
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            profit_factor=profit_factor,
            expectancy=expectancy,
            total_return=total_return,
            max_drawdown=max_drawdown
        )
    
    def _step2_statistical_validation(
        self, 
        returns: np.ndarray,
        pnls: np.ndarray,
        entry_costs: Optional[List[float]]
    ) -> StatisticalValidation:
        """
        Step 2: Robust Statistical Validation
        
        Validates statistical significance and robustness to costs.
        """
        # Calculate Sharpe ratio (raw)
        sharpe_raw = self._calculate_sharpe(returns)
        
        # Calculate costs
        if entry_costs is None:
            # Estimate costs: 0.35% round-trip (typical crypto)
            avg_cost_per_trade = 0.0035
            entry_costs = [avg_cost_per_trade] * len(returns)
        
        avg_cost_per_trade = np.mean(entry_costs)
        total_costs = np.sum(entry_costs)
        
        # Apply costs
        returns_after_costs = returns - np.array(entry_costs)
        sharpe_after_costs = self._calculate_sharpe(returns_after_costs)
        
        # Calculate net return
        cumulative_after_costs = np.cumprod(1 + returns_after_costs)
        net_return_after_costs = cumulative_after_costs[-1] - 1 if len(cumulative_after_costs) > 0 else 0
        
        # Calculate Sortino (downside-adjusted Sharpe)
        sortino_ratio = self._calculate_sortino(returns_after_costs)
        
        # Calculate Calmar (return / max drawdown)
        running_max = np.maximum.accumulate(cumulative_after_costs)
        drawdown = (cumulative_after_costs - running_max) / running_max
        max_drawdown = abs(np.min(drawdown)) if len(drawdown) > 0 else 1
        calmar_ratio = (net_return_after_costs / max_drawdown) if max_drawdown > 0 else 0
        
        # Statistical significance (t-test)
        if len(returns_after_costs) > 1:
            mean_return = np.mean(returns_after_costs)
            std_return = np.std(returns_after_costs, ddof=1)
            t_statistic = (mean_return / std_return) * np.sqrt(len(returns_after_costs))
            # Approximate p-value (two-tailed)
            from scipy import stats
            p_value = 2 * (1 - stats.t.cdf(abs(t_statistic), len(returns_after_costs) - 1))
        else:
            t_statistic = 0
            p_value = 1.0
        
        return StatisticalValidation(
            sharpe_raw=sharpe_raw,
            sharpe_after_costs=sharpe_after_costs,
            sortino_ratio=sortino_ratio,
            calmar_ratio=calmar_ratio,
            t_statistic=t_statistic,
            p_value=p_value,
            avg_cost_per_trade=avg_cost_per_trade,
            total_costs=total_costs,
            net_return_after_costs=net_return_after_costs
        )
    
    def _step3_regime_testing(self, returns: np.ndarray, regime_labels: List[str]) -> RegimeTesting:
        """
        Step 3: Regime Testing
        
        Validates performance across bull, bear, and sideways markets.
        """
        # Segment by regime
        regimes = {'bull': [], 'bear': [], 'sideways': []}
        
        for ret, regime in zip(returns, regime_labels):
            regime_lower = regime.lower()
            if regime_lower in regimes:
                regimes[regime_lower].append(ret)
        
        # Calculate metrics per regime
        bull_returns = np.array(regimes['bull']) if regimes['bull'] else np.array([0])
        bear_returns = np.array(regimes['bear']) if regimes['bear'] else np.array([0])
        sideways_returns = np.array(regimes['sideways']) if regimes['sideways'] else np.array([0])
        
        bull_sharpe = self._calculate_sharpe(bull_returns)
        bull_win_rate = np.sum(bull_returns > 0) / len(bull_returns) if len(bull_returns) > 0 else 0
        bull_trades = len(bull_returns)
        
        bear_sharpe = self._calculate_sharpe(bear_returns)
        bear_win_rate = np.sum(bear_returns > 0) / len(bear_returns) if len(bear_returns) > 0 else 0
        bear_trades = len(bear_returns)
        
        sideways_sharpe = self._calculate_sharpe(sideways_returns)
        sideways_win_rate = np.sum(sideways_returns > 0) / len(sideways_returns) if len(sideways_returns) > 0 else 0
        sideways_trades = len(sideways_returns)
        
        # Worst regime
        sharpes = [bull_sharpe, bear_sharpe, sideways_sharpe]
        worst_regime_sharpe = min(sharpes)
        regime_consistency = np.std(sharpes) if len(sharpes) > 1 else 0
        
        return RegimeTesting(
            bull_sharpe=bull_sharpe,
            bull_win_rate=bull_win_rate,
            bull_trades=bull_trades,
            bear_sharpe=bear_sharpe,
            bear_win_rate=bear_win_rate,
            bear_trades=bear_trades,
            sideways_sharpe=sideways_sharpe,
            sideways_win_rate=sideways_win_rate,
            sideways_trades=sideways_trades,
            worst_regime_sharpe=worst_regime_sharpe,
            regime_consistency=regime_consistency
        )
    
    def _step4_monte_carlo_stress(self, returns: np.ndarray, initial_capital: float) -> MonteCarloStress:
        """
        Step 4: Monte Carlo Stress Testing
        
        Simulates thousands of scenarios to validate survivability.
        """
        num_simulations = 1000
        num_trades = len(returns)
        
        # Statistics of returns
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        
        # Run simulations
        final_capitals = []
        max_drawdowns = []
        
        for _ in range(num_simulations):
            # Simulate returns (with randomness)
            simulated_returns = np.random.normal(mean_return, std_return * 1.2, num_trades)
            
            # Calculate equity curve
            equity = initial_capital * np.cumprod(1 + simulated_returns)
            final_capital = equity[-1]
            final_capitals.append(final_capital)
            
            # Calculate max drawdown
            running_max = np.maximum.accumulate(equity)
            drawdown = (equity - running_max) / running_max
            max_dd = np.min(drawdown)
            max_drawdowns.append(max_dd)
        
        final_capitals = np.array(final_capitals)
        max_drawdowns = np.array(max_drawdowns)
        
        # Calculate metrics
        probability_of_ruin = np.sum(final_capitals < initial_capital * 0.5) / num_simulations
        probability_of_10pct_loss = np.sum(final_capitals < initial_capital * 0.9) / num_simulations
        
        median_return = np.median((final_capitals - initial_capital) / initial_capital)
        percentile_5 = np.percentile((final_capitals - initial_capital) / initial_capital, 5)
        percentile_95 = np.percentile((final_capitals - initial_capital) / initial_capital, 95)
        
        worst_drawdown = np.min(max_drawdowns)
        worst_return = np.min((final_capitals - initial_capital) / initial_capital)
        
        # Estimate recovery time (simplified)
        avg_recovery_time_days = 30  # Placeholder
        max_recovery_time_days = 90  # Placeholder
        
        return MonteCarloStress(
            num_simulations=num_simulations,
            probability_of_ruin=probability_of_ruin,
            probability_of_10pct_loss=probability_of_10pct_loss,
            median_return=median_return,
            percentile_5=percentile_5,
            percentile_95=percentile_95,
            worst_drawdown=worst_drawdown,
            worst_return=worst_return,
            avg_recovery_time_days=avg_recovery_time_days,
            max_recovery_time_days=max_recovery_time_days
        )
    
    def _calculate_sharpe(self, returns: np.ndarray, risk_free_rate: float = 0.0) -> float:
        """Calculate annualized Sharpe ratio"""
        if len(returns) == 0:
            return 0.0
        
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        
        if std_return == 0:
            return 0.0
        
        sharpe = (mean_return - risk_free_rate / 252) / std_return
        sharpe_annualized = sharpe * np.sqrt(252)
        
        return sharpe_annualized
    
    def _calculate_sortino(self, returns: np.ndarray, risk_free_rate: float = 0.0) -> float:
        """Calculate Sortino ratio (downside-adjusted Sharpe)"""
        if len(returns) == 0:
            return 0.0
        
        mean_return = np.mean(returns)
        downside_returns = returns[returns < 0]
        
        if len(downside_returns) == 0:
            return float('inf')
        
        downside_std = np.std(downside_returns)
        
        if downside_std == 0:
            return 0.0
        
        sortino = (mean_return - risk_free_rate / 252) / downside_std
        sortino_annualized = sortino * np.sqrt(252)
        
        return sortino_annualized
    
    def _create_failed_result(
        self,
        status: AlphaStatus,
        alpha_discovery: AlphaDiscovery,
        statistical: Optional[StatisticalValidation],
        regime: Optional[RegimeTesting],
        monte_carlo: Optional[MonteCarloStress],
        step1: bool, step2: bool, step3: bool, step4: bool,
        message: str
    ) -> AlphaValidationResult:
        """Create failed validation result"""
        # Create placeholder for missing steps
        if not statistical:
            statistical = StatisticalValidation(0, 0, 0, 0, 0, 1.0, 0, 0, 0)
        if not regime:
            regime = RegimeTesting(0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0)
        if not monte_carlo:
            monte_carlo = MonteCarloStress(0, 1.0, 1.0, 0, 0, 0, -1.0, -1.0, 0, 0)
        
        result = AlphaValidationResult(
            status=status,
            alpha_discovery=alpha_discovery,
            step1_passed=step1,
            statistical_validation=statistical,
            step2_passed=step2,
            regime_testing=regime,
            step3_passed=step3,
            monte_carlo_stress=monte_carlo,
            step4_passed=step4,
            ready_for_capital_scaling=False,
            validation_timestamp=datetime.now(),
            validation_message=message
        )
        
        self._save_result(result)
        self._log_result(result)
        
        return result
    
    def _save_result(self, result: AlphaValidationResult) -> None:
        """Save validation result to disk"""
        timestamp = result.validation_timestamp.strftime("%Y%m%d_%H%M%S")
        filename = f"alpha_validation_{timestamp}.json"
        filepath = self.results_dir / filename
        
        with open(filepath, 'w') as f:
            json.dump(result.to_dict(), f, indent=2)
        
        logger.debug(f"Saved alpha validation result to {filepath}")
    
    def _log_result(self, result: AlphaValidationResult) -> None:
        """Log validation result"""
        logger.info("")
        logger.info("=" * 80)
        logger.info("ALPHA VALIDATION RESULT")
        logger.info("=" * 80)
        logger.info(f"Status: {result.status.value.upper()}")
        logger.info(f"Ready for Capital Scaling: {'✅ YES' if result.ready_for_capital_scaling else '❌ NO'}")
        logger.info("")
        logger.info(f"[1/4] Alpha Discovery: {'✅ PASS' if result.step1_passed else '❌ FAIL'}")
        logger.info(f"      Win Rate: {result.alpha_discovery.win_rate:.1%}")
        logger.info(f"      Profit Factor: {result.alpha_discovery.profit_factor:.2f}")
        logger.info(f"      Expectancy: ${result.alpha_discovery.expectancy:.2f}")
        logger.info("")
        logger.info(f"[2/4] Statistical Validation: {'✅ PASS' if result.step2_passed else '❌ FAIL'}")
        logger.info(f"      Sharpe (after costs): {result.statistical_validation.sharpe_after_costs:.3f}")
        logger.info(f"      Sortino: {result.statistical_validation.sortino_ratio:.3f}")
        logger.info(f"      p-value: {result.statistical_validation.p_value:.4f}")
        logger.info("")
        logger.info(f"[3/4] Regime Testing: {'✅ PASS' if result.step3_passed else '❌ FAIL'}")
        logger.info(f"      Bull Sharpe: {result.regime_testing.bull_sharpe:.2f} ({result.regime_testing.bull_trades} trades)")
        logger.info(f"      Bear Sharpe: {result.regime_testing.bear_sharpe:.2f} ({result.regime_testing.bear_trades} trades)")
        logger.info(f"      Sideways Sharpe: {result.regime_testing.sideways_sharpe:.2f} ({result.regime_testing.sideways_trades} trades)")
        logger.info("")
        logger.info(f"[4/4] Monte Carlo Stress: {'✅ PASS' if result.step4_passed else '❌ FAIL'}")
        logger.info(f"      Probability of Ruin: {result.monte_carlo_stress.probability_of_ruin:.2%}")
        logger.info(f"      5th Percentile Return: {result.monte_carlo_stress.percentile_5:.1%}")
        logger.info(f"      Worst Drawdown: {result.monte_carlo_stress.worst_drawdown:.1%}")
        logger.info("")
        logger.info(result.validation_message)
        logger.info("=" * 80)
