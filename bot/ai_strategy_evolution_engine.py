"""
NIJA AI Strategy Evolution Engine
===================================

Evolves trading strategies autonomously using genetic-algorithm-inspired
mutation, fitness scoring, and natural selection.

Architecture
------------
::

  ┌─────────────────────────────────────────────────────────────────────┐
  │                   AIStrategyEvolutionEngine                          │
  │                                                                     │
  │  population: [StrategyGenome × N]                                   │
  │                                                                     │
  │  evolve_cycle()                                                      │
  │    1. score_fitness()  ← return / volatility (risk-adjusted)         │
  │    2. select_parents() ← top-K tournament selection                  │
  │    3. crossover()      ← blend parameter genes from two parents      │
  │    4. mutate()         ← Gaussian noise on continuous params         │
  │    5. replace_weakest()← swap bottom performers with offspring        │
  │                                                                     │
  │  record_trade()        ← feed live results to update fitness         │
  │  get_best_genome()     ← retrieve current champion parameters        │
  │  get_report()          ← population health dashboard                 │
  └─────────────────────────────────────────────────────────────────────┘

Public API
----------
::

    from bot.ai_strategy_evolution_engine import get_ai_strategy_evolution_engine

    evo = get_ai_strategy_evolution_engine()

    # Record live trade outcomes to drive fitness scoring
    evo.record_trade(
        genome_id="genome-003",
        pnl_pct=1.2,
        is_win=True,
        regime="BULL",
    )

    # Trigger an evolution cycle (call periodically, e.g., every 4 hours)
    report = evo.evolve_cycle()

    # Retrieve best-performing parameter set
    champion = evo.get_best_genome()
    print(champion.params)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import math
import random
import threading
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("nija.ai_strategy_evolution_engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

POPULATION_SIZE: int = 20          # number of strategy genomes
TOURNAMENT_SIZE: int = 4           # parents per tournament
CROSSOVER_RATE: float = 0.70       # probability of crossover vs. cloning
MUTATION_RATE: float = 0.20        # probability each gene mutates
MUTATION_SIGMA: float = 0.15       # Gaussian σ for continuous gene mutation
ELITISM_COUNT: int = 2             # top-N genomes preserved each generation
MIN_TRADES_FOR_FITNESS: int = 10   # minimum trades before fitness is meaningful

# Risk-adjusted fitness normalisation window
# Maps return/volatility ratio from [-1, 3] → [0, 1]
RISK_ADJ_OFFSET: float = 1.0
RISK_ADJ_SCALE: float = 4.0

# Parameter bounds  {param_name: (min, max, is_int)}
PARAM_BOUNDS: Dict[str, Tuple[float, float, bool]] = {
    "rsi_period_fast":       (5,    20,  True),
    "rsi_period_slow":       (14,   30,  True),
    "rsi_oversold":          (20,   40,  False),
    "rsi_overbought":        (60,   80,  False),
    "atr_multiplier":        (1.0,  4.0, False),
    "profit_target_pct":     (0.5,  8.0, False),
    "stop_loss_pct":         (0.3,  4.0, False),
    "position_size_pct":     (0.01, 0.05, False),
    "ema_fast":              (5,    20,  True),
    "ema_slow":              (20,   60,  True),
    "volume_filter_mult":    (1.0,  3.0, False),
    "adx_threshold":         (15,   35,  False),
}


# ---------------------------------------------------------------------------
# Data Structures
# ---------------------------------------------------------------------------

@dataclass
class StrategyGenome:
    """A single candidate strategy parameter set."""
    genome_id: str
    params: Dict[str, float]
    generation: int = 0

    # Live fitness tracking
    trade_count: int = 0
    win_count: int = 0
    total_pnl_pct: float = 0.0
    pnl_history: List[float] = field(default_factory=list)
    peak_pnl: float = 0.0
    max_drawdown: float = 0.0

    # Computed fitness (updated after each evolve_cycle)
    fitness: float = 0.0

    def win_rate(self) -> float:
        return self.win_count / self.trade_count if self.trade_count > 0 else 0.0

    def volatility(self) -> float:
        """Standard deviation of trade returns."""
        if len(self.pnl_history) < 2:
            return 0.0
        return float(np.asarray(self.pnl_history).std(ddof=1))

    def sharpe(self) -> float:
        """Return / Volatility (Sharpe ratio without risk-free rate)."""
        vol = self.volatility()
        if vol < 1e-9 or len(self.pnl_history) < 5:
            return 0.0
        return float(np.asarray(self.pnl_history).mean() / vol)

    def profit_factor(self) -> float:
        wins = [p for p in self.pnl_history if p > 0]
        losses = [abs(p) for p in self.pnl_history if p < 0]
        if not losses:
            return 10.0 if wins else 1.0
        return sum(wins) / sum(losses)

    def record_trade(self, pnl_pct: float) -> None:
        self.trade_count += 1
        if pnl_pct > 0:
            self.win_count += 1
        self.total_pnl_pct += pnl_pct
        self.pnl_history.append(pnl_pct)
        if len(self.pnl_history) > 500:
            self.pnl_history = self.pnl_history[-500:]
        # Update drawdown
        cumulative = sum(self.pnl_history)
        self.peak_pnl = max(self.peak_pnl, cumulative)
        dd = self.peak_pnl - cumulative
        self.max_drawdown = max(self.max_drawdown, dd)

    def compute_fitness(self) -> float:
        """Risk-adjusted fitness: fitness = return / volatility.

        Uses the mean trade return divided by the standard deviation of
        returns (a Sharpe-like ratio without a risk-free rate deduction).
        The raw ratio is normalised to [0, 1] via:
            fitness = clamp((rar + RISK_ADJ_OFFSET) / RISK_ADJ_SCALE, 0, 1)
        which maps the typical range [-1, 3] onto [0, 1].
        """
        if self.trade_count < MIN_TRADES_FOR_FITNESS:
            return 0.0

        rar = self.sharpe()  # return / volatility
        f = max(0.0, min(1.0, (rar + RISK_ADJ_OFFSET) / RISK_ADJ_SCALE))
        self.fitness = round(f, 6)
        return self.fitness

    def to_dict(self) -> Dict[str, Any]:
        return {
            "genome_id": self.genome_id,
            "generation": self.generation,
            "fitness": round(self.fitness, 4),
            "trade_count": self.trade_count,
            "win_rate": round(self.win_rate(), 4),
            "return_volatility_ratio": round(self.sharpe(), 4),
            "volatility": round(self.volatility(), 4),
            "sharpe": round(self.sharpe(), 4),
            "profit_factor": round(self.profit_factor(), 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "params": {k: round(v, 4) for k, v in self.params.items()},
        }


# ---------------------------------------------------------------------------
# AI Strategy Evolution Engine
# ---------------------------------------------------------------------------

class AIStrategyEvolutionEngine:
    """
    Genetic-algorithm evolution engine for trading strategy parameters.

    The engine maintains a *population* of :class:`StrategyGenome` objects.
    Each genome represents a distinct parameter set.  Live trade results are
    routed back to the appropriate genome, and periodic ``evolve_cycle()``
    calls replace weak performers with offspring of the fittest.
    """

    def __init__(
        self,
        population_size: int = POPULATION_SIZE,
        seed: Optional[int] = None,
    ) -> None:
        if seed is not None:
            random.seed(seed)
            np.random.seed(seed)

        self._population: List[StrategyGenome] = []
        self._generation: int = 0
        self._lock = threading.Lock()
        self._evolution_history: List[Dict[str, Any]] = []

        self._init_population(population_size)
        logger.info(
            "🧬 AIStrategyEvolutionEngine initialised with %d genomes.",
            population_size,
        )

    # ------------------------------------------------------------------
    # Population initialisation
    # ------------------------------------------------------------------

    def _init_population(self, size: int) -> None:
        for i in range(size):
            genome = StrategyGenome(
                genome_id=f"genome-{i:03d}",
                params=self._random_params(),
            )
            self._population.append(genome)

    def _random_params(self) -> Dict[str, float]:
        params: Dict[str, float] = {}
        for name, (lo, hi, is_int) in PARAM_BOUNDS.items():
            val = random.uniform(lo, hi)
            params[name] = round(val) if is_int else round(val, 4)
        return params

    # ------------------------------------------------------------------
    # Public: trade recording
    # ------------------------------------------------------------------

    def record_trade(
        self,
        genome_id: str,
        pnl_pct: float,
        is_win: bool,
        regime: str = "UNKNOWN",
    ) -> None:
        """Feed a live trade result to the owning genome."""
        with self._lock:
            genome = self._find_genome(genome_id)
            if genome is not None:
                genome.record_trade(pnl_pct)
            else:
                logger.debug("⚠️ record_trade: genome %s not found.", genome_id)

    def _find_genome(self, genome_id: str) -> Optional[StrategyGenome]:
        for g in self._population:
            if g.genome_id == genome_id:
                return g
        return None

    # ------------------------------------------------------------------
    # Public: evolution cycle
    # ------------------------------------------------------------------

    def evolve_cycle(self) -> Dict[str, Any]:
        """
        Run one full evolution cycle:
        score → select → crossover → mutate → replace.

        Returns a report dict with population statistics.
        """
        with self._lock:
            # 1. Score fitness
            for g in self._population:
                g.compute_fitness()

            # 2. Sort by fitness (descending)
            self._population.sort(key=lambda g: g.fitness, reverse=True)

            # 3. Elites survive unchanged
            elites = [deepcopy(g) for g in self._population[:ELITISM_COUNT]]

            # 4. Generate offspring
            offspring: List[StrategyGenome] = list(elites)
            replacement_count = len(self._population) - ELITISM_COUNT
            genome_idx = len(self._population)  # for unique IDs
            while len(offspring) < len(self._population):
                parent_a = self._tournament_select()
                parent_b = self._tournament_select()
                child_params = self._crossover(parent_a.params, parent_b.params)
                child_params = self._mutate(child_params)
                child = StrategyGenome(
                    genome_id=f"genome-{genome_idx:03d}",
                    params=child_params,
                    generation=self._generation + 1,
                )
                offspring.append(child)
                genome_idx += 1

            self._generation += 1
            self._population = offspring[:len(self._population)]

            summary = self._build_summary()
            self._evolution_history.append(summary)
            if len(self._evolution_history) > 100:
                self._evolution_history = self._evolution_history[-100:]

        logger.info(
            "🧬 Evolution gen=%d | champion fitness=%.4f | "
            "avg fitness=%.4f | replacement=%d",
            self._generation,
            summary["champion_fitness"],
            summary["avg_fitness"],
            replacement_count,
        )
        return summary

    # ------------------------------------------------------------------
    # Genetic operators
    # ------------------------------------------------------------------

    def _tournament_select(self) -> StrategyGenome:
        """Select one genome via tournament selection."""
        candidates = random.sample(self._population, min(TOURNAMENT_SIZE, len(self._population)))
        return max(candidates, key=lambda g: g.fitness)

    def _crossover(
        self, params_a: Dict[str, float], params_b: Dict[str, float]
    ) -> Dict[str, float]:
        """Uniform crossover or clone."""
        if random.random() > CROSSOVER_RATE:
            return deepcopy(params_a)
        child: Dict[str, float] = {}
        for key in params_a:
            child[key] = params_a[key] if random.random() < 0.5 else params_b[key]
        return child

    def _mutate(self, params: Dict[str, float]) -> Dict[str, float]:
        """Apply Gaussian mutation to each gene with probability MUTATION_RATE."""
        mutated = dict(params)
        for name, (lo, hi, is_int) in PARAM_BOUNDS.items():
            if random.random() < MUTATION_RATE:
                delta = random.gauss(0, MUTATION_SIGMA) * (hi - lo)
                val = mutated[name] + delta
                val = max(lo, min(hi, val))
                mutated[name] = round(val) if is_int else round(val, 4)
        return mutated

    # ------------------------------------------------------------------
    # Public: best genome retrieval
    # ------------------------------------------------------------------

    def get_best_genome(self) -> Optional[StrategyGenome]:
        """Return the current champion genome (highest fitness)."""
        with self._lock:
            if not self._population:
                return None
            return max(self._population, key=lambda g: g.fitness)

    def get_population(self) -> List[StrategyGenome]:
        with self._lock:
            return list(self._population)

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def _build_summary(self) -> Dict[str, Any]:
        fitnesses = [g.fitness for g in self._population]
        champion = self._population[0] if self._population else None
        return {
            "generation": self._generation,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "population_size": len(self._population),
            "champion_genome_id": champion.genome_id if champion else None,
            "champion_fitness": round(champion.fitness, 4) if champion else 0.0,
            "champion_params": champion.params if champion else {},
            "avg_fitness": round(float(np.mean(fitnesses)), 4) if fitnesses else 0.0,
            "max_fitness": round(float(np.max(fitnesses)), 4) if fitnesses else 0.0,
            "min_fitness": round(float(np.min(fitnesses)), 4) if fitnesses else 0.0,
        }

    def get_report(self) -> Dict[str, Any]:
        """Return full evolution report including population state."""
        with self._lock:
            summary = self._build_summary()
            population_state = [g.to_dict() for g in self._population]
            history = list(self._evolution_history[-10:])
        return {
            **summary,
            "evolution_history_tail": history,
            "population": population_state,
        }


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_evo_instance: Optional[AIStrategyEvolutionEngine] = None
_evo_lock = threading.Lock()


def get_ai_strategy_evolution_engine(
    population_size: int = POPULATION_SIZE,
    seed: Optional[int] = None,
) -> AIStrategyEvolutionEngine:
    """Return the process-level singleton AIStrategyEvolutionEngine."""
    global _evo_instance
    if _evo_instance is None:
        with _evo_lock:
            if _evo_instance is None:
                _evo_instance = AIStrategyEvolutionEngine(
                    population_size=population_size, seed=seed
                )
    return _evo_instance


# ---------------------------------------------------------------------------
# CLI self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import random as _rnd

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    evo = get_ai_strategy_evolution_engine(population_size=10, seed=42)

    # Simulate 200 trades across random genomes
    pop = evo.get_population()
    for _ in range(200):
        genome = _rnd.choice(pop)
        pnl = _rnd.gauss(0.3, 1.2)
        evo.record_trade(genome.genome_id, pnl, pnl > 0)

    # Run 3 evolution cycles
    for cycle in range(3):
        report = evo.evolve_cycle()
        print(
            f"Gen {report['generation']}: "
            f"champion={report['champion_genome_id']} "
            f"fitness={report['champion_fitness']:.4f} "
            f"avg={report['avg_fitness']:.4f}"
        )

    champion = evo.get_best_genome()
    if champion:
        print(f"\n🏆 Champion params: {champion.params}")
