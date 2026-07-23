from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "runtime_entrypoint_attestation.py"


def _load_module():
    name = "runtime_entrypoint_attestation_v23_test"
    spec = importlib.util.spec_from_file_location(name, MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_repository_canonical_runtime_contract_passes(monkeypatch):
    module = _load_module()
    monkeypatch.setenv("GIT_BRANCH", "main")
    monkeypatch.setenv("GIT_COMMIT", "eb8f660623f13372ce213e79c1f10535db686590")
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")

    report = module.validate_runtime(ROOT)

    assert report["canonical"] == "main.py->bot.bot->bot.bot_main"
    assert report["commit"].startswith("eb8f660")
    assert "bot/canonical_broker_prebootstrap_v22.py:" in report["hashes"]
    assert "bot/stalled_writer_release_guard_v22.py:" in report["hashes"]


def test_attestation_fails_when_required_runtime_file_is_missing(tmp_path, monkeypatch):
    module = _load_module()
    monkeypatch.setattr(
        module,
        "_CONTRACTS",
        (module.FileContract("bot/canonical_broker_prebootstrap_v22.py", ("marker",)),),
    )

    try:
        module.validate_runtime(tmp_path)
    except RuntimeError as exc:
        assert "required runtime file missing" in str(exc)
    else:
        raise AssertionError("expected missing runtime file to fail attestation")


def test_live_attestation_rejects_unknown_commit(monkeypatch):
    module = _load_module()
    monkeypatch.setenv("GIT_BRANCH", "main")
    monkeypatch.setenv("GIT_COMMIT", "unknown")
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")

    try:
        module.validate_runtime(ROOT)
    except RuntimeError as exc:
        assert "commit provenance is unknown" in str(exc)
    else:
        raise AssertionError("expected unknown live commit to fail attestation")


def test_paper_mode_allows_unknown_commit_for_local_validation(monkeypatch):
    module = _load_module()
    monkeypatch.setenv("GIT_BRANCH", "unknown")
    monkeypatch.setenv("GIT_COMMIT", "unknown")
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "false")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "true")

    report = module.validate_runtime(ROOT)
    assert report["commit"] == "unknown"
