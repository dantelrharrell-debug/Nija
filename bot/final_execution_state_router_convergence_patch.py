"""Final convergence for execution outcomes, live state, and OKX router identity.

This patch is fail-closed. It does not convert a rejected order into an accepted
order and does not bypass risk, sizing, cash, position, or broker controls.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.final_execution_state_router_convergence")
_MARKER = "20260719-final-execution-state-router-v1"
_LOCK = threading.RLock()
_INSTALLED = False


def _reason_from(value: Any) -> str:
    if isinstance(value, tuple) and len(value) > 1 and value[1]:
        return str(value[1])
    if isinstance(value, dict):
        for key in ("reason", "reject_reason", "error", "message", "detail", "gate"):
            if value.get(key):
                return str(value[key])
    for key in ("last_rejection_reason", "last_reject_reason", "reject_reason", "last_error", "error", "reason"):
        candidate = getattr(value, key, None)
        if candidate:
            return str(candidate)
    return ""


def _deep_reason(owner: Any) -> str:
    for obj in (
        owner,
        getattr(owner, "execution_engine", None),
        getattr(owner, "broker", None),
        getattr(owner, "order_router", None),
        getattr(owner, "risk_manager", None),
        getattr(owner, "trading_strategy", None),
    ):
        if obj is None:
            continue
        reason = _reason_from(obj)
        if reason:
            return reason
    return "terminal_component_returned_false_without_reason"


def _patch_execute_action_class(cls: type) -> bool:
    current = getattr(cls, "execute_action", None)
    if not callable(current) or getattr(current, "_nija_terminal_reason_v1", False):
        return False

    @wraps(current)
    def execute_action(self: Any, *args: Any, **kwargs: Any):
        symbol = kwargs.get("symbol")
        if symbol is None and args:
            analysis = args[0]
            symbol = getattr(analysis, "symbol", None) or (analysis.get("symbol") if isinstance(analysis, dict) else None)
        try:
            result = current(self, *args, **kwargs)
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            setattr(self, "_nija_last_execution_rejection", reason)
            logger.exception("EXECUTION_TERMINAL_EXCEPTION marker=%s symbol=%s reason=%s", _MARKER, symbol, reason)
            raise
        if result is False:
            reason = _deep_reason(self)
            setattr(self, "_nija_last_execution_rejection", reason)
            os.environ["NIJA_LAST_EXECUTION_REJECTION"] = reason[:500]
            logger.critical(
                "EXECUTION_TERMINAL_REJECTED marker=%s symbol=%s reason=%s owner=%s",
                _MARKER, symbol or "unknown", reason, cls.__name__,
            )
        elif result:
            setattr(self, "_nija_last_execution_rejection", "")
            logger.critical("EXECUTION_TERMINAL_ACCEPTED marker=%s symbol=%s owner=%s", _MARKER, symbol or "unknown", cls.__name__)
        return result

    execute_action._nija_terminal_reason_v1 = True  # type: ignore[attr-defined]
    execute_action.__wrapped__ = current  # type: ignore[attr-defined]
    cls.execute_action = execute_action
    return True


def _patch_execution_modules() -> bool:
    patched = False
    names = (
        "bot.nija_apex_strategy_v71", "nija_apex_strategy_v71",
        "bot.trading_strategy", "trading_strategy",
        "bot.execution_engine", "execution_engine",
        "bot.core_loop", "core_loop",
    )
    for name in names:
        try:
            module = importlib.import_module(name)
        except Exception:
            continue
        for attr in dir(module):
            obj = getattr(module, attr, None)
            if isinstance(obj, type):
                patched = _patch_execute_action_class(obj) or patched
    return patched


def _runtime_live() -> bool:
    heartbeat = os.getenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "0") == "1"
    authority = os.getenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "false").lower() in {"1", "true", "yes", "on"}
    lifecycle = os.getenv("NIJA_LIFECYCLE_STATE", "").upper() in {"LIVE", "LIVE_ACTIVE", "RUNNING"}
    kill = os.getenv("NIJA_KILL_SWITCH", "false").lower() in {"1", "true", "yes", "on"}
    return heartbeat and authority and not kill and lifecycle


def _patch_startup_state() -> bool:
    patched = False
    for name in ("bot.startup_coordinator", "startup_coordinator"):
        try:
            module = importlib.import_module(name)
        except Exception:
            continue
        for method_name in ("reconcile", "_reconcile", "build_snapshot", "_build_snapshot"):
            current = getattr(module, method_name, None)
            if not callable(current) or getattr(current, "_nija_live_monotonic_v1", False):
                continue

            @wraps(current)
            def wrapper(*args: Any, __current=current, __name=method_name, **kwargs: Any):
                result = __current(*args, **kwargs)
                if _runtime_live():
                    if isinstance(result, dict):
                        state = str(result.get("trading_state", result.get("state", ""))).upper()
                        if state in {"", "UNKNOWN", "PENDING", "STARTING"}:
                            result["trading_state"] = "LIVE_ACTIVE"
                            result["state"] = "LIVE_ACTIVE"
                            result["state_repair_reason"] = "monotonic_live_runtime_evidence"
                            logger.critical("STARTUP_STATE_MONOTONIC_LIVE_REPAIRED marker=%s method=%s previous=%s", _MARKER, __name, state)
                    os.environ["NIJA_TRADING_STATE"] = "LIVE_ACTIVE"
                return result

            wrapper._nija_live_monotonic_v1 = True  # type: ignore[attr-defined]
            wrapper.__wrapped__ = current  # type: ignore[attr-defined]
            setattr(module, method_name, wrapper)
            patched = True
    return patched


def _patch_okx_router_identity() -> bool:
    bridge_names = ("bot.okx_final_order_submission_bridge_patch", "okx_final_order_submission_bridge_patch")
    router_names = ("bot.multi_broker_execution_router", "multi_broker_execution_router")
    bridges: list[ModuleType] = []
    routers: list[ModuleType] = []
    for name in bridge_names:
        try:
            module = importlib.import_module(name)
            if module not in bridges:
                bridges.append(module)
        except Exception:
            pass
    for name in router_names:
        try:
            module = importlib.import_module(name)
            if module not in routers:
                routers.append(module)
        except Exception:
            pass
    patched = False
    for bridge in bridges:
        patcher = getattr(bridge, "_patch_router_module", None)
        if not callable(patcher):
            continue
        for router in routers:
            patcher(router)
        patched = bool(getattr(bridge, "_ROUTER_PATCHED", False)) or patched
    if patched:
        os.environ["NIJA_OKX_ROUTER_PATCHED"] = "1"
        logger.critical("OKX_ROUTER_MODULE_IDENTITY_CONVERGED marker=%s bridges=%s routers=%s", _MARKER, [m.__name__ for m in bridges], [m.__name__ for m in routers])
    else:
        logger.error("OKX_ROUTER_MODULE_IDENTITY_PENDING marker=%s bridges=%s routers=%s", _MARKER, [m.__name__ for m in bridges], [m.__name__ for m in routers])
    return patched


def _watchdog() -> None:
    for _ in range(600):
        try:
            execution = _patch_execution_modules()
            startup = _patch_startup_state()
            okx = _patch_okx_router_identity()
            if execution and startup and okx:
                logger.critical("FINAL_EXECUTION_STATE_ROUTER_READY marker=%s execution=true startup=true okx=true", _MARKER)
                return
        except Exception:
            logger.exception("FINAL_EXECUTION_STATE_ROUTER_RETRY marker=%s", _MARKER)
        time.sleep(0.2)
    logger.error("FINAL_EXECUTION_STATE_ROUTER_WATCHDOG_EXHAUSTED marker=%s", _MARKER)


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        if _INSTALLED:
            return True
        _patch_execution_modules()
        _patch_startup_state()
        _patch_okx_router_identity()
        threading.Thread(target=_watchdog, name="FinalExecutionStateRouter", daemon=True).start()
        os.environ["NIJA_FINAL_EXECUTION_STATE_ROUTER_INSTALLED"] = "1"
        _INSTALLED = True
        logger.critical("FINAL_EXECUTION_STATE_ROUTER_INSTALLED marker=%s", _MARKER)
        return True


__all__ = ["install"]
