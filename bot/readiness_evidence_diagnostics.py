"""Pure read-only diagnostic classification for NIJA startup blockers.

Does not grant authority, change readiness flags, refresh timestamps or submit orders.
A classification is diagnostic only, never an activation policy.
"""
from __future__ import annotations
from typing import Any, Mapping


def classify_readiness(
    readiness: Mapping[str, Any],
    execution_proof: Mapping[str, Any],
    *,
    execution_authority: bool,
    trading_engine_ready: bool,
    position_sync_ready: bool,
    capital_stale: bool,
    kraken_reconciled: bool | None,
    protective_exits_verified: bool | None,
) -> dict[str, Any]:
    """Return deterministic observations. Unknowns stay unknown (never ready)."""
    failure = str(execution_proof.get("failure_condition") or "unknown")
    source = str(execution_proof.get("source") or "unknown")
    producer = str(execution_proof.get("producer") or "missing")
    proof_ready = execution_proof.get("ready") is True
    blockers = []
    if not proof_ready:
        blockers.append("proof.execution_ready")
    if not position_sync_ready:
        blockers.append("position_sync_ready")
    if capital_stale or readiness.get("capital_ready") is not True:
        blockers.append("proof.capital_ready")
    if kraken_reconciled is not True:
        blockers.append("kraken_reconciliation_unverified")
    if protective_exits_verified is not True:
        blockers.append("protective_exits_unverified")
    if readiness.get("execution_ready") is not True:
        blockers.append("execution_ready")
    if not execution_authority:
        blockers.append("execution_authority")
    if not trading_engine_ready:
        blockers.append("trading_engine_ready")

    circular_dependency_candidate = (
        not proof_ready
        and failure == "verification_stale"
        and producer == "missing"
        and readiness.get("broker_connected") is True
        and readiness.get("nonce_ready") is True
    )
    return {
        "diagnostic_only": True,
        "activation_allowed": False,
        "execution_proof_source": source,
        "execution_proof_failure": failure,
        "execution_proof_producer": producer,
        "startup_proof_deadlock_candidate": circular_dependency_candidate,
        "blockers": blockers,
    }
