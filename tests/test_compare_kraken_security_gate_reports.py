"""Regression checks for value-free Kraken security failure attribution."""
import unittest

from scripts.compare_kraken_security_gate_reports import compare


def secret(findings, outcome="unbaselined_candidates"):
    return {"scanner": "detect-secrets", "outcome": outcome, "findings": findings}


def hook(failed, outcome="failed"):
    return {"outcome": outcome, "failed_hooks": failed}


class SecurityAttributionTests(unittest.TestCase):
    def test_existing_findings_are_not_new(self):
        old = secret([{"path": "legacy.py", "line": 3, "type": "Secret Keyword"}])
        new = secret([{"path": "legacy.py", "line": 99, "type": "Secret Keyword"}])
        result = compare(old, new, hook(["bandit"]), hook(["bandit"]))
        self.assertEqual(result["new_candidate_count"], 0)
        self.assertFalse(result["head_is_certified"])
        self.assertEqual(result["previously_failing_hooks"], ["bandit"])

    def test_new_findings_and_hooks_remain_visible(self):
        old = secret([{"path": "legacy.py", "line": 3, "type": "Secret Keyword"}])
        new = secret([
            {"path": "legacy.py", "line": 7, "type": "Secret Keyword"},
            {"path": "new.py", "line": 8, "type": "Private Key"},
        ])
        result = compare(old, new, hook(["bandit"]), hook(["bandit", "detect-secrets"]))
        self.assertEqual(result["new_candidate_count"], 1)
        self.assertEqual(result["newly_failing_hooks"], ["detect-secrets"])
        self.assertEqual(result["new_candidate_locations"], [
            {"path": "new.py", "detector": "Private Key", "count": 1}
        ])

    def test_no_candidate_values_are_copied(self):
        finding = {"path": "example.py", "line": 2, "type": "Secret Keyword", "secret": "DO_NOT_EXPOSE"}
        result = compare(secret([],"clean"),secret([finding]),hook([],"passed"),hook([],"passed"))
        self.assertNotIn("DO_NOT_EXPOSE", str(result))
        self.assertFalse(result["head_is_certified"])

    def test_clean_gates_can_be_reported(self):
        result = compare(secret([],"clean"),secret([],"clean"),hook([],"passed"),hook([],"passed"))
        self.assertTrue(result["head_is_certified"])

    def test_missing_finding_list_fails_closed(self):
        with self.assertRaises(ValueError):
            compare({"scanner": "detect-secrets", "outcome": "clean"},secret([],"clean"),
                    hook([],"passed"),hook([],"passed"))

    def test_scanner_error_never_certifies(self):
        result = compare(secret([],"clean"),secret([],"scanner_error"),hook([],"passed"),hook([],"passed"))
        self.assertFalse(result["head_is_certified"])


if __name__ == "__main__":
    unittest.main()
