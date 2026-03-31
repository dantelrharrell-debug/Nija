"""
NIJA Momentum Entry Filter
===========================

Implements the two fast-entry patterns that produce repeatable daily trades:

1. Momentum Entry
   Rule: RSI confirmed (>55 bull / <45 bear)
         AND (volume > rolling baseline  OR  price breaking short-term structure)
   Requires: RSI condition + at least 1 of the other 2 confirmations (2/3 OR logic)

2. Breakout Entry
   Rule: price closes above N-period high (long) / below N-period low (short)
         AND volume spike (current bar > surge_multiplier × rolling average)
   Requires: both conditions (2/2 — fast confirmation only)

Design principle: "repeatable trades with edge" — not perfect setups.
These entries bypass the institutional pullback / candlestick / MACD stack
and fire when the market shows *directional momentum*, which is the #1
scalping trigger used by professional desks.

Both checkers return the same 3-tuple as check_long/short_entry:
    (signal: bool, score: float, reason: str)

Configuration via environment variables (all optional):
    MOMENTUM_RSI_BULL=55        RSI threshold for long momentum (default 55)
    MOMENTUM_RSI_BEAR=45        RSI threshold for short momentum (default 45)
    MOMENTUM_VOLUME_WINDOW=10   Rolling bars for volume baseline (default 10)
    MOMENTUM_STRUCT_WINDOW=10   Rolling bars for structure break (default 10)
    BREAKOUT_WINDOW=20          Rolling bars for resistance/support (default 20)
    BREAKOUT_VOL_SURGE=1.4      Volume surge multiplier for breakout (default 1.4)
"""

from __future__ import annotations

import logging
import os
from typing import Dict, Tuple

import pandas as pd

logger = logging.getLogger("nija.momentum_entry_filter")

# ---------------------------------------------------------------------------
# Configurable thresholds (env-overridable)
# ---------------------------------------------------------------------------

def _ef(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


_RSI_BULL_THRESHOLD: float    = _ef("MOMENTUM_RSI_BULL", 55.0)
_RSI_BEAR_THRESHOLD: float    = _ef("MOMENTUM_RSI_BEAR", 45.0)
_VOL_WINDOW: int              = int(_ef("MOMENTUM_VOLUME_WINDOW", 10))
_STRUCT_WINDOW: int           = int(_ef("MOMENTUM_STRUCT_WINDOW", 10))
_BREAKOUT_WINDOW: int         = int(_ef("BREAKOUT_WINDOW", 20))
_BREAKOUT_VOL_SURGE: float    = _ef("BREAKOUT_VOL_SURGE", 1.4)

# Balance-based threshold tightening — mirrors trade_frequency_controller constants.
TARGET_BALANCE: float = 100.0       # tighten AI entry threshold once balance hits this
TIGHTENED_ENTRY_SCORE: float = 5.0  # restored threshold when TARGET_BALANCE is reached


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _last(series: pd.Series) -> float:
    """Return the last scalar value from a Series, handling NaN gracefully."""
    try:
        v = series.iloc[-1]
        return float(v) if pd.notna(v) else 0.0
    except Exception:
        return 0.0


# ---------------------------------------------------------------------------
# Momentum Entry
# ---------------------------------------------------------------------------

def check_momentum_long(
    df: pd.DataFrame,
    indicators: Dict,
) -> Tuple[bool, float, str]:
    """
    Momentum long entry: RSI > threshold + (volume rising OR price breaks structure).

    Returns:
        (signal, score, reason)
        score is 2.0 (RSI + 1 confirm) or 3.0 (RSI + both confirms)
    """
    try:
        rsi_series = indicators.get("rsi", indicators.get("rsi_14"))
        if rsi_series is None:
            return False, 0.0, "momentum_long: RSI unavailable"

        rsi = _last(rsi_series)
        close = _last(df["close"])

        # ── Condition 1: RSI bullish momentum (MANDATORY) ────────────
        rsi_ok = rsi > _RSI_BULL_THRESHOLD

        if not rsi_ok:
            return False, 0.0, f"momentum_long: RSI {rsi:.1f} ≤ {_RSI_BULL_THRESHOLD}"

        confirmations = 1  # RSI counts as 1
        parts = [f"RSI {rsi:.1f}>{_RSI_BULL_THRESHOLD}"]

        # ── Condition 2: Volume increasing ───────────────────────────
        vol_ok = False
        if "volume" in df.columns and len(df) > _VOL_WINDOW:
            cur_vol = float(df["volume"].iloc[-1])
            avg_vol = float(df["volume"].iloc[-(_VOL_WINDOW + 1):-1].mean())
            vol_ok = avg_vol > 0 and cur_vol > avg_vol
            if vol_ok:
                confirmations += 1
                parts.append(f"vol↑({cur_vol/avg_vol:.2f}×avg)")

        # ── Condition 3: Price breaking short-term structure ─────────
        struct_ok = False
        if len(df) > _STRUCT_WINDOW + 1:
            # Close above the highest close of the prior N bars
            prior_high = float(df["close"].iloc[-(_STRUCT_WINDOW + 1):-1].max())
            struct_ok = close > prior_high
            if struct_ok:
                confirmations += 1
                parts.append(f"struct break({close:.4f}>{prior_high:.4f})")

        # Need RSI + at least 1 more confirmation (2/3)
        signal = confirmations >= 2
        score = float(confirmations)
        reason = f"momentum_long [{confirmations}/3]: {' | '.join(parts)}"

        if signal:
            logger.debug("  ✅ %s", reason)
        return signal, score, reason

    except Exception as exc:
        logger.warning("momentum_long error: %s", exc)
        return False, 0.0, f"momentum_long error: {exc}"


def check_momentum_short(
    df: pd.DataFrame,
    indicators: Dict,
) -> Tuple[bool, float, str]:
    """
    Momentum short entry: RSI < threshold + (volume rising OR price breaks structure).

    Returns:
        (signal, score, reason)
    """
    try:
        rsi_series = indicators.get("rsi", indicators.get("rsi_14"))
        if rsi_series is None:
            return False, 0.0, "momentum_short: RSI unavailable"

        rsi = _last(rsi_series)
        close = _last(df["close"])

        # ── Condition 1: RSI bearish momentum (MANDATORY) ────────────
        rsi_ok = rsi < _RSI_BEAR_THRESHOLD

        if not rsi_ok:
            return False, 0.0, f"momentum_short: RSI {rsi:.1f} ≥ {_RSI_BEAR_THRESHOLD}"

        confirmations = 1
        parts = [f"RSI {rsi:.1f}<{_RSI_BEAR_THRESHOLD}"]

        # ── Condition 2: Volume increasing ───────────────────────────
        if "volume" in df.columns and len(df) > _VOL_WINDOW:
            cur_vol = float(df["volume"].iloc[-1])
            avg_vol = float(df["volume"].iloc[-(_VOL_WINDOW + 1):-1].mean())
            if avg_vol > 0 and cur_vol > avg_vol:
                confirmations += 1
                parts.append(f"vol↑({cur_vol/avg_vol:.2f}×avg)")

        # ── Condition 3: Price breaking short-term structure ─────────
        if len(df) > _STRUCT_WINDOW + 1:
            prior_low = float(df["close"].iloc[-(_STRUCT_WINDOW + 1):-1].min())
            if close < prior_low:
                confirmations += 1
                parts.append(f"struct break({close:.4f}<{prior_low:.4f})")

        signal = confirmations >= 2
        score = float(confirmations)
        reason = f"momentum_short [{confirmations}/3]: {' | '.join(parts)}"

        if signal:
            logger.debug("  ✅ %s", reason)
        return signal, score, reason

    except Exception as exc:
        logger.warning("momentum_short error: %s", exc)
        return False, 0.0, f"momentum_short error: {exc}"


# ---------------------------------------------------------------------------
# Breakout Entry
# ---------------------------------------------------------------------------

def check_breakout_long(
    df: pd.DataFrame,
    indicators: Dict,
) -> Tuple[bool, float, str]:
    """
    Breakout long: close above N-period resistance AND volume spike.

    Returns:
        (signal, score, reason)  score=2.0 when both conditions met
    """
    try:
        if len(df) < _BREAKOUT_WINDOW + 2 or "volume" not in df.columns:
            return False, 0.0, "breakout_long: insufficient data"

        close = float(df["close"].iloc[-1])
        # Resistance = highest close over the prior N bars (excluding current)
        resistance = float(df["close"].iloc[-(_BREAKOUT_WINDOW + 1):-1].max())
        price_break = close > resistance

        cur_vol = float(df["volume"].iloc[-1])
        avg_vol = float(df["volume"].iloc[-(_BREAKOUT_WINDOW + 1):-1].mean())
        vol_spike = avg_vol > 0 and cur_vol > avg_vol * _BREAKOUT_VOL_SURGE

        signal = price_break and vol_spike
        score = 2.0 if signal else float(price_break + vol_spike)
        parts = []
        if price_break:
            parts.append(f"price break({close:.4f}>{resistance:.4f})")
        if vol_spike:
            parts.append(f"vol spike({cur_vol/avg_vol:.2f}×)")
        reason = f"breakout_long [{int(score)}/2]: {' | '.join(parts) or 'no conditions'}"

        if signal:
            logger.debug("  ✅ %s", reason)
        return signal, score, reason

    except Exception as exc:
        logger.warning("breakout_long error: %s", exc)
        return False, 0.0, f"breakout_long error: {exc}"


def check_breakout_short(
    df: pd.DataFrame,
    indicators: Dict,
) -> Tuple[bool, float, str]:
    """
    Breakout short: close below N-period support AND volume spike.

    Returns:
        (signal, score, reason)  score=2.0 when both conditions met
    """
    try:
        if len(df) < _BREAKOUT_WINDOW + 2 or "volume" not in df.columns:
            return False, 0.0, "breakout_short: insufficient data"

        close = float(df["close"].iloc[-1])
        support = float(df["close"].iloc[-(_BREAKOUT_WINDOW + 1):-1].min())
        price_break = close < support

        cur_vol = float(df["volume"].iloc[-1])
        avg_vol = float(df["volume"].iloc[-(_BREAKOUT_WINDOW + 1):-1].mean())
        vol_spike = avg_vol > 0 and cur_vol > avg_vol * _BREAKOUT_VOL_SURGE

        signal = price_break and vol_spike
        score = 2.0 if signal else float(price_break + vol_spike)
        parts = []
        if price_break:
            parts.append(f"price break({close:.4f}<{support:.4f})")
        if vol_spike:
            parts.append(f"vol spike({cur_vol/avg_vol:.2f}×)")
        reason = f"breakout_short [{int(score)}/2]: {' | '.join(parts) or 'no conditions'}"

        if signal:
            logger.debug("  ✅ %s", reason)
        return signal, score, reason

    except Exception as exc:
        logger.warning("breakout_short error: %s", exc)
        return False, 0.0, f"breakout_short error: {exc}"


# ---------------------------------------------------------------------------
# Balance-based threshold tightening
# ---------------------------------------------------------------------------

def check_balance_and_adjust_threshold(current_balance: float) -> None:
    """
    Tighten the AI entry threshold once the account balance reaches TARGET_BALANCE.

    Call this at the end of each trade or scan loop.
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
            logger.warning(
                "check_balance_and_adjust_threshold: "
                "could not update ai_entry_gate threshold: %s", exc,
            )
