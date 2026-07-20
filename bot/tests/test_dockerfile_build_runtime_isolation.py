from pathlib import Path


def test_docker_build_does_not_import_runtime_patch_modules() -> None:
    dockerfile = Path(__file__).resolve().parents[2] / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")

    assert "NIJA_BUILD_MODULE_PRESENCE_OK" in text
    assert "RUN python -S -c" in text
    assert "NIJA_PTH_IMPORT_SMOKE_OK" not in text

    forbidden = (
        'RUN cd /tmp && python -c "import prebot_writer_authority_fail_closed',
        'import critical_runtime_repairs_v10, bot.position_cost_basis_entry_lock_patch',
    )
    for marker in forbidden:
        assert marker not in text
