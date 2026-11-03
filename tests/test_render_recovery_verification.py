"""Offline synthetic provenance tests; never contact Render, Kraken or Redis."""
import copy
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import time
import unittest
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

from scripts.nija_render_recovery_verification import (
    MANIFEST, OUTCOMES, RELEASE_BRANCH, SERVICE, SOURCE_PATHS, VerificationDenied,
    _command, _read_ssh_report, _read_render_instance_logs,
    _verify_render_instance_app_logs, load_reviewed_approval, run_verification,
    verify_baseline, verify_runtime,
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

    def test_remote_inspector_exit_two_reports_runtime_blocker_not_ssh_failure(self) -> None:
        remote = {**self.runtime, "failures": ["canonical_runtime_process_not_found"]}
        with patch("subprocess.run", return_value=subprocess.CompletedProcess(
            ["ssh"], 2, json.dumps(remote).encode(), b"private-stderr-canary",
        )):
            report = _read_ssh_report(["ssh"], data=b"synthetic-only")
        self.assertEqual(report["failures"], ["canonical_runtime_process_not_found"])
        with self.assertRaisesRegex(VerificationDenied, "^runtime_evidence_incomplete$"):
            verify_runtime(self.approval, report)
        outcome = self.run_synthetic(runtime=report)
        self.assertIn("runtime_evidence_incomplete", outcome["failures"])
        self.assertEqual(
            outcome["ssh_runtime_evidence_failures"],
            ["canonical_runtime_process_not_found"],
        )
        self.assertTrue(outcome["ssh_runtime_report_received"])
        self.assertFalse(outcome["DEPLOYMENT_BASELINE_VERIFIED"])
        self.assertFalse(outcome["CERTIFICATION_COMPLETE"])
        self.assertFalse(outcome["allow_new_orders"])

    def test_ssh_transport_denial_does_not_disclose_stderr(self) -> None:
        with patch("subprocess.run", return_value=subprocess.CompletedProcess(
            ["ssh"], 255, b"", b"private-secret-canary Permission denied (publickey)",
        )), self.assertRaisesRegex(
            VerificationDenied, "^ssh_transport_or_authorization_failed$",
        ) as ctx:
            _read_ssh_report(["ssh"], data=b"synthetic-only")
        self.assertNotIn("private-secret-canary", str(ctx.exception))

    def test_remote_ssh_report_invalid_or_exit_inconsistent_fails_closed(self) -> None:
        cases = (
            (2, b"not-json", "ssh_remote_report_invalid"),
            (0, b"[]", "ssh_remote_report_invalid"),
            (0, json.dumps({**self.runtime, "failures": ["runtime_source_read_failed"]}).encode(),
             "ssh_remote_report_exit_mismatch"),
            (2, json.dumps(self.runtime).encode(), "ssh_remote_report_exit_mismatch"),
            (1, json.dumps(self.runtime).encode(), "ssh_remote_command_failed"),
        )
        for rc, stdout, reason in cases:
            with self.subTest(code=rc, reason=reason), patch(
                "subprocess.run", return_value=subprocess.CompletedProcess(
                    ["ssh"], rc, stdout, b"private-canary",
                ),
            ), self.assertRaisesRegex(VerificationDenied, "^" + reason + "$"):
                _read_ssh_report(["ssh"], data=b"synthetic-only")

    def test_remote_failure_reasons_never_publish_unreviewed_content(self) -> None:
        remote = {**self.runtime, "failures": [
            "current_process_log_evidence_unavailable", "private_account_or_token_canary",
        ]}
        outcome = self.run_synthetic(runtime=remote)
        self.assertEqual(
            outcome["ssh_runtime_evidence_failures"],
            ["current_process_log_evidence_unavailable"],
        )
        self.assertNotIn("private_account_or_token_canary", json.dumps(outcome))
        self.assertFalse(outcome["CERTIFICATION_COMPLETE"])

    def _synthetic_app_rows(self, observed: float, instance: str) -> list[dict]:
        return [{
            "timestamp": datetime.fromtimestamp(observed - seconds, timezone.utc).isoformat(),
            "labels": [
                {"name": "resource", "value": SERVICE},
                {"name": "instance", "value": instance},
                {"name": "type", "value": "app"},
                {"name": "level", "value": "info"},
            ],
            "message": (
                "2026-11-03 15:35:00,000 | INFO | "
                "nija.runtime_heartbeat_marker_convergence_v238 | "
                "STARTUP_READONLY_RECOVERY_DIAGNOSTIC state=READ_ONLY_RECOVERY "
                "independent_attestations=unverified "
                "allow_new_orders=false canonical_gate_unchanged=true"
            ),
        } for seconds in (12, 6)]

    def _remote_missing_local_logs(self) -> dict:
        now = time.time()
        return {
            **self.runtime,
            "observed_at_epoch": now,
            "instance_id": SERVICE + "-synthetic",
            "processes": [{"started_at_epoch": now - 120, "configured": {}}],
            "failures": ["current_process_log_evidence_unavailable"],
            "log_signals": {},
        }

    def test_external_render_app_logs_correlate_exact_runtime_without_trading(self) -> None:
        remote = self._remote_missing_local_logs()
        logs = self._synthetic_app_rows(remote["observed_at_epoch"], remote["instance_id"])
        with patch(
            "scripts.nija_render_recovery_verification._read_render_instance_logs",
            return_value=logs,
        ) as source:
            self.assertTrue(_verify_render_instance_app_logs(self.approval, remote))
        source.assert_called_once()
        _, start, end = source.call_args.args
        self.assertEqual(source.call_args.args[0], remote["instance_id"])
        self.assertGreaterEqual(start, remote["processes"][0]["started_at_epoch"])
        self.assertLessEqual(end, time.time())
        with self.assertRaisesRegex(VerificationDenied, "^runtime_evidence_incomplete$"):
            verify_runtime(self.approval, remote)
        verify_runtime(self.approval, remote, render_instance_app_logs_verified=True)
        with patch(
            "scripts.nija_render_recovery_verification._verify_render_instance_app_logs",
            return_value=True,
        ):
            result = self.run_synthetic(runtime=remote)
        self.assertTrue(result["render_instance_app_log_evidence_verified"])
        self.assertTrue(result["RUNTIME_ACCESS_VERIFIED"])
        self.assertTrue(result["SOURCE_INTEGRITY_VERIFIED"])
        self.assertFalse(result["BROKER_EVIDENCE_VERIFIED"])
        self.assertFalse(result["CERTIFICATION_COMPLETE"])
        self.assertFalse(result["allow_new_orders"])

    def test_instance_log_fallback_denies_stale_or_cross_instance(self) -> None:
        base = self._remote_missing_local_logs()
        good = self._synthetic_app_rows(base["observed_at_epoch"], base["instance_id"])
        for label, rows in (
            ("cross_instance", [{**good[0], "labels": [
                {"name": "resource", "value": SERVICE},
                {"name": "instance", "value": SERVICE + "-wrong"},
                {"name": "type", "value": "app"},
            ]}, good[1]]),
            ("one_only", good[:1]),
            ("stale", [{**x, "timestamp": "2025-01-01T00:00:00Z"} for x in good]),
            ("wrong_module", [{**x, "message": x["message"].replace(
                "nija.runtime_heartbeat_marker_convergence_v238", "nija.some_other_logger",
            )} for x in good]),
            ("unsafe_marker", [{**x, "message": x["message"].replace(
                "allow_new_orders=false", "allow_new_orders=true",
            )} for x in good]),
            ("request_type", [{**x, "labels": [
                {"name": "resource", "value": SERVICE},
                {"name": "instance", "value": base["instance_id"]},
                {"name": "type", "value": "request"},
            ]} for x in good]),
        ):
            with self.subTest(label=label), patch(
                "scripts.nija_render_recovery_verification._read_render_instance_logs",
                return_value=rows,
            ), self.assertRaises(VerificationDenied):
                _verify_render_instance_app_logs(self.approval, base)

    def test_instance_log_fallback_cannot_mask_other_missing_proofs(self) -> None:
        remote = self._remote_missing_local_logs()
        for change in (
            {"failures": ["canonical_runtime_process_not_found"]},
            {"failures": ["current_process_log_evidence_unavailable", "runtime_source_read_failed"]},
            {"allow_new_orders": True},
            {"broker_requests": True},
            {"source_sha256": {}},
            {"commit": "b" * 40},
            {"instance_id": "srv-unrelated-instance"},
            {"observed_at_epoch": time.time() - 120},
            {"processes": []},
        ):
            with self.subTest(changes=list(change)), patch(
                "scripts.nija_render_recovery_verification._read_render_instance_logs",
            ) as api, self.assertRaises(VerificationDenied):
                _verify_render_instance_app_logs(self.approval, {**remote, **change})
            api.assert_not_called()
        for failures in (
            ["runtime_source_read_failed"],
            ["current_process_log_evidence_unavailable", "runtime_process_inspection_failed"],
        ):
            with self.assertRaisesRegex(VerificationDenied, "^runtime_evidence_incomplete$"):
                verify_runtime(
                    self.approval, {**remote, "failures": failures},
                    render_instance_app_logs_verified=True,
                )

    def test_instance_log_api_reads_only_bounded_fixed_scope(self) -> None:
        import unittest.mock
        fake = unittest.mock.MagicMock()
        fake.__enter__.return_value = io.BytesIO(b'{"logs":[]}')
        with patch.dict(os.environ, {"RENDER_API_KEY": "synthetic-api-key"}), patch(
            "scripts.nija_render_recovery_verification.urlopen", return_value=fake,
        ) as opener:
            self.assertEqual(
                _read_render_instance_logs(SERVICE + "-synthetic", 1700000000, 1700000060),
                [],
            )
        request = opener.call_args.args[0]
        q = parse_qs(urlsplit(request.full_url).query)
        self.assertEqual(urlsplit(request.full_url).netloc, "api.render.com")
        self.assertEqual(q["resource"], [SERVICE])
        self.assertEqual(q["ownerId"], ["tea-d37fhe8gjchc73c8eo0g"])
        self.assertEqual(q["instance"], [SERVICE + "-synthetic"])
        self.assertEqual(q["type"], ["app"])
        self.assertEqual(q["limit"], ["100"])
        self.assertEqual(q["direction"], ["backward"])
        self.assertNotIn("synthetic-api-key", request.full_url)

    def run_synthetic(self, *, runtime=None, command=None, evidence=None) -> dict:
        """Exercise orchestration with an independently reviewed synthetic approval."""
        with patch.dict(os.environ, {"GITHUB_REF": REF, "GITHUB_SHA": "c" * 40}, clear=True), patch(
            "scripts.nija_render_recovery_verification.load_reviewed_approval",
            return_value=self.approval,
        ), patch(
            "scripts.nija_render_recovery_verification.inspect_render_api",
            return_value=self.evidence if evidence is None else evidence,
        ), patch(
            "scripts.nija_render_recovery_verification._runtime",
            return_value=self.runtime if runtime is None else runtime,
        ), patch(
            "scripts.nija_render_recovery_verification._command",
            side_effect=command or (lambda args, reason: b"synthetic-source"),
        ):
            return run_verification()

    def test_access_success_never_means_broker_or_collector_certification(self) -> None:
        report = self.run_synthetic()
        for outcome in OUTCOMES[:4]:
            self.assertTrue(report[outcome], report)
        self.assertFalse(report["BROKER_EVIDENCE_VERIFIED"])
        self.assertFalse(report["CERTIFICATION_COMPLETE"])
        self.assertFalse(report["allow_new_orders"])

    def test_explicit_sole_owner_readonly_approval_never_certifies_orders(self) -> None:
        """A documented owner decision permits baseline reads, not execution."""
        self.approval = {
            **self.approval,
            "approval_reference": "owner-readonly-synthetic-audit-record",
        }
        report = self.run_synthetic()
        self.assertTrue(report["DEPLOYMENT_BASELINE_VERIFIED"], report)
        self.assertTrue(report["SOURCE_INTEGRITY_VERIFIED"], report)
        self.assertTrue(report["RUNTIME_ACCESS_VERIFIED"], report)
        self.assertFalse(report["BROKER_EVIDENCE_VERIFIED"])
        self.assertFalse(report["CERTIFICATION_COMPLETE"])
        self.assertFalse(report["allow_new_orders"])
        self.assertEqual(report["mode"], "READ_ONLY_RECOVERY")

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
            "scripts.nija_render_recovery_verification.load_reviewed_approval",
            return_value=self.approval,
        ), patch(
            "scripts.nija_render_recovery_verification.inspect_render_api",
            side_effect=[self.evidence, {**self.evidence, "deployment_id": "dep-new"}],
        ), patch(
            "scripts.nija_render_recovery_verification._runtime", return_value=self.runtime,
        ), patch("scripts.nija_render_recovery_verification._command", return_value=b"synthetic-source"):
            report = run_verification()
        self.assertFalse(report["DEPLOYMENT_BASELINE_VERIFIED"])
        self.assertFalse(report["SOURCE_INTEGRITY_VERIFIED"])
        self.assertFalse(report["RUNTIME_ACCESS_VERIFIED"])

    def test_committed_manifest_has_reviewed_sources_and_explicit_approval(self) -> None:
        approval = json.loads(MANIFEST.read_bytes())
        self.assertIs(approval["operator_approved"], False)
        self.assertIsNone(approval["approval_reference"])
        self.assertIsNone(approval["commit"])
        self.assertIsNone(approval["deployment_id"])
        for path, digest in approval["source_sha256"].items():
            self.assertEqual(hashlib.sha256(Path(path).read_bytes()).hexdigest(), digest)

    def test_real_git_inspection_reads_exact_pinned_source_not_control_head(self) -> None:
        approval = json.loads(MANIFEST.read_bytes())
        commit = _command(["git", "rev-parse", "HEAD"], "test_checkout_missing").decode().strip()
        approval.update({
            "operator_approved": True, "approval_reference": "synthetic-only",
            "commit": commit, "deployment_id": "dep-synthetic",
        })
        runtime = {**self.runtime, "commit": commit, "source_sha256": approval["source_sha256"]}
        with patch.dict(os.environ, {"GITHUB_REF": REF, "GITHUB_SHA": "c" * 40}, clear=True), patch(
            "scripts.nija_render_recovery_verification.load_reviewed_approval",
            return_value=approval,
        ), patch(
            "scripts.nija_render_recovery_verification.inspect_render_api",
            return_value={**self.evidence, "commit": commit},
        ), patch("scripts.nija_render_recovery_verification._runtime", return_value=runtime):
            report = run_verification()
        self.assertEqual(report["inspected_source_commit"], commit)
        self.assertNotEqual(report["inspected_source_commit"], report["workflow_source_commit"])
        self.assertTrue(report["SOURCE_INTEGRITY_VERIFIED"], report)

    def test_missing_external_approval_refuses_before_render_api_or_ssh(self) -> None:
        with patch.dict(os.environ, {"GITHUB_REF": REF}, clear=True), patch(
            "scripts.nija_render_recovery_verification.inspect_render_api",
        ) as api, patch(
            "scripts.nija_render_recovery_verification._runtime",
        ) as ssh:
            report = run_verification()
        self.assertFalse(report["DEPLOYMENT_BASELINE_VERIFIED"])
        self.assertIn("independent_environment_approval_missing", report["failures"])
        api.assert_not_called()
        ssh.assert_not_called()

    def test_invalid_external_approval_refuses_before_render_api_or_ssh(self) -> None:
        template = {
            **self.approval, "operator_approved": False,
            "approval_reference": None, "commit": None, "deployment_id": None,
        }
        invalid_approvals = (
            ({**self.approval, "operator_approved": False}, "deployment_operator_approval_missing"),
            ({**self.approval, "approval_reference": "  "}, "deployment_operator_approval_missing"),
            ({**self.approval, "commit": "not-a-commit"}, "approved_deployment_pin_missing"),
            ({**self.approval, "deployment_id": "not-a-deployment"}, "approved_deployment_pin_missing"),
            ({**self.approval, "source_sha256": {
                **self.approval["source_sha256"], SOURCE_PATHS[0]: "not-a-digest",
            }}, "independent_environment_approval_pins_mismatch"),
        )
        for approval, failure in invalid_approvals:
            with self.subTest(failure=failure), patch(
                "scripts.nija_render_recovery_verification.MANIFEST",
            ) as manifest, patch.dict(
                os.environ,
                {"GITHUB_REF": REF, "NIJA_RENDER_READONLY_APPROVAL_JSON": json.dumps(approval)},
                clear=True,
            ), patch(
                "scripts.nija_render_recovery_verification.inspect_render_api",
            ) as api, patch(
                "scripts.nija_render_recovery_verification._runtime",
            ) as ssh:
                manifest.read_bytes.return_value = json.dumps(template).encode()
                report = run_verification()
            self.assertIn(failure, report["failures"])
            api.assert_not_called()
            ssh.assert_not_called()

    def test_committed_manifest_cannot_approve_itself(self) -> None:
        with patch("scripts.nija_render_recovery_verification.MANIFEST") as manifest, patch.dict(
            os.environ, {"NIJA_RENDER_READONLY_APPROVAL_JSON": json.dumps(self.approval)}
        ):
            manifest.read_bytes.return_value = json.dumps(self.approval).encode()
            with self.assertRaisesRegex(
                VerificationDenied, "committed_manifest_must_remain_unapproved"
            ):
                load_reviewed_approval()

    def test_external_approval_matches_unapproved_template_only(self) -> None:
        template = {
            **self.approval, "operator_approved": False,
            "approval_reference": None, "commit": None, "deployment_id": None,
        }
        with patch("scripts.nija_render_recovery_verification.MANIFEST") as manifest, patch.dict(
            os.environ, {"NIJA_RENDER_READONLY_APPROVAL_JSON": json.dumps(self.approval)}
        ):
            manifest.read_bytes.return_value = json.dumps(template).encode()
            self.assertEqual(load_reviewed_approval(), self.approval)
            wrong = {**self.approval, "source_sha256": {
                **self.approval["source_sha256"], SOURCE_PATHS[0]: "0" * 64,
            }}
            with patch.dict(os.environ, {"NIJA_RENDER_READONLY_APPROVAL_JSON": json.dumps(wrong)}):
                with self.assertRaisesRegex(
                    VerificationDenied, "independent_environment_approval_pins_mismatch"
                ):
                    load_reviewed_approval()

    def test_malformed_or_duplicate_external_approval_rejected(self) -> None:
        template = {
            **self.approval, "operator_approved": False,
            "approval_reference": None, "commit": None, "deployment_id": None,
        }
        with patch("scripts.nija_render_recovery_verification.MANIFEST") as manifest:
            manifest.read_bytes.return_value = json.dumps(template).encode()
            for raw in (
                '{"operator_approved":true,"operator_approved":false}',
                '{"incomplete":',
                " " * 17000,
            ):
                with self.subTest(raw=raw[:20]), patch.dict(
                    os.environ, {"NIJA_RENDER_READONLY_APPROVAL_JSON": raw}
                ):
                    with self.assertRaises(VerificationDenied):
                        load_reviewed_approval()

    def test_unapproved_or_malformed_external_approval_refuses_before_remote_access(self) -> None:
        template = {
            **self.approval, "operator_approved": False,
            "approval_reference": None, "commit": None, "deployment_id": None,
        }
        cases = (
            ({"operator_approved": False}, "deployment_operator_approval_missing"),
            ({"approval_reference": "  "}, "deployment_operator_approval_missing"),
            ({"commit": "not-a-commit"}, "approved_deployment_pin_missing"),
            ({"deployment_id": "not-a-deployment"}, "approved_deployment_pin_missing"),
        )
        for changes, reason in cases:
            with self.subTest(changes=changes), patch(
                "scripts.nija_render_recovery_verification.MANIFEST"
            ) as manifest, patch.dict(
                os.environ,
                {
                    "GITHUB_REF": REF,
                    "NIJA_RENDER_READONLY_APPROVAL_JSON": json.dumps({**self.approval, **changes}),
                },
                clear=True,
            ), patch(
                "scripts.nija_render_recovery_verification._command", return_value=b"c" * 40,
            ), patch(
                "scripts.nija_render_recovery_verification.inspect_render_api",
            ) as api, patch(
                "scripts.nija_render_recovery_verification._runtime",
            ) as ssh:
                manifest.read_bytes.return_value = json.dumps(template).encode()
                report = run_verification()
            self.assertIn(reason, report["failures"])
            api.assert_not_called()
            ssh.assert_not_called()

    def test_required_approval_secret_is_forwarded_only_by_name(self) -> None:
        """GitHub requires explicit caller forwarding of environment secrets."""
        mapping = "NIJA_RENDER_READONLY_APPROVAL_JSON: ${{ secrets.NIJA_RENDER_READONLY_APPROVAL_JSON }}"
        for path in ("kraken-recovery-gate-diagnostics.yml", "render-recovery-access.yml"):
            with self.subTest(path=path):
                source = (Path(".github/workflows") / path).read_text()
                self.assertEqual(source.count(mapping), 1)
                self.assertNotIn("secrets: inherit", source)
        reusable = Path(".github/workflows/render-production-baseline.yml").read_text()
        self.assertIn("environment: nija-render-recovery-readonly", reusable)
        self.assertIn("NIJA_RENDER_READONLY_APPROVAL_JSON:\n        required: true", reusable)
        self.assertIn("secrets.NIJA_RENDER_READONLY_APPROVAL_JSON", reusable)

    def test_workflows_have_fixed_release_checkout_and_baseline_dependencies(self) -> None:
        for path in ("kraken-recovery-gate-diagnostics.yml", "render-recovery-access.yml"):
            source = (Path(".github/workflows") / path).read_text()
            self.assertIn("uses: ./.github/workflows/render-production-baseline.yml", source)
            self.assertIn("needs: baseline", source)
            self.assertNotIn("--request-identity", source)
            self.assertNotIn("secrets: inherit", source)
            self.assertIn("RENDER_API_KEY: ${{ secrets.RENDER_API_KEY }}", source)
            self.assertIn(
                "NIJA_RENDER_RECOVERY_SSH_PRIVATE_KEY: ${{ secrets.NIJA_RENDER_RECOVERY_SSH_PRIVATE_KEY }}",
                source,
            )
            self.assertIn(
                "NIJA_RENDER_READONLY_APPROVAL_JSON: ${{ secrets.NIJA_RENDER_READONLY_APPROVAL_JSON }}",
                source,
            )
        source = Path(".github/workflows/render-production-baseline.yml").read_text()
        self.assertIn("if: github.ref == 'refs/heads/" + RELEASE_BRANCH + "'", source)
        self.assertIn("ref: ${{ github.sha }}", source)
        self.assertIn("if-no-files-found: error", source)
        self.assertIn("environment: nija-render-recovery-readonly", source)
        self.assertIn("secrets.NIJA_RENDER_READONLY_APPROVAL_JSON", source)
        self.assertIn("RENDER_API_KEY:", source)
        self.assertIn("NIJA_RENDER_RECOVERY_SSH_PRIVATE_KEY:", source)
        self.assertIn("NIJA_RENDER_READONLY_APPROVAL_JSON:\n        required: true", source)
        source = Path(".github/workflows/kraken-recovery-gate-diagnostics.yml").read_text()
        self.assertIn("ref: ${{ needs.baseline.outputs.verification_source_commit }}", source)
