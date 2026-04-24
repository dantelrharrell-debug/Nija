"""
NIJA Regime Capital Allocator
================================

Shifts capital allocation targets whenever the market regime changes, so
the bot automatically de-risks in bear/volatile conditions and deploys
more aggressively during confirmed bull/trending conditions.

This module is the **authoritative decision layer** that maps a detected
regime to a set of allocation parameters.  Other components (position
sizer, orchestration engine, etc.) should consume these parameters rather
than making their own regime → size decisions.

Architecture
------------
::

  ┌────────────────────────────────────────────────────────────────────────┐
  │                    RegimeCapitalAllocator                              │
  │                                                                        │
  │  update_regime(regime, confidence)  ← call each bar                   │
  │  get_allocation_params()            → AllocationParams                │
  │  get_position_size_multiplier()     → float                           │
  │  get_max_open_positions()           → int                             │
  │  get_report()                       → Dict                            │
  └────────────────────────────────────────────────────────────────────────┘

Regime taxonomy (strings accepted, case-insensitive)
-----------------------------------------------------
  BULL_TRENDING, BULL_BREAKOUT, RECOVERY
  SIDEWAYS, RANGING
  VOLATILE
  BEAR_TRENDING, BEAR_BREAKDOWN, UNKNOWN

Transition hysteresis
---------------------
A regime switch is only committed when the new regime is signalled for
``min_confirm_bars`` consecutive bars AND the confidence exceeds
``min_confidence``.  This prevents thrashing between similar regimes.

Usage
-----
::

    from bot.regime_capital_allocator import (
        get_regime_capital_allocator,
        KnownRegime,
    )

    allocator = get_regime_capital_allocator()

    # Feed regime + confidence each bar:
    allocator.update_regime("BULL_TRENDING", confidence=0.82)

    params = allocator.get_allocation_params()
    # Multiply base position USD by:
    position_usd = base_usd * params.position_size_multiplier
    # Enforce max open positions:
    if open_positions >= params.max_positions:
        skip_new_entry()

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.regime_capital_allocator")


# ---------------------------------------------------------------------------
# Regime taxonomy
# ---------------------------------------------------------------------------

class KnownRegime(str, Enum):
    BULL_TRENDING = "BULL_TRENDING"
    BULL_BREAKOUT = "BULL_BREAKOUT"
    RECOVERY = "RECOVERY"
    SIDEWAYS = "SIDEWAYS"
    RANGING = "RANGING"
    VOLATILE = "VOLATILE"
    BEAR_TRENDING = "BEAR_TRENDING"
    BEAR_BREAKDOWN = "BEAR_BREAKDOWN"
    UNKNOWN = "UNKNOWN"

    @classmethod
    def parse(cls, value: str) -> "KnownRegime":
        normalised = value.upper().replace(" ", "_").replace("-", "_")
        try:
            return cls(normalised)
        except ValueError:
            return cls.UNKNOWN


# ---------------------------------------------------------------------------
# Per-regime allocation profiles
# ---------------------------------------------------------------------------

@dataclass
class RegimeProfile:
    """Capital allocation parameters for a single regime."""
    position_size_multiplier: float   # Scale factor applied to base position USD
    max_positions: int                 # Maximum concurrent open positions
    deploy_pct: float                 # Fraction of available capital to deploy (0–1)
    allow_new_entries: bool           # Whether new entries are permitted at all
    description: str = ""


_DEFAULT_PROFILES: Dict[KnownRegime, RegimeProfile] = {
    KnownRegime.BULL_TRENDING:  RegimeProfile(1.00, 8,  0.80, True,  "Full deployment — confirmed bull trend"),
    KnownRegime.BULL_BREAKOUT:  RegimeProfile(0.90, 7,  0.70, True,  "Slightly cautious — breakout needs confirmation"),
    KnownRegime.RECOVERY:       RegimeProfile(0.70, 6,  0.60, True,  "Rebuilding — moderate deployment"),
    KnownRegime.SIDEWAYS:       RegimeProfile(0.65, 5,  0.55, True,  "Range-bound — conservative"),
    KnownRegime.RANGING:        RegimeProfile(0.65, 5,  0.55, True,  "Range-bound — conservative"),
    KnownRegime.VOLATILE:       RegimeProfile(0.40, 3,  0.30, True,  "High volatility — small positions"),
    KnownRegime.BEAR_TRENDING:  RegimeProfile(0.35, 3,  0.25, True,  "Bear trend — defensive"),
    KnownRegime.BEAR_BREAKDOWN: RegimeProfile(0.20, 2,  0.15, True,  "Breakdown — near-shutdown"),
    KnownRegime.UNKNOWN:        RegimeProfile(0.50, 4,  0.40, True,  "Unknown regime — conservative default"),
}


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class RegimeAllocatorConfig:
    """Tunable hysteresis and confidence settings."""
    min_confidence: float = 0.55       # Minimum confidence to accept a regime signal
    min_confirm_bars: int = 2          # Bars the new regime must be observed before switching
    profiles: Dict[KnownRegime, RegimeProfile] = field(
        default_factory=lambda: dict(_DEFAULT_PROFILES)
    )


# ---------------------------------------------------------------------------
# Allocation result
# ---------------------------------------------------------------------------

@dataclass
class AllocationParams:
    """Current allocation parameters derived from the active regime."""
    regime: str
    position_size_multiplier: float
    max_positions: int
    deploy_pct: float
    allow_new_entries: bool
    confidence: float
    description: str
    switched_at: Optional[str] = None   # ISO-8601 timestamp of last regime switch


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

class RegimeCapitalAllocator:
    """
    Maps live market regime → capital allocation parameters.

    Thread-safe: all public methods acquire ``_lock``.
    """

    def __init__(self, config: Optional[RegimeAllocatorConfig] = None) -> None:
        self._config = config or RegimeAllocatorConfig()
        self._lock = threading.Lock()

        self._active_regime: KnownRegime = KnownRegime.UNKNOWN
        self._active_confidence: float = 0.0
        self._switched_at: Optional[str] = None

        # Hysteresis tracking
        self._pending_regime: KnownRegime = KnownRegime.UNKNOWN
        self._pending_count: int = 0

        # History (last 20 regime events)
        self._history: List[Tuple[str, str, float]] = []  # (timestamp, regime, conf)

        logger.info("✅ RegimeCapitalAllocator initialised — starting in UNKNOWN regime")

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def update_regime(self, regime: str, confidence: float = 1.0) -> bool:
        """
        Signal a detected market regime.

        Returns ``True`` if the active regime switched as a result.
        """
        parsed = KnownRegime.parse(regime)
        confidence = max(0.0, min(1.0, confidence))

        with self._lock:
            now_str = datetime.now(timezone.utc).isoformat()
            self._history.append((now_str, parsed.value, confidence))
            if len(self._history) > 20:
                self._history.pop(0)

            if confidence < self._config.min_confidence:
                logger.debug(
                    "RegimeAllocator: regime %s confidence %.2f below threshold %.2f — ignoring",
                    parsed.value, confidence, self._config.min_confidence,
                )
                return False

            if parsed == self._active_regime:
                # Reinforce current regime — reset pending
                self._pending_regime = parsed
                self._pending_count = 0
                self._active_confidence = confidence
                return False

            # New regime candidate
            if parsed == self._pending_regime:
                self._pending_count += 1
            else:
                self._pending_regime = parsed
                self._pending_count = 1

            if self._pending_count >= self._config.min_confirm_bars:
                old = self._active_regime
                self._active_regime = parsed
                self._active_confidence = confidence
                self._switched_at = now_str
                self._pending_count = 0
                logger.info(
                    "🔄 RegimeCapitalAllocator: regime switch %s → %s (conf=%.2f)",
                    old.value, parsed.value, confidence,
                )
                return True

        return False

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_allocation_params(self) -> AllocationParams:
        """Return the current allocation parameters."""
        with self._lock:
            regime = self._active_regime
            confidence = self._active_confidence
            switched_at = self._switched_at

        profile = self._config.profiles.get(regime, _DEFAULT_PROFILES[KnownRegime.UNKNOWN])
        return AllocationParams(
            regime=regime.value,
            position_size_multiplier=profile.position_size_multiplier,
            max_positions=profile.max_positions,
            deploy_pct=profile.deploy_pct,
            allow_new_entries=profile.allow_new_entries,
            confidence=confidence,
            description=profile.description,
            switched_at=switched_at,
        )

    def get_position_size_multiplier(self) -> float:
        """Convenience shortcut — returns current position size multiplier."""
        return self.get_allocation_params().position_size_multiplier

    def get_max_open_positions(self) -> int:
        """Convenience shortcut — returns max concurrent positions for this regime."""
        return self.get_allocation_params().max_positions

    def get_report(self) -> Dict:
        """Return a status dictionary for monitoring / logging."""
        params = self.get_allocation_params()
        with self._lock:
            history = list(self._history[-5:])
            pending = (self._pending_regime.value, self._pending_count)
        return {
            "active_regime": params.regime,
            "confidence": round(params.confidence, 3),
            "position_size_multiplier": params.position_size_multiplier,
            "max_positions": params.max_positions,
            "deploy_pct": params.deploy_pct,
            "allow_new_entries": params.allow_new_entries,
            "description": params.description,
            "switched_at": params.switched_at,
            "pending_regime": pending[0],
            "pending_count": pending[1],
            "min_confirm_bars": self._config.min_confirm_bars,
            "recent_signals": [
                {"timestamp": ts, "regime": r, "confidence": round(c, 3)}
                for ts, r, c in history
            ],
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_allocator_instance: Optional[RegimeCapitalAllocator] = None
_allocator_lock = threading.Lock()


def get_regime_capital_allocator(
    config: Optional[RegimeAllocatorConfig] = None,
) -> RegimeCapitalAllocator:
    """Return the singleton RegimeCapitalAllocator."""
    global _allocator_instance
    if _allocator_instance is None:
        with _allocator_lock:
            if _allocator_instance is None:
                _allocator_instance = RegimeCapitalAllocator(config=config)
    return _allocator_instance
