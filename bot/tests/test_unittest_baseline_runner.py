from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest

from scripts.run_unittest_baseline import (
    _TEST_RESTART_GRACE_ENV_NAMES,
    _observed_failures,
    _parse_baseline,
    main,
)


class UnittestBaselineRunnerTests(unittest.TestCase):
    def test_main_forces_restart_grace_during_run_and_restores_environment(self) -> None:
        saved = {
            name: os.environ.get(name)
            for name in _TEST_RESTART_GRACE_ENV_NAMES
        }
        try:
            for name in _TEST_RESTART_GRACE_ENV_NAMES:
                os.environ[name] = "5"

            # The CI sitecustomize guard permits discovery only inside the
            # checked-out project tree. Keep this synthetic suite inside it.
            with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
                root = Path(directory)
                baseline = root / "baseline.txt"
                baseline.write_text("", encoding="utf-8")
                (root / "__init__.py").write_text("", encoding="utf-8")
                (root / "test_restart_grace.py").write_text(
                    "import os\n"
                    "import unittest\n\n"
                    "class RestartGraceTests(unittest.TestCase):\n"
                    "    def test_runner_forces_safe_grace(self):\n"
                    "        names = (\n"
                    "            'NIJA_WRITER_AUTHORITY_FALLBACK_RESTART_GRACE_S',\n"
                    "            'NIJA_WRITER_AUTHORITY_RESTART_GRACE_S',\n"
                    "            'NIJA_CORE_REGISTRATION_RESTART_GRACE_S',\n"
                    "        )\n"
                    "        self.assertTrue(all(os.environ[name] == '3600' for name in names))\n",
                    encoding="utf-8",
                )

                self.assertEqual(
                    main([
                        "--baseline",
                        str(baseline),
                        "--start-dir",
                        str(root),
                    ]),
                    0,
                )

            for name in _TEST_RESTART_GRACE_ENV_NAMES:
                self.assertEqual(os.environ.get(name), "5")
        finally:
            for name, previous in saved.items():
                if previous is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = previous

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
