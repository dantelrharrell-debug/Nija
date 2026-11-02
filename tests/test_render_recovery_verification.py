"""Offline synthetic provenance tests; never contact Render, Kraken or Redis."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time
import unittest
from unittest.mock import patch

from scripts.nija_render_recovery_verification import (
    MANIFEST, OUTCOMES, RELEASE_BRANCH, SERVICE, SOURCE_PATHS, VerificationDenied,
    _command, run_verification, verify_baseline, verify_runtime,
)

PIN = "a" * 40
REF = "refs/heads/" + RELEASE_BRANCH


class RecoveryVerificationTests(unittest.TestCase):
    """Production verification requires all independent boundaries."""

    def setUp(self) -> None:
        self.approval = {
            "service_id": SERVICE, "release_branch": RELEASE_BRANCH,
            "operator_approved": True, "approval_reference": "synthetic-reviewed-receipt",
            "commit": PIN, "deployment_id": "dep-synthetic",
            "source_sha256": {path: hashlib.sha256(b"synthetic-source").hexdigest() for path in SOURCE_PATHS},
        }
        self.evidence = {
            "status": "DIAGNOSTIC_ONLY", "service_id": SERVICE, "failures": [],
            "deployment_status": "live", "release_branch_verified": True,
            "commit": PIN, "deployment_id": "dep-synthetic", "observed_at_epoch": time.time(),
        }
        self.runtime = {
            "status": "DIAGNOSTIC_ONLY", "service_id": SERVICE, "failures": [],
            "commit": PIN, "observed_at_epoch": time.time(), "processes": [{"started_at_epoch": time.time()}],
            "instance_id": "synthetic-instance", "broker_requests": False,
            "state_changed": False, "allow_new_orders": False,
            "source_sha256": self.approval["source_sha256"],
        }

    def test_correct_release_requires_exact_deployment_and_runtime(self) -> None:
        verify_baseline(self.approval, self.evidence, workflow_ref=REF)
        verify_runtime(self.approval, self.runtime)

    def test_main_dispatch_cannot_claim_release_inspection(self) -> None:
        for ref in ("refs/heads/main", "", "refs/tags/" + RELEASE_BRANCH):
            with self.subTest(ref=ref), self.assertRaisesRegex(
                VerificationDenied, "workflow_dispatch_not_production_release",
            ):
                verify_baseline(self.approval, self.evidence, workflow_ref=ref)

    def test_main_dispatch_never_uses_render_credentials(self) -> None:
        with patch.dict(os.environ, {"GITHUB_REF": "refs/heads/main"}, clear=True), patch(
            "scripts.nija_render_recovery_verification.inspect_render_api",
        ) as api, patch("scripts.nija_render_recovery_verification._runtime") as ssh:
            report = run_verification()
        api.assert_not_called()
        ssh.assert_not_called()
        self.assertFalse(report["DEPLOYMENT_BASELINE_VERIFIED"])
        self.assertIn("workflow_dispatch_not_production_release", report["failures"])

    def test_render_wrong_branch_or_missing_evidence_fails(self) -> None:
        for changes in (
            {"release_branch_verified": False}, {"service_id": "srv-wrong"},
            {"status": "BLOCKED"}, {"deployment_status": "build_in_progress"},
            {"failures": ["render_api_credential_unavailable"]},
            {"observed_at_epoch": time.time() - 61}, {"observed_at_epoch": True},
            {"observed_at_epoch": time.time() + 100},
        ):
            with self.subTest(changes=changes), self.assertRaises(VerificationDenied):
                verify_baseline(self.approval, {**self.evidence, **changes}, workflow_ref=REF)

    def test_stale_commit_or_deployment_id_fails(self) -> None:
        for changes in ({"commit": "b" * 40}, {"deployment_id": "dep-new"}):
            with self.subTest(changes=changes), self.assertRaisesRegex(
                VerificationDenied, "approved_render_deployment_mismatch",
            ):
                verify_baseline(self.approval, {**self.evidence, **changes}, workflow_ref=REF)

    def test_unapproved_or_incomplete_pin_cannot_be_promoted(self) -> None:
        for changes in (
            {"operator_approved": False}, {"operator_approved": "true"}, {"approval_reference": None},
            {"commit": None}, {"deployment_id": None}, {"source_sha256": {}},
        ):
            with self.subTest(changes=changes), self.assertRaises(VerificationDenied):
                verify_baseline({**self.approval, **changes}, self.evidence, workflow_ref=REF)

    def test_wrong_runtime_digest_fails(self) -> None:
        runtime = copy.deepcopy(self.runtime)
        runtime["source_sha256"][SOURCE_PATHS[0]] = "0" * 64
        with self.assertRaisesRegex(VerificationDenied, "runtime_source_digest_mismatch"):
            verify_runtime(self.approval, runtime)

    def test_stale_or_missing_runtime_evidence_fails(self) -> None:
        for changes in (
            {"observed_at_epoch": time.time() - 61}, {"processes": []}, {"instance_id": ""},
            {"failures": ["current_process_log_evidence_unavailable"]}, {"allow_new_orders": True},
        ):
            with self.subTest(changes=changes), self.assertRaises(VerificationDenied):
                verify_runtime(self.approval, {**self.runtime, **changes})

    def test_ssh_authentication_failure_never_exports_remote_stderr(self) -> None:
        with patch("subprocess.run", return_value=subprocess.CompletedProcess(
            [], 255, b"", b"private-canary Permission denied",
        )), self.assertRaisesRegex(VerificationDenied, "^ssh_runtime_inspection_failed$"):
            _command(["ssh"], "ssh_runtime_inspection_failed")

    def run_synthetic(self, *, runtime=None, command=None, evidence=None) -> dict:
        """Exercise orchestration with isolated synthetic authority boundaries."""
        with patch.dict(os.environ, {"GITHUB_REF": REF, "GITHUB_SHA": "c" * 40}, clear=True), patch(
            "scripts.nija_render_recovery_verification.MANIFEST",
        ) as manifest, patch(
            "scripts.nija_render_recovery_verification.inspect_render_api",
            return_value=self.evidence if evidence is None else evidence,
        ), patch(
            "scripts.nija_render_recovery_verification._runtime",
            return_value=self.runtime if runtime is None else runtime,
        ), patch(
            "scripts.nija_render_recovery_verification._command",
            side_effect=command or (lambda args, reason: b"synthetic-source"),
        ):
            manifest.read_bytes.return_value = json.dumps(self.approval).encode()
            return run_verification()

    def test_access_success_never_means_broker_or_collector_certification(self) -> None:
        report = self.run_synthetic()
        for outcome in OUTCOMES[:4]:
            self.assertTrue(report[outcome], report)
        self.assertFalse(report["BROKER_EVIDENCE_VERIFIED"])
        self.assertFalse(report["CERTIFICATION_COMPLETE"])
        self.assertFalse(report["allow_new_orders"])

    def test_incomplete_collector_cannot_be_inferred_from_logs(self) -> None:
        runtime = {
            **self.runtime, "collector_installed": True,
            "log_signals": {"AUTHENTICATED_CONNECTION_SUCCEEDED": 9},
        }
        report = self.run_synthetic(runtime=runtime)
        self.assertFalse(report["BROKER_EVIDENCE_VERIFIED"])
        self.assertFalse(report["CERTIFICATION_COMPLETE"])

    def test_reviewed_git_digest_mismatch_prevents_runtime_access(self) -> None:
        report = self.run_synthetic(command=lambda args, reason: b"changed-source")
        self.assertIn("reviewed_source_digest_mismatch", report["failures"])
        self.assertFalse(report["SOURCE_INTEGRITY_VERIFIED"])
        self.assertFalse(report["RUNTIME_ACCESS_VERIFIED"])

    def test_nonrelease_deployed_commit_fails_lineage_check(self) -> None:
        def command(args, reason):
            if args[1] == "merge-base":
                raise VerificationDenied(reason)
            return b"synthetic-source"
        report = self.run_synthetic(command=command)
        self.assertIn("deployment_not_on_release_lineage", report["failures"])
        self.assertFalse(report["DEPLOYMENT_BASELINE_VERIFIED"])

    def test_deployment_change_during_ssh_revokes_verification(self) -> None:
        with patch.dict(os.environ, {"GITHUB_REF": REF}, clear=True), patch(
            "scripts.nija_render_recovery_verification.MANIFEST",
        ) as manifest, patch(
            "scripts.nija_render_recovery_verification.inspect_render_api",
            side_effect=[self.evidence, {**self.evidence, "deployment_id": "dep-new"}],
        ), patch(
            "scripts.nija_render_recovery_verification._runtime", return_value=self.runtime,
        ), patch("scripts.nija_render_recovery_verification._command", return_value=b"synthetic-source"):
            manifest.read_bytes.return_value = json.dumps(self.approval).encode()
            report = run_verification()
        self.assertFalse(report["DEPLOYMENT_BASELINE_VERIFIED"])
        self.assertFalse(report["SOURCE_INTEGRITY_VERIFIED"])
        self.assertFalse(report["RUNTIME_ACCESS_VERIFIED"])

    def test_committed_manifest_has_reviewed_sources_and_explicit_approval(self) -> None:
        approval = json.loads(MANIFEST.read_bytes())
        self.assertIn(approval["operator_approved"], (True, False))
        if approval["operator_approved"] is False:
            self.assertIsNone(approval["commit"])
            self.assertIsNone(approval["deployment_id"])
        else:
            self.assertTrue(approval["approval_reference"])
            self.assertRegex(approval["commit"], r"^[0-9a-f]{40}$")
            self.assertRegex(approval["deployment_id"], r"^dep-[a-zA-Z0-9]+$")
        for path, digest in approval["source_sha256"].items():
            if approval["operator_approved"]:
                source = _command(["git", "show", approval["commit"] + ":" + path], "test_source_missing")
            else:
                source = Path(path).read_bytes()
            self.assertEqual(hashlib.sha256(source).hexdigest(), digest)

    def test_real_git_inspection_reads_exact_pinned_source_not_control_head(self) -> None:
        approval = json.loads(MANIFEST.read_bytes())
        commit = _command(["git", "rev-parse", "HEAD"], "test_checkout_missing").decode().strip()
        approval.update({
            "operator_approved": True, "approval_reference": "synthetic-only",
            "commit": commit, "deployment_id": "dep-synthetic",
        })
        runtime = {**self.runtime, "commit": commit, "source_sha256": approval["source_sha256"]}
        with patch.dict(os.environ, {"GITHUB_REF": REF, "GITHUB_SHA": "c" * 40}, clear=True), patch(
            "scripts.nija_render_recovery_verification.MANIFEST",
        ) as manifest, patch(
            "scripts.nija_render_recovery_verification.inspect_render_api",
            return_value={**self.evidence, "commit": commit},
        ), patch("scripts.nija_render_recovery_verification._runtime", return_value=runtime):
            manifest.read_bytes.return_value = json.dumps(approval).encode()
            report = run_verification()
        self.assertEqual(report["inspected_source_commit"], commit)
        self.assertNotEqual(report["inspected_source_commit"], report["workflow_source_commit"])
        self.assertTrue(report["SOURCE_INTEGRITY_VERIFIED"], report)

    def test_workflows_have_fixed_release_checkout_and_baseline_dependencies(self) -> None:
        for path in ("kraken-recovery-gate-diagnostics.yml", "render-recovery-access.yml"):
            source = (Path(".github/workflows") / path).read_text()
            self.assertIn("uses: ./.github/workflows/render-production-baseline.yml", source)
            self.assertIn("needs: baseline", source)
            self.assertNotIn("--request-identity", source)
        source = Path(".github/workflows/render-production-baseline.yml").read_text()
        self.assertIn("ref: " + RELEASE_BRANCH, source)
        self.assertIn("if-no-files-found: error", source)
        source = Path(".github/workflows/kraken-recovery-gate-diagnostics.yml").read_text()
        self.assertIn("ref: ${{ needs.baseline.outputs.verification_source_commit }}", source)
