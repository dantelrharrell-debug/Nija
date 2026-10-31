import unittest

from bot.kraken_close_evidence_comparison_v493 import (\n    verify_exact_close, verify_broker_readback_consistency,\n)


class KrakenCloseEvidenceComparisonTests(unittest.TestCase):
    def setUp(self):
        self.expected = {"order_id": "ORDER1", "pair": "XETHZUSD", "side": "sell",
                         "volume": "2", "cost": "200", "fee": "0.5"}
        self.order = {"status": "closed", "descr": {"pair": "XETHZUSD", "type": "sell"},
                      "trades": ["TRADE1", "TRADE2"], "vol_exec": "2"}
        self.trades = {
            "TRADE1": {"ordertxid": "ORDER1", "pair": "XETHZUSD", "type": "sell",
                       "vol": "1", "cost": "100", "fee": "0.25"},
            "TRADE2": {"ordertxid": "ORDER1", "pair": "XETHZUSD", "type": "sell",
                       "vol": "1", "cost": "100", "fee": "0.25"},
        }

    def test_matching_close_never_authorizes_execution(self):
        result = verify_exact_close(self.expected, self.order, self.trades)
        self.assertTrue(result["verified"])
        self.assertFalse(result["execution_authorized"])
        self.assertFalse(result["ledger_mutation_allowed"])

    def test_missing_trade_fails_closed(self):
        result = verify_exact_close(self.expected, self.order,
                                    {"TRADE1": self.trades["TRADE1"]})
        self.assertFalse(result["verified"])

    def test_wrong_account_order_link_fails_closed(self):
        self.trades["TRADE1"]["ordertxid"] = "OTHER"
        self.assertFalse(verify_exact_close(self.expected, self.order,
                                            self.trades)["verified"])

    def test_fee_discrepancy_fails_closed(self):
        self.expected["fee"] = "0.1"
        self.assertFalse(verify_exact_close(self.expected, self.order,
                                            self.trades)["verified"])

    def test_partial_order_fails_closed(self):
        self.order["status"] = "open"
        self.assertFalse(verify_exact_close(self.expected, self.order,
                                            self.trades)["verified"])

    def test_duplicate_trade_fails_closed(self):
        self.order["trades"] = ["TRADE1", "TRADE1"]
        self.assertFalse(verify_exact_close(self.expected, self.order,
                                            self.trades)["verified"])

    def test_non_mapping_order_fails_closed(self):
        self.assertFalse(verify_exact_close(self.expected, [], self.trades)["verified"])

    def test_non_mapping_trade_fails_closed(self):
        self.trades["TRADE1"] = []
        self.assertFalse(verify_exact_close(self.expected, self.order,
                                            self.trades)["verified"])

    def test_unhashable_trade_id_fails_closed(self):
        self.order["trades"] = [["TRADE1"]]
        self.assertFalse(verify_exact_close(self.expected, self.order,
                                            self.trades)["verified"])

    def test_nan_amount_fails_closed(self):
        self.trades["TRADE1"]["cost"] = "NaN"
        self.assertFalse(verify_exact_close(self.expected, self.order,
                                            self.trades)["verified"])

    def test_infinite_amount_fails_closed(self):
        self.expected["cost"] = "Infinity"
        self.assertFalse(verify_exact_close(self.expected, self.order,
                                            self.trades)["verified"])

    def test_broker_readback_only_never_certifies_ledger(self):
        result = verify_broker_readback_consistency("ORDER1", self.order, self.trades)
        self.assertTrue(result["verified"])
        self.assertFalse(result["independent_ledger_certified"])
        self.assertFalse(result["execution_authorized"])

    def test_broker_readback_rejects_mismatched_fill(self):
        self.trades["TRADE2"]["ordertxid"] = "OTHER"
        self.assertFalse(verify_broker_readback_consistency(
            "ORDER1", self.order, self.trades)["verified"])

    def test_broker_readback_rejects_missing_cost(self):
        del self.trades["TRADE2"]["cost"]
        self.assertFalse(verify_broker_readback_consistency(
            "ORDER1", self.order, self.trades)["verified"])


if __name__ == "__main__":
    unittest.main()
