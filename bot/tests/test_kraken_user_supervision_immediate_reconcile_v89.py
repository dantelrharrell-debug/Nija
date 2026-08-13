from __future__ import annotations

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


class KrakenUserSupervisionImmediateReconcileV89Tests(unittest.TestCase):
    def setUp(self) -> None:
        with v86._LOCK:
            v86._INFLIGHT.clear()
            v86._FAILURES.clear()
            v86._NEXT_RETRY.clear()

    def tearDown(self) -> None:
        with v86._LOCK:
            v86._INFLIGHT.clear()
            v86._FAILURES.clear()
            v86._NEXT_RETRY.clear()

    def test_reconcile_schedules_registered_disconnected_user_immediately(self) -> None:
        broker = _Broker()
        manager = SimpleNamespace(
            _all_user_brokers={("alice", _BrokerType): broker},
            user_brokers={},
            user_configs={"alice": SimpleNamespace(user_id="alice")},
            _failed_user_connections={},
            _users_without_credentials={},
            _capital_blocked_users={},
            _user_metadata={"alice": {"brokers": {_BrokerType: False}}},
            _resync_single_user_kraken_nonce=lambda _config: None,
            _audit_user_trading_capital=lambda *args: (True, {"usable_balance": 100.0}, ""),
        )

        with patch.object(v86, "_writer_proof", return_value=(True, "exact")):
            state = v86.reconcile_once(manager)
            self.assertEqual(state["registered"], 1)
            self.assertIn(
                state["states"]["user:alice:kraken"],
                {"reconnect_scheduled", "reconnect_inflight", "connected"},
            )

    def test_reconcile_never_schedules_missing_credentials(self) -> None:
        broker = _Broker(configured=False)
        manager = SimpleNamespace(
            _all_user_brokers={("alice", _BrokerType): broker},
            user_brokers={},
            _failed_user_connections={},
            _users_without_credentials={("alice", _BrokerType): True},
            _user_metadata={"alice": {"brokers": {_BrokerType: False}}},
        )

        state = v86.reconcile_once(manager)

        self.assertEqual(state["registered"], 1)
        self.assertEqual(state["connected"], 0)
        self.assertEqual(
            state["states"]["user:alice:kraken"],
            "credentials_not_configured",
        )
        self.assertEqual(broker.connect_calls, 0)

    def test_reconcile_remains_fail_closed_without_writer_proof(self) -> None:
        broker = _Broker()
        manager = SimpleNamespace(
            _all_user_brokers={("alice", _BrokerType): broker},
            user_brokers={},
            user_configs={"alice": SimpleNamespace(user_id="alice")},
            _failed_user_connections={},
            _users_without_credentials={},
            _user_metadata={"alice": {"brokers": {_BrokerType: False}}},
        )

        with patch.object(v86, "_writer_proof", return_value=(False, "metadata_stale")):
            state = v86.reconcile_once(manager)

        self.assertEqual(state["registered"], 1)
        self.assertEqual(state["connected"], 0)
        self.assertEqual(broker.connect_calls, 0)
