"""
NIJA Monte Carlo Portfolio Simulator

Validates structural survivability through randomization of:
- Strategy returns
- Correlations
- Regime shifts
- Volatility spikes

This is fund discipline testing.

Author: NIJA Trading Systems
Version: 1.0
Date: January 29, 2026
"""

import logging
import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
from pathlib import Path

logger = logging.getLogger("nija.monte_carlo")


@dataclass
class SimulationParameters:
    """Monte Carlo simulation parameters"""
    num_simulations: int = 1000
    num_days: int = 252  # 1 year
    initial_capital: float = 100000.0

    # Return parameters
    mean_return_daily: float = 0.001  # 0.1% daily
    volatility_daily: float = 0.02  # 2% daily vol

    # Correlation parameters
    min_correlation: float = -0.3
    max_correlation: float = 0.7

    # Regime parameters
    regime_shift_probability: float = 0.05  # 5% chance per day

    # Volatility spike parameters
    vol_spike_probability: float = 0.02  # 2% chance per day
    vol_spike_multiplier: float = 3.0  # 3x normal vol during spike


@dataclass
class SimulationResults:
    """Results from Monte Carlo simulation"""
    # Summary statistics
    mean_final_capital: float
    median_final_capital: float
    std_final_capital: float
    percentile_5: float
    percentile_95: float

    # Risk metrics
    max_drawdown_mean: float
    max_drawdown_worst: float
    probability_of_ruin: float  # Probability of losing >50%

    # All simulation paths
    all_final_capitals: List[float] = field(default_factory=list)
    all_max_drawdowns: List[float] = field(default_factory=list)
    equity_curves: List[List[float]] = field(default_factory=list)


class MonteCarloPortfolioSimulator:
    """
    Monte Carlo simulation for portfolio structural survivability

    Randomizes:
    - Strategy returns (with realistic distributions)
    - Correlations (varying correlation structures)
    - Regime shifts (sudden market changes)
    - Volatility spikes (crisis events)

    Validates:
    - Structural survivability under stress
    - Drawdown resistance
    - Recovery capability
    - Risk control effectiveness
    """

    def __init__(self, params: Optional[SimulationParameters] = None):
        """
        Initialize Monte Carlo simulator

        Args:
            params: Simulation parameters (uses defaults if not provided)
        """
        self.params = params or SimulationParameters()

        logger.info(f"✅ Monte Carlo Simulator initialized")
        logger.info(f"   Simulations: {self.params.num_simulations}")
        logger.info(f"   Days: {self.params.num_days}")
        logger.info(f"   Initial Capital: ${self.params.initial_capital:,.2f}")

    def generate_correlated_returns(self,
                                    num_strategies: int,
                                    num_days: int,
                                    correlation_matrix: Optional[np.ndarray] = None) -> np.ndarray:
        """
        Generate correlated strategy returns

        Args:
            num_strategies: Number of strategies
            num_days: Number of days
            correlation_matrix: Custom correlation matrix (optional)

        Returns:
            Matrix of returns (strategies x days)
        """
        if correlation_matrix is None:
            # Generate random correlation matrix
            correlation_matrix = self._generate_random_correlation_matrix(num_strategies)

        # Generate uncorrelated returns
        uncorrelated = np.random.normal(
            self.params.mean_return_daily,
            self.params.volatility_daily,
            (num_strategies, num_days)
        )

        # Apply correlation using Cholesky decomposition
        cholesky = np.linalg.cholesky(correlation_matrix)
        correlated = cholesky @ uncorrelated

        return correlated

    def _generate_random_correlation_matrix(self, size: int) -> np.ndarray:
        """Generate random positive semi-definite correlation matrix"""
        # Generate random correlations
        correlations = np.random.uniform(
            self.params.min_correlation,
            self.params.max_correlation,
            (size, size)
        )

        # Make symmetric
        correlations = (correlations + correlations.T) / 2

        # Set diagonal to 1
        np.fill_diagonal(correlations, 1.0)

        # Ensure positive semi-definite (project to nearest valid correlation matrix)
        eigenvalues, eigenvectors = np.linalg.eigh(correlations)
        eigenvalues = np.maximum(eigenvalues, 0.01)  # Ensure positive
        correlations = eigenvectors @ np.diag(eigenvalues) @ eigenvectors.T

        # Rescale to correlation matrix
        d = np.sqrt(np.diag(correlations))
        correlations = correlations / np.outer(d, d)

        return correlations

    def simulate_regime_shifts(self, num_days: int) -> List[int]:
        """
        Simulate regime shifts over time

        Args:
            num_days: Number of days

        Returns:
            List of regime indices (0-4 for 5 regimes)
        """
        regimes = [0]  # Start in regime 0

        for _ in range(num_days - 1):
            # Probability of regime shift
            if np.random.random() < self.params.regime_shift_probability:
                # Shift to random regime
                new_regime = np.random.randint(0, 5)
                regimes.append(new_regime)
            else:
                # Stay in current regime
                regimes.append(regimes[-1])

        return regimes

    def simulate_volatility_spikes(self, num_days: int) -> np.ndarray:
        """
        Simulate volatility spikes

        Args:
            num_days: Number of days

        Returns:
            Array of volatility multipliers
        """
        vol_multipliers = np.ones(num_days)

        for i in range(num_days):
            if np.random.random() < self.params.vol_spike_probability:
                vol_multipliers[i] = self.params.vol_spike_multiplier

        return vol_multipliers

    def run_single_simulation(self, num_strategies: int = 3) -> Tuple[float, float, List[float]]:
        """
        Run single Monte Carlo simulation

        Args:
            num_strategies: Number of strategies in portfolio

        Returns:
            Tuple of (final_capital, max_drawdown, equity_curve)
        """
        # Generate returns
        returns = self.generate_correlated_returns(num_strategies, self.params.num_days)

        # Simulate regime shifts
        regimes = self.simulate_regime_shifts(self.params.num_days)

        # Simulate volatility spikes
        vol_multipliers = self.simulate_volatility_spikes(self.params.num_days)

        # Apply volatility spikes to returns
        returns = returns * vol_multipliers

        # Apply regime-based adjustments
        for day in range(self.params.num_days):
            regime = regimes[day]
            if regime == 4:  # Crisis regime
                returns[:, day] *= 0.5  # Reduce exposure

        # Calculate portfolio equity curve
        equity = self.params.initial_capital
        equity_curve = [equity]
        peak_equity = equity
        max_drawdown = 0.0

        # Equal weight across strategies
        strategy_weight = 1.0 / num_strategies

        for day in range(self.params.num_days):
            # Daily return is weighted average of strategy returns
            daily_return = np.sum(returns[:, day] * strategy_weight)

            # Update equity
            equity = equity * (1 + daily_return)
            equity_curve.append(equity)

            # Track drawdown
            if equity > peak_equity:
                peak_equity = equity

            drawdown = (peak_equity - equity) / peak_equity * 100
            max_drawdown = max(max_drawdown, drawdown)

        final_capital = equity_curve[-1]

        return final_capital, max_drawdown, equity_curve

    def run_simulations(self, num_strategies: int = 3) -> SimulationResults:
        """
        Run full Monte Carlo simulation

        Args:
            num_strategies: Number of strategies

        Returns:
            SimulationResults with all metrics
        """
        logger.info(f"🎲 Running {self.params.num_simulations} Monte Carlo simulations...")

        final_capitals = []
        max_drawdowns = []
        equity_curves = []

        for i in range(self.params.num_simulations):
            if (i + 1) % 100 == 0:
                logger.info(f"   Completed {i + 1}/{self.params.num_simulations} simulations...")

            final_capital, max_dd, equity_curve = self.run_single_simulation(num_strategies)

            final_capitals.append(final_capital)
            max_drawdowns.append(max_dd)
            equity_curves.append(equity_curve)

        # Calculate statistics
        final_capitals_array = np.array(final_capitals)
        max_drawdowns_array = np.array(max_drawdowns)

        mean_final = np.mean(final_capitals_array)
        median_final = np.median(final_capitals_array)
        std_final = np.std(final_capitals_array)
        p5 = np.percentile(final_capitals_array, 5)
        p95 = np.percentile(final_capitals_array, 95)

        max_dd_mean = np.mean(max_drawdowns_array)
        max_dd_worst = np.max(max_drawdowns_array)

        # Probability of ruin (losing > 50%)
        ruin_threshold = self.params.initial_capital * 0.5
        probability_of_ruin = np.sum(final_capitals_array < ruin_threshold) / len(final_capitals_array)

        results = SimulationResults(
            mean_final_capital=mean_final,
            median_final_capital=median_final,
            std_final_capital=std_final,
            percentile_5=p5,
            percentile_95=p95,
            max_drawdown_mean=max_dd_mean,
            max_drawdown_worst=max_dd_worst,
            probability_of_ruin=probability_of_ruin,
            all_final_capitals=final_capitals,
            all_max_drawdowns=max_drawdowns,
            equity_curves=equity_curves[:10]  # Store only first 10 for visualization
        )

        logger.info(f"✅ Monte Carlo Simulation Complete")
        self._log_results(results)

        return results

    def _log_results(self, results: SimulationResults) -> None:
        """Log simulation results"""
        logger.info(f"\n📊 Monte Carlo Results:")
        logger.info(f"   Mean Final Capital: ${results.mean_final_capital:,.2f}")
        logger.info(f"   Median Final Capital: ${results.median_final_capital:,.2f}")
        logger.info(f"   Std Dev: ${results.std_final_capital:,.2f}")
        logger.info(f"   5th Percentile: ${results.percentile_5:,.2f}")
        logger.info(f"   95th Percentile: ${results.percentile_95:,.2f}")
        logger.info(f"\n🎯 Risk Metrics:")
        logger.info(f"   Mean Max Drawdown: {results.max_drawdown_mean:.2f}%")
        logger.info(f"   Worst Drawdown: {results.max_drawdown_worst:.2f}%")
        logger.info(f"   Probability of Ruin: {results.probability_of_ruin:.2%}")

    def export_results(self, results: SimulationResults,
                       output_dir: str = "./data/monte_carlo") -> str:
        """
        Export simulation results

        Args:
            results: Simulation results
            output_dir: Output directory

        Returns:
            Path to exported file
        """
        output_path = Path(output_dir)
        output_path.mkdir(exist_ok=True, parents=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"monte_carlo_results_{timestamp}.json"
        filepath = output_path / filename

        # Prepare export data (exclude equity curves for size)
        export_data = {
            'timestamp': datetime.now().isoformat(),
            'parameters': {
                'num_simulations': self.params.num_simulations,
                'num_days': self.params.num_days,
                'initial_capital': self.params.initial_capital,
                'mean_return_daily': self.params.mean_return_daily,
                'volatility_daily': self.params.volatility_daily
            },
            'results': {
                'mean_final_capital': results.mean_final_capital,
                'median_final_capital': results.median_final_capital,
                'std_final_capital': results.std_final_capital,
                'percentile_5': results.percentile_5,
                'percentile_95': results.percentile_95,
                'max_drawdown_mean': results.max_drawdown_mean,
                'max_drawdown_worst': results.max_drawdown_worst,
                'probability_of_ruin': results.probability_of_ruin
            }
        }

        with open(filepath, 'w') as f:
            json.dump(export_data, f, indent=2)

        logger.info(f"📄 Results exported to: {filepath}")

        return str(filepath)


def run_monte_carlo_test(num_simulations: int = 1000,
                         num_days: int = 252,
                         initial_capital: float = 100000.0) -> SimulationResults:
    """
    Convenience function to run Monte Carlo test

    Args:
        num_simulations: Number of simulations
        num_days: Trading days to simulate
        initial_capital: Starting capital

    Returns:
        SimulationResults
    """
    params = SimulationParameters(
        num_simulations=num_simulations,
        num_days=num_days,
        initial_capital=initial_capital
    )

    simulator = MonteCarloPortfolioSimulator(params)
    results = simulator.run_simulations(num_strategies=3)
    simulator.export_results(results)

    return results
