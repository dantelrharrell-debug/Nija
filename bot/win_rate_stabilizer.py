"""
NIJA Win Rate Stabilizer
========================

Tracks the last N trade outcomes (default: 20) and dynamically adjusts three
levers that control how aggressively the strategy trades:

    1. Entry confidence delta  — shifts the sniper-filter gate up or down
    2. Take-profit multiplier  — scales TP *distance* from entry (not raw price)
    3. Stop-loss multiplier    — scales SL *distance* from entry (not raw price)

Performance bands
-----------------
    ┌─────────┬──────────┬──────┬──────┬───────────────┐
    │ Band    │ Win Rate │ TP×  │ SL×  │ Conf delta    │
    ├─────────┼──────────┼──────┼──────┼───────────────┤
    │ HOT     │ ≥ 65 %   │ 1.25 │ 1.00 │ −0.05 (looser)│
    │ GOOD    │ 55–65 %  │ 1.10 │ 1.00 │  0.00         │
    │ NEUTRAL │ 45–55 %  │ 1.00 │ 1.00 │  0.00         │
    │ WEAK    │ 35–45 %  │ 0.85 │ 0.90 │ +0.05 (tighter│
    │ COLD    │ < 35 %   │ 0.70 │ 0.80 │ +0.10 (tighter│
    └─────────┴──────────┴──────┴──────┴───────────────┘

Multipliers are applied to the *distance* between entry price and TP/SL:
    long  TP: new_tp = entry + (raw_tp − entry) × tp_mult
    long  SL: new_sl = entry − (entry − raw_sl) × sl_mult   (< 1 = closer)
    short TP: new_tp = entry − (entry − raw_tp) × tp_mult
    short SL: new_sl = entry + (raw_sl − entry) × sl_mult

Minimum sample guard
--------------------
No adjustments are applied until ``min_sample`` trades have been recorded
(default: 10).  Before that threshold is reached every call to
``get_adjustments()`` returns the neutral baseline so the system behaves
as before until it has enough data.

All parameters are configurable via environment variables:
    WRS_WINDOW        — rolling window size (default: 20)
    WRS_MIN_SAMPLE    — minimum trades before activation (default: 10)
    WRS_HOT_THRESH    — win-rate floor for HOT band (default: 0.65)
    WRS_GOOD_THRESH   — win-rate floor for GOOD band (default: 0.55)
    WRS_WEAK_THRESH   — win-rate floor for WEAK band (default: 0.35)

Thread safety
-------------
All state mutations are protected by a ``threading.Lock`` so the stabilizer
is safe to call from the main trading loop and from any background thread
that records trade outcomes.

Usage
-----
::

    from bot.win_rate_stabilizer import get_win_rate_stabilizer

    wrs = get_win_rate_stabilizer()

    # Record an outcome after each closed trade
    wrs.record(is_win=True)

    # Read current adjustments before opening a new position
    adj = wrs.get_adjustments()
    new_conf = current_confidence + adj.entry_confidence_delta
    new_tp   = entry + (raw_tp - entry) * adj.tp_multiplier
"""

from __future__ import annotations

import logging
import os
import threading
from collections import deque
from dataclasses import dataclass
from enum import Enum
from typing import Deque, Optional

logger = logging.getLogger("nija.win_rate_stabilizer")

# ---------------------------------------------------------------------------
# Configuration (env-overridable)
# ---------------------------------------------------------------------------

def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


_WINDOW:      int   = _env_int("WRS_WINDOW",      20)
_MIN_SAMPLE:  int   = _env_int("WRS_MIN_SAMPLE",  10)
_HOT_THRESH:  float = _env_float("WRS_HOT_THRESH",  0.65)
_GOOD_THRESH: float = _env_float("WRS_GOOD_THRESH", 0.55)
_WEAK_THRESH: float = _env_float("WRS_WEAK_THRESH", 0.35)
# COLD band is everything below _WEAK_THRESH


# ---------------------------------------------------------------------------
# Band enum
# ---------------------------------------------------------------------------

class WRSBand(str, Enum):
    HOT     = "HOT"      # ≥ 65% — strategy is on a hot streak; extend targets
    GOOD    = "GOOD"     # 55–65% — above baseline; mild TP boost
    NEUTRAL = "NEUTRAL"  # 45–55% — baseline; no change
    WEAK    = "WEAK"     # 35–45% — below par; tighten SL, reduce TP
    COLD    = "COLD"     # < 35%  — protect capital aggressively


# ---------------------------------------------------------------------------
# Adjustment dataclass
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class WRSAdjustments:
    """
    Resolved adjustments for the current win-rate band.

    Attributes:
        band:                   Current performance band.
        win_rate:               Rolling win rate (0.0–1.0).
        sample_size:            Number of trades in the window.
        tp_multiplier:          Multiply TP distance from entry by this value.
        sl_multiplier:          Multiply SL distance from entry by this value.
        entry_confidence_delta: Add to sniper-filter confidence score.
                                Negative → easier to enter (loosen gate).
                                Positive → harder to enter (tighten gate).
        active:                 False when sample_size < min_sample (no-op mode).
    """
    band: WRSBand
    win_rate: float
    sample_size: int
    tp_multiplier: float
    sl_multiplier: float
    entry_confidence_delta: float
    active: bool


# Neutral / no-op baseline returned when not enough data yet.
_NEUTRAL = WRSAdjustments(
    band=WRSBand.NEUTRAL,
    win_rate=0.5,
    sample_size=0,
    tp_multiplier=1.00,
    sl_multiplier=1.00,
    entry_confidence_delta=0.00,
    active=False,
)

# Per-band config table (win_rate / sample_size filled in at runtime)
_BAND_TEMPLATES: dict[WRSBand, tuple[float, float, float]] = {
    #            tp_mult  sl_mult  conf_delta
    WRSBand.HOT:     (1.25,   1.00,  -0.05),
    WRSBand.GOOD:    (1.10,   1.00,   0.00),
    WRSBand.NEUTRAL: (1.00,   1.00,   0.00),
    WRSBand.WEAK:    (0.85,   0.90,  +0.05),
    WRSBand.COLD:    (0.70,   0.80,  +0.10),
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _classify(win_rate: float) -> WRSBand:
    """Proper 5-band classifier."""
    if win_rate >= _HOT_THRESH:
        return WRSBand.HOT
    # NEUTRAL floor sits midway between GOOD and WEAK (45%)
    _neutral_floor = (_GOOD_THRESH + _WEAK_THRESH) / 2.0  # default: 0.45
    if win_rate >= _GOOD_THRESH:
        return WRSBand.GOOD
    if win_rate >= _neutral_floor:
        return WRSBand.NEUTRAL
    if win_rate >= _WEAK_THRESH:
        return WRSBand.WEAK
    return WRSBand.COLD


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

class WinRateStabilizer:
    """
    Thread-safe rolling win-rate tracker with dynamic adjustment engine.

    Designed as a long-lived singleton — record every trade outcome and
    call ``get_adjustments()`` before each new entry to receive the current
    TP/SL/confidence parameters.
    """

    def __init__(
        self,
        window: int = _WINDOW,
        min_sample: int = _MIN_SAMPLE,
    ) -> None:
        self._window = window
        self._min_sample = min_sample
        self._outcomes: Deque[bool] = deque(maxlen=window)
        self._lock = threading.Lock()
        self._last_band: Optional[WRSBand] = None

        logger.info(
            "📊 WinRateStabilizer initialised — window=%d min_sample=%d "
            "bands: HOT≥%.0f%% GOOD≥%.0f%% NEUTRAL≥%.0f%% WEAK≥%.0f%%",
            window, min_sample,
            _HOT_THRESH * 100,
            _GOOD_THRESH * 100,
            (_GOOD_THRESH + _WEAK_THRESH) / 2.0 * 100,
            _WEAK_THRESH * 100,
        )

    # ── Recording ────────────────────────────────────────────────────────────

    def record(self, is_win: bool) -> None:
        """
        Record a completed trade outcome.

        Args:
            is_win: True if the trade was profitable, False for a loss.
        """
        with self._lock:
            self._outcomes.append(is_win)
            n = len(self._outcomes)
            wins = sum(self._outcomes)
            wr = wins / n if n else 0.0
            band = _classify(wr) if n >= self._min_sample else WRSBand.NEUTRAL

            # Log band transitions at INFO level; routine records at DEBUG
            if band != self._last_band and n >= self._min_sample:
                logger.info(
                    "📊 WRS band transition → %s  (wr=%.0f%% %d/%d trades)",
                    band.value, wr * 100, wins, n,
                )
                self._last_band = band
            else:
                logger.debug(
                    "📊 WRS record: %s | wr=%.0f%% (%d/%d) band=%s",
                    "WIN ✅" if is_win else "LOSS ❌",
                    wr * 100, wins, n,
                    band.value if n >= self._min_sample else f'WARMING({n}/{self._min_sample})',
                )

    # ── Querying ─────────────────────────────────────────────────────────────

    def get_adjustments(self) -> WRSAdjustments:
        """
        Return the current TP/SL/confidence adjustments.

        Returns the neutral no-op baseline until ``min_sample`` trades have
        been recorded so early behaviour is unchanged.
        """
        with self._lock:
            n = len(self._outcomes)
            if n < self._min_sample:
                return _NEUTRAL
            wr = sum(self._outcomes) / n
            band = _classify(wr)
            tp_mult, sl_mult, conf_delta = _BAND_TEMPLATES[band]
            return WRSAdjustments(
                band=band,
                win_rate=wr,
                sample_size=n,
                tp_multiplier=tp_mult,
                sl_multiplier=sl_mult,
                entry_confidence_delta=conf_delta,
                active=True,
            )

    def get_win_rate(self) -> float:
        """Return the current rolling win rate (0.0–1.0), or 0.5 when warming up."""
        with self._lock:
            n = len(self._outcomes)
            return sum(self._outcomes) / n if n else 0.5

    def get_band(self) -> WRSBand:
        """Return the current performance band."""
        with self._lock:
            n = len(self._outcomes)
            if n < self._min_sample:
                return WRSBand.NEUTRAL
            return _classify(sum(self._outcomes) / n)

    def get_sample_size(self) -> int:
        """Return the number of trades currently in the rolling window."""
        with self._lock:
            return len(self._outcomes)

    def is_active(self) -> bool:
        """Return True once min_sample trades have been recorded."""
        with self._lock:
            return len(self._outcomes) >= self._min_sample

    def get_report(self) -> dict:
        """Return a JSON-serialisable summary for logging / API endpoints."""
        adj = self.get_adjustments()
        return {
            "active": adj.active,
            "band": adj.band.value,
            "win_rate_pct": round(adj.win_rate * 100, 1),
            "sample_size": adj.sample_size,
            "min_sample": self._min_sample,
            "window": self._window,
            "tp_multiplier": adj.tp_multiplier,
            "sl_multiplier": adj.sl_multiplier,
            "entry_confidence_delta": adj.entry_confidence_delta,
            "thresholds": {
                "hot": _HOT_THRESH,
                "good": _GOOD_THRESH,
                "neutral_floor": round((_GOOD_THRESH + _WEAK_THRESH) / 2.0, 2),
                "weak": _WEAK_THRESH,
            },
        }


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_singleton: Optional[WinRateStabilizer] = None
_singleton_lock = threading.Lock()


def get_win_rate_stabilizer() -> WinRateStabilizer:
    """Return (or create) the module-level singleton ``WinRateStabilizer``."""
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = WinRateStabilizer()
        return _singleton
