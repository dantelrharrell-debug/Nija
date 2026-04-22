"""
NIJA Cycle Barrier Scheduler
=============================

Guarantees all 4 entry signals (RSI_9, RSI_14, MACD histogram, Market Regime)
are computed from the **same activation tick** (same candle / DataFrame snapshot)
before any entry gate runs.

Problem solved
--------------
Previously, ``check_long_entry`` / ``check_short_entry`` ran first (reading the
stale ``self.current_regime`` set in the *previous* cycle) and the fresh regime
was detected afterwards.  This one-cycle lag meant the RSI range boundaries used
for entry validation could differ from the regime actually present in the market
data, making activation non-deterministic.

Design
------
``CycleBarrierScheduler.capture()`` performs one atomic pass over the shared
``indicators`` dict and calls ``regime_detector.detect_regime()`` — all from the
same ``df`` instance — producing a frozen ``SignalSnapshot``.  The scheduler
also exposes the fresh regime so the caller can update ``self.current_regime``
*before* any entry-check method runs.

Usage (inside ``NIJAApexStrategyV71.check_entry_with_enhanced_scoring``)
-----------------------------------------------------------------------
::

    snap = self._cycle_barrier.capture(
        df=df,
        indicators=indicators,
        side=side,
        regime_detector=self.regime_detector if self.use_enhanced_scoring else None,
    )
    # Publish fresh regime so check_long/short_entry use THIS cycle's value
    if snap.regime is not None:
        self.current_regime = snap.regime

    # Now ALL four signal values come from the same df snapshot
    legacy_signal, legacy_score, legacy_reason = self.check_long_entry(df, indicators)

Author: NIJA Trading Systems
Version: 1.0
Date: April 2026
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional, Tuple

import pandas as pd

logger = logging.getLogger("nija.cycle_barrier")


# ---------------------------------------------------------------------------
# SignalSnapshot — immutable, tick-aligned capture of all 4 signals
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SignalSnapshot:
    """Immutable capture of the four entry signals at a single market tick.

    All field values are derived from the **same** DataFrame row index so
    comparisons between RSI_9, RSI_14, MACD histogram, and regime are always
    referencing the same market moment.

    Attributes
    ----------
    tick_id         : Deterministic 16-character hex identifier built from the
                      last candle's timestamp + close price + df length.
    candle_index    : Integer row index of the last candle in the DataFrame.
    close_price     : Close price at the last candle (integrity check).
    rsi9            : RSI(9)  value at the last candle.   [Signal 1]
    rsi14           : RSI(14) value at the last candle.   [Signal 2]
    macd_hist       : MACD histogram value at the last candle.  [Signal 3]
    regime          : Market regime string freshly detected from this df.  [Signal 4]
    side            : Entry side this snapshot was built for ('long'/'short').
    """

    tick_id: str
    candle_index: int
    close_price: float
    rsi9: float          # Signal 1
    rsi14: float         # Signal 2
    macd_hist: float     # Signal 3
    regime: Optional[str]  # Signal 4

    side: str

    # ------------------------------------------------------------------
    # Derived properties
    # ------------------------------------------------------------------

    def signals_aligned(self) -> bool:
        """Return True when all four signals agree for the configured side.

        Alignment criteria
        ------------------
        Long  : RSI_9 > 50 (short-term momentum bullish)
                RSI_14 <= 70 (not extreme overbought)
                MACD histogram > 0 (trend confirming)
                regime not bearish/crisis (regime check is advisory only
                — a None regime does not block)

        Short : RSI_9 < 50 (short-term momentum bearish)
                RSI_14 >= 30 (not extreme oversold)
                MACD histogram < 0 (trend confirming)
                regime not bullish/crisis

        Note: regime alignment is *advisory* here — the full regime gate is
        enforced by ``check_market_filter`` and the RegimeStrategyBridge
        upstream in ``analyze_market``.  Its inclusion in this check
        provides a fast early-out for clearly misaligned signals.
        """
        _bearish_regimes = {"bear", "bearish", "crisis", "defensive", "extreme_volatility"}
        _bullish_regimes = {"bull", "bullish", "trending_up"}

        regime_str = str(self.regime).lower() if self.regime else ""

        if self.side == "long":
            regime_ok = regime_str not in _bearish_regimes
            return (
                self.rsi9 > 50.0
                and self.rsi14 <= 70.0
                and self.macd_hist > 0.0
                and regime_ok
            )
        elif self.side == "short":
            regime_ok = regime_str not in _bullish_regimes
            return (
                self.rsi9 < 50.0
                and self.rsi14 >= 30.0
                and self.macd_hist < 0.0
                and regime_ok
            )
        return False

    def as_log_dict(self) -> Dict[str, Any]:
        """Return a compact dict suitable for structured logging."""
        return {
            "tick": self.tick_id,
            "idx": self.candle_index,
            "close": round(self.close_price, 6),
            "rsi9": round(self.rsi9, 2),
            "rsi14": round(self.rsi14, 2),
            "macd_hist": round(self.macd_hist, 8),
            "regime": self.regime,
            "side": self.side,
            "aligned": self.signals_aligned(),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_tick_id(df: pd.DataFrame) -> str:
    """Build a deterministic 16-hex-char tick identifier from the last candle.

    The identifier encodes: last candle label (index), close price, and df
    length.  If two consecutive ``capture()`` calls receive data frames that
    differ only in the *last* row they will produce different tick IDs, making
    stale-data re-use detectable.
    """
    last = df.iloc[-1]
    raw = f"{last.name}:{float(last['close']):.8f}:{len(df)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _safe_float(series: Any, fallback: float = 50.0) -> float:
    """Extract a scalar float from the last element of a Series (or return fallback)."""
    try:
        if series is None:
            return fallback
        val = series.iloc[-1]
        return float(val)
    except Exception:
        return fallback


# ---------------------------------------------------------------------------
# CycleBarrierScheduler
# ---------------------------------------------------------------------------

class CycleBarrierScheduler:
    """Production-grade scheduler that captures all 4 entry signals atomically.

    Each call to ``capture()`` is independent and stateless with respect to
    prior market data — the scheduler only caches the last tick_id for change
    detection logging (no trading decisions depend on it).

    Thread safety
    -------------
    ``capture()`` does not mutate shared state (it only writes to
    ``_last_tick_id`` which is non-critical metadata for logging).  Concurrent
    calls from different coroutines are safe as long as each call passes its
    own ``df`` / ``indicators`` references.
    """

    def __init__(self) -> None:
        self._last_tick_id: str = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def capture(
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        side: str,
        regime_detector: Any = None,
    ) -> SignalSnapshot:
        """Atomically extract all 4 signal values from the same DataFrame.

        Parameters
        ----------
        df              : OHLCV DataFrame.  The same instance must have been
                          used to compute ``indicators`` via
                          ``calculate_indicators(df)``.
        indicators      : Pre-computed indicator dict (output of
                          ``NIJAApexStrategyV71.calculate_indicators``).
        side            : Entry side — ``'long'`` or ``'short'``.
        regime_detector : ``RegimeDetector`` instance (optional).  When
                          supplied, regime is freshly detected from ``df``
                          rather than read from a potentially stale attribute.

        Returns
        -------
        ``SignalSnapshot`` with all 4 values derived from ``df`` at this tick.
        The ``regime`` field is ``None`` when ``regime_detector`` is not
        provided (callers should fall back to their cached ``current_regime``).
        """
        tick_id = _make_tick_id(df)
        candle_index = len(df) - 1

        close_price = _safe_float(df["close"] if "close" in df.columns else None, 0.0)

        # ── Signal 1: RSI_9 ──────────────────────────────────────────────
        rsi9 = _safe_float(indicators.get("rsi_9"), 50.0)

        # ── Signal 2: RSI_14 ─────────────────────────────────────────────
        rsi14 = _safe_float(indicators.get("rsi"), 50.0)

        # ── Signal 3: MACD histogram ─────────────────────────────────────
        macd_hist = _safe_float(indicators.get("histogram"), 0.0)

        # ── Signal 4: Market regime — freshly detected from THIS df ──────
        # This is the critical invariant: regime is read from the same df
        # instance used to compute rsi9 / rsi14 / macd_hist, not from a
        # stale ``self.current_regime`` set in a previous cycle.
        regime: Optional[str] = None
        if regime_detector is not None:
            try:
                detected, _ = regime_detector.detect_regime(df, indicators)
                if detected is not None:
                    regime = str(detected)
            except Exception as _rd_err:
                logger.debug(
                    "[CycleBarrier] regime detection failed for tick=%s: %s",
                    tick_id, _rd_err,
                )

        snapshot = SignalSnapshot(
            tick_id=tick_id,
            candle_index=candle_index,
            close_price=close_price,
            rsi9=rsi9,
            rsi14=rsi14,
            macd_hist=macd_hist,
            regime=regime,
            side=side,
        )

        # Log on new tick only (avoids per-symbol noise for repeated df)
        if tick_id != self._last_tick_id:
            logger.debug(
                "[CycleBarrier] tick=%s idx=%d | rsi9=%.1f rsi14=%.1f "
                "macd_hist=%.6f regime=%s side=%s aligned=%s",
                tick_id,
                candle_index,
                rsi9,
                rsi14,
                macd_hist,
                regime,
                side,
                snapshot.signals_aligned(),
            )
            self._last_tick_id = tick_id

        return snapshot


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_cycle_barrier_scheduler() -> CycleBarrierScheduler:
    """Return a new ``CycleBarrierScheduler`` instance.

    Each ``NIJAApexStrategyV71`` instance should hold its own scheduler so
    barrier captures are scoped to that strategy's symbol analysis and do
    not interfere with concurrent strategy instances.
    """
    return CycleBarrierScheduler()
