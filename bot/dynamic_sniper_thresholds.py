"""
DYNAMIC SNIPER THRESHOLDS
==========================
Adapts the SniperFilter's entry thresholds in real-time based on observed
win-rate trends, market regime, and recent trade performance so the bot
actually trades more when conditions are favourable and less when they are not.

Problem with static thresholds
-------------------------------
The SniperFilter uses fixed values (e.g. ``min_confidence=0.65``,
``min_adx=20``, ``volume_spike=1.5×``).  In low-volatility trending markets
these are often too strict and the bot misses valid entries.  In choppy markets
the same thresholds are too loose and the bot over-trades.

Solution
--------
``DynamicSniperThresholds`` wraps a ``SniperConfig`` and returns an *adjusted*
copy whose values are loosened or tightened based on:

  1. **Recent win rate** – if win_rate > 60%, loosen thresholds slightly to
     capture more trades.  If win_rate < 40%, tighten to protect capital.
  2. **Trade frequency** – if < ``min_trades_per_hour`` is being executed,
     progressively loosen to generate more signals.
  3. **Market regime** – BULL loosens, CHOP/CRASH tightens.
  4. **Consecutive losses** – after N consecutive losses, tighten automatically.
  5. **ADX / volatility context** – very high ADX (strong trend) allows looser
     confidence requirement because the trend itself is the edge.

The adjustment is bounded by ``max_loosen_factor`` and ``max_tighten_factor``
to prevent extreme loosening/tightening.

Usage
-----
    from bot.dynamic_sniper_thresholds import get_dynamic_sniper_thresholds
    from bot.sniper_filter import get_sniper_filter

    dyn = get_dynamic_sniper_thresholds()
    dyn.record_trade(won=True)

    # Get adjusted config and rebuild filter (or call check() directly)
    adj_config = dyn.get_adjusted_config()
    result = get_sniper_filter(adj_config).check(symbol, df, side, confidence)

    # Convenience: check() wraps everything in one call
    result = dyn.check(symbol, df, side, confidence, bid=bid, ask=ask)

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

logger = logging.getLogger("nija.dynamic_sniper_thresholds")


# ---------------------------------------------------------------------------
# Import optional dependencies safely
# ---------------------------------------------------------------------------

try:
    import pandas as pd
    _PD_AVAILABLE = True
except ImportError:
    _PD_AVAILABLE = False

try:
    from bot.sniper_filter import SniperConfig, SniperFilter, SniperResult
    _SNIPER_AVAILABLE = True
except ImportError:
    try:
        from sniper_filter import SniperConfig, SniperFilter, SniperResult  # type: ignore
        _SNIPER_AVAILABLE = True
    except ImportError:
        _SNIPER_AVAILABLE = False
except (ImportError, ModuleNotFoundError, NameError, AttributeError) as exc:
    logger.warning("DynamicSniperThresholds: sniper import failed — hard disabling sniper dependency: %s", exc)
    _SNIPER_AVAILABLE = False

if not _SNIPER_AVAILABLE:
    SniperConfig = None  # type: ignore
    SniperFilter = None  # type: ignore
    SniperResult = None  # type: ignore


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class DynamicThresholdConfig:
    """Controls how thresholds adapt to observed performance."""

    # ── Win-rate gates ────────────────────────────────────────────────────────
    # Above this win rate: loosen thresholds to capture more trades
    win_rate_loosen_threshold: float = 0.60   # 60% win rate
    # Below this win rate: tighten thresholds to protect capital
    win_rate_tighten_threshold: float = 0.40  # 40% win rate

    # Rolling window size for win-rate calculation
    win_rate_window: int = 20

    # ── Trade frequency gate ─────────────────────────────────────────────────
    # If fewer than this many trades execute per hour, loosen to get more
    min_trades_per_hour: float = 0.5  # ~1 trade per 2 hours

    # Tracks the last N timestamps of executed trades
    trade_history_window: int = 100

    # ── Consecutive loss protection ───────────────────────────────────────────
    # After this many consecutive losses, tighten automatically
    max_consecutive_losses: int = 3

    # ── Regime multipliers ────────────────────────────────────────────────────
    # These multiply the adjustment factor.
    # factor < 1.0 → loosen (allow more trades), factor > 1.0 → tighten (fewer trades)
    # BULL market: loosen (lower thresholds) → factor multiplier < 1.0
    # CHOP/CRASH:  tighten (raise thresholds) → factor multiplier > 1.0
    regime_bull_factor: float = 0.85    # Bull market: loosen by 15%
    regime_chop_factor: float = 1.10    # Choppy: tighten by 10%
    regime_crash_factor: float = 1.25   # Crash: tighten by 25%

    # ── Bounds ───────────────────────────────────────────────────────────────
    # Maximum loosening: thresholds cannot drop below baseline × this factor
    max_loosen_factor: float = 0.70     # Can loosen by up to 30%
    # Maximum tightening: thresholds cannot rise above baseline × this factor
    max_tighten_factor: float = 1.30    # Can tighten by up to 30%

    # ── ADX loosening ─────────────────────────────────────────────────────────
    # When the latest ADX is above this level, confidence floor is reduced
    # (strong trend = additional edge beyond the signal itself)
    high_adx_threshold: float = 35.0
    high_adx_confidence_relief: float = 0.05   # Lower min_confidence by this


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ThresholdAdjustment:
    """Report of how thresholds were adjusted and why."""
    adjustment_factor: float        # Multiplicative factor applied (1.0 = no change)
    reasons: List[str] = field(default_factory=list)
    win_rate: float = 0.0
    consecutive_losses: int = 0
    regime: str = "UNKNOWN"
    trades_per_hour: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Core engine
# ---------------------------------------------------------------------------

class DynamicSniperThresholds:
    """
    Adapts SniperFilter thresholds in real-time based on performance signals.

    Thread-safe singleton via ``get_dynamic_sniper_thresholds()``.
    """

    def __init__(
        self,
        base_config: Optional["SniperConfig"] = None,
        dynamic_config: Optional[DynamicThresholdConfig] = None,
    ) -> None:
        self._dyn_cfg = dynamic_config or DynamicThresholdConfig()

        # Base (immutable) SniperConfig — this is the reference point
        if _SNIPER_AVAILABLE and base_config is not None:
            self._base_config = base_config
        elif _SNIPER_AVAILABLE:
            self._base_config = SniperConfig()
        else:
            self._base_config = None

        self._lock = threading.Lock()

        # ── Tracking state ────────────────────────────────────────────────
        self._trade_outcomes: Deque[bool] = deque(
            maxlen=self._dyn_cfg.win_rate_window
        )
        self._trade_timestamps: Deque[datetime] = deque(
            maxlen=self._dyn_cfg.trade_history_window
        )
        self._consecutive_losses: int = 0
        self._current_regime: str = "UNKNOWN"

        # Last computed adjustment for inspection / logging
        self._last_adjustment: Optional[ThresholdAdjustment] = None

        logger.info(
            "🎯 DynamicSniperThresholds initialised "
            "(win_rate_loosen=%.0f%%, win_rate_tighten=%.0f%%, "
            "max_consec_loss=%d, sniper_available=%s)",
            self._dyn_cfg.win_rate_loosen_threshold * 100,
            self._dyn_cfg.win_rate_tighten_threshold * 100,
            self._dyn_cfg.max_consecutive_losses,
            _SNIPER_AVAILABLE,
        )

    # ------------------------------------------------------------------
    # State update API
    # ------------------------------------------------------------------

    def record_trade(self, won: bool) -> None:
        """
        Record the outcome of a completed trade.

        Call this after every trade that was filtered through the sniper.
        """
        with self._lock:
            self._trade_outcomes.append(won)
            self._trade_timestamps.append(datetime.now(timezone.utc))
            if won:
                self._consecutive_losses = 0
            else:
                self._consecutive_losses += 1

        logger.debug(
            "🎯 DynSniper: recorded trade won=%s | consecutive_losses=%d | "
            "win_rate=%.1f%%",
            won,
            self._consecutive_losses,
            self._compute_win_rate() * 100,
        )

    def update_regime(self, regime: str) -> None:
        """
        Update the current market regime (``"BULL"``, ``"CHOP"``, ``"CRASH"``).

        Called by the market regime engine or trading strategy loop.
        """
        with self._lock:
            self._current_regime = regime.upper()
        logger.debug("🎯 DynSniper: regime updated to %s", regime)

    # ------------------------------------------------------------------
    # Threshold computation
    # ------------------------------------------------------------------

    def get_adjusted_config(
        self, current_adx: float = 0.0
    ) -> Optional["SniperConfig"]:
        """
        Return a **new** ``SniperConfig`` with dynamically adjusted thresholds.

        The base config is never mutated; a copy with modified values is
        returned each call.

        Parameters
        ----------
        current_adx:
            Latest ADX value from the market data frame.  Pass 0.0 when
            unavailable; the ADX-based relief will not be applied.

        Returns
        -------
        SniperConfig or None
            Adjusted config, or None when sniper_filter is not installed.
        """
        if not _SNIPER_AVAILABLE or self._base_config is None:
            return None

        with self._lock:
            factor, adjustment = self._compute_adjustment()

        cfg = self._base_config
        dyn = self._dyn_cfg

        # Apply multiplicative factor to the thresholds that benefit from
        # loosening/tightening (lower is looser for confidence/adx/vol;
        # the factor is < 1 for loosening and > 1 for tightening).
        new_min_confidence = _clamp(
            cfg.min_confidence * factor,
            lower=cfg.min_confidence * dyn.max_loosen_factor,
            upper=cfg.min_confidence * dyn.max_tighten_factor,
        )

        # ADX relief: if currently in a strong trend, lower the bar further
        if current_adx >= dyn.high_adx_threshold:
            new_min_confidence = max(
                new_min_confidence - dyn.high_adx_confidence_relief,
                cfg.min_confidence * dyn.max_loosen_factor,
            )
            logger.debug(
                "🎯 DynSniper: ADX %.1f > %.1f → confidence relief −%.2f → %.2f",
                current_adx, dyn.high_adx_threshold,
                dyn.high_adx_confidence_relief, new_min_confidence,
            )

        new_min_adx = _clamp(
            cfg.min_adx * factor,
            lower=cfg.min_adx * dyn.max_loosen_factor,
            upper=cfg.min_adx * dyn.max_tighten_factor,
        )

        new_vol_spike = _clamp(
            cfg.volume_spike_multiplier * factor,
            lower=cfg.volume_spike_multiplier * dyn.max_loosen_factor,
            upper=cfg.volume_spike_multiplier * dyn.max_tighten_factor,
        )

        # Build adjusted config by copying all base fields then overriding
        adjusted = SniperConfig(
            mtf_fast=cfg.mtf_fast,
            mtf_slow=cfg.mtf_slow,
            ema_fast=cfg.ema_fast,
            ema_slow=cfg.ema_slow,
            volume_spike_multiplier=round(new_vol_spike, 3),
            volume_lookback=cfg.volume_lookback,
            breakout_lookback=cfg.breakout_lookback,
            strong_body_pct=cfg.strong_body_pct,
            max_spread_pct=cfg.max_spread_pct,
            min_depth_usd=cfg.min_depth_usd,
            min_confidence=round(new_min_confidence, 4),
            min_adx=round(new_min_adx, 2),
            low_volume_multiplier=_clamp(
                cfg.low_volume_multiplier * factor,
                lower=cfg.low_volume_multiplier * dyn.max_loosen_factor,
                upper=cfg.low_volume_multiplier * dyn.max_tighten_factor,
            ),
            min_bars=cfg.min_bars,
        )

        logger.debug(
            "🎯 DynSniper adj: factor=%.3f | min_conf %.2f→%.2f | "
            "min_adx %.1f→%.1f | vol_spike %.2f→%.2f",
            factor,
            cfg.min_confidence, adjusted.min_confidence,
            cfg.min_adx, adjusted.min_adx,
            cfg.volume_spike_multiplier, adjusted.volume_spike_multiplier,
        )

        # Cache the last adjustment for reporting
        with self._lock:
            self._last_adjustment = adjustment

        return adjusted

    def check(
        self,
        symbol: str,
        df: Any,
        signal_side: str,
        confidence: float,
        bid: float = 0.0,
        ask: float = 0.0,
        depth_usd: float = 0.0,
        current_adx: float = 0.0,
    ) -> Optional["SniperResult"]:
        """
        Convenience wrapper: build an adjusted filter and run the check.

        Returns the ``SniperResult``, or ``None`` when the sniper_filter
        module is unavailable.
        """
        if not _SNIPER_AVAILABLE or SniperFilter is None:
            return None

        adjusted_config = self.get_adjusted_config(current_adx=current_adx)
        if adjusted_config is None:
            return None
        _filter = SniperFilter(config=adjusted_config)
        return _filter.check(
            symbol=symbol,
            df=df,
            signal_side=signal_side,
            confidence=confidence,
            bid=bid,
            ask=ask,
            depth_usd=depth_usd,
        )

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_report(self) -> Dict:
        """Return a summary dict for dashboards and logging."""
        with self._lock:
            factor, adjustment = self._compute_adjustment()
            win_rate = self._compute_win_rate()
            trades_hr = self._trades_per_hour()
            consec = self._consecutive_losses
            regime = self._current_regime
            last_adj = self._last_adjustment

        return {
            "current_factor": round(factor, 4),
            "win_rate_pct": round(win_rate * 100, 2),
            "trades_per_hour": round(trades_hr, 3),
            "consecutive_losses": consec,
            "regime": regime,
            "adjustment_reasons": adjustment.reasons,
            "last_adjustment_ts": last_adj.timestamp if last_adj else None,
            "sniper_available": _SNIPER_AVAILABLE,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_win_rate(self) -> float:
        """Return the rolling win rate as a fraction [0, 1]."""
        if not self._trade_outcomes:
            return 0.5  # Neutral when no data
        return sum(self._trade_outcomes) / len(self._trade_outcomes)

    def _trades_per_hour(self) -> float:
        """Return the average number of trades per hour over recent history."""
        if len(self._trade_timestamps) < 2:
            return 0.0
        now = datetime.now(timezone.utc)
        oldest = self._trade_timestamps[0]
        elapsed_hours = (now - oldest).total_seconds() / 3600.0
        if elapsed_hours <= 0:
            return 0.0
        return len(self._trade_timestamps) / elapsed_hours

    def _compute_adjustment(self) -> Tuple[float, ThresholdAdjustment]:
        """
        Compute the multiplicative adjustment factor.

        Returns (factor, ThresholdAdjustment).
        factor < 1.0 → loosen (allow more trades)
        factor > 1.0 → tighten (fewer, higher-quality trades)
        """
        dyn = self._dyn_cfg
        win_rate = self._compute_win_rate()
        trades_hr = self._trades_per_hour()
        consec = self._consecutive_losses
        regime = self._current_regime

        factor: float = 1.0
        reasons: List[str] = []

        # ── Win-rate adjustment ───────────────────────────────────────────
        if win_rate > dyn.win_rate_loosen_threshold:
            delta = (win_rate - dyn.win_rate_loosen_threshold) * 0.5  # gentle
            factor -= delta
            reasons.append(
                f"high_win_rate={win_rate*100:.1f}% → loosen (−{delta:.3f})"
            )
        elif win_rate < dyn.win_rate_tighten_threshold:
            delta = (dyn.win_rate_tighten_threshold - win_rate) * 0.5
            factor += delta
            reasons.append(
                f"low_win_rate={win_rate*100:.1f}% → tighten (+{delta:.3f})"
            )

        # ── Trade frequency adjustment ────────────────────────────────────
        if trades_hr < dyn.min_trades_per_hour and len(self._trade_timestamps) >= 3:
            loosen_amount = 0.05  # Loosen by 5% when under-trading
            factor -= loosen_amount
            reasons.append(
                f"low_frequency={trades_hr:.2f}/hr < {dyn.min_trades_per_hour}/hr "
                f"→ loosen (−{loosen_amount:.2f})"
            )

        # ── Consecutive losses protection ─────────────────────────────────
        if consec >= dyn.max_consecutive_losses:
            extra_tighten = 0.05 * (consec - dyn.max_consecutive_losses + 1)
            factor += extra_tighten
            reasons.append(
                f"consec_losses={consec} → tighten (+{extra_tighten:.3f})"
            )

        # ── Regime adjustment ─────────────────────────────────────────────
        regime_map = {
            "BULL": dyn.regime_bull_factor,
            "CHOP": dyn.regime_chop_factor,
            "CHOPPY": dyn.regime_chop_factor,
            "RANGING": dyn.regime_chop_factor,
            "CRASH": dyn.regime_crash_factor,
        }
        regime_mult = regime_map.get(regime, 1.0)
        if regime_mult != 1.0:
            factor *= regime_mult
            reasons.append(
                f"regime={regime} → ×{regime_mult:.2f}"
            )

        # ── Clamp to configured bounds ────────────────────────────────────
        factor = _clamp(
            factor,
            lower=dyn.max_loosen_factor,
            upper=dyn.max_tighten_factor,
        )

        if not reasons:
            reasons.append("no_adjustment_needed (factor=1.0)")

        adjustment = ThresholdAdjustment(
            adjustment_factor=round(factor, 4),
            reasons=reasons,
            win_rate=round(win_rate, 4),
            consecutive_losses=consec,
            regime=regime,
            trades_per_hour=round(trades_hr, 3),
        )
        return factor, adjustment


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _clamp(value: float, lower: float, upper: float) -> float:
    """Clamp ``value`` to the range [lower, upper]."""
    return max(lower, min(upper, value))


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[DynamicSniperThresholds] = None
_instance_lock = threading.Lock()


def get_dynamic_sniper_thresholds(
    base_config: Optional["SniperConfig"] = None,
    dynamic_config: Optional[DynamicThresholdConfig] = None,
) -> DynamicSniperThresholds:
    """
    Return the process-wide DynamicSniperThresholds singleton.

    Configuration is applied only on the first call.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = DynamicSniperThresholds(
                    base_config=base_config,
                    dynamic_config=dynamic_config,
                )
    return _instance
