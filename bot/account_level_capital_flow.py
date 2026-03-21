"""
NIJA Account-Level Capital Flow
================================

Connects the three already-built account management subsystems into a single
entry point that the trading engine calls every cycle:

  1. CapitalConcentrationEngine  — rolling win-rate, drawdown tracking,
                                   concentration boost, kill-weak accounts.
  2. AICapitalAllocator          — EMA-smoothed Sharpe / win-rate / profit-factor
                                   score weighting per broker account.

Together they answer two questions every bar:

  A. "Is this account still healthy enough to open new positions?"
     → :meth:`is_account_tradeable`

  B. "How much capital should this account deploy relative to baseline?"
     → :meth:`get_size_multiplier`

Architecture
------------
::

    ┌───────────────────────────────────────────────────────────────────┐
    │               AccountLevelCapitalFlow                             │
    │                                                                   │
    │  update(account_id, balance_usd)                                  │
    │    → concentration_engine.update_equity()                         │
    │    → ai_allocator.update()  (throttled: once per 60 s)            │
    │                                                                   │
    │  is_account_tradeable(account_id) → bool                          │
    │    → False when concentration_engine.is_killed()                  │
    │                                                                   │
    │  get_size_multiplier(account_id) → float                          │
    │    → concentration_multiplier × ai_weight_factor                  │
    │    → 0.0 when account is killed                                   │
    │                                                                   │
    │  get_preferred_account(candidates) → str                          │
    │    → highest-ranked account_id from ranked list                   │
    │                                                                   │
    │  get_report() → dict                                              │
    │    → combined snapshot from both engines                          │
    └───────────────────────────────────────────────────────────────────┘

Usage
-----
::

    from bot.account_level_capital_flow import get_account_level_capital_flow

    flow = get_account_level_capital_flow()

    # Once per cycle, after the balance fetch:
    flow.update("coinbase", balance_usd=10_500.0)

    # Before sizing each trade — hard block for killed accounts:
    if not flow.is_account_tradeable("coinbase"):
        continue  # skip entry

    # Soft scaling — apply composite multiplier to base position size:
    position_usd *= flow.get_size_multiplier("coinbase")

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Dict, List, Optional

logger = logging.getLogger("nija.account_capital_flow")

# ---------------------------------------------------------------------------
# Optional dependency imports — both engines degrade gracefully when absent
# ---------------------------------------------------------------------------

try:
    from capital_concentration_engine import get_capital_concentration_engine
    _CCE_AVAILABLE = True
except ImportError:
    try:
        from bot.capital_concentration_engine import get_capital_concentration_engine
        _CCE_AVAILABLE = True
    except ImportError:
        _CCE_AVAILABLE = False
        get_capital_concentration_engine = None  # type: ignore[assignment]

try:
    from ai_capital_allocator import get_ai_capital_allocator
    _ACA_AVAILABLE = True
except ImportError:
    try:
        from bot.ai_capital_allocator import get_ai_capital_allocator
        _ACA_AVAILABLE = True
    except ImportError:
        _ACA_AVAILABLE = False
        get_ai_capital_allocator = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# AccountLevelCapitalFlow
# ---------------------------------------------------------------------------

class AccountLevelCapitalFlow:
    """
    Unified account-level capital router.

    Connects the Capital Concentration Engine (account ranking, drawdown
    tracking, kill-weak accounts) with the AI Capital Allocator (EMA-weighted
    Sharpe / win-rate / profit-factor scores) into a single per-cycle call.
    """

    # Minimum seconds between full AI-allocator weight refreshes
    _AI_UPDATE_INTERVAL: float = 60.0

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._last_ai_update: float = 0.0

        # Lazy-resolved singletons — constructor never raises
        self._cce = None   # CapitalConcentrationEngine
        self._aca = None   # AICapitalAllocator

        self._init_engines()

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _init_engines(self) -> None:
        if _CCE_AVAILABLE and get_capital_concentration_engine is not None:
            try:
                self._cce = get_capital_concentration_engine()
                logger.info(
                    "[CapitalFlow] CapitalConcentrationEngine attached "
                    "(account ranking + kill-weak + Kelly sizing)"
                )
            except Exception as exc:
                logger.warning("[CapitalFlow] CCE init failed: %s", exc)

        if _ACA_AVAILABLE and get_ai_capital_allocator is not None:
            try:
                self._aca = get_ai_capital_allocator()
                logger.info(
                    "[CapitalFlow] AICapitalAllocator attached "
                    "(EMA-smoothed Sharpe/win-rate/PF weights)"
                )
            except Exception as exc:
                logger.warning("[CapitalFlow] ACA init failed: %s", exc)

    def _maybe_refresh_ai_weights(self) -> None:
        """Refresh AI allocator weights at most once per ``_AI_UPDATE_INTERVAL``."""
        if self._aca is None:
            return
        now = time.monotonic()
        if now - self._last_ai_update >= self._AI_UPDATE_INTERVAL:
            try:
                self._aca.update()
                self._last_ai_update = now
            except Exception as exc:
                logger.debug("[CapitalFlow] AIAllocator.update skipped: %s", exc)

    # ── Public API ────────────────────────────────────────────────────────────

    def update(self, account_id: str, balance_usd: float) -> None:
        """
        Refresh per-account equity and (periodically) AI allocation weights.

        Call this once per trading cycle, immediately after the balance fetch.

        Args:
            account_id:  Stable broker / account label (e.g. ``"coinbase"``).
            balance_usd: Current account balance in USD.
        """
        if self._cce is not None:
            try:
                self._cce.update_equity(account_id, balance_usd)
            except Exception as exc:
                logger.debug("[CapitalFlow] CCE.update_equity skipped: %s", exc)

        with self._lock:
            self._maybe_refresh_ai_weights()

    def is_account_tradeable(self, account_id: str) -> bool:
        """
        Return ``False`` when the account must not open new positions.

        An account becomes non-tradeable when the Capital Concentration Engine
        has reduced its allocation multiplier to zero due to excessive drawdown
        (the *kill-weak-accounts* feature).

        Args:
            account_id: Broker / account label.

        Returns:
            ``True`` if new entries are permitted; ``False`` to block them.
        """
        if self._cce is None:
            return True  # no data → fail-open
        try:
            return not self._cce.is_killed(account_id)
        except Exception as exc:
            logger.debug("[CapitalFlow] is_killed check failed: %s", exc)
            return True  # fail-open on error

    def get_size_multiplier(self, account_id: str) -> float:
        """
        Return a composite position-size multiplier for *account_id*.

        Combines two signals:

        - **Concentration multiplier** from ``CapitalConcentrationEngine``
          — >1.0 for hot accounts (win-rate > 70 %), <1.0 for weakened ones,
          0.0 for killed accounts.

        - **AI weight factor** from ``AICapitalAllocator``
          — the account's EMA-smoothed score weight divided by the equal-weight
          baseline (1 / n_accounts), clamped to ``[0.25, 2.0]`` to prevent
          extreme rebalancing swings.

        When either engine is unavailable the other is used alone.
        Returns ``1.0`` (neutral) when neither engine has data.

        Args:
            account_id: Broker / account label.

        Returns:
            Float multiplier to apply to the base position size.  Always ≥ 0.
        """
        concentration_mult = 1.0
        ai_weight_factor = 1.0

        # ── Concentration multiplier ──────────────────────────────────────────
        if self._cce is not None:
            try:
                concentration_mult = self._cce.get_concentration_multiplier(account_id)
            except Exception as exc:
                logger.debug("[CapitalFlow] CCE.get_concentration_multiplier failed: %s", exc)

        # ── AI weight factor ──────────────────────────────────────────────────
        if self._aca is not None:
            try:
                weights = self._aca.get_weights()
                if weights:
                    account_weight = weights.get(account_id, 0.0)
                    if account_weight > 0:
                        n = len(weights)
                        equal_weight = 1.0 / n if n > 0 else 1.0
                        raw_factor = account_weight / equal_weight
                        # Clamp to avoid violent swings
                        ai_weight_factor = max(0.25, min(raw_factor, 2.0))
            except Exception as exc:
                logger.debug("[CapitalFlow] ACA.get_weights failed: %s", exc)

        composite = concentration_mult * ai_weight_factor
        return max(composite, 0.0)

    def get_preferred_account(self, candidates: List[str]) -> Optional[str]:
        """
        From a list of candidate account_ids, return the highest-ranked one.

        Falls back to ``AICapitalAllocator.get_best_account()`` if the
        concentration engine has no ranking data, then to ``candidates[0]``.

        Args:
            candidates: Account_ids to choose among (order does not matter).

        Returns:
            The preferred account_id, or ``None`` when *candidates* is empty.
        """
        if not candidates:
            return None

        if self._cce is not None:
            try:
                top = self._cce.get_top_accounts(n=len(candidates))
                for acct in top:
                    if acct in candidates:
                        return acct
            except Exception as exc:
                logger.debug("[CapitalFlow] CCE.get_top_accounts failed: %s", exc)

        if self._aca is not None:
            try:
                best = self._aca.get_best_account()
                if best and best in candidates:
                    return best
            except Exception as exc:
                logger.debug("[CapitalFlow] ACA.get_best_account failed: %s", exc)

        return candidates[0]

    def get_report(self) -> Dict:
        """Return a combined snapshot of both engines for dashboards / logging."""
        report: Dict = {
            "account_capital_flow": {
                "cce_available": self._cce is not None,
                "aca_available": self._aca is not None,
            }
        }

        if self._cce is not None:
            try:
                report["concentration"] = self._cce.get_report()
            except Exception as exc:
                report["concentration"] = {"error": str(exc)}

        if self._aca is not None:
            try:
                report["ai_allocation"] = self._aca.get_report()
            except Exception as exc:
                report["ai_allocation"] = {"error": str(exc)}

        return report


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_FLOW: Optional[AccountLevelCapitalFlow] = None
_FLOW_LOCK = threading.Lock()


def get_account_level_capital_flow() -> AccountLevelCapitalFlow:
    """Return the process-wide ``AccountLevelCapitalFlow`` singleton."""
    global _FLOW
    with _FLOW_LOCK:
        if _FLOW is None:
            _FLOW = AccountLevelCapitalFlow()
            logger.info(
                "[CapitalFlow] singleton created — "
                "account ranking + kill-weak + AI weights connected"
            )
    return _FLOW
