"""Converge live runtime truth after strategy/readiness bootstrap.

Production deployments exposed four stale-truth failure modes after the
canonical strategy-integrity guards were enabled:

* ``bot.nija_apex_strategy_v71`` could exist in ``sys.modules`` as a partial
  module object without ``NIJAApexStrategyV71``.
* the APEX wiring patch can also be source-loaded under compatibility aliases,
  so name-only patching can miss the resolver that is actually executing.
* position fetches that time out can be caught by an outer compatibility layer
  and returned as ``[]``; a masked failure must never become an empty-snapshot
  synchronization success.
* the writer scan-start watchdog needs the actual core scan lifecycle rather
  than merely core-thread liveness.

This patch repairs only those truth handoffs. It does not lower risk thresholds,
bypass writer/nonce/kill-switch gates, synthesize positions, or submit orders.
"""
from __future__ import annotations

import builtins
import importlib
import importlib.util
import logging
import os
import sys
import threading
from functools import wraps
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_truth_convergence_v97")
MARKER = "20260815-runtime-truth-convergence-v97b"
_LOCK = threading.RLock()
_HOOK_FLAG = "_NIJA_RUNTIME_TRUTH_CONVERGENCE_V97_IMPORT_HOOK"
_IMPORT_MODULE_FLAG = "_NIJA_RUNTIME_TRUTH_CONVERGENCE_V97_IMPORT_MODULE_HOOK"
_APEX_ATTR = "_nija_runtime_truth_convergence_v97_apex"
_POSITION_ATTR = "_nija_runtime_truth_convergence_v97_position"
_POSITION_SYNC_ATTR = "_nija_runtime_truth_convergence_v97_startup_sync"
_SCAN_ATTR = "_nija_runtime_truth_convergence_v97_scan"
_RECOVERY_MODULE = "bot._nija_apex_strategy_v71_recovery_v97"
_WIRING_BASENAME = "trading_strategy_apex_wiring_patch.py"
_APEX_BASENAME = "nija_apex_strategy_v71.py"
_STARTUP_SYNC_BASENAME = "startup_position_sync.py"
_RECOVERED_APEX_CLASS: Any = None


def _module_basename(module: Any) -> str:
    if not isinstance(module, ModuleType):
        return ""
    try:
        return Path(str(getattr(module, "__file__", "") or "")).name
    except Exception:
        return ""


def _iter_loaded_modules(*, names: tuple[str, ...] = (), basenames: tuple[str, ...] = ()):
    seen: set[int] = set()
    for name in names:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            yield name, module
    wanted = set(basenames)
    if wanted:
        for name, module in tuple(sys.modules.items()):
            if not isinstance(module, ModuleType) or id(module) in seen:
                continue
            if _module_basename(module) not in wanted:
                continue
            seen.add(id(module))
            yield str(name), module


def _apex_module_diagnostics() -> str:
    details: list[str] = []
    for name, module in _iter_loaded_modules(
        names=("bot.nija_apex_strategy_v71", "nija_apex_strategy_v71", _RECOVERY_MODULE),
        basenames=(_APEX_BASENAME,),
    ):
        spec = getattr(module, "__spec__", None)
        details.append(
            f"{name}:id={id(module)};file={getattr(module, '__file__', None)!r};"
            f"class={hasattr(module, 'NIJAApexStrategyV71')};"
            f"spec={getattr(spec, 'name', None)!r};"
            f"initializing={getattr(spec, '_initializing', None)!r};"
            f"keys={len(vars(module))}"
        )
    return " | ".join(details) or "none"


def _loaded_apex_class() -> tuple[Any | None, str]:
    for name, module in _iter_loaded_modules(
        names=("bot.nija_apex_strategy_v71", "nija_apex_strategy_v71", _RECOVERY_MODULE),
        basenames=(_APEX_BASENAME,),
    ):
        cls = getattr(module, "NIJAApexStrategyV71", None)
        if cls is not None:
            return cls, name
    return None, ""


def _partial_apex_module_present() -> bool:
    found = False
    for _name, module in _iter_loaded_modules(
        names=("bot.nija_apex_strategy_v71", "nija_apex_strategy_v71"),
        basenames=(_APEX_BASENAME,),
    ):
        found = True
        if getattr(module, "NIJAApexStrategyV71", None) is not None:
            return False
    return found


def _bind_apex_class(cls: Any) -> None:
    """Publish a recovered class onto every loaded APEX/strategy surface."""
    if cls is None:
        return
    for _name, module in _iter_loaded_modules(
        names=("bot.nija_apex_strategy_v71", "nija_apex_strategy_v71", _RECOVERY_MODULE),
        basenames=(_APEX_BASENAME,),
    ):
        try:
            setattr(module, "NIJAApexStrategyV71", cls)
        except Exception:
            pass
    for _name, module in _iter_loaded_modules(
        names=("bot.trading_strategy", "trading_strategy"),
        basenames=("trading_strategy.py",),
    ):
        try:
            setattr(module, "NIJAApexStrategyV71", cls)
            setattr(module, "_APEX_AVAILABLE", True)
        except Exception:
            pass


def _recover_apex_class_from_source(wiring_module: ModuleType) -> tuple[Any | None, str]:
    """Recover v7.1 from canonical source without replacing a partial module."""
    global _RECOVERED_APEX_CLASS
    if _RECOVERED_APEX_CLASS is not None:
        _bind_apex_class(_RECOVERED_APEX_CLASS)
        return _RECOVERED_APEX_CLASS, _RECOVERY_MODULE

    loaded, loaded_from = _loaded_apex_class()
    if loaded is not None:
        _RECOVERED_APEX_CLASS = loaded
        _bind_apex_class(loaded)
        return loaded, loaded_from

    try:
        source_path = Path(str(getattr(wiring_module, "__file__", "") or "")).resolve().parent / _APEX_BASENAME
    except Exception as exc:
        return None, f"source_path_error:{type(exc).__name__}:{exc}"
    if not source_path.is_file():
        return None, f"source_missing:{source_path}"

    recovery = sys.modules.get(_RECOVERY_MODULE)
    if isinstance(recovery, ModuleType):
        cls = getattr(recovery, "NIJAApexStrategyV71", None)
        if cls is not None:
            _RECOVERED_APEX_CLASS = cls
            _bind_apex_class(cls)
            return cls, _RECOVERY_MODULE

    try:
        spec = importlib.util.spec_from_file_location(_RECOVERY_MODULE, source_path)
        if spec is None or spec.loader is None:
            return None, "recovery_spec_missing"
        recovery = importlib.util.module_from_spec(spec)
        sys.modules[_RECOVERY_MODULE] = recovery
        try:
            spec.loader.exec_module(recovery)
        except BaseException:
            if sys.modules.get(_RECOVERY_MODULE) is recovery:
                sys.modules.pop(_RECOVERY_MODULE, None)
            raise
        cls = getattr(recovery, "NIJAApexStrategyV71", None)
        if cls is None:
            return None, "recovery_class_missing"
        _RECOVERED_APEX_CLASS = cls
        _bind_apex_class(cls)
        LOGGER.critical(
            "APEX_CLASS_V97B_RECOVERED marker=%s source=%s poisoned_module_replaced=false class=%s",
            MARKER,
            source_path,
            getattr(cls, "__name__", type(cls).__name__),
        )
        return cls, _RECOVERY_MODULE
    except BaseException as exc:
        LOGGER.critical(
            "APEX_CLASS_V97B_RECOVERY_FAILED marker=%s error=%s:%s fail_closed=true diagnostics=%s",
            MARKER,
            type(exc).__name__,
            exc,
            _apex_module_diagnostics(),
            exc_info=True,
        )
        return None, f"recovery_failed:{type(exc).__name__}:{exc}"


def _patch_apex_wiring(module: ModuleType) -> bool:
    current = getattr(module, "_resolve_apex_class", None)
    if not callable(current):
        return False
    if getattr(current, _APEX_ATTR, False):
        return True

    @wraps(current)
    def resolve_apex_class_v97():
        loaded, loaded_from = _loaded_apex_class()
        if loaded is not None:
            _bind_apex_class(loaded)
            return loaded, loaded_from

        # A partial canonical module is exactly the production failure mode. Do
        # not call the legacy canonical->flat resolver first: its flat fallback
        # can recurse through compatibility import hooks. Recover directly from
        # the source adjacent to the wiring module instead.
        if _partial_apex_module_present():
            LOGGER.warning(
                "APEX_CLASS_V97B_PARTIAL_MODULE_DETECTED marker=%s wiring_module=%s diagnostics=%s",
                MARKER,
                getattr(module, "__name__", "<unknown>"),
                _apex_module_diagnostics(),
            )
            recovered, recovery_source = _recover_apex_class_from_source(module)
            if recovered is not None:
                return recovered, recovery_source
            return None, f"partial_module_recovery_failed:{recovery_source}"

        try:
            cls, source = current()
        except RecursionError as exc:
            cls, source = None, f"legacy_resolver_recursion:{exc}"
        except Exception as exc:
            cls, source = None, f"legacy_resolver_error:{type(exc).__name__}:{exc}"
        if cls is not None:
            _bind_apex_class(cls)
            return cls, source

        recovered, recovery_source = _recover_apex_class_from_source(module)
        if recovered is not None:
            return recovered, recovery_source
        return None, f"{source}; {recovery_source}"

    setattr(resolve_apex_class_v97, _APEX_ATTR, True)
    setattr(resolve_apex_class_v97, "__wrapped__", current)
    module._resolve_apex_class = resolve_apex_class_v97
    LOGGER.critical(
        "APEX_CLASS_V97B_RESOLVER_PATCHED marker=%s module=%s file=%s alias_independent=true recovery_preempts_partial=true",
        MARKER,
        getattr(module, "__name__", "<unknown>"),
        getattr(module, "__file__", None),
    )
    return True


def _set_fetch_proof(broker: Any, value: Any, error: str | None = None) -> None:
    try:
        setattr(broker, "_startup_position_sync_fetch_ok", value)
        setattr(broker, "_startup_position_sync_error", error)
    except Exception:
        pass


def _invalidate_position_sync(broker: Any, *, reason: str) -> None:
    try:
        setattr(broker, "_startup_position_sync_adopted", False)
    except Exception:
        pass
    _set_fetch_proof(broker, False, str(reason or "position_fetch_failed"))
    os.environ["NIJA_POSITION_SYNC_ACTIVATION_READY"] = "0"
    os.environ["NIJA_POSITION_SYNC_DISPATCH_READY"] = "0"


def _wrap_position_fetch(method: Callable[..., Any], broker_label: str) -> Callable[..., Any]:
    @wraps(method)
    def get_positions_v97(self: Any, *args: Any, **kwargs: Any):
        try:
            depth = int(getattr(self, "_startup_position_sync_fetch_depth", 0) or 0)
        except Exception:
            depth = 0
        try:
            setattr(self, "_startup_position_sync_fetch_depth", depth + 1)
        except Exception:
            pass
        if depth == 0:
            _set_fetch_proof(self, None, None)
        try:
            result = method(self, *args, **kwargs)
            # A nested v97 wrapper may have observed a real failure that an
            # outer compatibility wrapper converted to []. Never overwrite that
            # failure proof merely because the outer call returned normally.
            if getattr(self, "_startup_position_sync_fetch_ok", None) is not False:
                _set_fetch_proof(self, True, None)
            return result
        except BaseException as exc:
            _invalidate_position_sync(self, reason=f"{type(exc).__name__}:{exc}")
            LOGGER.warning(
                "POSITION_SYNC_V97_INVALIDATED marker=%s broker=%s error=%s:%s stale_success_reused=false",
                MARKER,
                broker_label,
                type(exc).__name__,
                exc,
            )
            raise
        finally:
            try:
                if depth > 0:
                    setattr(self, "_startup_position_sync_fetch_depth", depth)
                else:
                    setattr(self, "_startup_position_sync_fetch_depth", 0)
            except Exception:
                pass

    setattr(get_positions_v97, _POSITION_ATTR, True)
    setattr(get_positions_v97, "__wrapped__", method)
    return get_positions_v97


def _patch_position_broker_module(module: ModuleType) -> bool:
    changed = False
    for name, cls in tuple(vars(module).items()):
        if not isinstance(cls, type) or "broker" not in str(name).lower():
            continue
        current = getattr(cls, "get_positions", None)
        if not callable(current) or getattr(current, _POSITION_ATTR, False):
            continue
        cls.get_positions = _wrap_position_fetch(current, str(name).replace("Broker", "").lower())
        changed = True
    if changed:
        LOGGER.critical(
            "POSITION_SYNC_V97_BROKERS_PATCHED marker=%s module=%s failure_invalidates_previous_success=true nested_failure_proof=true",
            MARKER,
            getattr(module, "__name__", "<unknown>"),
        )
    return changed


def _patch_startup_sync_module(module: ModuleType) -> bool:
    current = getattr(module, "_adopt_broker_positions", None)
    if not callable(current):
        return False
    if getattr(current, _POSITION_SYNC_ATTR, False):
        return True

    @wraps(current)
    def adopt_broker_positions_v97(broker: Any, broker_name: str, eps: Any) -> int:
        _set_fetch_proof(broker, None, None)
        result = int(current(broker, broker_name, eps) or 0)
        if getattr(broker, "_startup_position_sync_fetch_ok", None) is False:
            reason = str(getattr(broker, "_startup_position_sync_error", "position_fetch_failed") or "position_fetch_failed")
            _invalidate_position_sync(broker, reason=reason)
            LOGGER.critical(
                "POSITION_SYNC_V97B_MASKED_FAILURE_REJECTED marker=%s broker=%s error=%s empty_or_cached_snapshot_not_authoritative=true activation_blocked=true",
                MARKER,
                broker_name,
                reason,
            )
        return result

    setattr(adopt_broker_positions_v97, _POSITION_SYNC_ATTR, True)
    setattr(adopt_broker_positions_v97, "__wrapped__", current)
    module._adopt_broker_positions = adopt_broker_positions_v97
    LOGGER.critical(
        "POSITION_SYNC_V97B_STARTUP_GUARD_PATCHED marker=%s module=%s masked_failure_rejection=true",
        MARKER,
        getattr(module, "__name__", "<unknown>"),
    )
    return True


def _writer_runtime() -> Any:
    for name in ("bot.entrypoint_writer_authority", "entrypoint_writer_authority"):
        module = sys.modules.get(name)
        getter = getattr(module, "get_entrypoint_writer_authority", None) if isinstance(module, ModuleType) else None
        if callable(getter):
            try:
                return getter()
            except Exception:
                continue
    try:
        module = importlib.import_module("bot.entrypoint_writer_authority")
        getter = getattr(module, "get_entrypoint_writer_authority", None)
        return getter() if callable(getter) else None
    except Exception:
        return None


def _record_scan_started() -> None:
    runtime = _writer_runtime()
    recorder = getattr(runtime, "record_scan_started", None) if runtime is not None else None
    if callable(recorder):
        recorder()


def _record_scan_complete() -> None:
    runtime = _writer_runtime()
    recorder = getattr(runtime, "record_scan_complete", None) if runtime is not None else None
    if callable(recorder):
        recorder()


def _patch_core_loop(module: ModuleType) -> bool:
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "run_scan_phase", None)
    if not callable(current):
        return False
    if getattr(current, _SCAN_ATTR, False):
        return True

    @wraps(current)
    def run_scan_phase_v97(self: Any, *args: Any, **kwargs: Any):
        _record_scan_started()
        result = current(self, *args, **kwargs)
        _record_scan_complete()
        return result

    setattr(run_scan_phase_v97, _SCAN_ATTR, True)
    setattr(run_scan_phase_v97, "__wrapped__", current)
    cls.run_scan_phase = run_scan_phase_v97
    LOGGER.critical(
        "SCAN_LIFECYCLE_V97_PATCHED marker=%s module=%s scan_phase_is_authoritative=true",
        MARKER,
        getattr(module, "__name__", "<unknown>"),
    )
    return True


def _patch_loaded() -> bool:
    changed = False
    for _name, module in _iter_loaded_modules(
        names=(
            "bot.trading_strategy_apex_wiring_patch",
            "trading_strategy_apex_wiring_patch",
            "nija_trading_strategy_apex_wiring_patch",
        ),
        basenames=(_WIRING_BASENAME,),
    ):
        changed = _patch_apex_wiring(module) or changed
    for _name, module in _iter_loaded_modules(
        names=("bot.broker_manager", "broker_manager"),
        basenames=("broker_manager.py",),
    ):
        changed = _patch_position_broker_module(module) or changed
    for _name, module in _iter_loaded_modules(
        names=("bot.startup_position_sync", "startup_position_sync"),
        basenames=(_STARTUP_SYNC_BASENAME,),
    ):
        changed = _patch_startup_sync_module(module) or changed
    for _name, module in _iter_loaded_modules(
        names=("bot.nija_core_loop", "nija_core_loop"),
        basenames=("nija_core_loop.py",),
    ):
        changed = _patch_core_loop(module) or changed
    return changed


def _relevant_import(name: Any) -> bool:
    text = str(name or "")
    return any(
        token in text
        for token in (
            "trading_strategy_apex_wiring_patch",
            "broker_manager",
            "startup_position_sync",
            "empty_position_sync_success_patch",
            "kraken_equity_runtime_patch",
            "nija_core_loop",
        )
    )


def install_import_hook() -> bool:
    with _LOCK:
        _patch_loaded()

        if not getattr(importlib, _IMPORT_MODULE_FLAG, False):
            original_import_module = importlib.import_module

            @wraps(original_import_module)
            def import_module_v97(name: str, package: str | None = None):
                result = original_import_module(name, package)
                if _relevant_import(name):
                    _patch_loaded()
                return result

            importlib.import_module = import_module_v97  # type: ignore[assignment]
            setattr(importlib, _IMPORT_MODULE_FLAG, True)

        if not getattr(builtins, _HOOK_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                if _relevant_import(name):
                    _patch_loaded()
                return result

            builtins.__import__ = importing
            setattr(builtins, _HOOK_FLAG, True)

        os.environ["NIJA_RUNTIME_TRUTH_CONVERGENCE_V97_INSTALLED"] = "1"
        os.environ["NIJA_RUNTIME_TRUTH_CONVERGENCE_V97B_INSTALLED"] = "1"
        LOGGER.critical(
            "RUNTIME_TRUTH_CONVERGENCE_V97B_INSTALLED marker=%s apex_alias_independent=true "
            "partial_recovery_preempts_legacy=true position_failure_invalidates=true "
            "masked_position_failure_rejected=true scan_lifecycle_bridge=true safety_gates_unchanged=true",
            MARKER,
        )
        return True


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_patch_apex_wiring",
    "_patch_position_broker_module",
    "_patch_startup_sync_module",
    "_patch_core_loop",
    "_recover_apex_class_from_source",
]
