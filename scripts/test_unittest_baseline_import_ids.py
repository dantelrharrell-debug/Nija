"""CI-only regression checks: no unexpected import failure may be normalized away."""
from __future__ import annotations

import unittest

from scripts.run_unittest_baseline import _normalize_named_import_failure_ids


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


if __name__ == "__main__":
    unittest.main()
