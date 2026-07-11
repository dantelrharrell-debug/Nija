"""Process-wide recursion shield for NIJA startup import hooks.

NIJA has a large compatibility layer whose modules historically wrapped
``builtins.__import__`` independently.  Re-importing those modules under aliases
can create a deep wrapper chain.  Nested imports then traverse the entire chain
again and can raise ``RecursionError`` before broker startup completes.

This module is loaded from a ``.pth`` file before sitecustomize.  It installs one
process-wide compactor around the current hook chain:

* the outer import traverses the latest compatibility-hook chain once;
* calls back into the compact guard from that chain use Python's original import;
* nested imports while the outer import is active use the original import;
* newly installed wrappers are periodically compacted behind the same guard.

The compactor does not grant writer authority, create brokers, alter balances,
submit orders, clear risk stops, or bypass venue readiness.  Existing patch
monitors remain responsible for late-loaded modules.
"""

from __future__ import annotations

import builtins
import logging
import sys
import threading
import time
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.import_hook_recursion_shield")
_MARKER = "20260711d"
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

# These attributes live on builtins so duplicate imports of this module share one
# process-wide guard, delegate, lock, and thread-local recursion state.
_BASE_IMPORT_ATTR = "_NIJA_BASE_IMPORT_20260711D"
_GUARD_IMPORT_ATTR = "_NIJA_COMPACT_IMPORT_GUARD_20260711D"
_DELEGATE_IMPORT_ATTR = "_NIJA_COMPACT_IMPORT_DELEGATE_20260711D"
_IMPORT_LOCAL_ATTR = "_NIJA_COMPACT_IMPORT_LOCAL_20260711D"
_IMPORT_LOCK_ATTR = "_NIJA_COMPACT_IMPORT_LOCK_20260711D"
_MONITOR_STARTED_ATTR = "_NIJA_COMPACT_IMPORT_MONITOR_STARTED_20260711D"
_COMPACTION_GENERATION_ATTR = "_NIJA_COMPACT_IMPORT_GENERATION_20260711D"


def _process_object(name: str, factory):
    value = getattr(builtins, name, None)
    if value is None:
        value = factory()
        setattr(builtins, name, value)
    return value


def _callable_name(value: Any) -> str:
    module = str(getattr(value, "__module__", "") or "")
    name = str(getattr(value, "__qualname__", getattr(value, "__name__", "")) or "")
    return f"{module}.{name}".strip(".") or type(value).__name__


def _base_import():
    base = getattr(builtins, _BASE_IMPORT_ATTR, None)
    if callable(base):
        return base
    # This module is installed from the first NIJA .pth hook, before the runtime
    # compatibility wrappers.  The current value is therefore Python's importer.
    base = builtins.__import__
    setattr(builtins, _BASE_IMPORT_ATTR, base)
    return base


def _compact_guard():
    existing = getattr(builtins, _GUARD_IMPORT_ATTR, None)
    if callable(existing):
        return existing

    local: threading.local = _process_object(_IMPORT_LOCAL_ATTR, threading.local)
    base = _base_import()

    def guarded_import(
        name: str,
        globals=None,
        locals=None,
        fromlist=(),
        level: int = 0,
    ):
        # A compatibility wrapper captured this guard as its original importer,
        # or a nested module import occurred while the outer hook chain is active.
        # In either case, going through the chain again is recursive and unsafe.
        if getattr(local, "active", False):
            return base(name, globals, locals, fromlist, level)

        local.active = True
        try:
            delegate = getattr(builtins, _DELEGATE_IMPORT_ATTR, base)
            if not callable(delegate) or delegate is guarded_import:
                delegate = base
            try:
                return delegate(name, globals, locals, fromlist, level)
            except RecursionError:
                # Final fail-safe for a pre-existing cyclic delegate.  Resetting
                # the delegate to the original importer prevents repeat crashes;
                # existing background monitors still patch late-loaded modules.
                setattr(builtins, _DELEGATE_IMPORT_ATTR, base)
                logger.critical(
                    "IMPORT_HOOK_RECURSION_RECOVERED marker=%s name=%s "
                    "delegate=%s fallback=python_original authority_bypass=false "
                    "risk_bypass=false",
                    _MARKER,
                    name,
                    _callable_name(delegate),
                )
                return base(name, globals, locals, fromlist, level)
        finally:
            local.active = False

    guarded_import.__name__ = "nija_compact_import_guard"
    setattr(guarded_import, "_nija_import_chain_compactor", _MARKER)
    setattr(builtins, _GUARD_IMPORT_ATTR, guarded_import)
    return guarded_import


def compact_import_chain(*, force_log: bool = False) -> bool:
    """Put the latest wrapper chain behind one non-recursive process guard."""

    lock: threading.RLock = _process_object(_IMPORT_LOCK_ATTR, threading.RLock)
    guard = _compact_guard()
    base = _base_import()
    with lock:
        current = builtins.__import__
        if current is guard:
            return False

        # A later compatibility module replaced builtins.__import__.  Preserve its
        # callback chain as the outer delegate, then restore the compact guard as
        # the only public importer.  The delegate eventually calls the guard it
        # captured; the guard's active branch then invokes Python's base importer.
        if callable(current):
            setattr(builtins, _DELEGATE_IMPORT_ATTR, current)
        else:
            setattr(builtins, _DELEGATE_IMPORT_ATTR, base)
        builtins.__import__ = guard

        generation = int(getattr(builtins, _COMPACTION_GENERATION_ATTR, 0) or 0) + 1
        setattr(builtins, _COMPACTION_GENERATION_ATTR, generation)
        if force_log or generation <= 5 or generation % 25 == 0:
            logger.warning(
                "IMPORT_HOOK_CHAIN_COMPACTED marker=%s generation=%d delegate=%s "
                "nested_imports=python_original authority_bypass=false risk_bypass=false",
                _MARKER,
                generation,
                _callable_name(current),
            )
        return True


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
        "IMPORT_HOOK_RECURSION_SHIELD_RUNTIME_PATCHED marker=%s module=%s "
        "original_patch_core=%s fail_closed_preserved=true",
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
    compact_import_chain()
    return patched


def _monitor() -> None:
    deadline = time.monotonic() + 600.0
    last_log = 0.0
    while time.monotonic() < deadline:
        compacted = compact_import_chain()
        patched = apply_once()
        now = time.monotonic()
        if patched or compacted or now - last_log >= 30.0:
            logger.info(
                "IMPORT_HOOK_RECURSION_SHIELD_HEARTBEAT marker=%s patched_now=%d "
                "compacted_now=%s generation=%s runtime_total=%d volume_total=%d",
                _MARKER,
                patched,
                compacted,
                getattr(builtins, _COMPACTION_GENERATION_ATTR, 0),
                len(_PATCHED_RUNTIME),
                len(_PATCHED_VOLUME),
            )
            last_log = now
        # Compact aggressively while startup wrappers are being installed, then
        # settle to a low-frequency safety check after the chain stabilizes.
        generation = int(getattr(builtins, _COMPACTION_GENERATION_ATTR, 0) or 0)
        time.sleep(0.02 if generation < 25 else 0.5)


def install_import_hook() -> None:
    compact_import_chain(force_log=True)
    apply_once()
    lock: threading.Lock = _process_object("_NIJA_IMPORT_SHIELD_START_LOCK_20260711D", threading.Lock)
    with lock:
        if getattr(builtins, _MONITOR_STARTED_ATTR, False):
            return
        setattr(builtins, _MONITOR_STARTED_ATTR, True)
        thread = threading.Thread(
            target=_monitor,
            name="import-hook-recursion-shield",
            daemon=True,
        )
        thread.start()
        logger.warning(
            "IMPORT_HOOK_RECURSION_SHIELD_INSTALLED marker=%s thread_alive=%s "
            "chain_compactor=true authority_bypass=false risk_bypass=false",
            _MARKER,
            thread.is_alive(),
        )


def install() -> None:
    install_import_hook()


__all__ = [
    "install",
    "install_import_hook",
    "compact_import_chain",
    "apply_once",
]
