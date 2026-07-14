"""Recover legitimate same-thread scan delegation without disabling scan ownership.

The canonical scan owner intentionally suppresses a true recursive call.  Some legacy
wrappers, however, capture an older canonical method and delegate through it after a
newer canonical owner has already acquired the same account lock.  Both wrappers use
the same process-wide scan state, so that legitimate delegation looks recursive and
returns ``scored=0, blocked=1``.

This patch changes only the canonical owner's *reentry recovery helper*.  During
normal installation/canonicalization the existing strict known-wrapper unwrapping is
preserved.  During an active ``run_scan_phase`` reentry, the helper may continue down
explicit ``__wrapped__`` links and narrowly named closure-held originals to reach the
real core scan exactly once.  Risk gates and telemetry wrappers already entered by
the outer call are not re-entered or bypassed globally.
"""
from __future__ import annotations

import importlib
import inspect
import logging
import os
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.scan_reentrant_delegate_repair")
_MARKER = "20260714-scan-delegate-v1"
_PATCH_ATTR = "_nija_scan_reentrant_delegate_repair_v1"
_LOCK = threading.RLock()
_WATCHDOG_STARTED = False

_CLOSURE_ORIGINAL_NAMES = (
    "original_run_scan_phase",
    "original_scan_phase",
    "original_method",
    "wrapped_run_scan_phase",
    "wrapped",
    "original",
    "base",
)


def _closure_original(func: Callable[..., Any]) -> Callable[..., Any] | None:
    """Return a narrowly identified wrapped scan function from *func*'s closure."""
    try:
        code = getattr(func, "__code__", None)
        closure = tuple(getattr(func, "__closure__", ()) or ())
        freevars = tuple(getattr(code, "co_freevars", ()) or ())
        values = {name: cell.cell_contents for name, cell in zip(freevars, closure)}
    except Exception:
        return None

    for name in _CLOSURE_ORIGINAL_NAMES:
        candidate = values.get(name)
        if callable(candidate):
            return candidate
    return None


def _next_delegate(func: Callable[..., Any]) -> Callable[..., Any] | None:
    wrapped = getattr(func, "__wrapped__", None)
    if callable(wrapped):
        return wrapped
    return _closure_original(func)


def _unwrap_delegate(func: Callable[..., Any]) -> tuple[Callable[..., Any], int, bool]:
    """Walk explicit wrapper/delegate links to the deepest callable target."""
    current = func
    seen: set[int] = set()
    depth = 0
    cycle = False
    while callable(current):
        ident = id(current)
        if ident in seen:
            cycle = True
            break
        seen.add(ident)
        nxt = _next_delegate(current)
        if not callable(nxt):
            break
        current = nxt
        depth += 1
        if depth >= 4096:
            cycle = True
            break
    return current, depth, cycle


def _caller_is_active_scan() -> bool:
    """True only when the canonical wrapper is asking for reentry recovery."""
    frame = inspect.currentframe()
    try:
        caller = frame.f_back.f_back if frame and frame.f_back else None
        return bool(caller and caller.f_code.co_name == "run_scan_phase")
    finally:
        del frame


def _patch_module(module: ModuleType) -> bool:
    current = getattr(module, "_unwrap_known", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def unwrap_known(func: Callable[..., Any]):
        resolved, depth, cycle = current(func)
        if cycle or not _caller_is_active_scan() or not callable(resolved):
            return resolved, depth, cycle

        delegated, extra_depth, delegated_cycle = _unwrap_delegate(resolved)
        if delegated_cycle:
            logger.error(
                "SCAN_REENTRANT_DELEGATE_CYCLE marker=%s base=%s depth=%d",
                _MARKER,
                getattr(resolved, "__qualname__", getattr(resolved, "__name__", "unknown")),
                depth + extra_depth,
            )
            return resolved, depth, True
        if callable(delegated) and delegated is not resolved and extra_depth > 0:
            logger.critical(
                "SCAN_REENTRANT_DELEGATION_RECOVERED marker=%s base=%s target=%s removed_layers=%d",
                _MARKER,
                getattr(resolved, "__qualname__", getattr(resolved, "__name__", "unknown")),
                getattr(delegated, "__qualname__", getattr(delegated, "__name__", "unknown")),
                depth + extra_depth,
            )
            return delegated, depth + extra_depth, False
        return resolved, depth, cycle

    setattr(unwrap_known, _PATCH_ATTR, True)
    setattr(unwrap_known, "__wrapped__", current)
    module._unwrap_known = unwrap_known
    os.environ["NIJA_SCAN_REENTRANT_DELEGATE_REPAIR_INSTALLED"] = "1"
    logger.critical(
        "SCAN_REENTRANT_DELEGATE_REPAIR_INSTALLED marker=%s strict_install_unwrap_preserved=true",
        _MARKER,
    )
    return True


def _patch_loaded() -> bool:
    changed = False
    for name in (
        "scan_wrapper_convergence_repair_patch",
        "nija.scan_wrapper_convergence_repair_patch",
    ):
        try:
            module = importlib.import_module(name)
        except Exception:
            continue
        if isinstance(module, ModuleType):
            changed = _patch_module(module) or changed
    return changed


def _watchdog() -> None:
    while True:
        try:
            _patch_loaded()
        except Exception as exc:
            logger.warning("SCAN_REENTRANT_DELEGATE_REPAIR_RETRY marker=%s error=%s", _MARKER, exc)
        time.sleep(0.5)


def install_import_hook() -> None:
    global _WATCHDOG_STARTED
    with _LOCK:
        if not _patch_loaded():
            raise RuntimeError("scan_wrapper_convergence_repair_not_patchable")
        if not _WATCHDOG_STARTED:
            _WATCHDOG_STARTED = True
            threading.Thread(
                target=_watchdog,
                name="ScanReentrantDelegateRepair",
                daemon=True,
            ).start()


def install() -> None:
    install_import_hook()


__all__ = [
    "install",
    "install_import_hook",
    "_closure_original",
    "_unwrap_delegate",
    "_patch_module",
]
