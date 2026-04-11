"""
NIJA Strategy Robustness Layer
================================

Answers the question: *does the dual-RSI edge survive the current market regime?*

For every closed trade the layer records whether the strategy won or lost and
which market regime was active at the time.  Before each new entry the layer
checks whether the per-regime win-rate has fallen below a configurable floor —
if it has, the trade is blocked until the edge recovers.

Architecture
------------
::

    ┌─────────────────────────────────────────────────────────────────┐
    │                  StrategyRobustnessLayer                         │
    │                                                                   │
    │  1. Regime History   – rolling deque of (regime, win) per trade  │
    │                                                                   │
    │  2. Edge Metrics     – win-rate + profit-factor per regime        │
    │                                                                   │
    │  3. Gate             – approve_entry() blocks when edge is weak   │
    │                                                                   │
    │  4. Persistence      – state saved to data/robustness_state.json  │
    └─────────────────────────────────────────────────────────────────┘

Usage
-----
    from bot.strategy_robustness_layer import get_strategy_robustness_layer

    srl = get_strategy_robustness_layer()

    # Before every entry:
    decision = srl.approve_entry(regime="ranging", confidence=0.6)
    if not decision.allowed:
        logger.warning("Robustness gate blocked entry: %s", decision.reason)
        return

    # After every trade closes:
    srl.record_trade(regime="ranging", is_win=True, pnl_usd=12.50)

Author: NIJA Trading Systems
Version: 1.0
"""

from __future__ import annotations

import json
import logging
import threading
from collections import defaultdict, deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.strategy_robustness_layer")

# ---------------------------------------------------------------------------
# Configuration constants (all overridable via constructor kwargs)
# ---------------------------------------------------------------------------

# Minimum trades in a regime before we trust its statistics
DEFAULT_MIN_REGIME_TRADES: int = 10

# Win-rate below this for a given regime → block new entries in that regime
DEFAULT_MIN_WIN_RATE: float = 0.40

# Profit-factor below this (total_profit / total_loss) → block entries
DEFAULT_MIN_PROFIT_FACTOR: float = 0.80

# Rolling window: only the last N trades per regime count
DEFAULT_REGIME_WINDOW: int = 30

# Regimes considered high-risk even when statistics are sparse
HIGH_RISK_REGIMES: frozenset = frozenset({"crisis", "volatility_spike"})

# Win-rate floor applied to high-risk regimes regardless of sample size
HIGH_RISK_MIN_WIN_RATE: float = 0.50

DATA_DIR: Path = Path(__file__).parent.parent / "data"


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class RegimeStats:
    """Running statistics for a single market regime."""
    regime: str
    total_trades: int = 0
    wins: int = 0
    total_profit_usd: float = 0.0
    total_loss_usd: float = 0.0
    last_updated: str = ""

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades if self.total_trades else 0.0

    @property
    def profit_factor(self) -> float:
        if self.total_loss_usd == 0:
            return float("inf") if self.total_profit_usd > 0 else 1.0
        return self.total_profit_usd / self.total_loss_usd

    def to_dict(self) -> Dict:
        return {
            "regime": self.regime,
            "total_trades": self.total_trades,
            "wins": self.wins,
            "win_rate": round(self.win_rate, 4),
            "profit_factor": round(self.profit_factor, 4),
            "total_profit_usd": round(self.total_profit_usd, 4),
            "total_loss_usd": round(self.total_loss_usd, 4),
            "last_updated": self.last_updated,
        }


@dataclass
class RobustnessDecision:
    """Result of an approve_entry() call."""
    allowed: bool
    regime: str
    reason: str
    win_rate: float
    profit_factor: float
    regime_trades: int


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

class StrategyRobustnessLayer:
    """
    Tracks the per-regime edge of the dual-RSI strategy and gates new entries
    when the win-rate or profit-factor has deteriorated below safe thresholds.

    Parameters
    ----------
    min_regime_trades : int
        Minimum number of trades in a regime before statistics are trusted.
    min_win_rate : float
        Win-rate floor across all regimes (default 0.40).
    min_profit_factor : float
        Profit-factor floor (default 0.80).
    regime_window : int
        Rolling window: only the last N trades per regime contribute.
    """

    _STATE_FILE = DATA_DIR / "robustness_state.json"

    def __init__(
        self,
        min_regime_trades: int = DEFAULT_MIN_REGIME_TRADES,
        min_win_rate: float = DEFAULT_MIN_WIN_RATE,
        min_profit_factor: float = DEFAULT_MIN_PROFIT_FACTOR,
        regime_window: int = DEFAULT_REGIME_WINDOW,
    ) -> None:
        self.min_regime_trades = min_regime_trades
        self.min_win_rate = min_win_rate
        self.min_profit_factor = min_profit_factor
        self.regime_window = regime_window

        # Rolling trade history per regime: deque of (is_win, pnl_usd)
        self._history: Dict[str, Deque[Tuple[bool, float]]] = defaultdict(
            lambda: deque(maxlen=self.regime_window)
        )
        # Persistent all-time stats (not windowed) — for reporting
        self._stats: Dict[str, RegimeStats] = {}

        self._lock = threading.RLock()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load_state()

        logger.info(
            "✅ Strategy Robustness Layer initialized | "
            "min_trades=%d  min_wr=%.0f%%  min_pf=%.2f  window=%d",
            self.min_regime_trades,
            self.min_win_rate * 100,
            self.min_profit_factor,
            self.regime_window,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def approve_entry(
        self,
        regime: str,
        confidence: float = 1.0,
    ) -> RobustnessDecision:
        """
        Decide whether the strategy has a sufficient edge in *regime* to
        justify opening a new position.

        Parameters
        ----------
        regime : str
            Current market regime string (e.g. ``"ranging"``, ``"strong_trend"``).
        confidence : float
            Signal confidence in [0, 1].  Not yet used for gating but
            included for future calibration.

        Returns
        -------
        RobustnessDecision
        """
        regime_key = (regime or "unknown").lower().replace(" ", "_")
        with self._lock:
            win_rate, profit_factor, n_trades = self._rolling_metrics(regime_key)

            # Not enough data → optimistic pass (trust the signal)
            if n_trades < self.min_regime_trades:
                return RobustnessDecision(
                    allowed=True,
                    regime=regime_key,
                    reason=f"insufficient regime data ({n_trades}/{self.min_regime_trades} trades) — optimistic pass",
                    win_rate=win_rate,
                    profit_factor=profit_factor,
                    regime_trades=n_trades,
                )

            # High-risk regimes have a stricter floor
            effective_min_wr = (
                HIGH_RISK_MIN_WIN_RATE
                if regime_key in HIGH_RISK_REGIMES
                else self.min_win_rate
            )

            reason_parts: List[str] = []
            allowed = True

            if win_rate < effective_min_wr:
                allowed = False
                reason_parts.append(
                    f"win_rate={win_rate:.1%} < floor={effective_min_wr:.1%} in regime={regime_key}"
                )
            if profit_factor < self.min_profit_factor:
                allowed = False
                reason_parts.append(
                    f"profit_factor={profit_factor:.2f} < floor={self.min_profit_factor:.2f}"
                )

            reason = (
                " | ".join(reason_parts)
                if reason_parts
                else (
                    f"edge healthy in {regime_key} "
                    f"(wr={win_rate:.1%} pf={profit_factor:.2f} n={n_trades})"
                )
            )

            decision = RobustnessDecision(
                allowed=allowed,
                regime=regime_key,
                reason=reason,
                win_rate=win_rate,
                profit_factor=profit_factor,
                regime_trades=n_trades,
            )

            if not allowed:
                logger.warning(
                    "🛡️  Robustness gate BLOCKED entry in regime=%s: %s",
                    regime_key,
                    reason,
                )
            else:
                logger.debug(
                    "✅ Robustness gate PASSED regime=%s wr=%.1%% pf=%.2f n=%d",
                    regime_key,
                    win_rate,
                    profit_factor,
                    n_trades,
                )

            return decision

    def record_trade(
        self,
        regime: str,
        is_win: bool,
        pnl_usd: float = 0.0,
    ) -> None:
        """
        Record the outcome of a completed trade for a given regime.

        Parameters
        ----------
        regime : str
            The market regime that was active when the trade was opened.
        is_win : bool
            Whether the trade was profitable.
        pnl_usd : float
            Net profit/loss in USD (positive for wins, negative for losses).
        """
        regime_key = (regime or "unknown").lower().replace(" ", "_")
        now_ts = datetime.now(timezone.utc).isoformat()

        with self._lock:
            # Rolling window
            self._history[regime_key].append((is_win, pnl_usd))

            # All-time stats
            if regime_key not in self._stats:
                self._stats[regime_key] = RegimeStats(regime=regime_key)
            s = self._stats[regime_key]
            s.total_trades += 1
            if is_win:
                s.wins += 1
                s.total_profit_usd += abs(pnl_usd)
            else:
                s.total_loss_usd += abs(pnl_usd)
            s.last_updated = now_ts

            self._save_state()

        logger.debug(
            "Robustness: recorded %s trade in regime=%s pnl=%.2f "
            "all_time wr=%.1%% pf=%.2f",
            "WIN" if is_win else "LOSS",
            regime_key,
            pnl_usd,
            self._stats[regime_key].win_rate,
            self._stats[regime_key].profit_factor,
        )

    def get_regime_report(self) -> List[Dict]:
        """Return per-regime edge statistics as a list of dicts."""
        with self._lock:
            report = []
            for regime_key, stat in sorted(self._stats.items()):
                row = stat.to_dict()
                roll_wr, roll_pf, roll_n = self._rolling_metrics(regime_key)
                row["rolling_win_rate"] = round(roll_wr, 4)
                row["rolling_profit_factor"] = round(roll_pf, 4)
                row["rolling_trades"] = roll_n
                report.append(row)
            return report

    def log_report(self) -> None:
        """Log a summary table of per-regime edge health."""
        rows = self.get_regime_report()
        if not rows:
            logger.info("📊 Strategy Robustness: no trades recorded yet")
            return
        logger.info("=" * 70)
        logger.info("📊 STRATEGY ROBUSTNESS LAYER — per-regime edge health")
        logger.info("=" * 70)
        header = f"  {'Regime':<22} {'Trades':>6} {'WinRate':>8} {'PF':>6} {'Roll WR':>8} {'Roll PF':>7}"
        logger.info(header)
        logger.info("  " + "-" * 65)
        for r in rows:
            healthy = "✅" if r["rolling_win_rate"] >= self.min_win_rate else "⚠️ "
            logger.info(
                "  %s %-20s %6d %7.1f%% %6.2f %7.1f%% %7.2f",
                healthy,
                r["regime"],
                r["total_trades"],
                r["win_rate"] * 100,
                r["profit_factor"],
                r["rolling_win_rate"] * 100,
                r["rolling_profit_factor"],
            )
        logger.info("=" * 70)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _rolling_metrics(
        self, regime_key: str
    ) -> Tuple[float, float, int]:
        """Return (win_rate, profit_factor, n_trades) from the rolling window."""
        history = self._history.get(regime_key, deque())
        n = len(history)
        if n == 0:
            return 0.0, 1.0, 0
        wins = sum(1 for (w, _) in history if w)
        profit = sum(p for (w, p) in history if w and p > 0)
        loss = sum(abs(p) for (w, p) in history if not w)
        pf = (profit / loss) if loss > 0 else (float("inf") if profit > 0 else 1.0)
        return wins / n, pf, n

    def _save_state(self) -> None:
        try:
            payload = {
                "stats": {k: v.to_dict() for k, v in self._stats.items()},
                "history": {
                    k: list(v)
                    for k, v in self._history.items()
                },
                "saved_at": datetime.now(timezone.utc).isoformat(),
            }
            tmp = self._STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
            tmp.replace(self._STATE_FILE)
        except Exception as exc:
            logger.debug("Robustness state save failed: %s", exc)

    def _load_state(self) -> None:
        try:
            if not self._STATE_FILE.exists():
                return
            payload = json.loads(self._STATE_FILE.read_text(encoding="utf-8"))
            for key, row in payload.get("stats", {}).items():
                s = RegimeStats(regime=key)
                s.total_trades = row.get("total_trades", 0)
                s.wins = row.get("wins", 0)
                s.total_profit_usd = row.get("total_profit_usd", 0.0)
                s.total_loss_usd = row.get("total_loss_usd", 0.0)
                s.last_updated = row.get("last_updated", "")
                self._stats[key] = s
            for key, pairs in payload.get("history", {}).items():
                dq = deque(maxlen=self.regime_window)
                for item in pairs[-self.regime_window:]:
                    if isinstance(item, (list, tuple)) and len(item) == 2:
                        dq.append((bool(item[0]), float(item[1])))
                self._history[key] = dq
            logger.debug("Robustness state loaded from %s", self._STATE_FILE)
        except Exception as exc:
            logger.debug("Robustness state load failed (starting fresh): %s", exc)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_instance: Optional[StrategyRobustnessLayer] = None
_instance_lock = threading.Lock()


def get_strategy_robustness_layer(**kwargs) -> StrategyRobustnessLayer:
    """Return the process-wide singleton StrategyRobustnessLayer."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = StrategyRobustnessLayer(**kwargs)
    return _instance
