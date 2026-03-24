"""
NIJA Execution Health Monitor
================================

Tracks API latency, order rejection rates, and fill times to detect
degraded execution conditions and automatically slow or pause trading.

Tracked metrics
---------------
* **API latency (ms)**       — round-trip time for any API call
* **Order rejection rate**   — fraction of submitted orders that were rejected
* **Fill time (ms)**         — time from order submission to confirmed fill

Degradation levels
------------------
::

  HEALTHY     — all metrics normal; full trading allowed
  DEGRADED    — latency or rejection rate elevated; reduce trade frequency
  IMPAIRED    — significant degradation; new entries paused until recovery
  CRITICAL    — severe API problems; all entries blocked

Thresholds (configurable via :class:`HealthConfig`)
------------------------------------------------------
::

  DEGRADED   latency ≥ 800 ms  OR  rejection_rate ≥ 5 %
  IMPAIRED   latency ≥ 2000 ms OR  rejection_rate ≥ 15 %
  CRITICAL   latency ≥ 5000 ms OR  rejection_rate ≥ 30 %

Recovery
--------
The monitor steps back toward HEALTHY automatically once the rolling
metrics return below the thresholds for ``recovery_window`` consecutive
measurements.

Singleton usage
---------------
::

    from bot.execution_health_monitor import get_execution_health_monitor

    monitor = get_execution_health_monitor()

    # Wrap every API call:
    with monitor.measure_api_call("get_candles"):
        candles = client.get_candles(...)

    # Record order outcomes:
    monitor.record_order_submitted()
    monitor.record_order_filled(fill_ms=220)
    monitor.record_order_rejected(reason="insufficient_funds")

    # Check before placing a new entry:
    health = monitor.check()
    if not health.allow_entries:
        logger.warning("Execution paused: %s", health.reason)
        return
    frequency_multiplier = health.frequency_multiplier   # 0.0 – 1.0

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import contextlib
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Deque, Dict, Generator, List, Optional

logger = logging.getLogger("nija.execution_health_monitor")


# ---------------------------------------------------------------------------
# Health levels
# ---------------------------------------------------------------------------

class HealthLevel(str, Enum):
    HEALTHY  = "HEALTHY"
    DEGRADED = "DEGRADED"
    IMPAIRED = "IMPAIRED"
    CRITICAL = "CRITICAL"


_LEVEL_ORDER: Dict[str, int] = {
    "HEALTHY":  0,
    "DEGRADED": 1,
    "IMPAIRED": 2,
    "CRITICAL": 3,
}

# Level → (allow_entries, frequency_multiplier, emoji_label)
_LEVEL_PARAMS: Dict[HealthLevel, tuple] = {
    HealthLevel.HEALTHY:  (True,  1.00, "🟢 Healthy  — full execution"),
    HealthLevel.DEGRADED: (True,  0.50, "🟡 Degraded — halved frequency"),
    HealthLevel.IMPAIRED: (False, 0.00, "🟠 Impaired — entries paused"),
    HealthLevel.CRITICAL: (False, 0.00, "🔴 Critical — all entries blocked"),
}


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class HealthConfig:
    """Configurable thresholds for the execution health monitor."""

    # Rolling window sizes
    latency_window: int = 50     # number of recent latency samples
    order_window: int = 100      # number of recent orders for rejection rate

    # Degradation thresholds
    degraded_latency_ms: float  = 800.0
    impaired_latency_ms: float  = 2_000.0
    critical_latency_ms: float  = 5_000.0

    degraded_rejection_pct: float  = 5.0
    impaired_rejection_pct: float  = 15.0
    critical_rejection_pct: float  = 30.0

    # Consecutive good measurements needed to step recovery
    recovery_window: int = 5


@dataclass
class HealthDecision:
    """Result of :meth:`ExecutionHealthMonitor.check`."""
    level: str
    allow_entries: bool
    frequency_multiplier: float
    reason: str
    avg_latency_ms: float
    p95_latency_ms: float
    rejection_rate_pct: float
    avg_fill_ms: float
    timestamp: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "level": self.level,
            "allow_entries": self.allow_entries,
            "frequency_multiplier": round(self.frequency_multiplier, 3),
            "reason": self.reason,
            "metrics": {
                "avg_latency_ms": round(self.avg_latency_ms, 1),
                "p95_latency_ms": round(self.p95_latency_ms, 1),
                "rejection_rate_pct": round(self.rejection_rate_pct, 2),
                "avg_fill_ms": round(self.avg_fill_ms, 1),
            },
            "timestamp": self.timestamp.isoformat(),
        }


# ---------------------------------------------------------------------------
# Core monitor
# ---------------------------------------------------------------------------

class ExecutionHealthMonitor:
    """
    Tracks API latency, rejection rate, and fill time; provides an entry gate
    that slows or halts trading when execution quality degrades.

    Thread-safe; use :func:`get_execution_health_monitor` for the process-wide
    singleton.
    """

    def __init__(self, config: Optional[HealthConfig] = None) -> None:
        self._cfg = config or HealthConfig()
        self._lock = threading.Lock()

        # Rolling metric buffers
        self._latencies_ms: Deque[float] = deque(maxlen=self._cfg.latency_window)
        self._fill_times_ms: Deque[float] = deque(maxlen=50)

        # Order outcome ring buffer: True = filled, False = rejected
        self._order_outcomes: Deque[bool] = deque(maxlen=self._cfg.order_window)

        # Current health level
        self._level: HealthLevel = HealthLevel.HEALTHY
        self._consecutive_good: int = 0

        # Totals for dashboard
        self._total_api_calls: int = 0
        self._total_orders: int = 0
        self._total_rejections: int = 0
        self._total_fills: int = 0

        logger.info(
            "ExecutionHealthMonitor initialised | "
            "degraded≥%.0fms/%.0f%% impaired≥%.0fms/%.0f%% critical≥%.0fms/%.0f%%",
            self._cfg.degraded_latency_ms, self._cfg.degraded_rejection_pct,
            self._cfg.impaired_latency_ms, self._cfg.impaired_rejection_pct,
            self._cfg.critical_latency_ms, self._cfg.critical_rejection_pct,
        )

    # ------------------------------------------------------------------
    # Measurement API
    # ------------------------------------------------------------------

    def record_api_latency(self, latency_ms: float) -> None:
        """Record a single API round-trip latency measurement in milliseconds."""
        with self._lock:
            self._total_api_calls += 1
            self._latencies_ms.append(latency_ms)
            self._update_level()

    @contextlib.contextmanager
    def measure_api_call(self, label: str = "") -> Generator[None, None, None]:
        """
        Context manager that automatically times and records API latency.

        Usage::

            with monitor.measure_api_call("get_candles"):
                result = api.get_candles(...)
        """
        t0 = time.monotonic()
        try:
            yield
        finally:
            elapsed_ms = (time.monotonic() - t0) * 1_000.0
            self.record_api_latency(elapsed_ms)
            if elapsed_ms > self._cfg.degraded_latency_ms:
                logger.debug(
                    "Slow API call%s: %.1f ms",
                    f" ({label})" if label else "",
                    elapsed_ms,
                )

    def record_order_submitted(self) -> None:
        """Call every time an order is submitted (before knowing the outcome)."""
        with self._lock:
            self._total_orders += 1

    def record_order_filled(self, fill_ms: float = 0.0) -> None:
        """Record a successful order fill.  ``fill_ms`` is the fill latency."""
        with self._lock:
            self._order_outcomes.append(True)
            self._total_fills += 1
            if fill_ms > 0:
                self._fill_times_ms.append(fill_ms)
            self._update_level()

    def record_order_rejected(self, reason: str = "") -> None:
        """Record an order rejection."""
        with self._lock:
            self._order_outcomes.append(False)
            self._total_rejections += 1
            self._update_level()
            if reason:
                logger.warning("Order rejected: %s", reason)

    # ------------------------------------------------------------------
    # Decision API
    # ------------------------------------------------------------------

    def check(self) -> HealthDecision:
        """Return the current execution health decision."""
        with self._lock:
            return self._build_decision()

    @property
    def level(self) -> HealthLevel:
        """Current health level."""
        with self._lock:
            return self._level

    @property
    def is_healthy(self) -> bool:
        """``True`` when execution is fully healthy."""
        with self._lock:
            return self._level == HealthLevel.HEALTHY

    @property
    def allow_entries(self) -> bool:
        """``True`` when new entries are permitted."""
        with self._lock:
            return _LEVEL_PARAMS[self._level][0]

    # ------------------------------------------------------------------
    # Reporting
    # ------------------------------------------------------------------

    def get_report(self) -> Dict[str, Any]:
        """Return a serialisable health snapshot."""
        with self._lock:
            d = self._build_decision()
            return {
                **d.to_dict(),
                "totals": {
                    "api_calls": self._total_api_calls,
                    "orders_submitted": self._total_orders,
                    "orders_filled": self._total_fills,
                    "orders_rejected": self._total_rejections,
                },
                "config": {
                    "degraded_latency_ms": self._cfg.degraded_latency_ms,
                    "impaired_latency_ms": self._cfg.impaired_latency_ms,
                    "critical_latency_ms": self._cfg.critical_latency_ms,
                    "degraded_rejection_pct": self._cfg.degraded_rejection_pct,
                    "impaired_rejection_pct": self._cfg.impaired_rejection_pct,
                    "critical_rejection_pct": self._cfg.critical_rejection_pct,
                },
            }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _avg_latency(self) -> float:
        if not self._latencies_ms:
            return 0.0
        return sum(self._latencies_ms) / len(self._latencies_ms)

    def _p95_latency(self) -> float:
        if not self._latencies_ms:
            return 0.0
        sorted_lat = sorted(self._latencies_ms)
        idx = max(0, int(len(sorted_lat) * 0.95) - 1)
        return sorted_lat[idx]

    def _rejection_rate_pct(self) -> float:
        n = len(self._order_outcomes)
        if n == 0:
            return 0.0
        rejections = sum(1 for ok in self._order_outcomes if not ok)
        return rejections / n * 100.0

    def _avg_fill_ms(self) -> float:
        if not self._fill_times_ms:
            return 0.0
        return sum(self._fill_times_ms) / len(self._fill_times_ms)

    def _classify_level(self, avg_lat: float, rej_pct: float) -> HealthLevel:
        if (
            avg_lat >= self._cfg.critical_latency_ms
            or rej_pct >= self._cfg.critical_rejection_pct
        ):
            return HealthLevel.CRITICAL
        if (
            avg_lat >= self._cfg.impaired_latency_ms
            or rej_pct >= self._cfg.impaired_rejection_pct
        ):
            return HealthLevel.IMPAIRED
        if (
            avg_lat >= self._cfg.degraded_latency_ms
            or rej_pct >= self._cfg.degraded_rejection_pct
        ):
            return HealthLevel.DEGRADED
        return HealthLevel.HEALTHY

    def _update_level(self) -> None:
        """Re-classify and apply recovery / escalation logic."""
        avg_lat = self._avg_latency()
        rej_pct = self._rejection_rate_pct()
        new_level = self._classify_level(avg_lat, rej_pct)

        if _LEVEL_ORDER[new_level.value] > _LEVEL_ORDER[self._level.value]:
            # Escalation — immediate
            old = self._level
            self._level = new_level
            self._consecutive_good = 0
            logger.warning(
                "ExecutionHealth DEGRADED: %s → %s | avg_lat=%.0fms rej=%.1f%%",
                old.value, new_level.value, avg_lat, rej_pct,
            )
        elif _LEVEL_ORDER[new_level.value] < _LEVEL_ORDER[self._level.value]:
            # Potential recovery — require recovery_window consecutive good reads
            self._consecutive_good += 1
            if self._consecutive_good >= self._cfg.recovery_window:
                old = self._level
                # Step back one level at a time
                level_list = [
                    HealthLevel.HEALTHY,
                    HealthLevel.DEGRADED,
                    HealthLevel.IMPAIRED,
                    HealthLevel.CRITICAL,
                ]
                current_idx = level_list.index(self._level)
                if current_idx > 0:
                    self._level = level_list[current_idx - 1]
                self._consecutive_good = 0
                logger.info(
                    "ExecutionHealth RECOVERED: %s → %s | avg_lat=%.0fms rej=%.1f%%",
                    old.value, self._level.value, avg_lat, rej_pct,
                )
        else:
            self._consecutive_good = 0

    def _build_decision(self) -> HealthDecision:
        allow, freq_mult, label = _LEVEL_PARAMS[self._level]
        avg_lat = self._avg_latency()
        p95_lat = self._p95_latency()
        rej_pct = self._rejection_rate_pct()
        fill_ms = self._avg_fill_ms()

        reasons: List[str] = [label]
        if avg_lat >= self._cfg.degraded_latency_ms:
            reasons.append(f"avg_latency={avg_lat:.0f}ms")
        if rej_pct >= self._cfg.degraded_rejection_pct:
            reasons.append(f"rejection_rate={rej_pct:.1f}%")

        return HealthDecision(
            level=self._level.value,
            allow_entries=allow,
            frequency_multiplier=freq_mult,
            reason="; ".join(reasons),
            avg_latency_ms=avg_lat,
            p95_latency_ms=p95_lat,
            rejection_rate_pct=rej_pct,
            avg_fill_ms=fill_ms,
        )


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_MONITOR_INSTANCE: Optional[ExecutionHealthMonitor] = None
_MONITOR_LOCK = threading.Lock()


def get_execution_health_monitor(
    config: Optional[HealthConfig] = None,
) -> ExecutionHealthMonitor:
    """
    Return the process-wide :class:`ExecutionHealthMonitor` singleton.

    ``config`` is only applied on the first call; subsequent calls return the
    existing instance regardless of the arguments passed.
    """
    global _MONITOR_INSTANCE
    with _MONITOR_LOCK:
        if _MONITOR_INSTANCE is None:
            _MONITOR_INSTANCE = ExecutionHealthMonitor(config)
    return _MONITOR_INSTANCE


__all__ = [
    "HealthConfig",
    "HealthDecision",
    "HealthLevel",
    "ExecutionHealthMonitor",
    "get_execution_health_monitor",
]
