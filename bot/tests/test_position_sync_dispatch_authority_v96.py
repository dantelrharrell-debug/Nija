from __future__ import annotations

import os
import types
import unittest
from unittest import mock

from bot import position_sync_dispatch_authority_v96_patch as v96


class PositionSyncDispatchAuthorityV96Tests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("NIJA_POSITION_SYNC_ACTIVATION_READY", None)
        os.environ.pop("NIJA_POSITION_SYNC_DISPATCH_READY", None)

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


if __name__ == "__main__":
    unittest.main()
