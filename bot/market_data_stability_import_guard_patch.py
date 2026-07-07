from __future__ import annotations

import builtins
import importlib
import logging
import sys
import threading
from types import ModuleType
from typing import Any, Callable, Optional

logger = logging.getLogger("nija.market_data_stability_import_guard")
_MARKER = "MARKET_DATA_STABILITY_IMPORT_GUARD marker=20260707b"
_HOOK_FLAG = "_NIJA_MARKET_DATA_STABILITY_IMPORT_GUARD_20260707B"
_LOCK = threading.Lock()
_ORIGINAL_IMPORT: Optional[Callable[..., Any]] = None
_INSTALLING = False
_APPLIED = False
_APPLY_LOGGED = False


def _broker_loaded() -> bool:
    for name in ("bot.broker_integration", "broker_integration"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and hasattr(module, "KrakenBrokerAdapter"):
            return True
    return False


def _force_install_market_data_patch(reason: str) -> bool:
    global _INSTALLING, _APPLIED, _APPLY_LOGGED
    if _APPLIED or _INSTALLING:
        return _APPLIED
    if not _broker_loaded():
        logger.debug("%s waiting_for_broker_integration reason=%s", _MARKER, reason)
        return False
    _INSTALLING = True
    try:
        try:
            patch = importlib.import_module("bot.market_data_stability_runtime_patch")
        except Exception:
            try:
                patch = importlib.import_module("market_data_stability_runtime_patch")
            except Exception as exc:
                logger.warning("MARKET_DATA_STABILITY_IMPORT_GUARD_IMPORT_FAILED marker=20260707b reason=%s err=%s", reason, exc)
                return False

        installer = getattr(patch, "_install_kraken_market_data_patch", None)
        if not callable(installer):
            logger.warning("MARKET_DATA_STABILITY_IMPORT_GUARD_NO_INSTALLER marker=20260707b module=%s", getattr(patch, "__name__", "unknown"))
            return False
        try:
            installer()
            _APPLIED = True
            if not _APPLY_LOGGED:
                _APPLY_LOGGED = True
                logger.warning("MARKET_DATA_STABILITY_IMPORT_GUARD_APPLIED marker=20260707b reason=%s mode=one_shot", reason)
                print(f"[NIJA-PRINT] MARKET_DATA_STABILITY_IMPORT_GUARD_APPLIED marker=20260707b reason={reason} mode=one_shot", flush=True)
            return True
        except Exception as exc:
            logger.warning("MARKET_DATA_STABILITY_IMPORT_GUARD_APPLY_FAILED marker=20260707b reason=%s err=%s", reason, exc)
            return False
    finally:
        _INSTALLING = False


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT
    with _LOCK:
        _force_install_market_data_patch("install_start")
        if getattr(builtins, _HOOK_FLAG, False):
            return
        _ORIGINAL_IMPORT = builtins.__import__

        def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
            module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
            try:
                if not _APPLIED and "broker_integration" in str(name):
                    _force_install_market_data_patch(f"import:{name}")
            except Exception as exc:
                logger.warning("MARKET_DATA_STABILITY_IMPORT_GUARD_HOOK_FAILED marker=20260707b name=%s err=%s", name, exc)
            return module

        builtins.__import__ = guarded_import
        setattr(builtins, _HOOK_FLAG, True)
        logger.warning("MARKET_DATA_STABILITY_IMPORT_GUARD_HOOK_INSTALLED marker=20260707b mode=broker_import_only")


def install() -> None:
    install_import_hook()
