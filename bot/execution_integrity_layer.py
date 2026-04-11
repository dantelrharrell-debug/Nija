"""
NIJA Execution Integrity Layer
================================

Enforces fill integrity across every order and every trading cycle:

1. **Partial-fill detection** — compares actual fill vs intended size and
   classifies the result as FULL, PARTIAL, or UNDERFILL.
2. **Per-cycle fill reconciliation** — every order placed within a cycle is
   registered in the ``CycleLedger``; at cycle end ``reconcile_cycle()``
   produces a structured report.
3. **Silent-underfill prevention** — ``is_acceptable_fill()`` returns
   ``False`` when the fill ratio falls below the configured minimum threshold,
   preventing downstream code from treating underfills as success.

Typical usage
-------------
::

    from bot.execution_integrity_layer import get_execution_integrity_layer

    eil = get_execution_integrity_layer()

    # --- on each order placement ---
    verdict = eil.register_fill(
        cycle_id="cycle-42",
        order_id="abc123",
        symbol="BTC-USD",
        side="buy",
        intended_size_usd=500.0,
        actual_fill_usd=480.0,
    )
    if not verdict.is_acceptable:
        logger.error("Fill integrity failure: %s", verdict.reason)

    # --- at end of cycle ---
    report = eil.reconcile_cycle("cycle-42")
    if report.has_integrity_failures:
        logger.warning("Cycle %s: %d integrity failure(s)", report.cycle_id,
                       report.underfill_count)

Author: NIJA Trading Systems
Version: 1.0
"""

from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, List, Optional

logger = logging.getLogger("nija.execution.integrity")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Minimum fill ratio (actual / intended) to be considered acceptable.
# Example: 0.95 → at least 95 % of the intended size must be filled.
DEFAULT_MIN_FILL_RATIO: float = 0.95

# Below this ratio the fill is classified as a hard underfill and treated as
# a failure even when partial capital was deployed.
DEFAULT_UNDERFILL_RATIO: float = 0.50

# Maximum number of per-cycle fill records kept in memory.
_MAX_CYCLE_RECORDS: int = 500

# How many closed-cycle reports to retain for inspection.
_MAX_CLOSED_CYCLES: int = 100


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class FillIntegrityStatus(Enum):
    """Classification of a single fill event."""
    FULL = "FULL"               # ≥ min_fill_ratio — treated as success
    PARTIAL = "PARTIAL"         # < min_fill_ratio but ≥ underfill_ratio
    UNDERFILL = "UNDERFILL"     # < underfill_ratio — hard integrity failure
    ZERO_FILL = "ZERO_FILL"     # No units filled at all
    UNKNOWN = "UNKNOWN"         # Insufficient data to classify


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class FillRecord:
    """Immutable record of a single order's fill event."""

    cycle_id: str
    order_id: str
    symbol: str
    side: str                           # "buy" / "sell"
    intended_size_usd: float
    actual_fill_usd: float
    fill_ratio: float = 0.0             # actual / intended (computed on creation)
    status: FillIntegrityStatus = FillIntegrityStatus.UNKNOWN
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    broker: str = ""
    notes: str = ""

    def __post_init__(self) -> None:
        if self.intended_size_usd > 0:
            self.fill_ratio = self.actual_fill_usd / self.intended_size_usd
        else:
            # No intended size — fill ratio is undefined; use 0.0 to avoid
            # masking unintended fills with a spurious 100% value.
            self.fill_ratio = 0.0

    def to_dict(self) -> dict:
        return {
            "cycle_id": self.cycle_id,
            "order_id": self.order_id,
            "symbol": self.symbol,
            "side": self.side,
            "intended_size_usd": self.intended_size_usd,
            "actual_fill_usd": self.actual_fill_usd,
            "fill_ratio": round(self.fill_ratio, 6),
            "fill_pct": round(self.fill_ratio * 100, 2),
            "status": self.status.value,
            "timestamp": self.timestamp,
            "broker": self.broker,
            "notes": self.notes,
        }


@dataclass
class IntegrityVerdict:
    """
    Result of a single ``register_fill()`` call.

    ``is_acceptable`` is ``True`` only when the fill meets or exceeds the
    configured minimum fill ratio.  When ``False`` the caller **must not**
    treat the order as a successful execution.
    """

    order_id: str
    symbol: str
    status: FillIntegrityStatus
    fill_ratio: float
    intended_size_usd: float
    actual_fill_usd: float
    is_acceptable: bool
    reason: str = ""

    def to_dict(self) -> dict:
        return {
            "order_id": self.order_id,
            "symbol": self.symbol,
            "status": self.status.value,
            "fill_ratio": round(self.fill_ratio, 6),
            "fill_pct": round(self.fill_ratio * 100, 2),
            "intended_size_usd": self.intended_size_usd,
            "actual_fill_usd": self.actual_fill_usd,
            "is_acceptable": self.is_acceptable,
            "reason": self.reason,
        }


@dataclass
class CycleReconciliationReport:
    """
    Summary of fill integrity across all orders within one trading cycle.

    Attributes
    ----------
    cycle_id:
        Identifier of the reconciled cycle (e.g. ``"cycle-42"``).
    total_orders:
        Number of orders registered in the cycle.
    full_fills:
        Orders classified as FULL.
    partial_fills:
        Orders classified as PARTIAL.
    underfills:
        Orders classified as UNDERFILL or ZERO_FILL — hard failures.
    underfill_count:
        Convenience alias for ``underfills``.
    total_intended_usd:
        Sum of all intended order sizes (USD).
    total_filled_usd:
        Sum of all actual fills (USD).
    overall_fill_ratio:
        ``total_filled_usd / total_intended_usd``.
    has_integrity_failures:
        ``True`` when any underfill was detected.
    records:
        All individual :class:`FillRecord` objects for the cycle.
    closed_at:
        ISO timestamp when ``reconcile_cycle()`` was called.
    """

    cycle_id: str
    total_orders: int = 0
    full_fills: int = 0
    partial_fills: int = 0
    underfills: int = 0
    total_intended_usd: float = 0.0
    total_filled_usd: float = 0.0
    overall_fill_ratio: float = 0.0
    has_integrity_failures: bool = False
    records: List[FillRecord] = field(default_factory=list)
    closed_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def underfill_count(self) -> int:
        return self.underfills

    def to_dict(self) -> dict:
        return {
            "cycle_id": self.cycle_id,
            "total_orders": self.total_orders,
            "full_fills": self.full_fills,
            "partial_fills": self.partial_fills,
            "underfills": self.underfills,
            "total_intended_usd": round(self.total_intended_usd, 4),
            "total_filled_usd": round(self.total_filled_usd, 4),
            "overall_fill_ratio": round(self.overall_fill_ratio, 6),
            "overall_fill_pct": round(self.overall_fill_ratio * 100, 2),
            "has_integrity_failures": self.has_integrity_failures,
            "closed_at": self.closed_at,
        }


# ---------------------------------------------------------------------------
# CycleLedger
# ---------------------------------------------------------------------------


class CycleLedger:
    """
    Tracks every fill registered for a single trading cycle.

    Thread-safe.  Created automatically by :class:`ExecutionIntegrityLayer`
    on the first ``register_fill()`` call for a given ``cycle_id``.
    """

    def __init__(self, cycle_id: str) -> None:
        self.cycle_id = cycle_id
        self._records: List[FillRecord] = []
        self._lock = threading.Lock()

    def add(self, record: FillRecord) -> None:
        with self._lock:
            if len(self._records) < _MAX_CYCLE_RECORDS:
                self._records.append(record)

    def get_records(self) -> List[FillRecord]:
        with self._lock:
            return list(self._records)

    def order_count(self) -> int:
        with self._lock:
            return len(self._records)


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------


class ExecutionIntegrityLayer:
    """
    Central authority for fill integrity enforcement.

    All order fills must be registered here via :meth:`register_fill`.
    At cycle end call :meth:`reconcile_cycle` to get a full reconciliation
    report and to detect silent underfills.

    Configuration
    -------------
    min_fill_ratio:
        Minimum acceptable fill ratio (default 0.95 = 95 %).  Fills below
        this threshold are flagged as integrity failures.
    underfill_ratio:
        Hard underfill threshold (default 0.50 = 50 %).  Fills at or below
        this level are classified as ``UNDERFILL`` (hard failure).
    """

    def __init__(
        self,
        min_fill_ratio: float = DEFAULT_MIN_FILL_RATIO,
        underfill_ratio: float = DEFAULT_UNDERFILL_RATIO,
    ) -> None:
        if underfill_ratio >= min_fill_ratio:
            raise ValueError(
                f"underfill_ratio ({underfill_ratio}) must be < min_fill_ratio ({min_fill_ratio})"
            )
        self.min_fill_ratio = min_fill_ratio
        self.underfill_ratio = underfill_ratio

        self._open_ledgers: Dict[str, CycleLedger] = {}
        self._closed_reports: List[CycleReconciliationReport] = []
        self._lock = threading.Lock()

        # Session-level counters
        self._total_orders: int = 0
        self._total_underfills: int = 0
        self._total_partials: int = 0

        logger.info(
            "ExecutionIntegrityLayer initialized — "
            "min_fill=%.0f%%  underfill_threshold=%.0f%%",
            min_fill_ratio * 100,
            underfill_ratio * 100,
        )

    # ------------------------------------------------------------------
    # Public API — per-order
    # ------------------------------------------------------------------

    def register_fill(
        self,
        cycle_id: str,
        intended_size_usd: float,
        actual_fill_usd: float,
        order_id: Optional[str] = None,
        symbol: str = "",
        side: str = "",
        broker: str = "",
        notes: str = "",
    ) -> IntegrityVerdict:
        """
        Register an order fill and return an integrity verdict.

        Parameters
        ----------
        cycle_id:
            Identifier for the current trading cycle (e.g. ``"cycle-42"``).
            A new ledger is opened automatically if this is the first fill
            for that cycle.
        intended_size_usd:
            The original intended order size in USD.
        actual_fill_usd:
            The actual amount filled in USD as reported by the broker.
        order_id:
            Optional broker order ID.  Auto-generated if not provided.
        symbol:
            Trading pair (e.g. ``"BTC-USD"``).
        side:
            ``"buy"`` or ``"sell"``.
        broker:
            Broker name for audit purposes.
        notes:
            Optional free-text notes attached to the record.

        Returns
        -------
        IntegrityVerdict
            ``is_acceptable`` is ``False`` when the fill is below the
            configured minimum fill ratio — callers must **not** treat the
            order as a successful execution in this case.
        """
        if order_id is None:
            order_id = str(uuid.uuid4())

        status, is_acceptable, reason = self._classify(
            intended_size_usd, actual_fill_usd
        )

        fill_ratio = (
            actual_fill_usd / intended_size_usd if intended_size_usd > 0 else 0.0
        )

        record = FillRecord(
            cycle_id=cycle_id,
            order_id=order_id,
            symbol=symbol,
            side=side,
            intended_size_usd=intended_size_usd,
            actual_fill_usd=actual_fill_usd,
            status=status,
            broker=broker,
            notes=notes,
        )

        # Register in the cycle ledger
        ledger = self._get_or_create_ledger(cycle_id)
        ledger.add(record)

        # Update session counters
        with self._lock:
            self._total_orders += 1
            if status == FillIntegrityStatus.UNDERFILL or status == FillIntegrityStatus.ZERO_FILL:
                self._total_underfills += 1
            elif status == FillIntegrityStatus.PARTIAL:
                self._total_partials += 1

        verdict = IntegrityVerdict(
            order_id=order_id,
            symbol=symbol,
            status=status,
            fill_ratio=fill_ratio,
            intended_size_usd=intended_size_usd,
            actual_fill_usd=actual_fill_usd,
            is_acceptable=is_acceptable,
            reason=reason,
        )

        if not is_acceptable:
            logger.warning(
                "🔒 FILL INTEGRITY FAILURE [%s] %s %s — "
                "intended=$%.2f  filled=$%.2f  ratio=%.1f%%  status=%s  reason=%s",
                cycle_id, side.upper(), symbol,
                intended_size_usd, actual_fill_usd,
                fill_ratio * 100, status.value, reason,
            )
        elif status == FillIntegrityStatus.PARTIAL:
            logger.info(
                "⚠️  PARTIAL FILL [%s] %s %s — "
                "intended=$%.2f  filled=$%.2f  ratio=%.1f%%",
                cycle_id, side.upper(), symbol,
                intended_size_usd, actual_fill_usd, fill_ratio * 100,
            )
        else:
            logger.debug(
                "✅ FILL OK [%s] %s %s — ratio=%.1f%%",
                cycle_id, symbol, side, fill_ratio * 100,
            )

        return verdict

    def is_acceptable_fill(
        self,
        intended_size_usd: float,
        actual_fill_usd: float,
    ) -> bool:
        """
        Lightweight guard — returns ``True`` only if the fill meets the
        minimum fill ratio requirement.

        Use this as a fast gate at the call-site **before** treating an
        execution as successful.

        Parameters
        ----------
        intended_size_usd:
            The original intended order size in USD.
        actual_fill_usd:
            The actual amount filled in USD.
        """
        if intended_size_usd <= 0:
            return actual_fill_usd == 0
        return (actual_fill_usd / intended_size_usd) >= self.min_fill_ratio

    # ------------------------------------------------------------------
    # Public API — per-cycle
    # ------------------------------------------------------------------

    def reconcile_cycle(self, cycle_id: str) -> CycleReconciliationReport:
        """
        Reconcile all fills registered for the given cycle and return a
        full report.

        The cycle ledger is closed (moved to the closed-reports archive)
        after reconciliation so further fills cannot be added under the
        same ``cycle_id``.

        Parameters
        ----------
        cycle_id:
            The cycle identifier used when calling :meth:`register_fill`.

        Returns
        -------
        CycleReconciliationReport
            Summary of fill integrity for the cycle.  Check
            ``report.has_integrity_failures`` to determine whether any
            underfills were silently treated as success.
        """
        with self._lock:
            ledger = self._open_ledgers.pop(cycle_id, None)

        if ledger is None:
            logger.debug("reconcile_cycle: no open ledger for cycle_id=%s", cycle_id)
            report = CycleReconciliationReport(cycle_id=cycle_id)
            return report

        records = ledger.get_records()
        report = self._build_report(cycle_id, records)

        # Archive closed report
        with self._lock:
            self._closed_reports.append(report)
            if len(self._closed_reports) > _MAX_CLOSED_CYCLES:
                self._closed_reports.pop(0)

        if report.has_integrity_failures:
            logger.warning(
                "🔒 CYCLE RECONCILIATION FAILURE [%s] — "
                "%d order(s) | %d underfill(s) | %d partial(s) | "
                "intended=$%.2f  filled=$%.2f  overall=%.1f%%",
                cycle_id,
                report.total_orders,
                report.underfills,
                report.partial_fills,
                report.total_intended_usd,
                report.total_filled_usd,
                report.overall_fill_ratio * 100,
            )
        else:
            logger.info(
                "✅ CYCLE RECONCILIATION OK [%s] — "
                "%d order(s) | intended=$%.2f  filled=$%.2f  overall=%.1f%%",
                cycle_id,
                report.total_orders,
                report.total_intended_usd,
                report.total_filled_usd,
                report.overall_fill_ratio * 100,
            )

        return report

    def get_open_cycles(self) -> List[str]:
        """Return cycle IDs that have open (unreconciled) ledgers."""
        with self._lock:
            return list(self._open_ledgers.keys())

    def get_cycle_report(self, cycle_id: str) -> Optional[CycleReconciliationReport]:
        """
        Return a closed cycle reconciliation report by ``cycle_id``, or
        ``None`` if not found.
        """
        with self._lock:
            for report in reversed(self._closed_reports):
                if report.cycle_id == cycle_id:
                    return report
        return None

    def get_recent_reports(self, n: int = 10) -> List[CycleReconciliationReport]:
        """Return up to *n* most-recent closed reconciliation reports."""
        with self._lock:
            return list(self._closed_reports[-n:])

    def get_session_stats(self) -> dict:
        """Return session-level fill integrity counters."""
        with self._lock:
            return {
                "total_orders": self._total_orders,
                "total_underfills": self._total_underfills,
                "total_partials": self._total_partials,
                "open_cycles": len(self._open_ledgers),
                "closed_cycles": len(self._closed_reports),
                "underfill_rate_pct": (
                    round(self._total_underfills * 100.0 / self._total_orders, 2)
                    if self._total_orders > 0 else 0.0
                ),
                "min_fill_ratio": self.min_fill_ratio,
                "underfill_ratio": self.underfill_ratio,
            }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _classify(
        self,
        intended: float,
        actual: float,
    ) -> tuple[FillIntegrityStatus, bool, str]:
        """
        Classify fill completeness.

        Returns
        -------
        (status, is_acceptable, reason)
        """
        if intended <= 0:
            return FillIntegrityStatus.UNKNOWN, True, "zero intended size — skipped"

        if actual <= 0:
            return (
                FillIntegrityStatus.ZERO_FILL,
                False,
                f"zero fill on intended ${intended:.2f}",
            )

        ratio = actual / intended

        if ratio >= self.min_fill_ratio:
            return (
                FillIntegrityStatus.FULL,
                True,
                f"fill ratio {ratio:.1%} meets minimum {self.min_fill_ratio:.1%}",
            )

        if ratio > self.underfill_ratio:
            return (
                FillIntegrityStatus.PARTIAL,
                False,
                (
                    f"partial fill {ratio:.1%} — below minimum {self.min_fill_ratio:.1%}, "
                    f"above hard-underfill threshold {self.underfill_ratio:.1%}"
                ),
            )

        return (
            FillIntegrityStatus.UNDERFILL,
            False,
            (
                f"hard underfill {ratio:.1%} — below underfill threshold "
                f"{self.underfill_ratio:.1%}"
            ),
        )

    def _get_or_create_ledger(self, cycle_id: str) -> CycleLedger:
        with self._lock:
            if cycle_id not in self._open_ledgers:
                self._open_ledgers[cycle_id] = CycleLedger(cycle_id)
            return self._open_ledgers[cycle_id]

    @staticmethod
    def _build_report(
        cycle_id: str,
        records: List[FillRecord],
    ) -> CycleReconciliationReport:
        report = CycleReconciliationReport(
            cycle_id=cycle_id,
            total_orders=len(records),
            records=records,
        )

        for rec in records:
            report.total_intended_usd += rec.intended_size_usd
            report.total_filled_usd += rec.actual_fill_usd

            if rec.status == FillIntegrityStatus.FULL:
                report.full_fills += 1
            elif rec.status == FillIntegrityStatus.PARTIAL:
                report.partial_fills += 1
            elif rec.status in (
                FillIntegrityStatus.UNDERFILL,
                FillIntegrityStatus.ZERO_FILL,
            ):
                report.underfills += 1

        if report.total_intended_usd > 0:
            report.overall_fill_ratio = (
                report.total_filled_usd / report.total_intended_usd
            )

        report.has_integrity_failures = report.underfills > 0

        return report


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_INSTANCE: Optional[ExecutionIntegrityLayer] = None
_INSTANCE_LOCK = threading.Lock()


def get_execution_integrity_layer(
    min_fill_ratio: float = DEFAULT_MIN_FILL_RATIO,
    underfill_ratio: float = DEFAULT_UNDERFILL_RATIO,
) -> ExecutionIntegrityLayer:
    """
    Return (or create) the process-wide :class:`ExecutionIntegrityLayer`
    singleton.

    Parameters are only honoured on the **first** call; subsequent calls
    return the already-created instance regardless of parameters.
    """
    global _INSTANCE
    with _INSTANCE_LOCK:
        if _INSTANCE is None:
            _INSTANCE = ExecutionIntegrityLayer(
                min_fill_ratio=min_fill_ratio,
                underfill_ratio=underfill_ratio,
            )
    return _INSTANCE
