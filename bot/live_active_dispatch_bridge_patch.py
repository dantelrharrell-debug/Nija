"""Live-active dispatch bridge for NIJA.

This patch closes the gap where startup reaches live writer authority and the
TradingStateMachine reaches LIVE_ACTIVE, but no TradingLoop thread is actually
started. It does not relax order admission, does not set operator override flags,
and does not create a second strategy. It only dispatches an already-published
TradingStrategy after strict live writer authority is present.
"""

from __future__ import annotations

import gc
import importlib
import logging
import os
import sys
import threading
import time
from typing import Any, Optional, Tuple

logger = logging.getLogger("nija.live_active_dispatch_bridge")
_TRUTHY = {"1", "true", "yes", "on", "enabled", "y"}
_STARTED = False
_START_LOCK = threading.Lock()
_THREAD_NAMES = {"TradingLoop", "nija-trading-loop"}


def _truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in _TRUTHY


def _live_mode() -> bool:
    return _truthy("LIVE_CAPITAL_VERIFIED", False) and not _truthy("DRY_RUN_MODE", False) and not _truthy("PAPER_MODE", False)


def _has_writer_authority() -> bool:
    token = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "")).strip()
    generation = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "")).strip()
    lease = _truthy("NIJA_WRITER_LEASE_ACQUIRED", False) or bool(token)
    runtime_auth = _truthy("NIJA_RUNTIME_EXECUTION_AUTHORITY", False)
    return bool(token and generation and lease and runtime_auth)


def _loop_thread_running() -> bool:
    for thread in threading.enumerate():
        try:
            if thread.is_alive() and (thread.name in _THREAD_NAMES or "TradingLoop" in thread.name):
                return True
        except Exception:
            continue
    return False


def _state_machine_live_active() -> bool:
    for module_name in ("bot.trading_state_machine", "trading_state_machine"):
        try:
            module = importlib.import_module(module_name)
            getter = getattr(module, "get_state_machine", None)
            if not callable(getter):
                continue
            sm = getter()
            is_live = getattr(sm, "is_live_trading_active", None)
            if callable(is_live) and bool(is_live()):
                return True
            state = getattr(sm, "get_current_state", lambda: None)()
            state_value = str(getattr(state, "value", state) or "")
            if state_value == "LIVE_ACTIVE":
                return True
        except Exception as exc:
            logger.debug("LIVE_ACTIVE probe skipped module=%s err=%s", module_name, exc)
    return str(os.environ.get("NIJA_RUNTIME_TRADING_STATE", "")).strip() == "LIVE_ACTIVE"


def _dispatch_allowed() -> Tuple[bool, str]:
    if not _live_mode():
        return False, "not_live_mode"
    if not _has_writer_authority():
        return False, "writer_authority_missing"
    if not _state_machine_live_active():
        return False, "state_not_live_active"
    if _loop_thread_running():
        return False, "trading_loop_already_running"
    return True, "ok"


def _module_candidates() -> list[Any]:
    modules: list[Any] = []
    for name in ("__main__", "bot", "bot.__main__"):
        mod = sys.modules.get(name)
        if mod is not None:
            modules.append(mod)
    for mod in list(sys.modules.values()):
        try:
            mod_name = str(getattr(mod, "__name__", ""))
        except Exception:
            continue
        if mod_name.endswith(("bot", "main", "trading_strategy")) and mod not in modules:
            modules.append(mod)
    return modules


def _strategy_class() -> Optional[type]:
    for module_name in ("bot.trading_strategy", "trading_strategy"):
        try:
            module = importlib.import_module(module_name)
            cls = getattr(module, "TradingStrategy", None)
            if isinstance(cls, type):
                return cls
        except Exception as exc:
            logger.debug("TradingStrategy class probe skipped module=%s err=%s", module_name, exc)
    return None


def _strategy_from_initialized_state() -> Tuple[Optional[Any], str]:
    for mod in _module_candidates():
        try:
            state = getattr(mod, "_initialized_state", None)
            if isinstance(state, dict):
                strategy = state.get("strategy")
                if strategy is not None:
                    return strategy, f"{getattr(mod, '__name__', 'module')}._initialized_state"
        except Exception:
            continue
    return None, "not_found"


def _strategy_from_module_globals(cls: Optional[type]) -> Tuple[Optional[Any], str]:
    if cls is None:
        return None, "class_unavailable"
    for mod in _module_candidates():
        try:
            for name, value in vars(mod).items():
                if isinstance(value, cls):
                    return value, f"{getattr(mod, '__name__', 'module')}.{name}"
        except Exception:
            continue
    return None, "not_found"


def _strategy_from_gc(cls: Optional[type]) -> Tuple[Optional[Any], str]:
    if cls is None:
        return None, "class_unavailable"
    try:
        for obj in gc.get_objects():
            try:
                if isinstance(obj, cls):
                    return obj, "gc.TradingStrategy"
            except Exception:
                continue
    except Exception as exc:
        logger.debug("GC strategy scan skipped: %s", exc)
    return None, "not_found"


def _find_strategy() -> Tuple[Optional[Any], str]:
    strategy, source = _strategy_from_initialized_state()
    if strategy is not None:
        return strategy, source
    cls = _strategy_class()
    strategy, source = _strategy_from_module_globals(cls)
    if strategy is not None:
        return strategy, source
    return _strategy_from_gc(cls)


def _set_start_gate() -> None:
    for module_name in ("bot.nija_core_loop", "nija_core_loop"):
        try:
            module = importlib.import_module(module_name)
            ready = getattr(module, "TRADING_ENGINE_READY", None)
            if ready is not None and callable(getattr(ready, "set", None)):
                ready.set()
                logger.warning("LIVE_ACTIVE_DISPATCH_BRIDGE_START_GATE_SET module=%s", module_name)
                return
        except Exception as exc:
            logger.debug("start gate set skipped module=%s err=%s", module_name, exc)


def _start_trading_loop(strategy: Any, source: str) -> bool:
    if strategy is None:
        return False
    if _loop_thread_running():
        logger.warning("LIVE_ACTIVE_DISPATCH_BRIDGE_ALREADY_RUNNING source=%s", source)
        return True
    with _START_LOCK:
        if _loop_thread_running():
            logger.warning("LIVE_ACTIVE_DISPATCH_BRIDGE_ALREADY_RUNNING source=%s", source)
            return True
        try:
            module = importlib.import_module("bot.nija_core_loop")
        except Exception:
            module = importlib.import_module("nija_core_loop")
        starter = getattr(module, "start_trading_engine", None)
        if not callable(starter):
            logger.error("LIVE_ACTIVE_DISPATCH_BRIDGE_START_FAILED reason=start_trading_engine_unavailable")
            return False
        _set_start_gate()
        logger.critical(
            "LIVE_ACTIVE_DISPATCH_BRIDGE_STARTING strategy_source=%s strategy_type=%s token_prefix=%s generation=%s",
            source,
            type(strategy).__name__,
            str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", ""))[:8],
            os.environ.get("NIJA_WRITER_LEASE_GENERATION", ""),
        )
        thread = starter(strategy)
        alive = bool(thread is not None and getattr(thread, "is_alive", lambda: False)())
        logger.critical(
            "LIVE_ACTIVE_DISPATCH_BRIDGE_STARTED_THREAD name=%s alive=%s ident=%s",
            getattr(thread, "name", "none"),
            alive,
            getattr(thread, "ident", None),
        )
        return alive


def _monitor() -> None:
    interval = max(1.0, float(os.environ.get("NIJA_LIVE_DISPATCH_BRIDGE_INTERVAL_S", "3") or 3.0))
    warn_every = max(5.0, float(os.environ.get("NIJA_LIVE_DISPATCH_BRIDGE_LOG_INTERVAL_S", "15") or 15.0))
    last_log = 0.0
    logger.warning("LIVE_ACTIVE_DISPATCH_BRIDGE_STARTED interval_s=%.1f", interval)
    while True:
        try:
            allowed, reason = _dispatch_allowed()
            now = time.time()
            if not allowed:
                if reason == "trading_loop_already_running":
                    return
                if now - last_log >= warn_every:
                    logger.warning(
                        "LIVE_ACTIVE_DISPATCH_BRIDGE_WAITING reason=%s live=%s writer_authority=%s live_active=%s threads=%s",
                        reason,
                        _live_mode(),
                        _has_writer_authority(),
                        _state_machine_live_active(),
                        [t.name for t in threading.enumerate() if t.is_alive()],
                    )
                    last_log = now
                time.sleep(interval)
                continue
            strategy, source = _find_strategy()
            if strategy is None:
                if now - last_log >= warn_every:
                    logger.critical(
                        "LIVE_ACTIVE_DISPATCH_BRIDGE_WAITING reason=no_strategy live_active=True writer_authority=True modules=%s",
                        sorted(str(getattr(m, "__name__", "")) for m in _module_candidates()),
                    )
                    last_log = now
                time.sleep(interval)
                continue
            if _start_trading_loop(strategy, source):
                return
            time.sleep(interval)
        except Exception as exc:
            logger.exception("LIVE_ACTIVE_DISPATCH_BRIDGE_ERROR err=%s", exc)
            time.sleep(interval)


def install_import_hook() -> None:
    global _STARTED
    if _STARTED:
        return
    _STARTED = True
    thread = threading.Thread(target=_monitor, name="live-active-dispatch-bridge", daemon=True)
    thread.start()
    logger.warning("LIVE_ACTIVE_DISPATCH_BRIDGE_INSTALL_COMPLETE thread_alive=%s", thread.is_alive())
