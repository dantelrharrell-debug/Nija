from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from bot.entrypoint_writer_authority import (
    EntrypointWriterAuthority,
    EntrypointWriterAuthorityResult,
)


class WriterRenewalProofV85Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.saved = {
            key: os.environ.get(key)
            for key in (
                "NIJA_WRITER_LEASE_RENEWAL_ACTIVE",
                "NIJA_WRITER_LEASE_RENEWED_TS",
            )
        }
        for key in self.saved:
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        for key, value in self.saved.items():
            os.environ.pop(key, None)
            if value is not None:
                os.environ[key] = value

    @staticmethod
    def _acquired_runtime(redis_code: int) -> EntrypointWriterAuthority:
        runtime = EntrypointWriterAuthority()
        runtime._client = MagicMock()
        runtime._client.eval.return_value = redis_code
        runtime._result = EntrypointWriterAuthorityResult(acquired=True)
        runtime._lock_key = "nija:writer_lock:test"
        runtime._meta_key = "nija:writer_lock_meta:test"
        runtime._fencing_key = "nija:writer_fence:test"
        runtime._lock_value = "17:owner"
        runtime._token = "17"
        runtime._generation = 23
        runtime._instance_id = "instance-1"
        return runtime

    def test_publish_env_records_initial_renewal_proof(self) -> None:
        runtime = self._acquired_runtime(1)
        with patch("bot.entrypoint_writer_authority.time.monotonic", return_value=11.5), patch(
            "bot.entrypoint_writer_authority.time.time", return_value=101.25
        ):
            runtime._publish_env(scope="test", generation_key="generation", fallback=False)

        self.assertEqual(runtime._nija_last_lease_renewal_monotonic, 11.5)
        self.assertEqual(runtime._nija_last_lease_renewal_epoch, 101.25)
        self.assertEqual(os.environ["NIJA_WRITER_LEASE_RENEWAL_ACTIVE"], "1")
        self.assertEqual(os.environ["NIJA_WRITER_LEASE_RENEWED_TS"], "101.250000")

    def test_successful_canonical_heartbeat_refreshes_renewal_proof(self) -> None:
        runtime = self._acquired_runtime(1)
        runtime._nija_last_lease_renewal_monotonic = 11.5
        runtime._heartbeat_thread = MagicMock()
        runtime._heartbeat_thread.is_alive.return_value = True
        with patch.object(
            runtime, "_check_authority_invariant", return_value=(True, "")
        ), patch.object(runtime, "_notify_runtime_reconciliation"), patch(
            "bot.entrypoint_writer_authority.time.monotonic", return_value=42.0
        ), patch("bot.entrypoint_writer_authority.time.time", return_value=202.5):
            ok, reason = runtime._heartbeat_tick()
            healthy, health_reason, age_s, max_age_s = runtime._nija_lease_renewal_health()

        self.assertTrue(ok)
        self.assertEqual(reason, "")
        self.assertEqual(runtime._nija_last_lease_renewal_monotonic, 42.0)
        self.assertEqual(runtime._nija_last_lease_renewal_epoch, 202.5)
        self.assertEqual(os.environ["NIJA_WRITER_LEASE_RENEWED_TS"], "202.500000")
        self.assertTrue(healthy)
        self.assertEqual(health_reason, "renewal_healthy")
        self.assertEqual(age_s, 0.0)
        self.assertGreaterEqual(max_age_s, 10.0)

    def test_failed_heartbeat_does_not_refresh_renewal_proof(self) -> None:
        runtime = self._acquired_runtime(0)
        runtime._nija_last_lease_renewal_monotonic = 11.5
        runtime._nija_last_lease_renewal_epoch = 101.25

        with patch.object(
            runtime, "_check_authority_invariant", return_value=(True, "")
        ), patch("bot.entrypoint_writer_authority.time.monotonic", return_value=42.0), patch(
            "bot.entrypoint_writer_authority.time.time", return_value=202.5
        ):
            ok, reason = runtime._heartbeat_tick()

        self.assertFalse(ok)
        self.assertEqual(reason, "lock_owned_by_different_writer")
        self.assertEqual(runtime._nija_last_lease_renewal_monotonic, 11.5)
        self.assertEqual(runtime._nija_last_lease_renewal_epoch, 101.25)


if __name__ == "__main__":
    unittest.main()
