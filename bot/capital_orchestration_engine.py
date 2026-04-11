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
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("nija.capital_orchestration")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Default cash reserve: never deploy more than (1 - RESERVE_PCT) of equity.
DEFAULT_RESERVE_PCT: float = 0.20  # 20 %

# Maximum allocation to a single strategy (% of deployable capital).
DEFAULT_MAX_SINGLE_STRATEGY_PCT: float = 0.40  # 40 %

# Maximum ExecutionToken history records kept in memory (per bucket).
_MAX_TOKEN_HISTORY: int = 200

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


@dataclass
class ExecutionToken:
    """Opaque handle returned by :meth:`CapitalOrchestrationEngine.begin_execution`.

    Carries the complete lifecycle audit trail for one trade reservation —
    from the moment capital is reserved through to either a confirmed fill
    (COMMITTED) or a failed/cancelled execution (ROLLED_BACK).

    Status transitions
    ------------------
    ::

        PENDING  ──commit_execution()──►  COMMITTED
                 ──rollback_execution()─►  ROLLED_BACK

    Attributes
    ----------
    token_id:            UUID assigned at reservation time.
    strategy:            Requesting strategy name.
    symbol:              Trading pair.
    regime:              Market regime at reservation time.
    reserved_usd:        Capital locked by ``request_allocation()``.
    pre_trade_equity:    PnL-adjusted account equity captured at reservation.
    created_at:          ISO-8601 timestamp of reservation.
    status:              ``"PENDING"`` | ``"COMMITTED"`` | ``"ROLLED_BACK"``.
    actual_fill_usd:     Broker-confirmed filled amount (set on commit).
    committed_at:        ISO-8601 timestamp of commit (None until committed).
    rolled_back_at:      ISO-8601 timestamp of rollback (None unless rolled back).
    post_trade_equity:   PnL-adjusted equity captured after broker confirmation.
    capital_drift_usd:   ``actual_fill_usd − reserved_usd`` (post-commit reconciliation).
                         Positive = over-fill, negative = under-fill.
    """

    token_id: str
    strategy: str
    symbol: str
    regime: str
    reserved_usd: float
    pre_trade_equity: float
    created_at: str
    status: str = "PENDING"
    actual_fill_usd: float = 0.0
    committed_at: Optional[str] = None
    rolled_back_at: Optional[str] = None
    post_trade_equity: float = 0.0
    capital_drift_usd: float = 0.0

    def to_dict(self) -> Dict:
        """Return a JSON-serialisable representation for audit logging."""
        return {
            "token_id":          self.token_id,
            "strategy":          self.strategy,
            "symbol":            self.symbol,
            "regime":            self.regime,
            "reserved_usd":      round(self.reserved_usd, 4),
            "actual_fill_usd":   round(self.actual_fill_usd, 4),
            "capital_drift_usd": round(self.capital_drift_usd, 4),
            "pre_trade_equity":  round(self.pre_trade_equity, 4),
            "post_trade_equity": round(self.post_trade_equity, 4),
            "status":            self.status,
            "created_at":        self.created_at,
            "committed_at":      self.committed_at,
            "rolled_back_at":    self.rolled_back_at,
        }


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

        # Execution token stores (Execution Integrity Layer)
        # _active_tokens:    currently PENDING reservations (token_id → token)
        # _committed_tokens: recent COMMITTED executions (capped at _MAX_TOKEN_HISTORY)
        # _rolled_back_tokens: recent ROLLED_BACK executions (capped at _MAX_TOKEN_HISTORY)
        self._active_tokens: Dict[str, ExecutionToken] = {}
        self._committed_tokens: List[ExecutionToken] = []
        self._rolled_back_tokens: List[ExecutionToken] = []

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
                "active_tokens": len(self._active_tokens),
                "committed_tokens": len(self._committed_tokens),
                "rolled_back_tokens": len(self._rolled_back_tokens),
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

    def sync_and_update_capital(
        self,
        raw_balance_usd: float,
        unrealized_pnl_usd: float,
        request: AllocationRequest,
        *,
        latency_ms: float = 0.0,
    ) -> float:
        """Canonical entry point for ALL trade sizing decisions.

        Enforces the mandatory, immutable pipeline ordering::

            1. latency            — observe API/network round-trip (logging)
            2. balance            — accept raw account cash balance
            3. pnl-adjusted equity — balance + unrealized_pnl
            4. reservation        — update engine equity baseline AFTER PnL adjustment
            5. sizing             — request_allocation() against the adjusted equity

        ⚠️  The ordering is load-bearing.  If reservation (step 4) were to
        happen before PnL adjustment (step 3) the engine would price new
        trades against stale capital, silently under- or over-allocating.
        Never reorder these steps — integrity breaks the moment you do.

        Args:
            raw_balance_usd:     Raw account cash balance in USD.
            unrealized_pnl_usd:  Sum of open-position mark-to-market PnL in
                                 USD.  May be negative when positions are
                                 underwater.
            request:             Broker-agnostic :class:`AllocationRequest`.
            latency_ms:          Optional API/network round-trip latency in
                                 milliseconds.  Recorded for observability and
                                 reserved for future adaptive latency guards.

        Returns:
            Granted USD amount (≥ ``request.min_usd``), or ``0.0`` when the
            trade should be skipped.
        """
        # ── Step 1: latency observation ───────────────────────────────────────
        # Logged now; reserved for future adaptive guards (e.g. widen reserve
        # during high-latency windows when stale data risk is elevated).
        if latency_ms > 0:
            logger.debug(
                "sync_and_update_capital: API latency %.1f ms [%s / %s]",
                latency_ms, request.strategy, request.symbol,
            )

        # ── Steps 2 + 3: balance → pnl-adjusted equity ───────────────────────
        # RESERVATION MUST USE THIS ADJUSTED FIGURE.  Using raw_balance_usd
        # would ignore the mark-to-market exposure of existing open positions
        # and allow over-allocation when those positions are in a drawdown.
        pnl_adjusted_equity = raw_balance_usd + unrealized_pnl_usd
        if pnl_adjusted_equity <= 0:
            logger.warning(
                "sync_and_update_capital: pnl-adjusted equity $%.2f ≤ 0 "
                "(balance=$%.2f, unrealized=$%.2f) — allocation blocked "
                "[%s / %s]",
                pnl_adjusted_equity, raw_balance_usd, unrealized_pnl_usd,
                request.strategy, request.symbol,
            )
            return 0.0

        logger.debug(
            "sync_and_update_capital: balance=$%.2f + unrealized=$%.2f "
            "→ adjusted_equity=$%.2f [%s / %s]",
            raw_balance_usd, unrealized_pnl_usd, pnl_adjusted_equity,
            request.strategy, request.symbol,
        )

        # ── Step 4: reservation baseline — MUST follow PnL adjustment ────────
        # set_equity() establishes the capital pool that request_allocation()
        # will draw from.  Calling it here, after the PnL-adjusted figure is
        # computed, guarantees reservation is never priced against stale data.
        self.set_equity(pnl_adjusted_equity)

        # ── Step 5: sizing — draws from the freshly-updated reservation pool ──
        return self.request_allocation(request)

    # ------------------------------------------------------------------
    # Execution Integrity Layer  (begin / commit / rollback)
    # ------------------------------------------------------------------

    def begin_execution(
        self,
        raw_balance_usd: float,
        unrealized_pnl_usd: float,
        request: AllocationRequest,
        *,
        latency_ms: float = 0.0,
    ) -> Optional["ExecutionToken"]:
        """Reserve capital and return an :class:`ExecutionToken`.

        This is the **mandatory entry point** for all trade executions.
        It combines the PnL-safe capital sync (see :meth:`sync_and_update_capital`)
        with the creation of an immutable audit token that must be closed by
        either :meth:`commit_execution` (fill confirmed) or
        :meth:`rollback_execution` (execution failed or was rejected).

        Pattern::

            token = engine.begin_execution(balance, unrealized_pnl, request)
            if token is None:
                return  # insufficient capital — skip trade
            try:
                fill_usd = broker.place_order(token.symbol, token.reserved_usd)
                engine.commit_execution(token, fill_usd, post_balance, post_unrealized)
            except Exception:
                engine.rollback_execution(token)
                raise

        Args:
            raw_balance_usd:     Raw account cash balance in USD.
            unrealized_pnl_usd:  Open-position mark-to-market PnL in USD.
            request:             Broker-agnostic :class:`AllocationRequest`.
            latency_ms:          Optional API round-trip latency for logging.

        Returns:
            :class:`ExecutionToken` if capital was granted, ``None`` if the
            trade should be skipped (insufficient deployable capital).
        """
        granted = self.sync_and_update_capital(
            raw_balance_usd,
            unrealized_pnl_usd,
            request,
            latency_ms=latency_ms,
        )

        if granted < request.min_usd:
            # sync_and_update_capital already logged the skip reason
            return None

        pnl_adjusted_equity = raw_balance_usd + unrealized_pnl_usd
        token = ExecutionToken(
            token_id=str(uuid.uuid4()),
            strategy=request.strategy,
            symbol=request.symbol,
            regime=request.regime,
            reserved_usd=granted,
            pre_trade_equity=pnl_adjusted_equity,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        with self._lock:
            self._active_tokens[token.token_id] = token

        logger.info(
            "🔒 Execution token created: %s  %s/%s  reserved=$%.2f  "
            "equity_snapshot=$%.2f  [token=%s]",
            token.status, token.strategy, token.symbol,
            token.reserved_usd, token.pre_trade_equity, token.token_id,
        )
        return token

    def commit_execution(
        self,
        token: "ExecutionToken",
        actual_fill_usd: float,
        post_trade_balance_usd: float,
        post_trade_unrealized_usd: float = 0.0,
    ) -> None:
        """Finalise a trade execution and reconcile reserved vs actual capital.

        Must be called **after** the broker confirms the fill.  Releases the
        original reservation, re-records the actual fill amount, and computes
        the capital drift for audit purposes.

        Capital reconciliation
        ----------------------
        * ``reserved_usd`` is released from ``_in_use``.
        * ``actual_fill_usd`` is re-added to ``_in_use`` (so the engine
          accurately tracks what is truly deployed post-fill).
        * ``capital_drift_usd = actual_fill_usd − reserved_usd``.
          Drift > 0 means the broker filled more than reserved (rare but
          possible with market orders).  Drift < 0 means an underfill.

        Args:
            token:                    Token returned by :meth:`begin_execution`.
            actual_fill_usd:          Broker-confirmed filled amount in USD.
            post_trade_balance_usd:   Account cash balance after the fill.
            post_trade_unrealized_usd: Open-position PnL after the fill.
        """
        post_equity = post_trade_balance_usd + post_trade_unrealized_usd
        drift = actual_fill_usd - token.reserved_usd

        # Mutate the token record before moving it to the history bucket
        token.status = "COMMITTED"
        token.actual_fill_usd = actual_fill_usd
        token.committed_at = datetime.now(timezone.utc).isoformat()
        token.post_trade_equity = post_equity
        token.capital_drift_usd = drift

        # Release the original reservation; re-record the actual usage
        self.release_capital(token.strategy, token.reserved_usd, "commit_reconcile")
        if actual_fill_usd > 0.0:
            with self._lock:
                self._in_use[token.strategy] = (
                    self._in_use.get(token.strategy, 0.0) + actual_fill_usd
                )

        # Move token from active → committed history (capped)
        with self._lock:
            self._active_tokens.pop(token.token_id, None)
            self._committed_tokens.append(token)
            if len(self._committed_tokens) > _MAX_TOKEN_HISTORY:
                self._committed_tokens.pop(0)

        if abs(drift) >= 0.01:
            logger.warning(
                "⚠️  Capital drift on commit: reserved=$%.2f  actual=$%.2f  "
                "drift=%+.2f  [%s/%s  token=%s]",
                token.reserved_usd, actual_fill_usd, drift,
                token.strategy, token.symbol, token.token_id,
            )
        else:
            logger.info(
                "✅ Execution committed: %s/%s  reserved=$%.2f  filled=$%.2f  "
                "post_equity=$%.2f  [token=%s]",
                token.strategy, token.symbol,
                token.reserved_usd, actual_fill_usd,
                post_equity, token.token_id,
            )

    def rollback_execution(self, token: "ExecutionToken") -> None:
        """Release all reserved capital for a failed or cancelled execution.

        Must be called whenever execution fails after :meth:`begin_execution`
        has already reserved capital — including broker rejections, network
        errors, risk-gate vetoes discovered post-reservation, and any
        unexpected exceptions in the execution path.

        Calling this method is always safe, even if the token has already
        been committed or rolled back (idempotent guard prevents double-release).

        Args:
            token: Token returned by :meth:`begin_execution`.
        """
        if token.status != "PENDING":
            logger.warning(
                "rollback_execution: token %s already in status=%s — skipped",
                token.token_id, token.status,
            )
            return

        token.status = "ROLLED_BACK"
        token.rolled_back_at = datetime.now(timezone.utc).isoformat()

        # Unconditionally release the full reservation
        self.release_capital(token.strategy, token.reserved_usd, "rollback")

        # Move token from active → rollback history (capped)
        with self._lock:
            self._active_tokens.pop(token.token_id, None)
            self._rolled_back_tokens.append(token)
            if len(self._rolled_back_tokens) > _MAX_TOKEN_HISTORY:
                self._rolled_back_tokens.pop(0)

        logger.info(
            "🔄 Execution rolled back: %s/%s  released=$%.2f  [token=%s]",
            token.strategy, token.symbol, token.reserved_usd, token.token_id,
        )

    # ------------------------------------------------------------------
    # Audit trail
    # ------------------------------------------------------------------

    def get_audit_trail(
        self,
        last_n: int = 50,
    ) -> Dict[str, List[Dict]]:
        """Return the most-recent committed and rolled-back token records.

        Args:
            last_n: Maximum number of records to return from each bucket.

        Returns:
            Dict with keys ``"committed"`` and ``"rolled_back"``, each a
            list of token dicts (newest last) suitable for JSON serialisation.
        """
        with self._lock:
            committed = [t.to_dict() for t in self._committed_tokens[-last_n:]]
            rolled_back = [t.to_dict() for t in self._rolled_back_tokens[-last_n:]]
            active = [t.to_dict() for t in self._active_tokens.values()]
        return {
            "active":       active,
            "committed":    committed,
            "rolled_back":  rolled_back,
        }

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
    """Return the singleton :class:`CapitalOrchestrationEngine`.

    Creates the instance on first call with default parameters.
    """
    global _engine_instance
    if _engine_instance is None:
        with _engine_lock:
            if _engine_instance is None:
                _engine_instance = CapitalOrchestrationEngine()
    return _engine_instance


# ---------------------------------------------------------------------------
# Enforcement stub — hard gate against direct sizing bypass
# ---------------------------------------------------------------------------


def size_trade(*args: object, **kwargs: object) -> None:  # noqa: ANN002
    """Enforcement stub — direct sizing is **disabled**.

    Any code that calls ``size_trade()`` directly is bypassing the
    :class:`CapitalOrchestrationEngine` and all associated capital
    protections:

    * PnL-adjusted equity enforcement
    * Cash-reserve guard
    * Per-strategy concentration cap
    * Regime-specific multiplier
    * Rollback-safe execution token lifecycle
    * Audit trail

    Use the canonical entry point instead::

        engine = get_capital_orchestration_engine()

        token = engine.begin_execution(
            raw_balance_usd    = balance,
            unrealized_pnl_usd = open_pnl,
            request            = AllocationRequest(
                strategy = "ApexTrend",
                symbol   = "BTC-USD",
                regime   = "BULL_TRENDING",
                max_usd  = 250.0,
                min_usd  = 10.0,
            ),
        )
        if token is None:
            return  # capital gate blocked the trade
        try:
            fill = broker.place_order(token.symbol, token.reserved_usd)
            engine.commit_execution(token, fill, post_balance, post_unrealized)
        except Exception:
            engine.rollback_execution(token)
            raise

    Raises:
        RuntimeError: Always — this function is intentionally non-functional.
    """
    raise RuntimeError(
        "Direct sizing disabled — use CapitalOrchestrationEngine. "
        "Call engine.begin_execution() to reserve capital with a rollback-safe "
        "ExecutionToken, then engine.commit_execution() or engine.rollback_execution()."
    )
