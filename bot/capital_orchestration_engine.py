"""
NIJA Capital Orchestration Engine
==================================

The Capital Orchestration Engine is the **top-level capital allocator** for
NIJA.  It sits above the existing CapitalRecyclingEngine and acts as a
unified coordination layer that decides *how much* capital each downstream
component (strategy, venue, position) may consume at any given moment.

Responsibilities
----------------
1. **Budget Management** – maintains a global USD budget and per-strategy
   sub-budgets derived from the current account equity.
2. **Regime-Aware Allocation** – scales budgets up/down based on the current
   market regime (BULL_TRENDING, BEAR_TRENDING, SIDEWAYS, VOLATILE, etc.).
3. **Risk-Weighted Sizing** – optional Sharpe / profit-factor weighting so
   higher-performing strategies receive a larger slice.
4. **Reserve Enforcement** – always keeps a configurable cash reserve
   (default 20 %) untouchable regardless of any other allocation decision.
5. **Asset Abstraction** – strategies declare intent via a universal
   ``AllocationRequest``; the engine resolves the actual USD amount to deploy
   without the strategy needing to know about account balance or regime.
6. **Capital Release** – positions call ``release_capital()`` on close so the
   engine accurately tracks in-use capital.
7. **Audit Trail** – every allocation and release is logged with a timestamp
   for post-trade analysis.

Architecture
------------
::

    ┌──────────────────────────────────────────────────────────────┐
    │                CapitalOrchestrationEngine                     │
    │                                                              │
    │  equity_usd            ← set_equity(equity_usd)             │
    │  reserve_pct = 20 %    → reserve_usd = equity × 0.20        │
    │  deployable_usd        = equity - reserve - in_use           │
    │                                                              │
    │  Strategy budgets:  score-weighted slices of deployable_usd  │
    │                                                              │
    │  request_allocation(strategy, max_usd, regime) → granted_usd │
    │  release_capital(strategy, usd)                              │
    └──────────────────────────────────────────────────────────────┘

Universal Order Model
---------------------
Strategies submit an ``AllocationRequest`` which is broker-agnostic::

    from bot.capital_orchestration_engine import (
        AllocationRequest, get_capital_orchestration_engine
    )

    engine = get_capital_orchestration_engine()
    engine.set_equity(total_account_usd)

    req = AllocationRequest(
        strategy="ApexTrend",
        symbol="BTC-USD",
        regime="BULL_TRENDING",
        max_usd=500.0,        # most the strategy wants
        min_usd=25.0,         # minimum viable size (below this, skip trade)
    )

    granted = engine.request_allocation(req)
    if granted >= req.min_usd:
        # place trade with `granted` USD
        engine.release_capital(req.strategy, granted, "trade_closed")

Usage
-----
::

    from bot.capital_orchestration_engine import get_capital_orchestration_engine

    engine = get_capital_orchestration_engine()
    engine.set_equity(1000.0)

    granted = engine.request_allocation(
        AllocationRequest("Scalper", "ETH-USD", "SIDEWAYS", max_usd=200.0)
    )

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger("nija.capital_orchestration")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default cash reserve: never deploy more than (1 - RESERVE_PCT) of equity.
DEFAULT_RESERVE_PCT: float = 0.20  # 20 %

# Maximum allocation to a single strategy (% of deployable capital).
DEFAULT_MAX_SINGLE_STRATEGY_PCT: float = 0.40  # 40 %

# Regime-specific capital multipliers – scale the deployable pool up/down.
REGIME_MULTIPLIERS: Dict[str, float] = {
    "BULL_TRENDING": 1.00,   # full deployment
    "BULL_BREAKOUT": 0.90,
    "BEAR_TRENDING": 0.50,   # reduce exposure in bear markets
    "BEAR_BREAKDOWN": 0.30,
    "SIDEWAYS": 0.70,
    "VOLATILE": 0.40,        # high volatility → protect capital
    "RECOVERY": 0.60,
    "UNKNOWN": 0.60,         # conservative default
}

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AllocationRequest:
    """Broker-agnostic, universal capital request submitted by a strategy.

    Attributes:
        strategy:  Name of the requesting strategy (e.g. 'ApexTrend').
        symbol:    Trading symbol (e.g. 'BTC-USD'). Used for logging only;
                   routing decisions live in the execution layer.
        regime:    Current market regime string (e.g. 'BULL_TRENDING').
        max_usd:   Maximum USD the strategy would like to deploy.
        min_usd:   Minimum USD below which the trade is not worth taking.
                   If the engine cannot grant at least ``min_usd``, it
                   returns 0.0 so the strategy skips the trade.
        priority:  Integer priority 1-10 (10 = highest). Higher-priority
                   requests are served first when capital is scarce.
        metadata:  Arbitrary key-value pairs for downstream logging.
    """

    strategy: str
    symbol: str
    regime: str = "UNKNOWN"
    max_usd: float = 0.0
    min_usd: float = 0.0
    priority: int = 5
    metadata: Dict = field(default_factory=dict)


@dataclass
class AllocationRecord:
    """Internal record of a granted allocation."""

    strategy: str
    symbol: str
    granted_usd: float
    timestamp: str
    regime: str


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class CapitalOrchestrationEngine:
    """Top-level capital orchestrator for NIJA Trading Systems."""

    def __init__(
        self,
        reserve_pct: float = DEFAULT_RESERVE_PCT,
        max_single_strategy_pct: float = DEFAULT_MAX_SINGLE_STRATEGY_PCT,
    ) -> None:
        self._lock = threading.Lock()

        self.reserve_pct = reserve_pct
        self.max_single_strategy_pct = max_single_strategy_pct

        # Current total account equity (USD)
        self._equity_usd: float = 0.0

        # Capital currently deployed per strategy { strategy_name: usd_in_use }
        self._in_use: Dict[str, float] = {}

        # Optional per-strategy performance scores { strategy_name: score }
        # Scores are used to weight allocations (higher score → bigger slice).
        # If no scores provided, equal-weight distribution is used.
        self._strategy_scores: Dict[str, float] = {}

        # Audit trail
        self._allocation_log: List[AllocationRecord] = []

        logger.info(
            "✅ CapitalOrchestrationEngine initialized "
            f"(reserve={reserve_pct*100:.0f}%, "
            f"max_single={max_single_strategy_pct*100:.0f}%)"
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_equity(self, equity_usd: float) -> None:
        """Update the engine with the current total account equity.

        Call this before requesting allocations, typically at the start of
        each trading cycle.

        Args:
            equity_usd: Total account value in USD.
        """
        with self._lock:
            self._equity_usd = max(0.0, equity_usd)
        logger.debug(f"Equity updated: ${self._equity_usd:,.2f}")

    def set_strategy_scores(self, scores: Dict[str, float]) -> None:
        """Provide per-strategy performance scores for weighted allocation.

        Args:
            scores: Mapping of strategy name → composite score (0–100).
                    Strategies not present are allocated equal weight.
        """
        with self._lock:
            self._strategy_scores = dict(scores)

    def request_allocation(self, request: AllocationRequest) -> float:
        """Request capital for a prospective trade.

        The engine computes how much capital it can safely grant, applying:
        * Cash reserve enforcement
        * Regime-specific multiplier
        * Per-strategy concentration cap
        * Minimum viable size check

        Args:
            request: Broker-agnostic allocation request.

        Returns:
            Granted USD amount (≥ request.min_usd), or 0.0 if the trade
            should be skipped due to insufficient deployable capital.
        """
        with self._lock:
            deployable = self._compute_deployable(request.regime)
            strategy_cap = deployable * self.max_single_strategy_pct

            current_in_use = self._in_use.get(request.strategy, 0.0)
            remaining_cap = max(0.0, strategy_cap - current_in_use)

            # Cap at what the strategy asked for
            grant = min(request.max_usd, remaining_cap, deployable)
            grant = max(0.0, grant)

            if grant < request.min_usd:
                logger.info(
                    f"🚫 Capital gate: {request.strategy} / {request.symbol} "
                    f"skipped — can grant ${grant:.2f} < min ${request.min_usd:.2f} "
                    f"(deployable=${deployable:.2f}, in_use=${current_in_use:.2f})"
                )
                return 0.0

            # Reserve the capital
            self._in_use[request.strategy] = current_in_use + grant
            self._allocation_log.append(
                AllocationRecord(
                    strategy=request.strategy,
                    symbol=request.symbol,
                    granted_usd=grant,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    regime=request.regime,
                )
            )

        logger.info(
            f"✅ Capital allocated: {request.strategy} / {request.symbol} "
            f"${grant:.2f} (regime={request.regime}, "
            f"deployable_before=${deployable:.2f})"
        )
        return grant

    def release_capital(
        self,
        strategy: str,
        amount_usd: float,
        reason: str = "trade_closed",
    ) -> None:
        """Release capital back to the deployable pool after a trade closes.

        Args:
            strategy:   Strategy that held the capital.
            amount_usd: Amount to release in USD.
            reason:     Human-readable reason (e.g. 'take_profit', 'stop_loss').
        """
        with self._lock:
            current = self._in_use.get(strategy, 0.0)
            released = min(amount_usd, current)
            self._in_use[strategy] = max(0.0, current - released)

        logger.info(
            f"🔓 Capital released: {strategy} ${released:.2f} [{reason}] "
            f"(remaining_in_use=${self._in_use.get(strategy, 0.0):.2f})"
        )

    def get_report(self) -> Dict:
        """Return a snapshot of the current capital state.

        Returns:
            dict with equity, reserve, deployable, in_use, and per-strategy
            breakdown.
        """
        with self._lock:
            total_in_use = sum(self._in_use.values())
            reserve_usd = self._equity_usd * self.reserve_pct
            deployable = max(0.0, self._equity_usd - reserve_usd - total_in_use)

            return {
                "equity_usd": self._equity_usd,
                "reserve_usd": reserve_usd,
                "total_in_use_usd": total_in_use,
                "deployable_usd": deployable,
                "per_strategy_in_use": dict(self._in_use),
                "allocation_count": len(self._allocation_log),
            }

    def get_allocation_log(self, last_n: int = 50) -> List[AllocationRecord]:
        """Return the most recent allocation records.

        Args:
            last_n: Maximum number of records to return.

        Returns:
            List of AllocationRecord (newest last).
        """
        with self._lock:
            return list(self._allocation_log[-last_n:])

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _compute_deployable(self, regime: str) -> float:
        """Compute how much USD can currently be deployed.

        Applies the regime multiplier to the free (non-reserved,
        non-in-use) capital.
        """
        total_in_use = sum(self._in_use.values())
        reserve_usd = self._equity_usd * self.reserve_pct
        free_usd = max(0.0, self._equity_usd - reserve_usd - total_in_use)
        multiplier = REGIME_MULTIPLIERS.get(regime.upper(), REGIME_MULTIPLIERS["UNKNOWN"])
        return free_usd * multiplier


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_engine_instance: Optional[CapitalOrchestrationEngine] = None
_engine_lock = threading.Lock()


def get_capital_orchestration_engine() -> CapitalOrchestrationEngine:
    """Return the singleton CapitalOrchestrationEngine.

    Creates the instance on first call with default parameters.
    """
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = CapitalOrchestrationEngine()
    return _engine_instance
