"""Verify narrow fixture exceptions with the real pinned detector and mutation."""
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import io
import json
from pathlib import Path
import secrets
import subprocess

from detect_secrets.pre_commit_hook import main as hook_main

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / ".secrets.baseline"
MANIFEST = ROOT / "docs/security/verified-synthetic-fixture-candidates-20261112.json"
FIXTURE = "bot/tests/test_writer_lease_lifecycle.py"


def test_review_is_limited_to_test_files_and_exact_keyword_identities():
    baseline = json.loads(BASELINE.read_text())
    review = json.loads(MANIFEST.read_text())
    assert len(review["entries"]) == 35
    for record in review["entries"]:
        path = record["path"]
        assert path.startswith(("tests/", "bot/tests/")) or Path(path).name.startswith("test_")
        assert record["type"] == "Secret Keyword"
        matches = [item for item in baseline["results"][path]
                   if item["line_number"] == record["line"] and item["type"] == record["type"]]
        assert len(matches) == 1
        assert matches[0]["is_secret"] is False
        assert set(matches[0]) == {
            "type", "filename", "hashed_secret", "is_verified", "line_number", "is_secret",
        }


def _run_detector(tmp_path, monkeypatch, source):
    path = tmp_path / FIXTURE
    path.parent.mkdir(parents=True)
    path.write_text(source)
    baseline = tmp_path / ".secrets.baseline"
    baseline.write_bytes(BASELINE.read_bytes())
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.name=Synthetic review test",
                    "-c", "user.email=fixture@example.invalid", "commit", "-qm", "Synthetic fixture"],
                   cwd=tmp_path, check=True)
    monkeypatch.chdir(tmp_path)
    output = io.StringIO()
    with redirect_stdout(output), redirect_stderr(io.StringIO()):
        status = hook_main(["--json", "--baseline", str(baseline), FIXTURE])
    return status, output.getvalue()


def test_exact_reviewed_fixture_has_no_unbaselined_findings(tmp_path, monkeypatch):
    status, _ = _run_detector(tmp_path, monkeypatch, (ROOT / FIXTURE).read_text())
    assert status == 0


def test_changed_value_at_same_reviewed_location_is_still_rejected(tmp_path, monkeypatch):
    source = (ROOT / FIXTURE).read_text()
    reviewed_literal = '"test-key"'
    assert source.count(reviewed_literal) == 1
    candidate = "unreviewed-" + secrets.token_hex(20)
    source = source.replace(reviewed_literal, repr(candidate), 1)
    status, output = _run_detector(tmp_path, monkeypatch, source)
    assert status == 1
    rows = json.loads(output)["results"][FIXTURE]
    assert any(item["hashed_secret"] == hashlib.sha1(candidate.encode(), usedforsecurity=False).hexdigest()
               for item in rows)
    assert candidate not in output
