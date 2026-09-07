import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bot import runtime_kraken_btnl_native_routing_v394_patch as v394


class KrakenBtnlNativeRoutingV394Tests(unittest.TestCase):
    def test_btnl_identity_preserves_venue_and_normalizes_separators(self):
        self.assertEqual(v394._btnl_identity("ETHUSD:BTNL"), "ETHUSD:BTNL")
        self.assertEqual(v394._btnl_identity("ETH/USD:BTNL"), "ETHUSD:BTNL")
        self.assertEqual(v394._btnl_identity("ETH-USD:BTNL"), "ETHUSD:BTNL")
        self.assertEqual(v394._btnl_identity("ETHUSD"), "ETHUSD")

    def test_private_pair_keeps_btnl_while_market_lookup_stays_standard(self):
        calls = []

        def original(broker, symbol):
            calls.append(symbol)
            return "ETHUSD", 2490.25

        fake_v380 = SimpleNamespace(_pair_and_price=original)
        with patch.object(
            v394.importlib,
            "import_module",
            side_effect=lambda name: fake_v380 if name == "bot.runtime_kraken_native_margin_backup_v380_patch" else None,
        ):
            self.assertTrue(v394._patch_v380_private_pair())
            pair, price = fake_v380._pair_and_price(object(), "ETHUSD:BTNL")

        self.assertEqual(calls, ["ETHUSD:BTNL"])
        self.assertEqual(pair, "ETHUSD:BTNL")
        self.assertEqual(price, 2490.25)

    def test_private_pair_fails_closed_if_public_resolver_drifts_base_pair(self):
        fake_v380 = SimpleNamespace(_pair_and_price=lambda broker, symbol: ("BTCUSD", 2490.25))
        with patch.object(
            v394.importlib,
            "import_module",
            side_effect=lambda name: fake_v380 if name == "bot.runtime_kraken_native_margin_backup_v380_patch" else None,
        ):
            self.assertTrue(v394._patch_v380_private_pair())
            self.assertEqual(fake_v380._pair_and_price(object(), "ETHUSD:BTNL"), ("", 0.0))

    def test_openorders_normalizer_rekeys_only_same_btnl_venue(self):
        def original(payload):
            return True, {
                "ETH-USD:BTNL": {
                    "stop_qty": 0.13742703,
                    "take_profit_qty": 0.0,
                    "stop_order_ids": ("STOP-BTNL",),
                    "take_profit_order_ids": (),
                },
                "ETH-USD": {
                    "stop_qty": 0.5,
                    "take_profit_qty": 0.0,
                    "stop_order_ids": ("STOP-STANDARD",),
                    "take_profit_order_ids": (),
                },
            }, "ok"

        fake_v367 = SimpleNamespace(_normalise_open_orders=original, _NATIVE_CACHE={"platform:kraken": object()})
        with patch.object(
            v394.importlib,
            "import_module",
            side_effect=lambda name: fake_v367 if name == "bot.runtime_kraken_margin_protection_truth_v367_patch" else None,
        ):
            self.assertTrue(v394._patch_v367_openorders_normalizer())
            ok, rows, reason = fake_v367._normalise_open_orders({})

        self.assertTrue(ok)
        self.assertEqual(reason, "ok")
        self.assertEqual(rows["ETHUSD:BTNL"]["stop_qty"], 0.13742703)
        self.assertEqual(rows["ETHUSD:BTNL"]["stop_order_ids"], ("STOP-BTNL",))
        self.assertEqual(rows["ETH-USD"]["stop_qty"], 0.5)
        self.assertEqual(fake_v367._NATIVE_CACHE, {})

    def test_wrong_venue_cleanup_cancels_only_nija_tagged_order_for_active_btnl(self):
        account = "platform:kraken"
        active = "ETHUSD:BTNL"
        expected_id = "njsl-active-btnl"
        calls = []

        def client_id(acct, symbol, leg):
            if acct == account and symbol == active and leg == "stop-loss":
                return expected_id
            return "other"

        def call(broker, method, params, category):
            calls.append((method, dict(params), category))
            if method == "OpenOrders":
                return {
                    "error": [],
                    "result": {
                        "open": {
                            "WRONG": {
                                "cl_ord_id": expected_id,
                                "descr": {"pair": "ETHUSD", "type": "sell", "ordertype": "stop-loss"},
                            },
                            "CORRECT": {
                                "cl_ord_id": expected_id,
                                "descr": {"pair": "ETH/USD:BTNL", "type": "sell", "ordertype": "stop-loss"},
                            },
                            "MANUAL": {
                                "cl_ord_id": "manual-order",
                                "descr": {"pair": "ETHUSD", "type": "sell", "ordertype": "stop-loss"},
                            },
                        }
                    },
                }
            if method == "CancelOrder":
                return {"error": [], "result": {"count": 1}}
            raise AssertionError(method)

        fake_v380 = SimpleNamespace(
            _cleanup_orphans=lambda acct, broker, active_symbols: (),
            _call=call,
            _client_id=client_id,
            _client_id_scope_v392=lambda acct, symbol, leg: "njsl-scope-does-not-match",
        )
        with patch.object(
            v394.importlib,
            "import_module",
            side_effect=lambda name: fake_v380 if name == "bot.runtime_kraken_native_margin_backup_v380_patch" else None,
        ):
            self.assertTrue(v394._patch_v380_wrong_venue_cleanup())
            cancelled = fake_v380._cleanup_orphans(account, object(), {active})

        self.assertEqual(cancelled, ("WRONG",))
        cancel_txids = [params["txid"] for method, params, _category in calls if method == "CancelOrder"]
        self.assertEqual(cancel_txids, ["WRONG"])


if __name__ == "__main__":
    unittest.main()
