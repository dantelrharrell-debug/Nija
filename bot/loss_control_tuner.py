"""
NIJA Loss Control Tuner
=========================

Automatic drawdown-response layer that tightens the entry filter and
reduces trade aggression whenever the account's drawdown spikes.

Three-tier response
-------------------
::

    Drawdown level     Confidence tighten delta    Auto-switch mode
    ──────────────     ────────────────────────    ────────────────
    < CAUTION_PCT      0.0                         (no change)
    CAUTION_PCT        +0.03                       BALANCED
    WARNING_PCT        +0.06                       SAFE
    DANGER_PCT+        +0.10                       SAFE  (max tighten)

The *confidence tighten delta* is a **positive** number added to the sniper
filter's confidence gate before it is compared against the incoming signal.
A higher gate means fewer signals pass → trade frequency drops and only
the strongest setups are accepted.

Automatic recovery
------------------
When drawdown falls back below the caution floor the module:
  • Resets the confidence delta to 0.0
  • Restores the aggression mode to whatever was set at startup (read from
    ``AGGRESSION_MODE`` env var, default ``AGGRESSIVE``).

The module reads drawdown information directly from the
``GlobalDrawdownCircuitBreaker`` singleton so there is a single source of
truth — it never double-counts.

Architecture
------------
::

    LossControlTuner (singleton via get_loss_control_tuner())
    │
    ├── update()
    │     Reads current drawdown % from GlobalDrawdownCircuitBreaker and
    │     updates internal state + AggressionModeController.
    │
    ├── get_confidence_tighten_delta() → float
    │     Positive number to ADD to confidence gate when filtering entries.
    │     0.0 when drawdown is within normal range.
    │
    ├── get_size_reduction_multiplier() → float
    │     1.0 – normal  |  < 1.0 – drawdown-driven size reduction.
    │     Separate from the circuit-breaker's own multiplier; stacks on top.
    │
    └── get_report() → dict

Usage
-----
::

    from bot.loss_control_tuner import get_loss_control_tuner

    tuner = get_loss_control_tuner()

    # Before each scan cycle (or at scan-loop start):
    tuner.update()

    # In the confidence gate (adds to existing deltas):
    effective_confidence += tuner.get_confidence_tighten_delta()

    # In position sizing (multiply AFTER other adjustments):
    position_size *= tuner.get_size_reduction_multiplier()

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger("nija.loss_control_tuner")

# ---------------------------------------------------------------------------
# Drawdown tier thresholds (%)
# ---------------------------------------------------------------------------

CAUTION_PCT: float = float(os.environ.get("LCT_CAUTION_PCT", "3.0"))
WARNING_PCT: float = float(os.environ.get("LCT_WARNING_PCT", "5.0"))
DANGER_PCT: float = float(os.environ.get("LCT_DANGER_PCT", "8.0"))

# Confidence deltas per tier (added to gate → tightens entry)
CAUTION_CONF_DELTA: float = 0.03
WARNING_CONF_DELTA: float = 0.06
DANGER_CONF_DELTA: float = 0.10

# Position-size multipliers per tier (< 1.0 → smaller position)
CAUTION_SIZE_MULT: float = 0.90
WARNING_SIZE_MULT: float = 0.75
DANGER_SIZE_MULT: float = 0.55


# ---------------------------------------------------------------------------
# Tier enum
# ---------------------------------------------------------------------------

class DrawdownTier(Enum):
    NORMAL = "NORMAL"
    CAUTION = "CAUTION"
    WARNING = "WARNING"
    DANGER = "DANGER"


# ---------------------------------------------------------------------------
# State snapshot
# ---------------------------------------------------------------------------

@dataclass
class LossControlState:
    tier: DrawdownTier
    drawdown_pct: float
    confidence_delta: float
    size_multiplier: float
    aggression_was_reduced: bool


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class LossControlTuner:
    """
    Monitors live drawdown and auto-tightens entry filters and aggression mode.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._tier = DrawdownTier.NORMAL
        self._confidence_delta: float = 0.0
        self._size_multiplier: float = 1.0
        self._aggression_was_reduced: bool = False

        # Lazy references to avoid circular imports at module load time
        self._drawdown_cb = None
        self._aggression_ctrl = None
        self._base_aggression_mode = None  # mode at startup, used for recovery

        logger.info(
            "✅ LossControlTuner ready — "
            "caution=%.0f%% warning=%.0f%% danger=%.0f%%",
            CAUTION_PCT, WARNING_PCT, DANGER_PCT,
        )

    # ── Internal helpers ─────────────────────────────────────────────────────

    def _get_drawdown_cb(self):
        if self._drawdown_cb is None:
            try:
                from global_drawdown_circuit_breaker import get_global_drawdown_cb
                self._drawdown_cb = get_global_drawdown_cb()
            except ImportError:
                try:
                    from bot.global_drawdown_circuit_breaker import get_global_drawdown_cb
                    self._drawdown_cb = get_global_drawdown_cb()
                except ImportError:
                    pass
        return self._drawdown_cb

    def _get_aggression_ctrl(self):
        if self._aggression_ctrl is None:
            try:
                from aggression_mode_controller import (
                    get_aggression_mode_controller,
                    AggressionMode,
                )
                self._aggression_ctrl = get_aggression_mode_controller()
                self._base_aggression_mode = self._aggression_ctrl.mode
                # Also store AggressionMode for later use
                self._AggressionMode = AggressionMode
            except ImportError:
                try:
                    from bot.aggression_mode_controller import (
                        get_aggression_mode_controller,
                        AggressionMode,
                    )
                    self._aggression_ctrl = get_aggression_mode_controller()
                    self._base_aggression_mode = self._aggression_ctrl.mode
                    self._AggressionMode = AggressionMode
                except ImportError:
                    pass
        return self._aggression_ctrl

    @staticmethod
    def _tier_from_drawdown(dd_pct: float) -> DrawdownTier:
        if dd_pct >= DANGER_PCT:
            return DrawdownTier.DANGER
        if dd_pct >= WARNING_PCT:
            return DrawdownTier.WARNING
        if dd_pct >= CAUTION_PCT:
            return DrawdownTier.CAUTION
        return DrawdownTier.NORMAL

    def _params_for_tier(self, tier: DrawdownTier):
        if tier == DrawdownTier.DANGER:
            return DANGER_CONF_DELTA, DANGER_SIZE_MULT
        if tier == DrawdownTier.WARNING:
            return WARNING_CONF_DELTA, WARNING_SIZE_MULT
        if tier == DrawdownTier.CAUTION:
            return CAUTION_CONF_DELTA, CAUTION_SIZE_MULT
        return 0.0, 1.0

    # ── Public API ────────────────────────────────────────────────────────────

    def update(self, drawdown_pct: Optional[float] = None) -> LossControlState:
        """
        Refresh internal state from the current drawdown level.

        If *drawdown_pct* is provided it is used directly (e.g. when the
        caller already has the value).  Otherwise the method fetches it from
        the ``GlobalDrawdownCircuitBreaker`` singleton.

        Returns the current ``LossControlState``.
        """
        if drawdown_pct is None:
            cb = self._get_drawdown_cb()
            if cb is not None:
                try:
                    drawdown_pct = cb.get_drawdown_pct()
                except Exception:
                    drawdown_pct = 0.0
            else:
                drawdown_pct = 0.0

        new_tier = self._tier_from_drawdown(drawdown_pct)
        conf_delta, size_mult = self._params_for_tier(new_tier)

        with self._lock:
            old_tier = self._tier
            self._tier = new_tier
            self._confidence_delta = conf_delta
            self._size_multiplier = size_mult

        # ── Aggression mode auto-switch ───────────────────────────────────────
        ctrl = self._get_aggression_ctrl()
        if ctrl is not None and hasattr(self, '_AggressionMode'):
            AggressionMode = self._AggressionMode
            try:
                if new_tier in (DrawdownTier.WARNING, DrawdownTier.DANGER):
                    if ctrl.mode != AggressionMode.SAFE:
                        _old_mode = ctrl.mode.value
                        ctrl.set_mode(AggressionMode.SAFE)
                        with self._lock:
                            self._aggression_was_reduced = True
                        logger.warning(
                            "🛡️  LossControlTuner: drawdown=%.1f%% — "
                            "AggressionMode → SAFE (was %s)",
                            drawdown_pct, _old_mode,
                        )
                elif new_tier == DrawdownTier.CAUTION:
                    if ctrl.mode == AggressionMode.AGGRESSIVE:
                        ctrl.set_mode(AggressionMode.BALANCED)
                        with self._lock:
                            self._aggression_was_reduced = True
                        logger.info(
                            "⚖️  LossControlTuner: drawdown=%.1f%% — "
                            "AggressionMode → BALANCED (caution)",
                            drawdown_pct,
                        )
                elif new_tier == DrawdownTier.NORMAL:
                    with self._lock:
                        was_reduced = self._aggression_was_reduced
                    if was_reduced and self._base_aggression_mode is not None:
                        if ctrl.mode != self._base_aggression_mode:
                            ctrl.set_mode(self._base_aggression_mode)
                            with self._lock:
                                self._aggression_was_reduced = False
                            logger.info(
                                "✅ LossControlTuner: drawdown normalised — "
                                "AggressionMode restored to %s",
                                self._base_aggression_mode.value,
                            )
            except Exception as _e:
                logger.debug("LossControlTuner aggression switch error: %s", _e)

        # ── Log tier change ───────────────────────────────────────────────────
        if new_tier != old_tier:
            emoji_map = {
                DrawdownTier.NORMAL: "✅",
                DrawdownTier.CAUTION: "⚠️",
                DrawdownTier.WARNING: "🔶",
                DrawdownTier.DANGER: "🚨",
            }
            logger.info(
                "%s LossControlTuner: tier %s → %s | drawdown=%.1f%% "
                "conf_delta=+%.2f size_mult=%.2f",
                emoji_map[new_tier],
                old_tier.value,
                new_tier.value,
                drawdown_pct,
                conf_delta,
                size_mult,
            )

        return LossControlState(
            tier=new_tier,
            drawdown_pct=drawdown_pct,
            confidence_delta=conf_delta,
            size_multiplier=size_mult,
            aggression_was_reduced=self._aggression_was_reduced,
        )

    def get_confidence_tighten_delta(self) -> float:
        """
        Return the current confidence tightening delta.

        This is a **positive** number — add it to the confidence gate to make
        entry harder.  Returns ``0.0`` when drawdown is within normal range.
        """
        with self._lock:
            return self._confidence_delta

    def get_size_reduction_multiplier(self) -> float:
        """
        Return the current position-size reduction multiplier.

        ``1.0`` when normal; ``< 1.0`` when drawdown protection is active.
        """
        with self._lock:
            return self._size_multiplier

    def get_report(self) -> dict:
        """Return a snapshot dict suitable for logging / dashboards."""
        with self._lock:
            return {
                "tier": self._tier.value,
                "confidence_tighten_delta": round(self._confidence_delta, 3),
                "size_reduction_multiplier": round(self._size_multiplier, 3),
                "aggression_was_reduced": self._aggression_was_reduced,
                "thresholds": {
                    "caution_pct": CAUTION_PCT,
                    "warning_pct": WARNING_PCT,
                    "danger_pct": DANGER_PCT,
                },
            }


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_instance: Optional[LossControlTuner] = None
_instance_lock = threading.Lock()


def get_loss_control_tuner() -> LossControlTuner:
    """Return the process-wide singleton ``LossControlTuner``."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = LossControlTuner()
    return _instance
