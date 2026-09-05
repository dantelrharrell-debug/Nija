from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PATCHER_PATH = ROOT / "scripts" / "apply_execution_proof_startup_isolation_v339.py"


def _load_patcher():
    spec = importlib.util.spec_from_file_location("nija_v339_patcher_test", PATCHER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_launcher_patch_routes_authority_marker_before_startup_guard():
    patcher = _load_patcher()
    source = (ROOT / "scripts" / "canonical_runtime_launcher_v26.py").read_text(
        encoding="utf-8"
    )
    patched = patcher.patch_launcher_text(source)

    main_at = patched.index("def main()")
    prepare_at = patched.index(
        "_prepare_execution_proof_startup_isolation_v339()", main_at
    )
    startup_at = patched.index("install_canonical_startup_guard()", main_at)
    assert prepare_at < startup_at
    assert 'os.environ["HEARTBEAT_MARKER_PATH"] = authority_path' in patched
    assert 'os.environ["NIJA_EXECUTION_MARKER_PATH"] = execution_path' in patched


def test_v169_patch_quarantines_only_authority_origin_execution_marker():
    patcher = _load_patcher()
    source = (ROOT / "bot" / "runtime_execution_capital_integrity_v169_patch.py").read_text(
        encoding="utf-8"
    )
    patched = patcher.patch_v169_text(source)

    assert "def _quarantine_authority_execution_marker()" in patched
    assert 'source not in {"heartbeat_authority_single_source", "authority_heartbeat"}' in patched
    assert 'kind not in {"", "authority_liveness"}' in patched
    assert 'os.environ["HEARTBEAT_MARKER_PATH"] = str(execution_path)' in patched
    assert "authority_execution_marker_path_collision" in patched


def test_v238_patch_requires_v169_and_explicit_execution_provenance():
    patcher = _load_patcher()
    source = (ROOT / "bot" / "runtime_heartbeat_marker_convergence_v238_patch.py").read_text(
        encoding="utf-8"
    )
    patched = patcher.patch_v238_text(source)

    assert "v169_provenance_guard_not_ready" in patched
    assert 'allowed_sources = {"heartbeat_trade", "canonical_confirmed_fill"}' in patched
    assert 'source not in allowed_sources' in patched
    assert 'kind != "execution_probe"' in patched
    assert "verified_v169_execution_probe:source=" in patched


def test_v238_patch_preserves_render_compatibility_token():
    patcher = _load_patcher()
    source = (ROOT / "bot" / "runtime_heartbeat_marker_convergence_v238_patch.py").read_text(
        encoding="utf-8"
    )
    patched = patcher.patch_v238_text(source)

    # render_entrypoint.sh still validates that the historical hardening token exists.
    assert 'source != "heartbeat_trade"' in patched


def test_v339_source_transformations_are_idempotent():
    patcher = _load_patcher()

    launcher = (ROOT / "scripts" / "canonical_runtime_launcher_v26.py").read_text(
        encoding="utf-8"
    )
    once = patcher.patch_launcher_text(launcher)
    assert patcher.patch_launcher_text(once) == once

    v169 = (ROOT / "bot" / "runtime_execution_capital_integrity_v169_patch.py").read_text(
        encoding="utf-8"
    )
    once = patcher.patch_v169_text(v169)
    assert patcher.patch_v169_text(once) == once

    v238 = (ROOT / "bot" / "runtime_heartbeat_marker_convergence_v238_patch.py").read_text(
        encoding="utf-8"
    )
    once = patcher.patch_v238_text(v238)
    assert patcher.patch_v238_text(once) == once