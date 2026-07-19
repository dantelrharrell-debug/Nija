"""Canonical OKX router identity and verified connection convergence.

Repairs duplicate import identities and the bridge idempotency contract. It never
fabricates credentials or balances and never marks OKX ready until an existing
broker returns a successful private balance response.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Mapping

logger = logging.getLogger("nija.okx_router_connection_convergence")
_MARKER = "20260719-okx-router-connection-v2"
_LOCK = threading.RLock()
_STARTED = False

_BRIDGE_NAMES = ("bot.okx_final_order_submission_bridge_patch", "okx_final_order_submission_bridge_patch")
_ROUTER_NAMES = ("bot.multi_broker_execution_router", "multi_broker_execution_router")
_CREDENTIAL_GROUPS = (
    ("OKX_API_KEY", "OKX_PLATFORM_API_KEY"),
    ("OKX_API_SECRET", "OKX_PLATFORM_API_SECRET"),
    ("OKX_PASSPHRASE", "OKX_API_PASSPHRASE", "OKX_PLATFORM_PASSPHRASE"),
)


def _truthy(name: str) -> bool:
    return str(os.getenv(name, "") or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}


def _credentials_ready() -> tuple[bool, list[str]]:
    missing: list[str] = []
    for aliases in _CREDENTIAL_GROUPS:
        if not any(str(os.getenv(name, "") or "").strip() for name in aliases):
            missing.append(aliases[0])
    return not missing, missing


def _canonical_import(primary: str, alias: str) -> ModuleType:
    module = sys.modules.get(primary) or sys.modules.get(alias)
    if not isinstance(module, ModuleType):
        module = importlib.import_module(primary)
    sys.modules[primary] = module
    sys.modules[alias] = module
    return module


def _method_has_router_marker(method: Any, marker_attr: str) -> bool:
    current = method
    seen: set[int] = set()
    for _ in range(32):
        if current is None or id(current) in seen:
            return False
        seen.add(id(current))
        if bool(getattr(current, marker_attr, False)):
            return True
        current = getattr(current, "__wrapped__", None)
    return False


def _converge_router() -> bool:
    bridge = _canonical_import(_BRIDGE_NAMES[0], _BRIDGE_NAMES[1])
    router = _canonical_import(_ROUTER_NAMES[0], _ROUTER_NAMES[1])
    patcher = getattr(bridge, "_patch_router_module", None)
    if callable(patcher):
        try:
            patcher(router)
        except Exception as exc:
            logger.warning("OKX_ROUTER_PATCH_CALL_FAILED marker=%s error=%s", _MARKER, exc)
    cls = getattr(router, "MultiBrokerExecutionRouter", None)
    method = getattr(cls, "_dispatch_direct_broker_market_order", None) if isinstance(cls, type) else None
    marker_attr = str(getattr(bridge, "_ROUTER_PATCH_ATTR", "_nija_okx_final_order_submission_bridge_router_v20260709d"))
    ready = bool(getattr(bridge, "_ROUTER_PATCHED", False)) or _method_has_router_marker(method, marker_attr)
    if ready:
        bridge._ROUTER_PATCHED = True
        os.environ["NIJA_OKX_ROUTER_PATCHED"] = "1"
        os.environ["NIJA_OKX_ROUTER_QUARANTINED"] = "0"
        logger.critical("OKX_ROUTER_IDENTITY_CONVERGED marker=%s bridge=%s router=%s", _MARKER, bridge.__name__, router.__name__)
    return ready


def _runtime_broker() -> tuple[Any, Any]:
    try:
        broker_module = _canonical_import("bot.broker_manager", "broker_manager")
        manager_module = _canonical_import("bot.multi_account_broker_manager", "multi_account_broker_manager")
    except Exception:
        return None, None
    manager = getattr(manager_module, "multi_account_broker_manager", None)
    if manager is None:
        getter = getattr(manager_module, "get_broker_manager", None)
        try:
            manager = getter() if callable(getter) else None
        except Exception:
            manager = None
    enum_value = getattr(getattr(broker_module, "BrokerType", None), "OKX", None)
    broker = None
    if manager is not None:
        for attr in ("_platform_brokers", "platform_brokers", "brokers"):
            mapping = getattr(manager, attr, None)
            if isinstance(mapping, Mapping):
                broker = mapping.get(enum_value) or mapping.get("okx") or mapping.get("OKX")
                if broker is not None:
                    break
    if broker is None:
        getter = getattr(broker_module, "get_platform_broker", None)
        if callable(getter):
            try:
                broker = getter("okx")
            except Exception:
                broker = None
    return manager, broker


def _connected(broker: Any) -> bool:
    for attr in ("connected", "is_connected"):
        if broker is not None and hasattr(broker, attr):
            try:
                value = getattr(broker, attr)
                if bool(value() if callable(value) else value):
                    return True
            except Exception:
                pass
    return False


def _balance(broker: Any) -> tuple[bool, float, str]:
    if broker is None:
        return False, 0.0, "broker_missing"
    for name in ("get_account_balance_detailed", "get_account_balance"):
        fn = getattr(broker, name, None)
        if not callable(fn):
            continue
        try:
            try:
                payload = fn(verbose=False)
            except TypeError:
                payload = fn()
            if isinstance(payload, (int, float)):
                return True, max(0.0, float(payload)), name
            if isinstance(payload, Mapping):
                for key in ("trading_balance", "available_balance", "available_usd", "usdt", "usdc", "usd", "total"):
                    if key in payload:
                        return True, max(0.0, float(payload.get(key) or 0.0)), f"{name}:{key}"
                return True, 0.0, name
        except Exception as exc:
            return False, 0.0, f"{name}:{type(exc).__name__}:{exc}"
    return False, 0.0, "balance_method_missing"


def _attempt_existing_broker_recovery(manager: Any, broker: Any) -> Any:
    if broker is not None or manager is None or not _truthy("NIJA_WRITER_HEARTBEAT_ACTIVE"):
        return broker
    initializer = getattr(manager, "initialize_platform_brokers", None)
    if callable(initializer):
        try:
            results = getattr(manager, "_platform_init_results", None)
            if isinstance(results, dict):
                results.pop("okx", None)
                results.pop("OKX", None)
            setattr(manager, "_platform_init_complete", False)
            initializer()
        except Exception as exc:
            logger.warning("OKX_PLATFORM_REINITIALIZE_FAILED marker=%s error=%s", _MARKER, exc)
    _, recovered = _runtime_broker()
    return recovered


def _converge_connection() -> bool:
    credentials, missing = _credentials_ready()
    if not credentials:
        os.environ["NIJA_OKX_ACTIVATION_STATE"] = "blocked_credentials"
        os.environ["NIJA_OKX_TRADING_READY"] = "0"
        logger.error("OKX_CONNECTION_BLOCKED marker=%s reason=missing_credentials missing=%s", _MARKER, ",".join(missing))
        return False
    manager, broker = _runtime_broker()
    broker = _attempt_existing_broker_recovery(manager, broker)
    if broker is None:
        os.environ["NIJA_OKX_ACTIVATION_STATE"] = "waiting_broker"
        logger.warning("OKX_CONNECTION_WAITING marker=%s reason=broker_not_registered", _MARKER)
        return False
    if not _connected(broker):
        connect = getattr(broker, "connect", None)
        if callable(connect) and _truthy("NIJA_WRITER_HEARTBEAT_ACTIVE"):
            try:
                connect()
            except Exception as exc:
                os.environ["NIJA_OKX_ACTIVATION_STATE"] = "authentication_failed"
                logger.error("OKX_AUTHENTICATION_FAILED marker=%s error=%s", _MARKER, exc)
                return False
    connected = _connected(broker)
    balance_ok, spendable, source = _balance(broker) if connected else (False, 0.0, "not_connected")
    if not connected or not balance_ok:
        os.environ["NIJA_OKX_ACTIVATION_STATE"] = "connection_failed"
        os.environ["NIJA_OKX_TRADING_READY"] = "0"
        logger.error("OKX_CONNECTION_UNVERIFIED marker=%s connected=%s balance_ok=%s source=%s", _MARKER, connected, balance_ok, source)
        return False
    os.environ["NIJA_OKX_BALANCE_OBSERVED"] = "1"
    os.environ["NIJA_OKX_TRADING_SPENDABLE"] = f"{spendable:.8f}"
    if spendable <= 0.0:
        os.environ["NIJA_OKX_ACTIVATION_STATE"] = "connected_no_spendable_quote"
        os.environ["NIJA_OKX_TRADING_READY"] = "0"
        logger.warning("OKX_CONNECTED_NO_SPENDABLE_QUOTE marker=%s source=%s", _MARKER, source)
        return False
    os.environ["NIJA_OKX_ACTIVATION_STATE"] = "ready"
    os.environ["NIJA_OKX_TRADING_READY"] = "1"
    logger.critical("OKX_CONNECTION_VERIFIED marker=%s connected=true spendable=%.8f source=%s", _MARKER, spendable, source)
    return True


def _watchdog() -> None:
    last = None
    for _ in range(900):
        try:
            router = _converge_router()
            connection = _converge_connection()
            state = (router, connection)
            if state != last:
                logger.warning("OKX_CONVERGENCE_STATE marker=%s router=%s connection=%s", _MARKER, router, connection)
                last = state
            if router and connection:
                os.environ["NIJA_OKX_FULLY_CONNECTED"] = "1"
                logger.critical("OKX_ROUTER_CONNECTION_READY marker=%s", _MARKER)
                return
        except Exception:
            logger.exception("OKX_CONVERGENCE_RETRY marker=%s", _MARKER)
        time.sleep(1.0)
    logger.error("OKX_ROUTER_CONNECTION_WATCHDOG_EXHAUSTED marker=%s", _MARKER)


def install() -> bool:
    global _STARTED
    with _LOCK:
        _converge_router()
        if not _STARTED:
            _STARTED = True
            threading.Thread(target=_watchdog, name="OKXRouterConnectionConvergence", daemon=True).start()
        os.environ["NIJA_OKX_ROUTER_CONNECTION_CONVERGENCE_INSTALLED"] = "1"
        logger.critical("OKX_ROUTER_CONNECTION_CONVERGENCE_INSTALLED marker=%s", _MARKER)
        return True


__all__ = ["install"]
