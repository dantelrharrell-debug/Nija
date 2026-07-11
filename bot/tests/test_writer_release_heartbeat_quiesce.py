from __future__ import annotations

import importlib
import os
import threading
import time
from types import ModuleType


def _module():
    return importlib.import_module("bot.writer_lock_release_guard")


def test_quiesce_runtime_stops_and_joins_heartbeat() -> None:
    module = _module()

    class Runtime:
        def __init__(self) -> None:
            self._stop = threading.Event()
            self._heartbeat_thread = threading.Thread(target=self._loop, daemon=True)

        def _loop(self) -> None:
            while not self._stop.wait(0.01):
                pass

    runtime = Runtime()
    runtime._heartbeat_thread.start()
    assert runtime._heartbeat_thread.is_alive()

    ok, reason = module._quiesce_runtime(runtime, timeout_s=1.0)

    assert ok is True
    assert reason == "heartbeat_quiesced"
    assert runtime._stop.is_set()
    assert not runtime._heartbeat_thread.is_alive()


def test_patched_canonical_release_joins_before_original_delete(monkeypatch) -> None:
    module = _module()
    fake_module = ModuleType("bot.entrypoint_writer_authority_test_double")

    class Authority:
        def __init__(self) -> None:
            self._stop = threading.Event()
            self.release_observed_thread_alive = None
            self._heartbeat_thread = threading.Thread(target=self._loop, daemon=True)
            self._heartbeat_thread.start()

        def _loop(self) -> None:
            while not self._stop.wait(0.01):
                pass

        def _heartbeat_tick(self):
            return True, ""

        def release(self) -> bool:
            self.release_observed_thread_alive = self._heartbeat_thread.is_alive()
            return True

    fake_module.EntrypointWriterAuthority = Authority
    monkeypatch.delenv("NIJA_WRITER_RELEASE_IN_PROGRESS", raising=False)

    assert module._patch_entrypoint_authority_module(fake_module) is True
    runtime = Authority()
    assert runtime.release() is True
    assert runtime.release_observed_thread_alive is False
    assert os.environ["NIJA_WRITER_RELEASE_IN_PROGRESS"] == "1"


def test_patched_heartbeat_refuses_tick_during_release(monkeypatch) -> None:
    module = _module()
    fake_module = ModuleType("bot.entrypoint_writer_authority_tick_double")

    class Authority:
        def __init__(self) -> None:
            self._stop = threading.Event()
            self._heartbeat_thread = None
            self.tick_calls = 0

        def _heartbeat_tick(self):
            self.tick_calls += 1
            return True, ""

        def release(self) -> bool:
            return True

    fake_module.EntrypointWriterAuthority = Authority
    assert module._patch_entrypoint_authority_module(fake_module) is True

    runtime = Authority()
    monkeypatch.setenv("NIJA_WRITER_RELEASE_IN_PROGRESS", "1")
    assert runtime._heartbeat_tick() == (False, "release_in_progress")
    assert runtime.tick_calls == 0


def test_release_guard_source_requires_heartbeat_quiescence() -> None:
    module = _module()
    source = open(module.__file__, encoding="utf-8").read()

    assert "_quiesce_local_writer_runtime" in source
    assert "heartbeat_thread_still_alive" in source
    assert "lock_delete_skipped=true" in source
    assert "heartbeat_quiesced=true" in source
