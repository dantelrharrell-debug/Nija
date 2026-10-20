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
    # Independent, account-scoped authorization and safety attestations.
    # These are not inferred from credentials, process liveness or old fills.
    "operator_live_authorization_verified",
    "account_scope_verified",
    "open_orders_reconciled",
    "unresolved_submissions_clear",
    "writer_fencing_generation_valid",
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


# Explicit mapping only: each field must be independently attested by the
# caller. This adapter never reads environment flags, broker caches or old fills.
_CERTIFICATE_INPUTS = {
    "account_permissions": "broker_permissions_verified",
    "account_identity": "broker_identity_verified",
    "broker_balances": "capital_fresh",
    "position_ledger_reconciliation": "kraken_ledger_reconciled",
    "protective_exit_readback": "protective_exits_verified",
    "open_order_reconciliation": "open_orders_reconciled",
    "duplicate_order_fence": "unresolved_submissions_clear",
    "writer_lease": "writer_lease_valid",
    "nonce_sequence": "nonce_ready",
    "operator_authorization": "operator_live_authorization_verified",
}


def certificate_from_independent_evidence(
    attestations: Mapping[str, Any],
) -> dict[str, bool]:
    """Fail closed unless all required source fields are literal True.

    Source provenance, account scope, timestamps, and signature validation
    remain responsibilities of the authenticated attestation producer.
    This is NOT an activation decision or a broker evidence verifier.
    """
    # These independently attested prerequisites cannot be represented by a
    # single mapped field; reject the entire certificate if any is unknown.
    global_required = (
        "authenticated_readonly_probe", "positions_reconciled",
        "risk_ready", "strategy_ready", "kill_switch_clear",
        "account_scope_verified", "writer_fencing_generation_valid",
    )
    prerequisites_ok = all(attestations.get(key) is True for key in global_required)
    return {target: prerequisites_ok and attestations.get(source) is True
            for target, source in _CERTIFICATE_INPUTS.items()}
