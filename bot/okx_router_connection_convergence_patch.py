"""Canonical OKX router identity and verified connection convergence.

Repairs duplicate import identities and the bridge idempotency contract. It never
fabricates credentials or balances and never marks OKX ready until an existing
broker returns a successful private balance response.

The connection watchdog is deliberately venue-local and bounded in intensity:
terminal configuration/authentication states stop reconnect attempts, while
transient failures use exponential backoff and isolate only OKX. Kraken and
Coinbase readiness are never changed here.
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
_MARKER = "20260808-okx-router-connection-v3"
_LOCK = threading.RLock()
_STARTED = False
_LAST_DIAGNOSTIC = ""

_BRIDGE_NAMES = ("bot.okx_final_order_submission_bridge_patch", "okx_final_order_submission_bridge_patch")
_ROUTER_NAMES = ("bot.multi_broker_execution_router", "multi_broker_execution_router")
_CREDENTIAL_GROUPS = (
    ("OKX_API_KEY", "OKX_PLATFORM_API_KEY"),
    ("OKX_API_SECRET", "OKX_PLATFORM_API_SECRET"),
    ("OKX_PASSPHRASE", "OKX_API_PASSPHRASE", "OKX_PLATFORM_PASSPHRASE"),
)
_ENABLE_FLAGS = (
    "ENABLE_OKX_TRADING",
    "OKX_LIVE_TRADING_ENABLED",
    "NIJA_OKX_EXECUTION_ENABLED",
    "NIJA_OKX_LIVE_TRADING_ENABLED",
)
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_FALSE = {"0", "false", "no", "off", "disabled", "n"}
_FATAL_AUTH_CODES = {"401", "403", "50100", "50101", "50111", "50112", "50113", "50119"}
_FATAL_AUTH_WORDS = (
    "api key",
    "apikey",
    "passphrase",
    "signature",
    "authentication",
    "unauthorized",
    "forbidden",
    "permission denied",
    "invalid key",
    "invalid secret",
)
_TERMINAL_STATES = {
    "disabled",
    "blocked_credentials",
    "credential_quarantined",
    "authentication_failed",
    "connected_no_spendable_quote",
}
_RETRY_BACKOFF_S = (2.0, 5.0, 15.0, 30.0, 60.0, 120.0, 300.0)
_TRANSIENT_QUARANTINE_AFTER = 4
_MAX_TRANSIENT_ATTEMPTS = 64


def _truthy(name: str) -> bool:
    return str(os.getenv(name, "") or "").strip().lower() in _TRUE


def _explicit_false(name: str) -> bool:
    raw = str(os.getenv(name, "") or "").strip().lower()
    return bool(raw) and raw in _FALSE


def _okx_enabled() -> tuple[bool, str]:
    if _truthy("NIJA_DISABLE_OKX"):
        return False, "NIJA_DISABLE_OKX=true"
    disabled = [name for name in _ENABLE_FLAGS if _explicit_false(name)]
    if disabled:
        return False, "disabled_flags=" + ",".join(disabled)
    return True, "enabled"


def _credentials_ready() -> tuple[bool, list[str]]:
    missing: list[str] = []
    for aliases in _CREDENTIAL_GROUPS:
        if not any(str(os.getenv(name, "") or "").strip() for name in aliases):
            missing.append(aliases[0])
    return not missing, missing


def _credential_quarantined() -> bool:
    return _truthy("NIJA_OKX_CREDENTIALS_QUARANTINED") or _truthy("NIJA_OKX_RECONNECT_DISABLED")


def _set_state(state: str, *, ready: bool = False) -> None:
    os.environ["NIJA_OKX_ACTIVATION_STATE"] = state
    os.environ["NIJA_OKX_TRADING_READY"] = "1" if ready else "0"
    if not ready:
        os.environ["NIJA_OKX_FULLY_CONNECTED"] = "0"


def _log_transition(level: int, key: str, message: str, *args: Any) -> None:
    global _LAST_DIAGNOSTIC
    with _LOCK:
        if key == _LAST_DIAGNOSTIC:
            return
        _LAST_DIAGNOSTIC = key
    logger.log(level, message, *args)


def _publish_terminal(state: str, reason: str) -> None:
    _set_state(state)
    os.environ["NIJA_OKX_ENTRY_ISOLATED"] = "1"
    os.environ["NIJA_OKX_RETRY_STATE"] = "terminal"
    os.environ["NIJA_OKX_RECONNECT_DISABLED"] = "1"
    _log_transition(
        logging.ERROR if state not in {"disabled", "connected_no_spendable_quote"} else logging.WARNING,
        f"terminal:{state}",
        "OKX_CONNECTION_TERMINAL marker=%s state=%s reason=%s scope=okx_only "
        "kraken_affected=false coinbase_affected=false retries_disabled=true",
        _MARKER,
        state,
        reason,
    )


def _clear_recovery_state() -> None:
    os.environ["NIJA_OKX_ENTRY_ISOLATED"] = "0"
    os.environ["NIJA_OKX_RETRY_STATE"] = "ready"
    if not _truthy("NIJA_OKX_CREDENTIALS_QUARANTINED"):
        os.environ["NIJA_OKX_RECONNECT_DISABLED"] = "0"


def _looks_fatal_auth(detail: object) -> bool:
    text = str(detail or "").strip().lower()
    if any(code in text for code in _FATAL_AUTH_CODES):
        return True
    return any(word in text for word in _FATAL_AUTH_WORDS)


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
            _log_transition(
                logging.WARNING,
                "platform_reinitialize_failed",
                "OKX_PLATFORM_REINITIALIZE_FAILED marker=%s error=%s",
                _MARKER,
                exc,
            )
    _, recovered = _runtime_broker()
    return recovered


def _converge_connection() -> bool:
    enabled, enable_reason = _okx_enabled()
    if not enabled:
        _publish_terminal("disabled", enable_reason)
        return False

    if _truthy("NIJA_OKX_CREDENTIALS_QUARANTINED"):
        code = os.getenv("NIJA_OKX_CREDENTIAL_QUARANTINE_CODE", "credential_rejected")
        _publish_terminal("credential_quarantined", f"credential_code={code}")
        return False

    credentials, missing = _credentials_ready()
    if not credentials:
        _publish_terminal("blocked_credentials", "missing=" + ",".join(missing))
        return False

    manager, broker = _runtime_broker()
    broker = _attempt_existing_broker_recovery(manager, broker)
    if broker is None:
        _set_state("waiting_broker")
        _log_transition(
            logging.WARNING,
            "waiting_broker",
            "OKX_CONNECTION_WAITING marker=%s reason=broker_not_registered",
            _MARKER,
        )
        return False

    if not _connected(broker):
        if not _truthy("NIJA_WRITER_HEARTBEAT_ACTIVE"):
            _set_state("waiting_writer")
            _log_transition(
                logging.WARNING,
                "waiting_writer",
                "OKX_CONNECTION_WAITING marker=%s reason=writer_heartbeat_not_active",
                _MARKER,
            )
            return False
        connect = getattr(broker, "connect", None)
        if callable(connect):
            try:
                connect()
            except Exception as exc:
                detail = f"{type(exc).__name__}:{exc}"
                if _looks_fatal_auth(detail):
                    _publish_terminal("authentication_failed", detail[:240])
                else:
                    _set_state("connection_failed")
                    _log_transition(
                        logging.ERROR,
                        "connection_failed",
                        "OKX_CONNECTION_FAILED marker=%s class=transient error=%s retry=backoff",
                        _MARKER,
                        detail[:240],
                    )
                return False

    if _truthy("NIJA_OKX_CREDENTIALS_QUARANTINED"):
        code = os.getenv("NIJA_OKX_CREDENTIAL_QUARANTINE_CODE", "credential_rejected")
        _publish_terminal("credential_quarantined", f"credential_code={code}")
        return False

    connected = _connected(broker)
    if not connected:
        _set_state("connection_failed")
        _log_transition(
            logging.ERROR,
            "connection_failed",
            "OKX_CONNECTION_UNVERIFIED marker=%s connected=false balance_ok=false source=not_connected retry=backoff",
            _MARKER,
        )
        return False

    balance_ok, spendable, source = _balance(broker)
    if not balance_ok:
        if _looks_fatal_auth(source):
            _publish_terminal("authentication_failed", source[:240])
        else:
            _set_state("connection_failed")
            _log_transition(
                logging.ERROR,
                "balance_unverified",
                "OKX_CONNECTION_UNVERIFIED marker=%s connected=true balance_ok=false source=%s retry=backoff",
                _MARKER,
                source[:240],
            )
        return False

    os.environ["NIJA_OKX_BALANCE_OBSERVED"] = "1"
    os.environ["NIJA_OKX_TRADING_SPENDABLE"] = f"{spendable:.8f}"
    if spendable <= 0.0:
        _publish_terminal("connected_no_spendable_quote", f"source={source}")
        return False

    _clear_recovery_state()
    _set_state("ready", ready=True)
    _log_transition(
        logging.CRITICAL,
        "ready",
        "OKX_CONNECTION_VERIFIED marker=%s connected=true spendable=%.8f source=%s",
        _MARKER,
        spendable,
        source,
    )
    return True


def _retry_delay(attempt: int, state: str) -> float:
    if state in {"waiting_broker", "waiting_writer"} and attempt < 10:
        return 1.0
    return _RETRY_BACKOFF_S[min(max(0, attempt), len(_RETRY_BACKOFF_S) - 1)]


def _watchdog() -> None:
    for attempt in range(_MAX_TRANSIENT_ATTEMPTS):
        state = "unknown"
        try:
            router = _converge_router()
            connection = _converge_connection()
            state = str(os.environ.get("NIJA_OKX_ACTIVATION_STATE", "unknown") or "unknown")
            if router and connection:
                os.environ["NIJA_OKX_FULLY_CONNECTED"] = "1"
                os.environ["NIJA_OKX_RETRY_STATE"] = "ready"
                logger.critical("OKX_ROUTER_CONNECTION_READY marker=%s", _MARKER)
                return
            if state in _TERMINAL_STATES:
                logger.warning(
                    "OKX_ROUTER_CONNECTION_STOPPED marker=%s state=%s terminal=true scope=okx_only",
                    _MARKER,
                    state,
                )
                return
        except Exception as exc:
            state = "connection_failed"
            _set_state(state)
            _log_transition(
                logging.ERROR,
                "watchdog_exception",
                "OKX_CONVERGENCE_RETRY marker=%s class=transient error=%s retry=backoff",
                _MARKER,
                f"{type(exc).__name__}:{exc}"[:240],
            )

        delay = _retry_delay(attempt, state)
        isolated = attempt + 1 >= _TRANSIENT_QUARANTINE_AFTER
        os.environ["NIJA_OKX_RETRY_STATE"] = "transient_quarantined" if isolated else "backoff"
        os.environ["NIJA_OKX_ENTRY_ISOLATED"] = "1" if isolated else "0"
        os.environ["NIJA_OKX_NEXT_RETRY_S"] = f"{delay:.0f}"
        if attempt == 0 or attempt + 1 == _TRANSIENT_QUARANTINE_AFTER or delay == _RETRY_BACKOFF_S[-1]:
            _log_transition(
                logging.WARNING,
                f"backoff:{'quarantined' if isolated else 'initial'}:{delay:.0f}",
                "OKX_CONNECTION_BACKOFF marker=%s attempt=%s state=%s next_retry_s=%.0f "
                "isolated=%s scope=okx_only kraken_affected=false coinbase_affected=false",
                _MARKER,
                attempt + 1,
                state,
                delay,
                str(isolated).lower(),
            )
        time.sleep(delay)

    _set_state("transient_quarantined")
    os.environ["NIJA_OKX_ENTRY_ISOLATED"] = "1"
    os.environ["NIJA_OKX_RETRY_STATE"] = "exhausted"
    logger.error(
        "OKX_ROUTER_CONNECTION_WATCHDOG_EXHAUSTED marker=%s attempts=%s scope=okx_only "
        "kraken_affected=false coinbase_affected=false",
        _MARKER,
        _MAX_TRANSIENT_ATTEMPTS,
    )


def install() -> bool:
    global _STARTED
    with _LOCK:
        enabled, enable_reason = _okx_enabled()
        if not enabled:
            _publish_terminal("disabled", enable_reason)
            os.environ["NIJA_OKX_ROUTER_CONNECTION_CONVERGENCE_INSTALLED"] = "1"
            return True

        credentials, missing = _credentials_ready()
        if not credentials:
            _publish_terminal("blocked_credentials", "missing=" + ",".join(missing))
            os.environ["NIJA_OKX_ROUTER_CONNECTION_CONVERGENCE_INSTALLED"] = "1"
            return True

        if _truthy("NIJA_OKX_CREDENTIALS_QUARANTINED"):
            code = os.getenv("NIJA_OKX_CREDENTIAL_QUARANTINE_CODE", "credential_rejected")
            _publish_terminal("credential_quarantined", f"credential_code={code}")
            os.environ["NIJA_OKX_ROUTER_CONNECTION_CONVERGENCE_INSTALLED"] = "1"
            return True

        _converge_router()
        if not _STARTED:
            _STARTED = True
            threading.Thread(target=_watchdog, name="OKXRouterConnectionConvergence", daemon=True).start()
        os.environ["NIJA_OKX_ROUTER_CONNECTION_CONVERGENCE_INSTALLED"] = "1"
        logger.critical("OKX_ROUTER_CONNECTION_CONVERGENCE_INSTALLED marker=%s policy=bounded_backoff", _MARKER)
        return True


__all__ = [
    "install",
    "_converge_connection",
    "_watchdog",
    "_retry_delay",
    "_looks_fatal_auth",
    "_okx_enabled",
]
