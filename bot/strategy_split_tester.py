"""
NIJA Strategy A/B Split Tester
================================

Runs two trading strategies simultaneously in live paper-equivalent mode,
tracks their performance, and automatically switches to the winner.

Architecture
------------
::

    ┌──────────────────────────────────────────────────────────────────┐
    │                   StrategySplitTester                            │
    │                                                                  │
    │  Strategy A (challenger)  vs  Strategy B (control)              │
    │                                                                  │
    │  Tracks per-strategy:                                            │
    │    • Cumulative P&L (USD)                                        │
    │    • Win rate                                                    │
    │    • Profit factor (gross wins / gross losses)                   │
    │    • Sharpe ratio (simplified rolling)                           │
    │    • Max drawdown                                                │
    │                                                                  │
    │  Evaluation:                                                     │
    │    • After min_trades_per_strategy trades on EACH side           │
    │    • Winner = highest composite score                            │
    │    • Auto-switch logic: if winner confidence > threshold,        │
    │      returns winner via get_active_strategy()                    │
    │                                                                  │
    │  Composite score = win_rate×0.35 + profit_factor×0.30           │
    │                  + sharpe×0.20 + drawdown_score×0.15            │
    │                                                                  │
    └──────────────────────────────────────────────────────────────────┘

Usage
-----
::

    from bot.strategy_split_tester import get_strategy_split_tester

    tester = get_strategy_split_tester(strategy_a="ApexV71", strategy_b="MeanReversion")

    # On each trade entry — ask which strategy to use:
    active = tester.get_active_strategy()   # "ApexV71" or "MeanReversion"

    # After each trade closes:
    tester.record_trade(strategy="ApexV71", pnl_usd=+85.0, is_win=True)

    # Force a summary:
    print(tester.get_report())

    # Force manual strategy selection:
    tester.force_strategy("ApexV71")

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
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.strategy_split_tester")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DATA_DIR: str = "data"
DEFAULT_MIN_TRADES: int = 20        # min trades per side before auto-switch
DEFAULT_SWITCH_CONFIDENCE: float = 0.15  # winner must beat loser score by 15 %
PNLS_WINDOW: int = 100              # rolling window for Sharpe calculation
W_WIN_RATE: float = 0.35
W_PROFIT_FACTOR: float = 0.30
W_SHARPE: float = 0.20
W_DRAWDOWN: float = 0.15


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class StrategyMetrics:
    """Rolling performance metrics for one strategy."""
    name: str
    trade_count: int = 0
    win_count: int = 0
    total_pnl: float = 0.0
    gross_wins: float = 0.0
    gross_losses: float = 0.0   # absolute value
    peak_pnl: float = 0.0
    max_drawdown: float = 0.0   # as fraction of peak (0-1)
    pnl_window: Deque[float] = field(default_factory=lambda: deque(maxlen=PNLS_WINDOW))

    @property
    def win_rate(self) -> float:
        return self.win_count / self.trade_count if self.trade_count > 0 else 0.0

    @property
    def profit_factor(self) -> float:
        if self.gross_losses == 0.0:
            return self.gross_wins / 0.0001 if self.gross_wins > 0 else 1.0
        return self.gross_wins / self.gross_losses

    @property
    def sharpe(self) -> float:
        """Simplified Sharpe: mean/std of rolling P&L window."""
        window = list(self.pnl_window)
        if len(window) < 5:
            return 0.0
        n = len(window)
        mean = sum(window) / n
        variance = sum((x - mean) ** 2 for x in window) / n
        std = math.sqrt(variance) if variance > 0 else 1e-9
        return mean / std

    def update(self, pnl_usd: float, is_win: bool) -> None:
        self.trade_count += 1
        if is_win:
            self.win_count += 1
        self.total_pnl += pnl_usd
        if pnl_usd > 0:
            self.gross_wins += pnl_usd
        else:
            self.gross_losses += abs(pnl_usd)
        self.pnl_window.append(pnl_usd)
        if self.total_pnl > self.peak_pnl:
            self.peak_pnl = self.total_pnl
        if self.peak_pnl > 0:
            drawdown = (self.peak_pnl - self.total_pnl) / self.peak_pnl
            if drawdown > self.max_drawdown:
                self.max_drawdown = drawdown

    def composite_score(self) -> float:
        """Compute composite performance score (higher = better)."""
        wr_score = self.win_rate * 100.0
        pf_score = min(self.profit_factor, 5.0) / 5.0 * 100.0
        sharpe_score = max(0.0, min(self.sharpe, 3.0)) / 3.0 * 100.0
        dd_score = max(0.0, (1.0 - self.max_drawdown)) * 100.0
        return (
            W_WIN_RATE * wr_score
            + W_PROFIT_FACTOR * pf_score
            + W_SHARPE * sharpe_score
            + W_DRAWDOWN * dd_score
        )

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "trade_count": self.trade_count,
            "win_count": self.win_count,
            "total_pnl": self.total_pnl,
            "gross_wins": self.gross_wins,
            "gross_losses": self.gross_losses,
            "peak_pnl": self.peak_pnl,
            "max_drawdown": self.max_drawdown,
            "pnl_window": list(self.pnl_window),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "StrategyMetrics":
        obj = cls(name=d["name"])
        obj.trade_count = int(d.get("trade_count", 0))
        obj.win_count = int(d.get("win_count", 0))
        obj.total_pnl = float(d.get("total_pnl", 0.0))
        obj.gross_wins = float(d.get("gross_wins", 0.0))
        obj.gross_losses = float(d.get("gross_losses", 0.0))
        obj.peak_pnl = float(d.get("peak_pnl", 0.0))
        obj.max_drawdown = float(d.get("max_drawdown", 0.0))
        for p in d.get("pnl_window", []):
            obj.pnl_window.append(float(p))
        return obj


# ---------------------------------------------------------------------------
# Split Tester
# ---------------------------------------------------------------------------

class StrategySplitTester:
    """
    Live A/B strategy split tester with auto-switch capability.
    """

    def __init__(
        self,
        strategy_a: str,
        strategy_b: str,
        min_trades_per_strategy: int = DEFAULT_MIN_TRADES,
        switch_confidence: float = DEFAULT_SWITCH_CONFIDENCE,
        data_dir: Optional[str] = None,
    ) -> None:
        self._strategy_a = strategy_a
        self._strategy_b = strategy_b
        self._min_trades = min_trades_per_strategy
        self._switch_confidence = switch_confidence
        self._data_dir = Path(data_dir or DEFAULT_DATA_DIR)
        self._data_dir.mkdir(parents=True, exist_ok=True)

        self._metrics: Dict[str, StrategyMetrics] = {
            strategy_a: StrategyMetrics(name=strategy_a),
            strategy_b: StrategyMetrics(name=strategy_b),
        }
        self._active_strategy: str = strategy_a
        self._forced: bool = False
        self._switch_count: int = 0
        self._last_switch_at: Optional[str] = None

        self._lock = threading.Lock()
        self._load_state()
        logger.info(
            "StrategySplitTester: A=%s vs B=%s (min_trades=%d)",
            strategy_a, strategy_b, min_trades_per_strategy,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_trade(self, strategy: str, pnl_usd: float, is_win: bool) -> None:
        """
        Record the outcome of a closed trade attributed to ``strategy``.

        After recording, if both strategies have >= ``min_trades`` and
        the winner's score advantage exceeds ``switch_confidence``,
        the active strategy is updated automatically.
        """
        with self._lock:
            if strategy not in self._metrics:
                self._metrics[strategy] = StrategyMetrics(name=strategy)
            self._metrics[strategy].update(pnl_usd, is_win)
            self._maybe_auto_switch()

        self._save_state()

    def get_active_strategy(self) -> str:
        """Return the currently active (winning) strategy name."""
        with self._lock:
            return self._active_strategy

    def force_strategy(self, strategy: str) -> None:
        """
        Manually override the active strategy selection.
        Disables auto-switch until :meth:`enable_auto_switch` is called.
        """
        with self._lock:
            self._active_strategy = strategy
            self._forced = True
            logger.info("StrategySplitTester: forced strategy → %s", strategy)
        self._save_state()

    def enable_auto_switch(self) -> None:
        """Re-enable auto-switching after a manual override."""
        with self._lock:
            self._forced = False
        logger.info("StrategySplitTester: auto-switch re-enabled")

    def get_metrics(self, strategy: str) -> Optional[StrategyMetrics]:
        """Return the :class:`StrategyMetrics` for the named strategy."""
        with self._lock:
            return self._metrics.get(strategy)

    def get_winner(self) -> Tuple[str, float]:
        """
        Return (winner_name, score_delta) based on composite scores.
        score_delta is always positive (winner minus loser score).
        """
        with self._lock:
            a = self._metrics[self._strategy_a]
            b = self._metrics[self._strategy_b]
            score_a = a.composite_score()
            score_b = b.composite_score()
        if score_a >= score_b:
            return self._strategy_a, score_a - score_b
        return self._strategy_b, score_b - score_a

    def get_report(self) -> str:
        """Human-readable split-test performance report."""
        with self._lock:
            active = self._active_strategy
            metrics = {k: v for k, v in self._metrics.items()}

        lines = [
            "═══════════════════════════════════════════════════",
            "  NIJA Strategy A/B Split Tester",
            "═══════════════════════════════════════════════════",
            f"  Active strategy : {active}",
            f"  Switches        : {self._switch_count}",
            "───────────────────────────────────────────────────",
        ]
        for name, m in metrics.items():
            marker = " ← ACTIVE" if name == active else ""
            lines += [
                f"  [{name}]{marker}",
                f"    Trades       : {m.trade_count}",
                f"    Win rate     : {m.win_rate:.1%}",
                f"    Profit factor: {m.profit_factor:.2f}",
                f"    Sharpe       : {m.sharpe:.2f}",
                f"    Max drawdown : {m.max_drawdown:.1%}",
                f"    Total P&L    : ${m.total_pnl:,.2f}",
                f"    Composite    : {m.composite_score():.1f}/100",
                "  ─────────────────────────────────────────────",
            ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _maybe_auto_switch(self) -> None:
        """Check if we should switch strategies (caller must hold lock)."""
        if self._forced:
            return
        a = self._metrics.get(self._strategy_a)
        b = self._metrics.get(self._strategy_b)
        if a is None or b is None:
            return
        if a.trade_count < self._min_trades or b.trade_count < self._min_trades:
            return

        score_a = a.composite_score()
        score_b = b.composite_score()
        winner = self._strategy_a if score_a >= score_b else self._strategy_b
        delta = abs(score_a - score_b)
        max_score = max(score_a, score_b, 1.0)
        relative_delta = delta / max_score

        if winner != self._active_strategy and relative_delta >= self._switch_confidence:
            prev = self._active_strategy
            self._active_strategy = winner
            self._switch_count += 1
            self._last_switch_at = datetime.now(timezone.utc).isoformat()
            logger.info(
                "StrategySplitTester: auto-switched %s → %s (delta=%.1f%%)",
                prev, winner, relative_delta * 100,
            )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        path = self._data_dir / "strategy_split_tester.json"
        try:
            with self._lock:
                state = {
                    "strategy_a": self._strategy_a,
                    "strategy_b": self._strategy_b,
                    "active_strategy": self._active_strategy,
                    "forced": self._forced,
                    "switch_count": self._switch_count,
                    "last_switch_at": self._last_switch_at,
                    "metrics": {k: v.to_dict() for k, v in self._metrics.items()},
                }
            path.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.warning("StrategySplitTester: save failed: %s", exc)

    def _load_state(self) -> None:
        path = self._data_dir / "strategy_split_tester.json"
        if not path.exists():
            return
        try:
            state = json.loads(path.read_text(encoding="utf-8"))
            # Only restore if same A/B pair
            if (
                state.get("strategy_a") == self._strategy_a
                and state.get("strategy_b") == self._strategy_b
            ):
                self._active_strategy = state.get("active_strategy", self._strategy_a)
                self._forced = bool(state.get("forced", False))
                self._switch_count = int(state.get("switch_count", 0))
                self._last_switch_at = state.get("last_switch_at")
                for name, mdict in state.get("metrics", {}).items():
                    self._metrics[name] = StrategyMetrics.from_dict(mdict)
                logger.info(
                    "StrategySplitTester: loaded state (active=%s, switches=%d)",
                    self._active_strategy, self._switch_count,
                )
        except Exception as exc:
            logger.warning("StrategySplitTester: load failed: %s", exc)


# ---------------------------------------------------------------------------
# Singleton (default A/B pair — can be overridden at startup)
# ---------------------------------------------------------------------------

_INSTANCE: Optional[StrategySplitTester] = None
_INSTANCE_LOCK = threading.Lock()


def get_strategy_split_tester(
    strategy_a: str = "ApexV71",
    strategy_b: str = "MeanReversion",
    min_trades_per_strategy: int = DEFAULT_MIN_TRADES,
    switch_confidence: float = DEFAULT_SWITCH_CONFIDENCE,
    data_dir: Optional[str] = None,
) -> StrategySplitTester:
    """
    Thread-safe singleton accessor.

    The first call establishes the A/B pair; subsequent calls return the
    existing instance regardless of the arguments passed.
    """
    global _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is None:
            _INSTANCE = StrategySplitTester(
                strategy_a=strategy_a,
                strategy_b=strategy_b,
                min_trades_per_strategy=min_trades_per_strategy,
                switch_confidence=switch_confidence,
                data_dir=data_dir,
            )
    return _INSTANCE
