"""
NIJA Market Phase Detector
===========================

Detects the four canonical market cycle phases:

1. Accumulation  — Smart money quietly buying after a downtrend; price
                   moves sideways with rising volume at support.
2. Expansion     — Price breaks out and trends upward; strong momentum,
                   high volume, and widening Bollinger Bands.
3. Distribution  — Smart money distributing holdings near the top; price
                   moves sideways with elevated volume near resistance.
4. Capitulation  — Forced selling / panic; sharp price drops, volume
                   spikes, and RSI deeply oversold.

Detection uses a multi-indicator scoring approach:
- RSI (momentum / oversold / overbought)
- ADX (trend strength)
- ATR (volatility expansion / contraction)
- Bollinger Band width (volatility regime)
- Volume profile (accumulation vs. distribution)
- Price position relative to moving averages (20 EMA, 50 EMA, 200 EMA)

A module-level singleton is provided via ``get_market_phase_detector()``.

Usage
-----
    from bot.market_phase_detector import get_market_phase_detector

    detector = get_market_phase_detector()
    result = detector.detect(ohlcv_df)
    print(result.phase.value, result.confidence)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

import logging
import numpy as np
import pandas as pd
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.market_phase")

# ---------------------------------------------------------------------------
# Phase enum
# ---------------------------------------------------------------------------


class MarketPhase(Enum):
    """The four canonical market cycle phases."""
    ACCUMULATION = "accumulation"   # Base-building after a downtrend
    EXPANSION    = "expansion"      # Upward breakout / markup
    DISTRIBUTION = "distribution"  # Top-building before a downtrend
    CAPITULATION = "capitulation"   # Panic selling / markdown


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------


@dataclass
class MarketPhaseResult:
    """Output of a single phase-detection run."""
    phase: MarketPhase
    confidence: float                        # 0.0 – 1.0
    phase_scores: Dict[str, float]           # raw score per phase (0–1)
    features: Dict[str, float]               # indicator values used
    signal: str                              # human-readable summary
    recommended_action: str                  # BUY / HOLD / REDUCE / SELL
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict:
        return {
            "phase": self.phase.value,
            "confidence": round(self.confidence, 4),
            "phase_scores": {k: round(v, 4) for k, v in self.phase_scores.items()},
            "features": {k: round(v, 4) if isinstance(v, float) else v
                         for k, v in self.features.items()},
            "signal": self.signal,
            "recommended_action": self.recommended_action,
            "timestamp": self.timestamp.isoformat(),
        }


# ---------------------------------------------------------------------------
# Recommended actions per phase
# ---------------------------------------------------------------------------

_PHASE_ACTIONS: Dict[MarketPhase, str] = {
    MarketPhase.ACCUMULATION: "BUY",     # Look for long entries
    MarketPhase.EXPANSION:    "HOLD",    # Ride the trend, trail stops
    MarketPhase.DISTRIBUTION: "REDUCE",  # Begin scaling out
    MarketPhase.CAPITULATION: "SELL",    # Exit or short; wait for reversal
}


# ---------------------------------------------------------------------------
# Core detector
# ---------------------------------------------------------------------------


class MarketPhaseDetector:
    """
    Detects which of the four market cycle phases the current bar occupies.

    Parameters
    ----------
    rsi_period : int
        Look-back for RSI (default 14).
    adx_period : int
        Look-back for ADX / DI (default 14).
    atr_period : int
        Look-back for ATR (default 14).
    bb_period : int
        Look-back for Bollinger Band width (default 20).
    volume_period : int
        Look-back for volume moving average (default 20).
    ema_fast : int
        Fast EMA (default 20).
    ema_slow : int
        Slow EMA (default 50).
    ema_long : int
        Long EMA (default 200).
    min_bars : int
        Minimum number of bars required (default 210).
    """

    def __init__(
        self,
        rsi_period: int = 14,
        adx_period: int = 14,
        atr_period: int = 14,
        bb_period: int = 20,
        volume_period: int = 20,
        ema_fast: int = 20,
        ema_slow: int = 50,
        ema_long: int = 200,
        min_bars: int = 210,
    ) -> None:
        self.rsi_period    = rsi_period
        self.adx_period    = adx_period
        self.atr_period    = atr_period
        self.bb_period     = bb_period
        self.volume_period = volume_period
        self.ema_fast      = ema_fast
        self.ema_slow      = ema_slow
        self.ema_long      = ema_long
        self.min_bars      = min_bars
        logger.info("MarketPhaseDetector initialised (rsi=%d adx=%d atr=%d bb=%d)",
                    rsi_period, adx_period, atr_period, bb_period)

    # ── public ───────────────────────────────────────────────────────────────

    def detect(self, df: pd.DataFrame) -> Optional[MarketPhaseResult]:
        """
        Detect the current market phase.

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV data with columns ``open``, ``high``, ``low``, ``close``,
            ``volume`` (case-insensitive).  Must contain at least
            ``min_bars`` rows; rows are ordered oldest-first.

        Returns
        -------
        MarketPhaseResult or None
            None if there is insufficient data.
        """
        df = self._normalise(df)
        if df is None or len(df) < self.min_bars:
            logger.warning("Not enough bars for phase detection (%d < %d)",
                           len(df) if df is not None else 0, self.min_bars)
            return None

        features = self._compute_features(df)
        scores   = self._score_phases(features)

        best_phase = max(scores, key=lambda p: scores[p])
        confidence = scores[best_phase]

        return MarketPhaseResult(
            phase=best_phase,
            confidence=confidence,
            phase_scores={p.value: s for p, s in scores.items()},
            features=features,
            signal=self._build_signal(best_phase, confidence, features),
            recommended_action=_PHASE_ACTIONS[best_phase],
        )

    # ── internal helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _normalise(df: pd.DataFrame) -> Optional[pd.DataFrame]:
        """Lowercase column names and validate required columns."""
        if df is None or df.empty:
            return None
        df = df.copy()
        df.columns = [c.lower() for c in df.columns]
        required = {"open", "high", "low", "close", "volume"}
        if not required.issubset(df.columns):
            missing = required - set(df.columns)
            logger.error("OHLCV dataframe missing columns: %s", missing)
            return None
        df = df.dropna(subset=list(required))
        return df

    def _compute_features(self, df: pd.DataFrame) -> Dict[str, float]:
        """Compute all indicator features from the dataframe."""
        close  = df["close"]
        high   = df["high"]
        low    = df["low"]
        volume = df["volume"]

        rsi    = self._rsi(close)
        atr    = self._atr(high, low, close)
        adx, plus_di, minus_di = self._adx(high, low, close)
        bb_width = self._bb_width(close)
        vol_ratio = volume.iloc[-1] / volume.rolling(self.volume_period).mean().iloc[-1]

        ema_f = close.ewm(span=self.ema_fast,  adjust=False).mean().iloc[-1]
        ema_s = close.ewm(span=self.ema_slow,  adjust=False).mean().iloc[-1]
        ema_l = close.ewm(span=self.ema_long,  adjust=False).mean().iloc[-1]
        price = close.iloc[-1]

        price_vs_ema_fast = (price - ema_f) / ema_f  # positive = above
        price_vs_ema_slow = (price - ema_s) / ema_s
        price_vs_ema_long = (price - ema_l) / ema_l

        # ATR as % of price (normalised volatility)
        atr_pct = atr / price if price > 0 else 0.0

        # 20-bar price range (for range-bound detection)
        recent_high = high.rolling(20).max().iloc[-1]
        recent_low  = low.rolling(20).min().iloc[-1]
        price_range_pct = (recent_high - recent_low) / recent_low if recent_low > 0 else 0.0

        # Slope of close over last 5 bars (momentum direction)
        ref_price = close.iloc[-6]
        momentum_slope = ((close.iloc[-1] - ref_price) / ref_price
                         if len(close) >= 6 and ref_price != 0 else 0.0)

        return {
            "rsi":               float(rsi),
            "adx":               float(adx),
            "plus_di":           float(plus_di),
            "minus_di":          float(minus_di),
            "atr_pct":           float(atr_pct),
            "bb_width":          float(bb_width),
            "volume_ratio":      float(vol_ratio),
            "price_vs_ema_fast": float(price_vs_ema_fast),
            "price_vs_ema_slow": float(price_vs_ema_slow),
            "price_vs_ema_long": float(price_vs_ema_long),
            "price_range_pct":   float(price_range_pct),
            "momentum_slope":    float(momentum_slope),
        }

    def _score_phases(self, f: Dict[str, float]) -> Dict[MarketPhase, float]:
        """
        Score each phase 0–1 using a weighted multi-condition approach.

        Each phase accumulates evidence from multiple indicators.
        The raw totals are softmax-normalised to produce probabilities.
        """

        # ── Accumulation ────────────────────────────────────────────────────
        # Characteristics: price near / below long EMA, low ADX (sideways),
        # RSI emerging from oversold, volume slowly rising, BB width narrow.
        acc = 0.0
        acc += self._clamp(1 - f["adx"] / 40)                             # low ADX (< 20 ideal)
        acc += self._clamp((35 - f["rsi"]) / 20) if f["rsi"] < 50 else 0  # RSI recovering from oversold
        acc += self._clamp((-f["price_vs_ema_long"] + 0.05) / 0.10)       # price below / near long EMA
        acc += self._clamp((0.05 - abs(f["momentum_slope"])) / 0.05)      # flat / sideways price action
        acc += self._clamp((f["volume_ratio"] - 0.8) / 0.6)               # modest volume pickup
        acc += self._clamp((0.04 - f["bb_width"]) / 0.04)                 # tight Bollinger Band

        # ── Expansion ───────────────────────────────────────────────────────
        # Characteristics: price above all EMAs, rising ADX, RSI 55–75,
        # momentum slope positive, high volume, BB expanding.
        exp = 0.0
        exp += self._clamp(f["adx"] / 40)                                 # rising ADX
        exp += self._clamp((f["rsi"] - 50) / 30) if f["rsi"] > 50 else 0  # RSI in bullish zone
        exp += self._clamp(f["price_vs_ema_fast"] / 0.05)                 # price above fast EMA
        exp += self._clamp(f["price_vs_ema_slow"] / 0.05)                 # price above slow EMA
        exp += self._clamp(f["momentum_slope"] / 0.05)                    # positive 5-bar slope
        exp += self._clamp((f["volume_ratio"] - 1.0) / 1.0)              # elevated volume
        exp += self._clamp((f["bb_width"] - 0.02) / 0.04)                # expanding Bollinger Band

        # ── Distribution ────────────────────────────────────────────────────
        # Characteristics: price near / above slow EMA, ADX declining,
        # RSI elevated but losing momentum (< 70), volume high but
        # price not making new highs, BB pinching.
        dis = 0.0
        dis += self._clamp((30 - f["adx"]) / 30) if f["adx"] < 35 else 0  # ADX fading from peak
        dis += self._clamp((f["rsi"] - 60) / 15) if 60 < f["rsi"] < 80 else 0  # overbought zone
        dis += self._clamp(f["price_vs_ema_slow"] / 0.05)                 # still above slow EMA
        # Price near but not far above long EMA — top-building range
        # Score peaks when price_vs_ema_long ≈ 0; tapers to 0 at ±0.10
        dis += self._clamp(1 - abs(f["price_vs_ema_long"]) / 0.10)
        dis += self._clamp((0.02 - f["momentum_slope"]) / 0.04)           # slowing upward momentum
        dis += self._clamp((f["volume_ratio"] - 0.9) / 0.6)              # still elevated volume

        # ── Capitulation ────────────────────────────────────────────────────
        # Characteristics: price below all EMAs, RSI deeply oversold (< 30),
        # momentum sharply negative, volume spike, ATR spike.
        cap = 0.0
        cap += self._clamp((30 - f["rsi"]) / 30) if f["rsi"] < 40 else 0  # deeply oversold RSI
        cap += self._clamp(-f["price_vs_ema_fast"] / 0.05)                # price below fast EMA
        cap += self._clamp(-f["price_vs_ema_slow"] / 0.05)                # price below slow EMA
        cap += self._clamp(-f["momentum_slope"] / 0.05)                   # sharp downward slope
        cap += self._clamp((f["volume_ratio"] - 1.2) / 1.0)              # volume surge (panic)
        cap += self._clamp((f["atr_pct"] - 0.02) / 0.04)                 # ATR spike (high fear)

        raw = {
            MarketPhase.ACCUMULATION: acc,
            MarketPhase.EXPANSION:    exp,
            MarketPhase.DISTRIBUTION: dis,
            MarketPhase.CAPITULATION: cap,
        }

        # Normalise scores so they sum to 1 (linear normalisation)
        values = np.array(list(raw.values()), dtype=float)
        values = np.clip(values, 0, None)
        total  = values.sum()
        if total > 0:
            values /= total

        return {phase: float(values[i]) for i, phase in enumerate(raw)}

    @staticmethod
    def _clamp(x: float) -> float:
        """Clamp a value to [0, 1]."""
        return float(np.clip(x, 0.0, 1.0))

    # ── Indicator helpers ─────────────────────────────────────────────────

    def _rsi(self, close: pd.Series) -> float:
        delta  = close.diff()
        gain   = delta.clip(lower=0).ewm(com=self.rsi_period - 1, adjust=False).mean()
        loss   = (-delta.clip(upper=0)).ewm(com=self.rsi_period - 1, adjust=False).mean()
        rs     = gain / loss.replace(0, np.nan)
        rsi    = 100 - (100 / (1 + rs))
        return float(rsi.iloc[-1])

    def _atr(self, high: pd.Series, low: pd.Series, close: pd.Series) -> float:
        prev_close = close.shift(1)
        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low  - prev_close).abs(),
        ], axis=1).max(axis=1)
        return float(tr.ewm(span=self.atr_period, adjust=False).mean().iloc[-1])

    def _adx(
        self, high: pd.Series, low: pd.Series, close: pd.Series
    ) -> Tuple[float, float, float]:
        """Return (ADX, +DI, -DI)."""
        prev_high  = high.shift(1)
        prev_low   = low.shift(1)
        prev_close = close.shift(1)

        up_move    = high - prev_high
        down_move  = prev_low - low

        plus_dm  = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
        minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)

        tr = pd.concat([
            high - low,
            (high - prev_close).abs(),
            (low  - prev_close).abs(),
        ], axis=1).max(axis=1)

        n   = self.adx_period
        atr = tr.ewm(span=n, adjust=False).mean()
        pdm = pd.Series(plus_dm,  index=high.index).ewm(span=n, adjust=False).mean()
        ndm = pd.Series(minus_dm, index=high.index).ewm(span=n, adjust=False).mean()

        plus_di  = 100 * pdm / atr.replace(0, np.nan)
        minus_di = 100 * ndm / atr.replace(0, np.nan)

        dx  = (100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan))
        adx = dx.ewm(span=n, adjust=False).mean()

        return (
            float(adx.iloc[-1]  if not np.isnan(adx.iloc[-1])  else 0.0),
            float(plus_di.iloc[-1]  if not np.isnan(plus_di.iloc[-1])  else 0.0),
            float(minus_di.iloc[-1] if not np.isnan(minus_di.iloc[-1]) else 0.0),
        )

    def _bb_width(self, close: pd.Series) -> float:
        """Bollinger Band width as fraction of middle band."""
        sma   = close.rolling(self.bb_period).mean()
        std   = close.rolling(self.bb_period).std()
        upper = sma + 2 * std
        lower = sma - 2 * std
        width = (upper - lower) / sma.replace(0, np.nan)
        return float(width.iloc[-1])

    # ── Signal builder ───────────────────────────────────────────────────

    @staticmethod
    def _build_signal(phase: MarketPhase, confidence: float, f: Dict[str, float]) -> str:
        rsi = f.get("rsi", 50)
        adx = f.get("adx", 20)
        vol = f.get("volume_ratio", 1.0)
        signals = {
            MarketPhase.ACCUMULATION: (
                f"Accumulation detected (confidence {confidence:.0%}): "
                f"RSI={rsi:.1f}, ADX={adx:.1f}, Vol×{vol:.2f}. "
                "Smart money may be building positions at support."
            ),
            MarketPhase.EXPANSION: (
                f"Expansion detected (confidence {confidence:.0%}): "
                f"RSI={rsi:.1f}, ADX={adx:.1f}, Vol×{vol:.2f}. "
                "Uptrend in progress — ride the trend with trailing stops."
            ),
            MarketPhase.DISTRIBUTION: (
                f"Distribution detected (confidence {confidence:.0%}): "
                f"RSI={rsi:.1f}, ADX={adx:.1f}, Vol×{vol:.2f}. "
                "Smart money may be distributing near highs — reduce risk."
            ),
            MarketPhase.CAPITULATION: (
                f"Capitulation detected (confidence {confidence:.0%}): "
                f"RSI={rsi:.1f}, ADX={adx:.1f}, Vol×{vol:.2f}. "
                "Panic selling detected — protect capital, watch for reversal."
            ),
        }
        return signals[phase]


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_INSTANCE: Optional[MarketPhaseDetector] = None


def get_market_phase_detector(**kwargs) -> MarketPhaseDetector:
    """Return the module-level singleton ``MarketPhaseDetector``.

    Any keyword arguments are forwarded to the constructor on first call
    and ignored on subsequent calls.
    """
    global _INSTANCE
    if _INSTANCE is None:
        _INSTANCE = MarketPhaseDetector(**kwargs)
        logger.info("MarketPhaseDetector singleton created.")
    return _INSTANCE
