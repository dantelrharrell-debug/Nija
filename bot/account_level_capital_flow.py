"""
NIJA Account-Level Capital Flow
================================

Connects the three already-built account management subsystems into a single
entry point that the trading engine calls every cycle:

  1. CapitalConcentrationEngine  — rolling win-rate, drawdown tracking,
                                   concentration boost, kill-weak accounts.
  2. AICapitalAllocator          — EMA-smoothed Sharpe / win-rate / profit-factor
                                   score weighting per broker account.

Together they answer four questions every bar:

  A. "Is this account still healthy enough to open new positions?"
     → :meth:`is_account_tradeable`

  B. "How much capital should this account deploy relative to baseline?"
     → :meth:`get_size_multiplier`

  C. "Is this account over-concentrated (exposure cap reached)?"
     → :meth:`is_exposure_capped`

  D. "Should capital be physically moved away from a weak account?"
     → :meth:`maybe_reallocate` / :meth:`move_funds`

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
    │  is_exposure_capped(account_id, balance_usd,                      │
    │                      proposed_size_usd=0) → bool                  │
    │    → True when current + proposed exposure > 30% of balance       │
    │    → blocks new trades to prevent over-concentration               │
    │                                                                   │
    │  record_position_opened(account_id, size_usd)                     │
    │  record_position_closed(account_id, size_usd)                     │
    │    → maintain per-account open-exposure tracking                  │
    │                                                                   │
    │  move_funds(from_account, to_account, amount_usd, brokers)        │
    │    → hard capital reallocation: log + validate the transfer        │
    │    → returns ReallocationResult (caller executes the API calls)   │
    │                                                                   │
    │  maybe_reallocate(account_id, balance_usd, ...)                   │
    │    → if not is_account_tradeable → move_funds to top account      │
    │                                                                   │
    │  get_preferred_account(candidates) → str                          │
    │    → highest-ranked account_id from ranked list                   │
    │                                                                   │
    │  get_report() → dict                                              │
    │    → combined snapshot from both engines + exposure + realloc log │
    └───────────────────────────────────────────────────────────────────┘

Usage
-----
::

    from bot.account_level_capital_flow import get_account_level_capital_flow

    flow = get_account_level_capital_flow()

    # Once per cycle, after the balance fetch:
    flow.update("coinbase", balance_usd=10_500.0)

    # Hard capital reallocation — move funds away from killed accounts:
    result = flow.maybe_reallocate("coinbase", balance_usd=10_500.0)
    if result and result.success:
        # Caller executes the actual broker transfer here
        execute_transfer(result.from_account, result.to_account, result.amount_usd)

    # Before sizing each trade — hard block for killed accounts:
    if not flow.is_account_tradeable("coinbase"):
        continue  # skip entry

    # Global exposure cap — block new trades when account is over-concentrated:
    if flow.is_exposure_capped("coinbase", balance_usd=10_500.0,
                               proposed_size_usd=position_usd):
        continue  # skip entry — account at 30 % exposure ceiling

    # Soft scaling — apply composite multiplier to base position size:
    position_usd *= flow.get_size_multiplier("coinbase")

    # After entry:
    flow.record_position_opened("coinbase", position_usd)

    # After exit:
    flow.record_position_closed("coinbase", position_usd)

Author: NIJA Trading Systems
Version: 1.1
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional

logger = logging.getLogger("nija.account_capital_flow")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Maximum fraction of account balance that may be committed to open positions.
#: When current_exposure / balance > MAX_ACCOUNT_EXPOSURE new trades are blocked.
DEFAULT_MAX_ACCOUNT_EXPOSURE: float = 0.30  # 30%

#: How many reallocation records to keep in the in-memory audit log.
MAX_REALLOCATION_LOG: int = 100


# ---------------------------------------------------------------------------
# ReallocationResult
# ---------------------------------------------------------------------------

@dataclass
class ReallocationResult:
    """
    Outcome of a hard capital reallocation request.

    The :class:`AccountLevelCapitalFlow` engine **records** and **validates**
    the request; the *calling code* is responsible for actually executing the
    broker-level fund transfer (withdrawal / deposit API calls).
    """

    from_account: str
    """Source account_id (the weak / killed account)."""

    to_account: str
    """Destination account_id (the top-ranked account)."""

    amount_usd: float
    """Amount in USD that should be transferred."""

    success: bool
    """``True`` when the reallocation request was accepted and logged."""

    reason: str
    """Human-readable explanation (acceptance reason or rejection cause)."""

    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict:
        return {
            "from_account": self.from_account,
            "to_account": self.to_account,
            "amount_usd": self.amount_usd,
            "success": self.success,
            "reason": self.reason,
            "timestamp": self.timestamp,
        }


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

    def __init__(
        self,
        max_account_exposure: float = DEFAULT_MAX_ACCOUNT_EXPOSURE,
    ) -> None:
        self._lock = threading.Lock()
        self._last_ai_update: float = 0.0

        # ── Feature: Global Exposure Cap ─────────────────────────────────────
        #: Per-account open-position exposure in USD
        self._account_exposure: Dict[str, float] = {}
        #: Fraction of balance beyond which new trades are blocked (default 30 %)
        self._max_account_exposure: float = max_account_exposure

        # ── Feature: Hard Capital Reallocation ───────────────────────────────
        #: Audit log of reallocation requests (most-recent last)
        self._reallocation_log: Deque[ReallocationResult] = deque(
            maxlen=MAX_REALLOCATION_LOG
        )

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

    # ── Feature: Global Exposure Cap (Feature 2) ─────────────────────────────

    def record_position_opened(self, account_id: str, size_usd: float) -> None:
        """
        Increase the tracked open-position exposure for *account_id*.

        Call this immediately after a new position is opened so the exposure
        cap remains accurate.

        Args:
            account_id: Broker / account label.
            size_usd:   Position size in USD that was just opened.
        """
        with self._lock:
            current = self._account_exposure.get(account_id, 0.0)
            self._account_exposure[account_id] = max(0.0, current + size_usd)
        logger.debug(
            "[CapitalFlow] %s exposure +%.2f → %.2f",
            account_id, size_usd, self._account_exposure[account_id],
        )

    def record_position_closed(self, account_id: str, size_usd: float) -> None:
        """
        Decrease the tracked open-position exposure for *account_id*.

        Call this after a position is closed / reduced.

        Args:
            account_id: Broker / account label.
            size_usd:   Position size in USD that was just closed.
        """
        with self._lock:
            current = self._account_exposure.get(account_id, 0.0)
            self._account_exposure[account_id] = max(0.0, current - size_usd)
        logger.debug(
            "[CapitalFlow] %s exposure -%.2f → %.2f",
            account_id, size_usd, self._account_exposure.get(account_id, 0.0),
        )

    def get_account_exposure_pct(self, account_id: str, balance_usd: float) -> float:
        """
        Return the current open-position exposure as a fraction of *balance_usd*.

        Args:
            account_id:  Broker / account label.
            balance_usd: Current account balance in USD.

        Returns:
            Exposure fraction in ``[0, ∞)``.  Values above
            ``self._max_account_exposure`` mean the cap is breached.
        """
        if balance_usd <= 0:
            return 0.0
        with self._lock:
            exposure_usd = self._account_exposure.get(account_id, 0.0)
        return exposure_usd / balance_usd

    def is_exposure_capped(
        self,
        account_id: str,
        balance_usd: float,
        proposed_size_usd: float = 0.0,
    ) -> bool:
        """
        Return ``True`` when opening the proposed trade would push *account_id*
        over the global per-account exposure cap (default 30 %).

        Use this as a hard gate **before** sending an order:

        .. code-block:: python

            if flow.is_exposure_capped("coinbase", balance_usd=10_500.0,
                                       proposed_size_usd=position_usd):
                return  # blocked — account already at exposure ceiling

        Args:
            account_id:        Broker / account label.
            balance_usd:       Current account balance in USD.
            proposed_size_usd: Size of the trade you intend to open (USD).

        Returns:
            ``True`` → block the trade; ``False`` → exposure within limits.
        """
        if balance_usd <= 0:
            return False
        with self._lock:
            current_exposure = self._account_exposure.get(account_id, 0.0)
        total_exposure_pct = (current_exposure + proposed_size_usd) / balance_usd
        capped = total_exposure_pct > self._max_account_exposure
        if capped:
            logger.info(
                "[CapitalFlow] ⚠️  %s exposure cap hit: "
                "current=%.2f + proposed=%.2f = %.1f%% > cap %.0f%%",
                account_id,
                current_exposure,
                proposed_size_usd,
                total_exposure_pct * 100,
                self._max_account_exposure * 100,
            )
        return capped

    # ── Feature: Hard Capital Reallocation (Feature 1) ───────────────────────

    def move_funds(
        self,
        from_account: str,
        to_account: str,
        amount_usd: float,
        brokers: Optional[Dict] = None,
    ) -> ReallocationResult:
        """
        Record and validate a hard capital reallocation request.

        This method **logs and validates** the transfer intent; the *caller*
        must execute the actual broker-level withdrawal / deposit API calls
        using the data in the returned :class:`ReallocationResult`.

        Typical usage::

            result = flow.move_funds("weak_account", "top_account", 500.0)
            if result.success:
                broker_api.transfer(result.from_account,
                                    result.to_account,
                                    result.amount_usd)

        Args:
            from_account: Source account_id (the weak / killed account).
            to_account:   Destination account_id (the top-ranked account).
            amount_usd:   Amount in USD to transfer.  Must be > 0.
            brokers:      Optional ``{account_id: broker_object}`` map.
                          When provided the source account is verified to
                          exist in the map before the request is accepted.

        Returns:
            :class:`ReallocationResult` — ``success=True`` when accepted.
        """
        # ── Validation ────────────────────────────────────────────────────────
        if from_account == to_account:
            result = ReallocationResult(
                from_account=from_account,
                to_account=to_account,
                amount_usd=amount_usd,
                success=False,
                reason="Source and destination accounts are identical.",
            )
            logger.warning("[CapitalFlow] move_funds rejected: %s", result.reason)
            return result

        if amount_usd <= 0:
            result = ReallocationResult(
                from_account=from_account,
                to_account=to_account,
                amount_usd=amount_usd,
                success=False,
                reason=f"Invalid transfer amount: {amount_usd:.2f}",
            )
            logger.warning("[CapitalFlow] move_funds rejected: %s", result.reason)
            return result

        if brokers is not None and from_account not in brokers:
            result = ReallocationResult(
                from_account=from_account,
                to_account=to_account,
                amount_usd=amount_usd,
                success=False,
                reason=(
                    f"Source account '{from_account}' not found in provided brokers map."
                ),
            )
            logger.warning("[CapitalFlow] move_funds rejected: %s", result.reason)
            return result

        # ── Accept the request ────────────────────────────────────────────────
        result = ReallocationResult(
            from_account=from_account,
            to_account=to_account,
            amount_usd=round(amount_usd, 2),
            success=True,
            reason=(
                f"Reallocation of ${amount_usd:.2f} from '{from_account}' "
                f"to top account '{to_account}' accepted. "
                "Caller must execute the broker transfer."
            ),
        )
        with self._lock:
            self._reallocation_log.append(result)

        logger.info(
            "[CapitalFlow] 💸 Hard reallocation accepted: "
            "$%.2f from '%s' → '%s'",
            amount_usd, from_account, to_account,
        )
        return result

    def maybe_reallocate(
        self,
        account_id: str,
        balance_usd: float,
        reallocation_fraction: float = 0.50,
        brokers: Optional[Dict] = None,
    ) -> Optional[ReallocationResult]:
        """
        If *account_id* is not tradeable (killed by drawdown), automatically
        request a hard capital reallocation to the top-performing account.

        This is the primary integration point for the trading loop::

            result = flow.maybe_reallocate("coinbase", balance_usd=10_500.0)
            if result and result.success:
                # Execute the actual broker transfer here
                execute_transfer(result.from_account,
                                 result.to_account,
                                 result.amount_usd)

        Args:
            account_id:            Account to evaluate.
            balance_usd:           Current balance of *account_id* in USD.
            reallocation_fraction: Fraction of *balance_usd* to move
                                   (default 50 %).
            brokers:               Optional broker map passed to
                                   :meth:`move_funds` for validation.

        Returns:
            :class:`ReallocationResult` when reallocation was requested,
            ``None`` when the account is still healthy.
        """
        if self.is_account_tradeable(account_id):
            return None  # account is fine — nothing to do

        if self._cce is None:
            logger.debug(
                "[CapitalFlow] maybe_reallocate: CCE unavailable for '%s'",
                account_id,
            )
            return None

        # Find the top-ranked account to receive the capital
        try:
            top = self._cce.get_top_accounts(n=1)
        except Exception as exc:
            logger.debug(
                "[CapitalFlow] maybe_reallocate: get_top_accounts failed: %s", exc
            )
            return None

        if not top or top[0] == account_id:
            # No better destination available
            return None

        dest = top[0]
        amount = round(balance_usd * max(0.0, min(reallocation_fraction, 1.0)), 2)

        logger.info(
            "[CapitalFlow] 🚨 '%s' is non-tradeable — requesting %.0f%% ($%.2f) "
            "reallocation → '%s'",
            account_id,
            reallocation_fraction * 100,
            amount,
            dest,
        )
        return self.move_funds(
            from_account=account_id,
            to_account=dest,
            amount_usd=amount,
            brokers=brokers,
        )

    def get_reallocation_log(self) -> List[Dict]:
        """Return the recent reallocation audit log as a list of dicts."""
        with self._lock:
            return [r.to_dict() for r in self._reallocation_log]

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
                "max_account_exposure_pct": round(
                    self._max_account_exposure * 100, 1
                ),
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

        # ── Exposure snapshot ─────────────────────────────────────────────────
        with self._lock:
            exposure_snapshot = dict(self._account_exposure)
        report["account_exposure_usd"] = {
            aid: round(exp, 4) for aid, exp in exposure_snapshot.items()
        }

        # ── Reallocation audit log ────────────────────────────────────────────
        report["reallocation_log"] = self.get_reallocation_log()

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
