from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import pandas as pd

from bot.control.strategy_detectors import BreakRetestDetector, DetectorContext
from bot.control.trading_context import TradingContext


def _context() -> DetectorContext:
    trading = TradingContext(
        user_id="fvg-test-user",
        trading_account_id="fvg-test-account",
        broker="paper",
        broker_account_id="paper-account",
        strategy_instance_id="BREAK_RETEST",
        portfolio_id="fvg-test-portfolio",
        request_id="fvg-test-request",
        correlation_id="fvg-test-correlation",
        environment="backtest",
        mode="backtest",
    )
    return DetectorContext(
        symbol="BTC-USD",
        broker="paper",
        market_regime="trending",
        trading_context=trading,
    )


def _frame(direction: str, *, with_fvg: bool) -> pd.DataFrame:
    rows = [
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 100.0}
        for _ in range(40)
    ]
    if direction == "long":
        if with_fvg:
            rows[-4] = {"open": 99.8, "high": 100.2, "low": 99.4, "close": 100.0, "volume": 100.0}
        rows[-2] = {"open": 100.5, "high": 103.0, "low": 100.4, "close": 102.0, "volume": 150.0}
        rows[-1] = {"open": 101.0, "high": 102.2, "low": 100.8, "close": 101.7, "volume": 120.0}
    else:
        if with_fvg:
            rows[-4] = {"open": 100.2, "high": 100.6, "low": 99.8, "close": 100.0, "volume": 100.0}
        rows[-2] = {"open": 99.5, "high": 99.6, "low": 97.0, "close": 98.0, "volume": 150.0}
        rows[-1] = {"open": 99.0, "high": 99.2, "low": 97.8, "close": 98.3, "volume": 120.0}
    return pd.DataFrame(rows)


class TestBreakRetestFvgGate(unittest.TestCase):
    def test_bullish_fvg_is_required_and_recorded(self):
        with patch.dict(os.environ, {"NIJA_BREAK_RETEST_REQUIRE_FVG": "true"}):
            signal = BreakRetestDetector().detect(_frame("long", with_fvg=True), _context())

        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, "long")
        self.assertIn("bullish_fvg_confirmed", signal.supporting_evidence)
        self.assertTrue(signal.metadata["fvg_required"])
        self.assertEqual(signal.metadata["fvg_direction"], "bullish")
        self.assertGreater(signal.metadata["fvg_high"], signal.metadata["fvg_low"])
        self.assertGreater(signal.metadata["fvg_gap_size"], 0.0)

    def test_bullish_entry_fails_closed_without_required_fvg(self):
        with patch.dict(os.environ, {"NIJA_BREAK_RETEST_REQUIRE_FVG": "true"}):
            signal = BreakRetestDetector().detect(_frame("long", with_fvg=False), _context())
        self.assertIsNone(signal)

    def test_bearish_fvg_is_required_and_recorded(self):
        with patch.dict(os.environ, {"NIJA_BREAK_RETEST_REQUIRE_FVG": "true"}):
            signal = BreakRetestDetector().detect(_frame("short", with_fvg=True), _context())

        self.assertIsNotNone(signal)
        self.assertEqual(signal.direction, "short")
        self.assertIn("bearish_fvg_confirmed", signal.supporting_evidence)
        self.assertTrue(signal.metadata["fvg_required"])
        self.assertEqual(signal.metadata["fvg_direction"], "bearish")
        self.assertGreater(signal.metadata["fvg_high"], signal.metadata["fvg_low"])

    def test_fvg_gate_has_explicit_rollback_switch(self):
        with patch.dict(os.environ, {"NIJA_BREAK_RETEST_REQUIRE_FVG": "false"}):
            signal = BreakRetestDetector().detect(_frame("long", with_fvg=False), _context())

        self.assertIsNotNone(signal)
        self.assertFalse(signal.metadata["fvg_required"])
        self.assertNotIn("bullish_fvg_confirmed", signal.supporting_evidence)


if __name__ == "__main__":
    unittest.main()
