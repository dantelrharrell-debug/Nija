from bot.readiness_evidence_diagnostics import classify_readiness


def snapshot(**changes):
    table = {"broker_connected": True, "nonce_ready": True,
             "capital_ready": True, "execution_ready": False}
    table.update(changes)
    return table


def classify(proof, **changes):
    arguments = dict(execution_authority=False, trading_engine_ready=False,
                     position_sync_ready=True, capital_stale=False,
                     kraken_reconciled=None, protective_exits_verified=None)
    arguments.update(changes)
    return classify_readiness(snapshot(), proof, **arguments)


def test_stale_proof_cannot_grant_authority():
    report = classify({"ready": False, "source": "canonical_confirmed_fill",
                       "producer": "missing", "failure_condition": "verification_stale"})
    assert report["startup_proof_deadlock_candidate"] is True
    assert report["activation_allowed"] is False
    assert "proof.execution_ready" in report["blockers"]


def test_unknown_reconciliation_is_not_pass():
    report = classify({"ready": True})
    assert "kraken_reconciliation_unverified" in report["blockers"]
    assert "protective_exits_unverified" in report["blockers"]
    assert report["activation_allowed"] is False


def test_capital_and_position_flapping_reported_independently():
    report = classify({"ready": False}, capital_stale=True, position_sync_ready=False)
    assert "proof.capital_ready" in report["blockers"]
    assert "position_sync_ready" in report["blockers"]
    assert report["startup_proof_deadlock_candidate"] is False
