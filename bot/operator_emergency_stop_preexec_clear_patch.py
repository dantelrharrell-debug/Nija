from __future__ import annotations

import builtins
import logging
import sys
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.operator_emergency_stop_preexec_clear")
_MARKER = "20260709ai"
_HOOK_FLAG = "_NIJA_OPERATOR_EMERGENCY_STOP_PREEXEC_CLEAR_HOOK_20260709AI"
_EXEC_PATCH_ATTR = "_nija_operator_emergency_clear_pre_execute_20260709ai"
_KILL_PATCH_ATTR = "_nija_operator_emergency_clear_kill_switch_20260709ai"


def _run_operator_clear(source: str) -> int:
    try:
        try:
            from bot.operator_emergency_stop_clear_patch import run_once
        except ImportError:
            from operator_emergency_stop_clear_patch import run_once  # type: ignore[import]
        try:
            result = int(run_once(source) or 0)
        except TypeError:
            result = int(run_once() or 0)
    except Exception as exc:
        logger.warning("OPERATOR_EMERGENCY_STOP_PREEXEC_CLEAR_FAILED marker=%s source=%s err=%s", _MARKER, source, exc)
        return 0

    if result > 0:
        try:
            try:
                from bot.runtime_authority_convergence_repair_patch import converge_runtime_authority
            except ImportError:
                from runtime_authority_convergence_repair_patch import converge_runtime_authority  # type: ignore[import]
            converge_runtime_authority(f"operator_preexec_clear:{source}")
        except Exception as exc:
            logger.warning("OPERATOR_EMERGENCY_STOP_PREEXEC_CONVERGENCE_FAILED marker=%s source=%s err=%s", _MARKER, source, exc)
        logger.critical("OPERATOR_EMERGENCY_STOP_PREEXEC_CLEAR_APPLIED marker=%s source=%s cleared=%s", _MARKER, source, result)
        print(f"[NIJA-PRINT] OPERATOR_EMERGENCY_STOP_PREEXEC_CLEAR_APPLIED marker={_MARKER} source={source} cleared={result}", flush=True)
    return result


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
    logger.warning("OPERATOR_EMERGENCY_STOP_PREEXEC_KILL_SWITCH_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", "unknown"))
    print(f"[NIJA-PRINT] OPERATOR_EMERGENCY_STOP_PREEXEC_KILL_SWITCH_PATCHED marker={_MARKER}", flush=True)
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
    logger.warning("OPERATOR_EMERGENCY_STOP_PREEXEC_EXECUTION_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", "unknown"))
    print(f"[NIJA-PRINT] OPERATOR_EMERGENCY_STOP_PREEXEC_EXECUTION_PATCHED marker={_MARKER}", flush=True)
    return True


def _patch_loaded() -> None:
    for name in ("bot.kill_switch", "kill_switch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_kill_switch_module(module)
            except Exception as exc:
                logger.warning("OPERATOR_EMERGENCY_STOP_PREEXEC_KILL_PATCH_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)
    for name in ("bot.execution_engine", "execution_engine", "bot.execution", "execution"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_execution_module(module)
            except Exception as exc:
                logger.warning("OPERATOR_EMERGENCY_STOP_PREEXEC_EXEC_PATCH_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)


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
