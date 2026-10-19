"""CI regression: reject substring Kraken pair collisions in cost-basis history."""
from __future__ import annotations

from contextlib import nullcontext
import unittest
from unittest.mock import patch

from bot import runtime_kraken_cost_basis_history_pagination_v304_patch as v304


class TestKrakenV304ExactPair(unittest.TestCase):
    def _recover(self, trades):
        class FakeBroker:
            account_identifier = "OFFLINE_FIXTURE"

            def _kraken_private_call(self, method, params, category=None):
                self.assert_called = True
                assert method == "TradesHistory"
                assert params == {"ofs": 50}
                return {
                    "error": [],
                    "result": {"count": 50 + len(trades), "trades": trades},
                }

        with (
            patch.object(v304, "_authoritative_history_priority", return_value=nullcontext()),
            patch.object(v304, "_history_category", return_value="monitoring"),
            patch.object(v304, "_max_extra_pages", return_value=1),
            patch.object(v304, "_symbol_match_sets", return_value={
                "BABY-USD": ("BABY", {"BABYUSD", "XBABYZUSD", "BABY/USDT"})
            }),
        ):
            return v304._supplement_older_history(FakeBroker(), ("BABY-USD",))

    def test_foreign_symbol_with_substring_cannot_prove_baby_basis(self):
        recovered = self._recover({
            "foreign": {
                "type": "buy", "pair": "NOTBABYUSD", "price": "999",
                "vol": "2", "time": "1",
            },
        })
        self.assertEqual(recovered, {})

    def test_exact_pair_alias_recovers_authenticated_buy(self):
        recovered = self._recover({
            "genuine": {
                "type": "buy", "pair": "XBABYZUSD", "price": "10",
                "vol": "2", "time": "1",
            },
        })
        self.assertEqual(recovered, {"BABY-USD": 10.0})

    def test_foreign_buy_cannot_contaminate_valid_pair_vwap(self):
        recovered = self._recover({
            "genuine": {
                "type": "buy", "pair": "BABYUSD", "price": "10",
                "vol": "2", "time": "1",
            },
            "foreign": {
                "type": "buy", "pair": "NOTBABYUSD", "price": "10000",
                "vol": "3", "time": "2",
            },
        })
        self.assertEqual(recovered, {"BABY-USD": 10.0})

    def test_unmatched_or_selling_trades_never_prove_basis(self):
        recovered = self._recover({
            "foreign": {
                "type": "buy", "pair": "ETHUSD", "price": "1000",
                "vol": "2", "time": "1",
            },
            "sell": {
                "type": "sell", "pair": "BABYUSD", "price": "100",
                "vol": "1", "time": "2",
            },
        })
        self.assertEqual(recovered, {})


if __name__ == "__main__":
    unittest.main()
