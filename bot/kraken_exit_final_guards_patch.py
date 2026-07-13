"""Final writer-authorized and cost-basis guards for Kraken account exits."""

from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Mapping

logger = logging.getLogger("nija.kraken_exit_final_guards")
_MARKER = "20260713-kraken-exit-final-guards-v1"
_ORIGINAL_IMPORT = None
_LOCK = threading.RLock()
_PATCHED: set[tuple[str, int]] = set()
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _is_exit_request(request: Any) -> bool:
    intent = str(getattr(request, "intent_type", "") or "").strip().lower()
    effect = str(getattr(request, "position_effect", "") or "").strip().lower()
    metadata = dict(getattr(request, "metadata", {}) or {})
    return intent in {"exit", "reduce"} or effect in {"close", "reduce"} or metadata.get("closing_position") is True


def _live_mode() -> bool:
    return not (
        _truthy("DRY_RUN_MODE")
        or _truthy("PAPER_MODE")
        or _truthy("APP_STORE_MODE")
        or _truthy("NIJA_APP_STORE_MODE")
    )


def _writer_authorized() -> tuple[bool, str]:
    try:
        try:
            from bot.execution_authority_context import assert_distributed_writer_authority
        except ImportError:
            from execution_authority_context import assert_distributed_writer_authority  # type: ignore[import]
        assert_distributed_writer_authority()
        return True, "distributed_writer_authority_ok"
    except Exception as exc:
        return False, str(exc)


def _unverified_cost_basis(position: Any) -> bool:
    if not isinstance(position, Mapping):
        return True
    if position.get("cost_basis_verified") is False or position.get("auto_exit_blocked") is True:
        return True
    text = " ".join(
        str(position.get(key) or "").lower()
        for key in ("entry_price_source", "exit_profile", "notes", "auto_exit_block_reason")
    )
    return any(
        token in text
        for token in (
            "unverified_cost_basis",
            "estimated_from_adoption_mark",
            "reconciliation_required",
        )
    )


def _patch_exit_decision(module: ModuleType) -> bool:
    current = getattr(module, "_exit_reason", None)
    if not callable(current) or getattr(current, "_nija_verified_cost_basis_v1", False):
        return False

    @wraps(current)
    def exit_reason(position: Any, price: float, account: str, symbol: str):
        if _unverified_cost_basis(position):
            logger.critical(
                "KRAKEN_EXIT_SKIPPED_UNVERIFIED_COST_BASIS marker=%s account=%s symbol=%s",
                _MARKER, account, symbol,
            )
            return None, 0.0, 0.0
        return current(position, price, account, symbol)

    exit_reason._nija_verified_cost_basis_v1 = True  # type: ignore[attr-defined]
    module._exit_reason = exit_reason
    logger.warning("KRAKEN_VERIFIED_COST_BASIS_EXIT_GUARD_PATCHED marker=%s", _MARKER)
    return True


def _patch_execution_gate(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "_enforce_execution_gate", None)
    if not callable(current) or getattr(current, "_nija_risk_reducing_exit_gate_v1", False):
        return False

    @wraps(current)
    def enforce_execution_gate(self: Any, request: Any, t_start: float):
        if _is_exit_request(request) and _live_mode():
            authorized, reason = _writer_authorized()
            if authorized:
                logger.critical(
                    "ACCOUNT_EXIT_STATE_GATE_BYPASSED marker=%s account=%s symbol=%s side=%s "
                    "writer_authority_verified=true broker_and_ecel_gates_preserved=true",
                    _MARKER,
                    getattr(request, "account_id", "default"),
                    getattr(request, "symbol", ""),
                    getattr(request, "side", ""),
                )
                return None
            logger.error(
                "ACCOUNT_EXIT_STATE_GATE_NOT_BYPASSED marker=%s account=%s symbol=%s reason=%s",
                _MARKER,
                getattr(request, "account_id", "default"),
                getattr(request, "symbol", ""),
                reason,
            )
        return current(self, request, t_start)

    enforce_execution_gate._nija_risk_reducing_exit_gate_v1 = True  # type: ignore[attr-defined]
    cls._enforce_execution_gate = enforce_execution_gate
    logger.warning("ACCOUNT_EXIT_WRITER_AUTHORIZED_STATE_GATE_PATCHED marker=%s", _MARKER)
    return True


def _patch_module(module: ModuleType) -> bool:
    key = (str(getattr(module, "__name__", "")), id(module))
    if key in _PATCHED:
        return True
    name = str(getattr(module, "__name__", ""))
    changed = False
    if name.endswith("kraken_all_account_exit_runtime_patch"):
        changed = _patch_exit_decision(module) or changed
    if name.endswith("execution_pipeline"):
        changed = _patch_execution_gate(module) or changed
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
    logger.critical("KRAKEN_EXIT_FINAL_GUARDS_INSTALLED marker=%s", _MARKER)


__all__ = [
    "install_import_hook",
    "_is_exit_request",
    "_unverified_cost_basis",
    "_patch_exit_decision",
    "_patch_execution_gate",
]
