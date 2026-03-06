"""
NIJA AI Trade Ranker
=====================

Scores every potential trade before execution using a multi-factor formula
and rejects low-quality setups—dramatically improving win rate.

Scoring Formula
---------------
    trade_score = trend_strength + volatility + volume + momentum

Each component contributes up to 25 points (total 0–100).

Execution Gate
--------------
Only trades with ``trade_score > SCORE_THRESHOLD`` (default: 75) are
executed.  Trades below the threshold are logged and discarded.

Component Breakdown
-------------------
trend_strength (0–25)
    Combines ADX strength and EMA alignment.  High ADX + aligned EMAs = full
    marks.

volatility (0–25)
    ATR relative to its 14-period rolling mean.  Optimal volatility (neither
    too calm nor too explosive) scores highest.

volume (0–25)
    Current bar volume relative to the 20-period average.  Volume > 1.5× avg
    receives full marks; volume below avg scores zero.

momentum (0–25)
    RSI position and MACD histogram direction.  RSI in trend-aligned ranges
    with a confirming MACD histogram earns full marks.

Integration Example
-------------------
    from bot.ai_trade_ranker import AITradeRanker

    ranker = AITradeRanker()

    score, breakdown = ranker.score_trade(
        df=df,
        indicators=indicators,
        side="long",          # or "short"
        symbol="BTC-USD",
    )

    if ranker.should_execute(score):
        # Place the order
        ...
    else:
        logger.info(f"Trade rejected – score {score:.1f} < {ranker.score_threshold}")

Author: NIJA Trading Systems
Version: 1.0
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

import pandas as pd

logger = logging.getLogger("nija.ai_trade_ranker")

# Default execution threshold (as specified in the problem statement)
DEFAULT_SCORE_THRESHOLD: float = 75.0

# Maximum possible score (each of the 4 components is worth 25 points)
MAX_SCORE: float = 100.0


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class TradeScoreBreakdown:
    """
    Detailed breakdown of a trade's AI ranking score.

    Attributes
    ----------
    trend_strength : float   ADX + EMA alignment component (0–25).
    volatility     : float   ATR relative-to-average component (0–25).
    volume         : float   Volume-ratio component (0–25).
    momentum       : float   RSI + MACD component (0–25).
    total          : float   Sum of all four components (0–100).
    quality        : str     Human-readable label ("Excellent", "Good", …).
    should_execute : bool    ``True`` when total > threshold.
    reason         : str     Summary of the scoring decision.
    """
    trend_strength: float = 0.0
    volatility: float = 0.0
    volume: float = 0.0
    momentum: float = 0.0
    total: float = 0.0
    quality: str = "Poor"
    should_execute: bool = False
    reason: str = ""


# ---------------------------------------------------------------------------
# Ranker
# ---------------------------------------------------------------------------

class AITradeRanker:
    """
    Scores and filters trades using the four-factor AI ranking formula.

    Parameters
    ----------
    score_threshold : float
        Minimum score required for trade execution (default: 75).
    weights : dict, optional
        Per-component maximum points.  Must sum to 100.  Defaults to 25 each.
    """

    # Weights (maximum contribution of each factor)
    DEFAULT_WEIGHTS: Dict[str, float] = {
        "trend_strength": 25.0,
        "volatility":     25.0,
        "volume":         25.0,
        "momentum":       25.0,
    }

    def __init__(
        self,
        score_threshold: float = DEFAULT_SCORE_THRESHOLD,
        weights: Optional[Dict[str, float]] = None,
    ):
        self.score_threshold = score_threshold
        self.weights = weights if weights is not None else dict(self.DEFAULT_WEIGHTS)

        if abs(sum(self.weights.values()) - 100.0) > 0.01:
            raise ValueError(
                f"Weights must sum to 100, got {sum(self.weights.values()):.2f}"
            )

        logger.info(
            "AITradeRanker initialised | threshold=%.1f | weights=%s",
            self.score_threshold,
            self.weights,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def score_trade(
        self,
        df: pd.DataFrame,
        indicators: Dict,
        side: str = "long",
        symbol: str = "UNKNOWN",
    ) -> Tuple[float, TradeScoreBreakdown]:
        """
        Score a potential trade using the four-factor formula.

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV price DataFrame (must have ``close``, ``high``, ``low``,
            ``volume`` columns).
        indicators : dict
            Pre-computed technical indicators.  Recognised keys:
            ``rsi_9``, ``rsi_14``, ``rsi``, ``adx``, ``atr``,
            ``ema_9``, ``ema_21``, ``ema_50``, ``macd_hist``,
            ``macd_histogram``.
        side : str
            ``"long"`` or ``"short"``.
        symbol : str
            Trading pair symbol (used only for logging).

        Returns
        -------
        Tuple[float, TradeScoreBreakdown]
            ``(total_score, breakdown)``
        """
        side = side.lower()
        w = self.weights

        ts_score  = self._score_trend_strength(df, indicators, side, w["trend_strength"])
        vol_score = self._score_volatility(df, indicators, w["volatility"])
        vm_score  = self._score_volume(df, w["volume"])
        mom_score = self._score_momentum(df, indicators, side, w["momentum"])

        total = ts_score + vol_score + vm_score + mom_score
        total = min(total, MAX_SCORE)     # cap at 100 in case of rounding

        quality = self._classify(total)
        execute = total > self.score_threshold

        reason = (
            f"{symbol} | {side.upper()} | score={total:.1f}/100 ({quality}) | "
            f"trend={ts_score:.1f} volatility={vol_score:.1f} "
            f"volume={vm_score:.1f} momentum={mom_score:.1f} | "
            f"{'✅ EXECUTE' if execute else '❌ REJECT (threshold=' + str(self.score_threshold) + ')'}"
        )

        if execute:
            logger.info("Trade APPROVED  – %s", reason)
        else:
            logger.info("Trade REJECTED  – %s", reason)

        breakdown = TradeScoreBreakdown(
            trend_strength=ts_score,
            volatility=vol_score,
            volume=vm_score,
            momentum=mom_score,
            total=total,
            quality=quality,
            should_execute=execute,
            reason=reason,
        )
        return total, breakdown

    def should_execute(self, score: float) -> bool:
        """Return ``True`` when *score* exceeds the execution threshold."""
        return score > self.score_threshold

    # ------------------------------------------------------------------
    # Scoring components
    # ------------------------------------------------------------------

    def _score_trend_strength(
        self,
        df: pd.DataFrame,
        indicators: Dict,
        side: str,
        max_pts: float,
    ) -> float:
        """
        Trend Strength component (0 – max_pts).

        Sub-factors:
          * ADX strength  (0 – max_pts/2)
          * EMA alignment (0 – max_pts/2)
        """
        half = max_pts / 2.0
        score = 0.0

        # --- ADX strength ---
        adx = _scalar(indicators.get("adx"))
        if adx is not None:
            if adx >= 40:
                score += half
            elif adx >= 30:
                score += half * 0.8
            elif adx >= 25:
                score += half * 0.6
            elif adx >= 20:
                score += half * 0.4
            else:
                score += half * 0.2

        # --- EMA alignment ---
        close = _scalar(df["close"])
        ema9  = _scalar(indicators.get("ema_9",  indicators.get("ema9")))
        ema21 = _scalar(indicators.get("ema_21", indicators.get("ema21")))
        ema50 = _scalar(indicators.get("ema_50", indicators.get("ema50")))

        if close is not None:
            if side == "long":
                if ema9 is not None and ema21 is not None and ema50 is not None and close > ema9 > ema21 > ema50:
                    score += half
                elif ema9 is not None and ema21 is not None and close > ema9 > ema21:
                    score += half * 0.7
                elif ema9 is not None and close > ema9:
                    score += half * 0.4
            else:  # short
                if ema9 is not None and ema21 is not None and ema50 is not None and close < ema9 < ema21 < ema50:
                    score += half
                elif ema9 is not None and ema21 is not None and close < ema9 < ema21:
                    score += half * 0.7
                elif ema9 is not None and close < ema9:
                    score += half * 0.4

        return min(score, max_pts)

    def _score_volatility(
        self,
        df: pd.DataFrame,
        indicators: Dict,
        max_pts: float,
    ) -> float:
        """
        Volatility component (0 – max_pts).

        Uses ATR relative to its rolling mean.  Optimal volatility (1.0–1.5×)
        scores highest; very low or explosive volatility scores lower.
        """
        atr_series = indicators.get("atr")
        if atr_series is None:
            return max_pts * 0.3  # neutral fallback

        atr = _scalar(atr_series)
        if atr is None or atr == 0:
            return max_pts * 0.3

        # Rolling ATR mean
        if hasattr(atr_series, "rolling"):
            avg_atr_series = atr_series.rolling(14).mean()
            avg_atr = _scalar(avg_atr_series)
        else:
            avg_atr = atr  # scalar indicator – treat as self-referential

        if avg_atr is None or avg_atr == 0:
            return max_pts * 0.3

        ratio = atr / avg_atr

        if 1.0 <= ratio <= 1.5:
            return max_pts          # ideal sweet spot
        elif 0.8 <= ratio < 1.0:
            return max_pts * 0.8    # slightly below average – still tradable
        elif 1.5 < ratio <= 2.0:
            return max_pts * 0.6    # elevated – trade with caution
        elif 2.0 < ratio <= 3.0:
            return max_pts * 0.3    # high – reduce size
        else:
            return max_pts * 0.1    # extreme or very low – avoid

    def _score_volume(self, df: pd.DataFrame, max_pts: float) -> float:
        """
        Volume component (0 – max_pts).

        Compares the latest bar's volume to the 20-period rolling average.
        """
        if "volume" not in df.columns:
            return max_pts * 0.3  # neutral fallback

        volume = _scalar(df["volume"])
        avg_volume = df["volume"].rolling(20).mean().iloc[-1]

        if volume is None or avg_volume is None or avg_volume == 0:
            return max_pts * 0.3

        ratio = volume / avg_volume

        if ratio >= 2.0:
            return max_pts          # strong volume surge
        elif ratio >= 1.5:
            return max_pts * 0.9
        elif ratio >= 1.2:
            return max_pts * 0.7
        elif ratio >= 1.0:
            return max_pts * 0.5
        elif ratio >= 0.7:
            return max_pts * 0.2
        else:
            return 0.0              # very low volume – no conviction

    def _score_momentum(
        self,
        df: pd.DataFrame,
        indicators: Dict,
        side: str,
        max_pts: float,
    ) -> float:
        """
        Momentum component (0 – max_pts).

        Sub-factors:
          * RSI position / direction (0 – max_pts/2)
          * MACD histogram alignment  (0 – max_pts/2)
        """
        half = max_pts / 2.0
        score = 0.0

        # --- RSI ---
        rsi = _scalar(
            indicators.get("rsi_9",
            indicators.get("rsi9",
            indicators.get("rsi_14",
            indicators.get("rsi14",
            indicators.get("rsi")))))
        )

        if rsi is not None:
            if side == "long":
                if 30 <= rsi <= 50:       # oversold recovery – ideal
                    score += half
                elif 50 < rsi <= 60:      # building momentum
                    score += half * 0.6
                elif rsi < 30:            # extreme oversold – riskier
                    score += half * 0.4
                else:                      # overbought – bad long entry
                    score += 0.0
            else:  # short
                if 50 <= rsi <= 70:       # overbought rejection – ideal
                    score += half
                elif 40 <= rsi < 50:      # fading momentum
                    score += half * 0.6
                elif rsi > 70:            # extreme overbought – riskier
                    score += half * 0.4
                else:                      # oversold – bad short entry
                    score += 0.0

        # --- MACD histogram ---
        macd_hist = _scalar(
            indicators.get("macd_hist",
            indicators.get("macd_histogram",
            indicators.get("histogram")))
        )

        if macd_hist is not None:
            if side == "long" and macd_hist > 0:
                score += half
            elif side == "short" and macd_hist < 0:
                score += half
            elif side == "long" and macd_hist < 0:
                # Histogram improving (less negative) still partial credit
                score += half * 0.2
            elif side == "short" and macd_hist > 0:
                score += half * 0.2

        return min(score, max_pts)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _classify(score: float) -> str:
        if score >= 90:
            return "Excellent"
        elif score >= 75:
            return "Good"
        elif score >= 60:
            return "Marginal"
        elif score >= 40:
            return "Weak"
        else:
            return "Poor"



# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _scalar(series) -> Optional[float]:
    """Return the last scalar value of a pandas Series or a plain number."""
    if series is None:
        return None
    if hasattr(series, "iloc"):
        if len(series) == 0:
            return None
        try:
            return float(series.iloc[-1])
        except (TypeError, ValueError):
            return None
    try:
        return float(series)
    except (TypeError, ValueError):
        return None
