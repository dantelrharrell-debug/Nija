from __future__ import annotations

from pathlib import Path


def _dockerfile() -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / "Dockerfile").read_text(encoding="utf-8")


def test_docker_pth_hooks_add_app_and_honor_defer_flag() -> None:
    dockerfile = _dockerfile()

    assert "prefix = '/app\\n'" in dockerfile
    assert 'NIJA_DEFER_RUNTIME_SITE_HOOKS\\", \\"0\\") != \\"1\\" and ' in dockerfile

    expected_hooks = (
        ("000_nija_prebot_writer_authority.pth", "prebot_writer_authority_fail_closed"),
        ("nija_import_hook_recursion_shield.pth", "import_hook_recursion_shield_patch"),
        ("nija_disconnected_broker_execution_guard.pth", "disconnected_broker_execution_guard_patch"),
        ("0009_nija_critical_runtime_repairs_v10.pth", "critical_runtime_repairs_v10"),
        ("0010_nija_exit_protection_assurance.pth", "exit_protection_assurance_patch"),
    )

    for filename, module_name in expected_hooks:
        assert filename in dockerfile
        assert f'__import__(\\"{module_name}\\")' in dockerfile


def test_docker_applies_both_defer_guards_before_runtime_hooks() -> None:
    dockerfile = _dockerfile()

    package_patch = dockerfile.index("python -S /app/apply_bot_package_defer_fix.py")
    handoff_patch = dockerfile.index("python -S /app/scripts/apply_startup_handoff_fix.py")
    pth_install = dockerfile.index("000_nija_prebot_writer_authority.pth")

    assert package_patch < handoff_patch < pth_install
    assert "install(defer_if_render=True)" in dockerfile
    assert "bash -n /app/start.sh" in dockerfile


def test_docker_validates_module_presence_without_starting_runtime_hooks() -> None:
    dockerfile = _dockerfile()

    assert "RUN cd /tmp && python -c" not in dockerfile
    assert "NIJA_PTH_IMPORT_SMOKE_OK" not in dockerfile
    assert "python -S -c \"import pathlib; required =" in dockerfile
    assert "NIJA_BUILD_MODULE_PRESENCE_OK" in dockerfile
    assert "pathlib.Path('/app/apply_bot_package_defer_fix.py')" in dockerfile
    assert "pathlib.Path('/app/exit_protection_assurance_patch.py')" in dockerfile
