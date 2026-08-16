from __future__ import annotations

import os
import threading
import time
import types

import pytest

from bot import position_fetch_generation_v117_patch as v117


def setup_function() -> None:
    with v117._LOCK:
        v117._FLIGHTS.clear()
        v117._GENERATIONS.clear()


def test_stale_generation_is_superseded_and_late_result_discarded(monkeypatch):
    monkeypatch.setenv("NIJA_POSITION_FETCH_TIMEOUT_S", "0.05")
    monkeypatch.setenv("NIJA_POSITION_FETCH_STALE_GENERATION_S", "0.08")

    calls = []
    release_first = threading.Event()

    def raw(self):
        calls.append(time.monotonic())
        if len(calls) == 1:
            release_first.wait(timeout=1.0)
            return [{"symbol": "STALE"}]
        return [{"symbol": "FRESH"}]

    wrapped = v117._bounded_generation(raw, "kraken")
    broker = object()

    with pytest.raises(TimeoutError):
        wrapped(broker)

    time.sleep(0.09)
    fresh = wrapped(broker)
    assert fresh == [{"symbol": "FRESH"}]
    assert len(calls) == 2

    release_first.set()
    time.sleep(0.02)
    assert v117._GENERATIONS[id(broker)] == 2


def test_supervised_pending_allows_threads_starting_only_with_exact_writer(monkeypatch):
    monkeypatch.setattr(v117, "_bootstrap_state", lambda: "THREADS_STARTING")
    monkeypatch.setattr(v117, "_writer_core_healthy", lambda runtime, thread: True)

    class Thread:
        def is_alive(self):
            return True

    runtime = object()
    thread = Thread()

    original = lambda runtime, thread, *args, **kwargs: False
    fake_module = types.SimpleNamespace(_perform_post_core_activation_convergence=original)
    monkeypatch.setattr(v117, "_loaded", lambda *names: fake_module if "bot.bot_main" in names else None)

    assert v117._patch_bot_main() is True
    assert fake_module._perform_post_core_activation_convergence(runtime, thread) is True
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert os.environ["NIJA_EXECUTION_ACTIVE"] == "false"


def test_supervised_pending_does_not_mask_unhealthy_writer(monkeypatch):
    monkeypatch.setattr(v117, "_bootstrap_state", lambda: "THREADS_STARTING")
    monkeypatch.setattr(v117, "_writer_core_healthy", lambda runtime, thread: False)

    class Thread:
        def is_alive(self):
            return True

    runtime = object()
    thread = Thread()
    original = lambda runtime, thread, *args, **kwargs: False
    fake_module = types.SimpleNamespace(_perform_post_core_activation_convergence=original)
    monkeypatch.setattr(v117, "_loaded", lambda *names: fake_module if "bot.bot_main" in names else None)

    assert v117._patch_bot_main() is True
    assert fake_module._perform_post_core_activation_convergence(runtime, thread) is False
