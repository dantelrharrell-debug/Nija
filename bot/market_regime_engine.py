"""
NIJA Market Regime Engine
==========================

AI-powered market regime detection that classifies the current market
environment into one of three primary modes and dynamically controls
position sizing, trade frequency, and stop-loss width accordingly.

Primary regimes
---------------
* **BULL**   — Trending, momentum-driven upswing. Bot acts aggressively.
* **CHOP**   — Ranging / low-ADX environment. Bot slows down, trades less.
* **CRASH**  — Volatility spike + correlation breakdown. Bot goes defensive.

Detection methodology
---------------------
1. **Volatility** — ATR expansion ratio (current ATR / baseline ATR).
2. **Trend strength** — ADX (Average Directional Index).
3. **Liquidity shift** — volume surge ratio (current / baseline volume).

The three signals are combined via a weighted voting approach to produce a
regime classification with a confidence score.

Regime → behaviour mapping
--------------------------
::

    ┌──────────────────┬──────────────────────────────────────────────────┐
    │ Regime           │ position_mult │ freq_mult │ stop_mult │ label    │
    ├──────────────────┼───────────────┼───────────┼───────────┼──────────┤
    │ BULL             │     1.50      │   1.25    │   0.90    │ 🟢 Bull  │
    │ CHOP             │     0.60      │   0.50    │   1.10    │ 🟡 Chop  │
    │ CRASH            │     0.25      │   0.20    │   1.50    │ 🔴 Crash │
    └──────────────────┴───────────────┴───────────┴───────────┴──────────┘

Usage
-----
::

    from bot.market_regime_engine import get_market_regime_engine, Regime

    engine = get_market_regime_engine()

    # Feed a new candle on each bar:
    engine.update(close=42_000.0, high=42_500.0, low=41_800.0, volume=1_200.0)

    # Query the current regime:
    regime = engine.current_regime          # Regime.BULL / CHOP / CRASH
    confidence = engine.confidence          # 0.0 – 1.0
    size_mult = engine.position_size_multiplier
    freq_mult = engine.trade_frequency_multiplier
    stop_mult = engine.stop_loss_multiplier

    # Full human-readable report:
    print(engine.get_report())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Deque, List, Optional

logger = logging.getLogger("nija.market_regime_engine")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_ATR_PERIOD: int = 14
DEFAULT_ADX_PERIOD: int = 14
DEFAULT_VOL_BASELINE_BARS: int = 50   # bars used to compute baseline volume/ATR

# Regime thresholds
ATR_CRASH_RATIO: float = 2.5    # ATR expansion > 2.5× baseline → crash signal
ATR_BULL_RATIO: float = 1.3     # ATR mildly expanded with trend → bull signal
ADX_STRONG_TREND: float = 25.0  # ADX > 25 → trend regime
ADX_WEAK_TREND: float = 18.0    # ADX 18-25 → developing trend
VOL_SURGE_RATIO: float = 2.0    # Volume surge > 2× baseline → liquidity shift


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

class Regime(str, Enum):
    """Primary market regime classifications."""
    BULL = "BULL"
    CHOP = "CHOP"
    CRASH = "CRASH"
    UNKNOWN = "UNKNOWN"


@dataclass
class RegimeBehavior:
    """Trading-behaviour multipliers for each regime."""
    position_size_multiplier: float   # Scale position size by this factor
    trade_frequency_multiplier: float # Scale trade frequency by this factor
    stop_loss_multiplier: float       # Widen (>1) or tighten (<1) stop-loss
    label: str                        # Human-readable label with emoji


# Regime → behaviour map
REGIME_BEHAVIOR: dict[Regime, RegimeBehavior] = {
    Regime.BULL: RegimeBehavior(
        position_size_multiplier=1.50,
        trade_frequency_multiplier=1.25,
        stop_loss_multiplier=0.90,
        label="🟢 Bull",
    ),
    Regime.CHOP: RegimeBehavior(
        position_size_multiplier=0.60,
        trade_frequency_multiplier=0.50,
        stop_loss_multiplier=1.10,
        label="🟡 Chop",
    ),
    Regime.CRASH: RegimeBehavior(
        position_size_multiplier=0.25,
        trade_frequency_multiplier=0.20,
        stop_loss_multiplier=1.50,
        label="🔴 Crash",
    ),
    Regime.UNKNOWN: RegimeBehavior(
        position_size_multiplier=1.00,
        trade_frequency_multiplier=1.00,
        stop_loss_multiplier=1.00,
        label="⚪ Unknown",
    ),
}


@dataclass
class _Candle:
    """Minimal OHLCV data point."""
    close: float
    high: float
    low: float
    volume: float


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class MarketRegimeEngine:
    """
    AI Market Regime Engine — detects bull / chop / crash conditions and
    exposes behaviour multipliers that downstream systems consume.
    """

    def __init__(
        self,
        atr_period: int = DEFAULT_ATR_PERIOD,
        adx_period: int = DEFAULT_ADX_PERIOD,
        vol_baseline_bars: int = DEFAULT_VOL_BASELINE_BARS,
    ) -> None:
        self._atr_period = atr_period
        self._adx_period = adx_period
        self._vol_baseline_bars = vol_baseline_bars

        # Sliding windows
        self._candles: Deque[_Candle] = deque(maxlen=max(vol_baseline_bars + adx_period + 5, 200))

        # State
        self._regime: Regime = Regime.UNKNOWN
        self._confidence: float = 0.0
        self._atr_current: float = 0.0
        self._atr_baseline: float = 0.0
        self._adx_current: float = 0.0
        self._vol_current: float = 0.0
        self._vol_baseline: float = 0.0
        self._bars_in_regime: int = 0

        # Smoothed ATR (Wilder's EMA)
        self._atr_ema: Optional[float] = None
        self._plus_dm_ema: Optional[float] = None
        self._minus_dm_ema: Optional[float] = None
        self._tr_ema: Optional[float] = None

        self._lock = threading.Lock()
        logger.info(
            "MarketRegimeEngine initialised (ATR=%d, ADX=%d, vol_baseline=%d)",
            atr_period, adx_period, vol_baseline_bars,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update(
        self,
        close: float,
        high: float,
        low: float,
        volume: float = 0.0,
    ) -> Regime:
        """
        Ingest one new candle and re-classify the market regime.

        Parameters
        ----------
        close : float   Closing price.
        high  : float   High price.
        low   : float   Low price.
        volume: float   Trade volume (optional; if 0 liquidity signal ignored).

        Returns
        -------
        The newly computed :class:`Regime`.
        """
        with self._lock:
            candle = _Candle(close=close, high=high, low=low, volume=volume)
            self._candles.append(candle)

            if len(self._candles) < self._atr_period + 2:
                return self._regime  # not enough data yet

            prev_candle = list(self._candles)[-2]

            # ----- ATR (Wilder's smoothed) --------------------------------
            tr = max(
                high - low,
                abs(high - prev_candle.close),
                abs(low - prev_candle.close),
            )
            k = 1.0 / self._atr_period
            if self._atr_ema is None:
                self._atr_ema = tr
            else:
                self._atr_ema = self._atr_ema * (1 - k) + tr * k
            self._atr_current = self._atr_ema

            # Baseline ATR = simple mean over last vol_baseline_bars candles
            candles_list = list(self._candles)
            if len(candles_list) >= self._vol_baseline_bars:
                baseline_slice = candles_list[-self._vol_baseline_bars:-1]
                self._atr_baseline = sum(
                    max(c.high - c.low, 0.0001) for c in baseline_slice
                ) / len(baseline_slice)
            else:
                self._atr_baseline = self._atr_current or 0.0001

            # ----- ADX ----------------------------------------------------
            plus_dm = max(high - prev_candle.high, 0.0)
            minus_dm = max(prev_candle.low - low, 0.0)
            if plus_dm <= minus_dm:
                plus_dm = 0.0
            elif minus_dm < plus_dm:
                minus_dm = 0.0

            k_adx = 1.0 / self._adx_period
            if self._plus_dm_ema is None:
                self._plus_dm_ema = plus_dm
                self._minus_dm_ema = minus_dm
                self._tr_ema = tr
            else:
                self._plus_dm_ema = self._plus_dm_ema * (1 - k_adx) + plus_dm * k_adx
                self._minus_dm_ema = self._minus_dm_ema * (1 - k_adx) + minus_dm * k_adx
                self._tr_ema = self._tr_ema * (1 - k_adx) + tr * k_adx  # type: ignore[operator]

            tr_smooth = self._tr_ema or 0.0001
            plus_di = 100.0 * (self._plus_dm_ema / tr_smooth)  # type: ignore[operator]
            minus_di = 100.0 * (self._minus_dm_ema / tr_smooth)  # type: ignore[operator]
            di_sum = plus_di + minus_di
            dx = 100.0 * abs(plus_di - minus_di) / di_sum if di_sum > 0 else 0.0
            self._adx_current = dx

            # ----- Volume baseline ----------------------------------------
            self._vol_current = volume
            if len(candles_list) >= self._vol_baseline_bars and volume > 0:
                vol_slice = [c.volume for c in candles_list[-self._vol_baseline_bars:-1] if c.volume > 0]
                self._vol_baseline = sum(vol_slice) / len(vol_slice) if vol_slice else volume
            else:
                self._vol_baseline = volume or 1.0

            # ----- Classify -----------------------------------------------
            old_regime = self._regime
            self._regime, self._confidence = self._classify()
            if self._regime == old_regime:
                self._bars_in_regime += 1
            else:
                logger.info(
                    "Regime change: %s → %s (confidence=%.2f)",
                    old_regime.value, self._regime.value, self._confidence,
                )
                self._bars_in_regime = 1

            return self._regime

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def current_regime(self) -> Regime:
        """Current market regime classification."""
        with self._lock:
            return self._regime

    @property
    def confidence(self) -> float:
        """Confidence of the current regime classification (0–1)."""
        with self._lock:
            return self._confidence

    @property
    def position_size_multiplier(self) -> float:
        """Multiply base position size by this factor."""
        with self._lock:
            return REGIME_BEHAVIOR[self._regime].position_size_multiplier

    @property
    def trade_frequency_multiplier(self) -> float:
        """Scale trade frequency by this factor (0–1 means fewer trades)."""
        with self._lock:
            return REGIME_BEHAVIOR[self._regime].trade_frequency_multiplier

    @property
    def stop_loss_multiplier(self) -> float:
        """Multiply stop-loss distance by this factor."""
        with self._lock:
            return REGIME_BEHAVIOR[self._regime].stop_loss_multiplier

    @property
    def behavior(self) -> RegimeBehavior:
        """Full behaviour dataclass for the current regime."""
        with self._lock:
            return REGIME_BEHAVIOR[self._regime]

    @property
    def metrics(self) -> dict:
        """Raw underlying metric snapshot (for diagnostics)."""
        with self._lock:
            atr_ratio = (self._atr_current / self._atr_baseline) if self._atr_baseline > 0 else 1.0
            vol_ratio = (self._vol_current / self._vol_baseline) if self._vol_baseline > 0 else 1.0
            return {
                "regime": self._regime.value,
                "confidence": round(self._confidence, 4),
                "atr_current": round(self._atr_current, 6),
                "atr_baseline": round(self._atr_baseline, 6),
                "atr_expansion_ratio": round(atr_ratio, 3),
                "adx": round(self._adx_current, 2),
                "volume_current": round(self._vol_current, 2),
                "volume_baseline": round(self._vol_baseline, 2),
                "volume_surge_ratio": round(vol_ratio, 3),
                "bars_in_regime": self._bars_in_regime,
                "candles_buffered": len(self._candles),
            }

    # ------------------------------------------------------------------
    # Classification logic
    # ------------------------------------------------------------------

    def _classify(self) -> tuple[Regime, float]:
        """
        Weighted vote across three signals: volatility, trend, liquidity.

        Returns (Regime, confidence).
        """
        atr_ratio = (self._atr_current / self._atr_baseline) if self._atr_baseline > 0 else 1.0
        adx = self._adx_current
        vol_ratio = (self._vol_current / self._vol_baseline) if self._vol_baseline > 0 else 1.0

        # -- Vote for CRASH -----------------------------------------------
        # Primary signal: extreme ATR expansion AND volume surge
        crash_score = 0.0
        if atr_ratio >= ATR_CRASH_RATIO:
            crash_score += 0.6
        elif atr_ratio >= ATR_CRASH_RATIO * 0.8:
            crash_score += 0.3
        if vol_ratio >= VOL_SURGE_RATIO:
            crash_score += 0.3
        elif vol_ratio >= VOL_SURGE_RATIO * 0.7:
            crash_score += 0.1
        # Low ADX with extreme ATR = panic / crash (not a trend)
        if adx < ADX_WEAK_TREND and atr_ratio >= ATR_CRASH_RATIO * 0.8:
            crash_score += 0.1

        # -- Vote for BULL -----------------------------------------------
        bull_score = 0.0
        if adx >= ADX_STRONG_TREND:
            bull_score += 0.5
        elif adx >= ADX_WEAK_TREND:
            bull_score += 0.25
        # Mild ATR expansion with trend = healthy bull
        if ATR_BULL_RATIO <= atr_ratio < ATR_CRASH_RATIO * 0.7:
            bull_score += 0.3
        elif atr_ratio < ATR_BULL_RATIO:
            bull_score += 0.1
        # Volume in line (not surging) = orderly trend
        if 0.8 <= vol_ratio <= VOL_SURGE_RATIO * 0.7:
            bull_score += 0.2

        # -- Vote for CHOP -----------------------------------------------
        # Low ADX + normal ATR + no volume surge = sideways range
        chop_score = 0.0
        if adx < ADX_WEAK_TREND:
            chop_score += 0.5
        elif adx < ADX_STRONG_TREND:
            chop_score += 0.2
        if atr_ratio < ATR_BULL_RATIO:
            chop_score += 0.3
        if vol_ratio < 1.2:
            chop_score += 0.2

        # -- Determine winner --------------------------------------------
        scores = {
            Regime.CRASH: crash_score,
            Regime.BULL: bull_score,
            Regime.CHOP: chop_score,
        }
        best_regime = max(scores, key=lambda r: scores[r])
        best_score = scores[best_regime]
        total = sum(scores.values()) or 1.0
        confidence = best_score / total

        # Not enough data or all scores too low
        if best_score < 0.1:
            return Regime.UNKNOWN, 0.0

        return best_regime, min(confidence, 1.0)

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_report(self) -> str:
        """Human-readable regime status report."""
        m = self.metrics
        b = self.behavior
        lines = [
            "═══════════════════════════════════════════════════",
            "  NIJA Market Regime Engine",
            "═══════════════════════════════════════════════════",
            f"  Regime         : {b.label}  (confidence={m['confidence']:.0%})",
            f"  Bars in regime : {m['bars_in_regime']}",
            "───────────────────────────────────────────────────",
            "  Underlying signals:",
            f"    ATR expansion : {m['atr_expansion_ratio']:.2f}× baseline",
            f"    ADX           : {m['adx']:.1f}",
            f"    Volume surge  : {m['volume_surge_ratio']:.2f}× baseline",
            "───────────────────────────────────────────────────",
            "  Behaviour multipliers:",
            f"    Position size : {b.position_size_multiplier:.2f}×",
            f"    Trade freq    : {b.trade_frequency_multiplier:.2f}×",
            f"    Stop-loss     : {b.stop_loss_multiplier:.2f}×",
            "═══════════════════════════════════════════════════",
        ]
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_INSTANCE: Optional[MarketRegimeEngine] = None
_INSTANCE_LOCK = threading.Lock()


def get_market_regime_engine(
    atr_period: int = DEFAULT_ATR_PERIOD,
    adx_period: int = DEFAULT_ADX_PERIOD,
    vol_baseline_bars: int = DEFAULT_VOL_BASELINE_BARS,
) -> MarketRegimeEngine:
    """
    Thread-safe singleton accessor.

    All callers share the same engine instance, ensuring regime state is
    consistent across the bot.
    """
    global _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is None:
            _INSTANCE = MarketRegimeEngine(
                atr_period=atr_period,
                adx_period=adx_period,
                vol_baseline_bars=vol_baseline_bars,
            )
    return _INSTANCE
