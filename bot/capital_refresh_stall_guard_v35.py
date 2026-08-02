"""Capital refresh stall guard v35.

Bounds broker balance calls only inside CapitalRefreshCoordinator. All venue
fetches begin together and share one deadline, so a stalled API cannot multiply
the refresh timeout by the number of brokers. On timeout, an already-hydrated
broker balance is reused; without a cached payload the coordinator records that
venue as unavailable and continues fail-closed with the remaining venues.
"""
from __future__ import annotations

import logging
import os
import queue
import sys
import threading
import time
from types import ModuleType
from typing import Any, Dict

LOGGER = logging.getLogger("nija.capital_refresh_stall_guard_v35")
MARKER = "20260802-capital-refresh-shared-deadline-v36"
_TARGETS = ("bot.capital_flow_state_machine", "capital_flow_state_machine")
_LOCK = threading.RLock()
_STARTED = False
_REFRESH_CONTEXT = threading.local()
_LIVE_BALANCE_OBSERVED_AT = "_nija_capital_live_balance_observed_monotonic"


def _freshness_ttl_seconds() -> float:
    try:
        return max(
            5.0,
            float(os.getenv("NIJA_CAPITAL_FRESHNESS_TTL_S", "90.0") or "90.0"),
        )
    except (TypeError, ValueError):
        return 90.0


def _timeout_seconds() -> float:
    try:
        return max(2.0, float(os.getenv("NIJA_CAPITAL_BROKER_FETCH_TIMEOUT_S", "8.0")))
    except (TypeError, ValueError):
        return 8.0


class _BalanceFetchBatch:
    """Start all broker calls together and enforce one shared deadline."""

    def __init__(self, broker_map: Dict[str, Any]) -> None:
        self._started_at = time.monotonic()
        self._deadline = self._started_at + _timeout_seconds()
        self._results: Dict[str, "queue.Queue[tuple[bool, Any]]"] = {}
        for broker_id, broker in broker_map.items():
            result_queue: "queue.Queue[tuple[bool, Any]]" = queue.Queue(maxsize=1)
            self._results[broker_id] = result_queue

            def _call(
                target: Any = broker,
                output: "queue.Queue[tuple[bool, Any]]" = result_queue,
            ) -> None:
                try:
                    value = target.get_account_balance()
                    try:
                        setattr(target, _LIVE_BALANCE_OBSERVED_AT, time.monotonic())
                    except Exception:
                        pass
                    output.put_nowait((True, value))
                except BaseException as exc:  # preserve broker exception semantics
                    try:
                        output.put_nowait((False, exc))
                    except queue.Full:
                        pass

            threading.Thread(
                target=_call,
                name=f"capital-balance-fetch-{broker_id}",
                daemon=True,
            ).start()

    def result_for(self, broker_id: str, broker: Any) -> Any:
        result_queue = self._results[broker_id]
        remaining = max(0.0, self._deadline - time.monotonic())
        try:
            ok, value = result_queue.get(timeout=remaining)
        except queue.Empty:
            _REFRESH_CONTEXT.used_fallback = True
            cached = getattr(broker, "_last_known_balance", None)
            now = time.monotonic()
            observed_at = float(
                getattr(broker, _LIVE_BALANCE_OBSERVED_AT, 0.0) or 0.0
            )
            cached_age_s = (
                max(0.0, now - observed_at)
                if observed_at > 0.0
                else float("inf")
            )
            fallback_brokers = dict(
                getattr(_REFRESH_CONTEXT, "fallback_brokers", {}) or {}
            )
            fallback_brokers[str(broker_id)] = {
                "age_s": cached_age_s,
                "observed": observed_at > 0.0,
            }
            _REFRESH_CONTEXT.fallback_brokers = fallback_brokers
            elapsed = now - self._started_at
            if cached is not None:
                LOGGER.warning(
                    "CAPITAL_REFRESH_BROKER_FETCH_TIMEOUT_FALLBACK marker=%s "
                    "broker=%s elapsed=%.2fs cached_payload=true cached_age_s=%.2f "
                    "cached_within_ttl=%s shared_deadline=true",
                    MARKER,
                    broker_id,
                    elapsed,
                    cached_age_s,
                    cached_age_s <= _freshness_ttl_seconds(),
                )
                return cached
            LOGGER.error(
                "CAPITAL_REFRESH_BROKER_FETCH_TIMEOUT marker=%s broker=%s "
                "elapsed=%.2fs cached_payload=false shared_deadline=true",
                MARKER,
                broker_id,
                elapsed,
            )
            raise TimeoutError(
                f"capital balance fetch timed out for {broker_id} after {elapsed:.2f}s"
            )
        if ok:
            return value
        raise value


def current_refresh_used_fallback() -> bool:
    """Return whether this thread's active refresh consumed cached capital."""
    return bool(getattr(_REFRESH_CONTEXT, "used_fallback", False))


def current_refresh_fallback_status(
    freshness_ttl_s: float | None = None,
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
    """Transparent broker proxy backed by a shared balance-fetch batch."""

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
    LOGGER.critical(
        "CAPITAL_REFRESH_STALL_GUARD_V35_PATCHED marker=%s module=%s "
        "timeout_s=%.2f shared_deadline=true",
        MARKER,
        module.__name__,
        _timeout_seconds(),
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
    LOGGER.critical(
        "CAPITAL_REFRESH_STALL_GUARD_V35_INSTALLED marker=%s "
        "fail_closed=true shared_deadline=true",
        MARKER,
    )
    return True


install_import_hook = install
