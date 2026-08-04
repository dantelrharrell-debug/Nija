"""Runtime convergence for broker reconnect, Kraken recovery, and capital readiness.

This module is installed by the canonical launcher before application imports. It
adds only fail-closed, idempotent coordination:

* prevents nested ConnectionStabilityManager reconnect calls;
* deduplicates reconnect hooks and preserves the original reconnect callable;
* arms the existing writer-scoped Kraken authenticated recovery after authority;
* requests a canonical capital refresh after broker recovery; and
* re-evaluates activation/readiness after a fresh snapshot is published.

It does not synthesize balances, bypass authentication, force LIVE_ACTIVE, or
submit orders.
"""
from __future__ import annotations

import importlib
import importlib.abc
import importlib.machinery
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Callable, Optional

LOGGER = logging.getLogger("nija.runtime_execution_convergence")
MARKER = "20260727-runtime-execution-convergence-v32"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_TARGETS = {
    "bot.connection_stability_manager",
    "connection_stability_manager",
    "bot.bot_main",
}
_LOCK = threading.RLock()
_INSTALLED = False
_MONITOR_STARTED = False
_PATCHED_MODULES: set[int] = set()


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in _TRUE


def _writer_ready() -> bool:
    token = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "").strip()
    generation = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or "").strip()
    lease = _truthy("NIJA_WRITER_LEASE_ACQUIRED") or _truthy(
        "NIJA_PREBOT_WRITER_AUTHORITY_READY"
    )
    heartbeat_active = _truthy("NIJA_WRITER_HEARTBEAT_ACTIVE")
    core_alive = _truthy("NIJA_CORE_THREAD_ALIVE")
    if token and generation and lease and heartbeat_active and core_alive:
        return True
    return bool(
        generation
        and lease
        and heartbeat_active
        and (
            core_alive
            or str(os.environ.get("NIJA_RUNTIME_TRADING_STATE", "") or "").strip().upper()
            == "LIVE_PENDING_CONFIRMATION"
        )
    )


def _unwrap_callable(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Return the deepest non-cyclic wrapped callable."""
    current = fn
    seen: set[int] = set()
    while callable(current) and id(current) not in seen:
        seen.add(id(current))
        wrapped = getattr(current, "__wrapped__", None)
        if not callable(wrapped):
            break
        current = wrapped
    return current


def _call_first(module: ModuleType, names: tuple[str, ...]) -> bool:
    for name in names:
        fn = getattr(module, name, None)
        if callable(fn):
            try:
                fn()
                return True
            except TypeError:
                continue
            except Exception as exc:
                LOGGER.warning(
                    "RUNTIME_REEVALUATION_CALL_FAILED marker=%s function=%s error=%s:%s",
                    MARKER,
                    name,
                    type(exc).__name__,
                    exc,
                )
                return False
    return False


def _request_runtime_reconciliation(trigger: str) -> bool:
    """Refresh canonical capital and re-evaluate readiness without bypasses."""
    if not _writer_ready():
        return False
    refreshed = False
    try:
        manager_module = importlib.import_module("bot.multi_account_broker_manager")
        manager = manager_module.get_broker_manager()
        refresh = getattr(manager, "refresh_capital_authority", None)
        if callable(refresh):
            try:
                refresh(trigger=trigger)
            except TypeError:
                refresh()
            refreshed = True
            LOGGER.warning(
                "CAPITAL_REFRESH_REQUESTED marker=%s trigger=%s",
                MARKER,
                trigger,
            )
    except Exception as exc:
        LOGGER.warning(
            "CAPITAL_REFRESH_DEFERRED marker=%s trigger=%s error=%s:%s",
            MARKER,
            trigger,
            type(exc).__name__,
            exc,
        )
        return False

    try:
        state_module = importlib.import_module("bot.trading_state_machine")
        getter = getattr(state_module, "get_state_machine", None)
        state_machine = getter() if callable(getter) else None
        maybe_activate = getattr(state_machine, "maybe_auto_activate", None)
        if callable(maybe_activate):
            maybe_activate()
    except Exception as exc:
        LOGGER.warning(
            "ACTIVATION_REEVALUATION_DEFERRED marker=%s error=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )

    try:
        readiness = importlib.import_module("three_venue_execution_readiness")
        _call_first(
            readiness,
            (
                "refresh_execution_readiness",
                "evaluate_execution_readiness",
                "run_readiness_check",
                "check_readiness",
            ),
        )
    except Exception:
        pass
    return refreshed


def _arm_kraken_recovery() -> bool:
    if not _writer_ready():
        return False
    candidates = (
        "nija_canonical_broker_startup_convergence_v24_prebot",
        "bot.canonical_broker_startup_convergence_v24",
    )
    for name in candidates:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            try:
                module = importlib.import_module(name)
            except Exception:
                continue
        starter = getattr(module, "_start_kraken_recovery_coordinator", None)
        if callable(starter):
            try:
                result = bool(starter())
                if result:
                    LOGGER.warning(
                        "KRAKEN_RECOVERY_COORDINATOR_ARMED marker=%s source=%s",
                        MARKER,
                        name,
                    )
                return result
            except Exception as exc:
                LOGGER.warning(
                    "KRAKEN_RECOVERY_COORDINATOR_DEFERRED marker=%s error=%s:%s",
                    MARKER,
                    type(exc).__name__,
                    exc,
                )
                return False
    return False


def _patch_connection_stability(module: ModuleType) -> bool:
    cls = getattr(module, "ConnectionStabilityManager", None)
    if not isinstance(cls, type) or getattr(cls, "_nija_runtime_convergence_v32", False):
        return False

    original_register = cls.register_broker
    original_attempt = cls._attempt_reconnect
    original_pre_hook = cls.register_pre_reconnect_hook
    original_post_hook = cls.register_reconnect_hook

    @wraps(original_register)
    def register_broker(self: Any, broker: Any, reconnect_fn: Callable[[], bool], *args: Any, **kwargs: Any):
        base = _unwrap_callable(reconnect_fn)
        if getattr(self, "_nija_original_reconnect_fn", None) is None:
            self._nija_original_reconnect_fn = base
        else:
            base = self._nija_original_reconnect_fn
        return original_register(self, broker, base, *args, **kwargs)

    def _dedupe_hook(self: Any, attr: str, hook: Callable[[], None], registrar: Callable[..., Any]):
        key = (getattr(hook, "__module__", ""), getattr(hook, "__qualname__", repr(hook)))
        seen = getattr(self, attr, None)
        if seen is None:
            seen = set()
            setattr(self, attr, seen)
        if key in seen:
            return None
        seen.add(key)
        return registrar(self, hook)

    @wraps(original_pre_hook)
    def register_pre_reconnect_hook(self: Any, hook: Callable[[], None]):
        return _dedupe_hook(self, "_nija_pre_reconnect_hook_keys", hook, original_pre_hook)

    @wraps(original_post_hook)
    def register_reconnect_hook(self: Any, hook: Callable[[], None]):
        return _dedupe_hook(self, "_nija_post_reconnect_hook_keys", hook, original_post_hook)

    @wraps(original_attempt)
    def attempt_reconnect(self: Any) -> bool:
        guard = getattr(self, "_nija_reconnect_guard", None)
        if guard is None:
            guard = threading.Lock()
            self._nija_reconnect_guard = guard
        if not guard.acquire(blocking=False):
            LOGGER.warning(
                "RECONNECT_REENTRY_BLOCKED marker=%s broker=%s",
                MARKER,
                getattr(self, "broker_name", "unknown"),
            )
            return False
        try:
            result = bool(original_attempt(self))
            if result:
                _request_runtime_reconciliation(
                    f"{getattr(self, 'broker_name', 'broker')}_reconnect_success"
                )
            return result
        finally:
            guard.release()

    cls.register_broker = register_broker
    cls.register_pre_reconnect_hook = register_pre_reconnect_hook
    cls.register_reconnect_hook = register_reconnect_hook
    cls._attempt_reconnect = attempt_reconnect
    cls._nija_runtime_convergence_v32 = True
    LOGGER.critical(
        "CONNECTION_STABILITY_REENTRANCY_PATCHED marker=%s module=%s",
        MARKER,
        module.__name__,
    )
    return True


def _patch_bot_main(module: ModuleType) -> bool:
    name = "_acquire_writer_authority_before_nonce"
    original = getattr(module, name, None)
    if not callable(original) or getattr(original, "_nija_runtime_convergence_v32", False):
        return False

    @wraps(original)
    def acquire(*args: Any, **kwargs: Any) -> bool:
        acquired = bool(original(*args, **kwargs))
        if acquired:
            _arm_kraken_recovery()
            _start_monitor()
            _request_runtime_reconciliation("writer_authority_acquired")
        return acquired

    acquire._nija_runtime_convergence_v32 = True
    setattr(module, name, acquire)
    LOGGER.critical(
        "WRITER_POST_ACQUIRE_CONVERGENCE_PATCHED marker=%s module=%s",
        MARKER,
        module.__name__,
    )
    return True


def _patch_module(module: ModuleType) -> None:
    if id(module) in _PATCHED_MODULES:
        return
    if module.__name__.endswith("connection_stability_manager"):
        _patch_connection_stability(module)
    elif module.__name__ == "bot.bot_main":
        _patch_bot_main(module)
    _PATCHED_MODULES.add(id(module))


class _Loader(importlib.abc.Loader):
    def __init__(self, wrapped: importlib.abc.Loader) -> None:
        self._wrapped = wrapped

    def create_module(self, spec):
        creator = getattr(self._wrapped, "create_module", None)
        return creator(spec) if callable(creator) else None

    def exec_module(self, module: ModuleType) -> None:
        self._wrapped.exec_module(module)
        _patch_module(module)


class _Finder(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname: str, path: Optional[list[str]], target=None):
        if fullname not in _TARGETS:
            return None
        spec = importlib.machinery.PathFinder.find_spec(fullname, path)
        if spec is None or spec.loader is None or isinstance(spec.loader, _Loader):
            return spec
        spec.loader = _Loader(spec.loader)
        return spec


def _monitor() -> None:
    last_kraken_ready = False
    while True:
        try:
            if _writer_ready():
                _arm_kraken_recovery()
                kraken_ready = _truthy("NIJA_KRAKEN_AUTHENTICATED_RECOVERY_READY")
                trigger = "kraken_recovery_ready" if kraken_ready and not last_kraken_ready else "periodic_runtime_convergence"
                _request_runtime_reconciliation(trigger)
                last_kraken_ready = kraken_ready
        except Exception as exc:
            LOGGER.warning(
                "RUNTIME_CONVERGENCE_MONITOR_ERROR marker=%s error=%s:%s",
                MARKER,
                type(exc).__name__,
                exc,
            )
        time.sleep(max(10.0, float(os.environ.get("NIJA_RUNTIME_CONVERGENCE_INTERVAL_S", "30") or 30)))


def _start_monitor() -> bool:
    global _MONITOR_STARTED
    with _LOCK:
        if _MONITOR_STARTED:
            return True
        thread = threading.Thread(target=_monitor, name="RuntimeExecutionConvergenceV32", daemon=True)
        thread.start()
        _MONITOR_STARTED = True
    LOGGER.warning(
        "RUNTIME_EXECUTION_CONVERGENCE_MONITOR_STARTED marker=%s thread_alive=%s",
        MARKER,
        thread.is_alive(),
    )
    return thread.is_alive()


def install_import_hook() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return True
        for name in _TARGETS:
            module = sys.modules.get(name)
            if isinstance(module, ModuleType):
                _patch_module(module)
        if not any(isinstance(item, _Finder) for item in sys.meta_path):
            sys.meta_path.insert(0, _Finder())
        _INSTALLED = True
    os.environ["NIJA_RUNTIME_EXECUTION_CONVERGENCE_V32_INSTALLED"] = "1"
    LOGGER.critical("RUNTIME_EXECUTION_CONVERGENCE_INSTALLED marker=%s", MARKER)
    return True


install = install_import_hook
