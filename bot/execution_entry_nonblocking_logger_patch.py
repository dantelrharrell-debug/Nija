"""Prevent execute_entry from stalling on synchronous logger handlers.

This patch wraps ExecutionEngine.execute_entry() and temporarily swaps that
module's logger for a print-only logger while the original method runs. It does
not bypass any trading gate. It only makes logging non-blocking for this critical
entry section so bootstrap/capital/edge/ECEL/risk/broker checks can proceed and
remain visible through `[NIJA-PRINT] EXECUTION_ENTRY_LOG ...` markers.

It also requests the execution entry timeout guard so a non-returning downstream
entry call is reported and the live loop can continue safely.
"""

from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.execution_entry_nonblocking_logger")
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_PATCHED = False
_MONITOR_STARTED = False
_INSTALL_LOCK = threading.Lock()
_TRUTHY = {"1", "true", "yes", "enabled", "on", "y"}
_PATCHED_CLASS_IDS: set[int] = set()
_PATCHED_MODULE_NAMES: set[str] = set()
_TIMEOUT_CHAIN_REQUESTED = False


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUTHY


def _request_timeout_guard() -> None:
    global _TIMEOUT_CHAIN_REQUESTED
    if _TIMEOUT_CHAIN_REQUESTED:
        return
    os.environ.setdefault("NIJA_EXECUTION_ENTRY_TIMEOUT_GUARD_ENABLED", "true")
    os.environ.setdefault("NIJA_EXECUTION_ENTRY_TIMEOUT_SECONDS", "25")
    try:
        mod = importlib.import_module("bot.execution_entry_timeout_guard_patch")
        installer = getattr(mod, "install_import_hook", None)
        if callable(installer):
            installer()
            _TIMEOUT_CHAIN_REQUESTED = True
            logger.warning("EXECUTION_ENTRY_TIMEOUT_GUARD_CHAIN_REQUESTED")
    except Exception as exc:
        logger.warning("EXECUTION_ENTRY_TIMEOUT_GUARD_CHAIN_UNAVAILABLE err=%s", exc)


class _SafeExecutionEntryLogger:
    """Minimal logger facade that cannot block on external logging handlers."""

    def __init__(self, original: Any) -> None:
        self._original = original
        self.name = getattr(original, "name", "nija.execution")

    def _emit(self, level: str, msg: Any, *args: Any, **kwargs: Any) -> None:
        try:
            if args:
                try:
                    text = str(msg) % args
                except Exception:
                    text = " ".join([str(msg), *(str(arg) for arg in args)])
            else:
                text = str(msg)
            print(f"[NIJA-PRINT] EXECUTION_ENTRY_LOG | level={level} message={text}", flush=True)
        except Exception:
            pass

    def critical(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        self._emit("CRITICAL", msg, *args, **kwargs)

    def error(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        self._emit("ERROR", msg, *args, **kwargs)

    def warning(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        self._emit("WARNING", msg, *args, **kwargs)

    def info(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        self._emit("INFO", msg, *args, **kwargs)

    def debug(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        if _truthy("NIJA_EXECUTION_ENTRY_SAFE_LOGGER_DEBUG", "false"):
            self._emit("DEBUG", msg, *args, **kwargs)

    def exception(self, msg: Any, *args: Any, **kwargs: Any) -> None:
        self._emit("EXCEPTION", msg, *args, **kwargs)

    def log(self, level: int, msg: Any, *args: Any, **kwargs: Any) -> None:
        self._emit(str(logging.getLevelName(level)), msg, *args, **kwargs)

    def isEnabledFor(self, level: int) -> bool:
        return True

    def getEffectiveLevel(self) -> int:
        return logging.DEBUG


def _install_on_module(module: ModuleType) -> bool:
    global _PATCHED
    _request_timeout_guard()
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type):
        return False
    module_name = str(getattr(module, "__name__", "<unknown>"))
    class_id = id(cls)
    original = getattr(cls, "execute_entry", None)
    if not callable(original):
        return False
    if class_id in _PATCHED_CLASS_IDS or getattr(original, "_nija_execution_entry_nonblocking_logger_wrapped", False):
        _PATCHED = True
        _PATCHED_CLASS_IDS.add(class_id)
        _PATCHED_MODULE_NAMES.add(module_name)
        return True

    def _patched_execute_entry(self: Any, *args: Any, **kwargs: Any) -> Any:
        if not _truthy("NIJA_EXECUTION_ENTRY_SAFE_LOGGER_ENABLED", "true"):
            return original(self, *args, **kwargs)
        old_logger = getattr(module, "logger", None)
        setattr(module, "logger", _SafeExecutionEntryLogger(old_logger))
        try:
            print("[NIJA-PRINT] EXECUTION_ENTRY_SAFE_LOGGER_ACTIVE", flush=True)
            return original(self, *args, **kwargs)
        finally:
            if old_logger is not None:
                setattr(module, "logger", old_logger)

    setattr(_patched_execute_entry, "_nija_execution_entry_nonblocking_logger_wrapped", True)
    setattr(cls, "execute_entry", _patched_execute_entry)
    _PATCHED = True
    _PATCHED_CLASS_IDS.add(class_id)
    _PATCHED_MODULE_NAMES.add(module_name)
    logger.warning("EXECUTION_ENTRY_SAFE_LOGGER_PATCHED module=%s", module_name)
    print(f"[NIJA-PRINT] EXECUTION_ENTRY_SAFE_LOGGER_PATCHED | module={module_name}", flush=True)
    return True


def _try_patch_loaded() -> bool:
    _request_timeout_guard()
    patched = False
    for name, module in list(sys.modules.items()):
        if not isinstance(module, ModuleType):
            continue
        if name in {"bot.execution_engine", "execution_engine"} or hasattr(module, "ExecutionEngine"):
            patched = _install_on_module(module) or patched
    return patched


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + float(os.environ.get("NIJA_PATCH_MONITOR_SECONDS", "300") or "300")
        patched_any = False
        while time.time() < deadline:
            patched_any = _try_patch_loaded() or patched_any
            time.sleep(0.25)
        logger.warning(
            "EXECUTION_ENTRY_SAFE_LOGGER_MONITOR_COMPLETE patched=%s patched_any=%s modules=%s timeout_guard=%s",
            _PATCHED,
            patched_any,
            sorted(_PATCHED_MODULE_NAMES),
            _TIMEOUT_CHAIN_REQUESTED,
        )

    threading.Thread(target=_monitor, name="execution-entry-safe-logger-monitor", daemon=True).start()
    logger.warning("EXECUTION_ENTRY_SAFE_LOGGER_MONITOR_STARTED")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE
    with _INSTALL_LOCK:
        _request_timeout_guard()
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is not None:
            logger.warning(
                "EXECUTION_ENTRY_SAFE_LOGGER_INSTALL_COMPLETE already_installed=True patched=%s timeout_guard=%s",
                _PATCHED,
                _TIMEOUT_CHAIN_REQUESTED,
            )
            return

        _ORIGINAL_IMPORT_MODULE = importlib.import_module

        def _wrapped_import_module(name: str, package: str | None = None):
            module = _ORIGINAL_IMPORT_MODULE(name, package)
            if name in {"bot.execution_engine", "execution_engine"} or hasattr(module, "ExecutionEngine"):
                _install_on_module(module)
            _try_patch_loaded()
            return module

        importlib.import_module = _wrapped_import_module
        logger.warning(
            "EXECUTION_ENTRY_SAFE_LOGGER_INSTALL_COMPLETE patched=%s timeout_guard=%s",
            _PATCHED,
            _TIMEOUT_CHAIN_REQUESTED,
        )
