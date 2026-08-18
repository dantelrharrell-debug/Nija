from __future__ import annotations

import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
BOT = ROOT / "bot"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v146 = _load(
    "runtime_reconciliation_shutdown_v146_under_test",
    BOT / "runtime_reconciliation_shutdown_v146_patch.py",
)


class RuntimeReconciliationShutdownV146Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.env = patch.dict(os.environ, {}, clear=False)
        self.env.start()
        for key in (
            "NIJA_RECONCILIATION_STATUS",
            "NIJA_RECONCILIATION_COMPLETE",
        ):
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        self.env.stop()

    @staticmethod
    def _position_module(result):
        module = types.ModuleType("fake_position_sync_v96")
        broker_status = dict(result[2] or {})
        brokers = {
            name: types.SimpleNamespace(_startup_position_sync_fetch_ok=True)
            for name in broker_status
        }

        class V95:
            @staticmethod
            def position_sync_status(_manager):
                return result

            @staticmethod
            def _connected_brokers(_manager):
                return brokers

        module._v95_module = lambda: V95
        return module

    def test_zero_connected_brokers_never_proves_reconciliation(self) -> None:
        module = self._position_module((True, [], {}))
        ready, pending, status = v146._position_sync_truth(module, object())
        self.assertFalse(ready)
        self.assertEqual(pending, [])
        self.assertEqual(status, {})

    def test_all_connected_brokers_publish_clean_start(self) -> None:
        published = v146._publish_reconciliation_truth(
            True,
            [],
            {"platform:coinbase": True, "platform:kraken": True},
            source="unit_test",
        )
        self.assertTrue(published)
        self.assertEqual(os.environ["NIJA_RECONCILIATION_STATUS"], "CLEAN_START")
        self.assertEqual(os.environ["NIJA_RECONCILIATION_COMPLETE"], "true")

    def test_adopted_snapshot_without_fetch_proof_stays_fail_closed(self) -> None:
        module = self._position_module((True, [], {"platform:kraken": True}))
        module._v95_module()._connected_brokers(object())[
            "platform:kraken"
        ]._startup_position_sync_fetch_ok = None

        ready, pending, status = v146._position_sync_truth(module, object())

        self.assertFalse(ready)
        self.assertEqual(pending, ["platform:kraken"])
        self.assertEqual(status, {"platform:kraken": True})

    def test_broker_set_race_stays_fail_closed(self) -> None:
        module = self._position_module((True, [], {"platform:kraken": True}))
        coinbase = types.SimpleNamespace(_startup_position_sync_fetch_ok=True)
        module._v95_module = lambda: types.SimpleNamespace(
            position_sync_status=lambda _manager: (
                True,
                [],
                {"platform:kraken": True},
            ),
            _connected_brokers=lambda _manager: {"platform:coinbase": coinbase},
        )

        ready, pending, status = v146._position_sync_truth(module, object())

        self.assertFalse(ready)
        self.assertEqual(pending, ["platform:coinbase", "platform:kraken"])
        self.assertEqual(status, {"platform:kraken": True})

    def test_position_sync_regression_revokes_clean_proof(self) -> None:
        os.environ["NIJA_RECONCILIATION_STATUS"] = "CLEAN_START"
        os.environ["NIJA_RECONCILIATION_COMPLETE"] = "true"
        published = v146._publish_reconciliation_truth(
            False,
            ["user:customer:kraken"],
            {"platform:kraken": True, "user:customer:kraken": False},
            source="late_broker",
        )
        self.assertFalse(published)
        self.assertEqual(os.environ["NIJA_RECONCILIATION_STATUS"], "PENDING")
        self.assertEqual(os.environ["NIJA_RECONCILIATION_COMPLETE"], "false")

    def test_explicit_discrepancy_is_never_overwritten(self) -> None:
        os.environ["NIJA_RECONCILIATION_STATUS"] = "DISCREPANCIES_FOUND"
        os.environ["NIJA_RECONCILIATION_COMPLETE"] = "true"
        published = v146._publish_reconciliation_truth(
            True,
            [],
            {"platform:kraken": True},
            source="unit_test",
        )
        self.assertFalse(published)
        self.assertEqual(
            os.environ["NIJA_RECONCILIATION_STATUS"],
            "DISCREPANCIES_FOUND",
        )
        self.assertEqual(os.environ["NIJA_RECONCILIATION_COMPLETE"], "true")

    def test_incomplete_explicit_failure_is_never_overwritten(self) -> None:
        os.environ["NIJA_RECONCILIATION_STATUS"] = "FAILED"
        os.environ["NIJA_RECONCILIATION_COMPLETE"] = "false"

        published = v146._publish_reconciliation_truth(
            True,
            [],
            {"platform:kraken": True},
            source="unit_test",
        )

        self.assertFalse(published)
        self.assertEqual(os.environ["NIJA_RECONCILIATION_STATUS"], "FAILED")
        self.assertEqual(os.environ["NIJA_RECONCILIATION_COMPLETE"], "false")

    def test_reconciliation_is_visible_before_v96_readiness_edge(self) -> None:
        status = {"platform:kraken": True}
        module = self._position_module((True, [], status))
        observed = []

        def publish_position_sync_readiness(_manager, *, source):
            observed.append(
                (
                    source,
                    os.environ.get("NIJA_RECONCILIATION_STATUS"),
                    os.environ.get("NIJA_RECONCILIATION_COMPLETE"),
                )
            )
            return True, [], status

        module.publish_position_sync_readiness = publish_position_sync_readiness
        self.assertTrue(v146._patch_position_sync_publication(module))
        ready, pending, final_status = module.publish_position_sync_readiness(
            object(),
            source="startup_position_sync_complete",
        )

        self.assertTrue(ready)
        self.assertEqual(pending, [])
        self.assertEqual(final_status, status)
        self.assertEqual(
            observed,
            [("startup_position_sync_complete", "CLEAN_START", "true")],
        )

    def test_v96_adopted_true_cannot_override_missing_fetch_proof(self) -> None:
        status = {"platform:kraken": True}
        module = self._position_module((True, [], status))
        module._v95_module()._connected_brokers(object())[
            "platform:kraken"
        ]._startup_position_sync_fetch_ok = None
        readiness_calls = []
        module.READINESS_KEY = "position_sync_ready"
        module._readiness_module = lambda: types.SimpleNamespace(
            set_ready=lambda *args, **kwargs: readiness_calls.append((args, kwargs))
        )
        module.publish_position_sync_readiness = lambda _manager, *, source: (
            True,
            [],
            status,
        )

        self.assertTrue(v146._patch_position_sync_publication(module))
        ready, pending, final_status = module.publish_position_sync_readiness(
            object(),
            source="unit_test",
        )

        self.assertFalse(ready)
        self.assertEqual(pending, ["platform:kraken"])
        self.assertEqual(final_status, status)
        self.assertEqual(os.environ["NIJA_RECONCILIATION_STATUS"], "PENDING")
        self.assertEqual(os.environ["NIJA_RECONCILIATION_COMPLETE"], "false")
        self.assertEqual(
            readiness_calls,
            [(('position_sync_ready', False), {"allow_regression": True})],
        )

    def test_bot_main_finalizer_can_wake_loaded_core_without_importing(self) -> None:
        bot_main = _load("bot_main_v146_under_test", BOT / "bot_main.py")
        calls = []
        fake_core = types.ModuleType("bot.nija_core_loop")
        fake_core.request_trading_engine_stop = calls.append

        with patch.dict(sys.modules, {"bot.nija_core_loop": fake_core}):
            self.assertTrue(bot_main._signal_core_loop_shutdown("unit_test"))

        self.assertEqual(calls, ["unit_test"])

    def test_core_waits_and_finalizer_are_wired_to_stop_signal(self) -> None:
        core_source = (BOT / "nija_core_loop.py").read_text(encoding="utf-8")
        main_source = (BOT / "bot_main.py").read_text(encoding="utf-8")
        self.assertIn("def request_trading_engine_stop(", core_source)
        self.assertIn("_engine_stop_event.wait", core_source)
        self.assertIn(
            '_signal_core_loop_shutdown(_process_exit_reason or "bot_main_finally")',
            main_source,
        )


if __name__ == "__main__":
    unittest.main()
