"""
NIJA Stranded Position Recovery Loop
======================================

Automatically recovers stranded positions that were written to the stranded
journal by :class:`~bot.forced_liquidation_fallback.ForcedLiquidationFallback`
when all execution paths failed.

Key features
------------
* Background worker thread that periodically scans the stranded journal.
* Attempts ``force_close`` on each stranded position when the broker is healthy.
* **Too-many-venues-failed guard**: if more than a configurable fraction of
  known brokers/venues have failed, the worker sets ``pause_trading = True``
  globally and skips recovery attempts until health is restored.
* Persists recovery outcomes — successfully recovered entries are flagged so
  they are not re-attempted on the next pass.
* Singleton via :func:`get_stranded_position_recovery`.

Usage
-----
::

    from bot.stranded_position_recovery import get_stranded_position_recovery

    recovery = get_stranded_position_recovery()

    # Start the background thread (call once at bot startup)
    recovery.start(broker=my_broker, broker_manager=my_broker_manager)

    # Check if trading is globally paused due to venue failures
    if recovery.pause_trading:
        skip_new_entries()

    # Manual one-shot attempt (useful from tests or operator commands)
    results = recovery.recover_stranded_positions(broker=my_broker)

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("nija.stranded_position_recovery")

# ---------------------------------------------------------------------------
# Constants (tunable via environment variables)
# ---------------------------------------------------------------------------

# How often the background worker checks the stranded journal (seconds)
RECOVERY_INTERVAL_S: float = float(os.environ.get("SPR_INTERVAL_S", "120"))

# Maximum fraction of known venues that may fail before trading is paused
MAX_FAILED_VENUE_FRACTION: float = float(os.environ.get("SPR_MAX_FAILED_FRACTION", "0.5"))

# Path for the stranded-positions journal (must match ForcedLiquidationFallback)
STRANDED_POSITIONS_FILE: str = os.environ.get(
    "FLF_STRANDED_JOURNAL", "data/stranded_positions.jsonl"
)

# Path for the recovery audit log
RECOVERY_LOG_FILE: str = os.environ.get(
    "SPR_RECOVERY_LOG", "data/stranded_recovery_log.jsonl"
)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class RecoveryAttempt:
    """Record of a single recovery attempt for one stranded position."""

    symbol: str
    side: str
    quantity: float
    original_reason: str
    success: bool
    broker_response: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# StrandedPositionRecovery
# ---------------------------------------------------------------------------


class StrandedPositionRecovery:
    """
    Background recovery engine for stranded positions.

    Reads the stranded-positions journal written by
    :class:`~bot.forced_liquidation_fallback.ForcedLiquidationFallback`,
    and re-attempts closure when the broker is reported as healthy.

    Thread-safe; the recovery loop runs in a daemon thread.
    """

    def __init__(
        self,
        stranded_journal_path: str = STRANDED_POSITIONS_FILE,
        recovery_log_path: str = RECOVERY_LOG_FILE,
        interval_s: float = RECOVERY_INTERVAL_S,
        max_failed_venue_fraction: float = MAX_FAILED_VENUE_FRACTION,
    ) -> None:
        self._lock = threading.Lock()
        self._stranded_journal_path = stranded_journal_path
        self._recovery_log_path = recovery_log_path
        self._interval_s = interval_s
        self._max_failed_venue_fraction = max_failed_venue_fraction

        # Global guard: True → new entries are suspended, only exits allowed
        self.pause_trading: bool = False

        # Set of (symbol + timestamp) keys already successfully recovered
        self._recovered_keys: set = set()

        self._broker: Optional[Any] = None
        self._broker_manager: Optional[Any] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

        # Stats
        self._total_recovery_attempts: int = 0
        self._total_recovered: int = 0

        # Ensure data directories exist
        for path in (stranded_journal_path, recovery_log_path):
            directory = os.path.dirname(path)
            if directory:
                os.makedirs(directory, exist_ok=True)

        logger.info(
            "✅ StrandedPositionRecovery initialised | interval=%.0fs | "
            "max_failed_venue_fraction=%.0f%%",
            interval_s,
            max_failed_venue_fraction * 100,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(
        self,
        broker: Any,
        broker_manager: Optional[Any] = None,
    ) -> None:
        """
        Start the background recovery worker thread.

        Parameters
        ----------
        broker:
            Primary broker object used to attempt force-close orders.
        broker_manager:
            Optional multi-broker manager used to evaluate venue health for
            the ``too_many_venues_failed`` guard.  When omitted, only the
            primary broker health is checked.
        """
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                logger.debug("StrandedPositionRecovery: worker already running")
                return

            self._broker = broker
            self._broker_manager = broker_manager
            self._stop_event.clear()

            self._thread = threading.Thread(
                target=self._worker_loop,
                name="stranded-position-recovery",
                daemon=True,
            )
            self._thread.start()
            logger.info("🔄 StrandedPositionRecovery: background worker started")

    def stop(self) -> None:
        """Signal the background worker to stop at the next interval boundary."""
        self._stop_event.set()
        logger.info("🛑 StrandedPositionRecovery: stop signal sent")

    def recover_stranded_positions(
        self,
        broker: Optional[Any] = None,
    ) -> List[RecoveryAttempt]:
        """
        Perform a single recovery pass over the stranded journal.

        For each entry that has not already been recovered, attempts to
        force-close the position using the broker.  Results are written to
        the recovery audit log.

        Parameters
        ----------
        broker:
            Broker to use for this pass.  Falls back to the broker provided
            at :meth:`start` if omitted.

        Returns
        -------
        List[RecoveryAttempt]
            One record per attempted entry (successful or not).
        """
        active_broker = broker or self._broker
        if active_broker is None:
            logger.warning("StrandedPositionRecovery: no broker available — skipping pass")
            return []

        # Evaluate venue health guard before attempting any closure
        if self.too_many_venues_failed():
            if not self.pause_trading:
                self.pause_trading = True
                logger.critical(
                    "🚫 STRANDED RECOVERY: too many venues failed — "
                    "setting pause_trading=True; skipping recovery pass"
                )
            return []

        # If we previously paused, check whether we can resume
        if self.pause_trading and not self.too_many_venues_failed():
            self.pause_trading = False
            logger.info("✅ StrandedPositionRecovery: venue health restored — pause_trading=False")

        records = self._load_journal()
        if not records:
            return []

        results: List[RecoveryAttempt] = []

        for record in records:
            key = self._record_key(record)
            if key in self._recovered_keys:
                continue  # Already resolved — skip

            symbol: str = record.get("symbol", "")
            side: str = record.get("side", "sell")
            quantity: float = float(record.get("quantity", 0.0))
            reason: str = record.get("reason", "stranded")

            if not symbol or quantity <= 0:
                logger.warning(
                    "StrandedPositionRecovery: skipping malformed record — %s", record
                )
                continue

            if not self._broker_is_healthy(active_broker):
                logger.warning(
                    "StrandedPositionRecovery: broker not healthy — "
                    "deferring recovery of %s", symbol
                )
                break  # Don't attempt more if broker is unhealthy

            attempt = self._attempt_force_close(
                broker=active_broker,
                symbol=symbol,
                side=side,
                quantity=quantity,
                reason=reason,
            )
            results.append(attempt)

            with self._lock:
                self._total_recovery_attempts += 1
                if attempt.success:
                    self._total_recovered += 1
                    self._recovered_keys.add(key)
                    logger.info(
                        "✅ STRANDED RECOVERED: %s qty=%.8f side=%s",
                        symbol, quantity, side,
                    )
                else:
                    logger.warning(
                        "⚠️ STRANDED RECOVERY FAILED: %s qty=%.8f — %s",
                        symbol, quantity, attempt.error,
                    )

            self._append_recovery_log(attempt)

        return results

    def too_many_venues_failed(self) -> bool:
        """
        Return ``True`` when too many trading venues are currently offline.

        The check uses the optional ``broker_manager`` supplied at
        :meth:`start`.  When no manager is available, falls back to a single
        primary-broker health check.

        Returns
        -------
        bool
            ``True`` → caller should set ``pause_trading = True``.
        """
        try:
            # Prefer the multi-broker manager for an aggregated view
            if self._broker_manager is not None:
                total, failed = self._count_venues()
                if total == 0:
                    return False
                fraction = failed / total
                too_many = fraction >= self._max_failed_venue_fraction
                if too_many:
                    logger.warning(
                        "⚠️ too_many_venues_failed: %d/%d venues offline (%.0f%% ≥ threshold %.0f%%)",
                        failed, total, fraction * 100,
                        self._max_failed_venue_fraction * 100,
                    )
                return too_many

            # Fallback: single broker health check
            if self._broker is not None:
                return not self._broker_is_healthy(self._broker)

        except Exception as exc:
            logger.error("too_many_venues_failed check error: %s", exc)

        return False

    def get_status(self) -> Dict[str, Any]:
        """Return a serialisable snapshot of the recovery engine state."""
        with self._lock:
            return {
                "engine": "StrandedPositionRecovery",
                "version": "1.0",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "pause_trading": self.pause_trading,
                "total_recovery_attempts": self._total_recovery_attempts,
                "total_recovered": self._total_recovered,
                "recovered_keys_count": len(self._recovered_keys),
                "stranded_journal": self._stranded_journal_path,
                "recovery_log": self._recovery_log_path,
                "interval_s": self._interval_s,
                "worker_alive": self._thread is not None and self._thread.is_alive(),
            }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _worker_loop(self) -> None:
        """Background thread: repeatedly scan and attempt recovery."""
        logger.info("StrandedPositionRecovery: worker loop started")
        while not self._stop_event.is_set():
            try:
                self.recover_stranded_positions()
            except Exception as exc:
                logger.error("StrandedPositionRecovery: worker loop error — %s", exc)

            # Sleep in short intervals so we can respond to stop quickly
            for _ in range(int(self._interval_s / 5)):
                if self._stop_event.is_set():
                    break
                time.sleep(5)

        logger.info("StrandedPositionRecovery: worker loop stopped")

    def _load_journal(self) -> List[Dict[str, Any]]:
        """Read all entries from the stranded-positions JSONL journal."""
        records: List[Dict[str, Any]] = []
        try:
            with open(self._stranded_journal_path, "r") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        try:
                            records.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
        except FileNotFoundError:
            pass
        except Exception as exc:
            logger.error("StrandedPositionRecovery: journal read error — %s", exc)
        return records

    @staticmethod
    def _record_key(record: Dict[str, Any]) -> str:
        """Stable identity key for a stranded journal entry."""
        return f"{record.get('symbol', '')}::{record.get('timestamp', '')}"

    def _broker_is_healthy(self, broker: Any) -> bool:
        """
        Return ``True`` if the broker appears healthy enough for order submission.

        Tries, in order:
        1. ``broker.is_healthy()``
        2. Circuit-breaker attribute ``broker.circuit_breaker.is_trading_allowed()``
        3. Default to ``True`` so we don't block recovery when the method is absent.
        """
        try:
            if hasattr(broker, "is_healthy"):
                return bool(broker.is_healthy())
        except Exception:
            pass
        try:
            cb = getattr(broker, "circuit_breaker", None)
            if cb is not None and hasattr(cb, "is_trading_allowed"):
                return bool(cb.is_trading_allowed())
        except Exception:
            pass
        return True  # Assume healthy when no health API is available

    def _count_venues(self) -> tuple:
        """Return (total_venues, failed_venues) from the broker manager."""
        manager = self._broker_manager
        total = 0
        failed = 0
        try:
            # Try various broker-manager APIs
            if hasattr(manager, "get_all_brokers"):
                brokers = manager.get_all_brokers()
                for b in (brokers or []):
                    total += 1
                    if not self._broker_is_healthy(b):
                        failed += 1
            elif hasattr(manager, "brokers"):
                for b in (manager.brokers or {}).values():
                    total += 1
                    if not self._broker_is_healthy(b):
                        failed += 1
            else:
                # Unknown manager structure — no data
                return 0, 0
        except Exception as exc:
            logger.debug("_count_venues error: %s", exc)
        return total, failed

    def _attempt_force_close(
        self,
        broker: Any,
        symbol: str,
        side: str,
        quantity: float,
        reason: str,
    ) -> RecoveryAttempt:
        """
        Try to close a stranded position via the broker.

        Tries, in order:
        1. ``broker.place_market_order(symbol, side, quantity)``
        2. ``broker.close_position(symbol, quantity)``
        3. ``broker.force_liquidate(symbol, quantity)``
        """
        logger.info(
            "🔧 Attempting stranded recovery: %s qty=%.8f side=%s (reason: %s)",
            symbol, quantity, side, reason,
        )
        for method_name, kwargs in [
            ("place_market_order", {"symbol": symbol, "side": side,
                                     "quantity": quantity, "size_type": "base"}),
            ("close_position",     {"symbol": symbol, "quantity": quantity}),
            ("force_liquidate",    {"symbol": symbol, "quantity": quantity}),
        ]:
            method = getattr(broker, method_name, None)
            if method is None:
                continue
            try:
                response = method(**kwargs)
                if response is not None:
                    return RecoveryAttempt(
                        symbol=symbol,
                        side=side,
                        quantity=quantity,
                        original_reason=reason,
                        success=True,
                        broker_response=response if isinstance(response, dict) else None,
                    )
            except Exception as exc:
                logger.warning(
                    "StrandedRecovery.%s failed for %s: %s", method_name, symbol, exc
                )

        return RecoveryAttempt(
            symbol=symbol,
            side=side,
            quantity=quantity,
            original_reason=reason,
            success=False,
            error="all broker methods exhausted",
        )

    def _append_recovery_log(self, attempt: RecoveryAttempt) -> None:
        """Append a recovery attempt record to the audit log."""
        try:
            with open(self._recovery_log_path, "a") as fh:
                fh.write(json.dumps(attempt.to_dict()) + "\n")
        except Exception as exc:
            logger.error(
                "StrandedPositionRecovery: could not write recovery log — %s", exc
            )


# ---------------------------------------------------------------------------
# Singleton accessor
# ---------------------------------------------------------------------------

_RECOVERY_INSTANCE: Optional[StrandedPositionRecovery] = None
_RECOVERY_INSTANCE_LOCK = threading.Lock()


def get_stranded_position_recovery() -> StrandedPositionRecovery:
    """
    Return the process-wide singleton :class:`StrandedPositionRecovery`.

    Thread-safe; created once on first call.
    """
    global _RECOVERY_INSTANCE
    if _RECOVERY_INSTANCE is None:
        with _RECOVERY_INSTANCE_LOCK:
            if _RECOVERY_INSTANCE is None:
                _RECOVERY_INSTANCE = StrandedPositionRecovery()
    return _RECOVERY_INSTANCE
