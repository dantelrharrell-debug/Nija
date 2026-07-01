"""Publish a TradingStrategy object after startup components are ready."""

from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from typing import Any, Optional

logger = logging.getLogger("nija.strategy_publication_patch")
_TRUTHY = {"1", "true", "yes", "on", "enabled", "y"}
_STARTED = False
_LOCK = threading.Lock()
_PUBLISHED: Any = None
_LAST_SCAN_DETAIL = ""


def _truthy(name: str) -> bool:
    return str(os.environ.get(name, "")).strip().lower() in _TRUTHY


def _ready() -> tuple[bool, str]:
    if not _truthy("LIVE_CAPITAL_VERIFIED"):
        return False, "live_capital_not_verified"
    if _truthy("DRY_RUN_MODE") or _truthy("PAPER_MODE"):
        return False, "simulation_mode"
    if str(os.environ.get("NIJA_RUNTIME_TRADING_STATE", "")).strip() != "LIVE_ACTIVE":
        return False, "state_not_live_active"
    if not str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "")).strip():
        return False, "writer_token_missing"
    if not str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "")).strip():
        return False, "writer_generation_missing"
    return True, "ok"


def _strategy_class() -> Optional[type]:
    for module_name in ("bot.trading_strategy", "trading_strategy"):
        try:
            module = importlib.import_module(module_name)
            cls = getattr(module, "TradingStrategy", None)
            if isinstance(cls, type):
                return cls
        except Exception:
            continue
    return None


def _modules() -> list[Any]:
    out: list[Any] = []
    for name in ("__main__", "bot", "bot.trading_strategy", "trading_strategy"):
        try:
            module = sys.modules.get(name) or importlib.import_module(name)
            if module is not None:
                out.append(module)
        except Exception:
            continue
    return out


def _existing(cls: Optional[type]) -> Any:
    global _PUBLISHED
    if _PUBLISHED is not None:
        return _PUBLISHED
    if cls is None:
        return None
    for module in _modules():
        try:
            state = getattr(module, "_initialized_state", None)
            if isinstance(state, dict):
                candidate = state.get("strategy") or state.get("trading_strategy")
                if isinstance(candidate, cls):
                    return candidate
            for name in ("strategy", "trading_strategy", "nija_live_strategy"):
                candidate = getattr(module, name, None)
                if isinstance(candidate, cls):
                    return candidate
        except Exception:
            continue
    return None


def _call_bool(obj: Any, name: str) -> Optional[bool]:
    fn = getattr(obj, name, None)
    if not callable(fn):
        return None
    try:
        return bool(fn())
    except Exception:
        return None


def _broker_ready(broker: Any) -> bool:
    """Accept a broker when it is connected or has a usable hydrated payload."""
    if broker is None:
        return False
    if bool(getattr(broker, "connected", False)):
        return True
    for probe in (
        "is_ready_for_capital",
        "is_trade_ready",
        "is_ready",
        "has_balance_payload_for_capital",
        "has_balance_payload",
    ):
        value = _call_bool(broker, probe)
        if value is True:
            return True
    return getattr(broker, "_last_known_balance", None) is not None


def _normal_key(key: Any, broker: Any, prefix: str = "") -> str:
    raw = getattr(key, "value", key)
    if raw is None or str(raw).strip() in {"", "None"}:
        btype = getattr(broker, "broker_type", None)
        raw = getattr(btype, "value", btype)
    if raw is None or str(raw).strip() in {"", "None"}:
        raw = getattr(broker, "NAME", "") or broker.__class__.__name__
    text = str(raw).strip().lower().replace(" ", "_")
    if prefix and not text.startswith(prefix):
        return f"{prefix}{text}"
    return text


def _add_broker(results: dict[Any, dict[str, Any]], key: Any, broker: Any, source: str) -> None:
    if broker is None or not _broker_ready(broker):
        return
    norm = _normal_key(key, broker)
    # Keep the first object for a key; duplicate module aliases can expose the same
    # singleton under bot.* and top-level names.
    if norm in results:
        return
    results[norm] = {
        "broker": broker,
        "connected": bool(getattr(broker, "connected", False)),
        "ready_for_capital": True,
        "source": source,
    }


def _items(obj: Any) -> list[tuple[Any, Any]]:
    if isinstance(obj, dict):
        return list(obj.items())
    try:
        return list(obj.items())
    except Exception:
        return []


def _collect_from_manager(results: dict[Any, dict[str, Any]], manager: Any, source: str) -> None:
    if manager is None:
        return

    # Canonical platform maps used by MultiAccountBrokerManager.
    for attr in ("platform_brokers", "_platform_brokers", "brokers", "broker_map"):
        try:
            mapping = getattr(manager, attr, None)
            for key, broker in _items(mapping):
                _add_broker(results, key, broker, f"{source}.{attr}")
        except Exception:
            continue

    # Some paths expose a fully merged broker map through get_all_brokers().
    try:
        get_all = getattr(manager, "get_all_brokers", None)
        if callable(get_all):
            mapping = get_all()
            for key, broker in _items(mapping):
                _add_broker(results, key, broker, f"{source}.get_all_brokers")
    except Exception:
        pass

    # Platform init results have the same shape TradingStrategy expects.
    try:
        init_results = getattr(manager, "_platform_init_results", None)
        for key, meta in _items(init_results):
            if isinstance(meta, dict):
                _add_broker(results, key, meta.get("broker"), f"{source}._platform_init_results")
    except Exception:
        pass

    # Connected user brokers are nested by user/account.
    for attr in ("user_brokers", "_all_user_brokers"):
        try:
            mapping = getattr(manager, attr, None)
            for key, value in _items(mapping):
                if isinstance(value, dict):
                    for inner_key, broker in _items(value):
                        _add_broker(results, f"{key}_{inner_key}", broker, f"{source}.{attr}")
                else:
                    _add_broker(results, key, value, f"{source}.{attr}")
        except Exception:
            continue


def _manager_candidates(module: Any) -> list[Any]:
    candidates: list[Any] = []
    for attr in ("multi_account_broker_manager", "broker_manager"):
        try:
            obj = getattr(module, attr, None)
            if obj is not None and obj not in candidates:
                candidates.append(obj)
        except Exception:
            pass
    for getter in ("get_broker_manager", "get_multi_account_broker_manager"):
        try:
            fn = getattr(module, getter, None)
            if callable(fn):
                obj = fn()
                if obj is not None and obj not in candidates:
                    candidates.append(obj)
        except Exception:
            pass
    return candidates


def _collect_global_brokers(results: dict[Any, dict[str, Any]]) -> None:
    for module_name in ("bot.broker_manager", "broker_manager"):
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        try:
            mapping = getattr(module, "_PLATFORM_BROKER_INSTANCES", None)
            for key, broker in _items(mapping):
                _add_broker(results, key, broker, f"{module_name}._PLATFORM_BROKER_INSTANCES")
        except Exception:
            pass
        try:
            get_platform = getattr(module, "get_platform_broker", None)
            if callable(get_platform):
                for key in ("kraken", "coinbase", "okx", "alpaca"):
                    try:
                        _add_broker(results, key, get_platform(key), f"{module_name}.get_platform_broker")
                    except Exception:
                        continue
        except Exception:
            pass
        try:
            get_manager = getattr(module, "get_broker_manager", None)
            if callable(get_manager):
                _collect_from_manager(results, get_manager(), f"{module_name}.get_broker_manager")
        except Exception:
            pass


def _broker_results() -> tuple[dict[Any, dict[str, Any]], int]:
    global _LAST_SCAN_DETAIL
    results: dict[Any, dict[str, Any]] = {}
    scanned: list[str] = []

    for module_name in ("bot.multi_account_broker_manager", "multi_account_broker_manager"):
        try:
            module = importlib.import_module(module_name)
        except Exception as exc:
            scanned.append(f"{module_name}:import_error:{type(exc).__name__}")
            continue
        managers = _manager_candidates(module)
        scanned.append(f"{module_name}:managers={len(managers)}")
        for idx, manager in enumerate(managers, start=1):
            _collect_from_manager(results, manager, f"{module_name}.manager{idx}")

    _collect_global_brokers(results)

    _LAST_SCAN_DETAIL = ",".join(scanned) or "no_modules"
    return results, len(results)


def _publish(strategy: Any) -> None:
    global _PUBLISHED
    _PUBLISHED = strategy
    for module in _modules():
        try:
            setattr(module, "nija_live_strategy", strategy)
            setattr(module, "trading_strategy", strategy)
            state = getattr(module, "_initialized_state", None)
            if not isinstance(state, dict):
                state = {}
                setattr(module, "_initialized_state", state)
            state["strategy"] = strategy
            state["trading_strategy"] = strategy
        except Exception:
            continue
    logger.critical(
        "STRATEGY_PUBLICATION_READY type=%s broker=%s core_loop=%s symbols=%s",
        type(strategy).__name__,
        type(getattr(strategy, "broker", None)).__name__ if getattr(strategy, "broker", None) is not None else "none",
        bool(getattr(strategy, "nija_core_loop", None)),
        len(getattr(strategy, "symbols", []) or []),
    )


def _monitor() -> None:
    interval = max(1.0, float(os.environ.get("NIJA_STRATEGY_PUBLICATION_INTERVAL_S", "3") or 3.0))
    last_log = 0.0
    logger.warning("STRATEGY_PUBLICATION_MONITOR_STARTED interval_s=%.1f", interval)
    while True:
        ok, reason = _ready()
        now = time.time()
        if not ok:
            if now - last_log >= 15.0:
                logger.warning("STRATEGY_PUBLICATION_WAITING reason=%s", reason)
                last_log = now
            time.sleep(interval)
            continue
        cls = _strategy_class()
        existing = _existing(cls)
        if existing is not None:
            _publish(existing)
            return
        if cls is None:
            if now - last_log >= 15.0:
                logger.warning("STRATEGY_PUBLICATION_WAITING reason=class_unavailable")
                last_log = now
            time.sleep(interval)
            continue
        with _LOCK:
            existing = _existing(cls)
            if existing is not None:
                _publish(existing)
                return
            brokers, count = _broker_results()
            if count <= 0:
                if now - last_log >= 15.0:
                    logger.warning(
                        "STRATEGY_PUBLICATION_WAITING reason=no_connected_brokers scan=%s modules=%s",
                        _LAST_SCAN_DETAIL,
                        sorted(name for name in sys.modules if name.endswith("multi_account_broker_manager") or name.endswith("broker_manager"))[:20],
                    )
                    last_log = now
                time.sleep(interval)
                continue
            logger.warning(
                "STRATEGY_PUBLICATION_BROKERS_READY count=%d keys=%s",
                count,
                sorted(str(key) for key in brokers.keys()),
            )
            try:
                strategy = cls(broker_results=brokers)
            except TypeError:
                strategy = cls()
            except Exception as exc:
                logger.exception("STRATEGY_PUBLICATION_BUILD_ERROR err=%s", exc)
                time.sleep(interval)
                continue
            _publish(strategy)
            return


def install_import_hook() -> None:
    global _STARTED
    if _STARTED:
        return
    _STARTED = True
    thread = threading.Thread(target=_monitor, name="strategy-publication-monitor", daemon=True)
    thread.start()
    logger.warning("STRATEGY_PUBLICATION_INSTALL_COMPLETE thread_alive=%s", thread.is_alive())
