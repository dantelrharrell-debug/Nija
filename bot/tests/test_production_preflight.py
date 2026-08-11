from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bot.production_preflight import (
    _credential_status,
    _step5_clear_stale_locks,
    _step7_exchange_clock_sync,
)


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


class ProductionPreflightCredentialAndClockTests(unittest.TestCase):
    def test_partial_platform_credentials_fail_as_one_incomplete_venue(self) -> None:
        with patch.dict(
            "os.environ",
            {"KRAKEN_PLATFORM_API_KEY": "configured"},
            clear=True,
        ):
            complete, incomplete = _credential_status()

        self.assertEqual(complete, [])
        self.assertEqual(
            incomplete,
            {"kraken": ["KRAKEN_PLATFORM_API_SECRET"]},
        )

    def test_complete_legacy_kraken_credentials_are_accepted(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "KRAKEN_API_KEY": "configured",
                "KRAKEN_API_SECRET": "configured",
            },
            clear=True,
        ):
            complete, incomplete = _credential_status()

        self.assertEqual(complete, ["kraken"])
        self.assertEqual(incomplete, {})

    def test_exchange_clock_accepts_bounded_skew(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "COINBASE_API_KEY": "configured",
                "COINBASE_API_SECRET": "configured",
                "NIJA_PREFLIGHT_MAX_CLOCK_SKEW_S": "2",
            },
            clear=True,
        ), patch(
            "bot.production_preflight._fetch_exchange_epoch",
            return_value=100.0,
        ), patch(
            "bot.production_preflight.time.time",
            return_value=100.0,
        ):
            _step7_exchange_clock_sync()

    def test_exchange_clock_rejects_excessive_skew(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "COINBASE_API_KEY": "configured",
                "COINBASE_API_SECRET": "configured",
                "NIJA_PREFLIGHT_MAX_CLOCK_SKEW_S": "2",
            },
            clear=True,
        ), patch(
            "bot.production_preflight._fetch_exchange_epoch",
            return_value=80.0,
        ), patch(
            "bot.production_preflight.time.time",
            return_value=100.0,
        ):
            with self.assertRaises(SystemExit):
                _step7_exchange_clock_sync()

    def test_exchange_clock_requires_at_least_one_exchange_sample(self) -> None:
        with patch.dict(
            "os.environ",
            {
                "OKX_API_KEY": "configured",
                "OKX_API_SECRET": "configured",
                "OKX_PASSPHRASE": "configured",
            },
            clear=True,
        ), patch(
            "bot.production_preflight._fetch_exchange_epoch",
            side_effect=TimeoutError("clock unavailable"),
        ):
            with self.assertRaises(SystemExit):
                _step7_exchange_clock_sync()

    def test_exchange_clock_requires_every_configured_venue_sample(self) -> None:
        def _clock(venue: str, **_kwargs) -> float:
            if venue == "coinbase":
                return 100.0
            raise TimeoutError("configured venue clock unavailable")

        with patch.dict(
            "os.environ",
            {
                "COINBASE_API_KEY": "configured",
                "COINBASE_API_SECRET": "configured",
                "OKX_API_KEY": "configured",
                "OKX_API_SECRET": "configured",
                "OKX_PASSPHRASE": "configured",
            },
            clear=True,
        ), patch(
            "bot.production_preflight._fetch_exchange_epoch",
            side_effect=_clock,
        ), patch(
            "bot.production_preflight.time.time",
            return_value=100.0,
        ):
            with self.assertRaises(SystemExit):
                _step7_exchange_clock_sync()


if __name__ == "__main__":
    unittest.main()
