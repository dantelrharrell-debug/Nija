from __future__ import annotations

import importlib
import os
import sys
import threading
import time
import types
import unittest
from unittest import mock


class WriterRecoveryEpochCoreV81Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = importlib.import_module("bot.writer_recovery_epoch_core_v81_patch")
        self.saved = dict(os.environ)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.saved)

    def test_secondary_loss_is_recoverable_only_during_primary_epoch(self) -> None:
        self.assertTrue(self.mod.recoverable_reason("lock_missing_and_fencing_token_mismatch"))
        self.assertTrue(
            self.mod.recoverable_reason("heartbeat_grace_expired:runtime_already_lost")
        )
        os.environ["NIJA_WRITER_RECOVERY_EPOCH_TS"] = str(time.time() - 1000.0)
        self.assertFalse(
            self.mod.recoverable_reason("heartbeat_grace_expired:runtime_already_lost")
        )

    def test_arbitrary_heartbeat_failure_remains_terminal(self) -> None:
        os.environ.pop("NIJA_WRITER_RECOVERY_EPOCH_REASON", None)
        os.environ.pop("NIJA_WRITER_RECOVERY_EPOCH_TS", None)
        self.assertFalse(self.mod.recoverable_reason("heartbeat_grace_expired:redis_timeout"))
        self.assertFalse(self.mod.recoverable_reason("manual_stop"))
        self.assertFalse(self.mod.recoverable_reason("core_thread_not_alive"))

    def test_existing_live_core_is_registered_not_restarted(self) -> None:
        class Runtime:
            acquired = True
            lost = False
            _core_thread = None

            def __init__(self) -> None:
                self.registered = None

            def register_core_thread(self, thread):
                self.registered = thread

            def record_scan_started(self):
                return None

        stop = threading.Event()
        thread = threading.Thread(target=lambda: stop.wait(2.0), name="real-core", daemon=True)
        thread.start()
        runtime = Runtime()
        bot_main = types.ModuleType("bot.bot_main")
        bot_main._core_loop_thread = thread
        bot_main._startup_complete = True
        bot_main._shutdown_event = threading.Event()

        with mock.patch.object(self.mod, "_bot_main", return_value=bot_main), mock.patch.object(
            self.mod, "_runtime", return_value=runtime
        ), mock.patch.object(self.mod, "_canonical_strategy") as strategy:
            ok, reason = self.mod.repair_core_thread_once()

        stop.set()
        thread.join(timeout=2.0)
        self.assertTrue(ok)
        self.assertEqual(reason, "existing_live_thread")
        self.assertIs(runtime.registered, thread)
        strategy.assert_not_called()

    def test_dead_core_restarts_only_from_canonical_strategy(self) -> None:
        class Runtime:
            acquired = True
            lost = False
            _core_thread = None

            def __init__(self) -> None:
                self.registered = None

            def register_core_thread(self, thread):
                self.registered = thread

            def record_scan_started(self):
                return None

        class Strategy:
            def run_cycle(self):
                return None

        runtime = Runtime()
        bot_main = types.ModuleType("bot.bot_main")
        bot_main._core_loop_thread = None
        bot_main._startup_complete = True
        bot_main._shutdown_event = threading.Event()
        stop = threading.Event()
        created = []

        def starter(strategy):
            self.assertIsInstance(strategy, Strategy)
            thread = threading.Thread(target=lambda: stop.wait(2.0), name="restarted-core", daemon=True)
            thread.start()
            created.append(thread)
            return thread

        engine = types.ModuleType("bot.nija_core_loop")
        engine.start_trading_engine = starter
        original = sys.modules.get("bot.nija_core_loop")
        sys.modules["bot.nija_core_loop"] = engine
        try:
            with mock.patch.object(self.mod, "_bot_main", return_value=bot_main), mock.patch.object(
                self.mod, "_runtime", return_value=runtime
            ), mock.patch.object(self.mod, "_canonical_strategy", return_value=Strategy()):
                ok, reason = self.mod.repair_core_thread_once()
        finally:
            stop.set()
            for thread in created:
                thread.join(timeout=2.0)
            if original is None:
                sys.modules.pop("bot.nija_core_loop", None)
            else:
                sys.modules["bot.nija_core_loop"] = original

        self.assertTrue(ok)
        self.assertEqual(reason, "canonical_strategy_restart")
        self.assertIs(runtime.registered, created[0])
        self.assertIs(bot_main._core_loop_thread, created[0])

    def test_no_restart_without_writer_authority(self) -> None:
        runtime = types.SimpleNamespace(acquired=False, lost=True, _core_thread=None)
        bot_main = types.ModuleType("bot.bot_main")
        bot_main._core_loop_thread = None
        bot_main._startup_complete = True
        bot_main._shutdown_event = threading.Event()
        with mock.patch.object(self.mod, "_bot_main", return_value=bot_main), mock.patch.object(
            self.mod, "_runtime", return_value=runtime
        ):
            ok, reason = self.mod.repair_core_thread_once()
        self.assertFalse(ok)
        self.assertEqual(reason, "writer_not_acquired")


if __name__ == "__main__":
    unittest.main()
