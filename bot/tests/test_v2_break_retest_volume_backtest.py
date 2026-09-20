from __future__ import annotations

import unittest

import pandas as pd

from bot.control.strategy_detectors import BreakRetestDetector, DetectorContext
from bot.control.trading_context import TradingContext


def _context() -> DetectorContext:
    trading = TradingContext(
        user_id="backtest-user",
        trading_account_id="backtest-account",
        broker="paper",
        broker_account_id="paper-account",
        strategy_instance_id="BREAK_RETEST",
        portfolio_id="paper-portfolio",
        request_id="backtest-request",
        correlation_id="backtest-correlation",
        environment="backtest",
        mode="backtest",
    )
    return DetectorContext(
        symbol="BTC-USD",
        broker="paper",
        market_regime="trending",
        trading_context=trading,
    )


def _episode(direction: str, *, volume_ok: bool) -> pd.DataFrame:
    rows = [
        {"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 100.0}
        for _ in range(40)
    ]
    volume = 150.0 if volume_ok else 0.0
    if direction == "long":
        rows[-2] = {"open": 100.5, "high": 103.0, "low": 100.4, "close": 102.0, "volume": volume}
        rows[-1] = {"open": 101.0, "high": 102.2, "low": 100.8, "close": 101.7, "volume": 120.0 if volume_ok else 0.0}
    else:
        rows[-2] = {"open": 99.5, "high": 99.6, "low": 97.0, "close": 98.0, "volume": volume}
        rows[-1] = {"open": 99.0, "high": 99.2, "low": 97.8, "close": 98.3, "volume": 120.0 if volume_ok else 0.0}
    return pd.DataFrame(rows)


class TestBreakRetestVolumeGateBacktest(unittest.TestCase):
    """Deterministic 200-episode regression backtest for the volume eligibility change."""

    def test_volume_gate_backtest(self):
        detector = BreakRetestDetector()
        context = _context()
        detected_valid = 0
        detected_zero_volume = 0

        for i in range(200):
            direction = "long" if i % 2 == 0 else "short"
            volume_ok = i < 100
            signal = detector.detect(_episode(direction, volume_ok=volume_ok), context)
            if volume_ok:
                detected_valid += int(signal is not None and signal.direction == direction)
            else:
                detected_zero_volume += int(signal is not None)

        self.assertEqual(detected_valid, 100)
        self.assertEqual(detected_zero_volume, 0)


if __name__ == "__main__":
    unittest.main()
