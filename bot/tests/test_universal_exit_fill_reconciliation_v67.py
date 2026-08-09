from __future__ import annotations

import importlib
import sys
import types
import unittest


class UniversalExitFillReconciliationV67Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.mod = importlib.import_module("bot.universal_exit_fill_reconciliation_v67_patch")
        self.mod._PENDING.clear()

    def test_accepted_live_new_and_partial_are_not_full_fills(self) -> None:
        for status in ("accepted", "live", "new", "open", "partially_filled", "unknown"):
            with self.subTest(status=status):
                self.assertFalse(self.mod._is_full_fill({"status": status, "order_id": "o-1"}, 1.0))
                self.assertTrue(self.mod._is_submission_ack({"status": status, "order_id": "o-1"}))

    def test_filled_or_full_executed_quantity_is_confirmed(self) -> None:
        self.assertTrue(self.mod._is_full_fill({"status": "filled"}, 1.0))
        self.assertTrue(
            self.mod._is_full_fill(
                {"status": "partially_filled", "executed_qty": "1.0"},
                1.0,
            )
        )

    def test_order_id_only_is_pending_ack_not_fill(self) -> None:
        payload = {"order_id": "abc-123"}
        self.assertTrue(self.mod._is_submission_ack(payload))
        self.assertFalse(self.mod._is_full_fill(payload, 2.0))

    def test_nested_okx_order_fields_are_parsed(self) -> None:
        payload = {
            "code": "0",
            "data": [{"ordId": "99", "state": "filled", "accFillSz": "2.5", "avgPx": "101.25"}],
        }
        self.assertEqual(self.mod._order_id(payload), "99")
        self.assertEqual(self.mod._status(payload), "filled")
        self.assertAlmostEqual(self.mod._filled_quantity(payload), 2.5)
        self.assertTrue(self.mod._is_full_fill(payload, 2.5))

    def test_query_order_uses_generic_broker_method(self) -> None:
        class Broker:
            def get_order(self, order_id):
                return {"id": order_id, "status": "filled", "filled_quantity": 1.0}

        result = self.mod._query_order(Broker(), "o-7", "BTC-USD")
        self.assertEqual(result["status"], "filled")

    def test_pending_reconciliation_blocks_duplicate_submit_until_fill(self) -> None:
        auto_exit = types.SimpleNamespace()
        auto_exit._sym = lambda value: str(value).upper()
        auto_exit._quantity = lambda pos: float(pos.get("quantity", 0.0))
        auto_exit._entry_price = lambda pos: float(pos.get("entry_price", 0.0))
        auto_exit._side = lambda value, pos=None: str(value or "long")
        auto_exit._price = lambda broker, symbol: 105.0
        auto_exit._broker_label = lambda broker: "futurebroker"
        auto_exit._position_key = lambda pos: f"acct:{pos['symbol']}"
        auto_exit._HIGH_WATER = {}

        universal = types.ModuleType("universal_v67_fake")
        universal.auto_exit = auto_exit
        universal._ACTIVE = set()
        universal._account_label = lambda broker: "user-1"
        universal._trigger = lambda broker, pos, market: (True, "take_profit", 104.0)
        universal._register_broker = lambda broker: None
        closed = []
        universal._mark_closed = lambda broker, pos, order, reason, market: closed.append(
            (pos["symbol"], order.get("order_id") or order.get("id"))
        )

        position = {
            "symbol": "BTC-USD",
            "position_id": "p-1",
            "quantity": 1.0,
            "entry_price": 100.0,
            "side": "long",
        }
        universal._tracker_positions = lambda broker: [dict(position)]

        class Broker:
            connected = True

            def __init__(self) -> None:
                self.submits = 0
                self.order_status = "accepted"
                self.position_qty = 1.0

            def place_market_order(self, **kwargs):
                self.submits += 1
                return {"status": "accepted", "order_id": "o-1"}

            def get_order(self, order_id):
                return {
                    "status": self.order_status,
                    "order_id": order_id,
                    "filled_quantity": 1.0 if self.order_status == "filled" else 0.0,
                }

            def get_positions(self):
                if self.position_qty <= 0:
                    return []
                row = dict(position)
                row["quantity"] = self.position_qty
                return [row]

        broker = Broker()

        # First scan submits exactly once and preserves the position as pending.
        self.assertEqual(self.mod._safe_scan_broker(universal, broker), 0)
        self.assertEqual(broker.submits, 1)
        self.assertEqual(closed, [])

        # Still accepted: no duplicate submission.
        self.assertEqual(self.mod._safe_scan_broker(universal, broker), 0)
        self.assertEqual(broker.submits, 1)
        self.assertEqual(closed, [])

        # Terminal fill: local close occurs without another submission.
        broker.order_status = "filled"
        broker.position_qty = 0.0
        self.assertEqual(self.mod._safe_scan_broker(universal, broker), 1)
        self.assertEqual(broker.submits, 1)
        self.assertEqual(closed, [("BTC-USD", "o-1")])

    def test_registry_discovery_is_capability_based_not_class_name(self) -> None:
        class FutureVenueAdapter:
            def get_positions(self):
                return []

            def place_order(self, **kwargs):
                return {"status": "filled"}

        broker = FutureVenueAdapter()
        manager = types.SimpleNamespace(
            platform_brokers={"future": broker},
            user_brokers={},
        )
        module = types.ModuleType("bot.multi_account_broker_manager")
        module.multi_account_broker_manager = manager

        universal = types.SimpleNamespace(_register_broker=lambda value: None)
        with unittest.mock.patch.dict(sys.modules, {"bot.multi_account_broker_manager": module}):
            found = self.mod._discover_brokers(universal)
        self.assertIn(broker, found)


if __name__ == "__main__":
    unittest.main()
