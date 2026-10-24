from bot.execution_admission_acceptance_v468 import inspect_execution_admission


def test_acceptance_never_authorizes_orders(monkeypatch):
    import bot.pretrade_independent_attestation as att
    import preactivation_readiness_convergence_v16_patch as readiness

    monkeypatch.setattr(att, "inspect_authenticated_attestations", lambda scope: {
        "checks": {"account_permissions": True, "protective_exit_readback": True},
        "collector_installed": True, "producer_status": "checks_passed_diagnostic_only",
    })
    monkeypatch.setattr(readiness, "_strict_authority_ready", lambda: (True, "verified"))
    monkeypatch.setattr(readiness, "_kill_switch_clear", lambda: (True, ""))
    monkeypatch.setattr(readiness, "_genuine_execution_marker_proof", lambda: (True, "fresh"))
    result = inspect_execution_admission("platform:kraken")
    assert result["eligible_for_existing_gate"] is True
    assert result["authorizes_orders"] is False


def test_missing_protective_exit_fails_closed(monkeypatch):
    import bot.pretrade_independent_attestation as att
    import preactivation_readiness_convergence_v16_patch as readiness

    monkeypatch.setattr(att, "inspect_authenticated_attestations", lambda scope: {
        "checks": {"account_permissions": True, "protective_exit_readback": False},
        "collector_installed": True, "producer_status": "checks_incomplete",
    })
    monkeypatch.setattr(readiness, "_strict_authority_ready", lambda: (True, "verified"))
    monkeypatch.setattr(readiness, "_kill_switch_clear", lambda: (True, ""))
    monkeypatch.setattr(readiness, "_genuine_execution_marker_proof", lambda: (True, "fresh"))
    result = inspect_execution_admission("platform:kraken")
    assert result["eligible_for_existing_gate"] is False
    assert "protective_exit_readback" in result["missing_checks"]
    assert result["authorizes_orders"] is False
