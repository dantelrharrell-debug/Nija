"""
NIJA Walk-Forward Optimization Engine
======================================

Implements walk-forward optimization in two flavours:

WalkForwardOptimizer (genetic)
    Uses genetic algorithms (GeneticEvolution) to evolve parameters.
    High-quality results but requires the meta_ai package.

SimpleWalkForwardOptimizer (grid-search)
    Pure grid-search over a discrete parameter space.  No external
    dependencies — works out of the box with only pandas/numpy.
    Suitable for live auto-tuning of strategy parameters over time.

Common workflow
    1. Split historical data into rolling windows (train → test).
    2. Optimise parameters on the *training* window.
    3. Evaluate the best parameters on the *test* (out-of-sample) window.
    4. Roll the window forward and repeat.
    5. Select the parameter set that generalises best across windows.

Author: NIJA Trading Systems
Version: 1.1
Date: January 29, 2026 (updated March 2026 – SimpleWalkForwardOptimizer added)
"""

import itertools
import pandas as pd
import numpy as np
from typing import Any, Dict, List, Optional, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import logging

# Import genetic evolution engine (optional – only needed for WalkForwardOptimizer)
try:
    from bot.meta_ai.genetic_evolution import GeneticEvolution, StrategyGenome
    from bot.meta_ai.evolution_config import GENETIC_CONFIG, PARAMETER_SEARCH_SPACE
    _GENETIC_AVAILABLE = True
except ImportError:
    try:
        from meta_ai.genetic_evolution import GeneticEvolution, StrategyGenome
        from meta_ai.evolution_config import GENETIC_CONFIG, PARAMETER_SEARCH_SPACE
        _GENETIC_AVAILABLE = True
    except ImportError:
        _GENETIC_AVAILABLE = False
        GeneticEvolution = None  # type: ignore
        StrategyGenome = None  # type: ignore
        GENETIC_CONFIG = {}
        PARAMETER_SEARCH_SPACE = {}

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

        Raises:
            ImportError: If the meta_ai genetic evolution package is unavailable.
                Use :class:`SimpleWalkForwardOptimizer` as a drop-in alternative
                that requires only pandas/numpy.
        """
        if not _GENETIC_AVAILABLE:
            raise ImportError(
                "meta_ai.genetic_evolution is required for WalkForwardOptimizer. "
                "Use SimpleWalkForwardOptimizer instead (no external dependencies)."
            )

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


# ===========================================================================
# SimpleWalkForwardOptimizer
# ===========================================================================

@dataclass
class SimpleWFOWindow:
    """Result for a single walk-forward window (simple variant)."""
    window_id: int
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime
    best_params: Dict[str, Any] = field(default_factory=dict)
    train_score: float = 0.0
    test_score: float = 0.0
    efficiency_ratio: float = 0.0  # test_score / train_score

    def is_overfit(self, threshold: float = 0.70) -> bool:
        """Return True when test performance falls below *threshold* × train."""
        return self.efficiency_ratio < threshold


@dataclass
class SimpleWFOResult:
    """Aggregated result from :class:`SimpleWalkForwardOptimizer`."""
    windows: List[SimpleWFOWindow]
    best_params: Dict[str, Any] = field(default_factory=dict)
    avg_train_score: float = 0.0
    avg_test_score: float = 0.0
    avg_efficiency_ratio: float = 0.0
    total_windows: int = 0
    overfit_windows: int = 0
    parameter_stability: Dict[str, float] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # Convenience helpers
    # ------------------------------------------------------------------

    def get_recommended_params(self) -> Dict[str, Any]:
        """
        Return the best parameter set for live trading.

        Prefers parameters from the most recent non-overfit window so that
        the result reflects the latest market conditions.
        """
        non_overfit = [w for w in self.windows if not w.is_overfit()]
        if non_overfit:
            # Most recent non-overfit window
            return non_overfit[-1].best_params
        # Fallback: the globally best parameter set
        return self.best_params


class SimpleWalkForwardOptimizer:
    """
    Walk-forward parameter optimiser using exhaustive grid search.

    No external dependencies beyond *pandas* and *numpy* — works out of the
    box alongside the rest of the NIJA bot.

    This class automatically tunes strategy parameters over time by:
    1. Splitting historical data into rolling train / test windows.
    2. Running a grid search over the supplied parameter space on each
       training window.
    3. Evaluating the best parameters on the unseen test window.
    4. Rolling forward and repeating.
    5. Returning the most stable parameters that generalise well.

    Usage::

        param_grid = {
            'rsi_oversold': [25, 30, 35],
            'rsi_overbought': [65, 70, 75],
            'min_confirmations': [2, 3],
        }

        def my_backtest(params: dict, data: pd.DataFrame) -> dict:
            # run backtest on *data* using *params*
            # must return a dict with at least 'sharpe_ratio', 'win_rate',
            # 'profit_factor', 'max_drawdown' keys.
            ...

        optimizer = SimpleWalkForwardOptimizer(param_grid)
        result = optimizer.run(historical_df, my_backtest)
        live_params = result.get_recommended_params()
    """

    def __init__(
        self,
        param_grid: Dict[str, List[Any]],
        config: Optional[Dict] = None,
    ):
        """
        Args:
            param_grid: Mapping of parameter name → list of candidate values.
                        All combinations are evaluated via grid search.
            config: Optional configuration overrides:
                - ``train_window_days``   (int, default 90)
                - ``test_window_days``    (int, default 30)
                - ``step_days``           (int, default 30)
                - ``efficiency_threshold``(float, default 0.70)
                - ``fitness_weights``     (dict, default below)
        """
        self.param_grid = param_grid
        self.config = config or {}

        self.train_window_days = self.config.get("train_window_days", 90)
        self.test_window_days = self.config.get("test_window_days", 30)
        self.step_days = self.config.get("step_days", 30)
        self.efficiency_threshold = self.config.get("efficiency_threshold", 0.70)

        # Fitness function weights (Sharpe 40 %, profit factor 30 %,
        # win rate 20 %, low drawdown 10 %)
        default_weights = {
            "sharpe_ratio": 0.40,
            "profit_factor": 0.30,
            "win_rate": 0.20,
            "max_drawdown": 0.10,
        }
        self.fitness_weights = self.config.get("fitness_weights", default_weights)

        # Compute grid size once for logging; combinations are generated lazily
        # during each grid search so that large param spaces don't pre-allocate
        # memory unnecessarily.
        self._grid_size: int = 1
        for v in self.param_grid.values():
            self._grid_size *= len(v)

        logger.info("📐 SimpleWalkForwardOptimizer initialised")
        logger.info(f"   Train window : {self.train_window_days} days")
        logger.info(f"   Test  window : {self.test_window_days} days")
        logger.info(f"   Step  size   : {self.step_days} days")
        logger.info(f"   Grid  size   : {self._grid_size:,} combinations")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        data: pd.DataFrame,
        backtest_fn: Callable[[Dict[str, Any], pd.DataFrame], Dict[str, float]],
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
    ) -> "SimpleWFOResult":
        """
        Execute the walk-forward optimisation.

        Args:
            data: Historical OHLCV DataFrame with a :class:`~pandas.DatetimeIndex`.
            backtest_fn: ``fn(params, data) -> metrics`` where *metrics* is a
                dictionary containing at minimum:
                ``sharpe_ratio``, ``win_rate``, ``profit_factor``,
                ``max_drawdown``.
            start_date: Start of the optimisation period (defaults to first row).
            end_date:   End   of the optimisation period (defaults to last row).

        Returns:
            :class:`SimpleWFOResult` containing per-window results and the
            aggregated recommended parameter set.
        """
        if start_date is None:
            start_date = data.index[0]
        if end_date is None:
            end_date = data.index[-1]

        logger.info(
            f"🚀 SimpleWFO: {start_date.date()} → {end_date.date()}, "
            f"{self._grid_size:,} combinations/window"
        )

        windows: List[SimpleWFOWindow] = []
        window_id = 0
        current_train_start = start_date

        while True:
            train_end = current_train_start + timedelta(days=self.train_window_days)
            test_start = train_end
            test_end = test_start + timedelta(days=self.test_window_days)

            if test_end > end_date:
                break

            train_data = data[(data.index >= current_train_start) & (data.index < train_end)]
            test_data = data[(data.index >= test_start) & (data.index < test_end)]

            if train_data.empty or test_data.empty:
                current_train_start += timedelta(days=self.step_days)
                window_id += 1
                continue

            logger.info(
                f"  📊 Window {window_id}: "
                f"train [{current_train_start.date()}→{train_end.date()}], "
                f"test  [{test_start.date()}→{test_end.date()}]"
            )

            # Grid search on training data
            best_params, train_score = self._grid_search(train_data, backtest_fn)

            if not best_params:
                logger.warning(f"    ⚠️ No valid params found in window {window_id} – skipping")
                current_train_start += timedelta(days=self.step_days)
                window_id += 1
                continue

            # Out-of-sample evaluation
            try:
                test_metrics = backtest_fn(best_params, test_data)
                test_score = self._score(test_metrics)
            except Exception as exc:
                logger.debug(f"    Out-of-sample eval failed for window {window_id}: {exc}")
                current_train_start += timedelta(days=self.step_days)
                window_id += 1
                continue

            efficiency = test_score / train_score if train_score > 0 else 0.0

            flag = "⚠️ OVERFIT" if efficiency < self.efficiency_threshold else "✅"
            logger.info(
                f"    {flag}  train={train_score:.4f}  test={test_score:.4f}  "
                f"efficiency={efficiency:.1%}"
            )

            windows.append(
                SimpleWFOWindow(
                    window_id=window_id,
                    train_start=current_train_start,
                    train_end=train_end,
                    test_start=test_start,
                    test_end=test_end,
                    best_params=best_params,
                    train_score=train_score,
                    test_score=test_score,
                    efficiency_ratio=efficiency,
                )
            )

            current_train_start += timedelta(days=self.step_days)
            window_id += 1

        return self._aggregate(windows)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _grid_search(
        self,
        data: pd.DataFrame,
        backtest_fn: Callable,
    ) -> tuple:
        """Return (best_params, best_score) from an exhaustive grid search."""
        best_params: Dict[str, Any] = {}
        best_score: float = -np.inf

        # Iterate lazily to avoid materialising the full Cartesian product
        # in memory when the parameter space is very large.
        keys = list(self.param_grid.keys())
        for values in itertools.product(*self.param_grid.values()):
            params = dict(zip(keys, values))
            try:
                metrics = backtest_fn(params, data)
                score = self._score(metrics)
            except Exception as exc:
                logger.debug(f"    Grid eval failed for {params}: {exc}")
                continue

            if score > best_score:
                best_score = score
                best_params = params.copy()

        return best_params, best_score

    def _score(self, metrics: Dict[str, float]) -> float:
        """Weighted fitness score from a backtest metrics dictionary."""
        w = self.fitness_weights
        sharpe = metrics.get("sharpe_ratio", 0.0)
        pf = metrics.get("profit_factor", 1.0)
        wr = metrics.get("win_rate", 0.5)
        dd = metrics.get("max_drawdown", 0.0)

        score = (
            sharpe * w.get("sharpe_ratio", 0.40)
            + (pf - 1.0) * w.get("profit_factor", 0.30)
            + wr * w.get("win_rate", 0.20)
            + (1.0 - min(abs(dd), 1.0)) * w.get("max_drawdown", 0.10)
        )
        return max(score, 0.0)

    def _aggregate(self, windows: List[SimpleWFOWindow]) -> SimpleWFOResult:
        """Aggregate per-window results into a :class:`SimpleWFOResult`."""
        if not windows:
            return SimpleWFOResult(windows=[])

        valid = [w for w in windows if w.best_params]
        non_overfit = [w for w in valid if not w.is_overfit(self.efficiency_threshold)]

        avg_train = float(np.mean([w.train_score for w in valid])) if valid else 0.0
        avg_test = float(np.mean([w.test_score for w in valid])) if valid else 0.0
        avg_eff = float(np.mean([w.efficiency_ratio for w in valid])) if valid else 0.0
        overfit_count = len(valid) - len(non_overfit)

        # Best parameters: highest test score among non-overfit windows
        if non_overfit:
            best_window = max(non_overfit, key=lambda w: w.test_score)
            best_params = best_window.best_params
        elif valid:
            best_window = max(valid, key=lambda w: w.test_score)
            best_params = best_window.best_params
            logger.warning("⚠️  All windows overfit – returning best available params")
        else:
            best_params = {}

        # Parameter stability: std / mean per parameter (lower = more stable)
        param_stability: Dict[str, float] = {}
        if valid and valid[0].best_params:
            for key in valid[0].best_params:
                vals = [w.best_params[key] for w in valid if key in w.best_params]
                if len(vals) >= 2:
                    mean_v = float(np.mean(vals))
                    std_v = float(np.std(vals))
                    cv = std_v / mean_v if mean_v != 0 else float("inf")
                    param_stability[key] = round(1.0 / (1.0 + cv), 4)
                else:
                    param_stability[key] = 1.0

        result = SimpleWFOResult(
            windows=windows,
            best_params=best_params,
            avg_train_score=avg_train,
            avg_test_score=avg_test,
            avg_efficiency_ratio=avg_eff,
            total_windows=len(windows),
            overfit_windows=overfit_count,
            parameter_stability=param_stability,
        )

        logger.info("=" * 60)
        logger.info("📊 SimpleWFO RESULTS")
        logger.info(f"   Windows: {result.total_windows}  |  Overfit: {result.overfit_windows}")
        logger.info(f"   Avg train score : {result.avg_train_score:.4f}")
        logger.info(f"   Avg test  score : {result.avg_test_score:.4f}")
        logger.info(f"   Avg efficiency  : {result.avg_efficiency_ratio:.1%}")
        logger.info(f"   Best params     : {result.best_params}")
        logger.info("=" * 60)

        return result
