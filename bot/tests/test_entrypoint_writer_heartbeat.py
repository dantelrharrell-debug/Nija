from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock

from bot.entrypoint_writer_authority import EntrypointWriterAuthority


class EntrypointWriterHeartbeatTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ.pop("NIJA_WRITER_RELEASE_IN_PROGRESS", None)
        self.runtime = EntrypointWriterAuthority()
        self.runtime._client = MagicMock()
        self.runtime._lock_key = "nija:writer_lock:test"
        self.runtime._meta_key = "nija:writer_lock_meta:test"
        self.runtime._lock_value = "11:instance=test"
        self.runtime._token = "11"
        self.runtime._generation = 7
        self.runtime._instance_id = "test"
        self.runtime._identity = {"instance_id": "test"}
        self.runtime._owner = "instance=test"
        self.runtime._ttl_s = 60
        self.runtime._acquired_at = 1.0

    def tearDown(self) -> None:
        for key in (
            "NIJA_WRITER_HEARTBEAT_ACTIVE",
            "NIJA_WRITER_HEARTBEAT_LAST_TS",
            "NIJA_WRITER_HEARTBEAT_ALIVE_TS",
            "NIJA_WRITER_LEASE_ACQUIRED",
            "NIJA_WRITER_FENCING_TOKEN",
            "NIJA_RUNTIME_EXECUTION_AUTHORITY",
            "NIJA_EXECUTION_ACTIVE",
            "NIJA_CORE_THREAD_ALIVE",
            "NIJA_WRITER_RELEASE_IN_PROGRESS",
        ):
            os.environ.pop(key, None)

    def test_heartbeat_renews_only_exact_owned_value(self):
        self.runtime._core_thread = MagicMock()
        self.runtime._core_thread.is_alive.return_value = True
        self.runtime._client.eval.return_value = 1

        ok, reason = self.runtime._heartbeat_tick()

        self.assertTrue(ok)
        self.assertEqual(reason, "")
        call = self.runtime._client.eval.call_args
        self.assertEqual(call.args[4], self.runtime._lock_value)
        self.assertEqual(os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"], "1")

    def test_missing_lock_reacquires_atomically_with_nx(self):
        self.runtime._core_thread = MagicMock()
        self.runtime._core_thread.is_alive.return_value = True
        self.runtime._client.eval.return_value = -1
        self.runtime._client.set.return_value = True

        ok, reason = self.runtime._heartbeat_tick()

        self.assertTrue(ok)
        self.assertEqual(reason, "")
        reacquire = self.runtime._client.set.call_args_list[0]
        self.assertEqual(reacquire.args[0], self.runtime._lock_key)
        self.assertEqual(reacquire.args[1], self.runtime._lock_value)
        self.assertTrue(reacquire.kwargs["nx"])

    def test_different_owner_is_rejected_fail_closed(self):
        self.runtime._core_thread = MagicMock()
        self.runtime._core_thread.is_alive.return_value = True
        self.runtime._client.eval.return_value = 0

        ok, reason = self.runtime._heartbeat_tick()

        self.assertFalse(ok)
        self.assertEqual(reason, "lock_owned_by_different_writer")

    def test_missing_core_thread_releases_for_reelection(self):
        # Simulate the scan-started deadline having been exceeded: the core
        # loop never entered its running state, so a None core thread must
        # fail the liveness check and trigger a re-election.
        self.runtime._scan_deadline_exceeded = True
        self.runtime._release_owned_lock_for_reelection = MagicMock()

        ok, reason = self.runtime._heartbeat_tick()

        self.assertFalse(ok)
        self.assertIn("core_thread_missing", reason)
        self.runtime._release_owned_lock_for_reelection.assert_called_once()
        self.runtime._client.eval.assert_not_called()

    def test_dead_core_thread_releases_for_reelection(self):
        self.runtime._core_thread = MagicMock()
        self.runtime._core_thread.is_alive.return_value = False
        self.runtime._core_thread_name = "nija-core-loop"
        self.runtime._core_thread_ident = 1234
        self.runtime._release_owned_lock_for_reelection = MagicMock()

        ok, reason = self.runtime._heartbeat_tick()

        self.assertFalse(ok)
        self.assertIn("core_thread_dead", reason)
        self.runtime._release_owned_lock_for_reelection.assert_called_once()
        self.runtime._client.eval.assert_not_called()


if __name__ == "__main__":
    unittest.main()
