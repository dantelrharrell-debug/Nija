from __future__ import annotations

import importlib
import os
import types
import unittest
from unittest.mock import patch


class UniversalNetProfitExitFloorV68Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = importlib.import_module("bot.universal_net_profit_exit_floor_v68_patch")

    def _universal(self, trigger):
        module = types.ModuleType("universal_v68_fake")
        auto_exit = types.SimpleNamespace()
        auto_exit._broker_label = lambda broker: getattr(broker, "name", "futurebroker")
        auto_exit._sym = lambda value: str(value).upper()
        auto_exit._entry_price = lambda pos: float(pos.get("entry_price", 0.0))
        auto_exit._side = lambda value, pos=None: str(value or "long")
        module.auto_exit = auto_exit
        module._trigger = trigger
        self.mod._patch_universal(module)
        return module

    def test_gross_take_profit_below_net_floor_is_suppressed(self) -> None:
        class Broker:
            name = "futurebroker"
            taker_fee = 0.002

        module = self._universal(lambda broker, pos, market: (True, "take_profit_1", 100.5))
        pos = {"symbol": "BTC-USD", "entry_price": 100.0, "side": "long"}
        with patch.dict(
            os.environ,
            {
                "NIJA_EXIT_SPREAD_RESERVE_PCT": "0",
                "NIJA_EXIT_SLIPPAGE_RESERVE_PCT": "0.001",
                "NIJA_MINIMUM_NET_PROFIT_PCT": "0.004",
            },
            clear=False,
        ):
            hit, reason, target = module._trigger(Broker(), pos, 100.6)
        self.assertFalse(hit)
        self.assertEqual(reason, "")
        self.assertEqual(target, 0.0)

    def test_take_profit_above_net_floor_is_allowed(self) -> None:
        class Broker:
            name = "futurebroker"
            taker_fee = 0.001

        module = self._universal(lambda broker, pos, market: (True, "take_profit_1", 101.0))
        pos = {"symbol": "BTC-USD", "entry_price": 100.0, "side": "long"}
        with patch.dict(
            os.environ,
            {
                "NIJA_EXIT_SPREAD_RESERVE_PCT": "0",
                "NIJA_EXIT_SLIPPAGE_RESERVE_PCT": "0.001",
                "NIJA_MINIMUM_NET_PROFIT_PCT": "0.004",
            },
            clear=False,
        ):
            hit, reason, target = module._trigger(Broker(), pos, 101.0)
        self.assertTrue(hit)
        self.assertEqual(reason, "take_profit_1")
        self.assertGreater(target, 100.0)

    def test_stop_loss_is_never_delayed_by_profit_floor(self) -> None:
        class Broker:
            name = "futurebroker"
            taker_fee = 0.01

        module = self._universal(lambda broker, pos, market: (True, "stop_loss:stored_stop_loss", 98.0))
        pos = {"symbol": "BTC-USD", "entry_price": 100.0, "side": "long"}
        hit, reason, target = module._trigger(Broker(), pos, 98.0)
        self.assertTrue(hit)
        self.assertIn("stop_loss", reason)
        self.assertEqual(target, 98.0)

    def test_trailing_profit_exit_requires_cost_adjusted_break_even_only(self) -> None:
        class Broker:
            name = "futurebroker"
            taker_fee = 0.001

        module = self._universal(lambda broker, pos, market: (True, "profit_lock_trailing_exit", 100.3))
        pos = {"symbol": "BTC-USD", "entry_price": 100.0, "side": "long"}
        with patch.dict(
            os.environ,
            {
                "NIJA_EXIT_SPREAD_RESERVE_PCT": "0",
                "NIJA_EXIT_SLIPPAGE_RESERVE_PCT": "0.001",
                "NIJA_MINIMUM_NET_PROFIT_PCT": "0.020",
            },
            clear=False,
        ):
            # 0.2% round trip + 0.1% slippage = 100.30 break-even.
            hit, reason, _target = module._trigger(Broker(), pos, 100.35)
        self.assertTrue(hit)
        self.assertEqual(reason, "profit_lock_trailing_exit")

    def test_runtime_fee_preferred_over_static_matrix(self) -> None:
        class Broker:
            name = "coinbase"
            taker_fee = 0.00125

        fake_universal = types.SimpleNamespace(
            auto_exit=types.SimpleNamespace(
                _sym=lambda value: str(value).upper(),
                _broker_label=lambda broker: broker.name,
                _entry_price=lambda pos: float(pos.get("entry_price", 0.0)),
                _side=lambda value, pos=None: str(value or "long"),
            )
        )
        model = self.mod._cost_model(
            fake_universal,
            Broker(),
            {"symbol": "ETH-USD", "entry_price": 100.0, "side": "long"},
        )
        self.assertEqual(model["source"], "broker_runtime_taker_fee")
        self.assertGreater(float(model["round_trip"]), 0.0025)


if __name__ == "__main__":
    unittest.main()
