"""Market-adaptive entry thresholds for confidence, ADX, and relative volume."""

from __future__ import annotations

import os
import threading
from collections import deque
from dataclasses import dataclass
from typing import Any, Deque, Dict, Optional

import pandas as pd


CONFIDENCE_FLOOR = 0.12
CONFIDENCE_CEILING = 0.22
ADX_FLOOR = 1.5
ADX_CEILING = 10.0
REL_VOLUME_FLOOR = 0.20
REL_VOLUME_CEILING = 1.20


def _clamp(value: float, floor: float, ceiling: float) -> float:
    return max(floor, min(ceiling, float(value)))


def _series_last(indicators: Dict[str, Any], key: str, default: float = 0.0) -> float:
    try:
        series = indicators.get(key)
        if series is None:
            return default
        if hasattr(series, "iloc"):
            return float(series.iloc[-1])
        if isinstance(series, (list, tuple)) and series:
            return float(series[-1])
        return float(series)
    except Exception:
        return default


@dataclass(frozen=True)
class MarketRegimeClassification:
    trend: str
    volatility: str
    liquidity: str
    sentiment: str


@dataclass(frozen=True)
class AdaptiveEntryThresholds:
    confidence: float
    adx: float
    relative_volume: float
    regime: MarketRegimeClassification
    starvation_relaxation: float
    performance_adjustment: float


class AdaptiveEntryThresholdEngine:
    """Resolve bounded adaptive thresholds from market state and trade outcomes."""

    def __init__(self) -> None:
        window = int(os.getenv("NIJA_ADAPTIVE_REOPT_TRADE_WINDOW", "150"))
        self._reopt_window = max(100, min(250, window))
        self._outcomes: Deque[float] = deque(maxlen=self._reopt_window)
        self._lock = threading.Lock()

    def record_trade_outcome(self, pnl_pct: float) -> None:
        with self._lock:
            self._outcomes.append(float(pnl_pct))

    def resolve(
        self,
        df: pd.DataFrame,
        indicators: Dict[str, Any],
        regime: Any = None,
        zero_signal_streak: int = 0,
    ) -> AdaptiveEntryThresholds:
        adx_series = indicators.get("adx")
        current_adx = _series_last(indicators, "adx", 0.0)
        adx_threshold = self._percentile_threshold(adx_series, 0.35, ADX_FLOOR, ADX_CEILING)

        rel_volume_series = self._relative_volume_series(df)
        rel_volume_threshold = self._percentile_threshold(
            rel_volume_series,
            0.40,
            REL_VOLUME_FLOOR,
            REL_VOLUME_CEILING,
        )
        current_rel_volume = float(rel_volume_series.iloc[-1]) if len(rel_volume_series) else 0.0
        avg_abs_return = self._avg_abs_return_pct(df)

        classified = self.classify_market(
            current_adx=current_adx,
            current_rel_volume=current_rel_volume,
            avg_abs_return_pct=avg_abs_return,
            regime=regime,
        )

        base_confidence = self._base_confidence_for_regime(classified)
        performance_adjustment = self._performance_adjustment()
        starvation_relaxation = min(0.04, max(0, int(zero_signal_streak)) * 0.005)

        confidence = _clamp(
            base_confidence + performance_adjustment - starvation_relaxation,
            CONFIDENCE_FLOOR,
            CONFIDENCE_CEILING,
        )
        adx = _clamp(
            adx_threshold - (starvation_relaxation * 40.0),
            ADX_FLOOR,
            ADX_CEILING,
        )
        relative_volume = _clamp(
            rel_volume_threshold - (starvation_relaxation * 5.0),
            REL_VOLUME_FLOOR,
            REL_VOLUME_CEILING,
        )

        return AdaptiveEntryThresholds(
            confidence=confidence,
            adx=adx,
            relative_volume=relative_volume,
            regime=classified,
            starvation_relaxation=starvation_relaxation,
            performance_adjustment=performance_adjustment,
        )

    @staticmethod
    def classify_market(
        *,
        current_adx: float,
        current_rel_volume: float,
        avg_abs_return_pct: float,
        regime: Any = None,
    ) -> MarketRegimeClassification:
        regime_key = str(getattr(regime, "value", regime) or "").lower()
        if current_adx >= 18 or "strong" in regime_key or "trend" in regime_key:
            trend = "strong_trend"
        elif current_adx >= 8:
            trend = "weak_trend"
        else:
            trend = "ranging"

        if avg_abs_return_pct >= 2.5 or "volatility_explosion" in regime_key:
            volatility = "extreme"
        elif avg_abs_return_pct >= 0.75:
            volatility = "elevated"
        else:
            volatility = "quiet"

        if current_rel_volume >= 1.2:
            liquidity = "high"
        elif current_rel_volume >= 0.35:
            liquidity = "normal"
        else:
            liquidity = "thin"

        if trend == "strong_trend" and liquidity != "thin":
            sentiment = "risk_on"
        elif volatility == "extreme" or liquidity == "thin":
            sentiment = "risk_off"
        else:
            sentiment = "neutral"
        return MarketRegimeClassification(trend, volatility, liquidity, sentiment)

    def _performance_adjustment(self) -> float:
        with self._lock:
            outcomes = list(self._outcomes)
            reopt_window = self._reopt_window
        if len(outcomes) < reopt_window:
            return 0.0
        wins = sum(1 for pnl in outcomes if pnl > 0)
        win_rate = wins / float(len(outcomes))
        avg_pnl = sum(outcomes) / float(len(outcomes))
        if win_rate < 0.48 or avg_pnl < 0:
            return 0.025
        if win_rate > 0.58 and avg_pnl > 0:
            return -0.015
        return 0.0

    @staticmethod
    def _base_confidence_for_regime(classified: MarketRegimeClassification) -> float:
        if classified.volatility == "extreme" or classified.sentiment == "risk_off":
            return 0.22
        if classified.trend == "strong_trend" and classified.liquidity == "high":
            return 0.16
        if classified.trend == "ranging":
            return 0.18
        return 0.15

    @staticmethod
    def _percentile_threshold(data: Any, q: float, floor: float, ceiling: float) -> float:
        try:
            series = pd.Series(data).dropna().astype(float).tail(120)
            if len(series) < 5:
                return floor
            return _clamp(float(series.quantile(q)), floor, ceiling)
        except Exception:
            return floor

    @staticmethod
    def _relative_volume_series(df: pd.DataFrame) -> pd.Series:
        try:
            volume = pd.to_numeric(df["volume"], errors="coerce").dropna()
            baseline = volume.rolling(20, min_periods=5).mean()
            rel = (volume / baseline).replace([float("inf"), float("-inf")], pd.NA).dropna()
            return rel.tail(120)
        except Exception:
            return pd.Series(dtype=float)

    @staticmethod
    def _avg_abs_return_pct(df: pd.DataFrame) -> float:
        try:
            close = pd.to_numeric(df["close"], errors="coerce").dropna()
            returns = close.pct_change().dropna().tail(30).abs() * 100.0
            return float(returns.mean()) if len(returns) else 0.0
        except Exception:
            return 0.0


_engine: Optional[AdaptiveEntryThresholdEngine] = None
_engine_lock = threading.Lock()


def get_adaptive_entry_threshold_engine() -> AdaptiveEntryThresholdEngine:
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = AdaptiveEntryThresholdEngine()
    return _engine


def get_adaptive_entry_thresholds(
    df: pd.DataFrame,
    indicators: Dict[str, Any],
    regime: Any = None,
    zero_signal_streak: int = 0,
) -> AdaptiveEntryThresholds:
    return get_adaptive_entry_threshold_engine().resolve(
        df=df,
        indicators=indicators,
        regime=regime,
        zero_signal_streak=zero_signal_streak,
    )


def record_adaptive_trade_outcome(pnl_pct: float) -> None:
    get_adaptive_entry_threshold_engine().record_trade_outcome(pnl_pct)
