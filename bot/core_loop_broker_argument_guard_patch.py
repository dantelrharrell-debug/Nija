from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
from functools import wraps
from types import ModuleType
from typing import Any, Optional

logger = logging.getLogger("nija.core_loop_broker_argument_guard")
_MARKER = "CORE_LOOP_BROKER_ARGUMENT_GUARD_PATCHED marker=20260705d"
_PATCHED_ATTR = "_nija_core_loop_broker_argument_guard_20260705d"

_MARKET_METHODS = (
    "get_candles",
    "fetch_ohlcv",
    "get_ohlcv",
    "get_historical_data",
    "get_market_data",
)
_BROKER_METHODS = _MARKET_METHODS + (
    "get_account_balance",
    "get_balance",
    "fetch_balance",
    "place_order",
    "submit_order",
    "create_order",
)


def _name(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower()
    for key in ("okx", "coinbase", "kraken", "alpaca", "binance"):
        if key in text:
            return key
    return text


def _broker_name(broker: Any) -> str:
    if broker is None or isinstance(broker, (bool, int, float, str, bytes, bytearray)):
        return "invalid"
    for attr in ("broker_type", "name", "broker_name", "exchange", "exchange_name"):
        key = _name(getattr(broker, attr, None))
        if key:
            return key
    class_name = type(broker).__name__.lower()
    for key in ("okx", "coinbase", "kraken", "alpaca", "binance"):
        if key in class_name:
            return key
    return "unknown"


def _is_broker_adapter(obj: Any) -> bool:
    if obj is None or isinstance(obj, (bool, int, float, str, bytes, bytearray)):
        return False
    if any(callable(getattr(obj, method, None)) for method in _BROKER_METHODS):
        return True
    return _broker_name(obj) != "unknown" and _broker_name(obj) != "invalid"


def _candidate_brokers_from_owner(owner: Any) -> list[Any]:
    out: list[Any] = []
    if owner is None:
        return out
    for attr in ("broker_client", "broker", "active_broker"):
        broker = getattr(owner, attr, None)
        if _is_broker_adapter(broker) and broker not in out:
            out.append(broker)
    for manager_attr in ("broker_manager", "multi_account_manager", "multi_account_broker_manager"):
        manager = getattr(owner, manager_attr, None)
        if manager is None:
            continue
        for mapping_attr in ("platform_brokers", "_platform_brokers", "brokers", "_brokers"):
            mapping = getattr(manager, mapping_attr, {}) or {}
            if isinstance(mapping, dict):
                for broker in mapping.values():
                    if _is_broker_adapter(broker) and broker not in out:
                        out.append(broker)
        for attr in ("active_broker", "broker", "broker_client", "primary_broker"):
            broker = getattr(manager, attr, None)
            if _is_broker_adapter(broker) and broker not in out:
                out.append(broker)
        getter = getattr(manager, "get_primary_broker", None)
        if callable(getter):
            try:
                broker = getter()
                if _is_broker_adapter(broker) and broker not in out:
                    out.append(broker)
            except Exception:
                pass
    return out


def _resolve_broker(core_loop: Any, incoming: Any) -> Optional[Any]:
    if _is_broker_adapter(incoming):
        return incoming
    apex = getattr(core_loop, "apex", None)
    selected = _name(os.environ.get("NIJA_SELECTED_EXECUTION_BROKER") or os.environ.get("NIJA_PRIMARY_EXECUTION_BROKER"))
    candidates: list[Any] = []
    for owner in (apex, getattr(apex, "strategy", None), getattr(apex, "trading_strategy", None)):
        candidates.extend([b for b in _candidate_brokers_from_owner(owner) if b not in candidates])
    if selected:
        for broker in candidates:
            if _broker_name(broker) == selected:
                return broker
    return candidates[0] if candidates else None


def _patch_core_loop(module: ModuleType) -> bool:
    cls = getattr(module, "NijaCoreLoop", None)
    if not isinstance(cls, type):
        return False
    patched = False

    original_run = getattr(cls, "run_scan_phase", None)
    if callable(original_run) and not getattr(original_run, _PATCHED_ATTR, False):
        @wraps(original_run)
        def run_scan_phase_guarded(self: Any, *args: Any, **kwargs: Any):
            if "broker" in kwargs:
                broker = kwargs.get("broker")
                resolved = _resolve_broker(self, broker)
                if resolved is None:
                    logger.error("CORE_LOOP_BROKER_ARGUMENT_GUARD_BLOCKED marker=20260705d reason=no_real_broker incoming_type=%s", type(broker).__name__)
                    return original_run(self, *args, **kwargs)
                if resolved is not broker:
                    logger.warning(
                        "CORE_LOOP_BROKER_ARGUMENT_GUARD_REPLACED marker=20260705d incoming_type=%s resolved=%s resolved_type=%s",
                        type(broker).__name__,
                        _broker_name(resolved),
                        type(resolved).__name__,
                    )
                    kwargs["broker"] = resolved
                return original_run(self, *args, **kwargs)
            args_list = list(args)
            broker = args_list[0] if args_list else None
            resolved = _resolve_broker(self, broker)
            if resolved is not None and resolved is not broker:
                logger.warning(
                    "CORE_LOOP_BROKER_ARGUMENT_GUARD_REPLACED marker=20260705d incoming_type=%s resolved=%s resolved_type=%s",
                    type(broker).__name__,
                    _broker_name(resolved),
                    type(resolved).__name__,
                )
                if args_list:
                    args_list[0] = resolved
                else:
                    kwargs["broker"] = resolved
            return original_run(self, *tuple(args_list), **kwargs)

        setattr(run_scan_phase_guarded, _PATCHED_ATTR, True)
        setattr(cls, "run_scan_phase", run_scan_phase_guarded)
        patched = True

    original_fetch = getattr(cls, "_fetch_df", None)
    if callable(original_fetch) and not getattr(original_fetch, _PATCHED_ATTR, False):
        @wraps(original_fetch)
        def fetch_df_guarded(self: Any, broker: Any, symbol: Any, *args: Any, **kwargs: Any):
            resolved = _resolve_broker(self, broker)
            if resolved is None:
                logger.error("CORE_LOOP_FETCH_BROKER_GUARD_BLOCKED marker=20260705d symbol=%s incoming_type=%s", symbol, type(broker).__name__)
                return original_fetch(self, broker, symbol, *args, **kwargs)
            if resolved is not broker:
                logger.warning(
                    "CORE_LOOP_FETCH_BROKER_GUARD_REPLACED marker=20260705d symbol=%s incoming_type=%s resolved=%s resolved_type=%s",
                    symbol,
                    type(broker).__name__,
                    _broker_name(resolved),
                    type(resolved).__name__,
                )
            return original_fetch(self, resolved, symbol, *args, **kwargs)

        setattr(fetch_df_guarded, _PATCHED_ATTR, True)
        setattr(cls, "_fetch_df", fetch_df_guarded)
        patched = True

    if patched:
        logger.warning("%s module=%s", _MARKER, getattr(module, "__name__", "unknown"))
        print("[NIJA-PRINT] CORE_LOOP_BROKER_ARGUMENT_GUARD_PATCHED marker=20260705d", flush=True)
    return patched


def _try_patch_loaded() -> bool:
    patched = False
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_core_loop(module) or patched
    return patched


def install_import_hook() -> None:
    _try_patch_loaded()
    if getattr(builtins, "_NIJA_CORE_LOOP_BROKER_ARGUMENT_GUARD_HOOK_INSTALLED", False):
        return
    original_import = builtins.__import__

    def guarded_import(name: str, globals=None, locals=None, fromlist=(), level: int = 0):
        module = original_import(name, globals, locals, fromlist, level)
        try:
            if name.endswith("nija_core_loop"):
                _try_patch_loaded()
            else:
                _try_patch_loaded()
        except Exception as exc:
            logger.warning("CORE_LOOP_BROKER_ARGUMENT_GUARD hook failed: %s", exc)
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, "_NIJA_CORE_LOOP_BROKER_ARGUMENT_GUARD_HOOK_INSTALLED", True)
    logger.warning("CORE_LOOP_BROKER_ARGUMENT_GUARD_IMPORT_HOOK_INSTALLED marker=20260705d")


def install() -> None:
    install_import_hook()
