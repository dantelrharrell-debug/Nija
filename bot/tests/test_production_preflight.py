from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bot.production_preflight import _step5_clear_stale_locks


class _FakeRedis:
    def __init__(self, ttls: dict[str, int]) -> None:
        self._ttls = dict(ttls)
        self.deleted: list[str] = []

    def pttl(self, key: str) -> int:
        return self._ttls.get(key, -2)

    def delete(self, key: str) -> int:
        if key in self._ttls:
            del self._ttls[key]
            self.deleted.append(key)
            return 1
        return 0


class ProductionPreflightStep5Tests(unittest.TestCase):
    def test_preserves_persistent_authority_and_nonce_lineage_keys(self) -> None:
        redis_client = _FakeRedis(
            {
                "nija:writer_lock:test": 55_000,
                "nija:lease:generation": -1,
                "nija:kraken:writer:version_counter:test": -1,
                "nija:kraken:nonce:test": -1,
            }
        )

        fake_scan = SimpleNamespace(
            safe_scan=lambda *_args, **_kwargs: iter(
                [
                    "nija:lease:generation",
                    "nija:kraken:writer:version_counter:test",
                    "nija:kraken:nonce:test",
                ]
            )
        )
        with patch.dict("sys.modules", {"bot.redis_runtime": fake_scan}):
            _step5_clear_stale_locks(redis_client)

        self.assertEqual(redis_client.deleted, [])

    def test_preserves_active_writer_fence_key(self) -> None:
        redis_client = _FakeRedis(
            {
                "nija:writer_lock:test": 55_000,
                "nija:writer_fence:test": -1,
            }
        )

        fake_scan = SimpleNamespace(
            safe_scan=lambda *_args, **_kwargs: iter(["nija:writer_fence:test"])
        )
        with patch.dict("sys.modules", {"bot.redis_runtime": fake_scan}), patch.dict(
            "os.environ",
            {
                "NIJA_WRITER_LOCK_KEY": "nija:writer_lock:test",
                "NIJA_WRITER_FENCING_KEY": "nija:writer_fence:test",
            },
        ):
            _step5_clear_stale_locks(redis_client)

        self.assertNotIn("nija:writer_fence:test", redis_client.deleted)

    def test_clears_non_active_stale_writer_fence_key(self) -> None:
        redis_client = _FakeRedis(
            {
                "nija:writer_lock:test": 55_000,
                "nija:writer_fence:old": -1,
            }
        )

        fake_scan = SimpleNamespace(
            safe_scan=lambda *_args, **_kwargs: iter(["nija:writer_fence:old"])
        )
        with patch.dict("sys.modules", {"bot.redis_runtime": fake_scan}), patch.dict(
            "os.environ",
            {
                "NIJA_WRITER_LOCK_KEY": "nija:writer_lock:test",
                "NIJA_WRITER_FENCING_KEY": "nija:writer_fence:test",
            },
        ):
            _step5_clear_stale_locks(redis_client)

        self.assertIn("nija:writer_fence:old", redis_client.deleted)


if __name__ == "__main__":
    unittest.main()
