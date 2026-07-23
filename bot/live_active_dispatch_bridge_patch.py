"""Live-active dispatch bridge for NIJA.

This patch closes the gap where startup reaches live writer authority and the
TradingStateMachine reaches LIVE_ACTIVE, but no TradingLoop thread is actually
started. It does not relax order admission, set operator overrides, or create a
second strategy. It starts an already-published TradingStrategy only after the
canonical distributed writer lease, runtime execution authority, and LIVE_ACTIVE
state are all present.

The bridge also repairs a deferred-startup deadlock observed in production:
``activation_pending_commit_monitor_patch`` historically waited only for
``multi_account_broker_manager`` even when the active runtime loaded
``bot.broker_manager``/``bot.broker_integration``. Once a canonical broker
surface is loaded, this module invokes the existing idempotent startup-repair
installer. Those installers remain fail-closed and retain their own authority,
capital, kill-switch, nonce, and execution checks.
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
_BROKER_MODULE_NAMES = (
    "bot.multi_account_broker_manager",
    "multi_account_broker_manager",
    "bot.broker_manager",
    "broker_manager",
    "bot.broker_integration",
    "broker_integration",
)


def _truthy(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in _TRUTHY


def _live_mode() -> bool:
    return (
        _truthy("LIVE_CAPITAL_VERIFIED", False)
        and not _truthy("DRY_RUN_MODE", False)
        and not _truthy("PAPER_MODE", False)
    )


def _writer_authority_snapshot() -> dict[str, Any]:
    token = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "")).strip()
    generation = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "")).strip()
    lease_flag = _truthy("NIJA_WRITER_LEASE_ACQUIRED", False)
    lease = bool(lease_flag or token)
    runtime_auth = _truthy("NIJA_RUNTIME_EXECUTION_AUTHORITY", False)
    heartbeat_active = _truthy("NIJA_WRITER_HEARTBEAT_ACTIVE", False)
    return {
        "token": token,
        "token_present": bool(token),
        "generation": generation,
        "generation_present": bool(generation),
        "lease_flag": lease_flag,
        "lease": lease,
        "runtime_auth": runtime_auth,
        "heartbeat_active": heartbeat_active,
        "ready": bool(token and generation and lease),
    }


def _has_writer_authority() -> bool:
    """Return distributed writer-lease readiness, excluding runtime state."""

    return bool(_writer_authority_snapshot()["ready"])


def _runtime_execution_authority() -> bool:
    return bool(_writer_authority_snapshot()["runtime_auth"])


def _loop_thread_running() -> bool:
    for thread in threading.enumerate():
        try:
            if thread.is_alive() and (
                thread.name in _THREAD_NAMES or "TradingLoop" in thread.name
            ):
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
            logger.debug(
                "LIVE_ACTIVE probe skipped module=%s err=%s", module_name, exc
            )
    return (
        str(os.environ.get("NIJA_RUNTIME_TRADING_STATE", "")).strip()
        == "LIVE_ACTIVE"
    )


def _broker_bootstrap_loaded() -> tuple[bool, str]:
    """Observe canonical broker modules without importing them ahead of startup."""

    for name in _BROKER_MODULE_NAMES:
        module = sys.modules.get(name)
        if module is None:
            continue
        if name.endswith("broker_manager"):
            return True, name
        for attr in (
            "BrokerManager",
            "MultiAccountBrokerManager",
            "KrakenBroker",
            "CoinbaseBroker",
            "OKXBroker",
            "KrakenBrokerAdapter",
            "CoinbaseBrokerAdapter",
            "OKXBrokerAdapter",
        ):
            if hasattr(module, attr):
                return True, f"{name}.{attr}"
    return False, "not_loaded"


def _ensure_deferred_startup_repairs() -> tuple[bool, str]:
    """Install the existing deferred repair set after any canonical broker loads."""

    broker_loaded, broker_source = _broker_bootstrap_loaded()
    if not broker_loaded:
        return False, "broker_bootstrap_not_loaded"

    module = None
    for module_name in (
        "bot.activation_pending_commit_monitor_patch",
        "activation_pending_commit_monitor_patch",
    ):
        try:
            module = importlib.import_module(module_name)
            break
        except Exception:
            continue
    if module is None:
        return False, "activation_pending_monitor_unavailable"

    ready_event = getattr(module, "_STARTUP_REPAIRS_READY", None)
    if ready_event is not None and bool(getattr(ready_event, "is_set", lambda: False)()):
        return True, "already_ready"

    installer = getattr(module, "_install_startup_execution_repairs", None)
    if not callable(installer):
        return False, "startup_repair_installer_unavailable"

    try:
        complete = bool(installer())
    except Exception as exc:
        logger.warning(
            "LIVE_ACTIVE_DISPATCH_BRIDGE_STARTUP_REPAIRS_FAILED "
            "broker_source=%s err=%s",
            broker_source,
            exc,
            exc_info=True,
        )
        return False, f"installer_error:{type(exc).__name__}:{exc}"

    logger.warning(
        "LIVE_ACTIVE_DISPATCH_BRIDGE_STARTUP_REPAIRS_TRIGGERED "
        "broker_source=%s complete=%s",
        broker_source,
        complete,
    )
    return complete, "installed" if complete else "incomplete"


def _attempt_runtime_convergence(source: str) -> tuple[bool, str]:
    """Invoke the normal convergence repair; never force state or authority."""

    if not _has_writer_authority():
        return False, "writer_authority_missing"

    module = None
    for module_name in (
        "bot.runtime_authority_convergence_repair_patch",
        "runtime_authority_convergence_repair_patch",
    ):
        try:
            module = importlib.import_module(module_name)
            break
        except Exception:
            continue
    if module is None:
        return False, "runtime_convergence_module_unavailable"

    installer = getattr(module, "install_import_hook", None)
    if callable(installer):
        try:
            installer()
        except Exception as exc:
            return False, f"runtime_convergence_install_failed:{exc}"

    converge = getattr(module, "converge_runtime_authority", None)
    if not callable(converge):
        return False, "runtime_convergence_callable_unavailable"

    try:
        changed = bool(converge(source))
    except Exception as exc:
        logger.warning(
            "LIVE_ACTIVE_DISPATCH_BRIDGE_RUNTIME_CONVERGENCE_FAILED "
            "source=%s err=%s",
            source,
            exc,
            exc_info=True,
        )
        return False, f"runtime_convergence_error:{type(exc).__name__}:{exc}"

    ready = _runtime_execution_authority() and _state_machine_live_active()
    return ready, "ready" if ready else ("changed" if changed else "waiting")


def _dispatch_allowed() -> Tuple[bool, str]:
    if not _live_mode():
        return False, "not_live_mode"
    if not _has_writer_authority():
        return False, "writer_authority_missing"
    if not _runtime_execution_authority():
        return False, "runtime_execution_authority_missing"
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
            logger.debug(
                "TradingStrategy class probe skipped module=%s err=%s",
                module_name,
                exc,
            )
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
                logger.warning(
                    "LIVE_ACTIVE_DISPATCH_BRIDGE_START_GATE_SET module=%s",
                    module_name,
                )
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
            logger.warning(
                "LIVE_ACTIVE_DISPATCH_BRIDGE_ALREADY_RUNNING source=%s", source
            )
            return True
        try:
            module = importlib.import_module("bot.nija_core_loop")
        except Exception:
            module = importlib.import_module("nija_core_loop")
        starter = getattr(module, "start_trading_engine", None)
        if not callable(starter):
            logger.error(
                "LIVE_ACTIVE_DISPATCH_BRIDGE_START_FAILED "
                "reason=start_trading_engine_unavailable"
            )
            return False
        _set_start_gate()
        logger.critical(
            "LIVE_ACTIVE_DISPATCH_BRIDGE_STARTING strategy_source=%s "
            "strategy_type=%s token_prefix=%s generation=%s",
            source,
            type(strategy).__name__,
            str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", ""))[:8],
            os.environ.get("NIJA_WRITER_LEASE_GENERATION", ""),
        )
        thread = starter(strategy)
        alive = bool(
            thread is not None and getattr(thread, "is_alive", lambda: False)()
        )
        logger.critical(
            "LIVE_ACTIVE_DISPATCH_BRIDGE_STARTED_THREAD name=%s alive=%s ident=%s",
            getattr(thread, "name", "none"),
            alive,
            getattr(thread, "ident", None),
        )
        return alive


def _monitor() -> None:
    interval = max(
        1.0,
        float(os.environ.get("NIJA_LIVE_DISPATCH_BRIDGE_INTERVAL_S", "3") or 3.0),
    )
    warn_every = max(
        5.0,
        float(
            os.environ.get("NIJA_LIVE_DISPATCH_BRIDGE_LOG_INTERVAL_S", "15")
            or 15.0
        ),
    )
    last_log = 0.0
    logger.warning("LIVE_ACTIVE_DISPATCH_BRIDGE_STARTED interval_s=%.1f", interval)

    while True:
        try:
            repairs_ready, repair_detail = _ensure_deferred_startup_repairs()

            if _has_writer_authority() and (
                not _runtime_execution_authority()
                or not _state_machine_live_active()
            ):
                convergence_ready, convergence_detail = _attempt_runtime_convergence(
                    "live_active_dispatch_bridge"
                )
            else:
                convergence_ready = bool(
                    _runtime_execution_authority() and _state_machine_live_active()
                )
                convergence_detail = "not_needed" if convergence_ready else "waiting"

            allowed, reason = _dispatch_allowed()
            now = time.time()
            if not allowed:
                if reason == "trading_loop_already_running":
                    return
                if now - last_log >= warn_every:
                    writer = _writer_authority_snapshot()
                    broker_loaded, broker_source = _broker_bootstrap_loaded()
                    logger.warning(
                        "LIVE_ACTIVE_DISPATCH_BRIDGE_WAITING reason=%s live=%s "
                        "writer_authority=%s token=%s generation=%s lease=%s "
                        "heartbeat=%s runtime_auth=%s live_active=%s "
                        "broker_loaded=%s broker_source=%s repairs_ready=%s "
                        "repair_detail=%s convergence_ready=%s "
                        "convergence_detail=%s threads=%s",
                        reason,
                        _live_mode(),
                        writer["ready"],
                        writer["token_present"],
                        writer["generation"] or "missing",
                        writer["lease"],
                        writer["heartbeat_active"],
                        writer["runtime_auth"],
                        _state_machine_live_active(),
                        broker_loaded,
                        broker_source,
                        repairs_ready,
                        repair_detail,
                        convergence_ready,
                        convergence_detail,
                        [t.name for t in threading.enumerate() if t.is_alive()],
                    )
                    last_log = now
                time.sleep(interval)
                continue

            strategy, source = _find_strategy()
            if strategy is None:
                if now - last_log >= warn_every:
                    logger.critical(
                        "LIVE_ACTIVE_DISPATCH_BRIDGE_WAITING reason=no_strategy "
                        "live_active=True writer_authority=True modules=%s",
                        sorted(
                            str(getattr(m, "__name__", ""))
                            for m in _module_candidates()
                        ),
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
    thread = threading.Thread(
        target=_monitor,
        name="live-active-dispatch-bridge",
        daemon=True,
    )
    thread.start()
    logger.warning(
        "LIVE_ACTIVE_DISPATCH_BRIDGE_INSTALL_COMPLETE thread_alive=%s",
        thread.is_alive(),
    )


__all__ = [
    "install_import_hook",
    "_broker_bootstrap_loaded",
    "_ensure_deferred_startup_repairs",
    "_attempt_runtime_convergence",
    "_dispatch_allowed",
    "_writer_authority_snapshot",
]
