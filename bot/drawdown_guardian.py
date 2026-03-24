"""
NIJA Drawdown Guardian
=======================

Per-strategy / per-account drawdown protection with three escalating
protection levels and automatic recovery logic.

This module is distinct from the system-wide ``GlobalDrawdownCircuitBreaker``.
While the circuit breaker guards total portfolio equity, the Drawdown Guardian
watches a single strategy's or account's equity and applies targeted trading
restrictions.

Protection levels
-----------------
::

  HEALTHY    0 –  5 % drawdown  →  100 % sizing  | all entries allowed
  CAUTION    5 – 10 % drawdown  →   70 % sizing  | entries tightened
  DANGER    10 – 15 % drawdown  →   50 % sizing  | entries further restricted
  HALTED       > 15 % drawdown  →    0 % sizing  | entries BLOCKED

Recovery
--------
The guardian steps up one level at a time when **both** conditions hold:

  1. Account equity recovers by at least ``recovery_pct`` (default 1 %) above
     the lowest equity recorded since the level was triggered.
  2. At least ``recovery_wins`` (default 3) consecutive profitable trades have
     been recorded since the level was set.
  3. For ``HALTED`` only: a minimum cool-down of ``halt_min_minutes`` (default
     30 min) must also have elapsed.

Singleton usage
---------------
::

    from bot.drawdown_guardian import get_drawdown_guardian

    guardian = get_drawdown_guardian()
    guardian.update_equity(current_equity=9_200.0, peak_equity=10_000.0)

    decision = guardian.check()
    if not decision.allow_entries:
        skip_entry()
    else:
        position_size *= decision.size_multiplier
        ...

    # After every completed trade:
    guardian.record_trade(pnl=42.0, is_win=True)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.drawdown_guardian")


# ---------------------------------------------------------------------------
# Protection levels
# ---------------------------------------------------------------------------

class GuardianLevel(str, Enum):
    HEALTHY = "HEALTHY"   # 0 –  5 % — normal operation
    CAUTION = "CAUTION"   # 5 – 10 % — moderate restriction
    DANGER  = "DANGER"    # 10 – 15 % — severe restriction
    HALTED  = "HALTED"    # > 15 %   — all entries blocked


# Level → (size_multiplier, entries_allowed, emoji_label)
_LEVEL_PARAMS: Dict[GuardianLevel, tuple] = {
    GuardianLevel.HEALTHY: (1.00, True,  "🟢 Healthy — normal operation"),
    GuardianLevel.CAUTION: (0.70, True,  "🟡 Caution — size reduced 30 %"),
    GuardianLevel.DANGER:  (0.50, True,  "🟠 Danger  — size halved"),
    GuardianLevel.HALTED:  (0.00, False, "🔴 HALTED  — entries blocked"),
}

# Ordered list of levels used for level-order comparisons
_LEVEL_ORDER: Dict[GuardianLevel, int] = {
    GuardianLevel.HEALTHY: 0,
    GuardianLevel.CAUTION: 1,
    GuardianLevel.DANGER:  2,
    GuardianLevel.HALTED:  3,
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class GuardianConfig:
    """Configurable thresholds for the Drawdown Guardian."""

    # Drawdown thresholds (fractions, not percentages)
    caution_pct: float = 0.05    # 5 %  drawdown → CAUTION
    danger_pct: float  = 0.10    # 10 % drawdown → DANGER
    halt_pct: float    = 0.15    # 15 % drawdown → HALTED

    # Recovery conditions
    recovery_pct: float = 0.01   # equity must recover ≥ 1 % above trough
    recovery_wins: int  = 3      # consecutive wins needed to step up

    # HALTED-specific cool-down before recovery can begin
    halt_min_minutes: float = 30.0


@dataclass
class GuardianDecision:
    """Result returned by :meth:`DrawdownGuardian.check` and :meth:`update_equity`."""

    level: GuardianLevel
    allow_entries: bool
    size_multiplier: float
    drawdown_pct: float
    label: str
    consecutive_wins: int
    wins_needed: int
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level.value,
            "label": self.label,
            "allow_entries": self.allow_entries,
            "size_multiplier": round(self.size_multiplier, 4),
            "drawdown_pct": round(self.drawdown_pct * 100, 2),
            "recovery": {
                "consecutive_wins": self.consecutive_wins,
                "wins_needed": self.wins_needed,
                "progress_pct": round(
                    min(100.0, self.consecutive_wins / max(1, self.wins_needed) * 100), 1
                ),
            },
            "timestamp": self.timestamp.isoformat(),
        }


# ---------------------------------------------------------------------------
# Core guardian
# ---------------------------------------------------------------------------

class DrawdownGuardian:
    """
    Per-account / per-strategy drawdown protection with staged restrictions
    and automatic recovery.

    Thread-safe; use the singleton accessor :func:`get_drawdown_guardian`
    for shared state across the bot.
    """

    def __init__(self, config: Optional[GuardianConfig] = None) -> None:
        self._cfg = config or GuardianConfig()
        self._lock = threading.Lock()

        # Equity state
        self._peak_equity: float = 0.0
        self._current_equity: float = 0.0
        self._trough_equity: float = float("inf")  # lowest since last level trigger
        self._drawdown_pct: float = 0.0

        # Protection-level state
        self._level: GuardianLevel = GuardianLevel.HEALTHY
        self._level_triggered_at: Optional[datetime] = None

        # Recovery tracking
        self._consecutive_wins: int = 0
        self._total_trades: int = 0

        logger.info(
            "DrawdownGuardian initialised | caution=%.0f%% danger=%.0f%% halt=%.0f%%",
            self._cfg.caution_pct * 100,
            self._cfg.danger_pct * 100,
            self._cfg.halt_pct * 100,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_equity(
        self,
        current_equity: float,
        peak_equity: Optional[float] = None,
    ) -> GuardianDecision:
        """
        Feed the latest equity value.

        Parameters
        ----------
        current_equity:
            Latest account balance / NAV in USD.
        peak_equity:
            Known all-time high equity.  If ``None``, the guardian maintains
            its own running peak.
        """
        with self._lock:
            self._current_equity = current_equity

            if peak_equity is not None:
                self._peak_equity = max(self._peak_equity, peak_equity)
            elif current_equity > self._peak_equity:
                self._peak_equity = current_equity

            if current_equity < self._trough_equity:
                self._trough_equity = current_equity

            self._drawdown_pct = self._compute_drawdown()

            old_level = self._level
            new_level = self._classify_level(self._drawdown_pct)

            if new_level != old_level:
                self._on_level_change(old_level, new_level)

            return self._build_decision()

    def check(self) -> GuardianDecision:
        """Return the current guardian decision without updating equity."""
        with self._lock:
            return self._build_decision()

    def record_trade(self, pnl: float, is_win: bool) -> None:
        """
        Record a completed trade outcome to drive recovery logic.

        A loss resets the consecutive-win streak.  When the streak reaches
        ``recovery_wins`` and equity has recovered sufficiently, the guardian
        will automatically step up one protection level.
        """
        with self._lock:
            self._total_trades += 1

            if is_win:
                self._consecutive_wins += 1
            else:
                self._consecutive_wins = 0

            if self._level != GuardianLevel.HEALTHY:
                self._try_recover()

    def reset(self) -> None:
        """Manually reset the guardian to HEALTHY.  Use with caution."""
        with self._lock:
            old = self._level
            self._level = GuardianLevel.HEALTHY
            self._consecutive_wins = 0
            self._trough_equity = float("inf")
            self._level_triggered_at = None
            logger.warning(
                "DrawdownGuardian manually reset from %s → HEALTHY", old.value
            )

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def level(self) -> GuardianLevel:
        """Current protection level."""
        with self._lock:
            return self._level

    @property
    def drawdown_pct(self) -> float:
        """Current drawdown fraction (0.0 – 1.0)."""
        with self._lock:
            return self._drawdown_pct

    @property
    def is_halted(self) -> bool:
        """``True`` when entries are completely blocked."""
        with self._lock:
            return self._level == GuardianLevel.HALTED

    @property
    def size_multiplier(self) -> float:
        """Position-size scaling factor for the current level."""
        with self._lock:
            return _LEVEL_PARAMS[self._level][0]

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_report(self) -> Dict[str, Any]:
        """Return a serialisable status snapshot."""
        with self._lock:
            mult, allow, label = _LEVEL_PARAMS[self._level]
            wins_needed = max(0, self._cfg.recovery_wins - self._consecutive_wins)
            trough = (
                self._trough_equity
                if self._trough_equity != float("inf")
                else self._current_equity
            )
            return {
                "level": self._level.value,
                "label": label,
                "drawdown_pct": round(self._drawdown_pct * 100, 2),
                "peak_equity_usd": round(self._peak_equity, 2),
                "current_equity_usd": round(self._current_equity, 2),
                "trough_equity_usd": round(trough, 2),
                "size_multiplier": mult,
                "allow_entries": allow,
                "recovery": {
                    "consecutive_wins": self._consecutive_wins,
                    "wins_needed": wins_needed,
                    "progress_pct": round(
                        min(100.0, self._consecutive_wins / max(1, self._cfg.recovery_wins) * 100), 1
                    ),
                },
                "total_trades_recorded": self._total_trades,
                "config": {
                    "caution_pct": self._cfg.caution_pct * 100,
                    "danger_pct": self._cfg.danger_pct * 100,
                    "halt_pct": self._cfg.halt_pct * 100,
                    "recovery_wins": self._cfg.recovery_wins,
                    "recovery_pct": self._cfg.recovery_pct * 100,
                    "halt_min_minutes": self._cfg.halt_min_minutes,
                },
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_drawdown(self) -> float:
        if self._peak_equity <= 0 or self._current_equity >= self._peak_equity:
            return 0.0
        return (self._peak_equity - self._current_equity) / self._peak_equity

    def _classify_level(self, dd: float) -> GuardianLevel:
        if dd >= self._cfg.halt_pct:
            return GuardianLevel.HALTED
        if dd >= self._cfg.danger_pct:
            return GuardianLevel.DANGER
        if dd >= self._cfg.caution_pct:
            return GuardianLevel.CAUTION
        return GuardianLevel.HEALTHY

    def _on_level_change(
        self, old: GuardianLevel, new: GuardianLevel
    ) -> None:
        self._level = new
        self._level_triggered_at = datetime.utcnow()

        if _LEVEL_ORDER[new] > _LEVEL_ORDER[old]:
            # Escalation — reset streak and trough
            self._consecutive_wins = 0
            self._trough_equity = self._current_equity
            logger.warning(
                "DrawdownGuardian ESCALATED: %s → %s | drawdown=%.1f%%",
                old.value, new.value, self._drawdown_pct * 100,
            )
        else:
            # Recovery step
            logger.info(
                "DrawdownGuardian RECOVERED: %s → %s | drawdown=%.1f%%",
                old.value, new.value, self._drawdown_pct * 100,
            )

    def _try_recover(self) -> None:
        """Attempt to step back one protection level if recovery conditions met."""
        # HALTED: enforce minimum cool-down before any recovery attempt
        if self._level == GuardianLevel.HALTED and self._level_triggered_at is not None:
            elapsed_min = (
                datetime.utcnow() - self._level_triggered_at
            ).total_seconds() / 60.0
            if elapsed_min < self._cfg.halt_min_minutes:
                return

        # Equity must have recovered at least recovery_pct above the trough
        trough = (
            self._trough_equity
            if self._trough_equity != float("inf")
            else self._current_equity
        )
        equity_recovered = (
            self._current_equity >= trough * (1.0 + self._cfg.recovery_pct)
        )

        # Win streak must have reached the required count
        streak_ok = self._consecutive_wins >= self._cfg.recovery_wins

        if not (equity_recovered and streak_ok):
            return

        # Step up one level (not more than one at a time)
        step_map: Dict[GuardianLevel, GuardianLevel] = {
            GuardianLevel.HALTED:  GuardianLevel.DANGER,
            GuardianLevel.DANGER:  GuardianLevel.CAUTION,
            GuardianLevel.CAUTION: GuardianLevel.HEALTHY,
        }
        next_level = step_map.get(self._level)
        if next_level is None:
            return

        # Only allow stepping up if the actual drawdown does not currently
        # require a level MORE severe than the current one (hysteresis — the
        # win streak and equity bounce together justify one step of leniency).
        required = self._classify_level(self._drawdown_pct)
        if _LEVEL_ORDER[required] <= _LEVEL_ORDER[self._level]:
            self._on_level_change(self._level, next_level)
            # Reset streak so another X wins are needed for the next step
            self._consecutive_wins = 0

    def _build_decision(self) -> GuardianDecision:
        mult, allow, label = _LEVEL_PARAMS[self._level]
        wins_needed = max(0, self._cfg.recovery_wins - self._consecutive_wins)
        return GuardianDecision(
            level=self._level,
            allow_entries=allow,
            size_multiplier=mult,
            drawdown_pct=self._drawdown_pct,
            label=label,
            consecutive_wins=self._consecutive_wins,
            wins_needed=wins_needed,
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_GUARDIAN_INSTANCE: Optional[DrawdownGuardian] = None
_GUARDIAN_LOCK = threading.Lock()


def get_drawdown_guardian(
    config: Optional[GuardianConfig] = None,
) -> DrawdownGuardian:
    """
    Return the process-wide :class:`DrawdownGuardian` singleton.

    ``config`` is only applied on the first call; subsequent calls return the
    existing instance regardless of the arguments passed.
    """
    global _GUARDIAN_INSTANCE
    with _GUARDIAN_LOCK:
        if _GUARDIAN_INSTANCE is None:
            _GUARDIAN_INSTANCE = DrawdownGuardian(config)
    return _GUARDIAN_INSTANCE


__all__ = [
    "GuardianConfig",
    "GuardianDecision",
    "GuardianLevel",
    "DrawdownGuardian",
    "get_drawdown_guardian",
]
