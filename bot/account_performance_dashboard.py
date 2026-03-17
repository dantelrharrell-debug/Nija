"""
NIJA Account Performance Dashboard
=====================================

Per-account performance tracking with rolling Sharpe ratio, win-rate,
profit factor, and drawdown — surfaced as a single dashboard dict that
any API layer can render.

Usage
-----
::

    from bot.account_performance_dashboard import get_account_performance_dashboard

    dash = get_account_performance_dashboard()
    dash.record_trade("coinbase", pnl_usd=42.0, is_win=True)
    dash.record_trade("kraken",  pnl_usd=-15.0, is_win=False)

    print(dash.get_dashboard())               # all accounts
    print(dash.get_account_stats("coinbase")) # single account

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import math
import threading
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Deque, Dict, List, Optional

logger = logging.getLogger("nija.account_dashboard")

# Rolling window for Sharpe / profit-factor calculations
ROLLING_WINDOW = 50


# ---------------------------------------------------------------------------
# Per-account state
# ---------------------------------------------------------------------------

@dataclass
class AccountStats:
    """Rolling performance metrics for one broker account."""
    account_id: str
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    gross_profit: float = 0.0
    gross_loss: float = 0.0          # stored as negative sum
    peak_equity: float = 0.0
    current_equity: float = 0.0
    max_drawdown_pct: float = 0.0
    _pnl_window: Deque[float] = field(default_factory=lambda: deque(maxlen=ROLLING_WINDOW))
    last_updated: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    # ── derived metrics ───────────────────────────────────────────────────────

    @property
    def win_rate(self) -> float:
        return self.wins / self.total_trades if self.total_trades else 0.0

    @property
    def profit_factor(self) -> float:
        return self.gross_profit / abs(self.gross_loss) if self.gross_loss != 0 else float("inf")

    @property
    def sharpe_ratio(self) -> float:
        """Annualised Sharpe using rolling P&L window (assuming 150 trades/yr)."""
        data = list(self._pnl_window)
        if len(data) < 2:
            return 0.0
        n = len(data)
        mean = sum(data) / n
        variance = sum((x - mean) ** 2 for x in data) / (n - 1)
        std = math.sqrt(variance) if variance > 0 else 0.0
        if std == 0:
            return 0.0
        return round((mean / std) * math.sqrt(150), 3)

    def to_dict(self) -> Dict:
        return {
            "account_id": self.account_id,
            "total_trades": self.total_trades,
            "wins": self.wins,
            "losses": self.losses,
            "win_rate_pct": round(self.win_rate * 100, 2),
            "profit_factor": round(self.profit_factor, 3) if math.isfinite(self.profit_factor) else "∞",
            "sharpe_ratio": self.sharpe_ratio,
            "gross_profit_usd": round(self.gross_profit, 4),
            "gross_loss_usd": round(self.gross_loss, 4),
            "net_pnl_usd": round(self.gross_profit + self.gross_loss, 4),
            "max_drawdown_pct": round(self.max_drawdown_pct, 2),
            "current_equity_usd": round(self.current_equity, 2),
            "last_updated": self.last_updated,
        }


# ---------------------------------------------------------------------------
# Dashboard engine
# ---------------------------------------------------------------------------

class AccountPerformanceDashboard:
    """
    Collects per-account trade results and exposes a real-time performance
    dashboard for all registered broker accounts.
    """

    def __init__(self) -> None:
        self._accounts: Dict[str, AccountStats] = {}
        self._lock = threading.Lock()

    # ── Trade recording ───────────────────────────────────────────────────────

    def record_trade(
        self,
        account_id: str,
        pnl_usd: float,
        is_win: bool,
        equity_usd: Optional[float] = None,
    ) -> None:
        """
        Record a completed trade for *account_id*.

        Args:
            account_id: Broker / account identifier (e.g. "coinbase").
            pnl_usd: Net P&L of the closed trade in USD.
            is_win: True if the trade was profitable.
            equity_usd: Current total equity (used for drawdown tracking).
        """
        with self._lock:
            stats = self._accounts.setdefault(
                account_id,
                AccountStats(account_id=account_id),
            )
            stats.total_trades += 1
            stats._pnl_window.append(pnl_usd)

            if is_win:
                stats.wins += 1
                stats.gross_profit += pnl_usd
            else:
                stats.losses += 1
                stats.gross_loss += pnl_usd      # pnl_usd is negative for losses

            if equity_usd is not None:
                stats.current_equity = equity_usd
                if equity_usd > stats.peak_equity:
                    stats.peak_equity = equity_usd
                if stats.peak_equity > 0:
                    dd = (stats.peak_equity - equity_usd) / stats.peak_equity * 100
                    stats.max_drawdown_pct = max(stats.max_drawdown_pct, dd)

            stats.last_updated = datetime.now(timezone.utc).isoformat()

        logger.debug(
            "[Dashboard] %s trade recorded pnl=%.2f win=%s", account_id, pnl_usd, is_win
        )

    def update_equity(self, account_id: str, equity_usd: float) -> None:
        """Update equity snapshot without recording a trade."""
        with self._lock:
            stats = self._accounts.setdefault(
                account_id,
                AccountStats(account_id=account_id),
            )
            stats.current_equity = equity_usd
            if equity_usd > stats.peak_equity:
                stats.peak_equity = equity_usd
            if stats.peak_equity > 0:
                dd = (stats.peak_equity - equity_usd) / stats.peak_equity * 100
                stats.max_drawdown_pct = max(stats.max_drawdown_pct, dd)

    # ── Reporting ─────────────────────────────────────────────────────────────

    def get_account_stats(self, account_id: str) -> Optional[Dict]:
        """Return dashboard dict for a single account, or None if unknown."""
        with self._lock:
            stats = self._accounts.get(account_id)
            return stats.to_dict() if stats else None

    def get_dashboard(self) -> Dict[str, Dict]:
        """Return dashboard dicts for ALL registered accounts."""
        with self._lock:
            return {aid: stats.to_dict() for aid, stats in self._accounts.items()}

    def get_best_performer(self) -> Optional[str]:
        """Return the account_id with the highest Sharpe ratio."""
        with self._lock:
            if not self._accounts:
                return None
            return max(
                self._accounts,
                key=lambda aid: self._accounts[aid].sharpe_ratio,
            )

    def get_sorted_accounts(self, by: str = "sharpe_ratio") -> List[Dict]:
        """
        Return all accounts sorted by *by* metric (descending).

        Supported keys: ``sharpe_ratio``, ``win_rate_pct``, ``net_pnl_usd``,
        ``profit_factor``.
        """
        with self._lock:
            rows = [stats.to_dict() for stats in self._accounts.values()]

        def _key(row: Dict) -> float:
            val = row.get(by, 0)
            if isinstance(val, str):  # e.g. "∞"
                return float("inf")
            return float(val)

        return sorted(rows, key=_key, reverse=True)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_DASHBOARD: Optional[AccountPerformanceDashboard] = None
_DASHBOARD_LOCK = threading.Lock()


def get_account_performance_dashboard() -> AccountPerformanceDashboard:
    """Return the process-wide AccountPerformanceDashboard singleton."""
    global _DASHBOARD
    with _DASHBOARD_LOCK:
        if _DASHBOARD is None:
            _DASHBOARD = AccountPerformanceDashboard()
            logger.info(
                "[Dashboard] singleton created — per-account performance tracking enabled"
            )
    return _DASHBOARD
