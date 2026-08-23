"""Recover a late ExecutionPipeline binding for canonical order submission (v204).

Production proved that the heartbeat scheduler, position sync and canonical order
submitter were all live, but ``pipeline_order_submitter`` returned
``ExecutionPipeline unavailable``.  That return is only possible when its
module-level import cached ``PipelineRequest`` or ``get_execution_pipeline`` as
``None``.  During startup an import cycle can temporarily make those names
unavailable even though ``bot.execution_pipeline`` finishes loading later.

v204 fixes only that stale import binding.  At order-call time, if the cached
symbols are missing, it re-resolves them from the canonical execution_pipeline
module and then delegates to the unchanged submitter.  If the canonical module
is still unavailable, the original fail-closed error is preserved.

No broker fallback is added.  Writer authority, nonce, kill switch, risk,
capital, position reconciliation, throttling, broker routing, minimum notional,
order acknowledgement and fill verification remain owned by the existing
ExecutionPipeline path.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any

LOGGER = logging.getLogger("nija.runtime_execution_pipeline_late_binding_v204")
MARKER = "20260823-execution-pipeline-late-binding-v204"
_READY_FLAG = "NIJA_EXECUTION_PIPELINE_LATE_BINDING_V204_READY"
_PATCH_ATTR = "_nija_execution_pipeline_late_binding_v204"
_LOCK = threading.RLock()


def _resolve_pipeline_symbols(submitter: ModuleType) -> bool:
    """Refresh only missing cached pipeline symbols from the canonical module."""
    current_request = getattr(submitter, "PipelineRequest", None)
    current_getter = getattr(submitter, "get_execution_pipeline", None)
    if current_request is not None and callable(current_getter):
        return True

    pipeline = None
    last_error: BaseException | None = None
    for module_name in ("bot.execution_pipeline", "execution_pipeline"):
        try:
            pipeline = importlib.import_module(module_name)
            break
        except BaseException as exc:
            last_error = exc
            continue

    if not isinstance(pipeline, ModuleType):
        LOGGER.error(
            "EXECUTION_PIPELINE_LATE_BIND_V204_UNAVAILABLE marker=%s error=%s:%s "
            "direct_broker_fallback=false trading_fail_closed=true",
            MARKER,
            type(last_error).__name__ if last_error is not None else "ImportError",
            last_error if last_error is not None else "execution_pipeline_not_importable",
        )
        return False

    request_cls = getattr(pipeline, "PipelineRequest", None)
    getter = getattr(pipeline, "get_execution_pipeline", None)
    if request_cls is None or not callable(getter):
        LOGGER.error(
            "EXECUTION_PIPELINE_LATE_BIND_V204_UNAVAILABLE marker=%s reason=canonical_symbols_missing "
            "pipeline_request=%s getter_callable=%s direct_broker_fallback=false trading_fail_closed=true",
            MARKER,
            str(request_cls is not None).lower(),
            str(callable(getter)).lower(),
        )
        return False

    setattr(submitter, "PipelineRequest", request_cls)
    setattr(submitter, "get_execution_pipeline", getter)
    LOGGER.critical(
        "EXECUTION_PIPELINE_LATE_BIND_V204_RECOVERED marker=%s canonical_module=%s "
        "pipeline_request_rebound=true getter_rebound=true direct_broker_fallback=false "
        "writer_nonce_risk_killswitch_capital_position_order_fill_gates_unchanged=true "
        "forced_activation=false safety_gates_bypassed=false",
        MARKER,
        getattr(pipeline, "__name__", "bot.execution_pipeline"),
    )
    return True


def install() -> bool:
    """Wrap the canonical submitter with idempotent late pipeline resolution."""
    with _LOCK:
        try:
            submitter = importlib.import_module("bot.pipeline_order_submitter")
        except Exception as exc:
            os.environ[_READY_FLAG] = "0"
            LOGGER.critical(
                "EXECUTION_PIPELINE_LATE_BIND_V204_INSTALL_FAILED marker=%s reason=submitter_import_failed "
                "error=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            return False

        current = getattr(submitter, "submit_market_order_via_pipeline", None)
        if not callable(current):
            os.environ[_READY_FLAG] = "0"
            LOGGER.critical(
                "EXECUTION_PIPELINE_LATE_BIND_V204_INSTALL_FAILED marker=%s reason=submitter_missing "
                "trading_fail_closed=true",
                MARKER,
            )
            return False

        if not getattr(current, _PATCH_ATTR, False):
            previous = current

            @wraps(previous)
            def _submit_with_late_pipeline_binding(*args: Any, **kwargs: Any) -> Any:
                _resolve_pipeline_symbols(submitter)
                return previous(*args, **kwargs)

            setattr(_submit_with_late_pipeline_binding, _PATCH_ATTR, True)
            setattr(submitter, "_nija_v204_previous_submit_market_order_via_pipeline", previous)
            setattr(submitter, "submit_market_order_via_pipeline", _submit_with_late_pipeline_binding)

        installed = getattr(submitter, "submit_market_order_via_pipeline", None)
        ready = bool(callable(installed) and getattr(installed, _PATCH_ATTR, False))

        # TradingStrategy imports the submit helper by value.  If it was already
        # imported before v204 installed, repoint only that module-global helper
        # to the guarded canonical submitter.  Future imports receive it directly.
        strategy_module = sys.modules.get("bot.trading_strategy") or sys.modules.get("trading_strategy")
        if isinstance(strategy_module, ModuleType) and ready:
            setattr(strategy_module, "submit_market_order_via_pipeline", installed)

        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "EXECUTION_PIPELINE_LATE_BIND_V204_INSTALL_FAILED marker=%s reason=wrapper_not_installed "
                "trading_fail_closed=true",
                MARKER,
            )
            return False

        LOGGER.critical(
            "EXECUTION_PIPELINE_LATE_BIND_V204_READY marker=%s ready=true "
            "lazy_resolution_only=true canonical_pipeline_only=true direct_broker_fallback=false "
            "execution_proof_fabricated=false execution_authority_granted=false forced_activation=false "
            "writer_nonce_risk_killswitch_capital_position_order_fill_gates_unchanged=true "
            "safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = ["MARKER", "install", "install_import_hook", "_resolve_pipeline_symbols"]
