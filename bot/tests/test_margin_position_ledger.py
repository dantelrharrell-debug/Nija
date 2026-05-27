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
import time
import unittest

from bot.margin_position_ledger import get_margin_position_ledger


class TestMarginPositionLedger(unittest.TestCase):
    def test_risk_math_and_exposure(self):
        ledger = get_margin_position_ledger()
        account_id = f"unit-{int(time.time() * 1000)}"
        ledger.ingest_account_snapshot(
            broker="kraken",
            account_id=account_id,
            equity_usd=1000.0,
            free_balance_usd=500.0,
            margin_obligation_usd=200.0,
            free_margin_usd=600.0,
            unrealised_pnl_usd=0.0,
        )
        ledger.ingest_position_snapshot(
            broker="kraken",
            account_id=account_id,
            symbol="BTC-USD",
            position_id="p1",
            side="buy",
            notional_usd=1000.0,
            leverage=2.0,
        )
        snap = ledger.get_account_risk_snapshot(broker="kraken", account_id=account_id)
        self.assertAlmostEqual(snap.borrowed_exposure_usd, 500.0, places=2)
        self.assertAlmostEqual(snap.used_margin_usd, 500.0, places=2)
        self.assertAlmostEqual(snap.net_leverage, 1.0, places=2)
        self.assertEqual(snap.reconciliation_status, "ok")

    def test_stale_and_runtime_override(self):
        ledger = get_margin_position_ledger()
        account_id = f"unit-stale-{int(time.time() * 1000)}"
        old_ts = time.time() - 3600
        ledger.ingest_account_snapshot(
            broker="kraken",
            account_id=account_id,
            equity_usd=500.0,
            free_balance_usd=200.0,
            margin_obligation_usd=50.0,
            free_margin_usd=150.0,
            ts=old_ts,
        )
        snap = ledger.get_account_risk_snapshot(broker="kraken", account_id=account_id)
        self.assertTrue(snap.stale)
        overrides = ledger.get_runtime_capability_overrides(broker="kraken", account_id=account_id)
        self.assertFalse(overrides["supports_margin"])
        self.assertEqual(overrides["max_leverage"], 1.0)

    def test_reconcile_marks_diverged(self):
        ledger = get_margin_position_ledger()
        account_id = f"unit-rec-{int(time.time() * 1000)}"
        ledger.ingest_position_snapshot(
            broker="kraken",
            account_id=account_id,
            symbol="ETH-USD",
            position_id="pos-1",
            side="buy",
            notional_usd=400.0,
            leverage=2.0,
        )
        status = ledger.reconcile_positions(
            broker="kraken",
            account_id=account_id,
            truth_positions=[],
        )
        self.assertEqual(status, "diverged")
        snap = ledger.get_account_risk_snapshot(broker="kraken", account_id=account_id)
        self.assertEqual(snap.reconciliation_status, "diverged")


if __name__ == "__main__":
    unittest.main()
