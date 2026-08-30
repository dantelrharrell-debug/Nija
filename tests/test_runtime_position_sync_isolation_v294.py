from __future__ import annotations

from types import SimpleNamespace

from bot import position_sync_core_handoff_v95_patch as v95
from bot import runtime_position_sync_isolation_v294_patch as v294


def _install_controlled(monkeypatch, status):
    def controlled(_manager):
        pending = sorted(name for name, ready in status.items() if not ready)
        return not pending, pending, dict(status)

    monkeypatch.setattr(v95, "position_sync_status", controlled)
    assert v294._patch_v95_status() is True
    return v95.position_sync_status


def test_user_local_failure_does_not_revoke_platform_readiness(monkeypatch):
    wrapped = _install_controlled(monkeypatch, {
        "platform:kraken": True,
        "platform:coinbase": True,
        "platform:okx": True,
        "user:tania_gilbert:kraken": False,
    })

    ready, pending, status = wrapped(SimpleNamespace())

    assert ready is True
    assert pending == []
    assert status == {
        "platform:kraken": True,
        "platform:coinbase": True,
        "platform:okx": True,
    }


def test_unready_platform_broker_still_blocks_canonical_activation(monkeypatch):
    wrapped = _install_controlled(monkeypatch, {
        "platform:kraken": False,
        "platform:coinbase": True,
        "platform:okx": True,
        "user:tania_gilbert:kraken": True,
    })

    ready, pending, status = wrapped(SimpleNamespace())

    assert ready is False
    assert pending == ["platform:kraken"]
    assert status["platform:kraken"] is False


def test_missing_platform_set_remains_fail_closed(monkeypatch):
    wrapped = _install_controlled(monkeypatch, {
        "user:daivon_frazier:kraken": True,
        "user:tania_gilbert:kraken": True,
    })

    ready, pending, status = wrapped(SimpleNamespace())

    assert ready is False
    assert pending == []
    assert status == {}


def test_wrapper_is_read_only_with_respect_to_manager_account_metadata(monkeypatch):
    manager = SimpleNamespace(
        _capital_blocked_users={("tania_gilbert", "kraken"): "position_sync_v282:pending"},
        _user_metadata={"tania_gilbert": {"brokers": {"kraken": False}}},
    )
    before_blocks = dict(manager._capital_blocked_users)
    before_metadata = {
        user: {"brokers": dict(data["brokers"])}
        for user, data in manager._user_metadata.items()
    }
    wrapped = _install_controlled(monkeypatch, {
        "platform:kraken": True,
        "platform:coinbase": True,
        "platform:okx": True,
        "user:tania_gilbert:kraken": False,
    })

    wrapped(manager)

    assert manager._capital_blocked_users == before_blocks
    assert manager._user_metadata == before_metadata
