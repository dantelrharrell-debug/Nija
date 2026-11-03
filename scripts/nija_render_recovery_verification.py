"""Read-only, fail-closed Render deployment/source verification for Actions.

The reviewed approval manifest is never rewritten by this program. Render API
metadata, Git source and SSH runtime evidence must independently agree.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time

from scripts.nija_kraken_instance_diagnostic import (
    RELEASE_BRANCH, SERVICE, SOURCE_PATHS, inspect_render_api, report_succeeded,
)

MANIFEST = Path("ops/recovery/render_readonly_baseline.json")
APPROVAL_SECRET_ENV = "NIJA_RENDER_READONLY_APPROVAL_JSON"
_MAX_APPROVAL_BYTES = 16384
HOST = "ssh.oregon.render.com"
HOST_FINGERPRINT = "SHA256:KkZPgnApmttFYSkdJsCi7B01sgZPMI6kY53MDbbanGM"
OUTCOMES = (
    "WORKFLOW_EXECUTION_SUCCESS", "DEPLOYMENT_BASELINE_VERIFIED",
    "SOURCE_INTEGRITY_VERIFIED", "RUNTIME_ACCESS_VERIFIED",
    "BROKER_EVIDENCE_VERIFIED", "CERTIFICATION_COMPLETE",
)


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


def verify_runtime(approval: dict, report: dict) -> None:
    """Require exact current runtime source and process evidence, not log readiness."""
    if (not report_succeeded(report) or report.get("service_id") != SERVICE
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
        raw = _command([
            "ssh", "-T", "-i", str(private_key),
            "-o", "BatchMode=yes", "-o", "IdentitiesOnly=yes", "-o", "IdentityAgent=none",
            "-o", "StrictHostKeyChecking=yes", "-o", "UserKnownHostsFile=" + str(known_hosts),
            "-o", "HostKeyAlgorithms=ssh-ed25519", "-o", "ConnectTimeout=15",
            "-o", "ConnectionAttempts=1", "-o", "ServerAliveInterval=10",
            "-o", "ServerAliveCountMax=1", SERVICE + "@" + HOST,
            "env NIJA_APPROVED_RENDER_COMMIT=" + approval["commit"] + " python -B -S -",
        ], "ssh_runtime_inspection_failed", data=Path("scripts/nija_kraken_instance_diagnostic.py").read_bytes())
        report = json.loads(raw)
        if not isinstance(report, dict):
            raise VerificationDenied("runtime_report_invalid")
        return report


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
        verify_runtime(approval, report)
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
