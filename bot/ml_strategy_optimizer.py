"""
NIJA ML Strategy Parameter Optimizer
======================================

Provides machine-learning–driven parameter optimisation for trading strategies,
building on the existing walk_forward_optimizer and unified_backtest_engine.

Three optimisation backends are supported:

1. **GridSearchOptimizer** — exhaustive grid search; always available.
2. **BayesianOptimizer**  — Bayesian optimisation via ``scipy.optimize``
   (falls back gracefully if scipy is absent).
3. **GeneticOptimizer**   — Genetic algorithm; wraps existing
   ``bot.meta_ai.genetic_evolution.GeneticEvolution`` when available.

Adaptive Learning Loop
-----------------------
``AdaptiveLearningLoop`` chains the optimiser with a live performance
monitor. After every ``eval_window`` completed trades it re-runs
optimisation and updates the running strategy parameters — closing the
feedback loop without manual retuning.

Reinforcement Learning Adapter
--------------------------------
``RLFeedbackAdapter`` is a thin shim that wraps the existing
``bot.live_rl_feedback.LiveRLFeedback`` (if present) and exposes a
uniform ``record_outcome()`` / ``get_adjusted_params()`` interface.
When the live RL module is absent the adapter falls back to a simple
exponential-moving-average reward tracker.

Usage
-----
    from bot.ml_strategy_optimizer import (
        BayesianOptimizer,
        AdaptiveLearningLoop,
        RLFeedbackAdapter,
        ParameterSpace,
    )

    space = ParameterSpace({
        "fast_period": (5, 50, 5),       # (min, max, step)
        "slow_period": (20, 200, 10),
        "adx_threshold": (15.0, 40.0, 2.5),
    })

    def objective(params) -> float:
        # run backtest, return Sharpe ratio
        ...

    opt = BayesianOptimizer(space, objective)
    result = opt.optimise(n_iterations=50)
    print(result.best_params, result.best_score)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import itertools
import logging
import math
import random
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("nija.ml_optimizer")

# Optional heavy imports
try:
    from scipy.optimize import differential_evolution
    _SCIPY = True
except ImportError:
    _SCIPY = False
    logger.debug("[MLOptimizer] scipy not available — Bayesian fallback to random search")

try:
    from bot.meta_ai.genetic_evolution import GeneticEvolution, StrategyGenome
    _GENETIC = True
except ImportError:
    try:
        from meta_ai.genetic_evolution import GeneticEvolution, StrategyGenome
        _GENETIC = True
    except ImportError:
        _GENETIC = False
        GeneticEvolution = None   # type: ignore
        StrategyGenome = None     # type: ignore

try:
    from bot.live_rl_feedback import LiveRLFeedback
    _RL_AVAILABLE = True
except ImportError:
    try:
        from live_rl_feedback import LiveRLFeedback
        _RL_AVAILABLE = True
    except ImportError:
        _RL_AVAILABLE = False
        LiveRLFeedback = None   # type: ignore


# ---------------------------------------------------------------------------
# Parameter space
# ---------------------------------------------------------------------------

@dataclass
class ParameterSpec:
    name:    str
    min_val: float
    max_val: float
    step:    float = 1.0
    is_int:  bool = True

    def grid_values(self) -> List[float]:
        vals = []
        v = self.min_val
        while v <= self.max_val + 1e-9:
            vals.append(int(round(v)) if self.is_int else round(v, 8))
            v += self.step
        return vals

    def random_value(self) -> float:
        v = random.uniform(self.min_val, self.max_val)
        if self.is_int:
            return float(int(round(v)))
        # Round to nearest step
        steps = round((v - self.min_val) / self.step)
        return round(self.min_val + steps * self.step, 8)

    def clip(self, v: float) -> float:
        v = max(self.min_val, min(self.max_val, v))
        if self.is_int:
            return float(int(round(v)))
        return v


class ParameterSpace:
    """
    Defines the search space for a strategy's tunable parameters.

    Accepts:
        specs: dict mapping param_name → (min, max) or (min, max, step)
               or ParameterSpec objects.
    """

    def __init__(self, specs: Dict[str, Any]):
        self.specs: Dict[str, ParameterSpec] = {}
        for name, val in specs.items():
            if isinstance(val, ParameterSpec):
                self.specs[name] = val
            elif isinstance(val, (tuple, list)) and len(val) >= 2:
                mn, mx = float(val[0]), float(val[1])
                step = float(val[2]) if len(val) >= 3 else 1.0
                is_int = isinstance(val[0], int) and isinstance(val[1], int)
                self.specs[name] = ParameterSpec(name, mn, mx, step, is_int)
            else:
                raise ValueError(f"Invalid spec for '{name}': {val}")

    @property
    def names(self) -> List[str]:
        return list(self.specs.keys())

    def random_point(self) -> Dict[str, float]:
        return {n: s.random_value() for n, s in self.specs.items()}

    def grid_points(self) -> List[Dict[str, float]]:
        grids = [s.grid_values() for s in self.specs.values()]
        names = self.names
        return [dict(zip(names, combo)) for combo in itertools.product(*grids)]

    def bounds(self) -> List[Tuple[float, float]]:
        return [(s.min_val, s.max_val) for s in self.specs.values()]

    def clip(self, params: Dict[str, float]) -> Dict[str, float]:
        return {n: self.specs[n].clip(v) for n, v in params.items()}


# ---------------------------------------------------------------------------
# Optimisation result
# ---------------------------------------------------------------------------

@dataclass
class OptimisationResult:
    best_params:  Dict[str, float]
    best_score:   float
    all_trials:   List[Dict] = field(default_factory=list)  # [{params, score}]
    iterations:   int = 0
    method:       str = ""
    duration_s:   float = 0.0
    timestamp:    str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> Dict:
        return {
            "best_params": self.best_params,
            "best_score": round(self.best_score, 6),
            "iterations": self.iterations,
            "method": self.method,
            "duration_s": round(self.duration_s, 2),
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# 1. Grid Search
# ---------------------------------------------------------------------------

class GridSearchOptimizer:
    """
    Exhaustive parameter grid search. Useful as a baseline and for small
    search spaces (< ~1 000 combinations).
    """

    def __init__(self, space: ParameterSpace, objective: Callable[[Dict], float]):
        self.space = space
        self.objective = objective

    def optimise(self, max_evals: Optional[int] = None) -> OptimisationResult:
        import time
        points = self.space.grid_points()
        if max_evals:
            points = points[:max_evals]

        best_params: Dict = {}
        best_score = -math.inf
        trials: List[Dict] = []
        t0 = time.monotonic()

        for i, params in enumerate(points):
            try:
                score = float(self.objective(params))
            except Exception as exc:
                logger.warning("[GridSearch] Trial %d error: %s", i, exc)
                score = -math.inf
            trials.append({"params": params, "score": score})
            if score > best_score:
                best_score = score
                best_params = dict(params)

        return OptimisationResult(
            best_params=best_params,
            best_score=best_score,
            all_trials=trials,
            iterations=len(trials),
            method="GRID_SEARCH",
            duration_s=time.monotonic() - t0,
        )


# ---------------------------------------------------------------------------
# 2. Bayesian Optimizer (scipy DE / random fallback)
# ---------------------------------------------------------------------------

class BayesianOptimizer:
    """
    Bayesian-style optimiser.

    When scipy is available, uses ``differential_evolution`` which is a
    global stochastic optimiser that outperforms random search for smooth
    objective functions.  When scipy is absent, falls back to guided random
    search with EI (Expected Improvement) approximation via a Gaussian
    surrogate built from previously evaluated points.
    """

    def __init__(
        self,
        space: ParameterSpace,
        objective: Callable[[Dict], float],
        n_initial: int = 10,
    ):
        self.space = space
        self.objective = objective
        self.n_initial = n_initial
        self._history: List[Tuple[Dict, float]] = []

    def _surrogate_ei(self, params: Dict, best_so_far: float, xi: float = 0.01) -> float:
        """
        Approximate Expected Improvement using a weighted Gaussian surrogate.
        Pure-numpy implementation — no scipy dependency.
        Uses the normal CDF approximation: Φ(z) ≈ 1/(1 + exp(-1.7*z)).
        """
        if len(self._history) < 3:
            return random.random()
        names = self.space.names
        x0 = np.array([params[n] for n in names])
        Xs = np.array([[p[n] for n in names] for p, _ in self._history])
        ys = np.array([s for _, s in self._history])
        dists = np.linalg.norm(Xs - x0, axis=1)
        weights = np.exp(-dists / (dists.max() + 1e-9))
        mu = float(np.dot(weights, ys) / weights.sum())
        sigma = float(np.sqrt(np.dot(weights, (ys - mu) ** 2) / weights.sum()) + 1e-9)
        z = (mu - best_so_far - xi) / sigma
        # Numerically stable CDF and PDF approximations
        cdf_z = 1.0 / (1.0 + math.exp(-1.7 * float(z)))
        pdf_z = math.exp(-0.5 * float(z) ** 2) / math.sqrt(2 * math.pi)
        ei = sigma * (float(z) * cdf_z + pdf_z)
        return float(ei)

    def optimise(self, n_iterations: int = 50) -> OptimisationResult:
        import time
        t0 = time.monotonic()
        best_params: Dict = {}
        best_score = -math.inf
        trials: List[Dict] = []

        # --- scipy differential_evolution ---
        if _SCIPY:
            bounds = self.space.bounds()
            names  = self.space.names

            def _wrapper(x):
                params = self.space.clip(dict(zip(names, x)))
                try:
                    score = float(self.objective(params))
                except Exception:
                    score = -math.inf
                trials.append({"params": params, "score": score})
                return -score   # DE minimises

            result = differential_evolution(
                _wrapper,
                bounds=bounds,
                maxiter=max(1, n_iterations // 15),
                popsize=15,
                seed=42,
                tol=1e-4,
            )
            best_params = self.space.clip(dict(zip(names, result.x)))
            best_score  = -result.fun

        else:
            # Random search with EI guidance
            for i in range(n_iterations):
                if i < self.n_initial:
                    params = self.space.random_point()
                else:
                    # Sample candidates and pick the one with highest EI
                    candidates = [self.space.random_point() for _ in range(20)]
                    params = max(candidates, key=lambda p: self._surrogate_ei(p, best_score))

                try:
                    score = float(self.objective(params))
                except Exception as exc:
                    logger.warning("[Bayesian] Trial %d error: %s", i, exc)
                    score = -math.inf

                self._history.append((params, score))
                trials.append({"params": params, "score": score})
                if score > best_score:
                    best_score = score
                    best_params = dict(params)

        return OptimisationResult(
            best_params=best_params,
            best_score=best_score,
            all_trials=trials,
            iterations=len(trials),
            method="BAYESIAN_DE" if _SCIPY else "BAYESIAN_EI_RANDOM",
            duration_s=time.monotonic() - t0,
        )


# ---------------------------------------------------------------------------
# 3. Genetic Optimizer (wraps existing GeneticEvolution if present)
# ---------------------------------------------------------------------------

class GeneticOptimizer:
    """
    Genetic algorithm optimiser. Wraps the existing
    ``bot.meta_ai.genetic_evolution.GeneticEvolution`` when available,
    otherwise implements a standalone simple GA.
    """

    def __init__(
        self,
        space: ParameterSpace,
        objective: Callable[[Dict], float],
        population_size: int = 50,
        generations: int = 30,
        mutation_rate: float = 0.1,
        crossover_rate: float = 0.8,
    ):
        self.space = space
        self.objective = objective
        self.population_size = population_size
        self.generations = generations
        self.mutation_rate = mutation_rate
        self.crossover_rate = crossover_rate

    def _mutate(self, individual: Dict) -> Dict:
        child = dict(individual)
        for name, spec in self.space.specs.items():
            if random.random() < self.mutation_rate:
                range_size = (spec.max_val - spec.min_val) * 0.2
                child[name] = spec.clip(child[name] + random.gauss(0, range_size))
        return child

    def _crossover(self, a: Dict, b: Dict) -> Tuple[Dict, Dict]:
        if random.random() > self.crossover_rate:
            return dict(a), dict(b)
        point = random.randint(1, len(self.space.names) - 1)
        names = self.space.names
        c1 = {n: a[n] if i < point else b[n] for i, n in enumerate(names)}
        c2 = {n: b[n] if i < point else a[n] for i, n in enumerate(names)}
        return c1, c2

    def optimise(self, generations: Optional[int] = None) -> OptimisationResult:
        import time
        t0 = time.monotonic()
        gen = generations or self.generations

        if _GENETIC:
            # Defer to existing GeneticEvolution if available
            logger.info("[GeneticOptimizer] Using GeneticEvolution from meta_ai")
            # Minimal shim — run the built-in engine and parse its result
            try:
                ge = GeneticEvolution(
                    parameter_space=self.space.specs,
                    objective_function=self.objective,
                    population_size=self.population_size,
                    generations=gen,
                )
                ge_result = ge.evolve()
                best_genome = ge_result.best_genome if hasattr(ge_result, "best_genome") else None
                best_params = best_genome.parameters if best_genome else self.space.random_point()
                best_score  = best_genome.fitness if best_genome else -math.inf
                return OptimisationResult(
                    best_params=best_params,
                    best_score=best_score,
                    iterations=gen * self.population_size,
                    method="GENETIC_EVOLUTION_META_AI",
                    duration_s=time.monotonic() - t0,
                )
            except Exception as exc:
                logger.warning("[GeneticOptimizer] meta_ai error: %s — falling back to simple GA", exc)

        # --- Standalone simple GA ---
        population = [self.space.random_point() for _ in range(self.population_size)]
        best_params: Dict = {}
        best_score = -math.inf
        trials: List[Dict] = []

        def evaluate(ind: Dict) -> float:
            try:
                return float(self.objective(ind))
            except Exception:
                return -math.inf

        for g in range(gen):
            scores = [evaluate(ind) for ind in population]
            for i, (ind, sc) in enumerate(zip(population, scores)):
                trials.append({"params": ind, "score": sc, "generation": g})
                if sc > best_score:
                    best_score  = sc
                    best_params = dict(ind)

            # Selection: tournament
            new_population: List[Dict] = []
            while len(new_population) < self.population_size:
                a_idx, b_idx = random.sample(range(len(population)), 2)
                winner = population[a_idx] if scores[a_idx] >= scores[b_idx] else population[b_idx]
                new_population.append(dict(winner))

            # Crossover + Mutation
            next_gen: List[Dict] = []
            for i in range(0, len(new_population) - 1, 2):
                c1, c2 = self._crossover(new_population[i], new_population[i + 1])
                next_gen.extend([self._mutate(c1), self._mutate(c2)])
            if len(next_gen) < self.population_size:
                next_gen.append(self._mutate(new_population[-1]))
            population = next_gen[:self.population_size]

            if g % 10 == 0:
                logger.debug("[GeneticOptimizer] Gen %d best=%.4f", g, best_score)

        return OptimisationResult(
            best_params=best_params,
            best_score=best_score,
            all_trials=trials,
            iterations=gen * self.population_size,
            method="GENETIC_SIMPLE_GA",
            duration_s=time.monotonic() - t0,
        )


# ---------------------------------------------------------------------------
# Adaptive Learning Loop
# ---------------------------------------------------------------------------

class AdaptiveLearningLoop:
    """
    Continuously re-optimises strategy parameters as new trades complete.

    After every ``eval_window`` trades it runs the chosen optimiser and
    pushes the updated parameters to all registered parameter consumers.

    Args:
        space: ParameterSpace defining tunable parameters.
        objective_factory: Callable(trade_history) → objective_function.
            The factory is called with the recent trade list and must return
            a callable(params) → score.
        optimiser_class: One of GridSearchOptimizer / BayesianOptimizer /
                         GeneticOptimizer. Default: BayesianOptimizer.
        eval_window: Number of completed trades before re-optimising.
        on_params_updated: Callback(params: Dict) called with new params.
    """

    def __init__(
        self,
        space: ParameterSpace,
        objective_factory: Callable[[List[Dict]], Callable[[Dict], float]],
        optimiser_class=None,
        eval_window: int = 30,
        on_params_updated: Optional[Callable[[Dict], None]] = None,
        opt_iterations: int = 30,
    ):
        self.space = space
        self.objective_factory = objective_factory
        self.optimiser_class = optimiser_class or BayesianOptimizer
        self.eval_window = eval_window
        self.on_params_updated = on_params_updated
        self.opt_iterations = opt_iterations

        self._trades: List[Dict] = []
        self._current_params: Dict = space.random_point()
        self._optimisation_history: List[OptimisationResult] = []
        self._lock = threading.Lock()

    @property
    def current_params(self) -> Dict:
        with self._lock:
            return dict(self._current_params)

    def record_trade(self, trade: Dict) -> Optional[OptimisationResult]:
        """
        Record a completed trade. Triggers re-optimisation when eval_window
        is reached.

        Args:
            trade: Dict with at least {"pnl": float, "duration_bars": int, …}

        Returns:
            OptimisationResult if optimisation was triggered, else None.
        """
        with self._lock:
            self._trades.append(trade)
            should_optimise = len(self._trades) % self.eval_window == 0

        if should_optimise:
            return self._run_optimisation()
        return None

    def _run_optimisation(self) -> OptimisationResult:
        with self._lock:
            recent = list(self._trades[-self.eval_window * 3:])   # use 3× window for training

        objective = self.objective_factory(recent)
        opt = self.optimiser_class(self.space, objective)
        # Different optimiser classes use different keyword names
        try:
            result = opt.optimise(n_iterations=self.opt_iterations)
        except TypeError:
            try:
                result = opt.optimise(max_evals=self.opt_iterations)
            except TypeError:
                result = opt.optimise()

        with self._lock:
            self._current_params = result.best_params
            self._optimisation_history.append(result)

        logger.info(
            "[AdaptiveLearning] Re-optimised: score=%.4f params=%s",
            result.best_score, result.best_params,
        )

        if self.on_params_updated:
            try:
                self.on_params_updated(result.best_params)
            except Exception as exc:
                logger.warning("[AdaptiveLearning] on_params_updated error: %s", exc)

        return result

    def history(self) -> List[Dict]:
        with self._lock:
            return [r.to_dict() for r in self._optimisation_history]


# ---------------------------------------------------------------------------
# Reinforcement Learning Adapter
# ---------------------------------------------------------------------------

class RLFeedbackAdapter:
    """
    Thin shim over the existing LiveRLFeedback module (if present),
    or a simple EMA-based reward tracker as fallback.

    Purpose: provide a uniform record_outcome() / get_adjusted_params()
    interface regardless of which RL backend is available.
    """

    def __init__(
        self,
        base_params: Dict[str, float],
        learning_rate: float = 0.05,
        discount: float = 0.95,
    ):
        self.base_params = dict(base_params)
        self.learning_rate = learning_rate
        self.discount = discount
        self._ema_reward: float = 0.0
        self._adjustment: Dict[str, float] = {}
        self._outcomes: List[Dict] = []

        if _RL_AVAILABLE:
            try:
                self._rl = LiveRLFeedback()
                logger.info("[RLAdapter] Using LiveRLFeedback")
            except Exception:
                self._rl = None
        else:
            self._rl = None

    def record_outcome(self, trade: Dict, reward: float) -> None:
        """
        Record a trade outcome with its reward signal.

        Args:
            trade: Trade dict containing 'params_used' key (Dict).
            reward: Scalar reward (positive = profitable, negative = loss).
        """
        if self._rl:
            try:
                self._rl.record_outcome(trade, reward)
                return
            except Exception as exc:
                logger.debug("[RLAdapter] LiveRL error: %s", exc)

        # EMA fallback
        self._ema_reward = self.discount * self._ema_reward + (1 - self.discount) * reward
        params_used = trade.get("params_used", {})

        # Nudge parameters in direction that produced positive reward
        for name, val in params_used.items():
            if name in self.base_params:
                direction = 1.0 if reward > 0 else -1.0
                delta = direction * self.learning_rate * abs(val - self.base_params[name])
                self._adjustment[name] = self._adjustment.get(name, 0.0) + delta

        self._outcomes.append({"trade": trade, "reward": reward})

    def get_adjusted_params(self) -> Dict[str, float]:
        """Return base parameters adjusted by accumulated RL feedback."""
        if self._rl:
            try:
                return self._rl.get_adjusted_params()
            except Exception:
                pass

        adjusted = dict(self.base_params)
        for name, delta in self._adjustment.items():
            adjusted[name] = adjusted.get(name, 0.0) + delta
        return adjusted

    @property
    def ema_reward(self) -> float:
        return self._ema_reward

    def summary(self) -> Dict:
        return {
            "ema_reward": round(self._ema_reward, 6),
            "n_outcomes": len(self._outcomes),
            "adjusted_params": self.get_adjusted_params(),
            "backend": "LiveRLFeedback" if self._rl else "EMA_fallback",
        }
