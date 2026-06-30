"""Runtime telemetry hardening for ExecutionPipeline.

This patch is intentionally small and import-hook based so it does not replace
large execution files through the GitHub contents API.  It adds canonical
WARNING/ERROR telemetry and execution-journal events for every pipeline denial.
"""

from __future__ import annotations

import builtins
import logging
import time
from functools import wraps
from typing import Any

logger = logging.getLogger("nija.execution_pipeline_runtime_patch")
_PATCHED_ATTR = "__nija_execution_pipeline_deny_patch__"


def _patch_execution_pipeline(module: Any) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    result_cls = getattr(module, "PipelineResult", None)
    if not isinstance(cls, type) or getattr(cls, _PATCHED_ATTR, False):
        return bool(getattr(cls, _PATCHED_ATTR, False)) if cls is not None else False

    original = getattr(cls, "_deny", None)
    if not callable(original):
        return False

    @staticmethod
    @wraps(original)
    def _deny(request: Any, t_start: float, reason: str):
        symbol = str(getattr(request, "symbol", "?") or "?")
        side = str(getattr(request, "side", "?") or "?")
        try:
            size = float(getattr(request, "size_usd", 0.0) or 0.0)
        except Exception:
            size = 0.0
        account_id = str(getattr(request, "account_id", "default") or "default")
        broker = str(getattr(request, "preferred_broker", "") or "")
        latency_ms = (time.monotonic() - float(t_start or time.monotonic())) * 1000.0
        logger.error(
            "EXECUTION_PIPELINE_DENY symbol=%s side=%s size_usd=%.2f account=%s broker=%s reason=%s latency_ms=%.1f",
            symbol,
            side,
            size,
            account_id,
            broker or "auto",
            reason,
            latency_ms,
        )
        try:
            from bot.execution_journal import append_execution_journal_event
            append_execution_journal_event(
                "EXECUTION_PIPELINE_DENY",
                f"{account_id}:{broker or 'auto'}:{symbol}:{side}:{int(time.time() * 1000)}",
                {
                    "symbol": symbol,
                    "side": side,
                    "size_usd": size,
                    "account_id": account_id,
                    "broker": broker or "auto",
                    "reason": str(reason),
                    "latency_ms": latency_ms,
                },
            )
        except Exception as exc:
            logger.debug("execution deny journal append skipped: %s", exc)
        if result_cls is not None:
            try:
                return result_cls(
                    success=False,
                    symbol=symbol,
                    side=side,
                    size_usd=size,
                    error=str(reason),
                    latency_ms=latency_ms,
                )
            except Exception:
                pass
        return original(request, t_start, reason)

    setattr(cls, "_deny", _deny)
    setattr(cls, _PATCHED_ATTR, True)
    logger.warning("EXECUTION_PIPELINE_DENY_TELEMETRY_PATCHED")
    return True


def install_import_hook() -> None:
    import sys

    for name in ("bot.execution_pipeline", "execution_pipeline"):
        module = sys.modules.get(name)
        if module is not None and _patch_execution_pipeline(module):
            return

    if getattr(builtins, "_NIJA_EXECUTION_PIPELINE_PATCH_HOOK_INSTALLED", False):
        return

    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if name.endswith("execution_pipeline"):
            try:
                if _patch_execution_pipeline(module):
                    builtins.__import__ = original_import
                    setattr(builtins, "_NIJA_EXECUTION_PIPELINE_PATCH_HOOK_INSTALLED", False)
            except Exception as exc:
                logger.warning("execution pipeline runtime patch failed: %s", exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_EXECUTION_PIPELINE_PATCH_HOOK_INSTALLED", True)
