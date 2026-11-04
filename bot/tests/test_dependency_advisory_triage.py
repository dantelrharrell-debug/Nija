"""Offline advisory completeness and severity provenance regressions."""
import json
from pathlib import Path
import unittest

from scripts.nija_dependency_advisory_triage import build_triage


class DependencyTriageTests(unittest.TestCase):
    """No alias duplication or absent severity may silently become a clean bill."""

    def test_duplicates_keep_all_aliases_and_fix_branches(self) -> None:
        audit = {"dependencies": [{"name": "urllib3", "version": "1.26.12", "vulns": [
            {"id": "PYSEC-example", "aliases": ["GHSA-example"], "fix_versions": ["1.26.20"]},
            {"id": "PYSEC-example", "aliases": ["CVE-example"], "fix_versions": ["2.8.0"]},
        ]}]}
        severity = {"data": {"a": {"ghsaId": "GHSA-example", "severity": "HIGH", "withdrawnAt": None}}}
        result = build_triage(audit, severity, {"urllib3": "2.8.0"})
        self.assertEqual(result["raw_advisory_record_count"], 2)
        self.assertEqual(result["unique_primary_advisory_ids"], 1)
        row = result["advisories"][0]
        self.assertEqual(row["aliases"], ["CVE-example", "GHSA-example"])
        self.assertEqual(row["reported_fix_versions"], ["1.26.20", "2.8.0"])
        self.assertEqual(row["severity"], "HIGH")
        self.assertEqual(row["priority"], "P1")
        self.assertEqual(row["disposition"], "pin_changed_requires_fresh_resolved_audit")

    def test_missing_or_withdrawn_metadata_is_unknown_not_low_risk(self) -> None:
        audit = {"dependencies": [{"name": "example", "version": "1", "vulns": [
            {"id": "GHSA-example", "aliases": [], "fix_versions": []},
        ]}]}
        for nodes in ({}, {"a": {"ghsaId": "GHSA-example", "severity": "CRITICAL", "withdrawnAt": "2026-01-01"}}):
            result = build_triage(audit, {"data": nodes}, {})
            self.assertEqual(result["unknown_severity_rows"], 1)
            self.assertEqual(result["advisories"][0]["priority"], "UNVERIFIED")
            self.assertEqual(result["advisories"][0]["reported_fix_versions"], [])

    def test_partial_graphql_error_refuses_report(self) -> None:
        with self.assertRaises(ValueError):
            build_triage({"dependencies": []}, {"data": {}, "errors": [{"message": "failed"}]}, {})

    def test_fresh_resolution_matches_aliases_and_distinguishes_removed_packages(self) -> None:
        audit = {"dependencies": [{"name": "example", "version": "1", "vulns": [
            {"id": "PYSEC-example", "aliases": ["GHSA-example"], "fix_versions": ["2"]},
        ]}]}
        for resolved, expected in (
            ({"dependencies": []}, "not_installed_in_fresh_resolved_audit"),
            ({"dependencies": [{"name": "example", "version": "2", "vulns": []}]},
             "not_reported_by_fresh_resolved_audit"),
            ({"dependencies": [{"name": "example", "version": "2", "vulns": [
                {"id": "GHSA-example", "aliases": [], "fix_versions": []},
            ]}]}, "still_reported_by_fresh_resolved_audit"),
        ):
            result = build_triage(audit, {"data": {}}, {}, resolved)
            self.assertEqual(result["advisories"][0]["disposition"], expected)

    def test_committed_inventory_covers_every_baseline_id_and_preserves_residual(self) -> None:
        root = Path(__file__).resolve().parents[2] / "docs/security"
        baseline = json.loads((root / "dependency_triage_20261104.json").read_text())
        self.assertEqual(baseline["raw_advisory_record_count"], 264)
        self.assertEqual(baseline["unique_primary_advisory_ids"], 167)
        rows = baseline["advisories"]
        self.assertEqual(len({row["primary_advisory_id"] for row in rows}), 167)
        self.assertTrue(all(row["severity"] and row["production_exposure"] and row["exploitability"] for row in rows))
        residual = json.loads((root / "dependency_residual_20261104.json").read_text())
        self.assertEqual(residual["unique_primary_advisory_ids"], 1)
        self.assertEqual(residual["advisories"][0]["primary_advisory_id"], "PYSEC-2024-110")
        self.assertEqual(residual["advisories"][0]["severity"], "MODERATE")

    def test_hosted_followup_preserves_candidates_without_secret_values_or_waivers(self) -> None:
        path = Path(__file__).resolve().parents[2] / "docs/security/hosted_scan_blockers_20261104.json"
        report = json.loads(path.read_text())
        self.assertEqual(set(report["image_findings"]), {
            "library/nija", "library/nija-api", "library/nija-dashboard", "library/nija-gateway",
        })
        rows = report["container_advisories"]
        self.assertEqual(report["unique_package_advisory_rows"], len(rows))
        self.assertEqual(report["unique_advisory_ids"], len({row["advisory_id"] for row in rows}))
        self.assertTrue(all(set(row["images"]) <= set(report["image_findings"]) for row in rows))
        self.assertTrue(all("requires" in row["disposition"] for row in rows))
        candidates = report["credential_candidate_locations"]
        self.assertEqual(report["legacy_credential_candidate_count"],
                         sum(len(row["lines"]) for row in candidates))
        self.assertTrue(all(set(row) == {"file", "type", "lines", "disposition"} for row in candidates))
        unreviewed = sum(len(row["lines"]) for row in candidates
                         if row["disposition"].startswith("unreviewed_"))
        self.assertEqual(report["unreviewed_credential_candidate_count"], unreviewed)
        reviewed = [row for row in candidates if not row["disposition"].startswith("unreviewed_")]
        self.assertEqual(len(reviewed), 1)
        self.assertEqual(reviewed[0]["file"], "tests/test_member_broker_http_api.py")
        self.assertIn("public_dummy_fixture", reviewed[0]["disposition"])


if __name__ == "__main__":
    unittest.main()
