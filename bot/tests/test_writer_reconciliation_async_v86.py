from __future__ import annotations

import os
import sys
import threading
import types
import unittest
from unittest.mock import MagicMock, patch

from bot.entrypoint_writer_authority import EntrypointWriterAuthority


def _runtime() -> EntrypointWriterAuthority:
    runtime = EntrypointWriterAuthority()
    runtime._client = MagicMock()
    runtime._client.eval.return_value = 1
    runtime._lock_key = "lock"
    runtime._meta_key = "meta"
    runtime._fencing_key = "fence"
    runtime._lock_value = "11:owner"
    runtime._token = "11"
    runtime._generation = 7
    runtime._instance_id = "test"
    runtime._identity = {"instance_id": "test"}
    runtime._owner = "owner"
    runtime._ttl_s = 60
    runtime._acquired_at = 1.0
    runtime._core_thread = MagicMock()
    runtime._core_thread.is_alive.return_value = True
    return runtime


class WriterReconciliationAsyncV86Tests(unittest.TestCase):
    def test_slow_readiness_reconciliation_never_blocks_redis_renewal(self) -> None:
        runtime = _runtime()
        started = threading.Event()
        release = threading.Event()
        calls: list[dict[str, object]] = []
        readiness = types.ModuleType("three_venue_execution_readiness")

        def reconcile(**kwargs: object) -> None:
            calls.append(kwargs)
            started.set()
            release.wait(2.0)

        readiness.reconcile_execution_readiness = reconcile
        writer_env = {
            "NIJA_WRITER_LEASE_ACQUIRED": "1",
            "NIJA_WRITER_FENCING_TOKEN": "11",
            "NIJA_WRITER_LEASE_GENERATION": "7",
        }
        with (
            patch.dict(os.environ, writer_env, clear=False),
            patch("bot.entrypoint_writer_authority._get_heartbeat_state"),
            patch.dict(sys.modules, {"three_venue_execution_readiness": readiness}),
        ):
            try:
                ok, reason = runtime._heartbeat_tick()
                self.assertTrue(ok, reason)
                self.assertEqual(reason, "")
                self.assertTrue(started.wait(1.0))

                # A second renewal succeeds while the first readiness pass is
                # blocked, and it does not create another broker-I/O worker.
                ok, reason = runtime._heartbeat_tick()
                self.assertTrue(ok, reason)
                self.assertEqual(reason, "")
                self.assertEqual(
                    calls,
                    [{"trigger": "heartbeat_renewed", "force": True}],
                )
                self.assertEqual(runtime._client.eval.call_count, 2)
            finally:
                release.set()
                worker = runtime._runtime_reconcile_thread
                if worker is not None:
                    worker.join(1.0)
            self.assertIsNone(runtime._runtime_reconcile_thread)

    def test_non_heartbeat_reconciliation_remains_synchronous(self) -> None:
        runtime = _runtime()
        calls: list[dict[str, object]] = []
        readiness = types.ModuleType("three_venue_execution_readiness")
        readiness.reconcile_execution_readiness = lambda **kwargs: calls.append(kwargs)

        with patch.dict(sys.modules, {"three_venue_execution_readiness": readiness}):
            runtime._notify_runtime_reconciliation("core_thread_registered")

        self.assertEqual(
            calls,
            [{"trigger": "core_thread_registered", "force": True}],
        )
