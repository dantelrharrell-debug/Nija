import os
import unittest
import types
import sys
from unittest.mock import Mock, patch

if "redis" not in sys.modules:
    _redis_stub = types.ModuleType("redis")
    _redis_stub.from_url = lambda *args, **kwargs: None
    sys.modules["redis"] = _redis_stub

from bot.distributed_nonce_manager import (
    DistributedNonceManager,
    _PerKeyRedisBackend,
    _REDIS_NONCE_RESET_BUFFER_MS,
    _emit_nonce_debug_hook,
)
from bot import global_kraken_nonce as gkn


class _FakeRedisBackend:
    def __init__(self, *, lease_ok: bool = True, last_value: int = 0, raise_on_get_last: bool = False) -> None:
        self.lease_ok = lease_ok
        self.last_value = last_value
        self.raise_on_get_last = raise_on_get_last

    def ensure_writer_lease(self, _key_id: str) -> int:
        if not self.lease_ok:
            raise RuntimeError("lease failed")
        return 1

    def next_nonce(self, _key_id: str) -> int:
        self.last_value += 1
        return self.last_value

    def get_last(self, _key_id: str) -> int:
        if self.raise_on_get_last:
            raise RuntimeError("redis get_last failed")
        return self.last_value

    def advance_to_floor(self, _key_id: str, *, floor_ms: int) -> tuple[int, int]:
        before = self.last_value
        self.last_value = max(self.last_value, int(floor_ms))
        return before, self.last_value


class TestDistributedNonceManagerAuthority(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch("bot.distributed_nonce_manager.assert_startup_write_authority", return_value=None)
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_get_nonce_rejects_empty_key_id(self) -> None:
        mgr = DistributedNonceManager(redis_client=None)
        with self.assertRaises(ValueError):
            mgr.get_nonce("")

    def test_can_issue_nonce_uses_redis_lease_without_file_manager(self) -> None:
        mgr = DistributedNonceManager(redis_client=None)
        mgr._redis = _FakeRedisBackend(lease_ok=True)
        mgr._get_file_manager = Mock(side_effect=AssertionError("file manager should not be consulted in redis mode"))

        with patch("bot.distributed_nonce_manager._get_nonce_auth", return_value=True):
            self.assertTrue(mgr.can_issue_nonce("test-key"))

        mgr._get_file_manager.assert_not_called()

    def test_get_last_nonce_does_not_fallback_to_file_when_redis_present(self) -> None:
        mgr = DistributedNonceManager(redis_client=None)
        mgr._redis = _FakeRedisBackend(raise_on_get_last=True)
        mgr._get_file_manager = Mock(side_effect=AssertionError("file manager should not be consulted in redis mode"))

        self.assertEqual(mgr.get_last_nonce("test-key"), 0)
        mgr._get_file_manager.assert_not_called()

    def test_record_success_calls_helper_without_nonce_argument(self) -> None:
        mgr = DistributedNonceManager(redis_client=None)
        helper = Mock()
        mgr._get_file_manager = Mock(return_value=helper)

        mgr.record_success("test-key", 123456)

        helper.record_success.assert_called_once_with()

    def test_get_nonce_redis_failure_raises_when_redis_configured(self) -> None:
        """No file fallback when Redis backend is configured: RuntimeError is raised."""
        mgr = DistributedNonceManager(redis_client=None)

        class _FailingRedisBackend(_FakeRedisBackend):
            def next_nonce(self, _key_id: str) -> int:  # type: ignore[override]
                raise ConnectionError("redis gone")

        mgr._redis = _FailingRedisBackend(lease_ok=True)

        with self.assertRaises(RuntimeError) as ctx:
            mgr.get_nonce("test-key")

        self.assertIn("refusing file/fcntl fallback", str(ctx.exception))
        self.assertIn("single-writer Redis authority", str(ctx.exception))

    def test_record_error_skips_file_manager_in_redis_mode(self) -> None:
        """record_error() must NOT consult KrakenNonceManager when Redis is active."""
        mgr = DistributedNonceManager(redis_client=None)
        mgr._redis = _FakeRedisBackend(lease_ok=True)
        mgr._get_file_manager = Mock(side_effect=AssertionError("file manager must not be consulted in redis mode"))

        # Should complete without error and without touching the file manager.
        mgr.record_error("test-key")

        mgr._get_file_manager.assert_not_called()

    def test_record_success_skips_file_manager_in_redis_mode(self) -> None:
        """record_success() must NOT consult KrakenNonceManager when Redis is active."""
        mgr = DistributedNonceManager(redis_client=None)
        mgr._redis = _FakeRedisBackend(lease_ok=True)
        mgr._get_file_manager = Mock(side_effect=AssertionError("file manager must not be consulted in redis mode"))

        # Should complete without error and without touching the file manager.
        mgr.record_success("test-key", 123456)

        mgr._get_file_manager.assert_not_called()


class TestPerKeyRedisBackendReset(unittest.TestCase):
    def test_reset_sets_near_now_floor_instead_of_deleting_key(self) -> None:
        fake_client = Mock()
        backend = _PerKeyRedisBackend.__new__(_PerKeyRedisBackend)
        backend._client = fake_client
        backend._KEY_PREFIX = "nija:kraken:nonce:"

        with patch("bot.distributed_nonce_manager.time.time", return_value=1000.0):
            backend.reset("kid")

        expected_floor = int(1000.0 * 1000) + _REDIS_NONCE_RESET_BUFFER_MS
        fake_client.set.assert_called_once_with("nija:kraken:nonce:kid", str(expected_floor))
        fake_client.delete.assert_not_called()

    def test_advance_to_floor_never_lowers_existing_redis_nonce(self) -> None:
        backend = _PerKeyRedisBackend.__new__(_PerKeyRedisBackend)
        backend._client = Mock()
        backend._KEY_PREFIX = "nija:kraken:nonce:"
        backend.get_last = Mock(return_value=9_000_000)
        backend._advance_floor_script = None

        before, after = backend.advance_to_floor("kid", floor_ms=1_500_000)

        self.assertEqual(before, 9_000_000)
        self.assertEqual(after, 9_000_000)
        backend._client.set.assert_called_once_with("nija:kraken:nonce:kid", "9000000")


class TestDistributedNonceProbeServerSync(unittest.TestCase):
    def setUp(self) -> None:
        patcher = patch("bot.distributed_nonce_manager.assert_startup_write_authority", return_value=None)
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_probe_server_sync_advances_redis_to_startup_future_floor(self) -> None:
        mgr = DistributedNonceManager(redis_client=None)
        mgr._redis = _FakeRedisBackend(last_value=100)

        with patch("bot.distributed_nonce_manager.time.time", return_value=1000.0), patch.dict(
            os.environ, {"NIJA_STARTUP_NONCE_RESYNC_FUTURE_MS": "123456"}, clear=False
        ):
            mgr.probe_server_sync("kid")

        self.assertEqual(mgr.get_last_nonce("kid"), 1_123_456)

    def test_probe_server_sync_never_lowers_stale_high_redis_nonce(self) -> None:
        mgr = DistributedNonceManager(redis_client=None)
        mgr._redis = _FakeRedisBackend(last_value=9_000_000)

        with patch("bot.distributed_nonce_manager.time.time", return_value=1000.0), patch.dict(
            os.environ, {"NIJA_STARTUP_NONCE_RESYNC_FUTURE_MS": "123456"}, clear=False
        ):
            mgr.probe_server_sync("kid")

        self.assertEqual(mgr.get_last_nonce("kid"), 9_000_000)


class TestDistributedNonceDebugHooks(unittest.TestCase):
    def test_nonce_debug_hook_emits_only_when_enabled(self) -> None:
        with patch("bot.distributed_nonce_manager._nonce_debug_hooks_enabled", return_value=False), patch(
            "bot.distributed_nonce_manager._logger.warning"
        ) as warn_disabled:
            _emit_nonce_debug_hook("test", key_id="abc")
            warn_disabled.assert_not_called()

        with patch("bot.distributed_nonce_manager._nonce_debug_hooks_enabled", return_value=True), patch(
            "bot.distributed_nonce_manager._logger.warning"
        ) as warn_enabled:
            _emit_nonce_debug_hook("test", key_id="abc")
            warn_enabled.assert_called_once()


class TestGlobalKrakenNonceRecovery(unittest.TestCase):
    def test_ensure_live_manager_rebuilds_destroyed_singleton_when_authorized(self) -> None:
        replacement_mgr = object()
        with patch.object(gkn, "_NONCE_ISSUANCE_AUTHORIZED", True), patch.object(
            gkn.KrakenNonceManager, "_instance", None
        ), patch.object(gkn, "_nonce_manager", None), patch.object(
            gkn, "_wait_for_probe_window", return_value=True
        ), patch.object(
            gkn, "rebuild_nonce_manager", return_value=replacement_mgr
        ) as rebuild:
            self.assertIs(gkn._ensure_live_manager(), replacement_mgr)
            rebuild.assert_called_once_with()

    def test_ensure_live_manager_raises_when_rebuild_fails(self) -> None:
        with patch.object(gkn, "_NONCE_ISSUANCE_AUTHORIZED", True), patch.object(
            gkn.KrakenNonceManager, "_instance", None
        ), patch.object(gkn, "_wait_for_probe_window", return_value=True), patch.object(
            gkn, "rebuild_nonce_manager", side_effect=RuntimeError("boom")
        ), patch.object(gkn, "_last_rebuild_failure_monotonic", 0.0), patch.object(
            gkn, "_last_rebuild_failure_error", None
        ), patch.object(gkn, "_consecutive_rebuild_failures", 0), patch.object(
            gkn, "_last_rebuild_cooldown_diag_monotonic", 0.0
        ):
            with self.assertRaises(RuntimeError) as ctx:
                gkn._ensure_live_manager()
        self.assertIn("rebuild failed", str(ctx.exception).lower())

    def test_ensure_live_manager_applies_rebuild_cooldown_after_failure(self) -> None:
        with patch.object(gkn, "_NONCE_ISSUANCE_AUTHORIZED", True), patch.object(
            gkn.KrakenNonceManager, "_instance", None
        ), patch.object(gkn, "_wait_for_probe_window", return_value=True), patch.object(
            gkn, "_REBUILD_RETRY_COOLDOWN_S", 30.0
        ), patch.object(
            gkn, "_last_rebuild_failure_monotonic", 0.0
        ), patch.object(
            gkn, "_last_rebuild_failure_error", None
        ), patch.object(
            gkn, "_consecutive_rebuild_failures", 0
        ), patch.object(
            gkn, "_last_rebuild_cooldown_diag_monotonic", 0.0
        ), patch.object(
            gkn, "time"
        ) as mocked_time, patch.object(
            gkn, "rebuild_nonce_manager", side_effect=RuntimeError("boom")
        ) as rebuild:
            mocked_time.monotonic.side_effect = [100.0, 101.0, 105.0]
            with self.assertRaises(RuntimeError) as first:
                gkn._ensure_live_manager()
            self.assertIn("rebuild failed", str(first.exception).lower())

            with self.assertRaises(RuntimeError) as second:
                gkn._ensure_live_manager()
            self.assertIn("retry suppressed", str(second.exception).lower())
            self.assertEqual(rebuild.call_count, 1)

    def test_ensure_live_manager_increments_consecutive_failure_counter(self) -> None:
        """Each rebuild failure increments _consecutive_rebuild_failures."""
        with patch.object(gkn, "_NONCE_ISSUANCE_AUTHORIZED", True), patch.object(
            gkn.KrakenNonceManager, "_instance", None
        ), patch.object(gkn, "_wait_for_probe_window", return_value=True), patch.object(
            gkn, "_REBUILD_RETRY_COOLDOWN_S", 0.0
        ), patch.object(gkn, "_last_rebuild_failure_monotonic", 0.0), patch.object(
            gkn, "_last_rebuild_failure_error", None
        ), patch.object(gkn, "_last_rebuild_cooldown_diag_monotonic", 0.0), patch.object(
            gkn, "rebuild_nonce_manager", side_effect=RuntimeError("fail")
        ):
            for expected in range(1, 4):
                with self.assertRaises(RuntimeError):
                    gkn._ensure_live_manager()
                self.assertEqual(gkn._consecutive_rebuild_failures, expected)

    def test_ensure_live_manager_resets_counter_on_success(self) -> None:
        """A successful rebuild resets _consecutive_rebuild_failures to 0."""
        replacement_mgr = object()
        with patch.object(gkn, "_NONCE_ISSUANCE_AUTHORIZED", True), patch.object(
            gkn.KrakenNonceManager, "_instance", None
        ), patch.object(gkn, "_nonce_manager", None), patch.object(
            gkn, "_wait_for_probe_window", return_value=True
        ), patch.object(gkn, "_REBUILD_RETRY_COOLDOWN_S", 0.0), patch.object(
            gkn, "_last_rebuild_failure_monotonic", 0.0
        ), patch.object(gkn, "_last_rebuild_failure_error", None), patch.object(
            gkn, "_last_rebuild_cooldown_diag_monotonic", 0.0
        ), patch.object(
            gkn, "rebuild_nonce_manager", return_value=replacement_mgr
        ):
            # Seed a non-zero count to verify reset.
            gkn._consecutive_rebuild_failures = 5
            gkn._ensure_live_manager()
            self.assertEqual(gkn._consecutive_rebuild_failures, 0)

    def test_ensure_live_manager_logs_error_on_rebuild_failure(self) -> None:
        """The actual exception must be logged (not silently swallowed) when rebuild fails."""
        with patch.object(gkn, "_NONCE_ISSUANCE_AUTHORIZED", True), patch.object(
            gkn.KrakenNonceManager, "_instance", None
        ), patch.object(gkn, "_wait_for_probe_window", return_value=True), patch.object(
            gkn, "_REBUILD_RETRY_COOLDOWN_S", 0.0
        ), patch.object(gkn, "_last_rebuild_failure_monotonic", 0.0), patch.object(
            gkn, "_last_rebuild_failure_error", None
        ), patch.object(gkn, "_consecutive_rebuild_failures", 0), patch.object(
            gkn, "_last_rebuild_cooldown_diag_monotonic", 0.0
        ), patch.object(
            gkn, "rebuild_nonce_manager", side_effect=RuntimeError("auth_failure_detail")
        ), patch.object(gkn._logger, "error") as mock_error:
            with self.assertRaises(RuntimeError):
                gkn._ensure_live_manager()
        # The actual exception message must appear in the error log.
        logged_args = " ".join(str(a) for call in mock_error.call_args_list for a in call.args)
        self.assertIn("auth_failure_detail", logged_args)

    def test_ensure_live_manager_logs_credential_hint_after_repeated_failures(self) -> None:
        """After 3+ failures with an auth-related message, a credential hint is logged."""
        with patch.object(gkn, "_NONCE_ISSUANCE_AUTHORIZED", True), patch.object(
            gkn.KrakenNonceManager, "_instance", None
        ), patch.object(gkn, "_wait_for_probe_window", return_value=True), patch.object(
            gkn, "_REBUILD_RETRY_COOLDOWN_S", 0.0
        ), patch.object(gkn, "_last_rebuild_failure_monotonic", 0.0), patch.object(
            gkn, "_last_rebuild_failure_error", None
        ), patch.object(gkn, "_consecutive_rebuild_failures", 2), patch.object(
            gkn, "_last_rebuild_cooldown_diag_monotonic", 0.0
        ), patch.object(
            gkn, "rebuild_nonce_manager",
            side_effect=RuntimeError("EAPI:Invalid key — check credentials"),
        ), patch.object(gkn._logger, "error") as mock_error:
            with self.assertRaises(RuntimeError):
                gkn._ensure_live_manager()
        logged_args = " ".join(str(a) for call in mock_error.call_args_list for a in call.args)
        self.assertIn("KRAKEN_PLATFORM_API_KEY", logged_args)

    def test_get_consecutive_rebuild_failures_returns_counter(self) -> None:
        gkn._consecutive_rebuild_failures = 7
        self.assertEqual(gkn.get_consecutive_rebuild_failures(), 7)
        gkn._consecutive_rebuild_failures = 0


class TestPublishLockAcquiredStateNonOverwrite(unittest.TestCase):
    """Regression tests for fencing-token overwrite bug.

    When the process writer lock (bot.py) has already established
    NIJA_WRITER_FENCING_TOKEN, _publish_lock_acquired_state must NOT
    overwrite it with the nonce lease version.  Doing so causes
    assert_distributed_writer_authority() to compare the nonce-lease token
    against the Redis process-lock key and always find a mismatch.
    """

    def _make_mgr(self) -> "_PerKeyRedisBackend":
        """Create a minimal _PerKeyRedisBackend instance without a real Redis client."""
        backend = _PerKeyRedisBackend.__new__(_PerKeyRedisBackend)
        return backend

    def setUp(self) -> None:
        # Ensure a clean env state before each test.
        for key in ("NIJA_LOCK_ACQUIRED", "NIJA_WRITER_FENCING_TOKEN", "NIJA_WRITER_LEASE_ACQUIRED"):
            os.environ.pop(key, None)

    def tearDown(self) -> None:
        for key in ("NIJA_LOCK_ACQUIRED", "NIJA_WRITER_FENCING_TOKEN", "NIJA_WRITER_LEASE_ACQUIRED"):
            os.environ.pop(key, None)

    def test_sets_fencing_token_when_process_lock_not_yet_established(self) -> None:
        """When NIJA_WRITER_LEASE_ACQUIRED is absent, the nonce lease token IS written."""
        mgr = self._make_mgr()
        mgr._publish_lock_acquired_state(42)
        self.assertEqual(os.environ.get("NIJA_WRITER_FENCING_TOKEN"), "42")
        self.assertEqual(os.environ.get("NIJA_LOCK_ACQUIRED"), "true")

    def test_does_not_overwrite_fencing_token_when_process_lock_established(self) -> None:
        """When NIJA_WRITER_LEASE_ACQUIRED=1 (process lock token=15), the nonce lease
        version (28) must NOT overwrite NIJA_WRITER_FENCING_TOKEN."""
        os.environ["NIJA_WRITER_FENCING_TOKEN"] = "15"
        os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "1"

        mgr = self._make_mgr()
        mgr._publish_lock_acquired_state(28)

        # Token must remain 15 (the process lock token), not 28 (nonce lease).
        self.assertEqual(os.environ.get("NIJA_WRITER_FENCING_TOKEN"), "15")
        # NIJA_LOCK_ACQUIRED is still set.
        self.assertEqual(os.environ.get("NIJA_LOCK_ACQUIRED"), "true")

    def test_does_not_overwrite_for_any_truthy_lease_acquired_value(self) -> None:
        """All recognised truthy values of NIJA_WRITER_LEASE_ACQUIRED protect the token."""
        for truthy in ("1", "true", "yes", "on", "enabled"):
            with self.subTest(truthy=truthy):
                os.environ["NIJA_WRITER_FENCING_TOKEN"] = "15"
                os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = truthy
                mgr = self._make_mgr()
                mgr._publish_lock_acquired_state(99)
                self.assertEqual(os.environ.get("NIJA_WRITER_FENCING_TOKEN"), "15",
                                 f"Token overwritten when NIJA_WRITER_LEASE_ACQUIRED={truthy!r}")

    def test_overwrites_when_lease_acquired_is_falsy(self) -> None:
        """A falsy NIJA_WRITER_LEASE_ACQUIRED still allows the nonce manager to set the token."""
        for falsy in ("", "0", "false", "no"):
            with self.subTest(falsy=falsy):
                os.environ["NIJA_WRITER_FENCING_TOKEN"] = "15"
                os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = falsy
                mgr = self._make_mgr()
                mgr._publish_lock_acquired_state(99)
                self.assertEqual(os.environ.get("NIJA_WRITER_FENCING_TOKEN"), "99",
                                 f"Token not updated when NIJA_WRITER_LEASE_ACQUIRED={falsy!r}")


class TestLeaseStatusLogging(unittest.TestCase):
    def _make_backend(self) -> "_PerKeyRedisBackend":
        backend = _PerKeyRedisBackend.__new__(_PerKeyRedisBackend)
        backend._client = Mock()
        backend._lease_status_last_log = {}
        backend._owner_instance_id = "instance-123"
        backend._owner_fingerprint = "fp-123"
        backend._lease_by_key = {
            "kid": _PerKeyRedisBackend._LeaseState(
                version=7,
                owner_id="owner-123",
                stable_since=90.0,
                last_renewed_at=95.0,
            )
        }
        return backend

    def test_zero_interval_suppresses_steady_state_lease_status_logs(self) -> None:
        backend = self._make_backend()

        with patch("bot.distributed_nonce_manager._REDIS_LEASE_STATUS_LOG_INTERVAL_S", 0.0), patch(
            "bot.distributed_nonce_manager._logger.info"
        ) as mock_info, patch("bot.distributed_nonce_manager.time.monotonic", return_value=100.0):
            backend._log_lease_status("kid", 7, "owner-123")

        mock_info.assert_not_called()
        backend._client.pttl.assert_not_called()

    def test_force_logging_still_emits_when_periodic_status_logs_are_disabled(self) -> None:
        backend = self._make_backend()
        backend._client.pttl.return_value = 60000

        with patch("bot.distributed_nonce_manager._REDIS_LEASE_STATUS_LOG_INTERVAL_S", 0.0), patch(
            "bot.distributed_nonce_manager._logger.info"
        ) as mock_info, patch("bot.distributed_nonce_manager.time.monotonic", return_value=100.0):
            backend._log_lease_status("kid", 7, "owner-123", force=True)

        mock_info.assert_called_once()
        backend._client.pttl.assert_called_once()

    def test_positive_interval_rate_limits_periodic_status_logs(self) -> None:
        backend = self._make_backend()
        backend._client.pttl.return_value = 60000

        with patch("bot.distributed_nonce_manager._REDIS_LEASE_STATUS_LOG_INTERVAL_S", 30.0), patch(
            "bot.distributed_nonce_manager._logger.info"
        ) as mock_info, patch(
            "bot.distributed_nonce_manager.time.monotonic",
            side_effect=[100.0, 110.0, 131.0],
        ):
            backend._log_lease_status("kid", 7, "owner-123")
            backend._log_lease_status("kid", 7, "owner-123")
            backend._log_lease_status("kid", 7, "owner-123")

        self.assertEqual(mock_info.call_count, 2)
        self.assertEqual(backend._client.pttl.call_count, 2)


if __name__ == "__main__":
    unittest.main()
