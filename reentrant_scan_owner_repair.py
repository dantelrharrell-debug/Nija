"""Disable the scan-owner wrapper that suppresses legitimate live scans.

The convergence wrapper can misclassify NIJA's normal same-thread scan delegation
as recursion and return an empty blocked result before any symbol is scored. This
repair removes only that wrapper, preserves its underlying scan pipeline, and
permanently guards the convergence patch from reinstalling it.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.reentrant_scan_owner_repair")
_MARKER = "20260713e"
_PATCH_ATTR = "_nija_scan_owner_result_reuse_20260713b"
_REPAIR_ATTR = "_nija_reentrant_scan_owner_repair_20260713c"
_GUARD_ATTR = "_nija_reentrant_scan_owner_guard_20260713e"
_STARTED = False
_LOCK = threading.RLock()


def _wrapper_chain_has_attr(func: Callable[..., Any], attr: str) -> bool:
    """Return True when any callable in ``func.__wrapped__`` chain has ``attr``."""
    current: Any = func
    seen: set[int] = set()
    for _ in range(128):
        if not callable(current) or id(current) in seen:
            break
        seen.add(id(current))
        if getattr(current, attr, False):
            return True
        current = getattr(current, "__wrapped__", None)
    return False


def _unwrap_faulty_owner(func: Callable[..., Any]) -> Callable[..., Any]:
    current = func
    seen: set[int] = set()
    for _ in range(64):
        if id(current) in seen:
            break
        seen.add(id(current))
        if not getattr(current, _PATCH_ATTR, False):
            break
        wrapped = getattr(current, "__wrapped__", None)
        if not callable(wrapped):
            break
        current = wrapped
    return current


def _repair_module(module: ModuleType) -> bool:
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "run_scan_phase", None)
    if not callable(current):
        return False

    # A legitimate outer wrapper (for example venue readiness) may sit above the
    # repaired canonical method. Promote the repair marker to that outer wrapper
    # instead of treating it as an unprotected method. This prevents the
    # convergence watchdog from reinstalling its owner wrapper every few seconds.
    if _wrapper_chain_has_attr(current, _REPAIR_ATTR):
        if not getattr(current, _REPAIR_ATTR, False):
            setattr(current, _REPAIR_ATTR, True)
            logger.info(
                "REENTRANT_SCAN_OWNER_REPAIR_MARKER_PROPAGATED marker=%s module=%s wrapper=%s",
                _MARKER,
                getattr(module, "__name__", "unknown"),
                getattr(current, "__qualname__", "unknown"),
            )
        return True

    if not getattr(current, _PATCH_ATTR, False):
        return False

    canonical = _unwrap_faulty_owner(current)
    if canonical is current:
        return False

    setattr(canonical, _PATCH_ATTR, True)
    setattr(canonical, _REPAIR_ATTR, True)
    setattr(cls, "run_scan_phase", canonical)
    logger.critical(
        "REENTRANT_SCAN_OWNER_BLOCKER_REMOVED marker=%s module=%s canonical=%s",
        _MARKER,
        getattr(module, "__name__", "unknown"),
        getattr(canonical, "__qualname__", "unknown"),
    )
    return True


def _install_convergence_guard() -> bool:
    """Make the convergence watchdog respect repaired canonical scan methods."""
    try:
        import scan_owner_okx_auth_convergence_patch as convergence
    except Exception as exc:
        logger.debug(
            "REENTRANT_SCAN_OWNER_GUARD_IMPORT_PENDING marker=%s error=%s",
            _MARKER,
            type(exc).__name__,
        )
        return False

    current_patch_core = getattr(convergence, "_patch_core", None)
    if not callable(current_patch_core):
        return False
    if getattr(current_patch_core, _GUARD_ATTR, False):
        return True

    original_patch_core = current_patch_core

    def guarded_patch_core(module: ModuleType) -> bool:
        cls = getattr(module, "NijaCoreLoop", None)
        method = getattr(cls, "run_scan_phase", None) if isinstance(cls, type) else None

        # Inspect the full wrapper chain. Venue-readiness and other legitimate
        # wrappers may be above the repaired canonical method. Checking only the
        # outer function caused the patch/remove loop seen in live logs.
        if callable(method) and _wrapper_chain_has_attr(method, _REPAIR_ATTR):
            if not getattr(method, _REPAIR_ATTR, False):
                setattr(method, _REPAIR_ATTR, True)
            return True

        result = original_patch_core(module)
        _repair_module(module)
        return result

    setattr(guarded_patch_core, _GUARD_ATTR, True)
    setattr(guarded_patch_core, "__wrapped__", original_patch_core)
    convergence._patch_core = guarded_patch_core
    logger.critical("REENTRANT_SCAN_OWNER_CONVERGENCE_GUARDED marker=%s", _MARKER)
    return True


def _repair_loaded() -> bool:
    changed = _install_convergence_guard()
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            changed = _repair_module(module) or changed
    return changed


def _watchdog() -> None:
    while True:
        try:
            _repair_loaded()
        except Exception as exc:
            logger.warning("REENTRANT_SCAN_OWNER_REPAIR_RETRY marker=%s error=%s", _MARKER, exc)
        time.sleep(0.5)


def install() -> None:
    global _STARTED
    with _LOCK:
        _repair_loaded()
        if _STARTED:
            return
        _STARTED = True
        threading.Thread(target=_watchdog, name="ReentrantScanOwnerRepair", daemon=True).start()
        logger.warning("REENTRANT_SCAN_OWNER_REPAIR_INSTALLED marker=%s", _MARKER)


install()


__all__ = [
    "install",
    "_repair_module",
    "_unwrap_faulty_owner",
    "_wrapper_chain_has_attr",
    "_install_convergence_guard",
    "_PATCH_ATTR",
    "_REPAIR_ATTR",
]
