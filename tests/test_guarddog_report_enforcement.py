"""Offline coverage for scanner errors that are distinct from malware findings."""
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("guarddog_check", ROOT / "scripts/check_guarddog_report.py")
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def report(tmp_path, data):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(data))
    return path


def test_clean_complete_report_passes(tmp_path):
    assert checker.check_report(report(tmp_path, [{"result": {"issues": 0, "errors": {}}}]), 0) == 0


@pytest.mark.parametrize("status", [1, 2, 42, 183])
def test_scanner_exit_is_preserved(tmp_path, status):
    path = report(tmp_path, [{"result": {"issues": 0, "errors": {}}}])
    assert checker.check_report(path, status) == status


def test_zero_exit_with_errors_stays_blocked_and_private(tmp_path, capsys):
    sentinel = "synthetic-private-scanner-payload"
    path = report(tmp_path, [{"result": {"issues": 0, "errors": {sentinel: sentinel}}}])
    assert checker.check_report(path, 0) == 2
    assert sentinel not in capsys.readouterr().out


def test_zero_exit_with_findings_stays_blocked(tmp_path):
    path = report(tmp_path, [{"result": {"issues": 1, "errors": {}}}])
    assert checker.check_report(path, 0) == 1


@pytest.mark.parametrize("data", [[], {}, [None], [{"result": {}}],
    [{"result": {"issues": True, "errors": {}}}],
    [{"result": {"issues": -1, "errors": {}}}],
    [{"result": {"issues": 0, "errors": []}}]])
def test_empty_or_invalid_reports_deny(tmp_path, data):
    assert checker.check_report(report(tmp_path, data), 0) == 2


def test_missing_or_truncated_report_denies(tmp_path):
    path = tmp_path / "missing.json"
    assert checker.check_report(path, 0) == 2
    path.write_text('{"synthetic_truncated":')
    assert checker.check_report(path, 0) == 2


def test_workflow_preserves_status_and_pins_report_contract():
    workflow = yaml.safe_load((ROOT / ".github/workflows/artifact-scanning.yml").read_text())
    job = workflow["jobs"]["python-package-scan"]
    assert job["env"]["NIJA_DEFER_RUNTIME_SITE_HOOKS"] == "1"
    step = next(s for s in job["steps"] if s.get("name") == "Scan for malicious packages with PyPI Guardian")
    assert "guarddog==3.2.0" in step["run"]
    assert 'else\n  guarddog_status=$?\nfi' in step["run"]
    assert 'python -S scripts/check_guarddog_report.py guarddog-report.json "$guarddog_status"' in step["run"]
    assert "--no-sandbox" not in step["run"]
    assert "continue-on-error" not in step
