"""
CONTINUOUS DUST MONITOR (Option A)
====================================
Scheduled dust sweep for the Adaptive Intelligence Engine.

Every X minutes/hours, checks all accounts for positions below
DUST_THRESHOLD_USD and automatically closes them, logging each
cleanup action for auditing.

Design goals:
- Time-based scheduling (not cycle-count based)
- Full multi-account support (platform + users)
- Immutable audit log of every closure attempt
- Dry-run mode for safe testing
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.continuous_dust_monitor")

# Default dust threshold – positions below this USD value are swept
DUST_THRESHOLD_USD = 1.00

# Default sweep interval (minutes between sweeps)
DEFAULT_SWEEP_INTERVAL_MINUTES = 30


@dataclass
class DustCleanupRecord:
    """Immutable audit record for one dust-closure attempt."""
    timestamp: str
    account_id: str
    symbol: str
    quantity: float
    usd_value: float
    success: bool
    message: str


@dataclass
class SweepSummary:
    """Summary of a single dust-sweep run."""
    sweep_id: str
    started_at: str
    completed_at: str
    accounts_checked: int
    dust_found: int
    dust_closed: int
    dust_failed: int
    total_usd_recovered: float
    records: List[DustCleanupRecord] = field(default_factory=list)


class ContinuousDustMonitor:
    """
    Adaptive Intelligence Engine – Continuous Dust Monitor.

    Periodically sweeps all connected accounts and closes any position
    whose current USD value is below ``dust_threshold_usd``.

    Args:
        dust_threshold_usd: USD floor; positions below this are dust.
        sweep_interval_minutes: How often (wall-clock minutes) to sweep.
        dry_run: When *True* log planned actions but do not execute orders.
        audit_log: External list to append :class:`DustCleanupRecord` to;
                   if *None* the monitor maintains its own internal log.
    """

    def __init__(
        self,
        dust_threshold_usd: float = DUST_THRESHOLD_USD,
        sweep_interval_minutes: float = DEFAULT_SWEEP_INTERVAL_MINUTES,
        dry_run: bool = False,
        audit_log: Optional[List[DustCleanupRecord]] = None,
    ) -> None:
        self.dust_threshold_usd = dust_threshold_usd
        self.sweep_interval_seconds = sweep_interval_minutes * 60
        self.dry_run = dry_run
        self._audit_log: List[DustCleanupRecord] = audit_log if audit_log is not None else []
        self._last_sweep_time: Optional[float] = None  # monotonic seconds
        self._sweep_count: int = 0
        self._total_closed: int = 0
        self._total_recovered_usd: float = 0.0

        logger.info("🌀 CONTINUOUS DUST MONITOR initialized")
        logger.info(f"   Dust threshold : ${dust_threshold_usd:.2f} USD")
        logger.info(f"   Sweep interval : every {sweep_interval_minutes:.0f} minutes")
        logger.info(f"   Dry-run mode   : {'ENABLED (no real orders)' if dry_run else 'DISABLED (live)'}")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def maybe_sweep(
        self,
        brokers: Optional[List[Tuple[str, Any]]] = None,
        force: bool = False,
    ) -> Optional[SweepSummary]:
        """
        Run a dust sweep if the configured interval has elapsed (or forced).

        Args:
            brokers: List of ``(account_id, broker_instance)`` tuples covering
                     every account that should be checked. Pass *None* to skip.
            force: When *True* bypass the interval check and sweep immediately.

        Returns:
            A :class:`SweepSummary` if a sweep was executed, else *None*.
        """
        if not force and not self._is_sweep_due():
            return None

        if not brokers:
            logger.debug("   ℹ️  Dust monitor: no brokers provided – sweep skipped")
            self._last_sweep_time = time.monotonic()
            return None

        return self._run_sweep(brokers)

    @property
    def audit_log(self) -> List[DustCleanupRecord]:
        """Read-only view of the audit log."""
        return list(self._audit_log)

    @property
    def stats(self) -> Dict[str, Any]:
        """Lightweight lifetime statistics."""
        return {
            "sweep_count": self._sweep_count,
            "total_dust_closed": self._total_closed,
            "total_usd_recovered": round(self._total_recovered_usd, 4),
            "last_sweep": (
                datetime.fromtimestamp(
                    time.time() - (time.monotonic() - self._last_sweep_time)
                ).isoformat()
                if self._last_sweep_time is not None
                else None
            ),
        }

    def seconds_until_next_sweep(self) -> float:
        """Return seconds remaining until the next scheduled sweep (0 = due now)."""
        if self._last_sweep_time is None:
            return 0.0
        elapsed = time.monotonic() - self._last_sweep_time
        remaining = self.sweep_interval_seconds - elapsed
        return max(0.0, remaining)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _is_sweep_due(self) -> bool:
        if self._last_sweep_time is None:
            return True
        return (time.monotonic() - self._last_sweep_time) >= self.sweep_interval_seconds

    def _run_sweep(self, brokers: List[Tuple[str, Any]]) -> SweepSummary:
        """Execute a full dust sweep across all provided accounts."""
        self._sweep_count += 1
        sweep_id = f"sweep-{self._sweep_count:04d}"
        started_at = datetime.utcnow().isoformat()

        logger.warning("")
        logger.warning(f"🌀 CONTINUOUS DUST SWEEP [{sweep_id}] STARTED")
        logger.warning(f"   Time      : {started_at}")
        logger.warning(f"   Accounts  : {len(brokers)}")
        logger.warning(f"   Threshold : ${self.dust_threshold_usd:.2f} USD")
        logger.warning(f"   Mode      : {'DRY-RUN' if self.dry_run else 'LIVE'}")
        logger.warning("")

        records: List[DustCleanupRecord] = []
        accounts_checked = 0
        dust_found = 0
        dust_closed = 0
        dust_failed = 0
        usd_recovered = 0.0

        for account_id, broker in brokers:
            accounts_checked += 1
            found, closed, failed, recovered, acct_records = self._sweep_account(
                account_id, broker
            )
            dust_found += found
            dust_closed += closed
            dust_failed += failed
            usd_recovered += recovered
            records.extend(acct_records)

        self._last_sweep_time = time.monotonic()
        self._total_closed += dust_closed
        self._total_recovered_usd += usd_recovered
        self._audit_log.extend(records)

        completed_at = datetime.utcnow().isoformat()

        logger.warning(f"🌀 CONTINUOUS DUST SWEEP [{sweep_id}] COMPLETE")
        logger.warning(f"   Accounts checked : {accounts_checked}")
        logger.warning(f"   Dust found       : {dust_found}")
        logger.warning(f"   Dust closed      : {dust_closed}")
        logger.warning(f"   Dust failed      : {dust_failed}")
        logger.warning(f"   USD recovered    : ${usd_recovered:.4f}")
        logger.warning("")

        return SweepSummary(
            sweep_id=sweep_id,
            started_at=started_at,
            completed_at=completed_at,
            accounts_checked=accounts_checked,
            dust_found=dust_found,
            dust_closed=dust_closed,
            dust_failed=dust_failed,
            total_usd_recovered=usd_recovered,
            records=records,
        )

    def _sweep_account(
        self, account_id: str, broker: Any
    ) -> Tuple[int, int, int, float, List[DustCleanupRecord]]:
        """
        Sweep one account for dust positions.

        Returns:
            Tuple of (found, closed, failed, usd_recovered, records).
        """
        records: List[DustCleanupRecord] = []
        found = closed = failed = 0
        usd_recovered = 0.0

        try:
            positions = broker.get_positions()
        except Exception as exc:
            logger.error(f"   ❌ [{account_id}] Could not fetch positions: {exc}")
            return found, closed, failed, usd_recovered, records

        if not positions:
            logger.debug(f"   ℹ️  [{account_id}] No open positions")
            return found, closed, failed, usd_recovered, records

        logger.info(f"   🔍 [{account_id}] Checking {len(positions)} position(s)…")

        for pos in positions:
            symbol = pos.get("symbol", "UNKNOWN")
            quantity = float(pos.get("quantity", 0))

            # Determine current USD value
            usd_value = float(pos.get("usd_value", pos.get("size_usd", 0.0)))
            if usd_value <= 0.0:
                try:
                    price = broker.get_current_price(symbol)
                    usd_value = quantity * price if price and price > 0 else 0.0
                except Exception:
                    usd_value = 0.0

            if usd_value >= self.dust_threshold_usd:
                continue  # Not dust

            found += 1
            ts = datetime.utcnow().isoformat()
            logger.warning(
                f"   🗑️  DUST DETECTED [{account_id}] {symbol}: "
                f"${usd_value:.4f} (qty={quantity:.8f})"
            )

            if self.dry_run:
                msg = f"DRY-RUN: would close {symbol} (${usd_value:.4f})"
                logger.info(f"      [DRY-RUN] {msg}")
                records.append(
                    DustCleanupRecord(
                        timestamp=ts,
                        account_id=account_id,
                        symbol=symbol,
                        quantity=quantity,
                        usd_value=usd_value,
                        success=True,
                        message=msg,
                    )
                )
                closed += 1
                usd_recovered += usd_value
                continue

            # Attempt to close the position
            success, msg = self._close_position(broker, symbol, quantity, usd_value)
            if success:
                closed += 1
                usd_recovered += usd_value
                logger.warning(
                    f"   ✅ DUST CLOSED [{account_id}] {symbol}: ${usd_value:.4f} – {msg}"
                )
            else:
                failed += 1
                logger.error(
                    f"   ❌ DUST CLOSE FAILED [{account_id}] {symbol}: ${usd_value:.4f} – {msg}"
                )

            records.append(
                DustCleanupRecord(
                    timestamp=ts,
                    account_id=account_id,
                    symbol=symbol,
                    quantity=quantity,
                    usd_value=usd_value,
                    success=success,
                    message=msg,
                )
            )

        return found, closed, failed, usd_recovered, records

    @staticmethod
    def _close_position(
        broker: Any, symbol: str, quantity: float, usd_value: float
    ) -> Tuple[bool, str]:
        """
        Attempt to close a position via the broker API.

        Tries (in order):
        1. ``broker.close_position(symbol)``
        2. ``broker.place_order(symbol, 'sell', 'market', quantity)``

        Returns:
            ``(success, human-readable message)``
        """
        # Strategy 1 – dedicated close method
        if hasattr(broker, "close_position"):
            try:
                result = broker.close_position(symbol)
                if result and result.get("status") not in ("error", "failed"):
                    return True, f"close_position succeeded (status={result.get('status')})"
                return False, f"close_position returned error: {result}"
            except Exception as exc:
                logger.debug(f"      close_position raised: {exc}")

        # Strategy 2 – market sell order
        if hasattr(broker, "place_order"):
            try:
                result = broker.place_order(
                    symbol=symbol,
                    side="sell",
                    order_type="market",
                    size=quantity,
                )
                if result and result.get("status") not in ("error", "failed"):
                    return True, f"place_order sell succeeded (status={result.get('status')})"
                return False, f"place_order returned error: {result}"
            except Exception as exc:
                return False, f"place_order raised: {exc}"

        return False, "Broker has no close_position or place_order method"


# ---------------------------------------------------------------------------
# Module-level singleton factory (same pattern as other bot singletons)
# ---------------------------------------------------------------------------
_monitor_instance: Optional[ContinuousDustMonitor] = None


def get_continuous_dust_monitor(
    dust_threshold_usd: float = DUST_THRESHOLD_USD,
    sweep_interval_minutes: float = DEFAULT_SWEEP_INTERVAL_MINUTES,
    dry_run: bool = False,
) -> ContinuousDustMonitor:
    """
    Return (or create) the shared :class:`ContinuousDustMonitor` instance.

    Calling this multiple times with different arguments after the first
    call has no effect – the singleton is returned as-is.
    """
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = ContinuousDustMonitor(
            dust_threshold_usd=dust_threshold_usd,
            sweep_interval_minutes=sweep_interval_minutes,
            dry_run=dry_run,
        )
    return _monitor_instance
