"""
NIJA Walk-Forward Genetic Optimization Engine
==============================================

Implements walk-forward optimization with genetic algorithms:
- Rolling window optimization (in-sample training)
- Out-of-sample testing for validation
- Continuous parameter evolution over time
- Prevents overfitting through forward testing

Process:
1. Split historical data into windows (e.g., 3 months train, 1 month test)
2. Run genetic optimization on training window
3. Test best parameters on out-of-sample window
4. Roll forward and repeat
5. Track parameter stability and performance degradation

Author: NIJA Trading Systems
Version: 1.0 - God Mode Edition
Date: January 29, 2026
"""

import pandas as pd
import numpy as np
from typing import Dict, List, Tuple, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging

# Import genetic evolution engine
try:
    from bot.meta_ai.genetic_evolution import GeneticEvolution, StrategyGenome
    from bot.meta_ai.evolution_config import GENETIC_CONFIG, PARAMETER_SEARCH_SPACE
except ImportError:
    try:
        from meta_ai.genetic_evolution import GeneticEvolution, StrategyGenome
        from meta_ai.evolution_config import GENETIC_CONFIG, PARAMETER_SEARCH_SPACE
    except ImportError:
        raise ImportError("Genetic evolution module not found")

logger = logging.getLogger("nija.walk_forward")


@dataclass
class WalkForwardWindow:
    """A single walk-forward optimization window"""
    window_id: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    
    # Results
    best_genome: Optional[StrategyGenome] = None
    train_fitness: float = 0.0
    test_fitness: float = 0.0
    efficiency_ratio: float = 0.0  # test_fitness / train_fitness
    
    # Performance metrics
    train_metrics: Dict = field(default_factory=dict)
    test_metrics: Dict = field(default_factory=dict)
    
    def is_overfit(self, threshold: float = 0.70) -> bool:
        """
        Check if optimization overfit to training data
        
        Args:
            threshold: Minimum efficiency ratio to avoid overfitting
        
        Returns:
            True if test performance < threshold * train performance
        """
        return self.efficiency_ratio < threshold


@dataclass
class WalkForwardResult:
    """Result from walk-forward optimization"""
    windows: List[WalkForwardWindow]
    
    # Aggregated metrics
    avg_train_fitness: float = 0.0
    avg_test_fitness: float = 0.0
    avg_efficiency_ratio: float = 0.0
    
    # Best stable parameters (those that performed well out-of-sample)
    stable_parameters: Optional[Dict[str, float]] = None
    
    # Parameter stability over time
    parameter_stability: Dict[str, float] = field(default_factory=dict)
    
    # Summary
    total_windows: int = 0
    overfit_windows: int = 0
    summary: str = ""
    
    def get_best_stable_window(self) -> Optional[WalkForwardWindow]:
        """Get window with best test performance"""
        if not self.windows:
            return None
        return max(
            [w for w in self.windows if not w.is_overfit()],
            key=lambda w: w.test_fitness,
            default=None
        )


class WalkForwardOptimizer:
    """
    Walk-forward optimization with genetic algorithms
    
    Prevents overfitting by:
    1. Training on in-sample data
    2. Testing on unseen out-of-sample data
    3. Rolling forward continuously
    4. Selecting parameters that generalize well
    """
    
    def __init__(self, config: Dict = None):
        """
        Initialize Walk-Forward Optimizer
        
        Args:
            config: Optional configuration dictionary
        """
        self.config = config or {}
        
        # Window configuration
        self.train_window_days = self.config.get('train_window_days', 90)  # 3 months
        self.test_window_days = self.config.get('test_window_days', 30)  # 1 month
        self.step_days = self.config.get('step_days', 30)  # 1 month step forward
        
        # Genetic algorithm configuration
        genetic_config = self.config.get('genetic_config', GENETIC_CONFIG)
        self.genetic_engine = GeneticEvolution(genetic_config)
        
        # Overfitting detection
        self.efficiency_threshold = self.config.get('efficiency_threshold', 0.70)
        
        # Parameter stability tracking
        self.stability_lookback = self.config.get('stability_lookback', 5)  # windows
        
        # Results
        self.results: Optional[WalkForwardResult] = None
        
        logger.info("🚶 Walk-Forward Optimizer initialized (God Mode)")
        logger.info(f"   Train window: {self.train_window_days} days")
        logger.info(f"   Test window: {self.test_window_days} days")
        logger.info(f"   Step size: {self.step_days} days")
        logger.info(f"   Efficiency threshold: {self.efficiency_threshold:.2%}")
    
    def run_optimization(
        self,
        data: pd.DataFrame,
        backtest_function: Callable[[Dict, pd.DataFrame], Dict],
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> WalkForwardResult:
        """
        Run walk-forward optimization
        
        Args:
            data: Historical price data (must have datetime index)
            backtest_function: Function(parameters, data) -> metrics
            start_date: Start of walk-forward period (default: first date in data)
            end_date: End of walk-forward period (default: last date in data)
        
        Returns:
            WalkForwardResult with all windows and aggregated metrics
        """
        # Determine date range
        if start_date is None:
            start_date = data.index[0]
        if end_date is None:
            end_date = data.index[-1]
        
        logger.info(f"🚀 Starting walk-forward optimization: {start_date} to {end_date}")
        
        windows = []
        window_id = 0
        
        # Create windows
        current_train_start = start_date
        
        while True:
            # Calculate window dates
            train_end = current_train_start + timedelta(days=self.train_window_days)
            test_start = train_end
            test_end = test_start + timedelta(days=self.test_window_days)
            
            # Check if we have enough data
            if test_end > end_date:
                logger.info(f"✅ Completed {window_id} walk-forward windows")
                break
            
            # Create window
            window = WalkForwardWindow(
                window_id=window_id,
                train_start=current_train_start,
                train_end=train_end,
                test_start=test_start,
                test_end=test_end,
            )
            
            logger.info(
                f"📊 Window {window_id}: "
                f"Train [{current_train_start.date()} to {train_end.date()}], "
                f"Test [{test_start.date()} to {test_end.date()}]"
            )
            
            # Split data
            train_data = data[
                (data.index >= current_train_start) & 
                (data.index < train_end)
            ]
            test_data = data[
                (data.index >= test_start) & 
                (data.index < test_end)
            ]
            
            # Run genetic optimization on training data
            logger.info(f"   🧬 Running genetic optimization on training data...")
            best_genome = self._optimize_window(train_data, backtest_function)
            
            if best_genome is None:
                logger.warning(f"   ⚠️  Optimization failed for window {window_id}")
                window_id += 1
                current_train_start += timedelta(days=self.step_days)
                continue
            
            # Evaluate on training data (in-sample)
            train_metrics = backtest_function(best_genome.parameters, train_data)
            train_fitness = self._calculate_fitness(train_metrics)
            
            # Evaluate on test data (out-of-sample)
            logger.info(f"   📈 Testing on out-of-sample data...")
            test_metrics = backtest_function(best_genome.parameters, test_data)
            test_fitness = self._calculate_fitness(test_metrics)
            
            # Calculate efficiency ratio
            efficiency_ratio = test_fitness / train_fitness if train_fitness > 0 else 0.0
            
            # Update window
            window.best_genome = best_genome
            window.train_fitness = train_fitness
            window.test_fitness = test_fitness
            window.efficiency_ratio = efficiency_ratio
            window.train_metrics = train_metrics
            window.test_metrics = test_metrics
            
            # Log results
            overfit_flag = "⚠️ OVERFIT" if window.is_overfit(self.efficiency_threshold) else "✅"
            logger.info(
                f"   {overfit_flag} Train fitness: {train_fitness:.4f}, "
                f"Test fitness: {test_fitness:.4f}, "
                f"Efficiency: {efficiency_ratio:.2%}"
            )
            
            windows.append(window)
            
            # Step forward
            window_id += 1
            current_train_start += timedelta(days=self.step_days)
        
        # Aggregate results
        result = self._aggregate_results(windows)
        self.results = result
        
        return result
    
    def _optimize_window(
        self,
        train_data: pd.DataFrame,
        backtest_function: Callable,
    ) -> Optional[StrategyGenome]:
        """
        Optimize parameters for a single window using genetic algorithm
        
        Args:
            train_data: Training data for this window
            backtest_function: Backtest function
        
        Returns:
            Best genome found
        """
        # Initialize population
        self.genetic_engine.initialize_population(PARAMETER_SEARCH_SPACE)
        
        # Fitness evaluation function
        def evaluate_fitness(genome: StrategyGenome) -> float:
            """Evaluate fitness of a genome"""
            metrics = backtest_function(genome.parameters, train_data)
            return self._calculate_fitness(metrics)
        
        # Run evolution
        for generation in range(self.config.get('generations', 20)):
            # Evaluate population
            for genome in self.genetic_engine.population:
                if genome.fitness == 0.0:  # Not yet evaluated
                    genome.fitness = evaluate_fitness(genome)
            
            # Evolve to next generation
            self.genetic_engine.evolve()
            
            if generation % 5 == 0:
                best = self.genetic_engine.best_genome
                logger.debug(f"      Gen {generation}: Best fitness = {best.fitness:.4f}")
        
        return self.genetic_engine.best_genome
    
    def _calculate_fitness(self, metrics: Dict) -> float:
        """
        Calculate fitness score from backtest metrics
        
        Args:
            metrics: Dictionary of performance metrics
        
        Returns:
            Fitness score (higher is better)
        """
        # Weighted combination of metrics
        sharpe = metrics.get('sharpe_ratio', 0.0)
        profit_factor = metrics.get('profit_factor', 1.0)
        win_rate = metrics.get('win_rate', 0.5)
        max_dd = metrics.get('max_drawdown', 0.0)
        
        # Fitness formula (adjust weights as needed)
        fitness = (
            sharpe * 0.40 +  # 40% weight on risk-adjusted returns
            (profit_factor - 1.0) * 0.30 +  # 30% weight on profit factor
            win_rate * 0.20 +  # 20% weight on win rate
            (1.0 - min(abs(max_dd), 1.0)) * 0.10  # 10% penalty for drawdown
        )
        
        return max(fitness, 0.0)  # Non-negative fitness
    
    def _aggregate_results(self, windows: List[WalkForwardWindow]) -> WalkForwardResult:
        """
        Aggregate results from all windows
        
        Args:
            windows: List of completed windows
        
        Returns:
            Aggregated walk-forward result
        """
        if not windows:
            return WalkForwardResult(windows=[])
        
        # Calculate averages
        valid_windows = [w for w in windows if w.best_genome is not None]
        
        avg_train_fitness = np.mean([w.train_fitness for w in valid_windows])
        avg_test_fitness = np.mean([w.test_fitness for w in valid_windows])
        avg_efficiency = np.mean([w.efficiency_ratio for w in valid_windows])
        
        # Count overfitted windows
        overfit_count = sum(1 for w in valid_windows if w.is_overfit(self.efficiency_threshold))
        
        # Find most stable parameters
        stable_params = self._find_stable_parameters(valid_windows)
        
        # Calculate parameter stability
        param_stability = self._calculate_parameter_stability(valid_windows)
        
        # Create result
        result = WalkForwardResult(
            windows=windows,
            avg_train_fitness=avg_train_fitness,
            avg_test_fitness=avg_test_fitness,
            avg_efficiency_ratio=avg_efficiency,
            stable_parameters=stable_params,
            parameter_stability=param_stability,
            total_windows=len(windows),
            overfit_windows=overfit_count,
        )
        
        # Generate summary
        result.summary = self._generate_summary(result)
        
        logger.info("=" * 60)
        logger.info("📊 WALK-FORWARD OPTIMIZATION RESULTS")
        logger.info("=" * 60)
        logger.info(result.summary)
        logger.info("=" * 60)
        
        return result
    
    def _find_stable_parameters(
        self,
        windows: List[WalkForwardWindow],
    ) -> Optional[Dict[str, float]]:
        """
        Find parameters that perform well out-of-sample
        
        Strategy: Average parameters from top-performing non-overfit windows
        
        Args:
            windows: List of windows
        
        Returns:
            Stable parameter set
        """
        # Filter to non-overfit windows
        good_windows = [
            w for w in windows 
            if not w.is_overfit(self.efficiency_threshold) and w.best_genome is not None
        ]
        
        if not good_windows:
            logger.warning("No stable windows found - all appear overfit")
            return None
        
        # Take top 50% by test fitness
        sorted_windows = sorted(good_windows, key=lambda w: w.test_fitness, reverse=True)
        top_windows = sorted_windows[:max(1, len(sorted_windows) // 2)]
        
        # Average parameters
        param_keys = list(top_windows[0].best_genome.parameters.keys())
        stable_params = {}
        
        for key in param_keys:
            values = [w.best_genome.parameters[key] for w in top_windows]
            stable_params[key] = np.mean(values)
        
        logger.info(f"✅ Stable parameters found from {len(top_windows)} top windows")
        
        return stable_params
    
    def _calculate_parameter_stability(
        self,
        windows: List[WalkForwardWindow],
    ) -> Dict[str, float]:
        """
        Calculate stability score for each parameter
        
        Stability = 1 / coefficient_of_variation
        Higher score = more stable parameter
        
        Args:
            windows: List of windows
        
        Returns:
            Dictionary of parameter -> stability score
        """
        if not windows or not windows[0].best_genome:
            return {}
        
        param_keys = list(windows[0].best_genome.parameters.keys())
        stability_scores = {}
        
        for key in param_keys:
            values = [w.best_genome.parameters[key] for w in windows if w.best_genome]
            
            if not values:
                continue
            
            mean_val = np.mean(values)
            std_val = np.std(values)
            
            # Coefficient of variation
            cv = std_val / mean_val if mean_val != 0 else float('inf')
            
            # Stability score (inverse of CV, bounded 0-1)
            stability = 1.0 / (1.0 + cv)
            
            stability_scores[key] = stability
        
        return stability_scores
    
    def _generate_summary(self, result: WalkForwardResult) -> str:
        """Generate human-readable summary"""
        lines = [
            f"Total Windows: {result.total_windows}",
            f"Overfit Windows: {result.overfit_windows} ({result.overfit_windows/result.total_windows*100:.1f}%)",
            "",
            "Performance Metrics:",
            f"  Avg Train Fitness: {result.avg_train_fitness:.4f}",
            f"  Avg Test Fitness: {result.avg_test_fitness:.4f}",
            f"  Avg Efficiency: {result.avg_efficiency_ratio:.2%}",
            "",
        ]
        
        if result.stable_parameters:
            lines.append("Stable Parameters:")
            for key, value in result.stable_parameters.items():
                stability = result.parameter_stability.get(key, 0.0)
                lines.append(f"  {key}: {value:.4f} (stability: {stability:.2f})")
        
        return "\n".join(lines)
