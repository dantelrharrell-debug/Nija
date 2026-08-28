from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from bot import all_account_connectivity_truth_v266_patch as v266


class _BrokerType:
    value = "kraken"


class _Broker:
    def __init__(self, connected: bool) -> None:
        self.connected = connected


class AllAccountConnectivityTruthV266Tests(unittest.TestCase):
    def setUp(self) -> None:
        with v266._LOCK:
            v266._LAST_STATE_SIGNATURE = ""

    def tearDown(self) -> None:
        with v266._LOCK:
            v266._LAST_STATE_SIGNATURE = ""

    def test_state_signature_changes_when_per_account_recovery_state_changes(self) -> None:
        first = {
            "ok": False,
            "reason": "recovery_active",
            "registered": 2,
            "connected": 1,
            "disconnected": 1,
            "states": {
                "user:alice:kraken": "connected",
                "user:bob:kraken": "backoff",
            },
        }
        second = dict(first)
        second["states"] = {
            "user:alice:kraken": "connected",
            "user:bob:kraken": "credentials_not_configured",
        }

        self.assertNotEqual(
            v266._state_signature(first, 1, 0),
            v266._state_signature(second, 1, 1),
        )

    def test_registry_counts_preserve_failed_and_missing_user_truth(self) -> None:
        connected = _Broker(True)
        disconnected = _Broker(False)
        manager = SimpleNamespace(
            _platform_brokers={},
            _platform_failed_types=set(),
            _all_user_brokers={
                ("alice", _BrokerType): connected,
                ("bob", _BrokerType): disconnected,
            },
            user_brokers={"alice": {_BrokerType: connected}},
            _user_metadata={
                "alice": {"brokers": {_BrokerType: True}},
                "bob": {"brokers": {_BrokerType: False}},
            },
            _failed_user_connections={("bob", _BrokerType): "auth_failed"},
            _users_without_credentials={("bob", _BrokerType): True},
            _capital_blocked_users={},
        )

        self.assertEqual(v266._registry_counts(manager), (1, 1))

    def test_wrapper_observes_existing_reconcile_without_extra_call_or_state_mutation(self) -> None:
        manager = object()
        expected = {
            "ok": False,
            "reason": "recovery_active",
            "registered": 2,
            "connected": 1,
            "disconnected": 1,
            "states": {
                "user:alice:kraken": "connected",
                "user:bob:kraken": "backoff",
            },
        }
        original = Mock(return_value=expected)

        with patch.object(v266.v86, "reconcile_once", original), patch.object(v266, "_emit_state") as emit:
            self.assertTrue(v266._patch_v86_reconcile())
            wrapped = v266.v86.reconcile_once
            actual = wrapped(manager)

        self.assertIs(actual, expected)
        original.assert_called_once_with(manager)
        emit.assert_called_once_with(manager, expected, source="v86_reconcile")
        self.assertTrue(getattr(wrapped, "_nija_v266_connectivity_truth", False))


if __name__ == "__main__":
    unittest.main()
