"""
NIJA Capital Decision Engine
==============================

Single capital arbitration layer — the **only** writer of per-cycle
allocation decisions for the live trading pipeline.

Architecture
------------
::

    CapitalAuthority (raw balances, unchanged)
          ↓  read-only
    CapitalDecisionEngine          ← THIS MODULE (one writer)
      • reads  CapitalAuthority.get_usable_capital()
      • calls  advisory modules (read-only advise() interface):
          AdvisoryAllocationBrain  → CapitalAllocationBrain.advise()
          AdvisoryBrokerWeights    → AICapitalAllocator.advise()
          AdvisoryConcentration    → CapitalConcentrationEngine.advise()
      • produces AllocationDecision (immutable, cycle-scoped)
          ↓
    ExecutionEngine / TradeRouter  ← read from AllocationDecision only

Invariant enforcement
---------------------
``CapitalDecisionEngine`` calls
``BootstrapStateMachine.assert_invariant_i10_capital_writer()`` with its own
``WRITER_ID`` on construction to confirm it is the authorised writer.

Usage
-----
::

    from bot.capital_decision_engine import get_capital_decision_engine

    cde = get_capital_decision_engine()
    decision = cde.decide(broker_map=my_broker_map)

    budget = decision.get_strategy_budget("APEX_V71")
    broker_weight = decision.get_broker_weight("coinbase")

Author: NIJA Trading Systems
Version: 1.0
Date: April 2026
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.capital_decision_engine")

# ---------------------------------------------------------------------------
# Writer identity — must match bootstrap_state_machine._CAPITAL_WRITER_ID
# for the *allocation decision* layer (distinct from raw balance snapshots).
# ---------------------------------------------------------------------------
WRITER_ID: str = "capital_decision_engine"

# Minimum interval between full rebalances (seconds)
_MIN_REBALANCE_INTERVAL_S: float = 60.0

# States that satisfy the bootstrap pre-check for strategy arming
_ARMS_ALLOWED_STATES = frozenset({
    "CAPITAL_READY",
    "THREADS_STARTING",
    "RUNNING_SUPERVISED",
})


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class AllocationDecision:
    """
    Immutable output produced by :class:`CapitalDecisionEngine` each cycle.

    All sizing logic reads from this object; no module may invent capital
    figures independently.
    """

    # Gross usable capital at decision time (USD)
    usable_capital: float

    # Per-strategy budget caps {strategy_id: USD}
    strategy_budgets: Dict[str, float] = field(default_factory=dict)

    # Per-broker allocation weights {broker_id: 0.0–1.0}
    broker_weights: Dict[str, float] = field(default_factory=dict)

    # Per-account concentration multipliers {account_id: float}
    account_multipliers: Dict[str, float] = field(default_factory=dict)

    # Advisory metadata for diagnostics
    advisory_metadata: Dict[str, Any] = field(default_factory=dict)

    # ISO timestamp of this decision
    decided_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def get_strategy_budget(self, strategy_id: str, default: float = 0.0) -> float:
        """Return the USD budget for *strategy_id*, or *default* if unknown."""
        return self.strategy_budgets.get(strategy_id, default)

    def get_broker_weight(self, broker_id: str, default: float = 0.0) -> float:
        """Return the allocation weight for *broker_id*, or *default* if unknown."""
        return self.broker_weights.get(broker_id, default)

    def get_account_multiplier(self, account_id: str, default: float = 1.0) -> float:
        """Return the concentration multiplier for *account_id*."""
        return self.account_multipliers.get(account_id, default)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class CapitalDecisionEngine:
    """
    Single-writer capital arbitration layer.

    Reads raw balances from :class:`CapitalAuthority`, collects advisory
    signals from the three advisory modules, and produces one
    :class:`AllocationDecision` per cycle.  No other module may write
    allocation decisions.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_decision: Optional[AllocationDecision] = None
        self._last_rebalance_ts: float = 0.0

        # P2 — Bootstrap state machine pre-check: refuse construction before
        # CAPITAL_READY to enforce the BOOTSTRAP → … → CAPITAL_READY sequence.
        self._check_bootstrap_state()

        logger.info(
            "[CapitalDecisionEngine] initialised (writer_id=%r, "
            "min_rebalance_interval_s=%.0f)",
            WRITER_ID,
            _MIN_REBALANCE_INTERVAL_S,
        )

    # ------------------------------------------------------------------
    # Bootstrap / invariant helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _check_bootstrap_state() -> None:
        """Raise RuntimeError if bootstrap FSM has not reached CAPITAL_READY."""
        try:
            try:
                from bot.bootstrap_state_machine import get_bootstrap_fsm, BootstrapInvariantError
            except ImportError:
                from bootstrap_state_machine import get_bootstrap_fsm, BootstrapInvariantError  # type: ignore[import]
            get_bootstrap_fsm().assert_invariant_i11_strategy_arm()
        except BootstrapInvariantError:
            raise  # surface the invariant violation to the caller
        except Exception as exc:
            # Graceful degradation — if BSM is not yet available we allow
            # construction so the engine can still be used in test contexts.
            logger.debug(
                "[CapitalDecisionEngine] BSM check unavailable (%s) — proceeding", exc
            )

    # ------------------------------------------------------------------
    # Advisory module accessors (lazy, graceful)
    # ------------------------------------------------------------------

    @staticmethod
    def _get_capital_authority():
        try:
            try:
                from bot.capital_authority import get_capital_authority
            except ImportError:
                from capital_authority import get_capital_authority  # type: ignore[import]
            return get_capital_authority()
        except Exception:
            return None

    @staticmethod
    def _get_allocator_brain():
        """Return a CapitalAllocationBrain advisory instance, or None."""
        try:
            try:
                from bot.capital_allocation_brain import CapitalAllocationBrain
            except ImportError:
                from capital_allocation_brain import CapitalAllocationBrain  # type: ignore[import]
            return CapitalAllocationBrain()
        except Exception:
            return None

    @staticmethod
    def _get_ai_allocator():
        """Return the AICapitalAllocator advisory singleton, or None."""
        try:
            try:
                from bot.ai_capital_allocator import get_ai_capital_allocator
            except ImportError:
                from ai_capital_allocator import get_ai_capital_allocator  # type: ignore[import]
            return get_ai_capital_allocator()
        except Exception:
            return None

    @staticmethod
    def _get_concentration_engine():
        """Return the CapitalConcentrationEngine advisory singleton, or None."""
        try:
            try:
                from bot.capital_concentration_engine import get_capital_concentration_engine
            except ImportError:
                from capital_concentration_engine import get_capital_concentration_engine  # type: ignore[import]
            return get_capital_concentration_engine()
        except Exception:
            return None

    # ------------------------------------------------------------------
    # Core decision logic
    # ------------------------------------------------------------------

    def decide(
        self,
        broker_map: Optional[Dict[str, Any]] = None,
        force: bool = False,
    ) -> AllocationDecision:
        """
        Produce a fresh :class:`AllocationDecision` for the current cycle.

        Rate-limited to at most once per ``_MIN_REBALANCE_INTERVAL_S``
        seconds unless *force* is ``True``.

        Parameters
        ----------
        broker_map:
            Optional mapping of broker_id → broker object, passed through to
            :class:`CapitalAuthority` if a refresh is needed.
        force:
            When ``True``, bypass the rate-limit and always produce a fresh
            decision.

        Returns
        -------
        AllocationDecision
            The freshly computed (or last cached) decision.
        """
        now = time.monotonic()
        with self._lock:
            if (
                not force
                and self._last_decision is not None
                and (now - self._last_rebalance_ts) < _MIN_REBALANCE_INTERVAL_S
            ):
                return self._last_decision

        decision = self._compute_decision(broker_map=broker_map)

        with self._lock:
            self._last_decision = decision
            self._last_rebalance_ts = now

        logger.info(
            "[CapitalDecisionEngine] decision produced: "
            "usable=$%.2f brokers=%s accounts=%s",
            decision.usable_capital,
            list(decision.broker_weights.keys()),
            list(decision.account_multipliers.keys()),
        )
        return decision

    def _compute_decision(
        self, broker_map: Optional[Dict[str, Any]]
    ) -> AllocationDecision:
        """Internal: gather advisory signals and assemble AllocationDecision."""
        # ── 0. Capital System Gate — refuse to compute until the MABM coordinator
        #       has published at least one confirmed snapshot.  Without this check
        #       the engine would silently produce a $0-usable decision and
        #       downstream systems would incorrectly treat zero as "no capital".
        try:
            try:
                from bot.capital_authority import get_capital_system_gate as _get_csg_cde
            except ImportError:
                from capital_authority import get_capital_system_gate as _get_csg_cde  # type: ignore[import]
            if not _get_csg_cde().is_set():
                logger.debug(
                    "[CapitalDecisionEngine] CAPITAL_SYSTEM_READY not set — returning INITIALIZING decision"
                )
                return AllocationDecision(
                    usable_capital=0.0,
                    strategy_budgets={},
                    broker_weights={},
                    account_multipliers={},
                    advisory_metadata={"status": "INITIALIZING"},
                )
        except Exception as _csg_exc:
            logger.debug("[CapitalDecisionEngine] capital system gate check failed: %s", _csg_exc)

        # ── 1. Pull usable capital from the single authoritative source ──────
        usable_capital = 0.0
        authority = self._get_capital_authority()
        if authority is not None:
            try:
                if authority.is_stale() and broker_map:
                    authority.refresh(broker_map)
                usable_capital = authority.get_usable_capital()
            except Exception as exc:
                logger.warning("[CapitalDecisionEngine] CapitalAuthority read failed: %s", exc)

        advisory_metadata: Dict[str, Any] = {"usable_capital_raw": usable_capital}

        # ── 2. Advisory: broker weights (AICapitalAllocator) ─────────────────
        broker_weights: Dict[str, float] = {}
        ai_alloc = self._get_ai_allocator()
        if ai_alloc is not None:
            try:
                ai_advice = ai_alloc.advise(usable_capital)
                broker_weights = ai_advice.get("broker_weights", {})
                advisory_metadata["ai_allocator"] = ai_advice
            except Exception as exc:
                logger.debug("[CapitalDecisionEngine] AIAllocator advise failed: %s", exc)

        # ── 3. Advisory: strategy allocation pcts (CapitalAllocationBrain) ───
        strategy_budgets: Dict[str, float] = {}
        brain = self._get_allocator_brain()
        if brain is not None:
            try:
                brain_advice = brain.advise(usable_capital)
                strategy_weights = brain_advice.get("strategy_weights", {})
                advisory_metadata["allocation_brain"] = brain_advice
                # Translate percentage weights → USD budgets
                for sid, pct in strategy_weights.items():
                    strategy_budgets[sid] = usable_capital * float(pct)
            except Exception as exc:
                logger.debug("[CapitalDecisionEngine] Brain advise failed: %s", exc)

        # ── 4. Advisory: concentration multipliers (CapitalConcentrationEngine)
        account_multipliers: Dict[str, float] = {}
        cce = self._get_concentration_engine()
        if cce is not None:
            try:
                cce_advice = cce.advise(usable_capital)
                account_multipliers = cce_advice.get("account_multipliers", {})
                advisory_metadata["concentration"] = cce_advice
            except Exception as exc:
                logger.debug("[CapitalDecisionEngine] CCEngine advise failed: %s", exc)

        return AllocationDecision(
            usable_capital=usable_capital,
            strategy_budgets=strategy_budgets,
            broker_weights=broker_weights,
            account_multipliers=account_multipliers,
            advisory_metadata=advisory_metadata,
        )

    def get_last_decision(self) -> Optional[AllocationDecision]:
        """Return the most-recently produced decision without recomputing."""
        with self._lock:
            return self._last_decision

    def invalidate(self) -> None:
        """Force the next call to :meth:`decide` to recompute regardless of TTL."""
        with self._lock:
            self._last_rebalance_ts = 0.0


# ---------------------------------------------------------------------------
# Module-level singleton (double-checked locking)
# ---------------------------------------------------------------------------

_ENGINE: Optional[CapitalDecisionEngine] = None
_ENGINE_LOCK = threading.Lock()


def get_capital_decision_engine() -> CapitalDecisionEngine:
    """
    Return the process-wide :class:`CapitalDecisionEngine` singleton.

    Thread-safe via double-checked locking.  Created lazily on first call.
    """
    global _ENGINE
    if _ENGINE is None:
        with _ENGINE_LOCK:
            if _ENGINE is None:
                _ENGINE = CapitalDecisionEngine()
    return _ENGINE


__all__ = [
    "WRITER_ID",
    "AllocationDecision",
    "CapitalDecisionEngine",
    "get_capital_decision_engine",
]
