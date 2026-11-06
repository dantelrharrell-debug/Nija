"""Exercise real pinned secret enforcement without external provider verification."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts/run_baseline_secret_scan.py"


def run_scan(root: Path, baseline: dict, source: str) -> tuple[subprocess.CompletedProcess, dict]:
    """Build a throwaway tracked repository and invoke the actual scan wrapper."""
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    baseline_path = root / ".secrets.baseline"
    original = json.dumps(baseline).encode()
    baseline_path.write_bytes(original)
    (root / "probe.py").write_text(source)
    subprocess.run(["git", "add", "."], cwd=root, check=True)
    report = root / "report.json"
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--report", str(report)], cwd=root,
        capture_output=True, text=True, timeout=30,
        env=dict(os.environ, NIJA_DEFER_RUNTIME_SITE_HOOKS="1"),
    )
    assert baseline_path.read_bytes() == original
    return result, json.loads(report.read_text())


@pytest.fixture
def baseline() -> dict:
    """Use a deterministic local detector; do not send fixture values to providers."""
    return {
        "version": "1.5.0",
        "plugins_used": [{"name": "KeywordDetector", "keyword_exclude": ""}],
        "filters_used": [{"path": "detect_secrets.filters.common.is_baseline_file",
                          "filename": ".secrets.baseline"}],
        "results": {},
    }


def test_clean_scan_passes_without_rewriting_baseline(tmp_path, baseline):
    result, report = run_scan(tmp_path, baseline, "count = 12\n")
    assert result.returncode == 0
    assert report["outcome"] == "clean"
    assert report["tracked_file_count"] == 2


def test_new_candidate_blocks_without_disclosing_value_or_digest(tmp_path, baseline):
    candidate = secrets.token_hex(24)
    result, report = run_scan(tmp_path, baseline, f'password = "{candidate}"\n')
    assert result.returncode == 1
    assert report["outcome"] == "unbaselined_candidates"
    assert report["findings"] == [{"path": "probe.py", "line": 1, "type": "Secret Keyword"}]
    evidence = json.dumps(report) + result.stdout + result.stderr
    assert candidate not in evidence
    assert hashlib.sha1(candidate.encode(), usedforsecurity=False).hexdigest() not in evidence


def test_existing_baseline_identity_is_respected(tmp_path, baseline):
    candidate = secrets.token_hex(24)
    baseline["results"] = {"probe.py": [{
        "type": "Secret Keyword", "filename": "probe.py", "line_number": 1,
        "hashed_secret": hashlib.sha1(candidate.encode(), usedforsecurity=False).hexdigest(),
        "is_verified": False,
    }]}
    result, report = run_scan(tmp_path, baseline, f'password = "{candidate}"\n')
    assert result.returncode == 0
    assert report["findings"] == []


def test_line_number_drift_stays_nonzero_without_mutation(tmp_path, baseline):
    candidate = secrets.token_hex(24)
    baseline["results"] = {"probe.py": [{
        "type": "Secret Keyword", "filename": "probe.py", "line_number": 1,
        "hashed_secret": hashlib.sha1(candidate.encode(), usedforsecurity=False).hexdigest(),
        "is_verified": False,
    }]}
    result, report = run_scan(tmp_path, baseline, f'\npassword = "{candidate}"\n')
    assert result.returncode == 3
    assert report["outcome"] == "baseline_refresh_required"
    assert report["baseline_would_change"] is True


def test_invalid_baseline_fails_closed_with_evidence(tmp_path, baseline):
    baseline["version"] = "unsupported"
    result, report = run_scan(tmp_path, baseline, "count = 12\n")
    assert result.returncode == 2
    assert report["outcome"] == "scanner_error"


def test_security_workflow_keeps_secret_findings_blocking():
    """Baseline candidates still cause a hard failure and retain redacted evidence."""
    import yaml

    workflow = yaml.safe_load(
        (SCRIPT.parents[1] / ".github/workflows/security-scan.yml").read_text()
    )
    steps = workflow["jobs"]["secrets-scan"]["steps"]
    enforcement = next(step for step in steps if step["name"] == "Enforce baseline-aware scanning")
    evidence = next(step for step in steps if step["name"] == "Retain value-free secret scan evidence")
    assert "run_baseline_secret_scan.py" in enforcement["run"]
    assert "continue-on-error" not in enforcement
    assert "|| true" not in enforcement["run"]
    assert evidence["if"] == "always()"
    assert evidence["with"]["path"] == "secret-scan-report.json"


def test_precommit_failure_propagates_and_reports_real_outcome():
    """A failed hook build must fail CI instead of yielding a green job."""
    import yaml

    workflow = yaml.safe_load(
        (SCRIPT.parents[1] / ".github/workflows/security-scan.yml").read_text()
    )
    job = workflow["jobs"]["pre-commit-checks"]
    steps = job["steps"]
    setup = next(step for step in steps if step["name"] == "Set up compatible Go for existing hooks")
    assert setup["with"]["go-version"] == "1.24.x"
    assert setup["with"]["cache"] is False
    run = next(step for step in steps if step["name"] == "Run pre-commit on all files")
    assert run["id"] == "precommit"
    assert "pre-commit run --all-files --show-diff-on-failure" in run["run"]
    assert "continue-on-error" not in job
    assert all("continue-on-error" not in step for step in steps)
    assert "|| true" not in run["run"]
    report = next(step for step in steps if step["name"] == "Generate pre-commit report")
    assert report["if"] == "always()"
    assert "steps.precommit.outcome" in report["env"]["PRECOMMIT_OUTCOME"]
    assert "PRECOMMIT_OUTCOME" in report["run"]
    upload = next(step for step in steps if step["name"] == "Upload pre-commit report")
    assert upload["if"] == "always()"
