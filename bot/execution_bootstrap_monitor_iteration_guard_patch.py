from __future__ import annotations

import builtins
import logging
import sys
import threading
import time
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.execution_bootstrap_monitor_iteration_guard")
_MARKER = "20260709a"
_INSTALL_LOCK = threading.Lock()
_MONITOR_STARTED = False
_PATCHED_MODULES: set[str] = set()


def _is_target_module(name: str, module: Any) -> bool:
    file_name = str(getattr(module, "__file__", "") or "")
    return (
        name in {"nija_execution_bootstrap_authority_repair_patch", "bot.execution_bootstrap_authority_repair_patch", "execution_bootstrap_authority_repair_patch"}
        or file_name.endswith("execution_bootstrap_authority_repair_patch.py")
    )


def _snapshot_modules() -> list[tuple[str, Any]]:
    for _ in range(3):
        try:
            return list(sys.modules.items())
        except RuntimeError:
            time.sleep(0.01)
    try:
        return list(dict(sys.modules).items())
    except Exception:
        return []


def _patch_target_module(module: ModuleType) -> bool:
    original_install = getattr(module, "_install_on_execution_engine", None)
    if not callable(original_install):
        return False
    current = getattr(module, "_try_patch_loaded", None)
    if callable(current) and getattr(current, "_nija_monitor_iteration_guard_v20260709a", False):
        _PATCHED_MODULES.add(str(getattr(module, "__name__", "<unknown>")))
        return True

    def _safe_try_patch_loaded() -> bool:
        patched = False
        for name, loaded_module in _snapshot_modules():
            try:
                if not isinstance(loaded_module, ModuleType):
                    continue
                if name in {"bot.execution_engine", "execution_engine"} or hasattr(loaded_module, "ExecutionEngine"):
                    patched = original_install(loaded_module) or patched
            except RuntimeError as exc:
                if "dictionary changed size" in str(exc):
                    logger.warning("EXECUTION_BOOTSTRAP_MONITOR_ITERATION_RETRY marker=%s err=%s", _MARKER, exc)
                    continue
                raise
            except Exception as exc:
                logger.debug("EXECUTION_BOOTSTRAP_MONITOR_ITERATION_SKIPPED marker=%s module=%s err=%s", _MARKER, name, exc)
        return patched

    setattr(_safe_try_patch_loaded, "_nija_monitor_iteration_guard_v20260709a", True)
    setattr(_safe_try_patch_loaded, "__wrapped__", current)
    setattr(module, "_try_patch_loaded", _safe_try_patch_loaded)
    _PATCHED_MODULES.add(str(getattr(module, "__name__", "<unknown>")))
    logger.warning("EXECUTION_BOOTSTRAP_MONITOR_ITERATION_GUARD_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", "<unknown>"))
    print(f"[NIJA-PRINT] EXECUTION_BOOTSTRAP_MONITOR_ITERATION_GUARD_PATCHED marker={_MARKER} module={getattr(module, '__name__', '<unknown>')}", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name, module in _snapshot_modules():
        if isinstance(module, ModuleType) and _is_target_module(name, module):
            try:
                patched = _patch_target_module(module) or patched
            except Exception as exc:
                logger.warning("EXECUTION_BOOTSTRAP_MONITOR_ITERATION_GUARD_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)
    return patched


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + float(__import__("os").environ.get("NIJA_PATCH_MONITOR_SECONDS", "300") or "300")
        while time.time() < deadline:
            if _try_patch_loaded():
                return
            time.sleep(0.25)
        logger.warning("EXECUTION_BOOTSTRAP_MONITOR_ITERATION_GUARD_MONITOR_EXPIRED marker=%s patched_modules=%s", _MARKER, sorted(_PATCHED_MODULES))

    threading.Thread(target=_monitor, name="execution-bootstrap-monitor-iteration-guard", daemon=True).start()
    logger.warning("EXECUTION_BOOTSTRAP_MONITOR_ITERATION_GUARD_MONITOR_STARTED marker=%s", _MARKER)


def install_import_hook() -> None:
    with _INSTALL_LOCK:
        _try_patch_loaded()
        _start_monitor()
        if getattr(builtins, "_NIJA_EXECUTION_BOOTSTRAP_MONITOR_ITERATION_GUARD_V20260709A", False):
            logger.warning("EXECUTION_BOOTSTRAP_MONITOR_ITERATION_GUARD_INSTALL_COMPLETE marker=%s already_installed=True patched_modules=%s", _MARKER, sorted(_PATCHED_MODULES))
            return
        original_import = builtins.__import__

        def guarded_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
            module = original_import(name, globals, locals, fromlist, level)
            if "execution_bootstrap_authority_repair_patch" in str(name):
                _try_patch_loaded()
            return module

        builtins.__import__ = guarded_import
        setattr(builtins, "_NIJA_EXECUTION_BOOTSTRAP_MONITOR_ITERATION_GUARD_V20260709A", True)
        logger.warning("EXECUTION_BOOTSTRAP_MONITOR_ITERATION_GUARD_INSTALL_COMPLETE marker=%s patched_modules=%s", _MARKER, sorted(_PATCHED_MODULES))


def install() -> None:
    install_import_hook()
