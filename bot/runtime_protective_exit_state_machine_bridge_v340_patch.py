"""Protective-close state-machine bridge v340.

The canonical protective-exit path can satisfy all hard write-safety proofs while
the trading state machine remains ``LIVE_PENDING_CONFIRMATION`` solely because a
genuine entry/execution proof has not yet been established.  That state must
continue to block new positions, but it must not strand an already-owned,
verified position that NIJA is trying to reduce/close.

v340 changes only ``ExecutionPipeline._enforce_execution_gate``.  It first calls
the original gate unchanged.  A result is eligible for reconsideration only
when ALL of these are true:

* v335's strict trusted protective-close ContextVar is active;
* the original gate returned exactly ``Execution gate pending
  (state_machine=LIVE_PENDING_CONFIRMATION)``;
* v337's hard protective-exit authority proof succeeds at that instant.  Because
  v339 wraps v337 in the exact broker scope, this includes exact broker-local
  health when the global activation aggregate is not ready.

When those conditions hold, v340 returns ``None`` from this one gate, allowing
the already-existing downstream broker/ECEL/minimum-order/order-ack/fill gates
to continue.  It never changes the state machine, activation commit, runtime
readiness, global epoch, execution proof, writer/nonce, broker health, kill
switch, SEAK, circuit breaker, risk or fill state.

Ordinary entries, ordinary spot sells/shorts, untrusted exits, other state-machine
states, safety-controller blocks and dry-run/app-store modes are byte-for-byte
unchanged.
"""
from __future__ import annotations

import builtins
import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_protective_exit_state_machine_bridge_v340")
MARKER = "20260901-protective-exit-state-machine-bridge-v340"
RELEASE_ID = "20260901-runtime-convergence-v340"
_READY_FLAG = "NIJA_RUNTIME_PROTECTIVE_EXIT_STATE_MACHINE_BRIDGE_V340_READY"
_PATCH_ATTR = "_nija_protective_exit_state_machine_bridge_v340"
_INSTALL_FLAG = "_NIJA_RUNTIME_PROTECTIVE_EXIT_STATE_MACHINE_BRIDGE_V340"
_LOCK = threading.RLock()
_ALLOWED_ERROR = "Execution gate pending (state_machine=LIVE_PENDING_CONFIRMATION)"


def _trusted_close_active() -> bool:
    try:
        v335 = importlib.import_module("bot.runtime_exit_capability_semantics_v335_patch")
        context = getattr(v335, "_TRUSTED_CLOSE", None)
        getter = getattr(context, "get", None)
        return bool(getter()) if callable(getter) else False
    except Exception:
        return False


def _hard_exit_proof() -> tuple[bool, str, Any]:
    try:
        v337 = importlib.import_module("bot.runtime_protective_exit_authority_bridge_v337_patch")
        proof = getattr(v337, "_hard_exit_authority_proof", None)
        if not callable(proof):
            return False, "v337_hard_proof_unavailable", None
        result = proof()
        if isinstance(result, tuple) and len(result) >= 3:
            return bool(result[0]), str(result[1]), result[2]
        return False, "v337_hard_proof_invalid_result", None
    except Exception as exc:
        return False, f"v337_hard_proof_error:{type(exc).__name__}:{exc}", None


def _patch_execution_gate() -> bool:
    pipeline = importlib.import_module("bot.execution_pipeline")
    cls = getattr(pipeline, "ExecutionPipeline", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "_enforce_execution_gate", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def enforce_gate_v340(self: Any, request: Any, t_start: float):
        result = current(self, request, t_start)
        if result is None or not _trusted_close_active():
            return result

        error = str(getattr(result, "error", "") or "")
        if error != _ALLOWED_ERROR:
            return result

        proof_ok, proof_reason, snap = _hard_exit_proof()
        if not proof_ok:
            LOGGER.warning(
                "PROTECTIVE_EXIT_STATE_MACHINE_V340_DENIED marker=%s symbol=%s side=%s "
                "state=LIVE_PENDING_CONFIRMATION proof=%s original_gate_preserved=true "
                "order_submitted=false safety_gates_bypassed=false",
                MARKER,
                str(getattr(request, "symbol", "") or ""),
                str(getattr(request, "side", "") or ""),
                proof_reason,
            )
            return result

        LOGGER.critical(
            "PROTECTIVE_EXIT_STATE_MACHINE_V340_BRIDGE_ACTIVE marker=%s symbol=%s side=%s "
            "intent=%s position_effect=%s state=LIVE_PENDING_CONFIRMATION "
            "hard_exit_authority=true proof=%s lifecycle=%s coordinator=%s "
            "state_machine_mutated=false activation_commit_mutated=false execution_proof_fabricated=false "
            "entry_gate_unchanged=true downstream_broker_ecel_minimum_order_ack_fill_gates_preserved=true "
            "safety_gates_bypassed=false",
            MARKER,
            str(getattr(request, "symbol", "") or ""),
            str(getattr(request, "side", "") or ""),
            str(getattr(request, "intent_type", "") or ""),
            str(getattr(request, "position_effect", "") or ""),
            proof_reason,
            str(getattr(snap, "lifecycle_phase", "") or "") if snap is not None else "unknown",
            str(getattr(snap, "coordinator_state", "") or "") if snap is not None else "unknown",
        )
        return None

    setattr(enforce_gate_v340, _PATCH_ATTR, True)
    setattr(enforce_gate_v340, "__wrapped__", current)
    cls._enforce_execution_gate = enforce_gate_v340
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_protective_exit_state_machine_bridge_v340"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    with _LOCK:
        if getattr(builtins, _INSTALL_FLAG, False) and os.environ.get(_READY_FLAG) == "1":
            return True
        try:
            if os.environ.get("NIJA_RUNTIME_PROTECTIVE_EXIT_BROKER_HEALTH_V339_READY") != "1":
                raise RuntimeError("v339_not_ready")
            patched = _patch_execution_gate()
            manifest = _register_manifest()
            ready = bool(patched and manifest)
        except Exception as exc:
            ready = False
            LOGGER.exception(
                "PROTECTIVE_EXIT_STATE_MACHINE_V340_INSTALL_FAILED marker=%s error=%s:%s "
                "trading_fail_closed=true forced_exit=false safety_gates_bypassed=false",
                MARKER, type(exc).__name__, exc,
            )
        os.environ[_READY_FLAG] = "1" if ready else "0"
        setattr(builtins, _INSTALL_FLAG, ready)
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_PROTECTIVE_EXIT_STATE_MACHINE_BRIDGE_V340_%s marker=%s ready=%s "
            "trusted_close_only=true live_pending_confirmation_only=true v337_hard_proof_required=true "
            "v339_exact_broker_health_preserved=true state_machine_unchanged=true activation_commit_unchanged=true "
            "ordinary_entries_unchanged=true ordinary_shorts_unchanged=true "
            "broker_ecel_minimum_order_ack_fill_gates_unchanged=true forced_exit=false safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "RELEASE_ID", "install", "install_import_hook", "_trusted_close_active"]
