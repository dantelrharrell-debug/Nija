from bot.startup_two_phase_policy_v8 import PREFLIGHT, evaluate_startup_transition


def test_cold_start_does_not_require_prior_fill_but_cannot_authorize():
    facts = {key: True for key in PREFLIGHT}
    result = evaluate_startup_transition(
        facts, pending_execution=False, posttrade_verified=False)
    assert result["pretrade_candidate_ready"] is True
    assert result["activation_allowed"] is False
    assert result["legacy_execution_gate_unchanged"] is True


def test_pending_execution_requires_real_posttrade_proof():
    facts = {key: True for key in PREFLIGHT}
    result = evaluate_startup_transition(
        facts, pending_execution=True, posttrade_verified=False)
    assert result["pretrade_candidate_ready"] is False
    assert "posttrade_execution_proof" in result["missing"]


def test_missing_safety_certification_fails_closed():
    facts = {key: True for key in PREFLIGHT}
    for key in ("kill_switch_clear", "protective_exits_verified",
                "ledger_reconciled", "backup_restore_certified",
                "authenticated_pretrade_certificate"):
        invalid = dict(facts, **{key: False})
        assert not evaluate_startup_transition(
            invalid, pending_execution=False, posttrade_verified=False
        )["pretrade_candidate_ready"]
