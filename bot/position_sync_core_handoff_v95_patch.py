"""Bound startup position synchronization without weakening activation safety.

Production deployment 8e4ba829 showed capital and writer convergence succeeding,
then the process remained in THREADS_STARTING with no registered core. The last
forward-progress message was EXCHANGE_POSITION_SYNC starting with three connected
platform brokers and no subsequent per-broker completion. The historical startup
hook performs that reconciliation synchronously inside refresh_capital_authority
and may pre-latch _startup_position_sync_done before broker.get_positions returns.

v95 repairs the liveness/safety split:
* broker get_positions calls are bounded single-flight operations; a timed-out
  request stays in one daemon worker and later callers reuse that same flight;
* a timeout raises TimeoutError so startup_position_sync never interprets it as
  a valid empty position snapshot;
* the manager's _startup_position_sync_done flag is recomputed from the actual
  _startup_position_sync_adopted state of every connected broker;
* v61 activation remains fail closed until every currently connected broker has
  completed a real position snapshot.

No readiness key, writer/nonce authority, kill switch, risk gate, or execution
permission is synthesized by this patch.
"""
from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Callable

LOGGER = logging.getLogger("nija.position_sync_core_handoff_v95")
MARKER = "20260814-position-sync-core-handoff-v95"
_LOCK = threading.RLock()
_HOOK_FLAG = "_NIJA_POSITION_SYNC_CORE_HANDOFF_V95_IMPORT_HOOK"
_GET_POSITIONS_ATTR = "_nija_position_sync_core_handoff_v95"
_REFRESH_ATTR = "_nija_position_sync_core_handoff_v95"
_V61_ATTR = "_nija_position_sync_core_handoff_v95"
_FLIGHTS: dict[int, dict[str, Any]] = {}


def _timeout_s() -> float:
    try:
        return max(0.1, float(os.environ.get("NIJA_POSITION_FETCH_TIMEOUT_S", "5") or 5.0))
    except (TypeError, ValueError):
        return 5.0


def _connected_brokers(manager: Any) -> dict[str, Any]:
    brokers: dict[str, Any] = {}
    try:
        platform = getattr(manager, "platform_brokers", {}) or {}
        if callable(platform):
            platform = platform()
        for broker_type, broker in dict(platform or {}).items():
            if broker is None or not bool(getattr(broker, "connected", False)):
                continue
            name = str(getattr(broker_type, "value", broker_type) or "unknown").lower()
            brokers[f"platform:{name}"] = broker
    except Exception:
        pass

    try:
        users = getattr(manager, "user_brokers", {}) or {}
        for user_id, mapping in dict(users or {}).items():
            for broker_type, broker in dict(mapping or {}).items():
                if broker is None or not bool(getattr(broker, "connected", False)):
                    continue
                name = str(getattr(broker_type, "value", broker_type) or "unknown").lower()
                brokers[f"user:{user_id}:{name}"] = broker
    except Exception:
        pass
    return brokers


def position_sync_status(manager: Any) -> tuple[bool, list[str], dict[str, bool]]:
    brokers = _connected_brokers(manager)
    status = {
        name: bool(getattr(broker, "_startup_position_sync_adopted", False))
        for name, broker in brokers.items()
    }
    pending = sorted(name for name, synced in status.items() if not synced)
    return not pending, pending, status


def _finish_flight(key: int, flight: dict[str, Any], method: Callable[..., Any], self: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> None:
    try:
        flight["result"] = method(self, *args, **kwargs)
    except BaseException as exc:
        flight["error"] = exc
    finally:
        flight["finished_at"] = time.monotonic()
        flight["event"].set()


def _bounded_get_positions(method: Callable[..., Any], broker_name: str) -> Callable[..., Any]:
    @wraps(method)
    def get_positions_v95(self: Any, *args: Any, **kwargs: Any):
        key = id(self)
        with _LOCK:
            flight = _FLIGHTS.get(key)
            if flight is None:
                event = threading.Event()
                flight = {
                    "event": event,
                    "result": None,
                    "error": None,
                    "started_at": time.monotonic(),
                    "finished_at": 0.0,
                    "broker_name": broker_name,
                }
                _FLIGHTS[key] = flight
                thread = threading.Thread(
                    target=_finish_flight,
                    args=(key, flight, method, self, args, dict(kwargs)),
                    name=f"position-fetch-v95-{broker_name}",
                    daemon=True,
                )
                flight["thread"] = thread
                thread.start()
                started_new = True
            else:
                started_new = False

        timeout = _timeout_s()
        if not flight["event"].wait(timeout=timeout):
            age = max(0.0, time.monotonic() - float(flight.get("started_at", 0.0) or 0.0))
            LOGGER.critical(
                "POSITION_FETCH_V95_TIMEOUT marker=%s broker=%s timeout_s=%.2f age_s=%.2f "
                "single_flight_reused=%s synthetic_empty_snapshot=false",
                MARKER,
                broker_name,
                timeout,
                age,
                str(not started_new).lower(),
            )
            raise TimeoutError(
                f"position snapshot timed out for {broker_name} after {timeout:.2f}s"
            )

        error = flight.get("error")
        result = flight.get("result")
        with _LOCK:
            if _FLIGHTS.get(key) is flight:
                _FLIGHTS.pop(key, None)
        if error is not None:
            raise error
        return result

    setattr(get_positions_v95, _GET_POSITIONS_ATTR, True)
    setattr(get_positions_v95, "__wrapped__", method)
    return get_positions_v95


def _patch_broker_manager(module: ModuleType) -> bool:
    changed = False
    for class_name in ("CoinbaseBroker", "KrakenBroker", "OKXBroker", "AlpacaBroker"):
        cls = getattr(module, class_name, None)
        if not isinstance(cls, type):
            continue
        current = getattr(cls, "get_positions", None)
        if not callable(current):
            continue
        if getattr(current, _GET_POSITIONS_ATTR, False):
            continue
        cls.get_positions = _bounded_get_positions(current, class_name.replace("Broker", "").lower())
        changed = True
        LOGGER.critical(
            "POSITION_FETCH_V95_BROKER_PATCHED marker=%s broker_class=%s timeout_s=%.2f",
            MARKER,
            class_name,
            _timeout_s(),
        )
    return changed


def _patch_mabm(module: ModuleType) -> bool:
    cls = getattr(module, "MultiAccountBrokerManager", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "refresh_capital_authority", None)
    if not callable(current):
        return False
    if getattr(current, _REFRESH_ATTR, False):
        return True

    @wraps(current)
    def refresh_capital_authority_v95(self: Any, *args: Any, **kwargs: Any):
        result = current(self, *args, **kwargs)
        ready, pending, status = position_sync_status(self)
        setattr(self, "_startup_position_sync_done", bool(ready))
        os.environ["NIJA_POSITION_SYNC_ACTIVATION_READY"] = "1" if ready else "0"
        if pending:
            LOGGER.warning(
                "POSITION_SYNC_V95_PENDING marker=%s pending=%s status=%s activation_blocked=true",
                MARKER,
                pending,
                status,
            )
        return result

    setattr(refresh_capital_authority_v95, _REFRESH_ATTR, True)
    setattr(refresh_capital_authority_v95, "__wrapped__", current)
    cls.refresh_capital_authority = refresh_capital_authority_v95
    LOGGER.critical(
        "POSITION_SYNC_V95_MABM_PATCHED marker=%s false_pre_latch_corrected=true",
        MARKER,
    )
    return True


def _canonical_manager() -> Any:
    for name in ("bot.multi_account_broker_manager", "multi_account_broker_manager"):
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        getter = getattr(module, "get_broker_manager", None)
        if callable(getter):
            try:
                manager = getter()
                if manager is not None:
                    return manager
            except Exception:
                pass
        manager = getattr(module, "multi_account_broker_manager", None)
        if manager is not None:
            return manager
    return None


def _patch_v61(module: ModuleType) -> bool:
    current = getattr(module, "_activation_prerequisites", None)
    if not callable(current):
        return False
    if getattr(current, _V61_ATTR, False):
        return True

    @wraps(current)
    def activation_prerequisites_v95():
        ready, blockers, details = current()
        if not ready:
            return ready, blockers, details

        manager = _canonical_manager()
        if manager is None:
            details = dict(details or {})
            details["position_sync"] = {"ready": False, "reason": "manager_unavailable"}
            os.environ["NIJA_POSITION_SYNC_ACTIVATION_READY"] = "0"
            return False, ["position_sync.manager_unavailable"], details

        sync_ready, pending, status = position_sync_status(manager)
        details = dict(details or {})
        details["position_sync"] = {
            "ready": sync_ready,
            "pending": pending,
            "status": status,
        }
        os.environ["NIJA_POSITION_SYNC_ACTIVATION_READY"] = "1" if sync_ready else "0"
        if not sync_ready:
            LOGGER.warning(
                "POSITION_SYNC_V95_ACTIVATION_BLOCK marker=%s pending=%s status=%s trading_fail_closed=true",
                MARKER,
                pending,
                status,
            )
            return False, [f"position_sync:{name}" for name in pending], details
        return True, [], details

    setattr(activation_prerequisites_v95, _V61_ATTR, True)
    setattr(activation_prerequisites_v95, "__wrapped__", current)
    module._activation_prerequisites = activation_prerequisites_v95
    LOGGER.critical(
        "POSITION_SYNC_V95_ACTIVATION_GUARD_PATCHED marker=%s all_connected_brokers_require_snapshot=true",
        MARKER,
    )
    return True


def _patch_loaded() -> bool:
    changed = False
    seen: set[int] = set()
    for name in ("bot.broker_manager", "broker_manager"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            changed = _patch_broker_manager(module) or changed
    for name in ("bot.multi_account_broker_manager", "multi_account_broker_manager"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            changed = _patch_mabm(module) or changed
    for name in ("bot.final_production_activation_repair_v61_patch", "final_production_activation_repair_v61_patch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            changed = _patch_v61(module) or changed
    return changed


def install_import_hook() -> bool:
    with _LOCK:
        _patch_loaded()
        if not getattr(builtins, _HOOK_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                text = str(name or "")
                if any(token in text for token in (
                    "broker_manager",
                    "multi_account_broker_manager",
                    "final_production_activation_repair_v61_patch",
                )):
                    _patch_loaded()
                return result

            builtins.__import__ = importing
            setattr(builtins, _HOOK_FLAG, True)

        os.environ["NIJA_POSITION_SYNC_CORE_HANDOFF_V95_INSTALLED"] = "1"
        LOGGER.critical(
            "POSITION_SYNC_CORE_HANDOFF_V95_INSTALLED marker=%s position_fetch_timeout_s=%.2f "
            "synthetic_empty_snapshot=false activation_requires_position_sync=true",
            MARKER,
            _timeout_s(),
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "position_sync_status",
    "_bounded_get_positions",
    "_patch_broker_manager",
    "_patch_mabm",
    "_patch_v61",
]
