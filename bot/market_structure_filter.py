"""
NIJA Market Structure Filter
============================

Evaluates market conditions using a score-weighting system instead of hard
filters.  Each positive signal contributes points to a composite score; an
entry is permitted when the total score reaches the minimum threshold.

Score table
-----------
| Condition                              | Points |
|----------------------------------------|--------|
| Bullish trend (Higher High + Higher Low)| 30     |
| Breakout (price above rolling high)    | 30     |
| Volume spike (>= 1.5× 20-period avg)  | 20     |
| RSI < 40 (oversold / bounce zone)     | 20     |
| **Minimum score to allow entry**       | **60** |

Any combination of the four signals that adds up to 60+ points passes the
filter.  For example:
  - Trend + Volume spike → 50 pts  → BLOCKED
  - Trend + Breakout     → 60 pts  → ALLOWED
  - Volume spike + RSI < 40 → 40 pts → BLOCKED
  - All four signals     → 100 pts → ALLOWED

This dramatically improves signal generation compared with the previous
all-or-nothing (AND) approach while still preventing low-conviction entries.

Usage
-----
    from bot.market_structure_filter import structure_valid, get_structure_details

    if not structure_valid(df):
        return None  # skip this market

    # Or inspect the scoring breakdown:
    details = get_structure_details(df)
    print(details["score"], details["score_breakdown"])
"""

import logging
import pandas as pd

logger = logging.getLogger("nija")

# ── tunable thresholds ────────────────────────────────────────────────────────
VOLUME_EXPANSION_MULTIPLIER: float = 1.5   # volume spike: current volume must exceed avg * this
VOLUME_LOOKBACK_PERIODS: int = 20          # rolling window for average volume
BREAKOUT_LOOKBACK_PERIODS: int = 20        # rolling window for breakout high detection
RSI_OVERSOLD_THRESHOLD: float = 40.0       # RSI below this value → +20 pts (oversold/bounce zone)
MIN_SCORE_TO_ENTER: int = 60               # minimum composite score required to allow entry

# Score weights (must be consistent with the docstring table above)
SCORE_TREND: int = 30      # bullish trend (HH + HL)
SCORE_BREAKOUT: int = 30   # breakout above rolling high
SCORE_VOLUME: int = 20     # volume spike
SCORE_RSI: int = 20        # RSI in oversold/bounce zone (< RSI_OVERSOLD_THRESHOLD)
# ──────────────────────────────────────────────────────────────────────────────


def structure_valid(df: pd.DataFrame) -> bool:
    """
    Return True when the composite market-structure score is >= MIN_SCORE_TO_ENTER.

    Args:
        df: OHLCV DataFrame that **must** contain columns:
            'high', 'low', 'close', 'volume', and 'rsi'.
            At least ``max(2, VOLUME_LOOKBACK_PERIODS, BREAKOUT_LOOKBACK_PERIODS)``
            rows are required.

    Returns:
        bool: True if the weighted score meets the entry threshold.
    """
    details = get_structure_details(df)

    if not details["data_sufficient"]:
        logger.debug(
            "⛔ Market structure filter: insufficient data — %s",
            details["reason"],
        )
        return False

    score = details["score"]
    passed = score >= MIN_SCORE_TO_ENTER

    if not passed:
        logger.debug(
            "⛔ Market structure score %d < %d — breakdown: %s",
            score,
            MIN_SCORE_TO_ENTER,
            details["score_breakdown"],
        )

    return passed


def get_structure_details(df: pd.DataFrame) -> dict:
    """
    Evaluate all market-structure conditions and return a detailed score dict.

    The dict always contains the key ``data_sufficient`` (bool).  When
    ``data_sufficient`` is True the dict also contains:

    * ``score``           – int: composite score (0–100)
    * ``score_breakdown`` – dict: per-condition points awarded
    * ``trend``           – bool: Higher High AND Higher Low
    * ``higher_high``     – bool
    * ``higher_low``      – bool
    * ``breakout``        – bool: close > rolling high (excl. last candle)
    * ``volume``          – bool: volume spike above threshold
    * ``volume_ratio``    – float: current / average volume
    * ``rsi_oversold``    – bool: RSI < RSI_OVERSOLD_THRESHOLD
    * ``rsi``             – float

    Args:
        df: OHLCV DataFrame with 'high', 'low', 'close', 'volume', 'rsi' columns.

    Returns:
        dict with the fields described above.
    """
    required_cols = {"high", "low", "close", "volume", "rsi"}
    missing = required_cols - set(df.columns)
    if missing:
        return {
            "data_sufficient": False,
            "reason": f"Missing columns: {', '.join(sorted(missing))}",
        }

    min_rows = max(2, VOLUME_LOOKBACK_PERIODS, BREAKOUT_LOOKBACK_PERIODS)
    if len(df) < min_rows:
        return {
            "data_sufficient": False,
            "reason": (
                f"Need at least {min_rows} rows, got {len(df)}"
            ),
        }

    # ── 1. Trend: Bullish Higher High + Higher Low ────────────────────────────
    high_now = float(df["high"].iloc[-1])
    high_prev = float(df["high"].iloc[-2])
    low_now = float(df["low"].iloc[-1])
    low_prev = float(df["low"].iloc[-2])

    higher_high = high_now > high_prev
    higher_low = low_now > low_prev
    trend = higher_high and higher_low

    # ── 2. Breakout: close above rolling high of prior candles ────────────────
    rolling_high = float(df["high"].iloc[-(BREAKOUT_LOOKBACK_PERIODS + 1):-1].max())
    close_now = float(df["close"].iloc[-1])
    breakout = close_now > rolling_high

    # ── 3. Volume spike ───────────────────────────────────────────────────────
    volume_now = float(df["volume"].iloc[-1])
    avg_volume = float(
        df["volume"].rolling(VOLUME_LOOKBACK_PERIODS).mean().iloc[-1]
    )

    if avg_volume > 0:
        volume_ratio = volume_now / avg_volume
    else:
        volume_ratio = 0.0

    volume = volume_ratio >= VOLUME_EXPANSION_MULTIPLIER

    # ── 4. RSI oversold / bounce zone ────────────────────────────────────────
    rsi = float(df["rsi"].iloc[-1])
    rsi_oversold = rsi < RSI_OVERSOLD_THRESHOLD

    # ── Composite score ───────────────────────────────────────────────────────
    score_breakdown: dict = {
        "trend": SCORE_TREND if trend else 0,
        "breakout": SCORE_BREAKOUT if breakout else 0,
        "volume": SCORE_VOLUME if volume else 0,
        "rsi_oversold": SCORE_RSI if rsi_oversold else 0,
    }
    score: int = sum(score_breakdown.values())

    return {
        "data_sufficient": True,
        "score": score,
        "score_breakdown": score_breakdown,
        "trend": trend,
        "higher_high": higher_high,
        "higher_low": higher_low,
        "breakout": breakout,
        "volume": volume,
        "volume_ratio": volume_ratio,
        "rsi_oversold": rsi_oversold,
        "rsi": rsi,
    }
