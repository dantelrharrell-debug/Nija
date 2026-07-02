from __future__ import annotations

import unittest
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

# Import the real execution_pipeline module (syntax errors previously required a stub).
import bot.execution_pipeline as _ep_real  # noqa: F401  # ensure it's fully loaded

from bot import broker_manager
from bot import broker_integration
from bot import live_broker_adapters
from bot.live_broker_adapters import AlpacaEquityBrokerAdapter
from bot.multi_asset_executor import CoinbaseBrokerAdapter


class LiveBrokerAdapterAuthorityTests(unittest.TestCase):
    def test_disconnected_adapter_returns_hard_error_not_simulated_fill(self):
        with patch(
            "bot.live_broker_adapters.can_execute",
            return_value=SimpleNamespace(allowed=True, reason="ok"),
        ), patch(
            "bot.live_broker_adapters.can_execute_startup_probe",
            return_value=(False, "no_probe"),
        ):
            adapter = AlpacaEquityBrokerAdapter(api_key=None, api_secret=None, paper=True)
            result = adapter.place_order("AAPL", "BUY", 1.0)

        self.assertEqual(result.get("status"), "ERROR")
        self.assertEqual(result.get("error"), "BROKER_ADAPTER_NOT_CONNECTED")


class MultiAssetAdapterBypassTests(unittest.TestCase):
    def test_coinbase_adapter_without_client_fails_closed(self):
        with patch("bot.multi_asset_executor.assert_distributed_writer_authority", return_value=None), patch(
            "bot.multi_asset_executor.has_execution_authority",
            return_value=True,
        ):
            result = CoinbaseBrokerAdapter(client=None).place_order("BTC-USD", "BUY", 0.01)

        self.assertEqual(result.get("status"), "ERROR")
        self.assertEqual(result.get("error"), "BROKER_ADAPTER_NOT_CONNECTED")


class BrokerManagerCapitalAuthorityTests(unittest.TestCase):
    def test_authoritative_balance_reads_from_capital_authority(self):
        fake_authority = SimpleNamespace(
            is_hydrated=True,
            get_raw_per_broker=lambda broker_id: 123.45 if broker_id == "coinbase" else 0.0,
        )
        with patch("bot.capital_authority.get_capital_authority", return_value=fake_authority):
            balance = broker_manager._get_authoritative_broker_balance_usd("coinbase")

        self.assertEqual(balance, 123.45)

    def test_authoritative_balance_fails_closed_when_not_hydrated(self):
        fake_authority = SimpleNamespace(
            is_hydrated=False,
            get_raw_per_broker=lambda broker_id: 100.0,
        )
        with patch("bot.capital_authority.get_capital_authority", return_value=fake_authority):
            with self.assertRaises(RuntimeError):
                broker_manager._get_authoritative_broker_balance_usd("coinbase")


class KillSwitchFeedbackLoopContractTests(unittest.TestCase):
    """Verify that authority-gate denials never record exchange-level order rejections.

    Background: recording denials as exchange rejections caused a feedback loop —
    high rejection rate → ExchangeKillSwitchProtector triggered EMERGENCY_STOP →
    more can_execute() denials → even more recorded rejections → infinite loop.
    These tests pin the invariant across all three broker layers.
    """

    _DENIED = SimpleNamespace(allowed=False, reason="state_machine=EMERGENCY_STOP")
    _NO_PROBE = (False, "no_probe")

    # ------------------------------------------------------------------
    # broker_integration._reject_if_unauthorized_order_submit
    # ------------------------------------------------------------------

    def test_broker_integration_authority_denial_does_not_record_kill_switch_rejection(self):
        """broker_integration: denied can_execute() must raise ExecutionBlocked, NOT record an order rejection."""
        protector = MagicMock()

        with patch("bot.broker_integration.can_execute", return_value=self._DENIED), \
             patch("bot.broker_integration.can_execute_startup_probe", return_value=self._NO_PROBE), \
             patch("bot.broker_integration.emit_pretrade_execution_validator_trace"), \
             patch("bot.broker_integration.get_exchange_kill_switch_protector", return_value=protector):
            with self.assertRaises(Exception):
                broker_integration._reject_if_unauthorized_order_submit(
                    "coinbase", "BTC-USD", "buy", 1.0
                )

        protector.record_order_result.assert_not_called()
        protector.record_order_submission.assert_not_called()
        protector.record_api_call.assert_not_called()

    def test_broker_integration_authority_denial_raises_execution_blocked(self):
        """broker_integration: authority denial raises ExecutionBlocked (not a silent return)."""
        from bot.broker_integration import ExecutionBlocked

        with patch("bot.broker_integration.can_execute", return_value=self._DENIED), \
             patch("bot.broker_integration.can_execute_startup_probe", return_value=self._NO_PROBE), \
             patch("bot.broker_integration.emit_pretrade_execution_validator_trace"):
            with self.assertRaises(ExecutionBlocked):
                broker_integration._reject_if_unauthorized_order_submit(
                    "kraken", "ETH/USD", "sell", 0.5
                )

    # ------------------------------------------------------------------
    # broker_manager._reject_if_unauthorized_order_submit
    # ------------------------------------------------------------------

    def test_broker_manager_authority_denial_does_not_record_kill_switch_rejection(self):
        """broker_manager: denied can_execute() must raise ExecutionBlocked, NOT record an order rejection."""
        protector = MagicMock()

        with patch("bot.broker_manager.can_execute", return_value=self._DENIED), \
             patch("bot.broker_manager.can_execute_startup_probe", return_value=self._NO_PROBE), \
             patch("bot.broker_manager.emit_pretrade_execution_validator_trace"), \
             patch("bot.broker_manager.get_exchange_kill_switch_protector", return_value=protector):
            with self.assertRaises(Exception):
                broker_manager._reject_if_unauthorized_order_submit(
                    "kraken", "BTC/USD", "buy", 1.0
                )

        protector.record_order_result.assert_not_called()
        protector.record_order_submission.assert_not_called()
        protector.record_api_call.assert_not_called()

    def test_broker_manager_authority_denial_raises_execution_blocked(self):
        """broker_manager: authority denial raises ExecutionBlocked (not a silent return)."""
        from bot.broker_manager import ExecutionBlocked

        with patch("bot.broker_manager.can_execute", return_value=self._DENIED), \
             patch("bot.broker_manager.can_execute_startup_probe", return_value=self._NO_PROBE), \
             patch("bot.broker_manager.emit_pretrade_execution_validator_trace"):
            with self.assertRaises(ExecutionBlocked):
                broker_manager._reject_if_unauthorized_order_submit(
                    "kraken", "ETH/USD", "sell", 0.5
                )

    # ------------------------------------------------------------------
    # live_broker_adapters._authority_blocked
    # ------------------------------------------------------------------

    def test_live_broker_adapters_authority_denial_does_not_record_kill_switch_rejection(self):
        """live_broker_adapters: denied can_execute() must return an error dict, NOT record an order rejection."""
        protector = MagicMock()

        with patch("bot.live_broker_adapters.can_execute", return_value=self._DENIED), \
             patch("bot.live_broker_adapters.can_execute_startup_probe", return_value=self._NO_PROBE), \
             patch("bot.live_broker_adapters.emit_pretrade_execution_validator_trace"), \
             patch("bot.live_broker_adapters.get_exchange_kill_switch_protector", return_value=protector):
            result = live_broker_adapters._authority_blocked("alpaca", "AAPL", "BUY", 10.0)

        self.assertIsNotNone(result)
        self.assertEqual(result.get("status"), "ERROR")
        protector.record_order_result.assert_not_called()
        protector.record_order_submission.assert_not_called()
        protector.record_api_call.assert_not_called()

    def test_live_broker_adapters_authority_allowed_returns_none(self):
        """live_broker_adapters: allowed can_execute() must return None so the order proceeds."""
        _allowed = SimpleNamespace(allowed=True, reason="ok")

        with patch("bot.live_broker_adapters.can_execute", return_value=_allowed), \
             patch("bot.live_broker_adapters.emit_pretrade_execution_validator_trace"):
            result = live_broker_adapters._authority_blocked("alpaca", "AAPL", "BUY", 10.0)

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
