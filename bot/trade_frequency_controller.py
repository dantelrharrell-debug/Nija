"""
NIJA Trade Frequency Controller
==================================
Ensures the strategy executes at least *X* trades per hour / per day by
dynamically relaxing or tightening the entry confidence gate.

When the actual trade rate falls below the configured targets the
controller emits a negative ``confidence_delta`` (makes entries easier).
When it is comfortably above target it backs off and lets the sniper
filter maintain quality.

Configuration via environment variables (all optional):

    MIN_TRADES_PER_HOUR=1.0   # default: 0.5
    MIN_TRADES_PER_DAY=6.0    # default: 5.0
    FREQ_LOOSEN_STEP=0.03     # per-cycle confidence nudge downward
    FREQ_TIGHTEN_STEP=0.02    # per-cycle confidence nudge upward
    FREQ_MAX_DELTA=0.10       # max |confidence_delta| allowed

The controller is intentionally lightweight: it does NOT gate entries
directly.  Instead callers read ``get_confidence_delta()`` and add it to
their confidence score before the sniper filter.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Deque, Optional

logger = logging.getLogger("nija.trade_frequency_controller")

# ---------------------------------------------------------------------------
# Constants (can be overridden by env vars)
# ---------------------------------------------------------------------------

_DEFAULT_MIN_TRADES_PER_HOUR: float = 0.5
_DEFAULT_MIN_TRADES_PER_DAY: float = 5.0
_DEFAULT_LOOSEN_STEP: float = 0.03
_DEFAULT_TIGHTEN_STEP: float = 0.02
_DEFAULT_MAX_DELTA: float = 0.10

# Rolling window sizes
_HOUR_WINDOW_SECS: float = 3600.0
_DAY_WINDOW_SECS: float = 86400.0


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class FrequencyStatus:
    """Snapshot of current frequency state returned to callers."""
    confidence_delta: float       # Add this to signal confidence
    trades_last_hour: int
    trades_last_day: int
    target_per_hour: float
    target_per_day: float
    below_hourly_target: bool
    below_daily_target: bool
    mode: str                     # "ON_TARGET" | "BELOW_HOURLY" | "BELOW_DAILY" | "WELL_ABOVE"


# ---------------------------------------------------------------------------
# Controller class
# ---------------------------------------------------------------------------

class TradeFrequencyController:
    """
    Thread-safe trade-frequency targeting controller.

    Call ``record_trade()`` after every completed or entered trade.
    Call ``get_confidence_delta()`` in the signal-scanning loop to obtain
    the current confidence nudge.
    """

    def __init__(
        self,
        min_trades_per_hour: Optional[float] = None,
        min_trades_per_day: Optional[float] = None,
        loosen_step: Optional[float] = None,
        tighten_step: Optional[float] = None,
        max_delta: Optional[float] = None,
    ) -> None:
        def _env(name: str, default: float, provided: Optional[float]) -> float:
            if provided is not None:
                return provided
            raw = os.environ.get(name)
            if raw is not None:
                try:
                    return float(raw)
                except ValueError:
                    pass
            return default

        self._min_per_hour = _env("MIN_TRADES_PER_HOUR", _DEFAULT_MIN_TRADES_PER_HOUR, min_trades_per_hour)
        self._min_per_day = _env("MIN_TRADES_PER_DAY", _DEFAULT_MIN_TRADES_PER_DAY, min_trades_per_day)
        self._loosen_step = _env("FREQ_LOOSEN_STEP", _DEFAULT_LOOSEN_STEP, loosen_step)
        self._tighten_step = _env("FREQ_TIGHTEN_STEP", _DEFAULT_TIGHTEN_STEP, tighten_step)
        self._max_delta = _env("FREQ_MAX_DELTA", _DEFAULT_MAX_DELTA, max_delta)

        # Rolling timestamp windows
        self._lock = threading.Lock()
        self._trade_timestamps: Deque[float] = deque()
        self._confidence_delta: float = 0.0
        self._last_update_ts: float = 0.0

        logger.info(
            "📊 TradeFrequencyController started — "
            "target: %.1f/hr, %.1f/day | step loosen=%.3f tighten=%.3f cap=±%.3f",
            self._min_per_hour,
            self._min_per_day,
            self._loosen_step,
            self._tighten_step,
            self._max_delta,
        )

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _purge_old_timestamps(self, now: float) -> None:
        """Remove timestamps older than 24 h from the rolling window."""
        cutoff = now - _DAY_WINDOW_SECS
        while self._trade_timestamps and self._trade_timestamps[0] < cutoff:
            self._trade_timestamps.popleft()

    def _count_window(self, now: float, window_secs: float) -> int:
        cutoff = now - window_secs
        return sum(1 for ts in self._trade_timestamps if ts >= cutoff)

    def _update_delta(self, now: float) -> None:
        """Recalculate confidence_delta based on current frequency."""
        hourly = self._count_window(now, _HOUR_WINDOW_SECS)
        daily = self._count_window(now, _DAY_WINDOW_SECS)

        below_hourly = hourly < self._min_per_hour
        below_daily = daily < self._min_per_day
        # Well above target = both hourly and daily clearly exceeded
        well_above = (
            hourly >= self._min_per_hour * 1.5
            and daily >= self._min_per_day * 1.5
        )

        if below_hourly or below_daily:
            # Loosen: nudge confidence gate downward
            self._confidence_delta = max(
                -self._max_delta,
                self._confidence_delta - self._loosen_step,
            )
        elif well_above:
            # Above target: restore delta toward zero
            self._confidence_delta = min(
                0.0,
                self._confidence_delta + self._tighten_step,
            )
        # else: on target — leave delta unchanged

        self._last_update_ts = now

    # ── Public API ────────────────────────────────────────────────────────────

    def record_trade(self) -> None:
        """
        Register that a trade was executed (entry placed).
        Call once per trade entry, not per close.
        """
        now = time.time()
        with self._lock:
            self._trade_timestamps.append(now)
            self._purge_old_timestamps(now)
            self._update_delta(now)

    def get_confidence_delta(self) -> float:
        """
        Return the current confidence adjustment delta.

        This value is negative when the strategy is below the frequency
        target (easier to enter) and zero or slightly positive when above.

        Callers should add this to the raw signal confidence:
            effective_confidence = raw_confidence + controller.get_confidence_delta()
        """
        now = time.time()
        with self._lock:
            # Re-evaluate at most once per minute to avoid excessive logging
            if now - self._last_update_ts > 60.0:
                self._purge_old_timestamps(now)
                self._update_delta(now)
            return self._confidence_delta

    def get_status(self) -> FrequencyStatus:
        """Return a full status snapshot (for logging / analytics)."""
        now = time.time()
        with self._lock:
            self._purge_old_timestamps(now)
            self._update_delta(now)
            hourly = self._count_window(now, _HOUR_WINDOW_SECS)
            daily = self._count_window(now, _DAY_WINDOW_SECS)
            below_hourly = hourly < self._min_per_hour
            below_daily = daily < self._min_per_day
            well_above = (
                hourly >= self._min_per_hour * 1.5
                and daily >= self._min_per_day * 1.5
            )
            if well_above:
                mode = "WELL_ABOVE"
            elif below_hourly and below_daily:
                mode = "BELOW_DAILY"
            elif below_hourly:
                mode = "BELOW_HOURLY"
            else:
                mode = "ON_TARGET"

            return FrequencyStatus(
                confidence_delta=self._confidence_delta,
                trades_last_hour=hourly,
                trades_last_day=daily,
                target_per_hour=self._min_per_hour,
                target_per_day=self._min_per_day,
                below_hourly_target=below_hourly,
                below_daily_target=below_daily,
                mode=mode,
            )

    def get_report(self) -> dict:
        """Return a JSON-serialisable summary for logging / API endpoints."""
        s = self.get_status()
        return {
            "confidence_delta": round(s.confidence_delta, 4),
            "trades_last_hour": s.trades_last_hour,
            "trades_last_day": s.trades_last_day,
            "target_per_hour": s.target_per_hour,
            "target_per_day": s.target_per_day,
            "mode": s.mode,
        }

    def update_targets(self, min_per_hour: float, min_per_day: float) -> None:
        """
        Hot-update frequency targets at runtime (e.g. when aggression mode changes).
        """
        with self._lock:
            self._min_per_hour = min_per_hour
            self._min_per_day = min_per_day
        logger.info(
            "📊 TradeFrequencyController targets updated → %.1f/hr, %.1f/day",
            min_per_hour, min_per_day,
        )

    @property
    def min_trades_per_hour(self) -> float:
        """Current minimum trades-per-hour target."""
        with self._lock:
            return self._min_per_hour

    @property
    def min_trades_per_day(self) -> float:
        """Current minimum trades-per-day target."""
        with self._lock:
            return self._min_per_day


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_controller_instance: Optional[TradeFrequencyController] = None
_controller_lock = threading.Lock()


def get_trade_frequency_controller(
    min_trades_per_hour: Optional[float] = None,
    min_trades_per_day: Optional[float] = None,
) -> TradeFrequencyController:
    """
    Return the thread-safe singleton TradeFrequencyController.

    Parameters are only used on the first (initialising) call.
    """
    global _controller_instance
    if _controller_instance is None:
        with _controller_lock:
            if _controller_instance is None:
                _controller_instance = TradeFrequencyController(
                    min_trades_per_hour=min_trades_per_hour,
                    min_trades_per_day=min_trades_per_day,
                )
    return _controller_instance
