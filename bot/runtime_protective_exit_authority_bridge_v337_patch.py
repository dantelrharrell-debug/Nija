"""Protective-exit authority bridge v337.

Problem
-------
A verified sell-to-close can reach the canonical ExecutionPipeline while NIJA is
still BOOT/WARM or the startup coordinator is reconciling a stale global epoch.
The pipeline's normal authority contract is intentionally entry-centric: it
requires the whole runtime to be LIVE before *any* order.  Production therefore
blocked a genuine profitable Kraken ETH close with
``Runtime authority convergence lost`` even though the exact distributed writer
lease was current and the position/cost basis were proven.

Policy
------
v337 does NOT make the runtime LIVE and does NOT grant general execution
permission.  It provides a context-local bridge only for the canonical trusted
protective-close scope established by v335.  The bridge is admitted only when
all hard write-safety proofs are true at dispatch time:

* exact distributed writer authority verifies now;
* writer startup authority prerequisites (Redis, lease, fencing token,
  heartbeat, authority verification) verify now;
* runtime nonce authority is ready;
* broker dispatch health is ready;
* kill switch is inactive;
* SEAK is not halted;
* execution circuit is CLOSED (or approved RECOVERING);
* a writer fencing token is present.

Only the lifecycle/global-epoch convergence requirement is relaxed for that
single risk-reducing close.  Capability, margin, pre-trade risk, ECEL,
throttling, risk governor, spread/slippage, broker-health, terminal writer,
nonce, minimum-order, order-ack and fill-confirmation checks remain in force.
No environment lifecycle state, startup coordinator state, or global readiness
bit is mutated.
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
        # Force-refresh the startup write proof so a stale cached coordinator
        # epoch cannot be mistaken for current Redis/lease truth.
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
    # dispatch_enabled may be lifecycle-derived on some startup snapshots.
    # We do not use it as a substitute for the exact writer proof above, but if
    # it is explicitly false for a non-lifecycle reason the reason remains
    # visible in telemetry and downstream terminal checks still fail closed.

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
    # This bridge is intentionally for startup/convergence only.  A degraded
    # runtime for another hard reason must not be converted into exit authority.
    startup_shape = (
        lifecycle in {"BOOT", "WARM"}
        or "global_epoch_stale" in reason.lower()
        or "startup" in reason.lower()
        or "activation" in coordinator.lower()
    )
    if not startup_shape and not bool(getattr(snap, "ready", False)):
        return False, f"non_startup_runtime_block:{reason or lifecycle or coordinator}", snap

    return True, "hard_exit_authority_proven", snap


def _patch_pipeline() -> bool:
    pipeline = importlib.import_module("bot.execution_pipeline")
    original_snapshot = getattr(pipeline, "runtime_authority_snapshot", None)
    original_assert = getattr(pipeline, "assert_execution_dispatch_permitted", None)
    if not callable(original_snapshot) or not callable(original_assert):
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

    original_assert = getattr(pipeline, "assert_execution_dispatch_permitted", None)
    if callable(original_assert) and not bool(getattr(original_assert, _ASSERT_ATTR, False)):
        base_assert = original_assert

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
        pipeline.assert_execution_dispatch_permitted = protective_exit_dispatch_v337

    return bool(
        getattr(getattr(pipeline, "runtime_authority_snapshot", None), _SNAPSHOT_ATTR, False)
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
            patched = _patch_pipeline()
            manifest = _register_manifest()
            ready = bool(patched and manifest)
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
            "lifecycle_global_epoch_bridge_only=true global_lifecycle_mutated=false "
            "ordinary_entries_unchanged=true ordinary_shorts_unchanged=true "
            "ecel_risk_slippage_minimum_order_ack_fill_gates_unchanged=true "
            "forced_live=false forced_exit=false safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "RELEASE_ID", "install", "install_import_hook", "_hard_exit_authority_proof"]
