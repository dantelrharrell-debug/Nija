from __future__ import annotations

import importlib.util
import os
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


BOT_DIR = Path(__file__).resolve().parents[1]


def _load_patch():
    spec = importlib.util.spec_from_file_location(
        "stale_renewal_recovery_v40_patch_under_test",
        BOT_DIR / "stale_renewal_recovery_v40_patch.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StaleRenewalEpochV83Tests(unittest.TestCase):
    def test_watchdog_rotates_when_writer_generation_changes(self) -> None:
        patch = _load_patch()
        runtime = SimpleNamespace(
            _generation=41,
            acquired=False,
            lost=False,
        )

        self.assertTrue(patch._start_watchdog(runtime))
        old_thread = getattr(runtime, patch._WATCHDOG_ATTR)
        self.assertEqual(getattr(old_thread, patch._WATCHDOG_GENERATION_ATTR), 41)

        runtime._generation = 42
        self.assertTrue(patch._start_watchdog(runtime))
        new_thread = getattr(runtime, patch._WATCHDOG_ATTR)
        self.assertIsNot(new_thread, old_thread)
        self.assertEqual(getattr(new_thread, patch._WATCHDOG_GENERATION_ATTR), 42)

        getattr(runtime, patch._WATCHDOG_STOP_ATTR).set()
        new_thread.join(timeout=3.0)
        old_thread.join(timeout=3.0)
        self.assertFalse(old_thread.is_alive())
        self.assertFalse(new_thread.is_alive())

    def test_stale_epoch_exits_before_fail_closed_mutation(self) -> None:
        patch = _load_patch()
        health_entered = threading.Event()
        health_release = threading.Event()

        def blocked_health(_runtime):
            health_entered.set()
            health_release.wait(timeout=2.0)
            return False, "renewal_success_stale", 30.0, 15.0

        runtime = SimpleNamespace(
            _generation=7,
            acquired=True,
            lost=False,
        )
        env = {
            "NIJA_RUNTIME_EXECUTION_AUTHORITY": "1",
            "NIJA_EXECUTION_ACTIVE": "true",
        }
        with mock.patch.object(patch, "_runtime_health", blocked_health), mock.patch.object(
            patch, "_cfg_float", lambda *_args: 0.25
        ), mock.patch.dict(os.environ, env, clear=False):
            stop = threading.Event()
            thread = threading.Thread(
                target=patch._watchdog_loop,
                args=(runtime, stop),
                daemon=True,
            )
            thread.start()
            self.assertTrue(health_entered.wait(timeout=1.0))
            runtime._generation = 8
            health_release.set()
            thread.join(timeout=2.0)

            self.assertFalse(thread.is_alive())
            self.assertEqual(os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"], "1")
            self.assertEqual(os.environ["NIJA_EXECUTION_ACTIVE"], "true")


if __name__ == "__main__":
    unittest.main()
