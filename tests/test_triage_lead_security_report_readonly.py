"""Synthetic value-free tests; no provider data or network connections."""
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

from scripts.triage_lead_security_report_readonly import summarize, main


class SecretTriageTests(unittest.TestCase):
    def setUp(self):
        self.data = {
            "scanner": "detect-secrets",
            "exit_code": 1,
            "checked_out_commit": "a" * 40,
            "baseline_would_change": False,
            "findings": [
                {"path": "scripts/example.py", "line": 8, "type": "Secret Keyword", "secret_value": "do-not-print"},
                {"path": "docs/sample.md", "line": 21, "type": "Private Key", "secret_value": "do-not-print"},
            ],
        }

    def test_exact_changed_path_attribution_with_blocked_status(self):
        r = summarize(self.data, {"scripts/example.py", "tests/another.py"})
        self.assertEqual(r["candidate_count"], 2)
        self.assertEqual(r["changed_file_candidate_count"], 1)
        self.assertEqual(r["certification"], "BLOCKED")
        self.assertFalse(r["production_pipeline_certified"])

    def test_no_candidate_value_escapes(self):
        self.assertNotIn("do-not-print", json.dumps(summarize(self.data, set())))

    def test_does_not_assume_docs_and_tests_are_safe(self):
        r = summarize(self.data, set())
        self.assertEqual(r["priority_candidate_count"], 1)
        self.assertEqual(r["priority_review_coordinates"][0]["path"], "docs/sample.md")

    def test_rejects_extra_nonpath_data_and_traversal(self):
        for unsafe in ("../secret.txt", "bad\nvalue", "/absolute.txt", "bad//path"):
            self.data["findings"][0]["path"] = unsafe
            with self.assertRaises(ValueError):
                summarize(self.data, set())

    def test_conflicting_clean_status_is_rejected(self):
        self.data["exit_code"] = 0
        with self.assertRaises(ValueError):
            summarize(self.data, set())

    def test_cli_cannot_turn_scan_failure_into_success(self):
        with tempfile.TemporaryDirectory() as directory:
            report = Path(directory) / "report.json"
            report.write_text(json.dumps(self.data), encoding="utf-8")
            output = Path(directory) / "output.json"
            with patch("sys.argv", ["triage", "--report", str(report), "--output", str(output)]):
                with redirect_stderr(io.StringIO()), redirect_stdout(io.StringIO()):
                    status = main()
            self.assertEqual(status, 1)
            self.assertTrue(output.exists())
            self.assertEqual(json.loads(output.read_text())["certification"], "BLOCKED")


if __name__ == "__main__":
    unittest.main()
