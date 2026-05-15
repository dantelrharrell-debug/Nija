import os
import unittest
from unittest.mock import patch

from bot.redis_env import get_all_redis_urls, get_redis_url, get_redis_url_source


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


if __name__ == "__main__":
    unittest.main()
