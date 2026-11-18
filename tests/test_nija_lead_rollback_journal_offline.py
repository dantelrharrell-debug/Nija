"""Offline safety regression for a hot SQLite rollback journal.

Separated from the exact-source reviewed synthetic fixture so its reviewed
fingerprint remains byte-identical. Uses a throwaway temporary database only.
"""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.nija_lead_storage_preflight import _sqlite_summary


class LeadRollbackJournalSafetyTests(unittest.TestCase):
    def test_hot_rollback_journal_blocks_sqlite_without_touching_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            lead_db = root / "website_leads.sqlite3"
            with sqlite3.connect(lead_db) as conn:
                conn.execute(
                    "CREATE TABLE website_leads (event_key TEXT PRIMARY KEY, "
                    "form_name TEXT, email TEXT, received_at TEXT)"
                )
                conn.execute(
                    "INSERT INTO website_leads VALUES (?, ?, ?, ?)",
                    ("offline-qa", "fixture", "synthetic@example.test", "2026-11-18"),
                )

            journal = Path(str(lead_db) + "-journal")
            journal.write_bytes(b"synthetic hot rollback journal")
            before = {p.name: p.read_bytes() for p in root.iterdir()}

            with patch("sqlite3.connect", side_effect=AssertionError("SQLite must not open")):
                result = _sqlite_summary(lead_db)

            self.assertEqual(result["read_error"], "rollback_journal_requires_offline_snapshot")
            self.assertIsNone(result["row_count"])
            self.assertEqual(before, {p.name: p.read_bytes() for p in root.iterdir()})


if __name__ == "__main__":
    unittest.main()
