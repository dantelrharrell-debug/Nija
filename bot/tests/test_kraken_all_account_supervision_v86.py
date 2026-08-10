from __future__ import annotations

import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

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


class KrakenAllAccountSupervisionV86Tests(unittest.TestCase):
    def setUp(self) -> None:
        _clear_state()

    def tearDown(self) -> None:
        _clear_state()

    def test_records_include_disconnected_registered_users_without_duplicates(self) -> None:
        broker = _Broker()
        manager = SimpleNamespace(
            _all_user_brokers={("alice", _BrokerType): broker},
            user_brokers={"alice": {_BrokerType: broker}},
        )

        records = v86._user_records(manager)

        self.assertEqual(
            records,
            [("user:alice:kraken", "alice", _BrokerType, broker)],
        )

    def test_records_include_failed_users_without_broker_objects(self) -> None:
        manager = SimpleNamespace(
            _all_user_brokers={},
            user_brokers={},
            _user_metadata={
                "alice": {"brokers": {_BrokerType: False}},
            },
            _failed_user_connections={
                ("alice", _BrokerType): "broker_creation_failed",
            },
            _users_without_credentials={},
        )

        records = v86._user_records(manager)
        state = v86.reconcile_once(manager)

        self.assertEqual(
            records,
            [("user:alice:kraken", "alice", _BrokerType, None)],
        )
        self.assertEqual(state["registered"], 1)
        self.assertEqual(state["connected"], 0)
        self.assertEqual(state["states"]["user:alice:kraken"], "broker_unavailable")
        self.assertEqual(state["reason"], "recovery_active")

    def test_reconnect_uses_exact_writer_proof_and_canonical_connect(self) -> None:
        broker = _Broker()
        user = SimpleNamespace(user_id="alice", broker_type="KRAKEN")
        resync_calls: list[object] = []
        manager = SimpleNamespace(
            user_brokers={},
            user_configs={"alice": user},
            _failed_user_connections={("alice", _BrokerType): "timeout"},
            _resync_single_user_kraken_nonce=lambda config: resync_calls.append(config),
        )
        with patch.object(v86, "_writer_proof", return_value=(True, "exact")):
            v86._connect_account(
                manager,
                "user:alice:kraken",
                "alice",
                _BrokerType,
                broker,
            )

        self.assertEqual(broker.connect_calls, 1)
        self.assertTrue(broker.connected)
        self.assertIs(manager.user_brokers["alice"][_BrokerType], broker)
        self.assertEqual(manager._failed_user_connections, {})
        self.assertEqual(resync_calls, [user])

    def test_reconnect_fails_closed_without_writer_proof(self) -> None:
        broker = _Broker()
        manager = SimpleNamespace(
            user_brokers={}, user_configs={}, _failed_user_connections={}
        )
        with patch.object(
            v86,
            "_writer_proof",
            return_value=(False, "metadata_stale"),
        ):
            v86._connect_account(
                manager,
                "user:alice:kraken",
                "alice",
                _BrokerType,
                broker,
            )

        self.assertEqual(broker.connect_calls, 0)
        self.assertFalse(broker.connected)
        self.assertGreater(v86._NEXT_RETRY["user:alice:kraken"], time.monotonic())

    def test_missing_credentials_never_schedule_broker_io(self) -> None:
        broker = _Broker(configured=False)
        manager = SimpleNamespace(user_brokers={}, _failed_user_connections={})

        state = v86._schedule(
            manager,
            ("user:alice:kraken", "alice", _BrokerType, broker),
        )

        self.assertEqual(state, "credentials_not_configured")
        self.assertEqual(broker.connect_calls, 0)
        self.assertEqual(v86._INFLIGHT, set())

    def test_missing_broker_object_never_schedules_broker_io(self) -> None:
        manager = SimpleNamespace(
            user_brokers={},
            _failed_user_connections={("alice", _BrokerType): "create_failed"},
            _users_without_credentials={},
        )

        state = v86._schedule(
            manager,
            ("user:alice:kraken", "alice", _BrokerType, None),
        )

        self.assertEqual(state, "broker_unavailable")
        self.assertEqual(v86._INFLIGHT, set())
