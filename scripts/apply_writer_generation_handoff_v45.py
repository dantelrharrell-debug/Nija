#!/usr/bin/env python3
"""Idempotently wire writer-generation v45/v47/v48/v49 into canonical launcher v26.

v112 intentionally avoids rewriting launcher version markers. The canonical
launcher changes independently (v110/v111 and future revisions), so build-time
patching must key off stable structural anchors and attest the actual safety
wiring rather than a historical marker string.
"""
from __future__ import annotations

from pathlib import Path
import py_compile

ROOT = Path(__file__).resolve().parents[1]
LAUNCHER = ROOT / "scripts" / "canonical_runtime_launcher_v26.py"
V47 = ROOT / "bot" / "writer_generation_idempotence_v47_patch.py"
V48 = ROOT / "bot" / "writer_lost_epoch_v48_patch.py"
V49 = ROOT / "bot" / "writer_recovery_monitor_cleanup_v49_patch.py"
MARKER = "20260816-writer-generation-launcher-patcher-v112"


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"writer generation launcher patch anchor missing: {label}")
    return text.replace(old, new, 1)


def _wire_launcher(text: str) -> str:
    """Ensure writer-generation safety modules are structurally wired once."""
    text = _replace_once(
        text,
        'V44_PATH = ROOT / "bot" / "kraken_connection_convergence_v44_patch.py"\nV18_PATH',
        'V44_PATH = ROOT / "bot" / "kraken_connection_convergence_v44_patch.py"\n'
        'V45_PATH = ROOT / "bot" / "writer_generation_handoff_v45_patch.py"\n'
        'V47_PATH = ROOT / "bot" / "writer_generation_idempotence_v47_patch.py"\n'
        'V48_PATH = ROOT / "bot" / "writer_lost_epoch_v48_patch.py"\n'
        'V49_PATH = ROOT / "bot" / "writer_recovery_monitor_cleanup_v49_patch.py"\n'
        'V18_PATH',
        "v45/v47/v48/v49 paths",
    )

    functions = '''\n\ndef _install_writer_generation_handoff_v45() -> ModuleType:\n    if not V45_PATH.is_file():\n        raise RuntimeError(f"writer generation handoff v45 missing: {V45_PATH}")\n    module = _load_module_by_path("nija_writer_generation_handoff_v45_prebot", V45_PATH)\n    installer: Any = getattr(module, "install_import_hook", None) or getattr(module, "install", None)\n    if not callable(installer) or not bool(installer()):\n        raise RuntimeError("writer generation handoff v45 installer failed")\n    if os.environ.get("NIJA_WRITER_GENERATION_HANDOFF_V45_INSTALLED") != "1":\n        raise RuntimeError("writer generation handoff v45 did not attest installed")\n    return module\n\n\ndef _install_writer_generation_idempotence_v47() -> ModuleType:\n    if not V47_PATH.is_file():\n        raise RuntimeError(f"writer generation idempotence v47 missing: {V47_PATH}")\n    module = _load_module_by_path("nija_writer_generation_idempotence_v47_prebot", V47_PATH)\n    installer: Any = getattr(module, "install_import_hook", None) or getattr(module, "install", None)\n    if not callable(installer) or not bool(installer()):\n        raise RuntimeError("writer generation idempotence v47 installer failed")\n    if os.environ.get("NIJA_WRITER_GENERATION_IDEMPOTENCE_V47_INSTALLED") != "1":\n        raise RuntimeError("writer generation idempotence v47 did not attest installed")\n    return module\n\n\ndef _install_writer_lost_epoch_v48() -> ModuleType:\n    if not V48_PATH.is_file():\n        raise RuntimeError(f"writer lost epoch v48 missing: {V48_PATH}")\n    module = _load_module_by_path("nija_writer_lost_epoch_v48_prebot", V48_PATH)\n    installer: Any = getattr(module, "install_import_hook", None) or getattr(module, "install", None)\n    if not callable(installer) or not bool(installer()):\n        raise RuntimeError("writer lost epoch v48 installer failed")\n    if os.environ.get("NIJA_WRITER_LOST_EPOCH_V48_INSTALLED") != "1":\n        raise RuntimeError("writer lost epoch v48 did not attest installed")\n    return module\n\n\ndef _install_writer_recovery_monitor_cleanup_v49() -> ModuleType:\n    if not V49_PATH.is_file():\n        raise RuntimeError(f"writer recovery monitor cleanup v49 missing: {V49_PATH}")\n    module = _load_module_by_path("nija_writer_recovery_monitor_cleanup_v49_prebot", V49_PATH)\n    installer: Any = getattr(module, "install_import_hook", None) or getattr(module, "install", None)\n    if not callable(installer) or not bool(installer()):\n        raise RuntimeError("writer recovery monitor cleanup v49 installer failed")\n    if os.environ.get("NIJA_WRITER_RECOVERY_MONITOR_CLEANUP_V49_INSTALLED") != "1":\n        raise RuntimeError("writer recovery monitor cleanup v49 did not attest installed")\n    return module\n'''
    text = _replace_once(
        text,
        '\n\ndef _install_production_corrective_set() -> ModuleType:',
        functions + '\n\ndef _install_production_corrective_set() -> ModuleType:',
        "v45/v47/v48/v49 installer functions",
    )
    text = _replace_once(
        text,
        '    _install_runtime_execution_convergence()\n',
        '    _install_writer_generation_handoff_v45()\n'
        '    _install_writer_generation_idempotence_v47()\n'
        '    _install_writer_lost_epoch_v48()\n'
        '    _install_writer_recovery_monitor_cleanup_v49()\n'
        '    _install_runtime_execution_convergence()\n',
        "v45/v47/v48/v49 install order",
    )
    return text


def apply() -> bool:
    for label, path in (("v47", V47), ("v48", V48), ("v49", V49)):
        if not path.is_file():
            raise RuntimeError(f"{label} runtime patch missing: {path}")
        py_compile.compile(str(path), doraise=True)

    text = LAUNCHER.read_text(encoding="utf-8")
    original = text
    text = _wire_launcher(text)

    if text != original:
        LAUNCHER.write_text(text, encoding="utf-8")

    required = (
        'V45_PATH = ROOT / "bot" / "writer_generation_handoff_v45_patch.py"',
        'V47_PATH = ROOT / "bot" / "writer_generation_idempotence_v47_patch.py"',
        'V48_PATH = ROOT / "bot" / "writer_lost_epoch_v48_patch.py"',
        'V49_PATH = ROOT / "bot" / "writer_recovery_monitor_cleanup_v49_patch.py"',
        'def _install_writer_generation_handoff_v45()',
        'def _install_writer_generation_idempotence_v47()',
        'def _install_writer_lost_epoch_v48()',
        'def _install_writer_recovery_monitor_cleanup_v49()',
        '    _install_writer_generation_handoff_v45()\n',
        '    _install_writer_generation_idempotence_v47()\n',
        '    _install_writer_lost_epoch_v48()\n',
        '    _install_writer_recovery_monitor_cleanup_v49()\n',
    )
    missing = [item for item in required if item not in text]
    if missing:
        raise RuntimeError("writer generation launcher attestation missing: " + ", ".join(missing))

    py_compile.compile(str(LAUNCHER), doraise=True)
    print(
        f"WRITER_GENERATION_V45_V47_V48_V49_LAUNCHER_PATCHED marker={MARKER} "
        "v45=true v47=true v48=true v49=true version_marker_preserved=true",
        flush=True,
    )
    return True


if __name__ == "__main__":
    apply()
