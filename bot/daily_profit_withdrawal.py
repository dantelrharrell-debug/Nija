"""
NIJA Daily Profit Withdrawal Lock
===================================

**Pay yourself automatically** as profits grow.

Every trading day, when cumulative realised profits exceed a configurable
minimum threshold, this engine automatically "locks" and withdraws a
fraction of those profits — routing the payout through the existing
:class:`~bot.profit_extraction_engine.ProfitExtractionEngine` which
dispatches to bank, stablecoins, and treasury destinations.

How it works
------------
1. Each time a trade closes with a profit, call ``record_profit(symbol, pnl_usd)``.
2. The engine accumulates profits for the **current calendar day**.
3. Whenever cumulative daily profit exceeds ``min_daily_profit_usd``, the
   engine computes the new **withdrawable** amount:

   .. code-block:: text

       withdrawable_base = daily_profit - min_daily_profit_usd
       new_withdrawal    = withdrawable_base × withdrawal_fraction
                          − already_withdrawn_today   (ratchet: never re-withdraw)

4. If ``new_withdrawal >= min_withdrawal_usd``, it is logged as a
   **locked withdrawal** and dispatched to
   :meth:`ProfitExtractionEngine.extract`.
5. At midnight the daily counters reset.  Any remaining unswept profit is
   optionally extracted via an **end-of-day sweep**.

Default configuration
---------------------
* Minimum daily profit to trigger a withdrawal : **$50**
* Fraction of profits above threshold withdrawn : **30 %**
* Minimum individual withdrawal                 : **$10**
* End-of-day sweep                              : **enabled**

Example
-------
::

    from bot.daily_profit_withdrawal import get_daily_profit_withdrawal_engine

    engine = get_daily_profit_withdrawal_engine()

    # After every winning trade:
    engine.record_profit("BTC-USD", pnl_usd=120.0)

    # End of day:
    engine.run_end_of_day_sweep()

    # Dashboard:
    print(engine.get_report())

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.daily_profit_withdrawal")

# ---------------------------------------------------------------------------
# Optional integration with ProfitExtractionEngine
# ---------------------------------------------------------------------------

try:
    from bot.profit_extraction_engine import get_profit_extraction_engine, ProfitExtractionEngine
    _PEE_AVAILABLE = True
except ImportError:
    try:
        from profit_extraction_engine import get_profit_extraction_engine, ProfitExtractionEngine  # type: ignore
        _PEE_AVAILABLE = True
    except ImportError:
        _PEE_AVAILABLE = False
        get_profit_extraction_engine = None  # type: ignore
        ProfitExtractionEngine = None  # type: ignore
        logger.warning(
            "ProfitExtractionEngine not available — daily withdrawals will be "
            "logged but not dispatched to external destinations"
        )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


@dataclass
class DailyWithdrawalConfig:
    """Configuration for the daily profit withdrawal lock.

    Attributes
    ----------
    min_daily_profit_usd:
        Minimum cumulative daily profit (USD) that must be reached before
        any withdrawal is triggered.  Acts as a "keep-in-trading" buffer.
    withdrawal_fraction:
        Fraction of profits **above** ``min_daily_profit_usd`` that is
        automatically withdrawn on each check.  The ratchet ensures
        already-withdrawn amounts are never double-counted.
    min_withdrawal_usd:
        Smallest individual withdrawal that will be executed.  Smaller
        computed amounts are skipped (avoided dust transactions).
    end_of_day_sweep:
        When ``True``, :meth:`run_end_of_day_sweep` performs a final
        withdrawal of any eligible remaining profits before resetting the
        daily counters at midnight.
    """

    min_daily_profit_usd: float = 50.0
    withdrawal_fraction: float = 0.30
    min_withdrawal_usd: float = 10.0
    end_of_day_sweep: bool = True

    def validate(self) -> None:
        if not 0.0 < self.withdrawal_fraction <= 1.0:
            raise ValueError(
                f"withdrawal_fraction must be in (0, 1], got {self.withdrawal_fraction}"
            )
        if self.min_daily_profit_usd < 0:
            raise ValueError(
                f"min_daily_profit_usd must be >= 0, got {self.min_daily_profit_usd}"
            )
        if self.min_withdrawal_usd < 0:
            raise ValueError(
                f"min_withdrawal_usd must be >= 0, got {self.min_withdrawal_usd}"
            )


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class DailyWithdrawalRecord:
    """A single completed daily profit withdrawal event."""

    withdrawal_id: str
    timestamp: str
    date: str
    amount_usd: float
    daily_profit_at_time: float
    daily_withdrawn_before: float
    trigger: str  # "intraday" | "end_of_day" | "manual"
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------


class DailyProfitWithdrawalEngine:
    """
    Tracks daily realised profits and automatically withdraws a fraction
    once the configured minimum threshold is reached.

    Thread-safe; obtain the process-wide singleton via
    :func:`get_daily_profit_withdrawal_engine`.
    """

    DATA_DIR = Path("data/daily_withdrawal")

    # Retention limits for in-memory audit logs
    MAX_WITHDRAWAL_LOG_SIZE: int = 200
    MAX_DAILY_HISTORY_DAYS: int = 90

    def __init__(
        self,
        config: Optional[DailyWithdrawalConfig] = None,
        data_dir: Optional[Path] = None,
    ) -> None:
        self._lock = threading.RLock()
        self._config = config or DailyWithdrawalConfig()
        self._config.validate()

        # Allow overriding DATA_DIR for testing / multi-instance scenarios
        if data_dir is not None:
            self.DATA_DIR = data_dir

        # Daily state (reset at midnight)
        self._today: str = str(date.today())
        self._daily_profit_usd: float = 0.0
        self._daily_withdrawn_usd: float = 0.0

        # All-time totals
        self._total_profit_recorded_usd: float = 0.0
        self._total_withdrawn_usd: float = 0.0

        # Audit trail
        self._withdrawal_log: List[DailyWithdrawalRecord] = []
        self._daily_history: List[Dict[str, Any]] = []

        self.DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load_state()

        logger.info(
            "✅ DailyProfitWithdrawalEngine initialised | "
            "min_daily_profit=$%.2f  withdrawal_fraction=%.0f%%  "
            "min_withdrawal=$%.2f  eod_sweep=%s",
            self._config.min_daily_profit_usd,
            self._config.withdrawal_fraction * 100,
            self._config.min_withdrawal_usd,
            "yes" if self._config.end_of_day_sweep else "no",
        )

    # ------------------------------------------------------------------
    # Core public API
    # ------------------------------------------------------------------

    def record_profit(
        self,
        symbol: str,
        pnl_usd: float,
        note: str = "",
    ) -> float:
        """
        Record a realised profit from a closed position and trigger an
        automatic withdrawal check.

        Parameters
        ----------
        symbol:
            Trading pair that generated the profit (e.g. ``"BTC-USD"``).
        pnl_usd:
            Realised P&L in USD.  Negative values are ignored (losses do
            not reduce the daily profit counter).
        note:
            Optional annotation stored in the audit log.

        Returns
        -------
        float
            Current cumulative daily profit for today after recording.
        """
        with self._lock:
            self._check_day_rollover()

            if pnl_usd <= 0:
                logger.debug(
                    "Loss/zero P&L $%.2f from %s — not counted toward daily profit",
                    pnl_usd, symbol,
                )
                return self._daily_profit_usd

            self._daily_profit_usd += pnl_usd
            self._total_profit_recorded_usd += pnl_usd

            logger.info(
                "💰 Daily profit: $%.2f (+$%.2f from %s) | "
                "withdrawn_today=$%.2f  threshold=$%.2f",
                self._daily_profit_usd, pnl_usd, symbol,
                self._daily_withdrawn_usd,
                self._config.min_daily_profit_usd,
            )
            self._save_state()

        # Check for withdrawal opportunity outside the lock to avoid
        # nested-lock deadlocks with ProfitExtractionEngine.
        self._check_and_withdraw(
            trigger="intraday",
            note=note or f"after {symbol} profit",
        )
        return self._daily_profit_usd

    def force_withdrawal(self, note: str = "manual") -> Optional[DailyWithdrawalRecord]:
        """
        Manually trigger a withdrawal of any eligible daily profits right now.

        Useful for operator-initiated "pay yourself" calls from a dashboard
        or CLI.

        Returns the :class:`DailyWithdrawalRecord` if a withdrawal was made,
        or ``None`` if there was nothing eligible.
        """
        return self._check_and_withdraw(trigger="manual", note=note)

    def run_end_of_day_sweep(self) -> Optional[DailyWithdrawalRecord]:
        """
        Perform an end-of-day sweep — withdraw any remaining eligible profits
        that were not caught by earlier intraday checks, then roll over to a
        new day.

        Call this once at the end of each trading session (e.g. midnight UTC).
        If ``config.end_of_day_sweep`` is ``False`` the sweep is skipped but
        the rollover still occurs.
        """
        logger.info("🌙 Running end-of-day profit withdrawal sweep for %s", self._today)
        rec: Optional[DailyWithdrawalRecord] = None

        if self._config.end_of_day_sweep:
            rec = self._check_and_withdraw(trigger="end_of_day", note="EOD sweep")

        with self._lock:
            self._rollover_day()

        return rec

    # ------------------------------------------------------------------
    # Internal withdrawal logic
    # ------------------------------------------------------------------

    def _check_and_withdraw(
        self,
        trigger: str,
        note: str = "",
    ) -> Optional[DailyWithdrawalRecord]:
        """
        Compute whether a withdrawal should be made and, if so, execute it.

        Ratchet formula:
            withdrawable_base = daily_profit - min_daily_profit_usd
            new_withdrawal    = withdrawable_base × fraction − already_withdrawn_today

        The ratchet ensures we never double-withdraw profits already extracted
        earlier in the same day.
        """
        with self._lock:
            cfg = self._config

            withdrawable_base = self._daily_profit_usd - cfg.min_daily_profit_usd
            if withdrawable_base <= 0:
                logger.debug(
                    "No withdrawal: daily_profit=$%.2f < threshold=$%.2f",
                    self._daily_profit_usd, cfg.min_daily_profit_usd,
                )
                return None

            # Ratchet: only withdraw the NEW portion not yet extracted
            gross = withdrawable_base * cfg.withdrawal_fraction
            amount = gross - self._daily_withdrawn_usd

            if amount < cfg.min_withdrawal_usd:
                logger.debug(
                    "Withdrawal amount $%.2f below minimum $%.2f — skipping",
                    amount, cfg.min_withdrawal_usd,
                )
                return None

            # Commit the withdrawal
            withdrawn_before = self._daily_withdrawn_usd
            self._daily_withdrawn_usd += amount
            self._total_withdrawn_usd += amount

            rec = DailyWithdrawalRecord(
                withdrawal_id=str(uuid.uuid4()),
                timestamp=datetime.now(timezone.utc).isoformat(),
                date=self._today,
                amount_usd=amount,
                daily_profit_at_time=self._daily_profit_usd,
                daily_withdrawn_before=withdrawn_before,
                trigger=trigger,
                note=note,
            )
            self._withdrawal_log.append(rec)
            self._save_state()

            logger.info(
                "💸 DAILY PROFIT WITHDRAWAL LOCKED\n"
                "  Amount          : $%.2f\n"
                "  Trigger         : %s\n"
                "  Daily Profit    : $%.2f\n"
                "  Withdrawn Today : $%.2f (cumulative)\n"
                "  Retained        : $%.2f",
                amount,
                trigger,
                self._daily_profit_usd,
                self._daily_withdrawn_usd,
                self._daily_profit_usd - self._daily_withdrawn_usd,
            )

        # Dispatch to extraction engine outside the lock
        if _PEE_AVAILABLE and get_profit_extraction_engine is not None:
            try:
                engine = get_profit_extraction_engine()
                engine.extract(
                    amount_usd=amount,
                    note=f"daily-withdrawal/{trigger}: {note}",
                )
            except Exception as exc:
                logger.warning(
                    "DailyProfitWithdrawalEngine: extraction dispatch failed: %s", exc
                )

        return rec

    # ------------------------------------------------------------------
    # Day rollover
    # ------------------------------------------------------------------

    def _check_day_rollover(self) -> None:
        """Called inside the lock. Rolls over the day if the calendar date changed."""
        if str(date.today()) != self._today:
            self._rollover_day()

    def _rollover_day(self) -> None:
        """Archive today's data and reset daily counters. Must be called inside the lock."""
        if self._daily_profit_usd > 0 or self._daily_withdrawn_usd > 0:
            self._daily_history.append(
                {
                    "date": self._today,
                    "daily_profit_usd": self._daily_profit_usd,
                    "daily_withdrawn_usd": self._daily_withdrawn_usd,
                    "net_retained_usd": self._daily_profit_usd - self._daily_withdrawn_usd,
                    "withdrawal_rate_pct": (
                        self._daily_withdrawn_usd / self._daily_profit_usd * 100
                        if self._daily_profit_usd > 0
                        else 0.0
                    ),
                }
            )
            if len(self._daily_history) > self.MAX_DAILY_HISTORY_DAYS:
                self._daily_history = self._daily_history[-self.MAX_DAILY_HISTORY_DAYS:]

        self._today = str(date.today())
        self._daily_profit_usd = 0.0
        self._daily_withdrawn_usd = 0.0

        logger.info("📅 DailyProfitWithdrawalEngine: rolled over to %s", self._today)
        self._save_state()

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _state_path(self) -> Path:
        return self.DATA_DIR / "state.json"

    def _save_state(self) -> None:
        try:
            state = {
                "today": self._today,
                "daily_profit_usd": self._daily_profit_usd,
                "daily_withdrawn_usd": self._daily_withdrawn_usd,
                "total_profit_recorded_usd": self._total_profit_recorded_usd,
                "total_withdrawn_usd": self._total_withdrawn_usd,
                "withdrawal_log": [
                    r.to_dict()
                    for r in self._withdrawal_log[-self.MAX_WITHDRAWAL_LOG_SIZE:]
                ],
                "daily_history": self._daily_history[-self.MAX_DAILY_HISTORY_DAYS:],
            }
            tmp = self._state_path().with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump(state, f, indent=2)
            tmp.replace(self._state_path())
        except Exception as exc:
            logger.warning("DailyProfitWithdrawalEngine: failed to save state: %s", exc)

    def _load_state(self) -> None:
        path = self._state_path()
        if not path.exists():
            return
        try:
            with open(path) as f:
                state = json.load(f)

            saved_today = state.get("today", "")
            if saved_today == str(date.today()):
                self._daily_profit_usd = float(state.get("daily_profit_usd", 0.0))
                self._daily_withdrawn_usd = float(state.get("daily_withdrawn_usd", 0.0))
            else:
                logger.info(
                    "DailyProfitWithdrawalEngine: saved date (%s) != today — resetting daily counters",
                    saved_today,
                )

            self._total_profit_recorded_usd = float(
                state.get("total_profit_recorded_usd", 0.0)
            )
            self._total_withdrawn_usd = float(state.get("total_withdrawn_usd", 0.0))
            self._withdrawal_log = [
                DailyWithdrawalRecord(**r) for r in state.get("withdrawal_log", [])
            ]
            self._daily_history = list(state.get("daily_history", []))

            logger.info(
                "DailyProfitWithdrawalEngine: state loaded | "
                "daily_profit=$%.2f  withdrawn_today=$%.2f  all_time_withdrawn=$%.2f",
                self._daily_profit_usd,
                self._daily_withdrawn_usd,
                self._total_withdrawn_usd,
            )
        except Exception as exc:
            logger.warning(
                "DailyProfitWithdrawalEngine: failed to load state (starting fresh): %s", exc
            )

    # ------------------------------------------------------------------
    # Status & reporting
    # ------------------------------------------------------------------

    def get_daily_summary(self) -> Dict[str, Any]:
        """Return a dict with today's withdrawal state."""
        with self._lock:
            withdrawals_today = [
                r for r in self._withdrawal_log if r.date == self._today
            ]
            return {
                "date": self._today,
                "daily_profit_usd": self._daily_profit_usd,
                "daily_withdrawn_usd": self._daily_withdrawn_usd,
                "daily_retained_usd": self._daily_profit_usd - self._daily_withdrawn_usd,
                "withdrawal_rate_pct": (
                    self._daily_withdrawn_usd / self._daily_profit_usd * 100
                    if self._daily_profit_usd > 0
                    else 0.0
                ),
                "total_profit_recorded_usd": self._total_profit_recorded_usd,
                "total_withdrawn_usd": self._total_withdrawn_usd,
                "withdrawals_today_count": len(withdrawals_today),
                "config": {
                    "min_daily_profit_usd": self._config.min_daily_profit_usd,
                    "withdrawal_fraction": self._config.withdrawal_fraction,
                    "min_withdrawal_usd": self._config.min_withdrawal_usd,
                    "end_of_day_sweep": self._config.end_of_day_sweep,
                },
            }

    def get_recent_withdrawals(self, n: int = 10) -> List[Dict[str, Any]]:
        """Return the *n* most recent withdrawal records as dicts."""
        with self._lock:
            return [r.to_dict() for r in self._withdrawal_log[-n:]]

    def get_daily_history(self, n: int = 30) -> List[Dict[str, Any]]:
        """Return the last *n* days of daily profit / withdrawal history."""
        with self._lock:
            return list(self._daily_history[-n:])

    def get_report(self) -> str:
        """Generate a human-readable daily withdrawal status report."""
        summary = self.get_daily_summary()
        cfg = self._config
        lines = [
            "=" * 70,
            "  NIJA DAILY PROFIT WITHDRAWAL LOCK — STATUS REPORT",
            "=" * 70,
            f"  Date                  : {summary['date']}",
            f"  Daily Profit          : ${summary['daily_profit_usd']:>14,.2f}",
            f"  Withdrawn Today       : ${summary['daily_withdrawn_usd']:>14,.2f}",
            f"  Retained for Trading  : ${summary['daily_retained_usd']:>14,.2f}",
            f"  Withdrawal Rate       : {summary['withdrawal_rate_pct']:>13.1f}%",
            f"  Withdrawals Today     : {summary['withdrawals_today_count']:>14,}",
            "",
            "  CONFIGURATION",
            "-" * 70,
            f"  Min Daily Profit (trigger)  : ${cfg.min_daily_profit_usd:,.2f}",
            f"  Withdrawal Fraction         : {cfg.withdrawal_fraction * 100:.0f}%",
            f"  Min Individual Withdrawal   : ${cfg.min_withdrawal_usd:,.2f}",
            f"  End-of-Day Sweep            : {'Yes' if cfg.end_of_day_sweep else 'No'}",
            "",
            "  ALL-TIME TOTALS",
            "-" * 70,
            f"  Total Profit Recorded : ${summary['total_profit_recorded_usd']:>14,.2f}",
            f"  Total Withdrawn       : ${summary['total_withdrawn_usd']:>14,.2f}",
        ]

        recent = self.get_recent_withdrawals(n=5)
        if recent:
            lines += [
                "",
                "  RECENT WITHDRAWALS",
                "-" * 70,
            ]
            for rec in reversed(recent):
                lines.append(
                    f"  {rec['timestamp'][:19]}  ${rec['amount_usd']:>10,.2f}"
                    f"  [{rec['trigger']}]  {rec['note']}"
                )

        lines.append("=" * 70)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_instance: Optional[DailyProfitWithdrawalEngine] = None
_instance_lock = threading.Lock()


def get_daily_profit_withdrawal_engine(
    config: Optional[DailyWithdrawalConfig] = None,
) -> DailyProfitWithdrawalEngine:
    """
    Return the process-wide :class:`DailyProfitWithdrawalEngine` singleton.

    The *config* parameter is only applied on **first call**.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = DailyProfitWithdrawalEngine(config=config)
    return _instance


__all__ = [
    "DailyWithdrawalConfig",
    "DailyWithdrawalRecord",
    "DailyProfitWithdrawalEngine",
    "get_daily_profit_withdrawal_engine",
]


# ---------------------------------------------------------------------------
# Quick smoke-test / demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import logging as _logging

    _logging.basicConfig(level=_logging.INFO, format="%(levelname)s - %(message)s")

    # Low threshold for demo purposes
    cfg = DailyWithdrawalConfig(
        min_daily_profit_usd=100.0,
        withdrawal_fraction=0.30,
        min_withdrawal_usd=5.0,
        end_of_day_sweep=True,
    )
    engine = get_daily_profit_withdrawal_engine(config=cfg)

    print(engine.get_report())
    print("\n📈 Simulating a trading day...\n")

    # A series of winning trades
    for symbol, pnl in [
        ("BTC-USD", 40.0),   # $40  — below threshold, no withdrawal yet
        ("ETH-USD", 35.0),   # $75  — below threshold
        ("SOL-USD", 50.0),   # $125 — above threshold: 30% × ($125−$100) = $7.50 withdrawn
        ("ADA-USD", 80.0),   # $205 — 30% × ($205−$100) = $31.50 gross, minus $7.50 = $24 new
    ]:
        print(f"\n  → recording ${pnl:.0f} profit from {symbol}")
        engine.record_profit(symbol, pnl_usd=pnl)

    print("\n📊 After trades:")
    print(engine.get_report())

    print("\n🌙 Running end-of-day sweep…")
    engine.run_end_of_day_sweep()
    print(engine.get_report())
