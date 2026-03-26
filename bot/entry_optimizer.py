"""
NIJA Entry Optimizer
====================

Enhances entry signal quality scoring by detecting high-conviction patterns
that the base 5-condition entry check does not capture:

1. **RSI Divergence** – Bullish divergence (price lower low, RSI higher low)
   or bearish divergence (price higher high, RSI lower high) is one of the
   strongest reversal/continuation signals in technical analysis.

2. **Bollinger Band Proximity** – Entries near the lower BB (longs) or upper
   BB (shorts) align the trade with mean-reversion probabilities.

3. **Volume Pattern on Pullback** – Volume contracting during a pullback
   signals accumulation/distribution without panic, improving entry quality.

Usage
-----
::

    from bot.entry_optimizer import get_entry_optimizer

    optimizer = get_entry_optimizer()

    # Before entering a trade:
    result = optimizer.analyze_entry(df, indicators, side="long")
    optimized_score = base_score + result.score_delta

    # Log what was found:
    print(result.reason)

The ``score_delta`` is always >= 0 (additive bonus only), so it never blocks a
signal that the base conditions already approved.  It simply raises the score
for high-quality setups, which benefits:
- Position sizing (higher score → larger size multiplier)
- Signal ranking when multiple candidates compete in the same scan cycle

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("nija.entry_optimizer")

# ── Divergence detection parameters ──────────────────────────────────────────
_DIVERGENCE_LOOKBACK = 14   # Bars to scan for RSI divergence (split into 2 halves)
_MIN_PRICE_DIFF_PCT  = 0.001  # Minimum 0.1% price difference to count as a new low/high

# ── Bollinger Band scoring thresholds ────────────────────────────────────────
# bb_pct = (price - bb_lower) / (bb_upper - bb_lower)
_BB_OPTIMAL_LONG_MAX  = 0.25   # <= 25 %b  → optimal long zone (near lower band)
_BB_GOOD_LONG_MAX     = 0.45   # 25–45 %b  → good long zone
_BB_OPTIMAL_SHORT_MIN = 0.75   # >= 75 %b  → optimal short zone (near upper band)
_BB_GOOD_SHORT_MIN    = 0.55   # 55–75 %b  → good short zone

# ── Volume contraction thresholds ────────────────────────────────────────────
_VOL_CONTRACT_RATIO   = 0.75   # Recent 3-bar avg / prior 3-bar avg < this → contracting
_VOL_EXPAND_RATIO     = 1.40   # Recent 3-bar avg / prior 3-bar avg > this → expanding badly

# ── Score delta values ───────────────────────────────────────────────────────
_DELTA_RSI_DIVERGENCE  = 1.0   # Strongest signal
_DELTA_BB_OPTIMAL      = 0.5   # Price in optimal BB zone
_DELTA_BB_GOOD         = 0.25  # Price in good BB zone
_DELTA_VOL_CONTRACT    = 0.5   # Volume contracting on pullback


@dataclass
class EntryOptimizationResult:
    """Result of entry optimization analysis."""

    score_delta: float          # ≥ 0.0 — bonus added to the base entry score
    rsi_divergence: bool        # True if RSI divergence confirmed
    bb_zone: str                # "optimal" | "good" | "neutral" | "poor" | "unknown"
    volume_pattern: str         # "contracting" | "neutral" | "expanding" | "unknown"
    reason: str                 # Human-readable summary of bonuses found

    @property
    def has_any_boost(self) -> bool:
        return self.score_delta > 0.0


class EntryOptimizer:
    """
    Analyzes entry quality and returns an additive score bonus.

    The optimizer is read-only with respect to signals — it never vetoes a
    trade that the base conditions approved.  It only rewards extra-quality
    setups with a higher score, which flows through to position sizing and
    signal ranking.
    """

    def __init__(self) -> None:
        logger.info("EntryOptimizer initialized")

    # ── Public API ────────────────────────────────────────────────────────────

    def analyze_entry(
        self,
        df: pd.DataFrame,
        indicators: Dict,
        side: str,
    ) -> EntryOptimizationResult:
        """
        Run all entry-optimization checks and return an aggregated result.

        Args:
            df:          OHLCV DataFrame (index = chronological, most recent last)
            indicators:  Dict produced by ``NijaApexStrategyV71.calculate_indicators``
            side:        ``"long"`` or ``"short"``

        Returns:
            :class:`EntryOptimizationResult`
        """
        try:
            delta = 0.0
            bonuses: list[str] = []

            # 1. RSI divergence ────────────────────────────────────────────────
            rsi_div = self._check_rsi_divergence(df, indicators, side)
            if rsi_div:
                delta += _DELTA_RSI_DIVERGENCE
                bonuses.append("RSI divergence")

            # 2. Bollinger Band zone ───────────────────────────────────────────
            bb_zone = self._score_bb_zone(df, indicators, side)
            if bb_zone == "optimal":
                delta += _DELTA_BB_OPTIMAL
                bonuses.append("BB optimal zone")
            elif bb_zone == "good":
                delta += _DELTA_BB_GOOD
                bonuses.append("BB good zone")

            # 3. Volume pattern ────────────────────────────────────────────────
            vol_pattern = self._analyze_volume_pattern(df)
            if vol_pattern == "contracting":
                delta += _DELTA_VOL_CONTRACT
                bonuses.append("vol contracting")

            reason = " | ".join(bonuses) if bonuses else "no boost"

            return EntryOptimizationResult(
                score_delta=delta,
                rsi_divergence=rsi_div,
                bb_zone=bb_zone,
                volume_pattern=vol_pattern,
                reason=reason,
            )

        except Exception as exc:
            logger.warning(f"EntryOptimizer.analyze_entry error: {exc}")
            return EntryOptimizationResult(
                score_delta=0.0,
                rsi_divergence=False,
                bb_zone="unknown",
                volume_pattern="unknown",
                reason=f"error: {exc}",
            )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _check_rsi_divergence(
        self,
        df: pd.DataFrame,
        indicators: Dict,
        side: str,
    ) -> bool:
        """
        Detect classic RSI divergence over the last ``_DIVERGENCE_LOOKBACK`` bars.

        Bullish divergence (long): price makes a lower low while RSI makes a
        higher low — selling momentum is weakening.

        Bearish divergence (short): price makes a higher high while RSI makes
        a lower high — buying momentum is weakening.
        """
        rsi_series = indicators.get("rsi")
        if rsi_series is None or len(df) < _DIVERGENCE_LOOKBACK + 2:
            return False

        prices = df["close"].values[-_DIVERGENCE_LOOKBACK:]
        try:
            rsi_vals = rsi_series.values[-_DIVERGENCE_LOOKBACK:]
        except AttributeError:
            return False

        if len(prices) < _DIVERGENCE_LOOKBACK or len(rsi_vals) < _DIVERGENCE_LOOKBACK:
            return False

        mid = _DIVERGENCE_LOOKBACK // 2

        if side == "long":
            # First half: earlier period; second half: more recent
            p1_min_idx = int(np.argmin(prices[:mid]))
            p2_min_idx = int(np.argmin(prices[mid:])) + mid

            p1_low   = prices[p1_min_idx]
            p2_low   = prices[p2_min_idx]
            r1_low   = rsi_vals[p1_min_idx]
            r2_low   = rsi_vals[p2_min_idx]

            # Require a meaningful new price low (avoids noise)
            if p1_low <= 0:
                return False
            price_fell = p2_low < p1_low * (1.0 - _MIN_PRICE_DIFF_PCT)
            rsi_rose   = r2_low > r1_low

            return price_fell and rsi_rose

        else:  # short
            p1_max_idx = int(np.argmax(prices[:mid]))
            p2_max_idx = int(np.argmax(prices[mid:])) + mid

            p1_high  = prices[p1_max_idx]
            p2_high  = prices[p2_max_idx]
            r1_high  = rsi_vals[p1_max_idx]
            r2_high  = rsi_vals[p2_max_idx]

            if p1_high <= 0:
                return False
            price_rose  = p2_high > p1_high * (1.0 + _MIN_PRICE_DIFF_PCT)
            rsi_fell    = r2_high < r1_high

            return price_rose and rsi_fell

    def _score_bb_zone(
        self,
        df: pd.DataFrame,
        indicators: Dict,
        side: str,
    ) -> str:
        """
        Score the current price position within the Bollinger Bands.

        Returns one of: ``"optimal"``, ``"good"``, ``"neutral"``, ``"poor"``,
        ``"unknown"``.
        """
        bb_lower  = indicators.get("bb_lower")
        bb_upper  = indicators.get("bb_upper")

        if bb_lower is None or bb_upper is None:
            return "unknown"

        try:
            lower = float(bb_lower.iloc[-1])
            upper = float(bb_upper.iloc[-1])
        except (AttributeError, IndexError):
            return "unknown"

        bb_range = upper - lower
        if bb_range <= 0:
            return "unknown"

        price  = float(df["close"].iloc[-1])
        bb_pct = (price - lower) / bb_range   # 0 = at lower band, 1 = at upper band

        if side == "long":
            if bb_pct <= _BB_OPTIMAL_LONG_MAX:
                return "optimal"
            if bb_pct <= _BB_GOOD_LONG_MAX:
                return "good"
            if bb_pct <= 0.60:
                return "neutral"
            return "poor"  # Long entry near upper band = unfavorable
        else:  # short
            if bb_pct >= _BB_OPTIMAL_SHORT_MIN:
                return "optimal"
            if bb_pct >= _BB_GOOD_SHORT_MIN:
                return "good"
            if bb_pct >= 0.40:
                return "neutral"
            return "poor"  # Short entry near lower band = unfavorable

    def _analyze_volume_pattern(self, df: pd.DataFrame) -> str:
        """
        Compare recent 3-bar average volume against prior 3-bar average.

        Contracting volume during a pullback is a classic sign of healthy
        accumulation / distribution — the dominant force is not fighting the
        move.

        Returns: ``"contracting"``, ``"neutral"``, ``"expanding"``, or
        ``"unknown"``.
        """
        if len(df) < 6:
            return "unknown"

        try:
            recent = df["volume"].iloc[-3:].values.astype(float)
            prior  = df["volume"].iloc[-6:-3].values.astype(float)
        except Exception:
            return "unknown"

        avg_recent = np.mean(recent)
        avg_prior  = np.mean(prior)

        if avg_prior <= 0:
            return "unknown"

        ratio = avg_recent / avg_prior

        if ratio < _VOL_CONTRACT_RATIO:
            return "contracting"
        if ratio > _VOL_EXPAND_RATIO:
            return "expanding"
        return "neutral"


# ── Singleton ─────────────────────────────────────────────────────────────────
_entry_optimizer: Optional[EntryOptimizer] = None


def get_entry_optimizer() -> EntryOptimizer:
    """Return (or lazily create) the module-level singleton EntryOptimizer."""
    global _entry_optimizer
    if _entry_optimizer is None:
        _entry_optimizer = EntryOptimizer()
    return _entry_optimizer
