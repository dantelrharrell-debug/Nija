from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import render_liveness_server as server


def test_memory_snapshot_reports_cgroup_pressure_and_runtime_rss() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        cgroup = root / "cgroup"
        proc = root / "proc"
        runtime = proc / "321"
        cgroup.mkdir()
        runtime.mkdir(parents=True)

        (cgroup / "memory.current").write_text(str(384 * 1024 * 1024), encoding="utf-8")
        (cgroup / "memory.max").write_text(str(512 * 1024 * 1024), encoding="utf-8")
        (cgroup / "memory.peak").write_text(str(448 * 1024 * 1024), encoding="utf-8")
        (cgroup / "memory.events").write_text(
            "low 0\nhigh 3\nmax 9\noom 2\noom_kill 1\n",
            encoding="utf-8",
        )
        (runtime / "cmdline").write_bytes(
            b"python\0-u\0scripts/canonical_runtime_launcher_v26.py\0"
        )
        (runtime / "status").write_text(
            "Name:\tpython\nVmRSS:\t262144 kB\nThreads:\t17\n",
            encoding="utf-8",
        )

        details = server._memory_snapshot(cgroup, proc)

    assert details["memory_current_mb"] == 384.0
    assert details["memory_limit_mb"] == 512.0
    assert details["memory_peak_mb"] == 448.0
    assert details["memory_utilization_percent"] == 75.0
    assert details["memory_oom_count"] == 2
    assert details["memory_oom_kill_count"] == 1
    assert details["runtime_pid"] == 321
    assert details["runtime_rss_mb"] == 256.0
    assert details["runtime_threads"] == 17


def test_memory_snapshot_is_safe_when_cgroup_files_are_missing() -> None:
    with TemporaryDirectory() as directory:
        root = Path(directory)
        details = server._memory_snapshot(root / "missing-cgroup", root / "missing-proc")

    assert details["memory_current_mb"] is None
    assert details["memory_limit_mb"] is None
    assert details["memory_utilization_percent"] is None
    assert details["memory_oom_kill_count"] == 0
    assert "runtime_pid" not in details


def test_render_blueprint_bounds_native_memory_concurrency() -> None:
    source = (Path(__file__).resolve().parents[2] / "render.yaml").read_text(
        encoding="utf-8"
    )

    for name in (
        "OPENBLAS_NUM_THREADS",
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
    ):
        assert f"key: {name}\n        value: \"1\"" in source
    assert 'key: MALLOC_ARENA_MAX\n        value: "2"' in source
    assert 'key: MALLOC_TRIM_THRESHOLD_\n        value: "131072"' in source
