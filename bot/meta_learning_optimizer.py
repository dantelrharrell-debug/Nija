"""
Meta-Learning Optimizer
========================

Implements AI-driven optimization across three dimensions:

1. Strategy weighting across market regimes
   - Maintains per-regime EMA-based performance scores for each strategy.
   - Automatically up-weights strategies that perform well in the current
     regime and down-weights underperformers.

2. Risk-adjusted capital allocation
   - Uses Sharpe-ratio-weighted allocation across strategies.
   - Enforces min/max allocation bounds.
   - Applies drawdown-based penalty to reduce allocation during bad runs.

3. Continuous A/B testing between strategy variants
   - Splits traffic between a "champion" and one or more "challengers".
   - Evaluates statistical significance using a simple z-test on win-rates.
   - Promotes challenger to champion when significance threshold is reached.

Usage
-----
    from bot.meta_learning_optimizer import get_meta_learning_optimizer

    opt = get_meta_learning_optimizer()

    # Record a trade outcome
    opt.record_outcome(
        strategy="ApexTrend",
        regime="BULL_TRENDING",
        pnl=120.0,
        won=True,
        drawdown_pct=2.1,
    )

    # Get current weights
    weights = opt.get_regime_weights(regime="BULL_TRENDING")

    # A/B test routing
    variant = opt.ab_route("ApexTrend")

    # Evaluate A/B test
    opt.evaluate_ab_tests()

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.meta_learning_optimizer")

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

MIN_ALLOCATION_PCT   = 0.05   # 5 % floor per strategy
MAX_ALLOCATION_PCT   = 0.60   # 60 % ceiling per strategy
EMA_DECAY            = 0.88   # EMA smoothing factor (≈ 8-period half-life)
AB_SIGNIFICANCE      = 0.95   # confidence level for promotion decision
AB_MIN_TRIALS        = 50     # minimum trials before evaluating AB test
DRAWDOWN_PENALTY_RATE = 0.5   # allocation multiplier reduction per 10 % drawdown

KNOWN_STRATEGIES = [
    "ApexTrend",
    "MeanReversion",
    "MomentumBreakout",
    "LiquidityReversal",
    "Macro",
]

KNOWN_REGIMES = [
    "BULL_TRENDING",
    "BEAR_TRENDING",
    "RANGING",
    "VOLATILE",
    "CRISIS",
    "UNKNOWN",
]


# ─────────────────────────────────────────────────────────────────────────────
# Data structures
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class StrategyRegimeStats:
    """EMA-smoothed performance for one strategy in one market regime."""
    strategy: str
    regime:   str
    ema_return:       float = 0.0
    ema_win_rate:     float = 0.5
    ema_pf:           float = 1.0    # profit factor
    ema_drawdown:     float = 0.0
    ema_sharpe:       float = 0.0
    trades:           int   = 0
    gross_profit:     float = 0.0
    gross_loss:       float = 0.0
    last_updated:     str   = ""

    @property
    def composite_score(self) -> float:
        """0–1 score blending sharpe, win-rate, and profit-factor."""
        sharpe_part = math.tanh(self.ema_sharpe / 2.0)     # maps to (0, 1)
        wr_part     = self.ema_win_rate                      # 0–1
        pf_part     = math.tanh((self.ema_pf - 1.0) / 1.0) # maps excess PF to (0, 1)
        dd_penalty  = max(0.0, 1.0 - self.ema_drawdown / 20.0)
        return max(0.01, (sharpe_part * 0.40 + wr_part * 0.30 + pf_part * 0.30) * dd_penalty)


@dataclass
class ABVariant:
    """Single variant in an A/B test."""
    name:        str
    wins:        int   = 0
    trials:      int   = 0
    total_pnl:   float = 0.0
    is_champion: bool  = False

    @property
    def win_rate(self) -> float:
        return self.wins / self.trials if self.trials else 0.0

    @property
    def avg_pnl(self) -> float:
        return self.total_pnl / self.trials if self.trials else 0.0


@dataclass
class ABTest:
    """An ongoing A/B test between strategy variants."""
    strategy:   str
    champion:   ABVariant = field(default_factory=lambda: ABVariant("champion", is_champion=True))
    challenger: ABVariant = field(default_factory=lambda: ABVariant("challenger"))
    started_at: str = ""
    resolved_at: str = ""
    result:     str = ""   # "champion_wins" | "challenger_promoted" | "ongoing"
    split_pct:  float = 0.20   # fraction of traffic sent to challenger


# ─────────────────────────────────────────────────────────────────────────────
# Core class
# ─────────────────────────────────────────────────────────────────────────────

class MetaLearningOptimizer:
    """
    AI-driven meta-learning optimizer.

    Parameters
    ----------
    state_path : str
        JSON path for persistence.
    ema_decay : float
        EMA decay factor (higher = more weight on recent trades).
    """

    def __init__(
        self,
        state_path: str = "data/meta_learning_state.json",
        ema_decay: float = EMA_DECAY,
    ) -> None:
        self.state_path = state_path
        self.ema_decay  = ema_decay
        self._lock      = threading.RLock()

        # regime → strategy → stats
        self._stats: Dict[str, Dict[str, StrategyRegimeStats]] = {}
        # strategy → ABTest
        self._ab_tests: Dict[str, ABTest] = {}

        self._load_state()
        logger.info("🧠 MetaLearningOptimizer ready | ema_decay=%.2f", ema_decay)

    # ── Recording ─────────────────────────────────────────────────────────────

    def record_outcome(
        self,
        strategy: str,
        regime: str,
        pnl: float,
        won: bool,
        drawdown_pct: float = 0.0,
        capital: float = 10_000.0,
    ) -> None:
        """Record a completed trade for a given strategy and regime."""
        with self._lock:
            stats = self._get_or_create_stats(strategy, regime)
            α = 1.0 - self.ema_decay

            # EMA updates
            ret = pnl / max(1.0, capital)
            stats.ema_return   = self.ema_decay * stats.ema_return   + α * ret
            stats.ema_win_rate = self.ema_decay * stats.ema_win_rate + α * float(won)
            stats.ema_drawdown = self.ema_decay * stats.ema_drawdown + α * drawdown_pct

            if pnl > 0:
                stats.gross_profit += pnl
            else:
                stats.gross_loss += abs(pnl)

            pf = stats.gross_profit / stats.gross_loss if stats.gross_loss > 0 else 2.0
            stats.ema_pf = self.ema_decay * stats.ema_pf + α * pf

            # Very rough Sharpe proxy: return / std (using EMA return / |EMA return|)
            vol_proxy = max(0.001, abs(stats.ema_return))
            stats.ema_sharpe = stats.ema_return / vol_proxy

            stats.trades += 1
            stats.last_updated = _now()

            self._save_state()

    # ── Weight computation ────────────────────────────────────────────────────

    def get_regime_weights(self, regime: str) -> Dict[str, float]:
        """
        Return normalized capital allocation weights for every strategy
        in the given regime.  Missing strategies receive a neutral score.
        """
        with self._lock:
            regime_stats = self._stats.get(regime, {})
            scores: Dict[str, float] = {}
            for strat in KNOWN_STRATEGIES:
                if strat in regime_stats:
                    scores[strat] = regime_stats[strat].composite_score
                else:
                    scores[strat] = 0.10   # neutral prior

            # Normalize
            total = sum(scores.values()) or 1.0
            raw   = {s: v / total for s, v in scores.items()}

            # Enforce min / max allocation bounds
            weights = self._enforce_bounds(raw)
            return weights

    def get_risk_adjusted_allocations(
        self, regime: str, total_capital: float
    ) -> Dict[str, float]:
        """Return dollar allocations per strategy (Sharpe-weighted)."""
        weights = self.get_regime_weights(regime)
        return {s: w * total_capital for s, w in weights.items()}

    # ── A/B testing ───────────────────────────────────────────────────────────

    def register_ab_test(
        self,
        strategy: str,
        challenger_name: str = "challenger",
        split_pct: float = 0.20,
    ) -> None:
        """Register a new A/B test for a strategy variant."""
        with self._lock:
            if strategy in self._ab_tests and self._ab_tests[strategy].result == "ongoing":
                logger.info("[MetaLearning] A/B test for %s already active.", strategy)
                return
            test = ABTest(
                strategy=strategy,
                champion=ABVariant("champion", is_champion=True),
                challenger=ABVariant(challenger_name),
                started_at=_now(),
                result="ongoing",
                split_pct=max(0.05, min(0.50, split_pct)),
            )
            self._ab_tests[strategy] = test
            logger.info(
                "[MetaLearning] A/B test registered for %s | split=%.0f%%",
                strategy, split_pct * 100,
            )
            self._save_state()

    def ab_route(self, strategy: str) -> str:
        """
        Route one trade to a variant.

        Returns "champion" or "challenger" (or "champion" if no test active).
        """
        with self._lock:
            test = self._ab_tests.get(strategy)
            if test is None or test.result != "ongoing":
                return "champion"
            import random
            return "challenger" if random.random() < test.split_pct else "champion"

    def record_ab_outcome(
        self, strategy: str, variant: str, pnl: float, won: bool
    ) -> None:
        """Record the outcome of a trade routed to a specific A/B variant."""
        with self._lock:
            test = self._ab_tests.get(strategy)
            if test is None:
                return
            v = test.champion if variant == "champion" else test.challenger
            v.trials    += 1
            v.wins      += int(won)
            v.total_pnl += pnl
            self._save_state()

    def evaluate_ab_tests(self) -> List[Dict[str, Any]]:
        """
        Evaluate all active A/B tests.  Promotes challenger if statistically
        superior; retains champion otherwise.  Returns evaluation summaries.
        """
        summaries = []
        with self._lock:
            for strategy, test in self._ab_tests.items():
                if test.result != "ongoing":
                    continue

                c = test.champion
                ch = test.challenger

                if c.trials < AB_MIN_TRIALS or ch.trials < AB_MIN_TRIALS:
                    summaries.append({
                        "strategy": strategy,
                        "status":   "insufficient_data",
                        "champion_trials":   c.trials,
                        "challenger_trials": ch.trials,
                    })
                    continue

                # Two-proportion z-test (one-tailed: challenger > champion)
                z, significant = _two_prop_z_test(
                    ch.wins, ch.trials,
                    c.wins,  c.trials,
                    confidence=AB_SIGNIFICANCE,
                )

                if significant:
                    # Promote challenger
                    test.result      = "challenger_promoted"
                    test.resolved_at = _now()
                    logger.info(
                        "🏆 [AB] Challenger PROMOTED for %s | "
                        "champion WR=%.1f%% vs challenger WR=%.1f%% (z=%.2f)",
                        strategy, c.win_rate * 100, ch.win_rate * 100, z,
                    )
                    summaries.append({
                        "strategy":   strategy,
                        "status":     "challenger_promoted",
                        "z_score":    round(z, 3),
                        "champion_win_rate":   round(c.win_rate, 4),
                        "challenger_win_rate": round(ch.win_rate, 4),
                    })
                else:
                    # Keep champion
                    test.result      = "champion_wins"
                    test.resolved_at = _now()
                    logger.info(
                        "👑 [AB] Champion RETAINED for %s (z=%.2f, not significant)",
                        strategy, z,
                    )
                    summaries.append({
                        "strategy":   strategy,
                        "status":     "champion_retained",
                        "z_score":    round(z, 3),
                    })

            self._save_state()
        return summaries

    # ── Status ────────────────────────────────────────────────────────────────

    def status(self) -> Dict[str, Any]:
        with self._lock:
            regime_summaries: Dict[str, Any] = {}
            for regime in KNOWN_REGIMES:
                weights = self.get_regime_weights(regime)
                regime_summaries[regime] = weights

            ab_summaries = {}
            for strategy, test in self._ab_tests.items():
                ab_summaries[strategy] = {
                    "status":            test.result,
                    "champion_trials":   test.champion.trials,
                    "champion_win_rate": round(test.champion.win_rate, 4),
                    "challenger_trials": test.challenger.trials,
                    "challenger_win_rate": round(test.challenger.win_rate, 4),
                }

            return {
                "regime_weights": regime_summaries,
                "ab_tests":       ab_summaries,
                "total_strategies_tracked": sum(
                    len(v) for v in self._stats.values()
                ),
            }

    # ── Internals ─────────────────────────────────────────────────────────────

    def _get_or_create_stats(self, strategy: str, regime: str) -> StrategyRegimeStats:
        if regime not in self._stats:
            self._stats[regime] = {}
        if strategy not in self._stats[regime]:
            self._stats[regime][strategy] = StrategyRegimeStats(
                strategy=strategy, regime=regime
            )
        return self._stats[regime][strategy]

    def _enforce_bounds(self, raw: Dict[str, float]) -> Dict[str, float]:
        """Clip each weight to [MIN, MAX] then re-normalise."""
        clipped = {s: max(MIN_ALLOCATION_PCT, min(MAX_ALLOCATION_PCT, w)) for s, w in raw.items()}
        total   = sum(clipped.values()) or 1.0
        return {s: v / total for s, v in clipped.items()}

    def _load_state(self) -> None:
        try:
            if os.path.exists(self.state_path):
                with open(self.state_path) as fh:
                    data = json.load(fh)
                # Reconstruct stats
                for regime, strats in data.get("stats", {}).items():
                    self._stats[regime] = {}
                    for strat, sd in strats.items():
                        self._stats[regime][strat] = StrategyRegimeStats(**{
                            k: v for k, v in sd.items()
                            if k in StrategyRegimeStats.__dataclass_fields__
                        })
                # Reconstruct AB tests
                for strategy, td in data.get("ab_tests", {}).items():
                    champ = ABVariant(**{k: v for k, v in td.get("champion", {}).items()
                                        if k in ABVariant.__dataclass_fields__})
                    chall = ABVariant(**{k: v for k, v in td.get("challenger", {}).items()
                                        if k in ABVariant.__dataclass_fields__})
                    test  = ABTest(
                        strategy=strategy,
                        champion=champ,
                        challenger=chall,
                        started_at=td.get("started_at", ""),
                        resolved_at=td.get("resolved_at", ""),
                        result=td.get("result", "ongoing"),
                        split_pct=td.get("split_pct", 0.20),
                    )
                    self._ab_tests[strategy] = test
                logger.info("[MetaLearning] State restored from %s", self.state_path)
        except Exception as exc:
            logger.warning("[MetaLearning] Could not load state (%s) – starting fresh.", exc)

    def _save_state(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            stats_serialisable: Dict[str, Any] = {}
            for regime, strats in self._stats.items():
                stats_serialisable[regime] = {
                    s: asdict(v) for s, v in strats.items()
                }
            ab_serialisable: Dict[str, Any] = {}
            for strategy, test in self._ab_tests.items():
                ab_serialisable[strategy] = {
                    "champion":   asdict(test.champion),
                    "challenger": asdict(test.challenger),
                    "started_at":  test.started_at,
                    "resolved_at": test.resolved_at,
                    "result":      test.result,
                    "split_pct":   test.split_pct,
                }
            with open(self.state_path, "w") as fh:
                json.dump({"stats": stats_serialisable, "ab_tests": ab_serialisable}, fh, indent=2)
        except Exception as exc:
            logger.warning("[MetaLearning] Could not persist state: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

_optimizer_instance: Optional[MetaLearningOptimizer] = None
_optimizer_lock = threading.Lock()


def get_meta_learning_optimizer(
    state_path: str = "data/meta_learning_state.json",
    **kwargs: Any,
) -> MetaLearningOptimizer:
    """Return the process-wide MetaLearningOptimizer singleton."""
    global _optimizer_instance
    with _optimizer_lock:
        if _optimizer_instance is None:
            _optimizer_instance = MetaLearningOptimizer(
                state_path=state_path, **kwargs
            )
    return _optimizer_instance


# ─────────────────────────────────────────────────────────────────────────────
# Statistical helper
# ─────────────────────────────────────────────────────────────────────────────

def _two_prop_z_test(
    wins_a: int, n_a: int,
    wins_b: int, n_b: int,
    confidence: float = 0.95,
) -> Tuple[float, bool]:
    """
    One-tailed two-proportion z-test (H1: p_a > p_b).

    Returns (z_score, is_significant).
    """
    if n_a == 0 or n_b == 0:
        return 0.0, False

    p_a = wins_a / n_a
    p_b = wins_b / n_b
    p_pool = (wins_a + wins_b) / (n_a + n_b)

    denom = math.sqrt(p_pool * (1 - p_pool) * (1 / n_a + 1 / n_b))
    if denom == 0:
        return 0.0, False

    z = (p_a - p_b) / denom

    # Map confidence to z-threshold (approximate standard normal critical values)
    z_critical = {0.90: 1.282, 0.95: 1.645, 0.99: 2.326}.get(confidence, 1.645)
    return z, z >= z_critical


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()
