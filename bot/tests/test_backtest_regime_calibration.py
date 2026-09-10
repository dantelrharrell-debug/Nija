from __future__ import annotations

import unittest

from scripts.backtest_regime_calibration import evaluate_walk_forward


def _trade(pnl: float, regime: str = "volatile") -> dict[str, object]:
    return {
        "symbol": "BTC-USD",
        "regime_family": regime,
        "strategy": "APEX_V71",
        "side": "long",
        "pnl": pnl,
    }


class RegimeCalibrationBacktestTests(unittest.TestCase):
    """Verify chronological evaluation and fail-closed eligibility."""

    def test_walk_forward_uses_only_prior_outcomes_and_reduces_drawdown(self) -> None:
        report = evaluate_walk_forward([_trade(-0.01) for _ in range(25)])

        self.assertEqual(report["calibration_active_trades"], 5)
        self.assertLess(report["calibrated_max_drawdown"], report["baseline_max_drawdown"])
        self.assertGreater(report["calibrated_total_return"], report["baseline_total_return"])
        self.assertTrue(report["passes_non_degradation"])

    def test_walk_forward_refuses_to_pass_without_eligible_history(self) -> None:
        report = evaluate_walk_forward([_trade(0.01) for _ in range(19)])

        self.assertEqual(report["calibration_active_trades"], 0)
        self.assertFalse(report["passes_non_degradation"])


if __name__ == "__main__":
    unittest.main()
