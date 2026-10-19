"""Read-only phase-one diagnostics for execution-proof startup deadlock (v449).

This module does NOT alter readiness flags, broker orders, activation, or
execution evidence. Consumers must treat these values as telemetry only.
"""
from __future__ import annotations

from typing import Any, Mapping

PREFLIGHT_KEYS = (
    "broker_connected",
    "balance_hydrated",
    "authority_ready",
    "capital_ready",
    "risk_ready",
    "strategy_ready",
    "nonce_ready",
    "bootstrap_ready",
    "position_sync_ready",
)


def observe_preflight(
    readiness: Mapping[str, Any],
    *,
    kill_switch_clear: bool,
    ledger_verified: bool,
    protective_exits_verified: bool,
    broker_permissions_verified: bool,
    broker_data_fresh: bool,
    last_execution_evidence: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Classify observed preflight facts without granting execution authority.

    Missing evidence is false by default. The output is not a trading gate and
    cannot be used as a substitute for existing canonical execution proof.
    """
    checks = {key: readiness.get(key) is True for key in PREFLIGHT_KEYS}
    checks.update({
        "kill_switch_clear": kill_switch_clear is True,
        "ledger_verified": ledger_verified is True,
        "protective_exits_verified": protective_exits_verified is True,
        "broker_permissions_verified": broker_permissions_verified is True,
        "broker_data_fresh": broker_data_fresh is True,
    })
    evidence = last_execution_evidence or {}
    return {
        "preflight_operational_ready_observed": all(checks.values()),
        "preflight_missing": sorted(key for key, value in checks.items() if not value),
        "last_execution_evidence_status": (
            "verified" if evidence.get("verified") is True and evidence.get("fresh") is True
            else "stale" if evidence.get("verified") is True
            else "unverified"
        ),
        "diagnostic_only": True,
        "execution_authority_granted": False,
    }
