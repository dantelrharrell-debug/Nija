"""Persistent runtime convergence for NIJA's late-loaded repair graph.

This module does not bypass live-trading safety gates. It continuously restores
required wrapper ownership, republishes release readiness from the existing
manifest, and asks the existing activation monitor to commit only through the
normal TradingStateMachine gates.
"""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
import time
from types import ModuleType
from typing import Any, Callable

logger = logging.getLogger("nija.runtime_convergence_v15")
_MARKER = "20260723-runtime-convergence-v15"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_LOCK = threading.RLock()
_STARTED = False
_LAST_SIGNATURE = ""
_GUARD_ATTR = "_nija_runtime_convergence_v15_guarded"


def _truthy(name: str, default: str = "false") -> bool:
    return str(os.environ.get(name, default) or "").strip().lower() in _TRUE


def _chain_contains(func: Any, attr: str, *, limit: int = 4096) -> tuple[bool, bool, int]:
    current = func
    seen: set[int] = set()
    depth = 0
    while callable(current):
        ident = id(current)
        if ident in seen:
            return False, True, depth
        seen.add(ident)
        if bool(getattr(current, attr, False)):
            return True, False, depth
        current = getattr(current, "__wrapped__", None)
        if not callable(current):
            return False, False, depth
        depth += 1
        if depth >= limit:
            return False, True, depth
    return False, False, depth


def _core_modules() -> list[ModuleType]:
    modules: list[ModuleType] = []
    seen: set[int] = set()
    for name in ("bot.nija_core_loop", "nija_core_loop"):
        module = sys.modules.get(name)
        if isinstance(module, ModuleType) and id(module) not in seen:
            modules.append(module)
            seen.add(id(module))
    return modules


def _stamp_outer_when_chain_contains(cls: type, method_names: tuple[str, ...], attr: str) -> None:
    for method_name in method_names:
        current = getattr(cls, method_name, None)
        if not callable(current) or bool(getattr(current, attr, False)):
            continue
        found, cycle, _ = _chain_contains(current, attr)
        if found and not cycle:
            try:
                setattr(current, attr, True)
            except Exception:
                pass


def _guard_class_patcher(
    module: ModuleType,
    function_name: str,
    method_names: tuple[str, ...],
    attr_name: str,
) -> bool:
    original = getattr(module, function_name, None)
    if not callable(original) or bool(getattr(original, _GUARD_ATTR, False)):
        return False

    def guarded(cls: type, *args: Any, __original: Callable[..., Any] = original, **kwargs: Any) -> Any:
        if isinstance(cls, type):
            _stamp_outer_when_chain_contains(cls, method_names, attr_name)
        return __original(cls, *args, **kwargs)

    setattr(guarded, _GUARD_ATTR, True)
    setattr(guarded, "__wrapped__", original)
    setattr(module, function_name, guarded)
    return True


def _guard_module_patcher(
    module: ModuleType,
    function_name: str,
    class_name: str,
    method_name: str,
    attr_name: str,
) -> bool:
    original = getattr(module, function_name, None)
    if not callable(original) or bool(getattr(original, _GUARD_ATTR, False)):
        return False

    def guarded(target_module: ModuleType, *args: Any, __original: Callable[..., Any] = original, **kwargs: Any) -> Any:
        cls = getattr(target_module, class_name, None)
        if isinstance(cls, type):
            _stamp_outer_when_chain_contains(cls, (method_name,), attr_name)
        return __original(target_module, *args, **kwargs)

    setattr(guarded, _GUARD_ATTR, True)
    setattr(guarded, "__wrapped__", original)
    setattr(module, function_name, guarded)
    return True


def _ensure_okx_patch_idempotence() -> bool:
    changed = False
    try:
        instid = importlib.import_module("bot.okx_order_instid_payload_repair_patch")
        changed = _guard_class_patcher(
            instid,
            "_wrap_order_class",
            ("place_market_order", "execute_order", "place_order"),
            str(getattr(instid, "_ORDER_WRAP_ATTR", "")),
        ) or changed
        changed = _guard_class_patcher(
            instid,
            "_wrap_rest_class",
            ("_request",),
            str(getattr(instid, "_REST_WRAP_ATTR", "")),
        ) or changed
        retry = getattr(instid, "_try_patch_loaded", None)
        if callable(retry):
            retry()
    except Exception:
        logger.debug("OKX instId idempotence guard deferred", exc_info=True)

    try:
        bridge = importlib.import_module("bot.okx_final_order_submission_bridge_patch")
        changed = _guard_class_patcher(
            bridge,
            "_wrap_order_class",
            ("place_market_order", "execute_order", "place_order"),
            str(getattr(bridge, "_ORDER_WRAP_ATTR", "")),
        ) or changed
        changed = _guard_module_patcher(
            bridge,
            "_patch_router_module",
            "MultiBrokerExecutionRouter",
            "_dispatch_direct_broker_market_order",
            str(getattr(bridge, "_ROUTER_PATCH_ATTR", "")),
        ) or changed
        retry = getattr(bridge, "_try_patch_loaded", None)
        if callable(retry):
            retry()
    except Exception:
        logger.debug("OKX final-submit idempotence guard deferred", exc_info=True)

    if changed:
        logger.critical("OKX_PATCH_IDEMPOTENCE_GUARDS_INSTALLED marker=%s", _MARKER)
    return True


def _ensure_zero_signal_state() -> bool:
    try:
        patch = importlib.import_module("bot.zero_signal_streak_state_repair_patch")
        installer = getattr(patch, "install_import_hook", None)
        if callable(installer):
            installer()
        retry = getattr(patch, "_try_loaded", None)
        ready = bool(retry()) if callable(retry) else _truthy("NIJA_ZERO_SIGNAL_STREAK_STATE_READY")
        os.environ["NIJA_ZERO_SIGNAL_STREAK_STATE_READY"] = "1" if ready else "0"
        return ready
    except Exception:
        os.environ["NIJA_ZERO_SIGNAL_STREAK_STATE_READY"] = "0"
        logger.debug("zero-signal convergence deferred", exc_info=True)
        return False


def _ensure_downstream_risk() -> bool:
    try:
        patch = importlib.import_module("bot.downstream_risk_governor_equity_repair_patch")
        installer = getattr(patch, "install_import_hook", None)
        if callable(installer):
            installer()
        retry = getattr(patch, "_try_patch_loaded", None)
        if callable(retry):
            retry()
        state = dict(getattr(patch, "_STATE", {}) or {})
        ready = bool(state.get("pipeline")) and _truthy("NIJA_PRE_DISPATCH_RISK_SIZING_READY")
        if ready:
            os.environ["NIJA_DOWNSTREAM_RISK_GOVERNOR_V2_READY"] = "1"
        return ready
    except Exception:
        logger.debug("downstream-risk convergence deferred", exc_info=True)
        return False


def _ensure_scan_chain() -> bool:
    try:
        convergence = importlib.import_module("scan_wrapper_convergence_repair_patch")
        depth_guard = importlib.import_module("scan_wrapper_depth_convergence_patch")

        known = tuple(getattr(convergence, "_KNOWN_WRAPPER_MARKERS", ()) or ())
        broker_attr = str(getattr(depth_guard, "_BROKER_ATTR", "") or "")
        if broker_attr and broker_attr not in known:
            setattr(convergence, "_KNOWN_WRAPPER_MARKERS", known + (broker_attr,))

        install = getattr(convergence, "install", None)
        if callable(install):
            install()

        for module in _core_modules():
            cls = getattr(module, "NijaCoreLoop", None)
            current = getattr(cls, "run_scan_phase", None) if isinstance(cls, type) else None
            if not callable(current):
                continue
            status = depth_guard.inspect_chain(current)
            max_depth = max(4, min(64, int(float(os.environ.get("NIJA_MAX_SCAN_WRAPPER_DEPTH", "24") or 24))))
            needs_collapse = bool(status.get("cycle")) or int(status.get("depth", 0)) > max_depth or int(status.get("broker_layers", 0)) > 1 or int(status.get("canonical_layers", 0)) > 1
            if not needs_collapse:
                continue

            release = str(getattr(convergence, "_MARKER", "") or "")
            if str(getattr(current, "_nija_scan_wrapper_release", "") or "") == release:
                try:
                    setattr(current, "_nija_scan_wrapper_release", "")
                except Exception:
                    pass
            unwrap = getattr(convergence, "_unwrap_known", None)
            patch_core = getattr(convergence, "_patch_core_loop", None)
            if callable(unwrap) and callable(patch_core):
                base, removed, cycle = unwrap(current)
                if callable(base) and base is not current:
                    setattr(cls, "run_scan_phase", base)
                    patch_core(module)
                    logger.critical(
                        "SCAN_CHAIN_V15_COLLAPSED marker=%s module=%s removed_layers=%s cycle=%s prior=%s",
                        _MARKER,
                        getattr(module, "__name__", "unknown"),
                        removed,
                        str(cycle).lower(),
                        status,
                    )

        guard_broker = getattr(depth_guard, "_patch_loaded_broker_modules", None)
        if callable(guard_broker):
            guard_broker()
        patch_loaded = getattr(convergence, "_patch_loaded", None)
        if callable(patch_loaded):
            patch_loaded()
        ready, _details = depth_guard.audit()
        return bool(ready)
    except Exception:
        logger.debug("scan convergence deferred", exc_info=True)
        return False


def _publish_release() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        ready, details = manifest._audit()
        manifest._publish(bool(ready), details)
        return bool(ready)
    except Exception:
        logger.debug("release manifest convergence deferred", exc_info=True)
        return False


def _activation_step(release_ready: bool) -> bool:
    required = (
        release_ready,
        _truthy("NIJA_RUNTIME_MODULE_IDENTITY_READY"),
        _truthy("NIJA_SCAN_WRAPPER_DEPTH_READY"),
        _truthy("NIJA_ZERO_SIGNAL_STREAK_STATE_READY"),
        _truthy("NIJA_PRE_DISPATCH_RISK_SIZING_READY"),
        _truthy("LIVE_CAPITAL_VERIFIED"),
        not _truthy("DRY_RUN_MODE"),
        not _truthy("PAPER_MODE"),
    )
    if not all(required):
        return False
    try:
        monitor = importlib.import_module("bot.activation_pending_commit_monitor_patch")
        install_repairs = getattr(monitor, "_install_startup_execution_repairs", None)
        broker_loaded = getattr(monitor, "_broker_manager_module_loaded", None)
        if callable(install_repairs) and callable(broker_loaded) and broker_loaded():
            install_repairs()
        sm = monitor._state_machine()
        if sm is None:
            return False
        state = monitor._current_state_value(sm)
        if state == "LIVE_ACTIVE":
            return True
        if state != "LIVE_PENDING_CONFIRMATION":
            return False
        accepted, meta = monitor._capital_ready_snapshot()
        if not accepted:
            return False
        committed = bool(monitor._commit_once(sm, meta))
        return committed and monitor._current_state_value(sm) == "LIVE_ACTIVE"
    except Exception:
        logger.debug("activation convergence deferred", exc_info=True)
        return False


def _cycle() -> dict[str, bool]:
    okx = _ensure_okx_patch_idempotence()
    risk = _ensure_downstream_risk()
    zero_signal = _ensure_zero_signal_state()
    scan = _ensure_scan_chain()
    release = _publish_release()
    activation = _activation_step(release)
    return {
        "okx_idempotent": okx,
        "risk": risk,
        "zero_signal": zero_signal,
        "scan": scan,
        "release": release,
        "activation": activation,
    }


def _monitor() -> None:
    global _LAST_SIGNATURE
    initial_delay = max(0.25, float(os.environ.get("NIJA_RUNTIME_V15_INITIAL_DELAY_S", "1.0") or 1.0))
    interval = max(0.5, float(os.environ.get("NIJA_RUNTIME_V15_INTERVAL_S", "2.0") or 2.0))
    time.sleep(initial_delay)
    while True:
        try:
            state = _cycle()
            signature = repr(state)
            if signature != _LAST_SIGNATURE:
                _LAST_SIGNATURE = signature
                logger.log(
                    logging.INFO if state.get("release") else logging.WARNING,
                    "RUNTIME_CONVERGENCE_V15_STATE marker=%s state=%s persistent=true safety_gates_bypassed=false",
                    _MARKER,
                    state,
                )
        except Exception:
            logger.exception("RUNTIME_CONVERGENCE_V15_RETRY marker=%s", _MARKER)
        time.sleep(interval)


def install() -> bool:
    global _STARTED
    with _LOCK:
        if _STARTED:
            return True
        _STARTED = True
        os.environ["NIJA_RUNTIME_CONVERGENCE_V15_INSTALLED"] = "1"
        thread = threading.Thread(target=_monitor, name="RuntimeConvergenceV15", daemon=True)
        thread.start()
        logger.critical(
            "RUNTIME_CONVERGENCE_V15_INSTALLED marker=%s persistent=true activation_path=normal_commit safety_gates_bypassed=false thread_alive=%s",
            _MARKER,
            thread.is_alive(),
        )
        return True


__all__ = [
    "install",
    "_cycle",
    "_chain_contains",
    "_ensure_okx_patch_idempotence",
    "_ensure_zero_signal_state",
    "_ensure_downstream_risk",
    "_ensure_scan_chain",
    "_publish_release",
    "_activation_step",
]
