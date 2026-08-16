from __future__ import annotations

import os
import threading
import types

from bot import core_supervised_pending_v120_patch as v120


def test_supervised_pending_return_requires_exact_writer(monkeypatch):
    ready = threading.Event()
    fake_core = types.SimpleNamespace(TRADING_ENGINE_READY=ready)

    monkeypatch.delenv("NIJA_PROCESS_EXIT_REQUESTED", raising=False)
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")
    monkeypatch.setattr(v120, "_shutdown_requested", lambda: False)
    monkeypatch.setattr(v120, "_bootstrap_state", lambda: "RUNNING_SUPERVISED")
    monkeypatch.setattr(v120, "_writer_proof", lambda: (True, "exact_redis_process_writer", 42))

    allowed, reason, generation, state = v120._supervised_pending_return_allowed(fake_core)
    assert allowed is True
    assert reason == "supervised_activation_pending"
    assert generation == 42
    assert state == "RUNNING_SUPERVISED"


def test_supervised_pending_return_rejects_writer_loss(monkeypatch):
    ready = threading.Event()
    fake_core = types.SimpleNamespace(TRADING_ENGINE_READY=ready)

    monkeypatch.setattr(v120, "_shutdown_requested", lambda: False)
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")
    monkeypatch.setattr(v120, "_bootstrap_state", lambda: "RUNNING_SUPERVISED")
    monkeypatch.setattr(v120, "_writer_proof", lambda: (False, "writer_lock_missing", 0))

    allowed, reason, generation, state = v120._supervised_pending_return_allowed(fake_core)
    assert allowed is False
    assert reason == "writer_lock_missing"
    assert generation == 0
    assert state == "RUNNING_SUPERVISED"


def test_core_wrapper_keeps_execution_fail_closed_on_supervised_reentry(monkeypatch):
    calls = []
    fake_core = types.SimpleNamespace(__name__="bot.nija_core_loop")

    def raw(strategy):
        calls.append(strategy)

    fake_core.run_trading_loop = raw
    states = iter([
        (True, "supervised_activation_pending", 7, "RUNNING_SUPERVISED"),
        (False, "shutdown_requested", 0, "RUNNING_SUPERVISED"),
    ])
    monkeypatch.setattr(v120, "_supervised_pending_return_allowed", lambda module: next(states))
    monkeypatch.setattr(v120.time, "sleep", lambda seconds: None)
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")
    monkeypatch.setenv("NIJA_EXECUTION_ACTIVE", "true")

    assert v120._patch_core_loop(fake_core) is True
    fake_core.run_trading_loop("strategy")

    assert calls == ["strategy", "strategy"]
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert os.environ["NIJA_EXECUTION_ACTIVE"] == "false"
