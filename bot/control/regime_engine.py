"""
NIJA Control Layer — Regime Engine
====================================

Detects the current market regime from OHLCV data using a multi-indicator
ensemble (ADX, RSI, Bollinger Bands, ATR volatility).

Regimes
-------
TRENDING        — ADX > 25, clear directional momentum
RANGING         — ADX < 20, price oscillating within a band
BREAKOUT        — ADX rising fast, BB squeeze releasing, volume spike
MEAN_REVERSION  — RSI extreme (< 30 or > 70) + price at BB boundary
UNKNOWN         — insufficient data or conflicting signals

Redis Caching
-------------
Detected regimes are stored in Redis under::

    nija:control:regime:{symbol}   TTL = NIJA_REGIME_REDIS_TTL_SECONDS (300 s)

Author: NIJA Trading Systems
Phase:  1 — Control Layer
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger("nija.control.regime")

# ---------------------------------------------------------------------------
# Environment-driven configuration
# ---------------------------------------------------------------------------

_REGIME_DETECTOR_ENABLED: bool = (
    os.getenv("NIJA_REGIME_DETECTOR_ENABLED", "true").lower() == "true"
)
_REGIME_REDIS_TTL: int = int(os.getenv("NIJA_REGIME_REDIS_TTL_SECONDS", "300"))

# ADX thresholds
_ADX_TRENDING_MIN: float = 25.0
_ADX_RANGING_MAX: float = 20.0
_ADX_BREAKOUT_DELTA: float = 5.0   # ADX must rise by this much in last N bars

# RSI thresholds for mean-reversion
_RSI_OVERSOLD: float = 30.0
_RSI_OVERBOUGHT: float = 70.0

# Bollinger Band squeeze threshold (BB width / price)
_BB_SQUEEZE_PCT: float = 0.02      # < 2% width = squeeze
_BB_PERIOD: int = 20
_BB_STD: float = 2.0

# Minimum bars required for reliable detection
_MIN_BARS: int = 30


# ---------------------------------------------------------------------------
# Enums & data structures
# ---------------------------------------------------------------------------

class MarketRegime(Enum):
    TRENDING        = "trending"
    RANGING         = "ranging"
    BREAKOUT        = "breakout"
    MEAN_REVERSION  = "mean_reversion"
    UNKNOWN         = "unknown"


@dataclass
class RegimeResult:
    """Full output of one regime detection pass."""
    regime: MarketRegime
    confidence: float          # [0.0, 1.0]
    adx: float
    rsi: float
    volatility: float          # ATR as % of price
    bb_width_pct: float        # Bollinger Band width as % of mid
    context: Dict[str, Any]
    symbol: str
    detected_at: str

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["regime"] = self.regime.value
        return d


# ---------------------------------------------------------------------------
# RegimeEngine
# ---------------------------------------------------------------------------

class RegimeEngine:
    """
    Detects market regime from OHLCV DataFrame.

    Thread-safe.  Use ``get_regime_engine()`` for the process singleton.
    """

    def __init__(self, redis_client=None) -> None:
        self._redis = redis_client
        self._lock = threading.Lock()
        logger.info(
            "RegimeEngine initialised (enabled=%s, redis_ttl=%ds)",
            _REGIME_DETECTOR_ENABLED, _REGIME_REDIS_TTL,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def detect(self, symbol: str, df: pd.DataFrame) -> RegimeResult:
        """
        Detect the current market regime for *symbol* from *df*.

        Parameters
        ----------
        symbol : str
            Instrument identifier (e.g. "BTC-USD").
        df : pd.DataFrame
            OHLCV data with columns: open, high, low, close, volume.
            Must have at least ``_MIN_BARS`` rows.

        Returns
        -------
        RegimeResult
            Always returns a result; falls back to UNKNOWN on errors.
        """
        if not _REGIME_DETECTOR_ENABLED:
            return self._unknown_result(symbol, "regime_detector_disabled")

        # Check Redis cache first
        cached = self._load_from_redis(symbol)
        if cached is not None:
            return cached

        try:
            result = self._compute_regime(symbol, df)
        except Exception as exc:
            logger.warning("RegimeEngine: detection failed for %s: %s", symbol, exc)
            result = self._unknown_result(symbol, f"detection_error:{exc}")

        self._store_to_redis(symbol, result)
        return result

    def detect_from_dict(self, symbol: str, ohlcv: Dict[str, Any]) -> RegimeResult:
        """Convenience wrapper: detect from a dict of lists."""
        df = pd.DataFrame(ohlcv)
        return self.detect(symbol, df)

    # ------------------------------------------------------------------
    # Core detection logic
    # ------------------------------------------------------------------

    def _compute_regime(self, symbol: str, df: pd.DataFrame) -> RegimeResult:
        if len(df) < _MIN_BARS:
            return self._unknown_result(symbol, f"insufficient_bars:{len(df)}<{_MIN_BARS}")

        df = df.copy()
        df.columns = [c.lower() for c in df.columns]

        adx, plus_di, minus_di = self._calc_adx(df)
        rsi = self._calc_rsi(df)
        atr = self._calc_atr(df)
        bb_width_pct = self._calc_bb_width_pct(df)

        price = float(df["close"].iloc[-1])
        volatility = float(atr / price) if price > 0 else 0.0

        context: Dict[str, Any] = {
            "adx":         round(adx, 2),
            "plus_di":     round(plus_di, 2),
            "minus_di":    round(minus_di, 2),
            "rsi":         round(rsi, 2),
            "atr":         round(atr, 4),
            "bb_width_pct": round(bb_width_pct, 4),
            "bars":        len(df),
        }

        regime, confidence = self._classify(adx, rsi, bb_width_pct, df)

        return RegimeResult(
            regime=regime,
            confidence=round(confidence, 4),
            adx=round(adx, 2),
            rsi=round(rsi, 2),
            volatility=round(volatility, 6),
            bb_width_pct=round(bb_width_pct, 4),
            context=context,
            symbol=symbol.upper(),
            detected_at=datetime.now(timezone.utc).isoformat(),
        )

    def _classify(
        self,
        adx: float,
        rsi: float,
        bb_width_pct: float,
        df: pd.DataFrame,
    ) -> Tuple[MarketRegime, float]:
        """
        Rule-based regime classification.

        Returns (regime, confidence).
        """
        # --- BREAKOUT: BB squeeze releasing + ADX rising ---
        adx_rising = self._is_adx_rising(df)
        if bb_width_pct < _BB_SQUEEZE_PCT and adx_rising and adx > _ADX_RANGING_MAX:
            confidence = min(0.95, 0.60 + (adx - _ADX_RANGING_MAX) / 50.0)
            return MarketRegime.BREAKOUT, confidence

        # --- TRENDING: strong ADX ---
        if adx >= _ADX_TRENDING_MIN:
            confidence = min(0.95, 0.55 + (adx - _ADX_TRENDING_MIN) / 50.0)
            return MarketRegime.TRENDING, confidence

        # --- MEAN_REVERSION: RSI extreme + price at BB boundary ---
        if rsi <= _RSI_OVERSOLD or rsi >= _RSI_OVERBOUGHT:
            at_bb = self._is_at_bb_boundary(df, rsi)
            if at_bb:
                rsi_extreme = max(abs(rsi - 50) - 20, 0) / 30.0
                confidence = min(0.90, 0.50 + rsi_extreme * 0.40)
                return MarketRegime.MEAN_REVERSION, confidence

        # --- RANGING: low ADX ---
        if adx <= _ADX_RANGING_MAX:
            confidence = min(0.85, 0.50 + (_ADX_RANGING_MAX - adx) / 40.0)
            return MarketRegime.RANGING, confidence

        # --- Transitional zone (20 < ADX < 25) ---
        return MarketRegime.UNKNOWN, 0.30

    # ------------------------------------------------------------------
    # Indicator helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _calc_adx(df: pd.DataFrame, period: int = 14) -> Tuple[float, float, float]:
        high  = df["high"]
        low   = df["low"]
        close = df["close"]

        up_move   = high.diff()
        down_move = -low.diff()

        plus_dm  = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        plus_dm_s  = pd.Series(plus_dm,  index=df.index)
        minus_dm_s = pd.Series(minus_dm, index=df.index)

        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low  - close.shift(1)).abs()
        tr  = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(period, min_periods=period).mean()

        plus_di  = 100 * (plus_dm_s.rolling(period, min_periods=period).mean() / atr)
        minus_di = 100 * (minus_dm_s.rolling(period, min_periods=period).mean() / atr)

        dx  = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        adx = dx.rolling(period, min_periods=period).mean()

        adx_val      = float(adx.ffill().fillna(0).iloc[-1])
        plus_di_val  = float(plus_di.ffill().fillna(0).iloc[-1])
        minus_di_val = float(minus_di.ffill().fillna(0).iloc[-1])
        return adx_val, plus_di_val, minus_di_val

    @staticmethod
    def _calc_rsi(df: pd.DataFrame, period: int = 14) -> float:
        delta = df["close"].diff()
        gain  = delta.clip(lower=0)
        loss  = -delta.clip(upper=0)
        avg_gain = gain.rolling(period, min_periods=period).mean()
        avg_loss = loss.rolling(period, min_periods=period).mean()
        rs  = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - (100 / (1 + rs))
        return float(rsi.ffill().fillna(50).iloc[-1])

    @staticmethod
    def _calc_atr(df: pd.DataFrame, period: int = 14) -> float:
        high  = df["high"]
        low   = df["low"]
        close = df["close"]
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low  - close.shift(1)).abs()
        tr  = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(period, min_periods=period).mean()
        return float(atr.ffill().fillna(0).iloc[-1])

    @staticmethod
    def _calc_bb_width_pct(
        df: pd.DataFrame,
        period: int = _BB_PERIOD,
        num_std: float = _BB_STD,
    ) -> float:
        close = df["close"]
        mid   = close.rolling(period, min_periods=period).mean()
        std   = close.rolling(period, min_periods=period).std()
        upper = mid + num_std * std
        lower = mid - num_std * std
        width = upper - lower
        mid_val = float(mid.ffill().fillna(1).iloc[-1])
        if mid_val == 0:
            return 0.0
        return float((width / mid).ffill().fillna(0).iloc[-1])

    @staticmethod
    def _is_adx_rising(df: pd.DataFrame, period: int = 14, lookback: int = 5) -> bool:
        """Return True if ADX has been rising over the last *lookback* bars."""
        if len(df) < period + lookback + 5:
            return False
        high  = df["high"]
        low   = df["low"]
        close = df["close"]
        tr1 = high - low
        tr2 = (high - close.shift(1)).abs()
        tr3 = (low  - close.shift(1)).abs()
        tr  = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(period, min_periods=period).mean()
        up_move   = high.diff()
        down_move = -low.diff()
        plus_dm  = pd.Series(
            np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
            index=df.index,
        )
        minus_dm = pd.Series(
            np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
            index=df.index,
        )
        plus_di  = 100 * (plus_dm.rolling(period, min_periods=period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(period, min_periods=period).mean() / atr)
        dx  = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
        adx = dx.rolling(period, min_periods=period).mean().ffill().fillna(0)
        recent = adx.iloc[-lookback:]
        if len(recent) < 2:
            return False
        return float(recent.iloc[-1]) > float(recent.iloc[0]) + _ADX_BREAKOUT_DELTA

    @staticmethod
    def _is_at_bb_boundary(df: pd.DataFrame, rsi: float) -> bool:
        """Return True if price is near the upper or lower Bollinger Band."""
        close = df["close"]
        mid   = close.rolling(_BB_PERIOD, min_periods=_BB_PERIOD).mean()
        std   = close.rolling(_BB_PERIOD, min_periods=_BB_PERIOD).std()
        upper = (mid + _BB_STD * std).ffill().fillna(close)
        lower = (mid - _BB_STD * std).ffill().fillna(close)
        price = float(close.iloc[-1])
        upper_val = float(upper.iloc[-1])
        lower_val = float(lower.iloc[-1])
        band_range = upper_val - lower_val
        if band_range <= 0:
            return False
        if rsi >= _RSI_OVERBOUGHT:
            return price >= upper_val - 0.10 * band_range
        if rsi <= _RSI_OVERSOLD:
            return price <= lower_val + 0.10 * band_range
        return False

    # ------------------------------------------------------------------
    # Redis helpers
    # ------------------------------------------------------------------

    def _load_from_redis(self, symbol: str) -> Optional[RegimeResult]:
        if self._redis is None:
            return None
        try:
            key  = f"nija:control:regime:{symbol.upper()}"
            data = self._redis.get(key)
            if data is None:
                return None
            d = json.loads(data)
            return RegimeResult(
                regime=MarketRegime(d["regime"]),
                confidence=d["confidence"],
                adx=d["adx"],
                rsi=d["rsi"],
                volatility=d["volatility"],
                bb_width_pct=d["bb_width_pct"],
                context=d.get("context", {}),
                symbol=d["symbol"],
                detected_at=d["detected_at"],
            )
        except Exception as exc:
            logger.debug("RegimeEngine: Redis load failed for %s: %s", symbol, exc)
            return None

    def _store_to_redis(self, symbol: str, result: RegimeResult) -> None:
        if self._redis is None:
            return
        try:
            key = f"nija:control:regime:{symbol.upper()}"
            self._redis.setex(key, _REGIME_REDIS_TTL, json.dumps(result.to_dict()))
        except Exception as exc:
            logger.debug("RegimeEngine: Redis store failed for %s: %s", symbol, exc)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _unknown_result(symbol: str, reason: str) -> RegimeResult:
        return RegimeResult(
            regime=MarketRegime.UNKNOWN,
            confidence=0.0,
            adx=0.0,
            rsi=50.0,
            volatility=0.0,
            bb_width_pct=0.0,
            context={"reason": reason},
            symbol=symbol.upper(),
            detected_at=datetime.now(timezone.utc).isoformat(),
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_singleton: Optional[RegimeEngine] = None
_singleton_lock = threading.Lock()


def get_regime_engine(redis_client=None) -> RegimeEngine:
    """Return the process-level RegimeEngine singleton."""
    global _singleton
    if _singleton is None:
        with _singleton_lock:
            if _singleton is None:
                _singleton = RegimeEngine(redis_client=redis_client)
    return _singleton
