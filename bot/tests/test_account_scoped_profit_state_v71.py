from __future__ import annotations

import importlib
import types
import unittest


class AccountScopedProfitStateV71Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = importlib.import_module("bot.account_scoped_profit_state_v71_patch")

    def test_scoped_key_separates_same_symbol_by_account_and_broker(self) -> None:
        alpha = self.mod.scoped_position_key("user-alpha", "coinbase", "BTC-USD")
        beta = self.mod.scoped_position_key("user-beta", "coinbase", "BTC-USD")
        okx = self.mod.scoped_position_key("user-alpha", "okx", "BTC-USD")
        self.assertNotEqual(alpha, beta)
        self.assertNotEqual(alpha, okx)
        self.assertIn("scope=user-alpha", alpha)
        self.assertIn("broker=coinbase", alpha)
        self.assertIn("symbol=BTC-USD", alpha)

    def test_scoped_key_requires_identity_fields(self) -> None:
        with self.assertRaises(ValueError):
            self.mod.scoped_position_key("", "coinbase", "BTC-USD")
        with self.assertRaises(ValueError):
            self.mod.scoped_position_key("user-1", "", "BTC-USD")
        with self.assertRaises(ValueError):
            self.mod.scoped_position_key("user-1", "coinbase", "")

    def test_profit_lock_scoped_methods_keep_two_accounts_independent(self) -> None:
        fake = types.ModuleType("profit_lock_v71_fake")

        class Engine:
            def __init__(self) -> None:
                self.positions = {}

            def register_position(self, symbol, side, entry_price, entry_time=None):
                self.positions[symbol] = {
                    "symbol": symbol,
                    "side": side,
                    "entry_price": entry_price,
                    "peak": entry_price,
                }

            def update_position(self, symbol, current_price):
                state = self.positions[symbol]
                state["peak"] = max(state["peak"], current_price)
                return types.SimpleNamespace(symbol=symbol, peak_profit_pct=state["peak"])

            def remove_position(self, symbol):
                return self.positions.pop(symbol, None)

            def get_lock_status(self, symbol):
                return dict(self.positions[symbol]) if symbol in self.positions else None

        fake.ProfitLockEngine = Engine
        self.mod._patch_lock_engine(fake)
        engine = Engine()
        engine.register_scoped_position("user-a", "coinbase", "BTC-USD", "long", 100.0)
        engine.register_scoped_position("user-b", "coinbase", "BTC-USD", "long", 200.0)
        engine.update_scoped_position("user-a", "coinbase", "BTC-USD", 110.0)
        engine.update_scoped_position("user-b", "coinbase", "BTC-USD", 205.0)

        a = engine.get_scoped_lock_status("user-a", "coinbase", "BTC-USD")
        b = engine.get_scoped_lock_status("user-b", "coinbase", "BTC-USD")
        self.assertEqual(a["entry_price"], 100.0)
        self.assertEqual(a["peak"], 110.0)
        self.assertEqual(b["entry_price"], 200.0)
        self.assertEqual(b["peak"], 205.0)
        self.assertEqual(len(engine.positions), 2)

    def test_harvest_confirm_scoped_routes_fill_proof_to_scoped_key(self) -> None:
        fake = types.ModuleType("profit_harvest_v71_fake")
        calls = []

        class Layer:
            def register_position(self, symbol, side, entry_price, position_size_usd, entry_time=None):
                return None

            def process_price_update(self, symbol, current_price):
                return types.SimpleNamespace(symbol=symbol)

            def get_harvest_status(self, symbol):
                return {"symbol": symbol}

            def remove_position(self, symbol):
                return {"symbol": symbol}

            def confirm_realized_harvest(
                self,
                symbol,
                amount_usd,
                *,
                broker_fill_id,
                broker_name="",
                account_id="",
                note="",
            ):
                calls.append(
                    {
                        "symbol": symbol,
                        "amount": amount_usd,
                        "fill": broker_fill_id,
                        "broker": broker_name,
                        "account": account_id,
                    }
                )
                return amount_usd

        fake.ProfitHarvestLayer = Layer
        self.mod._patch_harvest_layer(fake)
        layer = Layer()
        actual = layer.confirm_scoped_realized_harvest(
            "user-a",
            "okx",
            "ETH-USDT",
            3.25,
            broker_fill_id="fill-77",
        )
        self.assertEqual(actual, 3.25)
        self.assertEqual(calls[0]["fill"], "fill-77")
        self.assertEqual(calls[0]["broker"], "okx")
        self.assertEqual(calls[0]["account"], "user-a")
        self.assertIn("scope=user-a", calls[0]["symbol"])
        self.assertIn("broker=okx", calls[0]["symbol"])
        self.assertIn("symbol=ETH-USDT", calls[0]["symbol"])


if __name__ == "__main__":
    unittest.main()
