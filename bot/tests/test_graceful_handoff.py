"""
Tests for the graceful handoff protocol (bot/graceful_handoff.py).

Covers:
  - InFlightTracker increment/decrement/drain
  - Generation tracking helpers
  - AcquireResult dataclass
  - GracefulHandoffCoordinator singleton
  - Shutdown gate in trading loop (is_shutting_down flag)
  - is_generation_current() stale-trade detection
"""

from __future__ import annotations

import os
import threading
import time
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# InFlightTracker
# ---------------------------------------------------------------------------

from bot.graceful_handoff import (
    InFlightTracker,
    AcquireResult,
    GracefulHandoffCoordinator,
    get_handoff_coordinator,
    is_generation_current,
)


class TestInFlightTracker(unittest.TestCase):
    def test_starts_drained(self):
        t = InFlightTracker()
        self.assertEqual(t.count, 0)
        self.assertTrue(t.wait_drained(timeout_s=0.01))

    def test_increment_decrement(self):
        t = InFlightTracker()
        t.increment()
        self.assertEqual(t.count, 1)
        self.assertFalse(t.wait_drained(timeout_s=0.01))
        t.decrement()
        self.assertEqual(t.count, 0)
        self.assertTrue(t.wait_drained(timeout_s=0.1))

    def test_decrement_below_zero_clamps(self):
        t = InFlightTracker()
        t.decrement()  # should not go negative
        self.assertEqual(t.count, 0)

    def test_track_context_manager(self):
        t = InFlightTracker()
        results = []

        def _work():
            results.append(t.count)

        t.track(_work)
        self.assertEqual(t.count, 0)
        self.assertEqual(results, [1])

    def test_drain_timeout(self):
        t = InFlightTracker()
        t.increment()
        drained = t.wait_drained(timeout_s=0.05)
        self.assertFalse(drained)
        t.decrement()

    def test_concurrent_increment_decrement(self):
        t = InFlightTracker()
        errors = []

        def _worker():
            for _ in range(100):
                t.increment()
                time.sleep(0)
                t.decrement()

        threads = [threading.Thread(target=_worker) for _ in range(5)]
        for th in threads:
            th.start()
        for th in threads:
            th.join(timeout=5)
        self.assertEqual(t.count, 0)


# ---------------------------------------------------------------------------
# is_generation_current
# ---------------------------------------------------------------------------


class TestIsGenerationCurrent(unittest.TestCase):
    def setUp(self):
        # Clear env before each test
        os.environ.pop("NIJA_WRITER_LEASE_GENERATION", None)

    def tearDown(self):
        os.environ.pop("NIJA_WRITER_LEASE_GENERATION", None)

    def test_matching_generation_returns_true(self):
        os.environ["NIJA_WRITER_LEASE_GENERATION"] = "5"
        self.assertTrue(is_generation_current(5))

    def test_mismatched_generation_returns_false(self):
        os.environ["NIJA_WRITER_LEASE_GENERATION"] = "5"
        self.assertFalse(is_generation_current(4))
        self.assertFalse(is_generation_current(6))

    def test_zero_local_generation_allows_by_default(self):
        os.environ["NIJA_WRITER_LEASE_GENERATION"] = "0"
        # Cannot verify — allow by default
        self.assertTrue(is_generation_current(5))

    def test_zero_trade_generation_allows_by_default(self):
        os.environ["NIJA_WRITER_LEASE_GENERATION"] = "5"
        # Cannot verify — allow by default
        self.assertTrue(is_generation_current(0))

    def test_missing_env_allows_by_default(self):
        # No env var set
        self.assertTrue(is_generation_current(3))

    def test_invalid_env_allows_by_default(self):
        os.environ["NIJA_WRITER_LEASE_GENERATION"] = "not-a-number"
        self.assertTrue(is_generation_current(3))


# ---------------------------------------------------------------------------
# AcquireResult dataclass
# ---------------------------------------------------------------------------


class TestAcquireResult(unittest.TestCase):
    def test_defaults(self):
        r = AcquireResult(
            acquired=True,
            generation=7,
            token="abc123",
            instance_id="test-instance",
        )
        self.assertTrue(r.acquired)
        self.assertEqual(r.generation, 7)
        self.assertEqual(r.token, "abc123")
        self.assertFalse(r.waited_for_release)
        self.assertFalse(r.forced)
        self.assertEqual(r.error, "")

    def test_failed_result(self):
        r = AcquireResult(
            acquired=False,
            generation=0,
            token="",
            instance_id="test-instance",
            error="redis_unavailable",
        )
        self.assertFalse(r.acquired)
        self.assertEqual(r.error, "redis_unavailable")


# ---------------------------------------------------------------------------
# GracefulHandoffCoordinator — singleton and startup guard
# ---------------------------------------------------------------------------


class TestGracefulHandoffCoordinatorSingleton(unittest.TestCase):
    def test_get_handoff_coordinator_returns_same_instance(self):
        c1 = get_handoff_coordinator()
        c2 = get_handoff_coordinator()
        self.assertIs(c1, c2)

    def test_is_shutting_down_false_before_startup(self):
        # A fresh coordinator (not started) should not be shutting down.
        c = GracefulHandoffCoordinator()
        self.assertFalse(c.is_shutting_down)

    def test_current_generation_zero_before_startup(self):
        c = GracefulHandoffCoordinator()
        self.assertEqual(c.current_generation, 0)

    def test_in_flight_count_zero_before_startup(self):
        c = GracefulHandoffCoordinator()
        self.assertEqual(c.in_flight_count, 0)

    def test_startup_returns_failed_result_when_redis_unavailable(self):
        """When Redis is not configured, startup() should return acquired=False."""
        c = GracefulHandoffCoordinator()
        with patch("bot.graceful_handoff._get_redis_client", return_value=None):
            result = c.startup()
        self.assertFalse(result.acquired)
        self.assertEqual(result.error, "redis_unavailable")

    def test_startup_idempotent(self):
        """Calling startup() twice returns the cached result."""
        c = GracefulHandoffCoordinator()
        with patch("bot.graceful_handoff._get_redis_client", return_value=None):
            r1 = c.startup()
            r2 = c.startup()
        # Second call returns cached result (already_started error)
        self.assertFalse(r1.acquired)
        self.assertFalse(r2.acquired)


# ---------------------------------------------------------------------------
# GracefulHandoffCoordinator — in_flight_scope
# ---------------------------------------------------------------------------


class TestInFlightScope(unittest.TestCase):
    def test_scope_increments_and_decrements(self):
        c = GracefulHandoffCoordinator()
        self.assertEqual(c.in_flight_count, 0)
        with c.in_flight_scope():
            self.assertEqual(c.in_flight_count, 1)
        self.assertEqual(c.in_flight_count, 0)

    def test_scope_raises_when_shutting_down(self):
        c = GracefulHandoffCoordinator()
        # Simulate shutdown by setting the event directly
        c._shutdown_handler = MagicMock()
        c._shutdown_handler.is_shutting_down = True
        with self.assertRaises(RuntimeError) as ctx:
            with c.in_flight_scope():
                pass
        self.assertIn("graceful shutdown", str(ctx.exception).lower())

    def test_scope_decrements_on_exception(self):
        c = GracefulHandoffCoordinator()
        try:
            with c.in_flight_scope():
                raise ValueError("test error")
        except ValueError:
            pass
        self.assertEqual(c.in_flight_count, 0)


# ---------------------------------------------------------------------------
# Lock acquisition with mocked Redis
# ---------------------------------------------------------------------------


class TestAcquireWriterLockWithHandoff(unittest.TestCase):
    def _make_redis_mock(
        self,
        *,
        existing_value: str = "",
        existing_ttl_ms: int = -2,
        set_result: bool = True,
        incr_result: int = 1,
    ) -> MagicMock:
        mock = MagicMock()
        mock.get.return_value = existing_value or None
        mock.pttl.return_value = existing_ttl_ms
        mock.set.return_value = set_result
        mock.incr.return_value = incr_result
        mock.delete.return_value = 1
        mock.pexpire.return_value = True
        return mock

    def test_acquire_fresh_lock(self):
        from bot.graceful_handoff import acquire_writer_lock_with_handoff

        mock_client = self._make_redis_mock(
            existing_value="",
            existing_ttl_ms=-2,
            set_result=True,
            incr_result=3,
        )
        with patch("bot.graceful_handoff._get_redis_client", return_value=mock_client):
            result = acquire_writer_lock_with_handoff(instance_id="test-instance")

        self.assertTrue(result.acquired)
        self.assertEqual(result.generation, 3)
        self.assertFalse(result.waited_for_release)
        self.assertFalse(result.forced)

    def test_acquire_fails_when_redis_unavailable(self):
        from bot.graceful_handoff import acquire_writer_lock_with_handoff

        with patch("bot.graceful_handoff._get_redis_client", return_value=None):
            result = acquire_writer_lock_with_handoff(instance_id="test-instance")

        self.assertFalse(result.acquired)
        self.assertEqual(result.error, "redis_unavailable")

    def test_acquire_waits_for_release_then_acquires(self):
        """Simulates old instance releasing lock after one poll cycle."""
        from bot.graceful_handoff import acquire_writer_lock_with_handoff

        call_count = {"n": 0}

        def _get_side_effect(key):
            call_count["n"] += 1
            if call_count["n"] <= 2:
                # First two calls: lock still held
                return "old-token:old-instance"
            # Third call: lock released
            return None

        def _pttl_side_effect(key):
            if call_count["n"] <= 2:
                return 15000  # 15s remaining
            return -2  # absent

        mock_client = MagicMock()
        mock_client.get.side_effect = _get_side_effect
        mock_client.pttl.side_effect = _pttl_side_effect
        mock_client.set.return_value = True
        mock_client.incr.return_value = 4
        mock_client.delete.return_value = 1

        with patch("bot.graceful_handoff._get_redis_client", return_value=mock_client):
            result = acquire_writer_lock_with_handoff(
                instance_id="new-instance",
                handoff_wait_timeout_s=5.0,
            )

        self.assertTrue(result.acquired)
        self.assertTrue(result.waited_for_release)
        self.assertFalse(result.forced)
        self.assertEqual(result.generation, 4)

    def test_force_acquire_after_timeout(self):
        """Simulates old instance never releasing — force-acquire after timeout."""
        from bot.graceful_handoff import acquire_writer_lock_with_handoff

        mock_client = MagicMock()
        # Lock always held
        mock_client.get.return_value = "old-token:old-instance"
        mock_client.pttl.return_value = 5000
        # First SET NX fails (lock still held), second succeeds after delete
        mock_client.set.side_effect = [False, True]
        mock_client.incr.return_value = 5
        mock_client.delete.return_value = 1

        with patch("bot.graceful_handoff._get_redis_client", return_value=mock_client):
            result = acquire_writer_lock_with_handoff(
                instance_id="new-instance",
                handoff_wait_timeout_s=0.1,  # very short timeout
            )

        self.assertTrue(result.acquired)
        self.assertTrue(result.forced)
        self.assertEqual(result.generation, 5)


# ---------------------------------------------------------------------------
# LockHeartbeat
# ---------------------------------------------------------------------------


class TestLockHeartbeat(unittest.TestCase):
    def test_heartbeat_renews_lock(self):
        from bot.graceful_handoff import LockHeartbeat

        mock_client = MagicMock()
        mock_client.get.return_value = "token:instance"
        mock_client.pexpire.return_value = True
        mock_client.set.return_value = True

        hb = LockHeartbeat(
            lock_key="nija:writer_lock:test",
            lock_value="token:instance",
            lock_ttl_s=30.0,
            meta_key="nija:writer_lock_meta:test",
            meta_payload_fn=lambda: '{"token":"token"}',
            interval_s=0.05,
        )

        with patch("bot.graceful_handoff._get_redis_client", return_value=mock_client):
            hb._tick()

        mock_client.pexpire.assert_called_once()
        self.assertFalse(hb.is_lost)

    def test_heartbeat_detects_stolen_lock(self):
        from bot.graceful_handoff import LockHeartbeat

        lost_reasons = []

        mock_client = MagicMock()
        # Lock value has changed — stolen by another instance
        mock_client.get.return_value = "other-token:other-instance"

        hb = LockHeartbeat(
            lock_key="nija:writer_lock:test",
            lock_value="my-token:my-instance",
            lock_ttl_s=30.0,
            meta_key="nija:writer_lock_meta:test",
            meta_payload_fn=lambda: "{}",
            interval_s=0.05,
            on_lock_lost=lambda reason: lost_reasons.append(reason),
        )

        with patch("bot.graceful_handoff._get_redis_client", return_value=mock_client):
            hb._tick()

        self.assertTrue(hb.is_lost)
        self.assertEqual(len(lost_reasons), 1)
        self.assertIn("lock_stolen", lost_reasons[0])

    def test_heartbeat_detects_expired_lock(self):
        from bot.graceful_handoff import LockHeartbeat

        lost_reasons = []

        mock_client = MagicMock()
        # Lock key is gone (expired)
        mock_client.get.return_value = None

        hb = LockHeartbeat(
            lock_key="nija:writer_lock:test",
            lock_value="my-token:my-instance",
            lock_ttl_s=30.0,
            meta_key="nija:writer_lock_meta:test",
            meta_payload_fn=lambda: "{}",
            interval_s=0.05,
            on_lock_lost=lambda reason: lost_reasons.append(reason),
        )

        with patch("bot.graceful_handoff._get_redis_client", return_value=mock_client):
            hb._tick()

        self.assertTrue(hb.is_lost)
        self.assertEqual(len(lost_reasons), 1)
        self.assertIn("lock_expired", lost_reasons[0])


if __name__ == "__main__":
    unittest.main()
