"""CI-only regression checks: no unexpected import failure may be normalized away."""
from __future__ import annotations

import unittest

from unittest.mock import patch

from scripts.run_unittest_baseline import (
    _normalize_named_import_failure_ids,
    _load_named_modules_like_discovery,
)


class NamedImportFailureNormalizationTests(unittest.TestCase):
    def test_known_discovery_import_error_maps_to_exact_baseline_id(self) -> None:
        baseline = {("ERROR", "unittest.loader._FailedTest.bot.test_writer_authority")}
        observed = {("ERROR", "unittest.loader._FailedTest.test_writer_authority")}
        actual = _normalize_named_import_failure_ids(
            observed, ["bot.test_writer_authority"], baseline
        )
        self.assertEqual(baseline, actual)

    def test_unknown_import_error_remains_a_new_failure(self) -> None:
        baseline = {("ERROR", "unittest.loader._FailedTest.bot.test_writer_authority")}
        observed = {("ERROR", "unittest.loader._FailedTest.test_brand_new")}
        actual = _normalize_named_import_failure_ids(
            observed, ["bot.test_brand_new"], baseline
        )
        self.assertEqual(observed, actual)

    def test_ambiguous_short_name_must_not_remap(self) -> None:
        baseline = {
            ("ERROR", "unittest.loader._FailedTest.bot.test_common"),
            ("ERROR", "unittest.loader._FailedTest.tests.test_common"),
        }
        observed = {("ERROR", "unittest.loader._FailedTest.test_common")}
        actual = _normalize_named_import_failure_ids(
            observed, ["bot.test_common", "tests.test_common"], baseline
        )
        self.assertEqual(observed, actual)

    def test_root_level_existing_baseline_is_unchanged(self) -> None:
        baseline = {("ERROR", "unittest.loader._FailedTest.test_risk_freeze")}
        actual = _normalize_named_import_failure_ids(
            baseline, ["test_risk_freeze"], baseline
        )
        self.assertEqual(baseline, actual)

    def test_failure_kind_cannot_be_silently_changed(self) -> None:
        baseline = {("FAIL", "unittest.loader._FailedTest.bot.test_writer_authority")}
        observed = {("ERROR", "unittest.loader._FailedTest.test_writer_authority")}
        actual = _normalize_named_import_failure_ids(
            observed, ["bot.test_writer_authority"], baseline
        )
        self.assertEqual(observed, actual)


class DiscoveryParityTests(unittest.TestCase):
    def test_missing_module_is_preserved_as_explicit_failed_test(self) -> None:
        with patch(
            "scripts.run_unittest_baseline.importlib.import_module",
            side_effect=ImportError("simulated missing module"),
        ):
            suite = _load_named_modules_like_discovery(["bot.test_missing_module"])
        result = unittest.TestResult()
        suite.run(result)
        self.assertEqual(1, result.testsRun)
        self.assertEqual(1, len(result.errors))
        self.assertEqual(
            "unittest.loader._FailedTest.bot.test_missing_module",
            result.errors[0][0].id(),
        )

    def test_module_level_pytest_style_baseexception_is_not_lost(self) -> None:
        class ModuleSkipLike(BaseException):
            pass

        with patch(
            "scripts.run_unittest_baseline.importlib.import_module",
            side_effect=ModuleSkipLike("synthetic pytest.skip"),
        ):
            suite = _load_named_modules_like_discovery(["test_optional_module"])
        result = unittest.TestResult()
        suite.run(result)
        self.assertEqual(1, result.testsRun)
        self.assertEqual(1, len(result.errors))
        self.assertEqual(
            "unittest.loader._FailedTest.test_optional_module",
            result.errors[0][0].id(),
        )

    def test_unittest_skip_preserves_discovery_skip_semantics(self) -> None:
        with patch(
            "scripts.run_unittest_baseline.importlib.import_module",
            side_effect=unittest.SkipTest("synthetic legitimate unittest skip"),
        ):
            suite = _load_named_modules_like_discovery(["bot.test_skipped_module"])
        result = unittest.TestResult()
        suite.run(result)
        self.assertEqual(1, result.testsRun)
        self.assertFalse(result.errors)
        self.assertEqual(1, len(result.skipped))


class PackageImportOrderTests(unittest.TestCase):
    def test_preloaded_bot_package_cannot_be_shadowed_by_legacy_bot_py(self) -> None:
        import importlib
        from pathlib import Path
        import sys

        # Replicate the sys.path edit made by the seven old root test scripts.
        package = importlib.import_module("bot")
        self.assertTrue(hasattr(package, "__path__"))
        package_dir = Path(package.__file__).resolve().parent
        self.assertEqual(package_dir.name, "bot")
        with patch.object(sys, "path", [str(package_dir), *sys.path]):
            resolved = importlib.import_module("bot")
            self.assertIs(resolved, package)
            self.assertTrue(hasattr(resolved, "__path__"))


if __name__ == "__main__":
    unittest.main()
