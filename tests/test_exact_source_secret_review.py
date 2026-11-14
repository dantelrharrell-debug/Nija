"""Keep exact false-positive reviews from concealing changed credentials."""
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import subprocess
import sys

from detect_secrets.pre_commit_hook import main as hook_main
import pytest
import yaml

from scripts.check_reviewed_secret_context import MANIFEST, check_context

ROOT = Path(__file__).resolve().parents[1]


def _reviewed_source_drift(root: Path, review: dict) -> list[str]:
    """Identify reviewed source drift by path only; never export source or digests."""
    changed = []
    for name, expected in review["files"].items():
        if not isinstance(name, str):
            changed.append("invalid_review_path")
            continue
        path = PurePosixPath(name)
        if path.is_absolute() or ".." in path.parts or str(path) != name:
            changed.append("invalid_review_path")
            continue
        source = root / name
        try:
            if (source.resolve() != source.absolute() or not source.is_file()
                    or hashlib.sha256(source.read_bytes()).hexdigest()
                    != expected.replace(":", "")):
                changed.append(name)
        except (OSError, ValueError, TypeError):
            changed.append(name)
    return changed



def _reviewed_source_checkout_reason(root: Path, review: dict, name: str) -> str:
    """Classify a failed source pin using only local Git evidence, never bytes."""
    try:
        name_path = PurePosixPath(name)
        if name_path.is_absolute() or ".." in name_path.parts or str(name_path) != name:
            return "reviewed_path_invalid"
        expected = review["files"][name].replace(":", "")
        original = subprocess.run(
            ["git", "show", "HEAD:" + name], cwd=root, capture_output=True, check=True,
        ).stdout
        if hashlib.sha256(original).hexdigest() != expected:
            return "committed_source_review_pin_mismatch"
        target = root / name
        if target.resolve() != target.absolute() or not target.is_file():
            return "worktree_source_path_invalid"
        if hashlib.sha256(target.read_bytes()).hexdigest() != expected:
            return "worktree_source_changed_from_commit"
        return "source_matches_reviewed_commit"
    except (OSError, KeyError, ValueError, TypeError, subprocess.CalledProcessError):
        return "committed_source_unavailable"


def _reviewed_source_drift_summary(root: Path, review: dict) -> str:
    """Provide paths and fixed reason codes only; source and hashes remain private."""
    paths = _reviewed_source_drift(root, review)
    if not paths:
        return "manifest_validation_failed"
    return ", ".join(
        path + "=" + _reviewed_source_checkout_reason(root, review, path)
        for path in paths
    )


def test_review_adds_only_the_exact_142_reviewed_identities():
    before = json.loads(subprocess.check_output([
        "git", "show", "15b64ddcb44fa67f33a336b799ee8f89b1bc1fe9:.secrets.baseline",
    ], cwd=ROOT))
    current = json.loads((ROOT / ".secrets.baseline").read_text())
    # Normalize only the separately reviewed public source-digest replacement
    # before checking the original 142-candidate review. All other identities,
    # audit flags, metadata and detector configuration remain checked below.
    consumer = "bot/kraken_identity_request_recovery_v491.py"
    digest = (
        "69:e4:61:77:11:01:3c:ad:18:54:6e:db:9e:e2:18:32:"
        "44:1d:88:b6:b8:4e:26:a1:76:bd:7c:ff:6b:c2:48:ce"
    ).replace(":", "")
    assert hashlib.sha256((ROOT / consumer).read_bytes()).hexdigest() == digest
    replacement = hashlib.sha1(digest.encode(), usedforsecurity=False).hexdigest()
    assert replacement == "cf:fe:4e:38:59:17:70:46:6a:fb:d7:96:43:f0:a9:b7:3f:0d:e0:28".replace(":", "")
    original = "13:d4:20:a6:f4:c6:49:56:89:a8:95:5d:10:6a:01:4a:c6:0e:2d:30".replace(":", "")
    for name in ("ops/recovery/render_readonly_baseline.json",
                 "scripts/nija_kraken_instance_diagnostic.py"):
        rows = current["results"][name]
        matches = [row for row in rows if row["type"] == "Hex High Entropy String"
                   and row["hashed_secret"] == replacement]
        assert len(matches) == 1
        assert not any(row["hashed_secret"] == original for row in rows)
        matches[0]["hashed_secret"] = original
    review = json.loads((ROOT / MANIFEST).read_text())
    assert current["reviewed_context_manifest"] == MANIFEST
    assert {k: v for k, v in before.items() if k != "results"} == {
        k: v for k, v in current.items() if k not in {"results", "reviewed_context_manifest"}
    }
    assert len(review["entries"]) == 142
    assert len(review["files"]) == 78
    assert check_context(ROOT), (
        "Reviewed context invalid (paths only): "
        + _reviewed_source_drift_summary(ROOT, review)
    )
    old = {(p, x["type"], x["hashed_secret"]): x
           for p, rows in before["results"].items() for x in rows}
    new = {(p, x["type"], x["hashed_secret"]): x
           for p, rows in current["results"].items() for x in rows}
    for key in old.keys() & new.keys():
        assert {k: v for k, v in old[key].items() if k not in {"line_number", "filename"}} == {
            k: v for k, v in new[key].items() if k not in {"line_number", "filename"}
        }
    assert {(k[0], k[1], old[k]["line_number"]) for k in old.keys() - new.keys()} == {
        (x["path"], x["type"], x["old_line"])
        for x in review["baseline_refresh"]["removed_absent_identities"]
    }
    assert len(old.keys() - new.keys()) == 10
    assert {(k[0], k[1], old[k]["line_number"], new[k]["line_number"])
            for k in old.keys() & new.keys() if old[k] != new[k]} == {
        (x["path"], x["type"], x["old_line"], x["new_line"])
        for x in review["baseline_refresh"]["normalized_existing_metadata"]
    }
    additions = [value for key, value in new.items() if key not in old]
    assert len(additions) == 142
    assert {(x["filename"], x["line_number"], x["type"]) for x in additions} == {
        (x["path"], x["line"], x["type"]) for x in review["entries"]
    }
    assert all(x["is_secret"] is False and x["is_verified"] is False for x in additions)


def fixture_review(root, contents="public format marker\n"):
    source = root / "probe.py"
    source.write_text(contents)
    manifest = root / MANIFEST
    manifest.parent.mkdir(parents=True)
    manifest.write_text(json.dumps({
        "schema_version": 1,
        "files": {"probe.py": hashlib.sha256(source.read_bytes()).digest().hex(":")},
        "entries": [{"path": "probe.py", "line": 1, "type": "Private Key"}],
    }))
    return source, manifest


def test_reviewed_source_drift_reports_only_paths_and_preserves_denial(tmp_path):
    source, manifest = fixture_review(tmp_path)
    review = json.loads(manifest.read_text())
    assert _reviewed_source_drift(tmp_path, review) == []
    changed_bytes = "changed fixture bytes must not appear in diagnostics"
    source.write_text(changed_bytes)
    paths = _reviewed_source_drift(tmp_path, review)
    assert paths == ["probe.py"]
    assert changed_bytes not in repr(paths)
    assert not check_context(tmp_path)



def test_checkout_drift_diagnosis_distinguishes_mutated_source_from_stale_pin(tmp_path):
    source, manifest = fixture_review(tmp_path)
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "-c", "user.name=Source review test",
         "-c", "user.email=fixture@example.invalid",
         "commit", "-qm", "Reviewed fixture source"],
        cwd=tmp_path, check=True,
    )
    review = json.loads(manifest.read_text())
    assert _reviewed_source_checkout_reason(tmp_path, review, "probe.py") == "source_matches_reviewed_commit"
    canary = "synthetic fixture bytes must never enter a source review report"
    source.write_text(canary)
    reason = _reviewed_source_drift_summary(tmp_path, review)
    assert reason == "probe.py=worktree_source_changed_from_commit"
    assert canary not in reason
    assert not check_context(tmp_path)
    source.write_text("public format marker\n")
    review["files"]["probe.py"] = "00:" * 31 + "00"
    reason = _reviewed_source_drift_summary(tmp_path, review)
    assert reason == "probe.py=committed_source_review_pin_mismatch"
    assert canary not in reason
    manifest.write_text(json.dumps(review))
    assert not check_context(tmp_path)


def test_exact_source_passes_but_any_payload_or_context_change_denies(tmp_path):
    source, _ = fixture_review(tmp_path)
    assert check_context(tmp_path)
    source.write_text(source.read_text() + "new payload\n")
    assert not check_context(tmp_path)


def test_real_scan_wrapper_rejects_changed_review_before_detection(tmp_path):
    source, _ = fixture_review(tmp_path)
    baseline = {
        "version": "1.5.0",
        "plugins_used": [{"name": "KeywordDetector", "keyword_exclude": ""}],
        "filters_used": [], "results": {}, "reviewed_context_manifest": MANIFEST,
    }
    (tmp_path / ".secrets.baseline").write_text(json.dumps(baseline))
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    def commit():
        subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
        subprocess.run([
            "git", "-c", "user.name=Source review test", "-c", "user.email=fixture@example.invalid",
            "commit", "-qm", "Isolated review fixture",
        ], cwd=tmp_path, check=True)

    commit()
    report = tmp_path / "report.json"
    env = {k: v for k, v in os.environ.items() if k not in {"GITHUB_SHA", "GITHUB_EVENT_NAME"}}
    env["NIJA_DEFER_RUNTIME_SITE_HOOKS"] = "1"
    def invoke():
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts/run_baseline_secret_scan.py"), "--report", str(report)],
            cwd=tmp_path, capture_output=True, text=True, env=env, timeout=30,
        )

    assert invoke().returncode == 0
    report.unlink()
    source.write_text("changed source must remain private\n")
    commit()  # A clean committed checkout must still fail its stale review.
    result = invoke()
    assert result.returncode == 2
    assert json.loads(report.read_text())["outcome"] == "scanner_error"
    assert "changed source must remain private" not in report.read_text() + result.stdout + result.stderr


def test_marker_identity_collision_does_not_authorize_changed_pem_payload(tmp_path, monkeypatch):
    begin = "-----BEGIN " + "PRIVATE KEY-----"
    end = "-----END " + "PRIVATE KEY-----"
    source, _ = fixture_review(tmp_path, 'pem = "' + begin + '\\nQUJDRA==\\n' + end + '"\n')
    baseline = json.loads((ROOT / ".secrets.baseline").read_text())
    baseline.pop("reviewed_context_manifest")
    baseline["results"] = {}
    path = tmp_path / ".secrets.baseline"
    path.write_text(json.dumps(baseline))
    monkeypatch.chdir(tmp_path)
    output = io.StringIO()
    with redirect_stdout(output), redirect_stderr(io.StringIO()):
        assert hook_main(["--json", "--baseline", str(path), str(source)]) == 1
    first = json.loads(output.getvalue())["results"]
    first_hashes = {x["hashed_secret"] for rows in first.values() for x in rows if x["type"] == "Private Key"}
    assert first_hashes
    source.write_text(source.read_text().replace("QUJDRA==", "TkVXUEFZTE9BRA=="))
    output = io.StringIO()
    with redirect_stdout(output), redirect_stderr(io.StringIO()):
        assert hook_main(["--json", "--baseline", str(path), str(source)]) == 1
    second = json.loads(output.getvalue())["results"]
    assert first_hashes == {x["hashed_secret"] for rows in second.values() for x in rows if x["type"] == "Private Key"}
    assert not check_context(tmp_path)


@pytest.mark.parametrize("change", ["missing", "duplicate", "bad_digest", "traversal", "symlink", "missing_file"])
def test_invalid_or_substituted_review_denies(tmp_path, change):
    source, manifest = fixture_review(tmp_path)
    data = json.loads(manifest.read_text())
    if change == "missing":
        manifest.unlink()
    elif change == "duplicate":
        manifest.write_text('{"schema_version":1,"schema_version":1}')
    elif change == "bad_digest":
        data["files"]["probe.py"] = "invalid"
        manifest.write_text(json.dumps(data))
    elif change == "traversal":
        data["files"] = {"../probe.py": "0" * 64}
        data["entries"][0]["path"] = "../probe.py"
        manifest.write_text(json.dumps(data))
    elif change == "symlink":
        target = tmp_path / "other.py"
        target.write_bytes(source.read_bytes())
        source.unlink()
        source.symlink_to(target)
    else:
        source.unlink()
    assert not check_context(tmp_path)


def test_mandatory_workflow_and_precommit_validate_context():
    workflow = yaml.safe_load((ROOT / ".github/workflows/security-scan.yml").read_text())
    run = next(s["run"] for s in workflow["jobs"]["secrets-scan"]["steps"]
               if s.get("name") == "Validate baseline reporting regressions")
    assert "tests/test_exact_source_secret_review.py" in run
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    hook = next(h for repo in config["repos"] for h in repo["hooks"] if h["id"] == "reviewed-secret-context")
    assert hook["always_run"] is True and hook["pass_filenames"] is False
    assert hook["entry"] == "python3 -S scripts/check_reviewed_secret_context.py"
