from __future__ import annotations

import builtins
import importlib
import logging
import sys
import threading
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.execution_route_integrity_import_guard")
_MARKER = "EXECUTION_ROUTE_INTEGRITY_IMPORT_GUARD marker=20260707a"
_HOOK_FLAG = "_NIJA_EXECUTION_ROUTE_INTEGRITY_IMPORT_GUARD_20260707A"
_LOCK = threading.Lock()
_ORIGINAL_IMPORT: Optional[Callable[..., Any]] = None
_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_TARGETS = {
    "bot.trading_strategy",
    "trading_strategy",
    "bot.execution_pipeline",
    "execution_pipeline",
    "bot.multi_broker_execution_router",
    "multi_broker_execution_router",
    "bot.independent_broker_trader",
    "independent_broker_trader",
}


def _patch_module(name: str, module: ModuleType) -> bool:
    try:
        try:
            patch = importlib.import_module("bot.execution_route_integrity_patch")
        except Exception:
            patch = importlib.import_module("execution_route_integrity_patch")
        installer = getattr(patch, "_install_on_module", None)
        if callable(installer):
            patched = bool(installer(name, module))
            if patched:
                logger.warning("%s patched=%s module=%s", _MARKER, patched, name)
            return patched
    except Exception as exc:
        logger.warning("EXECUTION_ROUTE_INTEGRITY_IMPORT_GUARD_PATCH_FAILED marker=20260707a name=%s err=%s", name, exc)
    return False


def _try_patch_loaded() -> bool:
    patched = False
    for name in _TARGETS:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_module(name, module) or patched
    return patched


def _patch_result(name: str, module: Any) -> Any:
    try:
        _try_patch_loaded()
        if isinstance(module, ModuleType):
            mod_name = str(getattr(module, "__name__", name))
            if mod_name in _TARGETS:
                _patch_module(mod_name, module)
    except Exception as exc:
        logger.debug("Execution route integrity import guard skipped name=%s err=%s", name, exc)
    return module


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT, _ORIGINAL_IMPORT_MODULE
    with _LOCK:
        _try_patch_loaded()
        if getattr(builtins, _HOOK_FLAG, False):
            return
        if _ORIGINAL_IMPORT_MODULE is None:
            _ORIGINAL_IMPORT_MODULE = importlib.import_module

            def import_module(name: str, package: str | None = None):
                module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
                return _patch_result(name, module)

            importlib.import_module = import_module  # type: ignore[assignment]
        if _ORIGINAL_IMPORT is None:
            _ORIGINAL_IMPORT = builtins.__import__

            def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
                module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
                return _patch_result(name, module)

            builtins.__import__ = importing
        setattr(builtins, _HOOK_FLAG, True)
        logger.warning("EXECUTION_ROUTE_INTEGRITY_IMPORT_GUARD_INSTALLED marker=20260707a")


def install() -> None:
    install_import_hook()
