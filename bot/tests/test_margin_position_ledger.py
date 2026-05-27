from __future__ import annotations

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
