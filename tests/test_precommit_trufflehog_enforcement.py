"""Offline checks for blocking status propagation and candidate redaction."""
import importlib.util
from pathlib import Path
import subprocess

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "precommit_trufflehog", ROOT / "scripts/run_precommit_trufflehog.py",
)
wrapper = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wrapper)


@pytest.fixture(autouse=True)
def scanner_path(monkeypatch):
    monkeypatch.setattr(wrapper.shutil, "which", lambda name: "/trusted-hook/trufflehog")


@pytest.mark.parametrize("status", [1, 2, 42, 183, -9])
def test_scanner_failures_stay_blocking_and_private(monkeypatch, capsys, status):
    sentinel = "synthetic-private-output-must-not-appear"
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], status, sentinel, sentinel))
    assert wrapper.main() != 0
    output = capsys.readouterr()
    assert sentinel not in output.out + output.err


def test_clean_result_preserves_verified_full_filesystem_scope(monkeypatch):
    calls = []

    def run(args, **kwargs):
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(wrapper.subprocess, "run", run)
    assert wrapper.main() == 0
    args, options = calls[0]
    assert args == ["/trusted-hook/trufflehog", "filesystem", ".", "--only-verified", "--json", "--fail"]
    assert options["capture_output"] is True
    assert options["timeout"] == 900
    assert options["stdin"] == subprocess.DEVNULL


@pytest.mark.parametrize("stdout", ['{"Verified":true,"Raw":"synthetic"}', 'invalid-json'])
def test_success_with_candidate_or_invalid_output_still_denies(monkeypatch, capsys, stdout):
    monkeypatch.setattr(wrapper.subprocess, "run", lambda *args, **kwargs:
                        subprocess.CompletedProcess(args[0], 0, stdout, ""))
    assert wrapper.main() != 0
    assert stdout not in capsys.readouterr().out


@pytest.mark.parametrize("exception", [FileNotFoundError(), subprocess.TimeoutExpired("scanner", 900)])
def test_missing_or_timed_out_scanner_denies(monkeypatch, exception):
    def run(*args, **kwargs):
        raise exception

    monkeypatch.setattr(wrapper.subprocess, "run", run)
    assert wrapper.main() == 2


def test_hook_uses_fail_closed_wrapper_without_runtime_site_hooks():
    config = yaml.safe_load((ROOT / ".pre-commit-config.yaml").read_text())
    hook = next(hook for repo in config["repos"] for hook in repo["hooks"]
                if hook["id"] == "trufflehog")
    assert hook["entry"] == "python3 -S scripts/run_precommit_trufflehog.py"
    assert hook["pass_filenames"] is False


def test_unresolved_scanner_path_denies(monkeypatch):
    monkeypatch.setattr(wrapper.shutil, "which", lambda name: None)
    assert wrapper.main() == 2
