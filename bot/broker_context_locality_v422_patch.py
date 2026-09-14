"""Remove transient broker selection from process-global environment state.

Older routing patches used ``NIJA_SELECTED_EXECUTION_BROKER`` and
``NIJA_PRIMARY_EXECUTION_BROKER`` as mutable per-cycle state. Environment
variables are process-global, so concurrent broker cells could overwrite one
another. This patch keeps venue selection on the strategy/APEX object and in a
ContextVar-backed broker/account scope only.
"""
from __future__ import annotations

import logging
import sys
import threading
import time
from types import ModuleType
from typing import Any, Dict, Optional

logger = logging.getLogger("nija.broker_context_locality_v422")
MARKER = "20260914-broker-context-locality-v422"
_LOCK = threading.RLock()
_STARTED = False


def _clean(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower()
    for name in ("kraken", "coinbase", "okx", "alpaca", "binance"):
        if name in text:
            return name
    return text


def _account_scope(broker: Any) -> str:
    for attr in (
        "nija_account_scope",
        "account_id",
        "user_id",
        "nija_user_id",
        "account_identifier",
    ):
        value = getattr(broker, attr, None)
        if value not in (None, ""):
            return str(value).strip().lower()
    account_type = getattr(getattr(broker, "account_type", None), "value", None)
    return str(account_type or "platform").strip().lower()


def _patch_broker_independent(module: ModuleType) -> bool:
    set_name = "_set_apex_broker_context"
    restore_name = "_restore_apex_broker_context"
    current_set = getattr(module, set_name, None)
    current_restore = getattr(module, restore_name, None)
    if not callable(current_set) or not callable(current_restore):
        return False
    if getattr(current_set, "_nija_context_local_v422", False):
        return True

    def set_local(apex: Any, name: str, broker: Any) -> Dict[str, Any]:
        old: Dict[str, Any] = {}
        for attr in (
            "broker_client",
            "broker",
            "active_broker",
            "_nija_selected_execution_broker",
            "_nija_execution_route_broker",
        ):
            try:
                old[attr] = getattr(apex, attr, None)
            except Exception:
                pass

        for attr in ("broker_client", "broker", "active_broker"):
            try:
                setattr(apex, attr, broker)
            except Exception:
                pass
        for attr in ("_nija_selected_execution_broker", "_nija_execution_route_broker"):
            try:
                setattr(apex, attr, _clean(name))
            except Exception:
                pass

        manager = getattr(apex, "broker_manager", None)
        if manager is not None:
            try:
                old["manager_active_broker"] = getattr(manager, "active_broker", None)
                manager.active_broker = broker
            except Exception:
                pass

        try:
            from bot.broker_account_scope import broker_account_scope
            cm = broker_account_scope(_clean(name), _account_scope(broker))
            cm.__enter__()
            old["_nija_scope_context_manager"] = cm
        except Exception as exc:
            logger.debug("BROKER_CONTEXT_SCOPE_ENTER_FAILED marker=%s error=%s", MARKER, exc)

        logger.debug(
            "BROKER_CONTEXT_SET marker=%s broker=%s account=%s process_env_write=false",
            MARKER,
            _clean(name),
            _account_scope(broker),
        )
        return old

    def restore_local(apex: Any, old: Dict[str, Any]) -> None:
        cm = old.get("_nija_scope_context_manager")
        if cm is not None:
            try:
                cm.__exit__(None, None, None)
            except Exception:
                pass

        for attr in (
            "broker_client",
            "broker",
            "active_broker",
            "_nija_selected_execution_broker",
            "_nija_execution_route_broker",
        ):
            if attr in old:
                try:
                    setattr(apex, attr, old[attr])
                except Exception:
                    pass

        manager = getattr(apex, "broker_manager", None)
        if manager is not None and "manager_active_broker" in old:
            try:
                manager.active_broker = old["manager_active_broker"]
            except Exception:
                pass

    setattr(set_local, "_nija_context_local_v422", True)
    setattr(restore_local, "_nija_context_local_v422", True)
    setattr(module, set_name, set_local)
    setattr(module, restore_name, restore_local)
    logger.critical("BROKER_INDEPENDENT_CONTEXT_LOCALIZED marker=%s", MARKER)
    return True


def _patch_route_integrity(module: ModuleType) -> bool:
    normalise = getattr(module, "_normalise_broker_name", _clean)
    broker_key = getattr(module, "_broker_key_from_obj", lambda obj: _clean(type(obj).__name__))
    allowed = getattr(module, "_allowed_brokers", lambda: ["kraken"])
    equity_map = getattr(module, "_EQUITY_SURFACE_BY_CRYPTO_BROKER", {}) or {}

    def set_strategy_broker(strategy: Any, name: str, broker: Any) -> None:
        name = normalise(name)
        try:
            strategy.broker = broker
            setattr(strategy, "_nija_execution_route_broker", name)
            setattr(strategy, "_nija_selected_execution_broker", name)
        except Exception:
            pass
        try:
            manager = getattr(strategy, "broker_manager", None)
            if manager is not None:
                manager.active_broker = broker
        except Exception:
            pass
        try:
            apex = getattr(strategy, "apex", None)
            if apex is not None:
                setattr(apex, "_nija_execution_route_broker", name)
                setattr(apex, "_nija_selected_execution_broker", name)
                if hasattr(apex, "update_broker_client"):
                    apex.update_broker_client(broker)
                else:
                    setattr(apex, "broker_client", broker)
        except Exception:
            pass
        logger.debug(
            "STRATEGY_BROKER_CONTEXT_LOCAL marker=%s broker=%s process_env_write=false",
            MARKER,
            name,
        )

    def resolve_selected_broker(request: Any) -> str:
        meta = dict(getattr(request, "metadata", {}) or {})
        asset_class = str(
            getattr(getattr(request, "asset_class", None), "value", getattr(request, "asset_class", None))
            or meta.get("asset_class")
            or ""
        ).strip().lower()

        candidates = [
            getattr(request, "preferred_broker", None),
            meta.get("execution_broker"),
            meta.get("dispatch_broker"),
            meta.get("broker_name"),
            broker_key(meta.get("broker_client") or meta.get("broker_adapter")),
        ]
        try:
            from bot.broker_account_scope import current_broker_name
            candidates.append(current_broker_name(""))
        except Exception:
            pass

        for candidate in candidates:
            key = normalise(candidate)
            if key and key not in {"unknown", "none"}:
                if asset_class in {"equity", "equities", "stock", "stocks", "etf", "etfs"}:
                    key = equity_map.get(key, key)
                return key
        eligible = list(allowed() or [])
        return normalise(eligible[0]) if eligible else "kraken"

    setattr(set_strategy_broker, "_nija_context_local_v422", True)
    setattr(resolve_selected_broker, "_nija_context_local_v422", True)
    setattr(module, "_set_strategy_broker", set_strategy_broker)
    setattr(module, "_resolve_selected_broker", resolve_selected_broker)
    logger.critical("EXECUTION_ROUTE_CONTEXT_LOCALIZED marker=%s", MARKER)
    return True


def _patch_loaded() -> bool:
    patched = False
    for name in ("bot.broker_independent_live_execution_patch", "broker_independent_live_execution_patch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_broker_independent(module) or patched
    for name in ("bot.execution_route_integrity_patch", "execution_route_integrity_patch"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            patched = _patch_route_integrity(module) or patched
    return patched


def _watchdog() -> None:
    deadline = time.monotonic() + 900.0
    while time.monotonic() < deadline:
        try:
            _patch_loaded()
        except Exception as exc:
            logger.debug("BROKER_CONTEXT_LOCALITY_RETRY marker=%s error=%s", MARKER, exc)
        time.sleep(0.5)


def install() -> bool:
    global _STARTED
    with _LOCK:
        patched = _patch_loaded()
        if not _STARTED:
            _STARTED = True
            threading.Thread(
                target=_watchdog,
                name="BrokerContextLocalityV422",
                daemon=True,
            ).start()
        logger.critical(
            "BROKER_CONTEXT_LOCALITY_V422_READY marker=%s currently_patched=%s process_env_routing=false",
            MARKER,
            patched,
        )
        return True


install_import_hook = install

__all__ = ["MARKER", "install", "install_import_hook"]
