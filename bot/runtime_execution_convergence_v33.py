"""Runtime execution convergence v33.

Fixes the bound-method regression in v32 reconnect registration and closes the
timing gap that can leave configured Kraken recovery unarmed after writer
lineage becomes available. All behavior remains fail-closed: this module never
synthesizes credentials, clears nonce quarantine, forces readiness, or submits
orders.
"""
from __future__ import annotations

import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_execution_convergence_v33")
MARKER = "20260727-runtime-execution-convergence-v33"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_V32_TARGETS = (
    "nija_runtime_execution_convergence_v32_prebot",
    "bot.runtime_execution_convergence_v32",
)
_V24_TARGETS = (
    "nija_canonical_broker_startup_convergence_v24_prebot",
    "bot.canonical_broker_startup_convergence_v24",
)
_LOCK = threading.RLock()
_MONITOR_STARTED = False


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in _TRUE


def _writer_ready() -> bool:
    token = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "").strip()
    generation = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or "").strip()
    lease = _truthy("NIJA_WRITER_LEASE_ACQUIRED") or _truthy(
        "NIJA_PREBOT_WRITER_AUTHORITY_READY"
    )
    return bool(token and generation and lease)


def _kraken_configured() -> bool:
    key = str(
        os.environ.get("KRAKEN_PLATFORM_API_KEY")
        or os.environ.get("KRAKEN_API_KEY")
        or ""
    ).strip()
    secret = str(
        os.environ.get("KRAKEN_PLATFORM_API_SECRET")
        or os.environ.get("KRAKEN_API_SECRET")
        or ""
    ).strip()
    disabled = _truthy("NIJA_DISABLE_KRAKEN") or _truthy(
        "KRAKEN_EXECUTION_DISABLED"
    )
    return bool(key and secret and not disabled)


def _bound_safe_unwrap(fn: Callable[..., Any]) -> Callable[..., Any]:
    """Unwrap decorators without discarding a bound method's instance."""
    bound_self = getattr(fn, "__self__", None)
    current: Callable[..., Any] = fn
    seen: set[int] = set()
    while callable(current) and id(current) not in seen:
        seen.add(id(current))
        wrapped = getattr(current, "__wrapped__", None)
        if not callable(wrapped):
            break
        current = wrapped
    if bound_self is not None and getattr(current, "__self__", None) is None:
        descriptor = getattr(current, "__get__", None)
        if callable(descriptor):
            rebound = descriptor(bound_self, type(bound_self))
            if callable(rebound):
                current = rebound
    return current


def _patch_v32() -> bool:
    patched = False
    for name in _V32_TARGETS:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        setattr(module, "_unwrap_callable", _bound_safe_unwrap)
        setattr(module, "BOUND_METHOD_HOTFIX_MARKER", MARKER)
        patched = True
    return patched


def _arm_kraken_recovery() -> bool:
    if _truthy("NIJA_KRAKEN_RECOVERY_V33_ARMED"):
        return True
    if not _writer_ready() or not _kraken_configured():
        return False
    for name in _V24_TARGETS:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        starter = getattr(module, "_start_kraken_recovery_coordinator", None)
        if not callable(starter):
            continue
        try:
            armed = bool(starter())
        except Exception as exc:
            LOGGER.error(
                "KRAKEN_RECOVERY_V33_ARM_FAILED marker=%s source=%s error=%s:%s",
                MARKER,
                name,
                type(exc).__name__,
                exc,
            )
            return False
        if armed:
            os.environ["NIJA_KRAKEN_RECOVERY_V33_ARMED"] = "1"
            LOGGER.critical(
                "KRAKEN_RECOVERY_V33_ARMED marker=%s source=%s writer_ready=true credentials_present=true",
                MARKER,
                name,
            )
            return True
    return False


def _monitor() -> None:
    last_state = ""
    while True:
        try:
            _patch_v32()
            if _writer_ready() and _kraken_configured() and not _truthy(
                "NIJA_KRAKEN_RECOVERY_V33_ARMED"
            ):
                _arm_kraken_recovery()
            state = (
                f"writer={int(_writer_ready())};"
                f"configured={int(_kraken_configured())};"
                f"armed={os.environ.get('NIJA_KRAKEN_RECOVERY_V33_ARMED', '0')}"
            )
            if state != last_state:
                LOGGER.warning(
                    "RUNTIME_EXECUTION_CONVERGENCE_V33_STATE marker=%s %s",
                    MARKER,
                    state,
                )
                last_state = state
        except Exception as exc:
            LOGGER.error(
                "RUNTIME_EXECUTION_CONVERGENCE_V33_MONITOR_ERROR marker=%s error=%s:%s",
                MARKER,
                type(exc).__name__,
                exc,
            )
        time.sleep(max(5.0, float(os.environ.get("NIJA_RUNTIME_V33_INTERVAL_S", "10") or 10)))


def _start_monitor() -> bool:
    global _MONITOR_STARTED
    with _LOCK:
        if _MONITOR_STARTED:
            return True
        thread = threading.Thread(
            target=_monitor,
            name="RuntimeExecutionConvergenceV33",
            daemon=True,
        )
        thread.start()
        _MONITOR_STARTED = True
    return thread.is_alive()


def install() -> bool:
    if not _patch_v32():
        LOGGER.critical(
            "RUNTIME_EXECUTION_CONVERGENCE_V33_DEFERRED marker=%s reason=v32_not_loaded",
            MARKER,
        )
        return False
    if not _start_monitor():
        return False
    os.environ["NIJA_RUNTIME_EXECUTION_CONVERGENCE_V33_INSTALLED"] = "1"
    LOGGER.critical(
        "RUNTIME_EXECUTION_CONVERGENCE_V33_INSTALLED marker=%s bound_method_preserved=true kraken_handoff_monitor=true",
        MARKER,
    )
    return True


install_import_hook = install
