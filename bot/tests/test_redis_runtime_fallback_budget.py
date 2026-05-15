from __future__ import annotations

import os
import sys
import types
import unittest
from unittest.mock import patch

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)
sys.modules.setdefault("redis", types.SimpleNamespace(Redis=types.SimpleNamespace(from_url=lambda *args, **kwargs: object())))

from bot.redis_runtime import connect_redis_with_fallback


class TestRedisRuntimeFallbackBudget(unittest.TestCase):
    @patch("bot.redis_runtime._detect_non_redis_http_endpoint", return_value="")
    @patch("bot.redis_runtime._prioritized_alt_urls", return_value=["redis://alt.internal:6379/0"])
    @patch("bot.redis_runtime.wait_for_redis_ready", side_effect=RuntimeError("redis unavailable"))
    @patch("bot.redis_runtime.create_redis", return_value=object())
    @patch("bot.redis_runtime.time.monotonic", side_effect=[0.0, 0.60, 1.20, 1.20, 1.20])
    def test_connect_redis_with_fallback_honors_total_budget(
        self,
        _mock_monotonic,
        mock_create_redis,
        _mock_wait_ready,
        _mock_alt_urls,
        _mock_non_redis_probe,
    ):
        with self.assertRaises(RuntimeError) as ctx:
            connect_redis_with_fallback(
                url="redis://primary.internal:6379/0",
                retries=5,
                delay_s=2.0,
                max_total_wait_s=1.0,
                log=lambda _msg: None,
            )
        self.assertIn("budget exhausted", str(ctx.exception).lower())
        self.assertEqual(mock_create_redis.call_count, 1)


if __name__ == "__main__":
    unittest.main()
