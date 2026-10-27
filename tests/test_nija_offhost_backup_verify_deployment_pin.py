"""Offline regression tests for pinned, independent off-host recovery SHA.

These exercise only a disposable synthetic capture. They NEVER contact Render,
Kraken or a brokerage and never assert that any real backup was restored.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
VERIFY_SCRIPT = ROOT / "ops/recovery/nija_offhost_backup_verify_v4.sh"
VERIFIERS = (
    "nija_state_store_persistence_audit_v441.py",
    "nija_trade_ledger_snapshot_v436.py",
    "nija_account_state_offhost_evidence_v449.py",
    "nija_legacy_global_state_evidence_v462.py",
)
ARCHIVES = (
    "nija-trading-ledger-20261027T160000Z-abcdef.tar.gz",
    "nija-account-state-20261027T160000Z-abcdef.zip",
    "nija-legacy-state-20261027T160000Z-abcdef.zip",
)
EVIDENCE = (
    "CAPTURE_CONTEXT.json",
    "source_persistence_audit.json",
    "ledger_snapshot_receipt.json",
    "account_state_receipt.json",
    "legacy_state_receipt.json",
)
MANIFESTS = (
    "SHA256SUMS",
    "EVIDENCE_SHA256SUMS",
    "VERIFIERS_SHA256SUMS",
)
CURRENT_DEPLOY = "9aa8bf33c46d6ba41c1e909b837fcdd1ce6314c8"
OTHER_DEPLOY = "12a9b0b2bfbfa559dc77553a0a98c09e3f82be64"


def _manifest(root: Path, filename: str, paths: tuple[str, ...]) -> None:
    lines = []
    for path in paths:
        digest = hashlib.sha256((root / path).read_bytes()).hexdigest()
        lines.append(f"{digest}  {path}\n")
    (root / filename).write_text("".join(lines), encoding="ascii")


class OffhostRestoreDeploymentPinTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="nija-offhost-sha-test-")
        self.addCleanup(self.temp.cleanup)
        self.capture = Path(self.temp.name) / "capture"
        self.capture.mkdir(mode=0o700)
        verifiers = self.capture / "verifiers"
        verifiers.mkdir(mode=0o700)
        for name in VERIFIERS:
            shutil.copyfile(ROOT / "scripts" / name, verifiers / name)

        # These archives deliberately are NOT valid recovery data. A matching
        # deployment pin may reach isolated restore validation, never pass it.
        for name in ARCHIVES:
            (self.capture / name).write_bytes(b"synthetic-invalid-archive\n")

        payloads = {
            EVIDENCE[0]: {
                "source_service_id": "srv-d98dsr5aeets73fpbaqg",
                "source_deployed_sha": CURRENT_DEPLOY,
                "executed_on_existing_instance": True,
                "deployment_authorized": False,
                "trading_authorized": False,
            },
            EVIDENCE[1]: {"storage_paths_aligned": True},
            EVIDENCE[2]: {"status": "captured"},
            EVIDENCE[3]: {"status": "captured"},
            EVIDENCE[4]: {"status": "captured"},
        }
        for filename, payload in payloads.items():
            (self.capture / filename).write_text(
                json.dumps(payload, sort_keys=True), encoding="utf-8"
            )
        _manifest(self.capture, MANIFESTS[0], ARCHIVES)
        _manifest(self.capture, MANIFESTS[1], EVIDENCE)
        _manifest(
            self.capture, MANIFESTS[2], tuple("verifiers/" + n for n in VERIFIERS)
        )
        seal_lines = "".join(
            f"{hashlib.sha256((self.capture / name).read_bytes()).hexdigest()}  {name}\n"
            for name in MANIFESTS
        )
        self.seal = hashlib.sha256(seal_lines.encode("ascii")).hexdigest()

    def run_verifier(self, *args: str) -> subprocess.CompletedProcess[str]:
        env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
        return subprocess.run(
            ["bash", str(VERIFY_SCRIPT), str(self.capture), self.seal, *args],
            cwd=str(ROOT), env=env, capture_output=True, text=True,
            timeout=25, check=False,
        )

    def test_matching_independently_supplied_sha_reaches_restore_check(self) -> None:
        result = self.run_verifier(CURRENT_DEPLOY)
        # Identity and manifests pass, but deliberately corrupted synthetic
        # archives MUST fail. This never fabricates a successful restore.
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("OFF_HOST_SOURCE_SEAL=PASS", result.stdout)
        self.assertIn("OFF_HOST_ARCHIVE_AND_RECEIPT_HASHES=PASS", result.stdout)
        self.assertIn("OFF_HOST_PINNED_VERIFIERS=PASS", result.stdout)
        self.assertNotIn("OFF_HOST_RESTORE_AND_ARCHIVE_VERIFICATION=PASS", result.stdout)

    def test_mismatched_deploy_sha_is_denied_even_with_valid_manifests(self) -> None:
        result = self.run_verifier(OTHER_DEPLOY)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("STOP: source identity", result.stderr)
        self.assertNotIn("OFF_HOST_SOURCE_SEAL=PASS", result.stdout)

    def test_missing_independent_deploy_sha_is_denied(self) -> None:
        result = self.run_verifier()
        self.assertEqual(result.returncode, 2)
        self.assertIn("INDEPENDENTLY_CONFIRMED_DEPLOY_SHA", result.stderr)

    def test_malformed_independent_deploy_sha_is_denied(self) -> None:
        result = self.run_verifier("NOT_A_SHA")
        self.assertEqual(result.returncode, 2)
        self.assertIn("INDEPENDENTLY_CONFIRMED_DEPLOY_SHA", result.stderr)


if __name__ == "__main__":
    unittest.main()
