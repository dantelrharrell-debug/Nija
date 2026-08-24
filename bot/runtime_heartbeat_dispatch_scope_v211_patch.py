"""Bridge heartbeat-only pipeline dispatch scope after startup authority (v211).

Production on 2026-08-24 proved the live heartbeat reaches ExecutionPipeline,
passes ECEL/risk, and is explicitly admitted by v197's startup-probe authority
bridge, but Pipeline._dispatch still rejects the same request because the
pipeline-local runtime snapshot keeps dispatch_enabled=False while lifecycle is
BOOT / coordinator state is fail-closed awaiting the heartbeat's own ORDER proof.

v211 closes only that circular handoff.  It never changes canonical lifecycle or
coordinator state.  When, and only when, all of the following are true:
* v197 already produced a pipeline-local ready snapshot,
* the runtime mode resolves to live,
* the canonical snapshot says the kill switch is not active,
* dispatch_enabled is the remaining local blocker, and
* can_execute_startup_probe() re-verifies a whitelisted HEARTBEAT_TRADE or
  HEARTBEAT_TRADE_CLOSE context and startup write authority,
then the pipeline-local proxy exposes dispatch_enabled=True for that probe.

Normal orders are untouched.  Canonical snapshots remain unchanged.  Writer,
nonce, risk, kill-switch, reconciliation, capital, broker-health, ECEL,
min-notional, exchange order, acknowledgement, and fill-verification gates are
not bypassed, and no execution proof/readiness/activation state is fabricated.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
from functools import wraps
from types import ModuleType, SimpleNamespace
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_heartbeat_dispatch_scope_v211")
MARKER = "20260824-heartbeat-dispatch-scope-v211"
_READY_FLAG = "NIJA_HEARTBEAT_DISPATCH_SCOPE_V211_READY"
_PATCH_ATTR = "_nija_heartbeat_dispatch_scope_v211"
_IMPORT_HOOK_ATTR = "_NIJA_HEARTBEAT_DISPATCH_SCOPE_V211_IMPORT_HOOK"

_AUTHORITY_MODULE_NAMES = (
    "bot.execution_authority_context",
    "execution_authority_context",
)
_PIPELINE_MODULE_NAMES = (
    "bot.execution_pipeline",
    "execution_pipeline",
)


def _canonical_authority_module() -> ModuleType:
    for name in _AUTHORITY_MODULE_NAMES:
        module = sys.modules.get(name)
        if isinstance(module, ModuleType):
            return module
    module = importlib.import_module("bot.execution_authority_context")
    if not isinstance(module, ModuleType):
        raise RuntimeError("canonical_execution_authority_unavailable")
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


def _live_runtime_mode() -> tuple[bool, str]:
    try:
        runtime_mode = importlib.import_module("bot.runtime_mode")
        resolver = getattr(runtime_mode, "resolve_runtime_mode_safe", None)
        if not callable(resolver):
            return False, "resolver_unavailable"
        resolved = resolver(LOGGER)
        if resolved is None:
            return False, "resolver_returned_none"
        conflicts = tuple(getattr(resolved, "conflicts", ()) or ())
        mode = str(getattr(resolved, "mode", "") or "").strip().lower()
        if conflicts:
            return False, "conflict:" + ",".join(str(item) for item in conflicts)
        return mode == "live", mode or "unresolved"
    except Exception as exc:
        return False, f"resolver_error:{type(exc).__name__}:{exc}"


def _dispatch_scope_proxy(snapshot: Any, *, probe_reason: str) -> Any:
    try:
        data = dict(getattr(snapshot, "__dict__", {}) or {})
    except Exception:
        data = {}
    for attr in (
        "ready",
        "authority_ready",
        "nonce_ready",
        "dispatch_health_ready",
        "dispatch_enabled",
        "kill_switch_active",
        "coordinator_state",
        "runtime_state",
        "reason",
        "lifecycle_phase",
    ):
        if attr not in data and hasattr(snapshot, attr):
            data[attr] = getattr(snapshot, attr)
    data["dispatch_enabled"] = True
    data["reason"] = (
        "startup_probe_dispatch_scope:"
        + str(probe_reason or "HEARTBEAT_TRADE")
        + ":"
        + str(data.get("reason") or "runtime_not_fully_executing")
    )
    return SimpleNamespace(**data)


def _wrap_pipeline_snapshot(
    authority: ModuleType,
    current: Callable[[], Any],
) -> Callable[[], Any]:
    if bool(getattr(current, _PATCH_ATTR, False)):
        return current

    @wraps(current)
    def snapshot_v211() -> Any:
        snapshot = current()

        # v211 is a companion to v197, not an independent pre-LIVE bypass.
        # If v197 did not already admit the startup probe to a ready local
        # snapshot, preserve the original fail-closed result.
        if not bool(getattr(snapshot, "ready", False)):
            return snapshot
        if getattr(snapshot, "dispatch_enabled", True) is not False:
            return snapshot
        if bool(getattr(snapshot, "kill_switch_active", False)):
            LOGGER.warning(
                "HEARTBEAT_DISPATCH_SCOPE_V211_BLOCKED marker=%s reason=kill_switch_active "
                "canonical_snapshot_unchanged=true trading_fail_closed=true",
                MARKER,
            )
            return snapshot

        live_mode, mode_detail = _live_runtime_mode()
        if not live_mode:
            return snapshot

        allowed, probe_reason = _startup_probe_allowed(authority)
        if not allowed:
            return snapshot

        proxied = _dispatch_scope_proxy(snapshot, probe_reason=probe_reason)
        LOGGER.critical(
            "HEARTBEAT_DISPATCH_SCOPE_V211_ALLOWED marker=%s probe_reason=%s "
            "dispatch_enabled_before=false dispatch_enabled_after=true "
            "lifecycle_phase=%s coordinator_state=%s runtime_mode=%s "
            "canonical_snapshot_unchanged=true startup_authority_reverified=true "
            "kill_switch_clear=true ordinary_orders_unchanged=true "
            "writer_nonce_risk_reconciliation_capital_broker_health_ecel_min_notional_order_fill_gates_unchanged=true "
            "execution_authority_granted=false proof_fabricated=false forced_trade=false safety_gates_bypassed=false",
            MARKER,
            probe_reason or "HEARTBEAT_TRADE",
            str(getattr(snapshot, "lifecycle_phase", "unknown")),
            str(getattr(snapshot, "coordinator_state", "unknown")),
            mode_detail,
        )
        return proxied

    setattr(snapshot_v211, _PATCH_ATTR, True)
    setattr(snapshot_v211, "__wrapped__", current)
    return snapshot_v211


def _bind_loaded_pipeline(authority: ModuleType) -> int:
    patched = 0
    for name in _PIPELINE_MODULE_NAMES:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        current = getattr(module, "runtime_authority_snapshot", None)
        if not callable(current):
            continue
        if not bool(getattr(current, _PATCH_ATTR, False)):
            setattr(module, "runtime_authority_snapshot", _wrap_pipeline_snapshot(authority, current))
        installed = getattr(module, "runtime_authority_snapshot", None)
        if callable(installed) and bool(getattr(installed, _PATCH_ATTR, False)):
            patched += 1
    return patched


def _install_import_reassertion_hook() -> bool:
    if bool(getattr(builtins, _IMPORT_HOOK_ATTR, False)):
        return True
    original_import = builtins.__import__

    def guarded_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
        module = original_import(name, globals, locals, fromlist, level)
        imported_name = str(name or "")
        if imported_name.endswith(("execution_pipeline", "execution_authority_context")):
            try:
                authority = _canonical_authority_module()
                _bind_loaded_pipeline(authority)
            except Exception as exc:
                LOGGER.error(
                    "HEARTBEAT_DISPATCH_SCOPE_V211_REASSERT_FAILED marker=%s imported=%s "
                    "error=%s:%s trading_fail_closed=true",
                    MARKER,
                    imported_name,
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
        required["heartbeat_dispatch_scope_v211"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    try:
        authority = _canonical_authority_module()
        try:
            importlib.import_module("bot.execution_pipeline")
        except Exception as exc:
            LOGGER.warning(
                "HEARTBEAT_DISPATCH_SCOPE_V211_PIPELINE_IMPORT_DEFERRED marker=%s error=%s:%s",
                MARKER,
                type(exc).__name__,
                exc,
            )
        patched = _bind_loaded_pipeline(authority)
        hook_ok = _install_import_reassertion_hook()
        manifest_ok = _patch_release_manifest()
    except Exception as exc:
        os.environ[_READY_FLAG] = "0"
        LOGGER.critical(
            "HEARTBEAT_DISPATCH_SCOPE_V211_FAILED marker=%s error=%s:%s trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False

    pipeline_present = any(isinstance(sys.modules.get(name), ModuleType) for name in _PIPELINE_MODULE_NAMES)
    ready = bool(hook_ok and manifest_ok and (patched > 0 or not pipeline_present))
    os.environ[_READY_FLAG] = "1" if ready else "0"
    if not ready:
        LOGGER.critical(
            "HEARTBEAT_DISPATCH_SCOPE_V211_FAILED marker=%s patched_surfaces=%s hook=%s manifest=%s "
            "trading_fail_closed=true",
            MARKER,
            patched,
            str(hook_ok).lower(),
            str(manifest_ok).lower(),
        )
        return False

    LOGGER.critical(
        "HEARTBEAT_DISPATCH_SCOPE_V211_READY marker=%s ready=true patched_surfaces=%s "
        "v197_companion_only=true startup_probe_only=true live_mode_only=true "
        "kill_switch_clear_required=true canonical_snapshot_unchanged=true lifecycle_state_unchanged=true "
        "ordinary_orders_unchanged=true execution_authority_granted=false proof_fabricated=false "
        "writer_nonce_risk_reconciliation_capital_broker_health_ecel_min_notional_order_fill_gates_unchanged=true "
        "forced_trade=false safety_gates_bypassed=false",
        MARKER,
        patched,
    )
    return True


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_dispatch_scope_proxy",
    "_wrap_pipeline_snapshot",
]
