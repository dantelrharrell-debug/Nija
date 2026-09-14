"""Compatibility bridge for v60 against current preactivation v16 API.

Production v112 proved the canonical fast-path import and build fixes, then
failed because final_production_activation_repair_v60_patch still expected
preactivation_readiness_convergence_v16_patch._cycle. Current v16 exposes
_attempt_activation instead. This shim patches v60's private installer step
before v60.install() runs. It preserves proof collection, readiness publication,
and fail-closed activation semantics while dispatching the actual activation
commit through v60's existing single-flight worker.

The September 14 production restart also exposed a second compatibility cycle:
v60's pre-dispatch probe asked the execution-authority FSM to converge using its
default gate evaluation before bootstrap_ready/execution_ready could be committed.
The shim evaluates every existing hard pre-dispatch gate first, then asks the FSM
to converge with gates_ok=True. This does not grant dispatch authority; the
normal order path still requires can_dispatch_trades() and coordinator authority.

Some later canonical startup repairs rebind/reload v60 after this compatibility
layer is first installed. A no-I/O guard therefore reasserts only the v60
pre-dispatch function wrapper when that specific binding drifts. It does not
publish readiness, mutate broker state, submit orders, or alter safety policy.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from typing import Any

LOGGER = logging.getLogger("nija.final_activation_v60_v16_compat_v113")
MARKER = "20260816-final-activation-v60-v16-compat-v113"
_INSTALLED = False
_GUARD_STARTED = False
_GUARD_LOCK = threading.RLock()


def _patch_v60_pre_dispatch_probe(v60: Any) -> bool:
    current = getattr(v60, "_pre_dispatch_safety_ready", None)
    if not callable(current):
        return False
    if getattr(current, "_nija_v113_authority_cycle_repair", False):
        return True

    def pre_dispatch_safety_ready(tsm: Any, sm: Any) -> tuple[bool, str]:
        """Prove hard gates before advancing the pre-dispatch authority FSM.

        gates_ok=True is supplied only after the same hard checks v60 already
        required have passed. It breaks the startup self-dependency without
        bypassing any broker-order, writer, nonce, heartbeat, circuit-breaker,
        kill-switch, strategy, risk, or coordinator dispatch gate.
        """
        try:
            breaker_probe = getattr(tsm, "_execution_circuit_breaker_status", None)
            breaker_ok, breaker_detail = (
                breaker_probe() if callable(breaker_probe) else (False, "probe_missing")
            )
            if not breaker_ok:
                return False, f"execution_circuit_breaker:{breaker_detail or 'tripped'}"

            runtime_probe = getattr(tsm, "_runtime_writer_nonce_ready", None)
            runtime_ok, runtime_detail = (
                runtime_probe() if callable(runtime_probe) else (False, "probe_missing")
            )
            if not runtime_ok:
                return False, f"writer_nonce:{runtime_detail or 'not_ready'}"

            heartbeat_required_probe = getattr(tsm, "_heartbeat_verification_required", None)
            heartbeat_status_probe = getattr(tsm, "_heartbeat_verification_status", None)
            heartbeat_required = bool(
                heartbeat_required_probe() if callable(heartbeat_required_probe) else True
            )
            heartbeat_ok, heartbeat_detail, _heartbeat_meta = (
                heartbeat_status_probe()
                if callable(heartbeat_status_probe)
                else (False, "probe_missing", None)
            )
            if heartbeat_required and not heartbeat_ok:
                return False, f"heartbeat_verification:{heartbeat_detail or 'not_ready'}"

            live_gate_probe = getattr(tsm, "_collect_live_gate_status", None)
            if not callable(live_gate_probe):
                return False, "live_gate_probe_missing"
            live_gate = dict(live_gate_probe())
            if not bool(live_gate.get("execution_allowed", False)):
                failed = sorted(
                    key
                    for key, value in live_gate.items()
                    if key.endswith("_ok") and not bool(value)
                )
                return False, f"live_gates:{','.join(failed) or 'not_ready'}"

            snapshot_fn = getattr(sm, "get_execution_authority_snapshot", None)
            if not callable(snapshot_fn):
                return False, "authority_snapshot_probe_missing"
            try:
                authority = dict(snapshot_fn(gates_ok=True))
            except TypeError:
                authority = dict(snapshot_fn())
            if (
                str(authority.get("safety_state", "")).strip().upper() != "AUTHORIZED"
                or not bool(authority.get("converged", False))
            ):
                return False, "authority_fsm_not_converged"

            LOGGER.critical(
                "FINAL_ACTIVATION_V113_PRE_DISPATCH_AUTHORITY_CONVERGED marker=%s "
                "hard_gates_proven=true gates_ok_override=validated_only dispatch_granted=false",
                MARKER,
            )
            return True, "ok"
        except Exception as exc:
            return False, f"exception:{type(exc).__name__}:{exc}"

    pre_dispatch_safety_ready._nija_v113_authority_cycle_repair = True  # type: ignore[attr-defined]
    pre_dispatch_safety_ready.__wrapped__ = current  # type: ignore[attr-defined]
    v60._pre_dispatch_safety_ready = pre_dispatch_safety_ready
    LOGGER.critical(
        "FINAL_ACTIVATION_V113_PRE_DISPATCH_PATCHED marker=%s "
        "hard_gates_first=true coordinator_dispatch_unchanged=true safety_gates_unchanged=true",
        MARKER,
    )
    return True


def _reassert_v60_binding() -> bool:
    try:
        v60 = importlib.import_module("bot.final_production_activation_repair_v60_patch")
    except Exception:
        return False
    current = getattr(v60, "_pre_dispatch_safety_ready", None)
    if callable(current) and getattr(current, "_nija_v113_authority_cycle_repair", False):
        return True
    repaired = _patch_v60_pre_dispatch_probe(v60)
    if repaired:
        LOGGER.warning(
            "FINAL_ACTIVATION_V113_PRE_DISPATCH_REASSERTED marker=%s "
            "reason=later_v60_binding_drift safety_gates_unchanged=true",
            MARKER,
        )
    return repaired


def _guard_loop() -> None:
    while True:
        try:
            _reassert_v60_binding()
        except Exception:
            pass
        time.sleep(0.25)


def _ensure_guard() -> None:
    global _GUARD_STARTED
    with _GUARD_LOCK:
        if _GUARD_STARTED:
            return
        _GUARD_STARTED = True
        threading.Thread(
            target=_guard_loop,
            name="FinalActivationV113BindingGuard",
            daemon=True,
        ).start()
        LOGGER.critical(
            "FINAL_ACTIVATION_V113_BINDING_GUARD_STARTED marker=%s "
            "broker_io=false readiness_mutation=false order_submission=false",
            MARKER,
        )


def _patch_v60() -> bool:
    v60 = importlib.import_module("bot.final_production_activation_repair_v60_patch")
    current = getattr(v60, "_patch_v16_nonblocking", None)
    if not getattr(current, "_nija_v113_current_v16_api", False):
        def patch_v16_nonblocking() -> bool:
            v16 = importlib.import_module("preactivation_readiness_convergence_v16_patch")
            original_attempt = getattr(v16, "_attempt_activation", None)
            if not callable(original_attempt):
                LOGGER.critical(
                    "FINAL_ACTIVATION_V113_V16_API_MISSING marker=%s expected=_attempt_activation",
                    MARKER,
                )
                return False
            if getattr(original_attempt, "_nija_v60_nonblocking", False):
                return True

            def attempt_activation() -> tuple[bool, dict[str, Any]]:
                proofs, details = v16._collect_proofs()
                ready, pending = v16._mark_proven_readiness(proofs)
                v60._publish_risk_compat(proofs)
                details["proofs"] = proofs
                details["pending"] = pending
                publisher_started, publisher_detail = v16._ensure_strategy_publication_monitor()
                details["strategy_publication_monitor"] = {
                    "started": publisher_started,
                    "detail": publisher_detail,
                }
                try:
                    monitor = importlib.import_module("bot.activation_pending_commit_monitor_patch")
                    sm = monitor._state_machine()
                    state = v60._state_value(sm) if sm is not None else "UNAVAILABLE"
                except Exception:
                    state = "UNAVAILABLE"
                if ready and state != "LIVE_ACTIVE":
                    dispatched = bool(v60.request_activation("v16_readiness_complete"))
                else:
                    dispatched = False
                details["state_before"] = state
                details["activation_dispatched"] = dispatched
                details["activation_mode"] = "single_flight_nonblocking_v113"
                return state == "LIVE_ACTIVE", details

            attempt_activation._nija_v60_nonblocking = True  # type: ignore[attr-defined]
            attempt_activation._nija_v113_current_v16_api = True  # type: ignore[attr-defined]
            attempt_activation.__wrapped__ = original_attempt  # type: ignore[attr-defined]
            v16._attempt_activation = attempt_activation
            LOGGER.critical(
                "FINAL_ACTIVATION_V113_V16_PATCHED marker=%s api=_attempt_activation "
                "proof_publication_nonblocking=true activation_single_flight=true force_activation=false",
                MARKER,
            )
            return True

        patch_v16_nonblocking._nija_v113_current_v16_api = True  # type: ignore[attr-defined]
        patch_v16_nonblocking.__wrapped__ = current  # type: ignore[attr-defined]
        v60._patch_v16_nonblocking = patch_v16_nonblocking

    return _patch_v60_pre_dispatch_probe(v60)


def install() -> bool:
    global _INSTALLED
    if not _patch_v60():
        os.environ["NIJA_FINAL_ACTIVATION_V60_V16_COMPAT_V113_INSTALLED"] = "0"
        return False
    _ensure_guard()
    if not _INSTALLED:
        _INSTALLED = True
        os.environ["NIJA_FINAL_ACTIVATION_V60_V16_COMPAT_V113_INSTALLED"] = "1"
        LOGGER.critical(
            "FINAL_ACTIVATION_V60_V16_COMPAT_V113_INSTALLED marker=%s fail_closed=true",
            MARKER,
        )
    return True


install_import_hook = install
