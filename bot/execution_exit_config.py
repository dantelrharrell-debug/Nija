"""
NIJA Execution & Exit Configuration
=====================================

Industry principle — "Position size + stop logic = survival and compounding"
— is wired into every parameter here.

This module is the single source of truth for ALL stop-loss, trailing-stop,
take-profit, and cooldown parameters.  Rather than scattering magic numbers
across the codebase, callers ask:

    ``config.get_exit_params(regime, entry_type, broker)``

and receive a fully-resolved ``ExitParams`` dataclass they can use directly.

Four strategy profiles (Principle #4: multiple strat types)
------------------------------------------------------------
The module automatically selects one of four strategy profiles based on
regime + entry_type, ensuring NIJA adapts its exit logic to the market:

    SCALP        — Micro targets 0.8–1.5%, tight stops 0.8–1.0%,
                   trailing activates at 1.5%, 20–30s cooldown.

    SWING        — Balanced targets 3.0–5.5%, stops 1.0–1.2%,
                   trailing activates at 1.8%, 45s cooldown.

    BREAKOUT     — Wide targets 3.0–7.0%, wider stops 1.2–1.5%
                   (room to retest), trailing activates at 2.5%,
                   60s cooldown (fewer, bigger trades).

    MEAN_REVERSION — Tight targets 1.5–2.5%, tight stops 0.8–1.0%,
                     trailing activates at 1.8%, 45s cooldown.

Parameters
----------
Hard stop-loss:
    Hard SL is expressed as a % of entry price:
    • SCALP:          0.80 %
    • SWING/M_REV:    1.10 %  (Coinbase) / 1.00 % (Kraken/Binance)
    • BREAKOUT:       1.20 %
    • VOLATILE boost: +0.30 % to all (avoids stops being hunted in chaos)

Trailing stop:
    activation_pct  — profit% at which trailing stop engages (default 1.8 %)
    buffer_pct      — distance from highest-price to trailing line:
                       0.50 % (scalp) / 0.60 % (swing) / 0.80 % (breakout)

Take-profit ladder:
    Four strategy-typed ladders, all with 3 exits + runner:
    SCALP  :  TP1=0.8%  TP2=1.2%  TP3=1.5%  sizes 30%/30%/25%  runner=15%
    SWING  :  TP1=3.0%  TP2=4.0%  TP3=5.5%  sizes 20%/25%/30%  runner=25%
    BREAKOUT: TP1=3.0%  TP2=5.5%  TP3=7.0%  sizes 20%/25%/30%  runner=25%
    M_REV  :  TP1=1.5%  TP2=2.0%  TP3=2.5%  sizes 25%/30%/25%  runner=20%
    Volatile regime: TP levels scaled ×1.25 to compensate for wider stops.

Cooldown:
    Per-symbol re-entry cooldown in seconds, based on recent trade activity:
    • >3 trades/hr (high activity)  → 20 s  (fast cycling)
    • 1–3 trades/hr (normal)        → 45 s
    • <1 trade/hr  (low activity)   → 60 s

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.execution_exit_config")


# ---------------------------------------------------------------------------
# Env-var helpers
# ---------------------------------------------------------------------------

def _ef(key: str, default: float) -> float:
    try:
        return float(os.environ.get(key, default))
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Strategy profile enum
# ---------------------------------------------------------------------------

class StratProfile(str, Enum):
    SCALP          = "scalp"
    SWING          = "swing"
    BREAKOUT       = "breakout"
    MEAN_REVERSION = "mean_reversion"


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class StopConfig:
    """Stop-loss and trailing-stop parameters for one trade."""
    profile: StratProfile

    # Hard stop-loss
    hard_sl_pct: float          # e.g. 0.011 = 1.1% from entry

    # Trailing stop
    trailing_activate_pct: float  # profit% that activates trailing
    trailing_buffer_pct: float    # distance between price peak and trail line

    # Source info
    regime_name: str = ""
    entry_type: str = ""
    broker: str = ""
    volatile_boost_applied: bool = False
    atr_pct: float = 0.0          # ATR fraction used for dynamic SL floor (0 = not provided)
    atr_sl_applied: bool = False  # True when ATR*1.2 exceeded the profile default


@dataclass
class TPLevel:
    """Single take-profit level."""
    target_pct: float     # gross profit % to trigger exit
    exit_fraction: float  # fraction of remaining position to close


@dataclass
class TPConfig:
    """Multi-tier take-profit ladder."""
    profile: StratProfile
    levels: List[TPLevel] = field(default_factory=list)
    regime_name: str = ""
    volatile_scaled: bool = False


@dataclass
class CooldownConfig:
    """Per-symbol re-entry cooldown."""
    seconds: int
    reason: str
    activity_band: str   # 'high' | 'normal' | 'low'


@dataclass
class ExitParams:
    """Complete exit configuration for one trade decision."""
    stop: StopConfig
    tp: TPConfig
    cooldown: CooldownConfig
    profile: StratProfile


# ---------------------------------------------------------------------------
# Raw parameter tables
# ---------------------------------------------------------------------------

# (hard_sl_pct, trailing_activate_pct, trailing_buffer_pct) per profile
_STOP_TABLE: Dict[StratProfile, Tuple[float, float, float]] = {
    StratProfile.SCALP:          (_ef("SL_SCALP_PCT",    0.80) / 100, 1.50 / 100, 0.50 / 100),
    StratProfile.SWING:          (_ef("SL_SWING_PCT",    2.00) / 100, 2.50 / 100, 0.60 / 100),  # Fix 3: SL 1.5→2.0% (must clear noise + fees)
    StratProfile.BREAKOUT:       (_ef("SL_BREAKOUT_PCT", 2.00) / 100, 2.80 / 100, 0.80 / 100),  # Fix 3: SL 1.5→2.0%
    StratProfile.MEAN_REVERSION: (_ef("SL_MREV_PCT",     2.00) / 100, 2.50 / 100, 0.55 / 100),  # Fix 3: SL 1.0→2.0%
}

# Hard SL reduction for low-fee brokers (basis points → fraction)
_LOW_FEE_SL_REDUCTION = 0.001   # tighten by 0.1% on Kraken/Binance

# Volatile-regime SL boost (add to hard_sl to avoid stop hunts in wide spreads)
_VOLATILE_SL_BOOST = 0.003   # +0.3%

# ATR-based dynamic stop floor: sl = max(_SL_MIN_FRACTION, atr_pct * _SL_ATR_MULTIPLIER)
# Ensures the stop breathes with real market volatility instead of using a
# fixed percentage that may be too tight in high-ATR conditions.
_SL_ATR_MULTIPLIER: float  = _ef("SL_ATR_MULTIPLIER", 1.2)
_SL_MIN_FRACTION: float    = _ef("SL_MIN_PCT", 1.2) / 100   # 1.2% hard floor (stored as decimal)

# TP ladders: list of (target_pct, exit_fraction)
# TP UPGRADE (Apr 2026): Raised all ladders to [3.0%, 4.0%, 5.5%, 7.0%] targets
# to improve R:R and reduce fees impact on profitability.
_TP_TABLE: Dict[StratProfile, List[Tuple[float, float]]] = {
    StratProfile.SCALP: [
        (0.012, 0.30),   # 30% at 1.2%  (raised from 0.8% — balanced aggression)
        (0.018, 0.30),   # 30% at 1.8%  (raised from 1.2%)
        (0.025, 0.25),   # 25% at 2.5%  (raised from 1.5% to match TAKE_PROFIT target)
        # 15% runner with trailing stop
    ],
    StratProfile.SWING: [
        (0.022, 0.20),   # 20% at 2.2%  (was 3.0% — tightened TP1 for faster partial, TUNE 7 Apr 2026)
        (0.032, 0.25),   # 25% at 3.2%  (was 4.0%, TUNE 7)
        (0.060, 0.30),   # 30% at 6.0%  (was 5.5% — widened TP3 for bigger runner, TUNE 7)
        # 25% runner with trailing stop
    ],
    StratProfile.BREAKOUT: [
        (0.030, 0.20),   # 20% at 3.0%
        (0.055, 0.25),   # 25% at 5.5%
        (0.070, 0.30),   # 30% at 7.0%
        # 25% runner with trailing stop
    ],
    StratProfile.MEAN_REVERSION: [
        (0.015, 0.25),   # 25% at 1.5%
        (0.020, 0.30),   # 30% at 2.0%
        (0.025, 0.25),   # 25% at 2.5%
        # 20% runner
    ],
}

# Volatile-regime TP scale factor (wider targets compensate for wide stops)
_VOLATILE_TP_SCALE = 1.25

# Regime → profile mapping
_REGIME_PROFILE: Dict[str, StratProfile] = {
    "strong_trend":         StratProfile.BREAKOUT,
    "weak_trend":           StratProfile.SWING,
    "ranging":              StratProfile.MEAN_REVERSION,
    "consolidation":        StratProfile.SCALP,
    "expansion":            StratProfile.BREAKOUT,
    "mean_reversion":       StratProfile.MEAN_REVERSION,
    "volatility_explosion": StratProfile.SWING,    # swing with volatile boost
    # Legacy
    "trending":             StratProfile.SWING,
    "volatile":             StratProfile.SWING,
}

# Cooldown seconds per activity band
# "normal" raised 45→60s to match ENTRY_COOLDOWN_SECONDS=60 target (TUNE 5, Apr 2026)
_COOLDOWN_TABLE: Dict[str, int] = {
    "high":   20,   # >3 trades/hr
    "normal": 60,   # 1–3 trades/hr  (was 45)
    "low":    60,   # <1 trade/hr
}


# ---------------------------------------------------------------------------
# Main config class
# ---------------------------------------------------------------------------

class ExecutionExitConfig:
    """
    Resolves regime + entry-type → complete ExitParams.

    Thread-safe (stateless computation; lock only for stats).
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        logger.info(
            "⚙️  ExecutionExitConfig initialized — "
            "4 strategy profiles: %s",
            " | ".join(p.value.upper() for p in StratProfile),
        )

    # ------------------------------------------------------------------
    # Primary API
    # ------------------------------------------------------------------

    def get_exit_params(
        self,
        regime: object = None,
        entry_type: str = "swing",
        broker: str = "coinbase",
        trades_per_hour: float = 2.0,
        atr_pct: float = 0.0,
    ) -> ExitParams:
        """
        Resolve complete exit parameters for one trade.

        Args:
            regime:           Current market regime (enum or string).
            entry_type:       Entry strategy type ('scalp', 'swing', etc.)
            broker:           Exchange name for fee-aware SL tightening.
            trades_per_hour:  Recent trade rate for cooldown selection.
            atr_pct:          Current ATR as a fraction of price (e.g. 0.018 = 1.8%).
                              When provided, the hard stop-loss is set to
                              ``max(1.2%, atr_pct * 1.2)`` so it always respects
                              real market volatility.

        Returns:
            ``ExitParams`` with stop, TP, cooldown, and profile.
        """
        regime_key  = self._regime_key(regime)
        broker_key  = self._broker_key(broker)
        is_volatile = regime_key in ("volatility_explosion", "volatile")

        # Determine strategy profile
        # entry_type overrides regime default when explicitly set
        if entry_type in {p.value for p in StratProfile}:
            profile = StratProfile(entry_type)
        else:
            profile = _REGIME_PROFILE.get(regime_key, StratProfile.SWING)

        stop    = self._build_stop(profile, broker_key, regime_key, is_volatile, atr_pct=atr_pct)
        tp      = self._build_tp(profile, regime_key, is_volatile)
        cooldown = self._build_cooldown(trades_per_hour)

        return ExitParams(stop=stop, tp=tp, cooldown=cooldown, profile=profile)

    def get_stop_config(
        self,
        regime: object = None,
        entry_type: str = "swing",
        broker: str = "coinbase",
        atr_pct: float = 0.0,
    ) -> StopConfig:
        """Convenience: return only the stop configuration."""
        return self.get_exit_params(regime, entry_type, broker, atr_pct=atr_pct).stop

    def get_tp_config(
        self,
        regime: object = None,
        entry_type: str = "swing",
    ) -> TPConfig:
        """Convenience: return only the TP ladder."""
        return self.get_exit_params(regime, entry_type).tp

    def get_cooldown_seconds(self, trades_per_hour: float = 2.0) -> int:
        """Convenience: return cooldown seconds for given activity level."""
        return self._build_cooldown(trades_per_hour).seconds

    # ------------------------------------------------------------------
    # Builders
    # ------------------------------------------------------------------

    def _build_stop(
        self,
        profile: StratProfile,
        broker_key: str,
        regime_key: str,
        is_volatile: bool,
        atr_pct: float = 0.0,
    ) -> StopConfig:
        hard_sl, trail_act, trail_buf = _STOP_TABLE[profile]
        profile_default_sl = hard_sl   # capture before any adjustments for logging

        # Low-fee brokers: tighten stop slightly (fees cost less → tighter OK)
        if broker_key in ("kraken", "binance", "okx"):
            hard_sl = max(0.005, hard_sl - _LOW_FEE_SL_REDUCTION)

        # Volatile boost: widen stop to avoid hunt during wide spreads
        volatile_boost = False
        if is_volatile:
            hard_sl += _VOLATILE_SL_BOOST
            volatile_boost = True

        # ATR-adaptive floor: sl = max(1.2%, atr_pct * 1.2)
        # Prevents stops from being placed inside normal market noise when
        # ATR-based distance is larger than the fixed profile default.
        atr_sl_applied = False
        if atr_pct > 0.0:
            atr_based_sl = atr_pct * _SL_ATR_MULTIPLIER
            if atr_based_sl > hard_sl:
                hard_sl = atr_based_sl
                atr_sl_applied = True
        # Always enforce the absolute minimum floor (1.2%)
        hard_sl = max(hard_sl, _SL_MIN_FRACTION)

        if atr_sl_applied:
            logger.debug(
                "🛡️  ATR SL: %.2f%% ATR×%.1f = %.2f%% (profile default was %.2f%%) [%s]",
                atr_pct * 100, _SL_ATR_MULTIPLIER, hard_sl * 100,
                profile_default_sl * 100, profile.value,
            )

        return StopConfig(
            profile=profile,
            hard_sl_pct=round(hard_sl, 4),
            trailing_activate_pct=trail_act,
            trailing_buffer_pct=trail_buf,
            regime_name=regime_key,
            broker=broker_key,
            volatile_boost_applied=volatile_boost,
            atr_pct=round(atr_pct, 6),
            atr_sl_applied=atr_sl_applied,
        )

    @staticmethod
    def _build_tp(
        profile: StratProfile,
        regime_key: str,
        is_volatile: bool,
    ) -> TPConfig:
        raw_levels = _TP_TABLE.get(profile, _TP_TABLE[StratProfile.SWING])
        scale = _VOLATILE_TP_SCALE if is_volatile else 1.0

        levels = [
            TPLevel(
                target_pct=round(target * scale, 4),
                exit_fraction=fraction,
            )
            for target, fraction in raw_levels
        ]
        return TPConfig(
            profile=profile,
            levels=levels,
            regime_name=regime_key,
            volatile_scaled=is_volatile,
        )

    @staticmethod
    def _build_cooldown(trades_per_hour: float) -> CooldownConfig:
        if trades_per_hour > 3.0:
            band = "high"
        elif trades_per_hour >= 1.0:
            band = "normal"
        else:
            band = "low"
        secs = _COOLDOWN_TABLE[band]
        return CooldownConfig(
            seconds=secs,
            reason=f"{trades_per_hour:.1f} trades/hr → {band} activity → {secs}s cooldown",
            activity_band=band,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _regime_key(regime: object) -> str:
        if regime is None:
            return "weak_trend"
        if hasattr(regime, "value"):
            return str(regime.value).lower()
        return str(regime).lower().replace(" ", "_")

    @staticmethod
    def _broker_key(broker: str) -> str:
        b = broker.lower()
        for key in ("coinbase", "kraken", "binance", "okx"):
            if key in b:
                return key
        return "coinbase"


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_config_instance: Optional[ExecutionExitConfig] = None
_config_lock = threading.Lock()


def get_execution_exit_config() -> ExecutionExitConfig:
    """Return the module-level singleton ``ExecutionExitConfig``."""
    global _config_instance
    if _config_instance is None:
        with _config_lock:
            if _config_instance is None:
                _config_instance = ExecutionExitConfig()
    return _config_instance


# ---------------------------------------------------------------------------
# Quick self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cfg = get_execution_exit_config()

    scenarios = [
        ("strong_trend",   "breakout",      "coinbase", 2.0, 0.000),
        ("consolidation",  "scalp",         "kraken",   4.5, 0.015),   # ATR 1.5% → sl=max(1.2%,1.8%)=1.8%
        ("ranging",        "mean_reversion","coinbase",  1.5, 0.008),   # ATR 0.8% → sl=max(1.2%,0.96%)=1.2%
        ("weak_trend",     "swing",         "binance",  2.0, 0.020),   # ATR 2.0% → sl=max(1.2%,2.4%)=2.4%
        ("volatility_explosion", "swing",   "coinbase", 0.5, 0.025),   # ATR 2.5% → sl=max(1.2%,3.0%)=3.0%
    ]

    print("\n" + "=" * 88)
    print("EXECUTION EXIT CONFIG — STRATEGY PROFILES")
    print("=" * 88)
    for regime, etype, broker, tph, atr in scenarios:
        p = cfg.get_exit_params(regime, etype, broker, tph, atr_pct=atr)
        stop = p.stop
        tp   = p.tp
        cd   = p.cooldown
        print(
            f"\nRegime={regime:<22} type={etype:<16} broker={broker:<10} "
            f"atr={atr*100:.1f}%  → profile={p.profile.value.upper()}"
        )
        print(
            f"  STOP  hard={stop.hard_sl_pct*100:.2f}%"
            f"{'  [ATR×1.2]' if stop.atr_sl_applied else '  [profile floor]'}"
            f"  trail_act={stop.trailing_activate_pct*100:.1f}%  "
            f"trail_buf={stop.trailing_buffer_pct*100:.1f}%"
            f"{'  [+volatile boost]' if stop.volatile_boost_applied else ''}"
        )
        tp_str = "  TP    " + "  ".join(
            f"TP{i+1}={lv.target_pct*100:.1f}%→{lv.exit_fraction*100:.0f}%"
            for i, lv in enumerate(tp.levels)
        )
        if tp.volatile_scaled:
            tp_str += "  [×1.25 volatile]"
        print(tp_str)
        print(f"  COOLDOWN  {cd.seconds}s  ({cd.reason})")
    print("\n" + "=" * 88)
