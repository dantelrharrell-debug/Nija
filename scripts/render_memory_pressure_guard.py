"""Render-only memory pressure trimming for the canonical NIJA process.

The guard never changes trading state. It observes the container's cgroup usage
and, only above a configured threshold, asks Python to collect unreachable
cycles and glibc to return free heap pages to the kernel. This creates headroom
for transient strategy-import and scan allocations on a 512 MiB worker.
"""
from __future__ import annotations

import gc
import logging
import os
import threading
import time
from pathlib import Path
from typing import Callable, Optional


LOGGER = logging.getLogger("nija.render_memory_pressure_guard_v151")
MARKER = "20260818-render-memory-pressure-guard-v151"
_TRUE = {"1", "true", "yes", "on", "enabled", "y"}
_LOCK = threading.Lock()
_THREAD: Optional[threading.Thread] = None


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in _TRUE


def _is_render_runtime() -> bool:
    if _truthy(os.environ.get("RENDER")):
        return True
    return any(
        str(os.environ.get(name, "") or "").strip()
        for name in (
            "RENDER_SERVICE_ID",
            "RENDER_SERVICE_NAME",
            "RENDER_INSTANCE_ID",
            "RENDER_GIT_COMMIT",
        )
    )


def _bounded_float(name: str, default: float, minimum: float, maximum: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(maximum, value))


def _memory_pressure(cgroup_root: Path = Path("/sys/fs/cgroup")) -> Optional[tuple[int, int, float]]:
    try:
        current = int((cgroup_root / "memory.current").read_text(encoding="utf-8").strip())
        maximum_raw = (cgroup_root / "memory.max").read_text(encoding="utf-8").strip()
        if maximum_raw == "max":
            return None
        maximum = int(maximum_raw)
    except (FileNotFoundError, PermissionError, OSError, TypeError, ValueError):
        return None
    if current < 0 or maximum <= 0:
        return None
    return current, maximum, current / maximum


def _trim_memory(
    *,
    collect: Optional[Callable[[], int]] = None,
    trim: Optional[Callable[[int], int]] = None,
) -> tuple[int, bool]:
    collector = collect or gc.collect
    collected = int(collector())
    trimmed = False
    try:
        if trim is None:
            import ctypes

            candidate = getattr(ctypes.CDLL(None), "malloc_trim", None)
            trim = candidate if callable(candidate) else None
        if trim is not None:
            trimmed = bool(trim(0))
    except Exception:
        LOGGER.debug("RENDER_MEMORY_TRIM_UNAVAILABLE marker=%s", MARKER, exc_info=True)
    return collected, trimmed


def _guard_loop() -> None:
    threshold = _bounded_float("NIJA_RENDER_MEMORY_TRIM_THRESHOLD", 0.72, 0.50, 0.95)
    interval_s = _bounded_float("NIJA_RENDER_MEMORY_GUARD_INTERVAL_S", 5.0, 2.0, 60.0)
    minimum_gap_s = _bounded_float("NIJA_RENDER_MEMORY_TRIM_MIN_GAP_S", 10.0, 2.0, 120.0)
    last_trim = 0.0
    while True:
        pressure = _memory_pressure()
        now = time.monotonic()
        if pressure is not None and pressure[2] >= threshold and now - last_trim >= minimum_gap_s:
            current, maximum, utilization = pressure
            collected, trimmed = _trim_memory()
            last_trim = now
            after = _memory_pressure()
            after_current = after[0] if after is not None else current
            LOGGER.warning(
                "RENDER_MEMORY_PRESSURE_TRIM marker=%s before_mb=%.2f after_mb=%.2f "
                "limit_mb=%.2f utilization=%.3f collected=%d malloc_trim=%s "
                "trading_state_unchanged=true authority_gates_unchanged=true",
                MARKER,
                current / (1024 * 1024),
                after_current / (1024 * 1024),
                maximum / (1024 * 1024),
                utilization,
                collected,
                str(trimmed).lower(),
            )
        time.sleep(interval_s)


def start() -> bool:
    """Start the Render-only daemon once; return whether it is active."""
    global _THREAD
    if not _is_render_runtime():
        return False
    with _LOCK:
        if _THREAD is not None and _THREAD.is_alive():
            return True
        thread = threading.Thread(
            target=_guard_loop,
            name="RenderMemoryPressureGuardV151",
            daemon=True,
        )
        _THREAD = thread
        thread.start()
    os.environ["NIJA_RENDER_MEMORY_PRESSURE_GUARD_V151_READY"] = "1"
    LOGGER.warning(
        "RENDER_MEMORY_PRESSURE_GUARD_STARTED marker=%s threshold=%.3f interval_s=%.1f "
        "trading_state_unchanged=true authority_gates_unchanged=true",
        MARKER,
        _bounded_float("NIJA_RENDER_MEMORY_TRIM_THRESHOLD", 0.72, 0.50, 0.95),
        _bounded_float("NIJA_RENDER_MEMORY_GUARD_INTERVAL_S", 5.0, 2.0, 60.0),
    )
    return True


__all__ = ["MARKER", "start", "_memory_pressure", "_trim_memory"]
