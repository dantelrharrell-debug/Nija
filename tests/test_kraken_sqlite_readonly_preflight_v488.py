"""Offline regression: actual SQLite schema read without any trading authority."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from bot.kraken_sqlite_readonly_preflight_v488 import inspect_kraken_ledger

OPEN_ID = "OABCDE-ABCDE-ABCDEF"
STOP_ID = "OBCDEF-BCDEF-BCDEFG"
PROFIT_ID = "OCDEFG-CDEFG-CDEFGH"


class KrakenLedgerReadonlyPreflightTests(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        self.db_path = self.root / "trade_ledger.db"

    def create_db(self, *, exits=False, pending=0, opening=True):
        with sqlite3.connect(self.db_path) as db:
            db.executescript("""
                CREATE TABLE trade_ledger (
                    position_id TEXT, user_id TEXT, action TEXT, order_id TEXT
                );
                CREATE TABLE completed_trades (
                    position_id TEXT, user_id TEXT
                );
                CREATE TABLE strategy_order_intents (
                    broker TEXT, account_scope TEXT, order_id TEXT
                );
                CREATE TABLE pending_kraken_closes (
                    broker TEXT, account_scope TEXT, state TEXT, order_id TEXT
                );
            """)
            cols = (
                ", stop_order_id TEXT, take_profit_order_id TEXT" if exits else ""
            )
            db.execute(
                "CREATE TABLE open_positions (position_id TEXT, user_id TEXT, "
                "status TEXT, quantity REAL, entry_price REAL" + cols + ")"
            )
            if exits:
                db.execute(
                    "INSERT INTO open_positions VALUES (?,?,?,?,?,?,?)",
                    ("lot-1", "platform", "open", 1.0, 2000.0, STOP_ID, PROFIT_ID),
                )
            else:
                db.execute(
                    "INSERT INTO open_positions VALUES (?,?,?,?,?)",
                    ("lot-1", "platform", "open", 1.0, 2000.0),
                )
            if opening:
                db.execute(
                    "INSERT INTO trade_ledger VALUES (?,?,?,?)",
                    ("lot-1", "platform", "OPEN", OPEN_ID),
                )
            for _ in range(pending):
                db.execute(
                    "INSERT INTO pending_kraken_closes VALUES (?,?,?,?)",
                    ("kraken", "platform:kraken", "pending", OPEN_ID),
                )

    def inspect(self):
        return inspect_kraken_ledger(self.db_path, persistent_root=self.root)

    def test_missing_mount_or_database_refused(self):
        result = self.inspect()
        self.assertIn("persistent_ledger_path_unverified", result["issues"])
        self.assertFalse(result["collector_install_allowed"])

    def test_database_outside_root_denied(self):
        self.create_db()
        other = self.root / "other"
        other.mkdir()
        report = inspect_kraken_ledger(self.db_path, persistent_root=other)
        self.assertIn("persistent_ledger_path_unverified", report["issues"])

    def test_pending_closes_and_missing_exchange_id_map_refused(self):
        self.create_db(pending=13)
        report = self.inspect()
        self.assertTrue(report["sqlite_integrity_ok"])
        self.assertEqual(report["counts"]["pending_kraken_closes"], 13)
        self.assertEqual(report["counts"]["platform_positions_without_exact_opening"], 0)
        self.assertIn("pending_kraken_closes_require_reconciliation", report["issues"])
        self.assertIn("exchange_protective_order_id_mapping_missing", report["issues"])
        self.assertFalse(report["broker_history_reconciled"])

    def test_missing_opening_records_flagged(self):
        self.create_db(opening=False, exits=True)
        report = self.inspect()
        self.assertEqual(report["counts"]["platform_positions_without_exact_opening"], 1)
        self.assertIn("opening_ledger_order_links_unverified", report["issues"])

    def test_even_complete_local_rows_do_not_certify_broker_or_backup(self):
        self.create_db(exits=True)
        before = self.db_path.read_bytes()
        report = self.inspect()
        after = self.db_path.read_bytes()
        self.assertEqual(before, after)
        self.assertEqual(report["issues"], [])
        self.assertFalse(report["independent_ledger_certified"])
        self.assertFalse(report["backup_restore_certified"])
        self.assertFalse(report["protective_exits_broker_verified"])
        self.assertFalse(report["collector_install_allowed"])
        self.assertFalse(report["authorizes_orders"])

    def test_invalid_non_exchange_exit_ids_flagged(self):
        self.create_db(exits=True)
        with sqlite3.connect(self.db_path) as db:
            db.execute(
                "UPDATE open_positions SET stop_order_id=?",
                ("unverified-stop-reference",),
            )
        report = self.inspect()
        self.assertEqual(report["counts"]["platform_positions_without_unique_exchange_exits"], 1)
        self.assertIn("exchange_protective_order_ids_unverified", report["issues"])

    def test_missing_required_table_is_never_treated_as_empty(self):
        self.create_db(exits=True)
        with sqlite3.connect(self.db_path) as db:
            db.execute("DROP TABLE strategy_order_intents")
        report = self.inspect()
        self.assertIn(
            "required_table_or_columns_missing:strategy_order_intents",
            report["issues"],
        )

    def test_invalid_sqlite_content_fails_closed(self):
        self.db_path.write_bytes(b"this is not a sqlite database")
        report = self.inspect()
        self.assertIn("readonly_ledger_query_failed", report["issues"])
        self.assertFalse(report["collector_install_allowed"])


if __name__ == "__main__":
    unittest.main()
