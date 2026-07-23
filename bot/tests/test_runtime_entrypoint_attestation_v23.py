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


def _clear_provider_metadata(monkeypatch):
    for name in (
        "GIT_BRANCH",
        "RENDER_GIT_BRANCH",
        "RAILWAY_GIT_BRANCH",
        "GIT_COMMIT",
        "RENDER_GIT_COMMIT",
        "RAILWAY_GIT_COMMIT_SHA",
    ):
        monkeypatch.delenv(name, raising=False)


def test_repository_canonical_runtime_contract_passes(monkeypatch):
    _clear_provider_metadata(monkeypatch)
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


def test_live_attestation_uses_render_commit_when_generic_value_is_placeholder(monkeypatch):
    _clear_provider_metadata(monkeypatch)
    module = _load_module()
    monkeypatch.setenv("GIT_BRANCH", "unknown")
    monkeypatch.setenv("RENDER_GIT_BRANCH", "main")
    monkeypatch.setenv("GIT_COMMIT", "unknown")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "render-commit-123")
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")

    report = module.validate_runtime(ROOT)

    assert report["branch"] == "main"
    assert report["commit"] == "render-commit-123"


def test_live_attestation_rejects_unknown_commit_across_all_providers(monkeypatch):
    _clear_provider_metadata(monkeypatch)
    module = _load_module()
    monkeypatch.setenv("GIT_BRANCH", "main")
    monkeypatch.setenv("GIT_COMMIT", "unknown")
    monkeypatch.setenv("RENDER_GIT_COMMIT", "none")
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "null")
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
    _clear_provider_metadata(monkeypatch)
    module = _load_module()
    monkeypatch.setenv("GIT_BRANCH", "unknown")
    monkeypatch.setenv("GIT_COMMIT", "unknown")
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "false")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "true")

    report = module.validate_runtime(ROOT)
    assert report["commit"] == "unknown"
