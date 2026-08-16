from pathlib import Path


def _patcher_source() -> str:
    root = Path(__file__).resolve().parents[2]
    return (root / "scripts" / "apply_writer_generation_handoff_v45.py").read_text(encoding="utf-8")


def test_v112_does_not_rewrite_launcher_version_markers():
    source = _patcher_source()
    assert '20260807-canonical-runtime-launcher-v26-v44-v43-v42-v41-v40-v39-v38-v37-v18' not in source
    assert 'CANONICAL_ENTRYPOINT_FAST_PATH_ARMED marker=20260807' not in source
    assert 'version_marker_preserved=true' in source


def test_v112_structurally_wires_writer_generation_modules():
    source = _patcher_source()
    assert 'V45_PATH = ROOT / "bot" / "writer_generation_handoff_v45_patch.py"' in source
    assert 'V47_PATH = ROOT / "bot" / "writer_generation_idempotence_v47_patch.py"' in source
    assert 'V48_PATH = ROOT / "bot" / "writer_lost_epoch_v48_patch.py"' in source
    assert 'V49_PATH = ROOT / "bot" / "writer_recovery_monitor_cleanup_v49_patch.py"' in source
    assert '_install_writer_generation_handoff_v45()' in source
    assert '_install_writer_generation_idempotence_v47()' in source
    assert '_install_writer_lost_epoch_v48()' in source
    assert '_install_writer_recovery_monitor_cleanup_v49()' in source


def test_v112_compiles_launcher_after_patch():
    source = _patcher_source()
    assert 'py_compile.compile(str(LAUNCHER), doraise=True)' in source
