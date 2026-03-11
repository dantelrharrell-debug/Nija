"""
NIJA Capital Growth Throttle
=============================

Limits the velocity of capital deployment growth to prevent overexposure
during rapid account growth periods.

Key Features:
1. Growth velocity tracking — measures rate of capital increase over rolling
   short-term (7-day) and long-term (30-day) windows.
2. Velocity-based throttling — reduces position-size scaling multiplier
   automatically when capital grows too fast.
3. Cooling period enforcement — keeps a mild throttle for a configurable
   number of days after the immediate growth spike resolves.
4. Singleton interface — ``get_capital_growth_throttle()`` returns the shared
   instance so every subsystem sees the same state.

This system ensures that rapid profits do not immediately lead to dramatically
larger positions, guarding against overexposure right before potential market
reversals.

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Deque, Dict, Optional

logger = logging.getLogger("nija.capital_growth_throttle")


# ---------------------------------------------------------------------------
# Enums & configuration
# ---------------------------------------------------------------------------

class GrowthThrottleLevel(Enum):
    """Throttle intensity driven by capital-growth velocity."""
    FREE = "free"              # Growth within normal bounds — no restriction
    CAUTION = "caution"        # Growth slightly elevated — mild reduction
    RESTRICTED = "restricted"  # Growth elevated — moderate reduction
    LOCKED = "locked"          # Growth excessive — heavy reduction (floor, not zero)


@dataclass
class GrowthThrottleConfig:
    """Configuration for the capital growth throttle."""

    # Rolling windows used to measure velocity
    short_window_days: int = 7    # Fast-reaction window
    long_window_days: int = 30    # Trend-confirmation window

    # Growth-rate thresholds (percentage gain within ``short_window_days``)
    # that trigger each throttle level.
    # Crypto markets can rally sharply; these defaults are intentionally wide
    # so only exceptional velocity (e.g. 2× in a week) triggers a hard lock.
    # Tune per account size / risk appetite via GrowthThrottleConfig.
    caution_growth_pct: float = 50.0      # ≥50%  → CAUTION
    restricted_growth_pct: float = 100.0  # ≥100% → RESTRICTED
    locked_growth_pct: float = 200.0      # ≥200% → LOCKED

    # Position-size multiplier applied at each throttle level
    free_multiplier: float = 1.00
    caution_multiplier: float = 0.80
    restricted_multiplier: float = 0.50
    locked_multiplier: float = 0.25   # Floor — never drops to zero here

    # After the growth spike resolves, stay in CAUTION for this many days.
    cooling_period_days: int = 3

    # Minimum number of recorded snapshots before throttling is evaluated.
    min_snapshots: int = 5

    # Master switch
    enabled: bool = True


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class _CapitalSnapshot:
    """A single capital observation."""
    capital: float
    timestamp: datetime


@dataclass
class GrowthThrottleState:
    """Mutable state of the growth throttle (one instance per engine)."""
    throttle_level: GrowthThrottleLevel = GrowthThrottleLevel.FREE
    current_multiplier: float = 1.0
    short_growth_pct: float = 0.0
    long_growth_pct: float = 0.0
    throttle_reason: str = "initialising"
    last_throttle_time: Optional[datetime] = None
    cooling_until: Optional[datetime] = None
    last_updated: datetime = field(default_factory=datetime.now)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class CapitalGrowthThrottle:
    """
    Capital Growth Throttle System

    Tracks capital balance over time and reduces position-size scaling
    whenever the growth velocity exceeds configured thresholds.

    Typical integration::

        throttle = get_capital_growth_throttle(initial_capital=5000.0)

        # Called each trading cycle / bar
        throttle.update_capital(current_balance)

        # Applied before every position-sizing calculation
        size_usd = base_size_usd * throttle.get_size_multiplier()
    """

    def __init__(
        self,
        initial_capital: float,
        config: Optional[GrowthThrottleConfig] = None,
    ) -> None:
        self.config = config or GrowthThrottleConfig()
        self.initial_capital = initial_capital

        # Circular buffer — we never need more than long_window + buffer days
        self._snapshots: Deque[_CapitalSnapshot] = deque()
        self.state = GrowthThrottleState()

        # Seed with the starting capital so the first few calls have context.
        self._record_snapshot(initial_capital)

        logger.info("=" * 60)
        logger.info("🚦 Capital Growth Throttle Initialised")
        logger.info("=" * 60)
        logger.info("Initial Capital  : $%.2f", initial_capital)
        logger.info("Short Window     : %d days", self.config.short_window_days)
        logger.info("Long Window      : %d days", self.config.long_window_days)
        logger.info(
            "Thresholds       : CAUTION≥%.0f%%  RESTRICTED≥%.0f%%  LOCKED≥%.0f%%",
            self.config.caution_growth_pct,
            self.config.restricted_growth_pct,
            self.config.locked_growth_pct,
        )
        logger.info("=" * 60)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _record_snapshot(self, capital: float) -> None:
        """Append a new capital snapshot and prune stale entries."""
        self._snapshots.append(
            _CapitalSnapshot(capital=capital, timestamp=datetime.now())
        )
        # Drop entries older than the long window + a small buffer.
        cutoff = datetime.now() - timedelta(
            days=self.config.long_window_days + 5
        )
        while self._snapshots and self._snapshots[0].timestamp < cutoff:
            self._snapshots.popleft()

    def _growth_pct_over_window(self, window_days: int) -> Optional[float]:
        """
        Return percentage capital growth observed within ``window_days``.

        The internal deque is maintained in chronological order (oldest at the
        left, newest at the right — oldest first, newest last).  We scan from
        left to right to find the *earliest* snapshot that falls inside the
        window; that becomes the reference starting point for the growth
        calculation.

        Returns ``None`` if there are not enough snapshots or the oldest
        reference capital is zero / negative.
        """
        if len(self._snapshots) < self.config.min_snapshots:
            return None

        cutoff = datetime.now() - timedelta(days=window_days)
        reference: Optional[_CapitalSnapshot] = None
        for snap in self._snapshots:
            if snap.timestamp >= cutoff:
                reference = snap
                break

        if reference is None or reference.capital <= 0:
            return None

        current = self._snapshots[-1].capital
        return (current - reference.capital) / reference.capital * 100.0

    # ------------------------------------------------------------------
    # Public interface
    # ------------------------------------------------------------------

    def update_capital(self, current_capital: float) -> GrowthThrottleState:
        """
        Record the latest balance and refresh the throttle level.

        **Call this once per trading cycle** (whenever the account balance is
        fetched from the broker) *before* calling :meth:`get_size_multiplier`.
        :meth:`get_size_multiplier` only reads the cached state computed by
        the most recent ``update_capital`` call; it does not re-evaluate growth
        velocity on its own.

        Args:
            current_capital: Current account balance in USD.

        Returns:
            The updated :class:`GrowthThrottleState`.
        """
        if not self.config.enabled:
            self.state.throttle_reason = "disabled"
            return self.state

        self._record_snapshot(current_capital)

        short_growth = self._growth_pct_over_window(self.config.short_window_days)
        long_growth = self._growth_pct_over_window(self.config.long_window_days)

        self.state.short_growth_pct = short_growth if short_growth is not None else 0.0
        self.state.long_growth_pct = long_growth if long_growth is not None else 0.0
        self.state.last_updated = datetime.now()

        # Not enough history yet — stay FREE
        if short_growth is None:
            self.state.throttle_level = GrowthThrottleLevel.FREE
            self.state.current_multiplier = self.config.free_multiplier
            self.state.throttle_reason = "insufficient_history"
            return self.state

        # Determine target level from growth velocity
        if short_growth >= self.config.locked_growth_pct:
            new_level = GrowthThrottleLevel.LOCKED
            new_multiplier = self.config.locked_multiplier
            reason = (
                f"extreme_growth_{short_growth:.1f}%"
                f"_in_{self.config.short_window_days}d"
            )
        elif short_growth >= self.config.restricted_growth_pct:
            new_level = GrowthThrottleLevel.RESTRICTED
            new_multiplier = self.config.restricted_multiplier
            reason = (
                f"high_growth_{short_growth:.1f}%"
                f"_in_{self.config.short_window_days}d"
            )
        elif short_growth >= self.config.caution_growth_pct:
            new_level = GrowthThrottleLevel.CAUTION
            new_multiplier = self.config.caution_multiplier
            reason = (
                f"elevated_growth_{short_growth:.1f}%"
                f"_in_{self.config.short_window_days}d"
            )
        else:
            # Growth is normal; check whether we are still in a cooling period.
            if (
                self.state.cooling_until is not None
                and datetime.now() < self.state.cooling_until
            ):
                new_level = GrowthThrottleLevel.CAUTION
                new_multiplier = self.config.caution_multiplier
                reason = (
                    f"cooling_until_"
                    f"{self.state.cooling_until.strftime('%Y-%m-%d')}"
                )
            else:
                new_level = GrowthThrottleLevel.FREE
                new_multiplier = self.config.free_multiplier
                reason = "normal_growth"

        # Log transitions
        old_level = self.state.throttle_level
        if new_level != GrowthThrottleLevel.FREE and old_level == GrowthThrottleLevel.FREE:
            # Entering a throttled state — start the cooling clock.
            self.state.last_throttle_time = datetime.now()
            self.state.cooling_until = datetime.now() + timedelta(
                days=self.config.cooling_period_days
            )
            logger.warning(
                "⚠️  Growth throttle ACTIVATED: level=%s  growth=%.1f%%  "
                "multiplier=%.2fx  cooling_until=%s",
                new_level.value,
                short_growth,
                new_multiplier,
                self.state.cooling_until.strftime("%Y-%m-%d"),
            )
        elif new_level == GrowthThrottleLevel.FREE and old_level != GrowthThrottleLevel.FREE:
            logger.info(
                "✅ Growth throttle CLEARED (still in cooling period until %s)",
                self.state.cooling_until.strftime("%Y-%m-%d")
                if self.state.cooling_until
                else "N/A",
            )

        self.state.throttle_level = new_level
        self.state.current_multiplier = new_multiplier
        self.state.throttle_reason = reason

        return self.state

    def get_size_multiplier(self) -> float:
        """
        Return the position-size multiplier that should be applied *before*
        computing the final position size.

        Returns:
            A float in the range [``locked_multiplier``, 1.0].
            If the throttle is disabled, always returns ``1.0``.
        """
        if not self.config.enabled:
            return 1.0
        return self.state.current_multiplier

    def get_status(self) -> Dict:
        """Return a diagnostic snapshot suitable for dashboards and logging."""
        return {
            "enabled": self.config.enabled,
            "throttle_level": self.state.throttle_level.value,
            "current_multiplier": self.state.current_multiplier,
            "short_growth_pct": round(self.state.short_growth_pct, 2),
            "long_growth_pct": round(self.state.long_growth_pct, 2),
            "throttle_reason": self.state.throttle_reason,
            "last_throttle_time": (
                self.state.last_throttle_time.isoformat()
                if self.state.last_throttle_time
                else None
            ),
            "cooling_until": (
                self.state.cooling_until.isoformat()
                if self.state.cooling_until
                else None
            ),
            "snapshots_recorded": len(self._snapshots),
            "last_updated": self.state.last_updated.isoformat(),
        }


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_THROTTLE_INSTANCE: Optional[CapitalGrowthThrottle] = None


def get_capital_growth_throttle(
    initial_capital: float = 1_000.0,
    config: Optional[GrowthThrottleConfig] = None,
) -> CapitalGrowthThrottle:
    """
    Return the process-wide singleton :class:`CapitalGrowthThrottle`.

    The first caller determines ``initial_capital`` and ``config``; subsequent
    callers receive the already-initialised instance regardless of the
    arguments they pass.
    """
    global _THROTTLE_INSTANCE
    if _THROTTLE_INSTANCE is None:
        _THROTTLE_INSTANCE = CapitalGrowthThrottle(initial_capital, config)
    return _THROTTLE_INSTANCE
