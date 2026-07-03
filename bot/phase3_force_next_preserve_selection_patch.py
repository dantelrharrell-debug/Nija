"""Preserve multiple Phase 3 candidates without source-text rewriting.

The first 20260703k implementation tried to rewrite NijaCoreLoop source text at
runtime. That failed after other runtime wrappers were already installed, causing
SOURCE_MISS spam and Railway log rate limiting.

This replacement is intentionally simple and robust:
- no inspect.getsource()
- no source-text matching
- no repeated source-miss logs

When FORCE_NEXT_CYCLE is armed, this wrapper atomically consumes that flag before
NijaCoreLoop sees it, then calls the original Phase 3 scanner with a boosted
fallback streak. That preserves multi-candidate selection while keeping the
intended fallback/forced-entry behavior active. All downstream safety gates
(TPE, expectancy, ECEL, risk, writer authority, exchange constraints) remain
unchanged.
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

logger = logging.getLogger("nija.phase3_force_next_preserve_selection")

_ORIGINAL_IMPORT_MODULE: Optional[Callable[..., Any]] = None
_ORIGINAL_BUILTINS_IMPORT: Optional[Callable[..., Any]] = None
_PATCHED = False
_MONITOR_STARTED = False
_LOCK = threading.Lock()
_LAST_MISS_LOG = 0.0
_MARKER = "PHASE3_FORCE_NEXT_PRESERVE_SELECTION_PATCHED marker=20260703l"
_ATTR = "_nija_force_next_preserve_selection_v20260703l"


def _int_env(name: str, default: int) -> int:
    try:
        return max(1, int(float(os.environ.get(name, str(default)) or default)))
    except Exception:
        return int(default)


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _consume_force_next(module: ModuleType) -> bool:
    """Consume FORCE_NEXT_CYCLE without letting core collapse selected to [top]."""
    if not bool(getattr(module, "FORCE_NEXT_CYCLE", False)):
        return False
    lock = getattr(module, "_FORCE_LOCK", None)
    try:
        if lock is not None:
            with lock:
                armed = bool(getattr(module, "FORCE_NEXT_CYCLE", False))
                if armed:
                    setattr(module, "FORCE_NEXT_CYCLE", False)
                return armed
        armed = bool(getattr(module, "FORCE_NEXT_CYCLE", False))
        if armed:
            setattr(module, "FORCE_NEXT_CYCLE", False)
        return armed
    except Exception:
        return False


def _patch_core_loop_module(module: ModuleType) -> bool:
    global _PATCHED, _LAST_MISS_LOG
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_phase3_scan_and_enter", None)
    if not callable(original):
        return False
    if getattr(original, _ATTR, False):
        _PATCHED = True
        return True

    def _patched_phase3_scan_and_enter(
        self: Any,
        broker: Any,
        snapshot: Any,
        symbols: list[str],
        available_slots: int,
        zero_signal_streak: int = 0,
    ):
        force_next_was_armed = _consume_force_next(module)
        if force_next_was_armed:
            # Preserve the one-cycle forced-entry intent without letting the core
            # FORCE_NEXT_CYCLE block replace an already over-selected list with
            # a singleton. A high streak activates existing fallback paths; it
            # does not bypass downstream execution safety gates.
            boosted_streak = max(
                int(zero_signal_streak or 0),
                _int_env("NIJA_FORCE_NEXT_PRESERVE_STREAK", 999),
            )
            logger.warning(
                "PHASE3_FORCE_NEXT_PRESERVE_SELECTION_ACTIVE marker=20260703l original_streak=%s boosted_streak=%s available_slots=%s symbols=%s",
                zero_signal_streak,
                boosted_streak,
                available_slots,
                len(symbols or []),
            )
            print(
                f"[NIJA-PRINT] PHASE3_FORCE_NEXT_PRESERVE_SELECTION_ACTIVE marker=20260703l slots={available_slots} symbols={len(symbols or [])}",
                flush=True,
            )
            return original(
                self,
                broker=broker,
                snapshot=snapshot,
                symbols=symbols,
                available_slots=available_slots,
                zero_signal_streak=boosted_streak,
            )
        return original(
            self,
            broker=broker,
            snapshot=snapshot,
            symbols=symbols,
            available_slots=available_slots,
            zero_signal_streak=zero_signal_streak,
        )

    setattr(_patched_phase3_scan_and_enter, _ATTR, True)
    setattr(cls, "_phase3_scan_and_enter", _patched_phase3_scan_and_enter)
    _PATCHED = True
    logger.warning("%s module=%s", _MARKER, getattr(module, "__name__", "<unknown>"))
    print("[NIJA-PRINT] PHASE3_FORCE_NEXT_PRESERVE_SELECTION_PATCHED marker=20260703l", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_core_loop_module(module) or patched
    return patched


def _start_monitor() -> None:
    global _MONITOR_STARTED
    if _MONITOR_STARTED:
        return
    _MONITOR_STARTED = True

    def _monitor() -> None:
        deadline = time.time() + float(os.environ.get("NIJA_PATCH_MONITOR_SECONDS", "240") or "240")
        while time.time() < deadline:
            if _try_patch_loaded():
                return
            time.sleep(1.0)
        logger.warning("PHASE3_FORCE_NEXT_PRESERVE_SELECTION_MONITOR_EXPIRED marker=20260703l patched=%s", _PATCHED)

    threading.Thread(target=_monitor, name="phase3-force-next-preserve-selection", daemon=True).start()
    logger.warning("PHASE3_FORCE_NEXT_PRESERVE_SELECTION_MONITOR_STARTED marker=20260703l")


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT_MODULE, _ORIGINAL_BUILTINS_IMPORT
    with _LOCK:
        logger.warning("PHASE3_FORCE_NEXT_PRESERVE_SELECTION_INSTALL_START marker=20260703l")
        print("[NIJA-PRINT] PHASE3_FORCE_NEXT_PRESERVE_SELECTION_INSTALL_START marker=20260703l", flush=True)
        _try_patch_loaded()
        _start_monitor()

        if _ORIGINAL_IMPORT_MODULE is None:
            _ORIGINAL_IMPORT_MODULE = importlib.import_module

            def _wrapped_import_module(name: str, package: str | None = None):
                module = _ORIGINAL_IMPORT_MODULE(name, package)  # type: ignore[misc]
                if name in {"bot.nija_core_loop", "nija_core_loop"}:
                    _patch_core_loop_module(module)
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
                            _patch_core_loop_module(target)
                    else:
                        _try_patch_loaded()
                except Exception as exc:
                    logger.debug("Phase3 force-next preserve import hook skipped: %s", exc)
                return module

            builtins.__import__ = _wrapped_builtin_import

        logger.warning("PHASE3_FORCE_NEXT_PRESERVE_SELECTION_INSTALL_COMPLETE marker=20260703l patched=%s", _PATCHED)
