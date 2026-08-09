from __future__ import annotations

import importlib.util
import sys
import threading
from pathlib import Path


PATCH_PATH = Path(__file__).resolve().parents[1] / "execution_bootstrap_monitor_iteration_guard_patch.py"


def _load_patch(name: str = "writer_scan_deadline_lease_guard_v61_patch"):
    spec = importlib.util.spec_from_file_location(name, PATCH_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


class _AliveThread:
    def is_alive(self) -> bool:
        return True


class _DeadThread:
    def is_alive(self) -> bool:
        return False


class _Runtime:
    def __init__(self) -> None:
        self._core_thread = None
        self._scan_deadline_exceeded = False
        self._scan_started_at = 0.0

    def _validate_core_thread_liveness(self):
        thread = self._core_thread
        if thread is None:
            if self._scan_deadline_exceeded and not self._scan_started_at:
                return False, "core_thread_missing_deadline_exceeded"
            return True, ""
        if not thread.is_alive():
            return False, "core_thread_dead"
        return True, ""


class _WriterModule:
    __name__ = "fake_entrypoint_writer_authority_v61"
    EntrypointWriterAuthority = _Runtime


def test_scan_deadline_is_warning_only_before_core_thread_registration():
    patch = _load_patch("v61_scan_deadline_warning_only")
    module = _WriterModule()

    assert patch._patch_writer_module(module) is True

    runtime = module.EntrypointWriterAuthority()
    runtime._scan_deadline_exceeded = True
    runtime._scan_started_at = 0.0
    runtime._core_thread = None

    ok, reason = runtime._validate_core_thread_liveness()

    assert ok is True
    assert reason == "scan_start_deadline_warning_only"


def test_registered_dead_core_thread_remains_fail_closed():
    patch = _load_patch("v61_dead_core_still_fails")
    module = _WriterModule()

    # Rebuild an unpatched class because the prior test patches class methods in-place.
    class Runtime:
        def __init__(self) -> None:
            self._core_thread = None
            self._scan_deadline_exceeded = False
            self._scan_started_at = 0.0

        def _validate_core_thread_liveness(self):
            thread = self._core_thread
            if thread is None:
                if self._scan_deadline_exceeded and not self._scan_started_at:
                    return False, "core_thread_missing_deadline_exceeded"
                return True, ""
            if not thread.is_alive():
                return False, "core_thread_dead"
            return True, ""

    module.EntrypointWriterAuthority = Runtime
    assert patch._patch_writer_module(module) is True

    runtime = module.EntrypointWriterAuthority()
    runtime._core_thread = _DeadThread()
    runtime._scan_deadline_exceeded = True

    ok, reason = runtime._validate_core_thread_liveness()

    assert ok is False
    assert reason == "core_thread_dead"


def test_registered_live_core_thread_remains_healthy():
    patch = _load_patch("v61_live_core_healthy")
    module = _WriterModule()

    class Runtime:
        def __init__(self) -> None:
            self._core_thread = _AliveThread()
            self._scan_deadline_exceeded = True
            self._scan_started_at = 0.0

        def _validate_core_thread_liveness(self):
            if not self._core_thread.is_alive():
                return False, "core_thread_dead"
            return True, ""

    module.EntrypointWriterAuthority = Runtime
    assert patch._patch_writer_module(module) is True

    runtime = module.EntrypointWriterAuthority()
    ok, reason = runtime._validate_core_thread_liveness()

    assert ok is True
    assert reason == ""
