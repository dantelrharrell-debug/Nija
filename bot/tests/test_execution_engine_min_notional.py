import unittest
from unittest.mock import patch

from bot.execution_engine import ExecutionEngine


class _FakeNotionalGate:
    def __init__(self, minimum: float) -> None:
        self.minimum = minimum

    def validate_entry_size(
        self,
        *,
        symbol,
        size_usd,
        is_stop_loss=False,
        broker_name=None,
        balance=0.0,
    ):
        if size_usd < self.minimum:
            return False, f"Entry size ${size_usd:.2f} below minimum notional ${self.minimum:.2f} USD"
        return True, None

    def adjust_size_to_minimum(self, size_usd, broker_name=None, balance=0.0):
        return max(size_usd, self.minimum)


class TestExecutionEngineMinimumNotional(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = ExecutionEngine()

    def test_minimum_notional_gate_auto_adjusts_when_affordable(self) -> None:
        fake_gate = _FakeNotionalGate(5.0)
        with patch("bot.execution_engine.MIN_NOTIONAL_GATE_AVAILABLE", True), patch(
            "bot.execution_engine.get_minimum_notional_gate",
            return_value=fake_gate,
        ):
            size, reason = self.engine._apply_minimum_notional_gate(
                symbol="BTC-USD",
                position_size=3.0,
                broker_name="coinbase",
                balance_usd=10.0,
                affordable_usd=8.0,
            )
        self.assertEqual(size, 5.0)
        self.assertIsNone(reason)

    def test_minimum_notional_gate_rejects_when_adjustment_exceeds_affordable_balance(self) -> None:
        fake_gate = _FakeNotionalGate(5.0)
        with patch("bot.execution_engine.MIN_NOTIONAL_GATE_AVAILABLE", True), patch(
            "bot.execution_engine.get_minimum_notional_gate",
            return_value=fake_gate,
        ):
            size, reason = self.engine._apply_minimum_notional_gate(
                symbol="BTC-USD",
                position_size=3.0,
                broker_name="coinbase",
                balance_usd=10.0,
                affordable_usd=4.0,
            )
        self.assertIsNone(size)
        self.assertIn("below minimum", reason or "")
