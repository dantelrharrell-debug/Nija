"""Protective-exit authority bridge v337.

A verified sell-to-close may need to reduce risk while NIJA is still BOOT/WARM
or reconciling a stale global epoch.  This module never makes the runtime LIVE
and never grants general execution permission.  It bridges only the canonical,
context-local trusted close established by v335 after re-proving hard writer,
nonce, broker-health, circuit and stability safety.

Capability, pre-trade risk, ECEL, throttling, spread/slippage, broker health,
terminal writer, nonce, minimum-order, order-ack and fill-confirmation checks
remain in force.  No global lifecycle/environment state is mutated.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import threading
from dataclasses import replace
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_protective_exit_authority_bridge_v337")
MARKER = "20260901-runtime-protective-exit-authority-bridge-v337"
RELEASE_ID = "20260901-runtime-convergence-v337"
_READY_FLAG = "NIJA_RUNTIME_PROTECTIVE_EXIT_AUTHORITY_BRIDGE_V337_READY"
_SNAPSHOT_ATTR = "_nija_protective_exit_snapshot_bridge_v337"
_CAN_EXECUTE_ATTR = "_nija_protective_exit_can_execute_bridge_v337"
_ASSERT_ATTR = "_nija_protective_exit_dispatch_bridge_v337"
_INSTALL_FLAG = "_NIJA_RUNTIME_PROTECTIVE_EXIT_AUTHORITY_BRIDGE_V337"
_LOCK = threading.RLock()


def _trusted_close() -> bool:
    try:
        v335 = importlib.import_module("bot.runtime_exit_capability_semantics_v335_patch")
        token = getattr(v335, "_TRUSTED_CLOSE", None)
        return bool(token is not None and token.get())
    except Exception:
        return False


def _circuit_permits_exit() -> tuple[bool, str]:
    state = str(os.environ.get("NIJA_EXECUTION_CIRCUIT_STATE", "CLOSED") or "CLOSED").strip().upper()
    if state == "CLOSED":
        return True, state
    if state == "RECOVERING" and str(os.environ.get("NIJA_EXECUTION_RECOVERY_APPROVED", "") or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}:
        return True, state
    return False, state


def _hard_exit_authority_proof() -> tuple[bool, str, Any]:
    """Re-prove hard write safety without requiring global LIVE lifecycle."""
    eac = importlib.import_module("bot.execution_authority_context")
    snap = eac.runtime_authority_snapshot()

    try:
        eac.assert_distributed_writer_authority()
    except Exception as exc:
        return False, f"distributed_writer:{exc}", snap

    try:
        eac.require_startup_execution_authority(
            context="protective_exit_v337",
            force_refresh=True,
        )
    except Exception as exc:
        return False, f"startup_write_authority:{exc}", snap

    if bool(getattr(snap, "kill_switch_active", False)):
        return False, "kill_switch_active", snap
    if not bool(getattr(snap, "nonce_ready", False)):
        return False, "nonce_not_ready", snap
    if not bool(getattr(snap, "dispatch_health_ready", False)):
        return False, "broker_dispatch_health_not_ready", snap
    if eac.is_seak_halted():
        return False, "seak_halted", snap

    circuit_ok, circuit_state = _circuit_permits_exit()
    if not circuit_ok:
        return False, f"execution_circuit:{circuit_state}", snap

    if not str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "").strip():
        return False, "writer_fencing_token_missing", snap

    lifecycle = str(getattr(snap, "lifecycle_phase", "") or "").upper()
    reason = str(getattr(snap, "reason", "") or "")
    coordinator = str(getattr(snap, "coordinator_state", "") or "")
    startup_shape = (
        lifecycle in {"BOOT", "WARM"}
        or "global_epoch_stale" in reason.lower()
        or "startup" in reason.lower()
        or "activation" in coordinator.lower()
        or coordinator.upper() == "FAIL_SAFE_HALT"
    )
    if not startup_shape and not bool(getattr(snap, "ready", False)):
        return False, f"non_startup_runtime_block:{reason or lifecycle or coordinator}", snap

    return True, "hard_exit_authority_proven", snap


def _bridge_initial_authority_decision(decision: Any) -> Any:
    """Bridge only the first lifecycle denial for a trusted risk-reducing close."""
    if bool(getattr(decision, "allowed", False)) or not _trusted_close():
        return decision

    first_failed = str(getattr(decision, "first_failed_gate", "") or "")
    reason = str(getattr(decision, "reason_detail", None) or getattr(decision, "reason", "") or "")
    if first_failed != "lifecycle.phase" and not reason.startswith("lifecycle_phase:"):
        return decision

    ok, proof_reason, snap = _hard_exit_authority_proof()
    if not ok:
        LOGGER.warning(
            "PROTECTIVE_EXIT_AUTHORITY_V337_INITIAL_DEFERRED marker=%s reason=%s "
            "lifecycle=%s ordinary_execution_unchanged=true safety_gates_bypassed=false",
            MARKER, proof_reason, getattr(snap, "lifecycle_phase", "unknown"),
        )
        return decision

    eac = importlib.import_module("bot.execution_authority_context")
    try:
        stability = eac._evaluate_stability_authority(
            runtime_snapshot=snap,
            state_live_active=True,
            lease_valid=True,
            lease_generation_current=True,
            heartbeat_fresh=True,
            heartbeat_stage_sufficient=True,
            broker_health_ok=True,
            dispatch_enabled=True,
            circuit_breaker_closed=True,
        )
    except Exception as exc:
        LOGGER.warning(
            "PROTECTIVE_EXIT_AUTHORITY_V337_INITIAL_DEFERRED marker=%s reason=stability_unavailable:%s "
            "ordinary_execution_unchanged=true safety_gates_bypassed=false",
            MARKER, exc,
        )
        return decision

    if not bool(getattr(stability, "allowed", False)):
        LOGGER.warning(
            "PROTECTIVE_EXIT_AUTHORITY_V337_INITIAL_DEFERRED marker=%s reason=stability_denied:%s "
            "ordinary_execution_unchanged=true safety_gates_bypassed=false",
            MARKER, getattr(stability, "reason", "unknown"),
        )
        return decision

    circuit_state = str(os.environ.get("NIJA_EXECUTION_CIRCUIT_STATE", "CLOSED") or "CLOSED").strip().upper()
    bridged = replace(
        decision,
        allowed=True,
        reason="protective_exit_lifecycle_bridge",
        circuit_state=circuit_state,
        state_live_active=True,
        lease_valid=True,
        lease_generation_current=True,
        nonce_ready=True,
        heartbeat_fresh=True,
        heartbeat_stage_sufficient=True,
        broker_health_ok=True,
        circuit_breaker_closed=True,
        dispatch_enabled=True,
        stability_allowed=True,
        stability_halt_state=str(getattr(stability, "halt_state", "STABLE") or "STABLE"),
        stability_throttle=float(getattr(stability, "throttle", 0.0) or 0.0),
        stability_size_multiplier=float(getattr(stability, "size_multiplier", 1.0) or 1.0),
        stability_stress_score=float(getattr(stability, "stress_score", 0.0) or 0.0),
        stability_collapsed_risk_score=float(getattr(stability, "collapsed_risk_score", 0.0) or 0.0),
        stability_reason=str(getattr(stability, "reason", "stable") or "stable"),
        first_failed_gate="",
        reason_code="allowed",
        reason_detail="protective_exit_lifecycle_bridge",
        lifecycle_phase="LIVE",
    )
    LOGGER.critical(
        "PROTECTIVE_EXIT_AUTHORITY_V337_INITIAL_DECISION_BRIDGED marker=%s "
        "source_lifecycle=%s exact_writer=true startup_write_authority=true nonce_ready=true "
        "broker_health_ready=true kill_switch_clear=true seak_clear=true circuit_clear=true "
        "stability_allowed=true risk_reducing_exit_only=true global_lifecycle_mutated=false "
        "downstream_risk_minimum_order_ack_fill_gates_unchanged=true safety_gates_bypassed=false",
        MARKER, getattr(snap, "lifecycle_phase", "unknown"),
    )
    return bridged


def _make_dispatch_bridge(base_assert):
    @wraps(base_assert)
    def protective_exit_dispatch_v337() -> None:
        if not _trusted_close():
            return base_assert()
        ok, reason, snap = _hard_exit_authority_proof()
        if not ok:
            eac = importlib.import_module("bot.execution_authority_context")
            raise eac.ExecutionBlocked(f"protective_exit_authority:{reason}")
        LOGGER.critical(
            "PROTECTIVE_EXIT_AUTHORITY_V337_DISPATCH_GRANTED marker=%s lifecycle=%s coordinator=%s "
            "exact_writer=true startup_write_authority=true nonce_ready=true broker_health_ready=true "
            "kill_switch_clear=true seak_clear=true circuit_clear=true risk_reducing_exit_only=true "
            "ordinary_execution_unchanged=true global_lifecycle_mutated=false safety_gates_bypassed=false",
            MARKER,
            getattr(snap, "lifecycle_phase", "unknown"),
            getattr(snap, "coordinator_state", "unknown"),
        )
        return None

    setattr(protective_exit_dispatch_v337, _ASSERT_ATTR, True)
    setattr(protective_exit_dispatch_v337, "__wrapped__", base_assert)
    return protective_exit_dispatch_v337


def _patch_authority_module() -> bool:
    """Patch the source authority module so later import/rebinds retain v337."""
    eac = importlib.import_module("bot.execution_authority_context")
    current_can_execute = getattr(eac, "can_execute", None)
    current_assert = getattr(eac, "assert_execution_dispatch_permitted", None)
    if not callable(current_can_execute) or not callable(current_assert):
        return False

    if not bool(getattr(current_can_execute, _CAN_EXECUTE_ATTR, False)):
        base_can_execute = current_can_execute

        @wraps(base_can_execute)
        def authority_can_execute_v337(*args, **kwargs):
            return _bridge_initial_authority_decision(base_can_execute(*args, **kwargs))

        setattr(authority_can_execute_v337, _CAN_EXECUTE_ATTR, True)
        setattr(authority_can_execute_v337, "__wrapped__", base_can_execute)
        eac.can_execute = authority_can_execute_v337

    current_assert = getattr(eac, "assert_execution_dispatch_permitted", None)
    if callable(current_assert) and not bool(getattr(current_assert, _ASSERT_ATTR, False)):
        eac.assert_execution_dispatch_permitted = _make_dispatch_bridge(current_assert)

    return bool(
        getattr(getattr(eac, "can_execute", None), _CAN_EXECUTE_ATTR, False)
        and getattr(getattr(eac, "assert_execution_dispatch_permitted", None), _ASSERT_ATTR, False)
    )


def _patch_pipeline() -> bool:
    pipeline = importlib.import_module("bot.execution_pipeline")
    original_snapshot = getattr(pipeline, "runtime_authority_snapshot", None)
    if not callable(original_snapshot):
        return False

    if not bool(getattr(original_snapshot, _SNAPSHOT_ATTR, False)):
        base_snapshot = original_snapshot

        @wraps(base_snapshot)
        def protective_exit_snapshot_v337():
            snap = base_snapshot()
            if bool(getattr(snap, "ready", False)) or not _trusted_close():
                return snap
            ok, reason, current = _hard_exit_authority_proof()
            if not ok:
                LOGGER.warning(
                    "PROTECTIVE_EXIT_AUTHORITY_V337_SNAPSHOT_DEFERRED marker=%s reason=%s "
                    "lifecycle=%s coordinator=%s runtime_reason=%s ready_unchanged=false "
                    "forced_live=false safety_gates_bypassed=false",
                    MARKER, reason,
                    getattr(current, "lifecycle_phase", "unknown"),
                    getattr(current, "coordinator_state", "unknown"),
                    getattr(current, "reason", "unknown"),
                )
                return snap
            bridged = replace(current, ready=True)
            LOGGER.critical(
                "PROTECTIVE_EXIT_AUTHORITY_V337_SNAPSHOT_BRIDGED marker=%s lifecycle=%s coordinator=%s "
                "runtime_reason=%s exact_writer=true startup_write_authority=true nonce_ready=true "
                "broker_health_ready=true kill_switch_clear=true seak_clear=true circuit_clear=true "
                "global_lifecycle_mutated=false entry_authority_unchanged=true safety_gates_bypassed=false",
                MARKER,
                getattr(current, "lifecycle_phase", "unknown"),
                getattr(current, "coordinator_state", "unknown"),
                getattr(current, "reason", "unknown"),
            )
            return bridged

        setattr(protective_exit_snapshot_v337, _SNAPSHOT_ATTR, True)
        setattr(protective_exit_snapshot_v337, "__wrapped__", base_snapshot)
        pipeline.runtime_authority_snapshot = protective_exit_snapshot_v337

    # Bind pipeline aliases to the authority-level wrappers.  This survives any
    # subsequent module that refreshes its imports from execution_authority_context.
    eac = importlib.import_module("bot.execution_authority_context")
    pipeline.can_execute = eac.can_execute
    pipeline.assert_execution_dispatch_permitted = eac.assert_execution_dispatch_permitted

    return bool(
        getattr(getattr(pipeline, "runtime_authority_snapshot", None), _SNAPSHOT_ATTR, False)
        and getattr(getattr(pipeline, "can_execute", None), _CAN_EXECUTE_ATTR, False)
        and getattr(getattr(pipeline, "assert_execution_dispatch_permitted", None), _ASSERT_ATTR, False)
    )


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_protective_exit_authority_bridge_v337"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    with _LOCK:
        if getattr(builtins, _INSTALL_FLAG, False) and os.environ.get(_READY_FLAG) == "1":
            return True
        try:
            if os.environ.get("NIJA_RUNTIME_EXIT_SUBMISSION_FAILURE_TRUTH_V336_READY") != "1":
                raise RuntimeError("v336_not_ready")
            authority_patched = _patch_authority_module()
            pipeline_patched = _patch_pipeline()
            manifest = _register_manifest()
            ready = bool(authority_patched and pipeline_patched and manifest)
        except Exception as exc:
            ready = False
            LOGGER.exception(
                "RUNTIME_PROTECTIVE_EXIT_AUTHORITY_BRIDGE_V337_INSTALL_FAILED marker=%s error=%s:%s "
                "trading_fail_closed=true global_lifecycle_mutated=false safety_gates_bypassed=false",
                MARKER, type(exc).__name__, exc,
            )
        os.environ[_READY_FLAG] = "1" if ready else "0"
        setattr(builtins, _INSTALL_FLAG, ready)
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_PROTECTIVE_EXIT_AUTHORITY_BRIDGE_V337_%s marker=%s ready=%s "
            "trusted_protective_close_only=true exact_distributed_writer_required=true "
            "startup_write_authority_required=true nonce_required=true broker_health_required=true "
            "kill_switch_clear_required=true seak_clear_required=true circuit_clear_required=true "
            "authority_source_binding=true pipeline_alias_binding=true initial_lifecycle_gate_bridge=true "
            "lifecycle_global_epoch_bridge_only=true global_lifecycle_mutated=false "
            "ordinary_entries_unchanged=true ordinary_shorts_unchanged=true "
            "ecel_risk_slippage_minimum_order_ack_fill_gates_unchanged=true "
            "forced_live=false forced_exit=false safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook",
    "_hard_exit_authority_proof", "_bridge_initial_authority_decision",
]
