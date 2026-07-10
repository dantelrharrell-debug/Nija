from __future__ import annotations

import builtins
import logging
import sys
import time
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.ecel_invalid_order_fail_closed")
_MARKER = "20260709as"
_HOOK_FLAG = "_NIJA_ECEL_INVALID_ORDER_FAIL_CLOSED_HOOK_20260709AS"
_REJECT_PATCH_ATTR = "_nija_ecel_invalid_order_reject_fail_closed_20260709as"
_EXECUTE_PATCH_ATTR = "_nija_ecel_invalid_order_execute_fail_closed_20260709as"


def _is_ecel_invalid_order_error(error: Any) -> bool:
    text = str(error or "").lower()
    return "ecel failure" in text and "invalid order escaped" in text


def _pipeline_result(module: ModuleType, request: Any, t_start: float, reason: str) -> Any:
    result_cls = getattr(module, "PipelineResult", None)
    if callable(result_cls):
        try:
            return result_cls(
                success=False,
                symbol=str(getattr(request, "symbol", "") or ""),
                side=str(getattr(request, "side", "") or ""),
                size_usd=float(getattr(request, "size_usd", 0.0) or 0.0),
                error=reason,
                latency_ms=(time.monotonic() - t_start) * 1000.0,
            )
        except Exception:
            pass
    return None


def _patch_execution_pipeline(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False
    patched = False

    original_reject = getattr(cls, "_on_order_rejected", None)
    if callable(original_reject) and not getattr(original_reject, _REJECT_PATCH_ATTR, False):
        @wraps(original_reject)
        def _on_order_rejected_fail_closed(self: Any, request: Any, error: str) -> None:
            try:
                return original_reject(self, request, error)
            except SystemError as exc:
                if not _is_ecel_invalid_order_error(exc):
                    raise
                logger.critical(
                    "ECEL_INVALID_ORDER_FAIL_CLOSED marker=%s surface=on_order_rejected symbol=%s side=%s error=%s action=return_rejected_result_no_retry",
                    _MARKER,
                    getattr(request, "symbol", ""),
                    getattr(request, "side", ""),
                    error,
                )
                print(
                    f"[NIJA-PRINT] ECEL_INVALID_ORDER_FAIL_CLOSED marker={_MARKER} symbol={getattr(request, 'symbol', '')} action=return_rejected_result_no_retry",
                    flush=True,
                )
                return None

        setattr(_on_order_rejected_fail_closed, _REJECT_PATCH_ATTR, True)
        setattr(cls, "_on_order_rejected", _on_order_rejected_fail_closed)
        patched = True

    original_execute = getattr(cls, "execute", None)
    if callable(original_execute) and not getattr(original_execute, _EXECUTE_PATCH_ATTR, False):
        @wraps(original_execute)
        def _execute_fail_closed(self: Any, request: Any, *args: Any, **kwargs: Any):
            t_start = time.monotonic()
            try:
                return original_execute(self, request, *args, **kwargs)
            except SystemError as exc:
                if not _is_ecel_invalid_order_error(exc):
                    raise
                reason = "ECEL invalid order rejected before broker dispatch: invalid order escaped"
                logger.critical(
                    "ECEL_INVALID_ORDER_FAIL_CLOSED marker=%s surface=execute symbol=%s side=%s size_usd=%.2f error=%s action=fail_closed_no_retry",
                    _MARKER,
                    getattr(request, "symbol", ""),
                    getattr(request, "side", ""),
                    float(getattr(request, "size_usd", 0.0) or 0.0),
                    exc,
                )
                result = _pipeline_result(module, request, t_start, reason)
                if result is not None:
                    return result
                return False

        setattr(_execute_fail_closed, _EXECUTE_PATCH_ATTR, True)
        setattr(cls, "execute", _execute_fail_closed)
        patched = True

    if patched:
        logger.warning("ECEL_INVALID_ORDER_FAIL_CLOSED_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", "unknown"))
        print(f"[NIJA-PRINT] ECEL_INVALID_ORDER_FAIL_CLOSED_PATCHED marker={_MARKER}", flush=True)
    return patched


def _patch_loaded() -> None:
    for name in ("bot.execution_pipeline", "execution_pipeline"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_execution_pipeline(module)
            except Exception as exc:
                logger.warning("ECEL_INVALID_ORDER_FAIL_CLOSED_PATCH_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)


def install_import_hook() -> None:
    _patch_loaded()
    if getattr(builtins, _HOOK_FLAG, False):
        return
    original_import = builtins.__import__

    def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        text = str(name)
        if text.endswith("execution_pipeline") or text in {"bot.execution_pipeline", "execution_pipeline"}:
            _patch_loaded()
        return module

    builtins.__import__ = importing
    setattr(builtins, _HOOK_FLAG, True)
    logger.warning("ECEL_INVALID_ORDER_FAIL_CLOSED_INSTALL_COMPLETE marker=%s", _MARKER)


def install() -> None:
    install_import_hook()
