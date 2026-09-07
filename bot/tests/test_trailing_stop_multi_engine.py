"""Regression tests for universal trailing-stop coverage."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch


class TestTrailingStopMultiEngine(unittest.TestCase):
    def setUp(self):
        from bot import trailing_stop_loss_runtime_patch as mod
        self.mod = mod
        self.original_started = mod._PROCESS_STARTED
        mod._PROCESS_STARTED = True  # do not start a daemon worker in unit tests
        mod._ENGINES.clear()
        setattr(__import__("builtins"), mod._FALLBACK_REGISTRY_ATTR, [])

    def tearDown(self):
        self.mod._ENGINES.clear()
        self.mod._PROCESS_STARTED = self.original_started
        setattr(__import__("builtins"), self.mod._FALLBACK_REGISTRY_ATTR, [])

    def test_every_engine_is_registered(self):
        class Engine:
            pass

        engines = [Engine(), Engine(), Engine()]
        for engine in engines:
            self.mod._register_engine(engine)

        snapshot = self.mod._engine_snapshot()
        self.assertEqual({id(x) for x in snapshot}, {id(x) for x in engines})
        for engine in engines:
            self.assertTrue(getattr(engine, self.mod._MONITOR_STARTED_ATTR))

    def test_quantity_aliases_cover_multiple_broker_schemas(self):
        for key in ("quantity", "qty", "size", "amount", "units", "balance"):
            with self.subTest(key=key):
                self.assertEqual(self.mod._quantity({key: "1.25"}), 1.25)

    def test_live_mode_cannot_disable_trailing_protection(self):
        with patch.dict(os.environ, {
            "DRY_RUN_MODE": "false",
            "PAPER_MODE": "false",
            "NIJA_TRAILING_STOP_ENABLED": "false",
        }, clear=False):
            self.assertTrue(self.mod._live_protection_required())
            self.assertEqual(os.environ["NIJA_TRAILING_STOP_ENABLED"], "true")

    def test_paper_mode_can_disable_worker_for_tests(self):
        with patch.dict(os.environ, {
            "PAPER_MODE": "true",
            "NIJA_TRAILING_STOP_ENABLED": "false",
        }, clear=False):
            self.assertFalse(self.mod._live_protection_required())


if __name__ == "__main__":
    unittest.main()
