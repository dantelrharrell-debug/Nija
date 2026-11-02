"""Synthetic log fixtures; never import trading runtime or use credentials."""
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.nija_kraken_instance_diagnostic import (
    BASELINE, SERVICE, _read_regular, classify_log, inspect_instance, inspect_render_api,
)


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

    def test_wrong_service_or_commit_never_inspects_processes(self) -> None:
        for environment, reason in (
            ({}, "service_identity_mismatch"),
            ({"RENDER_SERVICE_ID": SERVICE}, "baseline_commit_mismatch"),
        ):
            with patch.dict("os.environ", environment, clear=True), patch.object(Path, "iterdir") as scan:
                self.assertEqual(inspect_instance(), {"status": "BLOCKED", "reason": reason})
                scan.assert_not_called()

    def test_api_missing_authorization_never_requests(self) -> None:
        for environment, reason in (
            ({}, "render_api_credential_unavailable"),
            ({"RENDER_API_KEY": "synthetic-only"}, "current_instance_identity_unavailable"),
        ):
            with patch.dict("os.environ", environment, clear=True), patch(
                "scripts.nija_kraken_instance_diagnostic.urlopen"
            ) as request:
                report = inspect_render_api()
                self.assertEqual(report["failures"], [reason])
                self.assertFalse(report["allow_new_orders"])
                request.assert_not_called()

    def test_baseline_is_an_exact_public_commit_pin(self) -> None:
        self.assertRegex(BASELINE, r"^[0-9a-f]{40}$")

    def test_api_logs_must_match_the_current_instance(self) -> None:
        for observed_instance, accepted in (
            ("wrong-instance", False), ("zsc58", False), (SERVICE + "-zsc58", True),
            (SERVICE + "-7d458c8976-zsc58", True), ("58", False),
        ):
            with self.subTest(instance=observed_instance):
                responses = [
                    {"id": SERVICE, "ownerId": "tea-synthetic"},
                    [{"deploy": {
                        "id": "dep-synthetic", "status": "live",
                        "commit": {"id": BASELINE}, "createdAt": "2026-11-02T00:00:00Z",
                    }}],
                ] + [{
                    "logs": [{
                        "timestamp": "2026-11-02T00:00:01Z",
                        "message": "EAPI:Invalid signature private-canary",
                        "labels": [{"name": "instance", "value": observed_instance}],
                    }],
                }] * 7
                with patch.dict("os.environ", {
                    "RENDER_API_KEY": "synthetic-only",
                    "EXPECTED_RENDER_INSTANCE": SERVICE + "-7d458c8976-zsc58",
                }, clear=True), patch(
                    "scripts.nija_kraken_instance_diagnostic.urlopen",
                    side_effect=[io.BytesIO(json.dumps(row).encode()) for row in responses],
                ):
                    report = inspect_render_api()
                self.assertEqual("INVALID_SIGNATURE" in report["log_signals"], accepted)
                self.assertNotIn("private-canary", json.dumps(report))
                self.assertNotIn("synthetic-only", json.dumps(report))
                self.assertFalse(report["allow_new_orders"])
