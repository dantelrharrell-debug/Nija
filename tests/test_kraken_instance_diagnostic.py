"""Synthetic log fixtures; never import trading runtime or use credentials."""
from datetime import datetime, timezone
import json
from pathlib import Path
import tempfile
import unittest

from scripts.nija_kraken_instance_diagnostic import _read_regular, classify_log


class InstanceDiagnosticTests(unittest.TestCase):
    """Current-process evidence must be bounded and non-sensitive."""

    def test_only_current_timestamped_evidence_is_counted(self) -> None:
        now = datetime(2026, 11, 2, tzinfo=timezone.utc).timestamp()
        text = "\n".join((
            "2026-11-01 23:59:59 EAPI:Invalid nonce",
            "2026-11-02 00:00:01 EAPI:Invalid signature secret=must-not-escape",
            "2026-11-02 00:00:02 collector_installed=false producer_status=collector_missing",
            "EAPI:Invalid key",
        ))
        result = classify_log(text, since=now)
        self.assertEqual(result, {"INVALID_SIGNATURE": 1, "COLLECTOR_MISSING": 1})
        self.assertNotIn("must-not-escape", json.dumps(result))

    def test_unknown_text_never_leaves_classifier(self) -> None:
        self.assertEqual(classify_log("2026-11-02 00:00:01 private payload", since=0), {})

    def test_file_budget_and_symlink_refusal(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "log"
            path.write_bytes(b"0123456789")
            self.assertEqual(_read_regular(path, 3, tail=True), b"789")
            with self.assertRaises(ValueError):
                _read_regular(path, 3)
            link = Path(root) / "link"
            link.symlink_to(path)
            with self.assertRaises(OSError):
                _read_regular(link, 20)
