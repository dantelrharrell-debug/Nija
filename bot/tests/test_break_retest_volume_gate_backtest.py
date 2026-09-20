from __future__ import annotations

import unittest

import pandas as pd

from bot.control.strategy_detectors import BreakRetestDetector, DetectorContext
from bot.control.trading_context import TradingContext


def _ctx() -> TradingContext:
    return TradingContext(
        user_id="backtest-user",
        trading_account_id="backtest-account",
        broker="kraken",
        broker_account_id="backtest-broker-account",
        strategy_instance_id="BREAK_RETEST",
        portfolio_id="backtest-portfolio",
        request_id="backtest-request",
        correlation_id="backtest-correlation",
        environment="backtest",
        mode="backtest",
        decision_id="backtest-decision",
    )


def _frame(direction: str, *, volume: float) -> pd.DataFrame:
    rows = [
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": volume}
        for _ in range(40)
    ]
    if direction == "long":
        rows[-2] = {"open": 100.5, "high": 103.0, "low": 100.4, "close": 102.0, "volume": volume * 1.5}
        rows[-1] = {"open": 101.0, "high": 102.2, "low": 100.8, "close": 101.7, "volume": volume * 1.2}
    else:
        rows[-2] = {"open": 99.5, "high": 99.6, "low": 97.0, "close": 98.0, "volume": volume * 1.5}
        rows[-1] = {"open": 99.0, "high": 99.2, "low": 97.8, "close": 98.3, "volume": volume * 1.2}
    return pd.DataFrame(rows)


class BreakRetestVolumeGateBacktest(unittest.TestCase):
    """Deterministic 120-scenario backtest for the volume-gate change.

    Scope: verify that the stricter volume requirement removes only setups with
    unavailable/non-positive volume while preserving otherwise-identical
    positive-volume long/short break-and-retest setups and their protection
    geometry.
    """

    def test_volume_gate_non_degradation_on_valid_data(self):
        detector = BreakRetestDetector()
        context = DetectorContext(
            symbol="BTC-USD",
            broker="kraken",
            trading_context=_ctx(),
            market_regime="trending",
        )
        emitted_positive = 0
        emitted_zero = 0
        long_count = 0
        short_count = 0

        for i in range(120):
            direction = "long" if i % 2 == 0 else "short"
            positive_volume = i < 60
            df = _frame(direction, volume=100.0 if positive_volume else 0.0)
            signal = detector.detect(df, context)

            if positive_volume:
                self.assertIsNotNone(signal, f"valid-volume scenario {i} unexpectedly rejected")
                emitted_positive += 1
                if signal.direction == "long":
                    long_count += 1
                else:
                    short_count += 1
                self.assertIsNotNone(signal.suggested_stop)
                self.assertTrue(signal.target_candidates)
                if signal.direction == "long":
                    self.assertLess(signal.suggested_stop, float(df.iloc[-1]["close"]))
                    self.assertGreater(signal.target_candidates[0], float(df.iloc[-1]["close"]))
                else:
                    self.assertGreater(signal.suggested_stop, float(df.iloc[-1]["close"]))
                    self.assertLess(signal.target_candidates[0], float(df.iloc[-1]["close"]))
            else:
                self.assertIsNone(signal, f"zero-volume scenario {i} should be rejected")
                emitted_zero += int(signal is not None)

        self.assertEqual(emitted_positive, 60)
        self.assertEqual(emitted_zero, 0)
        self.assertEqual(long_count, 30)
        self.assertEqual(short_count, 30)


if __name__ == "__main__":
    unittest.main()
