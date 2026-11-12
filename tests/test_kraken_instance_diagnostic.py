"""Synthetic log fixtures; never import trading runtime or use credentials."""
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
import time
import subprocess
import sys
import unittest
from unittest.mock import patch

from scripts.nija_kraken_instance_diagnostic import (
    SERVICE, RELEASE_BRANCH, IDENTITY_REQUEST, _read_regular, classify_log, identity_probe,
    inspect_instance, inspect_render_api, report_succeeded,
    _process_start_ticks, render_instance_label, render_instances_match,
)

BASELINE = "a" * 40


class InstanceDiagnosticTests(unittest.TestCase):
    """Current-process evidence must be bounded and non-sensitive."""

    def setUp(self) -> None:
        baseline = patch("scripts.nija_kraken_instance_diagnostic.BASELINE", BASELINE)
        baseline.start()
        self.addCleanup(baseline.stop)

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
                self.assertEqual(inspect_instance()["reason"], reason)
                scan.assert_not_called()

    def test_service_qualified_full_short_ids_and_conflicts(self) -> None:
        short = SERVICE + "-zsc58"
        full = SERVICE + "-7d458c8976-zsc58"
        for value in (short, full):
            self.assertEqual(render_instance_label(value), short)
            self.assertTrue(render_instances_match(value, short))
            self.assertTrue(render_instances_match(value, full))
        self.assertFalse(render_instances_match(full, SERVICE + "-different-zsc58"))
        for invalid in (None, "", "zsc58", "srv-other-zsc58", SERVICE + "-xyz98-extra6"):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                render_instance_label(invalid)
            self.assertFalse(render_instances_match(full, invalid))

    def test_stat_start_ticks_use_field_22_and_validate_pid(self) -> None:
        raw = "101 (python command ) with spaces) S " + "0 " * 18 + "12345 0"
        self.assertEqual(_process_start_ticks(raw, 101), 12345)
        for invalid in (raw.replace("101 ", "102 ", 1), raw.replace("12345", "0"), "101 (python) S"):
            with self.subTest(raw=invalid), self.assertRaises((ValueError, IndexError)):
                _process_start_ticks(invalid, 101)

    def _inspect_synthetic_process(self, *, clock=1700000200, process_environment=None,
                                   restart=False, boot_changed=False, extra_instance=None,
                                   inspector_instance=None) -> dict:
        """Inspect synthetic procfs without accessing production or broker clients."""
        instance = inspector_instance or SERVICE + "-7d458c8976-zsc58"
        environment = {
            "RENDER_SERVICE_ID": SERVICE, "RENDER_GIT_COMMIT": BASELINE,
            "RENDER_INSTANCE_ID": instance,
        }
        child = environment if process_environment is None else process_environment
        encoded = b"\0".join(key.encode() + b"=" + value.encode() for key, value in child.items())
        reads = {"stat": 0, "boot": 0}

        def read_text(path, *args, **kwargs):
            if str(path) == "/proc/sys/kernel/random/boot_id":
                reads["boot"] += 1
                return ("87654321" if boot_changed and reads["boot"] > 1 else "12345678") + (
                    "-1234-1234-1234-123456789abc\n"
                )
            if str(path) == "/proc/stat":
                return "cpu 0 0\nbtime 1700000000\n"
            if str(path) == "/proc/102/stat":
                return "102 (python command) S " + "0 " * 18 + "12345 0"
            if str(path) == "/proc/101/stat":
                reads["stat"] += 1
                ticks = 12346 if restart and reads["stat"] > 1 else 12345
                return "101 (python command) S " + "0 " * 18 + str(ticks) + " 0"
            raise AssertionError("unexpected synthetic read: " + str(path))

        def read_bytes(path):
            if path.name == "cmdline":
                return b"python\0/app/main.py\0"
            if path.name == "environ":
                if path.parent.name == "102":
                    return b"\0".join(
                        key.encode() + b"=" + value.encode()
                        for key, value in {**environment, "RENDER_INSTANCE_ID": extra_instance}.items()
                    )
                return encoded
            raise AssertionError("unexpected synthetic read: " + str(path))

        def regular(path, limit, **kwargs):
            if str(path).endswith(("nija.log", "nija.log.1")):
                raise FileNotFoundError()
            return b"synthetic-source"

        with patch.dict(os.environ, environment, clear=True), patch.object(
            Path, "iterdir", return_value=iter(
                [Path("/proc/101"), Path("/proc/102")] if extra_instance else [Path("/proc/101")]
            ),
        ), patch.object(Path, "read_text", read_text), patch.object(
            Path, "read_bytes", read_bytes,
        ), patch("os.getpid", return_value=999), patch("os.sysconf", return_value=100), patch(
            "time.time", return_value=clock,
        ), patch("scripts.nija_kraken_instance_diagnostic._read_regular", side_effect=regular):
            return inspect_instance()

    def test_inspector_reports_stable_boot_and_raw_ticks_without_uptime_drift(self) -> None:
        before = self._inspect_synthetic_process()
        after = self._inspect_synthetic_process(clock=1700000210)
        self.assertEqual(before["boot_id"], "12345678-1234-1234-1234-123456789abc")
        self.assertEqual(before["boot_id"], after["boot_id"])
        self.assertEqual(before["processes"], after["processes"])
        self.assertEqual(before["processes"][0]["pid"], 101)
        self.assertEqual(before["processes"][0]["start_ticks"], 12345)
        self.assertEqual(before["processes"][0]["started_at_epoch"], 1700000123.45)

    def test_inspector_rejects_conflicting_process_service_commit_or_instance(self) -> None:
        environment = {
            "RENDER_SERVICE_ID": SERVICE, "RENDER_GIT_COMMIT": BASELINE,
            "RENDER_INSTANCE_ID": SERVICE + "-7d458c8976-zsc58",
        }
        for field, value in (
            ("RENDER_SERVICE_ID", "srv-other"), ("RENDER_GIT_COMMIT", "b" * 40),
            ("RENDER_INSTANCE_ID", SERVICE + "-different-zsc58"),
            ("RENDER_INSTANCE_ID", ""),
        ):
            with self.subTest(field=field, value=value):
                report = self._inspect_synthetic_process(process_environment={**environment, field: value})
                self.assertIn("runtime_process_identity_conflict", report["failures"])
                self.assertEqual(report["processes"], [])
                self.assertFalse(report["allow_new_orders"])

    def test_inspector_rejects_pid_reuse_and_boot_change_during_scan(self) -> None:
        restart = self._inspect_synthetic_process(restart=True)
        self.assertIn("runtime_process_identity_conflict", restart["failures"])
        self.assertEqual(restart["processes"], [])
        changed = self._inspect_synthetic_process(boot_changed=True)
        self.assertIn("runtime_boot_identity_changed", changed["failures"])

    def test_short_inspector_rejects_multiple_conflicting_full_process_ids(self) -> None:
        environment = {
            "RENDER_SERVICE_ID": SERVICE, "RENDER_GIT_COMMIT": BASELINE,
            "RENDER_INSTANCE_ID": SERVICE + "-7d458c8976-zsc58",
        }
        report = self._inspect_synthetic_process(
            process_environment=environment, extra_instance=SERVICE + "-different-zsc58",
            inspector_instance=SERVICE + "-zsc58",
        )
        self.assertIn("runtime_process_identity_conflict", report["failures"])
        self.assertEqual(len(report["processes"]), 1)
        self.assertFalse(report_succeeded(report))

    def test_api_missing_authorization_never_requests(self) -> None:
        for environment, reason in (({}, "render_api_credential_unavailable"),):
            with patch.dict("os.environ", environment, clear=True), patch(
                "scripts.nija_kraken_instance_diagnostic.urlopen"
            ) as request:
                report = inspect_render_api()
                self.assertEqual(report["failures"], [reason])
                self.assertFalse(report["allow_new_orders"])
                request.assert_not_called()

    def test_missing_approved_baseline_cannot_accept_an_empty_runtime_commit(self) -> None:
        with patch("scripts.nija_kraken_instance_diagnostic.BASELINE", ""), patch.dict(
            os.environ, {"RENDER_SERVICE_ID": SERVICE, "RENDER_GIT_COMMIT": ""}, clear=True,
        ):
            self.assertEqual(inspect_instance()["reason"], "baseline_commit_mismatch")
            self.assertEqual(identity_probe()["reason"], "baseline_instance_unverified")

    def test_blocked_or_incomplete_reports_are_not_success(self) -> None:
        for report in (
            {"status": "BLOCKED"}, {"status": "DIAGNOSTIC_ONLY", "failures": ["missing"]},
            {"status": "PENDING"}, {"status": "IDENTITY_RECEIPT", "fresh": False},
            {"status": "DIAGNOSTIC_ONLY"},
        ):
            self.assertFalse(report_succeeded(report))

    def test_blocked_cli_exits_unsuccessfully(self) -> None:
        result = subprocess.run(
            [sys.executable, "-B", "-S", "scripts/nija_kraken_instance_diagnostic.py"],
            env={"NIJA_DEFER_RUNTIME_SITE_HOOKS": "1"}, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)["status"], "BLOCKED")

    def test_consumed_identity_request_id_survives_baseline_update(self) -> None:
        self.assertEqual(IDENTITY_REQUEST, "85c2521edd9754d6f6f7df677f8d6231")

    def test_recovery_workflows_pin_the_checked_out_history_source(self) -> None:
        repository = Path(__file__).resolve().parents[1]
        source = repository / "bot/kraken_live_history_recovery.py"
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        for path in (
            ".github/workflows/render-recovery-access.yml",
            ".github/workflows/kraken-recovery-gate-diagnostics.yml",
        ):
            with self.subTest(workflow=path):
                self.assertIn(digest, (repository / path).read_text())

    def test_api_logs_must_match_the_current_instance(self) -> None:
        for observed_instance, accepted in (
            ("wrong-instance", False), ("zsc58", False), (SERVICE + "-zsc58", True),
            (SERVICE + "-7d458c8976-zsc58", True), ("58", False),
        ):
            with self.subTest(instance=observed_instance):
                responses = [
                    {"id": SERVICE, "ownerId": "tea-synthetic", "branch": RELEASE_BRANCH},
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
                }] * 9
                with patch.dict("os.environ", {
                    "RENDER_API_KEY": "synthetic-only",  # pragma: allowlist secret (offline mocked HTTP fixture)
                    "EXPECTED_RENDER_INSTANCE": SERVICE + "-7d458c8976-zsc58",
                    "NIJA_APPROVED_RENDER_DEPLOYMENT_ID": "dep-synthetic",
                }, clear=True), patch(
                    "scripts.nija_kraken_instance_diagnostic.urlopen",
                    side_effect=[io.BytesIO(json.dumps(row).encode()) for row in responses],
                ):
                    report = inspect_render_api()
                self.assertEqual("INVALID_SIGNATURE" in report["log_signals"], accepted)
                self.assertNotIn("private-canary", json.dumps(report))
                self.assertNotIn("synthetic-only", json.dumps(report))
                self.assertFalse(report["allow_new_orders"])

    def test_api_logs_reject_conflicting_full_ids_across_queries(self) -> None:
        for expected_instance in (
            SERVICE + "-zsc58", SERVICE + "-7d458c8976-zsc58",
        ):
            with self.subTest(expected_instance=expected_instance):
                responses = [
                    {"id": SERVICE, "ownerId": "tea-synthetic", "branch": RELEASE_BRANCH},
                    [{"deploy": {
                        "id": "dep-synthetic", "status": "live",
                        "commit": {"id": BASELINE}, "createdAt": "2026-11-02T00:00:00Z",
                    }}],
                    {"logs": [
                        {
                            "timestamp": "2026-11-02T00:00:01Z",
                            "message": "KRAKEN_INITIALIZATION",
                            "labels": [{
                                "name": "instance", "value": SERVICE + "-7d458c8976-zsc58",
                            }],
                        },
                        {
                            "timestamp": "2026-11-02T00:00:02Z",
                            "message": "KRAKEN_INITIALIZATION",
                            "labels": [{
                                "name": "instance", "value": SERVICE + "-different-zsc58",
                            }],
                        },
                        {
                            "timestamp": "2026-11-02T00:00:03Z",
                            "message": "KRAKEN_INITIALIZATION",
                            "labels": [{"name": "instance", "value": SERVICE + "-zsc58"}],
                        },
                    ]},
                ] + [{"logs": []}] * 8
                with patch.dict(os.environ, {
                    "RENDER_API_KEY": "synthetic-only",  # pragma: allowlist secret (offline mocked HTTP fixture)
                    "EXPECTED_RENDER_INSTANCE": expected_instance,
                    "NIJA_APPROVED_RENDER_DEPLOYMENT_ID": "dep-synthetic",
                }, clear=True), patch(
                    "scripts.nija_kraken_instance_diagnostic.urlopen",
                    side_effect=[io.BytesIO(json.dumps(row).encode()) for row in responses],
                ):
                    report = inspect_render_api()
                self.assertEqual(report["status"], "BLOCKED")
                self.assertEqual(report["log_signals"], {})
                self.assertIn("render_api_response_unverified", report["failures"])

    def test_deployment_discovery_does_not_require_instance_or_approved_pin(self) -> None:
        responses = [
            {"id": SERVICE, "branch": RELEASE_BRANCH},
            [{"deploy": {"id": "dep-current", "status": "live", "commit": {"id": "b" * 40}}}],
        ]
        with patch.dict(os.environ, {"RENDER_API_KEY": "synthetic-only"}, clear=True), patch(  # pragma: allowlist secret (offline mocked HTTP fixture)
            "scripts.nija_kraken_instance_diagnostic.urlopen",
            side_effect=[io.BytesIO(json.dumps(row).encode()) for row in responses],
        ) as request:
            report = inspect_render_api(deployment_only=True)
        self.assertEqual(request.call_count, 2)
        self.assertEqual(report["commit"], "b" * 40)
        self.assertEqual(report["deployment_id"], "dep-current")
        self.assertTrue(report["release_branch_verified"])
        self.assertFalse(report["allow_new_orders"])


class IdentityProbeTests(unittest.TestCase):
    """Only the existing broker may consume one immutable diagnostic request."""

    def setUp(self) -> None:
        baseline = patch("scripts.nija_kraken_instance_diagnostic.BASELINE", BASELINE)
        baseline.start()
        self.addCleanup(baseline.stop)
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()
        self.environment = patch.dict(os.environ, {
            "RENDER_SERVICE_ID": SERVICE, "RENDER_GIT_COMMIT": BASELINE,
            "NIJA_KRAKEN_HISTORY_RECOVERY_DIR": str(self.root),
        }, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        # Request-publisher behavior uses explicitly approved synthetic source
        # bytes, independently of changes to the real production consumers.
        # Never refresh production approval digests merely to make tests pass.
        from scripts.nija_kraken_instance_diagnostic import IDENTITY_CONSUMER_PINS
        app_root = self.root / "synthetic-app"
        fixture_pins = []
        for relative, _ in IDENTITY_CONSUMER_PINS:
            source = app_root / relative
            source.parent.mkdir(parents=True, exist_ok=True)
            raw = ("synthetic-reviewed-source:" + relative).encode()
            source.write_bytes(raw)
            fixture_pins.append((relative, hashlib.sha256(raw).hexdigest()))
        for name, value in (
            ("RECOVERY_ROOT", self.root), ("APP_ROOT", app_root),
            ("IDENTITY_CONSUMER_PINS", tuple(fixture_pins)),
        ):
            change = patch("scripts.nija_kraken_instance_diagnostic." + name, value)
            change.start()
            self.addCleanup(change.stop)
        self.write("collector.lock", b"")
        self.write("approved-binding-platform-20261028.json", b"{}")

    def write(self, name: str, raw: bytes) -> Path:
        """Create a private synthetic recovery file."""
        path = self.root / name
        path.write_bytes(raw)
        path.chmod(0o600)
        return path

    def receipt(self, **overrides) -> None:
        """Write a synthetic receipt containing no account material."""
        row = {
            "request_id": IDENTITY_REQUEST, "account_scope": "platform:kraken",
            "trading_authorized": False, "diagnostic_only": True, "collector_installed": False,
            "independent_certification_complete": False,
            "collection_succeeded": True, "configured_account_and_key_match": True,
            "observation": {
                "verified": True, "read_only": True, "scope_verified": True,
                "observed_at_epoch": time.time(), "account": "platform:kraken",
                "source": "authenticated_broker",
                "provider_id": "kraken-account-identity-v480-private-recovery-v491",
            },
            "private_canary": "never-export-account-data",
        }
        row.update(overrides)
        self.write(IDENTITY_REQUEST + ".identity.evidence.json", json.dumps(row).encode())

    def test_identity_probe_rejects_unreviewed_consumer_source(self) -> None:
        from scripts import nija_kraken_instance_diagnostic as diagnostic

        original = diagnostic._read_regular

        def replace_one_source(path, limit):
            if path.name == "kraken_identity_request_recovery_v491.py":
                return b"synthetic-unreviewed-code"
            return original(path, limit)

        with patch.object(diagnostic, "_read_regular", side_effect=replace_one_source):
            report = identity_probe(publish=True)

        self.assertFalse(report["request_created"])
        self.assertFalse(report["allow_new_orders"])
        self.assertEqual(report["reason"], "identity_consumer_source_changed")
        self.assertFalse((self.root / "identity_request.json").exists())

    def test_publishes_once_without_overwriting_other_modes_or_bindings(self) -> None:
        before = (self.root / "approved-binding-platform-20261028.json").read_bytes()
        report = identity_probe(publish=True)
        self.assertTrue(report["request_created"])
        request = json.loads((self.root / "identity_request.json").read_bytes())
        self.assertEqual(set(request), {"request_id", "account_scope", "created_at", "max_pages"})
        self.assertEqual(request["request_id"], IDENTITY_REQUEST)
        self.assertEqual(request["account_scope"], "platform:kraken")
        self.assertEqual(request["max_pages"], 1)
        self.assertEqual(
            (self.root / "approved-binding-platform-20261028.json").read_bytes(), before,
        )
        self.assertEqual(identity_probe(publish=True)["reason"], "existing_recovery_request_preserved")
        self.assertFalse(identity_probe()["allow_new_orders"])

    def test_existing_request_or_claim_is_never_replaced_or_replayed(self) -> None:
        for name in ("request.json", "exact_request.json", "identity_request.json",
                     IDENTITY_REQUEST + ".identity.claimed.json"):
            with self.subTest(name=name):
                path = self.write(name, b"preserve-original")
                report = identity_probe(publish=True)
                self.assertFalse(report["request_created"])
                self.assertEqual(path.read_bytes(), b"preserve-original")
                path.unlink()

    def test_only_fresh_matching_diagnostic_receipt_counts_as_comparison(self) -> None:
        self.receipt()
        report = identity_probe()
        self.assertTrue(report["configured_account_key_match"])
        self.assertFalse(report["independent_certification_complete"])
        self.assertFalse(report["allow_new_orders"])
        self.assertNotIn("never-export-account-data", json.dumps(report))
        for observation in (
            {}, {"observed_at_epoch": time.time() - 61},
            {"observed_at_epoch": time.time() + 10},
            {"observed_at_epoch": True},
        ):
            self.receipt(observation=observation)
            self.assertFalse(identity_probe()["configured_account_key_match"])

    def test_unsafe_receipt_scope_and_source_fail_closed(self) -> None:
        self.receipt(trading_authorized=True)
        self.assertEqual(identity_probe()["reason"], "identity_receipt_invalid")
        self.receipt()
        path = self.root / (IDENTITY_REQUEST + ".identity.evidence.json")
        path.chmod(0o644)
        self.assertEqual(identity_probe()["reason"], "private_identity_receipt_required")
        path.unlink()
        path.symlink_to(self.root / "collector.lock")
        self.assertEqual(identity_probe()["reason"], "private_identity_receipt_required")

    def test_missing_binding_or_wrong_environment_never_publishes(self) -> None:
        (self.root / "approved-binding-platform-20261028.json").unlink()
        self.assertEqual(identity_probe(publish=True)["reason"], "required_identity_recovery_file_missing")
        self.assertFalse((self.root / "identity_request.json").exists())
        with patch.dict(os.environ, {"RENDER_GIT_COMMIT": "wrong"}):
            self.assertEqual(identity_probe(publish=True)["reason"], "baseline_instance_unverified")
        with patch.dict(os.environ, {"NIJA_KRAKEN_HISTORY_RECOVERY_DIR": "/wrong"}):
            self.assertEqual(identity_probe(publish=True)["reason"], "identity_request_consumer_directory_unverified")

    def test_failure_messages_are_fixed_and_never_export_provider_text(self) -> None:
        self.receipt(collection_succeeded=False, failure_code="approved_api_key_identity_mismatch")
        self.assertEqual(identity_probe()["reason"], "approved_api_key_identity_mismatch")
        self.receipt(collection_succeeded=False, failure_code="private-credential-canary")
        self.assertEqual(identity_probe()["reason"], "identity_comparison_unverified")
