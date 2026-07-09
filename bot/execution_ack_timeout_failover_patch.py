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
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default)).strip().lower() in _TRUE


def _is_ack_timeout_result(result: Any) -> bool:
    if bool(getattr(result, "success", False)):
        return False
    error = str(getattr(result, "error", "") or "").lower()
    return "ack_timeout" in error or "ack timeout" in error


def _patch_module(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_dispatch", None)
    if not callable(original) or getattr(original, _PATCHED_ATTR, False):
        return bool(getattr(original, _PATCHED_ATTR, False))

    @wraps(original)
    def _dispatch_with_ack_failover(self: Any, request: Any, t_start: float, *args: Any, **kwargs: Any):
        result = original(self, request, t_start, *args, **kwargs)
        if not _truthy("NIJA_ACK_TIMEOUT_SINGLE_ROUTER_FAILOVER", "true"):
            return result
        if not _is_ack_timeout_result(result):
            return result

        multi_router = getattr(self, "_multi_router", None)
        single_router = getattr(self, "_router", None)
        if multi_router is None or single_router is None:
            logger.warning(
                "EXECUTION_ACK_TIMEOUT_FAILOVER_UNAVAILABLE marker=%s symbol=%s multi_router=%s single_router=%s error=%s",
                _MARKER,
                getattr(request, "symbol", "unknown"),
                multi_router is not None,
                single_router is not None,
                getattr(result, "error", ""),
            )
            return result

        logger.critical(
            "EXECUTION_ACK_TIMEOUT_FAILOVER_TRIGGERED marker=%s symbol=%s side=%s size_usd=%.2f broker_hint=%s original_error=%s action=temporary_single_router_retry",
            _MARKER,
            getattr(request, "symbol", "unknown"),
            getattr(request, "side", "unknown"),
            float(getattr(request, "size_usd", 0.0) or 0.0),
            getattr(request, "preferred_broker", "") or "auto",
            getattr(result, "error", ""),
        )
        print(
            f"[NIJA-PRINT] EXECUTION_ACK_TIMEOUT_FAILOVER_TRIGGERED marker={_MARKER} symbol={getattr(request, 'symbol', 'unknown')} action=single_router_retry",
            flush=True,
        )

        try:
            setattr(self, "_multi_router", None)
            retry = original(self, request, t_start, *args, **kwargs)
        except Exception as exc:
            logger.warning(
                "EXECUTION_ACK_TIMEOUT_FAILOVER_EXCEPTION marker=%s symbol=%s err=%s",
                _MARKER,
                getattr(request, "symbol", "unknown"),
                exc,
            )
            return result
        finally:
            try:
                setattr(self, "_multi_router", multi_router)
            except Exception:
                pass

        logger.critical(
            "EXECUTION_ACK_TIMEOUT_FAILOVER_RESULT marker=%s symbol=%s success=%s broker=%s error=%s",
            _MARKER,
            getattr(request, "symbol", "unknown"),
            bool(getattr(retry, "success", False)),
            getattr(retry, "broker", "") or "unknown",
            getattr(retry, "error", "") or "",
        )
        print(
            f"[NIJA-PRINT] EXECUTION_ACK_TIMEOUT_FAILOVER_RESULT marker={_MARKER} symbol={getattr(request, 'symbol', 'unknown')} success={bool(getattr(retry, 'success', False))}",
            flush=True,
        )
        return retry

    setattr(_dispatch_with_ack_failover, _PATCHED_ATTR, True)
    setattr(cls, "_dispatch", _dispatch_with_ack_failover)
    logger.warning("EXECUTION_ACK_TIMEOUT_FAILOVER_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", "unknown"))
    print(f"[NIJA-PRINT] EXECUTION_ACK_TIMEOUT_FAILOVER_PATCHED marker={_MARKER}", flush=True)
    return True


def _patch_loaded() -> None:
    for name in ("bot.execution_pipeline", "execution_pipeline"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            try:
                _patch_module(module)
            except Exception as exc:
                logger.warning("EXECUTION_ACK_TIMEOUT_FAILOVER_PATCH_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)


def install_import_hook() -> None:
    _patch_loaded()
    if getattr(builtins, "_NIJA_EXECUTION_ACK_TIMEOUT_FAILOVER_HOOK_20260709AB", False):
        return
    original_import = builtins.__import__

    def importing(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if str(name).endswith("execution_pipeline") or "execution_pipeline" in str(name):
            _patch_loaded()
        return module

    builtins.__import__ = importing
    setattr(builtins, "_NIJA_EXECUTION_ACK_TIMEOUT_FAILOVER_HOOK_20260709AB", True)
    logger.warning("EXECUTION_ACK_TIMEOUT_FAILOVER_IMPORT_HOOK marker=%s installed=true", _MARKER)


def install() -> None:
    install_import_hook()
