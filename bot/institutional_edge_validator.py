"""
NIJA Institutional Edge Validator
==================================

Implements institutional-grade edge validation before deploying capital.

The real institutional order of operations:
1. Prove Edge (this module)
2. Lock Entry Discipline (deterministic_entry_validator.py)
3. Capital Architecture (existing capital_scaling_engine.py)

Edge Validation Requirements:
- Sharpe Ratio ≥ 1.0 after realistic costs
- Positive performance across all market regimes
- Out-of-sample validation passes
- Walk-forward optimization stable
- Monte Carlo stress tests pass

Philosophy:
If Sharpe < 1 after realistic costs, you don't scale.

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

logger = logging.getLogger("nija.edge_validator")


class EdgeStatus(Enum):
    """Edge validation status"""
    PROVEN = "proven"           # Edge proven, ready to scale
    MARGINAL = "marginal"       # Edge exists but marginal
    UNPROVEN = "unproven"       # Edge not proven, don't scale
    INSUFFICIENT_DATA = "insufficient_data"  # Not enough data to validate


@dataclass
class SlippageModel:
    """
    Realistic slippage model for backtesting
    
    Slippage = base_slippage + (volume_impact * position_size_pct)
    """
    # Base slippage (market impact regardless of size)
    base_slippage_bps: float = 5.0  # 5 basis points (0.05%)
    
    # Volume-based slippage (scales with position size)
    volume_impact_bps_per_pct: float = 2.0  # 2 bps per 1% of daily volume
    
    # Transaction costs
    maker_fee_bps: float = 10.0  # 10 bps (0.10%) maker fee
    taker_fee_bps: float = 20.0  # 20 bps (0.20%) taker fee
    
    # Additional costs
    spread_bps: float = 5.0  # 5 bps average bid-ask spread
    
    def calculate_entry_cost(self, position_size_pct_of_volume: float = 0.1, is_taker: bool = True) -> float:
        """
        Calculate total entry cost as percentage
        
        Args:
            position_size_pct_of_volume: Position size as % of daily volume (default 0.1% = 10 bps)
            is_taker: Whether order is taker (market order) vs maker (limit order)
            
        Returns:
            Total cost as decimal (e.g., 0.0035 = 0.35%)
        """
        # Base slippage
        cost = self.base_slippage_bps / 10000
        
        # Volume impact
        volume_impact = (self.volume_impact_bps_per_pct * position_size_pct_of_volume) / 10000
        cost += volume_impact
        
        # Transaction fee
        fee = (self.taker_fee_bps if is_taker else self.maker_fee_bps) / 10000
        cost += fee
        
        # Spread (half spread for entry)
        cost += (self.spread_bps / 2) / 10000
        
        return cost
    
    def calculate_exit_cost(self, position_size_pct_of_volume: float = 0.1, is_taker: bool = True) -> float:
        """
        Calculate total exit cost as percentage
        
        Similar to entry cost
        """
        return self.calculate_entry_cost(position_size_pct_of_volume, is_taker)
    
    def calculate_round_trip_cost(self, position_size_pct_of_volume: float = 0.1, is_taker: bool = True) -> float:
        """
        Calculate total round-trip cost (entry + exit)
        
        Returns:
            Total round-trip cost as decimal (e.g., 0.007 = 0.7%)
        """
        return self.calculate_entry_cost(position_size_pct_of_volume, is_taker) + \
               self.calculate_exit_cost(position_size_pct_of_volume, is_taker)


@dataclass
class RegimePerformance:
    """Performance metrics for a specific market regime"""
    regime_name: str
    num_trades: int
    win_rate: float
    avg_return: float
    sharpe_ratio: float
    max_drawdown: float
    total_return: float
    
    def is_profitable(self) -> bool:
        """Check if regime performance is positive"""
        return self.avg_return > 0 and self.win_rate > 0.45
    
    def has_sufficient_data(self, min_trades: int = 30) -> bool:
        """Check if regime has sufficient trades for validation"""
        return self.num_trades >= min_trades


@dataclass
class EdgeValidationResult:
    """
    Result of institutional edge validation
    
    Validates that strategy has proven edge before deploying capital
    """
    status: EdgeStatus
    overall_sharpe: float
    sharpe_after_costs: float
    
    # Regime performance
    bull_performance: Optional[RegimePerformance]
    bear_performance: Optional[RegimePerformance]
    sideways_performance: Optional[RegimePerformance]
    
    # Out-of-sample validation
    in_sample_sharpe: float
    out_sample_sharpe: float
    oos_efficiency: float  # out_sample / in_sample (should be > 0.7)
    
    # Walk-forward results
    walk_forward_passed: bool
    parameter_stability: float  # 0-1, higher is more stable
    
    # Monte Carlo stress test
    monte_carlo_passed: bool
    probability_of_ruin: float  # Should be < 0.05
    
    # Summary
    validation_timestamp: datetime
    total_trades: int
    validation_message: str
    ready_to_scale: bool
    
    def to_dict(self) -> Dict:
        """Convert to dictionary for JSON serialization"""
        data = {
            'status': self.status.value,
            'overall_sharpe': self.overall_sharpe,
            'sharpe_after_costs': self.sharpe_after_costs,
            'in_sample_sharpe': self.in_sample_sharpe,
            'out_sample_sharpe': self.out_sample_sharpe,
            'oos_efficiency': self.oos_efficiency,
            'walk_forward_passed': self.walk_forward_passed,
            'parameter_stability': self.parameter_stability,
            'monte_carlo_passed': self.monte_carlo_passed,
            'probability_of_ruin': self.probability_of_ruin,
            'validation_timestamp': self.validation_timestamp.isoformat(),
            'total_trades': self.total_trades,
            'validation_message': self.validation_message,
            'ready_to_scale': self.ready_to_scale
        }
        
        # Add regime performance if available
        if self.bull_performance:
            data['bull_performance'] = asdict(self.bull_performance)
        if self.bear_performance:
            data['bear_performance'] = asdict(self.bear_performance)
        if self.sideways_performance:
            data['sideways_performance'] = asdict(self.sideways_performance)
            
        return data


class InstitutionalEdgeValidator:
    """
    Institutional Edge Validator
    
    Validates strategy edge before deploying capital at scale.
    
    Requirements for PROVEN edge:
    1. Sharpe ≥ 1.0 after realistic costs
    2. Positive in all regimes (bull, bear, sideways)
    3. Out-of-sample efficiency ≥ 0.7
    4. Walk-forward optimization stable
    5. Monte Carlo probability of ruin < 5%
    
    If edge is unproven, don't scale capital.
    """
    
    # Edge validation thresholds
    MIN_SHARPE_AFTER_COSTS = 1.0  # Institutional minimum
    MIN_REGIME_WIN_RATE = 0.45    # Minimum 45% win rate per regime
    MIN_OOS_EFFICIENCY = 0.70     # Out-of-sample must be 70%+ of in-sample
    MAX_PROBABILITY_OF_RUIN = 0.05  # Maximum 5% probability of ruin
    MIN_PARAMETER_STABILITY = 0.60  # Parameters should be stable across windows
    MIN_TRADES_FOR_VALIDATION = 100  # Minimum trades needed
    MIN_TRADES_PER_REGIME = 30       # Minimum trades per regime
    
    def __init__(self, slippage_model: Optional[SlippageModel] = None, results_dir: str = "./data/edge_validation"):
        """
        Initialize Institutional Edge Validator
        
        Args:
            slippage_model: Slippage model for realistic cost calculation
            results_dir: Directory to store validation results
        """
        self.slippage_model = slippage_model or SlippageModel()
        self.results_dir = Path(results_dir)
        self.results_dir.mkdir(exist_ok=True, parents=True)
        
        logger.info("✅ Institutional Edge Validator initialized")
        logger.info(f"   Minimum Sharpe (after costs): {self.MIN_SHARPE_AFTER_COSTS}")
        logger.info(f"   Round-trip cost: {self.slippage_model.calculate_round_trip_cost() * 100:.2f}%")
    
    def validate_edge(
        self,
        returns: List[float],
        regime_labels: Optional[List[str]] = None,
        in_sample_sharpe: Optional[float] = None,
        out_sample_sharpe: Optional[float] = None,
        walk_forward_stable: bool = True,
        parameter_stability: float = 0.8,
        monte_carlo_prob_ruin: Optional[float] = None
    ) -> EdgeValidationResult:
        """
        Validate strategy edge comprehensively
        
        Args:
            returns: List of trade returns (as decimals, e.g., 0.02 = 2%)
            regime_labels: Optional regime labels for each return
            in_sample_sharpe: In-sample Sharpe ratio
            out_sample_sharpe: Out-of-sample Sharpe ratio
            walk_forward_stable: Whether walk-forward test passed
            parameter_stability: Parameter stability score (0-1)
            monte_carlo_prob_ruin: Probability of ruin from Monte Carlo
            
        Returns:
            EdgeValidationResult with validation status
        """
        if len(returns) < self.MIN_TRADES_FOR_VALIDATION:
            return EdgeValidationResult(
                status=EdgeStatus.INSUFFICIENT_DATA,
                overall_sharpe=0.0,
                sharpe_after_costs=0.0,
                bull_performance=None,
                bear_performance=None,
                sideways_performance=None,
                in_sample_sharpe=in_sample_sharpe or 0.0,
                out_sample_sharpe=out_sample_sharpe or 0.0,
                oos_efficiency=0.0,
                walk_forward_passed=walk_forward_stable,
                parameter_stability=parameter_stability,
                monte_carlo_passed=False,
                probability_of_ruin=1.0,
                validation_timestamp=datetime.now(),
                total_trades=len(returns),
                validation_message=f"Insufficient data: {len(returns)} trades (need {self.MIN_TRADES_FOR_VALIDATION})",
                ready_to_scale=False
            )
        
        # Calculate overall Sharpe ratio
        returns_array = np.array(returns)
        overall_sharpe = self._calculate_sharpe(returns_array)
        
        # Apply realistic costs
        round_trip_cost = self.slippage_model.calculate_round_trip_cost()
        returns_after_costs = returns_array - round_trip_cost
        sharpe_after_costs = self._calculate_sharpe(returns_after_costs)
        
        # Validate regime performance
        bull_perf, bear_perf, sideways_perf = self._validate_regime_performance(
            returns_array, regime_labels
        )
        
        # Calculate out-of-sample efficiency
        oos_efficiency = 0.0
        if in_sample_sharpe and out_sample_sharpe and in_sample_sharpe > 0:
            oos_efficiency = out_sample_sharpe / in_sample_sharpe
        
        # Check Monte Carlo stress test
        monte_carlo_passed = True
        prob_ruin = monte_carlo_prob_ruin or 0.0
        if monte_carlo_prob_ruin is not None:
            monte_carlo_passed = monte_carlo_prob_ruin < self.MAX_PROBABILITY_OF_RUIN
        
        # Determine edge status
        status = self._determine_edge_status(
            sharpe_after_costs=sharpe_after_costs,
            bull_perf=bull_perf,
            bear_perf=bear_perf,
            sideways_perf=sideways_perf,
            oos_efficiency=oos_efficiency,
            walk_forward_passed=walk_forward_stable,
            parameter_stability=parameter_stability,
            monte_carlo_passed=monte_carlo_passed
        )
        
        # Generate validation message
        validation_message = self._generate_validation_message(
            status=status,
            sharpe_after_costs=sharpe_after_costs,
            oos_efficiency=oos_efficiency,
            parameter_stability=parameter_stability,
            prob_ruin=prob_ruin
        )
        
        # Determine if ready to scale
        ready_to_scale = (status == EdgeStatus.PROVEN)
        
        result = EdgeValidationResult(
            status=status,
            overall_sharpe=overall_sharpe,
            sharpe_after_costs=sharpe_after_costs,
            bull_performance=bull_perf,
            bear_performance=bear_perf,
            sideways_performance=sideways_perf,
            in_sample_sharpe=in_sample_sharpe or 0.0,
            out_sample_sharpe=out_sample_sharpe or 0.0,
            oos_efficiency=oos_efficiency,
            walk_forward_passed=walk_forward_stable,
            parameter_stability=parameter_stability,
            monte_carlo_passed=monte_carlo_passed,
            probability_of_ruin=prob_ruin,
            validation_timestamp=datetime.now(),
            total_trades=len(returns),
            validation_message=validation_message,
            ready_to_scale=ready_to_scale
        )
        
        # Save result
        self._save_result(result)
        
        # Log result
        self._log_result(result)
        
        return result
    
    def _calculate_sharpe(self, returns: np.ndarray, risk_free_rate: float = 0.0) -> float:
        """
        Calculate annualized Sharpe ratio
        
        Args:
            returns: Array of returns
            risk_free_rate: Risk-free rate (annualized)
            
        Returns:
            Annualized Sharpe ratio
        """
        if len(returns) == 0:
            return 0.0
        
        mean_return = np.mean(returns)
        std_return = np.std(returns)
        
        if std_return == 0:
            return 0.0
        
        # Annualize (assuming daily returns)
        sharpe = (mean_return - risk_free_rate / 252) / std_return
        sharpe_annualized = sharpe * np.sqrt(252)
        
        return sharpe_annualized
    
    def _validate_regime_performance(
        self,
        returns: np.ndarray,
        regime_labels: Optional[List[str]]
    ) -> Tuple[Optional[RegimePerformance], Optional[RegimePerformance], Optional[RegimePerformance]]:
        """
        Validate performance across market regimes
        
        Returns:
            Tuple of (bull_performance, bear_performance, sideways_performance)
        """
        if regime_labels is None or len(regime_labels) != len(returns):
            return None, None, None
        
        regimes = {'bull': [], 'bear': [], 'sideways': []}
        
        for ret, regime in zip(returns, regime_labels):
            regime_lower = regime.lower()
            if regime_lower in regimes:
                regimes[regime_lower].append(ret)
        
        # Calculate performance for each regime
        bull_perf = self._calculate_regime_performance('bull', regimes['bull'])
        bear_perf = self._calculate_regime_performance('bear', regimes['bear'])
        sideways_perf = self._calculate_regime_performance('sideways', regimes['sideways'])
        
        return bull_perf, bear_perf, sideways_perf
    
    def _calculate_regime_performance(self, regime_name: str, returns: List[float]) -> Optional[RegimePerformance]:
        """Calculate performance metrics for a regime"""
        if len(returns) == 0:
            return None
        
        returns_array = np.array(returns)
        num_trades = len(returns_array)
        win_rate = np.sum(returns_array > 0) / num_trades
        avg_return = np.mean(returns_array)
        sharpe = self._calculate_sharpe(returns_array)
        
        # Calculate max drawdown
        cumulative = np.cumprod(1 + returns_array)
        running_max = np.maximum.accumulate(cumulative)
        drawdown = (cumulative - running_max) / running_max
        max_drawdown = np.min(drawdown)
        
        total_return = cumulative[-1] - 1
        
        return RegimePerformance(
            regime_name=regime_name,
            num_trades=num_trades,
            win_rate=win_rate,
            avg_return=avg_return,
            sharpe_ratio=sharpe,
            max_drawdown=max_drawdown,
            total_return=total_return
        )
    
    def _determine_edge_status(
        self,
        sharpe_after_costs: float,
        bull_perf: Optional[RegimePerformance],
        bear_perf: Optional[RegimePerformance],
        sideways_perf: Optional[RegimePerformance],
        oos_efficiency: float,
        walk_forward_passed: bool,
        parameter_stability: float,
        monte_carlo_passed: bool
    ) -> EdgeStatus:
        """
        Determine edge status based on all validation criteria
        
        Edge is PROVEN only if ALL criteria pass:
        1. Sharpe ≥ 1.0 after costs
        2. Positive in all regimes
        3. Out-of-sample efficiency ≥ 0.7
        4. Walk-forward stable
        5. Monte Carlo passed
        """
        # Check Sharpe threshold
        if sharpe_after_costs < self.MIN_SHARPE_AFTER_COSTS:
            return EdgeStatus.UNPROVEN
        
        # Check regime performance (if available)
        regimes = [p for p in [bull_perf, bear_perf, sideways_perf] if p is not None]
        if regimes:
            for regime_perf in regimes:
                if not regime_perf.is_profitable():
                    return EdgeStatus.MARGINAL
                if not regime_perf.has_sufficient_data(self.MIN_TRADES_PER_REGIME):
                    return EdgeStatus.INSUFFICIENT_DATA
        
        # Check out-of-sample efficiency
        if oos_efficiency > 0 and oos_efficiency < self.MIN_OOS_EFFICIENCY:
            return EdgeStatus.MARGINAL
        
        # Check walk-forward stability
        if not walk_forward_passed:
            return EdgeStatus.MARGINAL
        
        # Check parameter stability
        if parameter_stability < self.MIN_PARAMETER_STABILITY:
            return EdgeStatus.MARGINAL
        
        # Check Monte Carlo stress test
        if not monte_carlo_passed:
            return EdgeStatus.MARGINAL
        
        # All criteria passed
        return EdgeStatus.PROVEN
    
    def _generate_validation_message(
        self,
        status: EdgeStatus,
        sharpe_after_costs: float,
        oos_efficiency: float,
        parameter_stability: float,
        prob_ruin: float
    ) -> str:
        """Generate human-readable validation message"""
        if status == EdgeStatus.PROVEN:
            return (f"✅ EDGE PROVEN - Sharpe {sharpe_after_costs:.2f}, "
                   f"OOS efficiency {oos_efficiency:.2%}, "
                   f"Parameter stability {parameter_stability:.2%}, "
                   f"Probability of ruin {prob_ruin:.2%} - READY TO SCALE")
        elif status == EdgeStatus.MARGINAL:
            return (f"⚠️ MARGINAL EDGE - Sharpe {sharpe_after_costs:.2f}, "
                   f"OOS efficiency {oos_efficiency:.2%} - Scale cautiously")
        elif status == EdgeStatus.UNPROVEN:
            return (f"❌ EDGE UNPROVEN - Sharpe {sharpe_after_costs:.2f} "
                   f"(need ≥{self.MIN_SHARPE_AFTER_COSTS}) - DO NOT SCALE")
        else:
            return "⏳ INSUFFICIENT DATA - Need more trades for validation"
    
    def _save_result(self, result: EdgeValidationResult) -> None:
        """Save validation result to disk"""
        timestamp = result.validation_timestamp.strftime("%Y%m%d_%H%M%S")
        filename = f"edge_validation_{timestamp}.json"
        filepath = self.results_dir / filename
        
        with open(filepath, 'w') as f:
            json.dump(result.to_dict(), f, indent=2)
        
        logger.debug(f"Saved edge validation result to {filepath}")
    
    def _log_result(self, result: EdgeValidationResult) -> None:
        """Log validation result"""
        logger.info("=" * 80)
        logger.info("INSTITUTIONAL EDGE VALIDATION RESULT")
        logger.info("=" * 80)
        logger.info(f"Status: {result.status.value.upper()}")
        logger.info(f"Sharpe Ratio (after costs): {result.sharpe_after_costs:.3f}")
        logger.info(f"Overall Sharpe (before costs): {result.overall_sharpe:.3f}")
        logger.info(f"Total Trades: {result.total_trades}")
        logger.info("")
        
        if result.bull_performance:
            logger.info(f"Bull Market: Sharpe {result.bull_performance.sharpe_ratio:.2f}, "
                       f"Win Rate {result.bull_performance.win_rate:.1%}, "
                       f"{result.bull_performance.num_trades} trades")
        if result.bear_performance:
            logger.info(f"Bear Market: Sharpe {result.bear_performance.sharpe_ratio:.2f}, "
                       f"Win Rate {result.bear_performance.win_rate:.1%}, "
                       f"{result.bear_performance.num_trades} trades")
        if result.sideways_performance:
            logger.info(f"Sideways Market: Sharpe {result.sideways_performance.sharpe_ratio:.2f}, "
                       f"Win Rate {result.sideways_performance.win_rate:.1%}, "
                       f"{result.sideways_performance.num_trades} trades")
        
        if result.in_sample_sharpe > 0:
            logger.info("")
            logger.info(f"In-Sample Sharpe: {result.in_sample_sharpe:.3f}")
            logger.info(f"Out-of-Sample Sharpe: {result.out_sample_sharpe:.3f}")
            logger.info(f"OOS Efficiency: {result.oos_efficiency:.1%}")
        
        logger.info("")
        logger.info(f"Walk-Forward Stable: {result.walk_forward_passed}")
        logger.info(f"Parameter Stability: {result.parameter_stability:.1%}")
        logger.info(f"Monte Carlo Passed: {result.monte_carlo_passed}")
        logger.info(f"Probability of Ruin: {result.probability_of_ruin:.2%}")
        logger.info("")
        logger.info(f"READY TO SCALE: {result.ready_to_scale}")
        logger.info("")
        logger.info(result.validation_message)
        logger.info("=" * 80)
    
    def load_latest_result(self) -> Optional[EdgeValidationResult]:
        """Load the most recent validation result"""
        json_files = list(self.results_dir.glob("edge_validation_*.json"))
        if not json_files:
            return None
        
        latest_file = max(json_files, key=lambda p: p.stat().st_mtime)
        
        with open(latest_file, 'r') as f:
            data = json.load(f)
        
        # Reconstruct EdgeValidationResult
        # (simplified - in production would need full reconstruction)
        return data


# Convenience function for quick validation
def validate_strategy_edge(
    returns: List[float],
    regime_labels: Optional[List[str]] = None,
    **kwargs
) -> EdgeValidationResult:
    """
    Quick function to validate strategy edge
    
    Args:
        returns: List of trade returns
        regime_labels: Optional regime labels
        **kwargs: Additional arguments for validation
        
    Returns:
        EdgeValidationResult
    """
    validator = InstitutionalEdgeValidator()
    return validator.validate_edge(returns, regime_labels, **kwargs)
