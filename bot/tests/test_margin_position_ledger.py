from __future__ import annotations

import sqlite3
import tempfile
import unittest
from types import SimpleNamespace

from bot.margin_position_ledger import MarginPositionLedger


class MarginPositionLedgerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = f"{self._tmp.name}/margin_position_ledger.db"
        self.ledger = MarginPositionLedger(db_path=self.db_path)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    @staticmethod
    def _request(**overrides):
        payload = {
            "request_id": "req-1",
            "intent_id": "intent-1",
            "preferred_broker": "kraken",
            "account_id": "acc-1",
            "subaccount_id": "sub-1",
            "symbol": "BTC-USD",
            "asset_class": "crypto",
            "side": "buy",
            "intent_type": "entry",
            "size_usd": 100.0,
            "notional_usd": 100.0,
            "buying_power_usd": 250.0,
            "available_balance_usd": 250.0,
            "leverage": 1,
            "margin_mode": "cross",
            "reduce_only": False,
            "units": 0.01,
        }
        payload.update(overrides)
        return SimpleNamespace(**payload)

    @staticmethod
    def _result(**overrides):
        payload = {
            "success": True,
            "filled_size_usd": 100.0,
        }
        payload.update(overrides)
        return SimpleNamespace(**payload)

    def test_one_canonical_record_uniqueness(self):
        req1 = self._request(request_id="req-a", intent_id="intent-a")
        req2 = self._request(request_id="req-b", intent_id="intent-b")
        self.ledger.apply_submit(req1)
        self.ledger.apply_submit(req2)

        with sqlite3.connect(self.db_path) as conn:
            count = conn.execute("SELECT COUNT(*) FROM margin_position_ledger").fetchone()[0]
        self.assertEqual(count, 1)

    def test_idempotent_reapply_by_request_id_and_intent_id(self):
        req = self._request(request_id="req-idem", intent_id="intent-idem")
        self.ledger.apply_submit(req)
        self.ledger.apply_ack_fill(req, self._result(filled_size_usd=75.0))
        first = self.ledger.get_record(
            broker="kraken",
            account_id="acc-1",
            subaccount_id="sub-1",
            symbol="BTC-USD",
            asset_class="crypto",
        )

        self.ledger.apply_ack_fill(req, self._result(filled_size_usd=75.0))
        second = self.ledger.get_record(
            broker="kraken",
            account_id="acc-1",
            subaccount_id="sub-1",
            symbol="BTC-USD",
            asset_class="crypto",
        )

        self.assertEqual(first["position_notional_usd"], second["position_notional_usd"])

    def test_lifecycle_transition_ordering_rejection(self):
        req = self._request(request_id="req-rej", intent_id="intent-rej")
        self.ledger.apply_submit(req)
        self.ledger.apply_reject_or_cancel(req, "simulated rejection")

        with self.assertRaises(ValueError):
            self.ledger.apply_ack_fill(
                self._request(request_id="req-ack-after-reject", intent_id="intent-ack-after-reject"),
                self._result(filled_size_usd=40.0),
            )


if __name__ == "__main__":
    unittest.main()
