"""Read-only regression assertions for PR #3865 recovery source pins.

These tests do not grant approval, access Render, or certify production.
"""
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "ops/recovery/render_readonly_baseline.json"
SOURCES = (
    "bot/kraken_live_history_recovery.py",
    "bot/kraken_history_response_journal.py",
)
WORKFLOWS = (
    ".github/workflows/render-recovery-access.yml",
    ".github/workflows/kraken-recovery-gate-diagnostics.yml",
)


def pinned_source_matches(path: Path, expected: str) -> bool:
    """Reject absent, symlinked, or altered sources; never follow symlinks."""
    if path.is_symlink() or not path.is_file():
        return False
    return hashlib.sha256(path.read_bytes()).hexdigest() == expected


class RecoveryPinRegression(unittest.TestCase):
    def test_template_remains_unapproved(self):
        manifest = json.loads(BASELINE.read_text())
        self.assertIs(manifest["operator_approved"], False)
        for key in ("approval_reference", "deployment_id", "commit"):
            self.assertIsNone(manifest[key], key)

    def test_both_sources_match_manifest_and_workflows(self):
        manifest = json.loads(BASELINE.read_text())["source_sha256"]
        for source in SOURCES:
            with self.subTest(source=source):
                self.assertIn(source, manifest)
                digest = manifest[source]
                self.assertRegex(digest, r"^[0-9a-f]{64}$")
                self.assertTrue(pinned_source_matches(ROOT / source, digest))
                for workflow in WORKFLOWS:
                    self.assertIn(digest, (ROOT / workflow).read_text())

    def test_fail_closed_negative_controls(self):
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            expected = hashlib.sha256(b"reviewed source").hexdigest()
            source = directory / "source.py"
            self.assertFalse(pinned_source_matches(source, expected), "missing source")
            source.write_bytes(b"reviewed source")
            self.assertTrue(pinned_source_matches(source, expected))
            source.write_bytes(b"altered source")
            self.assertFalse(pinned_source_matches(source, expected), "tampered source")
            source.unlink()
            target = directory / "target.py"
            target.write_bytes(b"reviewed source")
            source.symlink_to(target)
            self.assertFalse(pinned_source_matches(source, expected), "symlink substitution")


if __name__ == "__main__":
    unittest.main()
