"""One-shot compatibility guard for NIJA runtime patch convergence.

The former implementation started another watchdog and import wrapper to control
older watchdogs. That reduced churn but still left mutation threads alive. This
module now delegates to ``final_runtime_cleanup_patch`` and exposes the legacy
helper API without starting a thread of its own.
"""
from __future__ import annotations

import logging
import sys
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.runtime_patch_quiescence")
_MARKER = "20260717-runtime-patch-quiescence-v2"
_INSTALLED = False

_CANONICAL_SCAN_MARKERS = (
    "_nija_scan_wrapper_release",
    "_nija_scan_wrapper_canonical_h",
    "_nija_scan_wrapper_canonical_v2",
    "_nija_final_runtime_frozen_20260717",
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
        "_nija_final_runtime_frozen_20260717",
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
        try:
            from bot.final_runtime_cleanup_patch import _okx_ready
        except ImportError:
            from final_runtime_cleanup_patch import _okx_ready  # type: ignore[import]
        ready, _reason, _spendable = _okx_ready()
        return bool(original()) if ready else False

    guarded._nija_quiescence_okx_guard = True  # type: ignore[attr-defined]
    guarded.__wrapped__ = original  # type: ignore[attr-defined]
    module._patch_okx_classes = guarded
    return True


def _patch_loaded() -> bool:
    changed = False
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
    try:
        from bot.final_runtime_cleanup_patch import _patch_loaded as final_patch_loaded
    except ImportError:
        from final_runtime_cleanup_patch import _patch_loaded as final_patch_loaded  # type: ignore[import]
    final_patch_loaded()
    return changed


def install_import_hook() -> None:
    global _INSTALLED
    try:
        from bot.final_runtime_cleanup_patch import install_import_hook as install_final
    except ImportError:
        from final_runtime_cleanup_patch import install_import_hook as install_final  # type: ignore[import]
    install_final()
    _patch_loaded()
    _INSTALLED = True
    logger.critical(
        "RUNTIME_PATCH_QUIESCENCE_GUARD_INSTALLED marker=%s canonical_scan_owner=true legacy_watchdogs=disabled background_thread=false",
        _MARKER,
    )


def install() -> None:
    install_import_hook()


def installed() -> bool:
    return _INSTALLED


__all__ = [
    "install",
    "install_import_hook",
    "installed",
    "_patch_loaded",
    "_chain_has",
    "_guard_core_patcher",
    "_guard_final_okx_patcher",
]
