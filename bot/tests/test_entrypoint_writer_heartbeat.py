from __future__ import annotations

import os
import sys
import types
import unittest
from unittest.mock import MagicMock, patch

from bot.entrypoint_writer_authority import EntrypointWriterAuthority, WriterState


class EntrypointWriterHeartbeatTests(unittest.TestCase):
    def setUp(self) -> None:
        os.environ.pop("NIJA_WRITER_RELEASE_IN_PROGRESS", None)
        self.runtime = EntrypointWriterAuthority()
        self.runtime._client = MagicMock()
        self.runtime._lock_key = "nija:writer_lock:test"
        self.runtime._meta_key = "nija:writer_lock_meta:test"
        self.runtime._fencing_key = "nija:writer_fence:test"
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
            "NIJA_WRITER_STATE",
            "NIJA_WRITER_STATE_SINCE_TS",
            "NIJA_WRITER_LOSS_GRACE_S",
        ):
            os.environ.pop(key, None)

    def test_ttl_refresh_never_disables_execution(self):
        self.runtime._core_thread = MagicMock()
        self.runtime._core_thread.is_alive.return_value = True
        self.runtime._client.eval.return_value = 1
        self.runtime._set_writer_state(WriterState.ACTIVE, reason="test_setup")
        os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "1"
        os.environ["NIJA_EXECUTION_ACTIVE"] = "true"

        ok, reason = self.runtime._heartbeat_tick()

        self.assertTrue(ok)
        self.assertEqual(reason, "")
        call = self.runtime._client.eval.call_args
        self.assertEqual(call.args[5], self.runtime._lock_value)
        self.assertEqual(os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"], "1")
        self.assertEqual(os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"], "1")
        self.assertEqual(os.environ["NIJA_EXECUTION_ACTIVE"], "true")
        self.assertEqual(os.environ["NIJA_WRITER_STATE"], "ACTIVE")

    def test_lock_refresh_preserves_fencing_token(self):
        self.runtime._core_thread = MagicMock()
        self.runtime._core_thread.is_alive.return_value = True
        self.runtime._client.eval.return_value = 2
        self.runtime._set_writer_state(WriterState.ACTIVE, reason="test_setup")
        os.environ["NIJA_WRITER_FENCING_TOKEN"] = self.runtime._token

        ok, reason = self.runtime._heartbeat_tick()

        self.assertTrue(ok)
        self.assertEqual(reason, "")
        self.runtime._client.set.assert_not_called()
        self.assertEqual(os.environ.get("NIJA_WRITER_FENCING_TOKEN"), self.runtime._token)
        self.assertEqual(os.environ["NIJA_WRITER_STATE"], "ACTIVE")

    def test_heartbeat_reconciles_only_after_writer_state_becomes_active(self):
        self.runtime._core_thread = MagicMock()
        self.runtime._core_thread.is_alive.return_value = True
        self.runtime._client.eval.return_value = 1
        self.runtime._set_writer_state(WriterState.ACTIVE, reason="test_setup")
        calls = []
        readiness = types.ModuleType("three_venue_execution_readiness")
        readiness.reconcile_execution_readiness = lambda **kwargs: calls.append(
            (kwargs, os.environ.get("NIJA_WRITER_STATE"))
        )

        with patch.dict(sys.modules, {"three_venue_execution_readiness": readiness}):
            ok, reason = self.runtime._heartbeat_tick()

        self.assertTrue(ok)
        self.assertEqual(reason, "")
        self.assertEqual(
            calls,
            [({"trigger": "heartbeat_renewed", "force": True}, "ACTIVE")],
        )

    def test_brief_redis_interruption_keeps_execution_enabled(self):
        self.runtime._set_writer_state(WriterState.ACTIVE, reason="test_setup")
        os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "1"
        os.environ["NIJA_EXECUTION_ACTIVE"] = "true"
        os.environ["NIJA_WRITER_LOSS_GRACE_S"] = "15"

        sequence = iter(
            [
                (False, "redis_heartbeat_error:TimeoutError:test"),
                (False, "redis_heartbeat_error:TimeoutError:test"),
                (True, ""),
            ]
        )

        def _next_tick():
            result = next(sequence)
            if result[0]:
                self.runtime._stop.set()
            return result

        with (
            patch.object(self.runtime, "_heartbeat_tick", side_effect=_next_tick),
            patch.object(self.runtime._stop, "wait", return_value=False),
            patch.object(self.runtime, "_mark_lost") as mark_lost,
        ):
            self.runtime._heartbeat_loop()

        mark_lost.assert_not_called()
        self.assertEqual(os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"], "1")
        self.assertEqual(os.environ["NIJA_EXECUTION_ACTIVE"], "true")
        self.assertEqual(os.environ["NIJA_WRITER_STATE"], "ACTIVE")

    def test_genuine_ownership_loss_demotes_disables_and_may_begin_recovery(self):
        self.runtime._set_writer_state(WriterState.ACTIVE, reason="test_setup")
        os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "1"
        os.environ["NIJA_WRITER_FENCING_TOKEN"] = self.runtime._token
        os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] = "1"
        os.environ["NIJA_EXECUTION_ACTIVE"] = "true"

        with (
            patch.object(
                self.runtime,
                "_heartbeat_tick",
                return_value=(False, "lock_owned_by_different_writer"),
            ),
            patch.object(self.runtime._stop, "wait", return_value=False),
        ):
            self.runtime._heartbeat_loop()

        # Ownership loss must always demote the canonical runtime and fail-close
        # execution. The v55/v39 bounded recovery handoff is allowed to advance
        # published telemetry from LOST to ACQUIRING immediately afterward; that
        # transition does not restore execution authority.
        self.assertTrue(self.runtime.lost)
        self.assertEqual(os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"], "0")
        self.assertEqual(os.environ["NIJA_EXECUTION_ACTIVE"], "false")
        self.assertIn(os.environ["NIJA_WRITER_STATE"], {"LOST", "ACQUIRING"})

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
