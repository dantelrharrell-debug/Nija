"""No-network, read-only tests for the NIJA canonical lead source audit."""
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from website_persisted_lead_audit import count_saved_submissions


class PersistedLeadAuditTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name, "private-intake.sqlite3")
        with sqlite3.connect(self.path) as conn:
            conn.executescript("""
                CREATE TABLE website_leads (
                    event_key TEXT PRIMARY KEY,
                    form_name TEXT NOT NULL,
                    email TEXT NOT NULL,
                    received_at TEXT NOT NULL
                );
            """)
            conn.executemany(
                "INSERT INTO website_leads VALUES (?,?,?,?)",
                [
                    ("one", "free_assessment", "PERSON@EXAMPLE.COM", "2026-10-06T09:00:00Z"),
                    ("two", "free_assessment", "person@example.com", "2026-10-06T09:03:00Z"),
                    ("three", "pilot_application", "second@example.com", "2026-10-15T17:00:00Z"),
                    ("four", "untrusted-phone-and-email@private.test", "third@example.com", "2026-10-18T17:00:00Z"),
                    ("last-month", "founding_waitlist", "old@example.com", "2026-09-30T23:59:00Z"),
                ],
            )

    def test_counts_saved_not_ad_conversion_events(self):
        data = count_saved_submissions(str(self.path), "2026-10")
        self.assertEqual(data["persisted_submissions"], 4)
        self.assertEqual(data["distinct_submission_ids"], 4)
        self.assertEqual(data["distinct_contact_emails"], 3)
        self.assertEqual(data["status"], "observed_not_certified")
        self.assertIs(data["qualified_leads_verified"], False)
        self.assertIs(data["complete_source_inventory"], False)

    def test_private_form_labels_and_emails_are_not_exposed(self):
        data = count_saved_submissions(str(self.path), "2026-10")
        result = repr(data)
        self.assertNotIn("person@example.com", result)
        self.assertNotIn("private.test", result)
        self.assertIn("other", result)
        by_name = {x["form_category"]: x["submissions"] for x in data["forms"]}
        self.assertEqual(by_name["free_assessment"], 2)
        self.assertEqual(by_name["pilot_application"], 1)
        self.assertEqual(by_name["other"], 1)

    def test_receipt_month_not_client_submission_month(self):
        october = count_saved_submissions(str(self.path), "2026-10")
        september = count_saved_submissions(str(self.path), "2026-09")
        self.assertEqual(october["persisted_submissions"], 4)
        self.assertEqual(september["persisted_submissions"], 1)

    def test_invalid_period_rejected(self):
        with self.assertRaises(ValueError):
            count_saved_submissions(str(self.path), "../2026-10")
        with self.assertRaises(ValueError):
            count_saved_submissions(str(self.path), "2026-13")

    def test_missing_file_not_created(self):
        missing = Path(self.temporary.name, "missing.sqlite3")
        with self.assertRaises(FileNotFoundError):
            count_saved_submissions(str(missing), "2026-10")
        self.assertFalse(missing.exists())

    def test_missing_authoritative_table_denied(self):
        wrong = Path(self.temporary.name, "wrong.sqlite3")
        with sqlite3.connect(wrong) as conn:
            conn.execute("CREATE TABLE other_leads (email TEXT)")
        with self.assertRaises(RuntimeError):
            count_saved_submissions(str(wrong), "2026-10")

    def test_database_read_only(self):
        before = self.path.read_bytes()
        count_saved_submissions(str(self.path), "2026-10")
        after = self.path.read_bytes()
        self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
