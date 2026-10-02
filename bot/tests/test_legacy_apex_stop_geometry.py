from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import pandas as pd

BOT_DIR = str(Path(__file__).resolve().parents[1])
if BOT_DIR not in sys.path:
    sys.path.insert(0, BOT_DIR)

from apex_strategy_v7 import ApexStrategyV7  # noqa: E402


class TestLegacyApexStopGeometry(unittest.TestCase):
    def setUp(self) -> None:
        # calculate_stop_loss has no instance-state dependency.
        self.strategy = ApexStrategyV7.__new__(ApexStrategyV7)
        self.df = pd.DataFrame(
            [{"open": 100.0, "high": 100.2, "low": 99.8, "close": 100.0, "volume": 1.0}]
        )

    @patch("apex_strategy_v7.find_swing_low", return_value=99.5)
    def test_long_stop_remains_below_swing_liquidity(self, _mock_swing) -> None:
        stop = self.strategy.calculate_stop_loss(self.df, {"atr": 0.1}, "long")
        self.assertLess(stop, 99.5)
        self.assertAlmostEqual(stop, 99.35, places=6)

    @patch("apex_strategy_v7.find_swing_high", return_value=100.5)
    def test_short_stop_remains_above_swing_liquidity(self, _mock_swing) -> None:
        stop = self.strategy.calculate_stop_loss(self.df, {"atr": 0.1}, "short")
        self.assertGreater(stop, 100.5)
        self.assertAlmostEqual(stop, 100.65, places=6)

    @patch("apex_strategy_v7.find_swing_low", return_value=99.0)
    def test_long_rejects_when_safe_stop_exceeds_legacy_risk_cap(self, _mock_swing) -> None:
        with self.assertRaisesRegex(ValueError, "unsafe_stop_geometry"):
            self.strategy.calculate_stop_loss(self.df, {"atr": 0.1}, "long")

    @patch("apex_strategy_v7.find_swing_high", return_value=101.0)
    def test_short_rejects_when_safe_stop_exceeds_legacy_risk_cap(self, _mock_swing) -> None:
        with self.assertRaisesRegex(ValueError, "unsafe_stop_geometry"):
            self.strategy.calculate_stop_loss(self.df, {"atr": 0.1}, "short")


if __name__ == "__main__":
    unittest.main()
