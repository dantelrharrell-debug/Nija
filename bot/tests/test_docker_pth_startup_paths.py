from __future__ import annotations

from pathlib import Path


def test_docker_pth_hooks_add_app_before_importing_modules() -> None:
    root = Path(__file__).resolve().parents[2]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")

    assert "prefix = '/app\\n'" in dockerfile

    expected_hooks = (
        ("000_nija_prebot_writer_authority.pth", "prebot_writer_authority_fail_closed"),
        ("nija_import_hook_recursion_shield.pth", "import_hook_recursion_shield_patch"),
        ("nija_disconnected_broker_execution_guard.pth", "disconnected_broker_execution_guard_patch"),
    )

    for filename, module_name in expected_hooks:
        assert filename in dockerfile
        assert f"prefix + 'import {module_name}" in dockerfile


def test_render_pth_defers_writer_wait_until_source_bootstrap() -> None:
    root = Path(__file__).resolve().parents[2]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")

    assert "_nija_prebot_writer.install(defer_if_render=True)" in dockerfile
    assert "source_runtime_guard_bootstrap acquires the same canonical" in dockerfile


def test_docker_runs_site_import_smoke_test_outside_app() -> None:
    root = Path(__file__).resolve().parents[2]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")

    assert "RUN cd /tmp && python -c" in dockerfile
    assert "NIJA_PTH_IMPORT_SMOKE_OK" in dockerfile
    assert "prebot_writer_authority_fail_closed" in dockerfile
    assert "import_hook_recursion_shield_patch" in dockerfile
    assert "disconnected_broker_execution_guard_patch" in dockerfile
