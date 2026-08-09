from __future__ import annotations

import importlib
import os
import types
import unittest
from unittest.mock import patch


class LiveExchangeBaseMinimumV73Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.v72 = importlib.import_module("bot.live_exchange_constraints_authority_v72_patch")
        self.v73 = importlib.import_module("bot.live_exchange_base_minimum_v73_patch")
        for name in self.v72.registered_constraint_providers():
            self.v72.unregister_live_constraint_provider(name)
        self.v73._BASE_MINIMUMS.clear()
        self.v73._install_constraint_capture()

    def _fake_eoc(self):
        fake = types.ModuleType("eoc_v73_fake")

        class Error(RuntimeError):
            pass

        class Constraints:
            def __init__(self, exchange, min_order_usd, min_notional_usd, fee_rate_one_way, step_size, precision_decimals):
                self.exchange = exchange
                self.min_order_usd = min_order_usd
                self.min_notional_usd = min_notional_usd
                self.fee_rate_one_way = fee_rate_one_way
                self.step_size = step_size
                self.precision_decimals = precision_decimals

        class Compiler:
            def get_constraints(self, exchange, symbol):
                return Constraints(exchange, 0.0, 0.0, 0.0, 0.0001, 4)

            def simulate_order(self, symbol, side, size_usd, pricing, constraints, *args, **kwargs):
                return (float(size_usd), 0.0, "ok", float(size_usd))

        fake.OrderCompileError = Error
        fake.ExchangeConstraints = Constraints
        fake.ExchangeOrderCompiler = Compiler
        return fake, Error, Compiler

    def test_alpaca_base_minimum_is_enforced_after_rounding(self) -> None:
        fake, Error, Compiler = self._fake_eoc()
        self.v72._patch(fake)
        self.v73._patch_eoc_module(fake)
        self.v72.register_live_constraint_provider(
            "alpaca",
            lambda symbol: {
                "min_order_size": "0.0001",
                "min_trade_increment": "0.0001",
                "price_increment": "0.01",
            },
        )
        with patch.dict(os.environ, {"LIVE_CAPITAL_VERIFIED": "true", "DRY_RUN_MODE": "false", "PAPER_MODE": "false"}, clear=False):
            constraints = Compiler().get_constraints("alpaca", "BTC-USD")
            with self.assertRaises(Error):
                Compiler().simulate_order("BTC-USD", "buy", 0.00005, object(), constraints)

    def test_quantity_at_base_minimum_passes(self) -> None:
        fake, _Error, Compiler = self._fake_eoc()
        self.v72._patch(fake)
        self.v73._patch_eoc_module(fake)
        self.v72.register_live_constraint_provider(
            "alpaca",
            lambda symbol: {
                "min_order_size": "0.0001",
                "min_trade_increment": "0.0001",
                "price_increment": "0.01",
            },
        )
        with patch.dict(os.environ, {"LIVE_CAPITAL_VERIFIED": "true", "DRY_RUN_MODE": "false", "PAPER_MODE": "false"}, clear=False):
            constraints = Compiler().get_constraints("alpaca", "BTC-USD")
            result = Compiler().simulate_order("BTC-USD", "buy", 0.0001, object(), constraints)
        self.assertEqual(result[0], 0.0001)

    def test_future_client_metadata_is_auto_registered(self) -> None:
        class FutureClient:
            broker_name = "futurebroker"

            def get_symbol_info(self, symbol):
                return {
                    "min_order_usd": 10.0,
                    "step_size": 0.01,
                    "precision_decimals": 2,
                }

        client = FutureClient()
        self.assertTrue(self.v73._maybe_register_broker(client))
        self.assertIn("futurebroker", self.v72.registered_constraint_providers())

    def test_future_client_without_metadata_stays_fail_closed(self) -> None:
        class FutureClient:
            broker_name = "futurebroker"

        self.assertFalse(self.v73._maybe_register_broker(FutureClient()))
        self.assertNotIn("futurebroker", self.v72.registered_constraint_providers())


if __name__ == "__main__":
    unittest.main()
