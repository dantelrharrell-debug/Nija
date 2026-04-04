"""
NIJA Aggression Mode Controller
=================================
User-configurable aggression modes: SAFE | BALANCED | MODERATE | AGGRESSIVE

Controls entry thresholds, position sizing, and trade frequency
based on the operator's risk preference. Set via environment variable:

    AGGRESSION_MODE=SAFE       # Most selective — capital preservation
    AGGRESSION_MODE=BALANCED   # Balanced risk/reward
    AGGRESSION_MODE=MODERATE   # Between BALANCED and AGGRESSIVE — quality + frequency
    AGGRESSION_MODE=MODERATE   # Relaxed quality filter + lowered thresholds (between BALANCED and AGGRESSIVE)
    AGGRESSION_MODE=AGGRESSIVE # More trades, lower thresholds — "print money" (default)

Each mode overlays a parameter delta on top of the base strategy
thresholds, meaning it works alongside (not against) existing safety
layers such as the sniper filter, drawdown circuit breaker, etc.

Subsystem wiring
----------------
Calling ``apply_to_subsystems()`` (or ``set_mode()``) propagates the
mode's quality-filter and scoring-threshold overrides into three
live singletons:
  • AITradeQualityFilter  — win-prob & model-confidence thresholds
  • NijaAIEngine          — absolute composite-score floor
  • AIEntryGate           — gate pass threshold (out of 9 pts)
  • WinRateMaximizer      — Layer-2 signal quality threshold
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

    # ── Quality filter thresholds ─────────────────────────────────────────────
    # Applied to AITradeQualityFilter via apply_to_subsystems().
    # quality_filter_win_prob   — min ML-predicted win probability (0-1);
    #                             also governs the heuristic fallback path.
    # quality_filter_model_conf — min model confidence score (0-1).
    quality_filter_win_prob: float
    quality_filter_model_conf: float

    # ── Scoring thresholds ────────────────────────────────────────────────────
    # score_floor_absolute  — hard composite-score floor in NijaAIEngine
    #                         (same scale as MIN_SCORE_ABSOLUTE, 0-100).
    # gate_pass_threshold   — weighted gate pass bar in AIEntryGate
    #                         (out of 9 total gate pts).
    # wmx_signal_threshold  — Layer-2 signal quality floor in WinRateMaximizer
    #                         (0-100 scale, 4-component score).
    score_floor_absolute: float
    gate_pass_threshold: float
    wmx_signal_threshold: float


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
    # Quality filter — strict
    quality_filter_win_prob=0.65,
    quality_filter_model_conf=0.80,
    # Scoring thresholds — tighter than defaults
    score_floor_absolute=28.0,
    gate_pass_threshold=4.0,
    wmx_signal_threshold=60.0,
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
    # Quality filter — standard defaults
    quality_filter_win_prob=0.55,
    quality_filter_model_conf=0.70,
    # Scoring thresholds — current system defaults
    score_floor_absolute=20.0,
    gate_pass_threshold=2.6,
    wmx_signal_threshold=46.0,
)

MODERATE_PROFILE = ModeProfile(
    mode=AggressionMode.MODERATE,
    description="Moderate aggression — relaxed quality filter + lowered thresholds (between BALANCED and AGGRESSIVE)",
    confidence_delta=-0.03,          # halfway between BALANCED (0.0) and AGGRESSIVE (-0.06)
    signal_strength_multiplier=0.95,
    position_size_multiplier=1.10,
    max_position_pct=0.12,
    max_concurrent_positions=7,
    stop_loss_multiplier=1.08,
    take_profit_multiplier=0.98,
    risk_per_trade_pct=1.25,
    min_trades_per_hour=0.55,
    min_trades_per_day=12.0,
    regime_strict=False,
    mtf_required=False,
    emoji="⚡",
    # Quality filter — relaxed relative to BALANCED
    quality_filter_win_prob=0.50,
    quality_filter_model_conf=0.63,
    # Scoring thresholds — lowered relative to BALANCED
    score_floor_absolute=18.5,
    gate_pass_threshold=2.4,
    wmx_signal_threshold=42.0,
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
    # Quality filter — flow-mode (AGGRESSIVE + Flow Overrides)
    quality_filter_win_prob=0.42,         # lowered 0.46 → 0.42 for flow mode
    quality_filter_model_conf=0.50,       # lowered 0.58 → 0.50 for flow mode
    # Scoring thresholds — flow-mode activation zone for micro-cap scalping
    score_floor_absolute=15.5,            # lowered 17.0 → 15.5 for flow mode
    gate_pass_threshold=2.2,
    wmx_signal_threshold=34.0,            # lowered 37.0 → 34.0 for flow mode
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
        self.apply_to_subsystems()

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
        self.apply_to_subsystems()

    def apply_to_subsystems(self) -> None:
        """
        Push the active profile's quality-filter and scoring thresholds into
        the live singletons that own them.

        Safe to call at any time — each subsystem setter is idempotent and
        logs its own update message.  ImportError / AttributeError (expected
        when an optional module is absent) are silently skipped at DEBUG level.
        Any other exception is logged at WARNING level since it likely indicates
        a genuine bug in a loaded subsystem.
        """
        p = self.profile

        self._wire_subsystem(
            label="AITradeQualityFilter",
            module_names=("ai_trade_quality_filter", "bot.ai_trade_quality_filter"),
            getter_name="get_ai_trade_quality_filter",
            action=lambda obj: obj.set_thresholds(
                win_prob=p.quality_filter_win_prob,
                model_conf=p.quality_filter_model_conf,
            ),
        )
        self._wire_subsystem(
            label="NijaAIEngine",
            module_names=("nija_ai_engine", "bot.nija_ai_engine"),
            getter_name="get_nija_ai_engine",
            action=lambda obj: obj.set_score_floor(p.score_floor_absolute),
        )
        self._wire_subsystem(
            label="AIEntryGate",
            module_names=("ai_entry_gate", "bot.ai_entry_gate"),
            getter_name="set_gate_pass_threshold",
            action=lambda fn: fn(p.gate_pass_threshold),
            is_function=True,
        )
        self._wire_subsystem(
            label="WinRateMaximizer",
            module_names=("win_rate_maximizer", "bot.win_rate_maximizer"),
            getter_name="get_win_rate_maximizer",
            action=lambda obj: obj.set_signal_threshold(p.wmx_signal_threshold),
        )

        logger.info(
            "%s apply_to_subsystems: win_prob=%.2f model_conf=%.2f "
            "score_floor=%.1f gate_thr=%.1f wmx_thr=%.1f",
            p.emoji,
            p.quality_filter_win_prob,
            p.quality_filter_model_conf,
            p.score_floor_absolute,
            p.gate_pass_threshold,
            p.wmx_signal_threshold,
        )

    @staticmethod
    def _wire_subsystem(
        label: str,
        module_names: tuple,
        getter_name: str,
        action,
        is_function: bool = False,
    ) -> None:
        """
        Import ``getter_name`` from the first available module in *module_names*
        and invoke *action* on the result.

        ImportError / AttributeError are logged at DEBUG (expected when an
        optional module is absent).  Any other exception is logged at WARNING
        since it likely indicates a genuine bug in a loaded subsystem.
        """
        import importlib
        for mod_name in module_names:
            try:
                mod = importlib.import_module(mod_name)
                target = getattr(mod, getter_name)
                obj = target if is_function else target()
                action(obj)
                return
            except (ImportError, AttributeError) as exc:
                logger.debug("apply_to_subsystems: %s skip (%s: %s)", label, type(exc).__name__, exc)
            except Exception as exc:
                logger.warning("apply_to_subsystems: %s error — %s: %s", label, type(exc).__name__, exc)
                return

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
            "quality_filter_win_prob": p.quality_filter_win_prob,
            "quality_filter_model_conf": p.quality_filter_model_conf,
            "score_floor_absolute": p.score_floor_absolute,
            "gate_pass_threshold": p.gate_pass_threshold,
            "wmx_signal_threshold": p.wmx_signal_threshold,
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
