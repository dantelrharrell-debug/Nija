"""Regression tests for the Kraken OHLC direct-REST thread guard.

These tests protect the live fix for Railway logs that showed thousands of
pykrakenapi ``_fetch_ohlc`` threads and repeated ``can't start new thread``
errors.  The patched Kraken market-data path must avoid the legacy
``get_ohlc_data`` implementation unless the explicit emergency fallback env var
is enabled.
"""
from __future__ import annotations

import threading
import time
import types
import unittest
from unittest.mock import patch


class TestKrakenOHLCThreadGuardDirectRest(unittest.TestCase):
    def test_rows_to_candles_parses_kraken_public_ohlc_rows(self):
        from bot import kraken_ohlc_thread_guard_patch as guard

        rows = [
            [1710000000, "100.0", "110.0", "95.0", "105.0", "103.0", "12.5", 42],
            [1710000300, "105.0", "112.0", "101.0", "111.0", "108.0", "15.0", 51],
        ]
        candles = guard._rows_to_candles(rows, limit=1)

        self.assertEqual(len(candles), 1)
        self.assertEqual(candles[0]["timestamp"], 1710000300)
        self.assertEqual(candles[0]["open"], 105.0)
        self.assertEqual(candles[0]["close"], 111.0)
        self.assertEqual(candles[0]["volume"], 15.0)

    def test_patch_uses_direct_rest_and_does_not_call_legacy_original(self):
        from bot import kraken_ohlc_thread_guard_patch as guard

        module = types.ModuleType("fake_broker_integration")
        original_called = {"value": False}

        class KrakenBrokerAdapter:
            def _convert_to_kraken_symbol(self, symbol: str) -> str:
                return symbol.replace("-", "").upper()

            def get_market_data(self, symbol: str, timeframe: str = "5m", limit: int = 100):
                original_called["value"] = True
                raise AssertionError("legacy pykrakenapi path should not be called")

        module.KrakenBrokerAdapter = KrakenBrokerAdapter

        sample_payload = {
            "pair_key": "BTCUSD",
            "rows": [[1710000000, "100", "110", "95", "105", "103", "9.5", 7]],
            "last": 1710000000,
        }

        with patch.object(guard, "_public_ohlc_rest", return_value=sample_payload):
            patched = guard._patch_module(module)
            self.assertTrue(patched)
            adapter = module.KrakenBrokerAdapter()
            result = adapter.get_market_data("BTC-USD", "5m", 100)

        self.assertFalse(original_called["value"])
        self.assertIsInstance(result, dict)
        self.assertEqual(result["symbol"], "BTCUSD")
        self.assertEqual(len(result["candles"]), 1)
        self.assertEqual(result["candles"][0]["close"], 105.0)


class TestBackgroundWorkerThreadStartGuard(unittest.TestCase):
    def test_duplicate_named_background_worker_is_not_started(self):
        from bot import kraken_ohlc_thread_guard_patch as guard

        guard._install_background_worker_thread_guard()

        stop = threading.Event()
        duplicate_ran = {"value": False}

        def hold_open():
            stop.wait(timeout=2)

        def duplicate_target():
            duplicate_ran["value"] = True

        first = threading.Thread(target=hold_open, name="nija-trailing-stop", daemon=True)
        first.start()
        try:
            # Give the first thread a moment to appear in threading.enumerate().
            time.sleep(0.05)
            duplicate = threading.Thread(target=duplicate_target, name="nija-trailing-stop", daemon=True)
            duplicate.start()
            time.sleep(0.05)
            self.assertFalse(duplicate_ran["value"], "duplicate singleton worker must not run")
            self.assertFalse(duplicate.is_alive(), "duplicate singleton worker should never become alive")
        finally:
            stop.set()
            first.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
