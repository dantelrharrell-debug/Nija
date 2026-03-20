"""
NIJA Profit Visibility Tracker
================================

Provides a single authoritative view of three profit categories:

* **Realized profit** — total net P&L from all closed trades (wins minus losses).
* **Locked profit** — profit currently "locked in" across open positions via
  the ratchet-floor system (see :class:`~bot.profit_lock_engine.ProfitLockEngine`).
* **Withdrawable profit** — profit that has cleared the withdrawal thresholds
  and is ready to be swept out (extraction-pool balance).

These three numbers give operators true performance visibility, build
confidence that the system is preserving gains, and drive clean reporting.

Usage
-----
::

    from bot.profit_visibility_tracker import get_profit_visibility_tracker

    tracker = get_profit_visibility_tracker()

    # After every trade closes:
    tracker.record_realized(symbol="BTC-USD", pnl_usd=+120.0)

    # Every price tick (for open positions):
    tracker.update_locked(symbol="BTC-USD", locked_usd=45.0)

    # Get the current snapshot:
    snap = tracker.get_snapshot()
    print(snap)  # ProfitSnapshot(realized=+120.00, locked=45.00, withdrawable=36.00)

    # Dashboard-ready string:
    print(tracker.get_report())

Thread Safety
-------------
All public methods are protected by a re-entrant lock.

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("nija.profit_visibility_tracker")

# ---------------------------------------------------------------------------
# State file
# ---------------------------------------------------------------------------

_DEFAULT_DATA_DIR = Path(os.environ.get("NIJA_DATA_DIR", "data"))
_STATE_FILE = _DEFAULT_DATA_DIR / "profit_visibility_state.json"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class ProfitSnapshot:
    """Point-in-time view of all three profit categories."""

    realized_usd: float = 0.0       # Cumulative closed-trade P&L (wins - losses)
    locked_usd: float = 0.0         # Currently locked across all open positions
    withdrawable_usd: float = 0.0   # Ready to sweep out of the extraction pool
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def __str__(self) -> str:
        return (
            f"ProfitSnapshot("
            f"realized=${self.realized_usd:,.2f}, "
            f"locked=${self.locked_usd:,.2f}, "
            f"withdrawable=${self.withdrawable_usd:,.2f})"
        )


# ---------------------------------------------------------------------------
# ProfitVisibilityTracker
# ---------------------------------------------------------------------------


class ProfitVisibilityTracker:
    """
    Tracks realized, locked, and withdrawable profit in a single engine.

    **Realized profit** is accumulated via :meth:`record_realized` after
    every trade close (positive for wins, negative for losses).

    **Locked profit** is the sum of per-position lock floors.  It is updated
    via :meth:`update_locked` / :meth:`remove_position_lock` as the ratchet
    engine moves floors on open positions.

    **Withdrawable profit** mirrors the extraction-pool balance.  Update it
    via :meth:`set_withdrawable` or :meth:`record_extraction` whenever the
    :class:`~bot.profit_extraction_engine.ProfitExtractionEngine` accumulates
    or disburses funds.

    Obtain the singleton via :func:`get_profit_visibility_tracker`.
    """

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self._lock = threading.RLock()

        _dir = data_dir if data_dir is not None else _DEFAULT_DATA_DIR
        _dir = Path(_dir)
        _dir.mkdir(parents=True, exist_ok=True)
        self._state_file = _dir / "profit_visibility_state.json"

        # Cumulative realized P&L (all closed trades, wins and losses)
        self._realized_usd: float = 0.0

        # Per-position locked amounts {symbol: locked_usd}
        self._position_locks: Dict[str, float] = {}

        # Withdrawal pool balance (set by extraction engine)
        self._withdrawable_usd: float = 0.0

        # All-time extraction disbursed
        self._total_extracted_usd: float = 0.0

        self._load_state()

        logger.info(
            "✅ ProfitVisibilityTracker initialised | "
            "realized=$%.2f | locked=$%.2f | withdrawable=$%.2f",
            self._realized_usd,
            self._total_locked_usd(),
            self._withdrawable_usd,
        )

    # ------------------------------------------------------------------
    # Realized profit
    # ------------------------------------------------------------------

    def record_realized(self, symbol: str, pnl_usd: float) -> float:
        """
        Record the realized P&L from a closed trade.

        Both wins (positive) and losses (negative) are accumulated so the
        ``realized_usd`` figure reflects true net performance.

        Parameters
        ----------
        symbol:
            Trading pair (used only for logging).
        pnl_usd:
            Net P&L in USD (+profit / −loss).

        Returns
        -------
        float
            Updated cumulative realized profit.
        """
        with self._lock:
            self._realized_usd += pnl_usd
            self._save_state()
            logger.debug(
                "ProfitVisibility: realized %+.2f from %s → cumulative=$%.2f",
                pnl_usd, symbol, self._realized_usd,
            )
            return self._realized_usd

    # ------------------------------------------------------------------
    # Locked profit (per open position)
    # ------------------------------------------------------------------

    def update_locked(self, symbol: str, locked_usd: float) -> float:
        """
        Set the locked profit amount for a single open position.

        Call this whenever the ratchet engine upgrades the lock floor for
        ``symbol``.

        Parameters
        ----------
        symbol:
            Trading pair.
        locked_usd:
            Absolute USD amount locked for this position (≥ 0).

        Returns
        -------
        float
            Updated total locked profit across all open positions.
        """
        with self._lock:
            locked_usd = max(0.0, locked_usd)
            self._position_locks[symbol] = locked_usd
            total = self._total_locked_usd()
            logger.debug(
                "ProfitVisibility: locked $%.2f for %s → total_locked=$%.2f",
                locked_usd, symbol, total,
            )
            return total

    def remove_position_lock(self, symbol: str) -> float:
        """
        Remove the locked-profit entry for a closed position.

        Parameters
        ----------
        symbol:
            Trading pair to remove.

        Returns
        -------
        float
            Remaining total locked profit across all still-open positions.
        """
        with self._lock:
            removed = self._position_locks.pop(symbol, 0.0)
            total = self._total_locked_usd()
            if removed > 0:
                logger.debug(
                    "ProfitVisibility: removed lock $%.2f for %s → total_locked=$%.2f",
                    removed, symbol, total,
                )
            return total

    # ------------------------------------------------------------------
    # Withdrawable profit (extraction-pool mirror)
    # ------------------------------------------------------------------

    def set_withdrawable(self, pool_balance_usd: float) -> None:
        """
        Set the current withdrawable pool balance (mirrors the extraction engine).

        Parameters
        ----------
        pool_balance_usd:
            Absolute current balance of the profit extraction pool in USD.
        """
        with self._lock:
            self._withdrawable_usd = max(0.0, pool_balance_usd)
            logger.debug(
                "ProfitVisibility: withdrawable pool=$%.2f", self._withdrawable_usd
            )

    def record_extraction(self, amount_usd: float) -> float:
        """
        Record a disbursement (withdrawal) from the extraction pool.

        Decrements the withdrawable balance and adds to the all-time extraction
        total.

        Parameters
        ----------
        amount_usd:
            Amount disbursed in USD.

        Returns
        -------
        float
            Remaining withdrawable balance.
        """
        with self._lock:
            amount_usd = max(0.0, amount_usd)
            self._withdrawable_usd = max(0.0, self._withdrawable_usd - amount_usd)
            self._total_extracted_usd += amount_usd
            self._save_state()
            logger.info(
                "💸 ProfitVisibility: extracted $%.2f → pool=$%.2f | total_extracted=$%.2f",
                amount_usd, self._withdrawable_usd, self._total_extracted_usd,
            )
            return self._withdrawable_usd

    # ------------------------------------------------------------------
    # Snapshot & reporting
    # ------------------------------------------------------------------

    def get_snapshot(self) -> ProfitSnapshot:
        """Return a point-in-time :class:`ProfitSnapshot`."""
        with self._lock:
            return ProfitSnapshot(
                realized_usd=self._realized_usd,
                locked_usd=self._total_locked_usd(),
                withdrawable_usd=self._withdrawable_usd,
            )

    def get_report(self) -> str:
        """Return a human-readable dashboard string."""
        snap = self.get_snapshot()
        with self._lock:
            total_extracted = self._total_extracted_usd
            position_count = len(self._position_locks)

        lines = [
            "=" * 60,
            "📊  PROFIT VISIBILITY TRACKER — STATUS REPORT",
            "=" * 60,
            f"  Realized Profit       : ${snap.realized_usd:>14,.2f}",
            f"  Locked Profit         : ${snap.locked_usd:>14,.2f}  "
            f"({position_count} open position(s))",
            f"  Withdrawable Profit   : ${snap.withdrawable_usd:>14,.2f}",
            f"  Total Extracted       : ${total_extracted:>14,.2f}",
            "-" * 60,
            f"  Net P&L (realized)    : ${snap.realized_usd:>+14,.2f}",
            "=" * 60,
        ]
        return "\n".join(lines)

    def get_metrics(self) -> Dict[str, Any]:
        """Return a serialisable metrics dictionary suitable for APIs/dashboards."""
        snap = self.get_snapshot()
        with self._lock:
            return {
                "realized_profit_usd": snap.realized_usd,
                "locked_profit_usd": snap.locked_usd,
                "withdrawable_profit_usd": snap.withdrawable_usd,
                "total_extracted_usd": self._total_extracted_usd,
                "open_position_locks": dict(self._position_locks),
                "timestamp": snap.timestamp,
            }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _total_locked_usd(self) -> float:
        """Sum of all per-position lock amounts (must be called under lock)."""
        return sum(self._position_locks.values())

    def _save_state(self) -> None:
        """Persist running totals to disk (called under lock)."""
        state = {
            "realized_usd": self._realized_usd,
            "withdrawable_usd": self._withdrawable_usd,
            "total_extracted_usd": self._total_extracted_usd,
            "position_locks": self._position_locks,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        try:
            with open(self._state_file, "w") as fh:
                json.dump(state, fh, indent=2)
        except Exception as exc:
            logger.warning("ProfitVisibilityTracker: state save failed — %s", exc)

    def _load_state(self) -> None:
        """Restore persisted state on startup."""
        try:
            with open(self._state_file, "r") as fh:
                state = json.load(fh)
            self._realized_usd = float(state.get("realized_usd", 0.0))
            self._withdrawable_usd = float(state.get("withdrawable_usd", 0.0))
            self._total_extracted_usd = float(state.get("total_extracted_usd", 0.0))
            self._position_locks = {
                str(k): float(v)
                for k, v in state.get("position_locks", {}).items()
            }
            logger.info(
                "💾 ProfitVisibilityTracker: state loaded from %s "
                "(realized=$%.2f, locked=$%.2f, withdrawable=$%.2f)",
                self._state_file,
                self._realized_usd,
                self._total_locked_usd(),
                self._withdrawable_usd,
            )
        except FileNotFoundError:
            pass  # First run — start fresh
        except Exception as exc:
            logger.warning("ProfitVisibilityTracker: state load failed — %s", exc)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_TRACKER_INSTANCE: Optional[ProfitVisibilityTracker] = None
_TRACKER_INSTANCE_LOCK = threading.Lock()


def get_profit_visibility_tracker() -> ProfitVisibilityTracker:
    """
    Return the process-wide singleton :class:`ProfitVisibilityTracker`.

    Thread-safe; created once on first call.
    """
    global _TRACKER_INSTANCE
    if _TRACKER_INSTANCE is None:
        with _TRACKER_INSTANCE_LOCK:
            if _TRACKER_INSTANCE is None:
                _TRACKER_INSTANCE = ProfitVisibilityTracker()
    return _TRACKER_INSTANCE
