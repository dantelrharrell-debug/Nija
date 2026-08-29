"""Converge current writer-authority and nonce truth without weakening safety.

Production on 2026-08-25 exposed two coupled readiness defects:

* authority_heartbeat could mark ``nonce_ready`` from the absence of the legacy
  KRAKEN_NONCE_LEASE_REQUIRED environment variable even while a connected Kraken
  platform broker was present; and
* preactivation_readiness_convergence_v16 used one combined writer+nonce probe
  for both ``authority_ready`` and ``nonce_ready``. A legitimate pending Kraken
  nonce proof could therefore erase a separately proven current writer authority
  heartbeat when v133 synchronized current proof truth.

v231 keeps those facts independent. Writer authority is reconstructed only from
current distributed-writer authority, a fresh writer heartbeat, and a clear kill
switch. Nonce readiness is reconstructed from the canonical raw nonce sync/lease
gates; if Kraken is connected, no Coinbase-only shortcut is permitted.

Production on 2026-08-29 then exposed a second coupling: v16's
``_runtime_writer_nonce_ready`` checks the genuine heartbeat execution marker
*before* its raw nonce gates. A missing ORDER/FILL marker therefore made both
``execution_ready`` and ``nonce_ready`` false even when raw nonce authority was
healthy. v272 separates those proofs at the v231 convergence boundary:

* ``nonce_ready`` requires the canonical raw nonce sync/lease proof only;
* ``execution_ready`` additionally requires a fresh, stage-sufficient heartbeat
  execution marker. v169 provenance validation remains authoritative, so only
  ``source=heartbeat_trade`` / ``proof_kind=execution_probe`` can satisfy
  ORDER_VERIFY/FILL_VERIFY policy;
* writer authority remains an independent current distributed-writer proof.

When position synchronization is still false after a healthy authority heartbeat,
v231 wakes the existing v161 authoritative position-sync monitor immediately.
It never marks position_sync_ready itself and never converts a failed/timeout
broker read into success.

No capital, broker connectivity, balance, position, nonce, writer, risk,
kill-switch, order/fill or LIVE activation proof is fabricated. All existing
fail-closed gates remain authoritative.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from functools import wraps
from typing import Any

LOGGER = logging.getLogger("nija.runtime_authority_nonce_truth_convergence_v231")
MARKER = "20260825-runtime-authority-nonce-truth-convergence-v231"
V272_MARKER = "20260829-nonce-execution-proof-separation-v272"
RELEASE_ID = "20260825-runtime-convergence-v231"
_READY_FLAG = "NIJA_RUNTIME_AUTHORITY_NONCE_TRUTH_V231_READY"
_V272_READY_FLAG = "NIJA_NONCE_EXECUTION_PROOF_SEPARATION_V272_READY"
_PATCH_ATTR = "_nija_runtime_authority_nonce_truth_v231"
_LOCK = threading.RLock()
_INSTALLED = False


def _v16():
    return importlib.import_module("preactivation_readiness_convergence_v16_patch")


def _tsm():
    return importlib.import_module("bot.trading_state_machine")


def _readiness():
    return importlib.import_module("bot.readiness_table")


def _current_writer_authority_proof() -> tuple[bool, str]:
    """Return writer authority independently of Kraken nonce maturity."""
    v16 = _v16()
    tsm = _tsm()

    token = str(os.environ.get("NIJA_WRITER_FENCING_TOKEN", "") or "").strip()
    generation = str(os.environ.get("NIJA_WRITER_LEASE_GENERATION", "") or "").strip()
    if not token or not generation:
        return False, f"writer_identity_missing:token={bool(token)} generation={generation or 'missing'}"

    heartbeat_probe = getattr(v16, "_heartbeat_ready", None)
    if not callable(heartbeat_probe):
        return False, "writer_heartbeat_probe_missing"
    heartbeat_ok, heartbeat_detail = heartbeat_probe()
    if not bool(heartbeat_ok):
        return False, str(heartbeat_detail or "writer_heartbeat_not_ready")

    authority_gate = getattr(tsm, "_distributed_writer_authority_gate", None)
    if not callable(authority_gate):
        return False, "distributed_writer_authority_gate_missing"
    authority_ok, authority_detail = authority_gate()
    if not bool(authority_ok):
        return False, str(authority_detail or "distributed_writer_authority_not_ready")

    kill_probe = getattr(v16, "_kill_switch_clear", None)
    if not callable(kill_probe):
        return False, "kill_switch_probe_missing"
    kill_ok, kill_detail = kill_probe()
    if not bool(kill_ok):
        return False, str(kill_detail or "kill_switch_not_clear")

    return True, f"writer_authority_current;{heartbeat_detail or 'heartbeat_fresh'}"


def _raw_nonce_authority_proof() -> tuple[bool, str]:
    """Return raw nonce sync/lease truth without consulting execution proof."""
    try:
        authority = importlib.import_module("bot.execution_authority_context")
        probe = getattr(authority, "_runtime_nonce_authority_status", None)
        if not callable(probe):
            return False, "runtime_nonce_authority_probe_missing"
        ready, detail = probe()
        if not bool(ready):
            return False, str(detail or "runtime_nonce_authority_not_ready")
        return True, str(detail or "raw_nonce_authority_current")
    except Exception as exc:
        return False, f"runtime_nonce_authority_probe_failed:{type(exc).__name__}:{exc}"


def _execution_marker_proof() -> tuple[bool, str]:
    """Return genuine execution-marker truth with v169 provenance enforcement."""
    try:
        status = getattr(_tsm(), "_heartbeat_verification_status", None)
        if not callable(status):
            return False, "heartbeat_verification_probe_missing"
        ready, detail, meta = status()
        meta = dict(meta or {})
        if not bool(ready):
            return False, str(detail or "heartbeat_execution_marker_not_ready")
        source = str(meta.get("source", "") or "").strip().lower()
        proof_kind = str(meta.get("proof_kind", "") or "").strip().lower()
        # v169 normally enforces these fields in the wrapped status function.
        # Re-check them here so v272 remains fail closed if wrapper ordering ever
        # changes during a late import/reassertion.
        required = str(meta.get("required_stage", "ORDER_VERIFY") or "ORDER_VERIFY").strip().upper()
        if required in {"ORDER_VERIFY", "FILL_VERIFY"}:
            if source != "heartbeat_trade" or proof_kind != "execution_probe":
                return False, (
                    "execution_provenance_invalid:"
                    f"source={source or 'missing'}:kind={proof_kind or 'missing'}"
                )
        stage = str(meta.get("stage", "") or "").strip().upper()
        return True, f"execution_marker_current:stage={stage or 'verified'}"
    except Exception as exc:
        return False, f"heartbeat_verification_probe_failed:{type(exc).__name__}:{exc}"


def _kraken_nonce_required() -> bool:
    """Use canonical runtime broker topology, never legacy env absence."""
    tsm = _tsm()
    required = getattr(tsm, "_kraken_nonce_gates_required", None)
    if not callable(required):
        # Fail closed if topology cannot be classified.
        return True
    try:
        return bool(required())
    except Exception:
        return True


def _patch_v16_proof_collection() -> bool:
    v16 = _v16()
    current = getattr(v16, "_collect_proofs", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def collect_v231():
        proofs, details = current()
        proofs = dict(proofs or {})
        details = dict(details or {})

        authority_ready, authority_detail = _current_writer_authority_proof()
        nonce_ready, nonce_detail = _raw_nonce_authority_proof()
        execution_marker_ready, execution_marker_detail = _execution_marker_proof()
        execution_pipeline = bool(details.get("execution_pipeline_wired", False))
        risk_ready = bool(proofs.get("risk_ready", False))

        proofs["authority_ready"] = bool(authority_ready)
        proofs["nonce_ready"] = bool(nonce_ready)
        proofs["execution_ready"] = bool(
            execution_pipeline
            and risk_ready
            and authority_ready
            and nonce_ready
            and execution_marker_ready
        )
        details["v231_writer_authority"] = authority_detail
        details["v231_kraken_nonce_required"] = _kraken_nonce_required()
        details["v231_nonce_ready"] = bool(nonce_ready)
        details["v272_raw_nonce_detail"] = nonce_detail
        details["v272_execution_marker_ready"] = bool(execution_marker_ready)
        details["v272_execution_marker_detail"] = execution_marker_detail
        return proofs, details

    setattr(collect_v231, _PATCH_ATTR, True)
    setattr(collect_v231, "__wrapped__", current)
    v16._collect_proofs = collect_v231
    return True


def _correct_heartbeat_nonce_truth() -> tuple[bool, str]:
    """Correct nonce readiness from raw nonce authority, never execution proof."""
    nonce_ready, nonce_detail = _raw_nonce_authority_proof()
    readiness = _readiness()
    table = dict(readiness.snapshot())

    if nonce_ready:
        if not bool(table.get("nonce_ready", False)):
            readiness.mark_ready("nonce_ready")
        return True, nonce_detail or "raw_nonce_current_proof_true"

    if bool(table.get("nonce_ready", False)):
        readiness.revoke_ready("nonce_ready", reason="v272_raw_nonce_authority_false")
        LOGGER.warning(
            "AUTHORITY_NONCE_V272_RAW_NONCE_REVOKED marker=%s kraken_nonce_required=%s "
            "detail=%s nonce_ready=false execution_marker_ignored_for_nonce=true "
            "proof_fabricated=false trading_fail_closed=true",
            V272_MARKER,
            str(_kraken_nonce_required()).lower(),
            nonce_detail or "raw_nonce_authority_false",
        )
    return False, nonce_detail or "raw_nonce_current_proof_false"


def _wake_position_sync_if_needed() -> bool:
    """Dispatch the existing authoritative v161 reconciler; never publish success."""
    try:
        table = dict(_readiness().snapshot())
        if bool(table.get("position_sync_ready", False)):
            return False
        v161 = importlib.import_module("bot.runtime_capital_position_convergence_v161_patch")
        iteration = getattr(v161, "_position_monitor_iteration", None)
        if not callable(iteration):
            return False
        started, published = iteration()
        LOGGER.info(
            "POSITION_SYNC_V231_WAKE marker=%s workers_started=%s readiness_published=%s "
            "authoritative_adopter_only=true synthetic_success=false",
            MARKER,
            started,
            str(bool(published)).lower(),
        )
        return bool(started or published)
    except Exception as exc:
        LOGGER.warning(
            "POSITION_SYNC_V231_WAKE_FAILED marker=%s error=%s:%s trading_fail_closed=true",
            MARKER,
            type(exc).__name__,
            exc,
        )
        return False


def _patch_authority_heartbeat() -> bool:
    heartbeat = importlib.import_module("bot.authority_heartbeat")
    cls = getattr(heartbeat, "AuthorityHeartbeatMonitor", None)
    if not isinstance(cls, type):
        return False
    current = getattr(cls, "_tick", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    @wraps(current)
    def tick_v231(self: Any) -> None:
        current(self)
        # Only reconcile readiness after a genuinely healthy current authority
        # heartbeat. Failure/lockdown paths remain untouched.
        authority_ok, _detail = _current_writer_authority_proof()
        if not authority_ok:
            return
        _correct_heartbeat_nonce_truth()
        _wake_position_sync_if_needed()

    setattr(tick_v231, _PATCH_ATTR, True)
    setattr(tick_v231, "__wrapped__", current)
    cls._tick = tick_v231
    return True


def _register_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if not isinstance(required, dict):
            return False
        required["runtime_authority_nonce_truth_v231"] = _READY_FLAG
        required["nonce_execution_proof_separation_v272"] = _V272_READY_FLAG
        return True
    except Exception:
        return False


def install() -> bool:
    global _INSTALLED
    with _LOCK:
        v16_ok = _patch_v16_proof_collection()
        heartbeat_ok = _patch_authority_heartbeat()
        manifest_ok = _register_manifest()
        ready = bool(v16_ok and heartbeat_ok and manifest_ok)
        os.environ[_READY_FLAG] = "1" if ready else "0"
        os.environ[_V272_READY_FLAG] = "1" if ready else "0"
        _INSTALLED = ready
        LOGGER.critical(
            "RUNTIME_AUTHORITY_NONCE_TRUTH_V231 marker=%s ready=%s "
            "authority_nonce_split=true active_kraken_topology_authoritative=true "
            "legacy_coinbase_nonce_shortcut_corrected=true position_sync_immediate_wakeup=true "
            "nonce_gates_unchanged=true writer_gates_unchanged=true kill_switch_unchanged=true "
            "risk_gates_unchanged=true execution_proof_fabricated=false forced_activation=false "
            "safety_gates_bypassed=false",
            MARKER,
            str(ready).lower(),
        )
        LOGGER.critical(
            "NONCE_EXECUTION_PROOF_SEPARATION_V272 marker=%s ready=%s "
            "raw_nonce_independent=true execution_marker_independent=true "
            "v169_execution_provenance_required=true nonce_from_execution_marker=false "
            "execution_requires_raw_nonce=true execution_requires_genuine_marker=true "
            "writer_authority_independent=true readiness_fabricated=false "
            "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
            V272_MARKER,
            str(ready).lower(),
        )
        return ready


def install_import_hook() -> bool:
    return install()


__all__ = [
    "MARKER",
    "V272_MARKER",
    "RELEASE_ID",
    "install",
    "install_import_hook",
    "_current_writer_authority_proof",
    "_raw_nonce_authority_proof",
    "_execution_marker_proof",
    "_kraken_nonce_required",
    "_correct_heartbeat_nonce_truth",
    "_wake_position_sync_if_needed",
    "_patch_v16_proof_collection",
    "_patch_authority_heartbeat",
]
