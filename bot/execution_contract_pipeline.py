"""Pipeline and router enforcement for NIJA's final execution contract."""
from __future__ import annotations

import logging
import time
from functools import wraps
from types import ModuleType
from typing import Any

from .execution_contract_authority import repair_snapshot
from .execution_contract_primitives import (
    LAST_ACK, MARKER, PINNED_AUTHORITY, broker_name, extract_order_id,
    freeze_request, normalize_symbol, number, pop_ack, store_ack,
)

logger = logging.getLogger("nija.execution_contract_pipeline")


def _failure(module: ModuleType, request: Any, started: float, error: str, broker: str = "") -> Any:
    cls = getattr(module, "PipelineResult", None)
    if callable(cls):
        return cls(
            success=False, symbol=normalize_symbol(getattr(request, "symbol", "")),
            side=str(getattr(request, "side", "")), size_usd=number(getattr(request, "size_usd", 0.0)),
            broker=broker, error=error, latency_ms=(time.monotonic() - started) * 1000.0,
        )
    return None


def patch_pipeline(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False
    reader = getattr(module, "runtime_authority_snapshot", None)
    if callable(reader) and not getattr(reader, "_nija_pin_20260710a", False):
        original_reader = reader
        @wraps(reader)
        def pinned_reader(*args: Any, **kwargs: Any):
            pinned = PINNED_AUTHORITY.get()
            return pinned if pinned is not None else original_reader(*args, **kwargs)
        pinned_reader._nija_pin_20260710a = True
        pinned_reader._nija_original = original_reader
        module.runtime_authority_snapshot = pinned_reader
    else:
        original_reader = getattr(reader, "_nija_original", reader)

    current_execute = getattr(cls, "execute", None)
    if callable(current_execute) and not getattr(current_execute, "_nija_contract_20260710a", False):
        @wraps(current_execute)
        def execute(self: Any, request: Any, *args: Any, **kwargs: Any):
            started = time.monotonic()
            frozen, broker, error = freeze_request(request)
            if error:
                logger.critical("FINAL_EXECUTION_CONTRACT_BLOCK marker=%s stage=freeze broker=%s reason=%s", MARKER, broker or "unknown", error)
                return _failure(module, request, started, error, broker)
            try:
                snapshot = original_reader() if callable(original_reader) else None
            except Exception as exc:
                logger.warning("authority snapshot read failed marker=%s err=%s", MARKER, exc)
                snapshot = None
            token = PINNED_AUTHORITY.set(repair_snapshot(snapshot) if snapshot is not None else None)
            LAST_ACK.set(None)
            try:
                return current_execute(self, frozen, *args, **kwargs)
            finally:
                PINNED_AUTHORITY.reset(token)
        execute._nija_contract_20260710a = True
        cls.execute = execute

    current_dispatch = getattr(cls, "_dispatch", None)
    if callable(current_dispatch) and not getattr(current_dispatch, "_nija_dispatch_contract_20260710a", False):
        @wraps(current_dispatch)
        def dispatch(self: Any, request: Any, started: float, *args: Any, **kwargs: Any):
            frozen, broker, error = freeze_request(request)
            if error:
                return _failure(module, request, started, error, broker)
            result = current_dispatch(self, frozen, started, *args, **kwargs)
            if result is None:
                return _failure(module, frozen, started, "broker_dispatch_returned_none", broker)
            actual = broker_name(getattr(result, "broker", ""))
            if actual and actual != broker:
                return _failure(module, frozen, started, f"execution_route_mismatch:selected={broker}:actual={actual}", broker)
            ack = pop_ack(frozen)
            order_id = extract_order_id(result) or extract_order_id(ack.get("order_id"))
            fill_price = number(getattr(result, "fill_price", 0.0)) or number(ack.get("fill_price"))
            filled_size = number(getattr(result, "filled_size_usd", 0.0)) or number(ack.get("filled_size_usd"))
            if bool(getattr(result, "success", False)):
                if not order_id:
                    return _failure(module, frozen, started, f"broker_ack_missing_real_order_id:broker={broker}", broker)
                if fill_price <= 0 or filled_size <= 0:
                    return _failure(module, frozen, started, f"broker_ack_unconfirmed_fill:broker={broker}:order_id={order_id}", broker)
                setattr(result, "order_id", order_id)
                setattr(result, "broker", broker)
                setattr(result, "fill_price", fill_price)
                setattr(result, "filled_size_usd", filled_size)
                LAST_ACK.set({"order_id": order_id, "broker": broker, "fill_price": fill_price, "filled_size_usd": filled_size})
                logger.critical("BROKER_ORDER_ACK_VERIFIED marker=%s broker=%s order_id=%s fill_price=%.8f filled_size_usd=%.2f", MARKER, broker, order_id, fill_price, filled_size)
            return result
        dispatch._nija_dispatch_contract_20260710a = True
        cls._dispatch = dispatch
    logger.warning("FINAL_EXECUTION_PIPELINE_CONTRACT_PATCHED marker=%s", MARKER)
    return True


def patch_router(module: ModuleType) -> bool:
    changed = False
    for class_name, method in (("MultiBrokerExecutionRouter", "route"), ("ExecutionRouter", "execute")):
        cls = getattr(module, class_name, None)
        current = getattr(cls, method, None) if isinstance(cls, type) else None
        if not callable(current) or getattr(current, "_nija_ack_20260710a", False):
            continue
        @wraps(current)
        def wrapped(self: Any, request: Any, *args: Any, __current=current, **kwargs: Any):
            result = __current(self, request, *args, **kwargs)
            if bool(getattr(result, "success", False)):
                store_ack(request, result)
            return result
        wrapped._nija_ack_20260710a = True
        setattr(cls, method, wrapped)
        changed = True
    return changed
