"""
Deterministic chart-pattern recognition for production entry scoring.

This module only uses completed OHLCV candles (drops the latest bar) to avoid
look-ahead bias and repainting in live scans.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import logging
import math

import numpy as np
import pandas as pd

logger = logging.getLogger("nija.patterns")


@dataclass
class PatternSignal:
    pattern_name: str
    direction: str
    confidence: float
    levels: Dict[str, float]
    confirmation_state: str
    invalidation_price: float
    category: str
    age_bars: int = 0

    def as_dict(self) -> Dict[str, Any]:
        return {
            "pattern_name": self.pattern_name,
            "direction": self.direction,
            "confidence": float(self.confidence),
            "levels": dict(self.levels),
            "confirmation_state": self.confirmation_state,
            "invalidation_price": float(self.invalidation_price),
            "category": self.category,
            "age_bars": int(self.age_bars),
        }


class DeterministicPatternRecognizer:
    """Deterministic technical-pattern engine for scoring and exit context."""

    def __init__(self, config: Optional[Dict[str, Any]] = None) -> None:
        cfg = config or {}
        self.enabled = bool(cfg.get("enabled", True))
        self.lookback = max(20, int(cfg.get("pattern_lookback", 120)))
        self.min_confidence = float(cfg.get("min_pattern_confidence", 0.65))
        self.breakout_lookback = max(10, int(cfg.get("breakout_lookback", 20)))
        self.stale_bars = max(2, int(cfg.get("stale_bars", 8)))
        self.min_volume_ratio = float(cfg.get("min_volume_ratio", 1.1))
        self.atr_stop_buffer = max(0.05, float(cfg.get("atr_stop_buffer", 0.35)))

    def analyze(
        self,
        df: pd.DataFrame,
        indicators: Optional[Dict[str, Any]],
        side: str,
        regime: Any = None,
    ) -> Dict[str, Any]:
        """
        Detect configured patterns and return score/confirmation/exit context.
        """
        if not self.enabled:
            return self._empty(reason="disabled")
        cleaned = self._prepare_frame(df)
        if cleaned is None:
            return self._empty(reason="invalid_or_insufficient_data")

        patterns = self._detect_all(cleaned, indicators or {})
        confirmed = [
            p for p in patterns
            if p.confirmation_state == "confirmed" and p.confidence >= self.min_confidence
        ]
        confirmed_for_side = [p for p in confirmed if p.direction == side]

        regime_label = str(regime.value).lower() if hasattr(regime, "value") else str(regime or "unknown").lower()
        score_adjustment = self._score_adjustment(
            confirmed=confirmed_for_side,
            all_confirmed=confirmed,
            regime_label=regime_label,
        )

        exit_plan = self._build_exit_plan(
            confirmed_for_side=confirmed_for_side,
            indicators=indicators or {},
            latest_price=float(cleaned["close"].iloc[-1]),
        )

        return {
            "patterns": [p.as_dict() for p in patterns],
            "confirmed_patterns": [p.as_dict() for p in confirmed_for_side],
            "score_adjustment": float(score_adjustment),
            "regime": regime_label,
            "rejection_reason": "" if confirmed_for_side else "no_confirmed_patterns_for_side",
            "exit_plan": exit_plan,
        }

    @staticmethod
    def _empty(reason: str) -> Dict[str, Any]:
        return {
            "patterns": [],
            "confirmed_patterns": [],
            "score_adjustment": 0.0,
            "regime": "unknown",
            "rejection_reason": reason,
            "exit_plan": None,
        }

    def _prepare_frame(self, df: pd.DataFrame) -> Optional[pd.DataFrame]:
        required = {"open", "high", "low", "close", "volume"}
        if df is None or df.empty or not required.issubset(df.columns):
            return None

        frame = df.copy()
        for col in ("open", "high", "low", "close", "volume"):
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        frame = frame.dropna(subset=["open", "high", "low", "close", "volume"])
        if len(frame) < 30:
            return None

        # Use completed candles only (drop latest potentially in-flight candle).
        completed = frame.iloc[:-1].copy()
        if len(completed) < 30:
            return None
        return completed.tail(self.lookback).copy()

    def _detect_all(self, df: pd.DataFrame, indicators: Dict[str, Any]) -> List[PatternSignal]:
        patterns: List[PatternSignal] = []
        for detector in (
            self._detect_double_top_bottom,
            self._detect_head_shoulders,
            self._detect_triangle,
            self._detect_channel,
            self._detect_breakout_breakdown,
            self._detect_momentum_divergence,
            self._detect_volume_confirmation,
        ):
            try:
                res = detector(df, indicators)
                if res:
                    patterns.extend(res)
            except Exception as exc:
                logger.debug("Pattern detector %s failed: %s", detector.__name__, exc)
        return patterns

    @staticmethod
    def _pivot_points(series: pd.Series, order: int = 2, mode: str = "high") -> List[Tuple[int, float]]:
        vals = np.asarray(series, dtype=float)
        pivots: List[Tuple[int, float]] = []
        for i in range(order, len(vals) - order):
            window = vals[i - order:i + order + 1]
            center = vals[i]
            if mode == "high" and center == np.nanmax(window) and int(np.sum(window == center)) == 1:
                pivots.append((i, float(center)))
            if mode == "low" and center == np.nanmin(window) and int(np.sum(window == center)) == 1:
                pivots.append((i, float(center)))
        return pivots

    def _detect_double_top_bottom(self, df: pd.DataFrame, _indicators: Dict[str, Any]) -> List[PatternSignal]:
        highs = self._pivot_points(df["high"], mode="high")
        lows = self._pivot_points(df["low"], mode="low")
        out: List[PatternSignal] = []
        close_now = float(df["close"].iloc[-1])

        if len(highs) >= 2:
            (i1, h1), (i2, h2) = highs[-2], highs[-1]
            if i2 > i1 + 2:
                tol = abs(h1 - h2) / max((h1 + h2) / 2.0, 1e-9)
                valley = float(df["low"].iloc[i1:i2 + 1].min())
                confirmed = close_now < valley
                conf = max(0.0, min(1.0, 0.62 + (0.02 if confirmed else -0.05) - tol * 1.2))
                out.append(PatternSignal(
                    pattern_name="double_top",
                    direction="short",
                    confidence=conf,
                    levels={"peak_1": h1, "peak_2": h2, "neckline": valley, "height": max(h1, h2) - valley},
                    confirmation_state="confirmed" if confirmed else "forming",
                    invalidation_price=max(h1, h2),
                    category="reversal",
                    age_bars=max(0, len(df) - 1 - i2),
                ))

        if len(lows) >= 2:
            (i1, l1), (i2, l2) = lows[-2], lows[-1]
            if i2 > i1 + 2:
                tol = abs(l1 - l2) / max((l1 + l2) / 2.0, 1e-9)
                neckline = float(df["high"].iloc[i1:i2 + 1].max())
                confirmed = close_now > neckline
                conf = max(0.0, min(1.0, 0.62 + (0.02 if confirmed else -0.05) - tol * 1.2))
                out.append(PatternSignal(
                    pattern_name="double_bottom",
                    direction="long",
                    confidence=conf,
                    levels={"bottom_1": l1, "bottom_2": l2, "neckline": neckline, "height": neckline - min(l1, l2)},
                    confirmation_state="confirmed" if confirmed else "forming",
                    invalidation_price=min(l1, l2),
                    category="reversal",
                    age_bars=max(0, len(df) - 1 - i2),
                ))

        return out

    def _detect_head_shoulders(self, df: pd.DataFrame, _indicators: Dict[str, Any]) -> List[PatternSignal]:
        highs = self._pivot_points(df["high"], mode="high")
        lows = self._pivot_points(df["low"], mode="low")
        out: List[PatternSignal] = []
        close_now = float(df["close"].iloc[-1])

        if len(highs) >= 3:
            (li, ls), (hi, head), (ri, rs) = highs[-3], highs[-2], highs[-1]
            if li < hi < ri and head > ls and head > rs:
                shoulder_diff = abs(ls - rs) / max((ls + rs) / 2.0, 1e-9)
                left_neck = float(df["low"].iloc[li:hi + 1].min())
                right_neck = float(df["low"].iloc[hi:ri + 1].min())
                neckline = (left_neck + right_neck) / 2.0
                confirmed = close_now < neckline
                conf = max(0.0, min(1.0, 0.67 + (0.03 if confirmed else -0.06) - shoulder_diff))
                out.append(PatternSignal(
                    pattern_name="head_and_shoulders",
                    direction="short",
                    confidence=conf,
                    levels={"left_shoulder": ls, "head": head, "right_shoulder": rs, "neckline": neckline, "height": head - neckline},
                    confirmation_state="confirmed" if confirmed else "forming",
                    invalidation_price=max(ls, rs),
                    category="reversal",
                    age_bars=max(0, len(df) - 1 - ri),
                ))

        if len(lows) >= 3:
            (li, ls), (hi, head), (ri, rs) = lows[-3], lows[-2], lows[-1]
            if li < hi < ri and head < ls and head < rs:
                shoulder_diff = abs(ls - rs) / max((abs(ls) + abs(rs)) / 2.0, 1e-9)
                left_neck = float(df["high"].iloc[li:hi + 1].max())
                right_neck = float(df["high"].iloc[hi:ri + 1].max())
                neckline = (left_neck + right_neck) / 2.0
                confirmed = close_now > neckline
                conf = max(0.0, min(1.0, 0.67 + (0.03 if confirmed else -0.06) - shoulder_diff))
                out.append(PatternSignal(
                    pattern_name="inverse_head_and_shoulders",
                    direction="long",
                    confidence=conf,
                    levels={"left_shoulder": ls, "head": head, "right_shoulder": rs, "neckline": neckline, "height": neckline - head},
                    confirmation_state="confirmed" if confirmed else "forming",
                    invalidation_price=min(ls, rs),
                    category="reversal",
                    age_bars=max(0, len(df) - 1 - ri),
                ))
        return out

    def _detect_triangle(self, df: pd.DataFrame, _indicators: Dict[str, Any]) -> List[PatternSignal]:
        window = min(len(df), max(30, self.breakout_lookback + 10))
        data = df.tail(window)
        x = np.arange(window, dtype=float)
        high_fit = np.polyfit(x, data["high"].to_numpy(dtype=float), 1)
        low_fit = np.polyfit(x, data["low"].to_numpy(dtype=float), 1)
        upper_slope, upper_intercept = float(high_fit[0]), float(high_fit[1])
        lower_slope, lower_intercept = float(low_fit[0]), float(low_fit[1])
        last_x = float(x[-1])
        upper_now = upper_slope * last_x + upper_intercept
        lower_now = lower_slope * last_x + lower_intercept
        close_now = float(data["close"].iloc[-1])
        range_now = max(abs(upper_now - lower_now), 1e-9)

        out: List[PatternSignal] = []
        flat = 0.02
        # Ascending triangle
        if abs(upper_slope) <= flat and lower_slope > flat:
            confirmed = close_now > upper_now * 1.001
            conf = min(1.0, 0.63 + (0.04 if confirmed else -0.05) + min(lower_slope, 0.15))
            out.append(PatternSignal(
                pattern_name="ascending_triangle",
                direction="long",
                confidence=conf,
                levels={"resistance": upper_now, "support": lower_now, "height": range_now},
                confirmation_state="confirmed" if confirmed else "forming",
                invalidation_price=lower_now,
                category="continuation",
                age_bars=0,
            ))
        # Descending triangle
        if upper_slope < -flat and abs(lower_slope) <= flat:
            confirmed = close_now < lower_now * 0.999
            conf = min(1.0, 0.63 + (0.04 if confirmed else -0.05) + min(abs(upper_slope), 0.15))
            out.append(PatternSignal(
                pattern_name="descending_triangle",
                direction="short",
                confidence=conf,
                levels={"resistance": upper_now, "support": lower_now, "height": range_now},
                confirmation_state="confirmed" if confirmed else "forming",
                invalidation_price=upper_now,
                category="continuation",
                age_bars=0,
            ))
        # Symmetrical triangle
        if upper_slope < -flat and lower_slope > flat:
            if close_now > upper_now * 1.001:
                direction = "long"
                confirmed = True
                invalidation = lower_now
            elif close_now < lower_now * 0.999:
                direction = "short"
                confirmed = True
                invalidation = upper_now
            else:
                direction = "neutral"
                confirmed = False
                invalidation = lower_now
            conf = min(1.0, 0.60 + (0.05 if confirmed else -0.02))
            out.append(PatternSignal(
                pattern_name="symmetrical_triangle",
                direction=direction,
                confidence=conf,
                levels={"resistance": upper_now, "support": lower_now, "height": range_now},
                confirmation_state="confirmed" if confirmed else "forming",
                invalidation_price=invalidation,
                category="continuation",
                age_bars=0,
            ))
        return out

    def _detect_channel(self, df: pd.DataFrame, _indicators: Dict[str, Any]) -> List[PatternSignal]:
        window = min(len(df), 40)
        data = df.tail(window)
        x = np.arange(window, dtype=float)
        upper_slope, upper_intercept = np.polyfit(x, data["high"].to_numpy(dtype=float), 1)
        lower_slope, lower_intercept = np.polyfit(x, data["low"].to_numpy(dtype=float), 1)
        slope_gap = abs(float(upper_slope - lower_slope))
        if slope_gap > 0.04:
            return []

        last_x = float(x[-1])
        upper_now = float(upper_slope * last_x + upper_intercept)
        lower_now = float(lower_slope * last_x + lower_intercept)
        close_now = float(data["close"].iloc[-1])
        flat = 0.02

        if abs(float(upper_slope)) <= flat and abs(float(lower_slope)) <= flat:
            name, direction, category = "horizontal_channel", "neutral", "range"
        elif float(upper_slope) > flat and float(lower_slope) > flat:
            name, direction, category = "rising_channel", "long", "continuation"
        elif float(upper_slope) < -flat and float(lower_slope) < -flat:
            name, direction, category = "falling_channel", "short", "continuation"
        else:
            return []

        midpoint = (upper_now + lower_now) / 2.0
        if direction == "long":
            confirmed = close_now >= midpoint
        elif direction == "short":
            confirmed = close_now <= midpoint
        else:
            confirmed = close_now > upper_now * 1.001 or close_now < lower_now * 0.999
        confidence = 0.58 + (0.07 if confirmed else -0.02)
        return [PatternSignal(
            pattern_name=name,
            direction=direction,
            confidence=min(1.0, confidence),
            levels={"upper": upper_now, "lower": lower_now, "mid": midpoint, "height": max(upper_now - lower_now, 0.0)},
            confirmation_state="confirmed" if confirmed else "forming",
            invalidation_price=lower_now if direction != "short" else upper_now,
            category=category,
            age_bars=0,
        )]

    def _detect_breakout_breakdown(self, df: pd.DataFrame, _indicators: Dict[str, Any]) -> List[PatternSignal]:
        n = min(self.breakout_lookback, len(df) - 2)
        if n < 5:
            return []
        prior = df.iloc[-(n + 1):-1]
        high = float(prior["high"].max())
        low = float(prior["low"].min())
        close_now = float(df["close"].iloc[-1])
        vol_now = float(df["volume"].iloc[-1])
        vol_avg = float(prior["volume"].tail(min(20, len(prior))).mean() or 0.0)
        vol_ratio = (vol_now / vol_avg) if vol_avg > 0 else 0.0
        out: List[PatternSignal] = []

        if close_now > high * 1.001:
            confirmed = vol_ratio >= self.min_volume_ratio
            conf = min(1.0, 0.60 + min((close_now / max(high, 1e-9) - 1.0) * 60.0, 0.2) + min(vol_ratio / 5.0, 0.2))
            out.append(PatternSignal(
                pattern_name="breakout",
                direction="long",
                confidence=conf,
                levels={"trigger": high, "close": close_now, "volume_ratio": vol_ratio, "height": high - low},
                confirmation_state="confirmed" if confirmed else "forming",
                invalidation_price=high,
                category="continuation",
                age_bars=0,
            ))
        if close_now < low * 0.999:
            confirmed = vol_ratio >= self.min_volume_ratio
            conf = min(1.0, 0.60 + min((1.0 - close_now / max(low, 1e-9)) * 60.0, 0.2) + min(vol_ratio / 5.0, 0.2))
            out.append(PatternSignal(
                pattern_name="breakdown",
                direction="short",
                confidence=conf,
                levels={"trigger": low, "close": close_now, "volume_ratio": vol_ratio, "height": high - low},
                confirmation_state="confirmed" if confirmed else "forming",
                invalidation_price=low,
                category="continuation",
                age_bars=0,
            ))
        return out

    def _detect_momentum_divergence(self, df: pd.DataFrame, indicators: Dict[str, Any]) -> List[PatternSignal]:
        osc = indicators.get("rsi")
        if osc is None:
            osc = indicators.get("histogram")
        if osc is None:
            return []
        osc_series = pd.to_numeric(pd.Series(osc).copy(), errors="coerce").dropna()
        if len(osc_series) < 20 or len(df) < 20:
            return []

        osc_vals = osc_series.tail(len(df)).to_numpy(dtype=float)
        if len(osc_vals) != len(df):
            return []

        highs = self._pivot_points(df["high"], mode="high")
        lows = self._pivot_points(df["low"], mode="low")
        out: List[PatternSignal] = []
        close_now = float(df["close"].iloc[-1])

        if len(lows) >= 2:
            (i1, p1), (i2, p2) = lows[-2], lows[-1]
            o1, o2 = float(osc_vals[i1]), float(osc_vals[i2])
            if p2 < p1 and o2 > o1:
                confirmed = close_now > float(df["close"].iloc[-2])
                conf = min(1.0, 0.61 + (0.05 if confirmed else -0.03) + min(abs((o2 - o1) / 100.0), 0.1))
                out.append(PatternSignal(
                    pattern_name="momentum_divergence",
                    direction="long",
                    confidence=conf,
                    levels={"price_low_1": p1, "price_low_2": p2, "osc_low_1": o1, "osc_low_2": o2},
                    confirmation_state="confirmed" if confirmed else "forming",
                    invalidation_price=p2,
                    category="reversal",
                    age_bars=max(0, len(df) - 1 - i2),
                ))

        if len(highs) >= 2:
            (i1, p1), (i2, p2) = highs[-2], highs[-1]
            o1, o2 = float(osc_vals[i1]), float(osc_vals[i2])
            if p2 > p1 and o2 < o1:
                confirmed = close_now < float(df["close"].iloc[-2])
                conf = min(1.0, 0.61 + (0.05 if confirmed else -0.03) + min(abs((o1 - o2) / 100.0), 0.1))
                out.append(PatternSignal(
                    pattern_name="momentum_divergence",
                    direction="short",
                    confidence=conf,
                    levels={"price_high_1": p1, "price_high_2": p2, "osc_high_1": o1, "osc_high_2": o2},
                    confirmation_state="confirmed" if confirmed else "forming",
                    invalidation_price=p2,
                    category="reversal",
                    age_bars=max(0, len(df) - 1 - i2),
                ))
        return out

    def _detect_volume_confirmation(self, df: pd.DataFrame, _indicators: Dict[str, Any]) -> List[PatternSignal]:
        if len(df) < 22:
            return []
        cur = float(df["volume"].iloc[-1])
        baseline = float(df["volume"].iloc[-21:-1].mean() or 0.0)
        if baseline <= 0:
            return []
        ratio = cur / baseline
        confirmed = ratio >= self.min_volume_ratio
        direction = "long" if float(df["close"].iloc[-1]) >= float(df["close"].iloc[-2]) else "short"
        confidence = max(0.0, min(1.0, 0.55 + min(ratio / 4.0, 0.25)))
        return [PatternSignal(
            pattern_name="volume_confirmation",
            direction=direction,
            confidence=confidence,
            levels={"volume_ratio": ratio, "current_volume": cur, "baseline_volume": baseline},
            confirmation_state="confirmed" if confirmed else "forming",
            invalidation_price=float(df["low"].iloc[-1] if direction == "long" else df["high"].iloc[-1]),
            category="confirmation",
            age_bars=0,
        )]

    def _score_adjustment(
        self,
        confirmed: List[PatternSignal],
        all_confirmed: List[PatternSignal],
        regime_label: str,
    ) -> float:
        if not confirmed:
            return 0.0
        trending = any(k in regime_label for k in ("trend", "bull", "bear", "momentum"))
        ranging = any(k in regime_label for k in ("range", "sideways", "chop"))

        adjustment = 0.0
        for pattern in confirmed:
            base = max(0.0, min(1.0, pattern.confidence)) * 3.0
            if pattern.category in {"continuation", "confirmation"}:
                weight = 1.15 if trending else 0.90
            else:  # reversal / range
                weight = 0.80 if trending else (1.10 if ranging else 0.95)
            if pattern.age_bars > self.stale_bars:
                weight *= 0.65
                adjustment -= 0.6
            adjustment += base * weight

        directions = {p.direction for p in all_confirmed if p.direction in {"long", "short"}}
        if "long" in directions and "short" in directions:
            adjustment -= 1.25
        return float(np.clip(adjustment, -3.0, 4.0))

    def _build_exit_plan(
        self,
        confirmed_for_side: List[PatternSignal],
        indicators: Dict[str, Any],
        latest_price: float,
    ) -> Optional[Dict[str, Any]]:
        if not confirmed_for_side or latest_price <= 0:
            return None

        strongest = max(confirmed_for_side, key=lambda p: p.confidence)
        atr_series = indicators.get("atr")
        atr_value = 0.0
        try:
            if atr_series is not None:
                atr_value = float(pd.Series(atr_series).dropna().iloc[-1])
        except Exception:
            atr_value = 0.0
        if not math.isfinite(atr_value) or atr_value <= 0:
            atr_value = latest_price * 0.01

        height = float(strongest.levels.get("height", 0.0) or 0.0)
        if height <= 0:
            height = max(atr_value * 1.8, latest_price * 0.004)
        buffer = atr_value * self.atr_stop_buffer
        invalidation = float(strongest.invalidation_price)

        if strongest.direction == "long":
            stop = max(0.0, invalidation - buffer)
            tp = [
                latest_price + height * 0.5,
                latest_price + height,
                latest_price + height * 1.5,
            ]
        else:
            stop = invalidation + buffer
            tp = [
                latest_price - height * 0.5,
                latest_price - height,
                latest_price - height * 1.5,
            ]
        return {
            "source_pattern": strongest.pattern_name,
            "direction": strongest.direction,
            "confidence": float(strongest.confidence),
            "invalidation_price": invalidation,
            "atr_buffer": float(buffer),
            "stop_loss": float(stop),
            "targets": [float(x) for x in tp],
            "confirmed": True,
        }
