"""
NIJA Performance Tracker
========================

Lightweight JSON-backed tracker for closed-trade P&L, fees, and slippage.
Designed for micro-account awareness: every dollar of fees and every basis
point of slippage is recorded so the operator can see true net returns.

Usage
-----
On bot start (once):
    tracker = get_performance_tracker()
    tracker.set_starting_balance(current_balance)

When a trade CLOSES (called automatically by execution_engine.execute_exit):
    tracker.record_trade(
        symbol=symbol,
        entry_price=entry_price,
        exit_price=exit_price,
        quantity=quantity,
        side="long",
        fees_usd=fees_paid,
        slippage_usd=slippage,
    )

Periodically (e.g. every 20 cycles):
    tracker.log_stats(current_balance)

Author: NIJA Trading Systems
"""

import json
import logging
import os
import threading
from datetime import datetime
from typing import Dict, List, Optional

logger = logging.getLogger("nija.performance_tracker")

# How often (in completed cycles) to emit a performance report via log_stats.
# At the default 2.5-minute scan interval this equals ~50 minutes.
PERF_LOG_CYCLE_INTERVAL: int = 20


class PerformanceTracker:
    """
    Records closed trades with fees and slippage, computes running stats,
    and persists everything to a JSON file so data survives restarts.
    """

    def __init__(self, filepath: str = "data/performance.json") -> None:
        self.filepath = filepath
        self._lock = threading.Lock()
        self.data = self._load()

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _load(self) -> Dict:
        """Load existing data from disk, or return a blank template."""
        if not os.path.exists(self.filepath):
            return {"trades": [], "starting_balance": None}
        try:
            with open(self.filepath, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as err:
            logger.warning("PerformanceTracker: could not read %s (%s) — starting fresh", self.filepath, err)
            return {"trades": [], "starting_balance": None}

    def _save(self) -> None:
        """Persist current data to disk (caller must hold self._lock)."""
        dir_path = os.path.dirname(self.filepath)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)
        with open(self.filepath, "w") as f:
            json.dump(self.data, f, indent=2)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_starting_balance(self, balance: float) -> None:
        """
        Record the starting balance.  Call once when the bot starts.
        Subsequent calls are ignored so the baseline is never overwritten.
        """
        with self._lock:
            if self.data["starting_balance"] is None:
                self.data["starting_balance"] = balance
                self._save()
                logger.info("📊 PerformanceTracker: starting balance set to $%.2f", balance)

    def record_trade(
        self,
        symbol: str,
        entry_price: float,
        exit_price: float,
        quantity: float,
        side: str = "long",
        fees_usd: float = 0.0,
        slippage_usd: float = 0.0,
    ) -> None:
        """
        Record a fully-closed trade.

        Args:
            symbol:       Trading pair (e.g. 'BTC-USD').
            entry_price:  Price at which the position was opened.
            exit_price:   Expected / signal exit price.
            quantity:     Position size in asset units (e.g. BTC amount).
            side:         'long' or 'short'.
            fees_usd:     Round-trip exchange fees paid in USD.
            slippage_usd: Signed slippage in USD.
                          Negative = unfavourable (we received / paid less/more than expected).
                          Positive = favourable fill.
        """
        if entry_price <= 0:
            logger.debug("PerformanceTracker.record_trade: skipping %s — entry_price is 0", symbol)
            return

        # Gross P&L (before fees and slippage)
        if side == "short":
            gross_pnl = (entry_price - exit_price) * quantity
            raw_pnl_pct = ((entry_price - exit_price) / entry_price) * 100
        else:
            gross_pnl = (exit_price - entry_price) * quantity
            raw_pnl_pct = ((exit_price - entry_price) / entry_price) * 100

        # Net P&L: gross + favourable slippage − fees − unfavourable slippage
        net_pnl = gross_pnl + slippage_usd - fees_usd

        trade: Dict = {
            "symbol": symbol,
            "entry": entry_price,
            "exit": exit_price,
            "qty": quantity,
            "side": side,
            "pnl": gross_pnl,
            "pnl_pct": raw_pnl_pct,
            "fees_usd": fees_usd,
            "slippage_usd": slippage_usd,
            "net_pnl": net_pnl,
            "timestamp": datetime.utcnow().isoformat(),
        }

        with self._lock:
            self.data["trades"].append(trade)
            self._save()

        logger.info(
            "📊 Trade recorded: %s %s | gross=$%.2f | fees=$%.2f | slip=$%.2f | net=$%.2f",
            symbol,
            side.upper(),
            gross_pnl,
            fees_usd,
            slippage_usd,
            net_pnl,
        )

    def get_stats(self, current_balance: float) -> Dict:
        """
        Compute aggregate performance statistics.

        All monetary figures use net_pnl (after fees and slippage) so the
        operator sees the true impact on the account — critical for micro
        accounts where fees can erode a large fraction of gross profit.

        Returns:
            Dict with stats, or empty dict if no trades have been recorded yet.
        """
        with self._lock:
            trades: List[Dict] = list(self.data["trades"])
            starting_balance: Optional[float] = self.data["starting_balance"]

        if not trades:
            return {}

        # Backwards-compatible: old records may lack net_pnl
        def _net(t: Dict) -> float:
            return t.get("net_pnl", t["pnl"])

        total_net_pnl = sum(_net(t) for t in trades)
        wins = [t for t in trades if _net(t) > 0]
        losses = [t for t in trades if _net(t) <= 0]

        win_rate = len(wins) / len(trades) * 100
        avg_win = sum(_net(t) for t in wins) / len(wins) if wins else 0.0
        avg_loss = sum(_net(t) for t in losses) / len(losses) if losses else 0.0

        total_fees = sum(t.get("fees_usd", 0.0) for t in trades)
        # Slippage cost = sum of unfavourable (negative) slippage values, expressed as positive
        total_slippage_cost = sum(
            -t.get("slippage_usd", 0.0)
            for t in trades
            if t.get("slippage_usd", 0.0) < 0
        )

        base = starting_balance if starting_balance else current_balance
        if starting_balance is None:
            logger.warning(
                "PerformanceTracker: starting_balance not set — "
                "call set_starting_balance() on bot start for accurate growth figures"
            )
        growth_pct = ((current_balance - base) / base * 100) if base else 0.0

        return {
            "total_trades": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "total_pnl": total_net_pnl,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "total_fees": total_fees,
            "total_slippage_cost": total_slippage_cost,
            "growth_pct": growth_pct,
        }

    def log_stats(self, current_balance: float) -> None:
        """Pretty-print a performance report."""
        stats = self.get_stats(current_balance)

        if not stats:
            logger.info("📊 PerformanceTracker: no trades recorded yet")
            return

        logger.info("📊 PERFORMANCE REPORT")
        logger.info("===================================")
        logger.info("  Trades   : %d  (W: %d / L: %d)", stats["total_trades"], stats["wins"], stats["losses"])
        logger.info("  Win Rate : %.2f%%", stats["win_rate"])
        logger.info("  Total PnL: $%.2f  (net after fees & slippage)", stats["total_pnl"])
        logger.info("  Avg Win  : $%.2f", stats["avg_win"])
        logger.info("  Avg Loss : $%.2f", stats["avg_loss"])
        logger.info("  Fees Paid: $%.2f", stats["total_fees"])
        logger.info("  Slip Cost: $%.2f", stats["total_slippage_cost"])
        logger.info("  Growth   : %.2f%%", stats["growth_pct"])
        logger.info("===================================")


# ---------------------------------------------------------------------------
# Module-level singleton (thread-safe double-checked locking)
# ---------------------------------------------------------------------------

_TRACKER_INSTANCE: Optional[PerformanceTracker] = None
_TRACKER_LOCK = threading.Lock()


def get_performance_tracker(filepath: str = "data/performance.json") -> PerformanceTracker:
    """Return the process-wide :class:`PerformanceTracker` singleton."""
    global _TRACKER_INSTANCE
    if _TRACKER_INSTANCE is None:
        with _TRACKER_LOCK:
            if _TRACKER_INSTANCE is None:
                _TRACKER_INSTANCE = PerformanceTracker(filepath=filepath)
    return _TRACKER_INSTANCE


__all__ = ["PerformanceTracker", "get_performance_tracker"]
