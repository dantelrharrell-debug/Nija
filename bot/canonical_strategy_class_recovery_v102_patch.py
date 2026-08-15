"""Passively converge canonical TradingStrategy publication during active imports.

Production deployment 8d85b3ea on 2026-08-15 proved v100 still failed closed
with bot.trading_strategy genuinely ``__spec__._initializing=True``. The v100
wrapper retried the original strategy resolver inside its bounded loop. That
resolver calls ``importlib.import_module``; when another thread owns the module
lock, the retry itself can consume the recovery budget instead of observing the
in-progress import.

v102 supersedes only the class resolver behavior:
* if no candidate module exists, perform one normal canonical import attempt;
* if a candidate exists and is initializing, never re-enter importlib for that
  module; passively poll sys.modules for the real TradingStrategy class;
* if initialization completes without the class, perform at most one controlled
  reload of that non-initializing stale module;
* return only a real TradingStrategy type, otherwise None so publication remains
  fail closed.

No readiness key, broker state, execution authority, writer/nonce proof, risk
state, positions, or trading state is fabricated or bypassed.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
import time
from functools import wraps
from types import ModuleType
from typing import Optional

LOGGER = logging.getLogger("nija.canonical_strategy_class_recovery_v102")
MARKER = "20260815-canonical-strategy-class-recovery-v102"
_LOCK = threading.RLock()
_HOOK_FLAG = "_NIJA_CANONICAL_STRATEGY_CLASS_RECOVERY_V102_IMPORT_HOOK"
_PATCH_ATTR = "_nija_canonical_strategy_class_recovery_v102"
_RELOAD_ATTEMPTED: set[int] = set()


def _timeout_s() -> float:
    try:
        return max(0.1, float(os.environ.get("NIJA_STRATEGY_CLASS_RECOVERY_TIMEOUT_S", "12") or 12.0))
    except (TypeError, ValueError):
        return 12.0


def _poll_s() -> float:
    try:
        return max(0.01, min(0.25, float(os.environ.get("NIJA_STRATEGY_CLASS_RECOVERY_POLL_S", "0.05") or 0.05)))
    except (TypeError, ValueError):
        return 0.05


def _candidates() -> list[tuple[str, ModuleType]]:
    out: list[tuple[str, ModuleType]] = []
    seen: set[int] = set()
    for name in ("bot.trading_strategy", "trading_strategy"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            out.append((name, module))
    return out


def _initializing(module: ModuleType) -> bool:
    return bool(getattr(getattr(module, "__spec__", None), "_initializing", False))


def _real_class() -> tuple[Optional[type], str]:
    for name, module in _candidates():
        cls = getattr(module, "TradingStrategy", None)
        if isinstance(cls, type):
            return cls, name
    return None, ""


def _diagnostics() -> str:
    parts: list[str] = []
    for name, module in _candidates():
        parts.append(
            f"{name}:id={id(module)};file={getattr(module, '__file__', None)!r};"
            f"class={isinstance(getattr(module, 'TradingStrategy', None), type)};"
            f"initializing={_initializing(module)};keys={len(vars(module))}"
        )
    return " | ".join(parts) or "none"


def _import_once_if_absent() -> tuple[Optional[type], str]:
    if _candidates():
        return _real_class()
    errors: list[str] = []
    for name in ("bot.trading_strategy", "trading_strategy"):
        try:
            module = importlib.import_module(name)
            cls = getattr(module, "TradingStrategy", None)
            if isinstance(cls, type):
                return cls, name
            errors.append(f"{name}:class_missing")
        except Exception as exc:
            errors.append(f"{name}:{type(exc).__name__}:{exc}")
    LOGGER.warning(
        "CANONICAL_STRATEGY_CLASS_V102_INITIAL_IMPORT_FAILED marker=%s errors=%s",
        MARKER,
        errors,
    )
    return None, ""


def _reload_stale_once() -> tuple[Optional[type], str]:
    for name, module in _candidates():
        if _initializing(module):
            continue
        cls = getattr(module, "TradingStrategy", None)
        if isinstance(cls, type):
            return cls, name
        key = id(module)
        if key in _RELOAD_ATTEMPTED:
            continue
        _RELOAD_ATTEMPTED.add(key)
        try:
            reloaded = importlib.reload(module)
            cls = getattr(reloaded, "TradingStrategy", None)
            if isinstance(cls, type):
                LOGGER.critical(
                    "CANONICAL_STRATEGY_CLASS_V102_RELOADED marker=%s module=%s class=%s",
                    MARKER,
                    name,
                    cls.__name__,
                )
                return cls, name
        except BaseException as exc:
            LOGGER.warning(
                "CANONICAL_STRATEGY_CLASS_V102_RELOAD_FAILED marker=%s module=%s error=%s:%s diagnostics=%s",
                MARKER,
                name,
                type(exc).__name__,
                exc,
                _diagnostics(),
            )
    return None, ""


def _passive_strategy_class() -> Optional[type]:
    cls, source = _real_class()
    if cls is not None:
        return cls

    if not _candidates():
        cls, source = _import_once_if_absent()
        if cls is not None:
            LOGGER.critical(
                "CANONICAL_STRATEGY_CLASS_V102_CONVERGED marker=%s mode=initial_import source=%s",
                MARKER,
                source,
            )
            return cls

    deadline = time.monotonic() + _timeout_s()
    stale_reload_checked = False
    saw_initializing = False

    while time.monotonic() < deadline:
        cls, source = _real_class()
        if cls is not None:
            LOGGER.critical(
                "CANONICAL_STRATEGY_CLASS_V102_CONVERGED marker=%s mode=passive_wait source=%s saw_initializing=%s",
                MARKER,
                source,
                str(saw_initializing).lower(),
            )
            return cls

        candidates = _candidates()
        initializing = any(_initializing(module) for _, module in candidates)
        if initializing:
            saw_initializing = True
            # Critical invariant: do not call import_module/reload while an
            # existing canonical candidate owns an active import lifecycle.
            time.sleep(_poll_s())
            continue

        if candidates and not stale_reload_checked:
            stale_reload_checked = True
            cls, source = _reload_stale_once()
            if cls is not None:
                return cls

        if not candidates:
            # Module disappeared after a failed import. One bounded fresh import
            # attempt is safe because no active candidate owns the module lock.
            cls, source = _import_once_if_absent()
            if cls is not None:
                return cls

        time.sleep(_poll_s())

    LOGGER.critical(
        "CANONICAL_STRATEGY_CLASS_V102_UNAVAILABLE marker=%s timeout_s=%.2f "
        "saw_initializing=%s trading_fail_closed=true diagnostics=%s",
        MARKER,
        _timeout_s(),
        str(saw_initializing).lower(),
        _diagnostics(),
    )
    return None


def _patch_publication(module: ModuleType) -> bool:
    current = getattr(module, "_strategy_class", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def strategy_class_v102() -> Optional[type]:
        return _passive_strategy_class()

    setattr(strategy_class_v102, _PATCH_ATTR, True)
    setattr(strategy_class_v102, "__wrapped__", current)
    module._strategy_class = strategy_class_v102
    LOGGER.critical(
        "CANONICAL_STRATEGY_CLASS_RECOVERY_V102_PATCHED marker=%s module=%s "
        "passive_during_initialization=true timeout_s=%.2f fail_closed=true",
        MARKER,
        getattr(module, "__name__", "<unknown>"),
        _timeout_s(),
    )
    return True


def _patch_loaded() -> bool:
    found = False
    ready = True
    seen: set[int] = set()
    for name in ("bot.strategy_publication_patch", "strategy_publication_patch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            found = True
            ready = _patch_publication(module) and ready
    return ready if found else True


def install_import_hook() -> bool:
    with _LOCK:
        if not _patch_loaded():
            return False
        if not getattr(builtins, _HOOK_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                if "strategy_publication_patch" in str(name or ""):
                    _patch_loaded()
                return result

            builtins.__import__ = importing
            setattr(builtins, _HOOK_FLAG, True)

        os.environ["NIJA_CANONICAL_STRATEGY_CLASS_RECOVERY_V102_INSTALLED"] = "1"
        LOGGER.critical(
            "CANONICAL_STRATEGY_CLASS_RECOVERY_V102_INSTALLED marker=%s "
            "passive_import_observer=true stale_reload_once=true safety_gates_unchanged=true",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_passive_strategy_class",
    "_patch_publication",
    "_reload_stale_once",
]
