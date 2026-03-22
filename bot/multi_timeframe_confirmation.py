"""
NIJA Phase 3 — Multi-Timeframe Confirmation AI
================================================

Validates trade signals by requiring agreement across multiple timeframes
before authorising an entry.  A signal on the base (fastest) timeframe is
only confirmed when higher timeframes are aligned in the same direction.

This module provides a lightweight, pure-Python engine that resamples an
OHLCV DataFrame into multiple timeframes on the fly and evaluates several
technical confirmation signals:

* RSI direction & level
* EMA trend alignment (EMA9 / EMA21)
* Momentum (price above / below mid-point of recent range)

Confirmation scoring
--------------------
Each timeframe produces a directional vote: **+1** (bullish), **-1** (bearish),
or **0** (neutral).  A signal is confirmed when:

    confirmed_votes / total_votes  ≥  min_agreement_ratio  (default 0.70)

This means ≥70 % of the checked timeframes agree on the direction.

Usage
-----
::

    import pandas as pd
    from bot.multi_timeframe_confirmation import get_mtf_confirmation

    mtf = get_mtf_confirmation()

    # df must have a DatetimeIndex and columns: open, high, low, close, volume
    result = mtf.confirm(df=df, signal_side="long")

    if result.confirmed:
        execute_entry()
    else:
        logger.info("MTF confirmation failed: %s", result.summary)

Author: NIJA Trading Systems
Version: 1.0 — Phase 3
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import pandas as pd

logger = logging.getLogger("nija.multi_timeframe_confirmation")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class MTFConfig:
    """Configuration for the multi-timeframe confirmation engine."""

    # Timeframe resample rules for pandas (base candles → higher TF candles)
    # The first entry is the fastest / most granular TF to include.
    timeframes: List[str] = field(default_factory=lambda: ["1min", "5min", "15min"])

    # RSI periods
    rsi_period: int = 14

    # EMA periods for trend alignment check
    ema_fast: int = 9
    ema_slow: int = 21

    # Min fraction of TFs that must agree for a confirmed signal
    min_agreement_ratio: float = 0.70

    # RSI thresholds
    rsi_oversold: float = 40.0
    rsi_overbought: float = 60.0

    # Minimum number of bars required in the base DataFrame
    min_bars: int = 50


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class MTFResult:
    confirmed: bool
    direction: str              # "bullish", "bearish", or "neutral"
    agreement_ratio: float      # fraction of TFs that agreed
    votes: Dict[str, int]       # TF → vote (+1 / -1 / 0)
    allow_long: bool
    allow_short: bool
    summary: str


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class MultiTimeframeConfirmation:
    """
    Multi-timeframe signal confirmation engine.

    Resamples a base-timeframe DataFrame into higher timeframes and evaluates
    each for directional agreement.  Thread-safe (stateless computation).
    """

    def __init__(self, config: Optional[MTFConfig] = None) -> None:
        self._cfg = config or MTFConfig()
        self._lock = threading.Lock()

        logger.info(
            "✅ MultiTimeframeConfirmation initialised — TFs: %s  "
            "min_agreement=%.0f%%",
            ", ".join(self._cfg.timeframes),
            self._cfg.min_agreement_ratio * 100,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def confirm(
        self,
        df: pd.DataFrame,
        signal_side: str,
    ) -> MTFResult:
        """
        Evaluate multi-timeframe agreement for the proposed trade side.

        Parameters
        ----------
        df:
            OHLCV DataFrame with a ``DatetimeIndex`` and columns
            ``open``, ``high``, ``low``, ``close``, ``volume``.
            Rows should be in **ascending** chronological order.
        signal_side:
            ``"long"`` or ``"short"`` — the proposed entry direction.

        Returns
        -------
        MTFResult
        """
        if df is None or len(df) < self._cfg.min_bars:
            return MTFResult(
                confirmed=False,
                direction="neutral",
                agreement_ratio=0.0,
                votes={},
                allow_long=False,
                allow_short=False,
                summary=(
                    f"Insufficient data ({len(df) if df is not None else 0} bars, "
                    f"need {self._cfg.min_bars})"
                ),
            )

        side = signal_side.lower()
        votes: Dict[str, int] = {}

        for tf in self._cfg.timeframes:
            try:
                tf_df = self._resample(df, tf)
                if tf_df is None or len(tf_df) < 20:
                    continue
                vote = self._evaluate_timeframe(tf_df)
                votes[tf] = vote
            except Exception as exc:
                logger.debug("MTF: TF %s evaluation error: %s", tf, exc)

        if not votes:
            return MTFResult(
                confirmed=False,
                direction="neutral",
                agreement_ratio=0.0,
                votes={},
                allow_long=False,
                allow_short=False,
                summary="No timeframes could be evaluated",
            )

        bullish_votes = sum(1 for v in votes.values() if v == 1)
        bearish_votes = sum(1 for v in votes.values() if v == -1)
        total = len(votes)

        bull_ratio = bullish_votes / total
        bear_ratio = bearish_votes / total
        min_ratio = self._cfg.min_agreement_ratio

        if bull_ratio >= min_ratio:
            direction = "bullish"
            agreement_ratio = bull_ratio
        elif bear_ratio >= min_ratio:
            direction = "bearish"
            agreement_ratio = bear_ratio
        else:
            direction = "neutral"
            agreement_ratio = max(bull_ratio, bear_ratio)

        allow_long = direction == "bullish" and side == "long"
        allow_short = direction == "bearish" and side == "short"
        confirmed = (side == "long" and allow_long) or (side == "short" and allow_short)

        votes_str = "  ".join(
            f"{tf}:{'▲' if v == 1 else '▼' if v == -1 else '—'}"
            for tf, v in votes.items()
        )
        summary = (
            f"MTF {direction} {agreement_ratio*100:.0f}% agreement  "
            f"[{votes_str}]  "
            f"{'✅ CONFIRMED' if confirmed else '❌ REJECTED'} for {side.upper()}"
        )

        if confirmed:
            logger.info("🔭 %s", summary)
        else:
            logger.debug("🔭 %s", summary)

        return MTFResult(
            confirmed=confirmed,
            direction=direction,
            agreement_ratio=agreement_ratio,
            votes=votes,
            allow_long=allow_long,
            allow_short=allow_short,
            summary=summary,
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _resample(self, df: pd.DataFrame, timeframe: str) -> Optional[pd.DataFrame]:
        """Resample base-TF OHLCV data to a higher timeframe."""
        try:
            resampled = df.resample(timeframe).agg({
                "open":   "first",
                "high":   "max",
                "low":    "min",
                "close":  "last",
                "volume": "sum",
            }).dropna()
            return resampled
        except Exception:
            return None

    def _evaluate_timeframe(self, df: pd.DataFrame) -> int:
        """
        Evaluate a single timeframe DataFrame and return a directional vote.

        Returns: +1 (bullish), -1 (bearish), 0 (neutral)
        """
        close = df["close"]
        if len(close) < self._cfg.rsi_period + 1:
            return 0

        # ── RSI ──────────────────────────────────────────────────────────
        rsi_val = self._calc_rsi(close, self._cfg.rsi_period)

        # ── EMA alignment ────────────────────────────────────────────────
        ema_fast = close.ewm(span=self._cfg.ema_fast, adjust=False).mean()
        ema_slow = close.ewm(span=self._cfg.ema_slow, adjust=False).mean()
        ema_bullish = float(ema_fast.iloc[-1]) > float(ema_slow.iloc[-1])
        ema_bearish = float(ema_fast.iloc[-1]) < float(ema_slow.iloc[-1])

        # ── Price momentum (above/below recent midpoint) ──────────────────
        recent_high = float(df["high"].iloc[-self._cfg.rsi_period:].max())
        recent_low = float(df["low"].iloc[-self._cfg.rsi_period:].min())
        midpoint = (recent_high + recent_low) / 2.0
        current_close = float(close.iloc[-1])
        price_above_mid = current_close > midpoint

        # ── Vote aggregation ─────────────────────────────────────────────
        bullish_signals = 0
        bearish_signals = 0

        # RSI
        if rsi_val <= self._cfg.rsi_oversold:
            bullish_signals += 1
        elif rsi_val >= self._cfg.rsi_overbought:
            bearish_signals += 1

        # EMA
        if ema_bullish:
            bullish_signals += 1
        elif ema_bearish:
            bearish_signals += 1

        # Price position
        if price_above_mid:
            bullish_signals += 1
        else:
            bearish_signals += 1

        if bullish_signals > bearish_signals:
            return 1
        elif bearish_signals > bullish_signals:
            return -1
        return 0

    @staticmethod
    def _calc_rsi(close: pd.Series, period: int) -> float:
        """Wilder RSI calculation."""
        delta = close.diff()
        gains = delta.clip(lower=0)
        losses = (-delta).clip(lower=0)
        avg_gain = gains.ewm(alpha=1 / period, adjust=False).mean()
        avg_loss = losses.ewm(alpha=1 / period, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0, 1e-10)
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1])


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[MultiTimeframeConfirmation] = None
_instance_lock = threading.Lock()


def get_mtf_confirmation(
    config: Optional[MTFConfig] = None,
) -> MultiTimeframeConfirmation:
    """Return the process-wide singleton MultiTimeframeConfirmation engine."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = MultiTimeframeConfirmation(config=config)
    return _instance
