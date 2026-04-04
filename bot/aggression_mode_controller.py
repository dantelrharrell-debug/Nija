"""
NIJA Aggression Mode Controller
=================================
User-configurable aggression modes: SAFE | BALANCED | MODERATE | AGGRESSIVE

Controls entry thresholds, position sizing, and trade frequency
based on the operator's risk preference. Set via environment variable:

    AGGRESSION_MODE=SAFE       # Most selective — capital preservation
    AGGRESSION_MODE=BALANCED   # Balanced risk/reward
    AGGRESSION_MODE=MODERATE   # Between BALANCED and AGGRESSIVE — quality + frequency
    AGGRESSION_MODE=AGGRESSIVE # More trades, lower thresholds — "print money" (default)

Each mode overlays a parameter delta on top of the base strategy
thresholds, meaning it works alongside (not against) existing safety
layers such as the sniper filter, drawdown circuit breaker, etc.
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, Optional

logger = logging.getLogger("nija.aggression_mode_controller")

# ---------------------------------------------------------------------------
# Enum
# ---------------------------------------------------------------------------

class AggressionMode(Enum):
    SAFE = "SAFE"
    BALANCED = "BALANCED"
    MODERATE = "MODERATE"
    AGGRESSIVE = "AGGRESSIVE"


# ---------------------------------------------------------------------------
# Mode parameter profiles
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ModeProfile:
    """Parameters injected into the strategy based on aggression mode."""

    mode: AggressionMode
    description: str

    # ── Entry thresholds ─────────────────────────────────────────────────────
    # Confidence delta applied on top of the base signal confidence.
    # Negative = easier to enter (AGGRESSIVE), positive = harder (SAFE).
    confidence_delta: float

    # Minimum signal strength multiplier (1.0 = no change).
    signal_strength_multiplier: float

    # ── Position sizing ───────────────────────────────────────────────────────
    # Multiplier applied to the resolved base position size.
    position_size_multiplier: float

    # Hard cap on position as % of account equity (0–1).
    max_position_pct: float

    # ── Concurrent positions ──────────────────────────────────────────────────
    max_concurrent_positions: int

    # ── Stop-loss / take-profit ───────────────────────────────────────────────
    # SL distance multiplier (>1 = wider stop, <1 = tighter stop).
    stop_loss_multiplier: float
    # TP target multiplier.
    take_profit_multiplier: float

    # ── Risk per trade (%) ────────────────────────────────────────────────────
    risk_per_trade_pct: float

    # ── Trade-frequency hint ──────────────────────────────────────────────────
    # Minimum trades per hour the mode is willing to target.
    min_trades_per_hour: float
    # Minimum trades per day.
    min_trades_per_day: float

    # ── Regime tolerance ──────────────────────────────────────────────────────
    # Whether to skip entries during CHOP/CRASH regimes.
    regime_strict: bool

    # ── MTF confirmation ─────────────────────────────────────────────────────
    mtf_required: bool

    # ── Emoji for logs ────────────────────────────────────────────────────────
    emoji: str


# ---------------------------------------------------------------------------
# Default profiles
# ---------------------------------------------------------------------------

SAFE_PROFILE = ModeProfile(
    mode=AggressionMode.SAFE,
    description="Capital preservation — only the highest-conviction entries",
    confidence_delta=+0.05,          # harder to enter
    signal_strength_multiplier=1.10,
    position_size_multiplier=0.80,
    max_position_pct=0.06,           # 6 % cap per trade
    max_concurrent_positions=3,
    stop_loss_multiplier=0.85,       # tighter stop
    take_profit_multiplier=1.10,     # stretch TP
    risk_per_trade_pct=0.75,
    min_trades_per_hour=0.25,
    min_trades_per_day=2.0,
    regime_strict=True,
    mtf_required=True,
    emoji="🛡️",
)

BALANCED_PROFILE = ModeProfile(
    mode=AggressionMode.BALANCED,
    description="Balanced risk/reward — default production setting",
    confidence_delta=0.0,
    signal_strength_multiplier=1.0,
    position_size_multiplier=1.0,
    max_position_pct=0.10,
    max_concurrent_positions=5,
    stop_loss_multiplier=1.0,
    take_profit_multiplier=1.0,
    risk_per_trade_pct=1.0,
    min_trades_per_hour=0.45,
    min_trades_per_day=10.0,
    regime_strict=False,
    mtf_required=False,
    emoji="⚖️",
)

MODERATE_PROFILE = ModeProfile(
    mode=AggressionMode.MODERATE,
    description="Quality + frequency — sits between BALANCED and AGGRESSIVE, floor ≥12 trades/day",
    confidence_delta=-0.03,          # gently easier to enter than BALANCED
    signal_strength_multiplier=0.95,
    position_size_multiplier=1.10,
    max_position_pct=0.12,           # 12 % cap per trade
    max_concurrent_positions=7,
    stop_loss_multiplier=1.07,       # slightly wider stop
    take_profit_multiplier=0.97,
    risk_per_trade_pct=1.25,
    min_trades_per_hour=0.55,
    min_trades_per_day=12.0,         # floor: at least 12 trades/day
    regime_strict=False,
    mtf_required=False,
    emoji="⚡",
)

AGGRESSIVE_PROFILE = ModeProfile(
    mode=AggressionMode.AGGRESSIVE,
    description="High-quality trades targeting 10–15/day — quality over pure frequency",
    confidence_delta=-0.06,          # easier to enter
    signal_strength_multiplier=0.90,
    position_size_multiplier=1.20,
    max_position_pct=0.15,
    max_concurrent_positions=10,     # increased from 8 → 10 for more simultaneous opportunities
    stop_loss_multiplier=1.15,       # slightly wider stop
    take_profit_multiplier=0.95,
    risk_per_trade_pct=1.50,
    min_trades_per_hour=0.65,        # ~0.65/hr sustains the 15/day upper cap without over-loosening
    min_trades_per_day=15.0,         # top of 10–15/day target band
    regime_strict=False,
    mtf_required=False,
    emoji="🔥",
)

_MODE_MAP: Dict[AggressionMode, ModeProfile] = {
    AggressionMode.SAFE: SAFE_PROFILE,
    AggressionMode.BALANCED: BALANCED_PROFILE,
    AggressionMode.MODERATE: MODERATE_PROFILE,
    AggressionMode.AGGRESSIVE: AGGRESSIVE_PROFILE,
}


# ---------------------------------------------------------------------------
# Controller class
# ---------------------------------------------------------------------------

class AggressionModeController:
    """
    Thread-safe controller that resolves the current aggression mode and
    provides helpers to apply mode parameters to strategy inputs.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._mode = self._resolve_mode_from_env()
        logger.info(
            "%s AggressionModeController started — mode=%s (%s)",
            self.profile.emoji,
            self._mode.value,
            self.profile.description,
        )

    # ── Internal helpers ─────────────────────────────────────────────────────

    @staticmethod
    def _resolve_mode_from_env() -> AggressionMode:
        raw = os.environ.get("AGGRESSION_MODE", "AGGRESSIVE").upper().strip()
        try:
            return AggressionMode(raw)
        except ValueError:
            logger.warning(
                "⚠️ Unknown AGGRESSION_MODE=%r — falling back to BALANCED", raw
            )
            return AggressionMode.BALANCED

    # ── Public API ────────────────────────────────────────────────────────────

    @property
    def mode(self) -> AggressionMode:
        with self._lock:
            return self._mode

    @property
    def profile(self) -> ModeProfile:
        with self._lock:
            return _MODE_MAP[self._mode]

    def set_mode(self, mode: AggressionMode) -> None:
        """Hot-switch aggression mode at runtime (e.g. via webhook command)."""
        with self._lock:
            old = self._mode
            self._mode = mode
        if old != mode:
            p = _MODE_MAP[mode]
            logger.info(
                "%s AggressionMode changed: %s → %s (%s)",
                p.emoji, old.value, mode.value, p.description,
            )

    def apply_confidence(self, raw_confidence: float) -> float:
        """
        Apply the mode's confidence_delta to a raw signal confidence score.

        Returns a value clamped to [0.0, 1.0].
        """
        adjusted = raw_confidence + self.profile.confidence_delta
        return max(0.0, min(1.0, adjusted))

    def apply_position_size(self, base_size_usd: float, balance_usd: float) -> float:
        """
        Apply the mode's position-size multiplier and enforce the % cap.

        Args:
            base_size_usd: The base calculated position size in USD.
            balance_usd: Current account balance in USD (used for cap).

        Returns:
            Final position size in USD.
        """
        p = self.profile
        size = base_size_usd * p.position_size_multiplier
        cap = balance_usd * p.max_position_pct
        return min(size, cap)

    def get_report(self) -> dict:
        """Return a summary dict for logging / API endpoints."""
        p = self.profile
        return {
            "mode": p.mode.value,
            "description": p.description,
            "confidence_delta": p.confidence_delta,
            "position_size_multiplier": p.position_size_multiplier,
            "max_position_pct": p.max_position_pct,
            "max_concurrent_positions": p.max_concurrent_positions,
            "risk_per_trade_pct": p.risk_per_trade_pct,
            "min_trades_per_hour": p.min_trades_per_hour,
            "min_trades_per_day": p.min_trades_per_day,
            "regime_strict": p.regime_strict,
            "mtf_required": p.mtf_required,
        }


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_controller_instance: Optional[AggressionModeController] = None
_controller_lock = threading.Lock()


def get_aggression_mode_controller(
    mode: Optional[AggressionMode] = None,
) -> AggressionModeController:
    """
    Return the thread-safe singleton AggressionModeController.

    If *mode* is provided on the first call it will override the env-var
    default, allowing programmatic initialisation.
    """
    global _controller_instance
    if _controller_instance is None:
        with _controller_lock:
            if _controller_instance is None:
                _controller_instance = AggressionModeController()
                if mode is not None:
                    _controller_instance.set_mode(mode)
    return _controller_instance
