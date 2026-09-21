from __future__ import annotations

import os
import sys
import types
import unittest
from unittest.mock import patch

from bot import runtime_reconciliation_shutdown_v146_patch as v146


class ReconciliationGateStabilityV146Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {}, clear=False)
        self.env.start()
        os.environ["NIJA_RECONCILIATION_STATUS"] = "CLEAN_START"
        os.environ["NIJA_RECONCILIATION_COMPLETE"] = "true"

    def tearDown(self) -> None:
        self.env.stop()

    @staticmethod
    def _module(state: dict[str, object]):
        coinbase = types.SimpleNamespace(_startup_position_sync_fetch_ok=True)

        class V95:
            platform_position_sync_status = staticmethod(lambda _manager: None)

            @staticmethod
            def position_sync_status(_manager):
                return state["result"]

            @staticmethod
            def _connected_brokers(_manager):
                return {"platform:coinbase": coinbase}

        module = types.ModuleType("fake_position_sync_v96_gate_stability")
        module._v95_module = lambda: V95
        module.READINESS_KEY = "position_sync_ready"
        module._readiness_module = lambda: types.SimpleNamespace(set_ready=lambda *args, **kwargs: None)
        return module

    @staticmethod
    def _coordinator_modules():
        readiness = types.ModuleType("bot.readiness_table")
        readiness.get_version = lambda: 1
        readiness.snapshot = lambda: {"position_sync_ready": True}

        startup = types.ModuleType("bot.startup_coordinator")
        coordinator = types.SimpleNamespace(record_readiness=lambda **kwargs: None)
        startup.get_startup_coordinator = lambda: coordinator
        return readiness, startup

    def test_transient_prepublication_regression_does_not_flap_clean_gate(self) -> None:
        state = {
            "result": (
                False,
                ["platform:coinbase"],
                {"platform:coinbase": False},
            )
        }
        module = self._module(state)
        observed = []

        def publish_position_sync_readiness(_manager, *, source):
            observed.append(
                (
                    source,
                    os.environ.get("NIJA_RECONCILIATION_STATUS"),
                    os.environ.get("NIJA_RECONCILIATION_COMPLETE"),
                )
            )
            state["result"] = (
                True,
                [],
                {"platform:coinbase": True},
            )
            return False, ["platform:coinbase"], {"platform:coinbase": False}

        module.publish_position_sync_readiness = publish_position_sync_readiness
        self.assertTrue(v146._patch_position_sync_publication(module))

        readiness, startup = self._coordinator_modules()
        with patch.dict(
            sys.modules,
            {
                "bot.readiness_table": readiness,
                "bot.startup_coordinator": startup,
            },
        ):
            ready, pending, status = module.publish_position_sync_readiness(
                object(),
                source="platform_isolation_v320_convergence",
            )

        self.assertTrue(ready)
        self.assertEqual(pending, [])
        self.assertEqual(status, {"platform:coinbase": True})
        self.assertEqual(
            observed,
            [
                (
                    "platform_isolation_v320_convergence",
                    "CLEAN_START",
                    "true",
                )
            ],
        )
        self.assertEqual(os.environ["NIJA_RECONCILIATION_STATUS"], "CLEAN_START")
        self.assertEqual(os.environ["NIJA_RECONCILIATION_COMPLETE"], "true")

    def test_persistent_regression_still_revokes_after_final_refresh_result(self) -> None:
        state = {
            "result": (
                False,
                ["platform:coinbase"],
                {"platform:coinbase": False},
            )
        }
        module = self._module(state)
        observed = []

        def publish_position_sync_readiness(_manager, *, source):
            observed.append(
                (
                    os.environ.get("NIJA_RECONCILIATION_STATUS"),
                    os.environ.get("NIJA_RECONCILIATION_COMPLETE"),
                )
            )
            return state["result"]

        module.publish_position_sync_readiness = publish_position_sync_readiness
        self.assertTrue(v146._patch_position_sync_publication(module))

        ready, pending, status = module.publish_position_sync_readiness(
            object(),
            source="platform_isolation_v320_convergence",
        )

        self.assertFalse(ready)
        self.assertEqual(pending, ["platform:coinbase"])
        self.assertEqual(status, {"platform:coinbase": False})
        self.assertEqual(observed, [("CLEAN_START", "true")])
        self.assertEqual(os.environ["NIJA_RECONCILIATION_STATUS"], "PENDING")
        self.assertEqual(os.environ["NIJA_RECONCILIATION_COMPLETE"], "false")


if __name__ == "__main__":
    unittest.main()
