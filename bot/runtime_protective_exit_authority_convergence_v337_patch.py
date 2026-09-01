"""Protective-exit runtime authority convergence v337.

A canonical protective close can be fully proven (position quantity/cost basis,
public price, explicit exit intent, writer authority, ECEL contract) while the
startup coordinator still reports ``execution_permitted=False`` solely because
its global activation epoch is stale/BOOT.  That aggregate is appropriate for
new entries but contradicts NIJA's existing writer-authorized risk-reducing exit
contract in ``kraken_exit_final_guards_patch``.

v337 changes only the *pipeline-local* runtime_authority_snapshot reference used
by the generic pre-dispatch aggregate check.  It never mutates GLOBAL_STATE,
startup coordinator state, lifecycle phase, runtime trading state or the
canonical execution_authority_context.runtime_authority_snapshot function.

A not-ready snapshot is treated as sufficient for this one pre-dispatch check
only when all of the following are true:
  * v335's trusted-close ContextVar is active (strict canonical exit origin);
  * reason is exactly global_epoch_stale;
  * lifecycle is BOOT or WARM and coordinator is ACTIVATION_CONVERGING;
  * exact distributed process-writer authority succeeds now;
  * live runtime nonce authority succeeds now; and
  * dispatch/broker health in the snapshot is ready.

The returned copy changes only ``ready`` and the diagnostic reason.  It leaves
lifecycle_phase, authority_ready, nonce_ready, dispatch flags, kill-switch state
and all other fields unchanged.  All later broker, nonce, kill-switch, ECEL,
minimum-order, terminal acknowledgement and fill-confirmation gates remain in
place.  Outside the trusted-close context the original snapshot is returned
byte-for-byte.
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

LOGGER = logging.getLogger("nija.runtime_protective_exit_authority_convergence_v337")
MARKER = "20260901-protective-exit-authority-convergence-v337"
RELEASE_ID = "20260901-runtime-convergence-v337"
_READY_FLAG = "NIJA_RUNTIME_PROTECTIVE_EXIT_AUTHORITY_CONVERGENCE_V337_READY"
_PATCH_ATTR = "_nija_protective_exit_authority_convergence_v337"
_INSTALL_FLAG = "_NIJA_RUNTIME_PROTECTIVE_EXIT_AUTHORITY_CONVERGENCE_V337"
_LOCK = threading.RLock()


def _norm(value: Any) -> str:
    return str(value or "").strip().lower().replace("-", "_").replace(" ", "_")


def _trusted_close_active() -> bool:
    try:
        v335 = importlib.import_module("bot.runtime_exit_capability_semantics_v335_patch")
        marker = getattr(v335, "_TRUSTED_CLOSE", None)
        getter = getattr(marker, "get", None)
        return bool(getter()) if callable(getter) else False
    except Exception:
        return False


def _exact_writer_and_nonce_ready() -> tuple[bool, str]:
    try:
        authority = importlib.import_module("bot.execution_authority_context")
        writer_check = getattr(authority, "assert_distributed_writer_authority", None)
        nonce_check = getattr(authority, "_runtime_nonce_authority_status", None)
        if not callable(writer_check) or not callable(nonce_check):
            return False, "authority_helpers_unavailable"
        writer_check()
        nonce_ok, nonce_reason = nonce_check()
        if not bool(nonce_ok):
            return False, f"nonce_not_ready:{nonce_reason or 'unknown'}"
        return True, "exact_writer_and_runtime_nonce_ready"
    except Exception as exc:
        return False, f"writer_or_nonce_error:{type(exc).__name__}:{exc}"


def _eligible_snapshot(snapshot: Any) -> tuple[bool, str]:
    if bool(getattr(snapshot, "ready", False)):
        return False, "already_ready"
    if _norm(getattr(snapshot, "reason", "")) != "global_epoch_stale":
        return False, f"reason_not_allowed:{getattr(snapshot, 'reason', '')}"
    lifecycle = str(getattr(snapshot, "lifecycle_phase", "BOOT") or "BOOT").strip().upper()
    if lifecycle not in {"BOOT", "WARM"}:
        return False, f"lifecycle_not_allowed:{lifecycle}"
    coordinator = str(getattr(snapshot, "coordinator_state", "") or "").strip().upper()
    if coordinator != "ACTIVATION_CONVERGING":
        return False, f"coordinator_not_allowed:{coordinator}"
    if not bool(getattr(snapshot, "dispatch_health_ready", False)):
        return False, "dispatch_health_not_ready"
    return True, "eligible_global_epoch_stale"


def _patch_pipeline_snapshot() -> bool:
    pipeline = importlib.import_module("bot.execution_pipeline")
    current = getattr(pipeline, "runtime_authority_snapshot", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def protective_exit_snapshot_v337():
        snapshot = current()
        if not _trusted_close_active():
            return snapshot
        eligible, eligibility_reason = _eligible_snapshot(snapshot)
        if not eligible:
            LOGGER.warning(
                "PROTECTIVE_EXIT_AUTHORITY_V337_DEFERRED marker=%s reason=%s "
                "snapshot_reason=%s lifecycle=%s coordinator=%s dispatch_health_ready=%s "
                "aggregate_not_overridden=true safety_gates_bypassed=false",
                MARKER,
                eligibility_reason,
                str(getattr(snapshot, "reason", "")),
                str(getattr(snapshot, "lifecycle_phase", "")),
                str(getattr(snapshot, "coordinator_state", "")),
                str(bool(getattr(snapshot, "dispatch_health_ready", False))).lower(),
            )
            return snapshot

        proof_ok, proof_reason = _exact_writer_and_nonce_ready()
        if not proof_ok:
            LOGGER.error(
                "PROTECTIVE_EXIT_AUTHORITY_V337_DENIED marker=%s proof=%s "
                "aggregate_not_overridden=true exact_writer_required=true runtime_nonce_required=true "
                "safety_gates_bypassed=false",
                MARKER, proof_reason,
            )
            return snapshot

        try:
            promoted = replace(
                snapshot,
                ready=True,
                reason="protective_exit_writer_nonce_authorized_global_epoch_stale",
            )
        except Exception:
            # RuntimeAuthoritySnapshot is a frozen dataclass in the canonical
            # implementation. If that contract changes, fail closed rather than
            # manufacturing an ad-hoc object.
            LOGGER.exception(
                "PROTECTIVE_EXIT_AUTHORITY_V337_COPY_FAILED marker=%s aggregate_not_overridden=true",
                MARKER,
            )
            return snapshot

        LOGGER.critical(
            "PROTECTIVE_EXIT_AUTHORITY_V337_CONVERGENCE_EXCEPTION marker=%s "
            "original_reason=global_epoch_stale lifecycle=%s coordinator=%s "
            "exact_writer=true runtime_nonce=true dispatch_health_ready=true "
            "ready_copy_only=true lifecycle_unchanged=true global_state_mutated=false "
            "runtime_state_mutated=false entry_authority_unchanged=true broker_ecel_minimum_order_fill_gates_preserved=true "
            "safety_gates_bypassed=false",
            MARKER,
            str(getattr(snapshot, "lifecycle_phase", "")),
            str(getattr(snapshot, "coordinator_state", "")),
        )
        return promoted

    setattr(protective_exit_snapshot_v337, _PATCH_ATTR, True)
    setattr(protective_exit_snapshot_v337, "__wrapped__", current)
    pipeline.runtime_authority_snapshot = protective_exit_snapshot_v337
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_protective_exit_authority_convergence_v337"] = _READY_FLAG
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
            patched = _patch_pipeline_snapshot()
            manifest = _register_manifest()
            ready = bool(patched and manifest)
        except Exception as exc:
            ready = False
            LOGGER.exception(
                "PROTECTIVE_EXIT_AUTHORITY_V337_INSTALL_FAILED marker=%s error=%s:%s "
                "trading_fail_closed=true forced_exit=false safety_gates_bypassed=false",
                MARKER, type(exc).__name__, exc,
            )
        os.environ[_READY_FLAG] = "1" if ready else "0"
        setattr(builtins, _INSTALL_FLAG, ready)
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_PROTECTIVE_EXIT_AUTHORITY_CONVERGENCE_V337_%s marker=%s ready=%s "
            "trusted_close_only=true global_epoch_stale_only=true boot_warm_only=true "
            "activation_converging_only=true exact_writer_required=true runtime_nonce_required=true "
            "dispatch_health_required=true pipeline_local_snapshot_only=true global_readiness_unchanged=true "
            "entry_lifecycle_gate_unchanged=true broker_ecel_minimum_order_fill_gates_unchanged=true "
            "forced_loss_exit=false safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER", "RELEASE_ID", "install", "install_import_hook",
    "_eligible_snapshot", "_exact_writer_and_nonce_ready",
]
