"""Recover canonical TradingStrategy publication from a partial import safely.

Production deployment 89f94744 on 2026-08-15 reached Step 2.5 with live capital
and writer authority, then failed closed because strategy_publication_patch saw
``TradingStrategy`` as unavailable. The same logs show trading_strategy had begun
importing (it emitted the NIJAApexStrategyV71 degraded-mode warning), which means
publication raced a partial/stale module surface rather than proving that the
strategy source was absent.

v100 repairs only class publication convergence:
* wait briefly for an actively-initializing canonical trading_strategy module;
* if a trading_strategy module is present but no longer initializing and still
  lacks TradingStrategy, perform at most one controlled importlib.reload();
* consume only the real TradingStrategy class from the canonical module object;
* preserve the existing class_unavailable fail-closed result if recovery fails.

No readiness key, execution authority, writer/nonce state, risk gate, position
state, broker connectivity, or trading state is synthesized by this patch.
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
from typing import Any, Callable, Optional

LOGGER = logging.getLogger("nija.canonical_strategy_class_recovery_v100")
MARKER = "20260815-canonical-strategy-class-recovery-v100"
_LOCK = threading.RLock()
_HOOK_FLAG = "_NIJA_CANONICAL_STRATEGY_CLASS_RECOVERY_V100_IMPORT_HOOK"
_PATCH_ATTR = "_nija_canonical_strategy_class_recovery_v100"
_RELOAD_ATTEMPTED: set[int] = set()


def _timeout_s() -> float:
    try:
        return max(
            0.1,
            float(os.environ.get("NIJA_STRATEGY_CLASS_RECOVERY_TIMEOUT_S", "6") or 6.0),
        )
    except (TypeError, ValueError):
        return 6.0


def _poll_s() -> float:
    try:
        return max(
            0.01,
            min(
                0.5,
                float(os.environ.get("NIJA_STRATEGY_CLASS_RECOVERY_POLL_S", "0.05") or 0.05),
            ),
        )
    except (TypeError, ValueError):
        return 0.05


def _candidate_modules() -> list[tuple[str, ModuleType]]:
    out: list[tuple[str, ModuleType]] = []
    seen: set[int] = set()
    for name in ("bot.trading_strategy", "trading_strategy"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            out.append((name, module))
    return out


def _real_strategy_class() -> tuple[Optional[type], str]:
    for name, module in _candidate_modules():
        cls = getattr(module, "TradingStrategy", None)
        if isinstance(cls, type):
            return cls, name
    return None, ""


def _initializing(module: ModuleType) -> bool:
    spec = getattr(module, "__spec__", None)
    return bool(getattr(spec, "_initializing", False))


def _diagnostics() -> str:
    details: list[str] = []
    for name, module in _candidate_modules():
        spec = getattr(module, "__spec__", None)
        details.append(
            f"{name}:id={id(module)};file={getattr(module, '__file__', None)!r};"
            f"class={isinstance(getattr(module, 'TradingStrategy', None), type)};"
            f"initializing={bool(getattr(spec, '_initializing', False))};"
            f"keys={len(vars(module))}"
        )
    return " | ".join(details) or "none"


def _reload_stale_candidate_once() -> tuple[Optional[type], str]:
    """Reload one demonstrably non-initializing partial canonical module."""
    for name, module in _candidate_modules():
        if _initializing(module):
            continue
        if isinstance(getattr(module, "TradingStrategy", None), type):
            return getattr(module, "TradingStrategy"), name
        key = id(module)
        if key in _RELOAD_ATTEMPTED:
            continue
        _RELOAD_ATTEMPTED.add(key)
        try:
            reloaded = importlib.reload(module)
            cls = getattr(reloaded, "TradingStrategy", None)
            if isinstance(cls, type):
                LOGGER.critical(
                    "CANONICAL_STRATEGY_CLASS_V100_RELOADED marker=%s module=%s "
                    "same_object=%s class=%s",
                    MARKER,
                    name,
                    str(reloaded is module).lower(),
                    cls.__name__,
                )
                return cls, name
            LOGGER.warning(
                "CANONICAL_STRATEGY_CLASS_V100_RELOAD_INCOMPLETE marker=%s module=%s diagnostics=%s",
                MARKER,
                name,
                _diagnostics(),
            )
        except BaseException as exc:
            LOGGER.warning(
                "CANONICAL_STRATEGY_CLASS_V100_RELOAD_FAILED marker=%s module=%s error=%s:%s "
                "trading_fail_closed=true diagnostics=%s",
                MARKER,
                name,
                type(exc).__name__,
                exc,
                _diagnostics(),
            )
    return None, ""


def _bounded_strategy_class(original: Callable[[], Any]) -> Optional[type]:
    """Return the real TradingStrategy class or None without synthesizing one."""
    try:
        cls = original()
    except BaseException as exc:
        cls = None
        LOGGER.warning(
            "CANONICAL_STRATEGY_CLASS_V100_ORIGINAL_ERROR marker=%s error=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )
    if isinstance(cls, type):
        return cls

    cls, source = _real_strategy_class()
    if cls is not None:
        return cls

    deadline = time.monotonic() + _timeout_s()
    reload_checked = False
    while time.monotonic() < deadline:
        candidates = _candidate_modules()
        actively_initializing = any(_initializing(module) for _, module in candidates)

        cls, source = _real_strategy_class()
        if cls is not None:
            LOGGER.critical(
                "CANONICAL_STRATEGY_CLASS_V100_CONVERGED marker=%s source=%s mode=wait",
                MARKER,
                source,
            )
            return cls

        # A non-initializing module missing TradingStrategy is stale/partial,
        # not an import currently making forward progress. Reload once only.
        if candidates and not actively_initializing and not reload_checked:
            reload_checked = True
            cls, source = _reload_stale_candidate_once()
            if cls is not None:
                return cls

        try:
            cls = original()
        except BaseException:
            cls = None
        if isinstance(cls, type):
            LOGGER.critical(
                "CANONICAL_STRATEGY_CLASS_V100_CONVERGED marker=%s source=original mode=retry",
                MARKER,
            )
            return cls

        time.sleep(_poll_s())

    LOGGER.critical(
        "CANONICAL_STRATEGY_CLASS_V100_UNAVAILABLE marker=%s timeout_s=%.2f "
        "trading_fail_closed=true diagnostics=%s",
        MARKER,
        _timeout_s(),
        _diagnostics(),
    )
    return None


def _patch_publication_module(module: ModuleType) -> bool:
    current = getattr(module, "_strategy_class", None)
    if not callable(current):
        return False
    if getattr(current, _PATCH_ATTR, False):
        return True

    @wraps(current)
    def strategy_class_v100() -> Optional[type]:
        return _bounded_strategy_class(current)

    setattr(strategy_class_v100, _PATCH_ATTR, True)
    setattr(strategy_class_v100, "__wrapped__", current)
    module._strategy_class = strategy_class_v100
    LOGGER.critical(
        "CANONICAL_STRATEGY_CLASS_RECOVERY_V100_PATCHED marker=%s module=%s "
        "timeout_s=%.2f fail_closed=true",
        MARKER,
        getattr(module, "__name__", "<unknown>"),
        _timeout_s(),
    )
    return True


def _patch_loaded() -> bool:
    ready = True
    found = False
    seen: set[int] = set()
    for name in ("bot.strategy_publication_patch", "strategy_publication_patch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            found = True
            ready = _patch_publication_module(module) and ready
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

        os.environ["NIJA_CANONICAL_STRATEGY_CLASS_RECOVERY_V100_INSTALLED"] = "1"
        LOGGER.critical(
            "CANONICAL_STRATEGY_CLASS_RECOVERY_V100_INSTALLED marker=%s "
            "bounded_wait=true stale_reload_once=true safety_gates_unchanged=true",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_bounded_strategy_class",
    "_patch_publication_module",
    "_reload_stale_candidate_once",
]
