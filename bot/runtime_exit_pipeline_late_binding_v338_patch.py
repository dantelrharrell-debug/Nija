"""Canonical exit pipeline late binding v338.

During writer startup the protective-exit stack can import
``pipeline_order_submitter`` while ``bot.execution_pipeline`` is still inside a
circular import.  The submitter intentionally falls back to
``PipelineRequest=None`` / ``get_execution_pipeline=None`` on ImportError, but
those globals were previously sticky for the life of the process.  A verified
profit exit could therefore retry forever as ``ExecutionPipeline unavailable``
even after the canonical pipeline had fully loaded.

v338 wraps the submitter with a lazy, lock-protected rebind.  Before every market
order it checks the two canonical references; if either is missing it imports
``bot.execution_pipeline`` and binds only the real ``PipelineRequest`` class and
real ``get_execution_pipeline`` callable.  If the canonical module is still not
complete, submission fails exactly as before and the exit scanner retries later.

No alternate/direct broker path is introduced.  Writer, authority, ECEL, risk,
capability, minimum-order, acknowledgement and fill-confirmation gates remain
unchanged.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_exit_pipeline_late_binding_v338")
MARKER = "20260901-runtime-exit-pipeline-late-binding-v338"
RELEASE_ID = "20260901-runtime-convergence-v338"
_READY_FLAG = "NIJA_RUNTIME_EXIT_PIPELINE_LATE_BINDING_V338_READY"
_PATCH_ATTR = "_nija_exit_pipeline_late_binding_v338"
_INSTALL_FLAG = "_NIJA_RUNTIME_EXIT_PIPELINE_LATE_BINDING_V338"
_LOCK = threading.RLock()
_BIND_LOCK = threading.RLock()


def _late_bind(submitter: Any) -> tuple[bool, str]:
    request_cls = getattr(submitter, "PipelineRequest", None)
    getter = getattr(submitter, "get_execution_pipeline", None)
    if request_cls is not None and callable(getter):
        return True, "already_bound"

    with _BIND_LOCK:
        request_cls = getattr(submitter, "PipelineRequest", None)
        getter = getattr(submitter, "get_execution_pipeline", None)
        if request_cls is not None and callable(getter):
            return True, "bound_by_peer"
        try:
            pipeline = importlib.import_module("bot.execution_pipeline")
        except Exception as exc:
            return False, f"pipeline_import:{type(exc).__name__}:{exc}"
        request_cls = getattr(pipeline, "PipelineRequest", None)
        getter = getattr(pipeline, "get_execution_pipeline", None)
        if request_cls is None or not callable(getter):
            return False, "canonical_pipeline_symbols_incomplete"
        submitter.PipelineRequest = request_cls
        submitter.get_execution_pipeline = getter
        LOGGER.critical(
            "EXIT_PIPELINE_V338_REBOUND marker=%s canonical_module=bot.execution_pipeline "
            "pipeline_request_bound=true getter_bound=true direct_broker_fallback=false "
            "safety_gates_bypassed=false",
            MARKER,
        )
        return True, "canonical_pipeline_rebound"


def _patch_submitter() -> bool:
    submitter = importlib.import_module("bot.pipeline_order_submitter")
    current = getattr(submitter, "submit_market_order_via_pipeline", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def late_bound_submit(*args: Any, **kwargs: Any):
        bound, reason = _late_bind(submitter)
        if not bound:
            symbol = str(kwargs.get("symbol") or (args[1] if len(args) > 1 else "") or "")
            side = str(kwargs.get("side") or (args[2] if len(args) > 2 else "") or "")
            LOGGER.warning(
                "EXIT_PIPELINE_V338_DEFERRED marker=%s symbol=%s side=%s reason=%s "
                "direct_broker_fallback=false retryable=true safety_gates_bypassed=false",
                MARKER, symbol, side, reason,
            )
            return {
                "status": "error",
                "error": "ExecutionPipeline unavailable",
                "detail": reason,
                "symbol": symbol,
                "side": side,
            }
        return current(*args, **kwargs)

    setattr(late_bound_submit, _PATCH_ATTR, True)
    setattr(late_bound_submit, "__wrapped__", current)
    submitter.submit_market_order_via_pipeline = late_bound_submit
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_exit_pipeline_late_binding_v338"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    with _LOCK:
        if getattr(builtins, _INSTALL_FLAG, False) and os.environ.get(_READY_FLAG) == "1":
            return True
        try:
            if os.environ.get("NIJA_RUNTIME_PROTECTIVE_EXIT_AUTHORITY_BRIDGE_V337_READY") != "1":
                raise RuntimeError("v337_not_ready")
            patched = _patch_submitter()
            manifest = _register_manifest()
            ready = bool(patched and manifest)
        except Exception as exc:
            ready = False
            LOGGER.exception(
                "RUNTIME_EXIT_PIPELINE_LATE_BINDING_V338_INSTALL_FAILED marker=%s error=%s:%s "
                "trading_fail_closed=true direct_broker_fallback=false safety_gates_bypassed=false",
                MARKER, type(exc).__name__, exc,
            )
        os.environ[_READY_FLAG] = "1" if ready else "0"
        setattr(builtins, _INSTALL_FLAG, ready)
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_EXIT_PIPELINE_LATE_BINDING_V338_%s marker=%s ready=%s "
            "canonical_pipeline_only=true circular_import_recovery=true lazy_rebind=true "
            "direct_broker_fallback=false writer_authority_ecel_risk_capability_minimum_order_ack_fill_gates_unchanged=true "
            "forced_exit=false safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "RELEASE_ID", "install", "install_import_hook", "_late_bind"]
