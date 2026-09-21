from types import SimpleNamespace

from bot import runtime_all_account_broker_identity_convergence_v374_patch as v374


def _stub_audit_import(monkeypatch):
    monkeypatch.setattr(
        v374.importlib,
        "import_module",
        lambda name: SimpleNamespace(audit_once=lambda: None),
    )


def test_auxiliary_protection_monitors_start_before_v375(monkeypatch):
    events = []
    _stub_audit_import(monkeypatch)

    monkeypatch.setattr(v374, "_install_v289", lambda: events.append("v289") or True)
    monkeypatch.setattr(v374, "_patch_v281", lambda: events.append("identity") or True)
    monkeypatch.setattr(v374, "_install_v377", lambda: events.append("v377") or True)
    monkeypatch.setattr(v374, "_install_v381", lambda: events.append("v381") or True)
    monkeypatch.setattr(v374, "_install_v379", lambda: events.append("v379") or True)
    monkeypatch.setattr(v374, "_install_v375", lambda: events.append("v375") or True)
    monkeypatch.setattr(v374, "_install_v390", lambda: events.append("v390") or True)
    monkeypatch.setattr(v374, "_install_v376", lambda: events.append("v376") or True)

    assert v374.install_import_hook() is True
    assert events == ["v289", "identity", "v377", "v381", "v379", "v375", "v390", "v376"]


def test_v375_failure_does_not_prevent_native_or_user_monitor_bootstrap(monkeypatch):
    events = []
    _stub_audit_import(monkeypatch)

    monkeypatch.setattr(v374, "_install_v289", lambda: events.append("v289") or True)
    monkeypatch.setattr(v374, "_patch_v281", lambda: events.append("identity") or True)
    monkeypatch.setattr(v374, "_install_v377", lambda: events.append("v377") or True)
    monkeypatch.setattr(v374, "_install_v381", lambda: events.append("v381") or True)
    monkeypatch.setattr(v374, "_install_v379", lambda: events.append("v379") or True)
    monkeypatch.setattr(v374, "_install_v375", lambda: events.append("v375") or False)
    monkeypatch.setattr(v374, "_install_v390", lambda: events.append("v390") or True)
    monkeypatch.setattr(v374, "_install_v376", lambda: events.append("v376") or True)

    assert v374.install_import_hook() is False
    assert events == ["v289", "identity", "v377", "v381", "v379", "v375"]
    assert "v390" not in events
    assert "v376" not in events


def test_v390_failure_blocks_scope_promotion_but_preserves_existing_exits(monkeypatch):
    events = []
    _stub_audit_import(monkeypatch)

    monkeypatch.setattr(v374, "_install_v289", lambda: events.append("v289") or True)
    monkeypatch.setattr(v374, "_patch_v281", lambda: events.append("identity") or True)
    monkeypatch.setattr(v374, "_install_v377", lambda: events.append("v377") or True)
    monkeypatch.setattr(v374, "_install_v381", lambda: events.append("v381") or True)
    monkeypatch.setattr(v374, "_install_v379", lambda: events.append("v379") or True)
    monkeypatch.setattr(v374, "_install_v375", lambda: events.append("v375") or True)
    monkeypatch.setattr(v374, "_install_v390", lambda: events.append("v390") or False)
    monkeypatch.setattr(v374, "_install_v376", lambda: events.append("v376") or True)

    assert v374.install_import_hook() is False
    assert events == ["v289", "identity", "v377", "v381", "v379", "v375", "v390"]
    assert "v376" not in events


def test_v281_prefers_connected_v86_supervised_user_broker_over_retired_snapshot(monkeypatch):
    retired = SimpleNamespace(
        connected=True,
        _startup_position_sync_fetch_ok=True,
        _startup_position_sync_adopted=True,
        _nija_authoritative_position_snapshot_fetch_ok_v285=True,
        _nija_authoritative_position_snapshot_rows_v285=(),
        _nija_authoritative_position_snapshot_at_monotonic_v285=v374.time.monotonic(),
        _nija_authoritative_position_snapshot_generation_v285=9,
    )
    current = SimpleNamespace(
        connected=True,
        _startup_position_sync_fetch_ok=False,
        _startup_position_sync_adopted=False,
    )
    manager = SimpleNamespace()

    fake_v281 = SimpleNamespace(
        _expected_accounts=lambda _manager: {"user:u1:kraken": retired},
    )

    monkeypatch.setattr(
        v374.importlib,
        "import_module",
        lambda name: fake_v281
        if name == "bot.runtime_all_account_position_exit_coverage_v281_patch"
        else SimpleNamespace(),
    )
    monkeypatch.setattr(
        v374,
        "_candidate_user_brokers",
        lambda _manager: {"user:u1:kraken": [retired, current]},
    )
    monkeypatch.setattr(
        v374,
        "_supervised_user_brokers",
        lambda _manager: {"user:u1:kraken": current},
    )

    assert v374._patch_v281() is True
    expected = fake_v281._expected_accounts(manager)
    assert expected["user:u1:kraken"] is current
    # Identity convergence must not copy readiness from the retired object.
    assert getattr(current, "_startup_position_sync_fetch_ok", None) is False
    assert not hasattr(current, "_nija_authoritative_position_snapshot_rows_v285")
