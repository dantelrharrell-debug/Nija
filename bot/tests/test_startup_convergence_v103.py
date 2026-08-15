from __future__ import annotations

import os
import threading
import types
import unittest
from unittest import mock

from bot import startup_convergence_v103_patch as v103


class StartupConvergenceV103Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.saved_timeout = os.environ.get("NIJA_STRATEGY_CLASS_RECOVERY_TIMEOUT_S")

    def tearDown(self) -> None:
        if self.saved_timeout is None:
            os.environ.pop("NIJA_STRATEGY_CLASS_RECOVERY_TIMEOUT_S", None)
        else:
            os.environ["NIJA_STRATEGY_CLASS_RECOVERY_TIMEOUT_S"] = self.saved_timeout

    def test_strategy_timeout_defaults_to_45_seconds(self) -> None:
        os.environ.pop("NIJA_STRATEGY_CLASS_RECOVERY_TIMEOUT_S", None)
        self.assertEqual(v103._strategy_timeout_s(), 45.0)

    def test_strategy_timeout_preserves_explicit_override(self) -> None:
        os.environ["NIJA_STRATEGY_CLASS_RECOVERY_TIMEOUT_S"] = "17.5"
        self.assertEqual(v103._strategy_timeout_s(), 17.5)

    def test_strategy_timeout_invalid_override_falls_back(self) -> None:
        os.environ["NIJA_STRATEGY_CLASS_RECOVERY_TIMEOUT_S"] = "not-a-number"
        self.assertEqual(v103._strategy_timeout_s(), 45.0)

    def test_reconciliation_guard_coalesces_nested_call(self) -> None:
        calls: list[str] = []
        fake_v32 = types.SimpleNamespace()

        def original(trigger: str) -> bool:
            calls.append(trigger)
            nested = fake_v32._request_runtime_reconciliation("nested")
            self.assertFalse(nested)
            return True

        fake_v32._request_runtime_reconciliation = original

        with mock.patch.dict("sys.modules", {"bot.runtime_execution_convergence_v32": fake_v32}):
            self.assertTrue(v103._patch_v32_reconciliation())
            patched = fake_v32._request_runtime_reconciliation
            self.assertTrue(patched("outer"))

        self.assertEqual(calls, ["outer"])

    def test_reconciliation_guard_releases_after_exception(self) -> None:
        fake_v32 = types.SimpleNamespace()
        attempt = {"count": 0}

        def original(trigger: str) -> bool:
            attempt["count"] += 1
            if attempt["count"] == 1:
                raise RuntimeError("boom")
            return True

        fake_v32._request_runtime_reconciliation = original

        with mock.patch.dict("sys.modules", {"bot.runtime_execution_convergence_v32": fake_v32}):
            self.assertTrue(v103._patch_v32_reconciliation())
            patched = fake_v32._request_runtime_reconciliation
            with self.assertRaises(RuntimeError):
                patched("first")
            self.assertTrue(patched("second"))

        self.assertEqual(attempt["count"], 2)


if __name__ == "__main__":
    unittest.main()
