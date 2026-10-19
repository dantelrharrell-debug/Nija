"""Offline safety tests for the release-only check-first backport script."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/backport_release_capital_kraken_20261019.py"
spec = importlib.util.spec_from_file_location("release_backport", SCRIPT)
assert spec and spec.loader
backport = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backport)


class ReleaseBackportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "bot").mkdir()
        (self.root / backport.MANAGER).write_text(
            "prefix\n" + backport.ANCHOR + "            authority = get_capital_authority()\n"
            + backport.OLD_FALLBACK + "\n",
            encoding="utf-8",
        )
        (self.root / backport.KRAKEN).write_text(
            "for pair in trades:\n    " + backport.OLD_PAIR + "\n",
            encoding="utf-8",
        )

    def tearDown(self):
        self.tmp.cleanup()

    def test_check_only_does_not_write_source(self):
        old = (self.root / backport.MANAGER).read_bytes()
        changes, statuses = backport.plan(self.root)
        self.assertEqual(len(changes), 2)
        self.assertEqual(len(statuses), 2)
        self.assertEqual((self.root / backport.MANAGER).read_bytes(), old)

    def test_rewrite_is_fail_closed_and_exact_match_only(self):
        changes, _ = backport.plan(self.root)
        for path, value in changes.items():
            path.write_text(value, encoding="utf-8")
        capital = (self.root / backport.MANAGER).read_text(encoding="utf-8")
        kraken = (self.root / backport.KRAKEN).read_text(encoding="utf-8")
        self.assertIn("coordinator_snapshot_missing", capital)
        self.assertIn("capital_publication_unchanged=true", capital)
        self.assertIn("if pair not in pair_set:", kraken)
        self.assertNotIn("currency not in pair", kraken)
        repeat, _ = backport.plan(self.root)
        self.assertFalse(repeat)

    def test_unknown_source_shape_aborts(self):
        (self.root / backport.KRAKEN).write_text("different code\n", encoding="utf-8")
        with self.assertRaises(ValueError):
            backport.plan(self.root)

    def test_duplicate_anchor_aborts(self):
        manager = self.root / backport.MANAGER
        manager.write_text(manager.read_text(encoding="utf-8") + backport.ANCHOR, encoding="utf-8")
        with self.assertRaises(ValueError):
            backport.plan(self.root)


if __name__ == "__main__":
    unittest.main()
