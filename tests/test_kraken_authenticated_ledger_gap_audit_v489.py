"""Offline regression of v489 authenticated-history gap audit; no production API calls."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from bot.kraken_authenticated_ledger_gap_audit_v489 import (
    inspect_authenticated_kraken_ledger_gaps, _summarize_trades,
)

ORDER = "OABCDE-ABCDE-ABCDEF"


class LedgerGapTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "trade_ledger.db"
        with sqlite3.connect(self.path) as db:
            db.executescript("""
                CREATE TABLE trade_ledger (
                    position_id TEXT, user_id TEXT, action TEXT, order_id TEXT,
                    symbol TEXT, side TEXT, quantity REAL, size_usd REAL, fee REAL
                );
                CREATE TABLE completed_trades (position_id TEXT, user_id TEXT);
                CREATE TABLE strategy_order_intents (
                    broker TEXT, account_scope TEXT, order_id TEXT
                );
                CREATE TABLE pending_kraken_closes (
                    broker TEXT, account_scope TEXT, state TEXT, order_id TEXT
                );
                CREATE TABLE open_positions (
                    position_id TEXT, user_id TEXT, status TEXT,
                    quantity REAL, entry_price REAL
                );
                INSERT INTO trade_ledger VALUES
                    ('lot', 'platform','OPEN','OABCDE-ABCDE-ABCDEF',
                     'ETH-USD','BUY',1.0,2000.0,2.0);
                INSERT INTO strategy_order_intents VALUES
                    ('kraken','platform:kraken','OABCDE-ABCDE-ABCDEF');
            """)
        self.broker = object()
        self.args = dict(
            broker=self.broker, ledger_path=self.path, persistent_root=self.root,
            approved_api_key_sha256="a" * 64, approved_iban_sha256="b" * 64,
            reviewed_identity_provider_id="approved", monitoring_category=object(),
            max_pages=2, independently_reviewed=True, monitoring_budget_approved=True,
        )

    def test_unapproved_budget_no_broker_io(self):
        with patch("bot.kraken_authenticated_ledger_gap_audit_v489.collect_from_existing_broker") as reader:
            result = inspect_authenticated_kraken_ledger_gaps(
                **{**self.args, "monitoring_budget_approved": False}
            )
            reader.assert_not_called()
            self.assertFalse(result["authorizes_orders"])

    def test_missing_exit_proof_does_not_certify_even_exact_fills(self):
        fill = {"ordertxid": ORDER, "type": "buy", "pair": "ETHUSD",
                "vol": "1", "cost": "2000", "fee": "2", "price": "2000"}
        observed = {
            "account_scope_asserted_by_caller": "platform:kraken",
            "repeat_read_consistent": True, "trading_authorized": False,
            "history": {"trades": {"TABC": fill}, "closed": {}, "ledger": {}},
            "open_orders": {}, "balance": {},
        }
        with patch("bot.kraken_authenticated_ledger_gap_audit_v489.make_kraken_account_identity_provider",
                   return_value=lambda: {"verified": True}), patch(
                "bot.kraken_authenticated_ledger_gap_audit_v489.collect_from_existing_broker",
                return_value=observed):
            result = inspect_authenticated_kraken_ledger_gaps(**self.args)
        self.assertEqual(result["counts"]["kraken_fill_orders_without_ledger"], 0)
        self.assertEqual(result["counts"]["broker_ledger_fill_amount_mismatches"], 0)
        self.assertFalse(result["independent_ledger_certified"])
        self.assertFalse(result["collector_install_allowed"])
        self.assertIn("historical_lots_protective_exits_and_backup_require_certification", result["issues"])

    def test_missing_broker_order_identified_without_ledger_mutation(self):
        before = self.path.read_bytes()
        fill = {"ordertxid": "OBCDEF-BCDEF-BCDEFG", "type": "buy", "pair": "ETHUSD",
                "vol": "1", "cost": "2000", "fee": "2", "price": "2000"}
        observed = {
            "account_scope_asserted_by_caller": "platform:kraken",
            "repeat_read_consistent": True, "trading_authorized": False,
            "history": {"trades": {"TABC": fill}, "closed": {}, "ledger": {}},
            "open_orders": {}, "balance": {},
        }
        with patch("bot.kraken_authenticated_ledger_gap_audit_v489.make_kraken_account_identity_provider",
                   return_value=lambda: {"verified": True}), patch(
                "bot.kraken_authenticated_ledger_gap_audit_v489.collect_from_existing_broker",
                return_value=observed):
            report = inspect_authenticated_kraken_ledger_gaps(**self.args)
        self.assertEqual(report["counts"]["kraken_fill_orders_without_ledger"], 1)
        self.assertIn("authenticated_broker_fills_disagree_with_local_ledger", report["issues"])
        self.assertEqual(self.path.read_bytes(), before)

    def test_invalid_trade_identity_refused(self):
        with self.assertRaises(ValueError):
            _summarize_trades({"T1": {"ordertxid": "internal-id", "type": "buy",
                                  "pair": "ETHUSD", "vol": "1", "cost": "2",
                                  "fee": "0", "price": "2"}})


if __name__ == "__main__":
    unittest.main()
