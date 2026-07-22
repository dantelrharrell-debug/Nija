from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PATCHER = ROOT / "scripts" / "apply_startup_handoff_fix.py"
START_SCRIPT = ROOT / "start.sh"


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
    unset_pos = patched.index("unset NIJA_DEFER_RUNTIME_SITE_HOOKS")
    main_pos = patched.index("$PY -u main.py")

    assert export_pos < first_python_pos
    assert export_pos < unset_pos < main_pos
    assert "STARTUP_HANDOFF_PREFLIGHT_BEGIN" in patched
    assert "STARTUP_HANDOFF_REDIS_VALIDATION_COMPLETE" in patched
    assert "STARTUP_HANDOFF_RUNTIME_BEGIN" in patched
    assert "STARTUP_HANDOFF_RUNTIME_EXIT" in patched


def test_repository_start_script_gets_early_defer() -> None:
    module = _load_patcher()
    source = START_SCRIPT.read_text(encoding="utf-8")
    patched = module.patch_text(source)

    export_pos = patched.index("export NIJA_DEFER_RUNTIME_SITE_HOOKS=1")
    first_python_candidates = [
        position
        for token in ("$PY ", '"${PY}" ', "${PY} ", "python3 ", "python ")
        if (position := patched.find(token)) >= 0
    ]
    assert first_python_candidates
    assert export_pos < min(first_python_candidates)
    assert patched.index("unset NIJA_DEFER_RUNTIME_SITE_HOOKS") < patched.index("$PY -u main.py")


def test_patcher_is_idempotent() -> None:
    module = _load_patcher()
    first = module.patch_text(_startup_source())
    second = module.patch_text(first)

    assert second == first
    assert second.count("STARTUP_HANDOFF_PREFLIGHT_BEGIN") == 1
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
