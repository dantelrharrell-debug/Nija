from __future__ import annotations

import importlib
import os


MODULE = "bot.writer_distributed_loss_watchdog_v52_patch"


class _Client:
    def __init__(self, value=None, error: Exception | None = None):
        self.value = value
        self.error = error

    def get(self, _key):
        if self.error is not None:
            raise self.error
        return self.value


class _Runtime:
    def __init__(self, redis_value=None):
        self._client = _Client(redis_value)
        self._lock_key = "nija:writer_lock:process"
        self._lock_value = "2044:owner"
        self._token = "2044"
        self._generation = 18
        self._local_fallback = False
        self.acquired = True
        self.lost = False
        self.marked: list[str] = []

    def _mark_lost(self, reason: str) -> None:
        self.marked.append(reason)
        self.lost = True


def _load():
    return importlib.import_module(MODULE)


def test_missing_lock_marks_recoverable_loss_even_without_renewal_staleness(monkeypatch):
    mod = _load()
    runtime = _Runtime(redis_value=None)
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")
    monkeypatch.setenv("NIJA_EXECUTION_ACTIVE", "true")

    result = mod.reconcile_once(runtime)

    assert result["state"] == "missing"
    assert result["action"] == "mark_lost_recoverable"
    assert runtime.marked == ["lock_missing_and_fencing_token_mismatch"]
    assert runtime.lost is True
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert os.environ["NIJA_EXECUTION_ACTIVE"] == "false"


def test_other_owner_marks_nonrecoverable_loss(monkeypatch):
    mod = _load()
    runtime = _Runtime(redis_value="9999:other")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")
    monkeypatch.setenv("NIJA_EXECUTION_ACTIVE", "true")

    result = mod.reconcile_once(runtime)

    assert result["state"] == "other"
    assert result["action"] == "mark_lost_nonrecoverable"
    assert runtime.marked == ["lock_owned_by_different_writer"]
    assert runtime.lost is True


def test_exact_owner_remains_healthy_and_unmodified():
    mod = _load()
    runtime = _Runtime(redis_value="2044:owner")

    result = mod.reconcile_once(runtime)

    assert result["ok"] is True
    assert result["state"] == "owned"
    assert result["action"] == "none"
    assert runtime.marked == []
    assert runtime.lost is False


def test_redis_error_fails_closed_without_inferred_loss(monkeypatch):
    mod = _load()
    runtime = _Runtime(redis_value=None)
    runtime._client = _Client(error=TimeoutError("redis timeout"))
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")
    monkeypatch.setenv("NIJA_EXECUTION_ACTIVE", "true")

    result = mod.reconcile_once(runtime)

    assert result["state"] == "error"
    assert result["action"] == "fail_closed_retry"
    assert runtime.marked == []
    assert runtime.lost is False
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert os.environ["NIJA_EXECUTION_ACTIVE"] == "false"


def test_local_fallback_is_revoked_instead_of_accepted():
    mod = _load()
    runtime = _Runtime(redis_value=None)
    runtime._local_fallback = True

    result = mod.reconcile_once(runtime)

    assert result["ok"] is False
    assert result["state"] == "local_fallback_forbidden"
    assert result["action"] == "mark_lost_nonrecoverable"
    assert runtime.marked == ["local_writer_fallback_forbidden"]
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert os.environ["NIJA_EXECUTION_ACTIVE"] == "false"
