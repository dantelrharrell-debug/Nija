from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from scripts.run_unittest_baseline import _observed_failures, _parse_baseline


class UnittestBaselineRunnerTests(unittest.TestCase):
    def test_parse_baseline_rejects_duplicate_entries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.txt"
            path.write_text(
                "FAIL example.Case.test_one\nFAIL example.Case.test_one\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "duplicate baseline entry"):
                _parse_baseline(path)

    def test_parse_baseline_rejects_multiple_categories_for_one_test(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.txt"
            path.write_text(
                "FAIL example.Case.test_one\nERROR example.Case.test_one\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "multiple baseline categories"):
                _parse_baseline(path)

    def test_parse_baseline_decodes_percent_encoded_test_ids(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.txt"
            path.write_text(
                "FAIL example.Case.test%5Fforty_character_identifier\n",
                encoding="utf-8",
            )

            self.assertEqual(
                _parse_baseline(path),
                {("FAIL", "example.Case.test_forty_character_identifier")},
            )

    def test_observed_failures_preserve_failure_category_and_id(self) -> None:
        class FailingFixture(unittest.TestCase):
            def test_failure(self) -> None:
                self.fail("expected test fixture failure")

            def test_error(self) -> None:
                raise RuntimeError("expected test fixture error")

        suite = unittest.defaultTestLoader.loadTestsFromTestCase(FailingFixture)
        result = unittest.TestResult()

        suite.run(result)

        self.assertEqual(
            _observed_failures(result),
            {
                ("ERROR", FailingFixture("test_error").id()),
                ("FAIL", FailingFixture("test_failure").id()),
            },
        )

    def test_passing_test_is_not_reported(self) -> None:
        class PassingFixture(unittest.TestCase):
            def test_ok(self) -> None:
                self.assertTrue(True)

        suite = unittest.defaultTestLoader.loadTestsFromTestCase(PassingFixture)
        result = unittest.TestResult()

        suite.run(result)

        self.assertEqual(_observed_failures(result), set())
