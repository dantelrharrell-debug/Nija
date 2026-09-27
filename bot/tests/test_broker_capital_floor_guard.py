from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from bot.broker_capital_floor_guard import evaluate_broker_capital_floor


class TestBrokerCapitalFloorGuard(unittest.TestCase):
    def test_alpaca_entry_allows_when_projected_equity_stays_above_floor(self):
        decision = evaluate_broker_capital_floor(
            broker_name="alpaca",
            equity_usd=2500.0,
            order_size_usd=100.0,
            side="buy",
            stop_loss_pct=0.02,
        )
        self.assertTrue(decision.allowed)
        self.assertIn(decision.state, {"GREEN", "YELLOW"})
        self.assertEqual(decision.hard_floor_usd, 2000.0)
        self.assertEqual(decision.required_floor_usd, 2250.0)

    def test_alpaca_entry_blocks_before_projected_equity_crosses_floor(self):
        decision = evaluate_broker_capital_floor(
            broker_name="alpaca",
            equity_usd=2255.0,
            order_size_usd=100.0,
            side="buy",
            stop_loss_pct=0.02,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.state, "RED")
        self.assertEqual(decision.reason, "projected_equity_below_protected_floor")

    def test_exit_is_allowed_even_below_floor(self):
        decision = evaluate_broker_capital_floor(
            broker_name="alpaca",
            equity_usd=1990.0,
            order_size_usd=250.0,
            side="sell",
            intent_type="exit",
            reduce_only=True,
        )
        self.assertTrue(decision.allowed)
        self.assertEqual(decision.state, "EXIT_ONLY")

    def test_dynamic_maintenance_margin_can_raise_kraken_floor(self):
        decision = evaluate_broker_capital_floor(
            broker_name="kraken",
            equity_usd=950.0,
            order_size_usd=50.0,
            side="buy",
            maintenance_margin_usd=480.0,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.required_floor_usd, 960.0)

    def test_margin_ratio_blocks_new_exposure(self):
        decision = evaluate_broker_capital_floor(
            broker_name="coinbase",
            equity_usd=500.0,
            order_size_usd=20.0,
            side="buy",
            margin_ratio=0.55,
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.state, "RED")
        self.assertIn("margin_ratio_too_high", decision.reason)

    def test_missing_equity_fails_closed_for_entry(self):
        decision = evaluate_broker_capital_floor(
            broker_name="okx",
            equity_usd=None,
            order_size_usd=10.0,
            side="buy",
        )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "account_equity_unavailable")

    def test_environment_override_is_respected(self):
        with patch.dict(
            os.environ,
            {"NIJA_KRAKEN_PROTECTED_FLOOR_USD": "900"},
            clear=False,
        ):
            decision = evaluate_broker_capital_floor(
                broker_name="kraken",
                equity_usd=905.0,
                order_size_usd=100.0,
                side="buy",
            )
        self.assertFalse(decision.allowed)
        self.assertEqual(decision.required_floor_usd, 900.0)


if __name__ == "__main__":
    unittest.main()
