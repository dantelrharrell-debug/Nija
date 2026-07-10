from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.operator_emergency_stop_preexec_clear")
_MARKER = "20260710t"
_HOOK_FLAG = "_NIJA_OPERATOR_EMERGENCY_STOP_PREEXEC_CLEAR_HOOK_20260710T"
_EXEC_PATCH_ATTR = "_nija_operator_emergency_clear_pre_execute_20260710t"
_KILL_PATCH_ATTR = "_nija_operator_emergency_clear_kill_switch_20260710t"
_CLEAR_LOCK = threading.Lock()
_TRUTHY = {"1", "true", "yes", "on", "y", "enabled"}


def _truthy_env(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in _TRUTHY


def _clear_patch_module() -> ModuleType:
    try:
        from bot import operator_emergency_stop_clear_patch as clear_patch
    except ImportError:
        import operator_emergency_stop_clear_patch as clear_patch  # type: ignore[import]
    return clear_patch


def _operator_clear_candidate_present() -> tuple[bool, str]:
    """Return true only when an actual operator/emergency latch may need clearing.

    KillSwitch.is_active() is called frequently throughout startup and normal
    execution. Running filesystem/env clear logic on every probe amplifies any
    detector defect and can recursively flood authority-convergence diagnostics.
    Normal fail-closed state (OFF with authority=0) is deliberately not a clear
    candidate.
    """

    if _truthy_env("NIJA_OPERATOR_CLEAR_EMERGENCY_STOP"):
        return True, "explicit_operator_request"

    try:
        clear_patch = _clear_patch_module()
    except Exception as exc:
        return False, f"clear_patch_unavailable:{type(exc).__name__}"

    for getter_name, reason in (
        ("_kill_files", "kill_file_present"),
        ("_state_files", "state_file_present"),
    ):
        getter = getattr(clear_patch, getter_name, None)
        if callable(getter):
            try:
                if getter():
                    return True, reason
            except Exception:
                # The canonical run_once path owns detailed path-check logging.
                pass

    detector = getattr(clear_patch, "_env_only_stop_present", None)
    if callable(detector):
        try:
            present, detail = detector()
            if bool(present):
                return True, f"env_latch:{detail}"
            return False, f"no_emergency_latch:{detail}"
        except Exception as exc:
            return False, f"env_probe_failed:{type(exc).__name__}"

    # Fail closed: without a canonical detector, do not mutate emergency state
    # from a hot-path is_active() probe.
    return False, "canonical_detector_missing"


def _run_operator_clear(source: str) -> int:
    candidate, candidate_reason = _operator_clear_candidate_present()
    if not candidate:
        return 0

    # Kill-switch probes can arrive concurrently. Only one thread may perform
    # the mutating clear/convergence sequence; all others continue to the
    # original safety check without waiting.
    if not _CLEAR_LOCK.acquire(blocking=False):
        return 0

    try:
        try:
            clear_patch = _clear_patch_module()
            run_once = getattr(clear_patch, "run_once")
            result = int(run_once() or 0)
        except Exception as exc:
            logger.warning(
                "OPERATOR_EMERGENCY_STOP_PREEXEC_CLEAR_FAILED marker=%s source=%s candidate=%s err=%s",
                _MARKER,
                source,
                candidate_reason,
                exc,
            )
            return 0

        if result > 0:
            try:
                try:
                    from bot.runtime_authority_convergence_repair_patch import converge_runtime_authority
                except ImportError:
                    from runtime_authority_convergence_repair_patch import converge_runtime_authority  # type: ignore[import]
                converge_runtime_authority(f"operator_preexec_clear:{source}")
            except Exception as exc:
                logger.warning(
                    "OPERATOR_EMERGENCY_STOP_PREEXEC_CONVERGENCE_FAILED marker=%s source=%s err=%s",
                    _MARKER,
                    source,
                    exc,
                )
            logger.critical(
                "OPERATOR_EMERGENCY_STOP_PREEXEC_CLEAR_APPLIED marker=%s source=%s candidate=%s cleared=%s",
                _MARKER,
                source,
                candidate_reason,
                result,
            )
            print(
                f"[NIJA-PRINT] OPERATOR_EMERGENCY_STOP_PREEXEC_CLEAR_APPLIED marker={_MARKER} source={source} cleared={result}",
                flush=True,
            )
        return result
    finally:
        _CLEAR_LOCK.release()


def _patch_kill_switch_module(module: ModuleType) -> bool:
    cls = getattr(module, "KillSwitch", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "is_active", None)
    if not callable(original) or getattr(original, _KILL_PATCH_ATTR, False):
        return bool(getattr(original, _KILL_PATCH_ATTR, False))

    @wraps(original)
    def is_active_with_operator_clear(self: Any, *args: Any, **kwargs: Any):
        _run_operator_clear("kill_switch.is_active")
        return original(self, *args, **kwargs)

    setattr(is_active_with_operator_clear, _KILL_PATCH_ATTR, True)
    setattr(cls, "is_active", is_active_with_operator_clear)
    logger.warning(
        "OPERATOR_EMERGENCY_STOP_PREEXEC_KILL_SWITCH_PATCHED marker=%s module=%s",
        _MARKER,
        getattr(module, "__name__", "unknown"),
    )
    print(
        f"[NIJA-PRINT] OPERATOR_EMERGENCY_STOP_PREEXEC_KILL_SWITCH_PATCHED marker={_MARKER}",
        flush=True,
    )
    return True


def _patch_execution_module(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionEngine", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "execute_entry", None)
    if not callable(original) or getattr(original, _EXEC_PATCH_ATTR, False):
        return bool(getattr(original, _EXEC_PATCH_ATTR, False))

    @wraps(original)
    def execute_entry_with_operator_clear(self: Any, *args: Any, **kwargs: Any):
        _run_operator_clear("pre_execute_entry")
        return original(self, *args, **kwargs)

    setattr(execute_entry_with_operator_clear, _EXEC_PATCH_ATTR, True)
    setattr(cls, "execute_entry", execute_entry_with_operator_clear)
    logger.warning(
        "OPERATOR_EMERGENCY_STOP_PREEXEC_EXECUTION_PATCHED marker=%s module=%s",
        _MARKER,
        getattr(module, "__name__", "unknown"),
    )
    print(
        f"[NIJA-PRINT] OPERATOR_EMERGENCY_STOP_PREEXEC_EXECUTION_PATCHED marker={_MARKER}",
        flush=True,
    )
    return True


def _patch_loaded() -> None:
    for name in ("bot.kill_switch", "kill_switch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_kill_switch_module(module)
            except Exception as exc:
                logger.warning(
                    "OPERATOR_EMERGENCY_STOP_PREEXEC_KILL_PATCH_FAILED marker=%s module=%s err=%s",
                    _MARKER,
                    name,
                    exc,
                )
    for name in ("bot.execution_engine", "execution_engine", "bot.execution", "execution"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_execution_module(module)
            except Exception as exc:
                logger.warning(
                    "OPERATOR_EMERGENCY_STOP_PREEXEC_EXEC_PATCH_FAILED marker=%s module=%s err=%s",
                    _MARKER,
                    name,
                    exc,
                )


def install_import_hook() -> None:
    _run_operator_clear("startup")
    _patch_loaded()
    if getattr(builtins, _HOOK_FLAG, False):
        return
    original_import = builtins.__import__

    def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        text = str(name)
        if text.endswith("kill_switch") or text.endswith("execution_engine") or text.endswith("execution"):
            _patch_loaded()
        return module

    builtins.__import__ = importing
    setattr(builtins, _HOOK_FLAG, True)
    logger.warning("OPERATOR_EMERGENCY_STOP_PREEXEC_CLEAR_INSTALL_COMPLETE marker=%s", _MARKER)


def install() -> None:
    install_import_hook()
