"""Additional offline negative cases for the canonical game evidence gate."""
import hashlib
import tempfile
import unittest
from pathlib import Path

from tests.test_tiq_canonical_release_gate_20261110 import verify_export

REQUIRED = ("chromium", "webkit", "mobile", "keyboard", "reduced_motion",
            "storage_denied", "practice_lab_4", "scorecard", "voiceover", "talkback")


class CanonicalNegativeCases(unittest.TestCase):
    def test_valid_export_hash_alone_never_certifies(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "candidate.zip"
            archive.write_bytes(b"unverified sample, not an IONOS export")
            checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
            self.assertFalse(verify_export(archive, checksum, "unverified-design", {}))

    def test_each_missing_or_failed_browser_gate_denies(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "candidate.zip"
            archive.write_bytes(b"fixture only")
            checksum = hashlib.sha256(archive.read_bytes()).hexdigest()
            all_pass = {key: True for key in REQUIRED}
            for key in REQUIRED:
                for missing in (True, False):
                    evidence = dict(all_pass)
                    if missing:
                        evidence.pop(key)
                    else:
                        evidence[key] = False
                    self.assertFalse(verify_export(archive, checksum, "design", evidence),
                                     (key, missing))

    def test_hash_mismatch_denies_even_when_browser_claims_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "candidate.zip"
            archive.write_bytes(b"fixture only")
            self.assertFalse(verify_export(archive, "0" * 64, "design",
                                           {key: True for key in REQUIRED}))


if __name__ == "__main__":
    unittest.main()
