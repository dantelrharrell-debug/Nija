from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import bot.nonce_lease_maturity_v155_patch as patch


class FakeManager:
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.calls = 0

    def get_writer_lease_status(self, key_id):
        index = min(self.calls, len(self.statuses) - 1)
        self.calls += 1
        return dict(self.statuses[index])


def _install_fakes(monkeypatch, manager):
    nonce_mod = ModuleType("bot.distributed_nonce_manager")
    nonce_mod.get_distributed_nonce_manager = lambda: manager
    nonce_mod.make_api_key_id = lambda key: "key-id"
    auth_mod = ModuleType("bot.execution_authority_context")
    auth_mod.assert_startup_write_authority = lambda: None
    monkeypatch.setitem(sys.modules, "bot.distributed_nonce_manager", nonce_mod)
    monkeypatch.setitem(sys.modules, "bot.execution_authority_context", auth_mod)
    monkeypatch.setenv("KRAKEN_PLATFORM_API_KEY", "test-key")
    monkeypatch.setenv("NIJA_NONCE_LEASE_FINAL_VERIFY_MAX_WAIT_S", "2.0")
    monkeypatch.setattr(patch.time, "sleep", lambda seconds: None)


def test_same_owner_token_can_finish_maturing(monkeypatch):
    manager = FakeManager([
        {"enabled": True, "token": "2137", "owner_instance": "srv-a", "stable_for_s": 29.4},
        {"enabled": True, "token": "2137", "owner_instance": "srv-a", "stable_for_s": 30.1},
    ])
    _install_fakes(monkeypatch, manager)
    tsm = SimpleNamespace(_nonce_lease_stability_requirement_s=lambda: 30.0)

    ok, err = patch._final_same_lease_maturity_check(tsm, "nonce lease unstable (stable_for=29.4s)")

    assert ok is True
    assert err == ""


def test_token_change_remains_fail_closed(monkeypatch):
    manager = FakeManager([
        {"enabled": True, "token": "2137", "owner_instance": "srv-a", "stable_for_s": 29.7},
        {"enabled": True, "token": "2138", "owner_instance": "srv-a", "stable_for_s": 30.2},
    ])
    _install_fakes(monkeypatch, manager)
    tsm = SimpleNamespace(_nonce_lease_stability_requirement_s=lambda: 30.0)

    ok, err = patch._final_same_lease_maturity_check(tsm, "nonce lease unstable")

    assert ok is False
    assert "lease_identity_changed" in err


def test_owner_change_remains_fail_closed(monkeypatch):
    manager = FakeManager([
        {"enabled": True, "token": "2137", "owner_instance": "srv-a", "stable_for_s": 29.7},
        {"enabled": True, "token": "2137", "owner_instance": "srv-b", "stable_for_s": 30.2},
    ])
    _install_fakes(monkeypatch, manager)
    tsm = SimpleNamespace(_nonce_lease_stability_requirement_s=lambda: 30.0)

    ok, err = patch._final_same_lease_maturity_check(tsm, "nonce lease unstable")

    assert ok is False
    assert "lease_identity_changed" in err


def test_stability_regression_remains_fail_closed(monkeypatch):
    manager = FakeManager([
        {"enabled": True, "token": "2137", "owner_instance": "srv-a", "stable_for_s": 29.7},
        {"enabled": True, "token": "2137", "owner_instance": "srv-a", "stable_for_s": 29.0},
    ])
    _install_fakes(monkeypatch, manager)
    tsm = SimpleNamespace(_nonce_lease_stability_requirement_s=lambda: 30.0)

    ok, err = patch._final_same_lease_maturity_check(tsm, "nonce lease unstable")

    assert ok is False
    assert "stability_regressed" in err


def test_large_remaining_gap_is_not_waited_through(monkeypatch):
    manager = FakeManager([
        {"enabled": True, "token": "2137", "owner_instance": "srv-a", "stable_for_s": 25.0},
    ])
    _install_fakes(monkeypatch, manager)
    tsm = SimpleNamespace(_nonce_lease_stability_requirement_s=lambda: 30.0)

    ok, err = patch._final_same_lease_maturity_check(tsm, "nonce lease unstable")

    assert ok is False
    assert "remaining_exceeds_cap" in err
