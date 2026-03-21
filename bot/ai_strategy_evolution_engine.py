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
  │  set_regime(regime)    ← push current market regime (TRENDING etc.)  │
  │  pull_regime()         ← auto-read regime from MarketRegimeController│
  │  get_genome_multipliers(id) ← base + regime-adjusted capital/conf    │
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

    # Push the current market regime so multipliers are regime-weighted
    evo.set_regime("TRENDING")               # explicit push
    # — or —
    evo.pull_regime()                        # auto-read from MarketRegimeController

    # Retrieve effective (regime-adjusted) capital & confidence multipliers
    mults = evo.get_genome_multipliers("genome-003")
    position_size *= mults["effective_capital_multiplier"]
    entry_confidence *= mults["effective_confidence_multiplier"]

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
MIN_TRADES_FOR_FITNESS: int = 10   # minimum trades per genome before fitness is meaningful

# Evolution safety gates — prevent overfitting on small / noisy samples
MIN_TRADES_BEFORE_EVOLVE: int = 50   # total trades across population before any cycle runs
MIN_WIN_RATE_THRESHOLD: float = 0.55 # population aggregate win rate required to evolve
BASELINE_GENOME_COUNT: int = 2       # number of initial genomes frozen as permanent baselines

# Risk-adjusted fitness normalisation window
# Maps return/volatility ratio from [-1, 3] → [0, 1]
RISK_ADJ_OFFSET: float = 1.0
RISK_ADJ_SCALE: float = 4.0

# Capital & confidence multiplier settings
RECENT_WINDOW: int = 20          # rolling trade window for real-time multiplier
CAPITAL_MULT_MIN: float = 0.50   # floor – reduce allocation 50% after poor run
CAPITAL_MULT_MAX: float = 2.00   # ceiling – at most double allocation
CAPITAL_MULT_SENSITIVITY: float = 0.50   # how steeply capital multiplier responds
CONFIDENCE_MULT_MIN: float = 0.50        # floor for confidence multiplier
CONFIDENCE_MULT_MAX: float = 1.50        # ceiling for confidence multiplier
CONFIDENCE_MULT_SENSITIVITY: float = 0.25  # half the sensitivity of capital

# Regime-weighted capital scale factors
# Applied on top of the base capital & confidence multipliers.
# Volatile / chaotic markets pull back risk; trending markets let it grow.
REGIME_CAPITAL_SCALE: Dict[str, float] = {
    "TRENDING":  1.2,   # strong directional movement  → compound aggressively
    "RANGING":   1.0,   # sideways / choppy            → neutral sizing
    "CHAOTIC":   0.8,   # extreme volatility / crisis  → protect capital
    "VOLATILE":  0.8,   # alias used by some detectors → same as CHAOTIC
    "BULL":      1.2,   # legacy alias for TRENDING
    "BEAR":      0.8,   # legacy alias for CHAOTIC
    "UNKNOWN":   1.0,   # no data yet                  → neutral
}

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

    # Real-time capital & confidence multipliers (updated after every trade)
    capital_multiplier: float = 1.0
    confidence_multiplier: float = 1.0

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

    def recent_rar(self) -> float:
        """Return / Volatility computed over the last RECENT_WINDOW trades.

        This is the real-time signal used to drive the capital and
        confidence multipliers; it reacts faster than the full-history
        ``sharpe()`` because it only looks at the most recent trades.
        """
        recent = self.pnl_history[-RECENT_WINDOW:]
        if len(recent) < 5:
            return 0.0
        arr = np.asarray(recent)
        vol = float(arr.std(ddof=1))
        return float(arr.mean() / vol) if vol > 1e-9 else 0.0

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
        # Self-adjust multipliers in real-time after every new trade
        self._update_multipliers()

    def _update_multipliers(self) -> None:
        """Recompute capital and confidence multipliers from recent performance.

        Both multipliers are driven by the rolling-window return/volatility
        ratio (``recent_rar``).  When recent performance is strong the
        multipliers rise above 1.0, increasing capital deployment and signal
        confidence; when performance deteriorates they fall below 1.0,
        pulling back risk automatically.

        Formula (per multiplier)::

            multiplier = clamp(1.0 + recent_rar * sensitivity, MIN, MAX)

        Capital is more aggressive (higher sensitivity / wider bounds) than
        confidence so that position sizing reacts quickly while entry
        confidence scores remain smoother.
        """
        rar = self.recent_rar()
        self.capital_multiplier = round(
            max(CAPITAL_MULT_MIN, min(CAPITAL_MULT_MAX,
                                      1.0 + rar * CAPITAL_MULT_SENSITIVITY)),
            4,
        )
        self.confidence_multiplier = round(
            max(CONFIDENCE_MULT_MIN, min(CONFIDENCE_MULT_MAX,
                                         1.0 + rar * CONFIDENCE_MULT_SENSITIVITY)),
            4,
        )

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
        rar = round(self.sharpe(), 4)
        return {
            "genome_id": self.genome_id,
            "generation": self.generation,
            "fitness": round(self.fitness, 4),
            "trade_count": self.trade_count,
            "win_rate": round(self.win_rate(), 4),
            # "return_volatility_ratio" is the canonical key; "sharpe" is kept
            # for backward compatibility with existing dashboards and reports.
            "return_volatility_ratio": rar,
            "sharpe": rar,
            "volatility": round(self.volatility(), 4),
            "profit_factor": round(self.profit_factor(), 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "capital_multiplier": self.capital_multiplier,
            "confidence_multiplier": self.confidence_multiplier,
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

        # Regime-weighted capital layer
        self._current_regime: str = "UNKNOWN"
        self._regime_scale: float = REGIME_CAPITAL_SCALE["UNKNOWN"]

        # Evolution safety tracking
        self._total_recorded_trades: int = 0
        # Frozen baseline snapshots — deep-copied at init, never overwritten.
        # These reference strategies are re-injected after each cycle to
        # prevent the entire population from drifting toward short-term noise.
        self._frozen_baselines: List[StrategyGenome] = []

        self._init_population(population_size)
        logger.info(
            "🧬 AIStrategyEvolutionEngine initialised with %d genomes "
            "(%d baseline(s) frozen).",
            population_size,
            len(self._frozen_baselines),
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
        # Freeze the first BASELINE_GENOME_COUNT genomes as permanent references
        for g in self._population[:BASELINE_GENOME_COUNT]:
            self._frozen_baselines.append(deepcopy(g))

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
                self._total_recorded_trades += 1
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

        Evolution is gated by two safety checks to prevent overfitting on
        short-term noise:

        1. **Minimum trades** — at least ``MIN_TRADES_BEFORE_EVOLVE`` trades
           must have been recorded across the whole population before any
           genetic operators run.
        2. **Minimum win rate** — the population aggregate win rate must be
           ≥ ``MIN_WIN_RATE_THRESHOLD`` (0.55) before allowing evolution.

        After each cycle the frozen baseline genomes are re-injected at the
        bottom of the population (replacing the weakest non-baseline entries)
        so there are always reference strategies in the gene pool.

        Returns a report dict with population statistics.
        """
        with self._lock:
            # ── Gate 1: require MIN_TRADES_BEFORE_EVOLVE total trades ─────────
            if self._total_recorded_trades < MIN_TRADES_BEFORE_EVOLVE:
                skipped_summary = {
                    "skipped": True,
                    "reason": (
                        f"Not enough trades to evolve: "
                        f"{self._total_recorded_trades} / {MIN_TRADES_BEFORE_EVOLVE}"
                    ),
                    "generation": self._generation,
                    "total_recorded_trades": self._total_recorded_trades,
                }
                logger.info(
                    "🧬 Evolution skipped — %d / %d trades required",
                    self._total_recorded_trades,
                    MIN_TRADES_BEFORE_EVOLVE,
                )
                return skipped_summary

            # ── Gate 2: require aggregate win rate ≥ MIN_WIN_RATE_THRESHOLD ───
            total_t = sum(g.trade_count for g in self._population)
            total_w = sum(g.win_count for g in self._population)
            agg_win_rate = (total_w / total_t) if total_t > 0 else 0.0
            if agg_win_rate < MIN_WIN_RATE_THRESHOLD:
                skipped_summary = {
                    "skipped": True,
                    "reason": (
                        f"Aggregate win rate {agg_win_rate:.2%} below "
                        f"threshold {MIN_WIN_RATE_THRESHOLD:.2%}"
                    ),
                    "generation": self._generation,
                    "aggregate_win_rate": round(agg_win_rate, 4),
                }
                logger.info(
                    "🧬 Evolution skipped — aggregate win rate %.1f%% < %.0f%% threshold",
                    agg_win_rate * 100,
                    MIN_WIN_RATE_THRESHOLD * 100,
                )
                return skipped_summary

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

            # 5. Re-inject frozen baselines — replace the tail (weakest) entries
            #    so reference strategies are always present in the gene pool.
            baseline_ids = {b.genome_id for b in self._frozen_baselines}
            existing_ids = {g.genome_id for g in self._population}
            missing = [b for b in self._frozen_baselines if b.genome_id not in existing_ids]
            if missing:
                # Sort population worst-first; skip any that are already baselines
                non_baseline = [g for g in self._population if g.genome_id not in baseline_ids]
                non_baseline.sort(key=lambda g: g.fitness)
                for baseline in missing:
                    if non_baseline:
                        worst = non_baseline.pop(0)
                        idx = next(
                            (i for i, g in enumerate(self._population)
                             if g.genome_id == worst.genome_id),
                            None,
                        )
                        if idx is not None:
                            self._population[idx] = deepcopy(baseline)
                logger.debug(
                    "🧬 %d frozen baseline(s) re-injected into population",
                    len(missing),
                )

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
    # Public: regime-weighted capital layer
    # ------------------------------------------------------------------

    def set_regime(self, regime: str) -> None:
        """Push the current market regime into the engine.

        Call this once per scan cycle (after your regime detector runs) so
        that :meth:`get_genome_multipliers` can apply the correct scale.

        Parameters
        ----------
        regime:
            One of ``"TRENDING"``, ``"RANGING"``, ``"CHAOTIC"``, or any
            alias defined in ``REGIME_CAPITAL_SCALE``.  Unknown values fall
            back to the neutral scale (1.0).
        """
        regime_upper = regime.upper()
        scale = REGIME_CAPITAL_SCALE.get(regime_upper, REGIME_CAPITAL_SCALE["UNKNOWN"])
        with self._lock:
            self._current_regime = regime_upper
            self._regime_scale = scale
        logger.debug(
            "🌐 Regime updated: %s → scale=%.2f", regime_upper, scale
        )

    def pull_regime(self) -> str:
        """Auto-read the current regime from :class:`MarketRegimeController`.

        Queries the process-level ``MarketRegimeController`` singleton and
        calls :meth:`set_regime` if a classified result is available.
        Silently no-ops when the controller is unavailable or has not yet
        produced a result, preserving the last known regime.

        Returns
        -------
        str
            The regime name that is now active (``"UNKNOWN"`` when the
            controller could not be reached).
        """
        try:
            try:
                from bot.market_regime_controller import get_market_regime_controller
            except ImportError:
                try:
                    from market_regime_controller import get_market_regime_controller  # type: ignore
                except ImportError as imp_err:
                    logger.debug("pull_regime: market_regime_controller not importable (%s)", imp_err)
                    return self._current_regime

            ctrl = get_market_regime_controller()
            controls = ctrl.current_controls
            if controls is not None:
                self.set_regime(controls.regime.value)
        except Exception as exc:  # noqa: BLE001
            logger.debug("pull_regime: controller unavailable (%s) — keeping %s",
                         exc, self._current_regime)
        return self._current_regime

    def get_genome_multipliers(self, genome_id: str) -> Dict[str, Any]:
        """Return base and regime-adjusted multipliers for a genome.

        The *effective* multipliers are the product of the genome's
        performance-driven base multipliers and the current regime scale::

            effective_capital    = clamp(capital_multiplier    * regime_scale,
                                         CAPITAL_MULT_MIN, CAPITAL_MULT_MAX)
            effective_confidence = clamp(confidence_multiplier * regime_scale,
                                         CONFIDENCE_MULT_MIN, CONFIDENCE_MULT_MAX)

        Parameters
        ----------
        genome_id:
            The genome whose multipliers should be returned.  If the genome
            is not found, neutral multipliers (1.0) are returned.

        Returns
        -------
        dict with keys:
            ``capital_multiplier``, ``confidence_multiplier``,
            ``regime``, ``regime_scale``,
            ``effective_capital_multiplier``, ``effective_confidence_multiplier``
        """
        with self._lock:
            g = self._find_genome(genome_id)
            base_cap  = g.capital_multiplier    if g else 1.0
            base_conf = g.confidence_multiplier if g else 1.0
            regime       = self._current_regime
            regime_scale = self._regime_scale

        eff_cap = round(
            max(CAPITAL_MULT_MIN,  min(CAPITAL_MULT_MAX,  base_cap  * regime_scale)), 4
        )
        eff_conf = round(
            max(CONFIDENCE_MULT_MIN, min(CONFIDENCE_MULT_MAX, base_conf * regime_scale)), 4
        )
        return {
            "capital_multiplier":            base_cap,
            "confidence_multiplier":         base_conf,
            "regime":                        regime,
            "regime_scale":                  regime_scale,
            "effective_capital_multiplier":  eff_cap,
            "effective_confidence_multiplier": eff_conf,
        }

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
            "regime": self._current_regime,
            "regime_scale": self._regime_scale,
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
