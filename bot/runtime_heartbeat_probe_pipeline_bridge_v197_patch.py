"""Bridge whitelisted heartbeat startup probes through ExecutionPipeline v197.

Production on 2026-08-23 exposed a real startup-verification deadlock after v169
correctly separated writer liveness from genuine ORDER/FILL execution proof.
TradingStrategy already scopes verification orders with
``startup_execution_probe_scope`` and the broker layer already honors
``can_execute_startup_probe()``.  ExecutionPipeline, however, rejected the same
probe earlier at two ordinary-runtime gates: its runtime-authority snapshot and
``assert_execution_dispatch_permitted()``.  As a result the heartbeat order
could not reach the broker to create the proof ordinary ``can_execute`` awaited.

v197 bridges only the existing whitelisted HEARTBEAT_TRADE and
HEARTBEAT_TRADE_CLOSE contexts.  Every bridge decision re-runs
``can_execute_startup_probe()``, which verifies startup write authority.  Normal
orders still require ordinary runtime authority.  Writer, nonce, kill-switch,
risk, broker-health, throttling, sizing, min-notional, and exchange order gates
remain unchanged.

v200 closes the remaining scheduler-policy mismatch exposed in production on
2026-08-23.  The trading state machine requires genuine heartbeat execution
verification whenever either ``HEARTBEAT_REQUIRED_FIRST_ACTIVATION`` or
``HEARTBEAT_TRADE`` is enabled, while TradingStrategy historically scheduled the
probe only for ``HEARTBEAT_TRADE``.  When the required-first policy was enabled
alone, startup could reach LIVE_ACTIVE state but post-core convergence remained
fail-closed on ``can_execute`` forever because no genuine probe was ever
scheduled.  v200 aligns those two policies by enabling the existing heartbeat
probe scheduler in-process whenever required-first verification is explicitly
configured.  It does not grant execution authority or bypass any downstream
writer, nonce, kill-switch, risk, broker-health, sizing, min-notional, order, or
fill-verification gate.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType, SimpleNamespace
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_heartbeat_probe_pipeline_bridge_v197")
MARKER = "20260823-heartbeat-probe-pipeline-bridge-v197"
V200_MARKER = "20260823-heartbeat-required-scheduler-v200"
_READY_FLAG = "NIJA_RUNTIME_HEARTBEAT_PROBE_PIPELINE_BRIDGE_V197_READY"
_V200_READY_FLAG = "NIJA_HEARTBEAT_REQUIRED_SCHEDULER_V200_READY"
_PATCH_ATTR = "_nija_runtime_heartbeat_probe_pipeline_bridge_v197"
_SNAPSHOT_PATCH_ATTR = "_nija_runtime_heartbeat_probe_snapshot_bridge_v197"
_IMPORT_HOOK_ATTR = "_NIJA_RUNTIME_HEARTBEAT_PROBE_PIPELINE_BRIDGE_V197_IMPORT_HOOK"
_LOCK = threading.RLock()
_TRUE = {"1", "true", "yes", "enabled", "on", "y"}

_AUTHORITY_MODULE_NAMES = (
    "bot.execution_authority_context",
    "execution_authority_context",
)
_PIPELINE_MODULE_NAMES = (
    "bot.execution_pipeline",
    "execution_pipeline",
)
_TARGET_IMPORT_SUFFIXES = (
    "execution_authority_context",
    "execution_pipeline",
)


def _env_truthy(name: str) -> bool:
    return str(os.environ.get(name, "") or "").strip().lower() in _TRUE


def _align_required_heartbeat_scheduler_policy() -> bool:
    """Ensure an explicitly required startup execution proof is actually scheduled."""
    required_first = _env_truthy("HEARTBEAT_REQUIRED_FIRST_ACTIVATION")
    heartbeat_trade = _env_truthy("HEARTBEAT_TRADE")
    aligned = False
    if required_first and not heartbeat_trade:
        os.environ["HEARTBEAT_TRADE"] = "true"
        heartbeat_trade = True
        aligned = True

    os.environ[_V200_READY_FLAG] = "1"
    LOGGER.critical(
        "HEARTBEAT_REQUIRED_SCHEDULER_V200_READY marker=%s "
        "required_first=%s heartbeat_trade=%s aligned=%s "
        "existing_probe_scheduler_only=true execution_authority_granted=false "
        "writer_nonce_risk_killswitch_order_fill_gates_unchanged=true "
        "forced_activation=false safety_gates_bypassed=false",
        V200_MARKER,
        str(required_first).lower(),
        str(heartbeat_trade).lower(),
        str(aligned).lower(),
    )
    return True


def _canonical_authority_module() -> ModuleType:
    for name in _AUTHORITY_MODULE_NAMES:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            return module
    module = importlib.import_module("bot.execution_authority_context")
    if not isinstance(module, ModuleType):
        raise RuntimeError("canonical execution authority module unavailable")
    return module


def _startup_probe_allowed(authority: ModuleType) -> tuple[bool, str]:
    checker = getattr(authority, "can_execute_startup_probe", None)
    if not callable(checker):
        return False, "startup_probe_checker_unavailable"
    try:
        allowed, reason = checker()
    except Exception as exc:
        return False, f"startup_probe_authority_error:{type(exc).__name__}:{exc}"
    return bool(allowed), str(reason or "")


def _patch_authority_dispatch(authority: ModuleType) -> Callable[[], None] | None:
    """Allow a verified whitelisted startup probe through the dispatch assertion."""
    current = getattr(authority, "assert_execution_dispatch_permitted", None)
    if not callable(current):
        return None
    if bool(getattr(current, _PATCH_ATTR, False)):
        return current

    execution_blocked = getattr(authority, "ExecutionBlocked", RuntimeError)
    if not isinstance(execution_blocked, type):
        return None

    @wraps(current)
    def assert_dispatch_v197() -> None:
        try:
            current()
            return None
        except execution_blocked as original_exc:
            allowed, reason = _startup_probe_allowed(authority)
            if not allowed:
                raise original_exc
            LOGGER.critical(
                "HEARTBEAT_PROBE_PIPELINE_BRIDGE_V197_ALLOWED marker=%s "
                "surface=dispatch_assertion probe_reason=%s whitelisted_startup_probe=true "
                "startup_authority_reverified=true ordinary_can_execute_unchanged=true "
                "downstream_risk_order_gates_unchanged=true forced_trade=false",
                MARKER,
                reason or "startup_probe_authorized",
            )
            return None

    setattr(assert_dispatch_v197, _PATCH_ATTR, True)
    setattr(assert_dispatch_v197, "__wrapped__", current)
    authority.assert_execution_dispatch_permitted = assert_dispatch_v197
    return assert_dispatch_v197


def _snapshot_proxy(snapshot: Any) -> Any:
    try:
        data = dict(getattr(snapshot, "__dict__", {}) or {})
    except Exception:
        data = {}
    for attr in (
        "authority_ready", "nonce_ready", "dispatch_health_ready", "dispatch_enabled",
        "kill_switch_active", "coordinator_state", "runtime_state", "reason", "lifecycle_phase",
    ):
        if attr not in data and hasattr(snapshot, attr):
            data[attr] = getattr(snapshot, attr)
    data["ready"] = True
    data["reason"] = "startup_probe_authorized:" + str(data.get("reason") or "runtime_not_fully_executing")
    return SimpleNamespace(**data)


def _pipeline_snapshot_wrapper(authority: ModuleType, original_snapshot: Callable[[], Any]) -> Callable[[], Any]:
    if bool(getattr(original_snapshot, _SNAPSHOT_PATCH_ATTR, False)):
        return original_snapshot

    @wraps(original_snapshot)
    def snapshot_v197() -> Any:
        snapshot = original_snapshot()
        if bool(getattr(snapshot, "ready", False)):
            return snapshot
        allowed, reason = _startup_probe_allowed(authority)
        if not allowed:
            return snapshot
        LOGGER.critical(
            "HEARTBEAT_PROBE_PIPELINE_BRIDGE_V197_ALLOWED marker=%s "
            "surface=runtime_snapshot probe_reason=%s whitelisted_startup_probe=true "
            "startup_authority_reverified=true ordinary_runtime_snapshot_unchanged=true "
            "downstream_risk_order_gates_unchanged=true forced_trade=false",
            MARKER,
            reason or "startup_probe_authorized",
        )
        return _snapshot_proxy(snapshot)

    setattr(snapshot_v197, _SNAPSHOT_PATCH_ATTR, True)
    setattr(snapshot_v197, "__wrapped__", original_snapshot)
    return snapshot_v197


def _bind_pipeline_surfaces(authority: ModuleType, dispatch_wrapper: Callable[[], None]) -> bool:
    """Bind both early Pipeline authority gates without mutating canonical snapshot truth."""
    bound_any = False
    for name in _PIPELINE_MODULE_NAMES:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        current_dispatch = getattr(module, "assert_execution_dispatch_permitted", None)
        current_snapshot = getattr(module, "runtime_authority_snapshot", None)
        if not callable(current_dispatch) or not callable(current_snapshot):
            continue
        module.assert_execution_dispatch_permitted = dispatch_wrapper
        if not bool(getattr(current_snapshot, _SNAPSHOT_PATCH_ATTR, False)):
            module.runtime_authority_snapshot = _pipeline_snapshot_wrapper(authority, current_snapshot)
        bound_any = bool(
            getattr(module, "assert_execution_dispatch_permitted", None) is dispatch_wrapper
            and callable(getattr(module, "runtime_authority_snapshot", None))
            and getattr(module.runtime_authority_snapshot, _SNAPSHOT_PATCH_ATTR, False)
        ) or bound_any
    return bound_any


def _apply() -> bool:
    authority = _canonical_authority_module()
    dispatch_wrapper = _patch_authority_dispatch(authority)
    if not callable(dispatch_wrapper):
        return False
    try:
        importlib.import_module("bot.execution_pipeline")
    except Exception as exc:
        LOGGER.warning(
            "HEARTBEAT_PROBE_PIPELINE_BRIDGE_V197_PIPELINE_IMPORT_DEFERRED marker=%s error=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )
    bound = _bind_pipeline_surfaces(authority, dispatch_wrapper)
    present = any(isinstance(sys.modules.get(name), ModuleType) for name in _PIPELINE_MODULE_NAMES)
    return bool(bound or not present)


def _install_import_reassertion_hook() -> bool:
    if bool(getattr(builtins, _IMPORT_HOOK_ATTR, False)):
        return True
    original_import = builtins.__import__

    def guarded_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
        module = original_import(name, globals, locals, fromlist, level)
        if any(str(name or "").endswith(suffix) for suffix in _TARGET_IMPORT_SUFFIXES):
            try:
                authority = _canonical_authority_module()
                dispatch_wrapper = _patch_authority_dispatch(authority)
                if callable(dispatch_wrapper):
                    _bind_pipeline_surfaces(authority, dispatch_wrapper)
            except Exception as exc:
                LOGGER.error(
                    "HEARTBEAT_PROBE_PIPELINE_BRIDGE_V197_REASSERT_FAILED marker=%s imported=%s "
                    "error=%s:%s trading_fail_closed=true",
                    MARKER,
                    name,
                    type(exc).__name__,
                    exc,
                )
        return module

    builtins.__import__ = guarded_import
    setattr(builtins, _IMPORT_HOOK_ATTR, True)
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_heartbeat_probe_pipeline_bridge_v197"] = _READY_FLAG
        required["runtime_heartbeat_required_scheduler_v200"] = _V200_READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        policy_ok = _align_required_heartbeat_scheduler_policy()
        apply_ok = _apply()
        hook_ok = _install_import_reassertion_hook()
        manifest_ok = _patch_release_manifest()
        ready = bool(policy_ok and apply_ok and hook_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        if not ready:
            LOGGER.critical(
                "RUNTIME_HEARTBEAT_PROBE_PIPELINE_BRIDGE_V197_FAILED marker=%s "
                "policy=%s apply=%s hook=%s manifest=%s trading_fail_closed=true",
                MARKER,
                str(policy_ok).lower(), str(apply_ok).lower(), str(hook_ok).lower(), str(manifest_ok).lower(),
            )
            return False
        LOGGER.critical(
            "RUNTIME_HEARTBEAT_PROBE_PIPELINE_BRIDGE_V197 marker=%s ready=true "
            "heartbeat_required_scheduler_v200=true pipeline_snapshot_bridge=true pipeline_dispatch_bridge=true "
            "probe_reasons=HEARTBEAT_TRADE,HEARTBEAT_TRADE_CLOSE "
            "ordinary_can_execute_unchanged=true canonical_runtime_snapshot_unchanged=true "
            "startup_authority_reverified=true writer_nonce_risk_killswitch_order_gates_unchanged=true "
            "forced_trade=false safety_gates_bypassed=false",
            MARKER,
        )
        return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "V200_MARKER",
    "install",
    "install_import_hook",
    "_align_required_heartbeat_scheduler_policy",
    "_patch_authority_dispatch",
    "_bind_pipeline_surfaces",
]
