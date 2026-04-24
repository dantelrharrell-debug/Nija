"""
NIJA RL Validation Engine
==========================

Validates that NIJA's parameter optimisers and RL adapters genuinely improve
performance over time rather than over-fitting or degrading.

Methodology
-----------
1. **Rolling Evaluation Windows** – performance is measured over a sliding
   window of N trades.  The engine compares successive windows to detect
   improvements or regressions.
2. **Regime Change Detection** – checks whether the RL adapter correctly
   adjusts its policy when the market regime shifts (e.g. trending → ranging).
3. **Validation Metrics** – Sharpe ratio, win rate, profit factor, and
   learning efficiency (reward per episode) are tracked per window.
4. **Pass/Fail Gates** – configurable thresholds determine whether the RL
   loop is genuinely learning or stagnating.

Integration points
------------------
- ``bot.live_rl_feedback``              – live RL Q-learning loop
- ``bot.self_learning_strategy_allocator`` – weight adaptation
- ``bot.adaptive_market_regime_engine`` – regime labels

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import statistics
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.rl_validation")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_WINDOW_SIZE: int = 30            # trades per evaluation window
DEFAULT_MIN_WINDOWS: int = 3             # need at least this many windows before judging
DEFAULT_IMPROVEMENT_THRESHOLD: float = 0.02  # 2 % improvement in win rate = learning
DEFAULT_MIN_WIN_RATE: float = 0.45       # absolute floor; fail if win rate < this

REGIME_LABELS: List[str] = ["trending", "ranging", "volatile", "unknown"]


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class ValidationStatus(Enum):
    LEARNING = "learning"          # RL is clearly improving over time
    STABLE = "stable"              # Performance is flat — acceptable but not improving
    DEGRADING = "degrading"        # Performance is worsening — investigate
    INSUFFICIENT_DATA = "insufficient_data"  # Not enough windows yet


@dataclass
class TradeRecord:
    """One completed trade as seen by the validation engine."""
    trade_id: str
    strategy: str
    regime: str
    pnl_usd: float
    return_pct: float
    is_win: bool
    rl_action: Optional[int] = None      # RL strategy index chosen
    rl_reward: Optional[float] = None    # Reward signal received
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class WindowMetrics:
    """Performance metrics for one evaluation window."""
    window_id: int
    trade_count: int
    win_rate: float
    profit_factor: float
    sharpe_ratio: float
    avg_return_pct: float
    avg_rl_reward: float
    dominant_regime: str
    start_trade: int                     # index of first trade in window
    end_trade: int                       # index of last trade in window

    @property
    def score(self) -> float:
        """Composite score (higher = better)."""
        return (
            self.win_rate * 40
            + min(self.profit_factor, 5.0) * 10
            + min(self.sharpe_ratio, 3.0) * 10
            + self.avg_rl_reward * 5
        )


@dataclass
class ValidationReport:
    """Full validation report across all rolling windows."""
    timestamp: str
    status: ValidationStatus
    total_trades: int
    num_windows: int
    window_metrics: List[WindowMetrics]
    improvement_rate: float          # avg change in score between successive windows
    regime_adaptation_score: float   # 0–1; 1 = perfectly adapts to regime changes
    notes: List[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            "=== RL Validation Engine Report ===",
            f"  Timestamp          : {self.timestamp}",
            f"  Status             : {self.status.value.upper()}",
            f"  Total trades       : {self.total_trades}",
            f"  Windows evaluated  : {self.num_windows}",
            f"  Improvement rate   : {self.improvement_rate:+.3f} pts/window",
            f"  Regime adaptation  : {self.regime_adaptation_score:.2f} / 1.00",
        ]
        if self.notes:
            lines.append("  Notes:")
            for note in self.notes:
                lines.append(f"    • {note}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helper: compute metrics for a list of trade records
# ---------------------------------------------------------------------------

def _compute_window_metrics(
    trades: List[TradeRecord], window_id: int, start: int, end: int
) -> WindowMetrics:
    n = len(trades)
    if n == 0:
        return WindowMetrics(
            window_id=window_id, trade_count=0,
            win_rate=0, profit_factor=0, sharpe_ratio=0,
            avg_return_pct=0, avg_rl_reward=0,
            dominant_regime="unknown", start_trade=start, end_trade=end,
        )

    wins = sum(1 for t in trades if t.is_win)
    win_rate = wins / n

    gross_profit = sum(t.pnl_usd for t in trades if t.pnl_usd > 0) or 0.0
    gross_loss = abs(sum(t.pnl_usd for t in trades if t.pnl_usd < 0)) or 1e-9
    profit_factor = gross_profit / gross_loss

    returns = [t.return_pct for t in trades]
    avg_ret = statistics.mean(returns)
    std_ret = statistics.stdev(returns) if len(returns) > 1 else 0.0
    sharpe = avg_ret / std_ret * (252 ** 0.5) if std_ret > 0 else 0.0  # annualised

    rl_rewards = [t.rl_reward for t in trades if t.rl_reward is not None]
    avg_reward = statistics.mean(rl_rewards) if rl_rewards else 0.0

    # Dominant regime
    regime_counts: Dict[str, int] = {}
    for t in trades:
        regime_counts[t.regime] = regime_counts.get(t.regime, 0) + 1
    dominant_regime = max(regime_counts, key=regime_counts.get) if regime_counts else "unknown"

    return WindowMetrics(
        window_id=window_id,
        trade_count=n,
        win_rate=win_rate,
        profit_factor=profit_factor,
        sharpe_ratio=sharpe,
        avg_return_pct=avg_ret,
        avg_rl_reward=avg_reward,
        dominant_regime=dominant_regime,
        start_trade=start,
        end_trade=end,
    )


# ---------------------------------------------------------------------------
# Main validation engine
# ---------------------------------------------------------------------------

class RLValidationEngine:
    """
    Validates RL adapter improvement over rolling evaluation windows.

    Parameters
    ----------
    window_size : int
        Number of trades per evaluation window.
    min_windows : int
        Minimum number of full windows required before emitting a status.
    improvement_threshold : float
        Minimum score increase per window to classify the RL loop as LEARNING.
    min_win_rate : float
        Absolute win-rate floor; any window below this triggers DEGRADING.
    """

    def __init__(
        self,
        window_size: int = DEFAULT_WINDOW_SIZE,
        min_windows: int = DEFAULT_MIN_WINDOWS,
        improvement_threshold: float = DEFAULT_IMPROVEMENT_THRESHOLD,
        min_win_rate: float = DEFAULT_MIN_WIN_RATE,
    ) -> None:
        self.window_size = window_size
        self.min_windows = min_windows
        self.improvement_threshold = improvement_threshold
        self.min_win_rate = min_win_rate

        self._trades: List[TradeRecord] = []
        self._windows: List[WindowMetrics] = []
        self._lock = threading.Lock()

        logger.info(
            "RLValidationEngine initialised — window=%d, min_windows=%d",
            window_size, min_windows,
        )

    # ------------------------------------------------------------------
    # Trade ingestion
    # ------------------------------------------------------------------

    def record_trade(self, trade: TradeRecord) -> None:
        """Record a completed trade and trigger a window evaluation if ready."""
        with self._lock:
            self._trades.append(trade)
            self._try_compute_window()

    def record_trades(self, trades: List[TradeRecord]) -> None:
        """Batch record trades."""
        with self._lock:
            self._trades.extend(trades)
            self._try_compute_window()

    # ------------------------------------------------------------------
    # Internal window computation
    # ------------------------------------------------------------------

    def _try_compute_window(self) -> None:
        """Compute a new window metric if enough new trades have arrived."""
        next_window_start = len(self._windows) * self.window_size
        while len(self._trades) >= next_window_start + self.window_size:
            window_trades = self._trades[next_window_start: next_window_start + self.window_size]
            metrics = _compute_window_metrics(
                window_trades,
                window_id=len(self._windows),
                start=next_window_start,
                end=next_window_start + self.window_size - 1,
            )
            self._windows.append(metrics)
            logger.debug(
                "Window %d computed: win_rate=%.1f%%, score=%.2f",
                metrics.window_id, metrics.win_rate * 100, metrics.score,
            )
            next_window_start += self.window_size

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def validate(self) -> ValidationReport:
        """
        Run the full validation and return a ``ValidationReport``.

        The status is determined as follows:
        - INSUFFICIENT_DATA → fewer than min_windows completed
        - DEGRADING         → any window has win_rate < min_win_rate
        - LEARNING          → avg score improvement ≥ improvement_threshold
        - STABLE            → otherwise
        """
        with self._lock:
            windows = list(self._windows)
            trades = list(self._trades)

        notes: List[str] = []

        if len(windows) < self.min_windows:
            return ValidationReport(
                timestamp=datetime.utcnow().isoformat(),
                status=ValidationStatus.INSUFFICIENT_DATA,
                total_trades=len(trades),
                num_windows=len(windows),
                window_metrics=windows,
                improvement_rate=0.0,
                regime_adaptation_score=0.0,
                notes=[
                    f"Need {self.min_windows} windows; only {len(windows)} completed "
                    f"({len(trades)} trades recorded, {self.window_size} per window)."
                ],
            )

        # Check for any degrading window
        degrading_windows = [w for w in windows if w.win_rate < self.min_win_rate]
        if degrading_windows:
            notes.append(
                f"{len(degrading_windows)} window(s) with win_rate < "
                f"{self.min_win_rate:.0%}"
            )
            status = ValidationStatus.DEGRADING
        else:
            # Calculate improvement rate (change in composite score per window)
            score_deltas = [
                windows[i].score - windows[i - 1].score
                for i in range(1, len(windows))
            ]
            improvement_rate = statistics.mean(score_deltas) if score_deltas else 0.0

            if improvement_rate >= self.improvement_threshold:
                status = ValidationStatus.LEARNING
                notes.append(
                    f"RL loop is learning: avg improvement "
                    f"{improvement_rate:+.3f} pts/window"
                )
            else:
                status = ValidationStatus.STABLE
                notes.append(
                    f"RL loop is stable but not improving "
                    f"(improvement_rate={improvement_rate:+.3f})"
                )

        # Regime adaptation score: fraction of regime-change windows where
        # the RL reward improved vs. the prior window.
        regime_adaptation_score = self._compute_regime_adaptation(windows)

        improvement_rate_val = 0.0
        if len(windows) > 1:
            deltas = [windows[i].score - windows[i - 1].score for i in range(1, len(windows))]
            improvement_rate_val = statistics.mean(deltas)

        return ValidationReport(
            timestamp=datetime.utcnow().isoformat(),
            status=status,
            total_trades=len(trades),
            num_windows=len(windows),
            window_metrics=windows,
            improvement_rate=improvement_rate_val,
            regime_adaptation_score=regime_adaptation_score,
            notes=notes,
        )

    def _compute_regime_adaptation(self, windows: List[WindowMetrics]) -> float:
        """
        Fraction of regime transitions where RL reward improved.

        A "regime transition" is any pair of consecutive windows with
        different dominant regimes.
        """
        if len(windows) < 2:
            return 0.0

        transitions = 0
        improvements = 0
        for i in range(1, len(windows)):
            if windows[i].dominant_regime != windows[i - 1].dominant_regime:
                transitions += 1
                if windows[i].avg_rl_reward > windows[i - 1].avg_rl_reward:
                    improvements += 1

        return improvements / transitions if transitions > 0 else 1.0

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    def get_latest_window(self) -> Optional[WindowMetrics]:
        with self._lock:
            return self._windows[-1] if self._windows else None

    def get_trade_count(self) -> int:
        with self._lock:
            return len(self._trades)

    def get_window_count(self) -> int:
        with self._lock:
            return len(self._windows)

    def reset(self) -> None:
        """Clear all trade history and window metrics."""
        with self._lock:
            self._trades.clear()
            self._windows.clear()
        logger.info("RLValidationEngine reset")


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_engine_instance: Optional[RLValidationEngine] = None
_engine_lock = threading.Lock()


def get_rl_validation_engine() -> RLValidationEngine:
    """Return the global RLValidationEngine singleton."""
    global _engine_instance
    with _engine_lock:
        if _engine_instance is None:
            _engine_instance = RLValidationEngine()
        return _engine_instance
