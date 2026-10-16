"""Regression tests for read-only recovery attestation summaries."""
from bot.recovery_evidence_gaps_v453 import REQUIRED, recovery_evidence_gaps


def test_absent_proof_never_appears_complete():
    result = recovery_evidence_gaps({})
    assert set(result["unresolved_requirements"]) == set(REQUIRED)
    assert result["verification_complete"] is False
    assert result["does_not_authorize_orders"] is True


def test_partial_proof_still_unresolved():
    result = recovery_evidence_gaps({"broker_position_sync": True, "ledger_integrity": "true"})
    assert result["verified_requirements"] == ("broker_position_sync",)
    assert "ledger_integrity" in result["unresolved_requirements"]


def test_fully_attested_diagnostic_does_not_grant_orders():
    result = recovery_evidence_gaps(dict.fromkeys(REQUIRED, True))
    assert result["verification_complete"] is True
    assert result["does_not_authorize_orders"] is True
