"""
NIJA Phase 3 — Partial Take-Profit Ladder
===========================================

Systematic multi-level profit-taking for open positions.  Rather than closing
a full position at a single target, the ladder exits in defined tranches at
increasing profit thresholds, locking in gains while keeping a "runner" alive.

Default ladder (all thresholds measured as % profit from entry)
----------------------------------------------------------------
::

    TP1  +1.5 % → exit 25 % of position, move stop to breakeven
    TP2  +3.0 % → exit 25 % more (50 % total out)
    TP3  +5.0 % → exit 25 % more (75 % total out)
    TP4  +8.0 % → exit remaining 25 % (full close — runner captured)

All levels are configurable.  The ladder remembers which levels have already
been triggered so repeated calls on the same bar never double-exit.

Usage
-----
::

    from bot.partial_tp_ladder import get_partial_tp_ladder, TakeAction

    ladder = get_partial_tp_ladder()

    # Register a new position at entry
    ladder.register_position("ETH-456", entry_price=3_200.0, side="long",
                             total_size=1.0)

    # On each bar / tick — call update() to get the next action (if any)
    action = ladder.update("ETH-456", current_price=3_350.0)
    if action:
        # action.exit_pct is the fraction of the original size to close now
        execute_partial_exit(symbol, size * action.exit_pct, action.label)

Author: NIJA Trading Systems
Version: 1.0 — Phase 3
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.partial_tp_ladder")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class TPLevel:
    """A single rung on the take-profit ladder."""
    profit_pct: float   # % profit from entry that triggers this level
    exit_pct: float     # fraction of the *original* total size to exit
    move_stop_to_be: bool = False  # True → move stop to breakeven after this level
    label: str = ""

    def __post_init__(self) -> None:
        if not self.label:
            self.label = f"TP{self.profit_pct:.1f}%"


@dataclass
class LadderConfig:
    """Full configuration for the partial TP ladder."""

    levels: List[TPLevel] = field(default_factory=lambda: [
        TPLevel(profit_pct=1.5, exit_pct=0.25, move_stop_to_be=True,  label="TP1"),
        TPLevel(profit_pct=3.0, exit_pct=0.25, move_stop_to_be=False, label="TP2"),
        TPLevel(profit_pct=5.0, exit_pct=0.25, move_stop_to_be=False, label="TP3"),
        TPLevel(profit_pct=8.0, exit_pct=0.25, move_stop_to_be=False, label="TP4"),
    ])

    # If True, fire only ONE level per update() call (one exit per bar/tick).
    # If False, fire all triggered levels that haven't been taken yet.
    one_per_call: bool = True


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------

@dataclass
class TakeAction:
    """Instruction returned when a TP level fires."""
    position_id: str
    label: str          # "TP1", "TP2", …
    profit_pct: float   # realised profit % at this trigger
    exit_pct: float     # fraction of *original* position to close now
    move_stop_to_be: bool
    entry_price: float
    trigger_price: float
    levels_remaining: int  # how many TP levels are still pending


@dataclass
class LadderStatus:
    position_id: str
    entry_price: float
    side: str
    levels_taken: List[str]
    levels_pending: List[str]
    remaining_position_pct: float  # fraction of original size still open (0–1)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class PartialTPLadder:
    """
    Multi-level take-profit ladder with per-position state tracking.

    Thread-safe.
    """

    def __init__(self, config: Optional[LadderConfig] = None) -> None:
        self._config = config or LadderConfig()
        self._lock = threading.Lock()
        # position_id → state dict
        self._positions: Dict[str, Dict] = {}

        logger.info(
            "✅ PartialTPLadder initialised — %d levels: %s",
            len(self._config.levels),
            ", ".join(f"{lvl.label}@{lvl.profit_pct}%" for lvl in self._config.levels),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_position(
        self,
        position_id: str,
        entry_price: float,
        side: str,
        total_size: float = 1.0,
    ) -> None:
        """Register a position so the ladder can track it."""
        with self._lock:
            self._positions[position_id] = {
                "entry": entry_price,
                "side": side.lower(),
                "total_size": total_size,
                "remaining_pct": 1.0,   # 100% still open
                "levels_taken": set(),
            }
            logger.debug(
                "📋 PartialTPLadder registered %s  entry=%.4f  side=%s",
                position_id, entry_price, side,
            )

    def update(
        self,
        position_id: str,
        current_price: float,
        entry_price: Optional[float] = None,
        side: Optional[str] = None,
    ) -> Optional[TakeAction]:
        """
        Check whether a TP level should fire for the given position.

        Auto-registers on first call if ``entry_price`` and ``side`` are given.

        Returns a :class:`TakeAction` if a level fires, or ``None`` if no
        action is needed.  The caller is responsible for actually executing
        the partial exit.
        """
        with self._lock:
            # Auto-register
            if position_id not in self._positions:
                if entry_price is None or side is None:
                    raise ValueError(
                        f"Position {position_id!r} not registered. "
                        "Provide entry_price and side on the first call."
                    )
                self._positions[position_id] = {
                    "entry": entry_price,
                    "side": side.lower(),
                    "total_size": 1.0,
                    "remaining_pct": 1.0,
                    "levels_taken": set(),
                }

            pos = self._positions[position_id]
            entry = pos["entry"]
            pos_side = pos["side"]

            # Profit % from entry
            if pos_side == "long":
                profit_pct = (current_price - entry) / entry * 100.0
            else:
                profit_pct = (entry - current_price) / entry * 100.0

            # Check levels in ascending order
            for lvl in sorted(self._config.levels, key=lambda x: x.profit_pct):
                if lvl.label in pos["levels_taken"]:
                    continue  # already fired
                if profit_pct >= lvl.profit_pct and pos["remaining_pct"] > 0:
                    # Fire this level
                    pos["levels_taken"].add(lvl.label)
                    pos["remaining_pct"] = max(
                        0.0, pos["remaining_pct"] - lvl.exit_pct
                    )

                    pending = [
                        l.label
                        for l in self._config.levels
                        if l.label not in pos["levels_taken"]
                    ]

                    logger.info(
                        "💰 %s — %s triggered at %.4f  (+%.2f%%)  "
                        "exit %.0f%% of original  remaining=%.0f%%",
                        position_id, lvl.label, current_price, profit_pct,
                        lvl.exit_pct * 100, pos["remaining_pct"] * 100,
                    )

                    action = TakeAction(
                        position_id=position_id,
                        label=lvl.label,
                        profit_pct=profit_pct,
                        exit_pct=lvl.exit_pct,
                        move_stop_to_be=lvl.move_stop_to_be,
                        entry_price=entry,
                        trigger_price=current_price,
                        levels_remaining=len(pending),
                    )

                    if self._config.one_per_call:
                        return action
                    # Otherwise keep iterating (rare — fast multi-level move)

        return None

    def remove_position(self, position_id: str) -> None:
        """Remove a fully closed position from tracking."""
        with self._lock:
            self._positions.pop(position_id, None)

    def get_status(self, position_id: str) -> Optional[LadderStatus]:
        """Return ladder status for one position, or None if not tracked."""
        with self._lock:
            pos = self._positions.get(position_id)
            if pos is None:
                return None
            taken = sorted(pos["levels_taken"])
            pending = [
                lvl.label
                for lvl in self._config.levels
                if lvl.label not in pos["levels_taken"]
            ]
            return LadderStatus(
                position_id=position_id,
                entry_price=pos["entry"],
                side=pos["side"],
                levels_taken=taken,
                levels_pending=pending,
                remaining_position_pct=pos["remaining_pct"],
            )

    def reset_position(self, position_id: str) -> None:
        """Reset a position's ladder state (e.g. after re-entry)."""
        with self._lock:
            if position_id in self._positions:
                self._positions[position_id]["levels_taken"] = set()
                self._positions[position_id]["remaining_pct"] = 1.0


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[PartialTPLadder] = None
_instance_lock = threading.Lock()


def get_partial_tp_ladder(
    config: Optional[LadderConfig] = None,
) -> PartialTPLadder:
    """Return the process-wide singleton PartialTPLadder."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = PartialTPLadder(config=config)
    return _instance
