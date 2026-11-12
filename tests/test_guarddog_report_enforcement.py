"""Exercise incomplete scan rejection and privacy using synthetic reports."""
import importlib.util
import json
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("guarddog_check", ROOT / "scripts/check_guarddog_report.py")
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


@pytest.fixture
def requirements(tmp_path):
    path = tmp_path / "requirements.txt"
    path.write_text("Example_Package[extra]==1.2.3 # pinned\nother==4.0\n")
    return path


def row(name="example-package", version="1.2.3", **updates):
    result = {"issues": 0, "errors": {}, "results": {}, "risks": []}
    result.update(updates)
    return {"dependency": name, "version": version, "result": result}


def report(tmp_path, data):
    path = tmp_path / "report.json"
    path.write_text(json.dumps(data))
    return path


def test_clean_complete_report_passes(tmp_path, requirements):
    data = [row(), row("other", "4.0")]
    assert checker.check_report(report(tmp_path, data), 0, requirements) == 0


@pytest.mark.parametrize("status", [1, 2, 42, 183])
def test_scanner_exit_is_preserved(tmp_path, requirements, status):
    path = report(tmp_path, [row(), row("other", "4.0")])
    assert checker.check_report(path, status, requirements) == status


def test_errors_and_payloads_stay_private(tmp_path, requirements, capsys):
    sentinel = "synthetic-private-scanner-payload"
    data = [row(errors={sentinel: sentinel}), row("other", "4.0")]
    assert checker.check_report(report(tmp_path, data), 0, requirements) == 2
    assert sentinel not in capsys.readouterr().out


def test_findings_stay_blocked_and_summary_has_no_code(tmp_path, requirements, capsys):
    sentinel = "synthetic-private-scanner-payload"
    data = [row(issues=1, results={"capability-process-spawn": [{"code": sentinel}]}), row("other", "4.0")]
    assert checker.check_report(report(tmp_path, data), 0, requirements) == 1
    output = capsys.readouterr().out
    assert "package=example-package findings=1" in output
    assert "rules=capability-process-spawn" in output
    assert sentinel not in output


@pytest.mark.parametrize("data", [[], {}, [None], [{"result": {}}],
    [row(issues=True)], [row(issues=-1)], [row(errors=[])],
    [row(results=[])], [row(risks={})], [row(results={"bundled_binary": False})], [row(results={"invalid rule": []})]])
def test_empty_or_invalid_reports_deny(tmp_path, requirements, data):
    assert checker.check_report(report(tmp_path, data), 0, requirements) == 2


@pytest.mark.parametrize("data", [
    [row()],
    [row(), row()],
    [row(), row("Example.Package")],
    [row(), row("other", "5.0")],
    [row(), row("substitute", "4.0")],
    [row(), row("other", "4.0"), row("unexpected", "2.0")],
])
def test_incomplete_duplicate_wrong_version_or_substituted_packages_deny(tmp_path, requirements, data):
    assert checker.check_report(report(tmp_path, data), 0, requirements) == 2


@pytest.mark.parametrize("updates", [
    {"results": {"threat-filesystem-read": [{"code": "synthetic"}]}},
    {"risks": [{"synthetic": "risk"}]},
])
def test_zero_issue_count_cannot_hide_findings(tmp_path, requirements, updates):
    data = [row(**updates), row("other", "4.0")]
    assert checker.check_report(report(tmp_path, data), 0, requirements) == 2


@pytest.mark.parametrize("contents", ["", "-r other.txt", "example>=1", "example==1; python_version>'3'",
    "example==1\nExample==1", "https://example.invalid/a.whl"])
def test_unsupported_requirement_contract_denies(tmp_path, requirements, contents):
    requirements.write_text(contents)
    assert checker.check_report(report(tmp_path, [row()]), 0, requirements) == 2


def test_missing_truncated_and_duplicate_json_keys_deny(tmp_path, requirements):
    path = tmp_path / "missing.json"
    assert checker.check_report(path, 0, requirements) == 2
    path.write_text('{"synthetic_truncated":')
    assert checker.check_report(path, 0, requirements) == 2
    path.write_text('[{"dependency":"example-package","dependency":"other"}]')
    assert checker.check_report(path, 0, requirements) == 2


@pytest.mark.parametrize("status", [-1, 256, True, "0"])
def test_invalid_scanner_status_denies(tmp_path, requirements, status):
    assert checker.check_report(report(tmp_path, [row(), row("other", "4.0")]), status, requirements) == 2


def test_all_ci_requirement_files_are_supported():
    for filename in ("requirements.txt", "requirements-billing.txt", "requirements-member-broker.txt"):
        assert checker.required_packages(ROOT / filename)


def test_workflow_preserves_status_and_requires_coverage():
    workflow = yaml.safe_load((ROOT / ".github/workflows/artifact-scanning.yml").read_text())
    job = workflow["jobs"]["python-package-scan"]
    assert job["env"]["NIJA_DEFER_RUNTIME_SITE_HOOKS"] == "1"
    step = next(s for s in job["steps"] if s.get("name") == "Scan for malicious packages with PyPI Guardian")
    assert "guarddog==3.2.0" in step["run"]
    assert 'else\n  guarddog_status=$?\nfi' in step["run"]
    assert 'guarddog-report.json "$guarddog_status" "${{ matrix.requirements }}"' in step["run"]
    assert "--no-sandbox" not in step["run"]
    assert "continue-on-error" not in step
