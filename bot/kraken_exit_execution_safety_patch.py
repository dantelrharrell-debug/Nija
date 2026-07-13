"""Preserve downstream execution safety while bypassing entry-only exit gates."""

from __future__ import annotations

import builtins
import logging
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.kraken_exit_execution_safety")
_MARKER = "20260713-kraken-exit-execution-safety-v1"
_ORIGINAL_IMPORT = None
_LOCK = threading.RLock()
_PATCHED: set[tuple[str, int]] = set()
_EXIT_EXECUTION_LOCK = threading.RLock()


def _is_exit_request(request: Any) -> bool:
    intent = str(getattr(request, "intent_type", "") or "").strip().lower()
    effect = str(getattr(request, "position_effect", "") or "").strip().lower()
    metadata = dict(getattr(request, "metadata", {}) or {})
    return intent in {"exit", "reduce"} or effect in {"close", "reduce"} or metadata.get("closing_position") is True


def _patch_execution_pipeline(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "execute", None)
    if not callable(current) or getattr(current, "_nija_exit_safe_gate_split_v2", False):
        return False

    # The earlier all-account patch wraps the canonical execute method and stores
    # it through functools.wraps. Replace that broad wrapper rather than stacking
    # another layer that would still disable the downstream guard internally.
    original = getattr(current, "__wrapped__", None)
    if not (
        getattr(current, "_nija_exit_entry_gate_split_v1", False)
        and callable(original)
    ):
        original = current

    @wraps(original)
    def execute(self: Any, request: Any):
        if not _is_exit_request(request):
            return original(self, request)
        with _EXIT_EXECUTION_LOCK:
            bypass_names = (
                "_pre_trade_risk_engine",
                "_allocation_clamp",
                "_throttler",
            )
            saved = {name: getattr(self, name, None) for name in bypass_names}
            observer = getattr(self, "_execution_observer", None)
            downstream = getattr(self, "_downstream_guard", None)
            try:
                for name in bypass_names:
                    setattr(self, name, None)
                logger.critical(
                    "ACCOUNT_EXIT_ENTRY_GATES_BYPASSED_SAFELY marker=%s account=%s symbol=%s "
                    "execution_observer_preserved=%s downstream_guard_preserved=%s",
                    _MARKER,
                    getattr(request, "account_id", "default"),
                    getattr(request, "symbol", ""),
                    observer is not None,
                    downstream is not None,
                )
                return original(self, request)
            finally:
                for name, value in saved.items():
                    setattr(self, name, value)

    execute._nija_exit_safe_gate_split_v2 = True  # type: ignore[attr-defined]
    execute._nija_exit_entry_gate_split_v1 = True  # type: ignore[attr-defined]
    cls.execute = execute
    logger.warning("ACCOUNT_EXIT_DOWNSTREAM_SAFETY_PRESERVED marker=%s", _MARKER)
    return True


def _patch_module(module: ModuleType) -> bool:
    key = (str(getattr(module, "__name__", "")), id(module))
    if key in _PATCHED:
        return True
    changed = False
    if str(getattr(module, "__name__", "")).endswith("execution_pipeline"):
        changed = _patch_execution_pipeline(module)
    if changed:
        _PATCHED.add(key)
    return changed


def _patch_loaded() -> None:
    for module in tuple(sys.modules.values()):
        if isinstance(module, ModuleType):
            try:
                _patch_module(module)
            except Exception:
                continue


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT
    _patch_loaded()
    with _LOCK:
        if _ORIGINAL_IMPORT is not None:
            return
        _ORIGINAL_IMPORT = builtins.__import__
        local = threading.local()

        def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
            module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)  # type: ignore[misc]
            if getattr(local, "active", False):
                return module
            local.active = True
            try:
                _patch_loaded()
            finally:
                local.active = False
            return module

        builtins.__import__ = guarded_import  # type: ignore[assignment]
    _patch_loaded()
    logger.critical("KRAKEN_EXIT_EXECUTION_SAFETY_INSTALLED marker=%s", _MARKER)


__all__ = ["install_import_hook", "_patch_execution_pipeline"]
