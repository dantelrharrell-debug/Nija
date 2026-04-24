"""
NIJA AI Market Regime Engine — Bull / Bear / Sideways Classifier
================================================================

A lightweight, self-contained market-regime classifier that maps any price
series to one of three actionable macro states:

  * **BULL**     — sustained uptrend; trend-following strategies preferred.
  * **BEAR**     — sustained downtrend; defensive / short strategies preferred.
  * **SIDEWAYS** — range-bound / low-momentum; mean-reversion strategies preferred.

Each classification comes with a **confidence score (0–100)** and an
**ensemble breakdown** showing how each sub-indicator voted.

Detection pillars
-----------------
1. **Trend Strength** — EMA(20) vs EMA(50) crossover with ADX confirmation.
2. **Momentum** — Rate-of-change (ROC-14) and RSI(14) dual reading.
3. **Volatility Regime** — ATR-based normalised volatility (low vol → sideways,
   high vol → trending or bear).
4. **Price Position** — Current price relative to 20-period high/low channel.
5. **Volume Confirmation** — Volume trend agreement with price direction.

The five pillars are weighted and combined into one probability distribution
over [BULL, BEAR, SIDEWAYS]; the argmax is the final regime.

Public API
----------
::

    from bot.ai_regime_engine import get_ai_regime_engine

    engine = get_ai_regime_engine()

    result = engine.classify(df)   # pandas DataFrame with OHLCV columns
    print(result.regime)           # "BULL" | "BEAR" | "SIDEWAYS"
    print(result.confidence)       # float 0–100
    print(result.probabilities)    # {"BULL": 0.7, "BEAR": 0.1, "SIDEWAYS": 0.2}

    # Notify on confirmed regime transitions:
    engine.record_transition(old_regime="SIDEWAYS", new_regime="BULL")

    # Full history & stats:
    print(engine.get_status())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np

try:
    import pandas as pd
    _PANDAS_AVAILABLE = True
except ImportError:
    _PANDAS_AVAILABLE = False
    pd = None  # type: ignore

logger = logging.getLogger("nija.ai_regime_engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REGIMES: List[str] = ["BULL", "BEAR", "SIDEWAYS"]

# Pillar weights (must sum to 1.0)
WEIGHT_TREND: float = 0.30
WEIGHT_MOMENTUM: float = 0.25
WEIGHT_VOLATILITY: float = 0.20
WEIGHT_PRICE_POSITION: float = 0.15
WEIGHT_VOLUME: float = 0.10

# EMA periods
EMA_FAST: int = 20
EMA_SLOW: int = 50

# ADX threshold for trending regime
ADX_TRENDING: float = 20.0

# RSI thresholds
RSI_OVERBOUGHT: float = 60.0
RSI_OVERSOLD: float = 40.0

# ROC period
ROC_PERIOD: int = 14

# Confidence mapping
CONFIDENCE_HIGH: float = 70.0   # majority ≥ 70% → high confidence
CONFIDENCE_LOW: float = 40.0    # majority < 40% → low confidence

# History tracking
MAX_REGIME_HISTORY: int = 100


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class RegimeResult:
    """Classification result returned by ``classify()``."""
    regime: str                          # "BULL" | "BEAR" | "SIDEWAYS"
    confidence: float                    # 0–100
    probabilities: Dict[str, float]      # {"BULL": x, "BEAR": y, "SIDEWAYS": z}
    pillar_votes: Dict[str, str]         # pillar_name → "BULL"/"BEAR"/"SIDEWAYS"
    adx: float = 0.0
    rsi: float = 50.0
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class _RegimeTransition:
    old_regime: str
    new_regime: str
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# Internal indicator helpers
# ---------------------------------------------------------------------------


def _ema(series: "np.ndarray", period: int) -> "np.ndarray":
    """Compute exponential moving average without pandas dependency."""
    alpha = 2.0 / (period + 1)
    result = np.full_like(series, np.nan, dtype=float)
    if len(series) < period:
        return result
    result[period - 1] = np.mean(series[:period])
    for i in range(period, len(series)):
        result[i] = alpha * series[i] + (1 - alpha) * result[i - 1]
    return result


def _rsi(close: "np.ndarray", period: int = 14) -> float:
    """Return the most recent RSI value."""
    if len(close) < period + 1:
        return 50.0
    deltas = np.diff(close[-(period + 1):])
    gains = np.where(deltas > 0, deltas, 0.0)
    losses = np.where(deltas < 0, -deltas, 0.0)
    avg_gain = np.mean(gains) or 1e-10
    avg_loss = np.mean(losses) or 1e-10
    rs = avg_gain / avg_loss
    return float(100.0 - 100.0 / (1.0 + rs))


def _adx(high: "np.ndarray", low: "np.ndarray", close: "np.ndarray", period: int = 14) -> float:
    """Return the most recent ADX value (simplified computation)."""
    n = len(close)
    if n < period + 2:
        return 0.0

    tr_list = []
    plus_dm_list = []
    minus_dm_list = []

    for i in range(1, n):
        h, l, c_prev = high[i], low[i], close[i - 1]
        tr = max(h - l, abs(h - c_prev), abs(l - c_prev))
        tr_list.append(tr)
        up = high[i] - high[i - 1]
        dn = low[i - 1] - low[i]
        plus_dm_list.append(up if up > dn and up > 0 else 0.0)
        minus_dm_list.append(dn if dn > up and dn > 0 else 0.0)

    tr_arr = np.array(tr_list[-period:])
    pdm_arr = np.array(plus_dm_list[-period:])
    mdm_arr = np.array(minus_dm_list[-period:])

    tr_sum = np.sum(tr_arr) or 1e-10
    plus_di = 100 * np.sum(pdm_arr) / tr_sum
    minus_di = 100 * np.sum(mdm_arr) / tr_sum
    dx = 100 * abs(plus_di - minus_di) / max(plus_di + minus_di, 1e-10)
    return float(dx)


# ---------------------------------------------------------------------------
# AIRegimeEngine
# ---------------------------------------------------------------------------


class AIRegimeEngine:
    """
    Bull / Bear / Sideways market regime classifier.

    Thread-safe singleton via ``get_ai_regime_engine()``.
    """

    def __init__(
        self,
        ema_fast: int = EMA_FAST,
        ema_slow: int = EMA_SLOW,
        roc_period: int = ROC_PERIOD,
        min_bars: int = 55,
    ) -> None:
        self._lock = threading.Lock()
        self._ema_fast = ema_fast
        self._ema_slow = ema_slow
        self._roc_period = roc_period
        self._min_bars = min_bars

        self._last_result: Optional[RegimeResult] = None
        self._history: Deque[RegimeResult] = deque(maxlen=MAX_REGIME_HISTORY)
        self._transitions: Deque[_RegimeTransition] = deque(maxlen=MAX_REGIME_HISTORY)
        self._regime_counts: Dict[str, int] = {r: 0 for r in REGIMES}

        logger.info("=" * 60)
        logger.info("🤖 AI Market Regime Engine initialised")
        logger.info("   EMA periods   : fast=%d  slow=%d", ema_fast, ema_slow)
        logger.info("   min_bars      : %d", min_bars)
        logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Core classification
    # ------------------------------------------------------------------

    def classify(self, df: Any) -> RegimeResult:
        """
        Classify the current market regime from price/volume data.

        Parameters
        ----------
        df : pandas.DataFrame
            Must contain at minimum a ``close`` column.  Optional columns:
            ``high``, ``low``, ``volume``.  Rows should be sorted oldest-first.

        Returns
        -------
        RegimeResult
            Regime label, confidence, probability distribution, and per-pillar votes.
        """
        with self._lock:
            result = self._classify_internal(df)
            self._last_result = result
            self._history.append(result)
            self._regime_counts[result.regime] += 1
            return result

    def _classify_internal(self, df: Any) -> RegimeResult:
        """Internal classification — must be called while holding self._lock."""
        # Extract arrays
        close = self._get_col(df, "close")
        high = self._get_col(df, "high") if self._has_col(df, "high") else close
        low = self._get_col(df, "low") if self._has_col(df, "low") else close
        volume = self._get_col(df, "volume") if self._has_col(df, "volume") else None

        n = len(close)

        if n < self._min_bars:
            logger.debug("Insufficient bars (%d < %d) — defaulting to SIDEWAYS", n, self._min_bars)
            return RegimeResult(
                regime="SIDEWAYS",
                confidence=0.0,
                probabilities={"BULL": 0.33, "BEAR": 0.33, "SIDEWAYS": 0.34},
                pillar_votes={},
            )

        votes: Dict[str, str] = {}

        # ── Pillar 1: Trend (EMA crossover + ADX) ─────────────────────
        ema_fast_arr = _ema(close, self._ema_fast)
        ema_slow_arr = _ema(close, self._ema_slow)
        ema_f = ema_fast_arr[-1]
        ema_s = ema_slow_arr[-1]
        adx_val = _adx(high, low, close, 14)

        if not np.isnan(ema_f) and not np.isnan(ema_s):
            if ema_f > ema_s and adx_val >= ADX_TRENDING:
                votes["trend"] = "BULL"
            elif ema_f < ema_s and adx_val >= ADX_TRENDING:
                votes["trend"] = "BEAR"
            else:
                votes["trend"] = "SIDEWAYS"
        else:
            votes["trend"] = "SIDEWAYS"

        # ── Pillar 2: Momentum (RSI + ROC) ────────────────────────────
        rsi_val = _rsi(close, 14)
        roc_val = (
            ((close[-1] - close[-self._roc_period]) / (close[-self._roc_period] or 1e-10)) * 100
            if n >= self._roc_period
            else 0.0
        )

        if rsi_val >= RSI_OVERBOUGHT and roc_val > 0:
            votes["momentum"] = "BULL"
        elif rsi_val <= RSI_OVERSOLD and roc_val < 0:
            votes["momentum"] = "BEAR"
        else:
            votes["momentum"] = "SIDEWAYS"

        # ── Pillar 3: Volatility regime (ATR-based) ───────────────────
        atr = self._calc_atr(high, low, close, 14)
        normalised_atr = atr / (close[-1] or 1e-10)  # ATR as % of price

        if normalised_atr < 0.01:
            # Low volatility → sideways
            votes["volatility"] = "SIDEWAYS"
        elif normalised_atr > 0.04:
            # High volatility → follow trend pillar
            votes["volatility"] = votes.get("trend", "BULL")
        else:
            votes["volatility"] = "SIDEWAYS"

        # ── Pillar 4: Price position in recent channel ─────────────────
        window = min(20, n)
        recent_high = float(np.max(high[-window:]))
        recent_low = float(np.min(low[-window:]))
        channel = recent_high - recent_low or 1e-10
        price_position = (close[-1] - recent_low) / channel  # 0 = bottom, 1 = top

        if price_position >= 0.7:
            votes["price_position"] = "BULL"
        elif price_position <= 0.3:
            votes["price_position"] = "BEAR"
        else:
            votes["price_position"] = "SIDEWAYS"

        # ── Pillar 5: Volume confirmation ──────────────────────────────
        if volume is not None and len(volume) >= 10:
            recent_vol = float(np.mean(volume[-5:]))
            older_vol = float(np.mean(volume[-10:-5])) or 1e-10
            vol_ratio = recent_vol / older_vol
            price_up = close[-1] > close[-5]
            if vol_ratio >= 1.2 and price_up:
                votes["volume"] = "BULL"
            elif vol_ratio >= 1.2 and not price_up:
                votes["volume"] = "BEAR"
            else:
                votes["volume"] = "SIDEWAYS"
        else:
            votes["volume"] = "SIDEWAYS"

        # ── Weighted probability aggregation ──────────────────────────
        weights = {
            "trend": WEIGHT_TREND,
            "momentum": WEIGHT_MOMENTUM,
            "volatility": WEIGHT_VOLATILITY,
            "price_position": WEIGHT_PRICE_POSITION,
            "volume": WEIGHT_VOLUME,
        }

        probs: Dict[str, float] = {"BULL": 0.0, "BEAR": 0.0, "SIDEWAYS": 0.0}
        for pillar, vote in votes.items():
            w = weights.get(pillar, 0.0)
            probs[vote] = probs.get(vote, 0.0) + w

        total = sum(probs.values()) or 1.0
        probs = {k: round(v / total, 4) for k, v in probs.items()}

        best_regime = max(probs, key=lambda k: probs[k])
        confidence = round(probs[best_regime] * 100, 1)

        return RegimeResult(
            regime=best_regime,
            confidence=confidence,
            probabilities=probs,
            pillar_votes=votes,
            adx=round(adx_val, 2),
            rsi=round(rsi_val, 2),
        )

    # ------------------------------------------------------------------
    # Transition tracking
    # ------------------------------------------------------------------

    def record_transition(self, old_regime: str, new_regime: str) -> None:
        """Record a confirmed regime transition for analytics."""
        with self._lock:
            self._transitions.append(
                _RegimeTransition(old_regime=old_regime, new_regime=new_regime)
            )
            logger.info("📊 Regime transition: %s → %s", old_regime, new_regime)

    # ------------------------------------------------------------------
    # Status / reporting
    # ------------------------------------------------------------------

    def get_last_result(self) -> Optional[RegimeResult]:
        """Return the most recent classification result."""
        with self._lock:
            return self._last_result

    def get_status(self) -> Dict[str, Any]:
        """Return a serialisable snapshot of engine state."""
        with self._lock:
            last = self._last_result
            return {
                "engine": "AIRegimeEngine",
                "version": "1.0",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "current_regime": last.regime if last else None,
                "current_confidence": last.confidence if last else None,
                "current_probabilities": last.probabilities if last else {},
                "regime_counts": dict(self._regime_counts),
                "total_classifications": len(self._history),
                "total_transitions": len(self._transitions),
                "recent_transitions": [
                    {"old": t.old_regime, "new": t.new_regime, "at": t.timestamp}
                    for t in list(self._transitions)[-5:]
                ],
                "config": {
                    "ema_fast": self._ema_fast,
                    "ema_slow": self._ema_slow,
                    "roc_period": self._roc_period,
                    "min_bars": self._min_bars,
                },
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _get_col(df: Any, col: str) -> "np.ndarray":
        """Extract a named column from a DataFrame or dict as a numpy array."""
        if _PANDAS_AVAILABLE and isinstance(df, pd.DataFrame):
            return df[col].to_numpy(dtype=float)
        if isinstance(df, dict):
            return np.array(df[col], dtype=float)
        raise TypeError(f"Unsupported data type: {type(df)}")

    @staticmethod
    def _has_col(df: Any, col: str) -> bool:
        if _PANDAS_AVAILABLE and isinstance(df, pd.DataFrame):
            return col in df.columns
        if isinstance(df, dict):
            return col in df
        return False

    @staticmethod
    def _calc_atr(high: "np.ndarray", low: "np.ndarray", close: "np.ndarray", period: int) -> float:
        n = len(close)
        if n < 2:
            return 0.0
        trs = []
        for i in range(max(1, n - period), n):
            tr = max(high[i] - low[i], abs(high[i] - close[i - 1]), abs(low[i] - close[i - 1]))
            trs.append(tr)
        return float(np.mean(trs)) if trs else 0.0


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[AIRegimeEngine] = None
_instance_lock = threading.Lock()


def get_ai_regime_engine(**kwargs) -> AIRegimeEngine:
    """
    Return the process-wide ``AIRegimeEngine`` singleton.

    Keyword arguments are forwarded to the constructor on first call only.
    """
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = AIRegimeEngine(**kwargs)
        return _instance


__all__ = [
    "RegimeResult",
    "AIRegimeEngine",
    "get_ai_regime_engine",
]
