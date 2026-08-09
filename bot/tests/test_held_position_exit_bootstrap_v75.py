from __future__ import annotations

import importlib
import types
import unittest


class HeldPositionExitBootstrapV75Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = importlib.import_module("bot.held_position_exit_bootstrap_v75_patch")
        self.v74 = importlib.import_module("bot.adaptive_profit_exit_v74_patch")
        self.v74._POSITIONS.clear()

    def test_persisted_peak_and_trough_are_preserved(self) -> None:
        pos = {
            "high_water": 125.0,
            "low_water": 91.0,
        }
        self.assertEqual(self.mod._persisted_peak(pos, 110.0), 125.0)
        self.assertEqual(self.mod._persisted_trough(pos, 110.0), 91.0)

    def test_first_verified_market_used_without_history(self) -> None:
        pos = {}
        self.assertEqual(self.mod._persisted_peak(pos, 110.0), 110.0)
        self.assertEqual(self.mod._persisted_trough(pos, 110.0), 110.0)

    def test_existing_position_is_connected_to_adaptive_state(self) -> None:
        class AutoExit:
            @staticmethod
            def _sym(value):
                return str(value or "").upper()

            @staticmethod
            def _entry_price(pos):
                return float(pos.get("entry_price") or 0.0)

            @staticmethod
            def _quantity(pos):
                return float(pos.get("quantity") or 0.0)

            @staticmethod
            def _price(broker, symbol):
                return float(broker.price)

            @staticmethod
            def _side(value, pos):
                return str(value or "long").lower()

        class Broker:
            price = 115.0
            account_id = "acct-1"

        broker = Broker()
        pos = {
            "symbol": "BTC-USD",
            "entry_price": 100.0,
            "quantity": 0.25,
            "side": "long",
            "position_id": "p1",
            "peak_price": 123.0,
            "regime": "bull_trending",
            "regime_confidence": 0.9,
        }
        universal = types.SimpleNamespace(
            auto_exit=AutoExit,
            _snapshot=lambda: [broker],
            _tracker_positions=lambda b: [pos],
        )
        self.mod._install_peak_bootstrap()
        count = self.mod._bootstrap_existing_positions(universal)
        self.assertEqual(count, 1)
        key = self.v74._position_key(universal, broker, pos)
        state = self.v74._POSITIONS[key]
        self.assertEqual(state["peak"], 123.0)
        self.assertEqual(state["market"], 115.0)
        self.assertEqual(state["bootstrap_source"], "persisted_position_history")

    def test_existing_position_without_history_uses_live_price(self) -> None:
        class AutoExit:
            @staticmethod
            def _sym(value):
                return str(value or "").upper()

            @staticmethod
            def _entry_price(pos):
                return float(pos.get("entry_price") or 0.0)

            @staticmethod
            def _quantity(pos):
                return float(pos.get("quantity") or 0.0)

            @staticmethod
            def _price(broker, symbol):
                return 105.0

            @staticmethod
            def _side(value, pos):
                return "long"

        broker = types.SimpleNamespace(account_id="acct-2")
        pos = {
            "symbol": "ETH-USD",
            "entry_price": 95.0,
            "quantity": 1.0,
            "position_id": "p2",
            "regime": "ranging",
            "regime_confidence": 0.8,
        }
        universal = types.SimpleNamespace(
            auto_exit=AutoExit,
            _snapshot=lambda: [broker],
            _tracker_positions=lambda b: [pos],
        )
        self.mod._install_peak_bootstrap()
        count = self.mod._bootstrap_existing_positions(universal)
        self.assertEqual(count, 1)
        key = self.v74._position_key(universal, broker, pos)
        state = self.v74._POSITIONS[key]
        self.assertEqual(state["peak"], 105.0)
        self.assertEqual(state["trough"], 105.0)
        self.assertEqual(state["bootstrap_source"], "first_verified_market")


if __name__ == "__main__":
    unittest.main()
