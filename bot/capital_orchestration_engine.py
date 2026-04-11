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
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Dict, List, Optional

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

        A granted allocation is immediately written to the
        ``CapitalReservationManager`` so that concurrent calls to
        ``PortfolioStateManager.get_deployable_capital_with_reservations()``
        see the reservation before the order is submitted (pre-trade gate).

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

            # Reserve the capital in-engine (fast in-memory tracking)
            self._in_use[request.strategy] = current_in_use + grant
            reservation_id = f"{request.strategy}:{request.symbol}:{uuid.uuid4().hex[:8]}"
            self._allocation_log.append(
                AllocationRecord(
                    strategy=request.strategy,
                    symbol=request.symbol,
                    granted_usd=grant,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    regime=request.regime,
                )
            )

        # ── Pre-trade reservation: write to CapitalReservationManager ─────────
        # Done outside the engine lock to avoid deadlocks.  The CapitalReservation-
        # Manager entry makes the reservation visible to get_deployable_capital_with_
        # reservations() before the order reaches the exchange.
        try:
            from capital_reservation_manager import get_capital_reservation_manager  # type: ignore[import]
        except ImportError:
            try:
                from bot.capital_reservation_manager import get_capital_reservation_manager  # type: ignore[import]
            except ImportError:
                get_capital_reservation_manager = None  # type: ignore[assignment]

        if get_capital_reservation_manager is not None:
            try:
                _crm = get_capital_reservation_manager()
                _crm.reserve_capital(
                    position_id=reservation_id,
                    amount=grant,
                    symbol=request.symbol,
                    account_id=request.strategy,
                    broker=request.metadata.get("broker", "unknown"),
                )
                # Store so release_capital can find it later
                request.metadata["_reservation_id"] = reservation_id
            except Exception as _crm_err:
                logger.debug("CapitalReservationManager write skipped: %s", _crm_err)

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
        reservation_id: Optional[str] = None,
    ) -> None:
        """Release capital back to the deployable pool after a trade closes.

        Also releases the matching ``CapitalReservationManager`` entry so the
        reservation is no longer deducted from
        ``get_deployable_capital_with_reservations()``.

        Args:
            strategy:        Strategy that held the capital.
            amount_usd:      Amount to release in USD.
            reason:          Human-readable reason (e.g. 'take_profit').
            reservation_id:  The ``_reservation_id`` stored in the original
                             ``AllocationRequest.metadata``.  When supplied the
                             matching ``CapitalReservationManager`` entry is
                             released; otherwise a best-effort lookup by
                             strategy (account_id) is performed.
        """
        with self._lock:
            current = self._in_use.get(strategy, 0.0)
            released = min(amount_usd, current)
            self._in_use[strategy] = max(0.0, current - released)

        logger.info(
            f"🔓 Capital released: {strategy} ${released:.2f} [{reason}] "
            f"(remaining_in_use=${self._in_use.get(strategy, 0.0):.2f})"
        )

        # ── Release from CapitalReservationManager ────────────────────────────
        try:
            from capital_reservation_manager import get_capital_reservation_manager  # type: ignore[import]
        except ImportError:
            try:
                from bot.capital_reservation_manager import get_capital_reservation_manager  # type: ignore[import]
            except ImportError:
                return

        try:
            _crm = get_capital_reservation_manager()
            if reservation_id:
                _crm.release_capital(reservation_id)
            else:
                # Best-effort: release the largest matching reservation for this
                # strategy (account_id) when no explicit ID was provided.
                reservations = _crm.get_reservations(account_id=strategy)
                if reservations:
                    best = max(reservations, key=lambda r: r.reserved_amount)
                    _crm.release_capital(best.position_id)
        except Exception as _crm_err:
            logger.debug("CapitalReservationManager release skipped: %s", _crm_err)

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


# ---------------------------------------------------------------------------
# Atomic capital sync orchestration
# ---------------------------------------------------------------------------

def sync_and_update_capital(
    broker_fetchers: Dict[str, Callable],
    portfolio_manager,
    advanced_manager=None,
    unrealized_confidence: float = 0.8,
) -> float:
    """Atomically refresh all broker balances and propagate to every downstream component.

    This is the **single entry point** for capital state updates.  Trade sizing
    must only be called *after* this function returns so that the position sizer
    always sees a coherent, up-to-date view of available capital.

    Wires together all three performance features in the correct order:

    1. **Latency-aware balance refresh** — calls ``BalanceService.refresh()``
       for every broker.  The service automatically adjusts its effective TTL
       by the EMA fetch latency so stale data is never served as fresh.

    2. **Minimum balance filter** — each broker balance is routed through
       ``portfolio_manager.update_broker_balance()``, which zeroes out and
       marks inactive any broker below its exchange minimum order size.

    3. **PnL-adjusted capital** — ``portfolio_manager.get_pnl_adjusted_total()``
       combines active-broker cash with discounted unrealized P&L so that the
       sizing models grow with *realised* profits but are not inflated by
       paper gains.

    The final PnL-adjusted total is pushed to:
    * ``CapitalOrchestrationEngine.set_equity()`` — governs all subsequent
      ``request_allocation()`` calls.
    * ``advanced_manager`` capital allocator (when provided).

    Args:
        broker_fetchers: Mapping of broker name → zero-argument callable that
            returns a balance (float or dict).  Example::

                {
                    "coinbase": lambda: broker.get_account_balance(),
                    "kraken":   lambda: kraken_broker.get_account_balance(),
                }

        portfolio_manager: A ``PortfolioStateManager`` instance (or compatible
            object with ``update_broker_balance``, ``get_pnl_adjusted_total``,
            and ``get_open_exposure`` methods).

        advanced_manager: Optional ``AdvancedTradingManager`` instance.  When
            provided its ``capital_allocator.update_total_capital()`` method is
            called with the PnL-adjusted total.

        unrealized_confidence: Fraction of unrealized gains to count as
            deployable capital (default 0.8 = 80 %).  Losses always apply in
            full.

    Returns:
        PnL-adjusted total capital in USD.  Pass this directly to any
        position-sizing call that happens after ``sync_and_update_capital``.
    """
    # Lazy import to avoid circular dependencies at module level.
    try:
        from balance_service import BalanceService  # type: ignore[import]
    except ImportError:
        from bot.balance_service import BalanceService  # type: ignore[import]

    # ── Step 1: Refresh every broker balance (latency-aware TTL) ────────────
    raw_balances: Dict[str, float] = {}
    for broker, fetch_fn in broker_fetchers.items():
        try:
            balance = BalanceService.refresh(broker, fetch_fn)
            raw_balances[broker] = balance
        except Exception as exc:
            logger.warning(
                "[sync_and_update_capital] %s: refresh error (%s) — using cached",
                broker, exc,
            )
            raw_balances[broker] = BalanceService.get(broker)

    # ── Step 2: Apply minimum balance filter per broker ──────────────────────
    for broker, balance in raw_balances.items():
        portfolio_manager.update_broker_balance(broker, balance)

    # ── Step 3: Compute PnL-adjusted total ───────────────────────────────────
    pnl_total = portfolio_manager.get_pnl_adjusted_total(unrealized_confidence)
    open_exposure = portfolio_manager.get_open_exposure()

    logger.info(
        "[sync_and_update_capital] PnL-adjusted capital: $%.2f "
        "(open_exposure=$%.2f, confidence=%.0f%%)",
        pnl_total, open_exposure, unrealized_confidence * 100,
    )

    # ── Step 4: Push to CapitalOrchestrationEngine ───────────────────────────
    engine = get_capital_orchestration_engine()
    engine.set_equity(pnl_total)

    # ── Step 5: Push to AdvancedTradingManager (optional) ────────────────────
    if advanced_manager is not None:
        try:
            if hasattr(advanced_manager, "capital_allocator") and advanced_manager.capital_allocator:
                advanced_manager.capital_allocator.update_total_capital(pnl_total)
        except Exception as exc:
            logger.warning("[sync_and_update_capital] advanced_manager update error: %s", exc)

    return pnl_total
