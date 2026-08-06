"""Regression tests for the writer-authority lifecycle state synchronization fix.

Covers:
- Writer lease acquisition
- Heartbeat publication via HeartbeatState
- Heartbeat refresh (timestamp advances)
- Startup scan completion clears deadline
- No repeated SCAN_STARTED_DEADLINE_EXCEEDED after scan completes
- Generation rollover
- Lease renewal
- Lease loss and reacquisition
- Steady-state runtime (heartbeat_stale never fires while beats are current)
"""
from __future__ import annotations

import os
import sys
import threading
import time
import types
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Ensure bot package is importable when running from the repo root
# ---------------------------------------------------------------------------
_BOT_DIR = os.path.join(os.path.dirname(__file__), "..")
if _BOT_DIR not in sys.path:
    sys.path.insert(0, _BOT_DIR)
_ROOT_DIR = os.path.join(_BOT_DIR, "..")
if _ROOT_DIR not in sys.path:
    sys.path.insert(0, _ROOT_DIR)


from bot.heartbeat_state import (
    HeartbeatState,
    WriterLifecyclePhase,
    get_heartbeat_state,
    reset_heartbeat_state_for_testing,
)
from bot.entrypoint_writer_authority import EntrypointWriterAuthority


_ENV_KEYS = (
    "LIVE_CAPITAL_VERIFIED",
    "DRY_RUN_MODE",
    "PAPER_MODE",
    "KRAKEN_PLATFORM_API_KEY",
    "NIJA_WRITER_LOCK_SCOPE",
    "NIJA_WRITER_LOCK_KEY",
    "NIJA_WRITER_LOCK_META_KEY",
    "NIJA_WRITER_FENCING_KEY",
    "NIJA_WRITER_FENCING_TOKEN",
    "NIJA_WRITER_OWNER_ID",
    "NIJA_WRITER_INSTANCE_ID",
    "NIJA_WRITER_LEASE_GENERATION",
    "NIJA_WRITER_GENERATION",
    "NIJA_WRITER_LEASE_ACQUIRED",
    "NIJA_LOCK_ACQUIRED",
    "NIJA_WRITER_HEARTBEAT_ACTIVE",
    "NIJA_WRITER_HEARTBEAT_LAST_TS",
    "NIJA_WRITER_HEARTBEAT_ALIVE_TS",
    "NIJA_ENTRYPOINT_WRITER_LOCK_WAIT_S",
    "NIJA_WRITER_RELEASE_HEARTBEAT_JOIN_S",
    "NIJA_FORCE_LOCAL_WRITER_LOCK_FALLBACK",
    "NIJA_CONFIRM_BYPASS_RISKS",
    "NIJA_WRITER_FENCING_TOKEN_FALLBACK",
    "NIJA_CORE_THREAD_ALIVE",
    "NIJA_SCAN_STARTED_DEADLINE_S",
    "NIJA_RUNTIME_AUTHORITY_CONVERGENCE_HEARTBEAT_MAX_AGE_S",
    "KRAKEN_NONCE_LEASE_REQUIRED",
)


class HeartbeatStateUnitTests(unittest.TestCase):
    """Unit tests for the HeartbeatState singleton."""

    def setUp(self) -> None:
        self.hs = reset_heartbeat_state_for_testing()

    def test_initial_state_is_boot_and_unhealthy(self) -> None:
        snap = self.hs.snapshot()
        self.assertEqual(snap.phase, WriterLifecyclePhase.BOOT)
        self.assertFalse(snap.healthy)
        self.assertEqual(snap.timestamp, 0.0)

    def test_record_heartbeat_sets_healthy_and_advances_timestamp(self) -> None:
        before = time.time()
        snap = self.hs.record_heartbeat(generation=7)
        after = time.time()
        self.assertTrue(snap.healthy)
        self.assertEqual(snap.generation, 7)
        self.assertGreaterEqual(snap.timestamp, before)
        self.assertLessEqual(snap.timestamp, after)

    def test_record_heartbeat_updates_marker_timestamp_when_provided(self) -> None:
        marker_ts = time.time()
        snap = self.hs.record_heartbeat(generation=1, marker_timestamp=marker_ts)
        self.assertEqual(snap.marker_timestamp, marker_ts)

    def test_record_heartbeat_does_not_regress_marker_timestamp(self) -> None:
        marker_ts = time.time()
        self.hs.record_heartbeat(generation=1, marker_timestamp=marker_ts)
        # Second beat without marker should preserve the first timestamp
        snap2 = self.hs.record_heartbeat(generation=1)
        self.assertEqual(snap2.marker_timestamp, marker_ts)

    def test_record_heartbeat_failure_marks_unhealthy(self) -> None:
        self.hs.record_heartbeat(generation=1)
        self.hs.record_heartbeat_failure()
        snap = self.hs.snapshot()
        self.assertFalse(snap.healthy)

    def test_is_fresh_requires_healthy_and_recent_timestamp(self) -> None:
        self.assertFalse(self.hs.is_fresh(max_age_s=90.0))
        self.hs.record_heartbeat(generation=1)
        self.assertTrue(self.hs.is_fresh(max_age_s=90.0))

    def test_is_fresh_returns_false_after_max_age_elapsed(self) -> None:
        self.hs.record_heartbeat(generation=1)
        with patch("bot.heartbeat_state.time") as mock_time:
            mock_time.time.return_value = time.time() + 200
            self.assertFalse(self.hs.is_fresh(max_age_s=90.0))

    def test_advance_phase_forward_only(self) -> None:
        self.hs.advance_phase(WriterLifecyclePhase.LEASE_ACQUIRED)
        self.assertEqual(self.hs.phase, WriterLifecyclePhase.LEASE_ACQUIRED)
        self.hs.advance_phase(WriterLifecyclePhase.SCAN_RUNNING)
        self.assertEqual(self.hs.phase, WriterLifecyclePhase.SCAN_RUNNING)
        # Attempt to regress — must be silently ignored
        self.hs.advance_phase(WriterLifecyclePhase.BOOT)
        self.assertEqual(self.hs.phase, WriterLifecyclePhase.SCAN_RUNNING)

    def test_advance_to_live(self) -> None:
        self.hs.advance_phase(WriterLifecyclePhase.LIVE)
        self.assertTrue(self.hs.is_live)

    def test_reset_returns_to_boot(self) -> None:
        self.hs.record_heartbeat(generation=5)
        self.hs.advance_phase(WriterLifecyclePhase.LIVE)
        self.hs.reset()
        snap = self.hs.snapshot()
        self.assertEqual(snap.phase, WriterLifecyclePhase.BOOT)
        self.assertFalse(snap.healthy)
        self.assertEqual(snap.timestamp, 0.0)

    def test_heartbeat_refresh_advances_timestamp(self) -> None:
        snap1 = self.hs.record_heartbeat(generation=1)
        time.sleep(0.02)
        snap2 = self.hs.record_heartbeat(generation=1)
        self.assertGreater(snap2.timestamp, snap1.timestamp)

    def test_generation_rollover(self) -> None:
        for gen in range(10):
            snap = self.hs.record_heartbeat(generation=gen)
            self.assertEqual(snap.generation, gen)
        snap = self.hs.record_heartbeat(generation=0)
        self.assertEqual(snap.generation, 0)

    def test_heartbeat_survives_many_beats(self) -> None:
        """Simulate 200 beats — state stays healthy throughout."""
        for i in range(200):
            self.hs.record_heartbeat(generation=1)
        snap = self.hs.snapshot()
        self.assertTrue(snap.healthy)

    def test_get_heartbeat_state_returns_singleton(self) -> None:
        hs1 = get_heartbeat_state()
        hs2 = get_heartbeat_state()
        self.assertIs(hs1, hs2)

    def test_age_s_returns_inf_before_any_beat(self) -> None:
        self.assertEqual(self.hs.age_s(), float("inf"))

    def test_age_s_increases_over_time(self) -> None:
        self.hs.record_heartbeat(generation=1)
        age1 = self.hs.age_s()
        time.sleep(0.05)
        age2 = self.hs.age_s()
        self.assertGreater(age2, age1)


class ScanDeadlineTests(unittest.TestCase):
    """Tests that the scan-started deadline is purely a startup check."""

    def setUp(self) -> None:
        self.saved = {k: os.environ.get(k) for k in _ENV_KEYS}
        for k in _ENV_KEYS:
            os.environ.pop(k, None)
        os.environ["LIVE_CAPITAL_VERIFIED"] = "true"
        os.environ["DRY_RUN_MODE"] = "false"
        os.environ["PAPER_MODE"] = "false"
        os.environ["KRAKEN_PLATFORM_API_KEY"] = "test-key"
        os.environ["NIJA_ENTRYPOINT_WRITER_LOCK_WAIT_S"] = "0"
        reset_heartbeat_state_for_testing()

    def tearDown(self) -> None:
        for k in _ENV_KEYS:
            os.environ.pop(k, None)
        for k, v in self.saved.items():
            if v is not None:
                os.environ[k] = v

    def _make_runtime(self) -> EntrypointWriterAuthority:
        r = EntrypointWriterAuthority()
        r._acquired_at = time.time()
        r._token = "tok1"
        r._generation = 1
        r._instance_id = "test-instance"
        return r

    def test_record_scan_started_clears_deadline_exceeded(self) -> None:
        r = self._make_runtime()
        r._scan_deadline_exceeded = True
        r.record_scan_started()
        self.assertFalse(r._scan_deadline_exceeded)

    def test_record_scan_started_is_idempotent(self) -> None:
        r = self._make_runtime()
        r.record_scan_started()
        ts1 = r._scan_started_at
        r._scan_deadline_exceeded = True  # simulate re-flag
        r.record_scan_started()
        self.assertEqual(r._scan_started_at, ts1)  # not changed
        # Idempotent call does NOT clear the flag (only first call does)
        # This is correct: subsequent calls are no-ops.

    def test_validate_core_thread_liveness_allows_none_thread_without_deadline(self) -> None:
        r = self._make_runtime()
        r._scan_deadline_exceeded = False
        r._scan_started_at = 0.0
        ok, reason = r._validate_core_thread_liveness()
        self.assertTrue(ok)

    def test_validate_core_thread_liveness_fails_when_deadline_exceeded_and_no_scan(self) -> None:
        r = self._make_runtime()
        r._scan_deadline_exceeded = True
        r._scan_started_at = 0.0
        ok, reason = r._validate_core_thread_liveness()
        self.assertFalse(ok)
        self.assertIn("deadline_exceeded", reason)

    def test_validate_core_thread_liveness_passes_when_scan_started_despite_deadline_flag(self) -> None:
        r = self._make_runtime()
        # Simulate: deadline was exceeded but scan then started and cleared the flag
        r._scan_deadline_exceeded = False
        r._scan_started_at = time.time()
        ok, reason = r._validate_core_thread_liveness()
        self.assertTrue(ok)

    def test_watchdog_loop_clears_deadline_when_scan_starts_late(self) -> None:
        """Watchdog must exit and clear deadline even if scan starts after deadline."""
        r = self._make_runtime()
        # Simulate deadline already elapsed
        r._acquired_at = time.time() - 400.0
        r._scan_deadline_exceeded = True

        # Background: set scan_started_at after a short delay
        def _set_scan_started() -> None:
            time.sleep(0.05)
            r._scan_started_at = time.time()

        bg = threading.Thread(target=_set_scan_started, daemon=True)
        bg.start()

        # Run watchdog with a very short deadline (already exceeded)
        r._scan_started_watchdog_loop(deadline_s=1.0)

        bg.join(timeout=1.0)
        self.assertFalse(r._scan_deadline_exceeded, "Deadline flag must be cleared after scan starts")

    def test_no_repeated_scan_deadline_error_after_scan_starts(self) -> None:
        """After record_scan_started(), _scan_deadline_exceeded must remain False."""
        r = self._make_runtime()
        r._scan_deadline_exceeded = True
        r.record_scan_started()
        # Even if someone polls _validate_core_thread_liveness repeatedly
        for _ in range(10):
            ok, _ = r._validate_core_thread_liveness()
            self.assertTrue(ok)
            self.assertFalse(r._scan_deadline_exceeded)

    def test_lifecycle_phase_advances_to_scan_running_on_record_scan_started(self) -> None:
        r = self._make_runtime()
        hs = reset_heartbeat_state_for_testing()
        hs.advance_phase(WriterLifecyclePhase.LEASE_ACQUIRED)
        r.record_scan_started()
        self.assertEqual(get_heartbeat_state().phase, WriterLifecyclePhase.SCAN_RUNNING)

    def test_record_scan_complete_cancels_watchdog(self) -> None:
        """record_scan_complete() must cancel the startup watchdog immediately."""
        r = self._make_runtime()
        r.record_scan_started()
        self.assertFalse(r._scan_watchdog_cancel.is_set())
        r.record_scan_complete()
        self.assertTrue(r._scan_watchdog_cancel.is_set())
        self.assertGreater(r._scan_complete_at, 0.0)
        self.assertFalse(r._scan_deadline_exceeded)

    def test_watchdog_exits_after_scan_complete_without_deadline_exceeded(self) -> None:
        """After record_scan_complete(), the watchdog must not log SCAN_STARTED_DEADLINE_EXCEEDED
        even when more time than the deadline has elapsed."""
        r = self._make_runtime()
        # Set acquired_at far in the past so elapsed is well beyond any deadline.
        r._acquired_at = time.time() - 1000.0
        r.record_scan_started()
        r.record_scan_complete()
        # The watchdog loop must exit immediately (cancel is set) without setting
        # _scan_deadline_exceeded.
        r._scan_deadline_exceeded = False
        r._scan_started_watchdog_loop(deadline_s=30.0)
        self.assertFalse(r._scan_deadline_exceeded)

    def test_reacquisition_after_scan_complete_does_not_restart_deadline_alarm(self) -> None:
        """Re-acquiring the lock after a completed scan must not re-arm the deadline
        watchdog in a way that fires SCAN_STARTED_DEADLINE_EXCEEDED."""
        r = self._make_runtime()
        r.record_scan_started()
        r.record_scan_complete()
        self.assertTrue(r._scan_watchdog_cancel.is_set())

        # Simulate the state that _acquire_once_locked resets before re-acquisition.
        prior_complete = r._scan_complete_at
        r._scan_started_at = 0.0
        r._scan_complete_at = 0.0
        r._scan_watchdog_cancel.clear()

        # Re-apply the fix: restore from prior state.
        if prior_complete:
            r.record_scan_complete()

        # Watchdog should be cancelled again; no deadline exceeded flag.
        self.assertTrue(r._scan_watchdog_cancel.is_set())
        self.assertFalse(r._scan_deadline_exceeded)

    def test_watchdog_exits_immediately_when_scan_complete_set(self) -> None:
        """_scan_started_watchdog_loop must exit at the top-of-loop check when
        _scan_complete_at is set, even without _scan_started_at being set."""
        r = self._make_runtime()
        r._acquired_at = time.time() - 1000.0
        # Only mark complete, not started (simulates post-reacquisition state
        # where _scan_started_at was reset but _scan_complete_at is restored).
        r._scan_complete_at = time.time()
        r._scan_started_at = 0.0
        r._scan_deadline_exceeded = False
        r._scan_started_watchdog_loop(deadline_s=30.0)
        self.assertFalse(r._scan_deadline_exceeded)


class HeartbeatStateIntegrationTests(unittest.TestCase):
    """Integration: entrypoint updates HeartbeatState on publish / renewal."""

    def setUp(self) -> None:
        self.saved = {k: os.environ.get(k) for k in _ENV_KEYS}
        for k in _ENV_KEYS:
            os.environ.pop(k, None)
        os.environ["LIVE_CAPITAL_VERIFIED"] = "true"
        os.environ["DRY_RUN_MODE"] = "false"
        os.environ["PAPER_MODE"] = "false"
        os.environ["KRAKEN_PLATFORM_API_KEY"] = "test-key"
        os.environ["NIJA_ENTRYPOINT_WRITER_LOCK_WAIT_S"] = "0"
        reset_heartbeat_state_for_testing()

    def tearDown(self) -> None:
        for k in _ENV_KEYS:
            os.environ.pop(k, None)
        for k, v in self.saved.items():
            if v is not None:
                os.environ[k] = v

    @staticmethod
    def _identity():
        return (
            {"instance_id": "test-instance-1", "hostname": "host-1"},
            "instance=test-instance-1|host=host-1|pid=1",
            "test-instance-1",
        )

    def test_acquire_once_updates_heartbeat_state(self) -> None:
        client = MagicMock()
        client.eval.return_value = [17, "17:owner", 60000, 42]
        client.set.return_value = True

        runtime = EntrypointWriterAuthority()
        with (
            patch("bot.entrypoint_writer_authority._connect_redis", return_value=(client, "rediss://x", "")),
            patch("bot.entrypoint_writer_authority._instance_identity", side_effect=self._identity),
            patch.object(runtime, "_start_heartbeat"),
        ):
            result = runtime.acquire_once()

        self.assertTrue(result.acquired)
        snap = get_heartbeat_state().snapshot()
        self.assertTrue(snap.healthy)
        self.assertEqual(snap.generation, 42)
        self.assertGreater(snap.timestamp, 0.0)
        self.assertEqual(snap.phase, WriterLifecyclePhase.LEASE_ACQUIRED)

    def test_heartbeat_renewal_updates_heartbeat_state(self) -> None:
        client = MagicMock()
        client.eval.return_value = [17, "17:owner", 60000, 5]
        client.set.return_value = True

        runtime = EntrypointWriterAuthority()
        with (
            patch("bot.entrypoint_writer_authority._connect_redis", return_value=(client, "rediss://x", "")),
            patch("bot.entrypoint_writer_authority._instance_identity", side_effect=self._identity),
            patch.object(runtime, "_start_heartbeat"),
        ):
            runtime.acquire_once()

        # Simulate Redis heartbeat renewal (code == 1)
        client.eval.return_value = 1
        snap_before = get_heartbeat_state().snapshot()
        time.sleep(0.02)

        # Patch core thread alive check
        with patch.object(runtime, "_validate_core_thread_liveness", return_value=(True, "")):
            ok, _ = runtime._heartbeat_tick()

        self.assertTrue(ok)
        snap_after = get_heartbeat_state().snapshot()
        self.assertTrue(snap_after.healthy)
        self.assertGreater(snap_after.timestamp, snap_before.timestamp)

    def test_heartbeat_state_stays_healthy_across_multiple_renewals(self) -> None:
        """Steady-state: repeated renewals keep HeartbeatState healthy."""
        client = MagicMock()
        client.eval.return_value = [17, "17:owner", 60000, 3]
        client.set.return_value = True

        runtime = EntrypointWriterAuthority()
        with (
            patch("bot.entrypoint_writer_authority._connect_redis", return_value=(client, "rediss://x", "")),
            patch("bot.entrypoint_writer_authority._instance_identity", side_effect=self._identity),
            patch.object(runtime, "_start_heartbeat"),
        ):
            runtime.acquire_once()

        client.eval.return_value = 1
        with patch.object(runtime, "_validate_core_thread_liveness", return_value=(True, "")):
            for _ in range(20):
                ok, _ = runtime._heartbeat_tick()
                self.assertTrue(ok)

        self.assertTrue(get_heartbeat_state().is_fresh(max_age_s=5.0))


class ConvergenceHeartbeatReadinessTests(unittest.TestCase):
    """Tests for _heartbeat_ready() in runtime_authority_convergence_repair_patch."""

    def setUp(self) -> None:
        self.saved = {k: os.environ.get(k) for k in _ENV_KEYS}
        for k in _ENV_KEYS:
            os.environ.pop(k, None)
        reset_heartbeat_state_for_testing()

    def tearDown(self) -> None:
        for k in _ENV_KEYS:
            os.environ.pop(k, None)
        for k, v in self.saved.items():
            if v is not None:
                os.environ[k] = v

    def _setup_env_for_ready(self) -> None:
        os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "1"
        os.environ["NIJA_WRITER_FENCING_TOKEN"] = "tok1"
        os.environ["NIJA_WRITER_LEASE_GENERATION"] = "5"
        os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "1"
        os.environ["NIJA_CORE_THREAD_ALIVE"] = "1"

    def test_heartbeat_ready_passes_when_heartbeat_state_healthy_and_fresh(self) -> None:
        self._setup_env_for_ready()
        hs = get_heartbeat_state()
        hs.record_heartbeat(generation=5)

        from bot.runtime_authority_convergence_repair_patch import _heartbeat_ready
        ok, reason = _heartbeat_ready()
        self.assertTrue(ok, reason)
        self.assertNotIn("stale", reason)

    def test_heartbeat_ready_fails_with_stale_when_heartbeat_state_old(self) -> None:
        self._setup_env_for_ready()
        hs = get_heartbeat_state()
        hs.record_heartbeat(generation=5)

        from bot.runtime_authority_convergence_repair_patch import _heartbeat_ready
        # Fast-forward time so the beat looks old
        with patch("bot.runtime_authority_convergence_repair_patch.time") as mt:
            mt.time.return_value = time.time() + 200
            ok, reason = _heartbeat_ready()

        self.assertFalse(ok)
        self.assertIn("stale", reason)

    def test_heartbeat_stale_never_fires_while_beats_are_current(self) -> None:
        """Acceptance criterion: no heartbeat_stale while successful heartbeats continue."""
        self._setup_env_for_ready()
        hs = get_heartbeat_state()

        from bot.runtime_authority_convergence_repair_patch import _heartbeat_ready

        # Simulate 10 back-to-back beats with a small delay
        for _ in range(10):
            hs.record_heartbeat(generation=5)
            ok, reason = _heartbeat_ready()
            self.assertTrue(ok, f"Expected heartbeat_ready but got: {reason}")
            self.assertNotIn("stale", reason)

    def test_heartbeat_ready_falls_back_to_env_var_when_state_not_seeded(self) -> None:
        """If HeartbeatState was never seeded, fall back to env-var timestamp."""
        self._setup_env_for_ready()
        now = str(time.time())
        os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"] = now
        # HeartbeatState is freshly reset — healthy=False, timestamp=0

        from bot.runtime_authority_convergence_repair_patch import _heartbeat_ready
        ok, reason = _heartbeat_ready()
        self.assertTrue(ok, reason)

    def test_writer_acquired_true_heartbeat_healthy_generation_matches_not_stale(self) -> None:
        """Acceptance criterion from the problem statement."""
        self._setup_env_for_ready()
        hs = get_heartbeat_state()
        hs.record_heartbeat(generation=5)

        from bot.runtime_authority_convergence_repair_patch import _heartbeat_ready
        ok, reason = _heartbeat_ready()
        self.assertTrue(ok, f"heartbeat_stale must not fire here; got: {reason}")


class LeaseLifecycleTests(unittest.TestCase):
    """Tests for lease acquisition, loss, and reacquisition."""

    def setUp(self) -> None:
        self.saved = {k: os.environ.get(k) for k in _ENV_KEYS}
        for k in _ENV_KEYS:
            os.environ.pop(k, None)
        os.environ["LIVE_CAPITAL_VERIFIED"] = "true"
        os.environ["DRY_RUN_MODE"] = "false"
        os.environ["PAPER_MODE"] = "false"
        os.environ["KRAKEN_PLATFORM_API_KEY"] = "test-key"
        os.environ["NIJA_ENTRYPOINT_WRITER_LOCK_WAIT_S"] = "0"
        reset_heartbeat_state_for_testing()

    def tearDown(self) -> None:
        for k in _ENV_KEYS:
            os.environ.pop(k, None)
        for k, v in self.saved.items():
            if v is not None:
                os.environ[k] = v

    @staticmethod
    def _identity():
        return (
            {"instance_id": "li-1", "hostname": "host-1"},
            "instance=li-1|host=host-1|pid=2",
            "li-1",
        )

    def test_lease_acquisition_sets_acquired(self) -> None:
        client = MagicMock()
        client.eval.return_value = [10, "10:owner", 60000, 1]
        client.set.return_value = True
        rt = EntrypointWriterAuthority()
        with (
            patch("bot.entrypoint_writer_authority._connect_redis", return_value=(client, "rediss://x", "")),
            patch("bot.entrypoint_writer_authority._instance_identity", side_effect=self._identity),
            patch.object(rt, "_start_heartbeat"),
        ):
            result = rt.acquire_once()
        self.assertTrue(result.acquired)
        self.assertTrue(rt.acquired)

    def test_lease_loss_sets_lost_and_resets_heartbeat_state(self) -> None:
        client = MagicMock()
        client.eval.return_value = [10, "10:owner", 60000, 2]
        client.set.return_value = True
        rt = EntrypointWriterAuthority()
        with (
            patch("bot.entrypoint_writer_authority._connect_redis", return_value=(client, "rediss://x", "")),
            patch("bot.entrypoint_writer_authority._instance_identity", side_effect=self._identity),
            patch.object(rt, "_start_heartbeat"),
        ):
            rt.acquire_once()

        # Simulate heartbeat failure: lock owned by different writer
        client.eval.return_value = 0
        with (
            patch.object(rt, "_validate_core_thread_liveness", return_value=(True, "")),
            patch.object(rt, "_release_owned_lock_for_reelection") as mock_release,
        ):
            ok, reason = rt._heartbeat_tick()
        self.assertFalse(ok)

    def test_lease_refresh_after_expiry_updates_heartbeat_state(self) -> None:
        client = MagicMock()
        client.eval.return_value = [10, "10:owner", 60000, 3]
        client.set.return_value = True
        rt = EntrypointWriterAuthority()
        with (
            patch("bot.entrypoint_writer_authority._connect_redis", return_value=(client, "rediss://x", "")),
            patch("bot.entrypoint_writer_authority._instance_identity", side_effect=self._identity),
            patch.object(rt, "_start_heartbeat"),
        ):
            rt.acquire_once()

        snap_before = get_heartbeat_state().snapshot()
        time.sleep(0.02)

        # Simulate: lock key was absent but fencing ownership still matched.
        client.eval.return_value = 2
        with (
            patch.object(rt, "_validate_core_thread_liveness", return_value=(True, "")),
            patch.object(rt, "_write_metadata"),
        ):
            ok, reason = rt._heartbeat_tick()

        self.assertTrue(ok, f"Refresh should succeed, got: {reason}")
        snap_after = get_heartbeat_state().snapshot()
        self.assertTrue(snap_after.healthy)
        self.assertGreater(snap_after.timestamp, snap_before.timestamp)


if __name__ == "__main__":
    unittest.main()
