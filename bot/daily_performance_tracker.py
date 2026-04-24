"""
NIJA Daily Performance Tracker
================================

Tracks five key metrics that reset automatically each calendar day (UTC):

    1. Win rate         — wins / total closed trades
    2. Avg win %        — mean return on winning trades as % of position
    3. Avg loss %       — mean return on losing trades as % of position
    4. Net PnL          — cumulative realised P&L in USD for the day
    5. Max drawdown %   — largest peak-to-trough equity decline intraday

State is persisted to ``data/daily_perf_checkpoint.json`` so the tracker
resumes correctly after a bot restart within the same calendar day.
Completed days are appended to ``data/daily_performance_tracker.jsonl``
as a permanent audit log.

Usage::

    from bot.daily_performance_tracker import get_daily_performance_tracker

    tracker = get_daily_performance_tracker()

    # After every closed trade supply the USD P&L and the % return:
    tracker.record_trade(pnl_usd=4.20, pnl_pct=0.028)   # +2.8 % win
    tracker.record_trade(pnl_usd=-1.80, pnl_pct=-0.012) # -1.2 % loss

    # Read today's snapshot at any time:
    snap = tracker.get_today_stats()
    print(snap)
    # [2026-03-20] trades=2(1W/1L) wr=50.0% avg_win=+2.80% avg_loss=-1.20%
    #              net=+$2.40 mdd=0.86%

Author: NIJA Trading Systems
Version: 1.0
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("nija.daily_performance_tracker")

_DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DailySnapshot:
    """
    Immutable snapshot of today's five tracked performance metrics.

    Attributes:
        date:             ISO-8601 date string (UTC), e.g. ``"2026-03-20"``.
        trades:           Total closed trades today.
        wins:             Number of winning trades (pnl_usd > 0).
        losses:           Number of losing trades (pnl_usd <= 0).
        win_rate:         Fraction of winning trades (0–1).
        avg_win_pct:      Mean return on winning trades as a fraction
                          (e.g. 0.025 = +2.5 %).  0.0 when no wins.
        avg_loss_pct:     Mean return on losing trades as a negative
                          fraction (e.g. -0.012 = -1.2 %).  0.0 when no
                          losses.
        net_pnl:          Cumulative realised USD P&L for the day.
        max_drawdown_pct: Maximum intraday peak-to-trough equity drawdown
                          as a fraction (0–1).
    """
    date: str
    trades: int
    wins: int
    losses: int
    win_rate: float
    avg_win_pct: float
    avg_loss_pct: float
    net_pnl: float
    max_drawdown_pct: float

    def __str__(self) -> str:
        wr = f"{self.win_rate * 100:.1f}%"
        aw = f"{self.avg_win_pct * 100:+.2f}%" if self.wins else "—"
        al = f"{self.avg_loss_pct * 100:+.2f}%" if self.losses else "—"
        mdd = f"{self.max_drawdown_pct * 100:.2f}%"
        return (
            f"[{self.date}] trades={self.trades}"
            f"({self.wins}W/{self.losses}L) "
            f"wr={wr} avg_win={aw} avg_loss={al} "
            f"net=${self.net_pnl:+.2f} mdd={mdd}"
        )


# ---------------------------------------------------------------------------
# Tracker engine
# ---------------------------------------------------------------------------

class DailyPerformanceTracker:
    """
    Real-time daily performance tracker.

    Thread-safe.  All counters reset automatically when the UTC calendar
    date changes.  The in-progress day is checkpointed after every trade
    so the tracker survives bot restarts within the same day.
    """

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self._lock = threading.Lock()
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self._data_dir.mkdir(parents=True, exist_ok=True)

        # Persistent files
        self._checkpoint_file = self._data_dir / "daily_perf_checkpoint.json"
        self._history_file = self._data_dir / "daily_performance_tracker.jsonl"

        # Per-day accumulators
        self._today: str = ""
        self._trades: int = 0
        self._wins: int = 0
        self._losses: int = 0
        self._net_pnl: float = 0.0
        # Running sums of pnl_pct for wins / losses.
        # Stored as positive magnitudes so averaging is straightforward;
        # avg_loss_pct is negated when building the output snapshot to
        # preserve the conventional negative sign for losses.
        self._win_pct_sum: float = 0.0
        self._loss_pct_sum: float = 0.0
        # Intraday equity curve starting at 0
        self._equity_curve: List[float] = [0.0]

        self._load_state()
        logger.info(
            "📊 DailyPerformanceTracker initialised — date=%s trades=%d",
            self._today, self._trades,
        )

    # -----------------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------------

    def record_trade(self, pnl_usd: float, pnl_pct: float = 0.0) -> None:
        """
        Record a single closed trade.

        Args:
            pnl_usd: Realised P&L in USD.  Positive = win, negative = loss.
            pnl_pct: P&L as a fraction of position size
                     (e.g. 0.03 = +3 %, -0.015 = -1.5 %).
                     Supply 0.0 when unknown — the percentage averages will
                     then exclude that trade.
        """
        with self._lock:
            self._check_daily_reset()

            self._trades += 1
            self._net_pnl += pnl_usd

            if pnl_usd > 0:
                self._wins += 1
                if pnl_pct != 0.0:
                    self._win_pct_sum += pnl_pct
            else:
                self._losses += 1
                if pnl_pct != 0.0:
                    self._loss_pct_sum += abs(pnl_pct)

            self._equity_curve.append(self._equity_curve[-1] + pnl_usd)
            self._save_state()
            snap = self._build_snapshot()

        logger.info("📊 Daily stats → %s", snap)

    def get_today_stats(self) -> DailySnapshot:
        """Return a snapshot of the five tracked metrics for today."""
        with self._lock:
            self._check_daily_reset()
            return self._build_snapshot()

    def get_history(self) -> List[DailySnapshot]:
        """
        Return all completed daily snapshots from the JSONL audit log,
        oldest first.  Today's in-progress snapshot is NOT included.
        """
        rows: List[DailySnapshot] = []
        if not self._history_file.exists():
            return rows
        with open(self._history_file, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(DailySnapshot(**json.loads(line)))
                except Exception:
                    pass
        return rows

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _today_str() -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def _check_daily_reset(self) -> None:
        """Reset all counters when the UTC calendar date has changed."""
        today = self._today_str()
        if today == self._today:
            return

        if self._today and self._trades > 0:
            # Persist the completed day before wiping counters
            self._append_to_history(self._build_snapshot())

        self._today = today
        self._trades = 0
        self._wins = 0
        self._losses = 0
        self._net_pnl = 0.0
        self._win_pct_sum = 0.0
        self._loss_pct_sum = 0.0
        self._equity_curve = [0.0]
        logger.info("📅 DailyPerformanceTracker — new day: %s", today)

    def _build_snapshot(self) -> DailySnapshot:
        """Construct a DailySnapshot from current accumulators (call inside lock)."""
        win_rate = self._wins / self._trades if self._trades else 0.0
        avg_win_pct = self._win_pct_sum / self._wins if self._wins else 0.0
        avg_loss_pct = -(self._loss_pct_sum / self._losses) if self._losses else 0.0
        return DailySnapshot(
            date=self._today or self._today_str(),
            trades=self._trades,
            wins=self._wins,
            losses=self._losses,
            win_rate=round(win_rate, 4),
            avg_win_pct=round(avg_win_pct, 4),
            avg_loss_pct=round(avg_loss_pct, 4),
            net_pnl=round(self._net_pnl, 2),
            max_drawdown_pct=round(self._compute_max_drawdown(), 4),
        )

    def _compute_max_drawdown(self) -> float:
        """
        Max intraday peak-to-trough equity drawdown as a fraction (0–1).
        """
        peak = 0.0
        max_dd = 0.0
        for equity in self._equity_curve:
            peak = max(peak, equity)
            if peak > 0:
                dd = (peak - equity) / peak
                max_dd = max(max_dd, dd)
        return max_dd

    def _save_state(self) -> None:
        """Checkpoint current counters to disk (called after every trade)."""
        try:
            data = {
                "date": self._today,
                "trades": self._trades,
                "wins": self._wins,
                "losses": self._losses,
                "net_pnl": self._net_pnl,
                "win_pct_sum": self._win_pct_sum,
                "loss_pct_sum": self._loss_pct_sum,
                "equity_curve": self._equity_curve,
            }
            self._checkpoint_file.write_text(
                json.dumps(data), encoding="utf-8"
            )
        except Exception as exc:
            logger.warning("DailyPerformanceTracker: save failed: %s", exc)

    def _load_state(self) -> None:
        """Restore today's counters from the checkpoint file (if same day)."""
        if not self._checkpoint_file.exists():
            self._today = self._today_str()
            return
        try:
            data = json.loads(
                self._checkpoint_file.read_text(encoding="utf-8")
            )
            if data.get("date") == self._today_str():
                self._today = data["date"]
                self._trades = int(data.get("trades", 0))
                self._wins = int(data.get("wins", 0))
                self._losses = int(data.get("losses", 0))
                self._net_pnl = float(data.get("net_pnl", 0.0))
                self._win_pct_sum = float(data.get("win_pct_sum", 0.0))
                self._loss_pct_sum = float(data.get("loss_pct_sum", 0.0))
                self._equity_curve = data.get("equity_curve", [0.0])
                logger.info(
                    "DailyPerformanceTracker: resumed %d trades from checkpoint",
                    self._trades,
                )
            else:
                self._today = self._today_str()
        except Exception as exc:
            logger.warning(
                "DailyPerformanceTracker: load failed: %s", exc
            )
            self._today = self._today_str()

    def _append_to_history(self, snap: DailySnapshot) -> None:
        """Append a completed day's snapshot to the JSONL audit log."""
        try:
            with open(self._history_file, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(asdict(snap)) + "\n")
        except Exception as exc:
            logger.warning(
                "DailyPerformanceTracker: history append failed: %s", exc
            )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_tracker: Optional[DailyPerformanceTracker] = None
_singleton_lock = threading.Lock()


def get_daily_performance_tracker(
    data_dir: Optional[Path] = None,
) -> DailyPerformanceTracker:
    """
    Return the process-wide :class:`DailyPerformanceTracker` singleton.

    Args:
        data_dir: Override the storage directory (useful in tests).

    Returns:
        The singleton :class:`DailyPerformanceTracker` instance.
    """
    global _tracker
    if _tracker is None:
        with _singleton_lock:
            if _tracker is None:
                _tracker = DailyPerformanceTracker(data_dir=data_dir)
    return _tracker
