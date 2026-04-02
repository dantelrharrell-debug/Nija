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
  NET PROFIT (after fees): $X.XX
  NEW CASH BALANCE: $X.XX

Tracked metrics
---------------
  - Daily PnL
  - Win rate (all-time and today)
  - Average profit per trade
  - Total fees paid

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
    "coinbase": 0.014,  # (0.60% taker × 2 sides) + 0.20% spread = 1.40%
    "kraken":   0.0062, # (0.26% taker × 2 sides) + 0.10% spread = 0.62%
    "binance":  0.0028, # (0.10% taker × 2 sides) + 0.08% spread = 0.28%
    "default":  0.014,  # conservative fallback (matches Coinbase)
}

# Minimum net profit per trade to cover fees and deliver real growth.
# A trade returning less than this value is effectively a break-even or loss
# once slippage and compounding friction are accounted for.
MIN_NET_PROFIT_USD: float = float(os.getenv("NIJA_MIN_NET_PROFIT_USD", "0.30"))

# Multiplier to estimate entry position size from gross PnL when entry_value_usd
# is unavailable.  A 1 % move on a position produces ~1 % of entry value as profit,
# so gross_pnl x 100 would be the full position -- we use 10 as a conservative
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
    # date string (YYYY-MM-DD) -> dict with net_pnl_usd / trades_count / wins
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

    # -- Persistence ----------------------------------------------------------

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
                    "TrueProfitTracker loaded -- %d trades | cumulative net profit $%.2f",
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

    # -- Public API -----------------------------------------------------------

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
        gross_pnl_usd   : exit_value - entry_value  (before fees)
        is_win          : True if gross_pnl_usd > 0
        entry_value_usd : Total USD size at entry -- used for fee estimation
        fee_usd         : Exact round-trip fee; estimated from broker rate if None
        broker          : Broker label for per-broker fee lookup

        Returns
        -------
        float
            net_profit_usd = gross_pnl_usd - fee_usd
        """
        # Estimate fees when not provided
        if fee_usd is None:
            broker_key = broker.lower()
            # Exact key lookup first; then partial-match (e.g. "coinbase_advanced" -> "coinbase")
            fee_rate = _BROKER_ROUNDTRIP_FEE.get(broker_key, None)
            if fee_rate is None:
                fee_rate = _BROKER_ROUNDTRIP_FEE["default"]
                for k, v in _BROKER_ROUNDTRIP_FEE.items():
                    if k in broker_key:
                        fee_rate = v
                        break
            # When entry_value_usd is unknown, estimate position size as the absolute profit
            # multiplied by _PNL_TO_SIZE: a 1% move on a typical position produces ~1/10th of
            # the entry value as profit, so 10x is a conservative lower-bound on position size.
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
            _total_trades = s.total_trades

            self._save()

        # Log after every close
        emoji = "OK" if net_profit >= 0 else "LOSS"
        logger.info(
            "[%s] [%s] NET PROFIT (after fees): $%+.2f  "
            "(gross $%+.2f - fees $%.2f)",
            emoji, symbol, net_profit, gross_pnl_usd, fee_usd,
        )
        # Warn when a winning trade returns less than the $0.30 minimum growth
        # threshold.  Losses are already flagged by the "LOSS" emoji above; this
        # warning targets trades that ARE fee-positive but too small to contribute
        # to real account growth (e.g. 0.38% net on a tiny $50 position = $0.19).
        if 0 < net_profit < MIN_NET_PROFIT_USD:
            logger.warning(
                "   ⚠️  BELOW MIN PROFIT: $%.2f net < $%.2f target — "
                "trade is fee-positive but not growing the account. "
                "Consider tightening entry filters or waiting for ≥1%% moves.",
                net_profit, MIN_NET_PROFIT_USD,
            )
        logger.info(
            "   NEW CASH BALANCE: $%,.2f  |  Account Growth: $%+,.2f",
            _cash_bal, _account_growth,
        )
        _today_wr = (_today_wins / _today_count * 100) if _today_count > 0 else 0.0
        logger.info(
            "   Today PnL: $%+.2f  |  Today Win Rate: %.0f%%  |  "
            "All-time Win Rate: %.1f%%  |  Avg Profit/Trade: $%+.2f  |  "
            "Total Trades: %d",
            _today_pnl, _today_wr, _win_rate, _avg_profit, _total_trades,
        )

        return net_profit

    # -- Reporting ------------------------------------------------------------

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
        logger.info("TRUE PROFIT TRACKER REPORT")
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
    return _instance
