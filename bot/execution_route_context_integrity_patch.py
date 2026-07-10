from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
import uuid
from dataclasses import is_dataclass, replace
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.execution_route_context_integrity")
_MARKER = "20260709at"
_HOOK = "_NIJA_EXECUTION_ROUTE_CONTEXT_HOOK_20260709AT"
_PATCHED = "_nija_execution_route_context_20260709at"


def _broker(value: Any) -> str:
    text = str(getattr(value, "value", value) or "").lower().strip().split(":", 1)[0]
    compact = text.replace("_", "").replace("-", "").replace(" ", "")
    for name in ("coinbase", "kraken", "okx", "alpaca", "binance"):
        if name in compact:
            return name
    return text


def _symbol(value: Any) -> str:
    return str(value or "").strip().upper().replace("/", "-").replace("_", "-").replace(":", "-")


def _native_symbol(value: Any, broker_name: str) -> str:
    symbol = _symbol(value)
    if "-" not in symbol:
        return symbol
    base, quote = symbol.rsplit("-", 1)
    if broker_name == "okx" and quote == "USD":
        return f"{base}-USDT"
    if broker_name in {"coinbase", "kraken"} and quote in {"USDT", "USDC"}:
        return f"{base}-USD"
    return symbol


def _client_broker(client: Any) -> str:
    if client is None:
        return ""
    for value in (
        getattr(getattr(client, "broker_type", None), "value", None),
        getattr(client, "broker_type", None), getattr(client, "broker_name", None),
        getattr(client, "exchange", None), client.__class__.__name__, client.__class__.__module__,
    ):
        name = _broker(value)
        if name in {"coinbase", "kraken", "okx", "alpaca", "binance"}:
            return name
    return ""


def _authoritative_broker(request: Any) -> str:
    metadata = dict(getattr(request, "metadata", {}) or {})
    route = metadata.get("execution_route")
    for value in (
        getattr(route, "selected_broker", None), getattr(request, "preferred_broker", None),
        metadata.get("preferred_broker"), metadata.get("selected_broker"),
        metadata.get("execution_broker"), metadata.get("dispatch_broker"), metadata.get("broker_name"),
    ):
        name = _broker(value)
        if name:
            return name
    return ""


def _replace_request(request: Any, **changes: Any) -> Any:
    try:
        if is_dataclass(request):
            return replace(request, **changes)
    except Exception:
        pass
    for key, value in changes.items():
        try:
            setattr(request, key, value)
        except Exception:
            pass
    return request


def _resolve_client(pipeline: Any, broker_name: str) -> Any:
    for module_name in ("bot.final_stage_venue_routing_repair_patch", "final_stage_venue_routing_repair_patch"):
        try:
            module = sys.modules.get(module_name) or __import__(module_name, fromlist=["*"])
            resolver = getattr(module, "_resolve_live_client", None)
            if callable(resolver):
                for seed in (getattr(pipeline, "_multi_router", None), getattr(pipeline, "_router", None), pipeline):
                    client = resolver(seed, broker_name)
                    if _client_broker(client) == broker_name:
                        return client
        except Exception:
            pass
    return None


def _repair_request(pipeline: Any, request: Any) -> tuple[Any, str]:
    broker_name = _authoritative_broker(request)
    if not broker_name:
        return request, ""
    metadata = dict(getattr(request, "metadata", {}) or {})
    old_symbol = _symbol(getattr(request, "symbol", ""))
    new_symbol = _native_symbol(old_symbol, broker_name)
    for key in ("preferred_broker", "broker_name", "selected_broker", "execution_broker",
                "dispatch_broker", "symbol_broker", "balance_broker"):
        metadata[key] = broker_name
    route = metadata.get("execution_route")
    try:
        metadata["execution_route"] = replace(route, selected_broker=broker_name, symbol=new_symbol)
    except Exception:
        pass
    client = metadata.get("broker_client") or metadata.get("broker_adapter")
    if _client_broker(client) != broker_name:
        metadata.pop("broker_client", None)
        metadata.pop("broker_adapter", None)
        resolved = _resolve_client(pipeline, broker_name)
        if resolved is not None:
            metadata["broker_client"] = resolved
    request_id = str(getattr(request, "request_id", "") or metadata.get("request_id") or uuid.uuid4())
    intent_id = str(getattr(request, "intent_id", "") or metadata.get("intent_id") or request_id)
    metadata.update({"request_id": request_id, "intent_id": intent_id, "route_consistency_marker": _MARKER})
    repaired = _replace_request(
        request, symbol=new_symbol, preferred_broker=broker_name,
        request_id=request_id, intent_id=intent_id, metadata=metadata,
    )
    if old_symbol != new_symbol or (_client_broker(client) and _client_broker(client) != broker_name):
        logger.warning(
            "EXECUTION_ROUTE_CONTEXT_REPAIRED marker=%s broker=%s symbol=%s->%s client=%s",
            _MARKER, broker_name, old_symbol, new_symbol, _client_broker(client) or "none",
        )
    return repaired, broker_name


def _patch(module: ModuleType) -> bool:
    cls = getattr(module, "ExecutionPipeline", None)
    result_cls = getattr(module, "PipelineResult", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_dispatch", None)
    if not callable(original) or getattr(original, _PATCHED, False):
        return bool(getattr(original, _PATCHED, False))

    @wraps(original)
    def dispatch(self: Any, request: Any, t_start: float, *args: Any, **kwargs: Any):
        request, expected = _repair_request(self, request)
        intent_id = str(getattr(request, "intent_id", "") or "")
        key = f"{expected}:{intent_id}" if intent_id else ""
        lock = getattr(self, "_nija_route_lock", None) or threading.Lock()
        setattr(self, "_nija_route_lock", lock)
        inflight = getattr(self, "_nija_route_inflight", None)
        if inflight is None:
            inflight = set()
            setattr(self, "_nija_route_inflight", inflight)
        if key:
            with lock:
                if key in inflight:
                    message = f"duplicate in-flight dispatch blocked: {key}"
                    logger.critical("EXECUTION_DUPLICATE_INFLIGHT_BLOCKED marker=%s key=%s", _MARKER, key)
                    if result_cls is not None:
                        return result_cls(
                            success=False, symbol=request.symbol, side=request.side,
                            size_usd=float(request.size_usd or 0), broker=expected, error=message,
                        )
                    return None
                inflight.add(key)
        try:
            result = original(self, request, t_start, *args, **kwargs)
        finally:
            if key:
                with lock:
                    inflight.discard(key)
        actual = _broker(getattr(result, "broker", ""))
        if expected and actual and actual != expected:
            logger.critical(
                "EXECUTION_ROUTE_MISMATCH marker=%s expected=%s actual=%s success=%s symbol=%s action=no_retry",
                _MARKER, expected, actual, bool(getattr(result, "success", False)), request.symbol,
            )
            if not bool(getattr(result, "success", False)):
                try:
                    result.error = f"route mismatch expected={expected} actual={actual}; {result.error}"
                except Exception:
                    pass
        return result

    setattr(dispatch, _PATCHED, True)
    setattr(cls, "_dispatch", dispatch)
    logger.warning("EXECUTION_ROUTE_CONTEXT_PATCHED marker=%s module=%s", _MARKER, module.__name__)
    return True


def _patch_loaded() -> None:
    for name in ("bot.execution_pipeline", "execution_pipeline"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            _patch(module)


def install_import_hook() -> None:
    os.environ["NIJA_ACK_TIMEOUT_SINGLE_ROUTER_FAILOVER"] = "false"
    _patch_loaded()
    if getattr(builtins, _HOOK, False):
        return
    original_import = builtins.__import__

    def importing(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        if "execution_pipeline" in str(name):
            _patch_loaded()
        return module

    builtins.__import__ = importing
    setattr(builtins, _HOOK, True)
    logger.warning("EXECUTION_ROUTE_CONTEXT_INSTALL_COMPLETE marker=%s", _MARKER)


def install() -> None:
    install_import_hook()
