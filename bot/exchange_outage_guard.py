"""
NIJA Exchange Outage Guard
===========================

Detects persistent exchange failure patterns and pauses trading until the
exchange is confirmed stable again.

Problem
-------
Temporary API failures are normal; the system already retries individual
calls.  But *sustained* failure patterns — many consecutive errors, frozen
price feeds, maintenance windows — require a higher-level response:

    1. Pause all new trade entries.
    2. Retry the exchange connection every N minutes.
    3. Resume automatically when the exchange is healthy again (or wait for
       a manual override if ``auto_resume`` is disabled).

What it detects
---------------
* **Repeated API failures** — ``consecutive_api_errors ≥ pause_on_errors``
* **Frozen market data** — no price tick received within ``price_stale_seconds``
* **Orders not confirming** — order rejection rate too high in rolling window
* **Exchange maintenance windows** — explicit ``signal_maintenance()`` call

Architecture
------------
::

    record_api_call()  →  _check_failure_pattern()  →  maybe_pause()
    record_price_tick() → _check_price_freshness()  →  maybe_pause()
    record_order_result() → _check_order_rejections() → maybe_pause()

    background thread → _retry_loop() → probe exchange health
                                       → resume() if healthy

Usage
-----
::

    from bot.exchange_outage_guard import get_exchange_outage_guard

    guard = get_exchange_outage_guard()

    # Feed every API call result:
    guard.record_api_call(success=True, latency_ms=95.0)

    # Feed every price tick:
    guard.record_price_tick("BTC-USD", price=65_000.0)

    # Feed every order event:
    guard.record_order_result(order_id="abc123", accepted=True)

    # Gate every trade entry:
    if guard.is_trading_paused():
        logger.warning("Exchange outage — skipping trade entry")
        return

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Callable, Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.exchange_outage_guard")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class OutageStatus(Enum):
    """High-level health status of the exchange connection."""
    HEALTHY = "HEALTHY"         # All systems nominal
    DEGRADED = "DEGRADED"       # Some failures but within tolerance
    PAUSED = "PAUSED"           # Trading paused due to outage
    MAINTENANCE = "MAINTENANCE"  # Explicit maintenance window signalled


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class ExchangeOutageGuardConfig:
    """Configurable thresholds for the Exchange Outage Guard.

    Attributes
    ----------
    pause_on_consecutive_errors:
        Pause trading after this many consecutive API errors.
        Default: 10 (matches problem statement example).
    pause_on_error_rate_pct:
        Also pause when the rolling error rate (within
        ``error_rate_window_seconds``) exceeds this percentage.
        Default: 60.0 (60 %).
    error_rate_window_seconds:
        Rolling window for API error rate calculation.
        Default: 120.0 (2 minutes).
    price_stale_seconds:
        Pause if no price tick has been received for any tracked symbol
        within this period (frozen market data).
        Default: 180.0 (3 minutes).
    order_reject_rate_threshold:
        Pause when this fraction of placed orders are rejected in the
        rolling window (``order_window_size`` events).
        Default: 0.70 (70 %).
    order_window_size:
        Number of most-recent order events to track for rejection rate.
        Default: 10.
    retry_interval_seconds:
        How often (seconds) the background retry loop checks whether the
        exchange has recovered.
        Default: 120.0 (2 minutes).
    auto_resume:
        If True (default), the guard resumes trading automatically when the
        exchange passes health checks.  If False, a manual ``resume()`` call
        is required.
    recovery_consecutive_successes:
        Number of consecutive successful API calls required (in a retry
        probe) before the guard considers the exchange recovered.
        Default: 3.
    degraded_consecutive_errors:
        Threshold for moving into DEGRADED status (below the full pause).
        Default: 5.
    min_error_rate_samples:
        Minimum number of API calls in the rolling window before the error
        *rate* check is evaluated.  This prevents a single error from
        triggering a rate-based pause when insufficient data is available.
        The consecutive burst check is unaffected by this setting.
        Default: 5.
    """
    pause_on_consecutive_errors: int = 10
    pause_on_error_rate_pct: float = 60.0
    error_rate_window_seconds: float = 120.0
    price_stale_seconds: float = 180.0
    order_reject_rate_threshold: float = 0.70
    order_window_size: int = 10
    retry_interval_seconds: float = 120.0
    auto_resume: bool = True
    recovery_consecutive_successes: int = 3
    degraded_consecutive_errors: int = 5
    min_error_rate_samples: int = 5


# ---------------------------------------------------------------------------
# Event record
# ---------------------------------------------------------------------------

@dataclass
class OutageEvent:
    """Record of a status change."""
    timestamp: str
    from_status: str
    to_status: str
    reason: str


# ---------------------------------------------------------------------------
# Main guard
# ---------------------------------------------------------------------------

class ExchangeOutageGuard:
    """Exchange outage detector with automatic retry and resume.

    Thread-safe.  Use ``get_exchange_outage_guard()`` for the singleton.
    """

    def __init__(
        self,
        config: Optional[ExchangeOutageGuardConfig] = None,
    ) -> None:
        self._config = config or ExchangeOutageGuardConfig()
        self._lock = threading.RLock()

        # Status
        self._status: OutageStatus = OutageStatus.HEALTHY
        self._pause_reason: str = ""
        self._event_log: List[OutageEvent] = []

        # API error tracking
        # Each entry: (monotonic_time, is_error: bool)
        self._api_calls: Deque[Tuple[float, bool]] = deque()
        self._consecutive_api_errors: int = 0
        self._consecutive_api_successes: int = 0

        # Price-feed tracking: symbol → last tick time (monotonic)
        self._last_price_time: Dict[str, float] = {}

        # Order tracking: deque of bool (True=accepted, False=rejected)
        self._order_results: Deque[bool] = deque(maxlen=self._config.order_window_size)

        # Maintenance window
        self._maintenance_mode: bool = False

        # Callbacks
        self._on_pause_callbacks: List[Callable[[str], None]] = []
        self._on_resume_callbacks: List[Callable[[], None]] = []

        # Background retry thread
        self._retry_thread: Optional[threading.Thread] = None
        self._stop_retry = threading.Event()

        logger.info(
            "🔌 ExchangeOutageGuard initialised | pause_on=%d errors | "
            "retry_every=%.0fs | auto_resume=%s",
            self._config.pause_on_consecutive_errors,
            self._config.retry_interval_seconds,
            self._config.auto_resume,
        )

    # ------------------------------------------------------------------
    # Feed methods — call these from the broker integration layer
    # ------------------------------------------------------------------

    def record_api_call(
        self,
        success: bool,
        latency_ms: float = 0.0,
        error: Optional[str] = None,
    ) -> None:
        """Record the outcome of a single API call.

        Parameters
        ----------
        success:
            True if the call succeeded, False on any error.
        latency_ms:
            Round-trip latency in milliseconds (informational).
        error:
            Optional error description for logging.
        """
        now = time.monotonic()
        with self._lock:
            self._api_calls.append((now, not success))  # True when it IS an error
            if success:
                self._consecutive_api_errors = 0
                self._consecutive_api_successes += 1
            else:
                self._consecutive_api_errors += 1
                self._consecutive_api_successes = 0
                logger.debug(
                    "⚠️  API error #%d: %s",
                    self._consecutive_api_errors,
                    error or "unknown",
                )

        self._check_failure_pattern()

    def record_price_tick(self, symbol: str, price: float) -> None:
        """Record a price tick for a symbol.

        Parameters
        ----------
        symbol:
            Instrument identifier (e.g. ``"BTC-USD"``).
        price:
            Latest price (must be > 0 to be valid).
        """
        if price > 0:
            now = time.monotonic()
            with self._lock:
                self._last_price_time[symbol] = now

    def record_order_result(self, order_id: str, accepted: bool) -> None:
        """Record the exchange response to an order submission.

        Parameters
        ----------
        order_id:
            Exchange-assigned order ID (used only for logging).
        accepted:
            True if the exchange accepted the order, False if rejected.
        """
        with self._lock:
            self._order_results.append(accepted)

        if not accepted:
            logger.debug("⚠️  Order rejected: %s", order_id)

        self._check_order_rejection_rate()

    # ------------------------------------------------------------------
    # Manual signals
    # ------------------------------------------------------------------

    def signal_maintenance(self, description: str = "Exchange maintenance") -> None:
        """Signal that the exchange is in a known maintenance window.

        Parameters
        ----------
        description:
            Human-readable description of the maintenance window.
        """
        self._pause(description, OutageStatus.MAINTENANCE)

    def signal_maintenance_over(self) -> None:
        """Signal that a maintenance window has ended.

        If ``auto_resume`` is True the guard will resume trading.
        """
        with self._lock:
            if self._status == OutageStatus.MAINTENANCE:
                self._maintenance_mode = False
        if self._config.auto_resume:
            self._attempt_resume()

    # ------------------------------------------------------------------
    # Check helpers
    # ------------------------------------------------------------------

    def _rolling_error_rate(self) -> float:
        """Return the API error rate over the rolling window (0–1).

        Returns 0.0 if there are fewer than ``min_error_rate_samples`` calls
        in the window to avoid false positives from tiny sample sizes.
        """
        now = time.monotonic()
        window = self._config.error_rate_window_seconds
        with self._lock:
            # Drop stale entries
            while self._api_calls and (now - self._api_calls[0][0]) > window:
                self._api_calls.popleft()
            total = len(self._api_calls)
            if total < self._config.min_error_rate_samples:
                return 0.0
            errors = sum(1 for _, is_err in self._api_calls if is_err)
            return errors / total

    def _check_failure_pattern(self) -> None:
        """Evaluate API failure patterns and pause if thresholds are exceeded."""
        with self._lock:
            consecutive = self._consecutive_api_errors
            status = self._status

        if status in (OutageStatus.PAUSED, OutageStatus.MAINTENANCE):
            return  # Already paused — no need to re-evaluate

        # Consecutive burst
        if consecutive >= self._config.pause_on_consecutive_errors:
            self._pause(
                f"Consecutive API failures: {consecutive} "
                f"(threshold: {self._config.pause_on_consecutive_errors})",
                OutageStatus.PAUSED,
            )
            return

        # Rolling error rate
        rate = self._rolling_error_rate()
        if rate * 100 >= self._config.pause_on_error_rate_pct:
            self._pause(
                f"API error rate {rate * 100:.1f}% ≥ "
                f"{self._config.pause_on_error_rate_pct:.0f}% over rolling window",
                OutageStatus.PAUSED,
            )
            return

        # Degraded but not paused
        if consecutive >= self._config.degraded_consecutive_errors:
            with self._lock:
                if self._status == OutageStatus.HEALTHY:
                    self._transition(OutageStatus.DEGRADED, f"{consecutive} consecutive errors")

    def _check_order_rejection_rate(self) -> None:
        """Pause if the order rejection rate is too high."""
        with self._lock:
            results = list(self._order_results)
            status = self._status

        if status in (OutageStatus.PAUSED, OutageStatus.MAINTENANCE):
            return

        if len(results) < 2:
            return

        rejection_rate = results.count(False) / len(results)
        if rejection_rate >= self._config.order_reject_rate_threshold:
            self._pause(
                f"Order rejection rate {rejection_rate * 100:.1f}% ≥ "
                f"{self._config.order_reject_rate_threshold * 100:.0f}% "
                f"over last {len(results)} orders",
                OutageStatus.PAUSED,
            )

    def check_price_freshness(self) -> bool:
        """Check all tracked symbols for stale price feeds.

        Returns
        -------
        bool
            True if a pause was triggered due to stale data.
        """
        now = time.monotonic()
        stale_threshold = self._config.price_stale_seconds

        with self._lock:
            stale = [
                sym
                for sym, last_t in self._last_price_time.items()
                if (now - last_t) > stale_threshold
            ]
            status = self._status

        if stale and status not in (OutageStatus.PAUSED, OutageStatus.MAINTENANCE):
            self._pause(
                f"Frozen price feed — no tick for {len(stale)} symbol(s) "
                f"in {stale_threshold:.0f}s: {', '.join(stale[:5])}",
                OutageStatus.PAUSED,
            )
            return True
        return False

    # ------------------------------------------------------------------
    # Pause / resume
    # ------------------------------------------------------------------

    def _pause(self, reason: str, new_status: OutageStatus) -> None:
        """Transition to a paused state."""
        with self._lock:
            if self._status in (OutageStatus.PAUSED, OutageStatus.MAINTENANCE):
                return  # already paused
            self._pause_reason = reason

        self._transition(new_status, reason)

        logger.critical(
            "🚫 EXCHANGE OUTAGE GUARD: Trading PAUSED | %s", reason
        )

        for cb in self._on_pause_callbacks:
            try:
                cb(reason)
            except Exception as exc:
                logger.error("❌ on_pause callback error: %s", exc)

        # Start retry thread if auto_resume is enabled
        if self._config.auto_resume and (
            self._retry_thread is None or not self._retry_thread.is_alive()
        ):
            self._stop_retry.clear()
            self._retry_thread = threading.Thread(
                target=self._retry_loop,
                name="ExchangeOutageRetry",
                daemon=True,
            )
            self._retry_thread.start()
            logger.info(
                "🔄 Retry loop started — will probe exchange every %.0fs",
                self._config.retry_interval_seconds,
            )

    def _attempt_resume(self) -> None:
        """Resume trading if the exchange appears healthy.

        Uses consecutive successful API calls as the primary recovery signal.
        Once the configured number of consecutive successes are recorded the
        guard transitions back to HEALTHY regardless of historical error rate
        in the rolling window (historical errors naturally age out of the
        window over time).
        """
        with self._lock:
            successes = self._consecutive_api_successes
            status = self._status

        if status not in (OutageStatus.PAUSED, OutageStatus.MAINTENANCE):
            return

        if successes >= self._config.recovery_consecutive_successes:
            self._transition(OutageStatus.HEALTHY, "Exchange recovered — consecutive successes met")
            logger.info("✅ EXCHANGE OUTAGE GUARD: Trading RESUMED")

            for cb in self._on_resume_callbacks:
                try:
                    cb()
                except Exception as exc:
                    logger.error("❌ on_resume callback error: %s", exc)

    def _retry_loop(self) -> None:
        """Background thread: periodically probe exchange health."""
        while not self._stop_retry.is_set():
            self._stop_retry.wait(self._config.retry_interval_seconds)
            if self._stop_retry.is_set():
                break

            with self._lock:
                status = self._status

            if status not in (OutageStatus.PAUSED, OutageStatus.MAINTENANCE):
                logger.debug("🔄 Retry loop: status=%s — stopping loop", status.value)
                break

            logger.info(
                "🔌 Retry loop: probing exchange health (status=%s)…",
                status.value,
            )
            # Fire a synthetic "healthy" check — real recovery happens when
            # the broker integration calls record_api_call(success=True)
            # repeatedly.  Here we just log a reminder.
            self._attempt_resume()

    def resume(self, reason: str = "Manual resume") -> None:
        """Manually resume trading (operator action).

        Parameters
        ----------
        reason:
            Human-readable reason for the override.
        """
        self._transition(OutageStatus.HEALTHY, reason)
        logger.warning("🔓 ExchangeOutageGuard manually resumed: %s", reason)
        self._stop_retry.set()

        for cb in self._on_resume_callbacks:
            try:
                cb()
            except Exception as exc:
                logger.error("❌ on_resume callback error: %s", exc)

    # ------------------------------------------------------------------
    # State transition helper
    # ------------------------------------------------------------------

    def _transition(self, new_status: OutageStatus, reason: str) -> None:
        """Record a status transition."""
        with self._lock:
            old_status = self._status
            if old_status == new_status:
                return
            self._status = new_status
            event = OutageEvent(
                timestamp=datetime.now(timezone.utc).isoformat(),
                from_status=old_status.value,
                to_status=new_status.value,
                reason=reason,
            )
            self._event_log.append(event)

        logger.info(
            "🔄 ExchangeOutageGuard: %s → %s | %s",
            old_status.value,
            new_status.value,
            reason,
        )

    # ------------------------------------------------------------------
    # Gate API
    # ------------------------------------------------------------------

    def is_trading_paused(self) -> bool:
        """Return True if trading should be paused due to exchange issues.

        Call this before every trade entry.
        """
        with self._lock:
            return self._status in (OutageStatus.PAUSED, OutageStatus.MAINTENANCE)

    def get_status(self) -> Dict:
        """Return a JSON-serialisable status snapshot."""
        with self._lock:
            return {
                "status": self._status.value,
                "paused": self.is_trading_paused(),
                "pause_reason": self._pause_reason,
                "consecutive_api_errors": self._consecutive_api_errors,
                "consecutive_api_successes": self._consecutive_api_successes,
                "tracked_symbols": list(self._last_price_time.keys()),
                "config": {
                    "pause_on_consecutive_errors": self._config.pause_on_consecutive_errors,
                    "retry_interval_seconds": self._config.retry_interval_seconds,
                    "auto_resume": self._config.auto_resume,
                },
                "event_count": len(self._event_log),
                "last_event": (
                    {
                        "timestamp": self._event_log[-1].timestamp,
                        "from": self._event_log[-1].from_status,
                        "to": self._event_log[-1].to_status,
                        "reason": self._event_log[-1].reason,
                    }
                    if self._event_log
                    else None
                ),
            }

    # ------------------------------------------------------------------
    # Callback registration
    # ------------------------------------------------------------------

    def register_on_pause(self, callback: Callable[[str], None]) -> None:
        """Register a callback invoked when trading is paused.

        Parameters
        ----------
        callback:
            Callable receiving ``(pause_reason: str)``.
        """
        self._on_pause_callbacks.append(callback)

    def register_on_resume(self, callback: Callable[[], None]) -> None:
        """Register a callback invoked when trading resumes.

        Parameters
        ----------
        callback:
            Callable receiving no arguments.
        """
        self._on_resume_callbacks.append(callback)

    def stop(self) -> None:
        """Stop the background retry thread (call on shutdown)."""
        self._stop_retry.set()
        if self._retry_thread and self._retry_thread.is_alive():
            self._retry_thread.join(timeout=5)


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_instance: Optional[ExchangeOutageGuard] = None
_instance_lock = threading.Lock()


def get_exchange_outage_guard(
    config: Optional[ExchangeOutageGuardConfig] = None,
) -> ExchangeOutageGuard:
    """Return (or create) the global ``ExchangeOutageGuard`` singleton.

    Parameters
    ----------
    config:
        Optional configuration; only used on the **first** call.
    """
    global _instance
    if _instance is None:
        with _instance_lock:
            if _instance is None:
                _instance = ExchangeOutageGuard(config)
    return _instance


# ---------------------------------------------------------------------------
# Quick smoke test
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys

    logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)

    cfg = ExchangeOutageGuardConfig(
        pause_on_consecutive_errors=10,
        retry_interval_seconds=5.0,   # fast for demo
        auto_resume=True,
        recovery_consecutive_successes=3,
    )
    guard = ExchangeOutageGuard(cfg)

    print("\n=== Exchange Outage Guard — smoke test ===\n")

    # Normal calls
    for _ in range(5):
        guard.record_api_call(success=True, latency_ms=80.0)
    print(f"After healthy calls: {guard.get_status()['status']}")

    # Simulate 10 consecutive errors
    for i in range(10):
        guard.record_api_call(success=False, error=f"timeout #{i}")
    print(f"After 10 errors:     {guard.get_status()['status']}  ← should be PAUSED")

    # Simulate recovery
    for _ in range(3):
        guard.record_api_call(success=True)
    guard._attempt_resume()
    print(f"After 3 successes:   {guard.get_status()['status']}")

    guard.stop()
    print("\n✅ Smoke test complete")
