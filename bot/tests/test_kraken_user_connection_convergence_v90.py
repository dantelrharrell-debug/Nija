from __future__ import annotations

import os
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from bot import kraken_all_account_supervision_v86 as v86
from bot import kraken_user_connection_convergence_v90_patch as v90


class _BrokerType:
    value = "kraken"


class _Broker:
    def __init__(self, *, connected: bool, configured: bool = True) -> None:
        self.connected = connected
        self.credentials_configured = configured


class KrakenUserConnectionConvergenceV90Tests(unittest.TestCase):
    def setUp(self) -> None:
        with v90._LOCK:
            v90._NEXT_REBUILD.clear()
            v90._REBUILD_FAILURES.clear()

    def tearDown(self) -> None:
        with v90._LOCK:
            v90._NEXT_REBUILD.clear()
            v90._REBUILD_FAILURES.clear()
        os.environ.pop("NIJA_KRAKEN_USER_CONNECTIONS_READY", None)

    def _manager(self):
        config = SimpleNamespace(user_id="alice")
        return SimpleNamespace(
            user_configs={"alice": config},
            user_brokers={},
            _all_user_brokers={},
            _failed_user_connections={("alice", _BrokerType): "startup_failed"},
            _users_without_credentials={},
            _capital_blocked_users={},
            _user_metadata={"alice": {"brokers": {_BrokerType: False}}},
            _audit_user_trading_capital=lambda *args: (True, {"usable_balance": 100.0}, ""),
        )

    def test_missing_broker_rebuilds_through_canonical_manager_and_requires_real_connection(self) -> None:
        manager = self._manager()
        broker = _Broker(connected=True)
        calls = []

        def add_user_broker(user_id, broker_type):
            calls.append((user_id, broker_type))
            manager._all_user_brokers[(user_id, broker_type)] = broker
            return broker

        manager.add_user_broker = add_user_broker
        with patch.object(v86, "_writer_proof", return_value=(True, "exact")):
            recovered, state = v90._recover_broker(
                manager,
                "user:alice:kraken",
                "alice",
                _BrokerType,
            )

        self.assertIs(recovered, broker)
        self.assertEqual(state, "connected")
        self.assertEqual(calls, [("alice", _BrokerType)])
        self.assertIs(manager.user_brokers["alice"][_BrokerType], broker)
        self.assertTrue(manager._user_metadata["alice"]["brokers"][_BrokerType])
        self.assertEqual(manager._failed_user_connections, {})

    def test_missing_broker_never_rebuilds_without_exact_writer_proof(self) -> None:
        manager = self._manager()
        manager.add_user_broker = lambda *_args: self.fail("broker IO must not run")

        with patch.object(v86, "_writer_proof", return_value=(False, "metadata_stale")):
            recovered, state = v90._recover_broker(
                manager,
                "user:alice:kraken",
                "alice",
                _BrokerType,
            )

        self.assertIsNone(recovered)
        self.assertEqual(state, "writer_proof_blocked:metadata_stale")
        self.assertGreater(v90._NEXT_REBUILD["user:alice:kraken"], time.monotonic())

    def test_rebuilt_broker_with_missing_credentials_remains_fail_closed(self) -> None:
        manager = self._manager()
        broker = _Broker(connected=False, configured=False)
        manager.add_user_broker = lambda *_args: broker

        with patch.object(v86, "_writer_proof", return_value=(True, "exact")):
            recovered, state = v90._recover_broker(
                manager,
                "user:alice:kraken",
                "alice",
                _BrokerType,
            )

        self.assertIs(recovered, broker)
        self.assertEqual(state, "credentials_not_configured")
        self.assertIn(("alice", _BrokerType), manager._users_without_credentials)
        self.assertFalse(manager._user_metadata["alice"]["brokers"][_BrokerType])

    def test_rebuilt_disconnected_broker_is_left_for_v86_serialized_reconnect(self) -> None:
        manager = self._manager()
        broker = _Broker(connected=False, configured=True)
        manager.add_user_broker = lambda *_args: broker

        with patch.object(v86, "_writer_proof", return_value=(True, "exact")):
            recovered, state = v90._recover_broker(
                manager,
                "user:alice:kraken",
                "alice",
                _BrokerType,
            )

        self.assertIs(recovered, broker)
        self.assertEqual(state, "broker_recovered_reconnect_pending")
        self.assertIn(("alice", _BrokerType), manager._failed_user_connections)
        self.assertGreater(v90._NEXT_REBUILD["user:alice:kraken"], time.monotonic())

    def test_schedule_reports_connected_only_after_authenticated_broker_truth(self) -> None:
        manager = self._manager()
        broker = _Broker(connected=True)
        manager.add_user_broker = lambda *_args: broker
        record = ("user:alice:kraken", "alice", _BrokerType, None)

        with patch.object(v86, "_writer_proof", return_value=(True, "exact")):
            state = v90._schedule_v90(manager, record)

        self.assertEqual(state, "connected")


if __name__ == "__main__":
    unittest.main()
