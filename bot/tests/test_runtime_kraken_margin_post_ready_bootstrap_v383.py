from bot import runtime_kraken_margin_protection_authority_v368_patch as v368


def test_post_ready_worker_bootstraps_native_and_user_proof_before_liveness(monkeypatch):
    events = []
    monkeypatch.setattr(v368, "_install_native_backup_v381", lambda: events.append("v381") or True)
    monkeypatch.setattr(v368, "_install_registered_user_proof_v379", lambda: events.append("v379") or True)
    monkeypatch.setattr(v368, "_install_v372", lambda: events.append("v372") or True)
    monkeypatch.setattr(v368, "_install_v373", lambda: events.append("v373") or True)
    monkeypatch.setattr(v368, "_wake_runtime", lambda: events.append("wake"))

    v368._post_ready_liveness_worker()

    assert events == ["v381", "v379", "v372", "v373", "wake"]


def test_native_bootstrap_failure_does_not_remove_existing_software_protection_path(monkeypatch):
    events = []
    monkeypatch.setattr(v368, "_install_native_backup_v381", lambda: events.append("v381") or False)
    monkeypatch.setattr(v368, "_install_registered_user_proof_v379", lambda: events.append("v379") or True)
    monkeypatch.setattr(v368, "_install_v372", lambda: events.append("v372") or False)
    monkeypatch.setattr(v368, "_wake_runtime", lambda: events.append("wake"))

    v368._post_ready_liveness_worker()

    assert events == ["v381", "v379", "v372", "wake"]
