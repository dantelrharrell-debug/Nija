from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Dict, List, Optional

import pandas as pd

from bot.control.strategy_signal import StrategySignal


def _to_float(v: float) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gains = delta.clip(lower=0).rolling(period).mean()
    losses = (-delta.clip(upper=0)).rolling(period).mean()
    rs = gains / losses.replace(0, pd.NA)
    return 100 - (100 / (1 + rs))


def _atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    tr1 = df["high"] - df["low"]
    tr2 = (df["high"] - df["close"].shift()).abs()
    tr3 = (df["low"] - df["close"].shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.rolling(period).mean()


def _vwap(df: pd.DataFrame) -> pd.Series:
    price_volume = df["close"] * df["volume"]
    return price_volume.cumsum() / df["volume"].replace(0, pd.NA).cumsum()


def _std_bands(close: pd.Series, window: int = 20, n_std: float = 2.0) -> pd.DataFrame:
    mid = close.rolling(window).mean()
    std = close.rolling(window).std()
    return pd.DataFrame({"upper": mid + n_std * std, "mid": mid, "lower": mid - n_std * std})


@dataclass
class DetectorContext:
    symbol: str
    broker: str
    market_regime: str = "uncertain"


class BaseDetector:
    strategy_name = "BASE"

    def detect(self, df: pd.DataFrame, context: DetectorContext) -> Optional[StrategySignal]:
        raise NotImplementedError

    @staticmethod
    def _signal(
        *,
        strategy: str,
        context: DetectorContext,
        direction: str,
        confidence: float,
        raw_score: float,
        invalidation_level: Optional[float],
        suggested_stop: Optional[float],
        targets: List[float],
        support: List[str],
        conflict: List[str],
        metadata: Optional[Dict] = None,
    ) -> StrategySignal:
        return StrategySignal(
            strategy=strategy,
            symbol=context.symbol,
            broker=context.broker,
            direction=direction,
            confidence=max(0.0, min(1.0, confidence)),
            raw_score=max(0.0, min(1.0, raw_score)),
            invalidation_level=invalidation_level,
            suggested_stop=suggested_stop,
            target_candidates=targets,
            market_regime=context.market_regime,
            supporting_evidence=support,
            conflicting_evidence=conflict,
            metadata=metadata or {},
        )


class OpeningRangeBreakoutDetector(BaseDetector):
    strategy_name = "FIRST_CANDLE_ORB"

    def __init__(self) -> None:
        self.lookback = int(os.getenv("NIJA_ORB_SESSION_BARS", "1"))
        self.require_close = os.getenv("NIJA_ORB_REQUIRE_CLOSE", "true").lower() == "true"
        self.require_retest = os.getenv("NIJA_ORB_REQUIRE_RETEST", "false").lower() == "true"
        self.volume_factor = float(os.getenv("NIJA_ORB_VOLUME_FACTOR", "1.10"))

    def detect(self, df: pd.DataFrame, context: DetectorContext) -> Optional[StrategySignal]:
        if len(df) < max(25, self.lookback + 2):
            return None
        first = df.iloc[self.lookback - 1]
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        first_high = _to_float(first["high"])
        first_low = _to_float(first["low"])
        close = _to_float(latest["close"])
        high = _to_float(latest["high"])
        low = _to_float(latest["low"])
        avg_volume = _to_float(df["volume"].iloc[-20:].mean())
        vol_ok = _to_float(latest["volume"]) >= avg_volume * self.volume_factor if avg_volume > 0 else True

        broke_up = close > first_high if self.require_close else high > first_high
        broke_down = close < first_low if self.require_close else low < first_low

        if self.require_retest:
            broke_up = broke_up and _to_float(prev["low"]) <= first_high <= _to_float(latest["low"])
            broke_down = broke_down and _to_float(prev["high"]) >= first_low >= _to_float(latest["high"])

        if broke_up and vol_ok:
            rng = max(first_high - first_low, 0.0)
            return self._signal(
                strategy=self.strategy_name,
                context=context,
                direction="long",
                confidence=0.70,
                raw_score=0.72,
                invalidation_level=first_low,
                suggested_stop=first_low,
                targets=[close + rng, close + 2 * rng],
                support=["orb_breakout_up", "volume_confirmed"],
                conflict=[],
                metadata={
                    "first_candle_open": _to_float(first["open"]),
                    "first_candle_high": first_high,
                    "first_candle_low": first_low,
                    "first_candle_close": _to_float(first["close"]),
                    "first_candle_range": rng,
                    "session_date": str(df.index[-1].date()) if hasattr(df.index[-1], "date") else "",
                },
            )

        if broke_down and vol_ok:
            rng = max(first_high - first_low, 0.0)
            return self._signal(
                strategy=self.strategy_name,
                context=context,
                direction="short",
                confidence=0.70,
                raw_score=0.72,
                invalidation_level=first_high,
                suggested_stop=first_high,
                targets=[close - rng, close - 2 * rng],
                support=["orb_breakout_down", "volume_confirmed"],
                conflict=[],
                metadata={
                    "first_candle_open": _to_float(first["open"]),
                    "first_candle_high": first_high,
                    "first_candle_low": first_low,
                    "first_candle_close": _to_float(first["close"]),
                    "first_candle_range": rng,
                    "session_date": str(df.index[-1].date()) if hasattr(df.index[-1], "date") else "",
                },
            )
        return None


class MeanReversionDetector(BaseDetector):
    strategy_name = "MEAN_REVERSION"

    def detect(self, df: pd.DataFrame, context: DetectorContext) -> Optional[StrategySignal]:
        if len(df) < 50:
            return None
        close = df["close"]
        ema20 = _ema(close, 20)
        vwap = _vwap(df)
        rsi = _rsi(close)
        atr = _atr(df)
        bands = _std_bands(close)

        c = _to_float(close.iloc[-1])
        prev_c = _to_float(close.iloc[-2])
        ema_now = _to_float(ema20.iloc[-1])
        vwap_now = _to_float(vwap.iloc[-1])
        rsi_now = _to_float(rsi.iloc[-1])
        atr_now = max(_to_float(atr.iloc[-1]), 1e-9)
        lower = _to_float(bands["lower"].iloc[-1])
        upper = _to_float(bands["upper"].iloc[-1])

        below_mean = c < ema_now and c < vwap_now and (c <= lower or (ema_now - c) > 0.8 * atr_now)
        above_mean = c > ema_now and c > vwap_now and (c >= upper or (c - ema_now) > 0.8 * atr_now)
        reversion_started_long = prev_c <= c and rsi_now > 30
        reversion_started_short = prev_c >= c and rsi_now < 70

        dev = abs(c - ema_now) / atr_now if atr_now else 0.0
        confidence = min(0.85, 0.55 + min(dev / 3.0, 0.25))

        if below_mean and rsi_now < 40 and reversion_started_long:
            stop = c - 1.5 * atr_now
            return self._signal(
                strategy=self.strategy_name,
                context=context,
                direction="long",
                confidence=confidence,
                raw_score=confidence,
                invalidation_level=stop,
                suggested_stop=stop,
                targets=[ema_now, vwap_now],
                support=["vwap_deviation", "ema_deviation", "rsi_recovering"],
                conflict=[],
            )
        if above_mean and rsi_now > 60 and reversion_started_short:
            stop = c + 1.5 * atr_now
            return self._signal(
                strategy=self.strategy_name,
                context=context,
                direction="short",
                confidence=confidence,
                raw_score=confidence,
                invalidation_level=stop,
                suggested_stop=stop,
                targets=[ema_now, vwap_now],
                support=["vwap_deviation", "ema_deviation", "rsi_fading"],
                conflict=[],
            )
        return None


class RangeTradingDetector(BaseDetector):
    strategy_name = "RANGE_TRADING"

    def detect(self, df: pd.DataFrame, context: DetectorContext) -> Optional[StrategySignal]:
        if len(df) < 40:
            return None
        window = df.iloc[-30:]
        range_high = _to_float(window["high"].max())
        range_low = _to_float(window["low"].min())
        close = _to_float(df["close"].iloc[-1])
        atr_now = _to_float(_atr(df).iloc[-1])

        width = range_high - range_low
        if width <= 0:
            return None
        breakout = close > range_high + atr_now * 0.2 or close < range_low - atr_now * 0.2
        if breakout:
            return None

        near_support = close <= range_low + width * 0.2
        near_resistance = close >= range_high - width * 0.2
        confidence = min(0.80, 0.55 + (1.0 - min(width / max(close, 1e-9), 0.2)))
        midpoint = range_low + width / 2

        metadata = {
            "range_high": range_high,
            "range_low": range_low,
            "range_midpoint": midpoint,
            "range_confidence": confidence,
        }
        if near_support:
            return self._signal(
                strategy=self.strategy_name,
                context=context,
                direction="long",
                confidence=confidence,
                raw_score=confidence,
                invalidation_level=range_low - atr_now,
                suggested_stop=range_low - atr_now,
                targets=[midpoint, range_high],
                support=["validated_range", "support_proximity"],
                conflict=[],
                metadata=metadata,
            )
        if near_resistance:
            return self._signal(
                strategy=self.strategy_name,
                context=context,
                direction="short",
                confidence=confidence,
                raw_score=confidence,
                invalidation_level=range_high + atr_now,
                suggested_stop=range_high + atr_now,
                targets=[midpoint, range_low],
                support=["validated_range", "resistance_proximity"],
                conflict=[],
                metadata=metadata,
            )
        return None


class SupportResistanceBounceDetector(BaseDetector):
    strategy_name = "SUPPORT_RESISTANCE_BOUNCE"

    def detect(self, df: pd.DataFrame, context: DetectorContext) -> Optional[StrategySignal]:
        if len(df) < 45:
            return None
        lows = df["low"].iloc[-40:]
        highs = df["high"].iloc[-40:]
        close = _to_float(df["close"].iloc[-1])
        atr_now = _to_float(_atr(df).iloc[-1])
        support = _to_float(lows.nsmallest(3).mean())
        resistance = _to_float(highs.nlargest(3).mean())
        touches_support = int((lows <= support + atr_now * 0.2).sum())
        touches_resistance = int((highs >= resistance - atr_now * 0.2).sum())
        bull_reject = _to_float(df["close"].iloc[-1]) > _to_float(df["open"].iloc[-1])
        bear_reject = _to_float(df["close"].iloc[-1]) < _to_float(df["open"].iloc[-1])

        if touches_support >= 2 and abs(close - support) <= atr_now * 0.5 and bull_reject:
            return self._signal(
                strategy=self.strategy_name,
                context=context,
                direction="long",
                confidence=0.68,
                raw_score=0.68,
                invalidation_level=support - atr_now,
                suggested_stop=support - atr_now,
                targets=[resistance],
                support=["support_touches", "rejection_candle"],
                conflict=[],
            )
        if touches_resistance >= 2 and abs(close - resistance) <= atr_now * 0.5 and bear_reject:
            return self._signal(
                strategy=self.strategy_name,
                context=context,
                direction="short",
                confidence=0.68,
                raw_score=0.68,
                invalidation_level=resistance + atr_now,
                suggested_stop=resistance + atr_now,
                targets=[support],
                support=["resistance_touches", "rejection_candle"],
                conflict=[],
            )
        return None


class VolatilityExpansionDetector(BaseDetector):
    strategy_name = "VOLATILITY_EXPANSION"

    def __init__(self) -> None:
        self.max_spread_bps = float(os.getenv("NIJA_VOL_EXP_MAX_SPREAD_BPS", "35"))

    def detect(self, df: pd.DataFrame, context: DetectorContext) -> Optional[StrategySignal]:
        if len(df) < 40:
            return None
        atr_series = _atr(df)
        recent_atr = _to_float(atr_series.iloc[-1])
        base_atr = _to_float(atr_series.iloc[-15:-3].mean())
        if base_atr <= 0:
            return None
        compression = recent_atr < base_atr * 0.9
        bar = df.iloc[-1]
        prev = df.iloc[-2]
        bar_range = _to_float(bar["high"]) - _to_float(bar["low"])
        vol_spike = _to_float(bar["volume"]) > _to_float(df["volume"].iloc[-20:].mean()) * 1.3
        spread_bps = _to_float(bar.get("spread_bps", 0.0))
        if spread_bps > self.max_spread_bps:
            return None

        prior_high = _to_float(df["high"].iloc[-31:-1].max())
        prior_low = _to_float(df["low"].iloc[-31:-1].min())
        break_up = _to_float(bar["close"]) > prior_high and _to_float(bar["close"]) > _to_float(prev["close"])
        break_down = _to_float(bar["close"]) < prior_low and _to_float(bar["close"]) < _to_float(prev["close"])
        if not (compression and vol_spike):
            return None
        if break_up:
            return self._signal(
                strategy=self.strategy_name,
                context=context,
                direction="long",
                confidence=0.74,
                raw_score=0.74,
                invalidation_level=_to_float(bar["close"]) - 1.2 * bar_range,
                suggested_stop=_to_float(bar["close"]) - 1.2 * bar_range,
                targets=[_to_float(bar["close"]) + 2 * bar_range],
                support=["compression_then_expansion", "volume_spike", "breakout_structure"],
                conflict=[],
            )
        if break_down:
            return self._signal(
                strategy=self.strategy_name,
                context=context,
                direction="short",
                confidence=0.74,
                raw_score=0.74,
                invalidation_level=_to_float(bar["close"]) + 1.2 * bar_range,
                suggested_stop=_to_float(bar["close"]) + 1.2 * bar_range,
                targets=[_to_float(bar["close"]) - 2 * bar_range],
                support=["compression_then_expansion", "volume_spike", "breakout_structure"],
                conflict=[],
            )
        return None


class ReversalExhaustionDetector(BaseDetector):
    strategy_name = "REVERSAL_EXHAUSTION"

    def detect(self, df: pd.DataFrame, context: DetectorContext) -> Optional[StrategySignal]:
        if len(df) < 60:
            return None
        close = df["close"]
        ema50 = _ema(close, 50)
        rsi = _rsi(close)
        atr = _atr(df)
        latest = df.iloc[-1]
        prev = df.iloc[-2]

        c = _to_float(latest["close"])
        p = _to_float(prev["close"])
        ema_now = _to_float(ema50.iloc[-1])
        rsi_now = _to_float(rsi.iloc[-1])
        rsi_prev = _to_float(rsi.iloc[-2])
        atr_now = max(_to_float(atr.iloc[-1]), 1e-9)
        distance = abs(c - ema_now) / atr_now
        vol_drop = _to_float(latest["volume"]) < _to_float(df["volume"].iloc[-15:-1].mean()) * 0.9

        bullish_reversal = c > p and rsi_now > rsi_prev and rsi_now < 45 and distance > 1.5 and vol_drop
        bearish_reversal = c < p and rsi_now < rsi_prev and rsi_now > 55 and distance > 1.5 and vol_drop

        if bullish_reversal:
            return self._signal(
                strategy=self.strategy_name,
                context=context,
                direction="long",
                confidence=0.69,
                raw_score=0.69,
                invalidation_level=c - 1.5 * atr_now,
                suggested_stop=c - 1.5 * atr_now,
                targets=[ema_now],
                support=["momentum_deterioration", "distance_from_mean", "volume_exhaustion"],
                conflict=[],
            )
        if bearish_reversal:
            return self._signal(
                strategy=self.strategy_name,
                context=context,
                direction="short",
                confidence=0.69,
                raw_score=0.69,
                invalidation_level=c + 1.5 * atr_now,
                suggested_stop=c + 1.5 * atr_now,
                targets=[ema_now],
                support=["momentum_deterioration", "distance_from_mean", "volume_exhaustion"],
                conflict=[],
            )
        return None


def build_default_detectors() -> Dict[str, BaseDetector]:
    return {
        "FIRST_CANDLE_ENABLED": OpeningRangeBreakoutDetector(),
        "MEAN_REVERSION_ENABLED": MeanReversionDetector(),
        "RANGE_TRADING_ENABLED": RangeTradingDetector(),
        "SUPPORT_RESISTANCE_ENABLED": SupportResistanceBounceDetector(),
        "VOLATILITY_EXPANSION_ENABLED": VolatilityExpansionDetector(),
        "REVERSAL_EXHAUSTION_ENABLED": ReversalExhaustionDetector(),
    }
