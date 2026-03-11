"""
Capital Growth Throttle
A lightweight singleton that tracks the live account balance every trading
cycle and exposes a position-size multiplier (0.0 – 1.0) so the rest of the
pipeline can scale down trade sizes automatically when a drawdown is detected.

Correct usage in each trading cycle
------------------------------------
1. ``get_capital_growth_throttle().update_capital(balance)``   ← update first
2. Calculate *base* position size from strategy/risk-manager
3. ``base_size * get_capital_growth_throttle().get_multiplier()``  ← scale it
4. Place the order with the throttled size

Throttle levels (drawdown from all-time peak)
----------------------------------------------
< 5 %    → 1.00  (no throttle)
5–10 %   → 0.75  (conservative)
10–15 %  → 0.50  (moderate)
15–20 %  → 0.25  (strict)
≥ 20 %   → 0.10  (minimal – severely reduced but not fully halted)

Note: some funds prefer a hard lock (0.00) at ≥20% drawdown; this
implementation uses 0.10 so the bot retains a small foothold during
deep drawdowns rather than going completely dark.
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

logger = logging.getLogger("nija.capital_growth_throttle")

# ---------------------------------------------------------------------------
# Drawdown thresholds → position-size multipliers
# ---------------------------------------------------------------------------
_DRAWDOWN_TIERS = [
    # (drawdown_pct_lower_bound, multiplier, label)
    (0.0,  1.00, "UNRESTRICTED"),
    (5.0,  0.75, "CONSERVATIVE"),
    (10.0, 0.50, "MODERATE"),
    (15.0, 0.25, "STRICT"),
    (20.0, 0.10, "MINIMAL"),
]


@dataclass
class ThrottleState:
    """Snapshot of the throttle's current state (read-only for callers)."""
    current_capital: float = 0.0
    peak_capital: float = 0.0
    drawdown_pct: float = 0.0
    multiplier: float = 1.0
    label: str = "UNRESTRICTED"
    last_updated: Optional[datetime] = field(default=None)


class CapitalGrowthThrottle:
    """
    Tracks live balance and returns a position-size multiplier based on
    the drawdown from the all-time peak balance seen during the session.

    Thread-safe via an internal lock.
    """

    def __init__(self, initial_capital: float = 0.0) -> None:
        self._lock = threading.Lock()
        self._state = ThrottleState(
            current_capital=initial_capital,
            peak_capital=initial_capital,
            last_updated=datetime.now(),
        )
        self._update_derived_fields()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_capital(self, current_capital: float) -> None:
        """
        Call once per trading cycle *before* calculating position sizes.

        Updates the internal balance, refreshes the peak if a new high is
        reached, and recalculates the current drawdown and throttle level.

        Args:
            current_capital: The live account balance in USD.
        """
        if current_capital < 0:
            logger.warning(
                "CapitalGrowthThrottle.update_capital received negative balance "
                "(%s) – ignoring update.", current_capital
            )
            return

        if current_capital == 0:
            logger.warning(
                "CapitalGrowthThrottle.update_capital received zero balance – "
                "this may indicate an API or data issue."
            )

        with self._lock:
            self._state.current_capital = current_capital

            # Track all-time peak for this session
            if current_capital > self._state.peak_capital:
                self._state.peak_capital = current_capital

            self._state.last_updated = datetime.now()
            self._update_derived_fields()

            logger.debug(
                "CapitalGrowthThrottle: balance=$%.2f  peak=$%.2f  "
                "drawdown=%.1f%%  multiplier=%.2f (%s)",
                self._state.current_capital,
                self._state.peak_capital,
                self._state.drawdown_pct,
                self._state.multiplier,
                self._state.label,
            )

    def get_multiplier(self) -> float:
        """
        Return the position-size multiplier for the current cycle.

        Apply this to the *base* position size calculated by the
        risk-manager **before** placing an order:

            throttled_size = base_size * throttle.get_multiplier()

        Returns:
            A float between 0.1 (minimal — severe drawdown) and 1.0 (no throttle).
        """
        with self._lock:
            return self._state.multiplier

    def get_size_multiplier(self) -> float:
        """Alias for :meth:`get_multiplier` for API compatibility."""
        return self.get_multiplier()

    @property
    def state(self) -> ThrottleState:
        """Read-only snapshot of the current throttle state."""
        with self._lock:
            return ThrottleState(
                current_capital=self._state.current_capital,
                peak_capital=self._state.peak_capital,
                drawdown_pct=self._state.drawdown_pct,
                multiplier=self._state.multiplier,
                label=self._state.label,
                last_updated=self._state.last_updated,
            )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _update_derived_fields(self) -> None:
        """Recalculate drawdown and select the matching throttle tier."""
        peak = self._state.peak_capital
        if peak > 0:
            self._state.drawdown_pct = (
                (peak - self._state.current_capital) / peak * 100
            )
        else:
            self._state.drawdown_pct = 0.0

        # Walk tiers from most-severe to least – pick the highest threshold exceeded.
        # Iterating in reverse means the first match is the correct (most severe) tier.
        multiplier = 1.0
        label = "UNRESTRICTED"
        for lower_bound, mult, tier_label in reversed(_DRAWDOWN_TIERS):
            if self._state.drawdown_pct >= lower_bound:
                multiplier = mult
                label = tier_label
                break

        prev_label = self._state.label
        self._state.multiplier = multiplier
        self._state.label = label

        if label != prev_label:
            if label == "MINIMAL":
                logger.warning(
                    "🔒 Capital Growth Throttle: MINIMAL — drawdown %.1f%% ≥ 20%%. "
                    "Position sizes reduced to 10%% until capital recovers.",
                    self._state.drawdown_pct,
                )
            elif label in ("STRICT", "MODERATE"):
                logger.warning(
                    "⚠️  Capital Growth Throttle: %s — drawdown %.1f%%, "
                    "position sizes scaled to %.0f%%.",
                    label, self._state.drawdown_pct, multiplier * 100,
                )
            else:
                logger.info(
                    "✅ Capital Growth Throttle: %s — drawdown %.1f%%, "
                    "position sizes at %.0f%%.",
                    label, self._state.drawdown_pct, multiplier * 100,
                )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_throttle_instance: Optional[CapitalGrowthThrottle] = None
_throttle_lock = threading.Lock()


def get_capital_growth_throttle(
    initial_capital: float = 0.0,
    reset: bool = False,
) -> CapitalGrowthThrottle:
    """
    Return the module-level singleton ``CapitalGrowthThrottle``.

    Args:
        initial_capital: Starting balance (only used on first call or reset).
        reset: If ``True``, destroy the existing singleton and create a fresh one.

    Returns:
        The shared ``CapitalGrowthThrottle`` instance.
    """
    global _throttle_instance

    with _throttle_lock:
        if _throttle_instance is None or reset:
            _throttle_instance = CapitalGrowthThrottle(initial_capital=initial_capital)
            logger.info(
                "CapitalGrowthThrottle singleton created (initial_capital=$%.2f).",
                initial_capital,
            )

    return _throttle_instance


__all__ = [
    "CapitalGrowthThrottle",
    "ThrottleState",
    "get_capital_growth_throttle",
]
