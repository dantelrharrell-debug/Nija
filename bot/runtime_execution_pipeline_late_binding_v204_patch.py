"""Recover late ExecutionPipeline binding and heartbeat ECEL price hints (v204).

Production proved that the heartbeat scheduler, position sync and canonical order
submitter were all live, but ``pipeline_order_submitter`` could retain stale
ExecutionPipeline symbols from an import cycle.  v204 re-resolves those symbols
from the canonical execution_pipeline module at order-call time.

A later production capture proved the next heartbeat blocker: the canonical
submitter reached ExecutionPipeline with a quote-sized HEARTBEAT_TRADE request,
but ``price_hint_usd`` was ``None``.  ECEL correctly rejected that request with
``PRICE_HINT_REQUIRED`` because a current price is required to compile quote
notional into exchange-valid base quantity.

This revision preserves ECEL's fail-closed contract.  It wraps only the cached
``PipelineRequest`` constructor used by ``pipeline_order_submitter``.  For
HEARTBEAT_TRADE / HEARTBEAT_TRADE_CLOSE requests whose price hint is missing, it
asks the already-selected broker for ``get_current_price(symbol)`` and supplies
that positive live value to the original PipelineRequest constructor.  If the
lookup is unavailable, raises, or returns a non-positive value, the hint remains
missing and ECEL rejects exactly as before.

No broker fallback is added. Writer authority, nonce, kill switch, risk, capital,
position reconciliation, throttling, broker routing, minimum notional, order
acknowledgement and fill verification remain owned by the existing
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
_REQUEST_FACTORY_ATTR = "_nija_heartbeat_price_hint_v204"
_LOCK = threading.RLock()
_HEARTBEAT_STRATEGIES = {"HEARTBEAT_TRADE", "HEARTBEAT_TRADE_CLOSE"}


def _positive_float(value: Any) -> float | None:
    try:
        parsed = float(value)
    except Exception:
        return None
    if parsed <= 0.0 or parsed != parsed:
        return None
    return parsed


def _heartbeat_price_hint_from_request_kwargs(kwargs: dict[str, Any]) -> float | None:
    """Resolve a positive broker price only for canonical heartbeat requests."""
    strategy = str(kwargs.get("strategy") or "").strip().upper()
    if strategy not in _HEARTBEAT_STRATEGIES:
        return None
    if _positive_float(kwargs.get("price_hint_usd")) is not None:
        return _positive_float(kwargs.get("price_hint_usd"))

    metadata = kwargs.get("metadata")
    broker = metadata.get("broker_client") if isinstance(metadata, dict) else None
    symbol = str(kwargs.get("symbol") or "").strip()
    getter = getattr(broker, "get_current_price", None) if broker is not None else None
    if not symbol or not callable(getter):
        LOGGER.warning(
            "HEARTBEAT_PRICE_HINT_V204_UNAVAILABLE marker=%s strategy=%s symbol=%s "
            "reason=current_price_getter_missing ecel_fail_closed=true",
            MARKER,
            strategy or "unknown",
            symbol or "unknown",
        )
        return None

    try:
        price = _positive_float(getter(symbol))
    except Exception as exc:
        LOGGER.warning(
            "HEARTBEAT_PRICE_HINT_V204_UNAVAILABLE marker=%s strategy=%s symbol=%s "
            "reason=current_price_error error=%s:%s ecel_fail_closed=true",
            MARKER,
            strategy,
            symbol,
            type(exc).__name__,
            exc,
        )
        return None

    if price is None:
        LOGGER.warning(
            "HEARTBEAT_PRICE_HINT_V204_UNAVAILABLE marker=%s strategy=%s symbol=%s "
            "reason=current_price_non_positive ecel_fail_closed=true",
            MARKER,
            strategy,
            symbol,
        )
        return None

    LOGGER.critical(
        "HEARTBEAT_PRICE_HINT_V204_RESOLVED marker=%s strategy=%s symbol=%s price=%.8f "
        "source=selected_broker_current_price ecel_contract_unchanged=true "
        "execution_authority_granted=false proof_fabricated=false forced_trade=false "
        "safety_gates_bypassed=false",
        MARKER,
        strategy,
        symbol,
        price,
    )
    return price


def _wrap_pipeline_request_constructor(request_cls: Any) -> Any:
    """Return a callable that delegates to the real PipelineRequest class."""
    if request_cls is None or getattr(request_cls, _REQUEST_FACTORY_ATTR, False):
        return request_cls

    def _pipeline_request_with_heartbeat_price(*args: Any, **kwargs: Any) -> Any:
        if kwargs and _positive_float(kwargs.get("price_hint_usd")) is None:
            price = _heartbeat_price_hint_from_request_kwargs(kwargs)
            if price is not None:
                kwargs = dict(kwargs)
                kwargs["price_hint_usd"] = price
        return request_cls(*args, **kwargs)

    setattr(_pipeline_request_with_heartbeat_price, _REQUEST_FACTORY_ATTR, True)
    setattr(_pipeline_request_with_heartbeat_price, "_nija_original_pipeline_request", request_cls)
    return _pipeline_request_with_heartbeat_price


def _resolve_pipeline_symbols(submitter: ModuleType) -> bool:
    """Refresh cached pipeline symbols and preserve heartbeat price hydration."""
    current_request = getattr(submitter, "PipelineRequest", None)
    current_getter = getattr(submitter, "get_execution_pipeline", None)
    if current_request is not None and callable(current_getter):
        if not getattr(current_request, _REQUEST_FACTORY_ATTR, False):
            setattr(submitter, "PipelineRequest", _wrap_pipeline_request_constructor(current_request))
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

    setattr(submitter, "PipelineRequest", _wrap_pipeline_request_constructor(request_cls))
    setattr(submitter, "get_execution_pipeline", getter)
    LOGGER.critical(
        "EXECUTION_PIPELINE_LATE_BIND_V204_RECOVERED marker=%s canonical_module=%s "
        "pipeline_request_rebound=true getter_rebound=true heartbeat_price_hint_guarded=true "
        "direct_broker_fallback=false "
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

        if not _resolve_pipeline_symbols(submitter):
            os.environ[_READY_FLAG] = "0"
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
        request_guard = getattr(submitter, "PipelineRequest", None)
        ready = bool(
            callable(installed)
            and getattr(installed, _PATCH_ATTR, False)
            and callable(request_guard)
            and getattr(request_guard, _REQUEST_FACTORY_ATTR, False)
        )

        # TradingStrategy imports the submit helper by value. If it was already
        # imported before v204 installed, repoint only that module-global helper
        # to the guarded canonical submitter. Future imports receive it directly.
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
            "heartbeat_price_hint_from_selected_broker=true ecel_contract_unchanged=true "
            "execution_proof_fabricated=false execution_authority_granted=false forced_activation=false "
            "writer_nonce_risk_killswitch_capital_position_order_fill_gates_unchanged=true "
            "safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_resolve_pipeline_symbols",
    "_heartbeat_price_hint_from_request_kwargs",
    "_wrap_pipeline_request_constructor",
]
