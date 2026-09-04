"""Gate runtime authority convergence on canonical execution proof (v361).

Production on 2026-09-04 showed ``three_venue_execution_readiness`` repeatedly
reporting ``WRITER_AUTHORITY_STATE_MACHINE_BUG`` while writer, capital, venues,
and the core were healthy but canonical ``execution_ready`` was deliberately
false because the confirmed-fill execution marker was still missing.

Broker/writer/capital readiness proves routing capability; it is not execution
proof.  v361 keeps that telemetry, but prevents the three-venue observer from
requesting runtime authority convergence or declaring a state-machine defect
until the canonical readiness table has genuine ``execution_ready`` proof.

This patch never marks execution readiness, never creates an execution marker,
never treats ACK/status/order-id as a fill, and does not alter writer, nonce,
risk, capital, position-sync, ECEL, broker-health, minimum-order, fill, kill-
switch, rejection, or protective-exit gates.
"""
from __future__ import annotations

import importlib
import logging
import os
import threading
from typing import Any

LOGGER = logging.getLogger("nija.runtime_execution_authority_proof_gate_v361")
MARKER = "20260904-runtime-execution-authority-proof-gate-v361"
_READY_FLAG = "NIJA_RUNTIME_EXECUTION_AUTHORITY_PROOF_GATE_V361_READY"
_PATCH_ATTR = "_nija_execution_authority_proof_gate_v361"
_LOCK = threading.RLock()


def _canonical_execution_ready() -> tuple[bool, str]:
    """Observe canonical execution proof without creating or repairing it."""
    try:
        try:
            readiness = importlib.import_module("bot.readiness_table")
        except ImportError:
            readiness = importlib.import_module("readiness_table")
        snapshot = getattr(readiness, "snapshot", None)
        if not callable(snapshot):
            return False, "readiness_snapshot_unavailable"
        table = dict(snapshot() or {})
        ready = bool(table.get("execution_ready", False))
        return ready, "canonical_execution_ready" if ready else "canonical_execution_proof_pending"
    except Exception as exc:
        return False, f"readiness_snapshot_error:{type(exc).__name__}"


def _patch_three_venue_reconcile() -> bool:
    module = importlib.import_module("three_venue_execution_readiness")
    current = getattr(module, "reconcile_execution_readiness", None)
    if not callable(current):
        return False
    if bool(getattr(current, _PATCH_ATTR, False)):
        return True

    original = current

    def reconcile_execution_readiness_v361(*, trigger: str = "manual", force: bool = False) -> dict[str, Any]:
        proof_ready, proof_detail = _canonical_execution_ready()
        if not proof_ready:
            # Preserve broker/writer/capital telemetry exactly while deliberately
            # skipping authority convergence.  Missing execution proof is an
            # expected fail-closed state, not a writer state-machine defect.
            payload = module.publish_once(force=force)
            LOGGER.info(
                "EXECUTION_AUTHORITY_PROOF_GATE_V361_DEFERRED marker=%s trigger=%s "
                "detail=%s writer_ready=%s capital_ready=%s ready_venues=%s "
                "runtime_authority_unchanged=true execution_ready_unchanged=true "
                "execution_proof_fabricated=false forced_activation=false safety_gates_bypassed=false",
                MARKER,
                trigger,
                proof_detail,
                payload.get("writer_ready"),
                payload.get("capital_ready"),
                ",".join(payload.get("ready_venues") or []) or "none",
            )
            return payload
        return original(trigger=trigger, force=force)

    setattr(reconcile_execution_readiness_v361, _PATCH_ATTR, True)
    setattr(reconcile_execution_readiness_v361, "__wrapped__", original)
    module.reconcile_execution_readiness = reconcile_execution_readiness_v361
    return True


def _patch_release_manifest() -> bool:
    try:
        manifest = importlib.import_module("bot.runtime_release_manifest_patch")
        required = getattr(manifest, "_REQUIRED_FLAGS", None)
        if isinstance(required, dict):
            required["runtime_execution_authority_proof_gate_v361"] = _READY_FLAG
            return True
    except Exception:
        pass
    return False


def install_import_hook() -> bool:
    with _LOCK:
        try:
            ok = bool(_patch_three_venue_reconcile() and _patch_release_manifest())
        except Exception as exc:
            LOGGER.exception(
                "RUNTIME_EXECUTION_AUTHORITY_PROOF_GATE_V361_INSTALL_FAILED marker=%s err=%s:%s fail_closed=true",
                MARKER,
                type(exc).__name__,
                exc,
            )
            ok = False
        os.environ[_READY_FLAG] = "1" if ok else "0"
        if ok:
            LOGGER.critical(
                "RUNTIME_EXECUTION_AUTHORITY_PROOF_GATE_V361_READY marker=%s ready=true "
                "canonical_execution_ready_required=true three_venue_telemetry_preserved=true "
                "authority_convergence_deferred_without_proof=true ack_not_fill=true "
                "execution_proof_fabricated=false forced_activation=false "
                "writer_nonce_risk_capital_position_ecel_broker_health_minimum_order_fill_gates_unchanged=true "
                "protective_exits_unchanged=true safety_gates_bypassed=false",
                MARKER,
            )
        return ok


def install() -> bool:
    return install_import_hook()


__all__ = [
    "MARKER",
    "install",
    "install_import_hook",
    "_canonical_execution_ready",
    "_patch_three_venue_reconcile",
]
