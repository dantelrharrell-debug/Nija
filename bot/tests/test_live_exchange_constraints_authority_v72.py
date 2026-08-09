from __future__ import annotations

import importlib
import os
import types
import unittest
from unittest.mock import patch


class LiveExchangeConstraintsAuthorityV72Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = importlib.import_module("bot.live_exchange_constraints_authority_v72_patch")
        for name in self.mod.registered_constraint_providers():
            self.mod.unregister_live_constraint_provider(name)

    def test_binance_exchange_info_filters_are_normalized(self) -> None:
        rules = self.mod._extract_rules(
            {
                "filters": [
                    {"filterType": "LOT_SIZE", "minQty": "0.001", "stepSize": "0.001"},
                    {"filterType": "MIN_NOTIONAL", "minNotional": "5.0"},
                ]
            }
        )
        self.assertEqual(rules["step_size"], 0.001)
        self.assertEqual(rules["precision_decimals"], 3)
        self.assertEqual(rules["min_base_qty"], 0.001)
        self.assertEqual(rules["min_notional_usd"], 5.0)

    def test_alpaca_crypto_asset_rules_are_base_quantity_scoped(self) -> None:
        rules = self.mod._extract_rules(
            {
                "symbol": "BTC/USD",
                "min_order_size": "0.0001",
                "min_trade_increment": "0.0001",
                "price_increment": "1",
            }
        )
        self.assertEqual(rules["min_base_qty"], 0.0001)
        self.assertEqual(rules["step_size"], 0.0001)
        self.assertEqual(rules["precision_decimals"], 4)
        self.assertEqual(rules["min_notional_usd"], 0.0)

    def test_unknown_live_exchange_cannot_use_generic_fallback(self) -> None:
        fake = types.ModuleType("eoc_v72_fake")

        class Error(RuntimeError):
            pass

        class Constraints:
            def __init__(
                self,
                exchange,
                min_order_usd,
                min_notional_usd,
                fee_rate_one_way,
                step_size,
                precision_decimals,
            ):
                self.exchange = exchange
                self.min_order_usd = min_order_usd
                self.min_notional_usd = min_notional_usd
                self.fee_rate_one_way = fee_rate_one_way
                self.step_size = step_size
                self.precision_decimals = precision_decimals

        class Compiler:
            def get_constraints(self, exchange, symbol):
                return Constraints(exchange, 5.0, 5.0, 0.006, 0.00000001, 8)

        fake.OrderCompileError = Error
        fake.ExchangeConstraints = Constraints
        fake.ExchangeOrderCompiler = Compiler
        self.mod._patch(fake)
        compiler = Compiler()
        with patch.dict(
            os.environ,
            {"LIVE_CAPITAL_VERIFIED": "true", "DRY_RUN_MODE": "false", "PAPER_MODE": "false"},
            clear=False,
        ):
            with self.assertRaises(Error):
                compiler.get_constraints("futurebroker", "BTC-USD")

    def test_registered_provider_allows_future_live_exchange(self) -> None:
        fake = types.ModuleType("eoc_v72_provider_fake")

        class Error(RuntimeError):
            pass

        class Constraints:
            def __init__(
                self,
                exchange,
                min_order_usd,
                min_notional_usd,
                fee_rate_one_way,
                step_size,
                precision_decimals,
            ):
                self.exchange = exchange
                self.min_order_usd = min_order_usd
                self.min_notional_usd = min_notional_usd
                self.fee_rate_one_way = fee_rate_one_way
                self.step_size = step_size
                self.precision_decimals = precision_decimals

        class Compiler:
            def get_constraints(self, exchange, symbol):
                raise AssertionError("generic fallback should not be used")

        fake.OrderCompileError = Error
        fake.ExchangeConstraints = Constraints
        fake.ExchangeOrderCompiler = Compiler
        self.mod._patch(fake)
        self.mod.register_live_constraint_provider(
            "futurebroker",
            lambda symbol: {
                "min_order_usd": 12.0,
                "min_notional_usd": 12.0,
                "step_size": 0.01,
                "precision_decimals": 2,
                "taker_fee": 0.0015,
            },
        )
        with patch.dict(
            os.environ,
            {"LIVE_CAPITAL_VERIFIED": "true", "DRY_RUN_MODE": "false", "PAPER_MODE": "false"},
            clear=False,
        ):
            c = Compiler().get_constraints("futurebroker", "ABC-USD")
        self.assertEqual(c.min_notional_usd, 12.0)
        self.assertEqual(c.step_size, 0.01)
        self.assertEqual(c.precision_decimals, 2)
        self.assertEqual(c.fee_rate_one_way, 0.0015)

    def test_known_crypto_venues_keep_compat_static_fallback(self) -> None:
        fake = types.ModuleType("eoc_v72_compat_fake")

        class Constraints:
            def __init__(self, exchange):
                self.exchange = exchange
                self.min_order_usd = 1.0
                self.min_notional_usd = 1.0
                self.fee_rate_one_way = 0.001
                self.step_size = 0.001
                self.precision_decimals = 3

        class Compiler:
            def get_constraints(self, exchange, symbol):
                return Constraints(exchange)

        fake.OrderCompileError = RuntimeError
        fake.ExchangeConstraints = lambda **kwargs: types.SimpleNamespace(**kwargs)
        fake.ExchangeOrderCompiler = Compiler
        self.mod._patch(fake)
        with patch.dict(
            os.environ,
            {"LIVE_CAPITAL_VERIFIED": "true", "DRY_RUN_MODE": "false", "PAPER_MODE": "false"},
            clear=False,
        ):
            c = Compiler().get_constraints("okx", "BTC-USDT")
        self.assertEqual(c.exchange, "okx")


if __name__ == "__main__":
    unittest.main()
