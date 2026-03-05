"""
NIJA Market Regime Controller
==============================

Monitors key market health metrics and controls bot behaviour per regime.

Monitors:
    - Volatility      (ATR % of price; price-return std-dev)
    - Trend strength  (ADX)
    - Market breadth  (fraction of scanned symbols in uptrend)
    - Liquidity       (24-h volume relative to a minimum threshold)

Regimes & controls:
    TRENDING  → position_size_multiplier = 1.0, normal scan_frequency, trades ALLOWED
    RANGING   → position_size_multiplier = 0.5, normal scan_frequency, trades ALLOWED
    CHAOTIC   → position_size_multiplier = 0.0, reduced scan_frequency, trades PAUSED

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger("nija.market_regime_controller")


# ---------------------------------------------------------------------------
# Regime definitions
# ---------------------------------------------------------------------------

class MarketRegime(Enum):
    """High-level market regime used by the controller."""
    TRENDING = "TRENDING"   # Strong directional movement — trade normally
    RANGING  = "RANGING"    # Sideways / choppy — trade at reduced size
    CHAOTIC  = "CHAOTIC"    # Extreme volatility / crisis — pause all trading


class TradePermission(Enum):
    """Whether new entries are permitted in the current regime."""
    ALLOWED = "ALLOWED"
    PAUSED  = "PAUSED"


# ---------------------------------------------------------------------------
# Per-regime control output
# ---------------------------------------------------------------------------

@dataclass
class RegimeControls:
    """Output emitted by the controller for the current regime."""
    regime: MarketRegime
    trade_permission: TradePermission
    position_size_multiplier: float   # Applied on top of base position size
    scan_frequency_seconds: int       # Seconds between market scans
    reason: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict:
        return {
            "regime": self.regime.value,
            "trade_permission": self.trade_permission.value,
            "position_size_multiplier": self.position_size_multiplier,
            "scan_frequency_seconds": self.scan_frequency_seconds,
            "reason": self.reason,
            "timestamp": self.timestamp.isoformat(),
        }


# ---------------------------------------------------------------------------
# Raw metric snapshot
# ---------------------------------------------------------------------------

@dataclass
class RegimeMetrics:
    """
    Snapshot of the four monitored dimensions used for regime classification.

    Fields
    ------
    volatility_pct : float
        Recent price-return standard deviation expressed as a percentage.
        Higher → more volatile.
    trend_strength : float
        ADX value (0–100).  Values above ``trending_adx_threshold`` indicate
        a clear trend; values below ``ranging_adx_threshold`` indicate chop.
    market_breadth : float
        Fraction of scanned symbols whose price is above their 20-bar EMA
        (0.0–1.0).  High breadth ≥ 0.6 supports trending regime;
        low breadth ≤ 0.4 supports ranging/chaotic.
    liquidity_ratio : float
        Ratio of the symbol's 24-h volume to the configured
        ``min_liquidity_volume``.  Values < 1.0 signal thin liquidity.
    """
    volatility_pct: float = 0.0
    trend_strength: float = 0.0
    market_breadth: float = 0.5
    liquidity_ratio: float = 1.0

    def to_dict(self) -> Dict:
        return {
            "volatility_pct": round(self.volatility_pct, 4),
            "trend_strength": round(self.trend_strength, 2),
            "market_breadth": round(self.market_breadth, 4),
            "liquidity_ratio": round(self.liquidity_ratio, 4),
        }


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class MarketRegimeController:
    """
    Monitors four market health dimensions and emits per-regime controls.

    Usage
    -----
    ::

        controller = MarketRegimeController()

        # From OHLCV data + precomputed indicators
        metrics = controller.compute_metrics(df, indicators, volume_24h=1_500_000)
        controls = controller.classify(metrics)

        # Apply controls in your strategy loop
        if controls.trade_permission == TradePermission.PAUSED:
            skip_entry()
        position_size *= controls.position_size_multiplier
        time.sleep(controls.scan_frequency_seconds)
    """

    # ------------------------------------------------------------------
    # Default thresholds (all overridable via ``config`` kwarg)
    # ------------------------------------------------------------------
    _DEFAULTS: Dict = {
        # --- Trend strength (ADX) ---
        "trending_adx_threshold": 25.0,   # ADX ≥ this → trending
        "ranging_adx_threshold": 20.0,    # ADX < this → ranging

        # --- Volatility ---
        "chaotic_volatility_pct": 6.0,    # vol % ≥ this → chaotic
        "ranging_volatility_pct": 3.0,    # vol % ≥ this (& ADX low) → ranging

        # --- Market breadth ---
        "trending_breadth_min": 0.55,     # breadth ≥ this supports trending
        "ranging_breadth_max": 0.45,      # breadth ≤ this hints at ranging

        # --- Liquidity ---
        "min_liquidity_ratio": 0.5,       # ratio < this → liquidity warning

        # --- Output controls per regime ---
        # TRENDING
        "trending_size_multiplier": 1.0,
        "trending_scan_seconds": 150,     # 2.5 minutes (default bot cadence)

        # RANGING
        "ranging_size_multiplier": 0.5,
        "ranging_scan_seconds": 150,

        # CHAOTIC
        "chaotic_size_multiplier": 0.0,
        "chaotic_scan_seconds": 300,      # slow down scan during chaos
    }

    def __init__(self, config: Optional[Dict] = None) -> None:
        """
        Initialise the controller.

        Parameters
        ----------
        config : dict, optional
            Override any of the threshold / control defaults listed in
            ``_DEFAULTS``.
        """
        cfg = {**self._DEFAULTS, **(config or {})}

        # Thresholds
        self.trending_adx_threshold: float  = cfg["trending_adx_threshold"]
        self.ranging_adx_threshold: float   = cfg["ranging_adx_threshold"]
        self.chaotic_volatility_pct: float  = cfg["chaotic_volatility_pct"]
        self.ranging_volatility_pct: float  = cfg["ranging_volatility_pct"]
        self.trending_breadth_min: float    = cfg["trending_breadth_min"]
        self.ranging_breadth_max: float     = cfg["ranging_breadth_max"]
        self.min_liquidity_ratio: float     = cfg["min_liquidity_ratio"]

        # Controls
        self._controls: Dict[MarketRegime, RegimeControls] = {
            MarketRegime.TRENDING: RegimeControls(
                regime=MarketRegime.TRENDING,
                trade_permission=TradePermission.ALLOWED,
                position_size_multiplier=cfg["trending_size_multiplier"],
                scan_frequency_seconds=cfg["trending_scan_seconds"],
                reason="Strong trend detected — normal trading",
            ),
            MarketRegime.RANGING: RegimeControls(
                regime=MarketRegime.RANGING,
                trade_permission=TradePermission.ALLOWED,
                position_size_multiplier=cfg["ranging_size_multiplier"],
                scan_frequency_seconds=cfg["ranging_scan_seconds"],
                reason=f"Ranging market — reduced position size ({cfg['ranging_size_multiplier']*100:.0f}%)",
            ),
            MarketRegime.CHAOTIC: RegimeControls(
                regime=MarketRegime.CHAOTIC,
                trade_permission=TradePermission.PAUSED,
                position_size_multiplier=cfg["chaotic_size_multiplier"],
                scan_frequency_seconds=cfg["chaotic_scan_seconds"],
                reason="Chaotic / extreme-volatility market — trading paused",
            ),
        }

        # State
        self._current_controls: Optional[RegimeControls] = None
        self._metrics_history: List[RegimeMetrics] = []

        logger.info("MarketRegimeController initialised with thresholds: "
                    "trending_adx=%.1f, ranging_adx=%.1f, chaotic_vol=%.1f%%",
                    self.trending_adx_threshold,
                    self.ranging_adx_threshold,
                    self.chaotic_volatility_pct)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compute_metrics(
        self,
        df: pd.DataFrame,
        indicators: Dict,
        volume_24h: float = 0.0,
        min_liquidity_volume: float = 1_000_000.0,
        symbol_prices: Optional[List[float]] = None,
        ema_period: int = 20,
    ) -> RegimeMetrics:
        """
        Derive the four monitored dimensions from raw market data.

        Parameters
        ----------
        df : pd.DataFrame
            OHLCV DataFrame with at least a ``close`` column and
            ``min(ema_period, 20)`` rows.
        indicators : dict
            Pre-computed indicator dictionary. Keys used:
            ``"adx"`` (pd.Series or float), ``"atr"`` (pd.Series or float).
        volume_24h : float
            24-hour trading volume for the primary symbol (in quote currency).
        min_liquidity_volume : float
            Minimum acceptable 24-h volume.  Used to compute ``liquidity_ratio``.
        symbol_prices : list of float, optional
            Latest close prices for a basket of symbols used to compute market
            breadth.  If *None* or fewer than 2 elements, breadth defaults to
            0.5 (neutral).
        ema_period : int
            EMA period used for breadth calculation (default 20).

        Returns
        -------
        RegimeMetrics
        """
        # --- Volatility ---
        volatility_pct = self._compute_volatility(df)

        # --- Trend strength (ADX) ---
        trend_strength = self._extract_scalar(indicators.get("adx", 0.0))

        # --- Market breadth ---
        market_breadth = self._compute_breadth(symbol_prices, df, ema_period)

        # --- Liquidity ---
        liquidity_ratio = (
            volume_24h / min_liquidity_volume
            if min_liquidity_volume > 0 else 1.0
        )

        metrics = RegimeMetrics(
            volatility_pct=volatility_pct,
            trend_strength=trend_strength,
            market_breadth=market_breadth,
            liquidity_ratio=liquidity_ratio,
        )

        self._metrics_history.append(metrics)
        if len(self._metrics_history) > 200:
            self._metrics_history = self._metrics_history[-200:]

        logger.debug(
            "RegimeMetrics — vol=%.2f%% adx=%.1f breadth=%.2f liq_ratio=%.2f",
            metrics.volatility_pct,
            metrics.trend_strength,
            metrics.market_breadth,
            metrics.liquidity_ratio,
        )

        return metrics

    def classify(self, metrics: RegimeMetrics) -> RegimeControls:
        """
        Classify the current market regime and return the matching controls.

        Classification priority
        -----------------------
        1. CHAOTIC  — extreme volatility *or* critically thin liquidity
        2. TRENDING — strong ADX *and* broad market participation
        3. RANGING  — everything else (low ADX, moderate vol, or weak breadth)

        Parameters
        ----------
        metrics : RegimeMetrics
            Current metric snapshot (use :meth:`compute_metrics` to build it).

        Returns
        -------
        RegimeControls
            Immutable control bundle for the detected regime.
        """
        regime = self._determine_regime(metrics)
        controls = self._build_controls(regime, metrics)

        if (self._current_controls is None
                or self._current_controls.regime != controls.regime):
            prev = self._current_controls.regime.value if self._current_controls else "None"
            logger.info(
                "Regime transition: %s → %s | vol=%.2f%% adx=%.1f "
                "breadth=%.2f liq=%.2f | %s",
                prev,
                controls.regime.value,
                metrics.volatility_pct,
                metrics.trend_strength,
                metrics.market_breadth,
                metrics.liquidity_ratio,
                controls.reason,
            )

        self._current_controls = controls
        return controls

    def evaluate(
        self,
        df: pd.DataFrame,
        indicators: Dict,
        volume_24h: float = 0.0,
        min_liquidity_volume: float = 1_000_000.0,
        symbol_prices: Optional[List[float]] = None,
    ) -> RegimeControls:
        """
        Convenience one-call method: compute metrics *and* classify.

        Parameters are forwarded to :meth:`compute_metrics`.

        Returns
        -------
        RegimeControls
        """
        metrics = self.compute_metrics(
            df=df,
            indicators=indicators,
            volume_24h=volume_24h,
            min_liquidity_volume=min_liquidity_volume,
            symbol_prices=symbol_prices,
        )
        return self.classify(metrics)

    @property
    def current_controls(self) -> Optional[RegimeControls]:
        """Most recently emitted :class:`RegimeControls`, or *None*."""
        return self._current_controls

    def get_status(self) -> Dict:
        """Return a JSON-serialisable status snapshot."""
        if self._current_controls is None:
            return {"regime": None, "controls": None}
        return {
            "regime": self._current_controls.regime.value,
            "controls": self._current_controls.to_dict(),
            "metrics_count": len(self._metrics_history),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _determine_regime(self, m: RegimeMetrics) -> MarketRegime:
        """Core classification logic."""

        # 1. CHAOTIC: extreme volatility — override everything
        if m.volatility_pct >= self.chaotic_volatility_pct:
            return MarketRegime.CHAOTIC

        # 2. CHAOTIC: liquidity is critically thin
        if m.liquidity_ratio < self.min_liquidity_ratio:
            return MarketRegime.CHAOTIC

        # 3. TRENDING: strong ADX *and* broad participation
        if (m.trend_strength >= self.trending_adx_threshold
                and m.market_breadth >= self.trending_breadth_min):
            return MarketRegime.TRENDING

        # 4. Everything else → RANGING
        return MarketRegime.RANGING

    def _build_controls(
        self, regime: MarketRegime, metrics: RegimeMetrics
    ) -> RegimeControls:
        """
        Build a fresh :class:`RegimeControls` stamped with the current time.
        Liquidity warnings are appended to the reason string.
        """
        template = self._controls[regime]
        reason = template.reason

        if (regime != MarketRegime.CHAOTIC
                and metrics.liquidity_ratio < 1.0):
            reason = f"{reason} [⚠️ low liquidity: ratio={metrics.liquidity_ratio:.2f}]"

        return RegimeControls(
            regime=regime,
            trade_permission=template.trade_permission,
            position_size_multiplier=template.position_size_multiplier,
            scan_frequency_seconds=template.scan_frequency_seconds,
            reason=reason,
            timestamp=datetime.now(timezone.utc),
        )

    @staticmethod
    def _compute_volatility(df: pd.DataFrame) -> float:
        """
        Compute recent price-return standard deviation as a percentage.
        Uses the last 20 close prices (or all available rows if fewer).
        """
        closes = df["close"].dropna()
        if len(closes) < 2:
            return 0.0
        window = closes.iloc[-20:]
        returns = window.pct_change().dropna()
        if len(returns) == 0:
            return 0.0
        return float(returns.std() * 100.0)

    @staticmethod
    def _compute_breadth(
        symbol_prices: Optional[List[float]],
        df: pd.DataFrame,
        ema_period: int,
    ) -> float:
        """
        Market breadth = fraction of symbols trading above the cross-sectional
        mean of the supplied price snapshot.

        When ``symbol_prices`` contains the latest close price for several
        symbols (a single-bar snapshot rather than full histories), a true
        per-symbol EMA cannot be computed.  Instead, each price is compared
        against the mean of the snapshot — a valid cross-sectional relative-
        strength measure that answers "how many symbols are above average?".

        If ``symbol_prices`` is not supplied (single-symbol context), the
        method falls back to checking whether the primary symbol's latest
        close is above its own ``ema_period``-bar EMA.  Returns 0.5 (neutral)
        when there is insufficient price history.
        """
        # Multi-symbol breadth (cross-sectional)
        if symbol_prices and len(symbol_prices) >= 2:
            arr  = np.array(symbol_prices, dtype=float)
            mean = arr.mean()
            above = (arr > mean).sum()
            return float(above) / float(len(arr))

        # Single-symbol fallback — use historical EMA
        close_series = df["close"].dropna()
        if len(close_series) < ema_period:
            return 0.5  # Neutral — not enough history
        ema = close_series.ewm(span=ema_period, adjust=False).mean()
        latest_close = float(close_series.iloc[-1])
        latest_ema   = float(ema.iloc[-1])
        return 1.0 if latest_close > latest_ema else 0.0

    @staticmethod
    def _extract_scalar(value) -> float:
        """
        Safely convert an indicator value (Series, tuple, list, or scalar)
        to a plain Python float.
        """
        if isinstance(value, pd.Series):
            return float(value.iloc[-1]) if len(value) > 0 else 0.0
        if isinstance(value, (list, tuple)):
            return float(value[-1]) if len(value) > 0 else 0.0
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_controller_instance: Optional[MarketRegimeController] = None


def get_market_regime_controller(
    config: Optional[Dict] = None,
) -> MarketRegimeController:
    """
    Return the module-level singleton :class:`MarketRegimeController`.

    On first call the instance is created with *config* (if provided).
    Subsequent calls return the existing instance regardless of *config*.
    """
    global _controller_instance
    if _controller_instance is None:
        _controller_instance = MarketRegimeController(config)
    return _controller_instance
