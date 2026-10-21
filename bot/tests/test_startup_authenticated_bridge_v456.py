from bot.startup_authenticated_bridge_v456 import evaluate_authenticated_startup_candidate
from bot import pretrade_independent_attestation as attestation


def test_unregistered_collector_denies_everything(monkeypatch):
    monkeypatch.setattr(attestation, "_COLLECTOR", None)
    result = evaluate_authenticated_startup_candidate(
        "platform:kraken", {}, pending_execution=False, posttrade_verified=False
    )
    assert result["pretrade_candidate_ready"] is False
    assert result["activation_allowed"] is False
    assert "authenticated_pretrade_certificate" in result["missing"]


def test_fresh_independent_producer_never_grants_authority(monkeypatch):
    def collector(account):
        return {
            "account": account, "source": "authenticated_independent",
            "read_only": True, "scope_verified": True,
            "observed_at_epoch": 1000.0,
            "checks": {key: True for key in attestation.FIELDS},
            "provenance": {
                "authenticated_broker_read_verified": True,
                "ledger_snapshot_verified": True,
                "complete_pagination_verified": True,
                "collector_identity_verified": True,
                "account_scope_verified": True,
            },
        }
    monkeypatch.setattr(attestation, "_COLLECTOR", collector)
    external = {key: True for key in (
        "risk_ready", "strategy_ready", "capital_ready", "kill_switch_clear",
        "backup_restore_certified", "account_scope_verified",
    )}
    monkeypatch.setattr(
        "bot.pretrade_independent_attestation.time.time", lambda: 1000.0
    )
    ready = evaluate_authenticated_startup_candidate(
        "platform:kraken", external,
        pending_execution=False, posttrade_verified=False
    )
    assert ready["pretrade_candidate_ready"] is True
    assert ready["activation_allowed"] is False
    assert ready["diagnostic_only"] is True
    pending = evaluate_authenticated_startup_candidate(
        "platform:kraken", external,
        pending_execution=True, posttrade_verified=False
    )
    assert pending["pretrade_candidate_ready"] is False
    assert "posttrade_execution_proof" in pending["missing"]


def test_claimed_success_without_provenance_is_denied(monkeypatch):
    monkeypatch.setattr(
        attestation, "_COLLECTOR",
        lambda account: {
            "account": account, "source": "authenticated_independent",
            "read_only": True, "scope_verified": True,
            "observed_at_epoch": 1000.0,
            "checks": {key: True for key in attestation.FIELDS},
        },
    )
    monkeypatch.setattr(attestation.time, "time", lambda: 1000.0)
    external = {
        key: True for key in (
            "risk_ready", "strategy_ready", "capital_ready",
            "kill_switch_clear", "backup_restore_certified", "account_scope_verified",
        )
    }
    result = evaluate_authenticated_startup_candidate(
        "platform:kraken", external,
        pending_execution=False, posttrade_verified=False,
    )
    assert result["pretrade_candidate_ready"] is False
    assert result["activation_allowed"] is False
    assert "authenticated_pretrade_certificate" in result["missing"]


def test_incomplete_external_gate_rejects_certificate(monkeypatch):
    monkeypatch.setattr(attestation, "_COLLECTOR", None)
    external = {
        "risk_ready": True, "strategy_ready": True,
        "capital_ready": True, "kill_switch_clear": True,
        "account_scope_verified": True,
    }
    result = evaluate_authenticated_startup_candidate(
        "platform:kraken", external,
        pending_execution=False, posttrade_verified=False,
    )
    assert "backup_restore_certified" in result["missing"]
    assert result["activation_allowed"] is False
