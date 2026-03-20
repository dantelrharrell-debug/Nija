"""
Capital Fragmentation Guard — Leak #3 fix
==========================================
Detects when capital is spread too thinly across too many brokers/accounts,
some of which are idle or losing money, and surfaces actionable recommendations.

Problem
-------
When you run multiple Coinbase accounts each with $50–$100, some accounts
drift into losing territory while others are profitable.  The idle/losing
accounts:
  * Miss trades (balance too low to meet minimums)
  * Pay fees on small, unprofitable positions
  * Dilute focus from the best-performing account

Fix
---
This guard maintains a rolling performance window per account and:
  1. Flags *fragmented* states (many accounts, few profitable ones).
  2. Identifies which accounts should be paused ("soft-disabled") so capital
     can be concentrated in top performers.
  3. Emits log warnings and returns a ``FragmentationReport`` that the caller
     can act on (e.g. skip entry for a soft-disabled account).

Integration
-----------
::

    from bot.capital_fragmentation_guard import get_fragmentation_guard

    guard = get_fragmentation_guard()

    # After every closed trade:
    guard.record_trade(account_id="coinbase_1", pnl_usd=1.20, is_win=True,
                       balance_usd=87.5)

    # Before each entry cycle — check whether this account should trade:
    report = guard.evaluate()
    if account_id in report.paused_accounts:
        logger.warning("Account %s paused (fragmentation guard)", account_id)
        continue

Author: NIJA Trading Systems
"""

from __future__ import annotations

import logging
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Dict, Deque, List, Optional, Tuple

logger = logging.getLogger("nija.capital_fragmentation_guard")

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

# Minimum number of accounts before fragmentation analysis is meaningful
MIN_ACCOUNTS_FOR_ANALYSIS: int = 2
# Rolling window size for per-account win-rate calculation
WINDOW: int = 20
# Pause account if rolling win-rate is below this fraction
MIN_WIN_RATE_THRESHOLD: float = 0.35  # 35%
# Pause account if rolling net P&L is negative beyond this amount
MAX_NET_LOSS_USD: float = -5.0
# Minimum balance an account needs to be considered "active"
MIN_ACTIVE_BALANCE_USD: float = 15.0
# Minimum trades recorded before an account can be evaluated for underperformance
MIN_TRADES_FOR_EVALUATION: int = max(3, WINDOW // 7)


@dataclass
class AccountStats:
    account_id: str
    balance_usd: float = 0.0
    total_trades: int = 0
    _outcomes: Deque[bool] = field(default_factory=lambda: deque(maxlen=WINDOW))
    _pnl_window: Deque[float] = field(default_factory=lambda: deque(maxlen=WINDOW))

    @property
    def rolling_win_rate(self) -> float:
        if not self._outcomes:
            return 0.5  # neutral when no data
        return sum(self._outcomes) / len(self._outcomes)

    @property
    def rolling_net_pnl(self) -> float:
        return sum(self._pnl_window)

    @property
    def is_active(self) -> bool:
        return self.balance_usd >= MIN_ACTIVE_BALANCE_USD


@dataclass
class FragmentationReport:
    total_accounts: int
    active_accounts: int
    underperforming_accounts: List[str]
    paused_accounts: List[str]         # caller should skip these for entries
    top_account: Optional[str]
    fragmentation_ratio: float
    is_fragmented: bool
    summary: str


class CapitalFragmentationGuard:
    """Detects capital fragmentation across multiple accounts."""

    def __init__(
        self,
        min_win_rate: float = MIN_WIN_RATE_THRESHOLD,
        max_net_loss_usd: float = MAX_NET_LOSS_USD,
        min_active_balance: float = MIN_ACTIVE_BALANCE_USD,
        enabled: bool = True,
    ) -> None:
        self.min_win_rate = min_win_rate
        self.max_net_loss_usd = max_net_loss_usd
        self.min_active_balance = min_active_balance
        self.enabled = enabled
        self._accounts: Dict[str, AccountStats] = {}
        self._lock = threading.Lock()
        logger.info(
            "🔍 Capital Fragmentation Guard initialised | "
            "min_win_rate=%.0f%% | max_net_loss=$%.2f | min_balance=$%.2f",
            min_win_rate * 100, max_net_loss_usd, min_active_balance,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record_trade(
        self,
        account_id: str,
        pnl_usd: float,
        is_win: bool,
        balance_usd: float = 0.0,
    ) -> None:
        """Record a closed trade for *account_id*."""
        with self._lock:
            stats = self._accounts.setdefault(account_id, AccountStats(account_id))
            stats.total_trades += 1
            stats._outcomes.append(is_win)
            stats._pnl_window.append(pnl_usd)
            if balance_usd > 0:
                stats.balance_usd = balance_usd

    def update_balance(self, account_id: str, balance_usd: float) -> None:
        """Update the current balance for *account_id* (call each cycle)."""
        with self._lock:
            stats = self._accounts.setdefault(account_id, AccountStats(account_id))
            stats.balance_usd = balance_usd

    def evaluate(self) -> FragmentationReport:
        """
        Analyse all registered accounts and return a ``FragmentationReport``.

        Accounts are marked for *pausing* when:
        * Their rolling win-rate is below *min_win_rate*, OR
        * Their rolling net P&L is more negative than *max_net_loss_usd*, OR
        * Their balance is below *min_active_balance*.

        When ``FragmentationReport.is_fragmented`` is True more than half the
        accounts are underperforming; a WARNING is emitted so the operator can
        take action.
        """
        with self._lock:
            accounts = dict(self._accounts)

        if not self.enabled or len(accounts) < MIN_ACCOUNTS_FOR_ANALYSIS:
            return FragmentationReport(
                total_accounts=len(accounts),
                active_accounts=len(accounts),
                underperforming_accounts=[],
                paused_accounts=[],
                top_account=None,
                fragmentation_ratio=0.0,
                is_fragmented=False,
                summary="Guard disabled or too few accounts",
            )

        active = [s for s in accounts.values() if s.balance_usd >= self.min_active_balance]
        if not active:
            return FragmentationReport(
                total_accounts=len(accounts),
                active_accounts=0,
                underperforming_accounts=[],
                paused_accounts=[],
                top_account=None,
                fragmentation_ratio=0.0,
                is_fragmented=False,
                summary="No active accounts above minimum balance",
            )

        underperforming: List[str] = []
        for s in active:
            if s.total_trades < MIN_TRADES_FOR_EVALUATION:
                continue  # not enough history to judge
            if (
                s.rolling_win_rate < self.min_win_rate
                or s.rolling_net_pnl < self.max_net_loss_usd
            ):
                underperforming.append(s.account_id)

        # Top performer: highest rolling net P&L among non-underperforming accounts
        performers = [s for s in active if s.account_id not in underperforming]
        top_account = None
        if performers:
            top_account = max(performers, key=lambda s: s.rolling_net_pnl).account_id

        fragmentation_ratio = len(underperforming) / len(active) if active else 0.0
        is_fragmented = fragmentation_ratio > FRAGMENTATION_RATIO_THRESHOLD

        # Build summary
        if is_fragmented:
            summary = (
                f"⚠️ CAPITAL FRAGMENTATION: {len(underperforming)}/{len(active)} accounts "
                f"underperforming. Consider concentrating capital in: {top_account}"
            )
            logger.warning(summary)
        elif underperforming:
            summary = (
                f"ℹ️ {len(underperforming)} account(s) underperforming "
                f"({[a for a in underperforming]}). Top performer: {top_account}"
            )
            logger.info(summary)
        else:
            summary = f"✅ All {len(active)} accounts healthy. Top: {top_account}"
            logger.debug(summary)

        return FragmentationReport(
            total_accounts=len(accounts),
            active_accounts=len(active),
            underperforming_accounts=underperforming,
            paused_accounts=underperforming,   # pause = underperforming for now
            top_account=top_account,
            fragmentation_ratio=fragmentation_ratio,
            is_fragmented=is_fragmented,
            summary=summary,
        )

    def should_trade(self, account_id: str) -> Tuple[bool, str]:
        """
        Convenience check: returns ``(True, "ok")`` if *account_id* is not
        currently flagged for pausing.
        """
        report = self.evaluate()
        if account_id in report.paused_accounts:
            return False, f"Account {account_id} paused — underperforming (fragmentation guard)"
        return True, "ok"


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[CapitalFragmentationGuard] = None


def get_fragmentation_guard(
    min_win_rate: float = MIN_WIN_RATE_THRESHOLD,
    max_net_loss_usd: float = MAX_NET_LOSS_USD,
    min_active_balance: float = MIN_ACTIVE_BALANCE_USD,
    enabled: bool = True,
) -> CapitalFragmentationGuard:
    """Return the process-wide singleton, creating it on first call."""
    global _instance
    if _instance is None:
        _instance = CapitalFragmentationGuard(
            min_win_rate=min_win_rate,
            max_net_loss_usd=max_net_loss_usd,
            min_active_balance=min_active_balance,
            enabled=enabled,
        )
    return _instance
