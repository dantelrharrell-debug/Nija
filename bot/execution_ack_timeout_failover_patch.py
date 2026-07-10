from __future__ import annotations

import builtins
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.execution_ack_timeout_failover")
_MARKER = "20260709ab"
_PATCHED_ATTR = "_nija_execution_ack_timeout_failover_20260709ab"


def _is_ack_timeout_result(result: Any) -> bool:
    if bool(getattr(result, "success", False)):
        return False
    error = str(getattr(result, "error", "") or "").lower()
    return "ack_timeout" in error or "ack timeout" in error


def _mark_uncertain(request: Any) -> None:
    try:
        metadata = dict(getattr(request, "metadata", {}) or {})
        metadata["ack_state"] = "uncertain"
        metadata["ack_retry_suppressed"] = True
        metadata["ack_safety_marker"] = _MARKER
        setattr(request, "metadata", metadata)
    except Exception:
        pass


def _patch_module(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_dispatch", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return bool(getattr(original, _PATCHED_ATTR, False))

    @wraps(original)
    def _dispatch_with_safe_ack_handling(self: Any, request: Any, t_start: float, *args: Any, **kwargs: Any):
        # Submit exactly once. An ACK timeout is an unknown broker state, not proof
        # that the exchange rejected the order. Retrying through another router or
        # broker can create duplicate live positions.
        result = original(self, request, t_start, *args, **kwargs)
        if not _is_ack_timeout_result(result):
            return result

        _mark_uncertain(request)
        broker = str(getattr(request, "preferred_broker", "") or getattr(result, "broker", "") or "unknown")
        intent_id = str(getattr(request, "intent_id", "") or getattr(request, "request_id", "") or "unknown")
        logger.critical(
            "EXECUTION_ACK_TIMEOUT_UNCERTAIN_NO_RETRY marker=%s symbol=%s side=%s size_usd=%.2f "
            "broker=%s intent_id=%s action=do_not_resubmit_reconcile_next_cycle",
            _MARKER,
            getattr(request, "symbol", "unknown"),
            getattr(request, "side", "unknown"),
            float(getattr(request, "size_usd", 0.0) or 0.0),
            broker,
            intent_id,
        )
        print(
            f"[NIJA-PRINT] EXECUTION_ACK_TIMEOUT_UNCERTAIN_NO_RETRY marker={_MARKER} "
            f"symbol={getattr(request, 'symbol', 'unknown')} broker={broker} intent_id={intent_id}",
            flush=True,
        )
        try:
            old_error = str(getattr(result, "error", "") or "ack timeout")
            setattr(result, "error", f"{old_error}; uncertain broker state; retry suppressed")
        except Exception:
            pass
        return result

    setattr(_dispatch_with_safe_ack_handling, _PATCHED_ATTR, True)
    setattr(cls, "_dispatch", _dispatch_with_safe_ack_handling)
    logger.warning("EXECUTION_ACK_TIMEOUT_SAFE_HANDLING_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", "unknown"))
    print(f"[NIJA-PRINT] EXECUTION_ACK_TIMEOUT_SAFE_HANDLING_PATCHED marker={_MARKER}", flush=True)
    return True


def _patch_loaded() -> None:
    for name in ("bot.execution_pipeline", "execution_pipeline"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_module(module)
            except Exception as exc:
                logger.warning("EXECUTION_ACK_TIMEOUT_SAFE_HANDLING_PATCH_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)


def install_import_hook() -> None:
    # Keep the legacy environment variable for compatibility, but force the unsafe
    # cross-router retry path off. Broker reconciliation must happen before a retry.
    os.environ["NIJA_ACK_TIMEOUT_SINGLE_ROUTER_FAILOVER"] = "false"
    _patch_loaded()
    flag = "_NIJA_EXECUTION_ACK_TIMEOUT_FAILOVER_HOOK_20260709AB"
    if getattr(builtins, flag, False):
        return
    original_import = builtins.__import__

    def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if str(name).endswith("execution_pipeline") or "execution_pipeline" in str(name):
            _patch_loaded()
        return module

    builtins.__import__ = importing
    setattr(builtins, flag, True)
    logger.warning("EXECUTION_ACK_TIMEOUT_SAFE_HANDLING_IMPORT_HOOK marker=%s installed=true", _MARKER)


def install() -> None:
    install_import_hook()
