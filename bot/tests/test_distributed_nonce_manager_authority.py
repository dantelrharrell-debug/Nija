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


if __name__ == "__main__":
    unittest.main()
