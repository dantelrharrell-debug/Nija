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
    monkeypatch.setattr(v374, "_install_v376", lambda: events.append("v376") or True)

    assert v374.install_import_hook() is True
    assert events == ["v289", "identity", "v377", "v381", "v379", "v375", "v376"]


def test_v375_failure_does_not_prevent_native_or_user_monitor_bootstrap(monkeypatch):
    events = []
    _stub_audit_import(monkeypatch)

    monkeypatch.setattr(v374, "_install_v289", lambda: events.append("v289") or True)
    monkeypatch.setattr(v374, "_patch_v281", lambda: events.append("identity") or True)
    monkeypatch.setattr(v374, "_install_v377", lambda: events.append("v377") or True)
    monkeypatch.setattr(v374, "_install_v381", lambda: events.append("v381") or True)
    monkeypatch.setattr(v374, "_install_v379", lambda: events.append("v379") or True)
    monkeypatch.setattr(v374, "_install_v375", lambda: events.append("v375") or False)
    monkeypatch.setattr(v374, "_install_v376", lambda: events.append("v376") or True)

    assert v374.install_import_hook() is False
    assert events == ["v289", "identity", "v377", "v381", "v379", "v375"]
    assert "v376" not in events
