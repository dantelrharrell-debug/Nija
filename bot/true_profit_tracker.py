"""
NIJA True Profit Tracker
========================

Tracks **real, fee-adjusted profit** and account growth after every close.

Formulas
--------
  realized_profit = exit_value - entry_value - fees
  account_growth  = current_cash_balance - starting_balance

Logged after every closed trade
---------------------------------
  💰 NET PROFIT (after fees): $X.XX
  💰 NEW CASH BALANCE: $X.XX

Tracked metrics
---------------
  • Daily PnL
  • Win rate (all-time and today)
  • Average profit per trade
  • Total fees paid

Note: Peak balance is intentionally NOT tracked per requirements.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Dict, Optional

logger = logging.getLogger("nija.true_profit_tracker")

# ---------------------------------------------------------------------------
# Persistence path
# ---------------------------------------------------------------------------

_DEFAULT_DATA_PATH = os.path.join(
    os.path.dirname(__file__), "..", "data", "true_profit_tracker.json"
)

# ---------------------------------------------------------------------------
# Per-broker round-trip fee estimates (entry taker + exit taker combined)
# ---------------------------------------------------------------------------

_BROKER_ROUNDTRIP_FEE: Dict[str, float] = {
    "coinbase": 0.012,  # ~0.6 % taker × 2 sides
    "kraken":   0.006,  # ~0.3 % taker × 2 sides
    "binance":  0.002,  # ~0.1 % taker × 2 sides
    "default":  0.010,  # conservative fallback
}

# Multiplier to estimate entry position size from gross PnL when entry_value_usd
# is unavailable.  A 1 % move on a position produces ~1 % of entry value as profit,
# so gross_pnl × 100 would be the full position — we use 10 as a conservative
# lower-bound (assumes at least 10 % move) to avoid underestimating fees.
_PNL_TO_SIZE: float = 10.0


# ---------------------------------------------------------------------------
# State dataclass
# ---------------------------------------------------------------------------

@dataclass
class _TrueProfitState:
    starting_balance: float = 0.0
    current_cash_balance: float = 0.0
    cumulative_net_profit: float = 0.0
    total_trades: int = 0
    total_wins: int = 0
    total_fees_paid: float = 0.0
    # date string (YYYY-MM-DD) → dict with net_pnl_usd / trades_count / wins
    daily: Dict[str, dict] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tracker
# ---------------------------------------------------------------------------

class TrueProfitTracker:
    """
    Tracks realized profit after fees and account growth.

    Thread-safe singleton; state is persisted to
    ``data/true_profit_tracker.json`` so metrics survive restarts.
    """

    def __init__(self, data_path: str = _DEFAULT_DATA_PATH) -> None:
        self._lock = threading.Lock()
        self._path = data_path
        self._state = _TrueProfitState()
        self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        try:
            if os.path.exists(self._path):
                with open(self._path, "r") as f:
                    raw = json.load(f)
                s = self._state
                s.starting_balance = float(raw.get("starting_balance", 0.0))
                s.current_cash_balance = float(raw.get("current_cash_balance", 0.0))
                s.cumulative_net_profit = float(raw.get("cumulative_net_profit", 0.0))
                s.total_trades = int(raw.get("total_trades", 0))
                s.total_wins = int(raw.get("total_wins", 0))
                s.total_fees_paid = float(raw.get("total_fees_paid", 0.0))
                s.daily = raw.get("daily", {})
                logger.info(
                    "TrueProfitTracker loaded — %d trades | cumulative net profit $%.2f",
                    s.total_trades,
                    s.cumulative_net_profit,
                )
        except Exception as e:
            logger.warning("TrueProfitTracker: could not load state: %s", e)

    def _save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            tmp = self._path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(asdict(self._state), f, indent=2)
            os.replace(tmp, self._path)
        except Exception as e:
            logger.warning("TrueProfitTracker: could not save state: %s", e)

    # ── Public API ────────────────────────────────────────────────────────────

    def set_starting_balance(self, balance: float) -> None:
        """Call once at bot startup with the opening account balance."""
        with self._lock:
            if self._state.starting_balance == 0.0 and balance > 0:
                self._state.starting_balance = balance
                self._state.current_cash_balance = balance
                logger.info(
                    "TrueProfitTracker: starting balance set to $%.2f", balance
                )
                self._save()

    def update_cash_balance(self, balance: float) -> None:
        """Sync the live cash balance fetched from the broker."""
        with self._lock:
            if balance > 0:
                self._state.current_cash_balance = balance
                self._save()
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
        gross_pnl_usd: float,
        is_win: bool,
        entry_value_usd: float = 0.0,
        fee_usd: Optional[float] = None,
        broker: str = "default",
    ) -> float:
        """
        Record a completed (closed) trade and log the result.

        Parameters
        ----------
        symbol          : Trading pair, e.g. ``"BTC-USD"``
        gross_pnl_usd   : exit_value − entry_value  (before fees)
        is_win          : True if gross_pnl_usd > 0
        entry_value_usd : Total USD size at entry — used for fee estimation
        fee_usd         : Exact round-trip fee; estimated from broker rate if None
        broker          : Broker label for per-broker fee lookup

        Returns
        -------
        float
            net_profit_usd = gross_pnl_usd − fee_usd
        """
        # ── Estimate fees when not provided ──────────────────────────────────
        if fee_usd is None:
            broker_key = broker.lower()
            # Exact key lookup first; then partial-match (e.g. "coinbase_advanced" → "coinbase")
            fee_rate = _BROKER_ROUNDTRIP_FEE.get(broker_key, None)
            if fee_rate is None:
                fee_rate = _BROKER_ROUNDTRIP_FEE["default"]
                for k, v in _BROKER_ROUNDTRIP_FEE.items():
                    if k in broker_key:
                        fee_rate = v
                        break
            # When entry_value_usd is unknown, estimate position size as the absolute profit
            # multiplied by _PNL_TO_SIZE: a 1% move on a typical position produces ~1/10th of
            # the entry value as profit, so 10× is a conservative lower-bound on position size.
            base = entry_value_usd if entry_value_usd > 0 else max(abs(gross_pnl_usd) * _PNL_TO_SIZE, 1.0)
            fee_usd = base * fee_rate

        net_profit = gross_pnl_usd - fee_usd
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        with self._lock:
            s = self._state
            s.cumulative_net_profit += net_profit
            s.total_trades += 1
            if is_win:
                s.total_wins += 1
            s.total_fees_paid += fee_usd

            # Advance balance estimate
            if s.current_cash_balance == 0.0 and s.starting_balance > 0:
                s.current_cash_balance = s.starting_balance
            s.current_cash_balance += net_profit

            # Daily bucket
            if today not in s.daily:
                s.daily[today] = {
                    "date": today,
                    "net_pnl_usd": 0.0,
                    "trades_count": 0,
                    "wins": 0,
                }
            s.daily[today]["net_pnl_usd"] += net_profit
            s.daily[today]["trades_count"] += 1
            if is_win:
                s.daily[today]["wins"] += 1

            # Snapshot for log lines (captured while lock is held)
            _cash_bal = s.current_cash_balance
            _account_growth = _cash_bal - s.starting_balance
            _win_rate = (s.total_wins / s.total_trades * 100) if s.total_trades > 0 else 0.0
            _avg_profit = s.cumulative_net_profit / s.total_trades
            _today_pnl = s.daily[today]["net_pnl_usd"]
            _today_wins = s.daily[today]["wins"]
            _today_count = s.daily[today]["trades_count"]

            self._save()

        # ── Log after every close ─────────────────────────────────────────────
        emoji = "✅" if net_profit >= 0 else "🔴"
        logger.info(
            "%s [%s] NET PROFIT (after fees): $%+.2f  "
            "(gross $%+.2f − fees $%.2f)",
            emoji, symbol, net_profit, gross_pnl_usd, fee_usd,
        )
        logger.info(
            "   💰 NEW CASH BALANCE: $%,.2f  |  Account Growth: $%+,.2f",
            _cash_bal, _account_growth,
        )
        _today_wr = (_today_wins / _today_count * 100) if _today_count > 0 else 0.0
        logger.info(
            "   📊 Today PnL: $%+.2f  |  Today Win Rate: %.0f%%  |  "
            "All-time Win Rate: %.1f%%  |  Avg Profit/Trade: $%+.2f  |  "
            "Total Trades: %d",
            _today_pnl, _today_wr, _win_rate, _avg_profit, s.total_trades,
        )

        return net_profit

    # ── Reporting ─────────────────────────────────────────────────────────────

    def get_report(self) -> dict:
        """Return a snapshot of all tracked metrics."""
        with self._lock:
            s = self._state
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            today_data = s.daily.get(today, {})
            today_count = today_data.get("trades_count", 0)
            return {
                "starting_balance": s.starting_balance,
                "current_cash_balance": s.current_cash_balance,
                "account_growth": s.current_cash_balance - s.starting_balance,
                "cumulative_net_profit": s.cumulative_net_profit,
                "total_trades": s.total_trades,
                "total_wins": s.total_wins,
                "win_rate_pct": (
                    s.total_wins / s.total_trades * 100
                ) if s.total_trades > 0 else 0.0,
                "avg_profit_per_trade": (
                    s.cumulative_net_profit / s.total_trades
                ) if s.total_trades > 0 else 0.0,
                "total_fees_paid": s.total_fees_paid,
                "today_pnl": today_data.get("net_pnl_usd", 0.0),
                "today_trades": today_count,
                "today_win_rate_pct": (
                    today_data.get("wins", 0) / today_count * 100
                ) if today_count > 0 else 0.0,
            }

    def log_report(self) -> None:
        """Print a full report to the logger at INFO level."""
        r = self.get_report()
        logger.info("=" * 60)
        logger.info("📊 TRUE PROFIT TRACKER REPORT")
        logger.info("   Starting Balance  : $%,.2f", r["starting_balance"])
        logger.info("   Current Balance   : $%,.2f", r["current_cash_balance"])
        logger.info("   Account Growth    : $%+,.2f", r["account_growth"])
        logger.info("   Net Profit (all)  : $%+,.2f", r["cumulative_net_profit"])
        logger.info("   Total Fees Paid   : $%.2f", r["total_fees_paid"])
        logger.info("   Total Trades      : %d", r["total_trades"])
        logger.info("   Win Rate          : %.1f%%", r["win_rate_pct"])
        logger.info("   Avg Profit/Trade  : $%+.2f", r["avg_profit_per_trade"])
        logger.info("   Today PnL         : $%+.2f", r["today_pnl"])
        logger.info("   Today Win Rate    : %.1f%%", r["today_win_rate_pct"])
        logger.info("=" * 60)
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
_instance_lock = threading.Lock()


def get_true_profit_tracker(
    data_path: str = _DEFAULT_DATA_PATH,
) -> TrueProfitTracker:
    """Return the process-wide ``TrueProfitTracker`` singleton."""
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = TrueProfitTracker(data_path=data_path)
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
