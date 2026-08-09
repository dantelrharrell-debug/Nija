from __future__ import annotations

import importlib
import os
import types
import unittest


class CapitalRefreshLiveContinuityV78Tests(unittest.TestCase):
    def setUp(self):
        self.mod = importlib.import_module("bot.capital_refresh_live_continuity_v78_patch")
        self.previous = os.environ.get("NIJA_CAPITAL_REFRESH_FETCH_BUDGET_SECONDS")

    def tearDown(self):
        if self.previous is None:
            os.environ.pop("NIJA_CAPITAL_REFRESH_FETCH_BUDGET_SECONDS", None)
        else:
            os.environ["NIJA_CAPITAL_REFRESH_FETCH_BUDGET_SECONDS"] = self.previous

    def test_default_budget_exceeds_observed_180_second_timeout(self):
        os.environ.pop("NIJA_CAPITAL_REFRESH_FETCH_BUDGET_SECONDS", None)
        self.assertEqual(self.mod.fetch_budget_seconds(), 420.0)

    def test_budget_is_bounded(self):
        os.environ["NIJA_CAPITAL_REFRESH_FETCH_BUDGET_SECONDS"] = "9999"
        self.assertEqual(self.mod.fetch_budget_seconds(), 600.0)
        os.environ["NIJA_CAPITAL_REFRESH_FETCH_BUDGET_SECONDS"] = "10"
        self.assertEqual(self.mod.fetch_budget_seconds(), 180.0)

    def test_patch_extends_old_batch_deadline_without_touching_freshness(self):
        fake = types.ModuleType("capital_guard_v78_fake")

        class Flight:
            def __init__(self):
                self.timeout_s = 180.0

        class Batch:
            def __init__(self, broker_map):
                self._cycle_started = 1000.0
                self._cycle_deadline = 1180.0
                self._flights = {name: Flight() for name in broker_map}

        fake._BalanceFetchBatch = Batch
        fake._freshness_ttl_seconds = lambda: 120.0
        os.environ["NIJA_CAPITAL_REFRESH_FETCH_BUDGET_SECONDS"] = "420"
        self.assertTrue(self.mod._patch_guard(fake))
        batch = Batch({"coinbase": object(), "okx": object()})
        self.assertEqual(batch._flights["coinbase"].timeout_s, 420.0)
        self.assertEqual(batch._cycle_deadline, 1420.0)
        self.assertEqual(fake._freshness_ttl_seconds(), 120.0)

    def test_operator_larger_timeout_is_not_shortened(self):
        fake = types.ModuleType("capital_guard_v78_large_fake")

        class Flight:
            def __init__(self):
                self.timeout_s = 500.0

        class Batch:
            def __init__(self, broker_map):
                self._cycle_started = 1000.0
                self._cycle_deadline = 1500.0
                self._flights = {name: Flight() for name in broker_map}

        fake._BalanceFetchBatch = Batch
        self.mod._patch_guard(fake)
        batch = Batch({"coinbase": object()})
        self.assertEqual(batch._flights["coinbase"].timeout_s, 500.0)
        self.assertEqual(batch._cycle_deadline, 1500.0)


if __name__ == "__main__":
    unittest.main()
