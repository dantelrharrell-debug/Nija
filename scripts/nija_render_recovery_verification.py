"""Read-only, fail-closed Render deployment/source verification for Actions.

The reviewed approval manifest is never rewritten by this program. Render API
metadata, Git source and SSH runtime evidence must independently agree.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from scripts.nija_kraken_instance_diagnostic import (
    RELEASE_BRANCH, SERVICE, SOURCE_PATHS, inspect_render_api, report_succeeded,
)

MANIFEST = Path("ops/recovery/render_readonly_baseline.json")
APPROVAL_SECRET_ENV = "NIJA_RENDER_READONLY_APPROVAL_JSON"
_MAX_APPROVAL_BYTES = 16384
HOST = "ssh.oregon.render.com"
HOST_FINGERPRINT = "SHA256:KkZPgnApmttFYSkdJsCi7B01sgZPMI6kY53MDbbanGM"
RENDER_LOG_OWNER = "tea-d37fhe8gjchc73c8eo0g"
RENDER_LOG_MODULE = "| nija.runtime_heartbeat_marker_convergence_v238 |"
RENDER_LOG_MARKER = "STARTUP_READONLY_RECOVERY_DIAGNOSTIC state=READ_ONLY_RECOVERY"
RENDER_LOG_SAFETY = (
    "independent_attestations=unverified", "allow_new_orders=false",
    "canonical_gate_unchanged=true",
)
RENDER_LOG_MAX_BYTES = 512 * 1024
OUTCOMES = (
    "WORKFLOW_EXECUTION_SUCCESS", "DEPLOYMENT_BASELINE_VERIFIED",
    "SOURCE_INTEGRITY_VERIFIED", "RUNTIME_ACCESS_VERIFIED",
    "BROKER_EVIDENCE_VERIFIED", "CERTIFICATION_COMPLETE",
)
# Only these fixed labels from the reviewed, read-only instance inspector may
# leave GitHub Actions. Never export raw remote stdout, stderr, accounts or keys.
SAFE_RUNTIME_EVIDENCE_FAILURES = frozenset({
    "runtime_process_inspection_failed", "process_inventory_unavailable",
    "runtime_log_read_failed", "current_process_log_evidence_unavailable",
    "canonical_runtime_process_not_found", "runtime_source_read_failed",
})


class VerificationDenied(ValueError):
    """A fixed technical reason safe to expose in diagnostic output."""


def _reject_duplicate_fields(pairs: list[tuple[str, object]]) -> dict:
    """Refuse ambiguous JSON, including nested duplicate approval fields."""
    out = {}
    for key, value in pairs:
        if key in out:
            raise VerificationDenied("approval_json_duplicate_field")
        out[key] = value
    return out


def _validate_approval_metadata(approval: dict) -> None:
    """Reject unapproved or malformed deployment pins before external access."""
    if (approval.get("service_id") != SERVICE
            or approval.get("release_branch") != RELEASE_BRANCH):
        raise VerificationDenied("approval_target_mismatch")
    if (approval.get("operator_approved") is not True
            or not isinstance(approval.get("approval_reference"), str)
            or not approval["approval_reference"].strip()):
        raise VerificationDenied("deployment_operator_approval_missing")
    commit, deployment = approval.get("commit"), approval.get("deployment_id")
    if (not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit)
            or not isinstance(deployment, str) or not re.fullmatch(r"dep-[a-zA-Z0-9]+", deployment)):
        raise VerificationDenied("approved_deployment_pin_missing")
    pins = approval.get("source_sha256")
    if (not isinstance(pins, dict) or set(pins) != set(SOURCE_PATHS)
            or any(not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value)
                   for value in pins.values())):
        raise VerificationDenied("reviewed_source_pins_incomplete")


def load_reviewed_approval() -> dict:
    """Use a separately protected GitHub environment secret, never a release push.

    The committed manifest remains a source-pin template with approval=false.
    Human review and secret administration are external to this program.
    Neither an issue comment nor the latest live Render SHA is an approval.
    """
    try:
        template = json.loads(
            MANIFEST.read_bytes(), object_pairs_hook=_reject_duplicate_fields,
        )
    except VerificationDenied:
        raise
    except (OSError, ValueError, TypeError):
        raise VerificationDenied("approval_template_invalid") from None
    if (not isinstance(template, dict)
            or template.get("operator_approved") is not False
            or template.get("approval_reference") is not None
            or template.get("commit") is not None
            or template.get("deployment_id") is not None
            or template.get("service_id") != SERVICE
            or template.get("release_branch") != RELEASE_BRANCH):
        raise VerificationDenied("committed_manifest_must_remain_unapproved")
    pins = template.get("source_sha256")
    if (not isinstance(pins, dict) or set(pins) != set(SOURCE_PATHS)
            or any(not isinstance(value, str) or re.fullmatch(r"[a-f0-9]{64}", value) is None
                   for value in pins.values())):
        raise VerificationDenied("approval_template_source_pins_invalid")

    raw = os.environ.get(APPROVAL_SECRET_ENV, "")
    if not raw or len(raw.encode("utf-8")) > _MAX_APPROVAL_BYTES:
        raise VerificationDenied("independent_environment_approval_missing")
    try:
        reviewed = json.loads(raw, object_pairs_hook=_reject_duplicate_fields)
    except VerificationDenied:
        raise
    except (ValueError, TypeError):
        raise VerificationDenied("independent_environment_approval_invalid") from None
    if (not isinstance(reviewed, dict) or set(reviewed) != set(template)
            or reviewed.get("service_id") != SERVICE
            or reviewed.get("release_branch") != RELEASE_BRANCH
            or reviewed.get("source_sha256") != pins):
        raise VerificationDenied("independent_environment_approval_pins_mismatch")
    _validate_approval_metadata(reviewed)
    if (reviewed.get("operator_approved") is not True
            or not isinstance(reviewed.get("approval_reference"), str)
            or not reviewed["approval_reference"].strip()):
        raise VerificationDenied("deployment_operator_approval_missing")
    commit, deployment = reviewed.get("commit"), reviewed.get("deployment_id")
    if (not isinstance(commit, str) or not re.fullmatch(r"[0-9a-f]{40}", commit)
            or not isinstance(deployment, str) or not re.fullmatch(r"dep-[a-zA-Z0-9]+", deployment)):
        raise VerificationDenied("approved_deployment_pin_missing")
    # verify_baseline still requires exact agreement with fresh Render evidence.
    return reviewed


def verify_baseline(approval: dict, evidence: dict, *, workflow_ref: str) -> None:
    """Require operator review AND independent, fresh Render deployment evidence."""
    if workflow_ref != "refs/heads/" + RELEASE_BRANCH:
        raise VerificationDenied("workflow_dispatch_not_production_release")
    _validate_approval_metadata(approval)
    stamp = evidence.get("observed_at_epoch")
    if (evidence.get("status") != "DIAGNOSTIC_ONLY" or evidence.get("failures") != []
            or evidence.get("service_id") != SERVICE
            or evidence.get("deployment_status") != "live"
            or evidence.get("release_branch_verified") is not True
            or type(stamp) not in (int, float) or not 0 <= time.time() - stamp <= 60):
        raise VerificationDenied("current_render_evidence_missing")
    if (evidence.get("commit") != approval["commit"]
            or evidence.get("deployment_id") != approval["deployment_id"]):
        raise VerificationDenied("approved_render_deployment_mismatch")


def verify_runtime(
    approval: dict, report: dict, *, render_instance_app_logs_verified: bool = False,
) -> None:
    """Require exact runtime evidence; only one known missing local-log gap is recoverable."""
    log_only_gap = (
        render_instance_app_logs_verified is True
        and report.get("failures") == ["current_process_log_evidence_unavailable"]
        and report.get("log_signals") == {}
        and report.get("status") == "DIAGNOSTIC_ONLY"
    )
    if (not (report_succeeded(report) or log_only_gap) or report.get("service_id") != SERVICE
            or report.get("commit") != approval["commit"]
            or not report.get("processes") or not report.get("instance_id")
            or report.get("state_changed") is not False
            or report.get("broker_requests") is not False
            or report.get("allow_new_orders") is not False):
        raise VerificationDenied("runtime_evidence_incomplete")
    stamp = report.get("observed_at_epoch")
    if type(stamp) not in (int, float) or not 0 <= time.time() - stamp <= 60:
        raise VerificationDenied("runtime_evidence_stale")
    if report.get("source_sha256") != approval["source_sha256"]:
        raise VerificationDenied("runtime_source_digest_mismatch")


def _utc_query_time(stamp: float) -> str:
    return datetime.fromtimestamp(stamp, timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _read_render_instance_logs(instance: str, start: float, end: float) -> list[dict]:
    """Read bounded Render app logs using the existing approval-scoped API key.

    Fixed endpoint, owner, service and instance filter. Never log response bodies.
    """
    token = os.environ.get("RENDER_API_KEY", "")
    if not token:
        raise VerificationDenied("render_instance_log_api_unavailable")
    query = urlencode({
        "ownerId": RENDER_LOG_OWNER, "resource": SERVICE, "instance": instance,
        "type": "app", "text": "STARTUP_READONLY_RECOVERY_DIAGNOSTIC",
        "startTime": _utc_query_time(start), "endTime": _utc_query_time(end),
        "direction": "backward", "limit": 100,
    })
    request = Request(
        "https://api.render.com/v1/logs?" + query,
        headers={"Authorization": "Bearer " + token, "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=15) as response:
            raw = response.read(RENDER_LOG_MAX_BYTES + 1)
        if len(raw) > RENDER_LOG_MAX_BYTES:
            raise VerificationDenied("render_instance_log_response_invalid")
        payload = json.loads(raw)
    except VerificationDenied:
        raise
    except (OSError, HTTPError, URLError, TimeoutError, ValueError, TypeError):
        raise VerificationDenied("render_instance_log_api_unavailable") from None
    if (not isinstance(payload, dict) or not isinstance(payload.get("logs"), list)
            or len(payload["logs"]) > 100):
        raise VerificationDenied("render_instance_log_response_invalid")
    return payload["logs"]


def _render_log_instance_matches(full: str, logged: str) -> bool:
    """Render app logs use the five-character instance slug after service ID.

    SSH may report that slug followed by an additional hyphen-delimited suffix.
    Never accept an arbitrary prefix or a different service.
    """
    prefix = SERVICE + "-"
    if not full.startswith(prefix) or not logged.startswith(prefix):
        return False
    suffix = full[len(prefix):]
    short = logged[len(prefix):]
    return bool(
        re.fullmatch(r"[a-z0-9]{5}", short)
        and re.fullmatch(r"[a-z0-9]{5}(?:-[a-zA-Z0-9]+)*", suffix)
        and (suffix == short or suffix.startswith(short + "-"))
    )


def _canonical_heartbeat(message: str) -> bool | None:
    """Return safe/unsafe for canonical diagnostics, None for unrelated logs."""
    if RENDER_LOG_MODULE not in message or "STARTUP_READONLY_RECOVERY_DIAGNOSTIC" not in message:
        return None
    # Fields must be standalone whitespace-delimited key=value tokens.
    tail = message.split("STARTUP_READONLY_RECOVERY_DIAGNOSTIC", 1)[1]
    fields = {}
    for token in tail.split():
        if "=" not in token:
            return False
        key, value = token.split("=", 1)
        if not re.fullmatch(r"[a-z_]+", key) or not value or key in fields:
            return False
        fields[key] = value
    expected = {
        "state": "READ_ONLY_RECOVERY",
        "independent_attestations": "unverified",
        "allow_new_orders": "false",
        "canonical_gate_unchanged": "true",
    }
    return all(fields.get(k) == v for k, v in expected.items())


def _verify_render_instance_app_logs(approval: dict, report: dict) -> bool:
    """Correlate authenticated Render app heartbeat to SSH instance/process times.

    Only supplements the missing local-file classification, never broker proof.
    """
    if (report.get("status") != "DIAGNOSTIC_ONLY"
            or report.get("service_id") != SERVICE
            or report.get("commit") != approval["commit"]
            or report.get("source_sha256") != approval["source_sha256"]
            or report.get("failures") != ["current_process_log_evidence_unavailable"]
            or report.get("log_signals") != {}
            or report.get("state_changed") is not False
            or report.get("broker_requests") is not False
            or report.get("allow_new_orders") is not False):
        raise VerificationDenied("render_instance_log_context_mismatch")
    instance = report.get("instance_id")
    if (not isinstance(instance, str)
            or not re.fullmatch(re.escape(SERVICE) + r"-[a-zA-Z0-9-]{1,64}", instance)):
        raise VerificationDenied("render_instance_log_context_mismatch")
    processes = report.get("processes")
    if not isinstance(processes, list) or not processes:
        raise VerificationDenied("render_instance_log_context_mismatch")
    observed = report.get("observed_at_epoch")
    now = time.time()
    if type(observed) not in (float, int) or not 0 <= now - observed <= 60:
        raise VerificationDenied("render_instance_log_context_mismatch")
    starts = []
    for process in processes:
        stamp = process.get("started_at_epoch") if isinstance(process, dict) else None
        if (type(stamp) not in (int, float) or not 0 < stamp <= observed
                or not isinstance(process.get("configured"), dict)):
            raise VerificationDenied("render_instance_log_context_mismatch")
        starts.append(stamp)
    start = max(observed - 75, max(starts))
    end = min(now, observed + 15)
    if end - start < 3:
        raise VerificationDenied("render_instance_log_window_insufficient")
    rows = _read_render_instance_logs(instance, start, end)
    heartbeats = set()
    for row in rows:
        if not isinstance(row, dict) or not isinstance(row.get("labels"), list):
            raise VerificationDenied("render_instance_log_response_invalid")
        labels = {}
        for label in row["labels"]:
            if (not isinstance(label, dict) or not isinstance(label.get("name"), str)
                    or not isinstance(label.get("value"), str)
                    or label["name"] in labels):
                raise VerificationDenied("render_instance_log_response_invalid")
            labels[label["name"]] = label["value"]
        if (labels.get("resource") != SERVICE or not _render_log_instance_matches(instance, labels.get("instance", ""))
                or labels.get("type") != "app"):
            raise VerificationDenied("render_instance_log_scope_mismatch")
        msg, timestamp = row.get("message"), row.get("timestamp")
        if (not isinstance(msg, str) or len(msg) > 8192
                or not isinstance(timestamp, str) or len(timestamp) > 60):
            raise VerificationDenied("render_instance_log_response_invalid")
        try:
            moment = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            if moment.tzinfo is None:
                raise ValueError("timezone required")
            observed_log_at = moment.timestamp()
        except (ValueError, TypeError, OverflowError):
            raise VerificationDenied("render_instance_log_response_invalid") from None
        if not start <= observed_log_at <= end:
            raise VerificationDenied("render_instance_log_time_mismatch")
        verdict = _canonical_heartbeat(msg)
        if verdict is False:
            raise VerificationDenied("render_instance_log_safety_conflict")
        if verdict is True:
            heartbeats.add(observed_log_at)
    if len(heartbeats) < 2 or max(heartbeats) - min(heartbeats) < 3:
        raise VerificationDenied("render_current_instance_heartbeat_unverified")
    return True


def _command(args: list[str], reason: str, *, data: bytes | None = None) -> bytes:
    try:
        result = subprocess.run(
            args, input=data, capture_output=True, timeout=90, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise VerificationDenied(reason) from None
    if result.returncode or len(result.stdout) > 1024 * 1024:
        raise VerificationDenied(reason)
    return result.stdout


def _read_ssh_report(args: list[str], *, data: bytes) -> dict:
    """Tell SSH transport errors from valid, fail-closed remote diagnostics.

    The remote read-only inspector intentionally exits 2 for missing runtime
    evidence, even after successful SSH authentication. Never export stderr.
    """
    try:
        result = subprocess.run(
            args, input=data, capture_output=True, timeout=90, check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise VerificationDenied("ssh_connection_or_command_unavailable") from None
    if result.returncode == 255:
        # OpenSSH uses 255 for transport/authentication failures. It does not
        # prove which issue occurred, so do not claim that credentials are bad.
        raise VerificationDenied("ssh_transport_or_authorization_failed")
    if result.returncode not in (0, 2):
        raise VerificationDenied("ssh_remote_command_failed")
    if len(result.stdout) > 1024 * 1024:
        raise VerificationDenied("ssh_remote_report_oversize")
    try:
        report = json.loads(result.stdout)
    except (ValueError, TypeError):
        raise VerificationDenied("ssh_remote_report_invalid") from None
    if not isinstance(report, dict):
        raise VerificationDenied("ssh_remote_report_invalid")
    if (report.get("status") == "BLOCKED"
            and report.get("reason") in {"service_identity_mismatch", "baseline_commit_mismatch"}):
        raise VerificationDenied("ssh_runtime_deployment_identity_mismatch")
    if (report.get("status") != "DIAGNOSTIC_ONLY"
            or (result.returncode == 0) != report_succeeded(report)):
        raise VerificationDenied("ssh_remote_report_exit_mismatch")
    return report


def _runtime(approval: dict) -> dict:
    key = os.environ.get("RENDER_RECOVERY_SSH_KEY", "")
    if not key:
        raise VerificationDenied("recovery_ssh_key_missing")
    with tempfile.TemporaryDirectory(prefix="nija-readonly-") as directory:
        root = Path(directory)
        private_key, known_hosts = root / "key", root / "known_hosts"
        private_key.touch(mode=0o600)
        private_key.write_text(key + "\n")
        _command(["ssh-keygen", "-y", "-P", "", "-f", str(private_key)], "recovery_ssh_key_invalid")
        host_keys = _command(
            ["ssh-keyscan", "-t", "ed25519", "-T", "15", HOST], "ssh_host_key_unavailable",
        )
        known_hosts.write_bytes(host_keys)
        fingerprints = _command(
            ["ssh-keygen", "-lf", str(known_hosts), "-E", "sha256"], "ssh_host_key_invalid",
        )
        if {line.split()[1] for line in fingerprints.decode().splitlines()} != {HOST_FINGERPRINT}:
            raise VerificationDenied("ssh_host_fingerprint_mismatch")
        return _read_ssh_report([
            "ssh", "-T", "-i", str(private_key),
            "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", "IdentityAgent=none",
            "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=" + str(known_hosts),
            "-o", "HostKeyAlgorithms=ssh-ed25519", "-o", "ConnectTimeout=15",
            "-o", "ConnectionAttempts=1", "-o", "ServerAliveInterval=10",
            "-o", "ServerAliveCountMax=1", SERVICE + "@" + HOST,
            "env NIJA_APPROVED_RENDER_COMMIT=" + approval["commit"] + " python -B -S -",
        ], data=Path("scripts/nija_kraken_instance_diagnostic.py").read_bytes())


def run_verification() -> dict:
    """Emit only public provenance and fixed outcomes; never broker/account payloads."""
    result = {name: False for name in OUTCOMES}
    result.update({
        "mode": "READ_ONLY_RECOVERY", "allow_new_orders": False, "failures": [],
        "workflow_source_commit": os.environ.get("GITHUB_SHA"),
    })
    try:
        if os.environ.get("GITHUB_REF") != "refs/heads/" + RELEASE_BRANCH:
            raise VerificationDenied("workflow_dispatch_not_production_release")
        result["verification_source_commit"] = _command(
            ["git", "rev-parse", "HEAD"], "release_checkout_unavailable",
        ).decode().strip()
        # The independent environment's guarded secret must exist BEFORE any
        # Render API or SSH access. A release-branch commit cannot self-approve.
        approval = load_reviewed_approval()
        evidence = inspect_render_api(deployment_only=True)
        for key in ("service_id", "deployment_id", "commit", "branch", "release_branch_verified", "deployment_status"):
            if key in evidence:
                result["render_" + key] = evidence[key]
        result["render_evidence_failures"] = evidence["failures"]
        verify_baseline(approval, evidence, workflow_ref=os.environ.get("GITHUB_REF", ""))
        commit = approval["commit"]
        _command(["git", "merge-base", "--is-ancestor", commit, "HEAD"], "deployment_not_on_release_lineage")
        result["inspected_source_commit"] = commit
        for path, digest in approval["source_sha256"].items():
            source = _command(["git", "show", commit + ":" + path], "inspected_source_missing")
            if hashlib.sha256(source).hexdigest() != digest:
                raise VerificationDenied("reviewed_source_digest_mismatch")
        result["DEPLOYMENT_BASELINE_VERIFIED"] = True
        report = _runtime(approval)
        # A valid, authenticated remote diagnostic may be blocked by its own
        # read-only evidence checks. Report ONLY predefined reason labels.
        if report.get("status") == "DIAGNOSTIC_ONLY":
            result["ssh_runtime_report_received"] = True
            failures = report.get("failures")
            if isinstance(failures, list):
                safe = sorted({
                    reason for reason in failures
                    if type(reason) is str and reason in SAFE_RUNTIME_EVIDENCE_FAILURES
                })
                if safe:
                    result["ssh_runtime_evidence_failures"] = safe
        # Render captures stdout/stderr outside local /app files. Only a
        # pinned, bounded same-instance heartbeat can corroborate this exact
        # missing-file issue; all other runtime failures still block.
        render_app_log_proof = False
        if report.get("failures") == ["current_process_log_evidence_unavailable"]:
            render_app_log_proof = _verify_render_instance_app_logs(approval, report)
            result["render_instance_app_log_evidence_verified"] = render_app_log_proof
        verify_runtime(
            approval, report, render_instance_app_logs_verified=render_app_log_proof,
        )
        # A deployment may change during SSH; recheck independent live metadata.
        verify_baseline(approval, inspect_render_api(deployment_only=True), workflow_ref=os.environ["GITHUB_REF"])
        result["RUNTIME_ACCESS_VERIFIED"] = True
        result["SOURCE_INTEGRITY_VERIFIED"] = True
        result["source_sha256"] = approval["source_sha256"]
        output = os.environ.get("GITHUB_OUTPUT")
        if output:
            with open(output, "a", encoding="utf-8") as stream:
                stream.write("approved_commit=" + commit + "\n")
                stream.write("approved_deployment_id=" + approval["deployment_id"] + "\n")
                stream.write("verification_source_commit=" + result["verification_source_commit"] + "\n")
    except VerificationDenied as exc:
        result["failures"].append(str(exc))
        # Partial/before-redeploy observations never leave a verified baseline.
        result["DEPLOYMENT_BASELINE_VERIFIED"] = False
    except (OSError, ValueError, TypeError, KeyError, IndexError):
        result["failures"].append("verification_input_or_report_invalid")
        result["DEPLOYMENT_BASELINE_VERIFIED"] = False
    result["WORKFLOW_EXECUTION_SUCCESS"] = True
    # This transport does not collect the 13 independent broker observations.
    # A passing access diagnostic must never become a trading certificate.
    return result


if __name__ == "__main__":
    report = run_verification()
    Path("render-recovery-verification.json").write_text(json.dumps(report, sort_keys=True) + "\n")
    print(json.dumps(report, sort_keys=True))
    raise SystemExit(2 if report["failures"] else 0)
