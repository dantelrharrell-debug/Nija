"""Read-only recovery evidence assessment.

No broker calls, order submission, database mutation, or activation.
Missing or malformed attestations are recorded as unresolved.
"""
from __future__ import annotations

from typing import Any, Mapping

REQUIRED = (
    "execution_preflight",
    "broker_position_sync",
    "startup_attempt_reconciliation",
    "protective_exits",
    "ledger_integrity",
    "offhost_restore",
    "emergency_stop_clear",
)


def recovery_evidence_gaps(attestations: Mapping[str, Any] | None) -> dict[str, Any]:
    """Return observed evidence gaps without granting trading permission."""
    observations = attestations if isinstance(attestations, Mapping) else {}
    missing = tuple(key for key in REQUIRED if observations.get(key) is not True)
    return {
        "verified_requirements": tuple(key for key in REQUIRED if observations.get(key) is True),
        "unresolved_requirements": missing,
        "verification_complete": not missing,
        "does_not_authorize_orders": True,
    }
