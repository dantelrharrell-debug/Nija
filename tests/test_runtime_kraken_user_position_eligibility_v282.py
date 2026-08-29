from __future__ import annotations

import time
from types import SimpleNamespace

from bot import kraken_all_account_supervision_v86 as v86
from bot import runtime_kraken_user_position_eligibility_v282_patch as v282
from bot import runtime_all_account_position_exit_coverage_v281_patch as v281


class _Broker:
    def __init__(self, *, connected=True, proof=True):
        self.connected = connected
        self._startup_position_sync_fetch_ok = True if proof else False
        self._startup_position_sync_adopted = True if proof else False
        self._startup_position_sync_symbols = tuple()
        self._startup_position_sync_error = None if proof else "position_snapshot_fail_closed"
        self._nija_kraken_local_read_busy_seq_v242 = 0


class _Manager:
    def __init__(self, broker):
        self._capital_blocked_users = {}
        self._user_metadata = {"u1": {"brokers": {"kraken": True}}}
        self.user_brokers = {"u1": {"kraken": broker}}
        self._all_user_brokers = {("u1", "kraken"): broker}
        self._failed_user_connections = {}
        self._users_without_credentials = {}


def _reset_state():
    v282._AUDIT_STATE.clear()
    v282._LAST_BLOCK_REASON.clear()
    v86._FAILURES.clear()
    v86._NEXT_RETRY.clear()


def test_false_runtime_metadata_does_not_disable_v281_account():
    assert v282._patch_v281_disabled_semantics() is True
    assert v281._explicitly_disabled(False) is False
    assert v281._explicitly_disabled({"enabled": False}) is True
    assert v281._explicitly_disabled({"enabled": True}) is False


def test_missing_authoritative_position_proof_blocks_only_user_account():
    _reset_state()
    broker = _Broker(proof=False)
    manager = _Manager(broker)

    v282._set_position_block(manager, "u1", "kraken", broker, "position_snapshot_fail_closed")

    assert manager._capital_blocked_users[("u1", "kraken")].startswith("position_sync_v282:")
    assert manager._user_metadata["u1"]["brokers"]["kraken"] is False
    assert broker.connected is True
    assert broker._nija_user_position_entry_blocked_v282 is True


def test_clear_only_removes_v282_owned_block():
    _reset_state()
    broker = _Broker()
    manager = _Manager(broker)
    key = ("u1", "kraken")

    manager._capital_blocked_users[key] = "auth_failure"
    v282._clear_owned_position_block(manager, "u1", "kraken", broker)
    assert manager._capital_blocked_users[key] == "auth_failure"

    manager._capital_blocked_users[key] = "position_sync_v282:stale"
    v282._clear_owned_position_block(manager, "u1", "kraken", broker)
    assert key not in manager._capital_blocked_users


def test_connected_schedule_inside_maintenance_window_performs_no_reaudit(monkeypatch):
    _reset_state()
    broker = _Broker()
    manager = _Manager(broker)
    calls = []

    def fake_mark_connected(*args):
        calls.append(args)

    monkeypatch.setattr(v86, "_mark_connected", fake_mark_connected)
    v282._AUDIT_STATE["user:u1:kraken"] = {
        "broker_id": id(broker),
        "audited": True,
        "position_ready": True,
        "reason": "ok",
        "next_audit_at": time.monotonic() + 30.0,
    }

    # Exercise the v282 schedule wrapper logic directly without depending on
    # whether another test already installed it on the module global.
    assert v282._patch_v86_schedule() is True
    state = v86._schedule(manager, ("user:u1:kraken", "u1", "kraken", broker))

    assert state == "connected"
    assert calls == []


def test_contention_during_post_connect_audit_fails_user_eligibility_closed(monkeypatch):
    _reset_state()
    broker = _Broker()
    manager = _Manager(broker)
    key = ("u1", "kraken")

    def legacy_reconcile(_manager, _user_id, _broker_type, _broker):
        _broker._nija_kraken_local_read_busy_seq_v242 += 1
        _manager._capital_blocked_users.pop(key, None)
        _manager._user_metadata["u1"]["brokers"]["kraken"] = True

    # Install a fresh wrapper around a controlled legacy surface.
    monkeypatch.setattr(v86, "_reconcile_post_connect", legacy_reconcile)
    assert v282._patch_v86_reconcile() is True
    v86._reconcile_post_connect(manager, "u1", "kraken", broker)

    assert manager._capital_blocked_users[key].startswith("position_sync_v282:local_read_contention")
    assert manager._user_metadata["u1"]["brokers"]["kraken"] is False
    assert broker.connected is True


def test_position_proof_requires_fetch_and_adoption():
    broker = _Broker(proof=True)
    assert v282._position_proof(broker)[0] is True

    broker._startup_position_sync_fetch_ok = False
    assert v282._position_proof(broker)[0] is False
    broker._startup_position_sync_fetch_ok = True
    broker._startup_position_sync_adopted = False
    assert v282._position_proof(broker)[0] is False


def test_v281_expected_accounts_keeps_false_metadata_user(monkeypatch):
    assert v282._patch_v281_disabled_semantics() is True
    broker = _Broker()
    manager = SimpleNamespace(
        _user_metadata={"u1": {"brokers": {"kraken": False}}},
        _platform_brokers={},
        _platform_failed_types=set(),
        _all_user_brokers={("u1", "kraken"): broker},
        user_brokers={"u1": {"kraken": broker}},
        _failed_user_connections={},
        _users_without_credentials={},
    )

    expected = v281._expected_accounts(manager)
    assert "user:u1:kraken" in expected
