from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PATCHER = ROOT / "scripts" / "apply_startup_handoff_fix.py"
DOCKERFILE = ROOT / "Dockerfile"


def _load_patcher():
    spec = importlib.util.spec_from_file_location("apply_startup_handoff_fix", PATCHER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_patcher_defers_hooks_until_main_runtime() -> None:
    module = _load_patcher()
    source = (
        "_validate_redis_url_or_exit\n"
        "_log_redis_lock_source_hint\n"
        "set +e\n"
        "$PY -u main.py\n"
        "status=$?\n"
    )
    patched = module.patch_text(source)
    assert "export NIJA_DEFER_RUNTIME_SITE_HOOKS=1" in patched
    assert "STARTUP_HANDOFF_PREFLIGHT_BEGIN" in patched
    assert "STARTUP_HANDOFF_REDIS_VALIDATION_COMPLETE" in patched
    assert "unset NIJA_DEFER_RUNTIME_SITE_HOOKS" in patched
    assert "STARTUP_HANDOFF_RUNTIME_BEGIN" in patched
    assert patched.index("unset NIJA_DEFER_RUNTIME_SITE_HOOKS") < patched.index("$PY -u main.py")


def test_docker_pth_hooks_respect_defer_flag() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "NIJA_DEFER_RUNTIME_SITE_HOOKS" in text
    assert "apply_startup_handoff_fix.py" in text
    assert "python -S /app/scripts/apply_startup_handoff_fix.py" in text
    assert "bash -n /app/start.sh" in text
    for name in (
        "prebot_writer_authority_fail_closed",
        "critical_runtime_repairs_v10",
        "exit_protection_assurance_patch",
    ):
        assert name in text
