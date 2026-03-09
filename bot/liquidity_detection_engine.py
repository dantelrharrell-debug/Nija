"""
NIJA Liquidity Detection Engine — Institutional Move Detector
=============================================================

Detects and alerts on **institutional-scale market activity** by analysing
order-flow imbalances, abnormal volume surges, and spread compression or
expansion that are characteristic of large-player participation.

Detection pillars
-----------------
1. **Volume Anomaly Detection** — Z-score of recent volume vs. a rolling
   baseline; sudden spikes signal institutional accumulation/distribution.
2. **Order-Flow Imbalance (OFI)** — Buy volume vs. sell volume ratio per
   bar; sustained imbalance indicates directional institutional pressure.
3. **Spread Compression / Expansion** — Tight spreads attract HFT/MM flow;
   sudden spread widening signals liquidity withdrawal.
4. **Price Impact Analysis** — Large volume producing little price movement
   indicates absorption (institutional buying/selling into liquidity).
5. **Composite Institutional Score (0–100)** — Weighted combination of the
   above signals; thresholded into NONE / WATCH / ALERT / STRONG alert
   levels.

Public API
----------
::

    from bot.liquidity_detection_engine import get_liquidity_detection_engine

    engine = get_liquidity_detection_engine()

    # Feed a new bar:
    signal = engine.update(
        symbol="BTC-USD",
        volume_usd=1_500_000.0,
        buy_volume_usd=950_000.0,
        spread_pct=0.0008,
        price=65_000.0,
    )

    if signal.alert_level in ("ALERT", "STRONG"):
        print(f"Institutional activity on {symbol}: {signal}")

    # Portfolio-level summary:
    report = engine.get_portfolio_report()

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import math
import threading
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger("nija.liquidity_detection")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Rolling window (bars) for volume baseline statistics
VOLUME_BASELINE_WINDOW: int = 50

# Z-score threshold for volume anomaly alerts
ZSCORE_WATCH: float = 1.5
ZSCORE_ALERT: float = 2.5
ZSCORE_STRONG: float = 4.0

# Order-flow imbalance thresholds (ratio: buy_vol / total_vol)
OFI_NEUTRAL_LO: float = 0.40
OFI_NEUTRAL_HI: float = 0.60
OFI_ALERT: float = 0.70       # ≥ 70% buy or ≤ 30% buy → directional pressure
OFI_STRONG: float = 0.80      # ≥ 80% buy or ≤ 20% buy → strong institutional

# Price-impact absorption: high volume + low price move → absorption signal
PRICE_IMPACT_HIGH_VOL_ZSCORE: float = 2.0
PRICE_IMPACT_LOW_MOVE_PCT: float = 0.003  # < 0.30% price change despite high vol

# Spread compression factor (EMA-smoothed vs. recent raw)
SPREAD_COMPRESSION_FACTOR: float = 0.50  # raw ≤ 50% of EMA → HFT/MM attracted
SPREAD_EXPANSION_FACTOR: float = 2.0     # raw ≥ 200% of EMA → liquidity withdrawn

# Component weights for composite score
WEIGHT_VOLUME: float = 0.35
WEIGHT_OFI: float = 0.30
WEIGHT_SPREAD: float = 0.20
WEIGHT_ABSORPTION: float = 0.15

# EMA alpha for spread smoothing
SPREAD_EMA_ALPHA: float = 0.15

# Per-symbol history cap
MAX_HISTORY_PER_SYMBOL: int = 200

# Alert levels
_ALERT_LEVELS: List[Tuple[float, str]] = [
    (75.0, "STRONG"),
    (50.0, "ALERT"),
    (25.0, "WATCH"),
    (0.0, "NONE"),
]


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class InstitutionalSignal:
    """Result from a single ``update()`` call."""
    symbol: str
    alert_level: str                  # NONE | WATCH | ALERT | STRONG
    institutional_score: float        # 0–100
    volume_zscore: float
    ofi_ratio: float                  # 0–1 (buy / total)
    spread_pct: float
    absorption_detected: bool
    direction: str                    # "BUY_PRESSURE" | "SELL_PRESSURE" | "NEUTRAL"
    details: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class _SymbolState:
    """Internal per-symbol rolling state."""
    volume_history: Deque[float] = field(
        default_factory=lambda: deque(maxlen=VOLUME_BASELINE_WINDOW)
    )
    price_history: Deque[float] = field(
        default_factory=lambda: deque(maxlen=MAX_HISTORY_PER_SYMBOL)
    )
    spread_ema: float = 0.0
    last_signal: Optional[InstitutionalSignal] = None
    alert_count: int = 0


# ---------------------------------------------------------------------------
# LiquidityDetectionEngine
# ---------------------------------------------------------------------------


class LiquidityDetectionEngine:
    """
    Detects institutional/smart-money moves via multi-pillar analysis.

    Thread-safe; single process-wide singleton via ``get_liquidity_detection_engine()``.
    """

    def __init__(
        self,
        volume_baseline_window: int = VOLUME_BASELINE_WINDOW,
        zscore_watch: float = ZSCORE_WATCH,
        zscore_alert: float = ZSCORE_ALERT,
        zscore_strong: float = ZSCORE_STRONG,
        ofi_alert: float = OFI_ALERT,
        ofi_strong: float = OFI_STRONG,
    ) -> None:
        self._lock = threading.Lock()
        self._vol_window = volume_baseline_window
        self._zs_watch = zscore_watch
        self._zs_alert = zscore_alert
        self._zs_strong = zscore_strong
        self._ofi_alert = ofi_alert
        self._ofi_strong = ofi_strong

        self._symbols: Dict[str, _SymbolState] = defaultdict(_SymbolState)
        self._portfolio_alerts: Deque[InstitutionalSignal] = deque(maxlen=500)

        logger.info("=" * 60)
        logger.info("🔍 Liquidity Detection Engine initialised")
        logger.info("   volume_baseline_window : %d bars", volume_baseline_window)
        logger.info("   zscore thresholds      : WATCH=%.1f ALERT=%.1f STRONG=%.1f",
                    zscore_watch, zscore_alert, zscore_strong)
        logger.info("   OFI thresholds         : ALERT=%.0f%% STRONG=%.0f%%",
                    ofi_alert * 100, ofi_strong * 100)
        logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Core update
    # ------------------------------------------------------------------

    def update(
        self,
        symbol: str,
        volume_usd: float,
        buy_volume_usd: Optional[float] = None,
        spread_pct: float = 0.001,
        price: float = 0.0,
    ) -> InstitutionalSignal:
        """
        Process one price bar for a symbol and return an ``InstitutionalSignal``.

        Parameters
        ----------
        symbol : str
            Market identifier (e.g. "BTC-USD").
        volume_usd : float
            Total traded volume in USD for this bar.
        buy_volume_usd : float, optional
            Buy-side volume in USD.  If omitted, OFI component is neutral.
        spread_pct : float
            Current best bid-ask spread as a fraction of price.
        price : float
            Current mid-price.
        """
        with self._lock:
            state = self._symbols[symbol]

            # ── 1. Volume Z-Score ─────────────────────────────────────
            state.volume_history.append(volume_usd)
            if len(state.volume_history) >= 5:
                vol_arr = np.array(state.volume_history)
                vol_mean = float(np.mean(vol_arr))
                vol_std = float(np.std(vol_arr)) or 1.0
                vol_zscore = (volume_usd - vol_mean) / vol_std
            else:
                vol_zscore = 0.0

            vol_score = self._zscore_to_score(vol_zscore)

            # ── 2. Order-Flow Imbalance ───────────────────────────────
            if buy_volume_usd is not None and volume_usd > 0:
                ofi_ratio = min(1.0, max(0.0, buy_volume_usd / volume_usd))
            else:
                ofi_ratio = 0.5  # neutral when not provided

            ofi_score = self._ofi_to_score(ofi_ratio)

            # Determine directional pressure
            if ofi_ratio >= self._ofi_alert:
                direction = "BUY_PRESSURE"
            elif ofi_ratio <= (1.0 - self._ofi_alert):
                direction = "SELL_PRESSURE"
            else:
                direction = "NEUTRAL"

            # ── 3. Spread Analysis ────────────────────────────────────
            if state.spread_ema == 0.0:
                state.spread_ema = spread_pct
            else:
                state.spread_ema = (
                    SPREAD_EMA_ALPHA * spread_pct
                    + (1 - SPREAD_EMA_ALPHA) * state.spread_ema
                )

            spread_score = self._spread_to_score(spread_pct, state.spread_ema)

            # ── 4. Absorption Detection ───────────────────────────────
            if price > 0:
                state.price_history.append(price)

            absorption_detected = False
            if (
                len(state.price_history) >= 2
                and vol_zscore >= PRICE_IMPACT_HIGH_VOL_ZSCORE
                and price > 0
            ):
                price_move_pct = abs(
                    (state.price_history[-1] - state.price_history[-2])
                    / state.price_history[-2]
                )
                if price_move_pct < PRICE_IMPACT_LOW_MOVE_PCT:
                    absorption_detected = True

            absorption_score = 100.0 if absorption_detected else 0.0

            # ── Composite score ───────────────────────────────────────
            institutional_score = (
                WEIGHT_VOLUME * vol_score
                + WEIGHT_OFI * ofi_score
                + WEIGHT_SPREAD * spread_score
                + WEIGHT_ABSORPTION * absorption_score
            )

            alert_level = self._score_to_alert(institutional_score)

            signal = InstitutionalSignal(
                symbol=symbol,
                alert_level=alert_level,
                institutional_score=round(institutional_score, 2),
                volume_zscore=round(vol_zscore, 3),
                ofi_ratio=round(ofi_ratio, 4),
                spread_pct=round(spread_pct, 6),
                absorption_detected=absorption_detected,
                direction=direction,
                details={
                    "volume_usd": round(volume_usd, 2),
                    "vol_score": round(vol_score, 2),
                    "ofi_score": round(ofi_score, 2),
                    "spread_score": round(spread_score, 2),
                    "absorption_score": round(absorption_score, 2),
                    "spread_ema": round(state.spread_ema, 6),
                },
            )

            state.last_signal = signal
            if alert_level in ("ALERT", "STRONG"):
                state.alert_count += 1
                self._portfolio_alerts.append(signal)
                logger.info(
                    "🐋 Institutional signal [%s] %s — score %.1f | %s",
                    alert_level, symbol, institutional_score, direction,
                )

            return signal

    # ------------------------------------------------------------------
    # Portfolio reporting
    # ------------------------------------------------------------------

    def get_portfolio_report(self) -> Dict[str, Any]:
        """Return a summary of current institutional signals across all symbols."""
        with self._lock:
            active_alerts = []
            for sym, state in self._symbols.items():
                if state.last_signal and state.last_signal.alert_level != "NONE":
                    active_alerts.append({
                        "symbol": sym,
                        "alert_level": state.last_signal.alert_level,
                        "score": state.last_signal.institutional_score,
                        "direction": state.last_signal.direction,
                        "alert_count": state.alert_count,
                        "timestamp": state.last_signal.timestamp,
                    })

            active_alerts.sort(key=lambda x: x["score"], reverse=True)

            return {
                "engine": "LiquidityDetectionEngine",
                "version": "1.0",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "tracked_symbols": len(self._symbols),
                "active_alerts": active_alerts,
                "total_portfolio_alerts": len(self._portfolio_alerts),
            }

    def get_symbol_signal(self, symbol: str) -> Optional[InstitutionalSignal]:
        """Return the most recent signal for a symbol, or None."""
        with self._lock:
            state = self._symbols.get(symbol)
            return state.last_signal if state else None

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _zscore_to_score(zscore: float) -> float:
        """Map volume Z-score to a 0–100 score."""
        if zscore <= 0:
            return 0.0
        if zscore >= ZSCORE_STRONG:
            return 100.0
        return min(100.0, (zscore / ZSCORE_STRONG) * 100.0)

    @staticmethod
    def _ofi_to_score(ofi_ratio: float) -> float:
        """Map OFI ratio to 0–100 score (extremes = high institutional score)."""
        deviation = abs(ofi_ratio - 0.5) * 2.0  # 0 at neutral, 1 at extreme
        return min(100.0, deviation * 100.0)

    @staticmethod
    def _spread_to_score(spread_pct: float, spread_ema: float) -> float:
        """
        Map spread dynamics to 0–100 score.
        Compression (HFT/MM attracted) and expansion (liquidity withdrawn) both score high.
        """
        if spread_ema == 0:
            return 0.0
        ratio = spread_pct / spread_ema
        if ratio <= SPREAD_COMPRESSION_FACTOR:
            # Compressed → institutional interest
            return 75.0
        if ratio >= SPREAD_EXPANSION_FACTOR:
            # Expanded → liquidity withdrawal
            return 100.0
        return 0.0

    @staticmethod
    def _score_to_alert(score: float) -> str:
        for threshold, level in _ALERT_LEVELS:
            if score >= threshold:
                return level
        return "NONE"


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[LiquidityDetectionEngine] = None
_instance_lock = threading.Lock()


def get_liquidity_detection_engine(**kwargs) -> LiquidityDetectionEngine:
    """
    Return the process-wide ``LiquidityDetectionEngine`` singleton.

    Keyword arguments are forwarded to the constructor on first call only.
    """
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = LiquidityDetectionEngine(**kwargs)
        return _instance


__all__ = [
    "InstitutionalSignal",
    "LiquidityDetectionEngine",
    "get_liquidity_detection_engine",
]
