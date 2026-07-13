"""Disable the scan-owner wrapper that suppresses legitimate live scans.

The convergence wrapper can misclassify NIJA's normal same-thread scan delegation
as recursion and return an empty blocked result before any symbol is scored. This
repair removes only that wrapper, preserves its underlying scan pipeline, and
marks the canonical method so the convergence watchdog cannot reinstall it.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.reentrant_scan_owner_repair")
_MARKER = "20260713c"
_PATCH_ATTR = "_nija_scan_owner_result_reuse_20260713b"
_REPAIR_ATTR = "_nija_reentrant_scan_owner_repair_20260713c"
_STARTED = False
_LOCK = threading.RLock()


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
    if getattr(current, _REPAIR_ATTR, False):
        return True
    if not getattr(current, _PATCH_ATTR, False):
        return False

    canonical = _unwrap_faulty_owner(current)
    if canonical is current:
        return False

    # Mark the canonical method as already handled so the convergence watchdog's
    # _patch_core() returns without wrapping it again.
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


def _repair_loaded() -> bool:
    changed = False
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
        time.sleep(0.25)


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

__all__ = ["install", "_repair_module", "_unwrap_faulty_owner"]
