"""CI-discovered v304 Kraken history regression tests (offline, no brokerage calls)."""
from __future__ import annotations

from contextlib import nullcontext
import unittest
from unittest.mock import patch

from bot import runtime_kraken_cost_basis_history_pagination_v304_patch as v304


class TestKrakenV304HistoryVWAP(unittest.TestCase):
    def _recover(self, trades):
        class FakeBroker:
            account_identifier = "OFFLINE_FIXTURE"

            def _kraken_private_call(self, method, params, category=None):
                assert method == "TradesHistory"
                assert params == {"ofs": 50}
                return {"error": [], "result": {"count": 50 + len(trades), "trades": trades}}

        with (
            patch.object(v304, "_symbol_match_sets", return_value={"BABY-USD": ("BABY", {"BABYUSD"})}),
            patch.object(v304, "_authoritative_history_priority", return_value=nullcontext()),
            patch.object(v304, "_history_category", return_value="monitoring"),
        ):
            return v304._supplement_older_history(FakeBroker(), ("BABY-USD",))

    def test_all_buys_on_page_are_weighted_not_only_first(self):
        recovered = self._recover({
            "one": {"type": "buy", "pair": "BABYUSD", "price": "10", "vol": "2", "time": "1"},
            "two": {"type": "buy", "pair": "BABYUSD", "price": "20", "vol": "1", "time": "2"},
            "other": {"type": "sell", "pair": "BABYUSD", "price": "999", "vol": "1", "time": "3"},
        })
        self.assertAlmostEqual(recovered["BABY-USD"], 40.0 / 3.0)

    def test_nonfinite_broker_evidence_stays_unverified(self):
        recovered = self._recover({
            "nan_price": {"type": "buy", "pair": "BABYUSD", "price": "nan", "vol": "1", "time": "1"},
            "inf_price": {"type": "buy", "pair": "BABYUSD", "price": "inf", "vol": "1", "time": "1"},
            "inf_volume": {"type": "buy", "pair": "BABYUSD", "price": "1", "vol": "inf", "time": "1"},
        })
        self.assertEqual(recovered, {})
        self.assertEqual(v304._positive_price_map({"BABY-USD": float("inf")}), {})

    def test_missing_matching_buy_never_fabricates_cost_basis(self):
        recovered = self._recover({
            "sell": {"type": "sell", "pair": "BABYUSD", "price": "2", "vol": "1", "time": "1"},
            "wrong_pair": {"type": "buy", "pair": "ETHUSD", "price": "200", "vol": "1", "time": "2"},
        })
        self.assertEqual(recovered, {})


if __name__ == "__main__":
    unittest.main()
