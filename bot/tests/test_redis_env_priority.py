import os
import unittest
from unittest.mock import patch

from bot.redis_env import (
    get_all_redis_urls,
    get_redis_resolution_diagnostics,
    get_redis_url,
    get_redis_url_source,
)


class TestRedisEnvPriority(unittest.TestCase):
    def test_private_and_public_urls_beat_legacy_redis_url(self):
        with patch.dict(
            os.environ,
            {
                "REDIS_URL": "redis://default:pw@legacy.proxy.rlwy.net:12345/0",
                "REDIS_PRIVATE_URL": "redis://default:pw@redis.railway.internal:6379/0",
                "REDIS_PUBLIC_URL": "rediss://default:pw@redis-production-e747.up.railway.app:6379/0",
            },
            clear=True,
        ):
            self.assertEqual(get_redis_url_source(), "REDIS_PRIVATE_URL")
            self.assertEqual(get_redis_url(), "redis://default:pw@redis.railway.internal:6379/0")
            self.assertEqual(
                get_all_redis_urls(),
                [
                    ("REDIS_PRIVATE_URL", "redis://default:pw@redis.railway.internal:6379/0"),
                    ("REDIS_PUBLIC_URL", "rediss://default:pw@redis-production-e747.up.railway.app:6379/0"),
                    ("REDIS_URL", "rediss://default:pw@legacy.proxy.rlwy.net:12345/0"),
                ],
            )

    def test_legacy_redis_url_still_supported_when_explicit_urls_missing(self):
        with patch.dict(
            os.environ,
            {
                "REDIS_URL": "redis://default:pw@redis-production-e747.up.railway.app:6379/0",
            },
            clear=True,
        ):
            self.assertEqual(get_redis_url_source(), "REDIS_URL")
            self.assertEqual(get_redis_url(), "rediss://default:pw@redis-production-e747.up.railway.app:6379/0")

    def test_render_private_url_beats_stale_railway_nija_url_on_render(self):
        with patch.dict(
            os.environ,
            {
                "RENDER": "true",
                "NIJA_REDIS_URL": "redis://redis-production-e747.up.railway.app:6379",
                "REDIS_URL": "redis://red-d98dsl5aeets73fpb0hg:6379",
            },
            clear=True,
        ):
            self.assertEqual(get_redis_url_source(), "REDIS_URL")
            self.assertEqual(get_redis_url(), "redis://red-d98dsl5aeets73fpb0hg:6379")
            self.assertEqual(
                get_all_redis_urls(),
                [
                    ("REDIS_URL", "redis://red-d98dsl5aeets73fpb0hg:6379"),
                    ("NIJA_REDIS_URL", "rediss://redis-production-e747.up.railway.app:6379"),
                ],
            )
            diagnostics = get_redis_resolution_diagnostics()
            self.assertTrue(diagnostics["is_render_runtime"])
            self.assertTrue(diagnostics["is_render_private"])
            self.assertEqual(diagnostics["resolved_source"], "REDIS_URL")

    def test_false_render_flag_does_not_change_priority(self):
        with patch.dict(
            os.environ,
            {
                "RENDER": "false",
                "NIJA_REDIS_URL": "redis://redis-production-e747.up.railway.app:6379",
                "REDIS_URL": "redis://red-d98dsl5aeets73fpb0hg:6379",
            },
            clear=True,
        ):
            self.assertEqual(get_redis_url_source(), "NIJA_REDIS_URL")
            self.assertEqual(
                get_redis_url(),
                "rediss://redis-production-e747.up.railway.app:6379",
            )

    def test_stale_railway_nija_url_keeps_priority_outside_render(self):
        with patch.dict(
            os.environ,
            {
                "NIJA_REDIS_URL": "redis://redis-production-e747.up.railway.app:6379",
                "REDIS_URL": "redis://red-d98dsl5aeets73fpb0hg:6379",
            },
            clear=True,
        ):
            self.assertEqual(get_redis_url_source(), "NIJA_REDIS_URL")
            self.assertEqual(
                get_redis_url(),
                "rediss://redis-production-e747.up.railway.app:6379",
            )


if __name__ == "__main__":
    unittest.main()
