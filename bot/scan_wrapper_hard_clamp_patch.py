"""Prevent and repair runaway NijaCoreLoop.run_scan_phase wrapper chains."""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.scan_wrapper_hard_clamp")
_MARKER = "20260716-scan-hard-clamp-v2"
_LOCK = threading.RLock()
_INSTALLED = False
_WATCHDOG = False
# NIJA's fully converged safety stack currently settles around 32 linked wrappers.
# Keep a strict ceiling above that stable baseline while still collapsing runaway
# chains such as the 94/1383-layer production failures.
_MAX_DEPTH = 64
_WRAP_ATTR = "_nija_broker_independent_live_execution_v20260705a"


def _next(func: Callable[..., Any]) -> Callable[..., Any] | None:
    wrapped = getattr(func, "__wrapped__", None)
    if callable(wrapped):
        return wrapped
    try:
        code = getattr(func, "__code__", None)
        closure = tuple(getattr(func, "__closure__", ()) or ())
        names = tuple(getattr(code, "co_freevars", ()) or ())
        values = {name: cell.cell_contents for name, cell in zip(names, closure)}
        for name in ("original", "original_run_scan_phase", "base", "wrapped", "wrapped_run_scan_phase"):
            candidate = values.get(name)
            if callable(candidate):
                return candidate
    except Exception:
        pass
    return None


def _walk(func: Callable[..., Any], limit: int = 4096) -> tuple[list[Callable[..., Any]], bool]:
    chain: list[Callable[..., Any]] = []
    seen: set[int] = set()
    current: Any = func
    while callable(current) and len(chain) < limit:
        if id(current) in seen:
            return chain, True
        seen.add(id(current))
        chain.append(current)
        nxt = _next(current)
        if not callable(nxt):
            break
        current = nxt
    return chain, len(chain) >= limit


def _chain_has(func: Callable[..., Any], attr: str) -> bool:
    chain, _ = _walk(func, 512)
    return any(bool(getattr(item, attr, False)) for item in chain)


def _normalise_depth_ceiling() -> int:
    """Publish one ceiling shared by the clamp and depth audit.

    Older releases defaulted to 24, below the current stable safety stack. Treat
    that legacy value as a default and migrate it to 64. Values above 64 are
    reduced to the hard safety ceiling.
    """
    raw = str(os.environ.get("NIJA_MAX_SCAN_WRAPPER_DEPTH", "") or "").strip()
    try:
        configured = int(float(raw)) if raw else _MAX_DEPTH
    except Exception:
        configured = _MAX_DEPTH
    if configured <= 24:
        configured = _MAX_DEPTH
    configured = max(32, min(_MAX_DEPTH, configured))
    os.environ["NIJA_MAX_SCAN_WRAPPER_DEPTH"] = str(configured)
    return configured


def _guard_broker_installer(module: ModuleType) -> bool:
    current = getattr(module, "_patch_core_loop_module", None)
    if not callable(current) or getattr(current, "_nija_chain_aware_hard_clamp_v2", False):
        return bool(getattr(current, "_nija_chain_aware_hard_clamp_v2", False))

    def patch_core_loop_module(core_module: ModuleType) -> bool:
        cls = getattr(core_module, "NijaCoreLoop", None)
        before = getattr(cls, "run_scan_phase", None) if isinstance(cls, type) else None
        if callable(before) and _chain_has(before, _WRAP_ATTR):
            module._PATCHED = True
            return True
        result = bool(current(core_module))
        after = getattr(cls, "run_scan_phase", None) if isinstance(cls, type) else None
        if callable(after) and callable(before) and after is not before and not callable(getattr(after, "__wrapped__", None)):
            after.__wrapped__ = before  # type: ignore[attr-defined]
        return result

    patch_core_loop_module._nija_chain_aware_hard_clamp_v2 = True  # type: ignore[attr-defined]
    patch_core_loop_module.__wrapped__ = current  # type: ignore[attr-defined]
    module._patch_core_loop_module = patch_core_loop_module
    logger.critical("BROKER_SCAN_INSTALLER_HARD_GUARDED marker=%s", _MARKER)
    return True


def _collapse_core(core_module: ModuleType) -> bool:
    cls = getattr(core_module, "NijaCoreLoop", None)
    current = getattr(cls, "run_scan_phase", None) if isinstance(cls, type) else None
    if not callable(current):
        return False
    ceiling = _normalise_depth_ceiling()
    chain, cycle = _walk(current)
    if not cycle and len(chain) <= ceiling:
        return False
    deepest = chain[-1] if chain else current
    setattr(cls, "run_scan_phase", deepest)

    broker_patch = importlib.import_module("bot.broker_independent_live_execution_patch")
    _guard_broker_installer(broker_patch)
    broker_patch._PATCHED = False
    broker_patch._patch_core_loop_module(core_module)

    convergence = importlib.import_module("scan_wrapper_convergence_repair_patch")
    convergence._patch_core_loop(core_module)
    final = getattr(cls, "run_scan_phase")
    final_chain, final_cycle = _walk(final)
    ready = not final_cycle and len(final_chain) <= ceiling
    logger.critical(
        "SCAN_WRAPPER_HARD_CLAMP_APPLIED marker=%s old_depth=%d old_cycle=%s new_depth=%d new_cycle=%s ceiling=%d ready=%s",
        _MARKER,
        len(chain),
        str(cycle).lower(),
        len(final_chain),
        str(final_cycle).lower(),
        ceiling,
        str(ready).lower(),
    )
    if not ready:
        raise RuntimeError(
            f"scan_wrapper_hard_clamp_failed:depth={len(final_chain)} ceiling={ceiling} cycle={final_cycle}"
        )
    return True


def _apply() -> bool:
    _normalise_depth_ceiling()
    broker_patch = importlib.import_module("bot.broker_independent_live_execution_patch")
    changed = _guard_broker_installer(broker_patch)
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            changed = _collapse_core(module) or changed
    return changed


def _watchdog() -> None:
    while True:
        try:
            _apply()
        except Exception as exc:
            logger.error("SCAN_WRAPPER_HARD_CLAMP_RETRY marker=%s error=%s", _MARKER, exc)
        time.sleep(5.0)


def install() -> bool:
    global _INSTALLED, _WATCHDOG
    with _LOCK:
        ceiling = _normalise_depth_ceiling()
        _apply()
        if not _WATCHDOG:
            _WATCHDOG = True
            threading.Thread(target=_watchdog, name="ScanWrapperHardClamp", daemon=True).start()
        _INSTALLED = True
        os.environ["NIJA_SCAN_WRAPPER_HARD_CLAMP_INSTALLED"] = "1"
        logger.critical(
            "SCAN_WRAPPER_HARD_CLAMP_INSTALLED marker=%s max_depth=%d",
            _MARKER,
            ceiling,
        )
        return True


__all__ = [
    "install",
    "_walk",
    "_chain_has",
    "_normalise_depth_ceiling",
    "_guard_broker_installer",
    "_collapse_core",
]
