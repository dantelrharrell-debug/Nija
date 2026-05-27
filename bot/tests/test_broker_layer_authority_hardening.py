from __future__ import annotations

import unittest
import sys
import types
from types import SimpleNamespace
from unittest.mock import patch

# execution_pipeline currently contains a repository-level syntax error.
# Inject a minimal stub so imports in broker modules can still resolve.
if "bot.execution_pipeline" not in sys.modules:
    _stub = types.ModuleType("bot.execution_pipeline")
    _stub.get_execution_pipeline = lambda: None
    _stub.PipelineRequest = object
    sys.modules["bot.execution_pipeline"] = _stub
    sys.modules.setdefault("execution_pipeline", _stub)

from bot import broker_manager
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


if __name__ == "__main__":
    unittest.main()
