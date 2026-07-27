"""Capital refresh stall guard v35.

Bounds broker balance calls only inside CapitalRefreshCoordinator. A broker API
call that stalls cannot leave the bootstrap FSM permanently in
REFRESH_IN_FLIGHT. On timeout, an already-hydrated broker balance is reused;
without a cached payload the coordinator records that venue as unavailable and
continues fail-closed with the remaining venues.
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
MARKER = "20260727-capital-refresh-stall-guard-v35"
_TARGETS = ("bot.capital_flow_state_machine", "capital_flow_state_machine")
_LOCK = threading.RLock()
_STARTED = False


def _timeout_seconds() -> float:
    try:
        return max(2.0, float(os.getenv("NIJA_CAPITAL_BROKER_FETCH_TIMEOUT_S", "8.0")))
    except (TypeError, ValueError):
        return 8.0


class _BoundedBrokerProxy:
    """Transparent broker proxy with a bounded get_account_balance call."""

    def __init__(self, broker_id: str, broker: Any) -> None:
        object.__setattr__(self, "_broker_id", str(broker_id))
        object.__setattr__(self, "_broker", broker)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_broker"), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(object.__getattribute__(self, "_broker"), name, value)

    def get_account_balance(self) -> Any:
        broker = object.__getattribute__(self, "_broker")
        broker_id = object.__getattribute__(self, "_broker_id")
        result_queue: "queue.Queue[tuple[bool, Any]]" = queue.Queue(maxsize=1)

        def _call() -> None:
            try:
                result_queue.put_nowait((True, broker.get_account_balance()))
            except BaseException as exc:  # preserve broker exception semantics
                try:
                    result_queue.put_nowait((False, exc))
                except queue.Full:
                    pass

        worker = threading.Thread(
            target=_call,
            name=f"capital-balance-fetch-{broker_id}",
            daemon=True,
        )
        started_at = time.monotonic()
        worker.start()
        try:
            ok, value = result_queue.get(timeout=_timeout_seconds())
        except queue.Empty:
            cached = getattr(broker, "_last_known_balance", None)
            elapsed = time.monotonic() - started_at
            if cached is not None:
                LOGGER.error(
                    "CAPITAL_REFRESH_BROKER_FETCH_TIMEOUT_FALLBACK marker=%s "
                    "broker=%s elapsed=%.2fs cached_payload=true",
                    MARKER,
                    broker_id,
                    elapsed,
                )
                return cached
            LOGGER.error(
                "CAPITAL_REFRESH_BROKER_FETCH_TIMEOUT marker=%s broker=%s "
                "elapsed=%.2fs cached_payload=false",
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
        bounded_map = {
            str(broker_id): _BoundedBrokerProxy(str(broker_id), broker)
            for broker_id, broker in broker_map.items()
            if broker is not None
        }
        return original(
            self,
            broker_map=bounded_map,
            trigger=trigger,
            open_exposure_usd=open_exposure_usd,
        )

    _pipeline_with_bounded_brokers._nija_capital_refresh_stall_guard_v35 = True
    cls._pipeline = _pipeline_with_bounded_brokers
    os.environ["NIJA_CAPITAL_REFRESH_STALL_GUARD_V35_PATCHED"] = "1"
    LOGGER.critical(
        "CAPITAL_REFRESH_STALL_GUARD_V35_PATCHED marker=%s module=%s timeout_s=%.2f",
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
        "CAPITAL_REFRESH_STALL_GUARD_V35_INSTALLED marker=%s fail_closed=true",
        MARKER,
    )
    return True


install_import_hook = install
