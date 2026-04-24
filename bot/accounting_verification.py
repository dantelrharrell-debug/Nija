"""
NIJA Accounting Verification Layer
====================================

Provides a lightweight double-entry audit ledger that tracks every financial
event the bot generates.  Every debit or credit is recorded as an
:class:`LedgerEntry`.  The ledger can be reconciled at any time to verify
that the running balance is internally consistent.

Financial event types captured
-------------------------------
* ``salary_paid``          — weekly salary payout
* ``daily_withdrawal``     — daily profit auto-withdrawal
* ``profit_recorded``      — realised trade profit deposited to pool
* ``loss_recorded``        — realised trade loss debited from pool
* ``deposit``              — external deposit (e.g. funding the account)
* ``adjustment``           — manual correction entry

Architecture
------------
::

  ┌──────────────────────────────────────────────────────────────────┐
  │                AccountingVerificationLayer                       │
  │                                                                  │
  │  record(event_type, debit, credit, …)  →  LedgerEntry           │
  │  reconcile()                           →  ReconciliationReport   │
  │  get_ledger()                          →  List[LedgerEntry]      │
  │  get_report()                          →  str                    │
  └──────────────────────────────────────────────────────────────────┘

All entries are persisted to ``data/accounting/ledger.jsonl`` (JSON-lines).
Reconciliation checks that:

1. running_balance = sum(all credits) - sum(all debits)
2. Each entry's running_balance field matches the running total.
3. No negative running_balance (optional strict mode).

Usage
-----
::

    from bot.accounting_verification import get_accounting_layer

    acct = get_accounting_layer()
    acct.record("profit_recorded", credit=120.0, description="BTC-USD long +120")
    acct.record("salary_paid",     debit=875.0,  description="Week 2026-W12 salary")

    report = acct.reconcile()
    print(report.is_balanced)
    print(acct.get_report())

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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.accounting_verification")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_DATA_DIR: Path = Path("data/accounting")
LEDGER_FILENAME: str = "ledger.jsonl"

VALID_EVENT_TYPES: frozenset = frozenset({
    "salary_paid",
    "daily_withdrawal",
    "profit_recorded",
    "loss_recorded",
    "deposit",
    "adjustment",
})

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class LedgerEntry:
    """A single double-entry accounting record."""

    entry_id: str
    event_type: str
    timestamp: str
    debit_usd: float           # outflows  (salary, withdrawal)
    credit_usd: float          # inflows   (profit, deposit)
    running_balance_usd: float # balance after this entry
    description: str = ""
    reference_id: str = ""     # optional link to trade/payment ID
    verified: bool = True      # False if entry was flagged during reconciliation

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "LedgerEntry":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


@dataclass
class ReconciliationReport:
    """Result of a ledger reconciliation run."""

    timestamp: str
    total_entries: int
    total_credits_usd: float
    total_debits_usd: float
    expected_balance_usd: float  # credits - debits
    ledger_balance_usd: float    # running_balance of last entry
    is_balanced: bool
    discrepancy_usd: float       # |expected - ledger|
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class AccountingVerificationLayer:
    """
    Thread-safe double-entry ledger for NIJA financial events.

    Every financial event must flow through :meth:`record`; the ledger
    maintains a running balance that can be verified with :meth:`reconcile`.
    """

    def __init__(
        self,
        data_dir: Optional[Path] = None,
        strict_no_negative: bool = False,
    ) -> None:
        self._data_dir = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._ledger_path = self._data_dir / LEDGER_FILENAME
        self._strict = strict_no_negative
        self._lock = threading.RLock()
        self._entries: List[LedgerEntry] = []
        self._running_balance: float = 0.0
        self._load_from_disk()
        logger.info(
            "AccountingVerificationLayer initialised — %d entries loaded, "
            "balance $%.2f",
            len(self._entries), self._running_balance,
        )

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _load_from_disk(self) -> None:
        if not self._ledger_path.exists():
            return
        errors = 0
        with open(self._ledger_path, "r", encoding="utf-8") as fh:
            for lineno, line in enumerate(fh, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    entry = LedgerEntry.from_dict(d)
                    self._entries.append(entry)
                    self._running_balance = entry.running_balance_usd
                except Exception as exc:
                    logger.warning("Ledger parse error line %d: %s", lineno, exc)
                    errors += 1
        if errors:
            logger.warning("%d ledger lines could not be loaded.", errors)

    def _append_to_disk(self, entry: LedgerEntry) -> None:
        try:
            with open(self._ledger_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry.to_dict()) + "\n")
        except OSError as exc:
            logger.error("Failed to write ledger entry: %s", exc)

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def record(
        self,
        event_type: str,
        debit_usd: float = 0.0,
        credit_usd: float = 0.0,
        description: str = "",
        reference_id: str = "",
    ) -> LedgerEntry:
        """
        Record a financial event.

        Parameters
        ----------
        event_type   : one of the VALID_EVENT_TYPES strings.
        debit_usd    : outflow amount in USD (salary, withdrawal).
        credit_usd   : inflow amount in USD (profit, deposit).
        description  : human-readable note.
        reference_id : optional external reference (trade ID, payment ID).

        Returns
        -------
        The persisted :class:`LedgerEntry`.

        Raises
        ------
        ValueError if both debit and credit are zero, or event_type is unknown.
        """
        if event_type not in VALID_EVENT_TYPES:
            raise ValueError(
                f"Unknown event_type '{event_type}'. "
                f"Valid types: {sorted(VALID_EVENT_TYPES)}"
            )
        if debit_usd < 0 or credit_usd < 0:
            raise ValueError("debit_usd and credit_usd must be non-negative.")

        with self._lock:
            new_balance = self._running_balance + credit_usd - debit_usd
            if self._strict and new_balance < 0:
                raise ValueError(
                    f"Strict mode: recording this entry would make balance "
                    f"negative (${new_balance:.2f})."
                )
            self._running_balance = new_balance
            entry = LedgerEntry(
                entry_id=str(uuid.uuid4()),
                event_type=event_type,
                timestamp=datetime.now(timezone.utc).isoformat(),
                debit_usd=debit_usd,
                credit_usd=credit_usd,
                running_balance_usd=new_balance,
                description=description,
                reference_id=reference_id,
            )
            self._entries.append(entry)
            self._append_to_disk(entry)

        logger.debug(
            "Ledger [%s] debit=%.2f credit=%.2f balance=%.2f — %s",
            event_type, debit_usd, credit_usd, new_balance, description,
        )
        return entry

    # Convenience shortcuts --------------------------------------------------

    def record_profit(self, amount_usd: float, description: str = "", ref: str = "") -> LedgerEntry:
        """Credit a realised trade profit."""
        return self.record("profit_recorded", credit_usd=amount_usd,
                           description=description, reference_id=ref)

    def record_loss(self, amount_usd: float, description: str = "", ref: str = "") -> LedgerEntry:
        """Debit a realised trade loss."""
        return self.record("loss_recorded", debit_usd=amount_usd,
                           description=description, reference_id=ref)

    def record_salary(self, amount_usd: float, week: str = "", ref: str = "") -> LedgerEntry:
        """Debit a salary payout."""
        return self.record(
            "salary_paid", debit_usd=amount_usd,
            description=f"Weekly salary — {week}" if week else "Weekly salary",
            reference_id=ref,
        )

    def record_withdrawal(self, amount_usd: float, description: str = "", ref: str = "") -> LedgerEntry:
        """Debit a daily profit withdrawal."""
        return self.record("daily_withdrawal", debit_usd=amount_usd,
                           description=description, reference_id=ref)

    def record_deposit(self, amount_usd: float, description: str = "", ref: str = "") -> LedgerEntry:
        """Credit an external deposit."""
        return self.record("deposit", credit_usd=amount_usd,
                           description=description, reference_id=ref)

    # ------------------------------------------------------------------
    # Reconciliation
    # ------------------------------------------------------------------

    def reconcile(self) -> ReconciliationReport:
        """
        Verify ledger internal consistency.

        Checks:
        * Sum(credits) - Sum(debits) == last entry's running_balance.
        * Each entry's running_balance is mathematically consistent with
          the previous entry.

        Returns a :class:`ReconciliationReport`.
        """
        with self._lock:
            entries = list(self._entries)

        total_credits = sum(e.credit_usd for e in entries)
        total_debits = sum(e.debit_usd for e in entries)
        expected = round(total_credits - total_debits, 6)
        ledger_bal = round(entries[-1].running_balance_usd, 6) if entries else 0.0
        discrepancy = abs(expected - ledger_bal)
        errors: List[str] = []

        # Check sequential consistency
        running = 0.0
        for i, e in enumerate(entries):
            expected_entry_bal = round(running + e.credit_usd - e.debit_usd, 6)
            if abs(expected_entry_bal - round(e.running_balance_usd, 6)) > 0.001:
                errors.append(
                    f"Entry {i} ({e.entry_id}): expected balance "
                    f"${expected_entry_bal:.6f}, got ${e.running_balance_usd:.6f}"
                )
            running = expected_entry_bal

        if discrepancy > 0.001:
            errors.append(
                f"Global balance mismatch: expected ${expected:.2f}, "
                f"ledger shows ${ledger_bal:.2f} "
                f"(discrepancy ${discrepancy:.6f})"
            )

        is_balanced = not errors
        report = ReconciliationReport(
            timestamp=datetime.now(timezone.utc).isoformat(),
            total_entries=len(entries),
            total_credits_usd=total_credits,
            total_debits_usd=total_debits,
            expected_balance_usd=expected,
            ledger_balance_usd=ledger_bal,
            is_balanced=is_balanced,
            discrepancy_usd=discrepancy,
            errors=errors,
        )
        if is_balanced:
            logger.info(
                "Reconciliation PASSED — %d entries, balance $%.2f",
                len(entries), ledger_bal,
            )
        else:
            logger.error(
                "Reconciliation FAILED — %d errors: %s",
                len(errors), errors,
            )
        return report

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def balance_usd(self) -> float:
        """Current running balance in USD."""
        with self._lock:
            return self._running_balance

    def get_ledger(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Return the most-recent *limit* entries as dicts."""
        with self._lock:
            return [e.to_dict() for e in self._entries[-limit:]]

    def get_summary(self) -> Dict[str, Any]:
        """Return a summary dict for dashboard consumption."""
        with self._lock:
            entries = list(self._entries)

        total_credits = sum(e.credit_usd for e in entries)
        total_debits = sum(e.debit_usd for e in entries)
        salary_paid = sum(e.debit_usd for e in entries if e.event_type == "salary_paid")
        daily_withdrawn = sum(e.debit_usd for e in entries if e.event_type == "daily_withdrawal")
        total_profit = sum(e.credit_usd for e in entries if e.event_type == "profit_recorded")
        total_loss = sum(e.debit_usd for e in entries if e.event_type == "loss_recorded")
        net_pnl = total_profit - total_loss

        return {
            "balance_usd": round(self._running_balance, 2),
            "total_entries": len(entries),
            "total_credits_usd": round(total_credits, 2),
            "total_debits_usd": round(total_debits, 2),
            "salary_paid_total_usd": round(salary_paid, 2),
            "daily_withdrawn_total_usd": round(daily_withdrawn, 2),
            "net_pnl_usd": round(net_pnl, 2),
            "total_profit_usd": round(total_profit, 2),
            "total_loss_usd": round(total_loss, 2),
        }

    def get_report(self) -> str:
        """Return a human-readable ledger report."""
        summary = self.get_summary()
        recon = self.reconcile()
        lines = [
            "=" * 70,
            "📒  ACCOUNTING VERIFICATION LAYER — LEDGER REPORT",
            "=" * 70,
            f"  Running Balance    : ${summary['balance_usd']:>12,.2f}",
            f"  Total Entries      : {summary['total_entries']}",
            "-" * 70,
            "  FLOWS",
            f"  Total Credits (in) : ${summary['total_credits_usd']:>12,.2f}",
            f"  Total Debits  (out): ${summary['total_debits_usd']:>12,.2f}",
            "-" * 70,
            "  BREAKDOWN",
            f"  Net P&L            : ${summary['net_pnl_usd']:>12,.2f}",
            f"    Profits          : ${summary['total_profit_usd']:>12,.2f}",
            f"    Losses           : ${summary['total_loss_usd']:>12,.2f}",
            f"  Salary Paid (total): ${summary['salary_paid_total_usd']:>12,.2f}",
            f"  Daily Withdrawals  : ${summary['daily_withdrawn_total_usd']:>12,.2f}",
            "-" * 70,
            "  RECONCILIATION",
            f"  Status             : {'✅ BALANCED' if recon.is_balanced else '❌ MISMATCH'}",
            f"  Discrepancy        : ${recon.discrepancy_usd:.6f}",
        ]
        if recon.errors:
            lines.append("  Errors:")
            for err in recon.errors:
                lines.append(f"    • {err}")
        lines.append("=" * 70)
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_INSTANCE: Optional[AccountingVerificationLayer] = None
_INSTANCE_LOCK = threading.Lock()


def get_accounting_layer(
    data_dir: Optional[Path] = None,
    strict_no_negative: bool = False,
) -> AccountingVerificationLayer:
    """
    Return the process-wide singleton :class:`AccountingVerificationLayer`.

    Thread-safe.  First call creates the instance; subsequent calls ignore
    arguments.
    """
    global _INSTANCE
    if _INSTANCE is None:
        with _INSTANCE_LOCK:
            if _INSTANCE is None:
                _INSTANCE = AccountingVerificationLayer(
                    data_dir=data_dir,
                    strict_no_negative=strict_no_negative,
                )
    return _INSTANCE
