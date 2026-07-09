from __future__ import annotations

import builtins
import logging
import sys
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.execution_soft_reject_classification")
_MARKER = "20260709af"
_PATCHED_ATTR = "_nija_execution_soft_reject_classification_20260709af"

_SOFT_REJECT_MARKERS = (
    "execution gate pending",
    "state_machine=emergency_stop",
    "state_machine=live_pending_confirmation",
    "state_machine=off",
    "terminal_reject_status:unfilled",
    "confirmed_order_rejected:ack_timeout",
    "ack_timeout_no_confirmed_fill",
    "dispatch_disabled",
    "runtime authority convergence lost",
    "executionauthority reject",
    "execution_authority_blocked",
    "execution_authority_runtime",
)


def _is_soft_operational_reject(error: Any) -> bool:
    text = str(error or "").strip().lower()
    return any(marker in text for marker in _SOFT_REJECT_MARKERS)


def _patch_module(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_on_order_rejected", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return bool(getattr(original, _PATCHED_ATTR, False))

    @wraps(original)
    def _on_order_rejected_soft(self: Any, request: Any, error: str, *args: Any, **kwargs: Any):
        if _is_soft_operational_reject(error):
            try:
                emit = getattr(self, "_emit_execution_rejection_telemetry", None)
                if callable(emit):
                    emit(
                        symbol=getattr(request, "symbol", "unknown"),
                        side=getattr(request, "side", "unknown"),
                        reason=error or "soft operational reject",
                    )
            except Exception:
                pass
            logger.warning(
                "EXECUTION_SOFT_REJECT_CLASSIFIED marker=%s symbol=%s side=%s error=%s action=no_ecel_systemerror",
                _MARKER,
                getattr(request, "symbol", "unknown"),
                getattr(request, "side", "unknown"),
                error,
            )
            print(
                f"[NIJA-PRINT] EXECUTION_SOFT_REJECT_CLASSIFIED marker={_MARKER} symbol={getattr(request, 'symbol', 'unknown')} action=no_ecel_systemerror",
                flush=True,
            )
            return None
        return original(self, request, error, *args, **kwargs)

    setattr(_on_order_rejected_soft, _PATCHED_ATTR, True)
    setattr(cls, "_on_order_rejected", _on_order_rejected_soft)
    logger.warning("EXECUTION_SOFT_REJECT_CLASSIFICATION_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", "unknown"))
    print(f"[NIJA-PRINT] EXECUTION_SOFT_REJECT_CLASSIFICATION_PATCHED marker={_MARKER}", flush=True)
    return True


def _patch_loaded() -> None:
    for name in ("bot.execution_pipeline", "execution_pipeline"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_module(module)
            except Exception as exc:
                logger.warning("EXECUTION_SOFT_REJECT_CLASSIFICATION_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)


def install_import_hook() -> None:
    _patch_loaded()
    if getattr(builtins, "_NIJA_EXECUTION_SOFT_REJECT_CLASSIFICATION_HOOK_20260709AF", False):
        return
    original_import = builtins.__import__

    def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if str(name).endswith("execution_pipeline") or "execution_pipeline" in str(name):
            _patch_loaded()
        return module

    builtins.__import__ = importing
    setattr(builtins, "_NIJA_EXECUTION_SOFT_REJECT_CLASSIFICATION_HOOK_20260709AF", True)
    logger.warning("EXECUTION_SOFT_REJECT_CLASSIFICATION_IMPORT_HOOK marker=%s installed=true", _MARKER)


def install() -> None:
    install_import_hook()
