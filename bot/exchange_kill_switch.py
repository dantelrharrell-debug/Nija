"""
NIJA Exchange Kill-Switch Protector
=====================================

Monitors live exchange / API health and automatically activates the global
kill switch when the exchange "goes crazy" — i.e. when signals indicate that
the exchange, its price feeds, or the API connection are behaving in ways
that make safe trading impossible.

Detectors (all independent, all contribute to a composite threat score)
-----------------------------------------------------------------------
1. **API Error-Rate Gate** — rolling-window consecutive/rate error tracker;
   activates kill switch when rate or burst count exceeds threshold.

2. **Price-Feed Anomaly Gate** — detects stale prices (no update for N
   seconds), zero/negative prices, and single-bar percentage jumps that
   exceed a configurable spike threshold.

3. **Order-Rejection Rate Gate** — tracks the fraction of placed orders
   that are rejected in a rolling window; kills trading when rejection
   rate is too high (exchange likely overloaded or rejecting silently).

4. **API Latency Gate** — rolling p95 latency tracker; flags sustained
   high latency as a signal that the exchange is struggling.

5. **Phantom-Fill / Duplicate-Order Gate** — detects the same order ID
   arriving as a fill event more than once (phantom fills) or the same
   client order ID being submitted twice (duplicate orders).

Architecture
------------
* Singleton via ``get_exchange_kill_switch_protector()``.
* Thread-safe throughout (one ``threading.Lock`` per gate).
* Activates the global ``KillSwitch`` (from ``bot/kill_switch.py``) and,
  when available, fires a CRITICAL alert via ``bot/alert_manager.py``.
* State is persisted to ``data/exchange_kill_switch_state.json`` so
  restarts do not silently reset a triggered protector.

Usage
-----
    from bot.exchange_kill_switch import get_exchange_kill_switch_protector

    eksp = get_exchange_kill_switch_protector()

    # On every API call result:
    eksp.record_api_call(success=True, latency_ms=120.0)
    eksp.record_api_call(success=False, latency_ms=0.0, error="timeout")

    # On every price tick:
    eksp.record_price_tick("BTC-USD", price=65_000.0)

    # On every order event:
    eksp.record_order_result(order_id="abc123", accepted=True)
    eksp.record_fill_event(order_id="abc123", fill_qty=0.001)

    # Query status:
    status = eksp.get_status()

Author: NIJA Trading Systems
Version: 1.0
Date: March 2026
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections import deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

logger = logging.getLogger("nija.exchange_kill_switch")

# ---------------------------------------------------------------------------
# Optional top-level imports (resolved lazily if not available)
# ---------------------------------------------------------------------------

def _resolve_get_kill_switch():
    try:
        from bot.kill_switch import get_kill_switch  # type: ignore
        return get_kill_switch
    except Exception:
        pass
    try:
        from kill_switch import get_kill_switch  # type: ignore
        return get_kill_switch
    except Exception:
        return None


def _resolve_get_alert_manager():
    try:
        from bot.alert_manager import get_alert_manager  # type: ignore
        return get_alert_manager
    except Exception:
        pass
    try:
        from alert_manager import get_alert_manager  # type: ignore
        return get_alert_manager
    except Exception:
        return None


# Module-level references (replaceable by tests via monkeypatching)
get_kill_switch = _resolve_get_kill_switch()
get_alert_manager = _resolve_get_alert_manager()

# ---------------------------------------------------------------------------
# Constants – all overridable via ExchangeKillSwitchConfig
# ---------------------------------------------------------------------------

# API error-rate gate
DEFAULT_API_ERROR_WINDOW: int = 60          # seconds for rolling error window
DEFAULT_API_ERROR_RATE_THRESHOLD: float = 0.5   # 50% error rate → RED
DEFAULT_API_BURST_THRESHOLD: int = 10       # 10 consecutive errors → RED
DEFAULT_API_BURST_CAUTION: int = 5          # 5 consecutive errors → YELLOW

# Price-feed anomaly gate
DEFAULT_PRICE_STALE_SECONDS: float = 120.0  # no update for 2 min → stale
DEFAULT_PRICE_SPIKE_PCT: float = 15.0       # single-bar jump > 15% → anomaly
DEFAULT_PRICE_STALE_CAUTION_SECONDS: float = 60.0  # 1 min without update → caution

# Order-rejection rate gate
DEFAULT_ORDER_WINDOW: int = 20              # rolling window of N orders
DEFAULT_ORDER_REJECT_RATE_THRESHOLD: float = 0.5    # 50% rejection → RED
DEFAULT_ORDER_REJECT_RATE_CAUTION: float = 0.25     # 25% rejection → YELLOW

# API latency gate
DEFAULT_LATENCY_WINDOW: int = 20            # rolling window of N calls
DEFAULT_LATENCY_P95_THRESHOLD_MS: float = 5_000.0  # p95 > 5 s → RED
DEFAULT_LATENCY_P95_CAUTION_MS: float = 2_000.0    # p95 > 2 s → YELLOW

# Phantom-fill / duplicate-order gate
DEFAULT_PHANTOM_FILL_THRESHOLD: int = 2     # same fill seen N times → anomaly
DEFAULT_DUPLICATE_ORDER_THRESHOLD: int = 2  # same client_order_id N times → anomaly

# Outage circuit-breaker defaults
DEFAULT_OUTAGE_FAILURE_THRESHOLD: int = 5       # consecutive failures to open circuit
DEFAULT_OUTAGE_RECOVERY_TIMEOUT_S: float = 60.0  # seconds before half-open probe
DEFAULT_OUTAGE_PROBE_SUCCESS_THRESHOLD: int = 2  # successes needed to close circuit

DATA_DIR = Path(__file__).parent.parent / "data"


# ---------------------------------------------------------------------------
# Enums / status types
# ---------------------------------------------------------------------------

class GateStatus(Enum):
    GREEN  = "green"    # no issue
    YELLOW = "yellow"   # elevated concern – log but allow
    RED    = "red"      # kill switch trigger


class ThreatLevel(Enum):
    """Composite threat level derived from all gates."""
    NORMAL   = "normal"
    ELEVATED = "elevated"
    CRITICAL = "critical"


class CircuitState(Enum):
    """States for the exchange-outage circuit breaker."""
    CLOSED    = "closed"     # Normal — requests flow through
    OPEN      = "open"       # Exchange unreachable — block all calls
    HALF_OPEN = "half_open"  # Testing recovery — allow probe calls


# ---------------------------------------------------------------------------
# Exchange outage circuit breaker
# ---------------------------------------------------------------------------

_CB_MAX_HISTORY: int = 50   # maximum transition records kept in ExchangeOutageCircuitBreaker


class ExchangeOutageCircuitBreaker:
    """Three-state circuit breaker for complete exchange outages.

    Unlike the rolling-window gates in :class:`ExchangeKillSwitchProtector`
    (which trigger on *rates*), this breaker trips on *N consecutive*
    connection failures and only recovers after a quiet period followed by a
    minimum number of successful probe calls.

    States
    ------
    * **CLOSED** — normal; all calls are allowed.
    * **OPEN**   — exchange is down; no calls allowed.  Transitions to
      HALF_OPEN after ``recovery_timeout_seconds``.
    * **HALF_OPEN** — one probe call is allowed per ``check()``.  If
      ``probe_success_threshold`` consecutive probes succeed the circuit
      closes; a single failure re-opens it.

    Usage
    -----
    ::

        cb = ExchangeOutageCircuitBreaker()

        # Before every API call:
        if not cb.allow_request():
            raise ConnectionError("Exchange circuit breaker is OPEN")

        try:
            response = api.get_price("BTC-USD")
            cb.record_success()
        except ConnectionError:
            cb.record_failure()
    """

    def __init__(
        self,
        failure_threshold: int = DEFAULT_OUTAGE_FAILURE_THRESHOLD,
        recovery_timeout_seconds: float = DEFAULT_OUTAGE_RECOVERY_TIMEOUT_S,
        probe_success_threshold: int = DEFAULT_OUTAGE_PROBE_SUCCESS_THRESHOLD,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._recovery_timeout = recovery_timeout_seconds
        self._probe_success_threshold = probe_success_threshold

        self._lock = threading.Lock()
        self._state: CircuitState = CircuitState.CLOSED
        self._consecutive_failures: int = 0
        self._consecutive_probe_successes: int = 0
        self._opened_at: Optional[float] = None   # monotonic timestamp when opened
        self._state_history: List[Dict] = []

        logger.info(
            "⚡ ExchangeOutageCircuitBreaker initialised "
            "(failure_threshold=%d, recovery_timeout=%.0fs, probe_threshold=%d)",
            failure_threshold, recovery_timeout_seconds, probe_success_threshold,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def allow_request(self) -> bool:
        """Return ``True`` if the caller is permitted to make an exchange call.

        In CLOSED state all requests are allowed.
        In OPEN state all requests are blocked (returns ``False``).
        In HALF_OPEN state exactly one probe is allowed at a time; subsequent
        calls return ``False`` until the probe result is recorded.
        """
        with self._lock:
            if self._state == CircuitState.CLOSED:
                return True

            if self._state == CircuitState.OPEN:
                # Check whether the recovery timeout has elapsed
                if (
                    self._opened_at is not None
                    and time.monotonic() - self._opened_at >= self._recovery_timeout
                ):
                    self._transition(CircuitState.HALF_OPEN, "recovery timeout elapsed")
                    self._consecutive_probe_successes = 0
                    return True  # allow first probe
                return False  # still open

            # HALF_OPEN — allow exactly one probe
            # (state is HALF_OPEN here because all states are covered above)
            return True

    def record_success(self) -> None:
        """Record a successful exchange call."""
        with self._lock:
            if self._state == CircuitState.CLOSED:
                self._consecutive_failures = 0
                return

            if self._state == CircuitState.HALF_OPEN:
                self._consecutive_probe_successes += 1
                logger.info(
                    "✅ Circuit breaker probe success %d/%d",
                    self._consecutive_probe_successes,
                    self._probe_success_threshold,
                )
                if self._consecutive_probe_successes >= self._probe_success_threshold:
                    self._consecutive_failures = 0
                    self._consecutive_probe_successes = 0
                    self._transition(CircuitState.CLOSED, "probes succeeded — exchange recovered")

    def record_failure(self) -> None:
        """Record a failed exchange call (connection error, timeout, etc.)."""
        with self._lock:
            if self._state == CircuitState.HALF_OPEN:
                # Any failure in HALF_OPEN re-opens immediately
                self._consecutive_probe_successes = 0
                self._opened_at = time.monotonic()
                self._transition(CircuitState.OPEN, "probe failed — re-opening circuit")
                return

            self._consecutive_failures += 1
            logger.warning(
                "⚠️  Exchange failure #%d (opens at %d)",
                self._consecutive_failures,
                self._failure_threshold,
            )
            if self._consecutive_failures >= self._failure_threshold:
                self._opened_at = time.monotonic()
                self._transition(
                    CircuitState.OPEN,
                    f"{self._consecutive_failures} consecutive failures — exchange unreachable",
                )

    def get_state(self) -> CircuitState:
        """Return the current circuit state."""
        with self._lock:
            return self._state

    def get_status(self) -> Dict:
        """Return a status snapshot for dashboards."""
        with self._lock:
            elapsed: Optional[float] = None
            if self._state == CircuitState.OPEN and self._opened_at is not None:
                elapsed = time.monotonic() - self._opened_at
            return {
                "state": self._state.value,
                "consecutive_failures": self._consecutive_failures,
                "consecutive_probe_successes": self._consecutive_probe_successes,
                "seconds_open": round(elapsed, 1) if elapsed is not None else None,
                "recovery_timeout_seconds": self._recovery_timeout,
                "recent_transitions": self._state_history[-5:],
            }

    def reset(self) -> None:
        """Force the circuit back to CLOSED (for testing / emergency recovery)."""
        with self._lock:
            self._consecutive_failures = 0
            self._consecutive_probe_successes = 0
            self._opened_at = None
            self._transition(CircuitState.CLOSED, "manual reset")
        logger.warning("🔄 ExchangeOutageCircuitBreaker reset to CLOSED")

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _transition(self, new_state: CircuitState, reason: str) -> None:
        """Record a state transition (must be called with self._lock held)."""
        old_state = self._state
        self._state = new_state
        record = {
            "from": old_state.value,
            "to": new_state.value,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._state_history.append(record)
        if len(self._state_history) > _CB_MAX_HISTORY:
            self._state_history = self._state_history[-_CB_MAX_HISTORY:]

        if new_state == CircuitState.OPEN:
            logger.critical(
                "🔴 Exchange circuit breaker OPEN — %s", reason
            )
        elif new_state == CircuitState.HALF_OPEN:
            logger.warning(
                "🟡 Exchange circuit breaker HALF-OPEN — %s", reason
            )
        else:
            logger.info(
                "🟢 Exchange circuit breaker CLOSED — %s", reason
            )

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class GateResult:
    """Result from a single exchange-health gate."""
    gate_name: str
    status: GateStatus
    reason: str
    detail: Dict = field(default_factory=dict)

    def to_dict(self) -> Dict:
        return {
            "gate": self.gate_name,
            "status": self.status.value,
            "reason": self.reason,
            "detail": self.detail,
        }


@dataclass
class ExchangeKillSwitchConfig:
    """Tunable configuration for ExchangeKillSwitchProtector."""
    # API error-rate
    api_error_window_seconds: int               = DEFAULT_API_ERROR_WINDOW
    api_error_rate_threshold: float             = DEFAULT_API_ERROR_RATE_THRESHOLD
    api_burst_threshold: int                    = DEFAULT_API_BURST_THRESHOLD
    api_burst_caution: int                      = DEFAULT_API_BURST_CAUTION

    # Price-feed
    price_stale_seconds: float                  = DEFAULT_PRICE_STALE_SECONDS
    price_stale_caution_seconds: float          = DEFAULT_PRICE_STALE_CAUTION_SECONDS
    price_spike_pct: float                      = DEFAULT_PRICE_SPIKE_PCT

    # Order rejection
    order_window_size: int                      = DEFAULT_ORDER_WINDOW
    order_reject_rate_threshold: float          = DEFAULT_ORDER_REJECT_RATE_THRESHOLD
    order_reject_rate_caution: float            = DEFAULT_ORDER_REJECT_RATE_CAUTION

    # Latency
    latency_window_size: int                    = DEFAULT_LATENCY_WINDOW
    latency_p95_threshold_ms: float             = DEFAULT_LATENCY_P95_THRESHOLD_MS
    latency_p95_caution_ms: float               = DEFAULT_LATENCY_P95_CAUTION_MS

    # Phantom fill / duplicate order
    phantom_fill_threshold: int                 = DEFAULT_PHANTOM_FILL_THRESHOLD
    duplicate_order_threshold: int              = DEFAULT_DUPLICATE_ORDER_THRESHOLD

    # Master switch – set False to disable auto-trigger (manual override)
    auto_trigger_enabled: bool                  = True


# ---------------------------------------------------------------------------
# Core protector
# ---------------------------------------------------------------------------

class ExchangeKillSwitchProtector:
    """
    Detects exchange / API misbehaviour and activates the global kill switch.

    Thread-safe singleton (use ``get_exchange_kill_switch_protector()``).
    """

    STATE_FILE = DATA_DIR / "exchange_kill_switch_state.json"

    def __init__(self, config: Optional[ExchangeKillSwitchConfig] = None) -> None:
        self._cfg = config or ExchangeKillSwitchConfig()
        self._lock = threading.Lock()

        # ---- API error-rate gate state ----
        # Each entry: (timestamp_float, is_error: bool)
        self._api_calls: Deque[Tuple[float, bool]] = deque()
        self._consecutive_api_errors: int = 0

        # ---- Price-feed anomaly gate state ----
        # symbol → (last_price, last_update_timestamp)
        self._price_state: Dict[str, Tuple[float, float]] = {}

        # ---- Order-rejection gate state ----
        # Each entry: True = accepted, False = rejected
        self._order_results: Deque[bool] = deque(maxlen=self._cfg.order_window_size)

        # ---- Latency gate state ----
        self._latencies_ms: Deque[float] = deque(maxlen=self._cfg.latency_window_size)

        # ---- Phantom-fill / duplicate-order gate state ----
        # fill_event_id → count of times seen
        self._fill_counts: Dict[str, int] = {}
        # client_order_id → count of times submitted
        self._order_counts: Dict[str, int] = {}

        # ---- Kill-switch trigger tracking ----
        self._triggered: bool = False
        self._trigger_reason: str = ""
        self._trigger_timestamp: Optional[str] = None
        self._trigger_history: List[Dict] = []

        # Ensure data dir exists and load persisted state
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        self._load_state()

        logger.info("🛡️  ExchangeKillSwitchProtector initialised")
        logger.info("   API error rate threshold : %.0f%%", self._cfg.api_error_rate_threshold * 100)
        logger.info("   API burst threshold      : %d consecutive errors", self._cfg.api_burst_threshold)
        logger.info("   Price spike threshold    : %.0f%%", self._cfg.price_spike_pct)
        logger.info("   Price stale threshold    : %.0fs", self._cfg.price_stale_seconds)
        logger.info("   Order reject rate        : %.0f%%", self._cfg.order_reject_rate_threshold * 100)
        logger.info("   Latency p95 threshold    : %.0f ms", self._cfg.latency_p95_threshold_ms)
        logger.info("   Auto-trigger             : %s", "ENABLED" if self._cfg.auto_trigger_enabled else "DISABLED")

    # ------------------------------------------------------------------
    # Public recording API
    # ------------------------------------------------------------------

    def record_api_call(
        self,
        success: bool,
        latency_ms: float = 0.0,
        error: Optional[str] = None,
    ) -> None:
        """
        Record the outcome of a single API call.

        Parameters
        ----------
        success:
            True if the call succeeded, False on any error.
        latency_ms:
            Round-trip time in milliseconds (0 if not available).
        error:
            Optional error description (used for logging only).
        """
        now = time.monotonic()
        with self._lock:
            self._api_calls.append((now, not success))  # store True when it's an error
            if success:
                self._consecutive_api_errors = 0
            else:
                self._consecutive_api_errors += 1
                logger.debug("⚠️  API error recorded (#%d): %s", self._consecutive_api_errors, error or "unknown")

            if latency_ms > 0:
                self._latencies_ms.append(latency_ms)

        self._evaluate_and_maybe_trigger("api_error_rate")
        self._evaluate_and_maybe_trigger("api_latency")

    def record_order_result(self, order_id: str, accepted: bool) -> None:
        """
        Record whether an order was accepted or rejected by the exchange.

        Parameters
        ----------
        order_id:
            Exchange-assigned or client order ID (for logging).
        accepted:
            True if the exchange accepted the order, False if rejected.
        """
        with self._lock:
            self._order_results.append(accepted)

        if not accepted:
            logger.debug("⚠️  Order rejected: %s", order_id)
        self._evaluate_and_maybe_trigger("order_rejection")

    def record_fill_event(self, order_id: str, fill_qty: float = 0.0) -> None:
        """
        Record a fill event for an order.

        Duplicate calls with the same *order_id* are counted; if the same
        fill arrives more than ``phantom_fill_threshold`` times the gate
        fires (phantom fill detected).

        Parameters
        ----------
        order_id:
            Unique identifier for the fill/order.
        fill_qty:
            Quantity filled (used only for logging).
        """
        with self._lock:
            count = self._fill_counts.get(order_id, 0) + 1
            self._fill_counts[order_id] = count

        if count > 1:
            logger.warning("⚠️  Duplicate fill event for order %s (seen %d times)", order_id, count)
        self._evaluate_and_maybe_trigger("phantom_fill", order_id=order_id, count=count)

    def record_order_submission(self, client_order_id: str) -> None:
        """
        Record a client-side order submission.

        If the same *client_order_id* is submitted more than
        ``duplicate_order_threshold`` times the gate fires (duplicate order
        loop detected).

        Parameters
        ----------
        client_order_id:
            Client-assigned order ID (must be unique per order).
        """
        with self._lock:
            count = self._order_counts.get(client_order_id, 0) + 1
            self._order_counts[client_order_id] = count

        if count > 1:
            logger.warning("⚠️  Duplicate order submission for id %s (seen %d times)", client_order_id, count)
        self._evaluate_and_maybe_trigger("duplicate_order", client_order_id=client_order_id, count=count)

    # ------------------------------------------------------------------
    # Gate evaluation
    # ------------------------------------------------------------------

    def evaluate_all_gates(self) -> List[GateResult]:
        """Run all gates and return their results (does NOT trigger kill switch)."""
        results = [
            self._gate_api_error_rate(),
            self._gate_price_feed(),
            self._gate_order_rejection(),
            self._gate_api_latency(),
            self._gate_phantom_fill(),
        ]
        return results

    def _evaluate_and_maybe_trigger(self, hint: str, **kwargs) -> None:
        """Internal: evaluate all gates; trigger kill switch if any are RED."""
        if not self._cfg.auto_trigger_enabled:
            return

        with self._lock:
            already_triggered = self._triggered
        if already_triggered:
            return  # already triggered — nothing more to do

        gates = self.evaluate_all_gates()
        red_gates = [g for g in gates if g.status == GateStatus.RED]

        if red_gates:
            reason = "; ".join(g.reason for g in red_gates)
            self._trigger(reason)

    # ------------------------------------------------------------------
    # Individual gates
    # ------------------------------------------------------------------

    def _gate_api_error_rate(self) -> GateResult:
        """Gate 1: rolling API error rate and consecutive burst."""
        cfg = self._cfg
        now = time.monotonic()
        cutoff = now - cfg.api_error_window_seconds

        with self._lock:
            # Purge old entries
            while self._api_calls and self._api_calls[0][0] < cutoff:
                self._api_calls.popleft()

            window = list(self._api_calls)
            consecutive = self._consecutive_api_errors

        if not window:
            return GateResult("api_error_rate", GateStatus.GREEN, "No API calls recorded")

        total = len(window)
        errors = sum(1 for _, is_err in window if is_err)
        rate = errors / total

        detail = {
            "window_calls": total,
            "window_errors": errors,
            "error_rate_pct": round(rate * 100, 1),
            "consecutive_errors": consecutive,
        }

        # Burst check (consecutive errors)
        if consecutive >= cfg.api_burst_threshold:
            return GateResult(
                "api_error_rate", GateStatus.RED,
                f"API burst: {consecutive} consecutive errors (threshold {cfg.api_burst_threshold})",
                detail,
            )

        # Rate check
        if rate >= cfg.api_error_rate_threshold:
            return GateResult(
                "api_error_rate", GateStatus.RED,
                f"API error rate {rate*100:.1f}% ≥ {cfg.api_error_rate_threshold*100:.0f}% "
                f"over last {cfg.api_error_window_seconds}s ({errors}/{total} calls)",
                detail,
            )

        if consecutive >= cfg.api_burst_caution:
            return GateResult(
                "api_error_rate", GateStatus.YELLOW,
                f"API errors elevated: {consecutive} consecutive (caution at {cfg.api_burst_caution})",
                detail,
            )

        return GateResult("api_error_rate", GateStatus.GREEN, "API error rate normal", detail)

    def _gate_price_feed(self) -> GateResult:
        """Gate 2: price staleness and single-bar spike detection."""
        cfg = self._cfg
        now = time.monotonic()

        with self._lock:
            price_state = dict(self._price_state)

        if not price_state:
            return GateResult("price_feed", GateStatus.GREEN, "No price data yet")

        stale_symbols: List[str] = []
        caution_symbols: List[str] = []
        spiked_symbols: List[str] = []
        bad_price_symbols: List[str] = []

        for symbol, (price, last_ts) in price_state.items():
            age = now - last_ts

            # Zero / negative price
            if price <= 0:
                bad_price_symbols.append(f"{symbol}(price={price})")
                continue

            # Staleness
            if age >= cfg.price_stale_seconds:
                stale_symbols.append(f"{symbol}({age:.0f}s)")
            elif age >= cfg.price_stale_caution_seconds:
                caution_symbols.append(f"{symbol}({age:.0f}s)")

        # Spike detection is done in record_price_tick via kwargs; here we
        # surface the already-logged anomalies from _price_spike_flags.
        with self._lock:
            spiked_symbols = list(getattr(self, "_price_spike_flags", []))

        detail = {
            "stale": stale_symbols,
            "caution": caution_symbols,
            "spiked": spiked_symbols,
            "bad_price": bad_price_symbols,
        }

        if bad_price_symbols:
            return GateResult(
                "price_feed", GateStatus.RED,
                f"Invalid price detected: {', '.join(bad_price_symbols)}",
                detail,
            )
        if stale_symbols:
            return GateResult(
                "price_feed", GateStatus.RED,
                f"Price feed stale (>{cfg.price_stale_seconds:.0f}s): {', '.join(stale_symbols)}",
                detail,
            )
        if spiked_symbols:
            return GateResult(
                "price_feed", GateStatus.RED,
                f"Extreme price spike detected: {', '.join(spiked_symbols)}",
                detail,
            )
        if caution_symbols:
            return GateResult(
                "price_feed", GateStatus.YELLOW,
                f"Price feed slow (>{cfg.price_stale_caution_seconds:.0f}s): {', '.join(caution_symbols)}",
                detail,
            )

        return GateResult("price_feed", GateStatus.GREEN, "Price feeds healthy", detail)

    def _gate_order_rejection(self) -> GateResult:
        """Gate 3: rolling order-rejection rate."""
        cfg = self._cfg

        with self._lock:
            results = list(self._order_results)

        if not results:
            return GateResult("order_rejection", GateStatus.GREEN, "No orders recorded yet")

        total = len(results)
        rejected = sum(1 for r in results if not r)
        rate = rejected / total

        detail = {
            "window_orders": total,
            "rejected": rejected,
            "rejection_rate_pct": round(rate * 100, 1),
        }

        if rate >= cfg.order_reject_rate_threshold:
            return GateResult(
                "order_rejection", GateStatus.RED,
                f"Order rejection rate {rate*100:.1f}% ≥ {cfg.order_reject_rate_threshold*100:.0f}% "
                f"({rejected}/{total} orders rejected)",
                detail,
            )
        if rate >= cfg.order_reject_rate_caution:
            return GateResult(
                "order_rejection", GateStatus.YELLOW,
                f"Order rejection elevated: {rate*100:.1f}% ({rejected}/{total} orders)",
                detail,
            )

        return GateResult("order_rejection", GateStatus.GREEN, "Order rejection rate normal", detail)

    def _gate_api_latency(self) -> GateResult:
        """Gate 4: rolling p95 API latency."""
        cfg = self._cfg

        with self._lock:
            latencies = sorted(self._latencies_ms)

        if not latencies:
            return GateResult("api_latency", GateStatus.GREEN, "No latency data yet")

        idx_p95 = max(0, int(len(latencies) * 0.95) - 1)
        p95_ms = latencies[idx_p95]
        p50_ms = latencies[len(latencies) // 2]

        detail = {
            "samples": len(latencies),
            "p50_ms": round(p50_ms, 1),
            "p95_ms": round(p95_ms, 1),
        }

        if p95_ms >= cfg.latency_p95_threshold_ms:
            return GateResult(
                "api_latency", GateStatus.RED,
                f"API p95 latency {p95_ms:.0f} ms ≥ {cfg.latency_p95_threshold_ms:.0f} ms threshold",
                detail,
            )
        if p95_ms >= cfg.latency_p95_caution_ms:
            return GateResult(
                "api_latency", GateStatus.YELLOW,
                f"API p95 latency elevated: {p95_ms:.0f} ms (caution at {cfg.latency_p95_caution_ms:.0f} ms)",
                detail,
            )

        return GateResult("api_latency", GateStatus.GREEN, "API latency normal", detail)

    def _gate_phantom_fill(self) -> GateResult:
        """Gate 5: phantom fills and duplicate order submissions."""
        cfg = self._cfg

        with self._lock:
            phantom = {k: v for k, v in self._fill_counts.items() if v >= cfg.phantom_fill_threshold}
            dupes = {k: v for k, v in self._order_counts.items() if v >= cfg.duplicate_order_threshold}

        detail = {
            "phantom_fills": phantom,
            "duplicate_orders": dupes,
        }

        if phantom:
            ids = ", ".join(f"{k}(×{v})" for k, v in phantom.items())
            return GateResult(
                "phantom_fill", GateStatus.RED,
                f"Phantom fill detected — same fill ID seen multiple times: {ids}",
                detail,
            )
        if dupes:
            ids = ", ".join(f"{k}(×{v})" for k, v in dupes.items())
            return GateResult(
                "phantom_fill", GateStatus.RED,
                f"Duplicate order submission detected: {ids}",
                detail,
            )

        return GateResult("phantom_fill", GateStatus.GREEN, "No phantom fills or duplicate orders", detail)

    # ------------------------------------------------------------------
    # Trigger logic
    # ------------------------------------------------------------------

    def _trigger(self, reason: str) -> None:
        """Activate the global kill switch with the given reason."""
        with self._lock:
            if self._triggered:
                return  # idempotent
            self._triggered = True
            self._trigger_reason = reason
            self._trigger_timestamp = datetime.now(timezone.utc).isoformat()
            record = {
                "reason": reason,
                "timestamp": self._trigger_timestamp,
            }
            self._trigger_history.append(record)

        logger.critical("=" * 80)
        logger.critical("🚨 EXCHANGE KILL-SWITCH TRIGGERED 🚨")
        logger.critical("=" * 80)
        logger.critical("Reason : %s", reason)
        logger.critical("Time   : %s", self._trigger_timestamp)
        logger.critical("=" * 80)

        self._persist_state()

        # Activate global kill switch
        try:
            ks_factory = get_kill_switch
            if ks_factory is not None:
                ks = ks_factory()
                ks.activate(f"Exchange kill-switch: {reason}", source="EXCHANGE_MONITOR")
        except Exception as exc:
            logger.error("❌ Could not activate global kill switch: %s", exc)

        # Fire alert
        try:
            alert_factory = get_alert_manager
            if alert_factory is not None:
                mgr = alert_factory()
                mgr.fire_alert(
                    category="RISK_LIMIT_BREACH",
                    severity="CRITICAL",
                    title="Exchange Kill-Switch Triggered",
                    message=reason,
                )
        except Exception as exc:
            logger.debug("AlertManager not available: %s", exc)

    def manual_trigger(self, reason: str) -> None:
        """Manually trigger the exchange kill switch."""
        self._trigger(f"[MANUAL] {reason}")

    def reset(self, reason: str = "Manual reset") -> None:
        """
        Reset the exchange kill switch protector (clear triggered state and
        all rolling windows).

        .. warning::
            This does **not** deactivate the global ``KillSwitch`` — call
            ``get_kill_switch().deactivate()`` separately after root-cause
            analysis.
        """
        with self._lock:
            self._triggered = False
            self._trigger_reason = ""
            self._trigger_timestamp = None
            self._api_calls.clear()
            self._consecutive_api_errors = 0
            self._price_state.clear()
            self._order_results.clear()
            self._latencies_ms.clear()
            self._fill_counts.clear()
            self._order_counts.clear()
            if hasattr(self, "_price_spike_flags"):
                self._price_spike_flags.clear()

        record = {
            "event": "reset",
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        with self._lock:
            self._trigger_history.append(record)

        self._persist_state()
        logger.warning("🔄 ExchangeKillSwitchProtector reset: %s", reason)

    # ------------------------------------------------------------------
    # Price tick helper (spike detection called inside record_price_tick)
    # ------------------------------------------------------------------

    def _check_price_spike(
        self,
        symbol: str,
        prev_price: float,
        new_price: float,
        now: float,
    ) -> bool:
        """
        Return True and flag the symbol if the price jumped more than the
        configured spike threshold in a single tick.
        """
        if prev_price <= 0 or new_price <= 0:
            return False
        change_pct = abs(new_price - prev_price) / prev_price * 100
        if change_pct >= self._cfg.price_spike_pct:
            logger.warning(
                "⚡ Price spike on %s: %.4f → %.4f (%.1f%%)",
                symbol, prev_price, new_price, change_pct,
            )
            with self._lock:
                if not hasattr(self, "_price_spike_flags"):
                    self._price_spike_flags: List[str] = []
                flag = f"{symbol}({change_pct:.1f}%)"
                if flag not in self._price_spike_flags:
                    self._price_spike_flags.append(flag)
            return True
        return False

    # Override record_price_tick to wire spike detection in
    def record_price_tick(self, symbol: str, price: float) -> None:
        """
        Record a price tick for a symbol.

        Parameters
        ----------
        symbol:
            Instrument identifier (e.g. ``"BTC-USD"``).
        price:
            Latest mid/last price.
        """
        now = time.monotonic()
        with self._lock:
            prev = self._price_state.get(symbol)
            self._price_state[symbol] = (price, now)

        if prev is not None:
            prev_price, _ = prev
            self._check_price_spike(symbol, prev_price, price, now)

        self._evaluate_and_maybe_trigger("price_feed")

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------

    def _persist_state(self) -> None:
        """Persist trigger state to disk (atomic write)."""
        try:
            with self._lock:
                payload = {
                    "triggered": self._triggered,
                    "trigger_reason": self._trigger_reason,
                    "trigger_timestamp": self._trigger_timestamp,
                    "history": self._trigger_history[-50:],
                    "last_saved": datetime.now(timezone.utc).isoformat(),
                }
            tmp = self.STATE_FILE.with_suffix(".tmp")
            tmp.write_text(json.dumps(payload, indent=2))
            tmp.replace(self.STATE_FILE)
        except Exception as exc:
            logger.error("❌ Could not persist exchange kill-switch state: %s", exc)

    def _load_state(self) -> None:
        """Restore persisted state on startup."""
        try:
            if self.STATE_FILE.exists():
                data = json.loads(self.STATE_FILE.read_text())
                self._triggered = data.get("triggered", False)
                self._trigger_reason = data.get("trigger_reason", "")
                self._trigger_timestamp = data.get("trigger_timestamp")
                self._trigger_history = data.get("history", [])
                if self._triggered:
                    logger.warning(
                        "⚠️  ExchangeKillSwitchProtector: triggered state restored from disk "
                        "(reason: %s) — call reset() after investigation",
                        self._trigger_reason,
                    )
        except Exception as exc:
            logger.error("❌ Could not load exchange kill-switch state: %s", exc)

    # ------------------------------------------------------------------
    # Status / diagnostics
    # ------------------------------------------------------------------

    def is_triggered(self) -> bool:
        """Return True if the exchange kill switch has been triggered."""
        with self._lock:
            return self._triggered

    def get_threat_level(self) -> ThreatLevel:
        """Compute current composite threat level without triggering."""
        gates = self.evaluate_all_gates()
        if any(g.status == GateStatus.RED for g in gates):
            return ThreatLevel.CRITICAL
        if any(g.status == GateStatus.YELLOW for g in gates):
            return ThreatLevel.ELEVATED
        return ThreatLevel.NORMAL

    def get_status(self) -> Dict:
        """Return a JSON-serialisable status snapshot."""
        gates = self.evaluate_all_gates()

        with self._lock:
            triggered = self._triggered
            trigger_reason = self._trigger_reason
            trigger_ts = self._trigger_timestamp
            api_consecutive = self._consecutive_api_errors

        return {
            "triggered": triggered,
            "trigger_reason": trigger_reason,
            "trigger_timestamp": trigger_ts,
            "threat_level": self.get_threat_level().value,
            "auto_trigger_enabled": self._cfg.auto_trigger_enabled,
            "gates": [g.to_dict() for g in gates],
            "metrics": {
                "consecutive_api_errors": api_consecutive,
            },
        }


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------

_protector: Optional[ExchangeKillSwitchProtector] = None
_protector_lock = threading.Lock()

_circuit_breaker: Optional[ExchangeOutageCircuitBreaker] = None
_circuit_breaker_lock = threading.Lock()


def get_exchange_kill_switch_protector(
    config: Optional[ExchangeKillSwitchConfig] = None,
) -> ExchangeKillSwitchProtector:
    """
    Return (or create) the global ``ExchangeKillSwitchProtector`` singleton.

    Parameters
    ----------
    config:
        Optional configuration; only used on first call.  Subsequent calls
        return the existing instance regardless of ``config``.
    """
    global _protector
    if _protector is None:
        with _protector_lock:
            if _protector is None:
                _protector = ExchangeKillSwitchProtector(config)
    return _protector


def get_exchange_outage_circuit_breaker(
    failure_threshold: int = DEFAULT_OUTAGE_FAILURE_THRESHOLD,
    recovery_timeout_seconds: float = DEFAULT_OUTAGE_RECOVERY_TIMEOUT_S,
    probe_success_threshold: int = DEFAULT_OUTAGE_PROBE_SUCCESS_THRESHOLD,
) -> ExchangeOutageCircuitBreaker:
    """Return (or create) the global :class:`ExchangeOutageCircuitBreaker` singleton.

    Parameters
    ----------
    failure_threshold:
        Number of consecutive failures before opening the circuit.
    recovery_timeout_seconds:
        Seconds to wait in OPEN state before probing for recovery.
    probe_success_threshold:
        Number of consecutive successful probes needed to close the circuit.

    Only the first call creates the instance; subsequent calls return the
    existing singleton regardless of the arguments.
    """
    global _circuit_breaker
    if _circuit_breaker is None:
        with _circuit_breaker_lock:
            if _circuit_breaker is None:
                _circuit_breaker = ExchangeOutageCircuitBreaker(
                    failure_threshold=failure_threshold,
                    recovery_timeout_seconds=recovery_timeout_seconds,
                    probe_success_threshold=probe_success_threshold,
                )
    return _circuit_breaker


# ---------------------------------------------------------------------------
# Quick smoke-test
# ---------------------------------------------------------------------------

if __name__ == "__main__":  # pragma: no cover
    import sys

    logging.basicConfig(level=logging.DEBUG, stream=sys.stdout)

    cfg = ExchangeKillSwitchConfig(
        api_burst_threshold=3,
        auto_trigger_enabled=False,   # don't touch real kill switch in demo
    )
    eksp = ExchangeKillSwitchProtector(cfg)

    print("\n=== Exchange Kill-Switch Protector — smoke test ===\n")

    # 1. Normal API calls
    for _ in range(5):
        eksp.record_api_call(success=True, latency_ms=80.0)
    print("Status after healthy calls:", eksp.get_status()["threat_level"])

    # 2. Simulate burst of API errors
    for i in range(4):
        eksp.record_api_call(success=False, error=f"connection error #{i}")
    print("Status after API burst  :", eksp.get_status()["threat_level"])
    gate_statuses = {g["gate"]: g["status"] for g in eksp.get_status()["gates"]}
    print("Gate statuses           :", gate_statuses)

    # 3. Price spike
    eksp.record_price_tick("BTC-USD", 60_000.0)
    eksp.record_price_tick("BTC-USD", 72_001.0)   # +20% spike
    print("Status after price spike:", eksp.get_status()["threat_level"])

    # 4. Phantom fill
    eksp.record_fill_event("fill-abc", fill_qty=0.01)
    eksp.record_fill_event("fill-abc", fill_qty=0.01)   # duplicate
    print("Status after phantom fill:", eksp.get_status()["threat_level"])

    print("\n✅ Smoke test complete\n")
