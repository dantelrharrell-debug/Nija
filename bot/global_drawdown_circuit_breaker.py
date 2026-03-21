"""
NIJA Global Drawdown Circuit Breaker
======================================

A **system-wide** drawdown halt that monitors aggregate account equity and
triggers progressively tighter trading restrictions when peak-to-trough
drawdown exceeds configured thresholds.

Unlike per-strategy drawdown guards, this module watches the **total
portfolio equity** and acts as the final override layer — no individual
strategy can bypass it.

Protection levels
-----------------
::

  CLEAR      0 – 5 % drawdown   →  100 % sizing  | entries ✅
  CAUTION    5 – 10 % drawdown  →   75 % sizing  | entries ✅
  WARNING   10 – 15 % drawdown  →   50 % sizing  | entries ✅ (reduced)
  DANGER    15 – 20 % drawdown  →   25 % sizing  | entries ✅ (minimal)
  HALT         > 20 % drawdown  →    0 % sizing  | entries ❌ (full stop)

Recovery (step-down)
--------------------
The circuit breaker steps back one level at a time once:

  1. Equity recovers by at least ``recovery_pct`` from the drawdown low.
  2. At least ``recovery_wins`` consecutive profitable trades are recorded.

Architecture
------------
::

  ┌───────────────────────────────────────────────────────────────────────┐
  │                GlobalDrawdownCircuitBreaker                           │
  │                                                                       │
  │  update_equity(equity_usd)       → CircuitBreakerDecision            │
  │  record_trade(pnl_usd, is_win)   → feeds recovery tracker            │
  │  can_trade()                     → (bool, reason)                    │
  │  get_position_size_multiplier()  → float  [0.0 – 1.0]               │
  │  is_halted()                     → bool                              │
  │  get_report()                    → Dict                              │
  └───────────────────────────────────────────────────────────────────────┘

Usage
-----
::

    from bot.global_drawdown_circuit_breaker import (
        get_global_drawdown_cb, CircuitBreakerDecision
    )

    cb = get_global_drawdown_cb()
    cb.initialise(starting_equity=10_000.0)   # call once at startup

    # Each cycle / after equity refresh:
    decision = cb.update_equity(current_equity=9_200.0)
    if not decision.allow_new_entries:
        block_all_entries()
    position_usd *= decision.position_size_multiplier

    # After a trade closes:
    cb.record_trade(pnl_usd=+120.0, is_win=True)

    # Inline gate (fastest path):
    can, reason = cb.can_trade()
    if not can:
        return  # skip this trade

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

logger = logging.getLogger("nija.global_drawdown_cb")


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class DrawdownCBConfig:
    """Tunable thresholds for the global drawdown circuit breaker."""
    caution_pct: float = 5.0       # % drawdown → CAUTION
    warning_pct: float = 10.0      # % drawdown → WARNING
    danger_pct: float = 15.0       # % drawdown → DANGER
    halt_pct: float = 20.0         # % drawdown → HALT (all entries blocked)
    recovery_pct: float = 3.0      # % equity recovery needed to step up one level
    recovery_wins: int = 3         # Consecutive wins needed alongside recovery_pct


# ---------------------------------------------------------------------------
# Protection levels
# ---------------------------------------------------------------------------

class ProtectionLevel(str, Enum):
    CLEAR = "CLEAR"
    CAUTION = "CAUTION"
    WARNING = "WARNING"
    DANGER = "DANGER"
    HALT = "HALT"

    def position_size_multiplier(self) -> float:
        return {
            "CLEAR":   1.00,
            "CAUTION": 0.75,
            "WARNING": 0.50,
            "DANGER":  0.25,
            "HALT":    0.00,
        }[self.value]

    def allow_new_entries(self) -> bool:
        return self != ProtectionLevel.HALT


# ---------------------------------------------------------------------------
# Decision dataclass
# ---------------------------------------------------------------------------

@dataclass
class CircuitBreakerDecision:
    """Result returned by update_equity() and can_trade()."""
    level: ProtectionLevel
    drawdown_pct: float
    allow_new_entries: bool
    position_size_multiplier: float
    reason: str
    peak_equity: float
    current_equity: float
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------

class GlobalDrawdownCircuitBreaker:
    """
    System-wide drawdown halt with tiered position-size scaling.

    Thread-safe: all public methods acquire ``_lock``.
    """

    def __init__(self, config: Optional[DrawdownCBConfig] = None) -> None:
        self._config = config or DrawdownCBConfig()
        self._lock = threading.Lock()

        self._peak_equity: float = 0.0
        self._current_equity: float = 0.0
        self._low_equity: float = float("inf")     # Lowest equity seen at current level
        self._level: ProtectionLevel = ProtectionLevel.CLEAR
        self._consecutive_wins: int = 0
        self._initialised: bool = False

        # Event log (last 50 decisions)
        self._log: List[Dict] = []

        logger.info("✅ GlobalDrawdownCircuitBreaker initialised")

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def initialise(self, starting_equity: float) -> None:
        """
        Set the baseline (peak) equity at startup.

        Must be called once with the opening account equity before the
        first ``update_equity`` call.  Safe to call again to reset.
        """
        with self._lock:
            self._peak_equity = max(starting_equity, 0.0)
            self._current_equity = self._peak_equity
            self._low_equity = self._peak_equity
            self._level = ProtectionLevel.CLEAR
            self._consecutive_wins = 0
            self._initialised = True
        logger.info(
            "GlobalDrawdownCircuitBreaker: peak equity set to $%.2f",
            starting_equity,
        )

    # ------------------------------------------------------------------
    # Equity update (main entry point)
    # ------------------------------------------------------------------

    def update_equity(self, equity_usd: float) -> CircuitBreakerDecision:
        """
        Record the latest total-portfolio equity and return a decision.

        Automatically updates peak, triggers level escalation, and handles
        step-down recovery.

        Args:
            equity_usd: Current total account equity in USD.

        Returns:
            CircuitBreakerDecision with sizing and entry instructions.
        """
        with self._lock:
            if not self._initialised or self._peak_equity <= 0:
                self._peak_equity = equity_usd
                self._current_equity = equity_usd
                self._low_equity = equity_usd
                self._initialised = True

            self._current_equity = equity_usd

            # Update peak
            if equity_usd > self._peak_equity:
                self._peak_equity = equity_usd

            # Calculate drawdown
            drawdown_pct = self._calc_drawdown_pct()

            # Escalate level (can only move up based on drawdown, never auto-step down here)
            new_level = self._level_from_drawdown(drawdown_pct)
            if self._level_order(new_level) > self._level_order(self._level):
                # Worsening — escalate immediately
                self._level = new_level
                self._low_equity = equity_usd
                self._consecutive_wins = 0
                logger.warning(
                    "⚠️ GlobalDrawdownCircuitBreaker: escalated to %s "
                    "(drawdown=%.2f%%, equity=$%.2f, peak=$%.2f)",
                    new_level.value, drawdown_pct,
                    equity_usd, self._peak_equity,
                )

            # Track new low
            if equity_usd < self._low_equity:
                self._low_equity = equity_usd

            decision = self._build_decision(drawdown_pct)
            self._log.append({
                "ts": decision.timestamp,
                "level": decision.level.value,
                "drawdown_pct": round(drawdown_pct, 2),
                "equity": equity_usd,
            })
            if len(self._log) > 50:
                self._log.pop(0)

        return decision

    # ------------------------------------------------------------------
    # Trade outcome feedback (drives recovery)
    # ------------------------------------------------------------------

    def record_trade(self, pnl_usd: float, is_win: bool) -> None:
        """
        Record a closed trade outcome.  Used to track the consecutive-win
        requirement for level step-down recovery.
        """
        with self._lock:
            if is_win:
                self._consecutive_wins += 1
                self._try_step_down()
            else:
                self._consecutive_wins = 0

    # ------------------------------------------------------------------
    # Query methods
    # ------------------------------------------------------------------

    def can_trade(self) -> Tuple[bool, str]:
        """
        Return ``(allowed, reason)`` — the fast-path gate for trade entry.
        """
        with self._lock:
            level = self._level
            dd = self._calc_drawdown_pct()
        allowed = level.allow_new_entries()
        reason = (
            f"GlobalDrawdownCB: {level.value} — drawdown={dd:.1f}%"
            if not allowed else
            f"GlobalDrawdownCB: {level.value} OK — drawdown={dd:.1f}%"
        )
        return allowed, reason

    def get_position_size_multiplier(self) -> float:
        """Return position-size multiplier ``[0.0 – 1.0]`` for current level."""
        with self._lock:
            return self._level.position_size_multiplier()

    def is_halted(self) -> bool:
        """Return ``True`` when the breaker is at HALT level (all entries blocked)."""
        with self._lock:
            return self._level == ProtectionLevel.HALT

    def get_current_level(self) -> ProtectionLevel:
        """Return the current protection level."""
        with self._lock:
            return self._level

    def get_drawdown_pct(self) -> float:
        """Return the current drawdown percentage."""
        with self._lock:
            return self._calc_drawdown_pct()

    def get_report(self) -> Dict:
        """Return a status dictionary for monitoring / logging."""
        with self._lock:
            dd = self._calc_drawdown_pct()
            level = self._level
            peak = self._peak_equity
            current = self._current_equity
            low = self._low_equity
            wins = self._consecutive_wins
            log = list(self._log[-5:])

        return {
            "level": level.value,
            "drawdown_pct": round(dd, 2),
            "position_size_multiplier": level.position_size_multiplier(),
            "allow_new_entries": level.allow_new_entries(),
            "peak_equity": round(peak, 2),
            "current_equity": round(current, 2),
            "low_equity": round(low, 2),
            "consecutive_wins": wins,
            "recovery_wins_needed": self._config.recovery_wins,
            "recovery_pct_needed": self._config.recovery_pct,
            "thresholds": {
                "caution_pct": self._config.caution_pct,
                "warning_pct": self._config.warning_pct,
                "danger_pct": self._config.danger_pct,
                "halt_pct": self._config.halt_pct,
            },
            "recent_events": log,
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _calc_drawdown_pct(self) -> float:
        """Percentage drawdown from peak (0 when equity >= peak)."""
        if self._peak_equity <= 0:
            return 0.0
        return max(0.0, (self._peak_equity - self._current_equity) / self._peak_equity * 100.0)

    def _level_from_drawdown(self, drawdown_pct: float) -> ProtectionLevel:
        cfg = self._config
        if drawdown_pct >= cfg.halt_pct:
            return ProtectionLevel.HALT
        if drawdown_pct >= cfg.danger_pct:
            return ProtectionLevel.DANGER
        if drawdown_pct >= cfg.warning_pct:
            return ProtectionLevel.WARNING
        if drawdown_pct >= cfg.caution_pct:
            return ProtectionLevel.CAUTION
        return ProtectionLevel.CLEAR

    _LEVEL_ORDER = {
        ProtectionLevel.CLEAR:   0,
        ProtectionLevel.CAUTION: 1,
        ProtectionLevel.WARNING: 2,
        ProtectionLevel.DANGER:  3,
        ProtectionLevel.HALT:    4,
    }

    def _level_order(self, level: ProtectionLevel) -> int:
        return self._LEVEL_ORDER.get(level, 0)

    def _try_step_down(self) -> None:
        """
        Attempt to step down one protection level.

        Requirements:
        * ``_consecutive_wins >= recovery_wins``
        * Equity recovered ``recovery_pct`` from the low at this level.
        """
        if self._level == ProtectionLevel.CLEAR:
            return
        if self._consecutive_wins < self._config.recovery_wins:
            return
        if self._low_equity <= 0:
            return
        recovery_achieved = (
            (self._current_equity - self._low_equity) / self._low_equity * 100.0
        )
        if recovery_achieved < self._config.recovery_pct:
            return

        # Step down one level
        levels = [
            ProtectionLevel.CLEAR,
            ProtectionLevel.CAUTION,
            ProtectionLevel.WARNING,
            ProtectionLevel.DANGER,
            ProtectionLevel.HALT,
        ]
        idx = levels.index(self._level)
        if idx > 0:
            self._level = levels[idx - 1]
            self._consecutive_wins = 0
            self._low_equity = self._current_equity
            logger.info(
                "✅ GlobalDrawdownCircuitBreaker: stepped down to %s "
                "(recovery=%.2f%%, wins=%d)",
                self._level.value, recovery_achieved, self._config.recovery_wins,
            )

    def _build_decision(self, drawdown_pct: float) -> CircuitBreakerDecision:
        return CircuitBreakerDecision(
            level=self._level,
            drawdown_pct=drawdown_pct,
            allow_new_entries=self._level.allow_new_entries(),
            position_size_multiplier=self._level.position_size_multiplier(),
            reason=(
                f"{self._level.value}: drawdown={drawdown_pct:.1f}% "
                f"(peak=${self._peak_equity:.2f}, current=${self._current_equity:.2f})"
            ),
            peak_equity=self._peak_equity,
            current_equity=self._current_equity,
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_cb_instance: Optional[GlobalDrawdownCircuitBreaker] = None
_cb_lock = threading.Lock()


def get_global_drawdown_cb(
    config: Optional[DrawdownCBConfig] = None,
) -> GlobalDrawdownCircuitBreaker:
    """Return the singleton GlobalDrawdownCircuitBreaker."""
    global _cb_instance
    if _cb_instance is None:
        with _cb_lock:
            if _cb_instance is None:
                _cb_instance = GlobalDrawdownCircuitBreaker(config=config)
    return _cb_instance
