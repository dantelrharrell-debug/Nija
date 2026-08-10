from __future__ import annotations

import time
from types import SimpleNamespace

from bot import kraken_all_account_supervision_v86 as v86


class _BrokerType:
    value = "kraken"


class _Broker:
    def __init__(self, *, connected: bool = False, configured: bool = True) -> None:
        self.connected = connected
        self.credentials_configured = configured
        self.connect_calls = 0

    def connect(self) -> bool:
        self.connect_calls += 1
        self.connected = True
        return True


def _clear_state() -> None:
    with v86._LOCK:
        v86._INFLIGHT.clear()
        v86._FAILURES.clear()
        v86._NEXT_RETRY.clear()


def test_records_include_disconnected_registered_users_without_duplicates() -> None:
    broker = _Broker()
    manager = SimpleNamespace(
        _all_user_brokers={("alice", _BrokerType): broker},
        user_brokers={"alice": {_BrokerType: broker}},
    )

    records = v86._user_records(manager)

    assert records == [("user:alice:kraken", "alice", _BrokerType, broker)]


def test_reconnect_uses_exact_writer_proof_and_canonical_connect(monkeypatch) -> None:
    _clear_state()
    broker = _Broker()
    user = SimpleNamespace(user_id="alice", broker_type="KRAKEN")
    resync_calls: list[object] = []
    manager = SimpleNamespace(
        user_brokers={},
        user_configs={"alice": user},
        _failed_user_connections={("alice", _BrokerType): "timeout"},
        _resync_single_user_kraken_nonce=lambda config: resync_calls.append(config),
    )
    monkeypatch.setattr(v86, "_writer_proof", lambda: (True, "exact"))

    v86._connect_account(manager, "user:alice:kraken", "alice", _BrokerType, broker)

    assert broker.connect_calls == 1
    assert broker.connected is True
    assert manager.user_brokers["alice"][_BrokerType] is broker
    assert manager._failed_user_connections == {}
    assert resync_calls == [user]


def test_reconnect_fails_closed_without_writer_proof(monkeypatch) -> None:
    _clear_state()
    broker = _Broker()
    manager = SimpleNamespace(
        user_brokers={}, user_configs={}, _failed_user_connections={}
    )
    monkeypatch.setattr(v86, "_writer_proof", lambda: (False, "metadata_stale"))

    v86._connect_account(manager, "user:alice:kraken", "alice", _BrokerType, broker)

    assert broker.connect_calls == 0
    assert broker.connected is False
    assert v86._NEXT_RETRY["user:alice:kraken"] > time.monotonic()


def test_missing_credentials_never_schedule_broker_io() -> None:
    _clear_state()
    broker = _Broker(configured=False)
    manager = SimpleNamespace(user_brokers={}, _failed_user_connections={})

    state = v86._schedule(
        manager,
        ("user:alice:kraken", "alice", _BrokerType, broker),
    )

    assert state == "credentials_not_configured"
    assert broker.connect_calls == 0
    assert v86._INFLIGHT == set()
