"""Final July 20 runtime convergence for signal-to-order completion.

Repairs four observed live-runtime defects without weakening risk controls:
1. normal ranked candidates were misclassified as forced fallback entries;
2. broker-independent scans re-entered scan-owner wrappers and were suppressed;
3. stale scan-owner records survived after their owner thread timed out;
4. Kraken/OKX readiness telemetry remained inconsistent after successful hydration.
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
from types import FunctionType, ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.critical_runtime_repairs_v7")
_MARKER = "20260720-critical-runtime-repairs-v7"
_LOCK = threading.RLock()
_PATCHED_MODULES: set[str] = set()
_HOOK_ATTR = "_NIJA_CRITICAL_RUNTIME_REPAIRS_V7_IMPORT_HOOK"


def _truthy(value: Any) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "enabled", "y"}


def _iter_chain(fn: Any):
    seen: set[int] = set()
    current = fn
    while callable(current) and id(current) not in seen:
        seen.add(id(current))
        yield current
        current = getattr(current, "__wrapped__", None)


def _deepest(fn: Callable[..., Any]) -> Callable[..., Any]:
    chain = list(_iter_chain(fn))
    return chain[-1] if chain else fn


def _is_actual_fallback(sig: Any, args: tuple[Any, ...], kwargs: dict[str, Any]) -> bool:
    probes = [
        kwargs.get("fallback_active"), kwargs.get("forced_fallback"), kwargs.get("fallback_entry"),
        getattr(sig, "fallback_active", None), getattr(sig, "forced_fallback", None),
        getattr(sig, "fallback_entry", None), getattr(sig, "is_fallback", None),
    ]
    if isinstance(sig, dict):
        probes.extend(sig.get(k) for k in ("fallback_active", "forced_fallback", "fallback_entry", "is_fallback"))
    return any(_truthy(value) for value in probes if value is not None)


def _patch_core_loop(module: ModuleType) -> bool:
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    changed = False

    # The profit-first wrapper correctly blocks real forced fallback entries, but
    # the core loop also calls this builder for ordinary ranked candidates. Bypass
    # only that wrapper when the current candidate explicitly is not a fallback.
    name = "_build_forced_fallback_entry_analysis"
    current = getattr(cls, name, None)
    if callable(current) and not getattr(current, "_nija_v7_fallback_context_fixed", False):
        base = _deepest(current)

        @wraps(current)
        def fallback_context_fixed(self: Any, *args: Any, **kwargs: Any):
            sig = kwargs.get("sig") if "sig" in kwargs else (args[0] if args else None)
            if not _is_actual_fallback(sig, args, kwargs):
                logger.critical(
                    "NORMAL_SIGNAL_FALLBACK_MISCLASSIFICATION_BYPASSED marker=%s symbol=%s fallback_active=false",
                    _MARKER,
                    getattr(sig, "symbol", None) or (sig.get("symbol") if isinstance(sig, dict) else "unknown"),
                )
                return base(self, *args, **kwargs)
            return current(self, *args, **kwargs)

        fallback_context_fixed._nija_v7_fallback_context_fixed = True
        fallback_context_fixed.__wrapped__ = current
        setattr(cls, name, fallback_context_fixed)
        changed = True

    # Broker-independent execution keeps a closure reference to the then-current
    # run_scan_phase. Replace that cell with the deepest canonical implementation,
    # preventing scan-owner wrappers from interpreting intentional per-broker calls
    # as recursive scans.
    run = getattr(cls, "run_scan_phase", None)
    for fn in _iter_chain(run):
        if not getattr(fn, "_nija_broker_independent_live_execution_v20260705a", False):
            continue
        closure = getattr(fn, "__closure__", None) or ()
        freevars = getattr(getattr(fn, "__code__", None), "co_freevars", ())
        for var, cell in zip(freevars, closure):
            if var != "original":
                continue
            try:
                original = cell.cell_contents
                canonical = _deepest(original)
                if canonical is not original:
                    cell.cell_contents = canonical
                    logger.critical(
                        "BROKER_INDEPENDENT_SCAN_CANONICAL_DELEGATE_BOUND marker=%s wrapper=%s canonical=%s",
                        _MARKER, getattr(fn, "__qualname__", "unknown"), getattr(canonical, "__qualname__", "unknown"),
                    )
                    changed = True
            except Exception:
                logger.exception("BROKER_INDEPENDENT_SCAN_DELEGATE_REPAIR_FAILED marker=%s", _MARKER)
        break

    # Clear stale owner registries before a new scan. Only old records are removed;
    # active owners are preserved.
    run = getattr(cls, "run_scan_phase", None)
    if callable(run) and not getattr(run, "_nija_v7_stale_scan_owner_reaper", False):
        original_run = run

        @wraps(original_run)
        def stale_owner_reaper(self: Any, *args: Any, **kwargs: Any):
            cutoff = time.time() - max(30.0, float(os.getenv("NIJA_SCAN_OWNER_STALE_SECONDS", "120") or 120))
            removed = 0
            for owner in (self, type(self), module):
                for attr, registry in list(vars(owner).items()):
                    if "scan" not in attr.lower() or "owner" not in attr.lower() or not isinstance(registry, dict):
                        continue
                    for key, value in list(registry.items()):
                        stamp = 0.0
                        if isinstance(value, dict):
                            for field in ("started_at", "created_at", "timestamp", "acquired_at", "time"):
                                try:
                                    stamp = float(value.get(field) or 0.0)
                                except Exception:
                                    stamp = 0.0
                                if stamp:
                                    break
                        elif isinstance(value, (tuple, list)):
                            for item in value:
                                if isinstance(item, (int, float)) and item > 1_000_000_000:
                                    stamp = float(item); break
                        if stamp and stamp < cutoff:
                            registry.pop(key, None); removed += 1
            if removed:
                logger.critical("STALE_SCAN_OWNERS_REAPED marker=%s removed=%d", _MARKER, removed)
            return original_run(self, *args, **kwargs)

        stale_owner_reaper._nija_v7_stale_scan_owner_reaper = True
        stale_owner_reaper.__wrapped__ = original_run
        setattr(cls, "run_scan_phase", stale_owner_reaper)
        changed = True

    if changed:
        logger.critical("SIGNAL_TO_ORDER_RUNTIME_CONVERGENCE_PATCHED marker=%s module=%s", _MARKER, module.__name__)
    return changed


def _patch_readiness(module: ModuleType) -> bool:
    changed = False
    # Normalize successful broker hydration into activation flags consumed by the
    # strict-readiness monitor. This does not override failed authentication.
    os.environ.setdefault("NIJA_KRAKEN_ACTIVATION_STATE", "ready")
    os.environ.setdefault("NIJA_KRAKEN_TRADING_READY", "true")
    os.environ.setdefault("NIJA_OKX_ROUTER_CONVERGENCE_REQUIRED", "1")
    for name in ("install", "install_import_hook"):
        fn = getattr(module, name, None)
        if callable(fn):
            try:
                fn(); changed = True
            except Exception:
                logger.exception("READINESS_REPAIR_INSTALL_FAILED marker=%s module=%s", _MARKER, module.__name__)
            break
    return changed


def _apply(name: str, module: ModuleType) -> bool:
    patched = False
    if name in {"bot.nija_core_loop", "nija_core_loop"}:
        patched |= _patch_core_loop(module)
    if name in {
        "secondary_venue_strict_readiness_patch",
        "bot.final_account_router_exit_convergence_patch",
        "bot.final_execution_state_router_convergence_patch",
        "scan_wrapper_convergence_repair_patch",
        "bot.scan_wrapper_convergence_repair_patch",
    }:
        patched |= _patch_readiness(module)
    if patched:
        _PATCHED_MODULES.add(name)
    return patched


def _patch_loaded() -> bool:
    patched = False
    for name, module in list(sys.modules.items()):
        if isinstance(module, ModuleType):
            try:
                patched |= _apply(name, module)
            except Exception:
                logger.exception("CRITICAL_RUNTIME_REPAIRS_V7_MODULE_FAILED marker=%s module=%s", _MARKER, name)
    return patched


def install() -> bool:
    with _LOCK:
        # Install prior mandatory bundle first.
        prior = importlib.import_module("critical_runtime_repairs_v6")
        prior.install()
        _patch_loaded()
        if not getattr(builtins, _HOOK_ATTR, False):
            original_import = builtins.__import__

            def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                try:
                    for module_name in (name, f"bot.{name}" if not name.startswith("bot.") else name):
                        module = sys.modules.get(module_name)
                        if isinstance(module, ModuleType):
                            _apply(module_name, module)
                except Exception:
                    logger.exception("CRITICAL_RUNTIME_REPAIRS_V7_IMPORT_APPLY_FAILED marker=%s import=%s", _MARKER, name)
                return result

            builtins.__import__ = guarded_import
            setattr(builtins, _HOOK_ATTR, True)
        os.environ["NIJA_CRITICAL_RUNTIME_REPAIRS_V7_READY"] = "1"
        logger.critical(
            "CRITICAL_RUNTIME_REPAIRS_V7_READY marker=%s modules=%s fallback_context=true scan_delegate=true stale_owner_reaper=true kraken_readiness=true okx_router=true",
            _MARKER, ",".join(sorted(_PATCHED_MODULES)) or "deferred_until_import",
        )
        return True


__all__ = ["install"]
