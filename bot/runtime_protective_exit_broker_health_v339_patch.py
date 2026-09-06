"""Exact-broker protective-exit health authority v339.

A protective close is account/venue specific.  The v337 startup bridge originally
required ``runtime_authority_snapshot.dispatch_health_ready`` which is a global
activation aggregate.  Production showed that aggregate false while the exact
Kraken exit broker remained connected and able to provide current positions and
prices.  This can strand profitable holdings solely because another entry
surface is not activation-ready.

v339 substitutes an exact broker-local connectivity proof only inside the fully
trusted v335 protective-close scope.  It does not mark global dispatch health
ready and it does not mutate any broker-health state.  The canonical pipeline
and terminal broker adapter still execute their existing broker-health checks.

The substitution is permitted only when:
* v335's full protective-close metadata is present;
* the exact broker object is carried by the canonical submitter call;
* that broker, or the concrete broker behind a known NIJA proxy, exposes a
  positive local connection/health state;
* v337's remaining hard proofs are re-verified: distributed writer, startup
  writer prerequisites, nonce, kill switch, SEAK, circuit and fencing token;
* the runtime block is startup/activation convergence rather than an unrelated
  degraded/corrupt state.

Proxy handling is intentionally conservative.  Only the same known broker
wrapper attributes used by the canonical Kraken position-state path are
followed.  The deepest concrete broker is authoritative; a stale wrapper
``connected=False`` may no longer veto a healthy concrete adapter, while a stale
wrapper ``connected=True`` cannot promote an unhealthy concrete adapter.  Proxy
cycles and over-deep chains fail closed.
"""
from __future__ import annotations

import builtins
import contextvars
import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any, Mapping

LOGGER = logging.getLogger("nija.runtime_protective_exit_broker_health_v339")
MARKER = "20260901-runtime-protective-exit-broker-health-v339"
RELEASE_ID = "20260901-runtime-convergence-v339"
_READY_FLAG = "NIJA_RUNTIME_PROTECTIVE_EXIT_BROKER_HEALTH_V339_READY"
_SUBMIT_ATTR = "_nija_exact_exit_broker_scope_v339"
_PROOF_ATTR = "_nija_exact_exit_broker_proof_v339"
_INSTALL_FLAG = "_NIJA_RUNTIME_PROTECTIVE_EXIT_BROKER_HEALTH_V339"
_LOCK = threading.RLock()
_BROKER = contextvars.ContextVar("nija_v339_exact_exit_broker", default=None)
_PROXY_ATTRS = ("_broker", "_real_broker", "_target", "broker")
_PROXY_MAX_DEPTH = 6


def _truthy(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if value is None:
        return None
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on", "connected", "healthy", "ready", "ok"}:
        return True
    if text in {"0", "false", "no", "off", "disconnected", "unhealthy", "failed", "error"}:
        return False
    return None


def _trusted_kwargs(kwargs: Mapping[str, Any]) -> bool:
    try:
        v335 = importlib.import_module("bot.runtime_exit_capability_semantics_v335_patch")
        return bool(v335._trusted_exit_kwargs(kwargs))
    except Exception:
        return False


def _local_broker_health(broker: Any) -> tuple[bool, str]:
    """Read side-effect-free health from one concrete broker object."""
    if broker is None:
        return False, "broker_missing"

    # Prefer explicit, side-effect-free state attributes.
    for attr in (
        "connected", "_connected", "is_connected", "connection_ready",
        "trading_ready", "is_healthy", "healthy",
    ):
        value = getattr(broker, attr, None)
        if callable(value):
            # Only invoke methods conventionally named as local predicates.
            if attr not in {"is_connected", "is_healthy"}:
                continue
            try:
                value = value()
            except Exception as exc:
                return False, f"{attr}_error:{type(exc).__name__}"
        state = _truthy(value)
        if state is True:
            return True, f"broker_local:{attr}"
        if state is False:
            return False, f"broker_local:{attr}=false"

    # Some adapters expose a status enum/string rather than a boolean.
    for attr in ("connection_status", "status", "health_status"):
        value = getattr(broker, attr, None)
        state = _truthy(getattr(value, "value", value))
        if state is True:
            return True, f"broker_local:{attr}"
        if state is False:
            return False, f"broker_local:{attr}=false"

    return False, "exact_broker_health_unproven"


def _exact_broker_health(broker: Any) -> tuple[bool, str]:
    """Prove health on the concrete broker behind known NIJA proxy wrappers.

    Kraken canonical position coverage v366 already resolves these exact wrapper
    attributes before authenticated read-only calls.  Protective-exit health must
    resolve the same object boundary, but it still requires positive local
    broker health and never treats a successful read as execution health.
    """
    if broker is None:
        return False, "broker_missing"

    current = broker
    seen: set[int] = set()
    path: list[str] = []

    for _depth in range(_PROXY_MAX_DEPTH):
        identity = id(current)
        if identity in seen:
            return False, "broker_proxy_cycle"
        seen.add(identity)

        nxt = None
        nxt_attr = ""
        for attr in _PROXY_ATTRS:
            try:
                candidate = getattr(current, attr, None)
            except Exception:
                candidate = None
            if candidate is not None and candidate is not current:
                nxt = candidate
                nxt_attr = attr
                break

        if nxt is None:
            ok, reason = _local_broker_health(current)
            if not path:
                return ok, reason
            return ok, f"broker_proxy:{'->'.join(path)}->{reason}"

        if id(nxt) in seen:
            return False, "broker_proxy_cycle"
        path.append(nxt_attr)
        current = nxt

    # If another known wrapper is still present after the depth budget, do not
    # guess which object is authoritative.
    for attr in _PROXY_ATTRS:
        try:
            candidate = getattr(current, attr, None)
        except Exception:
            candidate = None
        if candidate is not None and candidate is not current:
            return False, "broker_proxy_depth_exceeded"

    ok, reason = _local_broker_health(current)
    if not path:
        return ok, reason
    return ok, f"broker_proxy:{'->'.join(path)}->{reason}"


def _patch_submitter_scope() -> bool:
    submitter = importlib.import_module("bot.pipeline_order_submitter")
    current = getattr(submitter, "submit_market_order_via_pipeline", None)
    if not callable(current):
        return False
    if bool(getattr(current, _SUBMIT_ATTR, False)):
        return True

    @wraps(current)
    def submit_with_exact_broker(*args: Any, **kwargs: Any):
        if not _trusted_kwargs(kwargs):
            return current(*args, **kwargs)
        broker = kwargs.get("broker") or (args[0] if args else None)
        token = _BROKER.set(broker)
        try:
            return current(*args, **kwargs)
        finally:
            _BROKER.reset(token)

    setattr(submit_with_exact_broker, _SUBMIT_ATTR, True)
    setattr(submit_with_exact_broker, "__wrapped__", current)
    submitter.submit_market_order_via_pipeline = submit_with_exact_broker
    return True


def _circuit_ok() -> tuple[bool, str]:
    state = str(os.environ.get("NIJA_EXECUTION_CIRCUIT_STATE", "CLOSED") or "CLOSED").strip().upper()
    if state == "CLOSED":
        return True, state
    approved = str(os.environ.get("NIJA_EXECUTION_RECOVERY_APPROVED", "") or "").strip().lower() in {"1", "true", "yes", "on", "enabled"}
    return (state == "RECOVERING" and approved), state


def _startup_shape(snap: Any) -> bool:
    lifecycle = str(getattr(snap, "lifecycle_phase", "") or "").upper()
    reason = str(getattr(snap, "reason", "") or "").lower()
    coordinator = str(getattr(snap, "coordinator_state", "") or "").lower()
    return bool(
        lifecycle in {"BOOT", "WARM"}
        or "global_epoch_stale" in reason
        or "startup" in reason
        or "activation" in coordinator
        or ("fail_safe_halt" in coordinator and "execution" in reason)
    )


def _reprove_without_global_health() -> tuple[bool, str, Any]:
    broker = _BROKER.get()
    broker_ok, broker_reason = _exact_broker_health(broker)
    if not broker_ok:
        return False, f"exact_broker:{broker_reason}", None

    eac = importlib.import_module("bot.execution_authority_context")
    snap = eac.runtime_authority_snapshot()
    try:
        eac.assert_distributed_writer_authority()
        eac.require_startup_execution_authority(context="protective_exit_v339", force_refresh=True)
    except Exception as exc:
        return False, f"writer_authority:{exc}", snap
    if bool(getattr(snap, "kill_switch_active", False)):
        return False, "kill_switch_active", snap
    if not bool(getattr(snap, "nonce_ready", False)):
        return False, "nonce_not_ready", snap
    if eac.is_seak_halted():
        return False, "seak_halted", snap
    circuit_ok, state = _circuit_ok()
    if not circuit_ok:
        return False, f"execution_circuit:{state}", snap
    if not str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "").strip():
        return False, "writer_fencing_token_missing", snap
    if not _startup_shape(snap) and not bool(getattr(snap, "ready", False)):
        return False, f"non_startup_runtime_block:{getattr(snap, 'reason', '')}", snap

    LOGGER.critical(
        "PROTECTIVE_EXIT_BROKER_HEALTH_V339_EXACT_PROOF marker=%s venue=%s proof=%s "
        "global_dispatch_health=%s exact_broker_health=true distributed_writer=true nonce_ready=true "
        "kill_switch_clear=true seak_clear=true circuit_clear=true terminal_broker_health_gate_preserved=true "
        "global_health_mutated=false safety_gates_bypassed=false",
        MARKER,
        type(broker).__name__,
        broker_reason,
        str(bool(getattr(snap, "dispatch_health_ready", False))).lower(),
    )
    return True, "exact_broker_health_proven", snap


def _patch_v337_proof() -> bool:
    v337 = importlib.import_module("bot.runtime_protective_exit_authority_bridge_v337_patch")
    current = getattr(v337, "_hard_exit_authority_proof", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PROOF_ATTR, False)):
        return True

    @wraps(current)
    def exact_broker_proof_v339():
        ok, reason, snap = current()
        if ok or reason != "broker_dispatch_health_not_ready" or _BROKER.get() is None:
            return ok, reason, snap
        return _reprove_without_global_health()

    setattr(exact_broker_proof_v339, _PROOF_ATTR, True)
    setattr(exact_broker_proof_v339, "__wrapped__", current)
    v337._hard_exit_authority_proof = exact_broker_proof_v339
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_protective_exit_broker_health_v339"] = _READY_FLAG
        return True
    except Exception:
        return False


def install_import_hook() -> bool:
    with _LOCK:
        if getattr(builtins, _INSTALL_FLAG, False) and os.environ.get(_READY_FLAG) == "1":
            return True
        try:
            if os.environ.get("NIJA_RUNTIME_EXIT_PIPELINE_LATE_BINDING_V338_READY") != "1":
                raise RuntimeError("v338_not_ready")
            scope_ready = _patch_submitter_scope()
            proof_ready = _patch_v337_proof()
            manifest_ready = _register_manifest()
            ready = bool(scope_ready and proof_ready and manifest_ready)
        except Exception as exc:
            ready = False
            LOGGER.exception(
                "RUNTIME_PROTECTIVE_EXIT_BROKER_HEALTH_V339_INSTALL_FAILED marker=%s error=%s:%s "
                "trading_fail_closed=true global_health_unchanged=true safety_gates_bypassed=false",
                MARKER, type(exc).__name__, exc,
            )
        os.environ[_READY_FLAG] = "1" if ready else "0"
        setattr(builtins, _INSTALL_FLAG, ready)
        log = LOGGER.critical if ready else LOGGER.error
        log(
            "RUNTIME_PROTECTIVE_EXIT_BROKER_HEALTH_V339_%s marker=%s ready=%s "
            "trusted_close_only=true exact_broker_object_required=true exact_broker_connected_required=true "
            "global_dispatch_health_not_promoted=true distributed_writer_nonce_killswitch_seak_circuit_required=true "
            "terminal_broker_health_gate_preserved=true ordinary_orders_unchanged=true "
            "forced_exit=false safety_gates_bypassed=false",
            "READY" if ready else "NOT_READY", MARKER, str(ready).lower(),
        )
        return ready


def install() -> bool:
    return install_import_hook()


__all__ = ["MARKER", "RELEASE_ID", "install", "install_import_hook", "_exact_broker_health"]
