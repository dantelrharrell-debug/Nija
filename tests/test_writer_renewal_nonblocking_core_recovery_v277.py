"""Regression coverage for writer-renewal nonblocking core recovery v277.

The Redis writer renewal thread must never enter bot_main import/recovery work.
During startup it should return immediately while the normal registration
deadline remains authoritative. Once startup is complete it may dispatch the
existing canonical recovery routine, but only on a separate single-flight daemon
worker. Non-heartbeat callers retain the original synchronous behavior.
"""
from __future__ import annotations

import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock

import bot.stale_renewal_recovery_v40_patch as patch


class _Runtime:
    def __init__(self) -> None:
        self._generation = 77
        self._core_recovery_next_attempt_monotonic = 0.0
        self._heartbeat_thread = threading.current_thread()


def _install_loaded_bot_main(*, startup_complete: bool, shutdown: bool = False):
    previous = sys.modules.get("bot.bot_main")
    module = SimpleNamespace(
        _startup_complete=startup_complete,
        _shutdown_event=SimpleNamespace(is_set=lambda: shutdown),
    )
    sys.modules["bot.bot_main"] = module
    return previous


def _restore_bot_main(previous) -> None:
    if previous is None:
        sys.modules.pop("bot.bot_main", None)
    else:
        sys.modules["bot.bot_main"] = previous


def test_heartbeat_startup_incomplete_returns_without_original_recovery() -> None:
    runtime = _Runtime()
    original = Mock(return_value=(True, "should_not_run"))

    class Probe:
        _recover_core_thread_registration = original

    assert patch._patch_nonblocking_core_recovery(Probe)
    previous = _install_loaded_bot_main(startup_complete=False)
    try:
        ok, detail = Probe._recover_core_thread_registration(runtime, "heartbeat")
    finally:
        _restore_bot_main(previous)

    assert ok is False
    assert detail == "startup_not_complete"
    original.assert_not_called()


def test_heartbeat_missing_bot_main_does_not_import_or_recover() -> None:
    runtime = _Runtime()
    original = Mock(return_value=(True, "should_not_run"))

    class Probe:
        _recover_core_thread_registration = original

    assert patch._patch_nonblocking_core_recovery(Probe)
    previous = sys.modules.pop("bot.bot_main", None)
    try:
        ok, detail = Probe._recover_core_thread_registration(runtime, "heartbeat")
    finally:
        if previous is not None:
            sys.modules["bot.bot_main"] = previous

    assert ok is False
    assert detail == "startup_module_not_loaded"
    original.assert_not_called()


def test_nonheartbeat_caller_keeps_original_synchronous_behavior() -> None:
    runtime = _Runtime()
    runtime._heartbeat_thread = object()
    original = Mock(return_value=(True, "original_path"))

    class Probe:
        _recover_core_thread_registration = original

    assert patch._patch_nonblocking_core_recovery(Probe)
    result = Probe._recover_core_thread_registration(runtime, "manual")

    assert result == (True, "original_path")
    original.assert_called_once_with(runtime, "manual")


def test_startup_complete_dispatches_original_off_heartbeat_thread_single_flight() -> None:
    runtime = _Runtime()
    entered = threading.Event()
    release = threading.Event()
    completed = threading.Event()
    worker_names: list[str] = []

    def original(self, source):
        worker_names.append(threading.current_thread().name)
        entered.set()
        release.wait(timeout=2.0)
        completed.set()
        return True, "recovered"

    class Probe:
        _recover_core_thread_registration = original

    assert patch._patch_nonblocking_core_recovery(Probe)
    previous = _install_loaded_bot_main(startup_complete=True)
    try:
        first = Probe._recover_core_thread_registration(runtime, "heartbeat")
        assert first == (False, "recovery_dispatched")
        assert entered.wait(timeout=1.0)

        second = Probe._recover_core_thread_registration(runtime, "heartbeat")
        assert second == (False, "recovery_in_flight")

        release.set()
        assert completed.wait(timeout=1.0)
    finally:
        release.set()
        _restore_bot_main(previous)

    assert len(worker_names) == 1
    assert worker_names[0].startswith("writer-core-registration-recovery-v277-g77")
    assert worker_names[0] != threading.current_thread().name


def test_heartbeat_shutdown_remains_fail_closed_without_recovery() -> None:
    runtime = _Runtime()
    original = Mock(return_value=(True, "should_not_run"))

    class Probe:
        _recover_core_thread_registration = original

    assert patch._patch_nonblocking_core_recovery(Probe)
    previous = _install_loaded_bot_main(startup_complete=True, shutdown=True)
    try:
        ok, detail = Probe._recover_core_thread_registration(runtime, "heartbeat")
    finally:
        _restore_bot_main(previous)

    assert ok is False
    assert detail == "shutdown_requested"
    original.assert_not_called()
