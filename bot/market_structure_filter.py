"""
NIJA Market Structure Filter
============================

Confirms that a market is in a valid trending structure before allowing entry.
Three conditions must ALL pass for an entry to be permitted:

1. Trend Confirmation (Higher High / Higher Low)
   - current_high > previous_high
   - current_low  > previous_low
   Prevents buying into fake breakouts.

2. Volume Expansion
   - current_volume > average_volume * 1.5  (20-period rolling average)
   Ensures real participation in the move.

3. Momentum Confirmation
   - RSI > 55
   Avoids sideways / low-momentum markets.

Usage
-----
    from bot.market_structure_filter import structure_valid

    if not structure_valid(df):
        return None  # skip this market
"""

import logging
import pandas as pd

logger = logging.getLogger("nija")

# ── tunable thresholds ────────────────────────────────────────────────────────
VOLUME_EXPANSION_MULTIPLIER: float = 1.5   # current volume must exceed avg * this
MOMENTUM_RSI_THRESHOLD: float = 55.0       # minimum RSI value for momentum confirmation
VOLUME_LOOKBACK_PERIODS: int = 20          # rolling window for average volume
# ──────────────────────────────────────────────────────────────────────────────


def structure_valid(df: pd.DataFrame) -> bool:
    """
    Return True only when all three market-structure conditions are met.

    Args:
        df: OHLCV DataFrame that **must** contain columns:
            'high', 'low', 'volume', and 'rsi'.
            At least 2 rows are required for trend comparison.
            At least ``VOLUME_LOOKBACK_PERIODS`` rows are required for the
            rolling average.

    Returns:
        bool: True if trend, volume expansion, and momentum all confirm.
              False (and a debug log entry) if any condition fails or if the
              DataFrame does not have enough data.
    """
    details = get_structure_details(df)

    if not details["data_sufficient"]:
        logger.debug(
            "⛔ Market structure filter: insufficient data — %s",
            details["reason"],
        )
        return False

    passed = details["trend"] and details["volume"] and details["momentum"]

    if not passed:
        failed = [k for k in ("trend", "volume", "momentum") if not details[k]]
        logger.debug(
            "⛔ Market structure filter FAILED — conditions not met: %s "
            "(HH=%s, HL=%s, vol_ratio=%.2f, rsi=%.1f)",
            ", ".join(failed),
            details["higher_high"],
            details["higher_low"],
            details["volume_ratio"],
            details["rsi"],
        )
    return passed


def get_structure_details(df: pd.DataFrame) -> dict:
    """
    Evaluate all three structure conditions and return a rich detail dict.

    The dict always contains the key ``data_sufficient`` (bool).  When
    ``data_sufficient`` is True the dict also contains:

    * ``trend``       – bool: Higher High AND Higher Low
    * ``higher_high`` – bool
    * ``higher_low``  – bool
    * ``volume``      – bool: current volume > avg * VOLUME_EXPANSION_MULTIPLIER
    * ``volume_ratio``– float: current / average volume
    * ``momentum``    – bool: RSI > MOMENTUM_RSI_THRESHOLD
    * ``rsi``         – float

    Args:
        df: OHLCV DataFrame with 'high', 'low', 'volume', 'rsi' columns.

    Returns:
        dict with the fields described above.
    """
    required_cols = {"high", "low", "volume", "rsi"}
    missing = required_cols - set(df.columns)
    if missing:
        return {
            "data_sufficient": False,
            "reason": f"Missing columns: {', '.join(sorted(missing))}",
        }

    min_rows = max(2, VOLUME_LOOKBACK_PERIODS)
    if len(df) < min_rows:
        return {
            "data_sufficient": False,
            "reason": (
                f"Need at least {min_rows} rows, got {len(df)}"
            ),
        }

    # ── 1. Trend confirmation: Higher High + Higher Low ───────────────────────
    high_now = float(df["high"].iloc[-1])
    high_prev = float(df["high"].iloc[-2])
    low_now = float(df["low"].iloc[-1])
    low_prev = float(df["low"].iloc[-2])

    higher_high = high_now > high_prev
    higher_low = low_now > low_prev
    trend = higher_high and higher_low

    # ── 2. Volume expansion ───────────────────────────────────────────────────
    volume_now = float(df["volume"].iloc[-1])
    avg_volume = float(
        df["volume"].rolling(VOLUME_LOOKBACK_PERIODS).mean().iloc[-1]
    )

    if avg_volume > 0:
        volume_ratio = volume_now / avg_volume
    else:
        volume_ratio = 0.0

    volume = volume_ratio > VOLUME_EXPANSION_MULTIPLIER

    # ── 3. Momentum via RSI ───────────────────────────────────────────────────
    rsi = float(df["rsi"].iloc[-1])
    momentum = rsi > MOMENTUM_RSI_THRESHOLD

    return {
        "data_sufficient": True,
        "trend": trend,
        "higher_high": higher_high,
        "higher_low": higher_low,
        "volume": volume,
        "volume_ratio": volume_ratio,
        "momentum": momentum,
        "rsi": rsi,
    }
