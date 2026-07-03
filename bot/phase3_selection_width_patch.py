"""Phase 3 selection width repair with one-shot logging.

Raises the fallback-width constant inside NijaCoreLoop to the configured
execution-attempt budget so replacement candidates remain available after
downstream rejections. This version is idempotent and only emits operator logs
when a module is first patched or the width actually changes, preventing Railway
log-rate floods from repeated import-hook calls.
"""

from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.phase3_selection_width")

_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_ORIGINAL_BUILTINS_IMPORT: Optional[Callable[..., Any]] = None
_PATCHED = False
_MONITOR_STARTED = False
_LOCK = threading.Lock()
_MARKER = "PHASE3_SELECTION_WIDTH_PATCHED marker=20260703n"
_ALREADY_PATCHED_MODULES: set[str] = set()


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(float(os.environ.get(name, str(default)) or default)))
    except Exception:
        return int(default)


def _patch_module(module: ModuleType) -> bool:
    global _PATCHED
    width_name = "_SNIPER_TOP_N_DEFAULT"
    module_name = getattr(module, "__name__", "<unknown>")
    if not hasattr(module, width_name):
        return False
    try:
        old_value = int(getattr(module, width_name) or 2)
    except Exception:
        old_value = 2
    target_value = max(old_value, _int_env("NIJA_PHASE3_MAX_EXECUTION_ATTEMPTS", 8))
    already_done = module_name in _ALREADY_PATCHED_MODULES and old_value >= target_value
    if already_done:
        _PATCHED = True
        return True
    try:
        setattr(module, width_name, target_value)
        _PATCHED = True
        _ALREADY_PATCHED_MODULES.add(module_name)
        logger.warning("%s module=%s old=%s new=%s", _MARKER, module_name, old_value, target_value)
        print(f"[NIJA-PRINT] PHASE3_SELECTION_WIDTH_PATCHED marker=20260703n module={module_name} old={old_value} new={target_value}", flush=True)
        return True
    except Exception as exc:
        logger.warning("PHASE3_SELECTION_WIDTH_PATCH_FAILED marker=20260703n module=%s err=%s", module_name, exc)
        return False


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_module(module) or patched
    return patched


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + 240.0
        while time.time() < deadline:
            if _try_patch_loaded():
                return
            time.sleep(1.0)
        logger.warning("PHASE3_SELECTION_WIDTH_MONITOR_EXPIRED marker=20260703n patched=%s", _PATCHED)

    threading.Thread(target=_monitor, name="phase3-selection-width", daemon=True).start()
    logger.warning("PHASE3_SELECTION_WIDTH_MONITOR_STARTED marker=20260703n")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE, _ORIGINAL_BUILTINS_IMPORT
    with _LOCK:
        logger.warning("PHASE3_SELECTION_WIDTH_INSTALL_START marker=20260703n")
        print("[NIJA-PRINT] PHASE3_SELECTION_WIDTH_INSTALL_START marker=20260703n", flush=True)
        _try_patch_loaded()
        _start_monitor()
        if _ORIGINAL_IMPORT_MODULE is None:
            _ORIGINAL_IMPORT_MODULE = importlib.import_module

            def _wrapped_import_module(name: str, package: str | None = None):
                module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
                if name in {"bot.nija_core_loop", "nija_core_loop"}:
                    _patch_module(module)
                return module

            importlib.import_module = _wrapped_import_module  # type: ignore[assignment]
        if _ORIGINAL_BUILTINS_IMPORT is None:
            _ORIGINAL_BUILTINS_IMPORT = builtins.__import__

            def _wrapped_builtin_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
                module = _ORIGINAL_BUILTINS_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
                try:
                    if name in {"bot.nija_core_loop", "nija_core_loop"} or name.endswith(".nija_core_loop"):
                        target = sys.modules.get("bot.nija_core_loop") or sys.modules.get("nija_core_loop") or module
                        if isinstance(target, ModuleType):
                            _patch_module(target)
                    else:
                        _try_patch_loaded()
                except Exception as exc:
                    logger.debug("Phase3 selection width import hook skipped: %s", exc)
                return module

            builtins.__import__ = _wrapped_builtin_import
        logger.warning("PHASE3_SELECTION_WIDTH_INSTALL_COMPLETE marker=20260703n patched=%s", _PATCHED)
