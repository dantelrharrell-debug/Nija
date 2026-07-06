from __future__ import annotations

import builtins
import logging
import sys
from types import ModuleType
from typing import Any

logger = logging.getLogger("nija.broker_bool_guard_patch")
_MARKER = "BROKER_BOOL_GUARD_PATCHED marker=20260705b"
_PATCHED = False

_METHODS = (
    "get_candles",
    "fetch_ohlcv",
    "get_ohlcv",
    "get_historical_data",
    "get_market_data",
    "get_balance",
    "get_account_balance",
    "fetch_balance",
    "place_order",
    "submit_order",
    "create_order",
)


def _normalise_broker_name(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower()
    for key in ("okx", "coinbase", "kraken", "alpaca", "binance"):
        if key in text:
            return key
    return text


def _is_real_broker_adapter(obj: Any) -> bool:
    if obj is None or isinstance(obj, (bool, int, float, str, bytes, bytearray)):
        return False
    if any(callable(getattr(obj, name, None)) for name in _METHODS):
        return True
    for attr in ("broker_type", "name", "broker_name", "exchange", "exchange_name"):
        if _normalise_broker_name(getattr(obj, attr, None)):
            return True
    for attr in ("market_api", "account_api", "client", "session", "api_client"):
        if getattr(obj, attr, None) is not None:
            return True
    return False


def _broker_key_from_obj(obj: Any) -> str:
    if not _is_real_broker_adapter(obj):
        return "unknown"
    for attr in ("broker_type", "name", "broker_name", "exchange", "exchange_name", "id"):
        key = _normalise_broker_name(getattr(obj, attr, None))
        if key:
            return key
    cls_name = type(obj).__name__.lower()
    for key in ("okx", "coinbase", "kraken", "alpaca", "binance"):
        if key in cls_name:
            return key
    return "unknown"


def _patch_independent_module(module: ModuleType) -> bool:
    global _PATCHED
    if getattr(module, "_NIJA_BROKER_BOOL_GUARD_PATCHED", False):
        _PATCHED = True
        return True

    def guarded_is_real_broker_adapter(obj: Any) -> bool:
        return _is_real_broker_adapter(obj)

    def guarded_broker_key_from_obj(obj: Any) -> str:
        return _broker_key_from_obj(obj)

    def guarded_maybe_add_candidate(candidates: dict[str, Any], raw_key: Any, broker: Any, source: str) -> None:
        key = _broker_key_from_obj(broker)
        if key == "unknown":
            key = _normalise_broker_name(raw_key)
        if not key or key == "unknown":
            return
        enabled = getattr(module, "_broker_enabled", lambda name: True)
        if not enabled(key):
            return
        if not _is_real_broker_adapter(broker):
            logger.warning(
                "BROKER_BOOL_GUARD_REJECTED marker=20260705b key=%s source=%s object_type=%s",
                key,
                source,
                type(broker).__name__,
            )
            return
        previous = candidates.get(key)
        if previous is None or not _is_real_broker_adapter(previous):
            candidates[key] = broker
            logger.info(
                "BROKER_BOOL_GUARD_ACCEPTED marker=20260705b key=%s source=%s object_type=%s",
                key,
                source,
                type(broker).__name__,
            )

    module._is_real_broker_adapter = guarded_is_real_broker_adapter
    module._broker_key_from_obj = guarded_broker_key_from_obj
    module._maybe_add_candidate = guarded_maybe_add_candidate
    module._NIJA_BROKER_BOOL_GUARD_PATCHED = True
    _PATCHED = True
    logger.warning("%s independent_module=%s", _MARKER, getattr(module, "__name__", "unknown"))
    print("[NIJA-PRINT] BROKER_BOOL_GUARD_PATCHED marker=20260705b", flush=True)
    return True


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.broker_independent_live_execution_patch", "broker_independent_live_execution_patch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_independent_module(module) or patched
    return patched


def install_import_hook() -> None:
    if _try_patch_loaded():
        return
    if getattr(builtins, "_NIJA_BROKER_BOOL_GUARD_HOOK_INSTALLED", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("broker_independent_live_execution_patch"):
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("BROKER_BOOL_GUARD hook failed: %s", exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_BROKER_BOOL_GUARD_HOOK_INSTALLED", True)
    logger.warning("BROKER_BOOL_GUARD_IMPORT_HOOK_INSTALLED marker=20260705b")


def install() -> None:
    install_import_hook()
