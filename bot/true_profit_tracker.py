"""
NIJA True Profit Tracker
========================

Tracks realized profits strictly from closed trade math:

    realized_profit = exit_value - entry_value - fees

Also tracks:
    account_growth  = current_cash_balance - starting_balance
    daily_pnl       — resets each UTC calendar day
    win_rate        = wins / total_trades (all-time)
    avg_profit      = total_realized_profit / total_trades (all-time)

After every close the tracker emits two mandatory INFO log lines::

    💰 NET PROFIT (after fees): +$X.XX  |  trade #N  |  symbol
    💵 NEW CASH BALANCE: $X.XX  |  account growth: +$X.XX

Then a summary line::

    📊 Daily PnL: $X.XX  |  Win Rate: XX.X% (W/L)  |  Avg Profit/Trade: $X.XX

State is persisted to ``data/true_profit_tracker.json`` so the tracker
survives bot restarts.

Author: NIJA Trading Systems
"""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("nija.true_profit_tracker")

_DEFAULT_DATA_DIR = Path(__file__).parent.parent / "data"
_STATE_FILE = "true_profit_tracker.json"


class TrueProfitTracker:
    """
    Thread-safe singleton that tracks true realized P&L after fees.

    Deliberately omits any "peak balance" concept — account growth is
    always measured from the fixed starting balance set at bot launch.
    """

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self._lock = threading.Lock()
        self._data_dir = Path(data_dir) if data_dir else _DEFAULT_DATA_DIR
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._state_file = self._data_dir / _STATE_FILE

        # --- All-time accumulators ---
        self._starting_balance: float = 0.0
        self._total_realized_profit: float = 0.0
        self._total_fees_paid: float = 0.0
        self._total_trades: int = 0
        self._wins: int = 0
        self._losses: int = 0

        # --- Daily accumulators (reset at UTC midnight) ---
        self._daily_date: str = ""
        self._daily_pnl: float = 0.0
        self._daily_wins: int = 0
        self._daily_losses: int = 0

        self._load_state()
        logger.info(
            "💰 TrueProfitTracker initialised — starting_balance=$%.2f  "
            "total_trades=%d  all-time_pnl=$%.2f",
            self._starting_balance,
            self._total_trades,
            self._total_realized_profit,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_starting_balance(self, balance: float) -> None:
        """
        Record the starting cash balance (call once at bot launch).

        If a starting balance has already been persisted for a previous
        run it is NOT overwritten, so account growth is measured from the
        very first bot start.
        """
        with self._lock:
            if self._starting_balance <= 0.0 and balance > 0:
                self._starting_balance = float(balance)
                self._save_state()
                logger.info(
                    "💰 TrueProfitTracker: starting balance set to $%.2f",
                    self._starting_balance,
                )

    def record_trade(
        self,
        symbol: str,
        entry_value: float,
        exit_value: float,
        fees: float,
        current_balance: float = 0.0,
    ) -> None:
        """
        Record a closed trade and emit mandatory close-log lines.

        Args:
            symbol:          Trading symbol, e.g. ``"BTC-USD"``.
            entry_value:     USD capital deployed at entry (position size).
            exit_value:      USD proceeds received at exit.
            fees:            Total round-trip broker fees in USD.
            current_balance: Current cash balance after the trade closes.
                             Pass 0.0 when unavailable — account growth
                             line will be suppressed.
        """
        realized_profit = exit_value - entry_value - fees
        is_win = realized_profit > 0

        with self._lock:
            self._check_daily_reset()

            # --- All-time ---
            self._total_realized_profit += realized_profit
            self._total_fees_paid += fees
            self._total_trades += 1
            if is_win:
                self._wins += 1
            else:
                self._losses += 1

            # --- Daily ---
            self._daily_pnl += realized_profit
            if is_win:
                self._daily_wins += 1
            else:
                self._daily_losses += 1

            trade_num = self._total_trades
            win_rate = (self._wins / self._total_trades * 100) if self._total_trades else 0.0
            avg_profit = self._total_realized_profit / self._total_trades if self._total_trades else 0.0
            account_growth = (current_balance - self._starting_balance) if (current_balance > 0 and self._starting_balance > 0) else 0.0

            self._save_state()

        # --- Mandatory log lines (outside the lock to avoid deadlocks) ---
        pnl_sign = "+" if realized_profit >= 0 else ""
        logger.info(
            "💰 NET PROFIT (after fees): %s$%.2f  |  trade #%d  |  %s  "
            "|  fees: $%.4f",
            pnl_sign, realized_profit, trade_num, symbol, fees,
        )

        if current_balance > 0:
            growth_str = ""
            if self._starting_balance > 0:
                g_sign = "+" if account_growth >= 0 else ""
                growth_str = f"  |  account growth: {g_sign}${account_growth:.2f}"
            logger.info(
                "💵 NEW CASH BALANCE: $%.2f%s",
                current_balance, growth_str,
            )

        daily_sign = "+" if self._daily_pnl >= 0 else ""
        logger.info(
            "📊 Daily PnL: %s$%.2f  |  Win Rate: %.1f%% (%dW/%dL)  "
            "|  Avg Profit/Trade: $%.2f",
            daily_sign, self._daily_pnl,
            win_rate, self._wins, self._losses,
            avg_profit,
        )

    def get_summary(self, current_balance: float = 0.0) -> dict:
        """
        Return a snapshot dictionary of all tracked metrics.

        Args:
            current_balance: Live cash balance for computing account growth.

        Returns:
            Dict with keys: starting_balance, total_realized_profit,
            total_fees_paid, total_trades, wins, losses, win_rate,
            avg_profit_per_trade, account_growth, daily_pnl,
            daily_wins, daily_losses, daily_date.
        """
        with self._lock:
            self._check_daily_reset()
            win_rate = (self._wins / self._total_trades) if self._total_trades else 0.0
            avg_profit = self._total_realized_profit / self._total_trades if self._total_trades else 0.0
            account_growth = (current_balance - self._starting_balance) if (current_balance > 0 and self._starting_balance > 0) else 0.0
            return {
                "starting_balance": self._starting_balance,
                "total_realized_profit": round(self._total_realized_profit, 4),
                "total_fees_paid": round(self._total_fees_paid, 4),
                "total_trades": self._total_trades,
                "wins": self._wins,
                "losses": self._losses,
                "win_rate": round(win_rate, 4),
                "avg_profit_per_trade": round(avg_profit, 4),
                "account_growth": round(account_growth, 4),
                "daily_pnl": round(self._daily_pnl, 4),
                "daily_wins": self._daily_wins,
                "daily_losses": self._daily_losses,
                "daily_date": self._daily_date,
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _today_utc() -> str:
        return datetime.now(timezone.utc).date().isoformat()

    def _check_daily_reset(self) -> None:
        """Reset daily counters when the UTC calendar date changes."""
        today = self._today_utc()
        if today == self._daily_date:
            return
        if self._daily_date and (self._daily_wins + self._daily_losses) > 0:
            logger.info(
                "📅 TrueProfitTracker day closed [%s] — daily_pnl=$%.2f  "
                "wins=%d  losses=%d",
                self._daily_date, self._daily_pnl,
                self._daily_wins, self._daily_losses,
            )
        self._daily_date = today
        self._daily_pnl = 0.0
        self._daily_wins = 0
        self._daily_losses = 0
        self._save_state()
        logger.info("📅 TrueProfitTracker — new day: %s", today)

    def _save_state(self) -> None:
        """Persist state to JSON (must be called inside the lock)."""
        try:
            state = {
                "starting_balance": self._starting_balance,
                "total_realized_profit": self._total_realized_profit,
                "total_fees_paid": self._total_fees_paid,
                "total_trades": self._total_trades,
                "wins": self._wins,
                "losses": self._losses,
                "daily_date": self._daily_date,
                "daily_pnl": self._daily_pnl,
                "daily_wins": self._daily_wins,
                "daily_losses": self._daily_losses,
            }
            self._state_file.write_text(json.dumps(state, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("TrueProfitTracker: save failed: %s", exc)

    def _load_state(self) -> None:
        """Restore state from JSON if the file exists."""
        if not self._state_file.exists():
            self._daily_date = self._today_utc()
            return
        try:
            state = json.loads(self._state_file.read_text(encoding="utf-8"))
            self._starting_balance = float(state.get("starting_balance", 0.0))
            self._total_realized_profit = float(state.get("total_realized_profit", 0.0))
            self._total_fees_paid = float(state.get("total_fees_paid", 0.0))
            self._total_trades = int(state.get("total_trades", 0))
            self._wins = int(state.get("wins", 0))
            self._losses = int(state.get("losses", 0))

            saved_date = state.get("daily_date", "")
            today = self._today_utc()
            if saved_date == today:
                self._daily_date = saved_date
                self._daily_pnl = float(state.get("daily_pnl", 0.0))
                self._daily_wins = int(state.get("daily_wins", 0))
                self._daily_losses = int(state.get("daily_losses", 0))
            else:
                self._daily_date = today
                self._daily_pnl = 0.0
                self._daily_wins = 0
                self._daily_losses = 0
        except Exception as exc:
            logger.warning("TrueProfitTracker: load failed: %s", exc)
            self._daily_date = self._today_utc()


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_instance: Optional[TrueProfitTracker] = None
_singleton_lock = threading.Lock()


def get_true_profit_tracker(data_dir: Optional[Path] = None) -> TrueProfitTracker:
    """
    Return the process-wide :class:`TrueProfitTracker` singleton.

    Args:
        data_dir: Override the storage directory (useful in tests).

    Returns:
        The singleton :class:`TrueProfitTracker` instance.
    """
    global _instance
    if _instance is None:
        with _singleton_lock:
            if _instance is None:
                _instance = TrueProfitTracker(data_dir=data_dir)
    return _instance
