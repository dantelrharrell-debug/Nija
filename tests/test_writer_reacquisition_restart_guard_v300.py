from __future__ import annotations

import logging
import threading
from types import ModuleType, SimpleNamespace

from bot import writer_reacquisition_restart_guard_v300_patch as v300


class _Timer:
    def __init__(self, interval=0.0, function=None):
        self.interval = interval
        self.function = function
        self.name = ""
        self.daemon = False
        self.started = False
        self.cancelled = False

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True

    def is_alive(self):
        return self.started and not self.cancelled


class _Heartbeat:
    def is_alive(self):
        return True


class _Redis:
    def __init__(self, current: str, *, fail: bool = False):
        self.current = current
        self.fail = fail
        self.get_calls = []
        self.mutations = []

    def get(self, key):
        self.get_calls.append(key)
        if self.fail:
            raise RuntimeError("redis-read-failed")
        return self.current

    def __getattr__(self, name):
        if name in {"set", "delete", "eval", "expire"}:
            def _mutation(*args, **kwargs):
                self.mutations.append((name, args, kwargs))
                raise AssertionError(f"unexpected Redis mutation: {name}")
            return _mutation
        raise AttributeError(name)


def _runtime(*, lost: bool, generation: int, token: str, redis: _Redis | None = None):
    event = threading.Event()
    if lost:
        event.set()
    return SimpleNamespace(
        _lost=event,
        _result=SimpleNamespace(acquired=not lost),
        _generation=generation,
        _token=token,
        _lock_key="nija:writer_lock:test",
        _lock_value=f"{token}:owner",
        _client=redis,
        _heartbeat_thread=_Heartbeat(),
        _unhandled_loss_restart_timer=None,
        _nija_v300_restart_epoch=0,
        _nija_v300_restart_generation=0,
        _nija_v300_restart_token="",
        _nija_v300_restart_callback=None,
    )


def _owner_module() -> ModuleType:
    module = ModuleType("fake_entrypoint_writer_authority")
    module._MARKER = "test-writer-marker"
    module.logger = logging.getLogger("test.v300.owner")
    module._live_mode = lambda: True
    module._cfg_float = lambda name, default, minimum=0.0: max(float(minimum), float(default))
    return module


def test_cancel_pending_restart_invalidates_epoch_and_cancels_timer():
    runtime = _runtime(lost=False, generation=5009, token="3696")
    timer = _Timer()
    timer.start()
    runtime._unhandled_loss_restart_timer = timer
    runtime._nija_v300_restart_epoch = 7
    runtime._nija_v300_restart_generation = 5008
    runtime._nija_v300_restart_token = "3695"

    assert v300._cancel_pending_restart(
        runtime,
        reason="writer_reacquired",
        new_generation=5009,
        new_token="3696",
    ) is True

    assert timer.cancelled is True
    assert runtime._unhandled_loss_restart_timer is None
    assert runtime._nija_v300_restart_epoch == 8
    assert runtime._nija_v300_restart_generation == 0
    assert runtime._nija_v300_restart_token == ""


def test_recovered_writer_suppresses_stale_timer_only_with_exact_redis_proof():
    redis = _Redis("3696:owner")
    runtime = _runtime(lost=False, generation=5009, token="3696", redis=redis)
    timer = object()
    runtime._unhandled_loss_restart_timer = timer
    runtime._nija_v300_restart_epoch = 3

    suppress, detail = v300._restart_suppression_reason(
        runtime,
        timer=timer,
        epoch=3,
        scheduled_generation=5008,
        scheduled_token="3695",
    )

    assert suppress is True
    assert detail == "writer_recovered:exact_redis_process_writer"
    assert redis.get_calls == ["nija:writer_lock:test"]
    assert redis.mutations == []


def test_recovery_does_not_suppress_when_exact_redis_proof_fails():
    redis = _Redis("3696:other-owner")
    runtime = _runtime(lost=False, generation=5009, token="3696", redis=redis)
    timer = object()
    runtime._unhandled_loss_restart_timer = timer
    runtime._nija_v300_restart_epoch = 4

    suppress, detail = v300._restart_suppression_reason(
        runtime,
        timer=timer,
        epoch=4,
        scheduled_generation=5008,
        scheduled_token="3695",
    )

    assert suppress is False
    assert detail == "recovery_not_exact:redis_lock_owner_mismatch"
    assert redis.mutations == []


def test_redis_read_error_remains_fail_closed():
    redis = _Redis("", fail=True)
    runtime = _runtime(lost=False, generation=5009, token="3696", redis=redis)
    timer = object()
    runtime._unhandled_loss_restart_timer = timer
    runtime._nija_v300_restart_epoch = 5

    suppress, detail = v300._restart_suppression_reason(
        runtime,
        timer=timer,
        epoch=5,
        scheduled_generation=5008,
        scheduled_token="3695",
    )

    assert suppress is False
    assert detail.startswith("recovery_not_exact:redis_read_failed:RuntimeError")
    assert redis.mutations == []


def test_genuine_unresolved_loss_still_exits_75(monkeypatch):
    created = []

    def timer_factory(interval, function):
        timer = _Timer(interval, function)
        created.append(timer)
        return timer

    exits = []
    monkeypatch.setattr(v300.threading, "Timer", timer_factory)
    monkeypatch.setattr(v300.os, "_exit", lambda code: exits.append(code))

    runtime = _runtime(lost=True, generation=5008, token="3695", redis=_Redis(""))
    v300._schedule_restart_v300(
        runtime,
        _owner_module(),
        "lock_missing_and_fencing_token_mismatch",
    )

    assert len(created) == 1
    assert created[0].started is True
    created[0].function()
    assert exits == [75]


def test_timer_callback_self_suppresses_after_exact_reacquisition(monkeypatch):
    created = []

    def timer_factory(interval, function):
        timer = _Timer(interval, function)
        created.append(timer)
        return timer

    exits = []
    monkeypatch.setattr(v300.threading, "Timer", timer_factory)
    monkeypatch.setattr(v300.os, "_exit", lambda code: exits.append(code))

    redis = _Redis("3695:owner")
    runtime = _runtime(lost=True, generation=5008, token="3695", redis=redis)
    v300._schedule_restart_v300(
        runtime,
        _owner_module(),
        "lock_missing_and_fencing_token_mismatch",
    )
    timer = created[0]

    # Model a genuine reacquisition that raced with Timer.cancel(): the old
    # callback still runs, but the runtime now has a new exact writer epoch.
    runtime._lost.clear()
    runtime._result = SimpleNamespace(acquired=True)
    runtime._generation = 5009
    runtime._token = "3696"
    runtime._lock_value = "3696:owner"
    redis.current = "3696:owner"

    timer.function()

    assert exits == []
    assert runtime._unhandled_loss_restart_timer is None
    assert redis.mutations == []


def test_successful_activation_wrapper_cancels_old_timer():
    module = ModuleType("v300_patch_test_authority")
    module._MARKER = "test"
    module.logger = logging.getLogger("test.v300.patch")
    module._live_mode = lambda: True
    module._cfg_float = lambda name, default, minimum=0.0: max(float(minimum), float(default))

    class Authority:
        def __init__(self):
            self._unhandled_loss_restart_timer = _Timer()
            self._unhandled_loss_restart_timer.start()
            self._nija_v300_restart_epoch = 1
            self._nija_v300_restart_generation = 5008
            self._nija_v300_restart_token = "3695"
            self._generation = 5009
            self._token = "3696"

        def _activate_distributed_authority(self, *args, **kwargs):
            return SimpleNamespace(
                acquired=True,
                local_fallback=False,
                generation=5009,
                token="3696",
            )

        def _schedule_unhandled_loss_restart(self, reason, *, handler_confirmed=False):
            raise AssertionError("original scheduler should be replaced")

    module.EntrypointWriterAuthority = Authority
    assert v300._patch(module) is True

    runtime = Authority()
    old_timer = runtime._unhandled_loss_restart_timer
    result = runtime._activate_distributed_authority()

    assert result.acquired is True
    assert old_timer.cancelled is True
    assert runtime._unhandled_loss_restart_timer is None


def test_confirmed_callback_handoff_does_not_schedule_timer(monkeypatch):
    created = []
    monkeypatch.setattr(
        v300.threading,
        "Timer",
        lambda interval, function: created.append((interval, function)),
    )

    runtime = _runtime(lost=True, generation=5008, token="3695")
    v300._schedule_restart_v300(
        runtime,
        _owner_module(),
        "writer_lost",
        handler_confirmed=True,
    )

    assert created == []
    assert runtime._unhandled_loss_restart_timer is None
