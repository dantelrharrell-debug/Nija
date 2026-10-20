"""Pure synthetic Kraken BABY valuation tests; no brokerage requests."""
import unittest
from bot.kraken_baby_valuation_v461 import resolve_baby_usd_price


class FakeKraken:
    def __init__(self, ticker="0.012", pair=True, asset=True):
        self.ticker, self.pair, self.asset = ticker, pair, asset

    def query_public(self, endpoint, params):
        if endpoint == "Assets":
            return {"error": [], "result": {"BABY": {"altname": "BABY"}, "ZUSD": {"altname": "USD"}} if self.asset else {}}
        if endpoint == "AssetPairs":
            return {"error": [], "result": {"BABYZUSD": {"base": "BABY", "quote": "ZUSD", "status": "online"}} if self.pair else {}}
        if endpoint == "Ticker":
            return {"error": [], "result": {"BABYZUSD": {"c": [self.ticker]}}}
        raise AssertionError(endpoint)


class TestBabyResolver(unittest.TestCase):
    def test_confirmed_pair_price(self):
        self.assertEqual(resolve_baby_usd_price(FakeKraken()), 0.012)

    def test_unsupported_pair(self):
        self.assertIsNone(resolve_baby_usd_price(FakeKraken(pair=False)))

    def test_unknown_asset(self):
        self.assertIsNone(resolve_baby_usd_price(FakeKraken(asset=False)))

    def test_missing_price(self):
        self.assertIsNone(resolve_baby_usd_price(FakeKraken(ticker="0")))

    def test_public_api_error_is_not_a_price(self):
        class Rejected(FakeKraken):
            def query_public(self, endpoint, params):
                return {"error": ["EGeneral:Unavailable"], "result": {}}
        self.assertIsNone(resolve_baby_usd_price(Rejected()))

    def test_no_api_is_not_a_price(self):
        self.assertIsNone(resolve_baby_usd_price(None))

    def test_nonfinite_price(self):
        self.assertIsNone(resolve_baby_usd_price(FakeKraken(ticker="nan")))


if __name__ == "__main__":
    unittest.main()
