from __future__ import annotations

import importlib
import os
import threading
import types
import unittest
from unittest import mock


class WriterSingleOwnerV82Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = importlib.import_module("bot.writer_single_owner_convergence_v82_patch")
        self.saved = dict(os.environ)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self.saved)

    def test_exact_owner_rejects_foreign_lock(self) -> None:
        class Client:
            def get(self, key):
                if key == "lock":
                    return b"99:foreign"
                return b"7"
            def pttl(self, key):
                return 30000
        runtime = types.SimpleNamespace(
            acquired=True, lost=False, _local_fallback=False, _client=Client(),
            _lock_key="lock", _lock_value="12:mine", _generation=7,
        )
        ok, reason, generation = self.mod._exact_runtime_owner(runtime)
        self.assertFalse(ok)
        self.assertEqual(reason, "lock_owned_by_other")
        self.assertEqual(generation, 7)

    def test_exact_owner_requires_same_generation_and_positive_ttl(self) -> None:
        class Client:
            redis_generation = b"8"
            ttl = 30000
            def get(self, key):
                return b"12:mine" if key == "lock" else self.redis_generation
            def pttl(self, key):
                return self.ttl
        client = Client()
        runtime = types.SimpleNamespace(
            acquired=True, lost=False, _local_fallback=False, _client=client,
            _lock_key="lock", _lock_value="12:mine", _generation=7,
        )
        ok, reason, _ = self.mod._exact_runtime_owner(runtime)
        self.assertFalse(ok)
        self.assertIn("generation_mismatch", reason)
        client.redis_generation = b"7"
        client.ttl = 0
        ok, reason, _ = self.mod._exact_runtime_owner(runtime)
        self.assertFalse(ok)
        self.assertIn("lock_ttl_not_positive", reason)

    def test_observer_writer_never_mutates_writer_lock(self) -> None:
        writes = []
        class Client:
            def set(self, *args, **kwargs):
                writes.append((args, kwargs))
        runtime = types.SimpleNamespace(_client=Client())
        fake_module = types.ModuleType("bot.authority_heartbeat")
        class Monitor:
            def _write_heartbeat_to_redis(self):
                raise AssertionError("legacy writer must be replaced")
        fake_module.AuthorityHeartbeatMonitor = Monitor
        fake_module._check_authority_once = lambda timeout: (True, "")
        with mock.patch.object(self.mod, "_entrypoint_runtime", return_value=runtime), mock.patch.object(
            self.mod, "_exact_runtime_owner", return_value=(True, "exact_owner", 42)
        ), mock.patch("importlib.import_module", return_value=fake_module):
            self.assertTrue(self.mod._patch_authority_observer())
            Monitor()._write_heartbeat_to_redis()
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0][0][0], "nija:writer_heartbeat_active")
        self.assertNotIn("writer_lock", writes[0][0][0])

    def test_fresh_monitor_waits_for_old_monitor_exit(self) -> None:
        stop = threading.Event()
        old_thread = threading.Thread(target=lambda: stop.wait(0.1), daemon=True)
        old_thread.start()
        class Old:
            _thread = old_thread
            def stop(self):
                stop.set()
        bot_main = types.ModuleType("bot.bot_main")
        bot_main._authority_heartbeat_monitor = Old()
        prod = types.ModuleType("bot.production_readiness_v39_patch")
        prod._restart_authority_monitor = lambda module: False
        hb = types.ModuleType("bot.authority_heartbeat")
        class NewMonitor:
            def __init__(self):
                self._stop = threading.Event()
                self._thread = None
            def start(self):
                self._thread = threading.Thread(target=lambda: self._stop.wait(1), daemon=True)
                self._thread.start()
        hb.AuthorityHeartbeatMonitor = NewMonitor
        real_import = importlib.import_module
        def importer(name):
            if name == "bot.production_readiness_v39_patch": return prod
            if name == "bot.authority_heartbeat": return hb
            return real_import(name)
        with mock.patch("importlib.import_module", side_effect=importer), mock.patch.object(
            self.mod, "_exact_runtime_owner", return_value=(True, "exact_owner", 44)
        ):
            self.assertTrue(self.mod._patch_v39_monitor_restart())
            self.assertTrue(prod._restart_authority_monitor(bot_main))
        bot_main._authority_heartbeat_monitor._stop.set()
        bot_main._authority_heartbeat_monitor._thread.join(timeout=1)


if __name__ == "__main__":
    unittest.main()
