import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bot.execution_engine import ExecutionEngine


class _BrokerStub:
    broker_type = "coinbase"

    def supports_symbol(self, _symbol: str) -> bool:
        return True


class TestExecuteEntryRejectionLogging(unittest.TestCase):
    def test_bootstrap_gate_emits_flushed_rejection_breadcrumb(self) -> None:
        engine = ExecutionEngine()
        fake_fsm = SimpleNamespace(
            state="BOOT",
            has_execution_authority=lambda: False,
        )

        stdout = io.StringIO()
        with patch("bot.bootstrap_state_machine.get_bootstrap_fsm", return_value=fake_fsm), patch.dict(
            "os.environ",
            {"FORCE_TRADE": "false", "FORCE_TRADE_MODE": "false"},
            clear=False,
        ), redirect_stdout(stdout):
            result = engine.execute_entry(
                symbol="ADA-USD",
                side="long",
                position_size=12.0,
                entry_price=1.0,
                stop_loss=0.9,
                take_profit_levels={"tp1": 1.1, "tp2": 1.2, "tp3": 1.3},
            )

        self.assertIsNone(result)
        output = stdout.getvalue()
        self.assertIn("[NIJA-PRINT] execute_entry REJECTED", output)
        self.assertIn("bootstrap_execution_authority_false", output)

    def test_missing_order_id_emits_rejection_breadcrumb(self) -> None:
        engine = ExecutionEngine(broker_client=_BrokerStub())
        engine._get_cached_balance_snapshot = MagicMock(return_value=(100.0, 100.0, {}))
        engine.can_execute_trade = MagicMock(return_value=True)
        engine._is_expectancy_bucket_blocked = MagicMock(return_value=False)
        engine._optimize_execution_with_intelligence = MagicMock(return_value=None)
        engine._apply_minimum_notional_gate = MagicMock(return_value=(12.0, None))
        engine._compute_kelly_fraction = MagicMock(return_value=1.0)
        engine._submit_market_order_via_pipeline = MagicMock(return_value={"status": "filled"})
        engine._emit_execution_result = MagicMock()
        engine._confirm_order_fill = MagicMock(side_effect=lambda *_args: {"status": "filled"})
        engine._extract_fill_price = MagicMock(return_value=1.0)
        engine._validate_entry_price = MagicMock(return_value=True)

        fake_fsm = SimpleNamespace(
            state="LIVE",
            has_execution_authority=lambda: True,
        )

        stdout = io.StringIO()
        with patch("bot.bootstrap_state_machine.get_bootstrap_fsm", return_value=fake_fsm), patch(
            "bot.execution_engine.FORCE_TRADE_MODE", True
        ), patch("bot.execution_engine.RECOVERY_CONTROLLER_AVAILABLE", False), patch(
            "bot.execution_engine.HARD_CONTROLS_AVAILABLE", False
        ), patch(
            "bot.execution_engine.EXCHANGE_ORDER_COMPILER_AVAILABLE", False
        ), patch(
            "bot.execution_engine.EXECUTION_INTELLIGENCE_AVAILABLE", False
        ), redirect_stdout(stdout):
            result = engine.execute_entry(
                symbol="ADA-USDC",
                side="long",
                position_size=12.0,
                entry_price=1.0,
                stop_loss=0.998,
                take_profit_levels={"tp1": 1.05, "tp2": 1.1, "tp3": 1.15},
            )

        self.assertIsNone(result)
        output = stdout.getvalue()
        self.assertIn("[NIJA-PRINT] execute_entry REJECTED", output)
        self.assertIn("missing_order_id", output)

    def test_entry_price_validation_failure_emits_rejection_breadcrumb(self) -> None:
        engine = ExecutionEngine(broker_client=_BrokerStub())
        engine._get_cached_balance_snapshot = MagicMock(return_value=(100.0, 100.0, {}))
        engine.can_execute_trade = MagicMock(return_value=True)
        engine._is_expectancy_bucket_blocked = MagicMock(return_value=False)
        engine._optimize_execution_with_intelligence = MagicMock(return_value=None)
        engine._apply_minimum_notional_gate = MagicMock(return_value=(12.0, None))
        engine._compute_kelly_fraction = MagicMock(return_value=1.0)
        engine._submit_market_order_via_pipeline = MagicMock(
            return_value={"status": "filled", "order_id": "ord-123"}
        )
        engine._emit_execution_result = MagicMock()
        engine._confirm_order_fill = MagicMock(
            side_effect=lambda *_args: {"status": "filled", "order_id": "ord-123"}
        )
        engine._extract_fill_price = MagicMock(return_value=1.0)
        engine._validate_entry_price = MagicMock(return_value=False)

        fake_fsm = SimpleNamespace(
            state="LIVE",
            has_execution_authority=lambda: True,
        )

        stdout = io.StringIO()
        with patch("bot.bootstrap_state_machine.get_bootstrap_fsm", return_value=fake_fsm), patch(
            "bot.execution_engine.FORCE_TRADE_MODE", True
        ), patch("bot.execution_engine.RECOVERY_CONTROLLER_AVAILABLE", False), patch(
            "bot.execution_engine.HARD_CONTROLS_AVAILABLE", False
        ), patch(
            "bot.execution_engine.EXCHANGE_ORDER_COMPILER_AVAILABLE", False
        ), patch(
            "bot.execution_engine.EXECUTION_INTELLIGENCE_AVAILABLE", False
        ), redirect_stdout(stdout):
            result = engine.execute_entry(
                symbol="AERO-USD",
                side="long",
                position_size=12.0,
                entry_price=1.0,
                stop_loss=0.998,
                take_profit_levels={"tp1": 1.05, "tp2": 1.1, "tp3": 1.15},
            )

        self.assertIsNone(result)
        output = stdout.getvalue()
        self.assertIn("[NIJA-PRINT] execute_entry REJECTED", output)
        self.assertIn("entry_price_validation_failed", output)
