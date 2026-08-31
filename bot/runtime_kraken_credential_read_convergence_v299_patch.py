"""Credential-scoped Kraken monitoring coordination v299.

Production generation 5006 on 2026-08-30 exposed a topology mismatch after the
v293/v297 repairs. v293 correctly serializes Kraken private calls by proven API
credential, but v297 still keys its monitoring fairness gate and Balance
single-flight by ``id(broker)``. NIJA can hold more than one live KrakenBroker
object representing the same API credential during startup/reconciliation. Two
such objects therefore pre-wait independently, start independent Balance
flights, and then collide on v293's same-credential lock. v121 correctly reports
that collision as ``KrakenReadLockBusy`` and position proof falls fail-closed.

v299 aligns read coordination with the already-authoritative credential scope:

* broker objects with the same proven Kraken API key share one v297 priority/FIFO
  monitoring gate;
* read-only Balance calls with the same proven API key share one genuine
  authenticated response, even when initiated through different broker objects;
* different API keys remain independent;
* if credential identity cannot be proven, coordination falls back to the prior
  object-local behavior rather than guessing account identity.

v314 closes a priority inversion observed in production on 2026-08-31. A routine
capital/history caller could become the credential Balance single-flight owner
before an authoritative v286 position caller arrived. The authoritative caller
then joined the routine flight before reaching v297's priority gate, so the
existing owner remained routine priority and could sit behind another 60-second
monitoring turn. v314 promotes only that already-existing Balance owner's gate
priority when the joining caller is currently inside v297's authoritative
position context. The same single flight and same authenticated exchange call
remain authoritative: no duplicate request is created, no configured Kraken
interval is shortened, and no lock is released or bypassed.

No API key material is logged or persisted. The v293 SHA-256 credential
fingerprint is used only as an in-process map key. Kraken rate intervals,
transport timeouts, nonce ordering, credential serialization, snapshot TTL,
position/cost-basis truth, writer/risk/capital/kill-switch/order/fill gates and
mutating order semantics are unchanged. No readiness or broker response is
fabricated.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
import time
from functools import wraps
from typing import Any, Callable

LOGGER = logging.getLogger("nija.runtime_kraken_credential_read_convergence_v299")
MARKER = "20260830-kraken-credential-read-convergence-v299"
OWNER_PRIORITY_MARKER = "20260831-kraken-balance-owner-priority-v314"
RELEASE_ID = "20260831-runtime-convergence-v314"
_READY_FLAG = "NIJA_RUNTIME_KRAKEN_CREDENTIAL_READ_CONVERGENCE_V299_READY"
_GATE_PATCH_ATTR = "_nija_kraken_credential_read_gate_v299"
_BALANCE_PATCH_ATTR = "_nija_kraken_credential_balance_flight_v299"
_PRIORITY_BRIDGE_ATTR = "_nija_kraken_balance_owner_priority_v314"
_LOCK = threading.RLock()
_FLIGHT_LOCK = threading.RLock()
_GATES: dict[str, Any] = {}
_BALANCE_FLIGHTS: dict[str, dict[str, Any]] = {}
_PROMOTED_OWNER_THREADS: set[int] = set()


def _v286() -> Any:
    return importlib.import_module("bot.runtime_kraken_position_refresh_liveness_v286_patch")


def _v293() -> Any:
    return importlib.import_module("bot.runtime_kraken_credential_lock_scope_v293_patch")


def _v297() -> Any:
    return importlib.import_module("bot.runtime_kraken_monitoring_fairness_v297_patch")


def _credential_scope_key(broker: Any) -> str:
    """Return v293's non-reversible credential fingerprint, else empty."""
    try:
        helper = getattr(_v293(), "_credential_scope_key", None)
        if callable(helper):
            return str(helper(broker) or "")
    except Exception:
        pass
    return ""


def _coordination_key(broker: Any) -> tuple[str, bool]:
    scope = _credential_scope_key(broker)
    if scope:
        return f"credential:{scope}", True
    return f"object:{id(broker)}", False


def _scope_label(key: str, credential_proven: bool) -> str:
    if credential_proven and key.startswith("credential:"):
        return "cred:" + key.split(":", 1)[1][:12]
    return "object-local"


def _priority_gate_class() -> type | None:
    try:
        cls = getattr(_v297(), "_PriorityFairGate", None)
        return cls if isinstance(cls, type) else None
    except Exception:
        return None


def _shared_monitoring_gate(broker: Any) -> Any:
    key, credential_proven = _coordination_key(broker)
    gate_cls = _priority_gate_class()
    if gate_cls is None:
        raise RuntimeError("v297_priority_gate_unavailable")

    with _LOCK:
        gate = _GATES.get(key)
        if gate is not None:
            return gate

        existing = getattr(broker, "_nija_kraken_monitoring_priority_gate_v297", None)
        if isinstance(existing, gate_cls):
            gate = existing
        else:
            identity = str(getattr(broker, "account_identifier", "unknown") or "unknown")
            gate = gate_cls(identity)
        _GATES[key] = gate

    try:
        setattr(broker, "_nija_kraken_monitoring_priority_gate_v297", gate)
    except Exception:
        pass
    try:
        setattr(broker, "_nija_kraken_credential_read_scope_v299", _scope_label(key, credential_proven))
    except Exception:
        pass
    return gate


def _clone(value: Any) -> Any:
    try:
        helper = getattr(_v297(), "_clone", None)
        if callable(helper):
            return helper(value)
    except Exception:
        pass
    try:
        import copy
        return copy.deepcopy(value)
    except Exception:
        return value


def _balance_wait_s(broker: Any) -> float:
    try:
        helper = getattr(_v297(), "_balance_wait_s", None)
        if callable(helper):
            return max(1.0, float(helper(broker) or 0.0))
    except Exception:
        pass
    return 60.0


def _reuse_grace_s() -> float:
    try:
        helper = getattr(_v297(), "_reuse_grace_s", None)
        if callable(helper):
            return max(0.0, min(2.0, float(helper() or 0.0)))
    except Exception:
        pass
    return 0.5


def _ensure_priority_bridge() -> bool:
    """Make v297 priority evaluation aware of a promoted single-flight owner.

    The original v297 thread-local remains authoritative. The process-local set
    only upgrades the already-selected Balance owner thread while an
    authoritative consumer is attached to that exact flight.
    """
    try:
        v297 = _v297()
        current = getattr(v297, "_authoritative_priority", None)
    except Exception:
        return False
    if not callable(current):
        return False
    if bool(getattr(current, _PRIORITY_BRIDGE_ATTR, False)):
        return True
    original = current

    @wraps(original)
    def authoritative_priority_v314() -> bool:
        try:
            inherited = bool(original())
        except Exception:
            inherited = False
        thread_id = threading.get_ident()
        with _FLIGHT_LOCK:
            promoted = thread_id in _PROMOTED_OWNER_THREADS
        return bool(inherited or promoted)

    setattr(authoritative_priority_v314, _PRIORITY_BRIDGE_ATTR, True)
    setattr(authoritative_priority_v314, "__wrapped__", original)
    v297._authoritative_priority = authoritative_priority_v314
    return True


def _caller_is_authoritative() -> bool:
    try:
        probe = getattr(_v297(), "_authoritative_priority", None)
        return bool(callable(probe) and probe())
    except Exception:
        return False


def _clear_owner_promotion(thread_id: int) -> None:
    if thread_id <= 0:
        return
    with _FLIGHT_LOCK:
        _PROMOTED_OWNER_THREADS.discard(thread_id)


def _promote_existing_balance_owner(broker: Any, flight: dict[str, Any], label: str) -> bool:
    """Promote an existing routine Balance owner for an authoritative joiner.

    If the owner has not reached the gate yet, the v314 priority bridge makes its
    later admission authoritative. If it is already queued, update that token in
    place under the gate condition. If it already holds the gate, no scheduling
    mutation is needed; the process-local promotion is cleared when the flight
    finishes. Exclusivity and configured rate timing remain unchanged.
    """
    if not _caller_is_authoritative():
        return False
    try:
        owner_thread = int(flight.get("owner_thread", 0) or 0)
    except Exception:
        owner_thread = 0
    if owner_thread <= 0 or owner_thread == threading.get_ident():
        return False

    with _FLIGHT_LOCK:
        _PROMOTED_OWNER_THREADS.add(owner_thread)

    queued_promoted = False
    owner_holds_gate = False
    try:
        gate = _shared_monitoring_gate(broker)
        condition = getattr(gate, "_condition", None)
        waiters = getattr(gate, "_waiters", None)
        if condition is not None and isinstance(waiters, list):
            with condition:
                owner_holds_gate = bool(
                    getattr(gate, "_held", False)
                    and int(getattr(gate, "_owner", 0) or 0) == owner_thread
                )
                for token in waiters:
                    if not isinstance(token, dict):
                        continue
                    try:
                        token_thread = int(token.get("thread_id", 0) or 0)
                    except Exception:
                        token_thread = 0
                    if token_thread != owner_thread:
                        continue
                    prior = int(token.get("priority", 10) or 10)
                    if prior > 0:
                        token["priority"] = 0
                        queued_promoted = True
                notify = getattr(condition, "notify_all", None)
                if queued_promoted and callable(notify):
                    notify()
    except Exception:
        # The thread-level bridge still handles an owner that has not yet queued.
        pass

    LOGGER.critical(
        "KRAKEN_BALANCE_OWNER_PRIORITY_V314_PROMOTED marker=%s account=%s scope=%s "
        "owner_thread=%s queued_token_promoted=%s owner_already_holds_gate=%s "
        "authoritative_joiner=true same_flight=true duplicate_private_call=false "
        "configured_rate_interval_unchanged=true exclusive_gate_preserved=true "
        "lock_bypass=false lock_force_release=false readiness_granted=false "
        "execution_proof_fabricated=false safety_gates_bypassed=false",
        OWNER_PRIORITY_MARKER,
        str(getattr(broker, "account_identifier", "unknown") or "unknown"),
        label,
        owner_thread,
        str(queued_promoted).lower(),
        str(owner_holds_gate).lower(),
    )
    return True


def _credential_balance_call(broker: Any, call: Callable[[], Any]) -> Any:
    """Share one genuine Balance result across objects with the same credential."""
    key, credential_proven = _coordination_key(broker)
    now = time.monotonic()
    owner = False

    with _FLIGHT_LOCK:
        flight = _BALANCE_FLIGHTS.get(key)
        if isinstance(flight, dict):
            event = flight.get("event")
            done = bool(event.is_set()) if callable(getattr(event, "is_set", None)) else False
            finished_at = float(flight.get("finished_at", 0.0) or 0.0)
            if done and (finished_at <= 0.0 or now - finished_at > _reuse_grace_s()):
                _BALANCE_FLIGHTS.pop(key, None)
                flight = None

        if not isinstance(flight, dict):
            flight = {
                "event": threading.Event(),
                "result": None,
                "error": None,
                "started_at": now,
                "finished_at": 0.0,
                "owner_thread": threading.get_ident(),
                "waiters": 0,
                "credential_proven": credential_proven,
            }
            _BALANCE_FLIGHTS[key] = flight
            owner = True
        else:
            flight["waiters"] = int(flight.get("waiters", 0) or 0) + 1

    label = _scope_label(key, credential_proven)
    account = str(getattr(broker, "account_identifier", "unknown") or "unknown")

    if not owner:
        _promote_existing_balance_owner(broker, flight, label)

    if owner:
        owner_thread = int(flight.get("owner_thread", 0) or 0)
        try:
            result = call()
            flight["result"] = _clone(result)
            return _clone(result)
        except BaseException as exc:
            flight["error"] = exc
            raise
        finally:
            _clear_owner_promotion(owner_thread)
            flight["finished_at"] = time.monotonic()
            flight["event"].set()
            waiters = int(flight.get("waiters", 0) or 0)
            if waiters:
                LOGGER.info(
                    "KRAKEN_CREDENTIAL_BALANCE_V299_OWNER_COMPLETE marker=%s account=%s scope=%s "
                    "waiters=%d credential_proven=%s genuine_response_only=true defensive_copy=true "
                    "freshness_extended=false rate_interval_unchanged=true lock_bypass=false",
                    MARKER,
                    account,
                    label,
                    waiters,
                    str(credential_proven).lower(),
                )

    wait_s = _balance_wait_s(broker)
    age = max(0.0, now - float(flight.get("started_at", 0.0) or 0.0))
    LOGGER.info(
        "KRAKEN_CREDENTIAL_BALANCE_V299_JOIN marker=%s account=%s scope=%s "
        "flight_age_s=%.3f wait_budget_s=%.1f credential_proven=%s "
        "duplicate_private_call=false genuine_response_required=true",
        MARKER,
        account,
        label,
        age,
        wait_s,
        str(credential_proven).lower(),
    )
    if not flight["event"].wait(wait_s):
        raise TimeoutError(
            "Kraken credential Balance flight pending after "
            f"{wait_s:.1f}s age={max(0.0, time.monotonic() - float(flight.get('started_at', 0.0) or 0.0)):.1f}s"
        )
    error = flight.get("error")
    if error is not None:
        raise error
    return _clone(flight.get("result"))


def _patch_monitoring_gate() -> bool:
    try:
        v286 = _v286()
    except Exception:
        return False
    current = getattr(v286, "_instance_rate_gate", None)
    if not callable(current):
        return False
    if bool(getattr(current, _GATE_PATCH_ATTR, False)):
        return True

    @wraps(current)
    def gate_v299(broker: Any) -> Any:
        return _shared_monitoring_gate(broker)

    setattr(gate_v299, _GATE_PATCH_ATTR, True)
    setattr(gate_v299, "__wrapped__", current)
    v286._instance_rate_gate = gate_v299
    return True


def _patch_balance_coalescer() -> bool:
    try:
        v297 = _v297()
    except Exception:
        return False
    current = getattr(v297, "_coalesced_balance_call", None)
    if not callable(current):
        return False
    if bool(getattr(current, _BALANCE_PATCH_ATTR, False)):
        return True

    @wraps(current)
    def balance_v299(broker: Any, call: Callable[[], Any]) -> Any:
        return _credential_balance_call(broker, call)

    setattr(balance_v299, _BALANCE_PATCH_ATTR, True)
    setattr(balance_v299, "__wrapped__", current)
    v297._coalesced_balance_call = balance_v299
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_kraken_credential_read_convergence_v299"] = _READY_FLAG
        return True
    except Exception:
        return False


def reconcile_once() -> dict[str, Any]:
    helper_ready = callable(getattr(_v293(), "_credential_scope_key", None))
    gate_ready = _patch_monitoring_gate()
    balance_ready = _patch_balance_coalescer()
    priority_bridge = _ensure_priority_bridge()
    with _LOCK:
        shared_gates = len(_GATES)
    with _FLIGHT_LOCK:
        inflight = sum(
            1
            for flight in _BALANCE_FLIGHTS.values()
            if isinstance(flight, dict)
            and callable(getattr(flight.get("event"), "is_set", None))
            and not flight["event"].is_set()
        )
        promoted = len(_PROMOTED_OWNER_THREADS)
    return {
        "ready": bool(helper_ready and gate_ready and balance_ready and priority_bridge),
        "credential_helper": bool(helper_ready),
        "monitoring_gate": bool(gate_ready),
        "balance_coalescer": bool(balance_ready),
        "priority_bridge": bool(priority_bridge),
        "shared_gate_scopes": int(shared_gates),
        "credential_balance_flights": int(inflight),
        "promoted_owner_threads": int(promoted),
    }


def install() -> bool:
    try:
        manifest_ready = _register_manifest()
        state = reconcile_once()
    except Exception as exc:
        manifest_ready = False
        state = {"ready": False, "error": f"{type(exc).__name__}:{exc}"}

    ready = bool(manifest_ready and state.get("ready"))
    os.environ[_READY_FLAG] = "1" if ready else "0"
    log = LOGGER.critical if ready else LOGGER.error
    log(
        "RUNTIME_KRAKEN_CREDENTIAL_READ_CONVERGENCE_V299_%s marker=%s owner_priority_marker=%s ready=%s "
        "credential_helper=%s monitoring_gate=%s balance_coalescer=%s priority_bridge=%s "
        "same_credential_shared_gate=true same_credential_balance_single_flight=true "
        "authoritative_join_promotes_existing_owner=true duplicate_private_call=false "
        "different_credentials_independent=true unproven_credential_object_local=true "
        "rate_interval_unchanged=true transport_timeout_unchanged=true nonce_ordering_unchanged=true "
        "snapshot_ttl_unchanged=true lock_force_release=false lock_bypass=false "
        "position_success_fabricated=false execution_proof_fabricated=false forced_activation=false "
        "writer_nonce_risk_capital_killswitch_order_fill_gates_unchanged=true safety_gates_bypassed=false",
        "READY" if ready else "NOT_READY",
        MARKER,
        OWNER_PRIORITY_MARKER,
        str(ready).lower(),
        str(bool(state.get("credential_helper"))).lower(),
        str(bool(state.get("monitoring_gate"))).lower(),
        str(bool(state.get("balance_coalescer"))).lower(),
        str(bool(state.get("priority_bridge"))).lower(),
    )
    return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "OWNER_PRIORITY_MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "reconcile_once",
    "_credential_scope_key",
    "_coordination_key",
    "_shared_monitoring_gate",
    "_credential_balance_call",
    "_ensure_priority_bridge",
    "_promote_existing_balance_owner",
    "_patch_monitoring_gate",
    "_patch_balance_coalescer",
]
