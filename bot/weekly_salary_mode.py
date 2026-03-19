"""
NIJA Weekly Salary Mode
========================

Locks a fixed weekly payout so the bot operator receives predictable,
real-life-usable income — **only when the system is profitable**.

How it works
------------
1. After each trade closes, call ``record_profit(pnl_usd)`` to grow the
   weekly profit pool.
2. At the end of each ISO calendar week (or on demand via
   ``try_pay_salary()``), the engine checks three conditions:

   * The week's net profit is **≥ 0** (system is profitable).
   * The accumulated pool contains **enough funds** to cover the capped payout.
   * The ``EmergencyCapitalProtection`` engine is **not** active (account
     is not in a drawdown protection mode of WARNING or higher).

3. If all conditions pass the actual payout is::

       payout = min(weekly_profit * 0.5, weekly_salary_usd)

   That amount is deducted from the pool and logged as a salary payment.
   Any surplus above the payout remains in the pool for the following week.
4. If the system is *not* profitable, or the capital protection engine is
   active, the payout is **skipped** and the pool is carried forward — no
   salary is ever taken from base capital.

Architecture
------------
::

  ┌──────────────────────────────────────────────────────────────────┐
  │                    WeeklySalaryMode                              │
  │                                                                  │
  │  record_profit(pnl_usd)  →  weekly pool grows                   │
  │  try_pay_salary()        →  checks profit gate → pays / skips   │
  │  get_report()            →  status dashboard                     │
  └──────────────────────────────────────────────────────────────────┘

Usage
-----
    from bot.weekly_salary_mode import get_weekly_salary_mode, SalaryConfig

    engine = get_weekly_salary_mode()

    # After a trade closes:
    engine.record_profit(pnl_usd=320.0)

    # Check / pay at week boundary (safe to call every cycle — idempotent
    # within the same ISO week):
    result = engine.try_pay_salary()

    # Force an immediate pay attempt regardless of week boundary:
    result = engine.try_pay_salary(force=True)

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
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.weekly_salary_mode")

# ---------------------------------------------------------------------------
# Optional: EmergencyCapitalProtection integration
# ---------------------------------------------------------------------------

try:
    from bot.emergency_capital_protection import get_emergency_capital_protection
    _ECP_AVAILABLE = True
except ImportError:
    try:
        from emergency_capital_protection import get_emergency_capital_protection  # type: ignore
        _ECP_AVAILABLE = True
    except ImportError:
        get_emergency_capital_protection = None  # type: ignore
        _ECP_AVAILABLE = False
        logger.debug("EmergencyCapitalProtection not available — salary always allowed when profitable")

# ---------------------------------------------------------------------------
# Optional: TextAlertSystem integration
# ---------------------------------------------------------------------------

try:
    from bot.text_alert_system import get_text_alert_system as _get_text_alert_system
    _TEXT_ALERT_AVAILABLE = True
except ImportError:
    try:
        from text_alert_system import get_text_alert_system as _get_text_alert_system  # type: ignore
        _TEXT_ALERT_AVAILABLE = True
    except ImportError:
        _get_text_alert_system = None  # type: ignore
        _TEXT_ALERT_AVAILABLE = False

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_WEEKLY_SALARY_USD: float = 1_250.0
DEFAULT_DATA_DIR: Path = Path("data/weekly_salary")


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class SalaryConfig:
    """Configuration for the weekly salary mode."""

    #: Fixed salary to attempt to pay each week (USD).
    weekly_salary_usd: float = DEFAULT_WEEKLY_SALARY_USD

    #: Minimum weekly net profit required before a salary is paid.
    #: Set to 0.0 to pay whenever the pool has enough funds (any profitable week).
    min_weekly_profit_usd: float = 0.0

    #: Whether salary mode is enabled at all.
    enabled: bool = True

    #: Directory used for persistent state / audit log.
    data_dir: Optional[str] = None

    def validate(self) -> None:
        if self.weekly_salary_usd <= 0:
            raise ValueError(
                f"weekly_salary_usd must be > 0, got {self.weekly_salary_usd}"
            )
        if self.min_weekly_profit_usd < 0:
            raise ValueError(
                f"min_weekly_profit_usd must be >= 0, got {self.min_weekly_profit_usd}"
            )


@dataclass
class SalaryPayment:
    """Record of a single salary payment or skip event."""

    payment_id: str
    iso_week: str          # "YYYY-Www"  e.g. "2026-W12"
    timestamp: str
    weekly_profit_usd: float
    salary_paid_usd: float
    pool_before_usd: float
    pool_after_usd: float
    status: str            # "paid" | "skipped_unprofitable" | "skipped_insufficient_pool"
    note: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class WeeklySalaryState:
    """Persisted state for the weekly salary engine."""

    #: Accumulated (un-withdrawn) profits in the salary pool.
    pool_usd: float = 0.0

    #: Net profit recorded for the *current* ISO week.
    current_week_profit_usd: float = 0.0

    #: ISO week string of the last period where a payout was attempted.
    last_processed_week: str = ""

    #: Running total of all salary paid out.
    total_salary_paid_usd: float = 0.0

    #: Number of weeks where salary was paid.
    weeks_paid: int = 0

    #: Number of weeks where salary was skipped.
    weeks_skipped: int = 0

    #: Full audit log of payment / skip events.
    payment_log: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "WeeklySalaryState":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# ---------------------------------------------------------------------------
# WeeklySalaryMode
# ---------------------------------------------------------------------------


class WeeklySalaryMode:
    """
    Weekly fixed-salary engine for NIJA.

    Accumulates weekly realised profits and pays a configured salary
    only when the system is profitable.

    Thread-safe; obtain the process-wide singleton via
    ``get_weekly_salary_mode()``.
    """

    def __init__(
        self,
        config: Optional[SalaryConfig] = None,
        data_dir: Optional[Path] = None,
    ) -> None:
        self._lock = threading.RLock()
        self._config = config or SalaryConfig()
        self._config.validate()

        # Resolve data directory (config overrides explicit parameter overrides default)
        if self._config.data_dir:
            self._data_dir = Path(self._config.data_dir)
        elif data_dir is not None:
            self._data_dir = data_dir
        else:
            self._data_dir = DEFAULT_DATA_DIR

        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._state_file = self._data_dir / "salary_state.json"
        self._audit_file = self._data_dir / "salary_audit.jsonl"

        self._state = self._load_state()

        logger.info("=" * 70)
        logger.info("💵  Weekly Salary Mode initialised")
        logger.info("    Salary target : $%.2f / week", self._config.weekly_salary_usd)
        logger.info("    Min profit req: $%.2f", self._config.min_weekly_profit_usd)
        logger.info("    Enabled       : %s", self._config.enabled)
        logger.info("    Pool balance  : $%.2f", self._state.pool_usd)
        logger.info("    Total paid    : $%.2f (%d weeks)", self._state.total_salary_paid_usd, self._state.weeks_paid)
        logger.info("=" * 70)

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _load_state(self) -> WeeklySalaryState:
        if self._state_file.exists():
            try:
                with open(self._state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                state = WeeklySalaryState.from_dict(data)
                logger.debug("WeeklySalaryMode: state loaded from %s", self._state_file)
                return state
            except Exception as exc:
                logger.warning("WeeklySalaryMode: failed to load state (%s) — starting fresh", exc)
        return WeeklySalaryState()

    def _save_state(self) -> None:
        try:
            with open(self._state_file, "w", encoding="utf-8") as f:
                json.dump(self._state.to_dict(), f, indent=2)
        except Exception as exc:
            logger.error("WeeklySalaryMode: failed to save state: %s", exc)

    def _append_audit(self, record: SalaryPayment) -> None:
        try:
            with open(self._audit_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record.to_dict()) + "\n")
        except Exception as exc:
            logger.error("WeeklySalaryMode: failed to append audit record: %s", exc)

    # ------------------------------------------------------------------
    # ISO week helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _current_iso_week(now: Optional[datetime] = None) -> str:
        """Return the ISO week string for *now*, e.g. ``'2026-W12'``."""
        ts = now or datetime.now(timezone.utc)
        return f"{ts.isocalendar()[0]}-W{ts.isocalendar()[1]:02d}"

    @staticmethod
    def _week_has_ended(last_week: str, current_week: str) -> bool:
        """Return True if *current_week* is a newer ISO week than *last_week*."""
        if not last_week:
            return True
        return current_week != last_week

    # ------------------------------------------------------------------
    # Core public API
    # ------------------------------------------------------------------

    def record_profit(self, pnl_usd: float, symbol: str = "", note: str = "") -> float:
        """
        Record a realised profit (or loss) for the current week.

        Positive values grow the pool and weekly profit tally.
        Negative values reduce the weekly profit tally (but do **not**
        drain the pool below zero — losses only reduce the profit gate).

        Args:
            pnl_usd: Realised profit (+) or loss (−) in USD.
            symbol:  Optional trading pair label (informational).
            note:    Optional free-text annotation.

        Returns:
            Current pool balance after recording.
        """
        if not self._config.enabled:
            return 0.0

        with self._lock:
            # Roll over the week if needed before recording
            self._maybe_rollover_week()

            s = self._state
            s.current_week_profit_usd += pnl_usd

            # Only positive profits flow into the salary pool
            if pnl_usd > 0:
                s.pool_usd += pnl_usd
                logger.debug(
                    "WeeklySalaryMode: +$%.2f profit recorded (%s) — pool=$%.2f, week=$%.2f",
                    pnl_usd, symbol or "?", s.pool_usd, s.current_week_profit_usd,
                )
            else:
                logger.debug(
                    "WeeklySalaryMode: $%.2f loss recorded (%s) — week_profit=$%.2f",
                    pnl_usd, symbol or "?", s.current_week_profit_usd,
                )

            self._save_state()
            return s.pool_usd

    def try_pay_salary(
        self,
        force: bool = False,
        now: Optional[datetime] = None,
    ) -> Optional[SalaryPayment]:
        """
        Attempt to pay the weekly salary.

        By default this is idempotent within the same ISO week — calling it
        multiple times in a single week results in at most one payment.
        Pass ``force=True`` to bypass the week-boundary check (useful for
        operator-triggered immediate payouts or testing).

        The actual payout is capped by the formula::

            payout = min(weekly_profit * 0.5, weekly_salary_usd)

        This ensures the operator never takes out more than half of what the
        system earned in the week, while the configured salary acts as an
        upper ceiling.

        Payment is **skipped** (and the skip is logged) when:
        * The weekly net profit is below ``min_weekly_profit_usd``.
        * The salary pool does not contain enough funds to cover the capped payout.

        Args:
            force: Pay immediately, ignoring week-boundary check.
            now:   Override the current time (useful for testing).

        Returns:
            A ``SalaryPayment`` record if an attempt was made (paid or
            skipped), or ``None`` if it is still mid-week and ``force``
            is ``False``.
        """
        if not self._config.enabled:
            logger.debug("WeeklySalaryMode: disabled — skipping try_pay_salary")
            return None

        with self._lock:
            current_week = self._current_iso_week(now)
            s = self._state

            # Mid-week guard (skip unless forced or week has rolled over)
            if not force and not self._week_has_ended(s.last_processed_week, current_week):
                logger.debug(
                    "WeeklySalaryMode: still in week %s — salary check deferred", current_week
                )
                return None

            # Roll over internal week counter when transitioning FROM a previously
            # processed week.  Guard against the first-ever call (empty
            # last_processed_week) so we don't erase profits recorded before
            # the first try_pay_salary() call.
            if s.last_processed_week and self._week_has_ended(s.last_processed_week, current_week):
                self._rollover_week(current_week)

            target_week = current_week if force else s.last_processed_week
            pool_before = s.pool_usd
            weekly_profit = s.current_week_profit_usd

            # ----- Gate 0: emergency capital protection -----
            if _ECP_AVAILABLE and get_emergency_capital_protection is not None:
                try:
                    ecp = get_emergency_capital_protection()
                    if ecp.is_active():
                        ecp_level = ecp.current_level().value
                        payment = SalaryPayment(
                            payment_id=str(uuid.uuid4()),
                            iso_week=target_week,
                            timestamp=datetime.now(timezone.utc).isoformat(),
                            weekly_profit_usd=weekly_profit,
                            salary_paid_usd=0.0,
                            pool_before_usd=pool_before,
                            pool_after_usd=pool_before,
                            status="skipped_capital_protection",
                            note=f"Emergency capital protection active (level={ecp_level}) — salary withheld to preserve capital",
                        )
                        s.weeks_skipped += 1
                        s.last_processed_week = target_week
                        s.payment_log.append(payment.to_dict())
                        self._append_audit(payment)
                        self._save_state()
                        logger.warning(
                            "🛡️  WeeklySalaryMode: salary BLOCKED (week %s) — "
                            "EmergencyCapitalProtection level=%s",
                            target_week, ecp_level,
                        )
                        return payment
                except Exception as exc:
                    logger.warning("WeeklySalaryMode: ECP check failed (%s) — proceeding", exc)

            # ----- Gate 1: profitability -----
            if weekly_profit < self._config.min_weekly_profit_usd:
                status = "skipped_unprofitable"
                payment = SalaryPayment(
                    payment_id=str(uuid.uuid4()),
                    iso_week=target_week,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    weekly_profit_usd=weekly_profit,
                    salary_paid_usd=0.0,
                    pool_before_usd=pool_before,
                    pool_after_usd=pool_before,
                    status=status,
                    note=f"Week not profitable (${weekly_profit:.2f} < ${self._config.min_weekly_profit_usd:.2f} threshold)",
                )
                s.weeks_skipped += 1
                s.last_processed_week = target_week
                s.payment_log.append(payment.to_dict())
                self._append_audit(payment)
                self._save_state()
                logger.info(
                    "⏭️  WeeklySalaryMode: salary SKIPPED (week %s) — not profitable "
                    "(net=$%.2f, required=$%.2f)",
                    target_week, weekly_profit, self._config.min_weekly_profit_usd,
                )
                return payment

            # ----- Compute capped payout: min(weekly_profit * 0.5, salary_target) -----
            salary = min(weekly_profit * 0.5, self._config.weekly_salary_usd)

            # ----- Gate 2: sufficient pool (and non-zero payout) -----
            if salary <= 0 or pool_before < salary:
                status = "skipped_insufficient_pool"
                payment = SalaryPayment(
                    payment_id=str(uuid.uuid4()),
                    iso_week=target_week,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    weekly_profit_usd=weekly_profit,
                    salary_paid_usd=0.0,
                    pool_before_usd=pool_before,
                    pool_after_usd=pool_before,
                    status=status,
                    note=f"Insufficient pool (${pool_before:.2f} < ${salary:.2f} capped payout)",
                )
                s.weeks_skipped += 1
                s.last_processed_week = target_week
                s.payment_log.append(payment.to_dict())
                self._append_audit(payment)
                self._save_state()
                logger.info(
                    "⏭️  WeeklySalaryMode: salary SKIPPED (week %s) — pool too low "
                    "(pool=$%.2f, capped payout=$%.2f)",
                    target_week, pool_before, salary,
                )
                return payment

            # ----- Both gates pass → pay salary -----
            s.pool_usd -= salary
            s.total_salary_paid_usd += salary
            s.weeks_paid += 1
            s.last_processed_week = target_week

            payment = SalaryPayment(
                payment_id=str(uuid.uuid4()),
                iso_week=target_week,
                timestamp=datetime.now(timezone.utc).isoformat(),
                weekly_profit_usd=weekly_profit,
                salary_paid_usd=salary,
                pool_before_usd=pool_before,
                pool_after_usd=s.pool_usd,
                status="paid",
                note=(
                    f"Payout = min(${weekly_profit:.2f}×0.5, ${self._config.weekly_salary_usd:.2f}) "
                    f"= ${salary:.2f} — pool surplus=${s.pool_usd:.2f}"
                ),
            )
            s.payment_log.append(payment.to_dict())
            self._append_audit(payment)
            self._save_state()

            logger.info(
                "✅  WeeklySalaryMode: salary PAID (week %s) — $%.2f  "
                "| Pool: $%.2f → $%.2f  | Week profit: $%.2f  "
                "| Formula: min(%.2f×0.5, %.2f)",
                target_week, salary, pool_before, s.pool_usd, weekly_profit,
                weekly_profit, self._config.weekly_salary_usd,
            )
            if _TEXT_ALERT_AVAILABLE:
                try:
                    _get_text_alert_system().salary_paid(
                        amount_usd=salary,
                        week=target_week,
                    )
                except Exception as _ta_exc:
                    logger.debug("TextAlertSystem: salary_paid notification failed: %s", _ta_exc)
            return payment

    def _maybe_rollover_week(self) -> None:
        """Roll over weekly counters if the calendar week has changed (no lock — caller holds it)."""
        current_week = self._current_iso_week()
        if not self._state.last_processed_week:
            # First-ever activity: stamp the current week so future transitions work.
            self._state.last_processed_week = current_week
            return
        if self._week_has_ended(self._state.last_processed_week, current_week):
            self._rollover_week(current_week)

    def _rollover_week(self, new_week: str) -> None:
        """Reset per-week counters when entering a new ISO week (no lock — caller holds it)."""
        logger.debug(
            "WeeklySalaryMode: rolling over from week '%s' to '%s'",
            self._state.last_processed_week, new_week,
        )
        self._state.current_week_profit_usd = 0.0

    # ------------------------------------------------------------------
    # Status / diagnostics
    # ------------------------------------------------------------------

    @property
    def pool_usd(self) -> float:
        """Current salary pool balance (USD)."""
        with self._lock:
            return self._state.pool_usd

    @property
    def weekly_profit_usd(self) -> float:
        """Net profit recorded so far for the current ISO week (USD)."""
        with self._lock:
            return self._state.current_week_profit_usd

    @property
    def total_salary_paid_usd(self) -> float:
        """Running total of salary paid across all weeks (USD)."""
        with self._lock:
            return self._state.total_salary_paid_usd

    @property
    def config(self) -> SalaryConfig:
        """Read-only reference to the active configuration."""
        return self._config

    def get_report(self) -> str:
        """Return a human-readable status dashboard."""
        with self._lock:
            s = self._state
            current_week = self._current_iso_week()
            weeks_total = s.weeks_paid + s.weeks_skipped
            pay_rate = (s.weeks_paid / weeks_total * 100) if weeks_total else 0.0

            # Project the payout the engine would issue right now
            projected_payout = min(
                s.current_week_profit_usd * 0.5,
                self._config.weekly_salary_usd,
            )
            profit_gate_ok = s.current_week_profit_usd >= self._config.min_weekly_profit_usd
            pool_covers = s.pool_usd >= projected_payout

            lines = [
                "=" * 70,
                "💵  WEEKLY SALARY MODE — STATUS REPORT",
                "=" * 70,
                f"  Status            : {'🟢 ENABLED' if self._config.enabled else '🔴 DISABLED'}",
                f"  Current Week      : {current_week}",
                f"  Weekly Target     : ${self._config.weekly_salary_usd:,.2f}",
                f"  Min Profit Gate   : ${self._config.min_weekly_profit_usd:,.2f}",
                "-" * 70,
                "  📊  CURRENT WEEK",
                f"  Week Net Profit   : ${s.current_week_profit_usd:,.2f}",
                f"  Profit Gate Pass  : {'✅ YES' if profit_gate_ok else '❌ NO'}",
                f"  Projected Payout  : ${projected_payout:,.2f}  "
                f"[min(${s.current_week_profit_usd:,.2f}×0.5, ${self._config.weekly_salary_usd:,.2f})]",
                "-" * 70,
                "  🏦  SALARY POOL",
                f"  Pool Balance      : ${s.pool_usd:,.2f}",
                f"  Pool Covers Payout: {'✅ YES' if pool_covers else '❌ NO'}",
                "-" * 70,
                "  📈  LIFETIME STATS",
                f"  Total Paid        : ${s.total_salary_paid_usd:,.2f}",
                f"  Weeks Paid        : {s.weeks_paid}",
                f"  Weeks Skipped     : {s.weeks_skipped}",
                f"  Pay Rate          : {pay_rate:.1f} %",
                "=" * 70,
            ]
            return "\n".join(lines)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_INSTANCE: Optional[WeeklySalaryMode] = None
_INSTANCE_LOCK = threading.Lock()


def get_weekly_salary_mode(
    config: Optional[SalaryConfig] = None,
    data_dir: Optional[Path] = None,
) -> WeeklySalaryMode:
    """
    Return the process-wide singleton ``WeeklySalaryMode``.

    Thread-safe; the instance is created on first call.  Subsequent calls
    ignore *config* and *data_dir* (use constructor directly for custom
    instances in tests).
    """
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = WeeklySalaryMode(config=config, data_dir=data_dir)
    return _INSTANCE
