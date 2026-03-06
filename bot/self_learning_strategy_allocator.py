"""
NIJA Self-Learning Strategy Allocator
======================================

Automatically learns which strategies perform best in live trading and
continuously reallocates capital toward top performers.

How it works
------------
1. Every closed trade is recorded against the strategy that produced it.
2. Each strategy's performance score is maintained as an exponential moving
   average (EMA) of its per-trade returns, blended with win-rate and profit
   factor.  Recent trades are weighted more heavily than old ones (the EMA
   decay controls this).
3. Capital weights are normalised across all active strategies every time a
   trade is recorded.  Strategies with zero or negative score receive the
   configurable minimum allocation floor.
4. Weights are exposed as a ``get_weights()`` call that any position-sizer
   can query to scale trade size up or down per strategy.

Key Features
------------
- Pure-Python, no external ML libraries required
- Persistent JSON state survives restarts
- Thread-safe singleton via ``get_self_learning_allocator()``
- Configurable EMA decay, min/max per-strategy allocation floor
- Human-readable status report

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

import json
import logging
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.self_learning_allocator")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default strategy names that NIJA runs
DEFAULT_STRATEGIES: List[str] = [
    "ApexTrend",
    "MeanReversion",
    "MomentumBreakout",
    "LiquidityReversal",
]

# Minimum and maximum allocation any single strategy can receive (fraction)
MIN_ALLOCATION = 0.05   # 5 %
MAX_ALLOCATION = 0.60   # 60 %

# EMA decay factor for performance score updates.
# Higher values = slower adaptation (longer memory).
# 0.95 → very slow decay, 0.85 → moderate (default), 0.5 → fast adaptation.
DEFAULT_EMA_DECAY = 0.85

# Minimum number of trades before the allocator overrides the equal-weight default
MIN_TRADES_BEFORE_LEARNING = 10


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class StrategyStats:
    """Per-strategy statistics maintained by the allocator."""
    name: str
    total_trades: int = 0
    winning_trades: int = 0
    total_pnl_usd: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    ema_return: float = 0.0          # EMA of per-trade return (0.0 = neutral)
    current_allocation: float = 0.0  # Fraction 0-1
    last_trade_ts: str = ""
    trade_history: List[Dict] = field(default_factory=list)

    # ---------- computed ----------

    @property
    def win_rate(self) -> float:
        return (self.winning_trades / self.total_trades) if self.total_trades > 0 else 0.0

    @property
    def profit_factor(self) -> float:
        if self.gross_loss > 0:
            return round(self.gross_profit / self.gross_loss, 4)
        return 999.99 if self.gross_profit > 0 else 0.0

    @property
    def avg_pnl(self) -> float:
        return (self.total_pnl_usd / self.total_trades) if self.total_trades > 0 else 0.0

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["win_rate"] = self.win_rate
        d["profit_factor"] = self.profit_factor
        d["avg_pnl"] = self.avg_pnl
        return d


# ---------------------------------------------------------------------------
# Allocator engine
# ---------------------------------------------------------------------------

class SelfLearningStrategyAllocator:
    """
    Continuously learns strategy performance and reallocates capital weights.

    Usage::

        allocator = get_self_learning_allocator()
        # After a trade closes:
        allocator.record_trade("ApexTrend", pnl_usd=42.5, is_win=True)
        # Before entering a new position:
        weight = allocator.get_weight("ApexTrend")   # e.g. 0.35
        position_size *= weight / equal_weight        # scale accordingly
    """

    DATA_DIR = Path(__file__).parent.parent / "data"
    STATE_FILE = DATA_DIR / "self_learning_allocator_state.json"

    def __init__(
        self,
        strategies: Optional[List[str]] = None,
        ema_decay: float = DEFAULT_EMA_DECAY,
        min_allocation: float = MIN_ALLOCATION,
        max_allocation: float = MAX_ALLOCATION,
        min_trades_before_learning: int = MIN_TRADES_BEFORE_LEARNING,
    ):
        self._lock = threading.RLock()
        self.ema_decay = max(0.1, min(0.99, ema_decay))
        self.min_allocation = min_allocation
        self.max_allocation = max_allocation
        self.min_trades_before_learning = min_trades_before_learning

        self.DATA_DIR.mkdir(parents=True, exist_ok=True)

        if not self._load_state():
            strategy_names = strategies or DEFAULT_STRATEGIES
            self._stats: Dict[str, StrategyStats] = {
                name: StrategyStats(name=name) for name in strategy_names
            }
            self._rebalance()
            self._save_state()

        # Ensure any new strategies passed are present
        if strategies:
            changed = False
            for name in strategies:
                if name not in self._stats:
                    self._stats[name] = StrategyStats(name=name)
                    changed = True
            if changed:
                self._rebalance()
                self._save_state()

        logger.info("=" * 70)
        logger.info("🧠 Self-Learning Strategy Allocator initialised")
        for name, st in self._stats.items():
            logger.info(f"   {name:<25} alloc={st.current_allocation:.1%}  trades={st.total_trades}")
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
    ) -> None:
        """
        Record a closed trade and update the strategy's performance score.

        Args:
            strategy:           Strategy name (must be registered or will be added).
            pnl_usd:            Net P&L in USD.
            is_win:             True if the trade was profitable.
            position_size_usd:  Size of the trade in USD (for normalising returns).
        """
        with self._lock:
            if strategy not in self._stats:
                self._stats[strategy] = StrategyStats(name=strategy)

            st = self._stats[strategy]
            st.total_trades += 1
            st.total_pnl_usd += pnl_usd
            st.last_trade_ts = datetime.now().isoformat()

            if pnl_usd > 0:
                st.winning_trades += 1
                st.gross_profit += pnl_usd
            else:
                st.gross_loss += abs(pnl_usd)

            # Normalised return for this trade (-1 to +1 range, capped)
            trade_return = (pnl_usd / position_size_usd) if position_size_usd > 0 else 0.0
            trade_return = max(-1.0, min(1.0, trade_return))

            # EMA update: blend current EMA with this trade's return
            st.ema_return = (
                self.ema_decay * st.ema_return + (1.0 - self.ema_decay) * trade_return
            )

            # Keep a capped history
            st.trade_history.append({
                "ts": st.last_trade_ts,
                "pnl_usd": pnl_usd,
                "is_win": is_win,
                "ema_return": round(st.ema_return, 6),
            })
            if len(st.trade_history) > 200:
                st.trade_history = st.trade_history[-200:]

            # Rebalance allocations
            self._rebalance()
            self._save_state()

            logger.info(
                f"🧠 [{strategy}] trade recorded  pnl=${pnl_usd:.2f}  "
                f"ema={st.ema_return:.4f}  alloc={st.current_allocation:.1%}"
            )

    def get_weight(self, strategy: str) -> float:
        """
        Return the current allocation weight for a strategy (0-1).

        Returns the equal-weight default if the strategy is unknown or has
        fewer than ``min_trades_before_learning`` trades.
        """
        with self._lock:
            st = self._stats.get(strategy)
            if st is None or st.total_trades < self.min_trades_before_learning:
                return 1.0 / len(self._stats) if self._stats else 1.0
            return st.current_allocation

    def get_weights(self) -> Dict[str, float]:
        """Return a copy of the current allocation weights for all strategies."""
        with self._lock:
            return {name: st.current_allocation for name, st in self._stats.items()}

    def get_best_strategy(self) -> Optional[str]:
        """Return the name of the highest-weighted strategy."""
        with self._lock:
            if not self._stats:
                return None
            return max(self._stats, key=lambda n: self._stats[n].current_allocation)

    def get_stats(self, strategy: Optional[str] = None) -> Dict:
        """
        Return performance stats.

        Args:
            strategy: If provided, return stats for that strategy only.
                      Otherwise return all strategies.
        """
        with self._lock:
            if strategy:
                st = self._stats.get(strategy)
                return st.to_dict() if st else {}
            return {name: st.to_dict() for name, st in self._stats.items()}

    def add_strategy(self, name: str) -> None:
        """Register a new strategy with equal weight."""
        with self._lock:
            if name not in self._stats:
                self._stats[name] = StrategyStats(name=name)
                self._rebalance()
                self._save_state()
                logger.info(f"🧠 New strategy registered: {name}")

    def get_report(self) -> str:
        """Generate a human-readable allocation report."""
        with self._lock:
            lines = [
                "",
                "=" * 80,
                "  NIJA SELF-LEARNING STRATEGY ALLOCATOR — ALLOCATION REPORT",
                "=" * 80,
                f"  {'Strategy':<25} {'Alloc':>7} {'Trades':>7} {'Win%':>7} "
                f"{'PF':>7} {'AvgPnL':>9} {'EMA':>8}",
                "-" * 80,
            ]
            for st in sorted(self._stats.values(), key=lambda s: s.current_allocation, reverse=True):
                lines.append(
                    f"  {st.name:<25} {st.current_allocation:>7.1%} "
                    f"{st.total_trades:>7} {st.win_rate:>7.1%} "
                    f"{st.profit_factor:>7.2f} {st.avg_pnl:>+9.2f} "
                    f"{st.ema_return:>+8.4f}"
                )
            lines += ["=" * 80, ""]
            return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal logic
    # ------------------------------------------------------------------

    def _score(self, st: StrategyStats) -> float:
        """
        Calculate a composite performance score for a strategy.

        Score components (equal weight):
        - EMA return          : captures recent momentum
        - Win rate (centred)  : 0.5 win-rate = 0, 1.0 = +0.5, 0.0 = -0.5
        - Profit factor score : tanh-scaled profit factor (0 → -1, 1 → 0, >1 → positive)
        """
        if st.total_trades < self.min_trades_before_learning:
            return 0.0  # neutral — receives equal-weight floor

        ema_score = st.ema_return  # already in [-1, 1]
        wr_score = st.win_rate - 0.5  # centred at 0
        # Profit factor: PF=1 → 0, PF>1 → positive, PF<1 → negative (capped)
        pf = min(st.profit_factor, 10.0)
        pf_score = (pf - 1.0) / 5.0  # rough normalisation

        return (ema_score + wr_score + pf_score) / 3.0

    def _rebalance(self) -> None:
        """Recompute allocation weights from strategy scores."""
        if not self._stats:
            return

        scores = {name: self._score(st) for name, st in self._stats.items()}

        # Shift all scores so the minimum is 0 (no negative raw weights)
        min_score = min(scores.values())
        shifted = {name: score - min_score for name, score in scores.items()}
        total = sum(shifted.values())

        n = len(self._stats)
        if total == 0:
            # All equal weight (no learning data yet)
            for st in self._stats.values():
                st.current_allocation = 1.0 / n
            return

        # Compute raw proportional weights
        raw = {name: shifted[name] / total for name in self._stats}

        # Clip to [min, max] and renormalise
        clipped = {name: max(self.min_allocation, min(self.max_allocation, w))
                   for name, w in raw.items()}
        clip_total = sum(clipped.values())
        for name, st in self._stats.items():
            st.current_allocation = clipped[name] / clip_total

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        try:
            data = {name: st.to_dict() for name, st in self._stats.items()}
            with open(self.STATE_FILE, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as exc:
            logger.error(f"Failed to save allocator state: {exc}")

    def _load_state(self) -> bool:
        if not self.STATE_FILE.exists():
            return False
        try:
            with open(self.STATE_FILE, "r") as f:
                data = json.load(f)

            computed = {"win_rate", "profit_factor", "avg_pnl"}
            self._stats = {}
            for name, d in data.items():
                clean = {k: v for k, v in d.items() if k not in computed}
                self._stats[name] = StrategyStats(**clean)

            logger.info(f"✅ Allocator state loaded ({len(self._stats)} strategies)")
            return True
        except Exception as exc:
            logger.warning(f"Failed to load allocator state: {exc}")
            return False


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_allocator_instance: Optional[SelfLearningStrategyAllocator] = None
_allocator_lock = threading.Lock()


def get_self_learning_allocator(
    strategies: Optional[List[str]] = None,
    ema_decay: float = DEFAULT_EMA_DECAY,
) -> SelfLearningStrategyAllocator:
    """Return (or create) the global SelfLearningStrategyAllocator singleton."""
    global _allocator_instance
    if _allocator_instance is None:
        with _allocator_lock:
            if _allocator_instance is None:
                _allocator_instance = SelfLearningStrategyAllocator(
                    strategies=strategies,
                    ema_decay=ema_decay,
                )
    return _allocator_instance


# ---------------------------------------------------------------------------
# Quick smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s - %(message)s")

    alloc = get_self_learning_allocator(strategies=["ApexTrend", "MeanReversion", "MomentumBreakout"])

    # Simulate ApexTrend winning most trades
    for _ in range(15):
        alloc.record_trade("ApexTrend", pnl_usd=50.0, is_win=True)
    for _ in range(5):
        alloc.record_trade("ApexTrend", pnl_usd=-20.0, is_win=False)

    # MeanReversion barely profitable
    for _ in range(10):
        alloc.record_trade("MeanReversion", pnl_usd=10.0, is_win=True)
    for _ in range(8):
        alloc.record_trade("MeanReversion", pnl_usd=-12.0, is_win=False)

    # MomentumBreakout losing
    for _ in range(5):
        alloc.record_trade("MomentumBreakout", pnl_usd=8.0, is_win=True)
    for _ in range(12):
        alloc.record_trade("MomentumBreakout", pnl_usd=-18.0, is_win=False)

    print(alloc.get_report())
    print(f"Best strategy: {alloc.get_best_strategy()}")
    print(f"Weights: {alloc.get_weights()}")
