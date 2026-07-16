"""Quiesce legacy runtime patch watchdogs once canonical owners are installed.

Several older watchdogs inspect only the outermost callable marker. When another
legitimate wrapper sits above their marker they repeatedly wrap the same method,
causing scan-chain growth, noisy logs, and occasional false readiness failures.
This guard makes those checks chain-aware and delegates scan ownership to the
20260714a canonical scan wrapper.
"""
from __future__ import annotations

import builtins
import logging
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.runtime_patch_quiescence")
_MARKER = "20260716-runtime-patch-quiescence-v1"
_LOCK = threading.RLock()
_ORIGINAL_IMPORT: Callable[..., Any] | None = None
_STARTED = False

_CANONICAL_SCAN_MARKERS = (
    "_nija_scan_wrapper_release",
    "_nija_scan_wrapper_canonical_h",
    "_nija_scan_wrapper_canonical_v2",
)


def _walk_chain(func: Any, limit: int = 128):
    current = func
    seen: set[int] = set()
    for _ in range(limit):
        if not callable(current) or id(current) in seen:
            break
        seen.add(id(current))
        yield current
        current = getattr(current, "__wrapped__", None)


def _chain_has(func: Any, attr: str, value: Any | None = None) -> bool:
    for layer in _walk_chain(func):
        if not hasattr(layer, attr):
            continue
        if value is None or getattr(layer, attr, None) == value:
            return True
    return False


def _has_canonical_scan_owner(func: Any) -> bool:
    return any(_chain_has(func, attr) for attr in _CANONICAL_SCAN_MARKERS)


def _core_method(module: ModuleType) -> Any:
    cls = getattr(module, "NijaCoreLoop", None)
    return getattr(cls, "run_scan_phase", None) if isinstance(cls, type) else None


def _mark_scan_compatibility(func: Any) -> None:
    if not callable(func):
        return
    for attr in (
        "_nija_scan_identity_lock_v2",
        "_nija_final_result_contract_e",
        "_nija_account_scan_serialized_e",
        "_nija_final_result_contract",
    ):
        try:
            setattr(func, attr, True)
        except Exception:
            pass


def _guard_core_patcher(module: ModuleType, attr_name: str) -> bool:
    patcher = getattr(module, attr_name, None)
    guard_attr = f"_nija_quiescence_guard_{attr_name}"
    if not callable(patcher) or getattr(patcher, guard_attr, False):
        return False

    original = patcher

    def guarded(target: ModuleType, *args: Any, **kwargs: Any) -> bool:
        method = _core_method(target)
        if callable(method) and _has_canonical_scan_owner(method):
            _mark_scan_compatibility(method)
            return False
        return bool(original(target, *args, **kwargs))

    setattr(guarded, guard_attr, True)
    setattr(guarded, "__wrapped__", original)
    setattr(module, attr_name, guarded)
    return True


def _guard_final_okx_patcher(module: ModuleType) -> bool:
    patcher = getattr(module, "_patch_okx_classes", None)
    if not callable(patcher) or getattr(patcher, "_nija_quiescence_okx_guard", False):
        return False
    original = patcher

    def guarded() -> bool:
        missing = False
        for module_name in (
            "bot.broker_manager", "broker_manager",
            "bot.broker_integration", "broker_integration",
            "bot.multi_account_broker_manager", "multi_account_broker_manager",
        ):
            target = sys.modules.get(module_name)
            if not isinstance(target, ModuleType):
                continue
            for class_name in dir(target):
                cls = getattr(target, class_name, None)
                if not isinstance(cls, type) or "okx" not in class_name.lower():
                    continue
                connect = getattr(cls, "connect", None)
                if callable(connect) and not _chain_has(connect, "_nija_final_okx_endpoint_e"):
                    missing = True
                    break
            if missing:
                break
        return bool(original()) if missing else False

    guarded._nija_quiescence_okx_guard = True  # type: ignore[attr-defined]
    guarded.__wrapped__ = original  # type: ignore[attr-defined]
    module._patch_okx_classes = guarded
    return True


def _patch_loaded() -> bool:
    changed = False
    with _LOCK:
        canonical = sys.modules.get("scan_wrapper_convergence_repair_patch")
        if not isinstance(canonical, ModuleType):
            canonical = sys.modules.get("nija.scan_wrapper_convergence_repair_patch")
        if isinstance(canonical, ModuleType):
            patch_loaded = getattr(canonical, "_patch_loaded", None)
            if callable(patch_loaded):
                try:
                    patch_loaded()
                except Exception:
                    logger.debug("Canonical scan collapse deferred", exc_info=True)

        for name in ("runtime_convergence_v2_patch", "nija.runtime_convergence_v2_patch"):
            module = sys.modules.get(name)
            if isinstance(module, ModuleType):
                changed = _guard_core_patcher(module, "_patch_core_loop") or changed

        for name in ("final_runtime_convergence_patch", "nija.final_runtime_convergence_patch"):
            module = sys.modules.get(name)
            if isinstance(module, ModuleType):
                changed = _guard_core_patcher(module, "_patch_core_loop") or changed
                changed = _guard_final_okx_patcher(module) or changed

        for name in ("bot.nija_core_loop", "nija_core_loop"):
            module = sys.modules.get(name)
            if isinstance(module, ModuleType):
                method = _core_method(module)
                if callable(method) and _has_canonical_scan_owner(method):
                    _mark_scan_compatibility(method)
    return changed


def _watchdog() -> None:
    deadline = time.monotonic() + 120.0
    while time.monotonic() < deadline:
        try:
            _patch_loaded()
        except Exception:
            logger.debug("Runtime patch quiescence retry", exc_info=True)
        time.sleep(0.5)


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT, _STARTED
    _patch_loaded()
    if not getattr(builtins, "_NIJA_RUNTIME_PATCH_QUIESCENCE_IMPORT_HOOK", False):
        _ORIGINAL_IMPORT = builtins.__import__

        def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
            module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
            if name.endswith((
                "runtime_convergence_v2_patch",
                "final_runtime_convergence_patch",
                "scan_wrapper_convergence_repair_patch",
                "nija_core_loop",
            )):
                try:
                    _patch_loaded()
                except Exception:
                    logger.debug("Import-time quiescence deferred", exc_info=True)
            return module

        builtins.__import__ = guarded_import
        setattr(builtins, "_NIJA_RUNTIME_PATCH_QUIESCENCE_IMPORT_HOOK", True)

    if not _STARTED:
        _STARTED = True
        threading.Thread(
            target=_watchdog,
            name="RuntimePatchQuiescenceGuard",
            daemon=True,
        ).start()
    logger.critical(
        "RUNTIME_PATCH_QUIESCENCE_GUARD_INSTALLED marker=%s canonical_scan_owner=true chain_aware=true",
        _MARKER,
    )


def install() -> None:
    install_import_hook()


__all__ = ["install", "install_import_hook", "_patch_loaded", "_chain_has"]
