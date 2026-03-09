"""
NIJA Capital Recycling Engine
==============================

Automatically allocates **harvested profits** (from the ProfitHarvestLayer
and PortfolioProfitEngine) to the strategies with the strongest recent
performance.

How it works
------------
1. Harvested profit is **deposited** into the engine's recycling pool via
   ``deposit_profit()``.  The caller may optionally pass the current market
   regime so that strategy scores are regime-aware.
2. On every ``allocate()`` call the engine queries the
   ``MetaLearningOptimizer`` (or falls back to the
   ``SelfLearningStrategyAllocator``) for per-strategy composite scores in
   the current regime.
3. Scores are normalised and clipped to configurable min/max bounds, then
   used to split the available pool into per-strategy allocations.
4. A strategy (or orchestrator) calls ``claim_allocation(strategy, amount)``
   to draw down its share.  The deducted amount is removed from the pool.
5. State is persisted to JSON so the pool survives restarts.

Architecture
------------
::

  ┌─────────────────────────────────────────────────────────────┐
  │                CapitalRecyclingEngine  (NEW)                 │
  │                                                             │
  │  Pool ← deposit_profit(amount, source_symbol, regime)       │
  │                                                             │
  │  Scores ← MetaLearningOptimizer.get_regime_weights(regime)  │
  │       or   SelfLearningAllocator.get_weights()              │
  │                                                             │
  │  allocation[strategy] = pool × weight[strategy]             │
  │                                                             │
  │  Pool -= claim_allocation(strategy, amount)                 │
  └─────────────────────────────────────────────────────────────┘

Usage
-----
    from bot.capital_recycling_engine import get_capital_recycling_engine

    engine = get_capital_recycling_engine()

    # Deposit a harvested profit (e.g. called by ProfitHarvestLayer):
    engine.deposit_profit(amount_usd=250.0,
                          source_symbol="BTC-USD",
                          regime="BULL_TRENDING")

    # Compute / refresh allocations for the current regime:
    allocations = engine.allocate(regime="BULL_TRENDING")
    # → {"ApexTrend": 132.5, "MomentumBreakout": 71.0, ...}

    # A strategy claims its share before placing an order:
    granted = engine.claim_allocation("ApexTrend", requested_usd=100.0)

    # Status dashboard:
    print(engine.get_report())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import math
import os
import threading
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.capital_recycling")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Default strategies the recycler knows about.
DEFAULT_STRATEGIES: List[str] = [
    "ApexTrend",
    "MeanReversion",
    "MomentumBreakout",
    "LiquidityReversal",
    "Macro",
]

#: Minimum fraction of the pool any single strategy can receive.
MIN_ALLOCATION_FRAC: float = 0.05   # 5 %

#: Maximum fraction of the pool any single strategy can receive.
MAX_ALLOCATION_FRAC: float = 0.60   # 60 %

#: When the pool falls below this USD threshold the engine skips allocation
#: to avoid noise from micro-amounts.
MIN_POOL_FOR_ALLOCATION: float = 1.0   # $1


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class RecycleEvent:
    """A single profit-deposit event into the recycling pool."""
    timestamp: str
    source_symbol: str      # symbol that generated the profit (e.g. "BTC-USD")
    amount_usd: float       # amount added to the pool
    regime: str             # market regime at deposit time
    note: str = ""


@dataclass
class ClaimEvent:
    """A recorded allocation claim by a strategy."""
    timestamp: str
    strategy: str
    requested_usd: float
    granted_usd: float      # may be less than requested if pool is short
    regime: str
    note: str = ""


@dataclass
class EngineState:
    """Persistent state for the Capital Recycling Engine."""
    pool_usd: float = 0.0                  # currently available recycled capital
    total_deposited_usd: float = 0.0       # cumulative amount deposited
    total_claimed_usd: float = 0.0         # cumulative amount claimed
    recycle_events: List[Dict] = field(default_factory=list)
    claim_events: List[Dict] = field(default_factory=list)
    # Last computed per-strategy allocations (informational snapshot)
    last_allocations: Dict[str, float] = field(default_factory=dict)
    last_allocation_regime: str = ""
    last_allocation_ts: str = ""
    created_at: str = ""
    last_updated: str = ""


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class CapitalRecyclingEngine:
    """
    Capital Recycling Engine — channels harvested profits into the highest-
    performing strategies.

    Parameters
    ----------
    state_path : str
        Path to the JSON persistence file.
    strategies : list[str]
        Strategy names this engine knows about.
    min_allocation_frac : float
        Minimum fraction any strategy receives (default 5 %).
    max_allocation_frac : float
        Maximum fraction any strategy receives (default 60 %).
    min_pool_for_allocation : float
        Minimum pool size before allocations are computed (default $1).
    """

    def __init__(
        self,
        state_path: str = "data/capital_recycling_state.json",
        strategies: Optional[List[str]] = None,
        min_allocation_frac: float = MIN_ALLOCATION_FRAC,
        max_allocation_frac: float = MAX_ALLOCATION_FRAC,
        min_pool_for_allocation: float = MIN_POOL_FOR_ALLOCATION,
    ) -> None:
        self.state_path = state_path
        self.strategies = list(strategies or DEFAULT_STRATEGIES)
        self.min_allocation_frac = min_allocation_frac
        self.max_allocation_frac = max_allocation_frac
        self.min_pool_for_allocation = min_pool_for_allocation
        self._lock = threading.RLock()

        self._state = EngineState(
            created_at=_now(),
            last_updated=_now(),
        )
        self._load_state()

        logger.info(
            "♻️  CapitalRecyclingEngine ready | pool=$%.2f | strategies=%s",
            self._state.pool_usd,
            self.strategies,
        )

    # ── Public API ──────────────────────────────────────────────────────────

    def deposit_profit(
        self,
        amount_usd: float,
        source_symbol: str = "PORTFOLIO",
        regime: str = "UNKNOWN",
        note: str = "",
    ) -> float:
        """
        Deposit harvested profit into the recycling pool.

        Parameters
        ----------
        amount_usd : float
            USD amount to add (must be > 0).
        source_symbol : str
            Symbol that generated the profit (for audit trail).
        regime : str
            Current market regime (used by ``allocate()``).
        note : str
            Optional free-text annotation.

        Returns
        -------
        float
            Updated pool balance after deposit.
        """
        if amount_usd <= 0:
            logger.warning("[Recycle] deposit_profit called with non-positive amount: %.2f", amount_usd)
            return self._state.pool_usd

        with self._lock:
            self._state.pool_usd += amount_usd
            self._state.total_deposited_usd += amount_usd

            event = RecycleEvent(
                timestamp=_now(),
                source_symbol=source_symbol,
                amount_usd=amount_usd,
                regime=regime,
                note=note,
            )
            self._state.recycle_events.append(asdict(event))

            # Keep log bounded to last 500 events
            if len(self._state.recycle_events) > 500:
                self._state.recycle_events = self._state.recycle_events[-500:]

            self._state.last_updated = _now()
            self._save_state()

        logger.info(
            "♻️  [Recycle] Deposited $%.2f from %s | pool=$%.2f",
            amount_usd, source_symbol, self._state.pool_usd,
        )
        return self._state.pool_usd

    def allocate(self, regime: str = "UNKNOWN") -> Dict[str, float]:
        """
        Compute per-strategy dollar allocations from the current pool.

        The allocation is a *snapshot* — it does not modify the pool.  Strategies
        draw down their share by calling ``claim_allocation()``.

        Parameters
        ----------
        regime : str
            Current market regime (used to query MetaLearningOptimizer).

        Returns
        -------
        dict
            ``{strategy_name: dollar_amount}`` for every known strategy.
            All values are >= 0.  Returns an empty dict if the pool is below
            the minimum threshold.
        """
        with self._lock:
            pool = self._state.pool_usd

        if pool < self.min_pool_for_allocation:
            logger.debug(
                "[Recycle] Pool $%.2f below minimum $%.2f — skipping allocation.",
                pool, self.min_pool_for_allocation,
            )
            return {s: 0.0 for s in self.strategies}

        weights = self._get_strategy_weights(regime)
        allocations = {s: pool * w for s, w in weights.items()}

        with self._lock:
            self._state.last_allocations = {s: round(v, 4) for s, v in allocations.items()}
            self._state.last_allocation_regime = regime
            self._state.last_allocation_ts = _now()
            self._save_state()

        logger.info(
            "[Recycle] Allocations computed for regime=%s | pool=$%.2f",
            regime, pool,
        )
        for strat, amt in sorted(allocations.items(), key=lambda x: x[1], reverse=True):
            logger.info("  %-22s $%10.2f  (%.1f%%)", strat, amt, (amt / pool * 100) if pool else 0)

        return allocations

    def claim_allocation(
        self,
        strategy: str,
        requested_usd: float,
        regime: str = "UNKNOWN",
        note: str = "",
    ) -> float:
        """
        Claim recycled capital for a strategy.

        The granted amount is ``min(requested_usd, pool_usd)``.  The pool is
        reduced by the granted amount.

        Parameters
        ----------
        strategy : str
            Name of the strategy claiming the capital.
        requested_usd : float
            Dollar amount the strategy wishes to draw.
        regime : str
            Current market regime (for audit trail).
        note : str
            Optional annotation.

        Returns
        -------
        float
            Granted amount (may be less than requested if pool is short).
        """
        if requested_usd <= 0:
            return 0.0

        with self._lock:
            granted = min(requested_usd, max(0.0, self._state.pool_usd))
            self._state.pool_usd -= granted
            self._state.total_claimed_usd += granted

            event = ClaimEvent(
                timestamp=_now(),
                strategy=strategy,
                requested_usd=requested_usd,
                granted_usd=granted,
                regime=regime,
                note=note,
            )
            self._state.claim_events.append(asdict(event))

            # Keep log bounded to last 500 events
            if len(self._state.claim_events) > 500:
                self._state.claim_events = self._state.claim_events[-500:]

            self._state.last_updated = _now()
            self._save_state()

        logger.info(
            "♻️  [Recycle] %s claimed $%.2f (requested $%.2f) | pool=$%.2f",
            strategy, granted, requested_usd, self._state.pool_usd,
        )
        return granted

    def allocate_and_claim(
        self,
        strategy: str,
        regime: str = "UNKNOWN",
        note: str = "",
    ) -> float:
        """
        Convenience helper: compute the strategy's share of the current pool
        and immediately claim it.

        Parameters
        ----------
        strategy : str
            The strategy claiming its recycled-profit share.
        regime : str
            Current market regime.
        note : str
            Optional annotation.

        Returns
        -------
        float
            Dollar amount granted to the strategy.
        """
        allocations = self.allocate(regime=regime)
        share = allocations.get(strategy, 0.0)
        if share <= 0:
            return 0.0
        return self.claim_allocation(strategy, share, regime=regime, note=note)

    def get_pool_balance(self) -> float:
        """Return the current available pool balance in USD."""
        with self._lock:
            return self._state.pool_usd

    def get_status(self) -> Dict[str, Any]:
        """Return a structured status dict for dashboards and APIs."""
        with self._lock:
            s = self._state
            utilisation = (
                s.total_claimed_usd / s.total_deposited_usd
                if s.total_deposited_usd > 0 else 0.0
            )
            return {
                "pool_usd": round(s.pool_usd, 4),
                "total_deposited_usd": round(s.total_deposited_usd, 4),
                "total_claimed_usd": round(s.total_claimed_usd, 4),
                "utilisation_pct": round(utilisation * 100, 2),
                "last_allocations": {k: round(v, 4) for k, v in s.last_allocations.items()},
                "last_allocation_regime": s.last_allocation_regime,
                "last_allocation_ts": s.last_allocation_ts,
                "strategies": self.strategies,
                "recent_deposits": s.recycle_events[-10:],
                "recent_claims": s.claim_events[-10:],
                "created_at": s.created_at,
                "last_updated": s.last_updated,
            }

    def get_report(self) -> str:
        """Return a human-readable text report."""
        with self._lock:
            s = self._state
            utilisation = (
                s.total_claimed_usd / s.total_deposited_usd
                if s.total_deposited_usd > 0 else 0.0
            )
            lines = [
                "=" * 70,
                "  ♻️   CAPITAL RECYCLING ENGINE — STATUS REPORT",
                "=" * 70,
                f"  Pool Balance        : ${s.pool_usd:>12,.2f}",
                f"  Total Deposited     : ${s.total_deposited_usd:>12,.2f}",
                f"  Total Claimed       : ${s.total_claimed_usd:>12,.2f}",
                f"  Utilisation         : {utilisation * 100:>11.1f} %",
                f"  Last Regime         : {s.last_allocation_regime or 'N/A'}",
                f"  Last Allocation     : {s.last_allocation_ts or 'N/A'}",
                "",
                "  Last Computed Allocations:",
            ]
            if s.last_allocations:
                pool = s.pool_usd
                for strat, amt in sorted(s.last_allocations.items(), key=lambda x: x[1], reverse=True):
                    pct = (amt / pool * 100) if pool > 0 else 0.0
                    lines.append(f"    {strat:<22s} ${amt:>10,.2f}  ({pct:>5.1f} %)")
            else:
                lines.append("    (no allocations computed yet)")

            lines += [
                "",
                f"  Recent Deposits ({min(5, len(s.recycle_events))} of {len(s.recycle_events)}):",
            ]
            for ev in s.recycle_events[-5:]:
                lines.append(
                    f"    {ev.get('timestamp', '')[:19]}  "
                    f"{ev.get('source_symbol', ''):>10}  "
                    f"+${ev.get('amount_usd', 0):>8,.2f}  "
                    f"[{ev.get('regime', '')}]"
                )

            lines += [
                "",
                f"  Recent Claims ({min(5, len(s.claim_events))} of {len(s.claim_events)}):",
            ]
            for ev in s.claim_events[-5:]:
                lines.append(
                    f"    {ev.get('timestamp', '')[:19]}  "
                    f"{ev.get('strategy', ''):>22}  "
                    f"${ev.get('granted_usd', 0):>8,.2f}  "
                    f"[{ev.get('regime', '')}]"
                )

            lines.append("=" * 70)
            return "\n".join(lines)

    # ── Internals ────────────────────────────────────────────────────────────

    def _get_strategy_weights(self, regime: str) -> Dict[str, float]:
        """
        Query the best available scorer for normalised strategy weights.

        Priority:
        1. MetaLearningOptimizer (regime-aware, Sharpe-weighted)
        2. SelfLearningStrategyAllocator (simpler EMA-based)
        3. Equal-weight fallback

        Returns normalised weights clipped to [min_allocation_frac, max_allocation_frac].
        """
        # --- attempt MetaLearningOptimizer ---
        try:
            from bot.meta_learning_optimizer import get_meta_learning_optimizer
            opt = get_meta_learning_optimizer()
            raw_weights = opt.get_regime_weights(regime)
            # raw_weights may not include all strategies the recycler knows
            weights = {}
            for s in self.strategies:
                weights[s] = raw_weights.get(s, self.min_allocation_frac)
            return self._normalise_and_clip(weights)
        except Exception as exc:
            logger.debug("[Recycle] MetaLearningOptimizer unavailable (%s), trying SLA.", exc)

        # --- attempt SelfLearningStrategyAllocator ---
        try:
            from bot.self_learning_strategy_allocator import get_self_learning_allocator
            sla = get_self_learning_allocator()
            sla_weights = sla.get_weights()
            weights = {}
            for s in self.strategies:
                weights[s] = sla_weights.get(s, self.min_allocation_frac)
            return self._normalise_and_clip(weights)
        except Exception as exc:
            logger.debug("[Recycle] SelfLearningAllocator unavailable (%s), using equal weights.", exc)

        # --- equal-weight fallback ---
        n = len(self.strategies)
        if n == 0:
            return {}
        equal = 1.0 / n
        return {s: equal for s in self.strategies}

    def _normalise_and_clip(self, weights: Dict[str, float]) -> Dict[str, float]:
        """
        Apply min/max allocation bounds and re-normalise to sum to 1.0.

        Uses iterative clipping (one pass suffices for practical bound values).
        """
        # Clip to bounds
        clipped = {
            s: max(self.min_allocation_frac, min(self.max_allocation_frac, w))
            for s, w in weights.items()
        }
        total = sum(clipped.values()) or 1.0
        normalised = {s: v / total for s, v in clipped.items()}

        # Second clip in case normalisation pushed any weight out of bounds
        clipped2 = {
            s: max(self.min_allocation_frac, min(self.max_allocation_frac, v))
            for s, v in normalised.items()
        }
        total2 = sum(clipped2.values()) or 1.0
        return {s: v / total2 for s, v in clipped2.items()}

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load_state(self) -> None:
        try:
            if os.path.exists(self.state_path):
                with open(self.state_path) as fh:
                    data = json.load(fh)
                self._state = EngineState(
                    pool_usd=data.get("pool_usd", 0.0),
                    total_deposited_usd=data.get("total_deposited_usd", 0.0),
                    total_claimed_usd=data.get("total_claimed_usd", 0.0),
                    recycle_events=data.get("recycle_events", []),
                    claim_events=data.get("claim_events", []),
                    last_allocations=data.get("last_allocations", {}),
                    last_allocation_regime=data.get("last_allocation_regime", ""),
                    last_allocation_ts=data.get("last_allocation_ts", ""),
                    created_at=data.get("created_at", _now()),
                    last_updated=data.get("last_updated", _now()),
                )
                logger.info(
                    "[Recycle] State restored from %s | pool=$%.2f",
                    self.state_path, self._state.pool_usd,
                )
        except Exception as exc:
            logger.warning("[Recycle] Could not load state (%s) — starting fresh.", exc)

    def _save_state(self) -> None:
        """Persist state to JSON (must be called while holding self._lock)."""
        try:
            os.makedirs(os.path.dirname(self.state_path) or ".", exist_ok=True)
            with open(self.state_path, "w") as fh:
                json.dump(asdict(self._state), fh, indent=2)
        except Exception as exc:
            logger.warning("[Recycle] Could not persist state: %s", exc)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_engine_instance: Optional[CapitalRecyclingEngine] = None
_engine_lock = threading.Lock()


def get_capital_recycling_engine(
    state_path: str = "data/capital_recycling_state.json",
    **kwargs: Any,
) -> CapitalRecyclingEngine:
    """Return the process-wide CapitalRecyclingEngine singleton."""
    global _engine_instance
    with _engine_lock:
        if _engine_instance is None:
            _engine_instance = CapitalRecyclingEngine(
                state_path=state_path, **kwargs
            )
    return _engine_instance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    """Return current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# CLI self-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s | %(message)s")

    engine = CapitalRecyclingEngine(state_path="/tmp/cre_test_state.json")

    print("\n--- Depositing profits ---")
    engine.deposit_profit(500.0, source_symbol="BTC-USD", regime="BULL_TRENDING")
    engine.deposit_profit(250.0, source_symbol="ETH-USD", regime="BULL_TRENDING")

    print("\n--- Computing allocations ---")
    allocs = engine.allocate(regime="BULL_TRENDING")
    for s, a in sorted(allocs.items(), key=lambda x: x[1], reverse=True):
        print(f"  {s:<22s} ${a:>8,.2f}")

    print("\n--- Claiming for ApexTrend ---")
    granted = engine.claim_allocation("ApexTrend", 200.0, regime="BULL_TRENDING")
    print(f"  Granted: ${granted:.2f}")

    print("\n--- Full report ---")
    print(engine.get_report())
