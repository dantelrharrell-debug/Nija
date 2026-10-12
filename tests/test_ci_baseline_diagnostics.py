"""Ensure CI timeout diagnostics preserve the complete baseline failure policy."""

from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest


class BaselineDiagnosticTests(unittest.TestCase):
    def run_baseline(self, body: str, baseline: str = "", *options: str,
                     prefix: str = "", preload_source: str | None = None) -> subprocess.CompletedProcess:
        """Run an isolated fixture through the real standard-library CI runner."""
        runner = Path(__file__).resolve().parents[1] / "scripts" / "run_unittest_baseline.py"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "test_sample.py").write_text(
                prefix + "import unittest, time\nclass Example(unittest.TestCase):\n"
                "    def test_sample(self):\n" + body,
                encoding="utf-8",
            )
            known = root / "baseline.txt"
            known.write_text(baseline, encoding="utf-8")
            if preload_source is not None:
                (root / "fixture_client.py").write_text(preload_source, encoding="utf-8")
            return subprocess.run(
                [sys.executable, "-S", str(runner), "--baseline", str(known),
                 "--start-dir", str(root), *options],
                capture_output=True, text=True, timeout=10, check=False,
                env=dict(os.environ, PYTHONPATH=str(root)),
            )

    def test_pass_preserves_success(self):
        result = self.run_baseline("        self.assertTrue(True)\n", "", "--traceback-after", "1")
        self.assertEqual(result.returncode, 0)
        self.assertIn("CI_BASELINE_RATCHET_PASSED tests=1", result.stdout)

    def test_unexpected_failure_still_blocks(self):
        result = self.run_baseline("        self.fail('fixture')\n", "", "--traceback-after", "1")
        self.assertEqual(result.returncode, 1)
        self.assertIn("unexpected=1", result.stdout)

    def test_known_failure_remains_exact(self):
        result = self.run_baseline(
            "        self.fail('fixture')\n", "FAIL test_sample.Example.test_sample\n",
            "--traceback-after", "1",
        )
        self.assertEqual(result.returncode, 0)
        self.assertIn("known=1", result.stdout)

    def test_slow_test_reports_stack_without_changing_result(self):
        result = self.run_baseline("        time.sleep(1.2)\n", "", "--traceback-after", "1")
        self.assertEqual(result.returncode, 0)
        self.assertIn("Timeout (0:00:01)!", result.stderr)
        self.assertIn("test_sample.py", result.stderr)

    def test_nonpositive_diagnostic_interval_rejected(self):
        result = self.run_baseline("        pass\n", "", "--traceback-after", "0")
        self.assertEqual(result.returncode, 2)
        self.assertIn("must be positive", result.stderr)

    def test_dependency_is_loaded_before_discovery_imports_tests(self):
        result = self.run_baseline(
            "        self.assertTrue(True)\n", "", "--preload-module", "fixture_client",
            prefix="import sys\nassert 'fixture_client' in sys.modules\n",
            preload_source="READY = True\n",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("CI_BASELINE_RATCHET_PASSED tests=1", result.stdout)

    def test_preload_failure_cannot_certify_suite_success(self):
        result = self.run_baseline(
            "        self.assertTrue(True)\n", "", "--preload-module", "fixture_client",
            preload_source="raise RuntimeError('fixture preload error')\n",
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("CI_PRELOAD_FAILED", result.stderr)
        self.assertNotIn("CI_BASELINE_RATCHET_PASSED", result.stdout)

    def test_preloading_keeps_unexpected_failures_blocking(self):
        result = self.run_baseline(
            "        self.fail('fixture')\n", "", "--preload-module", "fixture_client",
            preload_source="READY = True\n",
        )
        self.assertEqual(result.returncode, 1)
        self.assertIn("unexpected=1", result.stdout)
