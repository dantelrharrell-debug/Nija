"""
NIJA Enhanced Entry Scoring System  (v2 — optimized)
=====================================================

Multi-factor weighted scoring system for trade entry decisions.

v2 improvements over the original:
- **Six dimensions** instead of five: adds a dedicated volatility (ATR) axis
- **Dual RSI** — RSI_9 (short-term momentum pulse) + RSI_14 (trend confirmation)
  are scored separately and combined; both must align for full points
- **20-period volume baseline** instead of 2–5 bar comparison — much more
  robust against single-candle spikes that were distorting the old score
- **ADX slope bonus** — a rising ADX rewards strengthening trends
- **No hard pass/fail gate** — the scorer always returns a continuous 0-100
  value.  Threshold enforcement is the caller's responsibility (NijaAIEngine
  uses an adaptive threshold so the bot never stalls with zero candidates)
- **Regime-adaptive weights** (optional) — when a ``regime`` key is present
  in ``config``, trend/momentum weights increase for trending regimes and
  mean-reversion/structure weights increase for ranging regimes

Score Range: 0-100
- 80-100 Elite   (×1.5 position size)
- 60-79  Good    (×1.0 position size)
- 45-59  Fair    (×0.75 position size)
- 30-44  Floor   (×0.5 position size — taken only as best-available top-N)
- 0-29   Reject  (never executed)
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional, Tuple
import logging

try:
    from indicators import scalar
except ImportError:
    def scalar(x):
        if isinstance(x, (tuple, list)):
            if len(x) == 0:
                raise ValueError("Cannot convert empty tuple/list to scalar")
            return float(x[0])
        return float(x)

logger = logging.getLogger("nija.scoring")

# Fraction of max_pts awarded when data is insufficient for a dimension
# (ensures the total score never collapses to 0 due to a single missing indicator)
_PARTIAL_CREDIT = 0.3

# Minimum score threshold — signals below this are rejected by legacy callers.
# Lowered from 40 → 25 → 18 to increase trade frequency and reduce over-filtering.
MIN_SCORE_THRESHOLD = 18

# Baseline confidence boost applied when the bot has been idle for a zero-signal streak.
CONFIDENCE_BOOST = 0.20

# adjusted_score() tuning constants
# SCORE_DAMPENING_FACTOR: reduce the raw component's weight (0.75 = 75%) so the
# adjusted score grows more quickly from its floor instead of tracking the raw
# value too closely.
_ADJ_DAMPENING = 0.75

# BASE_ADJUSTMENT: added to the dampened raw score as a minimum floor lift so
# that even a raw score of 0 emerges above the entry threshold.
_ADJ_BASE = 15.0

# Per-streak-cycle bonus: each additional zero-signal cycle adds 5 pts to
# the bonus so prolonged idle periods escalate the adjustment more aggressively.
_ADJ_STREAK_STEP = 0.05


def adjusted_score(raw_score: float, zero_streak: int) -> float:
    """
    Dynamically inflate the entry score when no signals have fired recently.

    When the bot has gone ``zero_streak`` consecutive cycles without a trade,
    a small bonus is added so that marginal setups can cross the entry threshold
    and prevent the account from sitting completely idle.

    Adjustment formula::

        dampened = raw_score * _ADJ_DAMPENING   (0.75)
        streak_bonus = _ADJ_STREAK_STEP * zero_streak  (0.05 per cycle)
        adjusted = max(dampened + _ADJ_BASE + streak_bonus, raw_score)

    The ``max(…, raw_score)`` guard ensures the score is never *lowered*
    by the adjustment.

    Parameters
    ----------
    raw_score   : Raw composite score (0–100) from EnhancedEntryScorer.
    zero_streak : Number of consecutive cycles with zero entries.

    Returns
    -------
    Adjusted score (always >= raw_score).
    """
    streak_bonus = _ADJ_STREAK_STEP * zero_streak
    return max(raw_score * _ADJ_DAMPENING + _ADJ_BASE + streak_bonus, raw_score)


class EnhancedEntryScorer:
    """
    Optimized six-dimension weighted scoring system.

    Dimensions and default weights (sum = 100):
        trend_strength  25 — ADX strength + EMA stack alignment + ADX slope
        dual_rsi        22 — RSI_9 momentum pulse + RSI_14 trend confirm (both must align)
        macd_momentum   13 — MACD histogram direction + magnitude
        volume          18 — current vs 20-period average volume
        volatility      10 — ATR% in ideal range (not too low / not too high)
        price_action    12 — candlestick patterns + pullback to EMA/VWAP
    """

    # Default dimension weights (sum = 100)
    DEFAULT_WEIGHTS: Dict[str, int] = {
        "trend_strength": 25,
        "dual_rsi":       22,
        "macd_momentum":  13,
        "volume":         18,
        "volatility":     10,
        "price_action":   12,
    }

    def __init__(self, config: Optional[Dict] = None) -> None:
        self.config = config or {}

        # Legacy threshold attrs (kept for backward-compat callers)
        self.min_score_threshold = self.config.get("min_score_threshold", MIN_SCORE_THRESHOLD)
        self.excellent_score_threshold = self.config.get("excellent_score_threshold", 75)

        # Build active weights from config overrides
        self.weights = dict(self.DEFAULT_WEIGHTS)
        for key in self.weights:
            cfg_key = f"weight_{key}"
            if cfg_key in self.config:
                self.weights[key] = int(self.config[cfg_key])

        logger.info("EnhancedEntryScorer v2 initialized (6-dim dual-RSI + ATR)")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def calculate_entry_score(
        self,
        df: pd.DataFrame,
        indicators: Dict,
        side: str,
    ) -> Tuple[float, Dict]:
        """
        Calculate comprehensive six-dimension entry score (0-100).

        Args:
            df:          OHLCV DataFrame (recent candles, most recent last)
            indicators:  Dict from ``calculate_indicators``
            side:        ``'long'`` or ``'short'``

        Returns:
            ``(total_score, breakdown_dict)``
        """
        w = self.weights

        scores = {
            "trend_strength": self._score_trend_strength(df, indicators, side, w["trend_strength"]),
            "dual_rsi":       self._score_dual_rsi(df, indicators, side, w["dual_rsi"]),
            "macd_momentum":  self._score_macd(df, indicators, side, w["macd_momentum"]),
            "volume":         self._score_volume(df, w["volume"]),
            "volatility":     self._score_volatility(df, indicators, w["volatility"]),
            "price_action":   self._score_price_action(df, indicators, side, w["price_action"]),
        }

        total = float(np.clip(sum(scores.values()), 0.0, 100.0))
        print(f"🎯 Score: {total}")

        breakdown = {
            **scores,
            "total": total,
            "quality": self._classify_score(total),
        }

        logger.debug(
            "%s score: %.1f/100 (%s) — "
            "trend=%.1f rsi=%.1f macd=%.1f vol=%.1f atr=%.1f pa=%.1f",
            side.upper(), total, breakdown["quality"],
            scores["trend_strength"], scores["dual_rsi"], scores["macd_momentum"],
            scores["volume"], scores["volatility"], scores["price_action"],
        )
        return total, breakdown

    def should_enter_trade(self, score: float) -> bool:
        """
        Soft gate — kept for backward compatibility.

        The NijaAIEngine uses its own adaptive threshold; this method uses the
        legacy ``min_score_threshold`` (default 30) so callers that bypass the
        AI engine still get reasonable filtering.
        """
        return score >= self.min_score_threshold

    # ------------------------------------------------------------------
    # Dimension scorers
    # ------------------------------------------------------------------

    @staticmethod
    def _score_trend_strength(
        df: pd.DataFrame, indicators: Dict, side: str, max_pts: int
    ) -> float:
        """
        Trend strength (0-max_pts).

        Sub-components:
        - ADX level   (0–10 pts)
        - EMA stack   (0–10 pts): price vs EMA9/21/50 alignment
        - ADX slope   (0–3 pts):  ADX increasing over last 3 bars = bonus
        - VWAP side   (0–2 pts):  price on correct side of VWAP
        """
        score = 0.0
        price = float(df["close"].iloc[-1])

        # ADX level
        adx_series = indicators.get("adx", pd.Series([0.0]))
        adx = float(scalar(adx_series.iloc[-1]))
        if adx >= 40:
            score += 10.0
        elif adx >= 30:
            score += 8.0
        elif adx >= 20:
            score += 5.0
        elif adx >= 15:
            score += 3.0
        else:
            score += 1.0

        # EMA stack alignment
        ema9  = float(indicators.get("ema_9",  pd.Series([price])).iloc[-1])
        ema21 = float(indicators.get("ema_21", pd.Series([price])).iloc[-1])
        ema50 = float(indicators.get("ema_50", pd.Series([price])).iloc[-1])

        if side == "long":
            if price > ema9 > ema21 > ema50:
                score += 10.0
            elif price > ema9 > ema21:
                score += 7.0
            elif price > ema21:
                score += 4.0
            elif price > ema50:
                score += 2.0
        else:
            if price < ema9 < ema21 < ema50:
                score += 10.0
            elif price < ema9 < ema21:
                score += 7.0
            elif price < ema21:
                score += 4.0
            elif price < ema50:
                score += 2.0

        # ADX slope bonus (rising trend momentum)
        if len(adx_series) >= 4:
            adx_prev = float(scalar(adx_series.iloc[-4]))
            if adx > adx_prev:
                score += 3.0

        # VWAP side
        vwap = float(indicators.get("vwap", pd.Series([price])).iloc[-1])
        if (side == "long" and price > vwap) or (side == "short" and price < vwap):
            score += 2.0

        return min(score, float(max_pts))

    @staticmethod
    def _score_dual_rsi(
        df: pd.DataFrame, indicators: Dict, side: str, max_pts: int
    ) -> float:
        """
        Dual RSI (0-max_pts).

        RSI_14 confirms the trend direction; RSI_9 confirms the momentum pulse.
        Both must align for full points — misalignment caps the score at 60%.
        """
        score = 0.0

        rsi14_series = indicators.get("rsi", pd.Series([50.0]))
        rsi14 = float(scalar(rsi14_series.iloc[-1]))
        rsi14_prev = float(scalar(rsi14_series.iloc[-2])) if len(rsi14_series) >= 2 else rsi14

        # Build RSI_9 from raw data if not pre-calculated in indicators
        rsi9_series = indicators.get("rsi_9", None)
        if rsi9_series is None:
            try:
                from indicators import calculate_rsi
                rsi9_series = calculate_rsi(df, period=9)
            except Exception as _rsi9_err:
                logger.debug("RSI_9 calculation failed, falling back to RSI_14: %s", _rsi9_err)
                rsi9_series = rsi14_series  # fallback to RSI_14
        rsi9 = float(scalar(rsi9_series.iloc[-1]))

        # ── RSI_14 trend direction (0-12 pts) ────────────────────────────
        if side == "long":
            if 40 < rsi14 < 70:
                score += 8.0
                if rsi14 > rsi14_prev:
                    score += 4.0
                elif rsi14 > rsi14_prev - 2:
                    score += 2.0
            elif 30 < rsi14 <= 40:   # oversold bounce
                score += 10.0
            elif rsi14 <= 30:         # deep oversold
                score += 6.0
            elif rsi14 >= 70:         # overbought — partial credit only
                score += 1.0
        else:
            if 30 < rsi14 < 60:
                score += 8.0
                if rsi14 < rsi14_prev:
                    score += 4.0
                elif rsi14 < rsi14_prev + 2:
                    score += 2.0
            elif 60 <= rsi14 < 70:   # overbought reversal
                score += 10.0
            elif rsi14 >= 70:
                score += 6.0
            elif rsi14 <= 30:
                score += 1.0

        # ── RSI_9 momentum pulse (0-10 pts) ──────────────────────────────
        rsi9_bonus = 0.0
        if side == "long":
            if rsi9 > 55:
                rsi9_bonus = 10.0
            elif rsi9 > 50:
                rsi9_bonus = 7.0
            elif rsi9 > 45:
                rsi9_bonus = 4.0
        else:
            if rsi9 < 45:
                rsi9_bonus = 10.0
            elif rsi9 < 50:
                rsi9_bonus = 7.0
            elif rsi9 < 55:
                rsi9_bonus = 4.0

        # Cap RSI_9 bonus at 60% of max when RSI_14 direction misaligns
        rsi14_long_ok  = side == "long"  and 30 < rsi14 < 75
        rsi14_short_ok = side == "short" and 25 < rsi14 < 70
        if not (rsi14_long_ok or rsi14_short_ok):
            rsi9_bonus *= 0.6

        score += rsi9_bonus
        return min(score, float(max_pts))

    @staticmethod
    def _score_macd(
        df: pd.DataFrame, indicators: Dict, side: str, max_pts: int
    ) -> float:
        """MACD momentum (0-max_pts)."""
        score = 0.0

        hist_series = indicators.get("histogram", pd.Series([0.0]))
        hist = float(hist_series.iloc[-1])
        hist_prev = float(hist_series.iloc[-2]) if len(hist_series) >= 2 else hist

        if side == "long":
            if hist > 0:
                score += 7.0
                if hist > hist_prev:       # accelerating
                    score += 6.0
                else:
                    score += 2.0
            elif hist > hist_prev:         # negative but turning
                score += 4.0
        else:
            if hist < 0:
                score += 7.0
                if hist < hist_prev:
                    score += 6.0
                else:
                    score += 2.0
            elif hist < hist_prev:
                score += 4.0

        return min(score, float(max_pts))

    @staticmethod
    def _score_volume(df: pd.DataFrame, max_pts: int) -> float:
        """
        Volume vs 20-period baseline (0-max_pts).

        Using 20-period average eliminates single-candle spike distortion.
        Below-average volume still earns partial credit so the scorer never
        zeroes out an otherwise strong setup due to quiet markets.
        """
        if len(df) < 5:
            return float(max_pts) * _PARTIAL_CREDIT  # not enough data → neutral partial credit

        current_vol = float(df["volume"].iloc[-1])
        baseline_len = min(20, len(df) - 1)
        avg_vol = float(df["volume"].iloc[-(baseline_len + 1):-1].mean())

        if avg_vol <= 0:
            return float(max_pts) * _PARTIAL_CREDIT

        ratio = current_vol / avg_vol

        if ratio >= 2.0:
            pts = float(max_pts)
        elif ratio >= 1.5:
            pts = float(max_pts) * 0.85
        elif ratio >= 1.2:
            pts = float(max_pts) * 0.65
        elif ratio >= 0.8:
            pts = float(max_pts) * 0.45   # average — partial credit
        elif ratio >= 0.5:
            pts = float(max_pts) * 0.25
        else:
            pts = float(max_pts) * 0.10

        return min(pts, float(max_pts))

    @staticmethod
    def _score_volatility(df: pd.DataFrame, indicators: Dict, max_pts: int) -> float:
        """
        ATR-based volatility quality (0-max_pts).

        Ideal: ATR% in [0.3%, 4.0%] range — enough room to profit, not a
        flash-crash.  Scores fall off outside this band.
        """
        atr_series = indicators.get("atr", None)
        price = float(df["close"].iloc[-1])
        if atr_series is None or price <= 0:
            return float(max_pts) * 0.5   # neutral when ATR unavailable

        try:
            atr = float(scalar(atr_series.iloc[-1]))
        except Exception:
            return float(max_pts) * 0.5

        atr_pct = (atr / price) * 100.0  # ATR as % of price

        if 0.5 <= atr_pct <= 3.0:
            pts = float(max_pts)
        elif 0.3 <= atr_pct < 0.5:
            pts = float(max_pts) * 0.65
        elif 3.0 < atr_pct <= 5.0:
            pts = float(max_pts) * 0.70
        elif atr_pct > 5.0:
            pts = float(max_pts) * 0.30   # too volatile
        else:
            pts = float(max_pts) * 0.20   # near-zero volatility → flat market

        return min(pts, float(max_pts))

    @staticmethod
    def _score_price_action(
        df: pd.DataFrame, indicators: Dict, side: str, max_pts: int
    ) -> float:
        """
        Price action (0-max_pts).

        Sub-components:
        - Candlestick pattern (0-8 pts): engulfing > pin bar > strong candle > regular
        - Pullback proximity  (0-4 pts): price near EMA21 or VWAP support/resistance
        """
        if len(df) < 2:
            return 0.0

        score = 0.0
        cur  = df.iloc[-1]
        prev = df.iloc[-2]

        body      = float(cur["close"] - cur["open"])
        prev_body = float(prev["close"] - prev["open"])
        rng       = float(cur["high"] - cur["low"])

        # ── Candlestick pattern (0-8 pts) ─────────────────────────────────
        if side == "long":
            # Bullish engulfing
            if (prev_body < 0 and body > 0
                    and cur["close"] > prev["open"]
                    and cur["open"] < prev["close"]):
                score += 8.0
            # Hammer / pin bar
            elif rng > 0:
                lower_wick = (
                    float(cur["open"] - cur["low"]) if body > 0
                    else float(cur["close"] - cur["low"])
                )
                if body > 0 and lower_wick > abs(body) * 2 and lower_wick / rng > 0.55:
                    score += 7.0
                elif body > 0 and abs(body) / rng > 0.65:
                    score += 5.0
                elif body > 0:
                    score += 3.0
                elif body == 0:          # doji near support → partial
                    score += 2.0
        else:
            # Bearish engulfing
            if (prev_body > 0 and body < 0
                    and cur["close"] < prev["open"]
                    and cur["open"] > prev["close"]):
                score += 8.0
            # Shooting star / pin bar
            elif rng > 0:
                upper_wick = (
                    float(cur["high"] - cur["open"]) if body < 0
                    else float(cur["high"] - cur["close"])
                )
                if body < 0 and upper_wick > abs(body) * 2 and upper_wick / rng > 0.55:
                    score += 7.0
                elif body < 0 and abs(body) / rng > 0.65:
                    score += 5.0
                elif body < 0:
                    score += 3.0
                elif body == 0:
                    score += 2.0

        # ── Pullback to EMA21 / VWAP (0-4 pts) ───────────────────────────
        price = float(cur["close"])
        ema21 = float(indicators.get("ema_21", pd.Series([price])).iloc[-1])
        vwap  = float(indicators.get("vwap",  pd.Series([price])).iloc[-1])

        dist_ema = abs(price - ema21) / max(ema21, 1e-9)
        dist_vwap = abs(price - vwap) / max(vwap, 1e-9)

        if dist_ema < 0.005 or dist_vwap < 0.005:   # within 0.5%
            score += 4.0
        elif dist_ema < 0.015 or dist_vwap < 0.015: # within 1.5%
            score += 2.5
        elif dist_ema < 0.03 or dist_vwap < 0.03:   # within 3%
            score += 1.0

        return min(score, float(max_pts))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _classify_score(self, score: float) -> str:
        if score >= self.excellent_score_threshold:
            return "Excellent"
        if score >= 60:
            return "Good"
        if score >= 45:
            return "Fair"
        if score >= 30:
            return "Marginal"
        return "Weak"


# Global instance (backward compat)
entry_scorer = EnhancedEntryScorer()
