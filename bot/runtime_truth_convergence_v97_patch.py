"""Converge live runtime truth after strategy/readiness bootstrap.

Production deployment 39560bb showed three stale-truth failures after the
canonical strategy-integrity guards were enabled:

* ``bot.nija_apex_strategy_v71`` existed in ``sys.modules`` but was a partial
  module object without ``NIJAApexStrategyV71``.  The wiring repair repeatedly
  observed ``class_missing`` and the live cycle remained blocked with
  ``strategy.apex is None``.
* position fetches that timed out could leave a previous
  ``_startup_position_sync_adopted=True`` latch intact, so v96 could publish
  ``position_sync_ready=true`` even though the current reconciliation failed.
* the writer scan-start watchdog was never handed the actual core scan lifecycle,
  so it could emit ``SCAN_STARTED_DEADLINE_EXCEEDED`` while the core thread was
  alive and real trading cycles were already executing.

v97 repairs only those truth handoffs.  It does not lower risk thresholds,
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
from typing import Any, Callable, Optional

LOGGER = logging.getLogger("nija.runtime_truth_convergence_v97")
MARKER = "20260815-runtime-truth-convergence-v97"
_LOCK = threading.RLock()
_HOOK_FLAG = "_NIJA_RUNTIME_TRUTH_CONVERGENCE_V97_IMPORT_HOOK"
_APEX_ATTR = "_nija_runtime_truth_convergence_v97_apex"
_POSITION_ATTR = "_nija_runtime_truth_convergence_v97_position"
_SCAN_ATTR = "_nija_runtime_truth_convergence_v97_scan"
_RECOVERY_MODULE = "bot._nija_apex_strategy_v71_recovery_v97"
_RECOVERED_APEX_CLASS: Any = None


def _bind_apex_class(cls: Any) -> None:
    """Publish a recovered class onto already-loaded canonical module surfaces."""
    if cls is None:
        return
    for name in ("bot.nija_apex_strategy_v71", "nija_apex_strategy_v71"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                setattr(module, "NIJAApexStrategyV71", cls)
            except Exception:
                pass
    for name in ("bot.trading_strategy", "trading_strategy"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                setattr(module, "NIJAApexStrategyV71", cls)
                setattr(module, "_APEX_AVAILABLE", True)
            except Exception:
                pass


def _recover_apex_class_from_source(wiring_module: ModuleType) -> tuple[Any | None, str]:
    """Recover the canonical v7.1 class without replacing a partial module object."""
    global _RECOVERED_APEX_CLASS
    if _RECOVERED_APEX_CLASS is not None:
        _bind_apex_class(_RECOVERED_APEX_CLASS)
        return _RECOVERED_APEX_CLASS, _RECOVERY_MODULE

    for name in ("bot.nija_apex_strategy_v71", "nija_apex_strategy_v71"):
        module = sys.modules.get(name)
        cls = getattr(module, "NIJAApexStrategyV71", None) if isinstance(module, ModuleType) else None
        if cls is not None:
            _RECOVERED_APEX_CLASS = cls
            _bind_apex_class(cls)
            return cls, name

    try:
        source_path = Path(str(getattr(wiring_module, "__file__", "") or "")).resolve().parent / "nija_apex_strategy_v71.py"
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
            "APEX_CLASS_V97_RECOVERED marker=%s source=%s poisoned_module_replaced=false class=%s",
            MARKER,
            source_path,
            getattr(cls, "__name__", type(cls).__name__),
        )
        return cls, _RECOVERY_MODULE
    except BaseException as exc:
        LOGGER.critical(
            "APEX_CLASS_V97_RECOVERY_FAILED marker=%s error=%s:%s fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
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
        cls, source = current()
        if cls is not None:
            return cls, source
        recovered, recovery_source = _recover_apex_class_from_source(module)
        if recovered is not None:
            return recovered, recovery_source
        return None, f"{source}; {recovery_source}"

    setattr(resolve_apex_class_v97, _APEX_ATTR, True)
    setattr(resolve_apex_class_v97, "__wrapped__", current)
    module._resolve_apex_class = resolve_apex_class_v97
    LOGGER.critical(
        "APEX_CLASS_V97_RESOLVER_PATCHED marker=%s module=%s partial_module_recovery=true",
        MARKER,
        getattr(module, "__name__", "<unknown>"),
    )
    return True


def _invalidate_position_sync(broker: Any, *, reason: str) -> None:
    try:
        setattr(broker, "_startup_position_sync_adopted", False)
        setattr(broker, "_startup_position_sync_error", str(reason or "position_fetch_failed"))
    except Exception:
        pass
    os.environ["NIJA_POSITION_SYNC_ACTIVATION_READY"] = "0"
    os.environ["NIJA_POSITION_SYNC_DISPATCH_READY"] = "0"


def _wrap_position_fetch(method: Callable[..., Any], broker_label: str) -> Callable[..., Any]:
    @wraps(method)
    def get_positions_v97(self: Any, *args: Any, **kwargs: Any):
        try:
            return method(self, *args, **kwargs)
        except BaseException as exc:
            _invalidate_position_sync(
                self,
                reason=f"{type(exc).__name__}:{exc}",
            )
            LOGGER.warning(
                "POSITION_SYNC_V97_INVALIDATED marker=%s broker=%s error=%s:%s stale_success_reused=false",
                MARKER,
                broker_label,
                type(exc).__name__,
                exc,
            )
            raise

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
            "POSITION_SYNC_V97_BROKERS_PATCHED marker=%s module=%s failure_invalidates_previous_success=true",
            MARKER,
            getattr(module, "__name__", "<unknown>"),
        )
    return changed


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
    seen: set[int] = set()
    for name in ("bot.trading_strategy_apex_wiring_patch", "trading_strategy_apex_wiring_patch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            changed = _patch_apex_wiring(module) or changed
    for name in ("bot.broker_manager", "broker_manager"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            changed = _patch_position_broker_module(module) or changed
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            seen.add(id(module))
            changed = _patch_core_loop(module) or changed
    return changed


def install_import_hook() -> bool:
    with _LOCK:
        _patch_loaded()
        if not getattr(builtins, _HOOK_FLAG, False):
            original_import = builtins.__import__

            @wraps(original_import)
            def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
                result = original_import(name, globals, locals, fromlist, level)
                text = str(name or "")
                if any(token in text for token in (
                    "trading_strategy_apex_wiring_patch",
                    "broker_manager",
                    "nija_core_loop",
                )):
                    _patch_loaded()
                return result

            builtins.__import__ = importing
            setattr(builtins, _HOOK_FLAG, True)

        os.environ["NIJA_RUNTIME_TRUTH_CONVERGENCE_V97_INSTALLED"] = "1"
        LOGGER.critical(
            "RUNTIME_TRUTH_CONVERGENCE_V97_INSTALLED marker=%s apex_partial_recovery=true "
            "position_failure_invalidates=true scan_lifecycle_bridge=true safety_gates_unchanged=true",
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
    "_patch_core_loop",
    "_recover_apex_class_from_source",
]
