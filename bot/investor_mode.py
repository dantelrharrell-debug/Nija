"""
NIJA Investor Mode
==================

Allows outside investors to plug capital into the NIJA trading engine.
Each investor is tracked individually with full per-user performance
attribution, and fees (management + performance) are collected
automatically.

Key Features
------------
* **Outside capital** — register any number of investors with their own
  contributed amounts.
* **Per-user performance tracking** — each investor has their own high-water
  mark (HWM), profit/loss history, and rate-of-return metrics.
* **Automatic fee collection** — two fee types:
    - *Management fee*  – annual percentage of AUM, accrued daily
      (default **2 % / year**).
    - *Performance fee* – percentage of **new** profits above the HWM,
      charged whenever a gain is recorded (default **20 %**).
* **Proportional profit allocation** — portfolio-level P&L is split among
  investors in proportion to their capital weight.

Architecture
------------
::

    engine = get_investor_mode_engine()

    # 1. Register an investor (once)
    engine.register_investor(
        investor_id="alice",
        name="Alice Smith",
        capital_usd=25_000.0,
    )

    # 2. After every trade close:
    engine.record_portfolio_profit(pnl_usd=500.0)

    # 3. Collect all accrued fees (call periodically):
    fee_records = engine.collect_all_fees()

    # 4. Reporting:
    print(engine.get_investor_report("alice"))
    print(engine.get_summary_report())

Persistence
-----------
All investor accounts and fee records are persisted in JSON files under
the ``data/investor_mode/`` directory so state survives bot restarts.

Thread Safety
-------------
All public methods are protected by per-investor locks; the registry is
protected by a global lock.

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import threading
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger("nija.investor_mode")

# ---------------------------------------------------------------------------
# Constants / defaults
# ---------------------------------------------------------------------------

DEFAULT_MANAGEMENT_FEE_PCT: float = 2.0    # % per year
DEFAULT_PERFORMANCE_FEE_PCT: float = 20.0  # % of gains above HWM
DEFAULT_DATA_DIR: Path = Path("data/investor_mode")
# Audit trail — every distribution is appended here for compliance review
DISTRIBUTION_AUDIT_LOG: Path = Path("data/investor_mode/distribution_audit.jsonl")
# Minimum allowed account value after allocation (prevents negative edge cases)
MIN_ACCOUNT_VALUE_USD: float = 0.0

# ---------------------------------------------------------------------------
# Data-classes
# ---------------------------------------------------------------------------


@dataclass
class InvestorConfig:
    """Per-investor fee and term configuration.

    Attributes
    ----------
    management_fee_pct:
        Annual management fee as a percentage of AUM (e.g. 2.0 = 2 %/year).
        Accrued continuously and deducted when :meth:`collect_management_fees`
        is called.
    performance_fee_pct:
        Percentage of new profits above the investor's high-water mark that
        is taken as a performance fee (e.g. 20.0 = 20 %).
    """

    management_fee_pct: float = DEFAULT_MANAGEMENT_FEE_PCT
    performance_fee_pct: float = DEFAULT_PERFORMANCE_FEE_PCT


@dataclass
class FeeRecord:
    """A single fee collection event.

    Attributes
    ----------
    record_id:
        Unique identifier for the fee record.
    investor_id:
        Identifier of the investor being charged.
    fee_type:
        ``"management"`` or ``"performance"``.
    amount_usd:
        Fee amount in USD.
    timestamp:
        ISO-8601 timestamp of when the fee was collected.
    note:
        Optional human-readable description.
    """

    record_id: str
    investor_id: str
    fee_type: str          # "management" | "performance"
    amount_usd: float
    timestamp: str
    note: str = ""


@dataclass
class InvestorAccount:
    """Tracks the state of a single investor.

    Attributes
    ----------
    investor_id:
        Unique identifier (caller-supplied, e.g. an email or UUID).
    name:
        Human-readable display name.
    capital_contributed_usd:
        Sum of all capital added by the investor (never decreases on
        withdrawals — use ``current_value_usd`` for net position).
    current_value_usd:
        Current account value after allocating profits and deducting fees.
    high_water_mark_usd:
        Highest ``current_value_usd`` ever reached — used for performance
        fee calculation so fees are never charged on the same gains twice.
    total_profit_usd:
        Cumulative profits allocated to this investor.
    total_fees_paid_usd:
        Cumulative fees collected from this investor (management + perf).
    management_fee_pct:
        Annual management fee percentage.
    performance_fee_pct:
        Performance fee percentage above HWM.
    accrued_management_fee_usd:
        Management fee accrued but not yet collected.
    last_management_fee_date:
        ISO date (``YYYY-MM-DD``) of the last management-fee accrual.
    entry_date:
        ISO-8601 timestamp when this investor was registered.
    fee_records:
        List of :class:`FeeRecord` dicts (serialised for JSON persistence).
    profit_history:
        List of ``{timestamp, pnl_usd, note}`` dicts recording each profit
        allocation event.
    """

    investor_id: str
    name: str
    capital_contributed_usd: float
    current_value_usd: float
    high_water_mark_usd: float
    total_profit_usd: float = 0.0
    total_fees_paid_usd: float = 0.0
    management_fee_pct: float = DEFAULT_MANAGEMENT_FEE_PCT
    performance_fee_pct: float = DEFAULT_PERFORMANCE_FEE_PCT
    accrued_management_fee_usd: float = 0.0
    last_management_fee_date: str = ""
    entry_date: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    fee_records: List[Dict] = field(default_factory=list)
    profit_history: List[Dict] = field(default_factory=list)


# ---------------------------------------------------------------------------
# InvestorModeEngine
# ---------------------------------------------------------------------------


class InvestorModeEngine:
    """Core engine for NIJA Investor Mode.

    Manages a registry of investor accounts, proportionally distributes
    portfolio-level profits, and automatically calculates and collects
    management + performance fees.

    Obtain the singleton via :func:`get_investor_mode_engine`.
    """

    def __init__(self, data_dir: Optional[Path] = None) -> None:
        self._data_dir: Path = Path(data_dir) if data_dir else DEFAULT_DATA_DIR
        self._data_dir.mkdir(parents=True, exist_ok=True)

        # Audit log for every profit distribution event
        self._audit_log: Path = self._data_dir / "distribution_audit.jsonl"

        # Registry: investor_id → InvestorAccount
        self._accounts: Dict[str, InvestorAccount] = {}

        # Per-investor thread locks
        self._investor_locks: Dict[str, threading.Lock] = {}
        self._registry_lock = threading.Lock()

        # Load persisted state
        self._load_all()

        logger.info(
            "💼 InvestorModeEngine initialised — %d investor(s) loaded from %s",
            len(self._accounts),
            self._data_dir,
        )

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _account_file(self, investor_id: str) -> Path:
        """Return the JSON file path for a given investor."""
        safe = investor_id.replace("/", "_").replace("\\", "_")
        return self._data_dir / f"investor_{safe}.json"

    def _load_all(self) -> None:
        """Load all persisted investor accounts from disk."""
        for path in self._data_dir.glob("investor_*.json"):
            try:
                with path.open() as fh:
                    data = json.load(fh)
                account = InvestorAccount(**data)
                self._accounts[account.investor_id] = account
                self._investor_locks[account.investor_id] = threading.Lock()
            except Exception as exc:
                logger.warning("Could not load investor file %s: %s", path, exc)

    def _save_account(self, account: InvestorAccount) -> None:
        """Persist an investor account to disk atomically."""
        path = self._account_file(account.investor_id)
        tmp = path.with_suffix(".tmp")
        try:
            with tmp.open("w") as fh:
                json.dump(asdict(account), fh, indent=2)
            tmp.replace(path)
        except OSError as exc:
            logger.error("Could not save investor %s: %s", account.investor_id, exc)

    def _get_lock(self, investor_id: str) -> threading.Lock:
        with self._registry_lock:
            if investor_id not in self._investor_locks:
                self._investor_locks[investor_id] = threading.Lock()
            return self._investor_locks[investor_id]

    # ------------------------------------------------------------------
    # Public API — Investor lifecycle
    # ------------------------------------------------------------------

    def register_investor(
        self,
        investor_id: str,
        name: str,
        capital_usd: float,
        management_fee_pct: float = DEFAULT_MANAGEMENT_FEE_PCT,
        performance_fee_pct: float = DEFAULT_PERFORMANCE_FEE_PCT,
    ) -> InvestorAccount:
        """Register a new investor and credit their initial capital.

        If an investor with ``investor_id`` already exists, a
        ``ValueError`` is raised to prevent accidental overwrites.

        Args:
            investor_id:          Unique identifier for this investor.
            name:                 Human-readable display name.
            capital_usd:          Initial capital contribution in USD.
            management_fee_pct:   Annual management fee (default 2 %).
            performance_fee_pct:  Performance fee above HWM (default 20 %).

        Returns:
            The newly created :class:`InvestorAccount`.
        """
        with self._registry_lock:
            if investor_id in self._accounts:
                raise ValueError(
                    f"Investor '{investor_id}' already registered. "
                    "Use update_investor_capital() to add funds."
                )

            if capital_usd <= 0:
                raise ValueError("capital_usd must be greater than 0.")

            now_iso = datetime.now(timezone.utc).isoformat()
            account = InvestorAccount(
                investor_id=investor_id,
                name=name,
                capital_contributed_usd=capital_usd,
                current_value_usd=capital_usd,
                high_water_mark_usd=capital_usd,
                management_fee_pct=management_fee_pct,
                performance_fee_pct=performance_fee_pct,
                last_management_fee_date=date.today().isoformat(),
                entry_date=now_iso,
            )
            self._accounts[investor_id] = account
            self._investor_locks[investor_id] = threading.Lock()
            self._save_account(account)

        logger.info(
            "✅ Investor registered: %s (%s) — capital=$%.2f, mgmt=%.1f%%, perf=%.1f%%",
            investor_id, name, capital_usd, management_fee_pct, performance_fee_pct,
        )
        return account

    def update_investor_capital(
        self,
        investor_id: str,
        delta_usd: float,
        note: str = "",
    ) -> float:
        """Add or withdraw capital for an existing investor.

        Positive ``delta_usd`` adds capital; negative withdraws.  The
        high-water mark is raised when capital is added.

        Args:
            investor_id:  Investor to update.
            delta_usd:    Amount to add (positive) or withdraw (negative).
            note:         Optional note recorded in profit history.

        Returns:
            Updated ``current_value_usd`` after the adjustment.

        Raises:
            KeyError: If the investor is not registered.
            ValueError: If a withdrawal would reduce the account below $0.
        """
        lock = self._get_lock(investor_id)
        with lock:
            account = self._accounts.get(investor_id)
            if account is None:
                raise KeyError(f"Investor '{investor_id}' not found.")

            new_value = account.current_value_usd + delta_usd
            if new_value < 0:
                raise ValueError(
                    f"Withdrawal of ${abs(delta_usd):.2f} would reduce "
                    f"investor '{investor_id}' balance below $0."
                )

            if delta_usd > 0:
                account.capital_contributed_usd += delta_usd
                # Raise HWM when new capital arrives
                if new_value > account.high_water_mark_usd:
                    account.high_water_mark_usd = new_value

            account.current_value_usd = new_value
            account.profit_history.append({
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "pnl_usd": delta_usd,
                "note": note or ("capital deposit" if delta_usd >= 0 else "capital withdrawal"),
            })
            self._save_account(account)

        logger.info(
            "💰 Investor %s capital updated by $%.2f — new value=$%.2f",
            investor_id, delta_usd, new_value,
        )
        return new_value

    # ------------------------------------------------------------------
    # Profit distribution
    # ------------------------------------------------------------------

    def record_portfolio_profit(
        self,
        pnl_usd: float,
        symbol: str = "",
        note: str = "",
    ) -> Dict[str, float]:
        """Distribute a portfolio-level P&L event to all investors.

        Profit (or loss) is split proportionally based on each investor's
        ``current_value_usd`` relative to the total AUM.  After distributing
        profits, performance fees above each investor's high-water mark are
        automatically calculated and collected.

        Args:
            pnl_usd:  Realised profit (positive) or loss (negative) in USD.
            symbol:   Trading symbol associated with this P&L (optional).
            note:     Optional note for the history record.

        Returns:
            Dict mapping ``investor_id → allocated_pnl_usd``.
        """
        with self._registry_lock:
            if not self._accounts:
                return {}
            # Snapshot account list to avoid holding the registry lock
            account_ids = list(self._accounts.keys())
            total_aum = sum(
                self._accounts[i].current_value_usd for i in account_ids
            )

        if total_aum <= 0:
            return {}

        allocations: Dict[str, float] = {}
        audit_records: List[Dict] = []
        ts = datetime.now(timezone.utc).isoformat()

        for investor_id in account_ids:
            lock = self._get_lock(investor_id)
            with lock:
                account = self._accounts.get(investor_id)
                if account is None:
                    continue

                weight = account.current_value_usd / total_aum
                # Round to 2 d.p. to prevent cumulative floating-point drift
                allocated = round(pnl_usd * weight, 2)
                allocations[investor_id] = allocated

                new_value = account.current_value_usd + allocated
                # Guard against negative allocation edge cases
                if new_value < MIN_ACCOUNT_VALUE_USD:
                    logger.warning(
                        "💼 Investor %s: allocation would make value negative "
                        "(%.2f + %.2f = %.2f); clamping to 0",
                        investor_id,
                        account.current_value_usd,
                        allocated,
                        new_value,
                    )
                    allocated = -account.current_value_usd  # wipe to zero
                    new_value = MIN_ACCOUNT_VALUE_USD

                account.current_value_usd = new_value
                account.total_profit_usd = round(account.total_profit_usd + allocated, 2)
                profit_record = {
                    "timestamp": ts,
                    "pnl_usd": allocated,
                    "symbol": symbol,
                    "note": note or (f"portfolio profit: {symbol}" if symbol else "portfolio profit"),
                }
                account.profit_history.append(profit_record)

                # Build audit entry (before fee deduction so gross amounts are recorded)
                audit_records.append({
                    "timestamp": ts,
                    "investor_id": investor_id,
                    "total_pnl_usd": pnl_usd,
                    "allocated_usd": allocated,
                    "weight": round(weight, 6),
                    "value_before": round(account.current_value_usd - allocated, 2),
                    "value_after": round(account.current_value_usd, 2),
                    "symbol": symbol,
                    "note": profit_record["note"],
                })

                # Immediately collect performance fees on new profits
                if allocated > 0:
                    self._collect_performance_fee_locked(account)

                self._save_account(account)

        logger.info(
            "📊 portfolio P&L $%.2f distributed to %d investor(s)",
            pnl_usd, len(allocations),
        )

        # Append every distribution to the JSONL audit trail
        self._append_distribution_audit(audit_records)

        return allocations

    def _append_distribution_audit(self, records: List[Dict]) -> None:
        """Append distribution records to the JSONL audit trail."""
        if not records:
            return
        try:
            with self._audit_log.open("a") as fh:
                for rec in records:
                    fh.write(json.dumps(rec) + "\n")
        except OSError as exc:
            logger.error("Could not write distribution audit log: %s", exc)

    # ------------------------------------------------------------------
    # Fee calculation and collection
    # ------------------------------------------------------------------

    def _collect_performance_fee_locked(self, account: InvestorAccount) -> Optional[FeeRecord]:
        """Collect performance fee if account is above HWM (caller holds lock)."""
        if account.current_value_usd <= account.high_water_mark_usd:
            return None

        gain_above_hwm = account.current_value_usd - account.high_water_mark_usd
        fee_amount = gain_above_hwm * (account.performance_fee_pct / 100.0)

        if fee_amount < 0.01:
            return None

        # Deduct fee from account and update HWM
        account.current_value_usd -= fee_amount
        account.high_water_mark_usd = account.current_value_usd
        account.total_fees_paid_usd += fee_amount

        record = FeeRecord(
            record_id=str(uuid.uuid4()),
            investor_id=account.investor_id,
            fee_type="performance",
            amount_usd=fee_amount,
            timestamp=datetime.now(timezone.utc).isoformat(),
            note=(
                f"Performance fee {account.performance_fee_pct:.1f}% "
                f"on ${gain_above_hwm:.2f} gain above HWM"
            ),
        )
        account.fee_records.append(asdict(record))
        logger.info(
            "💸 Performance fee $%.2f collected from investor %s "
            "(%.1f%% of $%.2f above HWM)",
            fee_amount, account.investor_id,
            account.performance_fee_pct, gain_above_hwm,
        )
        return record

    def accrue_management_fees(self) -> Dict[str, float]:
        """Accrue daily management fees for all investors.

        Should be called once per day (or more frequently; it is idempotent
        within the same calendar day).

        Returns:
            Dict mapping ``investor_id → fee_accrued_usd``.
        """
        today = date.today().isoformat()
        accruals: Dict[str, float] = {}

        with self._registry_lock:
            account_ids = list(self._accounts.keys())

        for investor_id in account_ids:
            lock = self._get_lock(investor_id)
            with lock:
                account = self._accounts.get(investor_id)
                if account is None:
                    continue

                if account.last_management_fee_date == today:
                    continue  # Already accrued today

                # Days since last accrual (at least 1)
                try:
                    last_date = date.fromisoformat(account.last_management_fee_date)
                except (ValueError, TypeError):
                    last_date = date.today() - timedelta(days=1)

                days_elapsed = max(1, (date.today() - last_date).days)
                daily_rate = account.management_fee_pct / 100.0 / 365.0
                fee_amount = account.current_value_usd * daily_rate * days_elapsed

                account.accrued_management_fee_usd += fee_amount
                account.last_management_fee_date = today
                accruals[investor_id] = fee_amount
                self._save_account(account)

        if accruals:
            logger.debug(
                "📅 Management fees accrued for %d investor(s)", len(accruals)
            )
        return accruals

    def collect_management_fees(self) -> List[FeeRecord]:
        """Collect all accrued management fees from investor accounts.

        Deducts the accrued amount from each investor's ``current_value_usd``
        and resets the accrual counter.

        Returns:
            List of :class:`FeeRecord` objects for the collected fees.
        """
        # Accrue first to ensure we're up-to-date
        self.accrue_management_fees()

        collected: List[FeeRecord] = []

        with self._registry_lock:
            account_ids = list(self._accounts.keys())

        for investor_id in account_ids:
            lock = self._get_lock(investor_id)
            with lock:
                account = self._accounts.get(investor_id)
                if account is None or account.accrued_management_fee_usd < 0.01:
                    continue

                fee_amount = account.accrued_management_fee_usd
                account.current_value_usd = max(0.0, account.current_value_usd - fee_amount)
                account.total_fees_paid_usd += fee_amount
                account.accrued_management_fee_usd = 0.0

                record = FeeRecord(
                    record_id=str(uuid.uuid4()),
                    investor_id=investor_id,
                    fee_type="management",
                    amount_usd=fee_amount,
                    timestamp=datetime.now(timezone.utc).isoformat(),
                    note=(
                        f"Management fee {account.management_fee_pct:.1f}% p.a. "
                        f"on ${account.current_value_usd + fee_amount:.2f} AUM"
                    ),
                )
                account.fee_records.append(asdict(record))
                self._save_account(account)
                collected.append(record)
                logger.info(
                    "💸 Management fee $%.2f collected from investor %s",
                    fee_amount, investor_id,
                )

        return collected

    def collect_all_fees(self) -> List[FeeRecord]:
        """Collect both management and any pending performance fees.

        This is a convenience method that calls :meth:`collect_management_fees`
        (which also re-runs :meth:`accrue_management_fees`) and then checks
        every investor for outstanding performance fees.

        Returns:
            Combined list of all :class:`FeeRecord` objects collected.
        """
        all_records: List[FeeRecord] = self.collect_management_fees()

        with self._registry_lock:
            account_ids = list(self._accounts.keys())

        for investor_id in account_ids:
            lock = self._get_lock(investor_id)
            with lock:
                account = self._accounts.get(investor_id)
                if account is None:
                    continue
                record = self._collect_performance_fee_locked(account)
                if record is not None:
                    all_records.append(record)
                    self._save_account(account)

        return all_records

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_investor_report(self, investor_id: str) -> Dict:
        """Return a detailed performance report for a single investor.

        Args:
            investor_id: Identifier of the investor.

        Returns:
            Dictionary with full account metrics and history.

        Raises:
            KeyError: If the investor is not registered.
        """
        with self._registry_lock:
            account = self._accounts.get(investor_id)
        if account is None:
            raise KeyError(f"Investor '{investor_id}' not found.")

        roi_pct = 0.0
        if account.capital_contributed_usd > 0:
            roi_pct = (
                (account.current_value_usd - account.capital_contributed_usd)
                / account.capital_contributed_usd
            ) * 100.0

        net_value = account.current_value_usd - account.accrued_management_fee_usd

        return {
            "investor_id": account.investor_id,
            "name": account.name,
            "entry_date": account.entry_date,
            "capital_contributed_usd": round(account.capital_contributed_usd, 2),
            "current_value_usd": round(account.current_value_usd, 2),
            "net_value_usd": round(net_value, 2),
            "high_water_mark_usd": round(account.high_water_mark_usd, 2),
            "total_profit_usd": round(account.total_profit_usd, 2),
            "total_fees_paid_usd": round(account.total_fees_paid_usd, 2),
            "accrued_management_fee_usd": round(account.accrued_management_fee_usd, 4),
            "roi_pct": round(roi_pct, 2),
            "management_fee_pct": account.management_fee_pct,
            "performance_fee_pct": account.performance_fee_pct,
            "fee_records_count": len(account.fee_records),
            "profit_events": len(account.profit_history),
            "last_management_fee_date": account.last_management_fee_date,
        }

    def get_summary_report(self) -> Dict:
        """Return a summary of all investors and total AUM.

        Returns:
            Dictionary with aggregate metrics and per-investor summaries.
        """
        with self._registry_lock:
            account_ids = list(self._accounts.keys())

        if not account_ids:
            return {
                "investor_count": 0,
                "total_aum_usd": 0.0,
                "total_capital_contributed_usd": 0.0,
                "total_fees_collected_usd": 0.0,
                "total_profit_allocated_usd": 0.0,
                "investors": [],
            }

        investors = []
        total_aum = 0.0
        total_contributed = 0.0
        total_fees = 0.0
        total_profit = 0.0

        for investor_id in account_ids:
            with self._registry_lock:
                account = self._accounts.get(investor_id)
            if account is None:
                continue

            roi_pct = 0.0
            if account.capital_contributed_usd > 0:
                roi_pct = (
                    (account.current_value_usd - account.capital_contributed_usd)
                    / account.capital_contributed_usd
                ) * 100.0

            total_aum += account.current_value_usd
            total_contributed += account.capital_contributed_usd
            total_fees += account.total_fees_paid_usd
            total_profit += account.total_profit_usd

            investors.append({
                "investor_id": account.investor_id,
                "name": account.name,
                "current_value_usd": round(account.current_value_usd, 2),
                "capital_contributed_usd": round(account.capital_contributed_usd, 2),
                "total_profit_usd": round(account.total_profit_usd, 2),
                "total_fees_paid_usd": round(account.total_fees_paid_usd, 2),
                "roi_pct": round(roi_pct, 2),
                "aum_weight_pct": 0.0,  # filled below
            })

        # Fill AUM weight
        for inv in investors:
            inv["aum_weight_pct"] = round(
                (inv["current_value_usd"] / total_aum * 100.0) if total_aum > 0 else 0.0,
                2,
            )

        # Sort by AUM weight descending
        investors.sort(key=lambda x: x["aum_weight_pct"], reverse=True)

        return {
            "investor_count": len(investors),
            "total_aum_usd": round(total_aum, 2),
            "total_capital_contributed_usd": round(total_contributed, 2),
            "total_fees_collected_usd": round(total_fees, 2),
            "total_profit_allocated_usd": round(total_profit, 2),
            "investors": investors,
        }

    def get_report(self) -> str:
        """Return a formatted console-friendly status report."""
        summary = self.get_summary_report()

        lines = [
            "=" * 70,
            "💼  INVESTOR MODE — STATUS REPORT",
            "=" * 70,
            f"  Investors       : {summary['investor_count']}",
            f"  Total AUM       : ${summary['total_aum_usd']:>12,.2f}",
            f"  Total Contributed: ${summary['total_capital_contributed_usd']:>11,.2f}",
            f"  Total Fees      : ${summary['total_fees_collected_usd']:>12,.2f}",
            f"  Total Profit    : ${summary['total_profit_allocated_usd']:>12,.2f}",
            "-" * 70,
        ]

        if summary["investors"]:
            lines.append(
                f"  {'ID':<20} {'Name':<20} {'Value':>10} {'ROI':>8} {'Fees':>10}"
            )
            lines.append("  " + "-" * 66)
            for inv in summary["investors"]:
                roi_str = f"{inv['roi_pct']:+.2f}%"
                lines.append(
                    f"  {inv['investor_id']:<20} {inv['name']:<20} "
                    f"${inv['current_value_usd']:>9,.2f} {roi_str:>8} "
                    f"${inv['total_fees_paid_usd']:>9,.2f}"
                )
        else:
            lines.append("  No investors registered.")

        lines.append("=" * 70)
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Accessor helpers
    # ------------------------------------------------------------------

    def list_investor_ids(self) -> List[str]:
        """Return a list of all registered investor IDs."""
        with self._registry_lock:
            return list(self._accounts.keys())

    def total_aum(self) -> float:
        """Return the total assets-under-management in USD."""
        with self._registry_lock:
            return sum(a.current_value_usd for a in self._accounts.values())

    def is_enabled(self) -> bool:
        """Return ``True`` if at least one investor is registered."""
        with self._registry_lock:
            return len(self._accounts) > 0


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_ENGINE_INSTANCE: Optional[InvestorModeEngine] = None
_ENGINE_LOCK = threading.Lock()


def get_investor_mode_engine(data_dir: Optional[Path] = None) -> InvestorModeEngine:
    """Return the process-wide singleton :class:`InvestorModeEngine`.

    Thread-safe; the instance is created once on the first call.

    Args:
        data_dir:  Override the default persistence directory
                   (useful for tests).  Only respected on the **first**
                   call; subsequent calls return the existing singleton.
    """
    global _ENGINE_INSTANCE
    if _ENGINE_INSTANCE is None:
        with _ENGINE_LOCK:
            if _ENGINE_INSTANCE is None:
                _ENGINE_INSTANCE = InvestorModeEngine(data_dir=data_dir)
    return _ENGINE_INSTANCE


__all__ = [
    "InvestorConfig",
    "InvestorAccount",
    "FeeRecord",
    "InvestorModeEngine",
    "get_investor_mode_engine",
]
