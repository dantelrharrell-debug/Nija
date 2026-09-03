"""Protective stop-loss lifecycle tracking, independent of entry scanning.

Stop-loss monitoring must run whether or not entry scanning is enabled: a
disabled entry system must never disable a valid protective exit.  This module
records the four mandated lifecycle timestamps for every triggered stop:

``stop_detected_at`` → ``order_submitted_at`` → ``broker_acknowledged_at``
→ ``filled_at``

It also enforces:

* an administrator alert when a triggered stop has no broker acknowledgment
  within :data:`ACK_ALERT_SECONDS` (10 seconds);
* idempotency / client-order IDs so bounded retries can never duplicate an
  exit;
* the rule that a stop is *never* reported as executed without both a genuine
  broker order ID and a confirmed fill.
"""

from __future__ import annotations

import hashlib
import logging
import threading
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger("nija.protective_exit_lifecycle")

#: Seconds a triggered stop may wait for a broker acknowledgment before the
#: administrator is alerted.
ACK_ALERT_SECONDS: float = 10.0

#: Maximum bounded retries for a retryable protective-exit failure.
MAX_EXIT_RETRIES: int = 3


class StopState(str, Enum):
    DETECTED = "detected"
    SUBMITTED = "submitted"
    ACKNOWLEDGED = "acknowledged"
    FILLED = "filled"
    FAILED = "failed"
    BELOW_MINIMUM_EXIT = "below_minimum_exit"


@dataclass
class StopLossLifecycle:
    """Lifecycle record for one triggered protective stop."""

    idempotency_key: str
    client_order_id: str
    broker: str
    account_id: str
    symbol: str
    owned_qty: float
    state: StopState = StopState.DETECTED
    stop_detected_at: Optional[float] = None
    order_submitted_at: Optional[float] = None
    broker_acknowledged_at: Optional[float] = None
    filled_at: Optional[float] = None
    broker_order_id: str = ""
    attempts: int = 0
    last_error: str = ""
    alerted_no_ack: bool = False
    minimum_qty: float = 0.0

    @property
    def executed(self) -> bool:
        """A stop is executed only with a genuine order ID and confirmed fill."""
        return bool(
            self.state is StopState.FILLED
            and self.broker_order_id
            and self.filled_at is not None
        )

    @property
    def ack_latency_seconds(self) -> Optional[float]:
        """Seconds from stop detection to genuine broker acknowledgment."""
        if self.broker_acknowledged_at is None or self.stop_detected_at is None:
            return None
        return self.broker_acknowledged_at - self.stop_detected_at

    @property
    def fill_latency_seconds(self) -> Optional[float]:
        """Seconds from stop detection to confirmed fill."""
        if self.filled_at is None or self.stop_detected_at is None:
            return None
        return self.filled_at - self.stop_detected_at

    def as_dict(self) -> Dict[str, Any]:
        return {
            "idempotency_key": self.idempotency_key,
            "client_order_id": self.client_order_id,
            "broker": self.broker,
            "account_id": self.account_id,
            "symbol": self.symbol,
            "owned_qty": self.owned_qty,
            "minimum_qty": self.minimum_qty,
            "state": self.state.value,
            "stop_detected_at": self.stop_detected_at,
            "order_submitted_at": self.order_submitted_at,
            "broker_acknowledged_at": self.broker_acknowledged_at,
            "filled_at": self.filled_at,
            "broker_order_id": self.broker_order_id,
            "attempts": self.attempts,
            "last_error": self.last_error,
            "executed": self.executed,
            "ack_latency_seconds": self.ack_latency_seconds,
            "fill_latency_seconds": self.fill_latency_seconds,
        }


def build_idempotency_key(broker: str, account_id: str, symbol: str, trigger_id: str) -> str:
    """Deterministic key so a retried stop can never create a duplicate order."""
    raw = "|".join(
        str(part or "").strip().lower() for part in (broker, account_id, symbol, trigger_id)
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


class ProtectiveExitMonitor:
    """Tracks triggered stops independently of the entry scanner."""

    def __init__(self, *, alert_hook: Optional[Callable[[Dict[str, Any]], None]] = None) -> None:
        self._lock = threading.RLock()
        self._records: Dict[str, StopLossLifecycle] = {}
        self._alert_hook = alert_hook

    # -- lifecycle ------------------------------------------------------

    def record_stop_detected(
        self,
        *,
        broker: str,
        account_id: str,
        symbol: str,
        trigger_id: str,
        owned_qty: float,
    ) -> StopLossLifecycle:
        """Register a triggered stop.  Idempotent for the same trigger."""
        key = build_idempotency_key(broker, account_id, symbol, trigger_id)
        with self._lock:
            existing = self._records.get(key)
            if existing is not None:
                return existing
            record = StopLossLifecycle(
                idempotency_key=key,
                client_order_id=f"nija-stop-{key}",
                broker=str(broker or "").strip().lower(),
                account_id=str(account_id or "default").strip().lower(),
                symbol=str(symbol or "").strip().upper(),
                owned_qty=float(owned_qty or 0.0),
                stop_detected_at=time.time(),
            )
            self._records[key] = record
        logger.critical(
            "STOP_DETECTED broker=%s account=%s symbol=%s owned_qty=%.12f "
            "idempotency_key=%s independent_of_entry_scanner=true",
            record.broker, record.account_id, record.symbol, record.owned_qty, key,
        )
        return record

    def record_order_submitted(self, key: str) -> Optional[StopLossLifecycle]:
        with self._lock:
            record = self._records.get(key)
            if record is None:
                return None
            record.attempts += 1
            record.order_submitted_at = time.time()
            record.state = StopState.SUBMITTED
        logger.critical(
            "STOP_ORDER_SUBMITTED broker=%s account=%s symbol=%s client_order_id=%s attempt=%d",
            record.broker, record.account_id, record.symbol, record.client_order_id, record.attempts,
        )
        return record

    def record_broker_acknowledgment(self, key: str, broker_order_id: str) -> Optional[StopLossLifecycle]:
        """Record a *genuine* broker acknowledgment.  Empty IDs are refused."""
        order_id = str(broker_order_id or "").strip()
        with self._lock:
            record = self._records.get(key)
            if record is None:
                return None
            if not order_id:
                record.last_error = "acknowledgment_without_broker_order_id"
                logger.error(
                    "STOP_ACK_REFUSED broker=%s account=%s symbol=%s reason=missing_broker_order_id "
                    "order_id_fabricated=false",
                    record.broker, record.account_id, record.symbol,
                )
                return record
            record.broker_order_id = order_id
            record.broker_acknowledged_at = time.time()
            record.state = StopState.ACKNOWLEDGED
        logger.critical(
            "STOP_BROKER_ACKNOWLEDGED broker=%s account=%s symbol=%s broker_order_id=%s "
            "latency_s=%.3f",
            record.broker, record.account_id, record.symbol, order_id,
            (record.broker_acknowledged_at or 0.0) - (record.stop_detected_at or 0.0),
        )
        return record

    def record_fill(self, key: str, *, filled_qty: float, fill_price: float) -> Optional[StopLossLifecycle]:
        """Record a confirmed fill.  Requires a prior genuine acknowledgment."""
        with self._lock:
            record = self._records.get(key)
            if record is None:
                return None
            if not record.broker_order_id:
                record.last_error = "fill_without_broker_order_id"
                logger.error(
                    "STOP_FILL_REFUSED broker=%s account=%s symbol=%s "
                    "reason=no_genuine_broker_order_id fill_fabricated=false",
                    record.broker, record.account_id, record.symbol,
                )
                return record
            if float(filled_qty or 0.0) <= 0 or float(fill_price or 0.0) <= 0:
                record.last_error = "fill_without_confirmed_quantity_or_price"
                logger.error(
                    "STOP_FILL_REFUSED broker=%s account=%s symbol=%s "
                    "reason=unconfirmed_fill fill_fabricated=false",
                    record.broker, record.account_id, record.symbol,
                )
                return record
            record.filled_at = time.time()
            record.state = StopState.FILLED
        logger.critical(
            "STOP_FILLED broker=%s account=%s symbol=%s broker_order_id=%s filled_qty=%.12f "
            "fill_price=%.10f detection_to_fill_s=%.3f",
            record.broker, record.account_id, record.symbol, record.broker_order_id,
            float(filled_qty), float(fill_price),
            (record.filled_at or 0.0) - (record.stop_detected_at or 0.0),
        )
        return record

    def record_failure(self, key: str, error: str, *, retryable: bool) -> Optional[StopLossLifecycle]:
        with self._lock:
            record = self._records.get(key)
            if record is None:
                return None
            record.last_error = str(error or "")
            if not retryable or record.attempts >= MAX_EXIT_RETRIES:
                record.state = StopState.FAILED
        logger.error(
            "STOP_SUBMISSION_FAILED broker=%s account=%s symbol=%s attempts=%d retryable=%s error=%s",
            record.broker, record.account_id, record.symbol, record.attempts,
            str(bool(retryable)).lower(), error,
        )
        return record

    def mark_below_minimum(
        self, key: str, *, owned_qty: float, minimum_qty: float, reason: str
    ) -> Optional[StopLossLifecycle]:
        """Mark a stop as non-executable because the position is below minimum.

        The quantity is never increased to the venue minimum and no order is
        submitted.  NIJA must not claim this position has active executable
        stop-loss protection.
        """
        with self._lock:
            record = self._records.get(key)
            if record is None:
                return None
            record.state = StopState.BELOW_MINIMUM_EXIT
            record.owned_qty = float(owned_qty)
            record.minimum_qty = float(minimum_qty)
            record.last_error = reason
        logger.critical(
            "BELOW_MINIMUM_EXIT broker=%s account=%s symbol=%s owned_qty=%.12f minimum_qty=%.12f "
            "reason=%s order_submitted=false quantity_increased=false short_created=false "
            "position_preserved_for_reconciliation=true executable_stop_protection=false",
            record.broker, record.account_id, record.symbol, float(owned_qty), float(minimum_qty), reason,
        )
        self._emit_alert(record.as_dict() | {"alert": "BELOW_MINIMUM_EXIT"})
        return record

    # -- retries / idempotency -----------------------------------------

    def may_submit(self, key: str) -> bool:
        """Return ``True`` when a (re)submission is permitted for this stop.

        A stop that already carries a genuine broker order ID is never
        resubmitted — that is how duplicate exits are prevented.
        """
        with self._lock:
            record = self._records.get(key)
            if record is None:
                return False
            if record.broker_order_id:
                return False
            if record.state in (StopState.FILLED, StopState.BELOW_MINIMUM_EXIT, StopState.FAILED):
                return False
            return record.attempts < MAX_EXIT_RETRIES

    # -- alerting -------------------------------------------------------

    def check_acknowledgment_deadlines(self, *, now: Optional[float] = None) -> List[Dict[str, Any]]:
        """Alert for any triggered stop lacking a broker ACK after 10 seconds."""
        moment = float(now if now is not None else time.time())
        alerts: List[Dict[str, Any]] = []
        with self._lock:
            records = list(self._records.values())
        for record in records:
            if record.broker_acknowledged_at is not None or record.alerted_no_ack:
                continue
            if record.state in (StopState.BELOW_MINIMUM_EXIT, StopState.FAILED):
                continue
            detected = record.stop_detected_at or moment
            if moment - detected < ACK_ALERT_SECONDS:
                continue
            record.alerted_no_ack = True
            payload = record.as_dict() | {
                "alert": "STOP_NO_BROKER_ACK",
                "elapsed_s": moment - detected,
                "threshold_s": ACK_ALERT_SECONDS,
            }
            logger.critical(
                "ADMIN_ALERT_STOP_NO_BROKER_ACK broker=%s account=%s symbol=%s elapsed_s=%.3f "
                "threshold_s=%.1f broker_order_id=none stop_reported_executed=false",
                record.broker, record.account_id, record.symbol,
                payload["elapsed_s"], ACK_ALERT_SECONDS,
            )
            alerts.append(payload)
            self._emit_alert(payload)
        return alerts

    def _emit_alert(self, payload: Dict[str, Any]) -> None:
        if self._alert_hook is None:
            return
        try:
            self._alert_hook(payload)
        except Exception:
            logger.warning("protective exit alert hook failed", exc_info=True)

    # -- reporting ------------------------------------------------------

    def get(self, key: str) -> Optional[StopLossLifecycle]:
        with self._lock:
            return self._records.get(key)

    def snapshot(self) -> List[Dict[str, Any]]:
        with self._lock:
            return [record.as_dict() for record in self._records.values()]

    def below_minimum_positions(self) -> List[Dict[str, Any]]:
        """Dashboard feed of positions the exchange will not let NIJA exit."""
        with self._lock:
            return [
                record.as_dict()
                for record in self._records.values()
                if record.state is StopState.BELOW_MINIMUM_EXIT
            ]


_MONITOR: Optional[ProtectiveExitMonitor] = None
_MONITOR_LOCK = threading.Lock()


def get_protective_exit_monitor() -> ProtectiveExitMonitor:
    """Return the process-wide :class:`ProtectiveExitMonitor` singleton."""
    global _MONITOR
    with _MONITOR_LOCK:
        if _MONITOR is None:
            _MONITOR = ProtectiveExitMonitor()
    return _MONITOR


__all__ = [
    "ACK_ALERT_SECONDS",
    "MAX_EXIT_RETRIES",
    "ProtectiveExitMonitor",
    "StopLossLifecycle",
    "StopState",
    "build_idempotency_key",
    "get_protective_exit_monitor",
]
