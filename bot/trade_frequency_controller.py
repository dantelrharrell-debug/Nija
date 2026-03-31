"""
NIJA Trade Frequency Controller
==================================
Ensures the strategy executes at least *X* trades per hour / per day by
dynamically relaxing or tightening the entry confidence gate.

When the actual trade rate falls below the configured targets the
controller emits a negative ``confidence_delta`` (makes entries easier).
When it is comfortably above target it backs off and lets the sniper
filter maintain quality.

Drought safeguard
-----------------
If **no trade has occurred in the last 2 hours** the controller enters
"drought mode" and returns a ``DroughtRelaxation`` that callers use to
automatically soften every filter layer by 10–20 %:

  * ADX requirement reduced by 3 points (e.g. 7 → 4)
  * Volume threshold halved (e.g. 5 % → 2.5 %)
  * Entry-score requirement reduced by 0.5 point
  * AI-gate score threshold reduced by 10 %
  * confidence_delta pinned to max loosening (-0.15)

Configuration via environment variables (all optional):

    MIN_TRADES_PER_HOUR=2.0       # default: 2.0
    MIN_TRADES_PER_DAY=12.0       # default: 12.0
    FREQ_LOOSEN_STEP=0.03         # per-cycle confidence nudge (subtracted)
    FREQ_TIGHTEN_STEP=0.02        # per-cycle confidence nudge (added)
    FREQ_MAX_DELTA=0.15           # max |confidence_delta| allowed
    DROUGHT_WINDOW_HOURS=2.0      # hours without a trade → drought mode
    DROUGHT_ADX_REDUCTION=3.0     # ADX points removed in drought
    DROUGHT_VOLUME_MULTIPLIER=0.5 # volume threshold multiplied in drought
    DROUGHT_SCORE_REDUCTION=0.5   # entry-score points removed in drought
    DROUGHT_GATE_PCT=0.10         # AI-gate score threshold reduced by this %

The controller is intentionally lightweight: it does NOT gate entries
directly.  Instead callers read ``get_confidence_delta()`` and
``get_drought_relaxation()`` and apply them before each filter check.
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

_DEFAULT_MIN_TRADES_PER_HOUR: float = 2.0
_DEFAULT_MIN_TRADES_PER_DAY: float = 12.0
_DEFAULT_LOOSEN_STEP: float = 0.03
_DEFAULT_TIGHTEN_STEP: float = 0.02
_DEFAULT_MAX_DELTA: float = 0.15

# Drought safeguard defaults
_DEFAULT_DROUGHT_WINDOW_SECS: float = 7200.0   # 2 hours
_DEFAULT_DROUGHT_ADX_REDUCTION: float = 3.0    # subtract 3 ADX points
_DEFAULT_DROUGHT_VOL_MULTIPLIER: float = 0.5   # halve volume threshold
_DEFAULT_DROUGHT_SCORE_REDUCTION: float = 0.5  # shave 0.5 from entry score
_DEFAULT_DROUGHT_GATE_PCT: float = 0.10        # lower AI-gate threshold by 10 %

# Rolling window sizes
_HOUR_WINDOW_SECS: float = 3600.0
_DAY_WINDOW_SECS: float = 86400.0

# Balance-based threshold tightening
TARGET_BALANCE: float = 100.0       # tighten AI entry threshold once balance hits this
TIGHTENED_ENTRY_SCORE: float = 5.0  # restored threshold when TARGET_BALANCE is reached


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


@dataclass
class DroughtRelaxation:
    """
    Filter relaxation applied when no trade has occurred for ``drought_window`` seconds.

    Callers should apply each field to the relevant threshold:
      * adx_reduction       — subtract from min_adx before the ADX gate
      * volume_multiplier   — multiply the volume_threshold (0.5 = halve it)
      * score_reduction     — subtract from the required entry score
      * gate_pct_reduction  — multiply AI-gate score thresholds by (1 - gate_pct_reduction)
      * confidence_delta    — add to signal confidence (negative = easier to enter)
    """
    active: bool
    secs_since_last_trade: float  # 0.0 if a trade was recorded today
    adx_reduction: float          # points to subtract from min_adx
    volume_multiplier: float      # fraction to multiply volume_threshold by
    score_reduction: float        # points to subtract from min entry score
    gate_pct_reduction: float     # fractional reduction of AI-gate thresholds
    confidence_delta: float       # additional confidence loosening
    reason: str


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

        # Drought safeguard parameters
        self._drought_window = _env("DROUGHT_WINDOW_HOURS", 2.0, None) * 3600.0
        self._drought_adx_reduction = _env(
            "DROUGHT_ADX_REDUCTION", _DEFAULT_DROUGHT_ADX_REDUCTION, None
        )
        self._drought_vol_multiplier = _env(
            "DROUGHT_VOLUME_MULTIPLIER", _DEFAULT_DROUGHT_VOL_MULTIPLIER, None
        )
        self._drought_score_reduction = _env(
            "DROUGHT_SCORE_REDUCTION", _DEFAULT_DROUGHT_SCORE_REDUCTION, None
        )
        self._drought_gate_pct = _env(
            "DROUGHT_GATE_PCT", _DEFAULT_DROUGHT_GATE_PCT, None
        )

        # Rolling timestamp windows
        self._lock = threading.Lock()
        self._trade_timestamps: Deque[float] = deque()
        self._confidence_delta: float = 0.0
        self._last_update_ts: float = 0.0
        # _init_ts anchors the drought clock: drought triggers only after the bot
        # has been running for drought_window seconds WITHOUT a recorded trade.
        self._init_ts: float = time.time()
        # Timestamp of most-recent recorded trade (0.0 = none yet)
        self._last_trade_ts: float = 0.0

        logger.info(
            "📊 TradeFrequencyController started — "
            "target: %.1f/hr, %.1f/day | step loosen=%.3f tighten=%.3f cap=±%.3f | "
            "drought window=%.0fh relax ADX-%.1f vol×%.2f score-%.1f gate-%.0f%%",
            self._min_per_hour,
            self._min_per_day,
            self._loosen_step,
            self._tighten_step,
            self._max_delta,
            self._drought_window / 3600.0,
            self._drought_adx_reduction,
            self._drought_vol_multiplier,
            self._drought_score_reduction,
            self._drought_gate_pct * 100,
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
            self._last_trade_ts = now
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

    def get_drought_relaxation(self) -> DroughtRelaxation:
        """
        Return filter relaxation parameters for the 2-hour drought safeguard.

        When no trade has been recorded for ``drought_window`` seconds this
        returns an *active* ``DroughtRelaxation`` with non-zero relaxation
        values.  Callers should apply those values to every threshold they
        own before evaluating a new entry:

            relax = controller.get_drought_relaxation()
            if relax.active:
                effective_adx = max(0, min_adx - relax.adx_reduction)
                effective_vol = volume_threshold * relax.volume_multiplier
                effective_score = max(1.0, min_score - relax.score_reduction)

        When no drought is detected all numeric fields are 0 / 1.0 (no-op).
        """
        now = time.time()
        with self._lock:
            if self._last_trade_ts > 0:
                # A trade has been recorded — measure from the last trade
                secs_since = now - self._last_trade_ts
            else:
                # No trade yet — measure from bot startup; drought only triggers
                # after the bot has been running for a full drought_window period.
                secs_since = now - self._init_ts
            in_drought = secs_since >= self._drought_window

        if not in_drought:
            return DroughtRelaxation(
                active=False,
                secs_since_last_trade=secs_since,
                adx_reduction=0.0,
                volume_multiplier=1.0,
                score_reduction=0.0,
                gate_pct_reduction=0.0,
                confidence_delta=0.0,
                reason="no drought — filters unchanged",
            )

        hours = secs_since / 3600.0
        logger.info(
            "⏳ DROUGHT SAFEGUARD active — %.1fh since last trade; "
            "relaxing filters: ADX-%.1f vol×%.2f score-%.1f gate-%.0f%%",
            hours,
            self._drought_adx_reduction,
            self._drought_vol_multiplier,
            self._drought_score_reduction,
            self._drought_gate_pct * 100,
        )
        return DroughtRelaxation(
            active=True,
            secs_since_last_trade=secs_since,
            adx_reduction=self._drought_adx_reduction,
            volume_multiplier=self._drought_vol_multiplier,
            score_reduction=self._drought_score_reduction,
            gate_pct_reduction=self._drought_gate_pct,
            confidence_delta=-self._max_delta,   # pin to maximum loosening
            reason=(
                f"drought {hours:.1f}h > {self._drought_window/3600:.0f}h limit — "
                f"ADX-{self._drought_adx_reduction:.0f} "
                f"vol×{self._drought_vol_multiplier:.2f} "
                f"score-{self._drought_score_reduction:.1f} "
                f"gate-{self._drought_gate_pct*100:.0f}%"
            ),
        )

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
        d = self.get_drought_relaxation()
        return {
            "confidence_delta": round(s.confidence_delta, 4),
            "trades_last_hour": s.trades_last_hour,
            "trades_last_day": s.trades_last_day,
            "target_per_hour": s.target_per_hour,
            "target_per_day": s.target_per_day,
            "mode": s.mode,
            "drought_active": d.active,
            "drought_secs_since_trade": round(d.secs_since_last_trade, 1),
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

    def check_balance_and_adjust_threshold(self, current_balance: float) -> None:
        """
        Tighten the AI entry threshold once the account balance reaches TARGET_BALANCE.

        Call this at the end of every trade or at every scan loop.
        When ``current_balance`` is at or above ``TARGET_BALANCE`` the
        ``BASE_ENTRY_SCORE_THRESHOLD`` in ``ai_entry_gate`` is restored to
        ``TIGHTENED_ENTRY_SCORE``, reversing the temporary loosening.
        The threshold is only updated (and the log emitted) on the first call
        that crosses the target, preventing repeated writes and log spam.
        """
        if current_balance >= TARGET_BALANCE:
            try:
                try:
                    import bot.ai_entry_gate as _ai_gate
                except ImportError:
                    import ai_entry_gate as _ai_gate  # type: ignore[no-redef]
                if _ai_gate.BASE_ENTRY_SCORE_THRESHOLD != TIGHTENED_ENTRY_SCORE:
                    _ai_gate.BASE_ENTRY_SCORE_THRESHOLD = TIGHTENED_ENTRY_SCORE
                    logger.info(
                        "💰 Balance $%.2f reached target $%.1f — "
                        "tightening AI entry threshold to %.1f",
                        current_balance, TARGET_BALANCE, TIGHTENED_ENTRY_SCORE,
                    )
            except Exception as exc:
                logger.warning("check_balance_and_adjust_threshold error: %s", exc)


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
