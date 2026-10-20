"""Regression tests for production evidence from October 17, 2026.

Read-only diagnostics: no broker API, credentials, orders, filesystem changes,
readiness promotion, or safety-control changes.
"""
from bot.readiness_evidence_diagnostics import classify_readiness


def report(*, proof_ready=False, capital_ready=True, capital_stale=False,
           position_sync=True, kraken=None, exits=None):
    return classify_readiness(
        {"broker_connected": True, "nonce_ready": True,
         "capital_ready": capital_ready, "execution_ready": False},
        {"ready": proof_ready, "source": "canonical_confirmed_fill",
         "producer": "missing", "failure_condition": "verification_stale"},
        execution_authority=False, trading_engine_ready=False,
        position_sync_ready=position_sync, capital_stale=capital_stale,
        kraken_reconciled=kraken, protective_exits_verified=exits,
    )


def test_capital_complete_does_not_clear_missing_execution_proof():
    observed = report(proof_ready=False, capital_ready=True, kraken=True, exits=True)
    assert "proof.capital_ready" not in observed["blockers"]
    assert "proof.execution_ready" in observed["blockers"]
    assert observed["activation_allowed"] is False


def test_intermittent_kraken_failure_stays_independent_of_capital():
    observed = report(proof_ready=False, capital_ready=True,
                      position_sync=False, kraken=False, exits=True)
    assert "position_sync_ready" in observed["blockers"]
    assert "kraken_reconciliation_unverified" in observed["blockers"]
    assert "proof.capital_ready" not in observed["blockers"]
    assert observed["activation_allowed"] is False


def test_protective_exit_coverage_pending_cannot_be_treated_as_ready():
    observed = report(proof_ready=False, position_sync=True,
                      kraken=True, exits=False)
    assert "protective_exits_unverified" in observed["blockers"]
    assert observed["activation_allowed"] is False


def test_unverified_capital_and_exit_proof_fail_closed_even_if_execution_proof_is_ready():
    observed = report(proof_ready=True, capital_ready=False,
                      position_sync=False, kraken=None, exits=None)
    for blocker in ("proof.capital_ready", "position_sync_ready",
                    "kraken_reconciliation_unverified", "protective_exits_unverified"):
        assert blocker in observed["blockers"]
    assert observed["activation_allowed"] is False
