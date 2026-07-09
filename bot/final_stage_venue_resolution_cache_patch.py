from __future__ import annotations

import builtins
import logging
import os
import sys
import time
from functools import wraps
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.final_stage_venue_resolution_cache")
_MARKER = "20260709r"
_PATCH_ATTR = "_nija_final_stage_resolution_cache_v20260709r"
_HOOK_FLAG = "_NIJA_FINAL_STAGE_RESOLUTION_CACHE_HOOK_V20260709R"
_CACHE: dict[tuple[int, str], tuple[float, Any]] = {}
_LAST_LOG: dict[tuple[int, str], float] = {}


def _ttl() -> float:
    try:
        return max(1.0, float(os.environ.get("NIJA_FINAL_STAGE_BROKER_RESOLUTION_CACHE_TTL_S", "20") or 20.0))
    except Exception:
        return 20.0


def _norm_broker(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "").replace("_", "").replace(" ", "")
    if "kraken" in text:
        return "kraken"
    if "coinbase" in text:
        return "coinbase"
    if "okx" in text:
        return "okx"
    if "binance" in text:
        return "binance"
    return text


def _looks_live_client(client: Any, broker: str) -> bool:
    if client is None:
        return False
    name_text = " ".join(
        str(x or "")
        for x in (
            getattr(client, "name", None),
            getattr(client, "broker_name", None),
            getattr(client, "exchange", None),
            getattr(client, "venue", None),
            getattr(getattr(client, "broker_type", None), "value", None),
            client.__class__.__name__,
            client.__class__.__module__,
        )
    ).lower()
    if broker and broker not in name_text:
        return False
    if getattr(client, "connected", True) is False:
        return False
    return any(callable(getattr(client, method, None)) for method in ("place_market_order", "place_order", "execute_order", "submit_order", "get_account_balance", "get_balance"))


def _patch_router_module(module: ModuleType) -> bool:
    cls = getattr(module, "MultiBrokerExecutionRouter", None)
    if not isinstance(cls, type):
        return False
    original = getattr(cls, "_resolve_live_broker", None)
    if not callable(original) or getattr(original, _PATCH_ATTR, False):
        return bool(getattr(original, _PATCH_ATTR, False))

    @wraps(original)
    def _resolve_live_broker(self: Any, broker_name: str):
        broker = _norm_broker(broker_name)
        key = (id(self), broker)
        now = time.monotonic()
        cached = _CACHE.get(key)
        if cached is not None:
            ts, client = cached
            if now - ts <= _ttl() and _looks_live_client(client, broker):
                return client
        client = original(self, broker_name)
        if _looks_live_client(client, broker):
            _CACHE[key] = (now, client)
            last = _LAST_LOG.get(key, 0.0)
            if now - last >= _ttl():
                _LAST_LOG[key] = now
                logger.critical(
                    "FINAL_STAGE_BROKER_RESOLUTION_CACHED marker=%s broker=%s client_type=%s ttl_s=%.1f",
                    _MARKER,
                    broker,
                    type(client).__name__,
                    _ttl(),
                )
            return client
        return client

    setattr(_resolve_live_broker, _PATCH_ATTR, True)
    setattr(_resolve_live_broker, "__wrapped__", original)
    setattr(cls, "_resolve_live_broker", _resolve_live_broker)
    logger.warning("FINAL_STAGE_BROKER_RESOLUTION_CACHE_PATCHED marker=%s module=%s", _MARKER, getattr(module, "__name__", ""))
    print(f"[NIJA-PRINT] FINAL_STAGE_BROKER_RESOLUTION_CACHE_PATCHED marker={_MARKER}", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name, module in list(sys.modules.items()):
        if isinstance(module, ModuleType) and name.endswith("multi_broker_execution_router"):
            try:
                patched = _patch_router_module(module) or patched
            except Exception as exc:
                logger.warning("FINAL_STAGE_BROKER_RESOLUTION_CACHE_PATCH_FAILED marker=%s module=%s err=%s", _MARKER, name, exc)
    return patched


def install_import_hook() -> None:
    _try_patch_loaded()
    if getattr(builtins, _HOOK_FLAG, False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if "multi_broker_execution_router" in str(name):
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("FINAL_STAGE_BROKER_RESOLUTION_CACHE_IMPORT_HOOK_FAILED marker=%s name=%s err=%s", _MARKER, name, exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, _HOOK_FLAG, True)
    logger.warning("FINAL_STAGE_BROKER_RESOLUTION_CACHE_IMPORT_HOOK marker=%s", _MARKER)


def install() -> None:
    install_import_hook()
