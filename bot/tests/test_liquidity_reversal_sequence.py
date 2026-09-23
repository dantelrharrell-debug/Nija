from __future__ import annotations

import unittest

import pandas as pd

from bot.strategies.liquidity_reversal import LiquidityReversalStrategy


def _base_rows(n: int = 60):
    return [
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 100.0}
        for _ in range(n)
    ]


def _bullish_frame() -> pd.DataFrame:
    rows = _base_rows()
    rows[-4] = {"open": 100.0, "high": 100.5, "low": 98.5, "close": 99.5, "volume": 180.0}
    rows[-3] = {"open": 99.6, "high": 100.4, "low": 99.4, "close": 100.2, "volume": 140.0}
    rows[-2] = {"open": 100.7, "high": 103.0, "low": 100.6, "close": 102.5, "volume": 160.0}
    rows[-1] = {"open": 101.0, "high": 101.2, "low": 100.55, "close": 100.8, "volume": 120.0}
    return pd.DataFrame(rows)


def _bearish_frame() -> pd.DataFrame:
    rows = _base_rows()
    rows[-4] = {"open": 100.0, "high": 101.5, "low": 99.5, "close": 100.5, "volume": 180.0}
    rows[-3] = {"open": 100.4, "high": 100.6, "low": 99.6, "close": 99.8, "volume": 140.0}
    rows[-2] = {"open": 99.3, "high": 99.4, "low": 97.0, "close": 97.5, "volume": 160.0}
    rows[-1] = {"open": 99.0, "high": 99.45, "low": 98.8, "close": 99.2, "volume": 120.0}
    return pd.DataFrame(rows)


class TestLiquidityReversalSequence(unittest.TestCase):
    def test_bullish_sequence_requires_sweep_displacement_fvg_and_retrace(self):
        strategy = LiquidityReversalStrategy()
        df = _bullish_frame()
        signal = strategy.generate_signal(df, {"rsi": pd.Series([35.0] * len(df))})

        self.assertEqual(signal["signal"], "BUY")
        self.assertGreaterEqual(signal["risk_reward"], 2.0)
        self.assertLess(signal["stop_loss"], float(df.iloc[-4]["low"]))
        self.assertTrue(signal["metadata"]["fvg_fresh"])
        self.assertTrue(signal["metadata"]["fvg_retrace_confirmed"])
        self.assertTrue(signal["metadata"]["crt_confirmed"])
        self.assertTrue(signal["metadata"]["po3_accumulation"])
        self.assertTrue(signal["metadata"]["po3_manipulation"])
        self.assertTrue(signal["metadata"]["po3_distribution"])
        self.assertTrue(signal["metadata"]["power_of_three_confirmed"])
        self.assertIn("Power of 3 confluence", signal["reason"])

    def test_bearish_sequence_requires_sweep_displacement_fvg_and_retrace(self):
        strategy = LiquidityReversalStrategy()
        df = _bearish_frame()
        signal = strategy.generate_signal(df, {"rsi": pd.Series([65.0] * len(df))})

        self.assertEqual(signal["signal"], "SELL")
        self.assertGreaterEqual(signal["risk_reward"], 2.0)
        self.assertGreater(signal["stop_loss"], float(df.iloc[-4]["high"]))
        self.assertTrue(signal["metadata"]["fvg_fresh"])
        self.assertTrue(signal["metadata"]["fvg_retrace_confirmed"])
        self.assertTrue(signal["metadata"]["power_of_three_confirmed"])

    def test_power_of_three_is_confluence_not_a_required_entry_gate(self):
        strategy = LiquidityReversalStrategy(
            {
                "po3_accumulation_max_atr": 0.25,
            }
        )
        df = _bullish_frame()
        signal = strategy.generate_signal(df, {"rsi": pd.Series([35.0] * len(df))})

        self.assertEqual(signal["signal"], "BUY")
        self.assertFalse(signal["metadata"]["po3_accumulation"])
        self.assertTrue(signal["metadata"]["po3_manipulation"])
        self.assertTrue(signal["metadata"]["po3_distribution"])
        self.assertFalse(signal["metadata"]["power_of_three_confirmed"])
        self.assertNotIn("Power of 3 confluence", signal["reason"])

    def test_power_of_three_cannot_substitute_for_missing_core_sequence(self):
        strategy = LiquidityReversalStrategy(
            {
                "po3_accumulation_max_atr": 999.0,
                "po3_max_close_drift_fraction": 999.0,
            }
        )
        df = _bullish_frame()
        df.loc[df.index[-2], ["open", "high", "low", "close"]] = [
            100.1,
            100.4,
            99.8,
            100.2,
        ]

        signal = strategy.generate_signal(df, {"rsi": pd.Series([35.0] * len(df))})

        self.assertEqual(signal["signal"], "NONE")

    def test_power_of_three_can_be_disabled_without_disabling_strategy(self):
        strategy = LiquidityReversalStrategy({"po3_enabled": False})
        df = _bullish_frame()
        signal = strategy.generate_signal(df, {"rsi": pd.Series([35.0] * len(df))})

        self.assertEqual(signal["signal"], "BUY")
        self.assertFalse(signal["metadata"]["power_of_three_confirmed"])
        self.assertFalse(signal["metadata"]["po3_accumulation"])
        self.assertFalse(signal["metadata"]["po3_manipulation"])
        self.assertTrue(signal["metadata"]["po3_distribution"])

    def test_body_close_break_is_not_misclassified_as_liquidity_sweep(self):
        strategy = LiquidityReversalStrategy()
        df = _bullish_frame()
        df.loc[df.index[-4], ["open", "close", "low"]] = [98.8, 98.6, 98.4]

        signal = strategy.generate_signal(df, {"rsi": pd.Series([35.0] * len(df))})

        self.assertEqual(signal["signal"], "NONE")

    def test_missing_displacement_fails_closed(self):
        strategy = LiquidityReversalStrategy()
        df = _bullish_frame()
        df.loc[df.index[-2], ["open", "high", "low", "close"]] = [100.1, 100.4, 99.8, 100.2]

        signal = strategy.generate_signal(df, {"rsi": pd.Series([35.0] * len(df))})

        self.assertEqual(signal["signal"], "NONE")

    def test_missing_fvg_fails_closed(self):
        strategy = LiquidityReversalStrategy()
        df = _bullish_frame()
        df.loc[df.index[-2], "low"] = 100.4

        signal = strategy.generate_signal(df, {"rsi": pd.Series([35.0] * len(df))})

        self.assertEqual(signal["signal"], "NONE")

    def test_fvg_must_be_first_touch(self):
        strategy = LiquidityReversalStrategy()
        rows = _base_rows(61)
        rows[-5] = {"open": 100.0, "high": 100.5, "low": 98.5, "close": 99.5, "volume": 180.0}
        rows[-4] = {"open": 99.6, "high": 100.4, "low": 99.4, "close": 100.2, "volume": 140.0}
        rows[-3] = {"open": 100.7, "high": 103.0, "low": 100.6, "close": 102.5, "volume": 160.0}
        rows[-2] = {"open": 101.0, "high": 101.2, "low": 100.55, "close": 101.0, "volume": 110.0}
        rows[-1] = {"open": 101.0, "high": 101.2, "low": 100.55, "close": 100.8, "volume": 120.0}
        df = pd.DataFrame(rows)

        signal = strategy.generate_signal(df, {"rsi": pd.Series([35.0] * len(df))})

        self.assertEqual(signal["signal"], "NONE")

    def test_no_retrace_into_fvg_means_no_entry(self):
        strategy = LiquidityReversalStrategy()
        df = _bullish_frame()
        df.loc[df.index[-1], ["open", "high", "low", "close"]] = [102.0, 103.0, 101.5, 102.5]

        signal = strategy.generate_signal(df, {"rsi": pd.Series([35.0] * len(df))})

        self.assertEqual(signal["signal"], "NONE")

    def test_rsi_and_volume_are_confluence_not_substitutes_for_sequence(self):
        strategy = LiquidityReversalStrategy()
        df = _bullish_frame()
        no_rsi = strategy.generate_signal(df, {})
        self.assertEqual(no_rsi["signal"], "BUY")

        broken = _bullish_frame()
        broken.loc[broken.index[-4], ["open", "close", "low"]] = [98.8, 98.6, 98.4]
        high_rsi = strategy.generate_signal(
            broken,
            {"rsi": pd.Series([10.0] * len(broken))},
        )
        self.assertEqual(high_rsi["signal"], "NONE")


if __name__ == "__main__":
    unittest.main()
