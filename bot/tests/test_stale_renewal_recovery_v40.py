from __future__ import annotations

import importlib
import os
import threading
import types


MODULE = "bot.stale_renewal_recovery_v40_patch"


def _load():
    return importlib.import_module(MODULE)


class _Client:
    def __init__(self, value=None, error: Exception | None = None):
        self.value = value
        self.error = error
        self.calls = 0

    def get(self, _key):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.value


class _Runtime:
    def __init__(self, lock_value: str = "77:owner", redis_value=None):
        self._client = _Client(redis_value)
        self._lock_key = "nija:writer_lock:process"
        self._lock_value = lock_value
        self._token = "77"
        self._generation = 5
        self.acquired = True
        self.lost = False
        self.marked = []

    def _mark_lost(self, reason: str):
        self.marked.append(reason)
        self.lost = True


def test_lock_inspection_owned_exact():
    mod = _load()
    runtime = _Runtime(redis_value="77:owner")
    state, detail = mod._inspect_lock(runtime)
    assert state == "owned"
    assert "lock_owned_exact" in detail


def test_lock_inspection_missing():
    mod = _load()
    runtime = _Runtime(redis_value=None)
    state, detail = mod._inspect_lock(runtime)
    assert state == "missing"
    assert "lock_missing" in detail


def test_lock_inspection_other_writer():
    mod = _load()
    runtime = _Runtime(redis_value="88:other")
    state, detail = mod._inspect_lock(runtime)
    assert state == "other"
    assert "current_prefix=88" in detail


def test_lock_inspection_error_never_infers_loss():
    mod = _load()
    runtime = _Runtime(redis_value=None)
    runtime._client = _Client(error=TimeoutError("redis timeout"))
    state, detail = mod._inspect_lock(runtime)
    assert state == "error"
    assert "redis_lock_read_error" in detail


def test_mark_runtime_lost_forces_execution_fail_closed(monkeypatch):
    mod = _load()
    runtime = _Runtime(redis_value=None)
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")
    monkeypatch.setenv("NIJA_EXECUTION_ACTIVE", "true")

    assert mod._mark_runtime_lost(runtime, "lock_missing_and_fencing_token_mismatch") is True
    assert runtime.marked == ["lock_missing_and_fencing_token_mismatch"]
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert os.environ["NIJA_EXECUTION_ACTIVE"] == "false"


def test_watchdog_stale_missing_triggers_recoverable_loss(monkeypatch):
    mod = _load()
    runtime = _Runtime(redis_value=None)
    stop = threading.Event()

    monkeypatch.setattr(mod, "_cfg_float", lambda name, default, minimum: 1.0)
    monkeypatch.setattr(
        mod,
        "_runtime_health",
        lambda _runtime: (False, "renewal_success_stale", 30.0, 10.0),
    )
    monkeypatch.setattr(mod, "_inspect_lock", lambda _runtime: ("missing", "lock_missing"))

    mod._watchdog_loop(runtime, stop)

    assert runtime.marked == ["lock_missing_and_fencing_token_mismatch"]
    assert runtime.lost is True


def test_watchdog_stale_other_writer_is_nonrecoverable(monkeypatch):
    mod = _load()
    runtime = _Runtime(redis_value="88:other")
    stop = threading.Event()

    monkeypatch.setattr(mod, "_cfg_float", lambda name, default, minimum: 1.0)
    monkeypatch.setattr(
        mod,
        "_runtime_health",
        lambda _runtime: (False, "renewal_success_stale", 30.0, 10.0),
    )
    monkeypatch.setattr(mod, "_inspect_lock", lambda _runtime: ("other", "other writer"))

    mod._watchdog_loop(runtime, stop)

    assert runtime.marked == ["lock_owned_by_different_writer"]
    assert runtime.lost is True


def test_watchdog_stale_but_owned_does_not_create_false_loss(monkeypatch):
    mod = _load()
    runtime = _Runtime(redis_value="77:owner")
    stop = threading.Event()
    calls = {"health": 0}

    monkeypatch.setattr(mod, "_cfg_float", lambda name, default, minimum: 0.01 if "POLL" in name else 1.0)

    def _health(_runtime):
        calls["health"] += 1
        if calls["health"] == 1:
            return False, "renewal_success_stale", 30.0, 10.0
        stop.set()
        return True, "renewal_healthy", 0.0, 10.0

    monkeypatch.setattr(mod, "_runtime_health", _health)
    monkeypatch.setattr(mod, "_inspect_lock", lambda _runtime: ("owned", "owned"))

    mod._watchdog_loop(runtime, stop)

    assert runtime.marked == []
    assert runtime.lost is False


def test_watchdog_redis_error_does_not_infer_ownership_loss(monkeypatch):
    mod = _load()
    runtime = _Runtime(redis_value=None)
    stop = threading.Event()
    calls = {"health": 0}

    monkeypatch.setattr(mod, "_cfg_float", lambda name, default, minimum: 0.01 if "POLL" in name else 1.0)

    def _health(_runtime):
        calls["health"] += 1
        if calls["health"] == 1:
            return False, "renewal_success_stale", 30.0, 10.0
        stop.set()
        return True, "renewal_healthy", 0.0, 10.0

    monkeypatch.setattr(mod, "_runtime_health", _health)
    monkeypatch.setattr(mod, "_inspect_lock", lambda _runtime: ("error", "redis timeout"))

    mod._watchdog_loop(runtime, stop)

    assert runtime.marked == []
    assert runtime.lost is False


def test_entrypoint_activation_arms_watchdog(monkeypatch):
    mod = _load()
    starts = []

    class _Authority:
        acquired = False

        def _activate_distributed_authority(self, *args, **kwargs):
            self.acquired = True
            return types.SimpleNamespace(acquired=True)

        def release(self):
            return True

    module = types.ModuleType("bot.entrypoint_writer_authority")
    module.EntrypointWriterAuthority = _Authority
    module.get_entrypoint_writer_authority = lambda: _Authority()

    monkeypatch.setattr(mod, "_start_watchdog", lambda runtime: starts.append(runtime) or True)
    assert mod._patch_entrypoint_writer_authority(module) is True

    runtime = _Authority()
    result = runtime._activate_distributed_authority()
    assert result.acquired is True
    assert starts == [runtime]
