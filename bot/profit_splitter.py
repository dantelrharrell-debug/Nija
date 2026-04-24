"""
NIJA Profit Splitter
=====================

Splits realised P&L across registered user accounts according to each
account's proportional share of total capital under management.

Responsibilities
----------------
- Track profit contributions per account.
- On a realised trade, call ``record_profit()`` and the engine
  distributes the net gain to every user's running balance.
- ``get_statement()`` returns a per-user breakdown for dashboards.

Usage
-----
::

    from bot.profit_splitter import get_profit_splitter

    ps = get_profit_splitter()
    ps.register_user("alice", balance=5_000.0)
    ps.register_user("bob",   balance=2_000.0)

    # After a master trade closes with $120 profit:
    splits = ps.record_profit(gross_pnl_usd=120.0, fee_usd=3.0)
    # → {"alice": 82.5, "bob": 34.5}   (proportional after fees)

    print(ps.get_statement())

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

logger = logging.getLogger("nija.profit_splitter")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class UserSplit:
    """Cumulative profit allocation for one user."""
    user_id: str
    balance: float
    total_allocated_usd: float = 0.0
    trade_count: int = 0
    last_updated: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


@dataclass
class SplitRecord:
    """Record of a single profit-split event."""
    gross_pnl_usd: float
    fee_usd: float
    net_pnl_usd: float
    splits: Dict[str, float]          # user_id → USD allocated
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


# ---------------------------------------------------------------------------
# ProfitSplitter
# ---------------------------------------------------------------------------

class ProfitSplitter:
    """
    Distributes net trade profit to all registered users proportionally
    to their share of total capital under management.
    """

    def __init__(self) -> None:
        self._users: Dict[str, UserSplit] = {}
        self._history: List[SplitRecord] = []
        self._lock = threading.Lock()

    # ── User registry ────────────────────────────────────────────────────────

    def register_user(self, user_id: str, balance: float) -> None:
        """Register or update a user account with current balance."""
        with self._lock:
            if user_id in self._users:
                self._users[user_id].balance = max(0.0, balance)
            else:
                self._users[user_id] = UserSplit(
                    user_id=user_id,
                    balance=max(0.0, balance),
                )
        logger.debug("[ProfitSplitter] registered %s balance=%.2f", user_id, balance)

    def update_balance(self, user_id: str, balance: float) -> None:
        """Update balance for an existing user (call each cycle)."""
        with self._lock:
            if user_id in self._users:
                self._users[user_id].balance = max(0.0, balance)

    def _total_balance(self) -> float:
        return sum(u.balance for u in self._users.values())

    # ── Profit distribution ───────────────────────────────────────────────────

    def record_profit(
        self,
        gross_pnl_usd: float,
        fee_usd: float = 0.0,
    ) -> Dict[str, float]:
        """
        Distribute net profit across all registered users proportionally.

        Args:
            gross_pnl_usd: Total gross profit from the closed trade.
            fee_usd: Total fees to deduct before splitting.

        Returns:
            Dict mapping user_id → USD allocated to that user.
        """
        net_pnl = gross_pnl_usd - fee_usd

        with self._lock:
            total = self._total_balance()
            splits: Dict[str, float] = {}

            if total <= 0 or not self._users:
                logger.warning("[ProfitSplitter] no users registered — profit not split")
                return splits

            for uid, user in self._users.items():
                share = user.balance / total
                allocation = round(net_pnl * share, 4)
                splits[uid] = allocation
                user.total_allocated_usd += allocation
                user.trade_count += 1
                user.last_updated = datetime.now(timezone.utc).isoformat()

            self._history.append(
                SplitRecord(
                    gross_pnl_usd=gross_pnl_usd,
                    fee_usd=fee_usd,
                    net_pnl_usd=net_pnl,
                    splits=splits.copy(),
                )
            )

        logger.info(
            "[ProfitSplitter] net=%.2f split across %d users: %s",
            net_pnl,
            len(splits),
            {k: f"${v:.2f}" for k, v in splits.items()},
        )
        return splits

    # ── Reporting ────────────────────────────────────────────────────────────

    def get_statement(self) -> Dict[str, Dict]:
        """Return per-user profit statement (for dashboards)."""
        with self._lock:
            total = self._total_balance()
            return {
                uid: {
                    "balance_usd": u.balance,
                    "capital_share_pct": round(u.balance / total * 100, 2) if total else 0.0,
                    "total_profit_usd": round(u.total_allocated_usd, 4),
                    "trade_count": u.trade_count,
                    "last_updated": u.last_updated,
                }
                for uid, u in self._users.items()
            }

    def get_history(self, last_n: int = 50) -> List[SplitRecord]:
        """Return the last *n* split records."""
        with self._lock:
            return list(self._history[-last_n:])


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_SPLITTER: Optional[ProfitSplitter] = None
_SPLITTER_LOCK = threading.Lock()


def get_profit_splitter() -> ProfitSplitter:
    """Return the process-wide ProfitSplitter singleton."""
    global _SPLITTER
    with _SPLITTER_LOCK:
        if _SPLITTER is None:
            _SPLITTER = ProfitSplitter()
            logger.info("[ProfitSplitter] singleton created — profit splitting per user enabled")
    return _SPLITTER
