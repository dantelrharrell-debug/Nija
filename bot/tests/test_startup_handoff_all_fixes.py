from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PATCHER = ROOT / "scripts" / "apply_startup_handoff_fix.py"
START_SCRIPT = ROOT / "start.sh"
DEFER_GUARD = ROOT / "scripts" / "install_sitecustomize_defer_guard.py"


def _load_patcher():
    spec = importlib.util.spec_from_file_location("apply_startup_handoff_fix", PATCHER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _startup_source() -> str:
    return (
        "#!/bin/bash\n"
        "set -e  # Exit on error\n"
        "$PY --version\n"
        "$PY -c \"print('preflight')\"\n"
        "_validate_redis_url_or_exit\n"
        "_log_redis_lock_source_hint\n"
        "set +e\n"
        "$PY -u main.py\n"
        "status=$?\n"
    )


def test_patcher_defers_hooks_before_every_python_preflight() -> None:
    module = _load_patcher()
    patched = module.patch_text(_startup_source())

    export_pos = patched.index("export NIJA_DEFER_RUNTIME_SITE_HOOKS=1")
    first_python_pos = patched.index("$PY --version")
    attestation_pos = patched.index("STARTUP_HANDOFF_ENTRYPOINT_ATTESTATION_COMPLETE")
    launcher_pos = patched.index(
        "NIJA_DEFER_RUNTIME_SITE_HOOKS=1 "
        "$PY -u scripts/canonical_runtime_launcher_v26.py"
    )

    assert export_pos < first_python_pos
    assert export_pos < attestation_pos < launcher_pos
    assert "unset NIJA_DEFER_RUNTIME_SITE_HOOKS" not in patched
    assert "$PY -u main.py" not in patched
    assert "STARTUP_HANDOFF_PREFLIGHT_BEGIN" in patched
    assert "STARTUP_HANDOFF_REDIS_VALIDATION_COMPLETE" in patched
    assert "runtime_entrypoint_attestation.py" in patched
    assert "STARTUP_HANDOFF_RUNTIME_BEGIN" in patched
    assert "canonical=launcher-v26->main.py->bot.bot->bot.bot_main" in patched
    assert "STARTUP_HANDOFF_RUNTIME_EXIT" in patched


def test_repository_start_script_uses_canonical_entrypoint_diagnostics() -> None:
    module = _load_patcher()
    source = START_SCRIPT.read_text(encoding="utf-8")
    patched = module.patch_text(source)

    assert source == patched

    export_pos = patched.index("export NIJA_DEFER_RUNTIME_SITE_HOOKS=1")
    first_python_candidates = [
        position
        for token in ("$PY ", '"${PY}" ', "${PY} ", "python3 ", "python ")
        if (position := patched.find(token)) >= 0
    ]
    assert first_python_candidates
    assert export_pos < min(first_python_candidates)
    assert patched.index("STARTUP_HANDOFF_ENTRYPOINT_ATTESTATION_COMPLETE") < patched.index(
        "NIJA_DEFER_RUNTIME_SITE_HOOKS=1 "
        "$PY -u scripts/canonical_runtime_launcher_v26.py"
    )
    assert "unset NIJA_DEFER_RUNTIME_SITE_HOOKS" not in patched
    assert "runtime_site_hooks=deferred" in patched
    assert "CANONICAL_ENTRYPOINT_DIAGNOSTICS" in patched
    assert "bot/canonical_broker_prebootstrap_v22.py" in patched
    assert "bot/stalled_writer_release_guard_v22.py" in patched
    assert "--- canonical bot/bot.py (head) ---" in patched
    assert "--- bot.py (head) ---" not in patched
    assert "py_compile ./main.py ./bot.py" not in patched
    assert "$PY -u main.py" not in source
    assert (
        "NIJA_DEFER_RUNTIME_SITE_HOOKS=1 "
        "$PY -u scripts/canonical_runtime_launcher_v26.py"
    ) in source


def test_patcher_is_idempotent() -> None:
    module = _load_patcher()
    first = module.patch_text(_startup_source())
    second = module.patch_text(first)

    assert second == first
    assert second.count("STARTUP_HANDOFF_PREFLIGHT_BEGIN") == 1
    assert second.count("STARTUP_HANDOFF_ENTRYPOINT_ATTESTATION_COMPLETE") == 1
    assert second.count("STARTUP_HANDOFF_RUNTIME_BEGIN") == 1


def test_patcher_rejects_missing_runtime_anchor() -> None:
    module = _load_patcher()
    source = (
        "#!/bin/bash\n"
        "set -e\n"
        "_validate_redis_url_or_exit\n"
        "_log_redis_lock_source_hint\n"
    )

    try:
        module.patch_text(source)
    except RuntimeError as exc:
        assert "runtime launch anchor" in str(exc)
    else:
        raise AssertionError("expected missing runtime anchor to fail closed")


def test_patcher_migrates_old_defer_unset_handoff() -> None:
    module = _load_patcher()
    current = module.patch_text(_startup_source())
    legacy = current.replace(
        "NIJA_DEFER_RUNTIME_SITE_HOOKS=1 "
        "$PY -u scripts/canonical_runtime_launcher_v26.py",
        "unset NIJA_DEFER_RUNTIME_SITE_HOOKS\n"
        "$PY -u scripts/canonical_runtime_launcher_v26.py",
        1,
    )

    migrated = module.patch_text(legacy)

    assert migrated == current
    assert "unset NIJA_DEFER_RUNTIME_SITE_HOOKS" not in migrated


def test_defer_guard_blocks_sitecustomize_and_usercustomize() -> None:
    spec = importlib.util.spec_from_file_location(
        "install_sitecustomize_defer_guard_test",
        DEFER_GUARD,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    content = module.guard_content("/app")

    assert 'sys.modules.setdefault("sitecustomize"' in content
    assert 'sys.modules.setdefault("usercustomize"' in content
    assert "NIJA_DEFER_RUNTIME_SITE_HOOKS" in content
