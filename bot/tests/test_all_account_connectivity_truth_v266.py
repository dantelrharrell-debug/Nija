from __future__ import annotations

import os
import sys
from types import ModuleType, SimpleNamespace
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
        self._original_reconcile = v266.v86.reconcile_once
        self._original_installed = v266._INSTALLED
        self._original_manager_module = sys.modules.get("bot.multi_account_broker_manager")
        self._original_env = os.environ.get("NIJA_ALL_ACCOUNT_CONNECTIVITY_TRUTH_V266_INSTALLED")
        with v266._LOCK:
            v266._LAST_STATE_SIGNATURE = ""
            v266._ORIGINAL_V86_RECONCILE = None

    def tearDown(self) -> None:
        v266.v86.reconcile_once = self._original_reconcile
        v266._INSTALLED = self._original_installed
        if self._original_manager_module is None:
            sys.modules.pop("bot.multi_account_broker_manager", None)
        else:
            sys.modules["bot.multi_account_broker_manager"] = self._original_manager_module
        if self._original_env is None:
            os.environ.pop("NIJA_ALL_ACCOUNT_CONNECTIVITY_TRUTH_V266_INSTALLED", None)
        else:
            os.environ["NIJA_ALL_ACCOUNT_CONNECTIVITY_TRUTH_V266_INSTALLED"] = self._original_env
        with v266._LOCK:
            v266._LAST_STATE_SIGNATURE = ""
            v266._ORIGINAL_V86_RECONCILE = None

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

    def test_state_signature_handles_non_mapping_state_truthfully(self) -> None:
        signature = v266._state_signature(None, 0, 0)  # type: ignore[arg-type]
        self.assertIn("invalid_state", signature)

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

    def test_registry_counts_none_is_empty(self) -> None:
        self.assertEqual(v266._registry_counts(None), (0, 0))

    def test_registry_counts_fallback_preserves_private_failure_sets(self) -> None:
        manager = SimpleNamespace(
            _failed_user_connections={"a": "auth_failed", "b": "connect_failed"},
            _users_without_credentials={"c": True},
        )
        with patch("bot.account_registry_snapshot.build_account_registry_snapshot", side_effect=RuntimeError("boom")):
            self.assertEqual(v266._registry_counts(manager), (2, 1))

    def test_canonical_manager_uses_getter(self) -> None:
        manager = object()
        module = ModuleType("bot.multi_account_broker_manager")
        module.get_broker_manager = lambda: manager  # type: ignore[attr-defined]
        sys.modules["bot.multi_account_broker_manager"] = module
        self.assertIs(v266._canonical_manager(), manager)

    def test_canonical_manager_getter_failure_is_fail_closed(self) -> None:
        module = ModuleType("bot.multi_account_broker_manager")

        def _raise():
            raise RuntimeError("unavailable")

        module.get_broker_manager = _raise  # type: ignore[attr-defined]
        sys.modules["bot.multi_account_broker_manager"] = module
        self.assertIsNone(v266._canonical_manager())

    def test_canonical_manager_uses_legacy_attribute_when_getter_absent(self) -> None:
        manager = object()
        module = ModuleType("bot.multi_account_broker_manager")
        module.multi_account_broker_manager = manager  # type: ignore[attr-defined]
        sys.modules["bot.multi_account_broker_manager"] = module
        self.assertIs(v266._canonical_manager(), manager)

    def test_emit_state_logs_only_when_state_sensitive_signature_changes(self) -> None:
        state = {
            "ok": False,
            "reason": "recovery_active",
            "registered": 2,
            "connected": 1,
            "disconnected": 1,
            "states": {"user:bob:kraken": "backoff"},
        }
        with patch.object(v266, "_registry_counts", return_value=(1, 0)), patch.object(v266.LOGGER, "warning") as warning:
            v266._emit_state(object(), state, source="test")
            v266._emit_state(object(), state, source="test")

        warning.assert_called_once()

    def test_emit_state_uses_critical_for_fully_ready_state(self) -> None:
        state = {
            "ok": True,
            "reason": "all_connected",
            "registered": 2,
            "connected": 2,
            "disconnected": 0,
            "states": {
                "user:alice:kraken": "connected",
                "user:bob:kraken": "connected",
            },
        }
        with patch.object(v266, "_registry_counts", return_value=(0, 0)), patch.object(v266.LOGGER, "critical") as critical:
            v266._emit_state(object(), state, source="test")

        critical.assert_called_once()

    def test_patch_rejects_non_callable_reconcile(self) -> None:
        with patch.object(v266.v86, "reconcile_once", None):
            self.assertFalse(v266._patch_v86_reconcile())

    def test_patch_is_idempotent_when_already_wrapped(self) -> None:
        def already_wrapped(manager=None):
            return {"ok": True}

        setattr(already_wrapped, "_nija_v266_connectivity_truth", True)
        with patch.object(v266.v86, "reconcile_once", already_wrapped):
            self.assertTrue(v266._patch_v86_reconcile())
            self.assertIs(v266.v86.reconcile_once, already_wrapped)

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

    def test_wrapper_resolves_canonical_manager_only_when_caller_omits_manager(self) -> None:
        manager = object()
        expected = {"ok": True, "registered": 1, "connected": 1, "disconnected": 0, "states": {}}
        original = Mock(return_value=expected)
        with patch.object(v266.v86, "reconcile_once", original), patch.object(
            v266, "_canonical_manager", return_value=manager
        ) as canonical, patch.object(v266, "_emit_state") as emit:
            self.assertTrue(v266._patch_v86_reconcile())
            actual = v266.v86.reconcile_once()

        self.assertIs(actual, expected)
        original.assert_called_once_with(None)
        canonical.assert_called_once_with()
        emit.assert_called_once_with(manager, expected, source="v86_reconcile")

    def test_wrapper_does_not_emit_for_non_dict_result(self) -> None:
        original = Mock(return_value=None)
        with patch.object(v266.v86, "reconcile_once", original), patch.object(v266, "_emit_state") as emit:
            self.assertTrue(v266._patch_v86_reconcile())
            self.assertIsNone(v266.v86.reconcile_once(object()))
        emit.assert_not_called()

    def test_install_import_hook_sets_marker_without_changing_recovery_policy(self) -> None:
        os.environ.pop("NIJA_ALL_ACCOUNT_CONNECTIVITY_TRUTH_V266_INSTALLED", None)
        with patch.object(v266, "_patch_v86_reconcile", return_value=True), patch.object(v266.LOGGER, "critical") as critical:
            self.assertTrue(v266.install_import_hook())

        self.assertTrue(v266._INSTALLED)
        self.assertEqual(os.environ.get("NIJA_ALL_ACCOUNT_CONNECTIVITY_TRUTH_V266_INSTALLED"), "1")
        critical.assert_called_once()

    def test_install_import_hook_failure_does_not_claim_installed_env_marker(self) -> None:
        os.environ.pop("NIJA_ALL_ACCOUNT_CONNECTIVITY_TRUTH_V266_INSTALLED", None)
        with patch.object(v266, "_patch_v86_reconcile", return_value=False), patch.object(v266.LOGGER, "critical"):
            self.assertFalse(v266.install_import_hook())

        self.assertFalse(v266._INSTALLED)
        self.assertNotIn("NIJA_ALL_ACCOUNT_CONNECTIVITY_TRUTH_V266_INSTALLED", os.environ)

    def test_install_alias_delegates_to_import_hook(self) -> None:
        with patch.object(v266, "install_import_hook", return_value=True) as install_hook:
            self.assertTrue(v266.install())
        install_hook.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
