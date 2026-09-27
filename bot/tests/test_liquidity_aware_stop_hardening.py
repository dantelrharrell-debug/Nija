from __future__ import annotations

import unittest

from bot.risk_manager import AdaptiveRiskManager


class TestLiquidityAwareStopHardening(unittest.TestCase):
    def setUp(self) -> None:
        self.risk = AdaptiveRiskManager()

    def test_long_stop_remains_beyond_swing_with_atr_buffer(self):
        stop = self.risk.calculate_stop_loss(
            entry_price=100.0,
            side="long",
            swing_level=99.0,
            atr=0.25,
        )
        # Default regime uses 1.2 ATR, so protection must remain below
        # the swing/liquidity low rather than being placed on it.
        self.assertAlmostEqual(stop, 98.7, places=6)
        self.assertLess(stop, 99.0)

    def test_short_stop_remains_beyond_swing_with_atr_buffer(self):
        stop = self.risk.calculate_stop_loss(
            entry_price=100.0,
            side="short",
            swing_level=101.0,
            atr=0.25,
        )
        self.assertAlmostEqual(stop, 101.3, places=6)
        self.assertGreater(stop, 101.0)

    def test_long_setup_fails_closed_when_safe_geometry_exceeds_risk_cap(self):
        with self.assertRaisesRegex(ValueError, "unsafe_stop_geometry"):
            self.risk.calculate_stop_loss(
                entry_price=100.0,
                side="long",
                swing_level=96.5,
                atr=0.25,
            )

    def test_short_setup_fails_closed_when_safe_geometry_exceeds_risk_cap(self):
        with self.assertRaisesRegex(ValueError, "unsafe_stop_geometry"):
            self.risk.calculate_stop_loss(
                entry_price=100.0,
                side="short",
                swing_level=103.5,
                atr=0.25,
            )

    def test_invalid_atr_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "unsafe_stop_geometry"):
            self.risk.calculate_stop_loss(
                entry_price=100.0,
                side="long",
                swing_level=99.0,
                atr=float("nan"),
            )

    def test_invalid_structure_side_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "unsafe_stop_geometry"):
            self.risk.calculate_stop_loss(
                entry_price=100.0,
                side="long",
                swing_level=101.0,
                atr=0.25,
            )

    def test_volatility_requirement_over_cap_fails_closed_instead_of_tightening(self):
        with self.assertRaisesRegex(ValueError, "unsafe_stop_geometry"):
            self.risk.calculate_stop_loss(
                entry_price=100.0,
                side="long",
                swing_level=99.5,
                atr=0.25,
                bb_width=0.08,
            )


if __name__ == "__main__":
    unittest.main()
