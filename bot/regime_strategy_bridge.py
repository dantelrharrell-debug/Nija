"""
NIJA Regime Strategy Bridge
============================

Industry Principle #2: Adaptive multi-regime strategy
------------------------------------------------------
Profitable AI bots do not use one static edge.  They detect the current
market regime and switch between:

    • TREND_FOLLOWING  — ride directional momentum (ADX > 25)
    • MOMENTUM         — trade developing trends (ADX 20-25)
    • MEAN_REVERSION   — buy oversold / sell overbought in ranges
    • BREAKOUT         — enter on volatility expansions
    • SCALPING         — high-frequency micro-profits in consolidation
    • DEFENSIVE        — minimal size, tight stops during chaos

This module is the single authoritative source for regime-specific
parameter sets.  Rather than scattering hard-coded thresholds across
multiple files, callers ask: ``bridge.get_params(regime) → RegimeTradingParams``
and use the returned values for RSI bounds, confidence gate, position
size multiplier, stop-loss distance, take-profit targets, and trade
frequency target.

Integration
-----------
Import the singleton via ``get_regime_strategy_bridge()`` and call
``get_params()`` at the start of each entry-decision cycle.  The bridge
auto-detects regime changes and logs transitions so the operator always
knows which strategy is active.

Compatibility
-------------
Works with both the legacy 3-regime ``MarketRegime`` (TRENDING / RANGING /
VOLATILE) and the advanced 7-regime ``RegimeType`` (STRONG_TREND / WEAK_TREND
/ RANGING / EXPANSION / MEAN_REVERSION / VOLATILITY_EXPLOSION /
CONSOLIDATION) from ``market_regime_detector.py``.

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional, Any

logger = logging.getLogger("nija.regime_strategy_bridge")


# ---------------------------------------------------------------------------
# Strategy type enum
# ---------------------------------------------------------------------------

class StrategyType(Enum):
    """High-level trading strategy appropriate for a given regime."""
    TREND_FOLLOWING = "trend_following"
    MOMENTUM        = "momentum"
    MEAN_REVERSION  = "mean_reversion"
    BREAKOUT        = "breakout"
    SCALPING        = "scalping"
    DEFENSIVE       = "defensive"


# ---------------------------------------------------------------------------
# Parameter dataclass
# ---------------------------------------------------------------------------

@dataclass
class RegimeTradingParams:
    """
    Complete set of trading parameters for one market regime.

    Every field has a safe default so callers can destructure without
    conditional checks.  Override only what a specific regime needs.
    """

    # ── Identification ────────────────────────────────────────────────────
    regime_name: str = "unknown"
    strategy_type: StrategyType = StrategyType.MOMENTUM
    description: str = ""

    # ── RSI entry windows ─────────────────────────────────────────────────
    # Long entries: buy when RSI is in [rsi_long_min, rsi_long_max]
    rsi_long_min: float  = 30.0
    rsi_long_max: float  = 67.0
    # Short entries: short when RSI is in [rsi_short_min, rsi_short_max]
    rsi_short_min: float = 33.0
    rsi_short_max: float = 70.0

    # ── Signal quality gate ───────────────────────────────────────────────
    # Added to the base confidence gate (negative = easier entry)
    confidence_delta: float = 0.0   # e.g. -0.05 loosens, +0.05 tightens

    # ── Position sizing ───────────────────────────────────────────────────
    position_size_multiplier: float = 1.0   # 1.0 = baseline size
    risk_per_trade_pct: float        = 1.5  # % of account to risk per trade

    # ── Stop-loss & take-profit ───────────────────────────────────────────
    stop_loss_atr_multiplier: float   = 1.5  # SL = entry ± (ATR × this)
    take_profit_atr_multiplier: float = 2.5  # TP1 = entry ± (ATR × this)
    take_profit_multiplier: float     = 1.0  # scale TP levels by this
    trailing_stop_atr_multiplier: float = 1.5 # trailing stop distance

    # ── Frequency ─────────────────────────────────────────────────────────
    min_trades_per_hour: float = 2.0
    min_trades_per_day: float  = 20.0

    # ── Entry score ───────────────────────────────────────────────────────
    min_entry_score: int = 3  # out of 5

    # ── Extra metadata ────────────────────────────────────────────────────
    extra: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Pre-built parameter sets for every regime
# ---------------------------------------------------------------------------

_PARAMS_STRONG_TREND = RegimeTradingParams(
    regime_name="STRONG_TREND",
    strategy_type=StrategyType.TREND_FOLLOWING,
    description=(
        "ADX > 30: ride the trend.  "
        "Wide RSI window, larger positions, stretched profit targets."
    ),
    rsi_long_min=45, rsi_long_max=72,   # buy confirmed uptrend (RSI > 45)
    rsi_short_min=28, rsi_short_max=55, # short confirmed downtrend
    confidence_delta=-0.04,             # slightly easier — trend gives edge
    position_size_multiplier=1.25,      # bigger size in strong trends
    risk_per_trade_pct=1.5,
    stop_loss_atr_multiplier=1.8,       # wider stop — let the trend breathe
    take_profit_atr_multiplier=3.5,     # stretch targets; trend can run far
    take_profit_multiplier=1.3,
    trailing_stop_atr_multiplier=1.8,
    min_trades_per_hour=2.0,
    min_trades_per_day=18.0,
    min_entry_score=3,
)

_PARAMS_WEAK_TREND = RegimeTradingParams(
    regime_name="WEAK_TREND",
    strategy_type=StrategyType.MOMENTUM,
    description=(
        "ADX 20-30: developing trend.  "
        "Moderate position, standard stops, normal TP."
    ),
    rsi_long_min=40, rsi_long_max=68,
    rsi_short_min=32, rsi_short_max=60,
    confidence_delta=-0.02,
    position_size_multiplier=1.10,
    risk_per_trade_pct=1.5,
    stop_loss_atr_multiplier=1.5,
    take_profit_atr_multiplier=2.5,
    take_profit_multiplier=1.1,
    trailing_stop_atr_multiplier=1.5,
    min_trades_per_hour=2.0,
    min_trades_per_day=20.0,
    min_entry_score=3,
)

_PARAMS_RANGING = RegimeTradingParams(
    regime_name="RANGING",
    strategy_type=StrategyType.MEAN_REVERSION,
    description=(
        "ADX < 20, low ATR: buy oversold extremes, sell overbought extremes.  "
        "Tighter positions, faster profit-taking."
    ),
    rsi_long_min=20, rsi_long_max=38,   # buy deep oversold (mean-reversion)
    rsi_short_min=62, rsi_short_max=80, # sell deep overbought
    confidence_delta=0.0,
    position_size_multiplier=0.85,
    risk_per_trade_pct=1.2,
    stop_loss_atr_multiplier=1.2,       # tight stop — range has defined bounds
    take_profit_atr_multiplier=2.0,     # take profit at range midpoint
    take_profit_multiplier=0.85,        # lower TP — market won't run far
    trailing_stop_atr_multiplier=1.0,
    min_trades_per_hour=2.5,            # more frequent in ranges
    min_trades_per_day=22.0,
    min_entry_score=4,                  # require higher quality in chop
)

_PARAMS_EXPANSION = RegimeTradingParams(
    regime_name="EXPANSION",
    strategy_type=StrategyType.BREAKOUT,
    description=(
        "Volatility expansion / breakout.  "
        "Enter on breakout confirmation, wider stops, extended targets."
    ),
    rsi_long_min=50, rsi_long_max=75,
    rsi_short_min=25, rsi_short_max=50,
    confidence_delta=-0.03,
    position_size_multiplier=1.15,
    risk_per_trade_pct=1.5,
    stop_loss_atr_multiplier=2.0,       # breakouts can retest, need room
    take_profit_atr_multiplier=4.0,     # breakouts can run hard
    take_profit_multiplier=1.2,
    trailing_stop_atr_multiplier=2.0,
    min_trades_per_hour=1.5,            # fewer but bigger setups
    min_trades_per_day=15.0,
    min_entry_score=3,
)

_PARAMS_MEAN_REVERSION = RegimeTradingParams(
    regime_name="MEAN_REVERSION",
    strategy_type=StrategyType.MEAN_REVERSION,
    description=(
        "Pullback / reversal context.  "
        "Wait for RSI extreme then fade the move."
    ),
    rsi_long_min=22, rsi_long_max=40,
    rsi_short_min=60, rsi_short_max=78,
    confidence_delta=0.0,
    position_size_multiplier=0.90,
    risk_per_trade_pct=1.2,
    stop_loss_atr_multiplier=1.3,
    take_profit_atr_multiplier=2.2,
    take_profit_multiplier=0.90,
    trailing_stop_atr_multiplier=1.2,
    min_trades_per_hour=2.0,
    min_trades_per_day=20.0,
    min_entry_score=4,
)

# CONSOLIDATION → SCALPING:
# Low volatility, price compressed.  High-frequency small-profit scalps
# are the most efficient edge here.  Fast entries, tight stops, quick TP.
_PARAMS_CONSOLIDATION = RegimeTradingParams(
    regime_name="CONSOLIDATION",
    strategy_type=StrategyType.SCALPING,
    description=(
        "Low-volatility consolidation: micro-scalp mode.  "
        "Tight stops, fast TP, maximum frequency."
    ),
    rsi_long_min=30, rsi_long_max=52,   # buy any reasonable dip
    rsi_short_min=48, rsi_short_max=70, # short any reasonable peak
    confidence_delta=-0.06,             # loosen gate — scalp anything
    position_size_multiplier=0.75,      # smaller size — faster churn
    risk_per_trade_pct=1.0,             # tighter risk — scalps are small
    stop_loss_atr_multiplier=0.8,       # very tight stop
    take_profit_atr_multiplier=1.2,     # small, quick TP
    take_profit_multiplier=0.70,        # take profit early
    trailing_stop_atr_multiplier=0.8,
    min_trades_per_hour=4.0,            # 4+ scalps per hour target
    min_trades_per_day=30.0,
    min_entry_score=2,                  # lower bar — volume compensates
)

_PARAMS_VOLATILITY_EXPLOSION = RegimeTradingParams(
    regime_name="VOLATILITY_EXPLOSION",
    strategy_type=StrategyType.DEFENSIVE,
    description=(
        "Panic / crisis mode.  "
        "Minimal new entries, maximum stop-tightening, protect capital."
    ),
    rsi_long_min=18, rsi_long_max=40,   # only buy extreme panic lows
    rsi_short_min=60, rsi_short_max=82,
    confidence_delta=+0.10,             # much harder to enter — be selective
    position_size_multiplier=0.35,      # tiny positions only
    risk_per_trade_pct=0.75,            # halve normal risk
    stop_loss_atr_multiplier=2.5,
    take_profit_atr_multiplier=3.0,
    take_profit_multiplier=1.0,
    trailing_stop_atr_multiplier=2.5,
    min_trades_per_hour=0.5,            # almost no new trades
    min_trades_per_day=5.0,
    min_entry_score=5,                  # require perfect setups only
)

# Legacy 3-regime fallbacks (TRENDING / RANGING / VOLATILE)
_PARAMS_LEGACY_TRENDING = _PARAMS_WEAK_TREND   # use WEAK_TREND params
_PARAMS_LEGACY_RANGING  = _PARAMS_RANGING
_PARAMS_LEGACY_VOLATILE = _PARAMS_VOLATILITY_EXPLOSION


# ---------------------------------------------------------------------------
# Regime → params dispatch tables
# ---------------------------------------------------------------------------

# Advanced 7-regime map (RegimeType strings)
_ADVANCED_MAP: Dict[str, RegimeTradingParams] = {
    "strong_trend":       _PARAMS_STRONG_TREND,
    "weak_trend":         _PARAMS_WEAK_TREND,
    "ranging":            _PARAMS_RANGING,
    "expansion":          _PARAMS_EXPANSION,
    "mean_reversion":     _PARAMS_MEAN_REVERSION,
    "consolidation":      _PARAMS_CONSOLIDATION,
    "volatility_explosion": _PARAMS_VOLATILITY_EXPLOSION,
}

# Legacy 3-regime map (MarketRegime strings)
_LEGACY_MAP: Dict[str, RegimeTradingParams] = {
    "trending": _PARAMS_LEGACY_TRENDING,
    "ranging":  _PARAMS_LEGACY_RANGING,
    "volatile": _PARAMS_LEGACY_VOLATILE,
}

_DEFAULT_PARAMS = _PARAMS_WEAK_TREND  # safe fallback when regime unknown


# ---------------------------------------------------------------------------
# Bridge class
# ---------------------------------------------------------------------------

class RegimeStrategyBridge:
    """
    Translates a detected market regime into a complete parameter set.

    Thread-safe.  Logs regime switches for operator visibility.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_regime: Optional[str] = None
        logger.info(
            "🌉 RegimeStrategyBridge initialized — "
            "7 regimes mapped to: %s",
            ", ".join(st.value for st in StrategyType),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_params(self, regime: Any) -> RegimeTradingParams:
        """
        Return the ``RegimeTradingParams`` for the given regime.

        Args:
            regime: Any object whose ``str()`` or ``.value`` yields a
                    known regime name (e.g. ``MarketRegime.TRENDING``,
                    ``RegimeType.CONSOLIDATION``, or the raw string
                    ``"strong_trend"``).

        Returns:
            ``RegimeTradingParams`` for the regime; falls back to the
            WEAK_TREND params when the regime is unrecognised.
        """
        regime_key = self._normalise(regime)

        # Log transitions
        with self._lock:
            if regime_key != self._last_regime:
                prev = self._last_regime or "none"
                params = self._lookup(regime_key)
                logger.info(
                    "🔀 REGIME SWITCH: %s → %s | strategy=%s | "
                    "RSI_long=%d-%d | conf_delta=%+.2f | "
                    "pos_mult=%.2f | sl_atr=%.1f× | tp_mult=%.2f",
                    prev.upper(), regime_key.upper(),
                    params.strategy_type.value,
                    params.rsi_long_min, params.rsi_long_max,
                    params.confidence_delta,
                    params.position_size_multiplier,
                    params.stop_loss_atr_multiplier,
                    params.take_profit_multiplier,
                )
                self._last_regime = regime_key

        return self._lookup(regime_key)

    def get_strategy_type(self, regime: Any) -> StrategyType:
        """Convenience: return just the strategy type for a regime."""
        return self.get_params(regime).strategy_type

    def describe(self, regime: Any) -> str:
        """Return a human-readable description of the active strategy."""
        p = self.get_params(regime)
        return (
            f"{p.regime_name} → {p.strategy_type.value}: {p.description} | "
            f"RSI_long={p.rsi_long_min}-{p.rsi_long_max} | "
            f"pos×{p.position_size_multiplier:.2f} | "
            f"SL {p.stop_loss_atr_multiplier:.1f}×ATR | "
            f"TP {p.take_profit_atr_multiplier:.1f}×ATR"
        )

    def get_all_params(self) -> Dict[str, RegimeTradingParams]:
        """Return the full regime → params mapping for inspection."""
        combined = {}
        combined.update(_ADVANCED_MAP)
        combined.update({k: v for k, v in _LEGACY_MAP.items() if k not in combined})
        return combined

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _normalise(regime: Any) -> str:
        """Convert any regime representation to a lowercase string key."""
        if regime is None:
            return "weak_trend"
        # Enum with .value attribute (RegimeType, MarketRegime)
        if hasattr(regime, "value"):
            return str(regime.value).lower()
        return str(regime).lower().replace(" ", "_")

    @staticmethod
    def _lookup(key: str) -> RegimeTradingParams:
        """Look up params from either the advanced or legacy map."""
        if key in _ADVANCED_MAP:
            return _ADVANCED_MAP[key]
        if key in _LEGACY_MAP:
            return _LEGACY_MAP[key]
        logger.warning(
            "⚠️  Unknown regime key '%s' — using default (WEAK_TREND) params", key
        )
        return _DEFAULT_PARAMS


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_bridge_instance: Optional[RegimeStrategyBridge] = None
_bridge_lock = threading.Lock()


def get_regime_strategy_bridge() -> RegimeStrategyBridge:
    """Return the module-level singleton ``RegimeStrategyBridge``."""
    global _bridge_instance
    if _bridge_instance is None:
        with _bridge_lock:
            if _bridge_instance is None:
                _bridge_instance = RegimeStrategyBridge()
    return _bridge_instance


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    bridge = get_regime_strategy_bridge()

    test_regimes = [
        "strong_trend", "weak_trend", "ranging", "expansion",
        "mean_reversion", "consolidation", "volatility_explosion",
        "trending",   # legacy
        "volatile",   # legacy
        "unknown_xyz",  # fallback
    ]

    print("\n" + "=" * 80)
    print("REGIME STRATEGY BRIDGE — PARAMETER SUMMARY")
    print("=" * 80)
    for r in test_regimes:
        p = bridge.get_params(r)
        print(
            f"\n{p.regime_name:<25} strategy={p.strategy_type.value:<18} "
            f"RSI_L={p.rsi_long_min}-{p.rsi_long_max}  "
            f"conf_Δ={p.confidence_delta:+.2f}  "
            f"pos×{p.position_size_multiplier:.2f}  "
            f"SL={p.stop_loss_atr_multiplier:.1f}×ATR  "
            f"trades={p.min_trades_per_hour:.1f}/hr"
        )
    print("\n" + "=" * 80)
