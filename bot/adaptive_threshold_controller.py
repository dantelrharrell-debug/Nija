"""
ADAPTIVE THRESHOLD CONTROLLER
==============================
Provides a safe, slow-moving adaptive controller for entry/exit thresholds.

This module is the FINAL SAFETY layer for threshold adaptation.  It enforces
three non-negotiable constraints that prevent the adaptive logic from
destabilising the bot during early or noisy periods:

1. **Minimum trade sample before adapting** (``MIN_TRADES_FOR_ADAPTATION = 10``)
   — no adjustments are made until at least 10 trades have been recorded,
   which stops early statistical noise from corrupting the threshold.

2. **Tighter adjustment range** (``max_adjustment = 3.0``)
   — the maximum cumulative adjustment from the base threshold is ±3.0 points,
   preventing runaway loosening or tightening.

3. **Slower adjustment speed** (``adjustment_step = 0.25``)
   — each adaptation cycle moves the threshold by at most 0.25 points,
   giving the system time to observe consequences before making further changes.

Architecture
------------
::

    AdaptiveThresholdController
    ├── record_outcome(is_win: bool)          — feed trade results
    ├── get_threshold(base_threshold: float)  — get current adjusted threshold
    ├── get_report()                          — diagnostic snapshot
    └── reset()                               — clear state (testing / hard reset)

Integration
-----------
Obtain the singleton via ``get_adaptive_threshold_controller()``.

    from bot.adaptive_threshold_controller import get_adaptive_threshold_controller

    atc = get_adaptive_threshold_controller()
    atc.record_outcome(is_win=True)
    threshold = atc.get_threshold(base_threshold=55.0)

Author: NIJA Trading Systems
Version: 1.0
Date: April 2026
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, Dict, List

logger = logging.getLogger("nija.adaptive_threshold_controller")

# ---------------------------------------------------------------------------
# Safety constants  (non-negotiable — do NOT relax without full review)
# ---------------------------------------------------------------------------

# Minimum number of completed trades required before any adaptation is applied.
# Below this count the controller always returns base_threshold unchanged.
MIN_TRADES_FOR_ADAPTATION: int = 10

# Maximum cumulative adjustment (positive or negative) from the base threshold.
# Prevents runaway loosening (threshold too low) or tightening (threshold too high).
_MAX_ADJUSTMENT: float = 3.0

# Size of each incremental step per adaptation cycle.
# Smaller = slower, more conservative convergence.
_ADJUSTMENT_STEP: float = 0.25

# Rolling window used to compute the recent win rate.
_WIN_RATE_WINDOW: int = 20

# Win-rate thresholds that trigger directional adjustments.
_WIN_RATE_LOWER: float = 0.40   # below this → tighten (raise threshold)
_WIN_RATE_UPPER: float = 0.60   # above this → loosen  (lower threshold)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ThresholdState:
    """Internal mutable state tracked by the controller."""
    cumulative_adjustment: float = 0.0   # net offset from base (clamped to ±max_adj)
    total_trades: int = 0                # all-time trade count
    wins: int = 0                        # all-time win count


@dataclass
class AdaptiveThresholdReport:
    """Diagnostic snapshot returned by get_report()."""
    base_threshold_example: float
    current_threshold: float
    cumulative_adjustment: float
    total_trades: int
    rolling_win_rate: float
    rolling_window_size: int
    adaptation_active: bool              # False when total_trades < MIN_TRADES_FOR_ADAPTATION
    max_adjustment: float
    adjustment_step: float
    min_trades_for_adaptation: int
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    reasons: List[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class AdaptiveThresholdController:
    """
    Safe, slow-moving adaptive threshold controller.

    Thread-safe singleton available via ``get_adaptive_threshold_controller()``.

    Parameters
    ----------
    max_adjustment:
        Maximum cumulative offset from the base threshold (both directions).
        Default: ``3.0``.
    adjustment_step:
        Maximum movement per adaptation cycle.
        Default: ``0.25``.
    win_rate_window:
        Number of recent trades used to compute the rolling win rate.
        Default: ``20``.
    """

    def __init__(
        self,
        max_adjustment: float = _MAX_ADJUSTMENT,
        adjustment_step: float = _ADJUSTMENT_STEP,
        win_rate_window: int = _WIN_RATE_WINDOW,
    ) -> None:
        self._max_adjustment = max_adjustment
        self._adjustment_step = adjustment_step

        self._state = ThresholdState()
        self._window: Deque[bool] = deque(maxlen=win_rate_window)
        self._lock = threading.Lock()

        logger.info(
            "🛡️  AdaptiveThresholdController initialised "
            "(max_adjustment=%.1f, adjustment_step=%.2f, "
            "min_trades_for_adaptation=%d, win_rate_window=%d)",
            self._max_adjustment,
            self._adjustment_step,
            MIN_TRADES_FOR_ADAPTATION,
            win_rate_window,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_outcome(self, is_win: bool) -> None:
        """
        Record the result of a completed trade.

        Must be called after every trade so the controller can track
        performance and decide whether to adjust the threshold.

        Parameters
        ----------
        is_win:
            ``True`` if the trade was profitable, ``False`` for a loss.
        """
        with self._lock:
            self._window.append(is_win)
            self._state.total_trades += 1
            if is_win:
                self._state.wins += 1

            # Attempt adaptation after recording the outcome
            self._adapt()

        logger.debug(
            "🛡️  ATC: recorded outcome is_win=%s | total_trades=%d | "
            "rolling_win_rate=%.1f%% | cumulative_adj=%.2f",
            is_win,
            self._state.total_trades,
            self._rolling_win_rate() * 100,
            self._state.cumulative_adjustment,
        )

    def get_threshold(self, base_threshold: float) -> float:
        """
        Return the current threshold for the given base value.

        If fewer than ``MIN_TRADES_FOR_ADAPTATION`` trades have been
        recorded the base threshold is returned unchanged — no noise
        from the early warm-up period is allowed to affect the system.

        Parameters
        ----------
        base_threshold:
            The reference threshold to adjust from.

        Returns
        -------
        float
            Adjusted threshold, always within
            ``[base_threshold - max_adjustment, base_threshold + max_adjustment]``.
        """
        with self._lock:
            total = self._state.total_trades
            adj = self._state.cumulative_adjustment

        # Safety gate: do not adapt until enough trades have been seen
        if total < MIN_TRADES_FOR_ADAPTATION:
            logger.debug(
                "🛡️  ATC: warm-up (%d/%d trades) — returning base_threshold=%.2f",
                total,
                MIN_TRADES_FOR_ADAPTATION,
                base_threshold,
            )
            return base_threshold

        adjusted = base_threshold + adj
        logger.debug(
            "🛡️  ATC: base=%.2f + adj=%.2f → threshold=%.2f",
            base_threshold, adj, adjusted,
        )
        return adjusted

    def get_report(self, base_threshold: float = 55.0) -> Dict:
        """
        Return a diagnostic snapshot of the controller's current state.

        Parameters
        ----------
        base_threshold:
            Example base value used to illustrate the current effective threshold.
        """
        with self._lock:
            total = self._state.total_trades
            adj = self._state.cumulative_adjustment
            wr = self._rolling_win_rate()
            win_rate_window_size = len(self._window)

        adaptation_active = total >= MIN_TRADES_FOR_ADAPTATION
        current_threshold = (base_threshold + adj) if adaptation_active else base_threshold

        report = AdaptiveThresholdReport(
            base_threshold_example=base_threshold,
            current_threshold=round(current_threshold, 4),
            cumulative_adjustment=round(adj, 4),
            total_trades=total,
            rolling_win_rate=round(wr, 4),
            rolling_window_size=win_rate_window_size,
            adaptation_active=adaptation_active,
            max_adjustment=self._max_adjustment,
            adjustment_step=self._adjustment_step,
            min_trades_for_adaptation=MIN_TRADES_FOR_ADAPTATION,
            reasons=self._describe_state(wr, adaptation_active),
        )
        return report.__dict__

    def reset(self) -> None:
        """
        Clear all recorded state and reset the controller to its initial values.

        Intended for hard resets and unit tests.  Use with caution in
        production — resetting wipes the warm-up history and the controller
        will not adapt again until ``MIN_TRADES_FOR_ADAPTATION`` new trades
        have been recorded.
        """
        with self._lock:
            self._state = ThresholdState()
            self._window.clear()
        logger.warning("🛡️  AdaptiveThresholdController: state reset to zero")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _rolling_win_rate(self) -> float:
        """Return the rolling win rate [0.0, 1.0].  Called under lock."""
        if not self._window:
            return 0.5   # neutral default before any data
        return sum(1 for w in self._window if w) / len(self._window)

    def _adapt(self) -> None:
        """
        Compute one adaptation step and update cumulative_adjustment.

        Called under ``self._lock`` immediately after recording an outcome.

        Logic
        -----
        * If not enough trades yet → do nothing (warm-up guard).
        * Win rate > upper band  → loosen by one step (lower threshold).
        * Win rate < lower band  → tighten by one step (raise threshold).
        * Otherwise              → no change.
        * Always clamp cumulative adjustment to [−max_adjustment, +max_adjustment].
        """
        if self._state.total_trades < MIN_TRADES_FOR_ADAPTATION:
            return   # warm-up: refuse to adapt until we have enough data

        wr = self._rolling_win_rate()
        delta = 0.0

        if wr > _WIN_RATE_UPPER:
            # Strong win rate → relax threshold slightly (negative offset)
            delta = -self._adjustment_step
        elif wr < _WIN_RATE_LOWER:
            # Weak win rate → tighten threshold slightly (positive offset)
            delta = +self._adjustment_step

        if delta == 0.0:
            return

        new_adj = self._state.cumulative_adjustment + delta
        # Clamp: never exceed ±max_adjustment from base
        self._state.cumulative_adjustment = max(
            -self._max_adjustment,
            min(self._max_adjustment, new_adj),
        )

    def _describe_state(
        self, win_rate: float, adaptation_active: bool
    ) -> List[str]:
        """Return a list of human-readable state descriptions."""
        reasons: List[str] = []
        if not adaptation_active:
            reasons.append(
                f"warm-up: {self._state.total_trades}/{MIN_TRADES_FOR_ADAPTATION} "
                "trades — threshold unchanged"
            )
            return reasons

        if win_rate > _WIN_RATE_UPPER:
            reasons.append(
                f"high_win_rate={win_rate*100:.1f}% > {_WIN_RATE_UPPER*100:.0f}% "
                "→ loosening threshold"
            )
        elif win_rate < _WIN_RATE_LOWER:
            reasons.append(
                f"low_win_rate={win_rate*100:.1f}% < {_WIN_RATE_LOWER*100:.0f}% "
                "→ tightening threshold"
            )
        else:
            reasons.append(
                f"win_rate={win_rate*100:.1f}% in target band "
                f"[{_WIN_RATE_LOWER*100:.0f}%–{_WIN_RATE_UPPER*100:.0f}%] "
                "→ no adjustment"
            )

        adj = self._state.cumulative_adjustment
        reasons.append(
            f"cumulative_adjustment={adj:+.2f} "
            f"(bounds: ±{self._max_adjustment:.1f})"
        )
        return reasons


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_atc_instance: AdaptiveThresholdController | None = None
_atc_lock = threading.Lock()


def get_adaptive_threshold_controller(
    max_adjustment: float = _MAX_ADJUSTMENT,
    adjustment_step: float = _ADJUSTMENT_STEP,
    win_rate_window: int = _WIN_RATE_WINDOW,
) -> AdaptiveThresholdController:
    """
    Return the process-wide singleton ``AdaptiveThresholdController``.

    Parameters are only applied on the first call; subsequent calls return
    the existing instance regardless of the arguments passed.

    Parameters
    ----------
    max_adjustment:
        Maximum cumulative offset from base threshold (both directions).
    adjustment_step:
        Maximum movement per adaptation cycle.
    win_rate_window:
        Rolling window size for win-rate computation.
    """
    global _atc_instance
    if _atc_instance is None:
        with _atc_lock:
            if _atc_instance is None:
                _atc_instance = AdaptiveThresholdController(
                    max_adjustment=max_adjustment,
                    adjustment_step=adjustment_step,
                    win_rate_window=win_rate_window,
                )
    return _atc_instance
