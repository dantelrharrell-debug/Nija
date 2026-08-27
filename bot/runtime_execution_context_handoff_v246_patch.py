"""Preserve call-scoped execution authority across the pipeline ACK worker.

Production on 2026-08-27 proved the startup heartbeat was independently verified,
passed the pipeline authority gate, and armed the bounded v233 terminal grant.  The
pipeline then dispatched routing work through ``ThreadPoolExecutor``.  Python
ContextVars are not inherited by new executor threads, so the broker terminal saw a
plain BOOT lifecycle and rejected the same verified startup probe.

v246 repairs only that handoff.  The execution-pipeline module receives a local
``concurrent`` proxy whose ThreadPoolExecutor captures ``contextvars.copy_context()``
for each submitted call and runs that call inside the copied context.  The stdlib
executor is not modified globally.  No startup-probe context is created here: an
ordinary order with no verified context remains ordinary in the worker.

Lifecycle state, writer/lease authority, nonce, risk, capital, broker health, kill
switch, ECEL, minimum notional, exchange acknowledgement, fill proof, and activation
proof are unchanged and remain fail closed.
"""
from __future__ import annotations

import concurrent as _stdlib_concurrent
import contextvars
import importlib
import logging
import os
from types import ModuleType
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_execution_context_handoff_v246")
MARKER = "20260827-runtime-execution-context-handoff-v246"
_FLAG = "NIJA_RUNTIME_EXECUTION_CONTEXT_HANDOFF_V246_READY"
_PATCH_ATTR = "_nija_runtime_execution_context_handoff_v246"


class _ContextPropagatingThreadPoolExecutor(_stdlib_concurrent.futures.ThreadPoolExecutor):
    """ThreadPoolExecutor that copies only the caller's existing ContextVars."""

    def submit(self, fn: Callable[..., Any], /, *args: Any, **kwargs: Any):
        ctx = contextvars.copy_context()
        return super().submit(ctx.run, fn, *args, **kwargs)


class _FuturesProxy:
    def __init__(self, original: Any) -> None:
        self._original = original
        self.ThreadPoolExecutor = _ContextPropagatingThreadPoolExecutor

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)


class _ConcurrentProxy:
    def __init__(self, original: ModuleType) -> None:
        self._original = original
        self.futures = _FuturesProxy(original.futures)
        setattr(self, _PATCH_ATTR, True)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._original, name)


def _execution_pipeline_module() -> ModuleType:
    return importlib.import_module("bot.execution_pipeline")


def _patch_execution_pipeline(module: ModuleType | None = None) -> bool:
    target = module or _execution_pipeline_module()
    current = getattr(target, "concurrent", None)
    if current is None or not hasattr(current, "futures"):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    # Keep the replacement local to bot.execution_pipeline.  In particular, do
    # not mutate concurrent.futures.ThreadPoolExecutor process-wide.
    setattr(target, "concurrent", _ConcurrentProxy(current))
    patched = getattr(target, "concurrent", None)
    return bool(
        getattr(patched, _PATCH_ATTR, False)
        and getattr(getattr(patched, "futures", None), "ThreadPoolExecutor", None)
        is _ContextPropagatingThreadPoolExecutor
        and _stdlib_concurrent.futures.ThreadPoolExecutor
        is not _ContextPropagatingThreadPoolExecutor
    )


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
    except Exception:
        return False
    required = getattr(manifest, "_REQUIRED_FLAGS", None)
    installers = getattr(manifest, "_INSTALLERS", None)
    if not isinstance(required, dict):
        return False
    required["runtime_execution_context_handoff_v246"] = _FLAG
    own = ("bot.runtime_execution_context_handoff_v246_patch", "install_import_hook")
    if isinstance(installers, tuple) and own not in installers:
        manifest._INSTALLERS = tuple(installers) + (own,)
    return True


def install() -> bool:
    try:
        pipeline_ready = _patch_execution_pipeline()
        manifest_ready = _register_manifest()
        ready = bool(pipeline_ready and manifest_ready)
    except Exception as exc:
        LOGGER.error(
            "RUNTIME_EXECUTION_CONTEXT_HANDOFF_V246_INSTALL_ERROR marker=%s error=%s:%s "
            "trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        ready = False
    os.environ[_FLAG] = "1" if ready else "0"
    if ready:
        LOGGER.critical(
            "RUNTIME_EXECUTION_CONTEXT_HANDOFF_V246 marker=%s ready=true "
            "pipeline_thread_context_propagated=true stdlib_executor_unchanged=true "
            "startup_probe_context_created=false existing_context_only=true ordinary_orders_unchanged=true "
            "lifecycle_writer_nonce_risk_capital_broker_health_killswitch_ecel_min_notional_fill_gates_unchanged=true "
            "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
            MARKER,
        )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_patch_execution_pipeline",
    "_register_manifest",
    "_ContextPropagatingThreadPoolExecutor",
]
