"""Regression tests for bounded heartbeat-only market discovery (v208)."""
from __future__ import annotations

import os
import threading
import time
import unittest
from unittest.mock import patch

from bot.runtime_heartbeat_probe_pipeline_bridge_v197_patch import (
    _wrap_heartbeat_market_discovery_method,
)


class _Broker:
    def __init__(self) -> None:
        self.release = threading.Event()
        self.calls = 0

    def get_available_markets(self):
        self.calls += 1
        self.release.wait(5.0)
        return ["BTC-USD"]


class HeartbeatMarketDiscoveryBoundV208Tests(unittest.TestCase):
    def test_heartbeat_thread_times_out_to_empty_markets(self) -> None:
        broker = _Broker()
        wrapped = _wrap_heartbeat_market_discovery_method(
            _Broker.get_available_markets,
            broker_class_name="TestBroker",
            method_name="get_available_markets",
        )
        result = []

        def run() -> None:
            result.append(wrapped(broker))

        with patch.dict(
            os.environ,
            {"NIJA_HEARTBEAT_MARKET_DISCOVERY_TIMEOUT_S": "0.5"},
            clear=False,
        ):
            started = time.monotonic()
            thread = threading.Thread(target=run, name="HeartbeatTrade-test")
            thread.start()
            thread.join(1.5)
            elapsed = time.monotonic() - started

        self.assertFalse(thread.is_alive())
        self.assertEqual(result, [[]])
        self.assertLess(elapsed, 1.25)
        broker.release.set()

    def test_normal_thread_behavior_is_unchanged(self) -> None:
        class FastBroker:
            def get_available_markets(self):
                return ["BTC-USD", "ETH-USD"]

        broker = FastBroker()
        wrapped = _wrap_heartbeat_market_discovery_method(
            FastBroker.get_available_markets,
            broker_class_name="FastBroker",
            method_name="get_available_markets",
        )
        self.assertEqual(wrapped(broker), ["BTC-USD", "ETH-USD"])


if __name__ == "__main__":
    unittest.main()
