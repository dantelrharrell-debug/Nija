from __future__ import annotations

import importlib
import logging
from typing import Any

logger = logging.getLogger("nija.broker_bool_guard_patch")
_MARKER = "BROKER_BOOL_GUARD_PATCHED marker=20260705d"
_METHODS = (
    "get_candles", "fetch_ohlcv", "get_ohlcv", "get_historical_data",
    "get_market_data", "get_account_balance", "get_balance", "place_market_order",
    "place_order", "submit_order",
)


def _name(value: Any) -> str:
    raw = getattr(value, "value", value)
    text = str(raw or "").strip().lower()
    for key in ("okx", "coinbase", "kraken", "alpaca", "binance"):
        if key in text:
            return key
    return text


def _broker_key(obj: Any) -> str:
    if obj is None or isinstance(obj, (bool, int, float, str, bytes, bytearray)):
        return "unknown"
    for attr in ("broker_type", "name", "broker_name", "exchange", "exchange_name"):
        found = _name(getattr(obj, attr, None))
        if found:
            return found
    class_name = type(obj).__name__.lower()
    for key in ("okx", "coinbase", "kraken", "alpaca", "binance"):
        if key in class_name:
            return key
    return "unknown"


def _is_adapter(obj: Any) -> bool:
    if obj is None or isinstance(obj, (bool, int, float, str, bytes, bytearray)):
        return False
    if any(callable(getattr(obj, method, None)) for method in _METHODS):
        return True
    return _broker_key(obj) != "unknown" and any(
        getattr(obj, attr, None) is not None
        for attr in ("market_api", "account_api", "client", "session")
    )


def _install_collector_override(module: Any) -> bool:
    if getattr(module, "_NIJA_BROKER_BOOL_GUARD_PATCHED_V20260705D", False):
        return True
    enabled = getattr(module, "_broker_enabled", lambda broker_name: True)

    def collect(apex: Any, explicit_broker: Any = None) -> dict[str, Any]:
        candidates: dict[str, Any] = {}

        def add(raw_key: Any, broker: Any, source: str) -> None:
            key = _broker_key(broker)
            if key == "unknown":
                key = _name(raw_key)
            if not key or key == "unknown" or not enabled(key):
                return
            if not _is_adapter(broker):
                logger.warning(
                    "BROKER_BOOL_GUARD_REJECTED marker=20260705d key=%s source=%s object_type=%s",
                    key, source, type(broker).__name__,
                )
                return
            candidates[key] = broker
            logger.info(
                "BROKER_BOOL_GUARD_ACCEPTED marker=20260705d key=%s source=%s object_type=%s",
                key, source, type(broker).__name__,
            )

        add("explicit", explicit_broker, "explicit")
        owners = [
            item for item in (
                apex,
                getattr(apex, "strategy", None),
                getattr(apex, "trading_strategy", None),
            ) if item is not None
        ]
        for owner in owners:
            for attr in ("broker_client", "broker", "active_broker"):
                add(attr, getattr(owner, attr, None), f"owner.{attr}")
            for manager_attr in ("broker_manager", "multi_account_manager", "multi_account_broker_manager"):
                manager = getattr(owner, manager_attr, None)
                if manager is None:
                    continue
                for mapping_attr in ("platform_brokers", "_platform_brokers", "brokers", "_brokers"):
                    mapping = getattr(manager, mapping_attr, {}) or {}
                    if isinstance(mapping, dict):
                        for raw_key, broker in mapping.items():
                            add(raw_key, broker, f"{manager_attr}.{mapping_attr}")
                for attr in ("active_broker", "broker", "broker_client"):
                    add(attr, getattr(manager, attr, None), f"{manager_attr}.{attr}")
        return candidates

    module._collect_candidate_brokers = collect
    module._broker_key_from_obj = _broker_key
    module._NIJA_BROKER_BOOL_GUARD_PATCHED_V20260705D = True
    logger.warning("%s collector_overridden=True", _MARKER)
    print("[NIJA-PRINT] BROKER_BOOL_GUARD_PATCHED marker=20260705d collector_overridden", flush=True)
    return True


def _install_module(primary: str, fallback: str, label: str, marker: str) -> None:
    try:
        mod = importlib.import_module(primary)
    except Exception:
        try:
            mod = importlib.import_module(fallback)
        except Exception as exc:
            logger.warning("%s_IMPORT_FAILED marker=%s error=%s", label, marker, exc)
            return
    try:
        installer = getattr(mod, "install_import_hook", None) or getattr(mod, "install", None)
        if callable(installer):
            installer()
            logger.warning("%s_INSTALL_REQUESTED marker=%s", label, marker)
    except Exception as exc:
        logger.warning("%s_INSTALL_FAILED marker=%s error=%s", label, marker, exc)


def _install_strategy_backrefs() -> None:
    _install_module(
        "bot.strategy_broker_backref_patch",
        "strategy_broker_backref_patch",
        "BROKER_BOOL_GUARD_STRATEGY_BACKREF",
        "20260705d",
    )


def _install_trade_cycle_convergence_repair() -> None:
    _install_module(
        "bot.trade_cycle_convergence_repair_patch",
        "trade_cycle_convergence_repair_patch",
        "TRADE_CYCLE_CONVERGENCE",
        "20260713a",
    )


def _install_position_sync_runtime_repair() -> None:
    _install_module(
        "bot.position_sync_runtime_repair_patch",
        "position_sync_runtime_repair_patch",
        "POSITION_SYNC_RUNTIME_REPAIR",
        "20260713-position-sync-v2",
    )


def _install_kraken_margin_auto_runtime() -> None:
    _install_module(
        "bot.kraken_margin_auto_runtime_patch",
        "kraken_margin_auto_runtime_patch",
        "KRAKEN_MARGIN_AUTO_RUNTIME",
        "20260713-kraken-margin-v1",
    )


def _install_kraken_all_account_exit_runtime() -> None:
    _install_module(
        "bot.kraken_all_account_exit_runtime_patch",
        "kraken_all_account_exit_runtime_patch",
        "KRAKEN_ALL_ACCOUNT_EXIT_RUNTIME",
        "20260713-kraken-all-account-exit-v1",
    )


def _install_kraken_exit_safety_convergence() -> None:
    _install_module(
        "bot.kraken_exit_safety_convergence_patch",
        "kraken_exit_safety_convergence_patch",
        "KRAKEN_EXIT_SAFETY_CONVERGENCE",
        "20260713-kraken-exit-safety-v1",
    )


def _install_kraken_exit_final_guards() -> None:
    _install_module(
        "bot.kraken_exit_final_guards_patch",
        "kraken_exit_final_guards_patch",
        "KRAKEN_EXIT_FINAL_GUARDS",
        "20260713-kraken-exit-final-guards-v1",
    )


def _install_kraken_exit_execution_safety() -> None:
    _install_module(
        "bot.kraken_exit_execution_safety_patch",
        "kraken_exit_execution_safety_patch",
        "KRAKEN_EXIT_EXECUTION_SAFETY",
        "20260713-kraken-exit-execution-safety-v1",
    )


def install_import_hook() -> None:
    _install_trade_cycle_convergence_repair()
    _install_position_sync_runtime_repair()
    _install_kraken_margin_auto_runtime()
    _install_kraken_all_account_exit_runtime()
    _install_kraken_exit_safety_convergence()
    _install_kraken_exit_final_guards()
    _install_kraken_exit_execution_safety()
    _install_strategy_backrefs()
    try:
        module = importlib.import_module("bot.broker_independent_live_execution_patch")
    except Exception:
        try:
            module = importlib.import_module("broker_independent_live_execution_patch")
        except Exception as exc:
            logger.warning("BROKER_BOOL_GUARD_IMPORT_WAIT marker=20260705d error=%s", exc)
            return
    _install_collector_override(module)


def install() -> None:
    install_import_hook()
