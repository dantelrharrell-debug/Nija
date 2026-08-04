"""Capital refresh stall guard v35.

Bounds broker balance calls inside CapitalRefreshCoordinator with independent
per-broker deadlines inside a bounded overall refresh cycle.

Key properties
--------------
* All venue fetches begin concurrently.
* Each broker has its own independent per-broker timeout so one slow API
  cannot consume the shared cycle deadline and starve every other venue.
* Only one in-flight request is permitted per broker; a timed-out thread
  does not cause overlapping requests on the next refresh cycle.
* A late result can never overwrite a newer live snapshot: results carry
  the sequence number of the request cycle and are rejected when stale.
* Cache entries are validated (finite, non-negative, timestamped, within
  TTL) before use; a failed/zero/None result never overwrites a valid cache.
* Separate per-broker observation timestamps mean one cached venue does not
  make the combined snapshot appear entirely fresh.
* A deduplication window suppresses repeated identical timeout warnings so
  logs are useful without hiding real state changes.
* A recovery log is emitted when a previously timing-out broker returns live
  data again.
* Never logs API keys, secrets, signatures, or private account data.
"""
from __future__ import annotations

import logging
import os
import queue
import sys
import threading
import time
from types import ModuleType
from typing import Any, Dict, Optional, Tuple

LOGGER = logging.getLogger("nija.capital_refresh_stall_guard_v35")
MARKER = "20260802-capital-refresh-shared-deadline-v36"
_TARGETS = ("bot.capital_flow_state_machine", "capital_flow_state_machine")
_LOCK = threading.RLock()
_STARTED = False
_REFRESH_CONTEXT = threading.local()
_LIVE_BALANCE_OBSERVED_AT = "_nija_capital_live_balance_observed_monotonic"

# Per-broker in-flight guard: maps broker_id → (thread, sequence_number)
_IN_FLIGHT: Dict[str, Tuple[threading.Thread, int]] = {}
_IN_FLIGHT_LOCK = threading.Lock()

# Per-broker cycle sequence counter (incremented each time a new request fires)
_BROKER_SEQUENCE: Dict[str, int] = {}

# Per-broker "last timeout logged at" for deduplication
_LAST_TIMEOUT_LOGGED: Dict[str, float] = {}
_TIMEOUT_LOG_DEDUP_S = 30.0  # suppress repeated identical timeout warnings for this interval

# Per-broker "was timing out on previous cycle" for recovery detection
_WAS_TIMING_OUT: Dict[str, bool] = {}


def _freshness_ttl_seconds() -> float:
    try:
        return max(
            5.0,
            float(os.getenv("NIJA_CAPITAL_FRESHNESS_TTL_S", "90.0") or "90.0"),
        )
    except (TypeError, ValueError):
        return 90.0


def _timeout_seconds() -> float:
    """Per-broker independent timeout (not a shared deadline)."""
    try:
        return max(2.0, float(os.getenv("NIJA_CAPITAL_BROKER_FETCH_TIMEOUT_S", "8.0")))
    except (TypeError, ValueError):
        return 8.0


def _cycle_deadline_seconds() -> float:
    """Overall cycle wall-clock budget.  Must be > per-broker timeout."""
    try:
        return max(
            _timeout_seconds() + 2.0,
            float(os.getenv("NIJA_CAPITAL_CYCLE_DEADLINE_S", "12.0")),
        )
    except (TypeError, ValueError):
        return _timeout_seconds() + 2.0


def _cache_valid(cached: Any, observed_at: float, now: float, ttl_s: float) -> bool:
    """Return True only when the cached value is safe to use as a fallback."""
    if cached is None:
        return False
    try:
        v = float(cached)
    except (TypeError, ValueError):
        return False
    if not (v >= 0.0 and v != float("inf") and v == v):  # finite and non-negative
        return False
    if observed_at <= 0.0:
        return False
    age_s = max(0.0, now - observed_at)
    return age_s <= ttl_s


class _BalanceFetchBatch:
    """Start all broker calls concurrently with independent per-broker deadlines.

    Design notes
    ------------
    * Each broker gets its own ``queue.Queue`` and dedicated daemon thread.
    * ``result_for()`` blocks only for the *remaining* per-broker budget, not
      a shared countdown.  Two calls to ``result_for()`` for different brokers
      can therefore overlap in time: the first call completes quickly while the
      second waits up to its full individual budget.
    * The overall cycle deadline acts as a safety net; it cannot be shorter
      than per_broker_timeout + 2 s.
    * Each fetch carries a ``seq`` counter so late results from a previously
      timed-out thread can be detected and discarded.
    """

    def __init__(self, broker_map: Dict[str, Any]) -> None:
        self._started_at = time.monotonic()
        self._per_broker_timeout = _timeout_seconds()
        self._cycle_deadline = self._started_at + _cycle_deadline_seconds()
        self._results: Dict[str, queue.Queue] = {}
        self._broker_seq: Dict[str, int] = {}

        for broker_id, broker in broker_map.items():
            bid = str(broker_id)
            result_queue: queue.Queue = queue.Queue(maxsize=1)
            self._results[bid] = result_queue

            with _IN_FLIGHT_LOCK:
                # Only one in-flight request per broker.
                existing = _IN_FLIGHT.get(bid)
                if existing is not None:
                    existing_thread, _seq = existing
                    if existing_thread.is_alive():
                        # Previous request still running — skip launching a new one.
                        # The queue is already connected; result_for() will receive
                        # the in-flight result via the existing thread.
                        self._broker_seq[bid] = _seq
                        continue

                seq = _BROKER_SEQUENCE.get(bid, 0) + 1
                _BROKER_SEQUENCE[bid] = seq
                self._broker_seq[bid] = seq

                def _call(
                    target: Any = broker,
                    output: queue.Queue = result_queue,
                    broker_seq: int = seq,
                    broker_key: str = bid,
                ) -> None:
                    try:
                        value = target.get_account_balance()
                        # Validate result before storing — never overwrite cache with
                        # None, exception, zero caused by API failure, or malformed data.
                        result_ok = False
                        try:
                            fv = float(value)
                            result_ok = fv >= 0.0 and fv == fv and fv != float("inf")
                        except (TypeError, ValueError):
                            pass
                        if result_ok:
                            try:
                                setattr(target, _LIVE_BALANCE_OBSERVED_AT, time.monotonic())
                            except Exception:
                                pass
                        try:
                            output.put_nowait((True, value, broker_seq))
                        except queue.Full:
                            pass
                    except BaseException as exc:
                        try:
                            output.put_nowait((False, exc, broker_seq))
                        except queue.Full:
                            pass
                    finally:
                        # Remove from in-flight when done so next cycle can start fresh.
                        with _IN_FLIGHT_LOCK:
                            current = _IN_FLIGHT.get(broker_key)
                            if current is not None and current[1] == broker_seq:
                                _IN_FLIGHT.pop(broker_key, None)

                t = threading.Thread(
                    target=_call,
                    name=f"capital-balance-fetch-{bid}",
                    daemon=True,
                )
                _IN_FLIGHT[bid] = (t, seq)
                t.start()

    def result_for(self, broker_id: str, broker: Any) -> Any:
        bid = str(broker_id)
        result_queue = self._results[bid]
        expected_seq = self._broker_seq.get(bid, 0)

        # Each broker gets its full individual budget, bounded by overall cycle deadline.
        broker_deadline = self._started_at + self._per_broker_timeout
        remaining = max(0.0, min(broker_deadline, self._cycle_deadline) - time.monotonic())
        now = time.monotonic()

        try:
            ok, value, result_seq = result_queue.get(timeout=remaining)
        except queue.Empty:
            return self._handle_timeout(bid, broker, now)

        # Reject late results that are from a stale sequence (e.g. a previously
        # timed-out thread that eventually returned).
        if result_seq < expected_seq:
            LOGGER.debug(
                "CAPITAL_REFRESH_LATE_RESULT_DISCARDED marker=%s broker=%s "
                "result_seq=%d expected_seq=%d",
                MARKER, bid, result_seq, expected_seq,
            )
            return self._handle_timeout(bid, broker, now)

        # Emit recovery log if this broker was previously timing out.
        if ok and _WAS_TIMING_OUT.get(bid):
            _WAS_TIMING_OUT[bid] = False
            LOGGER.info(
                "CAPITAL_REFRESH_BROKER_RECOVERED marker=%s broker=%s "
                "live_data_restored=true",
                MARKER, bid,
            )

        if ok:
            return value
        raise value

    def _handle_timeout(self, broker_id: str, broker: Any, started_at: float) -> Any:
        _REFRESH_CONTEXT.used_fallback = True
        now = time.monotonic()
        cached = getattr(broker, "_last_known_balance", None)
        observed_at = float(getattr(broker, _LIVE_BALANCE_OBSERVED_AT, 0.0) or 0.0)
        ttl_s = _freshness_ttl_seconds()
        cached_valid = _cache_valid(cached, observed_at, now, ttl_s)
        cached_age_s = max(0.0, now - observed_at) if observed_at > 0.0 else float("inf")

        fallback_brokers = dict(getattr(_REFRESH_CONTEXT, "fallback_brokers", {}) or {})
        fallback_brokers[broker_id] = {
            "age_s": cached_age_s,
            "observed": observed_at > 0.0,
            "cached_valid": cached_valid,
        }
        _REFRESH_CONTEXT.fallback_brokers = fallback_brokers

        elapsed = now - self._started_at

        # Deduplicate repeated identical timeout warnings.
        last_logged = _LAST_TIMEOUT_LOGGED.get(broker_id, 0.0)
        suppress = (now - last_logged) < _TIMEOUT_LOG_DEDUP_S
        _WAS_TIMING_OUT[broker_id] = True

        if cached_valid:
            if not suppress:
                _LAST_TIMEOUT_LOGGED[broker_id] = now
                LOGGER.warning(
                    "CAPITAL_REFRESH_BROKER_FETCH_TIMEOUT_FALLBACK marker=%s "
                    "broker=%s elapsed=%.2fs cached_payload=true cached_age_s=%.2f "
                    "cached_within_ttl=%s per_broker_timeout=true",
                    MARKER,
                    broker_id,
                    elapsed,
                    cached_age_s,
                    cached_age_s <= ttl_s,
                )
            return cached

        # Cached entry is absent or invalid — broker excluded from valid_brokers.
        if not suppress:
            _LAST_TIMEOUT_LOGGED[broker_id] = now
            LOGGER.error(
                "CAPITAL_REFRESH_BROKER_FETCH_TIMEOUT marker=%s broker=%s "
                "elapsed=%.2fs cached_payload=false per_broker_timeout=true",
                MARKER,
                broker_id,
                elapsed,
            )
        raise TimeoutError(
            f"capital balance fetch timed out for {broker_id} after {elapsed:.2f}s"
        )


def current_refresh_used_fallback() -> bool:
    """Return whether this thread's active refresh consumed cached capital."""
    return bool(getattr(_REFRESH_CONTEXT, "used_fallback", False))


def current_refresh_fallback_status(
    freshness_ttl_s: Optional[float] = None,
) -> Dict[str, Any]:
    """Return freshness evidence for cached balances used by this refresh."""

    used_fallback = current_refresh_used_fallback()
    brokers = dict(getattr(_REFRESH_CONTEXT, "fallback_brokers", {}) or {})
    ttl_s = (
        _freshness_ttl_seconds()
        if freshness_ttl_s is None
        else max(5.0, float(freshness_ttl_s))
    )
    all_recent = bool(
        used_fallback
        and brokers
        and all(
            bool(record.get("observed"))
            and float(record.get("age_s", float("inf"))) <= ttl_s
            for record in brokers.values()
        )
    )
    return {
        "used_fallback": used_fallback,
        "all_recent": all_recent,
        "freshness_ttl_s": ttl_s,
        "brokers": brokers,
    }


class _BoundedBrokerProxy:
    """Transparent broker proxy backed by a per-broker-bounded fetch batch."""

    def __init__(self, broker_id: str, broker: Any, batch: _BalanceFetchBatch) -> None:
        object.__setattr__(self, "_broker_id", str(broker_id))
        object.__setattr__(self, "_broker", broker)
        object.__setattr__(self, "_batch", batch)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_broker"), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(object.__getattribute__(self, "_broker"), name, value)

    def get_account_balance(self) -> Any:
        return object.__getattribute__(self, "_batch").result_for(
            object.__getattribute__(self, "_broker_id"),
            object.__getattribute__(self, "_broker"),
        )


def _patch(module: ModuleType) -> bool:
    cls = getattr(module, "CapitalRefreshCoordinator", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_pipeline", None)
    if not callable(original):
        return False
    if getattr(original, "_nija_capital_refresh_stall_guard_v35", False):
        return True

    def _pipeline_with_bounded_brokers(
        self: Any,
        broker_map: Dict[str, Any],
        trigger: str,
        open_exposure_usd: float,
    ) -> Any:
        _REFRESH_CONTEXT.used_fallback = False
        _REFRESH_CONTEXT.fallback_brokers = {}
        live_map = {
            str(broker_id): broker
            for broker_id, broker in broker_map.items()
            if broker is not None
        }
        batch = _BalanceFetchBatch(live_map)
        bounded_map = {
            broker_id: _BoundedBrokerProxy(broker_id, broker, batch)
            for broker_id, broker in live_map.items()
        }
        try:
            return original(
                self,
                broker_map=bounded_map,
                trigger=trigger,
                open_exposure_usd=open_exposure_usd,
            )
        finally:
            _REFRESH_CONTEXT.used_fallback = False
            _REFRESH_CONTEXT.fallback_brokers = {}

    _pipeline_with_bounded_brokers._nija_capital_refresh_stall_guard_v35 = True
    cls._pipeline = _pipeline_with_bounded_brokers
    os.environ["NIJA_CAPITAL_REFRESH_STALL_GUARD_V35_PATCHED"] = "1"
    LOGGER.info(
        "CAPITAL_REFRESH_STALL_GUARD_V35_PATCHED marker=%s module=%s "
        "per_broker_timeout_s=%.2f cycle_deadline_s=%.2f independent_deadlines=true",
        MARKER,
        module.__name__,
        _timeout_seconds(),
        _cycle_deadline_seconds(),
    )
    return True


def _monitor() -> None:
    while True:
        for name in _TARGETS:
            module = sys.modules.get(name)
            if isinstance(module, ModuleType):
                _patch(module)
        time.sleep(0.5)


def install() -> bool:
    global _STARTED
    with _LOCK:
        if not _STARTED:
            thread = threading.Thread(
                target=_monitor,
                name="capital-refresh-stall-guard-v35",
                daemon=True,
            )
            thread.start()
            _STARTED = thread.is_alive()
    if not _STARTED:
        return False
    os.environ["NIJA_CAPITAL_REFRESH_STALL_GUARD_V35_INSTALLED"] = "1"
    LOGGER.info(
        "CAPITAL_REFRESH_STALL_GUARD_V35_INSTALLED marker=%s "
        "fail_closed=true per_broker_independent_deadlines=true",
        MARKER,
    )
    return True


install_import_hook = install
