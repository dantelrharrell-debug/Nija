"""Regression/path tests for research adaptive exit policy v388.

Uses unittest so NIJA's canonical CI baseline runner discovers these tests.
The suite intentionally exercises pure policy helpers only; it does not mutate
process-wide runtime patch ownership and therefore cannot contaminate unrelated
CI tests.
"""
from __future__ import annotations

import unittest

from bot import runtime_research_adaptive_exit_v388_patch as v388


def _trailing_exit_index(
    prices: list[float], activation: float, distance: float
) -> int | None:
    entry = prices[0]
    high = entry
    armed = False
    for idx, price in enumerate(prices[1:], start=1):
        high = max(high, price)
        if high >= entry * (1 + activation):
            armed = True
        if armed and price <= high * (1 - distance):
            return idx
    return None


class TestResearchAdaptiveExitV388(unittest.TestCase):
    def test_hard_stop_uses_atr_1_5x_with_three_percent_cap(self) -> None:
        self.assertAlmostEqual(v388.hard_stop_pct({}, atr_pct=0.005), 0.015)
        self.assertAlmostEqual(v388.hard_stop_pct({}, atr_pct=0.012), 0.018)
        self.assertAlmostEqual(v388.hard_stop_pct({}, atr_pct=0.030), 0.030)

    def test_risk_unit_uses_actual_verified_stop_distance(self) -> None:
        row = {"entry_price": 100.0, "stop_loss": 98.0, "quantity": 1.0}
        self.assertAlmostEqual(v388.risk_unit_pct(row), 0.02)

    def test_universal_fallback_targets_are_r_based(self) -> None:
        row = {"entry_price": 100.0, "stop_loss": 98.5, "quantity": 1.0}
        tp1, tp2, tp3 = v388.fallback_tp_pcts(row)
        self.assertAlmostEqual(tp1, 0.0225)
        self.assertAlmostEqual(tp2, 0.0300)
        self.assertAlmostEqual(tp3, 0.0450)
        self.assertGreater(tp1, 0.005)  # old v239 TP1 was 0.5%

    def test_atr_aware_targets_keep_first_target_outside_two_atr(self) -> None:
        row = {
            "entry_price": 100.0,
            "stop_loss": 97.0,
            "quantity": 1.0,
            "atr_pct": 0.02,
        }
        tp1, tp2, tp3 = v388.fallback_tp_pcts(row)
        self.assertGreaterEqual(tp1, 2.0 * row["atr_pct"])
        self.assertLess(tp1, tp2)
        self.assertLess(tp2, tp3)

    def test_trailing_stop_arms_at_one_r_near_breakeven(self) -> None:
        row = {"entry_price": 100.0, "stop_loss": 98.5, "quantity": 1.0}
        settings = v388.trailing_pcts(row)
        activation = float(settings["trailing_stop_activation_pct"])
        distance = float(settings["trailing_stop_distance_pct"])
        self.assertAlmostEqual(activation, 0.015)
        self.assertAlmostEqual(distance, 0.015)
        peak = 100.0 * (1 + activation)
        boundary = peak * (1 - distance)
        self.assertAlmostEqual(boundary, 99.9775, places=4)

    def test_trailing_take_profit_arms_at_two_r(self) -> None:
        row = {"entry_price": 100.0, "stop_loss": 98.5, "quantity": 1.0}
        settings = v388.trailing_pcts(row)
        activation = float(settings["trailing_take_profit_activation_pct"])
        callback = float(settings["trailing_take_profit_callback_pct"])
        self.assertAlmostEqual(activation, 0.030)
        self.assertAlmostEqual(callback, 0.01125)
        self.assertLess(callback, v388.risk_unit_pct(row))

    def test_path_backtest_adaptive_trail_avoids_old_noise_whipsaw(self) -> None:
        # Deterministic regression path, not a profitability forecast.
        prices = [100.0, 101.05, 100.60, 101.50, 102.00, 102.30]
        old_exit = _trailing_exit_index(
            prices, activation=0.010, distance=0.0035
        )
        row = {"entry_price": 100.0, "stop_loss": 98.5, "quantity": 1.0}
        settings = v388.trailing_pcts(row)
        new_exit = _trailing_exit_index(
            prices,
            activation=float(settings["trailing_stop_activation_pct"]),
            distance=float(settings["trailing_stop_distance_pct"]),
        )
        self.assertEqual(old_exit, 2)
        self.assertIsNone(new_exit)
        tp1, _, _ = v388.fallback_tp_pcts(row)
        self.assertGreaterEqual(prices[-1], 100.0 * (1 + tp1))

    def test_short_side_uses_same_risk_geometry(self) -> None:
        row = {
            "entry_price": 100.0,
            "stop_loss": 101.5,
            "quantity": 1.0,
            "side": "short",
        }
        self.assertAlmostEqual(v388.risk_unit_pct(row), 0.015)
        tp1, tp2, tp3 = v388.fallback_tp_pcts(row)
        self.assertAlmostEqual(tp1, 0.0225)
        self.assertAlmostEqual(tp2, 0.0300)
        self.assertAlmostEqual(tp3, 0.0450)


if __name__ == "__main__":
    unittest.main()
