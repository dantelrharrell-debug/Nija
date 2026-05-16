import unittest
from unittest.mock import Mock, patch

from bot.distributed_nonce_manager import (
    DistributedNonceManager,
    _PerKeyRedisBackend,
    _REDIS_NONCE_RESET_BUFFER_MS,
)


class _FakeRedisBackend:
    def __init__(self, *, lease_ok: bool = True, last_value: int = 0, raise_on_get_last: bool = False) -> None:
        self.lease_ok = lease_ok
        self.last_value = last_value
        self.raise_on_get_last = raise_on_get_last

    def ensure_writer_lease(self, _key_id: str) -> int:
        if not self.lease_ok:
            raise RuntimeError("lease failed")
        return 1

    def get_last(self, _key_id: str) -> int:
        if self.raise_on_get_last:
            raise RuntimeError("redis get_last failed")
        return self.last_value


class TestDistributedNonceManagerAuthority(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
