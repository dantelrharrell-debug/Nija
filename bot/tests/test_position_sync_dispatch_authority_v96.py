from __future__ import annotations

import builtins
import os
import types
import unittest
from unittest import mock

from bot import position_sync_dispatch_authority_v96_patch as v96


class PositionSyncDispatchAuthorityV96Tests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("NIJA_POSITION_SYNC_ACTIVATION_READY", None)
        os.environ.pop("NIJA_POSITION_SYNC_DISPATCH_READY", None)
        os.environ.pop("NIJA_POSITION_SYNC_INSTALL_REPLAY_V188_READY", None)
        os.environ.pop("NIJA_POSITION_SYNC_INSTALLER_IDEMPOTENCE_V195_READY", None)
        for attr in (v96._INITIAL_FAIL_CLOSED_FLAG, v96._HOOK_FLAG):
            if hasattr(builtins, attr):
                delattr(builtins, attr)

    def test_publish_is_fail_closed_without_connected_brokers(self) -> None:
        calls = []
        readiness = types.SimpleNamespace(
            set_ready=lambda key, value, allow_regression=False: calls.append(
                (key, value, allow_regression)
            )
        )
        v95 = types.SimpleNamespace(position_sync_status=lambda manager: (True, [], {}))
        with mock.patch.object(v96, "_readiness_module", return_value=readiness), mock.patch.object(
            v96, "_v95_module", return_value=v95
        ):
            ready, pending, status = v96.publish_position_sync_readiness(
                object(), source="test"
            )

        self.assertFalse(ready)
        self.assertEqual(pending, [])
        self.assertEqual(status, {})
        self.assertEqual(calls, [(v96.READINESS_KEY, False, True)])
        self.assertEqual(os.environ["NIJA_POSITION_SYNC_DISPATCH_READY"], "0")

    def test_publish_tracks_all_connected_broker_truth_and_regression(self) -> None:
        calls = []
        readiness = types.SimpleNamespace(
            set_ready=lambda key, value, allow_regression=False: calls.append(
                (key, value, allow_regression)
            )
        )
        states = iter(
            [
                (True, [], {"platform:kraken": True, "user:tania:kraken": True}),
                (
                    False,
                    ["user:tania:kraken"],
                    {"platform:kraken": True, "user:tania:kraken": False},
                ),
            ]
        )
        v95 = types.SimpleNamespace(position_sync_status=lambda manager: next(states))
        with mock.patch.object(v96, "_readiness_module", return_value=readiness), mock.patch.object(
            v96, "_v95_module", return_value=v95
        ):
            self.assertTrue(v96.publish_position_sync_readiness(object(), source="ready")[0])
            self.assertFalse(v96.publish_position_sync_readiness(object(), source="regressed")[0])

        self.assertEqual(
            calls,
            [
                (v96.READINESS_KEY, True, True),
                (v96.READINESS_KEY, False, True),
            ],
        )
        self.assertEqual(os.environ["NIJA_POSITION_SYNC_DISPATCH_READY"], "0")

    def test_first_install_seed_remains_fail_closed(self) -> None:
        with mock.patch.object(v96.builtins, v96._HOOK_FLAG, False, create=True), mock.patch.object(
            v96, "publish_position_sync_readiness"
        ) as publish:
            v96._replay_safe_install_seed()
        publish.assert_called_once_with(None, source="install_fail_closed")

    def test_replay_rechecks_canonical_manager_and_preserves_real_regression(self) -> None:
        manager = object()
        v95 = types.SimpleNamespace(_canonical_manager=lambda: manager)
        with mock.patch.object(v96.builtins, v96._HOOK_FLAG, True, create=True), mock.patch.object(
            v96, "_v95_module", return_value=v95
        ), mock.patch.object(
            v96,
            "publish_position_sync_readiness",
            return_value=(False, ["platform:kraken"], {"platform:kraken": False}),
        ) as publish:
            v96._replay_safe_install_seed()
        publish.assert_called_once_with(manager, source="install_replay_canonical_manager")

    def test_replay_without_manager_preserves_existing_true_proof(self) -> None:
        readiness = types.SimpleNamespace(snapshot=lambda: {v96.READINESS_KEY: True})
        v95 = types.SimpleNamespace(_canonical_manager=lambda: None)
        with mock.patch.object(v96.builtins, v96._HOOK_FLAG, True, create=True), mock.patch.object(
            v96, "_readiness_module", return_value=readiness
        ), mock.patch.object(v96, "_v95_module", return_value=v95), mock.patch.object(
            v96, "publish_position_sync_readiness"
        ) as publish:
            v96._replay_safe_install_seed()
        publish.assert_not_called()
        self.assertEqual(os.environ["NIJA_POSITION_SYNC_ACTIVATION_READY"], "1")
        self.assertEqual(os.environ["NIJA_POSITION_SYNC_DISPATCH_READY"], "1")

    def test_startup_sync_wrapper_publishes_after_reconciliation(self) -> None:
        manager = object()
        strategy = types.SimpleNamespace(multi_account_manager=manager)
        module = types.ModuleType("bot.startup_position_sync")
        events = []

        def sync(current_strategy):
            events.append(("sync", current_strategy))
            return 7

        module.sync_exchange_positions_on_startup = sync
        self.assertTrue(v96._patch_startup_sync(module))

        with mock.patch.object(
            v96,
            "publish_position_sync_readiness",
            side_effect=lambda current_manager, source: events.append(
                ("publish", current_manager, source)
            ),
        ):
            result = module.sync_exchange_positions_on_startup(strategy)

        self.assertEqual(result, 7)
        self.assertEqual(events[0], ("sync", strategy))
        self.assertEqual(events[1], ("publish", manager, "startup_position_sync_complete"))

    def test_mabm_refresh_publishes_after_existing_refresh(self) -> None:
        events = []

        class Manager:
            def refresh_capital_authority(self):
                events.append("refresh")
                return {"ready": True}

        module = types.ModuleType("bot.multi_account_broker_manager")
        module.MultiAccountBrokerManager = Manager
        self.assertTrue(v96._patch_mabm(module))

        manager = Manager()
        with mock.patch.object(
            v96,
            "publish_position_sync_readiness",
            side_effect=lambda current_manager, source: events.append(
                ("publish", current_manager, source)
            ),
        ):
            result = manager.refresh_capital_authority()

        self.assertEqual(result, {"ready": True})
        self.assertEqual(events[0], "refresh")
        self.assertEqual(events[1], ("publish", manager, "refresh_capital_authority"))

    def test_installer_replay_does_not_republish_artificial_fail_closed_state(self) -> None:
        calls = []

        with mock.patch.object(
            v96,
            "publish_position_sync_readiness",
            side_effect=lambda manager, source: calls.append((manager, source)) or (False, [], {}),
        ), mock.patch.object(v96, "_patch_loaded", return_value=True):
            self.assertTrue(v96.install_import_hook())
            self.assertTrue(v96.install_import_hook())

        self.assertEqual(calls, [(None, "install_fail_closed")])
        self.assertEqual(os.environ["NIJA_POSITION_SYNC_INSTALLER_IDEMPOTENCE_V195_READY"], "1")


if __name__ == "__main__":
    unittest.main()
