from __future__ import annotations

import builtins
import logging
import os
import sys
import time
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.execution_entry_timeout_guard")

_MARKER = "EXECUTION_ENTRY_TIMEOUT_GUARD_PATCHED marker=20260709ae"
_IMPORT_FLAG = "_NIJA_EXECUTION_ENTRY_TIMEOUT_GUARD_IMPORT_HOOK_20260709AE"
_WRAP_ATTR = "_nija_execution_entry_timeout_guard_20260709ae"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)) or default)
    except Exception:
        return default


def _derived_timeout_s() -> float:
    ack_timeout = max(1.0, _float_env("NIJA_ACK_TIMEOUT_S", 30.0))
    return max(40.0, ack_timeout + 10.0)


def _timeout_s() -> float:
    floor = _derived_timeout_s()
    try:
        raw = os.environ.get("NIJA_EXECUTION_ENTRY_TIMEOUT_SECONDS")
        if raw not in (None, ""):
            requested = max(5.0, float(raw or "0"))
            return max(requested, floor)
    except Exception:
        pass
    return floor


def _symbol_from(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    return str(kwargs.get("symbol") or (args[0] if len(args) > 0 else "") or "").upper().replace("/", "-")


def _side_from(args: tuple[Any, ...], kwargs: dict[str, Any]) -> str:
    return str(kwargs.get("side") or (args[1] if len(args) > 1 else "") or "")


def _size_from(args: tuple[Any, ...], kwargs: dict[str, Any]) -> float:
    for value in (
        kwargs.get("position_size"),
        kwargs.get("size_usd"),
        kwargs.get("notional_usd"),
        args[2] if len(args) > 2 else None,
    ):
        try:
            amount = float(value)
            if amount > 0:
                return amount
        except Exception:
            continue
    return 0.0


def _patch_module(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "execute_entry", None)
    if not callable(original) or getattr(original, _WRAP_ATTR, False):
        return bool(getattr(original, _WRAP_ATTR, False))

    @wraps(original)
    def execute_entry(self: Any, *args: Any, **kwargs: Any):
        if not _truthy("NIJA_EXECUTION_ENTRY_TIMEOUT_GUARD_ENABLED", "true"):
            return original(self, *args, **kwargs)

        # Do not move live execution into a daemon thread. Context variables that
        # carry dispatch authority are thread-local, and Python cannot safely cancel
        # a timed-out worker. The former implementation returned while the worker
        # could still submit an order, creating orphaned and duplicate executions.
        timeout = _timeout_s()
        symbol = _symbol_from(args, kwargs)
        side = _side_from(args, kwargs)
        size = _size_from(args, kwargs)
        started = time.monotonic()
        try:
            result = original(self, *args, **kwargs)
        except BaseException:
            logger.exception(
                "EXECUTION_ENTRY_INLINE_EXCEPTION marker=20260709ae symbol=%s side=%s size_usd=%.2f",
                symbol,
                side,
                size,
            )
            raise

        elapsed = time.monotonic() - started
        if elapsed > timeout:
            logger.critical(
                "EXECUTION_ENTRY_SLOW_COMPLETION marker=20260709ae symbol=%s side=%s size_usd=%.2f "
                "elapsed_s=%.1f threshold_s=%.1f action=completed_inline_no_orphan_no_retry",
                symbol,
                side,
                size,
                elapsed,
                timeout,
            )
            print(
                f"[NIJA-PRINT] EXECUTION_ENTRY_SLOW_COMPLETION marker=20260709ae "
                f"symbol={symbol} side={side} size=${size:.2f} elapsed_s={elapsed:.1f}",
                flush=True,
            )
        return result

    setattr(execute_entry, _WRAP_ATTR, True)
    setattr(cls, "execute_entry", execute_entry)
    logger.warning(
        "%s class=ExecutionEngine mode=inline_context_preserving threshold_s=%.1f ack_timeout_s=%.1f",
        _MARKER,
        _timeout_s(),
        _float_env("NIJA_ACK_TIMEOUT_S", 30.0),
    )
    print("[NIJA-PRINT] EXECUTION_ENTRY_TIMEOUT_GUARD_PATCHED marker=20260709ae mode=inline_context_preserving", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.execution_engine", "execution_engine"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                patched = _patch_module(module) or patched
            except Exception:
                continue
    return patched


def _install_context_integrity_repair() -> None:
    module_names = (
        "broker_scoped_hardening_repair_patch",
        "execution_route_context_integrity_patch",
        "dispatch_scope_bridge_safety_patch",
    )
    for short_name in module_names:
        installed = False
        for name in (f"bot.{short_name}", short_name):
            try:
                module = __import__(name, fromlist=["*"])
                installer = getattr(module, "install_import_hook", None)
                if callable(installer):
                    installer()
                installed = True
                break
            except Exception:
                continue
        if not installed:
            logger.warning(
                "EXECUTION_CONTEXT_INTEGRITY_REPAIR_IMPORT_FAILED marker=20260709at module=%s",
                short_name,
            )


def install_import_hook() -> None:
    os.environ.setdefault("NIJA_EXECUTION_ENTRY_TIMEOUT_GUARD_ENABLED", "true")
    _try_patch_loaded()
    _install_context_integrity_repair()
    if getattr(builtins, _IMPORT_FLAG, False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("execution_engine") or "execution_engine" in str(name):
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("EXECUTION_ENTRY_TIMEOUT_GUARD_IMPORT_FAILED marker=20260709ae name=%s err=%s", name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, _IMPORT_FLAG, True)
    logger.warning(
        "EXECUTION_ENTRY_TIMEOUT_GUARD_IMPORT_HOOK marker=20260709ae installed=true mode=inline_context_preserving threshold_s=%.1f",
        _timeout_s(),
    )


def install() -> None:
    install_import_hook()
