from __future__ import annotations

from types import SimpleNamespace

from bot import runtime_account_scoped_reconciliation_truth_v292_patch as v292


def test_certificate_requires_current_generation(monkeypatch):
    tracker = SimpleNamespace()
    broker = SimpleNamespace(position_tracker=tracker)
    monkeypatch.setattr(v292, "_binding", lambda value: (True, "platform__coinbase", "ok"))
    monkeypatch.setattr(v292, "_snapshot", lambda value: (True, 7, "ok"))
    v292._CERTS["platform:coinbase"] = (id(broker), id(tracker), "platform__coinbase", 7)
    assert v292._current("platform:coinbase", broker)[0] is True
    monkeypatch.setattr(v292, "_snapshot", lambda value: (True, 8, "ok"))
    ready, reason = v292._current("platform:coinbase", broker)
    assert ready is False
    assert "snapshot_generation_changed" in reason


def test_certificate_rejects_tracker_identity_change(monkeypatch):
    tracker = SimpleNamespace()
    broker = SimpleNamespace(position_tracker=tracker)
    monkeypatch.setattr(v292, "_binding", lambda value: (True, "user__test__kraken", "ok"))
    monkeypatch.setattr(v292, "_snapshot", lambda value: (True, 3, "ok"))
    v292._CERTS["user:test:kraken"] = (id(broker), id(tracker), "user__test__kraken", 3)
    broker.position_tracker = SimpleNamespace()
    ready, reason = v292._current("user:test:kraken", broker)
    assert ready is False
    assert reason == "broker_or_tracker_identity_changed"


def test_certify_requires_authoritative_cleanup(monkeypatch):
    tracker = SimpleNamespace()
    broker = SimpleNamespace(position_tracker=tracker)
    monkeypatch.setattr(v292, "_binding", lambda value: (True, "platform__okx", "ok"))
    monkeypatch.setattr(v292, "_snapshot", lambda value: (True, 11, "ok"))
    fake_v289 = SimpleNamespace(_clean_authoritative_orphans=lambda value, scope: (0, "stale_position_snapshot"))
    monkeypatch.setattr(v292, "_mods", lambda: (SimpleNamespace(), SimpleNamespace(), fake_v289))
    ready, reason = v292._certify("platform:okx", broker, set())
    assert ready is False
    assert reason == "stale_position_snapshot"


def test_v281_wrapper_clears_protective_verification_without_certificate(monkeypatch):
    def original(account, broker, structural):
        return [], [{"account": account, "symbol": "BTC-USD", "protective_exit_verified": True, "exit_protections_attached": ("stop_loss",)}]

    fake_v281 = SimpleNamespace(_account_audit=original)
    monkeypatch.setattr(v292, "_mods", lambda: (fake_v281, SimpleNamespace(), SimpleNamespace()))
    monkeypatch.setattr(v292, "_current", lambda account, broker: (False, "certificate_missing"))
    assert v292._patch_v281() is True
    reasons, positions = fake_v281._account_audit("platform:coinbase", SimpleNamespace(), True)
    assert "account_scoped_reconciliation_uncertified:certificate_missing" in reasons
    assert positions[0]["protective_exit_verified"] is False
    assert positions[0]["exit_protections_attached"] == ()
