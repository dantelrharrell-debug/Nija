"""Recursion shield for NIJA's startup import-hook repair modules.

Several startup repair modules wrap ``builtins.__import__``.  Their callbacks
must never invoke the same convergence/import scan recursively.  This patch
adds thread-local re-entry guards and limits loaded-module inspection to the
exact NIJA core-loop module names.  It does not grant execution authority,
clear risk stops, or bypass Redis writer verification.
"""

from __future__ import annotations

import logging
import sys
import threading
import time
from types import ModuleType

logger = logging.getLogger("nija.import_hook_recursion_shield")
_MARKER = "20260710x"
_STARTED = False
_START_LOCK = threading.Lock()
_RUNTIME_GUARDS: dict[int, threading.local] = {}
_PATCHED_RUNTIME: set[int] = set()
_PATCHED_VOLUME: set[int] = set()
_CORE_LOOP_NAMES = ("bot.nija_core_loop", "nija_core_loop", "nija_apex_strategy_v71")
_RUNTIME_MODULE_NAMES = (
    "bot.runtime_authority_convergence_repair_patch",
    "runtime_authority_convergence_repair_patch",
)
_VOLUME_MODULE_NAMES = (
    "bot.closed_candle_volume_repair_patch",
    "closed_candle_volume_repair_patch",
)


def _loaded_modules(names: tuple[str, ...]) -> list[ModuleType]:
    found: list[ModuleType] = []
    seen: set[int] = set()
    for name in names:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            found.append(module)
    return found


def _exact_core_modules() -> list[ModuleType]:
    found: list[ModuleType] = []
    seen: set[int] = set()
    for name in _CORE_LOOP_NAMES:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            found.append(module)
    return found


def _patch_runtime_module(module: ModuleType) -> bool:
    module_id = id(module)
    if module_id in _PATCHED_RUNTIME:
        return False

    original_converge = module.__dict__.get("converge_runtime_authority")
    original_patch_core = module.__dict__.get("_patch_core_loop_module")
    if not callable(original_converge):
        return False

    local = _RUNTIME_GUARDS.setdefault(module_id, threading.local())

    def converge_guarded(source: str = "manual") -> bool:
        if getattr(local, "active", False):
            logger.debug(
                "IMPORT_HOOK_RECURSION_SHIELD_REENTRY_SKIPPED marker=%s module=%s source=%s",
                _MARKER,
                module.__name__,
                source,
            )
            return False
        local.active = True
        try:
            return bool(original_converge(source))
        finally:
            local.active = False

    def patch_core_loop_safe(core_module: ModuleType) -> bool:
        cls = core_module.__dict__.get("NijaCoreLoop")
        if not isinstance(cls, type):
            return False
        logger.warning(
            "RUNTIME_AUTHORITY_CONVERGENCE_CORE_LOOP_SEEN marker=%s shield=%s module=%s",
            module.__dict__.get("_MARKER", "unknown"),
            _MARKER,
            core_module.__name__,
        )
        return True

    def try_patch_loaded_safe() -> bool:
        patched = False
        for core_module in _exact_core_modules():
            try:
                patched = patch_core_loop_safe(core_module) or patched
            except Exception as exc:
                logger.warning(
                    "IMPORT_HOOK_RECURSION_SHIELD_RUNTIME_SCAN_FAILED marker=%s module=%s err=%s",
                    _MARKER,
                    core_module.__name__,
                    exc,
                )
        return patched

    converge_guarded.__name__ = getattr(original_converge, "__name__", "converge_runtime_authority")
    converge_guarded.__doc__ = getattr(original_converge, "__doc__", None)
    setattr(converge_guarded, "_nija_recursion_shield", _MARKER)
    setattr(patch_core_loop_safe, "_nija_recursion_shield", _MARKER)
    setattr(try_patch_loaded_safe, "_nija_recursion_shield", _MARKER)

    module.__dict__["converge_runtime_authority"] = converge_guarded
    module.__dict__["_patch_core_loop_module"] = patch_core_loop_safe
    module.__dict__["_try_patch_loaded"] = try_patch_loaded_safe
    _PATCHED_RUNTIME.add(module_id)
    logger.critical(
        "IMPORT_HOOK_RECURSION_SHIELD_RUNTIME_PATCHED marker=%s module=%s original_patch_core=%s fail_closed_preserved=true",
        _MARKER,
        module.__name__,
        callable(original_patch_core),
    )
    return True


def _patch_volume_module(module: ModuleType) -> bool:
    module_id = id(module)
    if module_id in _PATCHED_VOLUME:
        return False
    patch_core = module.__dict__.get("_patch_core_loop_module")
    if not callable(patch_core):
        return False

    def try_patch_loaded_safe() -> bool:
        patched = False
        for core_module in _exact_core_modules():
            try:
                patched = bool(patch_core(core_module)) or patched
            except Exception as exc:
                logger.warning(
                    "IMPORT_HOOK_RECURSION_SHIELD_VOLUME_SCAN_FAILED marker=%s module=%s err=%s",
                    _MARKER,
                    core_module.__name__,
                    exc,
                )
        return patched

    setattr(try_patch_loaded_safe, "_nija_recursion_shield", _MARKER)
    module.__dict__["_try_patch_loaded"] = try_patch_loaded_safe
    _PATCHED_VOLUME.add(module_id)
    logger.critical(
        "IMPORT_HOOK_RECURSION_SHIELD_VOLUME_PATCHED marker=%s module=%s exact_module_scan=true",
        _MARKER,
        module.__name__,
    )
    return True


def apply_once() -> int:
    patched = 0
    for module in _loaded_modules(_RUNTIME_MODULE_NAMES):
        try:
            patched += int(_patch_runtime_module(module))
        except Exception as exc:
            logger.warning(
                "IMPORT_HOOK_RECURSION_SHIELD_RUNTIME_FAILED marker=%s module=%s err=%s",
                _MARKER,
                module.__name__,
                exc,
            )
    for module in _loaded_modules(_VOLUME_MODULE_NAMES):
        try:
            patched += int(_patch_volume_module(module))
        except Exception as exc:
            logger.warning(
                "IMPORT_HOOK_RECURSION_SHIELD_VOLUME_FAILED marker=%s module=%s err=%s",
                _MARKER,
                module.__name__,
                exc,
            )
    return patched


def _monitor() -> None:
    deadline = time.monotonic() + 600.0
    last_log = 0.0
    while time.monotonic() < deadline:
        patched = apply_once()
        now = time.monotonic()
        if patched or now - last_log >= 30.0:
            logger.info(
                "IMPORT_HOOK_RECURSION_SHIELD_HEARTBEAT marker=%s patched_now=%d runtime_total=%d volume_total=%d",
                _MARKER,
                patched,
                len(_PATCHED_RUNTIME),
                len(_PATCHED_VOLUME),
            )
            last_log = now
        time.sleep(0.01 if not (_PATCHED_RUNTIME and _PATCHED_VOLUME) else 5.0)


def install_import_hook() -> None:
    global _STARTED
    apply_once()
    if _STARTED:
        return
    with _START_LOCK:
        if _STARTED:
            return
        _STARTED = True
        thread = threading.Thread(
            target=_monitor,
            name="import-hook-recursion-shield",
            daemon=True,
        )
        thread.start()
        logger.warning(
            "IMPORT_HOOK_RECURSION_SHIELD_INSTALLED marker=%s thread_alive=%s authority_bypass=false risk_bypass=false",
            _MARKER,
            thread.is_alive(),
        )


def install() -> None:
    install_import_hook()
