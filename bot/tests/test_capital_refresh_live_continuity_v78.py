from __future__ import annotations

import importlib
import os
import types
import unittest


class CapitalRefreshLiveContinuityV78Tests(unittest.TestCase):
    def setUp(self):
        self.mod = importlib.import_module("bot.capital_refresh_live_continuity_v78_patch")
        self.keys = (
            "NIJA_CAPITAL_REFRESH_FETCH_BUDGET_SECONDS",
            "NIJA_CAPITAL_REFRESH_PUBLISH_MARGIN_SECONDS",
            "NIJA_CAPITAL_FRESHNESS_TTL_S",
        )
        self.previous = {key: os.environ.get(key) for key in self.keys}
        for key in self.keys:
            os.environ.pop(key, None)

    def tearDown(self):
        for key, value in self.previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_default_budget_stays_inside_default_freshness_ttl(self):
        self.assertEqual(self.mod.fetch_budget_seconds(), 60.0)
        self.assertLess(
            self.mod.fetch_budget_seconds(),
            self.mod._freshness_ttl_seconds(),
        )

    def test_operator_budget_cannot_outlive_freshness(self):
        os.environ["NIJA_CAPITAL_REFRESH_FETCH_BUDGET_SECONDS"] = "9999"
        os.environ["NIJA_CAPITAL_FRESHNESS_TTL_S"] = "90"
        os.environ["NIJA_CAPITAL_REFRESH_PUBLISH_MARGIN_SECONDS"] = "15"
        self.assertEqual(self.mod.fetch_budget_seconds(), 75.0)

        os.environ["NIJA_CAPITAL_REFRESH_FETCH_BUDGET_SECONDS"] = "10"
        self.assertEqual(self.mod.fetch_budget_seconds(), 10.0)

    def test_patch_shortens_cycle_deadline_but_leaves_worker_timeout_unchanged(self):
        fake = types.ModuleType("capital_guard_v78_fake")

        class Flight:
            def __init__(self):
                self.timeout_s = 180.0

        class Batch:
            def __init__(self, broker_map):
                self._batch_started = 1000.0
                self._cycle_deadline = 1185.0
                self._flights = {name: Flight() for name in broker_map}

        fake._BalanceFetchBatch = Batch
        os.environ["NIJA_CAPITAL_REFRESH_FETCH_BUDGET_SECONDS"] = "60"
        self.assertTrue(self.mod._patch_guard(fake))
        batch = Batch({"coinbase": object(), "okx": object()})

        # Slow workers remain alive under their original broker-specific timeout;
        # only the synchronous publication deadline is shortened.
        self.assertEqual(batch._flights["coinbase"].timeout_s, 180.0)
        self.assertEqual(batch._cycle_deadline, 1060.0)

    def test_stricter_existing_cycle_deadline_is_not_lengthened(self):
        fake = types.ModuleType("capital_guard_v78_strict_fake")

        class Batch:
            def __init__(self, broker_map):
                self._batch_started = 1000.0
                self._cycle_deadline = 1030.0
                self._flights = {}

        fake._BalanceFetchBatch = Batch
        os.environ["NIJA_CAPITAL_REFRESH_FETCH_BUDGET_SECONDS"] = "60"
        self.mod._patch_guard(fake)
        batch = Batch({"coinbase": object()})
        self.assertEqual(batch._cycle_deadline, 1030.0)

    def test_cycle_started_compatibility_field_is_supported(self):
        fake = types.ModuleType("capital_guard_v78_compat_fake")

        class Batch:
            def __init__(self, broker_map):
                self._cycle_started = 2000.0
                self._cycle_deadline = 2200.0
                self._flights = {}

        fake._BalanceFetchBatch = Batch
        os.environ["NIJA_CAPITAL_REFRESH_FETCH_BUDGET_SECONDS"] = "45"
        self.mod._patch_guard(fake)
        batch = Batch({"okx": object()})
        self.assertEqual(batch._cycle_deadline, 2045.0)


if __name__ == "__main__":
    unittest.main()
