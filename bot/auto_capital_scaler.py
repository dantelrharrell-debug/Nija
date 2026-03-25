"""
NIJA Auto Capital Scaler
==========================
Automatically adjusts risk parameters (position size %, max concurrent
positions, risk per trade) as the account balance grows through defined
equity milestones.

The philosophy is Kelly-inspired: as capital compounds, the system earns
the right to deploy larger absolute positions — but the *fractional* risk
per trade is kept conservative at every tier to protect compounded gains.

Tier table (configurable via env vars):

    ┌─────────────┬──────────────┬──────────────┬──────────────────────────────────────┐
    │ Tier name   │ Min equity   │ Base pos %   │ Max pos % │ Max concurrent │ Risk %  │
    ├─────────────┼──────────────┼──────────────┼───────────┼────────────────┼─────────┤
    │ SEED        │ $0           │ 5 %          │ 10 %      │ 3              │ 1.0 %   │
    │ GROWING     │ $500         │ 6 %          │ 12 %      │ 4              │ 1.1 %   │
    │ ESTABLISHED │ $2 000       │ 7 %          │ 13 %      │ 5              │ 1.2 %   │
    │ SCALING     │ $5 000       │ 8 %          │ 14 %      │ 6              │ 1.3 %   │
    │ PRO         │ $10 000      │ 9 %          │ 15 %      │ 7              │ 1.4 %   │
    │ ELITE       │ $25 000      │ 10 %         │ 16 %      │ 8              │ 1.5 %   │
    │ INSTITUTION │ $100 000     │ 10 %         │ 15 %      │ 10             │ 1.25 %  │
    └─────────────┴──────────────┴──────────────┴───────────┴────────────────┴─────────┘

Each tier is a hard floor: once the account *drops below* the lower tier
threshold by more than HYSTERESIS_PCT, the system downgrades (avoids
flip-flopping on minor swings).

Usage
-----
::

    from bot.auto_capital_scaler import get_auto_capital_scaler

    scaler = get_auto_capital_scaler()
    scaler.update(balance_usd=3400.0)   # called each cycle

    params = scaler.get_params()
    logger.info("Base pos pct: %.1f%%", params.base_position_pct * 100)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import List, Optional

logger = logging.getLogger("nija.auto_capital_scaler")

# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CapitalTier:
    """A single equity milestone tier."""
    name: str
    min_equity: float
    base_position_pct: float     # fraction of balance per trade
    max_position_pct: float      # hard cap as fraction
    max_concurrent_positions: int
    risk_per_trade_pct: float    # % of balance at risk per trade
    position_size_multiplier: float  # multiplier applied to external size calcs
    emoji: str


# Default tier table
_DEFAULT_TIERS: List[CapitalTier] = [
    CapitalTier("SEED",        0.0,      0.050, 0.10, 3,  1.00, 0.80, "🌱"),
    CapitalTier("GROWING",     500.0,    0.060, 0.12, 4,  1.10, 0.90, "🌿"),
    CapitalTier("ESTABLISHED", 2_000.0,  0.070, 0.13, 5,  1.20, 1.00, "🌳"),
    CapitalTier("SCALING",     5_000.0,  0.080, 0.14, 6,  1.30, 1.10, "📈"),
    CapitalTier("PRO",         10_000.0, 0.090, 0.15, 7,  1.40, 1.20, "💼"),
    CapitalTier("ELITE",       25_000.0, 0.100, 0.16, 8,  1.50, 1.30, "👑"),
    CapitalTier("INSTITUTION", 100_000.0, 0.100, 0.15, 10, 1.25, 1.25, "🏛️"),
]

# Hysteresis: must drop this fraction below a tier floor before downgrading
_HYSTERESIS_PCT = 0.05   # 5 % buffer


# ---------------------------------------------------------------------------
# Params dataclass (returned to callers)
# ---------------------------------------------------------------------------

@dataclass
class ScalerParams:
    """Resolved scaling parameters for the current equity level."""
    tier_name: str
    current_equity: float
    base_position_pct: float
    max_position_pct: float
    max_concurrent_positions: int
    risk_per_trade_pct: float
    position_size_multiplier: float
    emoji: str

    def apply_to_position(self, base_size_usd: float, balance_usd: float) -> float:
        """
        Apply the tier's size multiplier and cap to a base position size.

        Args:
            base_size_usd: The starting position size in USD.
            balance_usd: Current account balance for cap enforcement.

        Returns:
            Final capped position size in USD.
        """
        sized = base_size_usd * self.position_size_multiplier
        cap = balance_usd * self.max_position_pct
        return min(sized, cap)


# ---------------------------------------------------------------------------
# Scaler class
# ---------------------------------------------------------------------------

class AutoCapitalScaler:
    """
    Thread-safe auto capital scaler.

    Call ``update(balance_usd)`` each trading cycle to keep tier resolution
    current.  Read ``get_params()`` to obtain the resolved parameters.
    """

    def __init__(self, tiers: Optional[List[CapitalTier]] = None) -> None:
        self._tiers: List[CapitalTier] = sorted(
            tiers or _DEFAULT_TIERS, key=lambda t: t.min_equity
        )
        self._lock = threading.Lock()
        self._current_tier: CapitalTier = self._tiers[0]
        self._current_equity: float = 0.0
        self._previous_tier_name: str = self._tiers[0].name

        logger.info(
            "💰 AutoCapitalScaler initialised — %d tiers loaded (SEED → %s)",
            len(self._tiers),
            self._tiers[-1].name,
        )

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _resolve_tier(self, equity: float) -> CapitalTier:
        """
        Find the appropriate tier for the given equity with hysteresis.

        Hysteresis prevents rapid tier switching when balance oscillates
        near a threshold.
        """
        resolved = self._tiers[0]
        for tier in self._tiers:
            if equity >= tier.min_equity:
                resolved = tier
        # Downgrade hysteresis: don't downgrade unless meaningfully below
        if resolved.name != self._current_tier.name:
            current_idx = next(
                (i for i, t in enumerate(self._tiers) if t.name == self._current_tier.name), 0
            )
            resolved_idx = next(
                (i for i, t in enumerate(self._tiers) if t.name == resolved.name), 0
            )
            if resolved_idx < current_idx:
                # Downgrade: only if equity < tier.min_equity * (1 - hysteresis)
                downgrade_threshold = self._current_tier.min_equity * (1.0 - _HYSTERESIS_PCT)
                if equity > downgrade_threshold:
                    return self._current_tier  # stay in current tier
        return resolved

    # ── Public API ────────────────────────────────────────────────────────────

    def update(self, balance_usd: float) -> ScalerParams:
        """
        Update the scaler with the current account balance.

        Should be called once per trading cycle.

        Returns:
            The resolved ScalerParams for the current equity level.
        """
        with self._lock:
            self._current_equity = balance_usd
            new_tier = self._resolve_tier(balance_usd)

            if new_tier.name != self._current_tier.name:
                old_name = self._current_tier.name
                self._current_tier = new_tier
                direction = "⬆️ UPGRADE" if new_tier.min_equity > (
                    next((t.min_equity for t in self._tiers if t.name == old_name), 0)
                ) else "⬇️ DOWNGRADE"
                logger.info(
                    "%s AutoCapitalScaler: %s → %s %s "
                    "(equity=$%.0f, pos=%.1f%%, max_concurrent=%d)",
                    new_tier.emoji,
                    old_name,
                    new_tier.name,
                    direction,
                    balance_usd,
                    new_tier.base_position_pct * 100,
                    new_tier.max_concurrent_positions,
                )

            return self._build_params()

    def get_params(self) -> ScalerParams:
        """Return the current scaling parameters without updating the equity."""
        with self._lock:
            return self._build_params()

    def _build_params(self) -> ScalerParams:
        t = self._current_tier
        return ScalerParams(
            tier_name=t.name,
            current_equity=self._current_equity,
            base_position_pct=t.base_position_pct,
            max_position_pct=t.max_position_pct,
            max_concurrent_positions=t.max_concurrent_positions,
            risk_per_trade_pct=t.risk_per_trade_pct,
            position_size_multiplier=t.position_size_multiplier,
            emoji=t.emoji,
        )

    def get_report(self) -> dict:
        """Return a JSON-serialisable summary for logging / API endpoints."""
        p = self.get_params()
        tiers_summary = [
            {
                "name": t.name,
                "min_equity": t.min_equity,
                "base_position_pct": t.base_position_pct,
                "max_concurrent_positions": t.max_concurrent_positions,
                "risk_per_trade_pct": t.risk_per_trade_pct,
                "active": t.name == p.tier_name,
            }
            for t in self._tiers
        ]
        return {
            "current_tier": p.tier_name,
            "current_equity": round(p.current_equity, 2),
            "base_position_pct": p.base_position_pct,
            "max_position_pct": p.max_position_pct,
            "max_concurrent_positions": p.max_concurrent_positions,
            "risk_per_trade_pct": p.risk_per_trade_pct,
            "position_size_multiplier": p.position_size_multiplier,
            "tiers": tiers_summary,
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_scaler_instance: Optional[AutoCapitalScaler] = None
_scaler_lock = threading.Lock()


def get_auto_capital_scaler(
    tiers: Optional[List[CapitalTier]] = None,
) -> AutoCapitalScaler:
    """
    Return the thread-safe singleton AutoCapitalScaler.

    ``tiers`` is only used on the first (initialising) call.
    """
    global _scaler_instance
    if _scaler_instance is None:
        with _scaler_lock:
            if _scaler_instance is None:
                _scaler_instance = AutoCapitalScaler(tiers=tiers)
    return _scaler_instance
