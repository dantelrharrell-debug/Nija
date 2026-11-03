"""Synthetic regression coverage for read-only NIJA lead reconciliation."""
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from contextlib import contextmanager
from unittest.mock import patch
from unittest.mock import patch
import scripts.nija_lead_delivery_reconciliation_readonly as reconciliation
from scripts.nija_lead_delivery_reconciliation_readonly import inspect


@contextmanager
def db_transaction(path):
    """Commit on success, roll back on error, and always close test connections."""
    db = sqlite3.connect(path)
    try:
        with db:
            yield db
    finally:
        db.close()


class ReconciliationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.disk = self.root / "disk"
        self.disk.mkdir()
        self.lead = self.disk / "nija_outreach.sqlite3"
        self.forward = self.disk / "nija_lead_forwarding.sqlite3"
        self.env = {
            "NIJA_LEAD_DB_PATH": str(self.lead),
            "NIJA_LEAD_FORWARD_DB_PATH": str(self.forward),
            "NIJA_LEAD_WEBHOOK_TOKEN": "secret-must-never-print",
            "NIJA_LEAD_FORWARD_URL": "https://hooks.zapier.com/hooks/catch/SECRET",
        }

    def tearDown(self):
        self.temp.cleanup()

    def populate(self):
        with db_transaction(self.lead) as db:
            db.execute("CREATE TABLE website_leads(event_key TEXT, email TEXT, received_at TEXT)")
            db.executemany("INSERT INTO website_leads VALUES(?,?,?)", [
                ("a", "one@example.com", "2026-10-20T10:00:00Z"),
                ("b", "ONE@example.com", "2026-10-20T11:00:00Z"),
                ("c", "two@example.com", "2026-10-20T12:00:00Z"),
            ])
            db.execute("CREATE TABLE website_lead_crm_sync(event_key TEXT, state TEXT, last_error_code TEXT)")
            db.executemany("INSERT INTO website_lead_crm_sync VALUES(?,?,?)", [
                ("a", "synced", ""),
                ("b", "synced", ""),
                ("c", "needs_review", "HTTP_422_email"),
            ])
        with db_transaction(self.forward) as db:
            db.execute("CREATE TABLE website_lead_forwarding(event_key TEXT,state TEXT)")
            db.executemany("INSERT INTO website_lead_forwarding VALUES(?,?)", [
                ("a", "pending"), ("b", "pending"), ("c", "sent")
            ])

    def audit(self):
        return inspect(environ=self.env, disk=self.disk,
                       app_default=self.root / "missing.sqlite3",
                       mount_check=lambda _: True)

    def test_aggregate_counts_and_no_secrets(self):
        self.populate()
        before = self.lead.read_bytes()
        report = self.audit()
        self.assertEqual(report["lead_database"]["lead_events"], 3)
        self.assertEqual(report["lead_database"]["unique_emails"], 2)
        self.assertEqual(report["lead_database"]["crm_state_counts"]["synced"], 2)
        self.assertEqual(report["lead_database"]["crm_review_categories"]["HTTP_422_email"], 1)
        self.assertEqual(report["forward_history"]["forwarding_states"]["pending"], 2)
        self.assertEqual(report["configured_forwarding_category"], "zapier")
        self.assertFalse(report["production_pipeline_certified"])
        self.assertFalse(report["bulk_replay_authorized"])
        self.assertEqual(before, self.lead.read_bytes())
        serialized = json.dumps(report)
        for sensitive in ("secret-must-never-print", "SECRET", "one@example.com"):
            self.assertNotIn(sensitive, serialized)

    def test_writer_cannot_change_database_during_scan(self):
        self.populate()
        connect = sqlite3.connect
        writer_blocked = []
        lead_path = self.lead

        class ReadConnection:
            def __init__(self, connection):
                self.connection = connection

            def __enter__(self):
                self.connection.__enter__()
                return self

            def __exit__(self, *args):
                return self.connection.__exit__(*args)

            def execute(self, sql, *args):
                cursor = self.connection.execute(sql, *args)
                if sql.startswith("SELECT COUNT(*), COUNT(DISTINCT"):
                    try:
                        with connect(lead_path, timeout=0.01) as writer:
                            writer.execute(
                                "UPDATE website_lead_crm_sync SET state='synced' "
                                "WHERE state='needs_review'"
                            )
                    except sqlite3.OperationalError:
                        writer_blocked.append(True)
                    else:
                        writer_blocked.append(False)
                return cursor

            def set_progress_handler(self, *args):
                return self.connection.set_progress_handler(*args)

        def connect_for_audit(database, *args, **kwargs):
            connection = connect(database, *args, **kwargs)
            if str(database).startswith(lead_path.resolve().as_uri()):
                return ReadConnection(connection)
            return connection

        with patch.object(reconciliation.sqlite3, "connect", side_effect=connect_for_audit):
            report = self.audit()

        self.assertEqual(writer_blocked, [True])
        self.assertEqual(report["lead_database"]["crm_state_counts"]["needs_review"], 1)

    def test_missing_databases_not_created(self):
        report = self.audit()
        self.assertEqual(report["lead_database"]["status"], "missing")
        self.assertFalse(self.lead.exists())
        self.assertFalse(self.forward.exists())

    def test_wal_sidecar_requires_consistent_snapshot(self):
        self.populate()
        Path(str(self.lead) + "-wal").touch()
        self.assertEqual(self.audit()["lead_database"]["status"], "live_wal_requires_consistent_snapshot")

    def test_scan_uses_lock_respecting_read_transaction(self):
        self.populate()
        connect = sqlite3.connect
        statements = []
        uris = []

        def traced_connect(database, *args, **kwargs):
            uris.append(database)
            db = connect(database, *args, **kwargs)
            db.set_trace_callback(statements.append)
            return db

        with patch("scripts.nija_lead_delivery_reconciliation_readonly.sqlite3.connect",
                   side_effect=traced_connect):
            report = self.audit()

        self.assertEqual(report["lead_database"]["status"], "read_only_counts")
        self.assertIn("mode=ro", uris[0])
        self.assertNotIn("immutable=1", uris[0])
        begin = next(index for index, statement in enumerate(statements)
                     if statement.upper() == "BEGIN")
        first_read = next(index for index, statement in enumerate(statements)
                          if statement.upper().startswith(("SELECT", "PRAGMA TABLE_INFO")))
        self.assertLess(begin, first_read)

    def test_rollback_journal_sidecar_requires_snapshot(self):
        self.populate()
        Path(str(self.lead) + "-journal").touch()
        self.assertEqual(
            self.audit()["lead_database"]["status"],
            "rollback_journal_requires_consistent_snapshot",
        )

    def test_whitespace_primary_override_does_not_use_secondary_path(self):
        self.populate()
        self.env["NIJA_LEAD_DB_PATH"] = "   "
        self.env["NIJA_OUTREACH_DB_PATH"] = str(self.lead)
        report = self.audit()
        self.assertEqual(report["lead_database"]["status"], "invalid_runtime_path")
        self.assertFalse(report["lead_db_on_mounted_disk"])

    def test_literal_tilde_path_is_not_expanded(self):
        self.populate()
        self.env["NIJA_LEAD_DB_PATH"] = "~/nija_outreach.sqlite3"
        report = self.audit()
        self.assertEqual(report["lead_database"]["status"], "missing")
        self.assertFalse(report["lead_db_on_mounted_disk"])

    def test_plain_http_not_accepted_as_forwarding(self):
        self.populate()
        self.env["NIJA_LEAD_FORWARD_URL"] = "http://hooks.zapier.com/SECRET"
        self.assertEqual(self.audit()["configured_forwarding_category"], "missing_or_invalid")

    def test_invalid_forwarding_ports_not_accepted(self):
        self.populate()
        for port in ("not-a-port", "0", "65536"):
            with self.subTest(port=port):
                self.env["NIJA_LEAD_FORWARD_URL"] = f"https://hooks.zapier.com:{port}/hooks/catch/SECRET"
                report = self.audit()
                self.assertFalse(report["configured_forwarding_https"])
                self.assertEqual(report["configured_forwarding_category"], "missing_or_invalid")

    def test_unknown_rejection_code_redacted(self):
        self.populate()
        with db_transaction(self.lead) as db:
            db.execute("UPDATE website_lead_crm_sync SET last_error_code='sensitive-customer@example.com' WHERE state='needs_review'")
        report = self.audit()
        self.assertEqual(report["lead_database"]["crm_review_categories"], {"other": 1})
        self.assertNotIn("sensitive-customer", json.dumps(report))

    def test_unknown_forward_state_redacted(self):
        self.populate()
        with db_transaction(self.forward) as db:
            db.execute("UPDATE website_lead_forwarding SET state='private-token' WHERE event_key='a'")
        report = self.audit()
        self.assertEqual(report["forward_history"]["forwarding_states"]["other"], 1)
        self.assertNotIn("private-token", json.dumps(report))

    def test_symlink_to_disk_is_durable(self):
        self.populate()
        app = self.root / "app"
        app.mkdir()
        (app / "nija_outreach.sqlite3").symlink_to(self.lead)
        self.env["NIJA_LEAD_DB_PATH"] = str(app / "nija_outreach.sqlite3")
        self.assertTrue(self.audit()["lead_db_on_mounted_disk"])

if __name__ == "__main__":
    unittest.main()
