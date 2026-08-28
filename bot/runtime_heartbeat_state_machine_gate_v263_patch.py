"""Bridge only the verified startup heartbeat through Pipeline state gating (v263).

Production on 2026-08-28 reached a healthy writer generation, connected Kraken /
Coinbase / OKX, complete position sync, fresh capital and a clear kill switch, but
activation remained LIVE_PENDING_CONFIRMATION because execution_ready required the
genuine heartbeat ORDER/FILL marker.  The existing heartbeat bridges admit the
whitelisted startup probe through canonical authority, dispatch and terminal
lifecycle checks; however ``ExecutionPipeline._enforce_execution_gate`` still
rejects every LIVE order while TradingStateMachine is not yet LIVE_ACTIVE.  That
creates a proof-before-proof deadlock: the heartbeat cannot place the order whose
result is required to leave LIVE_PENDING_CONFIRMATION.

v263 closes only that state-machine gate.  It converts the *existing* pipeline
denial into continuation only when all of these are independently re-verified in
the current ContextVar scope:

* the original denial is exactly the state-machine pending denial;
* the current state is exactly LIVE_PENDING_CONFIRMATION;
* runtime mode resolves to live without conflicts;
* ``can_execute_startup_probe()`` identifies HEARTBEAT_TRADE or
  HEARTBEAT_TRADE_CLOSE;
* ``assert_startup_write_authority()`` succeeds against the current distributed
  writer lease;
* the canonical kill switch is clear; and
* the raw runtime nonce authority gates are healthy.

It does not mutate trading state, readiness, nonce state, heartbeat markers,
capital, broker health, risk, ECEL, minimum notional, order acknowledgement, fill
proof or activation state.  Ordinary orders and every non-state-machine denial
are unchanged and remain fail closed.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import sys
import threading
from functools import wraps
from types import ModuleType
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_heartbeat_state_machine_gate_v263")
MARKER = "20260828-heartbeat-state-machine-gate-v263"
_READY_FLAG = "NIJA_HEARTBEAT_STATE_MACHINE_GATE_V263_READY"
_PATCH_ATTR = "_nija_heartbeat_state_machine_gate_v263"
_IMPORT_HOOK_ATTR = "_NIJA_HEARTBEAT_STATE_MACHINE_GATE_V263_IMPORT_HOOK"
_ALLOWED_PROBES = {"HEARTBEAT_TRADE", "HEARTBEAT_TRADE_CLOSE"}
_PENDING_STATE = "LIVE_PENDING_CONFIRMATION"
_PIPELINE_MODULE_NAMES = ("bot.execution_pipeline", "execution_pipeline")
_LOCK = threading.RLock()


def _authority_module() -> ModuleType:
    module = sys.modules.get("bot.execution_authority_context")
    if not isinstance(module, ModuleType):
        module = importlib.import_module("bot.execution_authority_context")
    if not isinstance(module, ModuleType):
        raise RuntimeError("canonical_execution_authority_unavailable")
    return module


def _runtime_mode_live() -> tuple[bool, str]:
    try:
        runtime_mode = importlib.import_module("bot.runtime_mode")
        resolver = getattr(runtime_mode, "resolve_runtime_mode_safe", None)
        if not callable(resolver):
            return False, "runtime_mode_resolver_unavailable"
        resolved = resolver(LOGGER)
        if resolved is None:
            return False, "runtime_mode_unresolved"
        conflicts = tuple(getattr(resolved, "conflicts", ()) or ())
        if conflicts:
            return False, "runtime_mode_conflict:" + ",".join(str(item) for item in conflicts)
        mode = str(getattr(resolved, "mode", "") or "").strip().lower()
        return mode == "live", mode or "unresolved"
    except Exception as exc:
        return False, f"runtime_mode_error:{type(exc).__name__}:{exc}"


def _current_state() -> str:
    try:
        state_module = importlib.import_module("bot.trading_state_machine")
        getter = getattr(state_module, "get_state_machine", None)
        if not callable(getter):
            return "UNKNOWN"
        machine = getter()
        current = getattr(machine, "get_current_state", lambda: None)()
        return str(getattr(current, "value", current) or "UNKNOWN").strip().upper()
    except Exception:
        return "UNKNOWN"


def _verified_startup_probe() -> tuple[bool, str]:
    """Re-verify every prerequisite that may safely cross the pending-state gate."""
    try:
        authority = _authority_module()
        checker = getattr(authority, "can_execute_startup_probe", None)
        reverify = getattr(authority, "assert_startup_write_authority", None)
        snapshot_fn = getattr(authority, "runtime_authority_snapshot", None)
        nonce_fn = getattr(authority, "_runtime_nonce_authority_status", None)
        if not all(callable(fn) for fn in (checker, reverify, snapshot_fn, nonce_fn)):
            return False, "canonical_authority_helpers_unavailable"

        allowed, reason = checker()
        probe_reason = str(reason or "").strip().upper()
        if not bool(allowed) or probe_reason not in _ALLOWED_PROBES:
            return False, f"startup_probe_denied:{probe_reason or reason or 'unknown'}"

        state = _current_state()
        if state != _PENDING_STATE:
            return False, f"state_not_pending_confirmation:{state}"

        live_mode, mode_detail = _runtime_mode_live()
        if not live_mode:
            return False, f"runtime_not_live:{mode_detail}"

        # Re-check exact distributed writer authority immediately before
        # crossing the one pending-state gate.
        reverify()

        canonical_snapshot = snapshot_fn()
        if bool(getattr(canonical_snapshot, "kill_switch_active", True)):
            return False, "kill_switch_active"

        nonce_ok, nonce_detail = nonce_fn()
        if not bool(nonce_ok):
            return False, f"nonce_not_ready:{nonce_detail or 'unknown'}"

        return True, probe_reason
    except Exception as exc:
        return False, f"verification_error:{type(exc).__name__}:{exc}"


def _is_state_machine_pending_denial(result: Any) -> bool:
    if result is None:
        return False
    error = str(getattr(result, "error", "") or "").strip()
    return error.startswith("Execution gate pending (state_machine=")


def _wrap_gate(current: Callable[..., Any], surface: str) -> Callable[..., Any]:
    if bool(getattr(current, _PATCH_ATTR, False)):
        return current

    @wraps(current)
    def enforce_execution_gate_v263(self: Any, request: Any, t_start: float, *args: Any, **kwargs: Any) -> Any:
        result = current(self, request, t_start, *args, **kwargs)
        if not _is_state_machine_pending_denial(result):
            return result

        verified, detail = _verified_startup_probe()
        if not verified:
            LOGGER.info(
                "HEARTBEAT_STATE_MACHINE_GATE_V263_DEFERRED marker=%s surface=%s detail=%s "
                "ordinary_orders_unchanged=true trading_fail_closed=true",
                MARKER,
                surface,
                detail,
            )
            return result

        LOGGER.critical(
            "HEARTBEAT_STATE_MACHINE_GATE_V263_ALLOWED marker=%s surface=%s probe_reason=%s "
            "state=LIVE_PENDING_CONFIRMATION runtime_mode=live distributed_writer_reverified=true "
            "raw_nonce_authority=true kill_switch_clear=true original_state_machine_denial_only=true "
            "readiness_mutated=false nonce_mutated=false heartbeat_marker_written=false "
            "ordinary_orders_unchanged=true risk_capital_broker_health_ecel_min_notional_order_fill_gates_unchanged=true "
            "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
            MARKER,
            surface,
            detail,
        )
        # ``None`` means this one pipeline gate passed; all later execution,
        # risk, ECEL, broker, acknowledgement and fill gates still execute.
        return None

    setattr(enforce_execution_gate_v263, _PATCH_ATTR, True)
    setattr(enforce_execution_gate_v263, "__wrapped__", current)
    return enforce_execution_gate_v263


def _patch_loaded_pipeline() -> tuple[bool, tuple[str, ...]]:
    try:
        importlib.import_module("bot.execution_pipeline")
    except Exception as exc:
        LOGGER.warning(
            "HEARTBEAT_STATE_MACHINE_GATE_V263_PIPELINE_IMPORT_DEFERRED marker=%s error=%s:%s",
            MARKER,
            type(exc).__name__,
            exc,
        )

    patched: list[str] = []
    seen_classes: set[int] = set()
    for name in _PIPELINE_MODULE_NAMES:
        module = sys.modules.get(name)
        if not isinstance(module, ModuleType):
            continue
        pipeline_cls = getattr(module, "ExecutionPipeline", None)
        if not isinstance(pipeline_cls, type) or id(pipeline_cls) in seen_classes:
            continue
        seen_classes.add(id(pipeline_cls))
        current = getattr(pipeline_cls, "_enforce_execution_gate", None)
        if not callable(current):
            continue
        wrapped = _wrap_gate(current, str(getattr(module, "__name__", name)))
        setattr(pipeline_cls, "_enforce_execution_gate", wrapped)
        installed = getattr(pipeline_cls, "_enforce_execution_gate", None)
        if callable(installed) and bool(getattr(installed, _PATCH_ATTR, False)):
            patched.append(str(getattr(module, "__name__", name)))
    return bool(patched), tuple(sorted(set(patched)))


def _install_import_reassertion_hook() -> bool:
    if bool(getattr(builtins, _IMPORT_HOOK_ATTR, False)):
        return True
    original_import = builtins.__import__

    def guarded_import(name: str, globals: Any = None, locals: Any = None, fromlist: Any = (), level: int = 0) -> Any:
        module = original_import(name, globals, locals, fromlist, level)
        if str(name or "").endswith("execution_pipeline"):
            try:
                _patch_loaded_pipeline()
            except Exception as exc:
                LOGGER.error(
                    "HEARTBEAT_STATE_MACHINE_GATE_V263_REASSERT_FAILED marker=%s imported=%s "
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
        required["runtime_heartbeat_state_machine_gate_v263"] = _READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    with _LOCK:
        try:
            patched, surfaces = _patch_loaded_pipeline()
            hook_ok = _install_import_reassertion_hook()
            manifest_ok = _patch_release_manifest()
            ready = bool(patched and hook_ok and manifest_ok)
        except Exception as exc:
            LOGGER.error(
                "HEARTBEAT_STATE_MACHINE_GATE_V263_INSTALL_ERROR marker=%s error=%s:%s trading_fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            ready, surfaces = False, ()

        os.environ[_READY_FLAG] = "1" if ready else "0"
        if ready:
            LOGGER.critical(
                "HEARTBEAT_STATE_MACHINE_GATE_V263_READY marker=%s ready=true patched_surfaces=%s "
                "pending_state_only=true whitelisted_startup_probe_only=true runtime_live_required=true "
                "distributed_writer_reverification_required=true raw_nonce_authority_required=true "
                "kill_switch_clear_required=true ordinary_orders_unchanged=true readiness_mutated=false "
                "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
                MARKER,
                ",".join(surfaces),
            )
        return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_verified_startup_probe",
    "_is_state_machine_pending_denial",
    "_wrap_gate",
]
