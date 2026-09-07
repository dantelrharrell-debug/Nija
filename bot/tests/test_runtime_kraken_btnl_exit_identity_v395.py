import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bot import runtime_kraken_btnl_exit_identity_v395_patch as v395


def _openpositions(rows):
    return {"error": [], "result": rows}


class KrakenBtnlExitIdentityV395Tests(unittest.TestCase):
    def test_discover_btnl_long_aggregates_same_execution_identity(self):
        payload = _openpositions({
            "P1": {
                "pair": "ETHUSD:BTNL", "type": "buy", "vol": "0.10", "vol_closed": "0.01",
                "cost": "225", "margin": "112.5",
            },
            "P2": {
                "pair": "ETH/USD:BTNL", "type": "buy", "vol": "0.05", "vol_closed": "0.00257297",
                "cost": "118.5", "margin": "59.25",
            },
        })
        fake_v366 = SimpleNamespace(_private_call=lambda broker: lambda method, params: payload)
        with patch.object(
            v395.importlib,
            "import_module",
            side_effect=lambda name: fake_v366 if name == "bot.runtime_kraken_margin_canonical_coverage_v366_patch" else None,
        ):
            truth = v395._discover_btnl_long(object(), "ETHUSD")

        self.assertTrue(truth["ok"])
        self.assertTrue(truth["found"])
        self.assertEqual(truth["symbol"], "ETHUSD:BTNL")
        self.assertAlmostEqual(truth["remaining_units"], 0.13742703, places=12)
        self.assertEqual(truth["leverage"], 2)
        self.assertEqual(set(truth["position_ids"]), {"P1", "P2"})

    def test_discover_btnl_long_fails_closed_on_mixed_direction(self):
        payload = _openpositions({
            "LONG": {"pair": "ETHUSD:BTNL", "type": "buy", "vol": "0.1", "vol_closed": "0"},
            "SHORT": {"pair": "ETHUSD:BTNL", "type": "sell", "vol": "0.02", "vol_closed": "0"},
        })
        fake_v366 = SimpleNamespace(_private_call=lambda broker: lambda method, params: payload)
        with patch.object(
            v395.importlib,
            "import_module",
            side_effect=lambda name: fake_v366 if name == "bot.runtime_kraken_margin_canonical_coverage_v366_patch" else None,
        ):
            truth = v395._discover_btnl_long(object(), "ETHUSD")

        self.assertFalse(truth["ok"])
        self.assertTrue(truth["ambiguous"])
        self.assertEqual(truth["reason"], "mixed_direction_btnl_openpositions")

    def test_reference_price_translation_is_read_only(self):
        class Broker:
            def __init__(self):
                self.calls = []

            def get_current_price(self, symbol):
                self.calls.append(symbol)
                return 2480.0

        broker = Broker()
        self.assertTrue(v395._patch_reference_price_class(broker))
        self.assertEqual(broker.get_current_price("ETHUSD:BTNL"), 2480.0)
        self.assertEqual(broker.get_current_price("BTCUSD"), 2480.0)
        self.assertEqual(broker.calls, ["ETHUSD", "BTCUSD"])

    def test_exit_submit_routes_authenticated_btnl_identity_and_caps_quantity(self):
        calls = []

        def prior_submit(broker, account, pair, quantity, reason):
            calls.append((account, pair, quantity, reason))
            return {"status": "filled", "filled_size_usd": 100.0}

        setattr(prior_submit, v395._V265_SENTINEL, True)
        fake_exit = SimpleNamespace(_submit_exit=prior_submit)
        payload = _openpositions({
            "P1": {
                "pair": "ETHUSD:BTNL", "type": "buy", "vol": "0.13742703", "vol_closed": "0",
                "cost": "343.38569", "margin": "171.692845",
            }
        })
        fake_v366 = SimpleNamespace(_private_call=lambda broker: lambda method, params: payload)

        def importer(name):
            if name == "bot.kraken_all_account_exit_runtime_patch":
                return fake_exit
            if name == "bot.runtime_kraken_margin_canonical_coverage_v366_patch":
                return fake_v366
            raise ImportError(name)

        class Broker:
            def get_current_price(self, symbol):
                return 2480.0

        with patch.object(v395.importlib, "import_module", side_effect=importer):
            self.assertTrue(v395._patch_exit_submit())
            result = fake_exit._submit_exit(Broker(), "platform:kraken", "ETHUSD", 0.2, "stop_loss")

        self.assertEqual(result["status"], "filled")
        self.assertEqual(len(calls), 1)
        account, pair, quantity, reason = calls[0]
        self.assertEqual(account, "platform:kraken")
        self.assertEqual(pair, "ETHUSD:BTNL")
        self.assertAlmostEqual(quantity, 0.13742703, places=12)
        self.assertEqual(reason, "stop_loss")
        self.assertTrue(getattr(fake_exit._submit_exit, v395._V265_SENTINEL))

    def test_exit_submit_does_not_fall_back_to_spot_when_btnl_is_ambiguous(self):
        calls = []

        def prior_submit(*args):
            calls.append(args)
            return {"status": "filled"}

        setattr(prior_submit, v395._V265_SENTINEL, True)
        fake_exit = SimpleNamespace(_submit_exit=prior_submit)
        payload = _openpositions({
            "LONG": {"pair": "ETHUSD:BTNL", "type": "buy", "vol": "0.1", "vol_closed": "0"},
            "SHORT": {"pair": "ETHUSD:BTNL", "type": "sell", "vol": "0.01", "vol_closed": "0"},
        })
        fake_v366 = SimpleNamespace(_private_call=lambda broker: lambda method, params: payload)

        def importer(name):
            if name == "bot.kraken_all_account_exit_runtime_patch":
                return fake_exit
            if name == "bot.runtime_kraken_margin_canonical_coverage_v366_patch":
                return fake_v366
            raise ImportError(name)

        with patch.object(v395.importlib, "import_module", side_effect=importer):
            self.assertTrue(v395._patch_exit_submit())
            result = fake_exit._submit_exit(object(), "platform:kraken", "ETHUSD", 0.1, "stop_loss")

        self.assertEqual(result["status"], "error")
        self.assertIn("mixed_direction_btnl_openpositions", result["error"])
        self.assertEqual(calls, [])

    def test_exit_submit_delegates_ordinary_non_margin_exit(self):
        calls = []

        def prior_submit(broker, account, pair, quantity, reason):
            calls.append((pair, quantity))
            return {"status": "filled"}

        setattr(prior_submit, v395._V265_SENTINEL, True)
        fake_exit = SimpleNamespace(_submit_exit=prior_submit)
        fake_v366 = SimpleNamespace(_private_call=lambda broker: lambda method, params: _openpositions({}))

        def importer(name):
            if name == "bot.kraken_all_account_exit_runtime_patch":
                return fake_exit
            if name == "bot.runtime_kraken_margin_canonical_coverage_v366_patch":
                return fake_v366
            raise ImportError(name)

        with patch.object(v395.importlib, "import_module", side_effect=importer):
            self.assertTrue(v395._patch_exit_submit())
            result = fake_exit._submit_exit(object(), "platform:kraken", "SOLUSD", 1.0, "profit_target")

        self.assertEqual(result["status"], "filled")
        self.assertEqual(calls, [("SOLUSD", 1.0)])


if __name__ == "__main__":
    unittest.main()
