from __future__ import annotations

import importlib.util
import os
from pathlib import Path
from tempfile import TemporaryDirectory


ROOT = Path(__file__).resolve().parents[2]
GUARD_PATH = ROOT / "scripts" / "render_memory_pressure_guard.py"
LAUNCHER_PATH = ROOT / "scripts" / "canonical_runtime_launcher_v26.py"
DOCKERIGNORE_PATH = ROOT / ".dockerignore"
DOCKERFILE_PATH = ROOT / "Dockerfile"


def _load_guard():
    spec = importlib.util.spec_from_file_location("test_render_memory_guard_v151", GUARD_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_memory_pressure_reads_finite_cgroup_limit() -> None:
    guard = _load_guard()
    with TemporaryDirectory() as directory:
        root = Path(directory)
        (root / "memory.current").write_text(str(384 * 1024 * 1024), encoding="utf-8")
        (root / "memory.max").write_text(str(512 * 1024 * 1024), encoding="utf-8")

        current, maximum, utilization = guard._memory_pressure(root)

    assert current == 384 * 1024 * 1024
    assert maximum == 512 * 1024 * 1024
    assert utilization == 0.75


def test_memory_trim_collects_and_returns_heap_pages() -> None:
    guard = _load_guard()
    calls: list[int] = []

    collected, trimmed = guard._trim_memory(
        collect=lambda: 7,
        trim=lambda padding: calls.append(padding) or 1,
    )

    assert collected == 7
    assert trimmed is True
    assert calls == [0]


def test_non_render_runtime_does_not_start_guard() -> None:
    guard = _load_guard()
    names = (
        "RENDER",
        "RENDER_SERVICE_ID",
        "RENDER_SERVICE_NAME",
        "RENDER_INSTANCE_ID",
        "RENDER_GIT_COMMIT",
    )
    previous = {name: os.environ.pop(name, None) for name in names}
    try:
        assert guard.start() is False
        assert guard._THREAD is None
    finally:
        for name, value in previous.items():
            if value is not None:
                os.environ[name] = value


def test_launcher_starts_guard_before_bot_package_imports() -> None:
    source = LAUNCHER_PATH.read_text(encoding="utf-8")
    main_block = source[source.index("def main() -> int:") :]

    assert main_block.index("_start_render_memory_pressure_guard()") < main_block.index(
        "install_canonical_startup_guard()"
    )
    assert "RENDER_MEMORY_GUARD_PATH.is_file()" in source
    assert "NIJA_RENDER_MEMORY_PRESSURE_GUARD_V151_READY" in source


def test_render_image_packages_and_validates_memory_guard() -> None:
    dockerignore = DOCKERIGNORE_PATH.read_text(encoding="utf-8")
    dockerfile = DOCKERFILE_PATH.read_text(encoding="utf-8")

    assert "!scripts/render_memory_pressure_guard.py" in dockerignore
    assert "/app/scripts/render_memory_pressure_guard.py" in dockerfile
    assert "test -f /app/scripts/render_memory_pressure_guard.py" in dockerfile
