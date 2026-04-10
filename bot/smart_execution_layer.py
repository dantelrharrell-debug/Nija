"""
NIJA Smart Execution Layer
==========================

Decides the execution mode for every confirmed signal before position sizing
begins.  The three possible outcomes are:

    NORMAL_TRADE  — healthy conditions; execute at full risk profile
    FORCED_TRADE  — marginal conditions; execute with reduced risk (65% size,
                    80% TP distance) so the trade still fires but capital
                    exposure is contained
    SKIP_CYCLE    — conditions are too poor; do not open a new position this
                    cycle (protects capital)

Decision inputs (all per-symbol)
---------------------------------
    atr_pct            ATR as a fraction of current price (e.g. 0.02 = 2 %)
    spread_pct         Bid-ask spread as a fraction of price (e.g. 0.001 = 0.1 %)
    win_rate           Rolling win rate 0-1 from WinRateStabilizer (or 0.5 fallback)
    zero_signal_streak Consecutive cycles with no signal (starvation indicator)
    position_cap_reached True when position cap is already full

Decision logic (evaluated top-to-bottom; first match wins)
------------------------------------------------------------
    SKIP  if position_cap_reached          — no room for another trade
    SKIP  if win_rate < WR_MIN             — capital protection floor
    SKIP  if spread_pct > SPREAD_HIGH      — cost destroys edge
    SKIP  if atr_pct < VOL_LOW             — dead / no-momentum market
    FORCE if win_rate < WR_FORCE           — weak but above floor → cautious
    FORCE if atr_pct > VOL_HIGH            — unusually volatile → reduce size
    FORCE if zero_signal_streak ≥ STREAK   — starvation → cautious entry
    NORMAL for everything else             — green-light full execution

Environment overrides
---------------------
    SEL_VOL_HIGH     float  ATR% threshold for "high volatility" (default 0.04)
    SEL_VOL_LOW      float  ATR% threshold for "dead market"      (default 0.005)
    SEL_SPREAD_HIGH  float  Spread% threshold for "expensive"     (default 0.003)
    SEL_WR_MIN       float  Win-rate capital-protection floor      (default 0.30)
    SEL_WR_FORCE     float  Win-rate forced-trade ceiling          (default 0.45)
    SEL_STREAK       int    Starvation streak threshold            (default 5)

FORCED_TRADE risk profile
--------------------------
    position_size_multiplier  = 0.65   (35% smaller than normal)
    tp_distance_multiplier    = 0.80   (20% tighter take-profit)

These multipliers are applied *on top of* any WinRateStabilizer adjustments
already applied earlier in the pipeline; the SEL is the final capital-control
gate before execution.

Thread safety
-------------
SmartExecutionLayer itself is stateless per-call so no locking is required
beyond the constructor, but the singleton factory uses a lock for safety.

Usage
-----
::

    from bot.smart_execution_layer import get_smart_execution_layer, ExecutionMode

    sel    = get_smart_execution_layer()
    wrs    = get_win_rate_stabilizer()
    win_rate = wrs.get_win_rate()

    decision = sel.evaluate(
        atr_pct=0.018,
        spread_pct=0.0008,
        win_rate=win_rate,
        zero_signal_streak=self._zero_signal_streak,
        position_cap_reached=managing_only,
    )

    if decision.mode == ExecutionMode.SKIP_CYCLE:
        continue          # skip this symbol

    if decision.mode == ExecutionMode.FORCED_TRADE:
        position_size *= decision.position_size_multiplier
        # TP tightened in the WRS TP/SL hook that follows
"""

from __future__ import annotations

import logging
import os
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Optional

logger = logging.getLogger("nija.smart_execution_layer")


# ---------------------------------------------------------------------------
# Configuration (env-overridable)
# ---------------------------------------------------------------------------

def _env_float(key: str, default: float) -> float:
    try:
        return float(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


def _env_int(key: str, default: int) -> int:
    try:
        return int(os.getenv(key, str(default)))
    except (ValueError, TypeError):
        return default


_VOL_HIGH:    float = _env_float("SEL_VOL_HIGH",    0.04)   # ATR% > 4%   → high vol
_VOL_LOW:     float = _env_float("SEL_VOL_LOW",     0.005)  # ATR% < 0.5% → dead
_SPREAD_HIGH: float = _env_float("SEL_SPREAD_HIGH", 0.003)  # spread > 0.3% → expensive
_WR_MIN:      float = _env_float("SEL_WR_MIN",      0.30)   # wr < 30%    → skip
_WR_FORCE:    float = _env_float("SEL_WR_FORCE",    0.45)   # wr < 45%    → forced
_STREAK:      int   = _env_int("SEL_STREAK",        5)      # starvation streak

# Risk profiles per mode
_FORCED_SIZE_MULT: float = 0.65   # position size at 65% of normal
_FORCED_TP_MULT:   float = 0.80   # TP distance at 80% of normal


# ---------------------------------------------------------------------------
# Enums and dataclasses
# ---------------------------------------------------------------------------

class ExecutionMode(str, Enum):
    """The three possible outcomes from SmartExecutionLayer.evaluate()."""
    NORMAL_TRADE = "NORMAL_TRADE"
    FORCED_TRADE = "FORCED_TRADE"
    SKIP_CYCLE   = "SKIP_CYCLE"


@dataclass(frozen=True)
class ExecutionDecision:
    """
    Result of a single call to ``SmartExecutionLayer.evaluate()``.

    Attributes:
        mode:                     NORMAL_TRADE, FORCED_TRADE, or SKIP_CYCLE.
        reason:                   Human-readable explanation (for logs).
        position_size_multiplier: 1.00 for NORMAL, 0.65 for FORCED, 0.0 for SKIP.
        tp_distance_multiplier:   1.00 for NORMAL, 0.80 for FORCED, 0.0 for SKIP.
        skip:                     True when mode == SKIP_CYCLE (convenience flag).
        forced:                   True when mode == FORCED_TRADE.
    """
    mode: ExecutionMode
    reason: str
    position_size_multiplier: float
    tp_distance_multiplier: float

    @property
    def skip(self) -> bool:
        return self.mode == ExecutionMode.SKIP_CYCLE

    @property
    def forced(self) -> bool:
        return self.mode == ExecutionMode.FORCED_TRADE

    @property
    def normal(self) -> bool:
        return self.mode == ExecutionMode.NORMAL_TRADE


# Pre-built normal decision (avoids repeated object creation in hot path)
_NORMAL = ExecutionDecision(
    mode=ExecutionMode.NORMAL_TRADE,
    reason="",
    position_size_multiplier=1.00,
    tp_distance_multiplier=1.00,
)


def _skip(reason: str) -> ExecutionDecision:
    return ExecutionDecision(
        mode=ExecutionMode.SKIP_CYCLE,
        reason=reason,
        position_size_multiplier=0.00,
        tp_distance_multiplier=0.00,
    )


def _force(reason: str) -> ExecutionDecision:
    return ExecutionDecision(
        mode=ExecutionMode.FORCED_TRADE,
        reason=reason,
        position_size_multiplier=_FORCED_SIZE_MULT,
        tp_distance_multiplier=_FORCED_TP_MULT,
    )


def _normal(reason: str) -> ExecutionDecision:
    return ExecutionDecision(
        mode=ExecutionMode.NORMAL_TRADE,
        reason=reason,
        position_size_multiplier=1.00,
        tp_distance_multiplier=1.00,
    )


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

class SmartExecutionLayer:
    """
    Per-signal execution mode selector.

    Stateless per-call — all inputs are provided on each ``evaluate()`` call
    so the layer can be re-used across cycles without any reset.
    """

    def __init__(self) -> None:
        logger.info(
            "⚡ SmartExecutionLayer initialised — "
            "vol_high=%.1f%% vol_low=%.2f%% spread_high=%.2f%% "
            "wr_min=%.0f%% wr_force=%.0f%% starvation_streak=%d",
            _VOL_HIGH * 100,
            _VOL_LOW * 100,
            _SPREAD_HIGH * 100,
            _WR_MIN * 100,
            _WR_FORCE * 100,
            _STREAK,
        )

    def evaluate(
        self,
        *,
        atr_pct: float,
        spread_pct: float,
        win_rate: float,
        zero_signal_streak: int = 0,
        position_cap_reached: bool = False,
    ) -> ExecutionDecision:
        """
        Evaluate market conditions and return an execution mode decision.

        Args:
            atr_pct:              ATR as a fraction of current close price.
            spread_pct:           Bid-ask spread as a fraction of current price.
            win_rate:             Rolling win rate 0.0–1.0 (use 0.5 when unknown).
            zero_signal_streak:   Consecutive cycles with no qualifying signal.
            position_cap_reached: True when max positions already held.

        Returns:
            ExecutionDecision with mode, reason, and risk multipliers.
        """
        # ── SKIP conditions (top priority) ───────────────────────────────────

        # 1. Position cap — no room; forced trades cannot override the cap.
        if position_cap_reached:
            return _skip("position_cap_reached — no room for new entries")

        # 2. Win rate below capital-protection floor.
        if win_rate < _WR_MIN:
            return _skip(
                f"win_rate {win_rate:.0%} < floor {_WR_MIN:.0%} — capital protection"
            )

        # 3. Spread too wide — cost of entry exceeds edge.
        if spread_pct > _SPREAD_HIGH:
            return _skip(
                f"spread {spread_pct:.3%} > {_SPREAD_HIGH:.3%} — edge destroyed by cost"
            )

        # 4. Volatility too low — no momentum, stale order-book risk.
        if atr_pct < _VOL_LOW:
            return _skip(
                f"atr {atr_pct:.3%} < {_VOL_LOW:.3%} — dead market / no momentum"
            )

        # ── FORCED conditions ─────────────────────────────────────────────────

        forced_reasons = []

        # 5. Win rate is marginal — above floor but below healthy threshold.
        if win_rate < _WR_FORCE:
            forced_reasons.append(
                f"wr={win_rate:.0%} (marginal, below {_WR_FORCE:.0%} healthy floor)"
            )

        # 6. Volatility unusually high — valid signal but higher variance.
        if atr_pct > _VOL_HIGH:
            forced_reasons.append(
                f"atr={atr_pct:.2%} (elevated, above {_VOL_HIGH:.0%} high-vol threshold)"
            )

        # 7. Signal starvation — bot has been dry for too many cycles.
        if zero_signal_streak >= _STREAK:
            forced_reasons.append(
                f"starvation streak={zero_signal_streak} ≥ {_STREAK}"
            )

        if forced_reasons:
            return _force(" | ".join(forced_reasons))

        # ── NORMAL trade ─────────────────────────────────────────────────────
        return _normal(
            f"healthy — wr={win_rate:.0%} atr={atr_pct:.2%} spread={spread_pct:.3%}"
        )

    def get_report(self) -> dict:
        """Return a JSON-serialisable configuration summary for logging / APIs."""
        return {
            "vol_high_pct": _VOL_HIGH * 100,
            "vol_low_pct": _VOL_LOW * 100,
            "spread_high_pct": _SPREAD_HIGH * 100,
            "wr_min_pct": _WR_MIN * 100,
            "wr_force_pct": _WR_FORCE * 100,
            "starvation_streak_threshold": _STREAK,
            "forced_position_size_multiplier": _FORCED_SIZE_MULT,
            "forced_tp_distance_multiplier": _FORCED_TP_MULT,
        }


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_singleton: Optional[SmartExecutionLayer] = None
_singleton_lock = threading.Lock()


def get_smart_execution_layer() -> SmartExecutionLayer:
    """Return (or create) the module-level singleton ``SmartExecutionLayer``."""
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = SmartExecutionLayer()
        return _singleton
