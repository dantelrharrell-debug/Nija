"""
NIJA Profit Harvest Layer
==========================

A **portfolio-level harvest orchestrator** that sits *above* the
``ProfitLockEngine``.  On each price update it:

1. Delegates to ``ProfitLockEngine.update_position()`` to evaluate the
   ratchet-floor stops.
2. Whenever a position crosses a new lock tier, it computes the
   **harvestable increment** — the portion of newly-locked profit that the
   operator has elected to take off the table immediately.
3. Records harvest events in a persistent ledger and routes them to the
   ``PortfolioProfitEngine`` so they count toward the portfolio's
   harvest total.

Architecture
------------
::

  ┌──────────────────────────────────────────────────────┐
  │              ProfitHarvestLayer  (NEW)               │
  │                                                      │
  │  • harvest_fraction per tier (configurable)          │
  │  • partial_harvest(symbol, fraction) on demand       │
  │  • routes amounts → PortfolioProfitEngine            │
  └────────────────────────┬─────────────────────────────┘
                           │  wraps / consumes
  ┌────────────────────────▼─────────────────────────────┐
  │              ProfitLockEngine (existing)             │
  │  • ratchet floor stops                               │
  │  • six ascending tiers                               │
  └──────────────────────────────────────────────────────┘

Harvest Fractions (defaults)
-----------------------------
At every **new** tier the system computes the *locked profit increment*
(the gain in locked %) and harvests ``harvest_fraction`` of that amount:

  Tier 1 (≥ +1.0 %)  → harvest 25 % of the newly locked increment
  Tier 2 (≥ +2.0 %)  → harvest 30 %
  Tier 3 (≥ +3.5 %)  → harvest 35 %
  Tier 4 (≥ +5.0 %)  → harvest 40 %
  Tier 5 (≥ +8.0 %)  → harvest 45 %
  Tier 6 (≥ +15.0 %) → harvest 50 %

All fractions are operator-configurable at construction time.

Partial Harvest on Demand
--------------------------
``partial_harvest(symbol, fraction=0.5)`` lets the caller withdraw any
fraction (0 < fraction ≤ 1.0) of the *current harvestable balance* for a
position at any time, independent of tier transitions.

Usage
-----
    from bot.profit_harvest_layer import get_profit_harvest_layer

    layer = get_profit_harvest_layer()

    # On position open:
    layer.register_position("BTC-USD", side="long",
                            entry_price=50_000.0,
                            position_size_usd=1_000.0)

    # On every price tick:
    decision = layer.process_price_update("BTC-USD", current_price=51_500.0)
    if decision.harvest_triggered:
        print(f"Harvested ${decision.harvest_amount_usd:.2f}")
    if decision.floor_hit:
        execute_close("BTC-USD")

    # On-demand partial harvest (50 % of available):
    amount = layer.partial_harvest("BTC-USD", fraction=0.5)

    # On position close:
    layer.remove_position("BTC-USD")

    # Dashboard:
    print(layer.get_report())

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
from pathlib import Path
from typing import Dict, List, Optional

from bot.profit_lock_engine import (
    LockDecision,
    LockTier,
    TIER_SPECS,
    get_profit_lock_engine,
)
from bot.portfolio_profit_engine import get_portfolio_profit_engine

logger = logging.getLogger("nija.profit_harvest")

# ---------------------------------------------------------------------------
# Default per-tier harvest fractions
# ---------------------------------------------------------------------------

#: Fraction of the *newly-locked profit increment* to harvest at each tier.
#: Keys match ``LockTier`` enum values (excluding NONE).
DEFAULT_TIER_HARVEST_FRACTIONS: Dict[str, float] = {
    LockTier.TIER_1.value: 0.25,
    LockTier.TIER_2.value: 0.30,
    LockTier.TIER_3.value: 0.35,
    LockTier.TIER_4.value: 0.40,
    LockTier.TIER_5.value: 0.45,
    LockTier.TIER_6.value: 0.50,
}

# Map tier name → index for comparisons
_TIER_ORDER: Dict[str, int] = {
    LockTier.NONE.value: -1,
    **{spec.name: i for i, spec in enumerate(TIER_SPECS)},
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class HarvestEvent:
    """A single harvest event recorded against one position."""
    timestamp: str
    symbol: str
    tier: str                      # tier that triggered this harvest
    locked_increment_pct: float    # newly-locked profit % that triggered it
    harvest_fraction: float        # fraction applied (0–1)
    harvest_pct: float             # % of position value harvested
    harvest_usd: float             # USD amount harvested
    note: str = ""                 # free-text annotation


@dataclass
class HarvestState:
    """Per-position runtime + persisted state for the harvest layer."""
    symbol: str
    side: str                              # 'long' | 'short'
    entry_price: float
    position_size_usd: float              # notional position size in USD
    entry_time: str                        # ISO timestamp
    last_harvested_tier: str = LockTier.NONE.value
    last_locked_pct: float = 0.0          # locked_profit_pct at last harvest
    cumulative_harvested_pct: float = 0.0 # total % of position harvested so far
    cumulative_harvested_usd: float = 0.0
    harvestable_balance_usd: float = 0.0  # accumulated but not yet taken
    harvest_log: List[Dict] = field(default_factory=list)
    last_updated: str = ""

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class HarvestDecision:
    """
    Result returned by ``process_price_update()``.

    Extends the underlying ``LockDecision`` with harvest-specific fields.
    """
    # --- mirror of LockDecision fields ---
    symbol: str
    current_price: float
    peak_profit_pct: float
    current_tier: str
    locked_profit_pct: float
    lock_floor_price: float
    tier_upgraded: bool
    floor_hit: bool
    lock_message: str

    # --- harvest-specific fields ---
    harvest_triggered: bool = False
    harvest_amount_usd: float = 0.0        # harvested in this update
    cumulative_harvested_usd: float = 0.0  # total harvested for this position
    harvestable_balance_usd: float = 0.0   # remaining available to harvest
    message: str = ""


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class ProfitHarvestLayer:
    """
    Profit Harvest Layer — orchestrates partial profit extraction above the
    ``ProfitLockEngine``.

    Thread-safe.  State is persisted to ``data/profit_harvest_state.json``
    so it survives bot restarts.
    """

    DATA_DIR = Path(__file__).parent.parent / "data"
    STATE_FILE = DATA_DIR / "profit_harvest_state.json"

    def __init__(
        self,
        tier_harvest_fractions: Optional[Dict[str, float]] = None,
    ) -> None:
        """
        Args:
            tier_harvest_fractions: Per-tier harvest fractions.  If omitted,
                ``DEFAULT_TIER_HARVEST_FRACTIONS`` is used.  Keys must be
                ``LockTier`` enum values (``"TIER_1"`` … ``"TIER_6"``).
                Values must be in (0, 1].
        """
        self._lock = threading.RLock()
        self._positions: Dict[str, HarvestState] = {}

        # Validate and store tier fractions
        fractions = tier_harvest_fractions or DEFAULT_TIER_HARVEST_FRACTIONS
        for key, val in fractions.items():
            if not (0.0 < val <= 1.0):
                raise ValueError(
                    f"Harvest fraction for {key!r} must be in (0, 1], got {val}"
                )
        self._tier_fractions: Dict[str, float] = dict(fractions)

        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load_state()

        logger.info("=" * 70)
        logger.info("🌾 Profit Harvest Layer initialised")
        for tier, frac in sorted(
            self._tier_fractions.items(), key=lambda kv: _TIER_ORDER.get(kv[0], 99)
        ):
            logger.info(f"   {tier}: harvest {frac * 100:.0f}% of locked increment on tier upgrade")
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
        position_size_usd: float,
        entry_time: Optional[datetime] = None,
    ) -> None:
        """
        Register a new position for harvest tracking.

        Also registers it with the underlying ``ProfitLockEngine``.

        Args:
            symbol:            Trading pair, e.g. ``"BTC-USD"``.
            side:              ``"long"`` or ``"short"``.
            entry_price:       Fill price of the opening order.
            position_size_usd: Notional value in USD (used to compute
                               harvest amounts in dollar terms).
            entry_time:        Trade entry timestamp (defaults to now).
        """
        side = side.lower()
        if side not in ("long", "short"):
            raise ValueError(f"side must be 'long' or 'short', got {side!r}")
        if position_size_usd <= 0:
            raise ValueError(f"position_size_usd must be > 0, got {position_size_usd}")

        ts = (entry_time or datetime.now()).isoformat()

        # Register in the underlying lock engine first
        get_profit_lock_engine().register_position(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            entry_time=entry_time,
        )

        with self._lock:
            if symbol in self._positions:
                logger.warning(
                    "⚠️  %s already registered in harvest layer — re-registering.", symbol
                )

            self._positions[symbol] = HarvestState(
                symbol=symbol,
                side=side,
                entry_price=entry_price,
                position_size_usd=position_size_usd,
                entry_time=ts,
                last_updated=ts,
            )
            self._save_state()

        logger.info(
            "📌 HarvestLayer registered: %s  side=%s  entry=$%.4f  size=$%.2f",
            symbol, side, entry_price, position_size_usd,
        )

    def process_price_update(
        self,
        symbol: str,
        current_price: float,
    ) -> HarvestDecision:
        """
        Process a price update for a registered position.

        Delegates to ``ProfitLockEngine.update_position()`` and, if the
        lock tier has upgraded, computes and records the harvest increment.

        Args:
            symbol:        Trading pair that must be registered.
            current_price: Latest market price.

        Returns:
            ``HarvestDecision`` combining lock status with harvest outcome.
        """
        # 1. Get the lock engine decision
        lock_decision: LockDecision = get_profit_lock_engine().update_position(
            symbol=symbol,
            current_price=current_price,
        )

        with self._lock:
            harvest_triggered = False
            harvest_amount_usd = 0.0

            hs = self._positions.get(symbol)
            if hs is None:
                logger.warning(
                    "⚠️  %s not registered in harvest layer — skipping harvest logic.", symbol
                )
                return HarvestDecision(
                    symbol=symbol,
                    current_price=current_price,
                    peak_profit_pct=lock_decision.peak_profit_pct,
                    current_tier=lock_decision.current_tier,
                    locked_profit_pct=lock_decision.locked_profit_pct,
                    lock_floor_price=lock_decision.lock_floor_price,
                    tier_upgraded=lock_decision.tier_upgraded,
                    floor_hit=lock_decision.floor_hit,
                    lock_message=lock_decision.message,
                    message="Position not registered in harvest layer",
                )

            # 2. Check for tier upgrade → trigger harvest
            if lock_decision.tier_upgraded:
                new_tier = lock_decision.new_tier
                harvest_fraction = self._tier_fractions.get(new_tier, 0.0)

                if harvest_fraction > 0.0:
                    # locked increment = new locked_pct − last locked_pct
                    locked_increment_pct = max(
                        0.0,
                        lock_decision.locked_profit_pct - hs.last_locked_pct,
                    )

                    if locked_increment_pct > 0.0:
                        harvest_pct = locked_increment_pct * harvest_fraction
                        harvest_usd = hs.position_size_usd * (harvest_pct / 100.0)

                        # Record the harvest event
                        event = HarvestEvent(
                            timestamp=datetime.now().isoformat(),
                            symbol=symbol,
                            tier=new_tier,
                            locked_increment_pct=round(locked_increment_pct, 4),
                            harvest_fraction=harvest_fraction,
                            harvest_pct=round(harvest_pct, 4),
                            harvest_usd=round(harvest_usd, 4),
                        )
                        hs.harvest_log.append(event.__dict__)
                        hs.cumulative_harvested_pct += harvest_pct
                        hs.cumulative_harvested_usd += harvest_usd
                        hs.harvestable_balance_usd += harvest_usd

                        harvest_triggered = True
                        harvest_amount_usd = harvest_usd

                        logger.info(
                            "🌾 %s → %s | locked_incr=+%.2f%% | "
                            "harvest_frac=%.0f%% | harvested=$%.2f | "
                            "cumulative=$%.2f",
                            symbol, new_tier, locked_increment_pct,
                            harvest_fraction * 100, harvest_usd,
                            hs.cumulative_harvested_usd,
                        )

                hs.last_harvested_tier = new_tier
                hs.last_locked_pct = lock_decision.locked_profit_pct

            # 3. If floor_hit, auto-harvest the remaining harvestable balance
            if lock_decision.floor_hit and hs.harvestable_balance_usd > 0:
                remaining = hs.harvestable_balance_usd
                logger.info(
                    "🏁 %s floor hit — flushing harvestable balance $%.2f to profit engine",
                    symbol, remaining,
                )
                self._route_to_profit_engine(
                    symbol=symbol,
                    amount_usd=remaining,
                    note=f"floor hit flush — tier={lock_decision.current_tier}",
                )
                hs.harvestable_balance_usd = 0.0

            hs.last_updated = datetime.now().isoformat()
            self._save_state()

            # Build harvest message
            parts = [lock_decision.message]
            if harvest_triggered:
                parts.append(f"harvested=${harvest_amount_usd:.2f}")
            if lock_decision.floor_hit:
                parts.append("floor hit")
            harvest_msg = " | ".join(parts)

            return HarvestDecision(
                symbol=symbol,
                current_price=current_price,
                peak_profit_pct=lock_decision.peak_profit_pct,
                current_tier=lock_decision.current_tier,
                locked_profit_pct=lock_decision.locked_profit_pct,
                lock_floor_price=lock_decision.lock_floor_price,
                tier_upgraded=lock_decision.tier_upgraded,
                floor_hit=lock_decision.floor_hit,
                lock_message=lock_decision.message,
                harvest_triggered=harvest_triggered,
                harvest_amount_usd=round(harvest_amount_usd, 4),
                cumulative_harvested_usd=round(hs.cumulative_harvested_usd, 4),
                harvestable_balance_usd=round(hs.harvestable_balance_usd, 4),
                message=harvest_msg,
            )

    def partial_harvest(
        self,
        symbol: str,
        fraction: float = 1.0,
        note: str = "",
    ) -> float:
        """
        On-demand partial harvest of the harvestable balance for *symbol*.

        Harvests ``fraction`` of the current ``harvestable_balance_usd`` and
        routes it to the ``PortfolioProfitEngine``.

        Args:
            symbol:   Trading pair.
            fraction: Fraction of the harvestable balance to withdraw
                      (0 < fraction ≤ 1.0).  Defaults to 1.0 (full harvest).
            note:     Annotation stored in the harvest log.

        Returns:
            USD amount harvested (0.0 if nothing available or symbol unknown).
        """
        if not (0.0 < fraction <= 1.0):
            raise ValueError(f"fraction must be in (0, 1], got {fraction}")

        with self._lock:
            hs = self._positions.get(symbol)
            if hs is None:
                logger.warning(
                    "⚠️  partial_harvest: %s not registered — skipping.", symbol
                )
                return 0.0

            available = hs.harvestable_balance_usd
            if available <= 0.0:
                logger.warning(
                    "⚠️  partial_harvest: no harvestable balance for %s.", symbol
                )
                return 0.0

            harvest_usd = available * fraction
            hs.harvestable_balance_usd -= harvest_usd

            # Log the on-demand event
            event = HarvestEvent(
                timestamp=datetime.now().isoformat(),
                symbol=symbol,
                tier=hs.last_harvested_tier,
                locked_increment_pct=0.0,
                harvest_fraction=fraction,
                harvest_pct=0.0,
                harvest_usd=round(harvest_usd, 4),
                note=note or f"on-demand partial harvest ({fraction * 100:.0f}%)",
            )
            hs.harvest_log.append(event.__dict__)
            hs.last_updated = datetime.now().isoformat()
            self._save_state()

        # Route outside the lock to avoid deadlock with profit engine
        self._route_to_profit_engine(
            symbol=symbol,
            amount_usd=harvest_usd,
            note=note or f"on-demand partial harvest ({fraction * 100:.0f}%)",
        )

        logger.info(
            "💵 Partial harvest: %s  fraction=%.0f%%  amount=$%.2f  "
            "remaining_balance=$%.2f",
            symbol, fraction * 100, harvest_usd, hs.harvestable_balance_usd,
        )
        return round(harvest_usd, 4)

    def remove_position(self, symbol: str) -> Optional[Dict]:
        """
        Unregister a closed position from both the harvest layer and the lock
        engine.

        Any remaining harvestable balance is flushed to the
        ``PortfolioProfitEngine`` before removal.

        Args:
            symbol: Trading pair to remove.

        Returns:
            Final ``HarvestState`` dict, or ``None`` if not tracked.
        """
        with self._lock:
            hs = self._positions.pop(symbol, None)
            if hs is None:
                logger.warning("⚠️  remove_position: %s not found in harvest layer.", symbol)
            else:
                # Flush remaining harvestable balance
                if hs.harvestable_balance_usd > 0.0:
                    self._route_to_profit_engine(
                        symbol=symbol,
                        amount_usd=hs.harvestable_balance_usd,
                        note="position close flush",
                    )
                    logger.info(
                        "🏁 %s closed — flushed harvestable balance $%.2f",
                        symbol, hs.harvestable_balance_usd,
                    )
                self._save_state()

        # Remove from underlying lock engine (may already be removed)
        get_profit_lock_engine().remove_position(symbol)

        if hs is not None:
            logger.info(
                "✅ HarvestLayer removed: %s | total_harvested=$%.2f",
                symbol, hs.cumulative_harvested_usd,
            )
            return hs.to_dict()
        return None

    def get_harvest_status(self, symbol: str) -> Optional[Dict]:
        """Return the current harvest state for a single position, or ``None``."""
        with self._lock:
            hs = self._positions.get(symbol)
            return hs.to_dict() if hs else None

    def get_all_statuses(self) -> Dict[str, Dict]:
        """Return harvest states for all tracked positions."""
        with self._lock:
            return {sym: hs.to_dict() for sym, hs in self._positions.items()}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _route_to_profit_engine(
        self,
        symbol: str,
        amount_usd: float,
        note: str = "",
    ) -> None:
        """
        Forward a harvested amount to the ``PortfolioProfitEngine``.

        Failures are logged but never propagate — the harvest layer must
        stay operational even if the profit engine is unavailable.
        """
        try:
            pe = get_portfolio_profit_engine()
            pe.harvest_profits(amount=amount_usd, note=f"[{symbol}] {note}".strip())
        except Exception as exc:
            logger.error(
                "Failed to route harvest to PortfolioProfitEngine: %s", exc
            )

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _save_state(self) -> None:
        """Persist all harvest states to disk (must be called under self._lock)."""
        try:
            data = {sym: hs.to_dict() for sym, hs in self._positions.items()}
            with open(self.STATE_FILE, "w") as fh:
                json.dump(data, fh, indent=2)
        except Exception as exc:
            logger.error("Failed to save harvest layer state: %s", exc)

    def _load_state(self) -> None:
        """Restore harvest states from disk (called from __init__)."""
        if not self.STATE_FILE.exists():
            return
        try:
            with open(self.STATE_FILE, "r") as fh:
                data = json.load(fh)
            for sym, raw in data.items():
                self._positions[sym] = HarvestState(**raw)
            logger.info(
                "✅ Harvest layer state loaded (%d positions)", len(self._positions)
            )
        except Exception as exc:
            logger.warning("Failed to load harvest layer state: %s", exc)

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_report(self) -> str:
        """Return a human-readable report of all active harvest positions."""
        with self._lock:
            positions = list(self._positions.values())
            fractions = dict(self._tier_fractions)

        header = [
            "",
            "=" * 80,
            "  NIJA PROFIT HARVEST LAYER — HARVEST STATUS REPORT",
            "=" * 80,
            "  Tier Harvest Fractions:",
        ]
        for tier, frac in sorted(fractions.items(), key=lambda kv: _TIER_ORDER.get(kv[0], 99)):
            header.append(f"    {tier}: {frac * 100:.0f}% of locked increment")
        header += [
            "",
            f"  Positions tracked : {len(positions)}",
            "",
        ]

        if not positions:
            header.append("  (no open positions)")
            header.append("=" * 80)
            return "\n".join(header)

        rows = []
        for hs in positions:
            rows += [
                f"  ▸ {hs.symbol}  ({hs.side.upper()})",
                f"      Entry Price        : ${hs.entry_price:.4f}",
                f"      Position Size      : ${hs.position_size_usd:,.2f}",
                f"      Last Harvested Tier: {hs.last_harvested_tier}",
                f"      Last Locked Pct    : +{hs.last_locked_pct:.2f}%",
                f"      Harvested (total)  : ${hs.cumulative_harvested_usd:,.2f}  "
                f"({hs.cumulative_harvested_pct:.2f}% of position)",
                f"      Harvestable Balance: ${hs.harvestable_balance_usd:,.2f}",
                f"      Harvest Events     : {len(hs.harvest_log)}",
                "",
            ]

        footer = ["=" * 80, ""]
        return "\n".join(header + rows + footer)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_layer_instance: Optional[ProfitHarvestLayer] = None
_layer_lock = threading.Lock()


def get_profit_harvest_layer(
    tier_harvest_fractions: Optional[Dict[str, float]] = None,
) -> ProfitHarvestLayer:
    """
    Return the global ``ProfitHarvestLayer`` singleton.

    Thread-safe; creates one instance on first call.  Subsequent calls ignore
    the ``tier_harvest_fractions`` argument (persisted state is authoritative).

    Args:
        tier_harvest_fractions: Optional per-tier fraction overrides for the
            first-time construction.  Ignored after the first call.
    """
    global _layer_instance
    if _layer_instance is None:
        with _layer_lock:
            if _layer_instance is None:
                _layer_instance = ProfitHarvestLayer(
                    tier_harvest_fractions=tier_harvest_fractions,
                )
    return _layer_instance


# ---------------------------------------------------------------------------
# CLI smoke-test / demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")

    layer = get_profit_harvest_layer()
    pe = get_portfolio_profit_engine(base_capital=10_000.0)

    # ------------------------------------------------------------------
    # Scenario: BTC-USD long, price climbs through multiple tiers
    # ------------------------------------------------------------------
    ENTRY = 50_000.0
    SIZE = 2_000.0  # $2 000 position

    print("\n─── Registering BTC-USD long ($2 000 position at $50 000) ───")
    layer.register_position("BTC-USD", side="long",
                            entry_price=ENTRY, position_size_usd=SIZE)

    price_steps = [
        50_000.0,  # 0 % — no tier
        50_505.0,  # +1.01 % → TIER_1
        51_010.0,  # +2.02 % → TIER_2
        51_765.0,  # +3.53 % → TIER_3
        52_525.0,  # +5.05 % → TIER_4
        54_040.0,  # +8.08 % → TIER_5
        57_575.0,  # +15.15 % → TIER_6
        54_000.0,  # price retreats — check if floor is hit
    ]

    print("\n─── Simulating price steps ───")
    for price in price_steps:
        pct = (price - ENTRY) / ENTRY * 100
        d = layer.process_price_update("BTC-USD", current_price=price)
        tag = f" [HARVEST ${d.harvest_amount_usd:.2f}]" if d.harvest_triggered else ""
        floor_tag = " *** FLOOR HIT ***" if d.floor_hit else ""
        print(
            f"  price=${price:>10,.2f}  ({pct:+.2f}%)  tier={d.current_tier:<6}"
            f"  locked={d.locked_profit_pct:.2f}%"
            f"  balance=${d.harvestable_balance_usd:.2f}{tag}{floor_tag}"
        )

    print("\n─── On-demand partial harvest (50 %) ───")
    taken = layer.partial_harvest("BTC-USD", fraction=0.5, note="mid-trade cash out")
    print(f"  Partial harvest: ${taken:.2f}")

    # Check status
    status = layer.get_harvest_status("BTC-USD")
    if status:
        print(f"  Remaining harvestable: ${status['harvestable_balance_usd']:.2f}")
        print(f"  Total harvested USD  : ${status['cumulative_harvested_usd']:.2f}")

    print(layer.get_report())

    # ------------------------------------------------------------------
    # Scenario: ETH-USD short
    # ------------------------------------------------------------------
    print("\n─── Registering ETH-USD short ($1 500 position at $3 000) ───")
    layer.register_position("ETH-USD", side="short",
                            entry_price=3_000.0, position_size_usd=1_500.0)

    short_steps = [3_000.0, 2_970.0, 2_940.0, 2_895.0, 2_850.0]
    print("\n─── Simulating ETH short price steps ───")
    for price in short_steps:
        pct = (3_000.0 - price) / 3_000.0 * 100
        d = layer.process_price_update("ETH-USD", current_price=price)
        tag = f" [HARVEST ${d.harvest_amount_usd:.2f}]" if d.harvest_triggered else ""
        print(
            f"  price=${price:>10,.2f}  ({pct:+.2f}%)  tier={d.current_tier:<6}"
            f"  locked={d.locked_profit_pct:.2f}%"
            f"  balance=${d.harvestable_balance_usd:.2f}{tag}"
        )

    # Close positions
    print("\n─── Closing positions ───")
    layer.remove_position("BTC-USD")
    layer.remove_position("ETH-USD")

    print(layer.get_report())
    print(pe.get_report())
