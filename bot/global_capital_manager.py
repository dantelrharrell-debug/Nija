"""
NIJA Global Capital Manager
============================

Manages capital allocation and cross-account risk balancing across all
registered broker accounts.

Responsibilities
----------------
1. **Global Capital Scaling** – tracks per-account balances and returns a
   proportional allocation fraction so each account's position size stays
   consistent with its share of total capital.
2. **Cross-Account Risk Balancing** – enforces a 6 % global risk ceiling
   across all accounts so no combination of simultaneous positions can
   exceed the portfolio-wide risk budget.

Usage
-----
::

    from bot.global_capital_manager import get_global_capital_manager

    gcm = get_global_capital_manager()

    # Register account balance once per trading cycle:
    gcm.register_account("coinbase", 5000.0)
    gcm.register_account("kraken",   3000.0)

    # Apply proportional allocation before sizing a position:
    allocation    = gcm.get_allocation("coinbase")   # e.g. 0.625
    position_size *= allocation

    # Gate every trade against the global 6 % risk ceiling:
    requested_risk = position_size / account_balance   # fraction of balance
    if not gcm.can_open_trade(requested_risk):
        return "BLOCKED_GLOBAL_RISK"

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
from typing import Dict, Optional

logger = logging.getLogger("nija.global_capital")

# ---------------------------------------------------------------------------
# Cross-account risk cap (Step 3)
# ---------------------------------------------------------------------------
MAX_GLOBAL_RISK = 0.06  # 6% total risk across all accounts


class GlobalCapitalManager:
    """
    Tracks per-account balances and risk exposures to enable proportional
    position sizing and cross-account risk enforcement.
    """

    def __init__(self) -> None:
        self.accounts: Dict[str, float] = {}        # account_id → balance USD
        self._account_risk: Dict[str, float] = {}   # account_id → current risk fraction
        self._lock = threading.Lock()

    # ── Capital Scaling ───────────────────────────────────────────────────────

    def register_account(self, account_id: str, balance: float) -> None:
        """Register or update an account balance."""
        with self._lock:
            self.accounts[account_id] = max(0.0, balance)
            logger.debug("[GlobalCapital] registered %s balance=%.2f", account_id, balance)

    def total_capital(self) -> float:
        """Return the sum of all registered account balances."""
        with self._lock:
            return sum(self.accounts.values())

    def get_allocation(self, account_id: str) -> float:
        """
        Return this account's proportional share of total capital (0–1).

        Returns 1.0 when the account is the only registered account or when
        total capital is zero, so position sizing is never accidentally zeroed.
        """
        with self._lock:
            total = sum(self.accounts.values())
            if total == 0 or account_id not in self.accounts:
                return 1.0
            return self.accounts[account_id] / total

    # ── Cross-Account Risk Balancing ──────────────────────────────────────────

    def update_account_risk(self, account_id: str, current_risk: float) -> None:
        """Update the current risk fraction already in use for an account."""
        with self._lock:
            self._account_risk[account_id] = max(0.0, current_risk)

    def can_open_trade(self, requested_risk: float) -> bool:
        """
        Return True if adding *requested_risk* keeps the portfolio within
        MAX_GLOBAL_RISK (6 %).

        Args:
            requested_risk: Proposed trade risk as a fraction of account balance
                            (e.g. position_size / account_balance).
        """
        with self._lock:
            total_risk = sum(self._account_risk.values())
            return (total_risk + requested_risk) <= MAX_GLOBAL_RISK


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_MANAGER: Optional[GlobalCapitalManager] = None
_MANAGER_LOCK = threading.Lock()


def get_global_capital_manager() -> GlobalCapitalManager:
    """Return the process-wide GlobalCapitalManager singleton."""
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = GlobalCapitalManager()
            logger.info("[GlobalCapital] singleton created (MAX_GLOBAL_RISK=%.0f%%)", MAX_GLOBAL_RISK * 100)
    return _MANAGER
