"""Regression tests for read-only startup-attempt diagnosis."""
import sqlite3
from pathlib import Path
import tempfile
import unittest
from scripts.nija_startup_attempt_audit_v441 import inspect


class StartupAttemptAuditTests(unittest.TestCase):
    def test_missing_database_does_not_claim_execution_proof(self):
        with tempfile.TemporaryDirectory() as d:
            result = inspect(Path(d) / "missing.db")
        self.assertFalse(result["database_present"])
        self.assertEqual(result["unresolved_count"], 0)

    def test_existing_directory_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            result = inspect(Path(d))
        self.assertFalse(result["proof_admissible_by_attempt_state"])
        self.assertFalse(result["database_present"])
        self.assertIsNotNone(result["error"])

    def test_broken_symlink_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            link = Path(d) / "broken.db"
            link.symlink_to(Path(d) / "missing.db")
            result = inspect(link)
        self.assertFalse(result["proof_admissible_by_attempt_state"])
        self.assertIsNotNone(result["error"])

    def test_unresolved_is_fail_closed_and_no_rows_modified(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "attempts.db"
            connection = sqlite3.connect(path)
            connection.execute(
                "CREATE TABLE startup_attempts (state TEXT, entry_order_id TEXT, exit_order_id TEXT)"
            )
            connection.executemany("INSERT INTO startup_attempts VALUES(?,?,?)",
                                   [("claimed", None, None), ("completed", "entry", "exit"),
                                    ("entry_pending", "entry", None)])
            connection.commit()
            connection.close()
            before = path.read_bytes()
            result = inspect(path)
            after = path.read_bytes()
        self.assertEqual(before, after)
        self.assertTrue(result["readable"])
        self.assertEqual(result["unresolved_count"], 2)
        self.assertFalse(result["proof_admissible_by_attempt_state"])

    def test_completed_attempt_requires_both_broker_order_ids(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "attempts.db"
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "CREATE TABLE startup_attempts (state TEXT, "
                    "entry_order_id TEXT, exit_order_id TEXT)"
                )
                connection.executemany("INSERT INTO startup_attempts VALUES(?,?,?)", [
                    ("completed", None, None), ("completed", "entry", " "),
                    (None, "entry", "exit"), ("completed", "entry", "exit"),
                ])
            before = path.read_bytes()
            result = inspect(path)
            self.assertEqual(before, path.read_bytes())
        self.assertTrue(result["readable"])
        self.assertEqual(result["unresolved_count"], 3)
        self.assertFalse(result["proof_admissible_by_attempt_state"])

    def test_completed_with_null_or_blank_order_ids_remains_unresolved(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "attempts.db"
            with sqlite3.connect(path) as connection:
                connection.execute(
                    "CREATE TABLE startup_attempts (state TEXT, "
                    "entry_order_id TEXT, exit_order_id TEXT)"
                )
                connection.executemany(
                    "INSERT INTO startup_attempts VALUES (?, ?, ?)",
                    [("completed", "ENTRY1", ""), ("completed", "ENTRY2", "EXIT2")],
                )
            before = path.read_bytes()
            result = inspect(path)
            self.assertEqual(path.read_bytes(), before)
        self.assertTrue(result["readable"])
        self.assertEqual(result["unresolved_count"], 1)
        self.assertFalse(result["proof_admissible_by_attempt_state"])

    def test_legacy_schema_cannot_claim_proof(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "attempts.db"
            with sqlite3.connect(path) as connection:
                connection.execute("CREATE TABLE startup_attempts (state TEXT)")
                connection.execute("INSERT INTO startup_attempts VALUES ('completed')")
            result = inspect(path)
        self.assertTrue(result["readable"])
        self.assertEqual(result["unresolved_count"], 0)
        self.assertFalse(result["proof_admissible_by_attempt_state"])

    def test_invalid_schema_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "attempts.db"
            with sqlite3.connect(path) as connection:
                connection.execute("CREATE TABLE unrelated (id INTEGER)")
            result = inspect(path)
        self.assertFalse(result["proof_admissible_by_attempt_state"])
        self.assertEqual(result["error"], "OperationalError")


if __name__ == "__main__":
    unittest.main()
