"""Offline enforcement and non-disclosure checks for pre-commit reporting."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from scripts.run_precommit_validation import COMMAND, run, summarize


class PrecommitReportTests(unittest.TestCase):
    def invoke(self, *, code=0, output="", failure=None):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "report.json"
            stream = io.StringIO()
            with patch("scripts.run_precommit_validation.subprocess.run") as execute:
                if failure is not None:
                    execute.side_effect = failure
                else:
                    execute.return_value = subprocess.CompletedProcess(COMMAND, code, output, "")
                with contextlib.redirect_stdout(stream):
                    status = run(path)
                kwargs = execute.call_args.kwargs
                self.assertEqual(execute.call_args.args[0], COMMAND)
                self.assertEqual(COMMAND, ["pre-commit", "run", "--all-files", "--show-diff-on-failure"])
                self.assertEqual(kwargs["stdin"], subprocess.DEVNULL)
                self.assertEqual(kwargs["timeout"], 1200)
                self.assertTrue(kwargs["capture_output"])
                self.assertFalse(kwargs["check"])
                self.assertFalse(kwargs["shell"])
            return status, json.loads(path.read_text()), stream.getvalue()

    def test_success(self):
        status, report, _ = self.invoke(output="Detect secrets........Passed\n")
        self.assertEqual(status, 0)
        self.assertEqual(report["outcome"], "passed")

    def test_failures_preserve_exit_and_identify_allowlisted_hooks(self):
        for code in (1, 2, 42, 183):
            with self.subTest(code=code):
                status, report, _ = self.invoke(code=code, output="Detect secrets........Failed\n")
                self.assertEqual(status, code)
                self.assertEqual(report["failed_hooks"], ["detect-secrets"])

    def test_colored_hook_failure(self):
        self.assertEqual(summarize("\x1b[31mTruffleHog secret scanner...Failed\x1b[0m\n")["failed_hooks"],
                         ["trufflehog"])

    def test_raw_output_never_reaches_report_or_console(self):
        marker = "PRIVATE_CANDIDATE_VALUE"
        _, report, output = self.invoke(code=1, output=marker + "\nUNKNOWN...Failed\n")
        self.assertNotIn(marker, json.dumps(report) + output)
        self.assertEqual(report["failed_hooks"], [])

    def test_installation_errors_are_classified_without_exception_text(self):
        _, report, output = self.invoke(code=3, output="InvalidManifestError: PRIVATE_DETAIL")
        self.assertEqual(report["categories"], ["hook_manifest_error"])
        self.assertNotIn("PRIVATE_DETAIL", json.dumps(report) + output)

    def test_mutated_files_still_fail(self):
        status, report, _ = self.invoke(code=1, output="files were modified by this hook")
        self.assertEqual(status, 1)
        self.assertEqual(report["categories"], ["hook_modified_files"])

    def test_reported_failure_with_zero_exit_is_rejected(self):
        status, _, _ = self.invoke(output="Detect secrets...Failed\n")
        self.assertEqual(status, 2)

    def test_negative_exit_is_rejected(self):
        status, _, _ = self.invoke(code=-9)
        self.assertEqual(status, 2)

    def test_runner_exceptions_do_not_disclose_output(self):
        for error, code in ((FileNotFoundError("PRIVATE_DETAIL"), 2),
                            (subprocess.TimeoutExpired(COMMAND, 1200, output="PRIVATE_DETAIL"), 124),
                            (subprocess.SubprocessError("PRIVATE_DETAIL"), 2)):
            with self.subTest(kind=type(error).__name__):
                status, report, output = self.invoke(failure=error)
                self.assertEqual(status, code)
                self.assertEqual(report["outcome"], "runner_error")
                self.assertNotIn("PRIVATE_DETAIL", json.dumps(report) + output)


if __name__ == "__main__":
    unittest.main()
