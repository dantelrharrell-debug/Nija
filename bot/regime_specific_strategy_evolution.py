"""
NIJA Regime-Specific Strategy Evolution
=========================================

Extends the genetic-algorithm evolution engine so that each market regime
maintains its **own independent population** of strategy parameter genomes.
This means strategies evolve separately for trending, ranging, and volatile
markets rather than competing in a single shared pool.

Key features
------------
* **Per-regime populations** – isolated gene pools for each regime so that
  optimal parameters for one regime do not corrupt another.
* **Cross-regime insight sharing** – the single best genome from a source
  regime can seed a target regime's pool as a *bootstrap candidate* (with
  reset fitness) when the target has too few trades to have evolved.
* **Regime-aware evolve cycle** – call :meth:`evolve` with a ``regime``
  argument to run one evolution cycle on just that regime's population.
  Calling without a regime evolves all regimes in one pass.
* **Champion lookup by regime** – :meth:`get_best_genome` accepts an
  optional ``regime`` to retrieve the champion for a specific context.
* **Unified reporting** – :meth:`get_report` returns per-regime population
  health plus a cross-regime champion leaderboard.

Architecture
------------
::

    ┌──────────────────────────────────────────────────────────┐
    │           RegimeSpecificStrategyEvolution                │
    │                                                          │
    │  populations: {regime: [StrategyGenome × N]}            │
    │                                                          │
    │  record_trade(genome_id, regime, pnl_pct, is_win)        │
    │    → routes to correct regime population                 │
    │                                                          │
    │  evolve(regime?)                                         │
    │    → score → select → crossover → mutate → replace       │
    │      (per regime independently)                          │
    │                                                          │
    │  get_best_genome(regime?)                                │
    │    → champion of that regime, or overall champion        │
    │                                                          │
    │  share_insight(from_regime, to_regime)                   │
    │    → inject champion genome from one regime into another │
    └──────────────────────────────────────────────────────────┘

Public API
----------
::

    from bot.regime_specific_strategy_evolution import (
        get_regime_specific_strategy_evolution,
    )

    evo = get_regime_specific_strategy_evolution()

    # Record a trade (always provide the regime)
    evo.record_trade(
        genome_id="trending-genome-003",
        regime="TRENDING",
        pnl_pct=1.8,
        is_win=True,
    )

    # Evolve only the TRENDING population
    report = evo.evolve(regime="TRENDING")

    # Evolve all regimes at once
    report = evo.evolve()

    # Get the best parameters for the current regime
    champion = evo.get_best_genome(regime="TRENDING")
    print(champion.params)

    # Share insight between regimes
    evo.share_insight(from_regime="TRENDING", to_regime="RANGING")

    # Full dashboard
    full_report = evo.get_report()

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

logger = logging.getLogger("nija.regime_specific_strategy_evolution")

# ---------------------------------------------------------------------------
# Constants (inheriting from the base evolution engine where sensible)
# ---------------------------------------------------------------------------

POPULATION_SIZE: int = 16          # genomes per regime
TOURNAMENT_SIZE: int = 4
CROSSOVER_RATE: float = 0.70
MUTATION_RATE: float = 0.20
MUTATION_SIGMA: float = 0.15
ELITISM_COUNT: int = 2
MIN_TRADES_FOR_FITNESS: int = 8    # slightly lower – regimes see fewer trades
INSIGHT_FRACTION: float = 0.10     # fraction of target pool replaced by shared insight
MAX_PNL_HISTORY: int = 500         # rolling window of per-genome trade results
MAX_EVOLUTION_HISTORY: int = 100   # stored evolution cycle summaries per regime

# Evolution safety gates — prevent overfitting on small / noisy samples
MIN_TRADES_BEFORE_EVOLVE: int = 50   # total trades per-regime population before evolving
MIN_WIN_RATE_THRESHOLD: float = 0.55 # population aggregate win rate required to evolve
BASELINE_GENOME_COUNT: int = 2       # frozen reference genomes per regime population

# Fitness normalisation anchors
# Sharpe normalization: maps [-1, 3] → [0, 1] via (sharpe + 1) / 4.
# Most crypto strategies have Sharpe in roughly -1 (poor) to 3 (excellent).
SHARPE_NORM_OFFSET: float = 1.0
SHARPE_NORM_SCALE: float = 4.0
# Drawdown normalization: a max-drawdown of MAX_EXPECTED_DRAWDOWN_PCT or more
# maps to a score of 0.  Values below it scale linearly toward 1.
MAX_EXPECTED_DRAWDOWN_PCT: float = 10.0

# Fitness weights
W_SHARPE: float = 0.40
W_WIN_RATE: float = 0.30
W_PROFIT_FACTOR: float = 0.20
W_MAX_DD: float = 0.10

# Canonical regime names and regime-specific parameter bounds
KNOWN_REGIMES: List[str] = [
    "TRENDING",
    "RANGING",
    "VOLATILE",
]

# Shared base parameter space
_BASE_PARAM_BOUNDS: Dict[str, Tuple[float, float, bool]] = {
    "rsi_period_fast":    (5,    20,  True),
    "rsi_period_slow":    (14,   30,  True),
    "rsi_oversold":       (20,   45,  False),
    "rsi_overbought":     (55,   80,  False),
    "atr_multiplier":     (1.0,  4.0, False),
    "profit_target_pct":  (0.5,  8.0, False),
    "stop_loss_pct":      (0.3,  4.0, False),
    "position_size_pct":  (0.01, 0.05, False),
    "ema_fast":           (5,    20,  True),
    "ema_slow":           (20,   60,  True),
    "volume_filter_mult": (1.0,  3.0, False),
    "adx_threshold":      (15,   35,  False),
}

# Per-regime parameter overrides – nudge the search space toward what
# works in each regime to accelerate evolution.
_REGIME_PARAM_OVERRIDES: Dict[str, Dict[str, Tuple[float, float, bool]]] = {
    "TRENDING": {
        "rsi_oversold":      (40,   60,  False),  # momentum bias: buy higher
        "rsi_overbought":    (65,   85,  False),
        "adx_threshold":     (22,   40,  False),  # only trade strong trends
        "profit_target_pct": (1.5,  8.0, False),  # ride the trend longer
        "atr_multiplier":    (1.5,  4.0, False),
    },
    "RANGING": {
        "rsi_oversold":      (20,   35,  False),  # mean-reversion: buy low
        "rsi_overbought":    (65,   80,  False),  # sell high
        "adx_threshold":     (10,   22,  False),  # low ADX preferred
        "profit_target_pct": (0.5,  3.0, False),  # tight targets
        "atr_multiplier":    (1.0,  2.5, False),
    },
    "VOLATILE": {
        "rsi_period_fast":   (5,    12,  True),   # faster signals
        "atr_multiplier":    (2.0,  5.0, False),  # wider stops for noise
        "profit_target_pct": (1.0,  6.0, False),
        "volume_filter_mult":(1.5,  3.5, False),  # higher volume bar required
        "position_size_pct": (0.01, 0.03, False), # smaller size in chaos
    },
}


# ---------------------------------------------------------------------------
# Regime-genome data structure
# ---------------------------------------------------------------------------

@dataclass
class RegimeGenome:
    """A strategy parameter set scoped to a specific market regime."""
    genome_id: str
    regime: str
    params: Dict[str, float]
    generation: int = 0

    trade_count: int = 0
    win_count: int = 0
    total_pnl_pct: float = 0.0
    pnl_history: List[float] = field(default_factory=list)
    peak_pnl: float = 0.0
    max_drawdown: float = 0.0
    fitness: float = 0.0

    def win_rate(self) -> float:
        return self.win_count / self.trade_count if self.trade_count > 0 else 0.0

    def sharpe(self) -> float:
        if len(self.pnl_history) < 5:
            return 0.0
        arr = np.asarray(self.pnl_history)
        std = float(arr.std(ddof=1))
        return float(arr.mean() / std) if std > 1e-9 else 0.0

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
        if len(self.pnl_history) > MAX_PNL_HISTORY:
            self.pnl_history = self.pnl_history[-MAX_PNL_HISTORY:]
        cumulative = sum(self.pnl_history)
        self.peak_pnl = max(self.peak_pnl, cumulative)
        dd = self.peak_pnl - cumulative
        self.max_drawdown = max(self.max_drawdown, dd)

    def compute_fitness(self) -> float:
        if self.trade_count < MIN_TRADES_FOR_FITNESS:
            return 0.0
        sharpe_norm = max(0.0, min(1.0, (self.sharpe() + SHARPE_NORM_OFFSET) / SHARPE_NORM_SCALE))
        wr_norm = self.win_rate()
        pf = self.profit_factor()
        pf_norm = max(0.0, min(1.0, (pf - 1) / 3))
        dd_norm = max(0.0, 1.0 - self.max_drawdown / MAX_EXPECTED_DRAWDOWN_PCT)
        f = (
            W_SHARPE * sharpe_norm
            + W_WIN_RATE * wr_norm
            + W_PROFIT_FACTOR * pf_norm
            + W_MAX_DD * dd_norm
        )
        self.fitness = round(f, 6)
        return self.fitness

    def to_dict(self) -> Dict[str, Any]:
        return {
            "genome_id": self.genome_id,
            "regime": self.regime,
            "generation": self.generation,
            "fitness": round(self.fitness, 4),
            "trade_count": self.trade_count,
            "win_rate": round(self.win_rate(), 4),
            "sharpe": round(self.sharpe(), 4),
            "profit_factor": round(self.profit_factor(), 4),
            "max_drawdown": round(self.max_drawdown, 4),
            "params": {k: round(v, 4) for k, v in self.params.items()},
        }


# ---------------------------------------------------------------------------
# Per-regime population manager
# ---------------------------------------------------------------------------

class RegimePopulation:
    """Manages the genome pool for a single market regime."""

    def __init__(
        self,
        regime: str,
        size: int = POPULATION_SIZE,
        rng: Optional[random.Random] = None,
    ) -> None:
        self.regime = regime
        self._rng = rng or random.Random()
        self._population: List[RegimeGenome] = []
        self._generation: int = 0
        self._evolution_history: List[Dict[str, Any]] = []
        self._next_idx: int = 0
        # Evolution safety tracking
        self._total_recorded_trades: int = 0
        self._frozen_baselines: List[RegimeGenome] = []
        self._init_population(size)

    # --- Initialisation ---

    def _param_bounds(self) -> Dict[str, Tuple[float, float, bool]]:
        """Return merged parameter bounds for this regime."""
        bounds = dict(_BASE_PARAM_BOUNDS)
        bounds.update(_REGIME_PARAM_OVERRIDES.get(self.regime, {}))
        return bounds

    def _random_params(self) -> Dict[str, float]:
        params: Dict[str, float] = {}
        for name, (lo, hi, is_int) in self._param_bounds().items():
            val = self._rng.uniform(lo, hi)
            params[name] = round(val) if is_int else round(val, 4)
        return params

    def _init_population(self, size: int) -> None:
        for i in range(size):
            genome = RegimeGenome(
                genome_id=f"{self.regime.lower()}-genome-{i:03d}",
                regime=self.regime,
                params=self._random_params(),
            )
            self._population.append(genome)
        self._next_idx = size
        # Freeze the first BASELINE_GENOME_COUNT genomes as permanent references
        for g in self._population[:BASELINE_GENOME_COUNT]:
            self._frozen_baselines.append(deepcopy(g))

    # --- Trade recording ---

    def find_genome(self, genome_id: str) -> Optional[RegimeGenome]:
        for g in self._population:
            if g.genome_id == genome_id:
                return g
        return None

    def record_trade(self, genome_id: str, pnl_pct: float) -> bool:
        genome = self.find_genome(genome_id)
        if genome is not None:
            genome.record_trade(pnl_pct)
            self._total_recorded_trades += 1
            return True
        return False

    # --- Evolution ---

    def evolve_cycle(self) -> Dict[str, Any]:
        """Run one full evolution cycle on this regime's population.

        Gated by:

        1. ``MIN_TRADES_BEFORE_EVOLVE`` total trades recorded for this regime.
        2. Aggregate population win rate ≥ ``MIN_WIN_RATE_THRESHOLD``.

        Frozen baseline genomes are re-injected after each successful cycle.
        """
        # ── Gate 1: require MIN_TRADES_BEFORE_EVOLVE total trades ─────────────
        if self._total_recorded_trades < MIN_TRADES_BEFORE_EVOLVE:
            logger.info(
                "🧬 [%s] Evolution skipped — %d / %d trades required",
                self.regime,
                self._total_recorded_trades,
                MIN_TRADES_BEFORE_EVOLVE,
            )
            return {
                "regime": self.regime,
                "skipped": True,
                "reason": (
                    f"Not enough trades: {self._total_recorded_trades} / "
                    f"{MIN_TRADES_BEFORE_EVOLVE}"
                ),
                "generation": self._generation,
            }

        # ── Gate 2: require aggregate win rate ≥ MIN_WIN_RATE_THRESHOLD ───────
        total_t = sum(g.trade_count for g in self._population)
        total_w = sum(g.win_count for g in self._population)
        agg_win_rate = (total_w / total_t) if total_t > 0 else 0.0
        if agg_win_rate < MIN_WIN_RATE_THRESHOLD:
            logger.info(
                "🧬 [%s] Evolution skipped — win rate %.1f%% < %.0f%% threshold",
                self.regime,
                agg_win_rate * 100,
                MIN_WIN_RATE_THRESHOLD * 100,
            )
            return {
                "regime": self.regime,
                "skipped": True,
                "reason": (
                    f"Aggregate win rate {agg_win_rate:.2%} below "
                    f"threshold {MIN_WIN_RATE_THRESHOLD:.2%}"
                ),
                "generation": self._generation,
                "aggregate_win_rate": round(agg_win_rate, 4),
            }

        # Score fitness, then sort, then evolve
        for g in self._population:
            g.compute_fitness()

        self._population.sort(key=lambda g: g.fitness, reverse=True)

        elites = [deepcopy(g) for g in self._population[:ELITISM_COUNT]]
        offspring: List[RegimeGenome] = list(elites)

        while len(offspring) < len(self._population):
            pa = self._tournament_select()
            pb = self._tournament_select()
            child_params = self._crossover(pa.params, pb.params)
            child_params = self._mutate(child_params)
            child = RegimeGenome(
                genome_id=f"{self.regime.lower()}-genome-{self._next_idx:03d}",
                regime=self.regime,
                params=child_params,
                generation=self._generation + 1,
            )
            offspring.append(child)
            self._next_idx += 1

        self._generation += 1
        self._population = offspring[: len(self._population)]

        # Re-inject frozen baselines — replace the tail (weakest) entries so
        # reference strategies are always present in the gene pool.
        baseline_ids = {b.genome_id for b in self._frozen_baselines}
        existing_ids = {g.genome_id for g in self._population}
        missing = [b for b in self._frozen_baselines if b.genome_id not in existing_ids]
        if missing:
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
                "🧬 [%s] %d frozen baseline(s) re-injected",
                self.regime, len(missing),
            )

        summary = self._build_summary()
        self._evolution_history.append(summary)
        if len(self._evolution_history) > MAX_EVOLUTION_HISTORY:
            self._evolution_history = self._evolution_history[-MAX_EVOLUTION_HISTORY:]

        return summary

    # --- Genetic operators ---

    def _tournament_select(self) -> RegimeGenome:
        candidates = self._rng.sample(
            self._population, min(TOURNAMENT_SIZE, len(self._population))
        )
        return max(candidates, key=lambda g: g.fitness)

    def _crossover(
        self, params_a: Dict[str, float], params_b: Dict[str, float]
    ) -> Dict[str, float]:
        if self._rng.random() > CROSSOVER_RATE:
            return deepcopy(params_a)
        child: Dict[str, float] = {}
        for key in params_a:
            child[key] = params_a[key] if self._rng.random() < 0.5 else params_b[key]
        return child

    def _mutate(self, params: Dict[str, float]) -> Dict[str, float]:
        mutated = dict(params)
        bounds = self._param_bounds()
        for name, (lo, hi, is_int) in bounds.items():
            if name in mutated and self._rng.random() < MUTATION_RATE:
                delta = self._rng.gauss(0, MUTATION_SIGMA) * (hi - lo)
                val = mutated[name] + delta
                val = max(lo, min(hi, val))
                mutated[name] = round(val) if is_int else round(val, 4)
        return mutated

    # --- Insight injection ---

    def inject_genome(self, donor: RegimeGenome) -> None:
        """
        Inject a genome from another regime as a fresh candidate.

        The donor's params are kept but all fitness/trade stats are reset
        so it has to prove itself in this regime's context.
        """
        newcomer = RegimeGenome(
            genome_id=f"{self.regime.lower()}-genome-{self._next_idx:03d}",
            regime=self.regime,
            params=deepcopy(donor.params),
            generation=self._generation,
        )
        self._next_idx += 1
        # Replace the weakest genome
        self._population.sort(key=lambda g: g.fitness, reverse=True)
        self._population[-1] = newcomer
        logger.info(
            "💡 Cross-regime insight: '%s' genome injected into '%s' population",
            donor.regime,
            self.regime,
        )

    # --- Reporting ---

    def get_champion(self) -> Optional[RegimeGenome]:
        if not self._population:
            return None
        return max(self._population, key=lambda g: g.fitness)

    def _build_summary(self) -> Dict[str, Any]:
        fitnesses = [g.fitness for g in self._population]
        champion = self._population[0] if self._population else None
        return {
            "regime": self.regime,
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
        summary = self._build_summary()
        return {
            **summary,
            "evolution_history_tail": list(self._evolution_history[-10:]),
            "population": [g.to_dict() for g in self._population],
        }


# ---------------------------------------------------------------------------
# Top-level RegimeSpecificStrategyEvolution
# ---------------------------------------------------------------------------

class RegimeSpecificStrategyEvolution:
    """
    Genetic-algorithm evolution engine with per-regime populations.

    Each :data:`KNOWN_REGIMES` entry has its own :class:`RegimePopulation`.
    Unknown regimes are created on-demand so the engine never rejects data.
    """

    def __init__(
        self,
        regimes: Optional[List[str]] = None,
        population_size: int = POPULATION_SIZE,
        seed: Optional[int] = None,
    ) -> None:
        self._rng = random.Random(seed)
        if seed is not None:
            np.random.seed(seed)

        self._populations: Dict[str, RegimePopulation] = {}
        self._lock = threading.Lock()
        self._total_evolutions: int = 0

        target_regimes = regimes or KNOWN_REGIMES
        for regime in target_regimes:
            self._populations[regime.upper()] = RegimePopulation(
                regime=regime.upper(),
                size=population_size,
                rng=self._rng,
            )

        logger.info(
            "🧬 RegimeSpecificStrategyEvolution initialised | "
            "regimes=%s | population_size=%d",
            list(self._populations.keys()),
            population_size,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_regime(self, regime: str, size: int = POPULATION_SIZE) -> RegimePopulation:
        key = regime.upper()
        if key not in self._populations:
            logger.info("🆕 Creating new regime population for '%s'", key)
            self._populations[key] = RegimePopulation(
                regime=key, size=size, rng=self._rng
            )
        return self._populations[key]

    # ------------------------------------------------------------------
    # Public: trade recording
    # ------------------------------------------------------------------

    def record_trade(
        self,
        genome_id: str,
        regime: str,
        pnl_pct: float,
        is_win: bool,
    ) -> None:
        """
        Feed a completed trade result to the correct regime population.

        Args:
            genome_id: The genome ID that generated the trade signal.
            regime:    Market regime active when the trade was taken.
            pnl_pct:   Percentage P&L of the trade.
            is_win:    True if the trade closed profitably.
        """
        with self._lock:
            pop = self._ensure_regime(regime)
            found = pop.record_trade(genome_id, pnl_pct)
            if not found:
                logger.debug(
                    "⚠️ record_trade: genome '%s' not found in regime '%s'.",
                    genome_id,
                    regime.upper(),
                )

    # ------------------------------------------------------------------
    # Public: evolution
    # ------------------------------------------------------------------

    def evolve(self, regime: Optional[str] = None) -> Dict[str, Any]:
        """
        Run one evolution cycle.

        Args:
            regime: If provided, evolve only that regime's population.
                    If ``None``, evolve all regimes in sequence.

        Returns:
            Summary dict.  If a single regime was specified the summary is
            for that regime only; otherwise it contains a ``"regimes"`` key
            with per-regime summaries plus an overall ``"champion"`` entry.
        """
        with self._lock:
            self._total_evolutions += 1

            if regime is not None:
                pop = self._ensure_regime(regime)
                summary = pop.evolve_cycle()
                logger.info(
                    "🧬 Regime '%s' gen=%d champion_fitness=%.4f",
                    regime.upper(),
                    summary["generation"],
                    summary["champion_fitness"],
                )
                return summary

            # Evolve all regimes
            results: Dict[str, Any] = {}
            for key, pop in self._populations.items():
                results[key] = pop.evolve_cycle()
                logger.info(
                    "🧬 Regime '%s' gen=%d champion_fitness=%.4f",
                    key,
                    results[key]["generation"],
                    results[key]["champion_fitness"],
                )

            # Cross-regime champion leaderboard
            champions = []
            for key, summary in results.items():
                champions.append({
                    "regime": key,
                    "champion_genome_id": summary["champion_genome_id"],
                    "champion_fitness": summary["champion_fitness"],
                })
            champions.sort(key=lambda x: x["champion_fitness"], reverse=True)

            return {
                "total_evolutions": self._total_evolutions,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "regimes": results,
                "champion_leaderboard": champions,
            }

    # ------------------------------------------------------------------
    # Public: genome retrieval
    # ------------------------------------------------------------------

    def get_best_genome(
        self, regime: Optional[str] = None
    ) -> Optional[RegimeGenome]:
        """
        Return the champion genome.

        Args:
            regime: If supplied, return the champion for that regime.
                    If ``None``, return the overall cross-regime champion.
        """
        with self._lock:
            if regime is not None:
                pop = self._ensure_regime(regime)
                return pop.get_champion()

            best: Optional[RegimeGenome] = None
            for pop in self._populations.values():
                candidate = pop.get_champion()
                if candidate is not None:
                    if best is None or candidate.fitness > best.fitness:
                        best = candidate
            return best

    def get_population(self, regime: str) -> List[RegimeGenome]:
        """Return the genome list for a specific regime."""
        with self._lock:
            return list(self._ensure_regime(regime)._population)

    # ------------------------------------------------------------------
    # Public: cross-regime insight sharing
    # ------------------------------------------------------------------

    def share_insight(self, from_regime: str, to_regime: str) -> bool:
        """
        Copy the champion genome from ``from_regime`` into ``to_regime``'s
        population, replacing the weakest genome.

        This is useful when a target regime has too little trade history to
        have evolved good parameters independently — it can bootstrap from
        a well-evolved sibling regime.

        Args:
            from_regime: Source regime (donor).
            to_regime:   Target regime (recipient).

        Returns:
            ``True`` if the injection succeeded, ``False`` if the donor
            had no champion yet.
        """
        with self._lock:
            donor_pop = self._ensure_regime(from_regime)
            champion = donor_pop.get_champion()
            if champion is None:
                logger.warning(
                    "share_insight: no champion in '%s', nothing to share.",
                    from_regime.upper(),
                )
                return False

            target_pop = self._ensure_regime(to_regime)
            target_pop.inject_genome(champion)
            return True

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_report(self) -> Dict[str, Any]:
        """Return the full multi-regime evolution report."""
        with self._lock:
            regime_reports: Dict[str, Any] = {}
            champions: List[Dict[str, Any]] = []

            for key, pop in self._populations.items():
                regime_reports[key] = pop.get_report()
                champ = pop.get_champion()
                if champ:
                    champions.append({
                        "regime": key,
                        "genome_id": champ.genome_id,
                        "fitness": round(champ.fitness, 4),
                        "trade_count": champ.trade_count,
                        "win_rate": round(champ.win_rate(), 4),
                        "sharpe": round(champ.sharpe(), 4),
                        "params": champ.params,
                    })

            champions.sort(key=lambda x: x["fitness"], reverse=True)

            return {
                "total_evolutions": self._total_evolutions,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "regimes": regime_reports,
                "champion_leaderboard": champions,
            }


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_rse_instance: Optional[RegimeSpecificStrategyEvolution] = None
_rse_lock = threading.Lock()


def get_regime_specific_strategy_evolution(
    regimes: Optional[List[str]] = None,
    population_size: int = POPULATION_SIZE,
    seed: Optional[int] = None,
) -> RegimeSpecificStrategyEvolution:
    """Return the process-level singleton RegimeSpecificStrategyEvolution."""
    global _rse_instance
    if _rse_instance is None:
        with _rse_lock:
            if _rse_instance is None:
                _rse_instance = RegimeSpecificStrategyEvolution(
                    regimes=regimes,
                    population_size=population_size,
                    seed=seed,
                )
    return _rse_instance


# ---------------------------------------------------------------------------
# CLI self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import json as _json

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)-8s %(name)s: %(message)s",
    )

    evo = RegimeSpecificStrategyEvolution(population_size=8, seed=42)

    # Simulate trades across all regimes
    regimes_sim = ["TRENDING", "RANGING", "VOLATILE"]
    for _ in range(300):
        regime = random.choice(regimes_sim)
        pop = evo.get_population(regime)
        genome = random.choice(pop)
        # Trending trades tend to be more profitable
        mean = 0.6 if regime == "TRENDING" else (0.1 if regime == "RANGING" else 0.3)
        pnl = random.gauss(mean, 1.2)
        evo.record_trade(genome.genome_id, regime, pnl, pnl > 0)

    # Evolution cycles per regime
    for cycle in range(4):
        report = evo.evolve()
        print(f"\n=== Evolution round {cycle + 1} ===")
        for regime_key, r in report["regimes"].items():
            print(
                f"  [{regime_key:<10}] gen={r['generation']} "
                f"champion={r['champion_genome_id']} "
                f"fitness={r['champion_fitness']:.4f} "
                f"avg={r['avg_fitness']:.4f}"
            )
        print("  Leaderboard:", report["champion_leaderboard"])

    # Cross-regime insight sharing
    print("\n--- Cross-regime insight: TRENDING → RANGING ---")
    evo.share_insight("TRENDING", "RANGING")

    # Final report
    print("\n--- Regime champion params ---")
    for regime in regimes_sim:
        champ = evo.get_best_genome(regime=regime)
        if champ:
            print(
                f"  {regime}: genome={champ.genome_id} "
                f"fitness={champ.fitness:.4f} trades={champ.trade_count}"
            )
