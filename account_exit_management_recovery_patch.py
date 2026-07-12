"""Account-local connection and held-position exit recovery for NIJA.

The normal independent trader starts full trading loops only for funded accounts
that are allowed to create entries.  That is correct for entries, but it can
leave exchange-held positions unmanaged when an account is:

* temporarily underfunded in quote currency,
* configured for copy/recovery mode,
* suppressed by platform-only entry policy, or
* waiting for another brokerage to connect.

This patch keeps entry controls intact and adds an isolated exit-only path.  Each
platform or user brokerage reconnects independently.  Accounts without a normal
trading thread receive a small recovery thread that only adopts positions and
calls ``TradingStrategy.run_cycle(..., user_mode=True)``.  NijaCoreLoop always
runs Phase 2 position management in user mode while Phase 3 entries remain
blocked.

No profit is guaranteed.  Existing take-profit, trailing-stop, stop-loss,
writer-authority, broker, and execution-pipeline checks remain authoritative.
"""

from __future__ import annotations

import builtins
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Iterable, Mapping, Optional

logger = logging.getLogger("nija.account_exit_management_recovery")

_MARKER = "20260711k"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_PATCHED_ATTR = "_nija_account_exit_management_recovery_20260711k"
_STRATEGY_PATCHED_ATTR = "_nija_account_exit_adoption_verify_20260711k"
_ORIGINAL_IMPORT = None
_INSTALL_LOCK = threading.RLock()


def _truthy(name: str, default: str = "true") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _interval() -> float:
    try:
        return max(5.0, float(os.environ.get("NIJA_ACCOUNT_EXIT_MANAGEMENT_INTERVAL_S", "15") or "15"))
    except (TypeError, ValueError):
        return 15.0


def _broker_name(broker_type: Any, broker: Any = None) -> str:
    raw = getattr(broker_type, "value", broker_type)
    text = str(raw or "").strip().lower()
    if text:
        return text
    for attr in ("broker_type", "name", "broker_name", "exchange", "exchange_name"):
        try:
            value = getattr(broker, attr, None)
            raw_value = getattr(value, "value", value)
            text = str(raw_value or "").strip().lower()
            if text:
                return text
        except Exception:
            pass
    return type(broker).__name__.replace("Broker", "").strip().lower() or "unknown"


def _is_connected(broker: Any) -> bool:
    if broker is None:
        return False
    try:
        value = getattr(broker, "connected", None)
        if value is not None:
            return bool(value() if callable(value) else value)
    except Exception:
        return False
    try:
        value = getattr(broker, "is_connected", None)
        if value is not None:
            return bool(value() if callable(value) else value)
    except Exception:
        return False
    return False


def _connect(broker: Any, identity: str) -> bool:
    if _is_connected(broker):
        return True
    connector = getattr(broker, "connect", None)
    if not callable(connector):
        return False
    try:
        result = connector()
        connected = _is_connected(broker) or result is True
        logger.info(
            "ACCOUNT_CONNECTION_RETRY marker=%s account=%s connected=%s",
            _MARKER,
            identity,
            connected,
        )
        return connected
    except Exception as exc:
        logger.warning(
            "ACCOUNT_CONNECTION_RETRY_FAILED marker=%s account=%s error=%s",
            _MARKER,
            identity,
            exc,
        )
        return False


def _safe_balance(trader: Any, broker: Any, broker_type: Any, identity: str) -> float:
    try:
        helper = getattr(trader, "_get_broker_balance", None)
        if callable(helper):
            return max(0.0, float(helper(broker, broker_type, identity) or 0.0))
        getter = getattr(broker, "get_account_balance", None)
        if callable(getter):
            return max(0.0, float(getter() or 0.0))
    except Exception as exc:
        logger.warning(
            "ACCOUNT_BALANCE_PROBE_FAILED marker=%s account=%s error=%s",
            _MARKER,
            identity,
            exc,
        )
    return 0.0


def _normalise_rows(payload: Any) -> list[Any]:
    if payload is None:
        return []
    if isinstance(payload, Mapping):
        for key in ("positions", "open_positions", "holdings"):
            value = payload.get(key)
            if isinstance(value, Mapping):
                return list(value.values())
            if isinstance(value, (list, tuple, set)):
                return list(value)
        if payload and all(isinstance(value, Mapping) for value in payload.values()):
            return list(payload.values())
        return []
    if isinstance(payload, (list, tuple, set)):
        return list(payload)
    return []


def _position_count(broker: Any) -> int:
    for method_name in (
        "get_positions",
        "get_open_positions",
        "get_spot_positions",
        "get_holdings",
    ):
        method = getattr(broker, method_name, None)
        if not callable(method):
            continue
        try:
            try:
                payload = method(verbose=False)
            except TypeError:
                payload = method()
            rows = _normalise_rows(payload)
            if rows:
                return len(rows)
        except Exception:
            continue
    return 0


def _open_order_count(broker: Any) -> int:
    getter = getattr(broker, "get_open_orders", None)
    if not callable(getter):
        return 0
    try:
        payload = getter() or []
        if isinstance(payload, Mapping):
            return len(payload)
        if isinstance(payload, (list, tuple, set)):
            return len(payload)
    except Exception:
        pass
    return 0


def _platform_source(trader: Any) -> Mapping[Any, Any]:
    getter = getattr(trader, "_get_platform_broker_source", None)
    if callable(getter):
        try:
            value = getter() or {}
            if isinstance(value, Mapping):
                return value
        except Exception:
            pass
    manager = getattr(trader, "multi_account_manager", None)
    value = getattr(manager, "platform_brokers", None)
    if isinstance(value, Mapping):
        return value
    manager = getattr(trader, "broker_manager", None)
    value = getattr(manager, "brokers", None)
    return value if isinstance(value, Mapping) else {}


def _iter_accounts(trader: Any) -> Iterable[tuple[str, str, Optional[str], Any, Any]]:
    for broker_type, broker in list(_platform_source(trader).items()):
        name = _broker_name(broker_type, broker)
        yield f"platform:{name}", "platform", None, broker_type, broker

    manager = getattr(trader, "multi_account_manager", None)
    user_brokers = getattr(manager, "user_brokers", None)
    if not isinstance(user_brokers, Mapping):
        return
    for user_id, mapping in list(user_brokers.items()):
        if not isinstance(mapping, Mapping):
            continue
        for broker_type, broker in list(mapping.items()):
            name = _broker_name(broker_type, broker)
            yield f"user:{user_id}:{name}", "user", str(user_id), broker_type, broker


def _normal_thread_alive(trader: Any, scope: str, user_id: Optional[str], broker_type: Any, broker: Any) -> bool:
    name = _broker_name(broker_type, broker)
    thread = None
    if scope == "platform":
        thread = (getattr(trader, "broker_threads", {}) or {}).get(name)
    else:
        key = f"{user_id}_{name}"
        thread = ((getattr(trader, "user_broker_threads", {}) or {}).get(user_id, {}) or {}).get(key)
    return bool(thread is not None and callable(getattr(thread, "is_alive", None)) and thread.is_alive())


def _user_config(trader: Any, user_id: str) -> Any:
    manager = getattr(trader, "multi_account_manager", None)
    configs = getattr(manager, "user_configs", None)
    if isinstance(configs, Mapping):
        return configs.get(user_id)
    return None


def _normal_user_entries_allowed(trader: Any, user_id: str) -> bool:
    if _truthy("NIJA_PLATFORM_ONLY_MODE", "false"):
        return False
    config = _user_config(trader, user_id)
    if config is not None and not bool(getattr(config, "active_trading", True)):
        return False
    checker = getattr(trader, "should_start_user_independent_thread", None)
    if callable(checker):
        try:
            return bool(checker(user_id))
        except Exception:
            return False
    return bool(getattr(config, "independent_trading", False)) if config is not None else False


def _ensure_state(trader: Any) -> None:
    if not hasattr(trader, "_nija_exit_recovery_lock"):
        trader._nija_exit_recovery_lock = threading.RLock()
    if not hasattr(trader, "_nija_exit_recovery_threads"):
        trader._nija_exit_recovery_threads = {}
    if not hasattr(trader, "_nija_exit_recovery_stops"):
        trader._nija_exit_recovery_stops = {}
    if not hasattr(trader, "_nija_exit_supervisor_stop"):
        trader._nija_exit_supervisor_stop = threading.Event()
    if not hasattr(trader, "_nija_exit_supervisor_thread"):
        trader._nija_exit_supervisor_thread = None


def _adopt_and_manage(trader: Any, identity: str, broker: Any) -> tuple[int, int]:
    strategy = getattr(trader, "trading_strategy", None)
    if strategy is None:
        return 0, 0

    positions = _position_count(broker)
    orders = _open_order_count(broker)
    adopter = getattr(strategy, "adopt_existing_positions", None)
    if callable(adopter):
        try:
            status = adopter(
                broker=broker,
                broker_name=identity,
                account_id=identity.upper().replace(":", "_"),
            ) or {}
            positions = max(
                positions,
                int(status.get("positions_found", 0) or 0),
                int(status.get("positions_adopted", 0) or 0),
            )
            orders = max(orders, int(status.get("open_orders_count", 0) or 0))
        except Exception as exc:
            logger.warning(
                "ACCOUNT_POSITION_ADOPTION_FAILED marker=%s account=%s error=%s",
                _MARKER,
                identity,
                exc,
            )
            return positions, orders

    if positions <= 0 and orders <= 0:
        return 0, 0

    try:
        from bot.startup_position_sync import sync_exchange_positions_on_startup
        sync_exchange_positions_on_startup(strategy)
    except Exception as exc:
        logger.debug(
            "ACCOUNT_POSITION_MIRROR_REFRESH_SKIPPED marker=%s account=%s error=%s",
            _MARKER,
            identity,
            exc,
        )

    runner = getattr(strategy, "run_cycle", None)
    if callable(runner):
        try:
            runner(broker=broker, user_mode=True)
            logger.critical(
                "ACCOUNT_EXIT_MANAGEMENT_CYCLE marker=%s account=%s positions=%d open_orders=%d entries_allowed=false",
                _MARKER,
                identity,
                positions,
                orders,
            )
        except Exception as exc:
            logger.warning(
                "ACCOUNT_EXIT_MANAGEMENT_CYCLE_FAILED marker=%s account=%s error=%s",
                _MARKER,
                identity,
                exc,
            )
    return positions, orders


def _exit_loop(trader: Any, identity: str, scope: str, user_id: Optional[str], broker_type: Any, broker: Any, stop: threading.Event) -> None:
    logger.warning(
        "ACCOUNT_EXIT_ONLY_THREAD_STARTED marker=%s account=%s entries_allowed=false",
        _MARKER,
        identity,
    )
    while not stop.is_set():
        if _normal_thread_alive(trader, scope, user_id, broker_type, broker):
            logger.info(
                "ACCOUNT_EXIT_ONLY_THREAD_HANDOFF marker=%s account=%s reason=normal_thread_active",
                _MARKER,
                identity,
            )
            break
        if not _connect(broker, identity):
            stop.wait(_interval())
            continue
        _adopt_and_manage(trader, identity, broker)
        stop.wait(_interval())
    logger.info("ACCOUNT_EXIT_ONLY_THREAD_STOPPED marker=%s account=%s", _MARKER, identity)


def _ensure_exit_thread(trader: Any, identity: str, scope: str, user_id: Optional[str], broker_type: Any, broker: Any) -> bool:
    _ensure_state(trader)
    if _normal_thread_alive(trader, scope, user_id, broker_type, broker):
        return False
    with trader._nija_exit_recovery_lock:
        existing = trader._nija_exit_recovery_threads.get(identity)
        if existing is not None and existing.is_alive():
            return False
        stop = threading.Event()
        thread = threading.Thread(
            target=_exit_loop,
            args=(trader, identity, scope, user_id, broker_type, broker, stop),
            name=f"ExitManager-{identity.replace(':', '-')}",
            daemon=True,
        )
        trader._nija_exit_recovery_stops[identity] = stop
        trader._nija_exit_recovery_threads[identity] = thread
        thread.start()
        return True


def _start_normal_or_exit(trader: Any, identity: str, scope: str, user_id: Optional[str], broker_type: Any, broker: Any) -> None:
    if not _connect(broker, identity):
        return
    balance = _safe_balance(trader, broker, broker_type, identity)
    try:
        minimum = max(0.0, float(getattr(sys.modules.get("bot.independent_broker_trader"), "MINIMUM_FUNDED_BALANCE", 0.5) or 0.5))
    except Exception:
        minimum = 0.5

    if _position_count(broker) > 0 or _open_order_count(broker) > 0:
        _adopt_and_manage(trader, identity, broker)

    if scope == "platform":
        if balance >= minimum:
            starter = getattr(trader, "_start_platform_thread", None)
            if callable(starter):
                starter(broker_type, broker)
                return
        _ensure_exit_thread(trader, identity, scope, user_id, broker_type, broker)
        return

    assert user_id is not None
    if balance >= minimum and _normal_user_entries_allowed(trader, user_id):
        starter = getattr(trader, "_start_user_thread", None)
        if callable(starter):
            starter(user_id, broker_type, broker)
            return
    _ensure_exit_thread(trader, identity, scope, user_id, broker_type, broker)


def _retry_all_accounts(trader: Any) -> None:
    manager = getattr(trader, "multi_account_manager", None)
    connector = getattr(manager, "connect_users_from_config", None)
    if callable(connector):
        try:
            connector()
        except Exception as exc:
            logger.warning("ACCOUNT_USER_CONFIG_CONNECT_FAILED marker=%s error=%s", _MARKER, exc)

    for identity, scope, user_id, broker_type, broker in list(_iter_accounts(trader)):
        if broker is None:
            continue
        _start_normal_or_exit(trader, identity, scope, user_id, broker_type, broker)


def _supervisor_loop(trader: Any) -> None:
    logger.warning("ACCOUNT_EXIT_RECOVERY_SUPERVISOR_STARTED marker=%s", _MARKER)
    while not trader._nija_exit_supervisor_stop.is_set():
        try:
            _retry_all_accounts(trader)
        except Exception:
            logger.exception("ACCOUNT_EXIT_RECOVERY_SUPERVISOR_ERROR marker=%s", _MARKER)
        trader._nija_exit_supervisor_stop.wait(_interval())
    logger.info("ACCOUNT_EXIT_RECOVERY_SUPERVISOR_STOPPED marker=%s", _MARKER)


def _start_supervisor(trader: Any) -> None:
    if not _truthy("NIJA_ACCOUNT_EXIT_MANAGEMENT_RECOVERY_ENABLED", "true"):
        return
    _ensure_state(trader)
    thread = trader._nija_exit_supervisor_thread
    if thread is not None and thread.is_alive():
        return
    trader._nija_exit_supervisor_stop.clear()
    _retry_all_accounts(trader)
    thread = threading.Thread(
        target=_supervisor_loop,
        args=(trader,),
        name="AccountExitRecoverySupervisor",
        daemon=True,
    )
    trader._nija_exit_supervisor_thread = thread
    thread.start()


def _stop_supervisor(trader: Any) -> None:
    _ensure_state(trader)
    trader._nija_exit_supervisor_stop.set()
    for stop in list(trader._nija_exit_recovery_stops.values()):
        stop.set()


def _patch_class(cls: type) -> bool:
    if getattr(cls, _PATCHED_ATTR, False):
        return True

    original_start = getattr(cls, "start_independent_trading", None)
    original_stop = getattr(cls, "stop_all_trading", None)
    if not callable(original_start):
        return False

    def start_independent_trading(self: Any, *args: Any, **kwargs: Any) -> Any:
        result = original_start(self, *args, **kwargs)
        _start_supervisor(self)
        return result

    setattr(start_independent_trading, "__wrapped__", original_start)
    cls.start_independent_trading = start_independent_trading

    if callable(original_stop):
        def stop_all_trading(self: Any, *args: Any, **kwargs: Any) -> Any:
            _stop_supervisor(self)
            return original_stop(self, *args, **kwargs)
        setattr(stop_all_trading, "__wrapped__", original_stop)
        cls.stop_all_trading = stop_all_trading

    def _retry_platform_connections(self: Any) -> None:
        for identity, scope, user_id, broker_type, broker in list(_iter_accounts(self)):
            if scope == "platform" and broker is not None:
                _start_normal_or_exit(self, identity, scope, user_id, broker_type, broker)

    def _retry_user_connections(self: Any) -> None:
        manager = getattr(self, "multi_account_manager", None)
        connector = getattr(manager, "connect_users_from_config", None)
        if callable(connector):
            try:
                connector()
            except Exception as exc:
                logger.warning("ACCOUNT_USER_CONFIG_CONNECT_FAILED marker=%s error=%s", _MARKER, exc)
        for identity, scope, user_id, broker_type, broker in list(_iter_accounts(self)):
            if scope == "user" and broker is not None:
                _start_normal_or_exit(self, identity, scope, user_id, broker_type, broker)

    cls._retry_platform_connections = _retry_platform_connections
    cls._retry_user_connections = _retry_user_connections
    setattr(cls, _PATCHED_ATTR, True)
    logger.warning("ACCOUNT_EXIT_MANAGEMENT_RECOVERY_PATCHED marker=%s class=%s", _MARKER, cls.__name__)
    return True


def _patch_strategy_class(cls: type) -> bool:
    """Make adoption verification account-aware when legacy callers omit broker."""
    if getattr(cls, _STRATEGY_PATCHED_ATTR, False):
        return True

    original_adopt = getattr(cls, "adopt_existing_positions", None)
    original_verify = getattr(cls, "verify_position_adoption_status", None)
    if not callable(original_adopt) or not callable(original_verify):
        return False

    def adopt_existing_positions(self: Any, broker: Any, broker_name: str = "", account_id: str = "") -> Any:
        result = original_adopt(self, broker=broker, broker_name=broker_name, account_id=account_id)
        if isinstance(result, Mapping) and bool(result.get("success")) and account_id:
            mapping = getattr(self, "_nija_adoption_broker_by_account", None)
            if not isinstance(mapping, dict):
                mapping = {}
                setattr(self, "_nija_adoption_broker_by_account", mapping)
            mapping[str(account_id)] = broker
        return result

    def verify_position_adoption_status(
        self: Any,
        broker: Any = None,
        broker_name: str = "",
        account_id: str = "",
    ) -> bool:
        selected = broker
        if selected is None and account_id:
            mapping = getattr(self, "_nija_adoption_broker_by_account", None)
            if isinstance(mapping, Mapping):
                selected = mapping.get(str(account_id))
        if selected is None:
            logger.warning(
                "ACCOUNT_POSITION_ADOPTION_VERIFY_BLOCKED marker=%s account=%s broker=%s reason=broker_unresolved",
                _MARKER,
                account_id,
                broker_name,
            )
            return False
        return bool(
            original_verify(
                self,
                broker=selected,
                broker_name=broker_name,
                account_id=account_id,
            )
        )

    setattr(adopt_existing_positions, "__wrapped__", original_adopt)
    setattr(verify_position_adoption_status, "__wrapped__", original_verify)
    cls.adopt_existing_positions = adopt_existing_positions
    cls.verify_position_adoption_status = verify_position_adoption_status
    setattr(cls, _STRATEGY_PATCHED_ATTR, True)
    logger.warning("ACCOUNT_POSITION_ADOPTION_VERIFY_PATCHED marker=%s class=%s", _MARKER, cls.__name__)
    return True


def _patch_loaded() -> bool:
    patched = False
    for name in ("bot.independent_broker_trader", "independent_broker_trader"):
        module = sys.modules.get(name)
        cls = getattr(module, "IndependentBrokerTrader", None) if isinstance(module, ModuleType) else None
        if isinstance(cls, type):
            patched = _patch_class(cls) or patched
    for name in ("bot.trading_strategy", "trading_strategy"):
        module = sys.modules.get(name)
        cls = getattr(module, "TradingStrategy", None) if isinstance(module, ModuleType) else None
        if isinstance(cls, type):
            patched = _patch_strategy_class(cls) or patched
    return patched


def install_import_hook() -> None:
    global _ORIGINAL_IMPORT
    with _INSTALL_LOCK:
        os.environ.setdefault("NIJA_ACCOUNT_EXIT_MANAGEMENT_RECOVERY_ENABLED", "true")
        os.environ.setdefault("NIJA_ACCOUNT_EXIT_MANAGEMENT_INTERVAL_S", "15")
        os.environ.setdefault("NIJA_ADOPTED_POSITION_PROFIT_EXIT_ENABLED", "true")
        os.environ.setdefault("NIJA_GLOBAL_TAKE_PROFIT_ENABLED", "true")
        os.environ.setdefault("NIJA_GLOBAL_TRAILING_TAKE_PROFIT_ENABLED", "true")
        os.environ.setdefault("NIJA_AUTO_EXIT_SL_TP_ENABLED", "true")
        if _ORIGINAL_IMPORT is None:
            _ORIGINAL_IMPORT = builtins.__import__

            def _import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
                module = _ORIGINAL_IMPORT(name, globals, locals, fromlist, level)
                try:
                    _patch_loaded()
                except Exception as exc:
                    logger.debug("ACCOUNT_EXIT_MANAGEMENT_IMPORT_PATCH_FAILED name=%s error=%s", name, exc)
                return module

            builtins.__import__ = _import
        _patch_loaded()
        logger.warning("ACCOUNT_EXIT_MANAGEMENT_RECOVERY_INSTALL_REQUESTED marker=%s", _MARKER)


__all__ = [
    "install_import_hook",
    "_patch_class",
    "_patch_strategy_class",
    "_retry_all_accounts",
    "_adopt_and_manage",
    "_ensure_exit_thread",
]
