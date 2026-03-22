"""
NIJA Phase 3 — Dynamic Stop-Loss Tightener
============================================

Protects "runners" by progressively tightening the stop-loss as a position
moves further in-profit.  The stop only ever moves in the trader's favour
(ratchet mechanic) and never widens once price has advanced past a milestone.

Tightening schedule (configurable)
------------------------------------
::

    Profit ≥ 1 R   → move stop to breakeven (entry price)
    Profit ≥ 2 R   → trail at 40% giveback from peak
    Profit ≥ 3 R   → trail at 30% giveback from peak
    Profit ≥ 5 R   → trail at 20% giveback from peak (very tight)
    Profit ≥ 8 R   → trail at 10% giveback from peak (lock 90%)

``R`` is the initial risk per unit: ``|entry_price − initial_stop_loss|``.

Usage
-----
::

    from bot.dynamic_stop_loss_tightener import get_dynamic_stop_tightener

    tightener = get_dynamic_stop_tightener()

    # On each bar / tick:
    result = tightener.update(
        position_id="BTC-123",
        current_price=105_000.0,
        entry_price=100_000.0,
        initial_stop=98_000.0,   # initial hard stop set at entry
        side="long",
    )
    print(result.new_stop, result.reason)

Author: NIJA Trading Systems
Version: 1.0 — Phase 3
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.dynamic_stop_loss_tightener")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class TightenerConfig:
    """Configures the dynamic stop-loss tightening schedule."""

    # Each tuple: (R-multiple threshold, max giveback fraction from peak)
    # Giveback fraction = how much of peak unrealised profit we allow back
    # before stopping out.  0.40 → allow 40% giveback; 0.10 → allow 10%.
    tightening_schedule: List[Tuple[float, float]] = field(default_factory=lambda: [
        (1.0, None),    # ≥ 1R  → move stop to breakeven (no giveback yet)
        (2.0, 0.40),    # ≥ 2R  → trail at 40% giveback from peak
        (3.0, 0.30),    # ≥ 3R  → trail at 30% giveback
        (5.0, 0.20),    # ≥ 5R  → trail at 20% giveback
        (8.0, 0.10),    # ≥ 8R  → trail at 10% giveback (lock 90%)
    ])

    # Minimum distance (as % of entry price) between new stop and current price.
    # Prevents the stop from being placed right at the market during fast moves.
    min_stop_distance_pct: float = 0.002  # 0.2%

    # Once the stop is set to breakeven it is never moved back below entry again.
    enforce_breakeven_floor: bool = True


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class StopUpdateResult:
    position_id: str
    old_stop: float
    new_stop: float
    r_multiple: float
    peak_price: float
    tightening_stage: str
    reason: str
    stop_moved: bool


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class DynamicStopLossTightener:
    """
    Progressive stop-loss tightening engine that protects running winners.

    Thread-safe via per-position locking.
    """

    def __init__(self, config: Optional[TightenerConfig] = None) -> None:
        self._config = config or TightenerConfig()
        self._lock = threading.Lock()

        # Keyed by position_id
        # value: {'entry': float, 'initial_stop': float, 'side': str,
        #         'current_stop': float, 'peak_price': float,
        #         'stage': str, 'breakeven_set': bool}
        self._positions: Dict[str, Dict] = {}

        logger.info(
            "✅ DynamicStopLossTightener initialised — %d tightening stages",
            len(self._config.tightening_schedule),
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_position(
        self,
        position_id: str,
        entry_price: float,
        initial_stop: float,
        side: str,
    ) -> None:
        """Register a newly opened position for stop tracking."""
        with self._lock:
            self._positions[position_id] = {
                "entry": entry_price,
                "initial_stop": initial_stop,
                "side": side.lower(),
                "current_stop": initial_stop,
                "peak_price": entry_price,
                "stage": "initial",
                "breakeven_set": False,
            }
            logger.debug(
                "📋 Registered position %s  entry=%.4f  stop=%.4f  side=%s",
                position_id, entry_price, initial_stop, side,
            )

    def update(
        self,
        position_id: str,
        current_price: float,
        entry_price: Optional[float] = None,
        initial_stop: Optional[float] = None,
        side: Optional[str] = None,
    ) -> StopUpdateResult:
        """
        Calculate the tightened stop for a position.

        Auto-registers the position on the first call if ``entry_price``,
        ``initial_stop``, and ``side`` are provided and the position is unknown.

        Returns a :class:`StopUpdateResult` — callers should apply
        ``result.new_stop`` to their position if ``result.stop_moved`` is True.
        """
        with self._lock:
            # Auto-register
            if position_id not in self._positions:
                if entry_price is None or initial_stop is None or side is None:
                    raise ValueError(
                        f"Position {position_id!r} not registered; supply "
                        "entry_price, initial_stop and side on first call."
                    )
                self._positions[position_id] = {
                    "entry": entry_price,
                    "initial_stop": initial_stop,
                    "side": side.lower(),
                    "current_stop": initial_stop,
                    "peak_price": entry_price,
                    "stage": "initial",
                    "breakeven_set": False,
                }

            pos = self._positions[position_id]
            old_stop = pos["current_stop"]
            entry = pos["entry"]
            init_stop = pos["initial_stop"]
            pos_side = pos["side"]

            # Update peak price
            if pos_side == "long":
                if current_price > pos["peak_price"]:
                    pos["peak_price"] = current_price
            else:
                if current_price < pos["peak_price"]:
                    pos["peak_price"] = current_price

            peak = pos["peak_price"]

            # Initial risk per unit (always positive)
            initial_risk = abs(entry - init_stop)
            if initial_risk == 0:
                return StopUpdateResult(
                    position_id=position_id,
                    old_stop=old_stop,
                    new_stop=old_stop,
                    r_multiple=0.0,
                    peak_price=peak,
                    tightening_stage=pos["stage"],
                    reason="zero initial risk — no adjustment",
                    stop_moved=False,
                )

            # Current unrealised profit per unit
            if pos_side == "long":
                unrealised = current_price - entry
            else:
                unrealised = entry - current_price

            r_multiple = unrealised / initial_risk

            # Determine applicable tightening stage
            new_stop = old_stop
            stage = pos["stage"]
            reason = "no change"

            sorted_schedule = sorted(
                self._config.tightening_schedule, key=lambda x: x[0], reverse=True
            )

            for r_threshold, giveback_frac in sorted_schedule:
                if r_multiple >= r_threshold:
                    if giveback_frac is None:
                        # Breakeven stage
                        if not pos["breakeven_set"]:
                            candidate = entry
                            new_stop = self._apply_direction(
                                pos_side, old_stop, candidate, current_price
                            )
                            if new_stop != old_stop:
                                pos["breakeven_set"] = True
                                stage = f"breakeven (≥{r_threshold}R)"
                                reason = (
                                    f"Breakeven stop at entry {entry:.4f} "
                                    f"(profit={r_multiple:.2f}R)"
                                )
                    else:
                        # Trailing giveback stage
                        if pos_side == "long":
                            profit_at_peak = peak - entry
                            giveback_amount = profit_at_peak * giveback_frac
                            candidate = peak - giveback_amount
                        else:
                            profit_at_peak = entry - peak
                            giveback_amount = profit_at_peak * giveback_frac
                            candidate = peak + giveback_amount

                        candidate = self._apply_direction(
                            pos_side, old_stop, candidate, current_price
                        )
                        if candidate != old_stop:
                            new_stop = candidate
                            stage = f"trail-{int(giveback_frac*100)}% (≥{r_threshold}R)"
                            reason = (
                                f"Trail stop at {new_stop:.4f} "
                                f"(peak={peak:.4f}, giveback={giveback_frac*100:.0f}%, "
                                f"profit={r_multiple:.2f}R)"
                            )
                    break  # Use the first (highest) applicable stage

            # Enforce breakeven floor
            if self._config.enforce_breakeven_floor and pos["breakeven_set"]:
                if pos_side == "long" and new_stop < entry:
                    new_stop = entry
                elif pos_side == "short" and new_stop > entry:
                    new_stop = entry

            # Apply minimum distance
            min_dist = current_price * self._config.min_stop_distance_pct
            if pos_side == "long" and new_stop > current_price - min_dist:
                new_stop = current_price - min_dist
            elif pos_side == "short" and new_stop < current_price + min_dist:
                new_stop = current_price + min_dist

            moved = abs(new_stop - old_stop) > 1e-8
            if moved:
                pos["current_stop"] = new_stop
                pos["stage"] = stage
                logger.info(
                    "📐 %s stop %.4f → %.4f  [%s]  %s",
                    position_id, old_stop, new_stop, stage, reason,
                )

            return StopUpdateResult(
                position_id=position_id,
                old_stop=old_stop,
                new_stop=new_stop,
                r_multiple=r_multiple,
                peak_price=peak,
                tightening_stage=stage,
                reason=reason,
                stop_moved=moved,
            )

    def remove_position(self, position_id: str) -> None:
        """Remove a closed or stopped-out position from tracking."""
        with self._lock:
            self._positions.pop(position_id, None)

    def get_current_stop(self, position_id: str) -> Optional[float]:
        """Return the current tracked stop for a position, or None."""
        with self._lock:
            pos = self._positions.get(position_id)
            return pos["current_stop"] if pos else None

    def get_status(self) -> Dict:
        """Return a summary of all tracked positions."""
        with self._lock:
            return {
                pid: {
                    "entry": p["entry"],
                    "current_stop": p["current_stop"],
                    "peak_price": p["peak_price"],
                    "stage": p["stage"],
                    "side": p["side"],
                }
                for pid, p in self._positions.items()
            }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _apply_direction(
        side: str,
        old_stop: float,
        candidate: float,
        current_price: float,
    ) -> float:
        """Return the candidate only if it improves (tightens) the stop."""
        if side == "long":
            # Stop can only move UP (closer to / through entry)
            return max(old_stop, candidate) if candidate < current_price else old_stop
        else:
            # Stop can only move DOWN (closer to / through entry)
            return min(old_stop, candidate) if candidate > current_price else old_stop


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[DynamicStopLossTightener] = None
_instance_lock = threading.Lock()


def get_dynamic_stop_tightener(
    config: Optional[TightenerConfig] = None,
) -> DynamicStopLossTightener:
    """Return the process-wide singleton DynamicStopLossTightener."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = DynamicStopLossTightener(config=config)
    return _instance
