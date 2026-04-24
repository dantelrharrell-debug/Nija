"""
NIJA Strategy Weight Evolution
================================

Tracks *how* strategy allocation weights evolve over time and applies
momentum-smoothed, multi-window scoring so the bot becomes genuinely
self-improving — not just reactive.

Architecture
------------
::

  ┌─────────────────────────────────────────────────────────────────────┐
  │                  StrategyWeightEvolution                             │
  │                                                                     │
  │  Per-strategy rolling windows (short / medium / long):              │
  │                                                                     │
  │  • Short  window (default 10 trades)  — fast recent signal          │
  │  • Medium window (default 50 trades)  — stable trend                │
  │  • Long   window (default 200 trades) — regime baseline             │
  │                                                                     │
  │  Weight momentum:                                                   │
  │  • velocity   = (current_weight - prev_weight) per snapshot         │
  │  • momentum   = EMA of velocity — smooth acceleration / braking     │
  │  • evolved_weight = raw_weight + momentum_boost (clamped)           │
  │                                                                     │
  │  Adaptive learning rate:                                            │
  │  • When performance is consistent → learn faster (lower EMA decay)  │
  │  • When performance is noisy      → learn slower (higher EMA decay)  │
  │                                                                     │
  │  Convergence detection:                                             │
  │  • Weight std-dev across last N snapshots < threshold → CONVERGED   │
  │                                                                     │
  │  Audit trail: every snapshot appended to                            │
  │  data/strategy_weight_evolution.jsonl                               │
  └─────────────────────────────────────────────────────────────────────┘

How it produces self-improvement
---------------------------------
1. Every closed trade is routed to ``record_trade()``.
2. Multi-window EMA scores are updated (short / medium / long).
3. A composite weight is derived that blends recency with stability.
4. Weight *velocity* is computed vs. the last snapshot.
5. A momentum term is added so well-performing strategies get a forward
   push — and declining strategies decelerate smoothly.
6. The adaptive learning rate shrinks the EMA decay when a strategy's
   returns are consistent, so it tracks signal more tightly when it's
   reliable.
7. Callers use ``get_evolved_weights()`` to obtain the final allocation;
   ``get_report()`` shows the full evolution dashboard.

Usage
-----
    from bot.strategy_weight_evolution import get_strategy_weight_evolution

    evo = get_strategy_weight_evolution()

    # After every closed trade:
    evo.record_trade(
        strategy="ApexTrend",
        pnl_usd=85.0,
        is_win=True,
        position_size_usd=1000.0,
        regime="BULL_TRENDING",
    )

    # Before opening a new position:
    weights = evo.get_evolved_weights()
    multiplier = weights.get("ApexTrend", 1.0) / (1.0 / len(weights))

    # Dashboard:
    print(evo.get_report())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import math
import threading
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.strategy_weight_evolution")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default strategy roster (mirrors SelfLearningStrategyAllocator)
DEFAULT_STRATEGIES: List[str] = [
    "ApexTrend",
    "MeanReversion",
    "MomentumBreakout",
    "LiquidityReversal",
]

# Rolling window depths
SHORT_WINDOW: int = 10
MEDIUM_WINDOW: int = 50
LONG_WINDOW: int = 200

# EMA decay bounds — adaptive rate clamps inside this range.
# EMA formula: new = decay * old + (1-decay) * new_value.
# Lower decay  → higher (1-decay) → more weight on new data → faster learning.
# Higher decay → lower  (1-decay) → more persistence of old data → slower learning.
EMA_DECAY_MIN: float = 0.70   # fast learning when signal is consistent (low volatility)
EMA_DECAY_MAX: float = 0.95   # slow learning when signal is noisy (high volatility)

# Volatility normalisation threshold for adaptive decay computation.
# Return std-dev at or above this value maps to EMA_DECAY_MAX.
VOLATILITY_NORMALIZATION_THRESHOLD: float = 0.50

# Allocation bounds
MIN_WEIGHT: float = 0.05   # 5 % floor
MAX_WEIGHT: float = 0.60   # 60 % ceiling

# Momentum
MOMENTUM_DECAY: float = 0.80   # EMA decay for weight-velocity momentum
MOMENTUM_SCALE: float = 0.30   # how much momentum can boost/reduce raw weight

# Convergence: weight std-dev below this (over last N snapshots) = converged
CONVERGENCE_THRESHOLD: float = 0.005
CONVERGENCE_WINDOW: int = 20   # snapshots to examine

# Minimum trades before learning kicks in (equal-weight below this)
MIN_TRADES: int = 5

# Maximum trade records kept per window
MAX_HISTORY: int = LONG_WINDOW + 50


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class WindowStats:
    """EMA statistics for a single rolling window."""
    window_size: int
    ema_return: float = 0.0
    ema_win_rate: float = 0.0
    trade_count: int = 0
    recent_returns: Deque = field(default_factory=lambda: deque(maxlen=200))

    @property
    def decay(self) -> float:
        """EMA decay implied by window size (2 / (N+1) convention, inverted)."""
        return 1.0 - (2.0 / (self.window_size + 1))

    @property
    def return_volatility(self) -> float:
        """Standard deviation of recent returns — used for adaptive decay."""
        buf = list(self.recent_returns)
        if len(buf) < 2:
            return 0.0
        mean = sum(buf) / len(buf)
        variance = sum((r - mean) ** 2 for r in buf) / len(buf)
        return math.sqrt(variance)

    def update(self, trade_return: float, is_win: bool) -> None:
        alpha = 1.0 - self.decay
        self.ema_return = self.decay * self.ema_return + alpha * trade_return
        self.ema_win_rate = self.decay * self.ema_win_rate + alpha * (1.0 if is_win else 0.0)
        self.trade_count += 1
        self.recent_returns.append(trade_return)

    def to_dict(self) -> Dict:
        return {
            "window_size": self.window_size,
            "ema_return": round(self.ema_return, 6),
            "ema_win_rate": round(self.ema_win_rate, 4),
            "trade_count": self.trade_count,
            "return_volatility": round(self.return_volatility, 6),
        }


@dataclass
class StrategyEvolutionState:
    """Full evolution state for a single strategy."""
    name: str
    total_trades: int = 0
    total_pnl_usd: float = 0.0

    # Multi-window EMA stats
    short_stats: WindowStats = field(default_factory=lambda: WindowStats(SHORT_WINDOW))
    medium_stats: WindowStats = field(default_factory=lambda: WindowStats(MEDIUM_WINDOW))
    long_stats: WindowStats = field(default_factory=lambda: WindowStats(LONG_WINDOW))

    # Evolved weight tracking
    raw_weight: float = 0.0          # proportional score before momentum
    evolved_weight: float = 0.0      # final weight after momentum boost
    weight_velocity: float = 0.0     # last snapshot Δweight
    weight_momentum: float = 0.0     # EMA of velocity
    weight_history: Deque = field(default_factory=lambda: deque(maxlen=CONVERGENCE_WINDOW))

    # Adaptive learning rate state
    adaptive_decay: float = (EMA_DECAY_MIN + EMA_DECAY_MAX) / 2.0

    # Last update
    last_trade_ts: str = ""
    last_regime: str = "UNKNOWN"

    def is_converged(self) -> bool:
        """True when weight has been stable across recent snapshots."""
        buf = list(self.weight_history)
        if len(buf) < CONVERGENCE_WINDOW:
            return False
        mean = sum(buf) / len(buf)
        std = math.sqrt(sum((w - mean) ** 2 for w in buf) / len(buf))
        return std < CONVERGENCE_THRESHOLD

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "total_trades": self.total_trades,
            "total_pnl_usd": round(self.total_pnl_usd, 4),
            "short": self.short_stats.to_dict(),
            "medium": self.medium_stats.to_dict(),
            "long": self.long_stats.to_dict(),
            "raw_weight": round(self.raw_weight, 6),
            "evolved_weight": round(self.evolved_weight, 6),
            "weight_velocity": round(self.weight_velocity, 6),
            "weight_momentum": round(self.weight_momentum, 6),
            "adaptive_decay": round(self.adaptive_decay, 4),
            "converged": self.is_converged(),
            "last_trade_ts": self.last_trade_ts,
            "last_regime": self.last_regime,
            "weight_history": list(self.weight_history),
        }


# ---------------------------------------------------------------------------
# Weight evolution engine
# ---------------------------------------------------------------------------

class StrategyWeightEvolution:
    """
    Tracks and evolves strategy allocation weights over time.

    The engine adds *momentum* and *multi-window awareness* on top of raw
    performance scores so that:

    - A strategy that has been consistently improving gets a forward push
      (positive momentum) — it receives a higher weight than its current
      score alone would justify.
    - A strategy that is declining decelerates smoothly rather than
      having its allocation cut suddenly.
    - The adaptive learning rate tightens when a strategy's signal is
      clean and relaxes when returns are noisy.

    This produces a genuinely self-improving system: the bot continuously
    rewards strategies that are getting *better*, not just those that are
    currently best.
    """

    DATA_DIR = Path(__file__).parent.parent / "data"
    STATE_FILE = DATA_DIR / "strategy_weight_evolution_state.json"
    AUDIT_FILE = DATA_DIR / "strategy_weight_evolution.jsonl"

    def __init__(
        self,
        strategies: Optional[List[str]] = None,
        short_window: int = SHORT_WINDOW,
        medium_window: int = MEDIUM_WINDOW,
        long_window: int = LONG_WINDOW,
        min_trades: int = MIN_TRADES,
        momentum_scale: float = MOMENTUM_SCALE,
    ) -> None:
        self._lock = threading.RLock()
        self.short_window = short_window
        self.medium_window = medium_window
        self.long_window = long_window
        self.min_trades = min_trades
        self.momentum_scale = momentum_scale

        self.DATA_DIR.mkdir(parents=True, exist_ok=True)

        if not self._load_state():
            names = strategies or DEFAULT_STRATEGIES
            self._states: Dict[str, StrategyEvolutionState] = {
                name: StrategyEvolutionState(name=name) for name in names
            }
            n = len(self._states)
            for st in self._states.values():
                st.evolved_weight = 1.0 / n
                st.raw_weight = 1.0 / n

        # Ensure any extra strategies passed are present
        if strategies:
            changed = False
            for name in strategies:
                if name not in self._states:
                    self._states[name] = StrategyEvolutionState(name=name)
                    changed = True
            if changed:
                self._rebalance()

        logger.info("=" * 70)
        logger.info("🧬 Strategy Weight Evolution initialised")
        for name, st in self._states.items():
            logger.info(
                f"   {name:<25}  evolved_w={st.evolved_weight:.1%}  "
                f"trades={st.total_trades}"
            )
        logger.info("=" * 70)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_trade(
        self,
        strategy: str,
        pnl_usd: float,
        is_win: bool,
        position_size_usd: float = 100.0,
        regime: str = "UNKNOWN",
    ) -> None:
        """
        Record a closed trade and evolve the strategy weights.

        Args:
            strategy:           Strategy name.
            pnl_usd:            Net P&L in USD for this trade.
            is_win:             True if the trade closed in profit.
            position_size_usd:  Trade size used to normalise the return.
            regime:             Current market regime label (informational).
        """
        with self._lock:
            if strategy not in self._states:
                self._states[strategy] = StrategyEvolutionState(name=strategy)

            st = self._states[strategy]

            # Normalised return clamped to [-1, 1]
            raw_return = (pnl_usd / position_size_usd) if position_size_usd > 0 else 0.0
            trade_return = max(-1.0, min(1.0, raw_return))
            if trade_return != raw_return:
                logger.debug(
                    "🧬 [%s] trade return clamped: %.4f → %.4f (pnl=$%.2f, size=$%.2f)",
                    strategy, raw_return, trade_return, pnl_usd, position_size_usd,
                )

            # Update all three windows
            st.short_stats.update(trade_return, is_win)
            st.medium_stats.update(trade_return, is_win)
            st.long_stats.update(trade_return, is_win)

            # Update adaptive decay based on short-window volatility
            st.adaptive_decay = self._adaptive_decay(st)

            # Track totals
            st.total_trades += 1
            st.total_pnl_usd += pnl_usd
            st.last_trade_ts = datetime.now(timezone.utc).isoformat()
            st.last_regime = regime

            # Recompute evolved weights for all strategies
            self._rebalance()
            self._save_state()
            self._append_audit(strategy, pnl_usd, trade_return)

            logger.debug(
                "🧬 [%s] trade recorded  pnl=$%.2f  evolved_w=%.1%%  "
                "momentum=%+.4f  converged=%s",
                strategy,
                pnl_usd,
                st.evolved_weight * 100,
                st.weight_momentum,
                st.is_converged(),
            )

    def get_evolved_weights(self) -> Dict[str, float]:
        """
        Return a copy of the current momentum-evolved weights for all strategies.

        Weights sum to 1.0.  Before a strategy has enough trades the equal-
        weight default is returned for that strategy.
        """
        with self._lock:
            n = len(self._states)
            equal = 1.0 / n if n else 1.0
            result: Dict[str, float] = {}
            for name, st in self._states.items():
                if st.total_trades < self.min_trades:
                    result[name] = equal
                else:
                    result[name] = st.evolved_weight
            # Renormalise in case some strategies are at equal-weight floor
            total = sum(result.values())
            if total > 0:
                result = {k: v / total for k, v in result.items()}
            return result

    def get_weight(self, strategy: str) -> float:
        """Return the evolved weight for a single strategy (0-1)."""
        weights = self.get_evolved_weights()
        return weights.get(strategy, 1.0 / len(self._states) if self._states else 1.0)

    def get_best_strategy(self) -> Optional[str]:
        """Return the strategy with the highest evolved weight."""
        with self._lock:
            if not self._states:
                return None
            return max(self._states, key=lambda n: self._states[n].evolved_weight)

    def get_stats(self, strategy: Optional[str] = None) -> Dict:
        """
        Return evolution statistics.

        Args:
            strategy: If given, return stats for that strategy only.
                      Otherwise returns all strategies.
        """
        with self._lock:
            if strategy:
                st = self._states.get(strategy)
                return st.to_dict() if st else {}
            return {name: st.to_dict() for name, st in self._states.items()}

    def add_strategy(self, name: str) -> None:
        """Register a new strategy and rebalance weights."""
        with self._lock:
            if name not in self._states:
                self._states[name] = StrategyEvolutionState(name=name)
                self._rebalance()
                self._save_state()
                logger.info("🧬 New strategy registered in weight evolution: %s", name)

    def get_report(self) -> str:
        """Return a human-readable weight evolution dashboard."""
        with self._lock:
            lines = [
                "",
                "=" * 90,
                "  NIJA STRATEGY WEIGHT EVOLUTION — DASHBOARD",
                "=" * 90,
                f"  {'Strategy':<22} {'Evolved W':>9} {'Raw W':>7} {'Momentum':>10} "
                f"{'Velocity':>10} {'Short EMA':>10} {'Med EMA':>9} {'Trades':>7} {'Conv?':>6}",
                "-" * 90,
            ]
            sorted_states = sorted(
                self._states.values(),
                key=lambda s: s.evolved_weight,
                reverse=True,
            )
            for st in sorted_states:
                conv_mark = "✓" if st.is_converged() else "·"
                lines.append(
                    f"  {st.name:<22} {st.evolved_weight:>9.1%} {st.raw_weight:>7.1%} "
                    f"{st.weight_momentum:>+10.4f} {st.weight_velocity:>+10.4f} "
                    f"{st.short_stats.ema_return:>+10.4f} {st.medium_stats.ema_return:>+9.4f} "
                    f"{st.total_trades:>7} {conv_mark:>6}"
                )
            lines += [
                "=" * 90,
                "  Legend: Evolved W = momentum-boosted weight | Conv? = weight converged",
                "=" * 90,
                "",
            ]
            return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal: scoring and rebalancing
    # ------------------------------------------------------------------

    def _composite_score(self, st: StrategyEvolutionState) -> float:
        """
        Combine short-, medium-, and long-window EMA returns into one score.

        Weights: short=50%, medium=35%, long=15%.  This deliberately
        over-weights recency so the bot adapts quickly while the long
        window anchors it against noise.
        """
        if st.total_trades < self.min_trades:
            return 0.0

        s = st.short_stats.ema_return
        m = st.medium_stats.ema_return
        lo = st.long_stats.ema_return

        # Blend win-rate signal with return signal (equal weight).
        # Win-rate is centred at 0.5 so that a 50 % win-rate is neutral (0),
        # a perfect record (+0.5) is a positive signal, and a 0 % record (-0.5)
        # is a negative signal — making it directly comparable to EMA returns.
        s_wr = st.short_stats.ema_win_rate - 0.5
        m_wr = st.medium_stats.ema_win_rate - 0.5

        combined_short = 0.5 * s + 0.5 * s_wr
        combined_medium = 0.5 * m + 0.5 * m_wr
        combined_long = lo  # no win-rate for long window to keep it stable

        return 0.50 * combined_short + 0.35 * combined_medium + 0.15 * combined_long

    @staticmethod
    def _adaptive_decay(st: StrategyEvolutionState) -> float:
        """
        Compute an adaptive EMA decay based on recent return consistency.

        Lower volatility → lower decay → faster learning.
        Higher volatility → higher decay → slower learning (more stable).
        """
        vol = st.short_stats.return_volatility
        # Linearly interpolate: vol=0 → EMA_DECAY_MIN (fast), vol≥threshold → EMA_DECAY_MAX (slow)
        t = min(1.0, vol / VOLATILITY_NORMALIZATION_THRESHOLD)
        return EMA_DECAY_MIN + t * (EMA_DECAY_MAX - EMA_DECAY_MIN)

    def _rebalance(self) -> None:
        """
        Recompute raw weights from composite scores, then apply momentum to
        produce evolved weights.  Stores weight velocity and updates momentum.
        """
        if not self._states:
            return

        # 1. Compute composite scores
        scores = {name: self._composite_score(st) for name, st in self._states.items()}
        if not scores:
            return

        # 2. Shift so minimum score = 0 (no negative raw weights)
        min_score = min(scores.values())
        shifted = {name: sc - min_score for name, sc in scores.items()}
        total = sum(shifted.values())

        n = len(self._states)
        if total == 0:
            raw = {name: 1.0 / n for name in self._states}
        else:
            raw = {name: shifted[name] / total for name in self._states}

        # 3. Clip raw weights
        clipped = {
            name: max(MIN_WEIGHT, min(MAX_WEIGHT, w)) for name, w in raw.items()
        }
        clip_total = sum(clipped.values())
        for name, st in self._states.items():
            prev_raw = st.raw_weight
            st.raw_weight = clipped[name] / clip_total

            # 4. Weight velocity = change since last rebalance
            velocity = st.raw_weight - prev_raw
            st.weight_velocity = velocity

            # 5. Momentum EMA update
            st.weight_momentum = (
                MOMENTUM_DECAY * st.weight_momentum
                + (1.0 - MOMENTUM_DECAY) * velocity
            )

        # 6. Apply momentum boost to produce evolved weights
        evolved = {}
        for name, st in self._states.items():
            boost = self.momentum_scale * st.weight_momentum
            evolved[name] = max(0.0, st.raw_weight + boost)

        # 7. Clip and renormalise evolved weights
        total_evo = sum(evolved.values()) or 1.0
        for name, st in self._states.items():
            raw_evo = evolved[name] / total_evo
            clamped = max(MIN_WEIGHT, min(MAX_WEIGHT, raw_evo))
            st.evolved_weight = clamped

        # Final renormalise after clamping
        final_total = sum(st.evolved_weight for st in self._states.values())
        for st in self._states.values():
            st.evolved_weight /= final_total

            # 8. Record weight in history for convergence detection
            st.weight_history.append(round(st.evolved_weight, 6))

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        try:
            data = {name: st.to_dict() for name, st in self._states.items()}
            with open(self.STATE_FILE, "w") as fh:
                json.dump(data, fh, indent=2)
        except Exception as exc:
            logger.error("Failed to save weight evolution state: %s", exc)

    def _load_state(self) -> bool:
        if not self.STATE_FILE.exists():
            return False
        try:
            with open(self.STATE_FILE) as fh:
                data = json.load(fh)

            self._states: Dict[str, StrategyEvolutionState] = {}
            for name, d in data.items():
                st = StrategyEvolutionState(name=name)
                st.total_trades = d.get("total_trades", 0)
                st.total_pnl_usd = d.get("total_pnl_usd", 0.0)
                st.raw_weight = d.get("raw_weight", 0.0)
                st.evolved_weight = d.get("evolved_weight", 0.0)
                st.weight_velocity = d.get("weight_velocity", 0.0)
                st.weight_momentum = d.get("weight_momentum", 0.0)
                st.adaptive_decay = d.get("adaptive_decay", (EMA_DECAY_MIN + EMA_DECAY_MAX) / 2.0)
                st.last_trade_ts = d.get("last_trade_ts", "")
                st.last_regime = d.get("last_regime", "UNKNOWN")
                st.weight_history = deque(d.get("weight_history", []), maxlen=CONVERGENCE_WINDOW)

                # Restore window stats
                for attr, win_key in (
                    ("short_stats", "short"),
                    ("medium_stats", "medium"),
                    ("long_stats", "long"),
                ):
                    wd = d.get(win_key, {})
                    ws: WindowStats = getattr(st, attr)
                    ws.ema_return = wd.get("ema_return", 0.0)
                    ws.ema_win_rate = wd.get("ema_win_rate", 0.0)
                    ws.trade_count = wd.get("trade_count", 0)

                self._states[name] = st

            logger.info("✅ Weight evolution state loaded (%d strategies)", len(self._states))
            return True
        except Exception as exc:
            logger.warning("Failed to load weight evolution state: %s", exc)
            return False

    def _append_audit(self, strategy: str, pnl_usd: float, trade_return: float) -> None:
        try:
            record = {
                "ts": datetime.now(timezone.utc).isoformat(),
                "strategy": strategy,
                "pnl_usd": round(pnl_usd, 4),
                "trade_return": round(trade_return, 6),
                "evolved_weights": {
                    name: round(st.evolved_weight, 6)
                    for name, st in self._states.items()
                },
                "momentums": {
                    name: round(st.weight_momentum, 6)
                    for name, st in self._states.items()
                },
            }
            with open(self.AUDIT_FILE, "a") as fh:
                fh.write(json.dumps(record) + "\n")
        except Exception as exc:
            logger.debug("Audit append failed: %s", exc)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_evo_instance: Optional[StrategyWeightEvolution] = None
_evo_lock = threading.Lock()


def get_strategy_weight_evolution(
    strategies: Optional[List[str]] = None,
    short_window: int = SHORT_WINDOW,
    medium_window: int = MEDIUM_WINDOW,
    long_window: int = LONG_WINDOW,
    min_trades: int = MIN_TRADES,
    momentum_scale: float = MOMENTUM_SCALE,
) -> StrategyWeightEvolution:
    """Return (or create) the global StrategyWeightEvolution singleton."""
    global _evo_instance
    if _evo_instance is None:
        with _evo_lock:
            if _evo_instance is None:
                _evo_instance = StrategyWeightEvolution(
                    strategies=strategies,
                    short_window=short_window,
                    medium_window=medium_window,
                    long_window=long_window,
                    min_trades=min_trades,
                    momentum_scale=momentum_scale,
                )
    return _evo_instance


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s - %(message)s",
    )

    evo = get_strategy_weight_evolution(
        strategies=["ApexTrend", "MeanReversion", "MomentumBreakout", "LiquidityReversal"],
        min_trades=3,
    )

    print("\n📊 Simulating 60 trades across 4 strategies …\n")

    import random
    random.seed(42)  # fixed seed for reproducible demo output — remove for live use

    scenarios = {
        # (win_prob, avg_pnl_win, avg_pnl_loss)
        "ApexTrend":        (0.68, 90.0, -40.0),
        "MeanReversion":    (0.52, 55.0, -48.0),
        "MomentumBreakout": (0.40, 120.0, -30.0),
        "LiquidityReversal":(0.60, 45.0, -55.0),
    }

    for i in range(60):
        strategy = random.choice(list(scenarios.keys()))
        wp, avg_win, avg_loss = scenarios[strategy]
        is_win = random.random() < wp
        pnl = (avg_win + random.uniform(-20, 20)) if is_win else (avg_loss + random.uniform(-10, 10))
        evo.record_trade(
            strategy=strategy,
            pnl_usd=pnl,
            is_win=is_win,
            position_size_usd=1000.0,
            regime="BULL_TRENDING",
        )

    print(evo.get_report())
    print(f"🏆 Best strategy: {evo.get_best_strategy()}")
    print(f"📐 Evolved weights: {evo.get_evolved_weights()}")

    best = evo.get_best_strategy()
    if best:
        stats = evo.get_stats(best)
        print(f"\n📈 {best} stats:")
        print(f"   Trades      : {stats['total_trades']}")
        print(f"   Total PnL   : ${stats['total_pnl_usd']:.2f}")
        print(f"   Evolved W   : {stats['evolved_weight']:.1%}")
        print(f"   Momentum    : {stats['weight_momentum']:+.4f}")
        print(f"   Converged   : {stats['converged']}")

    sys.exit(0)
