"""
NIJA AI Trade Confidence Engine
================================

Scores every potential trade on an aggregate confidence scale (0–100) by
combining six independent signal dimensions:

1. **Regime Alignment** (0–20 pts)
   The current market regime must support the proposed trade direction.
   A STRONG_TREND regime with a long signal earns full marks; a RANGING
   regime with a trend-following signal earns near zero.

2. **RSI Confluence** (0–20 pts)
   Both RSI_9 and RSI_14 must agree on direction and sit in the optimal
   zone for the trade side.  Divergence between the two RSIs is penalised.

3. **Volume Confirmation** (0–20 pts)
   Volume must be elevated above its 20-bar mean.  Signals accompanied by
   thin volume are treated as lower conviction.

4. **Momentum Quality** (0–20 pts)
   MACD histogram direction and magnitude; EMA alignment; ADX strength.

5. **Market Structure** (0–10 pts)
   Price action relative to key moving averages (EMA 9/21/50).  Trades
   taken "with" the structure score higher.

6. **Volatility Context** (0–10 pts)
   ATR must be in a tradeable range — not too calm (no edge) and not in
   crisis mode (unpredictable exits).

Execution Gate
--------------
Trades with ``confidence_score >= CONFIDENCE_THRESHOLD`` (default 65) are
recommended for execution.  Below-threshold signals are logged and returned
with ``recommended_action = "WAIT"`` or ``"SKIP"``.

Integration
-----------
::

    from bot.ai_trade_confidence_engine import get_ai_trade_confidence_engine

    engine = get_ai_trade_confidence_engine()
    result = engine.evaluate(df, indicators, side="long", symbol="BTC-USD")

    if result["recommended_action"] == "EXECUTE":
        # Place order
        ...
    else:
        logger.info(f"Trade skipped: {result['reason']}")

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("nija.confidence_engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CONFIDENCE_THRESHOLD: float = 65.0   # minimum score to recommend execution
MAX_SCORE: float = 100.0

_COMPONENT_MAX = {
    "regime_alignment": 20.0,
    "rsi_confluence":   20.0,
    "volume":           20.0,
    "momentum":         20.0,
    "market_structure": 10.0,
    "volatility":       10.0,
}


# ---------------------------------------------------------------------------
# Data containers
# ---------------------------------------------------------------------------

@dataclass
class ConfidenceBreakdown:
    """Per-component score breakdown."""
    regime_alignment: float = 0.0
    rsi_confluence: float = 0.0
    volume: float = 0.0
    momentum: float = 0.0
    market_structure: float = 0.0
    volatility: float = 0.0

    @property
    def total(self) -> float:
        return (
            self.regime_alignment
            + self.rsi_confluence
            + self.volume
            + self.momentum
            + self.market_structure
            + self.volatility
        )

    def to_dict(self) -> Dict:
        return {
            "regime_alignment": round(self.regime_alignment, 2),
            "rsi_confluence": round(self.rsi_confluence, 2),
            "volume": round(self.volume, 2),
            "momentum": round(self.momentum, 2),
            "market_structure": round(self.market_structure, 2),
            "volatility": round(self.volatility, 2),
            "total": round(self.total, 2),
        }


@dataclass
class ConfidenceResult:
    """Full confidence evaluation result."""
    symbol: str
    side: str                              # "long" or "short"
    score: float                           # 0–100
    breakdown: ConfidenceBreakdown
    recommended_action: str                # "EXECUTE" / "WAIT" / "SKIP"
    reason: str
    regime: str = "unknown"
    regime_confidence: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict:
        return {
            "symbol": self.symbol,
            "side": self.side,
            "score": round(self.score, 2),
            "breakdown": self.breakdown.to_dict(),
            "recommended_action": self.recommended_action,
            "reason": self.reason,
            "regime": self.regime,
            "regime_confidence": round(self.regime_confidence, 4),
            "threshold": CONFIDENCE_THRESHOLD,
            "timestamp": self.timestamp.isoformat(),
        }


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class AITradeConfidenceEngine:
    """
    Scores trade confidence using six signal dimensions.

    Parameters
    ----------
    confidence_threshold:
        Minimum aggregate score to recommend execution (default: 65).
    use_regime_detector:
        When True, attempt to import and use ``MarketRegimeDetectionEngine``
        for regime-aligned scoring.  Falls back gracefully if unavailable.
    """

    def __init__(
        self,
        confidence_threshold: float = CONFIDENCE_THRESHOLD,
        use_regime_detector: bool = True,
    ):
        self.confidence_threshold = confidence_threshold
        self._regime_engine = None

        if use_regime_detector:
            try:
                from bot.market_regime_detector import get_market_regime_detector
                self._regime_engine = get_market_regime_detector()
                logger.info("Regime detector linked to confidence engine")
            except ImportError:
                try:
                    from market_regime_detector import get_market_regime_detector
                    self._regime_engine = get_market_regime_detector()
                    logger.info("Regime detector linked to confidence engine")
                except ImportError:
                    logger.warning(
                        "MarketRegimeDetectionEngine not available — "
                        "regime scoring will use fallback ADX heuristic"
                    )

        logger.info(
            f"AITradeConfidenceEngine ready (threshold={self.confidence_threshold})"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate(
        self,
        df: pd.DataFrame,
        indicators: Dict,
        side: str = "long",
        symbol: str = "UNKNOWN",
    ) -> Dict:
        """
        Evaluate trade confidence.

        Parameters
        ----------
        df:
            OHLCV DataFrame (``close``, ``high``, ``low``, ``volume``).
        indicators:
            Pre-computed indicator dict.  Recognised keys: ``adx``,
            ``rsi_9``, ``rsi_14``, ``rsi``, ``atr``, ``macd_histogram``,
            ``macd_hist``, ``ema_9``, ``ema_21``, ``ema_50``.
        side:
            ``"long"`` or ``"short"``.
        symbol:
            Trading pair label used for logging.

        Returns
        -------
        dict  (see ``ConfidenceResult.to_dict()``)
        """
        side = side.lower()
        breakdown = ConfidenceBreakdown()

        # --- regime ---
        regime_label, regime_conf = self._get_regime(df, indicators)
        breakdown.regime_alignment = self._score_regime_alignment(
            regime_label, regime_conf, side, indicators
        )

        # --- RSI confluence ---
        breakdown.rsi_confluence = self._score_rsi_confluence(indicators, side)

        # --- volume ---
        breakdown.volume = self._score_volume(df)

        # --- momentum ---
        breakdown.momentum = self._score_momentum(indicators, side)

        # --- market structure ---
        breakdown.market_structure = self._score_market_structure(df, indicators, side)

        # --- volatility context ---
        breakdown.volatility = self._score_volatility(df, indicators)

        score = min(breakdown.total, MAX_SCORE)
        action, reason = self._gate(score, symbol, side)

        result = ConfidenceResult(
            symbol=symbol,
            side=side,
            score=score,
            breakdown=breakdown,
            recommended_action=action,
            reason=reason,
            regime=regime_label,
            regime_confidence=regime_conf,
        )

        log_fn = logger.info if action == "EXECUTE" else logger.debug
        log_fn(
            f"[ConfidenceEngine] {symbol} {side.upper()} | "
            f"score={score:.1f}/100 | action={action} | {reason}"
        )
        return result.to_dict()

    def should_execute(self, score: float) -> bool:
        """Return True when *score* clears the execution threshold."""
        return score >= self.confidence_threshold

    # ------------------------------------------------------------------
    # Regime alignment (0–20 pts)
    # ------------------------------------------------------------------

    def _get_regime(
        self, df: pd.DataFrame, indicators: Dict
    ) -> Tuple[str, float]:
        """Return (regime_label, confidence) using detector or fallback."""
        if self._regime_engine is not None:
            try:
                snap = self._regime_engine.detect(df, indicators)
                return snap.regime.value, snap.confidence
            except Exception as exc:
                logger.debug(f"Regime engine error: {exc}")

        # Fallback: crude ADX heuristic
        adx = self._last(indicators, "adx", default=15.0)
        if adx >= 30:
            return "strong_trend", 0.8
        if adx >= 20:
            return "weak_trend", 0.6
        return "ranging", 0.5

    _LONG_FAVOURABLE_REGIMES = frozenset([
        "strong_trend", "weak_trend", "expansion", "momentum"
    ])
    _SHORT_FAVOURABLE_REGIMES = frozenset([
        "strong_trend", "weak_trend", "volatility_explosion"
    ])
    _NEUTRAL_REGIMES = frozenset(["ranging", "consolidation"])
    _ADVERSE_REGIMES = frozenset(["mean_reversion"])

    def _score_regime_alignment(
        self,
        regime: str,
        confidence: float,
        side: str,
        indicators: Dict,
    ) -> float:
        max_pts = _COMPONENT_MAX["regime_alignment"]
        adx = self._last(indicators, "adx", default=15.0)

        if side == "long":
            favourable = self._LONG_FAVOURABLE_REGIMES
        else:
            favourable = self._SHORT_FAVOURABLE_REGIMES

        if regime in favourable:
            base = 1.0
        elif regime in self._NEUTRAL_REGIMES:
            base = 0.5
        elif regime in self._ADVERSE_REGIMES:
            base = 0.2
        else:
            base = 0.4

        # Scale by regime confidence and ADX
        adx_factor = min(adx / 40.0, 1.0)
        score = max_pts * base * confidence * (0.6 + 0.4 * adx_factor)
        return round(min(score, max_pts), 2)

    # ------------------------------------------------------------------
    # RSI confluence (0–20 pts)
    # ------------------------------------------------------------------

    def _score_rsi_confluence(self, indicators: Dict, side: str) -> float:
        max_pts = _COMPONENT_MAX["rsi_confluence"]
        rsi_14 = self._last(indicators, "rsi_14", "rsi", default=50.0)
        rsi_9 = self._last(indicators, "rsi_9", default=rsi_14)
        score = 0.0

        if side == "long":
            # Ideal: RSI_9 in 45–65, RSI_14 in 40–65, both above 50
            if rsi_14 > 50:
                score += max_pts * 0.5
            if 45 <= rsi_9 <= 70:
                score += max_pts * 0.3
            if rsi_9 > rsi_14:
                score += max_pts * 0.2          # short-term momentum confirming
        else:
            if rsi_14 < 50:
                score += max_pts * 0.5
            if 30 <= rsi_9 <= 55:
                score += max_pts * 0.3
            if rsi_9 < rsi_14:
                score += max_pts * 0.2

        # Penalise extreme overextension
        if side == "long" and rsi_9 > 80:
            score *= 0.4
        if side == "short" and rsi_9 < 20:
            score *= 0.4

        return round(min(score, max_pts), 2)

    # ------------------------------------------------------------------
    # Volume confirmation (0–20 pts)
    # ------------------------------------------------------------------

    def _score_volume(self, df: pd.DataFrame) -> float:
        max_pts = _COMPONENT_MAX["volume"]
        if "volume" not in df.columns or len(df) < 20:
            return max_pts * 0.5            # neutral when data absent

        vol_now = float(df["volume"].iloc[-1])
        vol_mean = float(df["volume"].iloc[-20:].mean())
        if vol_mean <= 0:
            return max_pts * 0.5

        ratio = vol_now / vol_mean
        if ratio >= 2.0:
            pts = max_pts
        elif ratio >= 1.5:
            pts = max_pts * 0.85
        elif ratio >= 1.2:
            pts = max_pts * 0.65
        elif ratio >= 0.8:
            pts = max_pts * 0.40
        else:
            pts = 0.0                       # thin volume — no confirmation

        return round(min(pts, max_pts), 2)

    # ------------------------------------------------------------------
    # Momentum quality (0–20 pts)
    # ------------------------------------------------------------------

    def _score_momentum(self, indicators: Dict, side: str) -> float:
        max_pts = _COMPONENT_MAX["momentum"]
        adx = self._last(indicators, "adx", default=15.0)
        macd = self._last(indicators, "macd_histogram", "macd_hist", default=0.0)
        score = 0.0

        # ADX component (max 10 pts)
        adx_pts = min(adx / 40.0, 1.0) * (max_pts * 0.5)
        score += adx_pts

        # MACD histogram direction (max 10 pts)
        if (side == "long" and macd > 0) or (side == "short" and macd < 0):
            macd_pts = max_pts * 0.5
        else:
            macd_pts = 0.0
        score += macd_pts

        return round(min(score, max_pts), 2)

    # ------------------------------------------------------------------
    # Market structure (0–10 pts)
    # ------------------------------------------------------------------

    def _score_market_structure(
        self, df: pd.DataFrame, indicators: Dict, side: str
    ) -> float:
        max_pts = _COMPONENT_MAX["market_structure"]
        if len(df) < 2:
            return max_pts * 0.5

        close = float(df["close"].iloc[-1])
        ema_9 = self._last(indicators, "ema_9", default=close)
        ema_21 = self._last(indicators, "ema_21", default=close)
        ema_50 = self._last(indicators, "ema_50", default=close)

        bull_aligned = ema_9 > ema_21 > ema_50
        bear_aligned = ema_9 < ema_21 < ema_50
        price_above_50 = close > ema_50

        if side == "long":
            if bull_aligned and price_above_50:
                return max_pts
            if ema_9 > ema_21 or price_above_50:
                return max_pts * 0.5
            return 0.0
        else:
            if bear_aligned and not price_above_50:
                return max_pts
            if ema_9 < ema_21 or not price_above_50:
                return max_pts * 0.5
            return 0.0

    # ------------------------------------------------------------------
    # Volatility context (0–10 pts)
    # ------------------------------------------------------------------

    def _score_volatility(self, df: pd.DataFrame, indicators: Dict) -> float:
        max_pts = _COMPONENT_MAX["volatility"]
        close = float(df["close"].iloc[-1]) if len(df) else 1.0
        atr = self._last(indicators, "atr", default=0.0)
        atr_pct = (atr / close) if close > 0 else 0.0

        # ATR expansion ratio
        atr_series = indicators.get("atr")
        if atr_series is not None and hasattr(atr_series, "rolling") and len(atr_series) >= 14:
            atr_mean = float(atr_series.rolling(14).mean().iloc[-1])
            expansion = (atr / atr_mean) if atr_mean > 0 else 1.0
        else:
            expansion = 1.0

        # Optimal: moderate volatility (ATR_pct 0.5–3%), expansion 0.8–1.6
        if 0.005 <= atr_pct <= 0.03 and 0.8 <= expansion <= 1.6:
            return max_pts
        if atr_pct < 0.002 or expansion < 0.5:
            return max_pts * 0.2            # too calm — no edge
        if expansion > 2.5 or atr_pct > 0.06:
            return max_pts * 0.1            # crisis — unpredictable
        return max_pts * 0.5

    # ------------------------------------------------------------------
    # Execution gate
    # ------------------------------------------------------------------

    def _gate(self, score: float, symbol: str, side: str) -> Tuple[str, str]:
        if score >= self.confidence_threshold:
            return "EXECUTE", f"Score {score:.1f} ≥ threshold {self.confidence_threshold}"
        if score >= self.confidence_threshold * 0.75:
            return "WAIT", (
                f"Score {score:.1f} below threshold {self.confidence_threshold} "
                f"— marginal setup, wait for better conditions"
            )
        return "SKIP", (
            f"Score {score:.1f} well below threshold {self.confidence_threshold} "
            f"— low-quality setup rejected"
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _last(
        indicators: Dict,
        key: str,
        alt: Optional[str] = None,
        default: float = 0.0,
    ) -> float:
        v = indicators.get(key)
        if v is None and alt:
            v = indicators.get(alt)
        if v is None:
            return default
        if hasattr(v, "iloc"):
            return float(v.iloc[-1])
        return float(v)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_confidence_engine: Optional[AITradeConfidenceEngine] = None


def get_ai_trade_confidence_engine(
    confidence_threshold: float = CONFIDENCE_THRESHOLD,
) -> AITradeConfidenceEngine:
    """
    Return (or create) the module-level ``AITradeConfidenceEngine`` singleton.

    Parameters
    ----------
    confidence_threshold:
        Passed only on the *first* call (default: 65).
    """
    global _confidence_engine
    if _confidence_engine is None:
        _confidence_engine = AITradeConfidenceEngine(
            confidence_threshold=confidence_threshold
        )
    return _confidence_engine
