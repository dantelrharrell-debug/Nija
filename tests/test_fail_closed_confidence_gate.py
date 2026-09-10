"""Regression and threshold-sweep coverage for the confidence risk envelope."""

import os
import unittest
from unittest.mock import patch

from bot import nija_apex_strategy_v71 as apex_module
from bot.hf_scalping_mode import HFScalpingMode


class FailClosedConfidenceGateTests(unittest.TestCase):
    """Prove weak signals cannot bypass the entry gate or sizing path."""

    @staticmethod
    def _strategy() -> apex_module.NIJAApexStrategyV71:
        strategy = apex_module.NIJAApexStrategyV71.__new__(
            apex_module.NIJAApexStrategyV71
        )
        strategy._get_broker_name = lambda: "coinbase"
        strategy._resolve_broker_min_notional_usd = lambda _broker: 10.0
        strategy._hf_min_confidence = 0.15
        return strategy

    def test_hf_environment_cannot_lower_confidence_floor(self) -> None:
        env = {
            "HF_SCALP_MODE": "true",
            "HF_MIN_CONFIDENCE": "0.05",
            "HF_SCALP_ENFORCE_SAFETY_FLOOR": "true",
        }
        with patch.dict(os.environ, env, clear=False):
            mode = HFScalpingMode()

        self.assertEqual(mode.config.min_confidence, 0.15)

    def test_low_confidence_is_rejected_before_adaptive_size_bump(self) -> None:
        with (
            patch.object(apex_module, "ADAPTIVE_MIN_SIZING_AVAILABLE", True),
            patch.object(
                apex_module,
                "get_adaptive_minimum_sizer",
                side_effect=AssertionError("low-confidence trade reached adaptive sizing"),
            ),
        ):
            result = self._strategy()._validate_trade_quality(
                position_size=11.0,
                score=0.5,
                account_balance=100.0,
            )

        self.assertFalse(result["valid"])
        self.assertLess(result["confidence"], 0.15)
        self.assertIn("mandatory floor", result["reason"])

    def test_confidence_at_floor_can_continue_to_size_validation(self) -> None:
        threshold_score = 0.15 * apex_module.MAX_ENTRY_SCORE
        with patch.object(apex_module, "ADAPTIVE_MIN_SIZING_AVAILABLE", False):
            result = self._strategy()._validate_trade_quality(
                position_size=11.0,
                score=threshold_score,
                account_balance=100.0,
            )

        self.assertTrue(result["valid"])
        self.assertEqual(result["confidence"], 0.15)

    def test_threshold_sweep_blocks_every_subfloor_signal(self) -> None:
        """Backtest the entry gate across the complete 0.00-1.00 score range."""
        strategy = self._strategy()
        with patch.object(apex_module, "ADAPTIVE_MIN_SIZING_AVAILABLE", False):
            decisions = {
                confidence: strategy._validate_trade_quality(
                    position_size=11.0,
                    score=confidence * apex_module.MAX_ENTRY_SCORE,
                    account_balance=100.0,
                )["valid"]
                for confidence in (index / 100 for index in range(101))
            }

        blocked = [value for value, valid in decisions.items() if not valid]
        admitted = [value for value, valid in decisions.items() if valid]
        self.assertEqual(blocked, [index / 100 for index in range(15)])
        self.assertEqual(admitted[0], 0.15)
        self.assertEqual(admitted[-1], 1.0)


if __name__ == "__main__":
    unittest.main()
