"""
NIJA Profit Lock Engine
========================

Implements a per-trade **ratchet-style** profit locking mechanism with six
tiered milestones.  As a position climbs to each tier, a growing fraction of
the peak profit is permanently "locked in" via a dynamic floor stop price.
The lock floor can only move in the profitable direction — it never releases
locked gains.

Architecture
------------
::

  ┌──────────────────────────────────────────────────────┐
  │                  ProfitLockEngine                    │
  │                                                      │
  │  Tier   Peak Profit   Fraction Locked   Lock Floor % │
  │  ─────────────────────────────────────────────────── │
  │  1      ≥ +1.0 %      30 % of peak     +0.30 %      │
  │  2      ≥ +2.0 %      50 % of peak     +1.00 %      │
  │  3      ≥ +3.5 %      70 % of peak     +2.45 %      │
  │  4      ≥ +5.0 %      82 % of peak     +4.10 %      │
  │  5      ≥ +8.0 %      92 % of peak     +7.36 %      │
  │  6      ≥ +15.0 %     96 % of peak     +14.40 %     │
  │                                                      │
  │  The "lock floor price" is the stop price at which   │
  │  the position would be closed to guarantee the       │
  │  locked profit fraction.  It is ratcheted up         │
  │  (for longs) or down (for shorts) monotonically.     │
  └──────────────────────────────────────────────────────┘

Key Design Decisions
--------------------
* **Ratchet only**: lock floor never moves against the trade.
* **Tiered milestones**: each tier supersedes the previous one.
* **Long & short**: symmetric logic for both directions.
* **Thread-safe singleton**: ``get_profit_lock_engine()``.
* **Lightweight JSON persistence**: survives bot restarts.
* **Zero hard dependencies**: works standalone.

Usage
-----
    from bot.profit_lock_engine import get_profit_lock_engine

    engine = get_profit_lock_engine()

    # When a position opens:
    engine.register_position("BTC-USD", side="long", entry_price=50_000.0)

    # On every price update:
    decision = engine.update_position("BTC-USD", current_price=51_500.0)
    if decision.tier_upgraded:
        logger.info(f"New lock tier: {decision.new_tier} | floor={decision.lock_floor_price:.2f}")
    if decision.floor_hit:
        # Close position to honour the profit lock
        execute_close("BTC-USD")

    # When position closes:
    engine.remove_position("BTC-USD")

    # Dashboard snapshot:
    print(engine.get_report())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("nija.profit_lock")

# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TierSpec:
    """Specification for a single profit-lock tier."""
    name: str           # human-readable identifier
    peak_trigger_pct: float   # activate when peak profit ≥ this (%)
    lock_fraction: float      # fraction of peak profit that is locked (0–1)

    @property
    def description(self) -> str:
        return (
            f"{self.name}: activates at peak ≥ +{self.peak_trigger_pct:.1f}%,"
            f" locks {self.lock_fraction * 100:.0f}% of peak"
        )


# Six ascending tiers. Each supersedes the previous.
TIER_SPECS: List[TierSpec] = [
    TierSpec("TIER_1", peak_trigger_pct=1.0,  lock_fraction=0.30),
    TierSpec("TIER_2", peak_trigger_pct=2.0,  lock_fraction=0.50),
    TierSpec("TIER_3", peak_trigger_pct=3.5,  lock_fraction=0.70),
    TierSpec("TIER_4", peak_trigger_pct=5.0,  lock_fraction=0.82),
    TierSpec("TIER_5", peak_trigger_pct=8.0,  lock_fraction=0.92),
    TierSpec("TIER_6", peak_trigger_pct=15.0, lock_fraction=0.96),
]

# Map tier name → spec for quick look-up
_TIER_MAP: Dict[str, TierSpec] = {t.name: t for t in TIER_SPECS}


class LockTier(str, Enum):
    NONE = "NONE"
    TIER_1 = "TIER_1"
    TIER_2 = "TIER_2"
    TIER_3 = "TIER_3"
    TIER_4 = "TIER_4"
    TIER_5 = "TIER_5"
    TIER_6 = "TIER_6"


# ---------------------------------------------------------------------------
# Per-position state
# ---------------------------------------------------------------------------

@dataclass
class LockState:
    """Runtime + persisted state for one open position."""
    symbol: str
    side: str                          # 'long' | 'short'
    entry_price: float
    entry_time: str                    # ISO timestamp
    peak_price: float                  # best price seen so far
    peak_profit_pct: float             # corresponding peak profit %
    current_tier: str = LockTier.NONE.value  # current LockTier name
    locked_profit_pct: float = 0.0    # floor profit % guaranteed
    lock_floor_price: float = 0.0     # stop price that guarantees the lock
    last_updated: str = ""
    tier_history: List[Dict] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Decision object returned by update_position()
# ---------------------------------------------------------------------------

@dataclass
class LockDecision:
    """Result of a single price-update evaluation."""
    symbol: str
    current_price: float
    peak_profit_pct: float
    current_tier: str
    locked_profit_pct: float
    lock_floor_price: float
    tier_upgraded: bool = False
    new_tier: str = LockTier.NONE.value
    floor_hit: bool = False            # True → position should be closed now
    message: str = ""


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class ProfitLockEngine:
    """
    Per-trade ratchet-style profit locking.

    Call ``register_position()`` when a trade opens, ``update_position()`` on
    every price tick (or candle close), and ``remove_position()`` when the
    trade closes.  ``update_position()`` returns a ``LockDecision`` that tells
    the caller whether the lock tier was upgraded and whether the lock-floor
    stop has been hit.
    """

    DATA_DIR = Path(__file__).parent.parent / "data"
    STATE_FILE = DATA_DIR / "profit_lock_state.json"

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._positions: Dict[str, LockState] = {}
        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load_state()

        logger.info("=" * 70)
        logger.info("🔒 Profit Lock Engine initialised")
        for spec in TIER_SPECS:
            logger.info(f"   {spec.description}")
        logger.info(f"   Active positions loaded: {len(self._positions)}")
        logger.info("=" * 70)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def register_position(
        self,
        symbol: str,
        side: str,
        entry_price: float,
        entry_time: Optional[datetime] = None,
    ) -> None:
        """
        Register a new open position for profit-lock tracking.

        Args:
            symbol:      Trading pair, e.g. ``"BTC-USD"``.
            side:        ``"long"`` or ``"short"``.
            entry_price: Fill price of the opening order.
            entry_time:  Trade entry timestamp (defaults to now).
        """
        side = side.lower()
        if side not in ("long", "short"):
            raise ValueError(f"side must be 'long' or 'short', got {side!r}")

        ts = (entry_time or datetime.now()).isoformat()

        with self._lock:
            if symbol in self._positions:
                logger.warning(
                    "⚠️  %s already registered — re-registering with new entry price.", symbol
                )

            state = LockState(
                symbol=symbol,
                side=side,
                entry_price=entry_price,
                entry_time=ts,
                peak_price=entry_price,
                peak_profit_pct=0.0,
                last_updated=ts,
            )
            self._positions[symbol] = state
            self._save_state()

        logger.info(
            "📌 ProfitLock registered: %s  side=%s  entry=$%.4f",
            symbol, side, entry_price,
        )

    def update_position(self, symbol: str, current_price: float) -> LockDecision:
        """
        Evaluate the current price against the profit-lock tiers.

        Updates the peak price / profit and ratchets the lock floor upwards
        as new tiers are reached.  Returns a ``LockDecision`` describing
        whether a tier was upgraded and whether the floor stop has been hit.

        Args:
            symbol:        Trading pair, must be registered first.
            current_price: Latest market price.

        Returns:
            ``LockDecision`` with all relevant fields populated.
        """
        with self._lock:
            if symbol not in self._positions:
                logger.warning("⚠️  %s not registered — skipping lock update.", symbol)
                return LockDecision(
                    symbol=symbol,
                    current_price=current_price,
                    peak_profit_pct=0.0,
                    current_tier=LockTier.NONE.value,
                    locked_profit_pct=0.0,
                    lock_floor_price=0.0,
                    message="Position not registered",
                )

            state = self._positions[symbol]
            now = datetime.now().isoformat()

            # --- 1. Update peak price and peak profit ---
            entry = state.entry_price
            if state.side == "long":
                current_profit_pct = (current_price - entry) / entry * 100.0
            else:
                current_profit_pct = (entry - current_price) / entry * 100.0

            if current_profit_pct > state.peak_profit_pct:
                state.peak_profit_pct = current_profit_pct
                state.peak_price = current_price

            # --- 2. Check for tier upgrade ---
            old_tier_name = state.current_tier
            tier_upgraded = False
            new_tier_name = old_tier_name

            for spec in reversed(TIER_SPECS):  # highest tier first
                if state.peak_profit_pct >= spec.peak_trigger_pct:
                    if spec.name != old_tier_name:
                        # Only upgrade (never downgrade)
                        old_idx = next(
                            (i for i, t in enumerate(TIER_SPECS) if t.name == old_tier_name), -1
                        )
                        new_idx = next(
                            (i for i, t in enumerate(TIER_SPECS) if t.name == spec.name), -1
                        )
                        if new_idx > old_idx:
                            new_tier_name = spec.name
                            tier_upgraded = True
                    break

            if tier_upgraded:
                state.current_tier = new_tier_name
                tier_spec = _TIER_MAP[new_tier_name]
                locked_pct = state.peak_profit_pct * tier_spec.lock_fraction
                state.locked_profit_pct = locked_pct

                # Compute lock floor stop price
                if state.side == "long":
                    new_floor = entry * (1.0 + locked_pct / 100.0)
                    # Ratchet: never lower the floor
                    if new_floor > state.lock_floor_price:
                        state.lock_floor_price = new_floor
                else:
                    new_floor = entry * (1.0 - locked_pct / 100.0)
                    # Ratchet: never raise the floor (for shorts, floor is lower price)
                    if state.lock_floor_price == 0.0 or new_floor < state.lock_floor_price:
                        state.lock_floor_price = new_floor

                state.tier_history.append({
                    "timestamp": now,
                    "tier": new_tier_name,
                    "peak_profit_pct": round(state.peak_profit_pct, 4),
                    "locked_profit_pct": round(locked_pct, 4),
                    "lock_floor_price": round(state.lock_floor_price, 6),
                })

                logger.info(
                    "🔒 %s → %s | peak=+%.2f%% | locked=+%.2f%% | floor=$%.4f",
                    symbol, new_tier_name,
                    state.peak_profit_pct,
                    state.locked_profit_pct,
                    state.lock_floor_price,
                )
            else:
                # Even without a tier upgrade, ratchet floor if the peak improved
                # and we are in an active tier
                if state.current_tier != LockTier.NONE.value and state.lock_floor_price > 0.0:
                    tier_spec = _TIER_MAP.get(state.current_tier)
                    if tier_spec is not None:
                        locked_pct = state.peak_profit_pct * tier_spec.lock_fraction
                        if state.side == "long":
                            candidate = entry * (1.0 + locked_pct / 100.0)
                            if candidate > state.lock_floor_price:
                                state.lock_floor_price = candidate
                                state.locked_profit_pct = locked_pct
                        else:
                            candidate = entry * (1.0 - locked_pct / 100.0)
                            if candidate < state.lock_floor_price:
                                state.lock_floor_price = candidate
                                state.locked_profit_pct = locked_pct

            # --- 3. Check if floor stop is hit ---
            floor_hit = False
            if state.lock_floor_price > 0.0:
                if state.side == "long" and current_price <= state.lock_floor_price:
                    floor_hit = True
                elif state.side == "short" and current_price >= state.lock_floor_price:
                    floor_hit = True

            state.last_updated = now
            self._save_state()

            msg_parts = [
                f"price=${current_price:.4f}",
                f"peak=+{state.peak_profit_pct:.2f}%",
                f"tier={state.current_tier}",
                f"floor=${state.lock_floor_price:.4f}" if state.lock_floor_price else "floor=N/A",
            ]
            if floor_hit:
                msg_parts.append("FLOOR HIT — close position")
            message = " | ".join(msg_parts)

            return LockDecision(
                symbol=symbol,
                current_price=current_price,
                peak_profit_pct=round(state.peak_profit_pct, 4),
                current_tier=state.current_tier,
                locked_profit_pct=round(state.locked_profit_pct, 4),
                lock_floor_price=round(state.lock_floor_price, 6),
                tier_upgraded=tier_upgraded,
                new_tier=new_tier_name,
                floor_hit=floor_hit,
                message=message,
            )

    def remove_position(self, symbol: str) -> Optional[Dict]:
        """
        Unregister a closed position.

        Args:
            symbol: Trading pair to remove.

        Returns:
            Final ``LockState`` dict, or ``None`` if symbol was not tracked.
        """
        with self._lock:
            state = self._positions.pop(symbol, None)
            if state is None:
                logger.warning("⚠️  remove_position: %s not found.", symbol)
                return None
            self._save_state()

        logger.info(
            "✅ ProfitLock removed: %s | final_tier=%s | locked=+%.2f%%",
            symbol, state.current_tier, state.locked_profit_pct,
        )
        return state.to_dict()

    def get_lock_status(self, symbol: str) -> Optional[Dict]:
        """Return the current lock state for a single position, or ``None``."""
        with self._lock:
            state = self._positions.get(symbol)
            return state.to_dict() if state else None

    def get_all_statuses(self) -> Dict[str, Dict]:
        """Return lock states for all tracked positions."""
        with self._lock:
            return {sym: s.to_dict() for sym, s in self._positions.items()}

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        """Persist all position states to disk (called under lock)."""
        try:
            data = {sym: s.to_dict() for sym, s in self._positions.items()}
            with open(self.STATE_FILE, "w") as fh:
                json.dump(data, fh, indent=2)
        except Exception as exc:
            logger.error("Failed to save profit lock state: %s", exc)

    def _load_state(self) -> None:
        """Restore position states from disk (called from __init__)."""
        if not self.STATE_FILE.exists():
            return
        try:
            with open(self.STATE_FILE, "r") as fh:
                data = json.load(fh)
            for sym, raw in data.items():
                self._positions[sym] = LockState(**raw)
            logger.info("✅ Profit lock state loaded (%d positions)", len(self._positions))
        except Exception as exc:
            logger.warning("Failed to load profit lock state: %s", exc)

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_report(self) -> str:
        """Return a human-readable report of all active profit locks."""
        with self._lock:
            positions = list(self._positions.values())

        header = [
            "",
            "=" * 80,
            "  NIJA PROFIT LOCK ENGINE — ACTIVE LOCK REPORT",
            "=" * 80,
            f"  Positions tracked : {len(positions)}",
            "",
        ]

        if not positions:
            header.append("  (no open positions)")
            header.append("=" * 80)
            return "\n".join(header)

        rows = []
        for s in positions:
            rows += [
                f"  ▸ {s.symbol}  ({s.side.upper()})",
                f"      Entry          : ${s.entry_price:.4f}",
                f"      Peak Profit    : +{s.peak_profit_pct:.2f}%",
                f"      Current Tier   : {s.current_tier}",
                f"      Locked Floor   : +{s.locked_profit_pct:.2f}%  "
                f"(stop @ ${s.lock_floor_price:.4f})",
                f"      Tier Upgrades  : {len(s.tier_history)}",
                "",
            ]

        footer = ["=" * 80, ""]
        return "\n".join(header + rows + footer)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_engine_instance: Optional[ProfitLockEngine] = None
_engine_lock = threading.Lock()


def get_profit_lock_engine() -> ProfitLockEngine:
    """
    Return the global ``ProfitLockEngine`` singleton.

    Thread-safe; creates one instance on first call.
    """
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = ProfitLockEngine()
    return _engine_instance


# ---------------------------------------------------------------------------
# CLI smoke-test / demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    engine = get_profit_lock_engine()

    # ---- Demo: long BTC position ----------------------------------------
    entry = 50_000.0
    engine.register_position("BTC-USD", side="long", entry_price=entry)

    price_sequence = [
        50_200,   # +0.4% — below tier 1
        50_500,   # +1.0% — tier 1 activates (30% of 1% = 0.3% locked)
        51_000,   # +2.0% — tier 2 activates (50% of 2% = 1.0% locked)
        51_750,   # +3.5% — tier 3 activates (70% of 3.5% = 2.45% locked)
        52_500,   # +5.0% — tier 4 activates (82% of 5% = 4.1% locked)
        54_000,   # +8.0% — tier 5 activates (92% of 8% = 7.36% locked)
        53_500,   # price drops — floor should stop exit (above floor)
        50_500,   # price drops to near floor area
    ]

    for price in price_sequence:
        decision = engine.update_position("BTC-USD", current_price=price)
        arrow = "⬆️ TIER UP" if decision.tier_upgraded else ""
        floor_alert = "⛔ FLOOR HIT" if decision.floor_hit else ""
        print(
            f"  price=${price:,.0f}  peak=+{decision.peak_profit_pct:.2f}%"
            f"  tier={decision.current_tier}"
            f"  floor=${decision.lock_floor_price:,.2f}"
            f"  {arrow}{floor_alert}"
        )
        if decision.floor_hit:
            print("  → Position should be closed to preserve locked profit")
            break

    print(engine.get_report())

    # ---- Demo: short ETH position ---------------------------------------
    eth_entry = 3_000.0
    engine.register_position("ETH-USD", side="short", entry_price=eth_entry)

    short_prices = [
        2_980,   # +0.67% — below tier 1
        2_970,   # +1.0% — tier 1
        2_940,   # +2.0% — tier 2
        2_900,   # +3.33% — tier 2 → 3
        2_850,   # +5.0% — tier 4
        2_975,   # price rises — check floor hit on short
    ]

    print("\n--- Short ETH-USD demo ---")
    for price in short_prices:
        decision = engine.update_position("ETH-USD", current_price=price)
        arrow = "⬆️ TIER UP" if decision.tier_upgraded else ""
        floor_alert = "⛔ FLOOR HIT" if decision.floor_hit else ""
        print(
            f"  price=${price:,.0f}  peak=+{decision.peak_profit_pct:.2f}%"
            f"  tier={decision.current_tier}"
            f"  floor=${decision.lock_floor_price:,.2f}"
            f"  {arrow}{floor_alert}"
        )

    engine.remove_position("BTC-USD")
    engine.remove_position("ETH-USD")

    print("\n✅ Profit Lock Engine demo complete.")
    sys.exit(0)
