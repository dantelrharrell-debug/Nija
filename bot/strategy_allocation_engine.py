"""
NIJA Strategy Allocation Engine
=================================

Automatically shifts capital toward the strategies currently performing best.

How it works
------------
1. Every closed trade is recorded against the strategy that produced it via
   ``record_trade()``.
2. Each strategy's composite performance score is maintained using:
   - EMA of per-trade returns          (captures recent momentum)
   - Win-rate (centred at 0.5)         (consistency signal)
   - Profit-factor score (tanh-scaled) (reward/risk quality)
   - Sharpe estimate (rolling returns) (risk-adjusted return)
3. On every ``rebalance()`` call, the engine converts scores to
   allocation weights (with configurable min/max bounds), then maps those
   weights to USD amounts based on the current total capital.
4. ``get_shift_plan()`` returns an ordered list of ``ShiftOrder`` objects
   describing exactly which capital transfers must be executed to move from
   the current allocation to the target allocation.  The caller can apply
   these incrementally so that no strategy is ever over-drawn.
5. A strategy claims its share by calling ``get_allocation(strategy)`` before
   placing an order.  Capital is never removed from the pool here — the engine
   only tracks *planned* allocations and transfers.
6. Full state is persisted to JSON after every ``record_trade()`` and
   ``rebalance()`` call so that allocations survive restarts.

Architecture
------------
::

  ┌─────────────────────────────────────────────────────────────────┐
  │              StrategyAllocationEngine                            │
  │                                                                 │
  │  record_trade(strategy, pnl_usd, is_win, position_size_usd)    │
  │      ↓                                                          │
  │  _update_score(strategy)                                        │
  │      ↓                                                          │
  │  rebalance()  →  {strategy: target_usd}                         │
  │                                                                 │
  │  get_shift_plan()  →  [ShiftOrder(from, to, amount_usd), ...]   │
  │                                                                 │
  │  get_allocation(strategy)  →  float (USD)                       │
  │  get_allocations()         →  {strategy: float}                 │
  └─────────────────────────────────────────────────────────────────┘

Usage
-----
    from bot.strategy_allocation_engine import get_strategy_allocation_engine

    engine = get_strategy_allocation_engine()
    engine.update_capital(total_capital=100_000.0)

    # After every trade closes:
    engine.record_trade("ApexTrend", pnl_usd=200.0, is_win=True)

    # Rebalance and get new USD allocations:
    allocations = engine.rebalance()
    # → {"ApexTrend": 42_000, "MeanReversion": 28_000, ...}

    # Inspect which capital transfers are needed:
    for shift in engine.get_shift_plan():
        print(f"  Move ${shift.amount_usd:.2f} from {shift.from_strategy} "
              f"to {shift.to_strategy}")

    # Full status report:
    print(engine.get_report())

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
from typing import Deque, Dict, List, Optional

logger = logging.getLogger("nija.strategy_allocation_engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_STRATEGIES: List[str] = [
    "APEX_V71",
]

MIN_ALLOCATION: float = 0.05   # 5 % floor per strategy
MAX_ALLOCATION: float = 0.60   # 60 % ceiling per strategy

# EMA decay for per-trade return smoothing.  Higher = slower adaptation.
DEFAULT_EMA_DECAY: float = 0.85

# Rolling window size for Sharpe estimation.
SHARPE_WINDOW: int = 30

# Minimum trades before the engine overrides the equal-weight default.
MIN_TRADES_BEFORE_LEARNING: int = 10

# Minimum USD shift before a ShiftOrder is emitted (avoids noise).
MIN_SHIFT_USD: float = 10.0

# Sentinel profit factor used when a strategy has profit but zero losses.
MAX_PROFIT_FACTOR: float = 999.99

DATA_DIR = Path(__file__).parent.parent / "data"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ShiftOrder:
    """Describes a single capital transfer between two strategies."""
    from_strategy: str
    to_strategy: str
    amount_usd: float
    reason: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class StrategyRecord:
    """Per-strategy performance statistics maintained by the engine."""
    name: str
    total_trades: int = 0
    winning_trades: int = 0
    total_pnl_usd: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0
    ema_return: float = 0.0          # EMA of per-trade normalised return
    current_allocation_usd: float = 0.0
    last_trade_ts: str = ""
    # Rolling returns kept for Sharpe estimation (not persisted as deque)
    _recent_returns: List[float] = field(default_factory=list)
    # Internal allocation weight (0–1), computed by the engine
    _weight: float = field(default=0.0, init=False, repr=False, compare=False)

    # ---------- computed ----------

    @property
    def win_rate(self) -> float:
        return (self.winning_trades / self.total_trades) if self.total_trades > 0 else 0.0

    @property
    def profit_factor(self) -> float:
        if self.gross_loss > 0:
            return round(self.gross_profit / self.gross_loss, 4)
        return MAX_PROFIT_FACTOR if self.gross_profit > 0 else 0.0

    @property
    def avg_pnl(self) -> float:
        return (self.total_pnl_usd / self.total_trades) if self.total_trades > 0 else 0.0

    @property
    def sharpe_estimate(self) -> float:
        """Annualised Sharpe estimate from the rolling returns window."""
        if len(self._recent_returns) < 2:
            return 0.0
        n = len(self._recent_returns)
        mean = sum(self._recent_returns) / n
        variance = sum((r - mean) ** 2 for r in self._recent_returns) / (n - 1)
        std = math.sqrt(variance) if variance > 0 else 0.0
        if std == 0.0:
            return 0.0
        # Approximate annualisation: assume ~365 trades per year
        return (mean / std) * math.sqrt(365)

    def to_dict(self) -> Dict:
        return {
            "name": self.name,
            "total_trades": self.total_trades,
            "winning_trades": self.winning_trades,
            "total_pnl_usd": self.total_pnl_usd,
            "gross_profit": self.gross_profit,
            "gross_loss": self.gross_loss,
            "ema_return": self.ema_return,
            "current_allocation_usd": self.current_allocation_usd,
            "last_trade_ts": self.last_trade_ts,
            "_recent_returns": self._recent_returns,
            # computed fields for convenience
            "win_rate": self.win_rate,
            "profit_factor": self.profit_factor,
            "avg_pnl": self.avg_pnl,
            "sharpe_estimate": self.sharpe_estimate,
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class StrategyAllocationEngine:
    """
    Automatically shifts capital toward the strategies currently performing best.

    The engine is the single source of truth for per-strategy USD capital
    targets.  It does **not** execute trades — it only answers the question:
    "Given everything we know about each strategy's performance, how should
    the total capital be distributed right now?"

    Thread-safe singleton.  Use ``get_strategy_allocation_engine()`` to obtain
    the shared instance.
    """

    DEFAULT_STATE_FILE = DATA_DIR / "strategy_allocation_engine_state.json"

    def __init__(
        self,
        strategies: Optional[List[str]] = None,
        total_capital: float = 0.0,
        ema_decay: float = DEFAULT_EMA_DECAY,
        min_allocation: float = MIN_ALLOCATION,
        max_allocation: float = MAX_ALLOCATION,
        min_trades_before_learning: int = MIN_TRADES_BEFORE_LEARNING,
        state_file: Optional[Path] = None,
    ):
        self._lock = threading.RLock()
        self.ema_decay = max(0.1, min(0.99, ema_decay))
        self.min_allocation = min_allocation
        self.max_allocation = max_allocation
        self.min_trades_before_learning = min_trades_before_learning
        self.total_capital = total_capital
        self.STATE_FILE = state_file if state_file is not None else self.DEFAULT_STATE_FILE

        DATA_DIR.mkdir(parents=True, exist_ok=True)

        if not self._load_state():
            strategy_names = strategies if strategies is not None else DEFAULT_STRATEGIES
            self._records: Dict[str, StrategyRecord] = {
                name: StrategyRecord(name=name) for name in strategy_names
            }
            self._rebalance_weights()
            self._save_state()

        # Ensure any newly requested strategies exist
        if strategies:
            changed = False
            for name in strategies:
                if name not in self._records:
                    self._records[name] = StrategyRecord(name=name)
                    changed = True
            if changed:
                self._rebalance_weights()
                self._save_state()

        # If a non-zero capital was passed, apply it now
        if total_capital > 0:
            self._apply_capital(total_capital)

        self._log_state("initialised")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_capital(self, total_capital: float) -> None:
        """
        Update the total capital pool and recompute USD allocations.

        Args:
            total_capital: New total capital in USD.
        """
        with self._lock:
            self.total_capital = total_capital
            self._apply_capital(total_capital)
            self._save_state()
            logger.info(f"💰 Total capital updated to ${total_capital:,.2f}")

    def record_trade(
        self,
        strategy: str,
        pnl_usd: float,
        is_win: bool,
        position_size_usd: float = 100.0,
    ) -> None:
        """
        Record a closed trade and refresh the strategy's performance score.

        After recording, internal allocation weights are updated automatically.
        Call ``rebalance()`` to translate updated weights into USD amounts.

        Args:
            strategy:           Strategy name.
            pnl_usd:            Net P&L in USD (positive = profit).
            is_win:             True if the trade was profitable.
            position_size_usd:  Trade size in USD (used to normalise returns).
        """
        with self._lock:
            if strategy not in self._records:
                self._records[strategy] = StrategyRecord(name=strategy)

            rec = self._records[strategy]
            rec.total_trades += 1
            rec.total_pnl_usd += pnl_usd
            rec.last_trade_ts = datetime.now(timezone.utc).isoformat()

            # Use is_win for win counting; pnl_usd sign for profit/loss buckets
            if is_win:
                rec.winning_trades += 1
            if pnl_usd > 0:
                rec.gross_profit += pnl_usd
            elif pnl_usd < 0:
                rec.gross_loss += abs(pnl_usd)

            # Normalised return for this trade, capped to [-1, +1]
            trade_return = (
                (pnl_usd / position_size_usd) if position_size_usd > 0 else 0.0
            )
            trade_return = max(-1.0, min(1.0, trade_return))

            # EMA update
            rec.ema_return = (
                self.ema_decay * rec.ema_return
                + (1.0 - self.ema_decay) * trade_return
            )

            # Rolling returns for Sharpe
            rec._recent_returns.append(trade_return)
            if len(rec._recent_returns) > SHARPE_WINDOW:
                rec._recent_returns = rec._recent_returns[-SHARPE_WINDOW:]

            # Refresh weights
            self._rebalance_weights()
            if self.total_capital > 0:
                self._apply_capital(self.total_capital)

            self._save_state()

            logger.info(
                f"📊 [{strategy}] trade recorded  pnl=${pnl_usd:+.2f}  "
                f"ema={rec.ema_return:.4f}  "
                f"alloc=${rec.current_allocation_usd:,.2f}"
            )

    def rebalance(self) -> Dict[str, float]:
        """
        Recompute performance scores and return the target USD allocation per
        strategy.

        Returns:
            Dictionary mapping strategy name → target USD allocation.
        """
        with self._lock:
            self._rebalance_weights()
            if self.total_capital > 0:
                self._apply_capital(self.total_capital)
            self._save_state()
            result = {
                name: rec.current_allocation_usd
                for name, rec in self._records.items()
            }
            logger.info("⚖️  Capital rebalanced: %s",
                        {k: f"${v:,.2f}" for k, v in result.items()})
            return result

    def get_shift_plan(
        self,
        current_usd: Optional[Dict[str, float]] = None,
    ) -> List[ShiftOrder]:
        """
        Return the list of ``ShiftOrder`` objects needed to move from the
        current per-strategy capital to the target allocation.

        Args:
            current_usd: Current USD amounts per strategy.  If omitted, the
                         engine's own ``current_allocation_usd`` values are
                         used as baseline — meaning this call only returns
                         shifts required after the *last* rebalance.

        Returns:
            List of ShiftOrder objects ordered largest-to-smallest by amount.
        """
        with self._lock:
            target = {
                name: rec.current_allocation_usd
                for name, rec in self._records.items()
            }
            if current_usd is None:
                # Nothing to shift — target IS current
                return []

            shifts: List[ShiftOrder] = []
            # Identify over-allocated (sources) and under-allocated (destinations)
            over: List[tuple] = []
            under: List[tuple] = []
            for name, target_usd in target.items():
                current = current_usd.get(name, 0.0)
                delta = target_usd - current
                if delta < -MIN_SHIFT_USD:
                    over.append((name, -delta))   # excess to give away
                elif delta > MIN_SHIFT_USD:
                    under.append((name, delta))   # needs funding

            # Greedy matching: largest sources → largest destinations
            over.sort(key=lambda x: x[1], reverse=True)
            under.sort(key=lambda x: x[1], reverse=True)

            over_pool = list(over)
            under_pool = list(under)

            oi = 0
            ui = 0
            while oi < len(over_pool) and ui < len(under_pool):
                src, src_avail = over_pool[oi]
                dst, dst_need = under_pool[ui]
                amount = min(src_avail, dst_need)
                if amount >= MIN_SHIFT_USD:
                    shifts.append(ShiftOrder(
                        from_strategy=src,
                        to_strategy=dst,
                        amount_usd=round(amount, 2),
                        reason=f"{src} over-allocated; {dst} under-allocated",
                    ))
                src_avail -= amount
                dst_need -= amount
                over_pool[oi] = (src, src_avail)
                under_pool[ui] = (dst, dst_need)
                if src_avail < MIN_SHIFT_USD:
                    oi += 1
                if dst_need < MIN_SHIFT_USD:
                    ui += 1

            shifts.sort(key=lambda s: s.amount_usd, reverse=True)
            return shifts

    def get_allocation(self, strategy: str) -> float:
        """
        Return the current USD allocation for a single strategy.

        Returns 0.0 if the strategy is unknown.
        """
        with self._lock:
            rec = self._records.get(strategy)
            return rec.current_allocation_usd if rec else 0.0

    def get_allocations(self) -> Dict[str, float]:
        """Return a snapshot of all current USD allocations."""
        with self._lock:
            return {
                name: rec.current_allocation_usd
                for name, rec in self._records.items()
            }

    def get_weights(self) -> Dict[str, float]:
        """Return the current fractional allocation weights (sum to 1.0)."""
        with self._lock:
            total = sum(rec.current_allocation_usd for rec in self._records.values())
            if total == 0:
                n = len(self._records)
                return {name: (1.0 / n if n > 0 else 0.0) for name in self._records}
            return {
                name: rec.current_allocation_usd / total
                for name, rec in self._records.items()
            }

    def get_best_strategy(self) -> Optional[str]:
        """Return the name of the strategy with the highest USD allocation."""
        with self._lock:
            if not self._records:
                return None
            return max(
                self._records,
                key=lambda n: self._records[n].current_allocation_usd,
            )

    def get_stats(self, strategy: Optional[str] = None) -> Dict:
        """
        Return performance statistics.

        Args:
            strategy: If given, return stats for that strategy only.
                      Otherwise return all strategies.
        """
        with self._lock:
            if strategy:
                rec = self._records.get(strategy)
                return rec.to_dict() if rec else {}
            return {name: rec.to_dict() for name, rec in self._records.items()}

    def add_strategy(self, name: str) -> None:
        """Register a new strategy and rebalance capital equally."""
        with self._lock:
            if name not in self._records:
                self._records[name] = StrategyRecord(name=name)
                self._rebalance_weights()
                if self.total_capital > 0:
                    self._apply_capital(self.total_capital)
                self._save_state()
                logger.info(f"➕ New strategy registered: {name}")

    def get_report(self) -> str:
        """Generate a human-readable allocation report."""
        with self._lock:
            lines = [
                "",
                "=" * 90,
                "  NIJA STRATEGY ALLOCATION ENGINE — CAPITAL ALLOCATION REPORT",
                f"  Total Capital: ${self.total_capital:,.2f}",
                "=" * 90,
                f"  {'Strategy':<25} {'Alloc $':>12} {'Alloc %':>8} "
                f"{'Trades':>7} {'Win%':>7} {'PF':>7} "
                f"{'Sharpe':>8} {'EMA':>8}",
                "-" * 90,
            ]
            total = sum(r.current_allocation_usd for r in self._records.values())
            for rec in sorted(
                self._records.values(),
                key=lambda r: r.current_allocation_usd,
                reverse=True,
            ):
                pct = (rec.current_allocation_usd / total * 100) if total > 0 else 0.0
                lines.append(
                    f"  {rec.name:<25} "
                    f"${rec.current_allocation_usd:>11,.2f} "
                    f"{pct:>7.1f}% "
                    f"{rec.total_trades:>7} "
                    f"{rec.win_rate:>7.1%} "
                    f"{rec.profit_factor:>7.2f} "
                    f"{rec.sharpe_estimate:>+8.2f} "
                    f"{rec.ema_return:>+8.4f}"
                )
            lines += ["=" * 90, ""]
            return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _score(self, rec: StrategyRecord) -> float:
        """
        Composite performance score for a strategy.

        Components (equal weight of 0.25 each):
        - EMA return           (recent momentum, range [-1, +1])
        - Win-rate centred     (0.5 win-rate → 0, 1.0 → +0.5)
        - Profit-factor score  (PF=1 → 0, PF>1 → positive, PF<1 → negative)
        - Sharpe estimate      (tanh-compressed to [-1, +1])
        """
        if rec.total_trades < self.min_trades_before_learning:
            return 0.0  # neutral — equal-weight floor

        ema_score = rec.ema_return  # already [-1, 1]
        wr_score = rec.win_rate - 0.5  # centred
        pf = min(rec.profit_factor, 10.0)
        pf_score = (pf - 1.0) / 5.0
        sharpe_score = math.tanh(rec.sharpe_estimate / 3.0)  # compress to [-1, 1]

        return (ema_score + wr_score + pf_score + sharpe_score) / 4.0

    def _rebalance_weights(self) -> None:
        """Compute fractional allocation weights from composite scores.

        Uses a water-filling algorithm so that min/max bounds are always
        respected exactly:
        1. Start every strategy at ``min_allocation``.
        2. Distribute the remaining budget proportionally to raw scores.
        3. Cap any strategy that exceeds ``max_allocation`` and redistribute
           the excess to the uncapped strategies, repeating until stable.
        """
        if not self._records:
            return

        scores = {name: self._score(rec) for name, rec in self._records.items()}

        # Shift so the minimum score → 0 (no negative raw weights)
        min_score = min(scores.values())
        shifted = {name: s - min_score for name, s in scores.items()}
        total = sum(shifted.values())

        n = len(self._records)
        if total == 0:
            # Not enough data — equal weight
            for rec in self._records.values():
                rec._weight = 1.0 / n
            return

        # Proportional scores (sum to 1)
        raw_prop = {name: shifted[name] / total for name in self._records}

        # Budget above the per-strategy floor
        surplus = max(0.0, 1.0 - n * self.min_allocation)

        # Initial allocation: floor + proportional share of surplus
        weights: Dict[str, float] = {
            name: self.min_allocation + raw_prop[name] * surplus
            for name in self._records
        }

        # Iteratively cap at max_allocation and redistribute excess
        for _ in range(n + 1):
            over = {name: w for name, w in weights.items() if w > self.max_allocation + 1e-12}
            if not over:
                break

            excess = sum(w - self.max_allocation for w in over.values())
            for name in over:
                weights[name] = self.max_allocation

            # Redistribute excess proportionally among uncapped strategies
            uncapped = {name for name, w in weights.items() if w < self.max_allocation - 1e-12}
            if not uncapped:
                break

            uncapped_score = sum(raw_prop[name] for name in uncapped)
            if uncapped_score > 0:
                for name in uncapped:
                    weights[name] = min(
                        self.max_allocation,
                        weights[name] + excess * raw_prop[name] / uncapped_score,
                    )
            else:
                share = excess / len(uncapped)
                for name in uncapped:
                    weights[name] = min(self.max_allocation, weights[name] + share)

        # Normalise to exactly 1.0 (floating-point cleanup)
        total_w = sum(weights.values())
        for name, rec in self._records.items():
            rec._weight = weights[name] / total_w if total_w > 0 else 1.0 / n

    def _apply_capital(self, total_capital: float) -> None:
        """Translate fractional weights into USD allocations."""
        n = len(self._records)
        for rec in self._records.values():
            rec.current_allocation_usd = total_capital * (rec._weight if n > 0 else 0.0)

    def _log_state(self, event: str) -> None:
        logger.info("=" * 70)
        logger.info("🚀 Strategy Allocation Engine %s", event)
        for name, rec in self._records.items():
            logger.info(
                "   %-25s  alloc=$%s  trades=%d",
                name,
                f"{rec.current_allocation_usd:,.2f}",
                rec.total_trades,
            )
        logger.info("=" * 70)

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        try:
            state = {
                "total_capital": self.total_capital,
                "ema_decay": self.ema_decay,
                "min_allocation": self.min_allocation,
                "max_allocation": self.max_allocation,
                "strategies": {
                    name: rec.to_dict() for name, rec in self._records.items()
                },
            }
            with open(self.STATE_FILE, "w") as fh:
                json.dump(state, fh, indent=2)
        except Exception as exc:
            logger.error("Failed to save engine state: %s", exc)

    def _load_state(self) -> bool:
        if not self.STATE_FILE.exists():
            return False
        try:
            with open(self.STATE_FILE, "r") as fh:
                state = json.load(fh)

            self.total_capital = state.get("total_capital", self.total_capital)
            self.ema_decay = state.get("ema_decay", self.ema_decay)
            self.min_allocation = state.get("min_allocation", self.min_allocation)
            self.max_allocation = state.get("max_allocation", self.max_allocation)

            computed = {"win_rate", "profit_factor", "avg_pnl", "sharpe_estimate"}
            self._records = {}
            for name, d in state.get("strategies", {}).items():
                clean = {k: v for k, v in d.items() if k not in computed}
                self._records[name] = StrategyRecord(**clean)

            logger.info(
                "✅ Engine state loaded (%d strategies)", len(self._records)
            )
            return True
        except Exception as exc:
            logger.warning("Failed to load engine state: %s", exc)
            return False


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_engine_instance: Optional[StrategyAllocationEngine] = None
_engine_lock = threading.Lock()


def get_strategy_allocation_engine(
    strategies: Optional[List[str]] = None,
    total_capital: float = 0.0,
    ema_decay: float = DEFAULT_EMA_DECAY,
) -> StrategyAllocationEngine:
    """Return (or create) the global StrategyAllocationEngine singleton."""
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = StrategyAllocationEngine(
                    strategies=strategies,
                    total_capital=total_capital,
                    ema_decay=ema_decay,
                )
    return _engine_instance


# ---------------------------------------------------------------------------
# CLI smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import logging as _logging
    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s - %(message)s")

    strategies = ["ApexTrend", "MeanReversion", "MomentumBreakout"]
    engine = StrategyAllocationEngine(
        strategies=strategies,
        total_capital=100_000.0,
    )

    # ApexTrend wins most trades
    for _ in range(18):
        engine.record_trade("ApexTrend", pnl_usd=60.0, is_win=True)
    for _ in range(4):
        engine.record_trade("ApexTrend", pnl_usd=-20.0, is_win=False)

    # MeanReversion barely breaks even
    for _ in range(12):
        engine.record_trade("MeanReversion", pnl_usd=8.0, is_win=True)
    for _ in range(10):
        engine.record_trade("MeanReversion", pnl_usd=-10.0, is_win=False)

    # MomentumBreakout is losing
    for _ in range(6):
        engine.record_trade("MomentumBreakout", pnl_usd=10.0, is_win=True)
    for _ in range(15):
        engine.record_trade("MomentumBreakout", pnl_usd=-18.0, is_win=False)

    engine.rebalance()
    print(engine.get_report())
    print(f"Best strategy: {engine.get_best_strategy()}")
    print(f"Weights: {engine.get_weights()}")

    # Simulate current allocation equal-weight and show shift plan
    equal = {s: 100_000.0 / 3 for s in strategies}
    plan = engine.get_shift_plan(current_usd=equal)
    print("\nCapital shift plan:")
    for shift in plan:
        print(f"  Move ${shift.amount_usd:,.2f} from {shift.from_strategy} "
              f"→ {shift.to_strategy}  ({shift.reason})")
