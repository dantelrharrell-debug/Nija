from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path

PATCH_PATH = Path(__file__).resolve().parents[1] / "writer_lost_epoch_v48_patch.py"
spec = importlib.util.spec_from_file_location("nija_test_writer_lost_epoch_v48", PATCH_PATH)
assert spec is not None and spec.loader is not None
v48 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v48)


class Redis:
    def __init__(self, value="2036:owner"):
        self.value = value
        self.get_calls = []

    def get(self, key):
        self.get_calls.append(key)
        return self.value


class Runtime:
    lost = False
    _client = Redis()
    _lock_key = "nija:writer_lock:process"
    _lock_value = "2036:owner"
    _generation = 3339
    _token = "2036"


def _module(original_result=(True, "")):
    module = types.ModuleType("bot.entrypoint_writer_authority")

    class Authority(Runtime):
        calls = 0

        def _heartbeat_tick(self):
            type(self).calls += 1
            return original_result

    module.EntrypointWriterAuthority = Authority
    return module, Authority


def test_exact_owner_delegates_to_canonical_renewal(monkeypatch):
    module, Authority = _module()
    redis = Redis("2036:owner")
    Authority._client = redis
    assert v48._patch_entrypoint_writer_authority(module) is True
    result = Authority()._heartbeat_tick()
    assert result == (True, "")
    assert Authority.calls == 1


def test_missing_lock_never_delegates_or_recreates(monkeypatch):
    module, Authority = _module()
    redis = Redis(None)
    Authority._client = redis
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "1")
    monkeypatch.setenv("NIJA_EXECUTION_ACTIVE", "true")
    assert v48._patch_entrypoint_writer_authority(module) is True
    ok, reason = Authority()._heartbeat_tick()
    assert ok is False
    assert reason == "lock_missing_and_fencing_token_mismatch"
    assert Authority.calls == 0
    assert redis.value is None
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert os.environ["NIJA_EXECUTION_ACTIVE"] == "false"


def test_other_owner_is_nonrecoverable_and_never_delegates(monkeypatch):
    module, Authority = _module()
    Authority._client = Redis("9999:other")
    assert v48._patch_entrypoint_writer_authority(module) is True
    ok, reason = Authority()._heartbeat_tick()
    assert ok is False
    assert reason == "lock_owned_by_different_writer"
    assert Authority.calls == 0


def test_redis_read_error_fails_closed(monkeypatch):
    module, Authority = _module()

    class BrokenRedis:
        def get(self, _key):
            raise RuntimeError("down")

    Authority._client = BrokenRedis()
    assert v48._patch_entrypoint_writer_authority(module) is True
    ok, reason = Authority()._heartbeat_tick()
    assert ok is False
    assert "redis_lock_read_error" in reason
    assert Authority.calls == 0


def test_already_lost_runtime_never_delegates(monkeypatch):
    module, Authority = _module()
    Authority.lost = True
    Authority._client = Redis("2036:owner")
    assert v48._patch_entrypoint_writer_authority(module) is True
    ok, reason = Authority()._heartbeat_tick()
    assert ok is False
    assert reason == "runtime_already_lost"
    assert Authority.calls == 0


def test_patch_is_idempotent():
    module, Authority = _module()
    assert v48._patch_entrypoint_writer_authority(module) is True
    first = Authority._heartbeat_tick
    assert v48._patch_entrypoint_writer_authority(module) is True
    assert Authority._heartbeat_tick is first
