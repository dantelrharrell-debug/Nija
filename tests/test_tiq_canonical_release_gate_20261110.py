"""Offline release-gate regression: missing canonical evidence never certifies."""
from pathlib import Path
import hashlib
import json
import unittest


def verify_export(path, expected_sha256, approved_design_sha256, browser_evidence):
    if not expected_sha256 or not approved_design_sha256 or not browser_evidence:
        return False
    p = Path(path)
    if not p.is_file() or p.is_symlink():
        return False
    actual = hashlib.sha256(p.read_bytes()).hexdigest()
    if actual != expected_sha256:
        return False
    required = {"chromium", "webkit", "mobile", "keyboard", "reduced_motion",
                "storage_denied", "practice_lab_4", "scorecard", "voiceover", "talkback"}
    return required.issubset(browser_evidence) and all(
        browser_evidence.get(key) is True for key in required
    )


class ReleaseGateTests(unittest.TestCase):
    def test_missing_export_denied(self):
        self.assertFalse(verify_export("/nonexistent/ionos.zip", "abc", "design", {"chromium": True}))

    def test_missing_design_denied(self):
        self.assertFalse(verify_export("/nonexistent/ionos.zip", "abc", "", {}))

    def test_missing_browser_evidence_denied(self):
        self.assertFalse(verify_export("/nonexistent/ionos.zip", "abc", "design", {}))


if __name__ == "__main__":
    unittest.main()
