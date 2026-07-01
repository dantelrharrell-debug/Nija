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


def _broker_results() -> tuple[dict[Any, dict[str, Any]], int]:
    results: dict[Any, dict[str, Any]] = {}
    try:
        module = importlib.import_module("bot.multi_account_broker_manager")
    except Exception:
        try:
            module = importlib.import_module("multi_account_broker_manager")
        except Exception:
            return results, 0
    manager = getattr(module, "multi_account_broker_manager", None)
    if manager is None:
        return results, 0
    for attr in ("platform_brokers", "brokers"):
        brokers = getattr(manager, attr, None)
        if not isinstance(brokers, dict):
            continue
        for key, broker in brokers.items():
            if broker is not None and bool(getattr(broker, "connected", False)):
                results[key] = {"broker": broker, "connected": True}
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
                    logger.warning("STRATEGY_PUBLICATION_WAITING reason=no_connected_brokers")
                    last_log = now
                time.sleep(interval)
                continue
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
