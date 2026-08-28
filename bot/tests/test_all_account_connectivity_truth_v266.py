from __future__ import annotations

from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch

from bot import all_account_connectivity_truth_v266_patch as v266


class _BrokerType:
    value = "kraken"


class _Broker:
    def __init__(self, connected: bool) -> None:
        self.connected = connected


class AllAccountConnectivityTruthV266Tests(unittest.TestCase):
    def setUp(self) -> None:
        with v266._LOCK:
            v266._PATCHED_V25_IDS.clear()
            v266._LAST_STATE_SIGNATURE = ""

    def tearDown(self) -> None:
        with v266._LOCK:
            v266._PATCHED_V25_IDS.clear()
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
        manager = SimpleNamespace(
            _platform_brokers={},
            _platform_failed_types=set(),
            _all_user_brokers={
                ("alice", _BrokerType): _Broker(True),
                ("bob", _BrokerType): _Broker(False),
            },
            user_brokers={"alice": {_BrokerType: _Broker(True)}},
            _user_metadata={
                "alice": {"brokers": {_BrokerType: True}},
                "bob": {"brokers": {_BrokerType: False}},
            },
            _failed_user_connections={("bob", _BrokerType): "auth_failed"},
            _users_without_credentials={("bob", _BrokerType): True},
            _capital_blocked_users={},
        )

        self.assertEqual(v266._registry_counts(manager), (1, 1))

    def test_pulse_delegates_to_existing_authenticated_v86_v90_path(self) -> None:
        manager = object()
        expected = {
            "ok": False,
            "reason": "recovery_active",
            "registered": 2,
            "connected": 1,
            "disconnected": 1,
            "states": {"user:bob:kraken": "reconnect_scheduled"},
        }
        with patch.object(v266.v86, "reconcile_once", return_value=expected) as reconcile:
            actual = v266._pulse_user_recovery(manager)

        self.assertEqual(actual, expected)
        reconcile.assert_called_once_with(manager)

    def test_live_broker_wrapper_pulses_user_recovery_and_preserves_platform_result(self) -> None:
        module = ModuleType("bot.live_broker_profit_exit_convergence_v25_test")
        manager = object()
        platform_result = {"kraken": True, "coinbase": True, "okx": True}
        calls = []

        module._manager = lambda: manager

        def original():
            calls.append("original")
            return platform_result

        module._reconcile_brokers_once = original
        recovery_state = {
            "ok": False,
            "reason": "recovery_active",
            "registered": 2,
            "connected": 1,
            "disconnected": 1,
            "states": {"user:bob:kraken": "backoff"},
        }

        with patch.object(v266, "_pulse_user_recovery", return_value=recovery_state) as pulse, patch.object(
            v266, "_emit_state"
        ) as emit:
            self.assertTrue(v266._patch_live_broker_reconciler(module))
            result = module._reconcile_brokers_once()

        self.assertIs(result, platform_result)
        self.assertEqual(calls, ["original"])
        pulse.assert_called_once_with(manager)
        emit.assert_called_once_with(manager, recovery_state, source="live_broker_reconcile")


if __name__ == "__main__":
    unittest.main()
