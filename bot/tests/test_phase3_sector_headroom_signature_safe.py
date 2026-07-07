"""Regression tests for Phase 3 sector-headroom wrapper signature safety.

The live Railway log showed:

    TypeError: _phase3_scan_and_enter() got multiple values for argument 'broker'

That happened because the sector-headroom wrapper treated the first wrapped
argument as ``signals`` and forwarded it positionally even when the core loop
called the canonical method with ``broker=...`` keyword arguments.  These tests
protect that exact live-call shape.
"""
from __future__ import annotations

import types
import unittest


class TestPhase3SectorHeadroomSignatureSafe(unittest.TestCase):
    def _make_fake_module(self):
        module = types.ModuleType("bot.nija_core_loop")

        class NijaCoreLoop:
            def _phase3_scan_and_enter(
                self,
                broker,
                snapshot,
                symbols,
                available_slots,
                zero_signal_streak=0,
            ):
                return {
                    "broker": broker,
                    "snapshot": snapshot,
                    "symbols": symbols,
                    "available_slots": available_slots,
                    "zero_signal_streak": zero_signal_streak,
                }

        module.NijaCoreLoop = NijaCoreLoop
        return module

    def test_keyword_broker_call_does_not_receive_duplicate_positional_broker(self):
        from bot import phase3_sector_headroom_prefilter_patch as patch

        module = self._make_fake_module()
        self.assertTrue(patch._patch_core_loop_module(module))
        loop = module.NijaCoreLoop()

        result = loop._phase3_scan_and_enter(
            broker="okx",
            snapshot="snap",
            symbols=["BTC-USDT", "ETH-USDT"],
            available_slots=8,
            zero_signal_streak=1,
        )

        self.assertEqual(result["broker"], "okx")
        self.assertEqual(result["symbols"], ["BTC-USDT", "ETH-USDT"])
        self.assertEqual(result["available_slots"], 8)
        self.assertEqual(result["zero_signal_streak"], 1)

    def test_positional_broker_call_is_passed_through_unchanged(self):
        from bot import phase3_sector_headroom_prefilter_patch as patch

        module = self._make_fake_module()
        self.assertTrue(patch._patch_core_loop_module(module))
        loop = module.NijaCoreLoop()

        result = loop._phase3_scan_and_enter(
            "kraken",
            "snap",
            ["BTC-USD", "ETH-USD"],
            3,
            2,
        )

        self.assertEqual(result["broker"], "kraken")
        self.assertEqual(result["symbols"], ["BTC-USD", "ETH-USD"])
        self.assertEqual(result["available_slots"], 3)
        self.assertEqual(result["zero_signal_streak"], 2)

    def test_symbol_list_is_not_treated_as_signal_list(self):
        from bot import phase3_sector_headroom_prefilter_patch as patch

        self.assertFalse(patch._looks_like_signal_list(["BTC-USD", "ETH-USD"]))
        self.assertTrue(patch._looks_like_signal_list([{"symbol": "BTC-USD"}]))


if __name__ == "__main__":
    unittest.main()
