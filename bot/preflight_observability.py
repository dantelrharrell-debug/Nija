"""Independent, OBSERVABILITY-ONLY preflight assessment.

Never consumed to grant execution authority. All inputs must be current,
independently verified booleans; absent/unknown attestations fail closed.
Execution proof is deliberately separate from operational preflight.
"""
from __future__ import annotations
from typing import Any, Mapping

REQUIRED_PREFLIGHT = (
    "writer_lease_valid", "nonce_ready", "broker_identity_verified",
    "broker_permissions_verified", "authenticated_readonly_probe",
    "capital_fresh", "positions_reconciled", "kraken_ledger_reconciled",
    "protective_exits_verified", "risk_ready", "strategy_ready",
    "kill_switch_clear",
)


def observe_preflight(attestations: Mapping[str, Any],
                      execution_evidence: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Report preflight and independent post-order evidence, never authorize."""
    missing = [key for key in REQUIRED_PREFLIGHT if attestations.get(key) is not True]
    evidence = execution_evidence or {}
    return {
        "diagnostic_only": True,
        "activation_allowed": False,
        "preflight_operational_ready": not missing,
        "preflight_missing_attestations": missing,
        "last_execution_evidence_status": (
            "verified" if evidence.get("verified") is True else
            "rejected" if evidence.get("verified") is False else "unknown"
        ),
        "execution_evidence_separate": True,
    }
