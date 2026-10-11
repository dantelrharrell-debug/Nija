"""Regression tests for v447's fail-closed account JSON preservation.

These use only temporary test fixtures. They never connect to Render or brokers.
Run: python -m unittest discover -s tests -p 'test_nija_account_state_preservation_v447.py' -v
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "scripts" / "nija_account_state_preservation_v447.py"
SPEC = importlib.util.spec_from_file_location("nija_account_state_preservation_v447", SOURCE)
assert SPEC and SPEC.loader
preserver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(preserver)


class AccountStatePreservationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.positions = root / "positions"
        self.entries = root / "entry_prices"
        self.output = root / "recovery"
        for directory in (self.positions, self.entries, self.output):
            directory.mkdir()
        self.position = self.positions / "platform__kraken.json"
        self.entry = self.entries / "platform__kraken.json"
        self.position.write_bytes(b'{"BTC-USD":{"quantity":0.01,"entry_price":100}}')
        self.entry.write_bytes(b'{"BTC-USD":{"price":100}}')
        self.source_hashes = {
            p: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (self.position, self.entry)
        }

    def capture(self):
        return preserver.capture(self.positions, self.entries, self.output)

    def test_preserves_both_scopes_and_isolated_restore(self):
        result = self.capture()
        bundle = Path(result["archive"])
        self.assertEqual(result["scope_counts"], {"positions": 1, "entry_prices": 1})
        self.assertTrue(result["isolated_restore_verified"])
        self.assertFalse(result["off_host_retention_verified"])
        self.assertFalse(result["live_trading_authorized"])
        self.assertFalse(result["cross_store_atomicity_verified"])
        self.assertEqual(stat.S_IMODE(bundle.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(bundle.parent.stat().st_mode), 0o700)
        self.assertTrue(preserver.verify_bundle(bundle, result["sha256"], isolated_restore=True)["isolated_restore_verified"])
        for path, original_digest in self.source_hashes.items():
            self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), original_digest)

    def test_tampering_archive_fails_source_digest(self):
        result = self.capture()
        bundle = Path(result["archive"])
        changed = self.output / "changed.json"
        changed.write_bytes(bundle.read_bytes().replace(b'"scopes":["positions"', b'"scopes":["different"'))
        with self.assertRaises(ValueError):
            preserver.verify_bundle(changed, result["sha256"])

    def test_invalid_member_hash_fails_even_with_new_outer_hash(self):
        result = self.capture()
        bundle = Path(result["archive"])
        obj = json.loads(bundle.read_bytes())
        obj["records"][0]["sha256"] = "0" * 64
        changed = self.output / "changed.json"
        raw = (json.dumps(obj, separators=(",", ":"), sort_keys=True) + "\n").encode()
        changed.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "member_digest_mismatch"):
            preserver.verify_bundle(changed, hashlib.sha256(raw).hexdigest())

    def test_duplicate_record_fails(self):
        result = self.capture()
        obj = json.loads(Path(result["archive"]).read_bytes())
        obj["records"].append(dict(obj["records"][0]))
        changed = self.output / "duplicate.json"
        raw = json.dumps(obj).encode()
        changed.write_bytes(raw)
        with self.assertRaisesRegex(ValueError, "duplicate_member"):
            preserver.verify_bundle(changed, hashlib.sha256(raw).hexdigest())

    def test_source_member_symlink_fails(self):
        self.position.unlink()
        self.position.symlink_to(self.entry)
        with self.assertRaises(ValueError):
            self.capture()

    def test_source_directory_symlink_fails(self):
        link = Path(self.temp.name) / "positions-link"
        link.symlink_to(self.positions, target_is_directory=True)
        with self.assertRaises(OSError):
            preserver.capture(link, self.entries, self.output)

    def test_output_directory_nested_under_source_fails(self):
        nested = self.positions / "recovery"
        nested.mkdir()
        with self.assertRaisesRegex(ValueError, "output_inside_source"):
            preserver.capture(self.positions, self.entries, nested)

    def test_unexpected_directory_member_fails(self):
        (self.positions / "unrecognized.txt").write_text("never archive")
        with self.assertRaisesRegex(ValueError, "unexpected_member_name"):
            self.capture()

    def test_missing_entry_prices_directory_fails(self):
        self.entries.rmdir() if not list(self.entries.iterdir()) else self.entry.unlink()
        if self.entries.exists():
            self.entries.rmdir()
        with self.assertRaises(OSError):
            self.capture()

    def test_verify_rejects_wrong_digest_format(self):
        result = self.capture()
        with self.assertRaisesRegex(ValueError, "invalid_source_sha256"):
            preserver.verify_bundle(result["archive"], "not-a-sha")


if __name__ == "__main__":
    unittest.main()
