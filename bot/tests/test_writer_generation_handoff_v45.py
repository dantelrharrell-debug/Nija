from __future__ import annotations

import importlib.util
import os
import sys
import types
from pathlib import Path

PATCH_PATH = Path(__file__).resolve().parents[1] / "writer_generation_handoff_v45_patch.py"
spec = importlib.util.spec_from_file_location("nija_test_writer_generation_handoff_v45", PATCH_PATH)
assert spec is not None and spec.loader is not None
v45 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(v45)


class Redis:
    def __init__(self, lock="tok:owner", gen="3337", ttl=50000):
        self.lock = lock
        self.gen = gen
        self.ttl = ttl
        self.sets = []
        self.expires = []

    def get(self, key):
        if key == "nija:writer_lock:scope":
            return self.lock
        if key == "nija:lease:generation":
            return self.gen
        return None

    def pttl(self, _key):
        return self.ttl

    def set(self, *args, **kwargs):
        self.sets.append((args, kwargs))
        return True

    def expire(self, *args, **kwargs):
        self.expires.append((args, kwargs))
        return True


class Runtime:
    acquired = True
    lost = False
    _local_fallback = False
    _generation = 3337
    _token = "tok"
    _lock_key = "nija:writer_lock:scope"
    _lock_value = "tok:owner"
    _ttl_s = 60

    def __init__(self, redis):
        self._client = redis


def install_runtime(monkeypatch, redis=None):
    redis = redis or Redis()
    runtime = Runtime(redis)
    module = types.ModuleType("bot.entrypoint_writer_authority")
    module.get_entrypoint_writer_authority = lambda: runtime
    monkeypatch.setitem(sys.modules, "bot.entrypoint_writer_authority", module)
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "tok")
    monkeypatch.setenv("NIJA_LEASE_GENERATION_KEY", "nija:lease:generation")
    return runtime, redis


def test_repairs_10_to_3337(monkeypatch):
    install_runtime(monkeypatch)
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "10")
    monkeypatch.setenv("NIJA_WRITER_GENERATION", "10")
    ok, generation, _ = v45.repair_process_generation("test")
    assert ok is True
    assert generation == 3337
    assert os.environ["NIJA_WRITER_LEASE_GENERATION"] == "3337"
    assert os.environ["NIJA_WRITER_GENERATION"] == "3337"


def test_wrong_lock_rejected(monkeypatch):
    install_runtime(monkeypatch, Redis(lock="other:owner"))
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "10")
    ok, _, reason = v45.repair_process_generation("test")
    assert ok is False
    assert reason == "redis_lock_owner_mismatch"
    assert os.environ["NIJA_WRITER_LEASE_GENERATION"] == "10"


def test_missing_lock_rejected(monkeypatch):
    install_runtime(monkeypatch, Redis(lock=""))
    ok, _, reason = v45.repair_process_generation("test")
    assert ok is False
    assert reason == "redis_lock_missing"


def test_wrong_redis_generation_rejected(monkeypatch):
    install_runtime(monkeypatch, Redis(gen="10"))
    ok, _, reason = v45.repair_process_generation("test")
    assert ok is False
    assert "redis_generation_mismatch" in reason


def test_expired_ttl_rejected(monkeypatch):
    install_runtime(monkeypatch, Redis(ttl=0))
    ok, _, reason = v45.repair_process_generation("test")
    assert ok is False
    assert "ttl_not_positive" in reason


def test_nonce_publish_does_not_mutate_process_token(monkeypatch):
    install_runtime(monkeypatch)
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "3337")
    module = types.ModuleType("bot.distributed_nonce_manager")

    class Backend:
        def _publish_lock_acquired_state(self, _version):
            raise AssertionError("legacy nonce publisher must not run")

    module._PerKeyRedisBackend = Backend
    assert v45._patch_nonce_module(module) is True
    Backend()._publish_lock_acquired_state(10)
    assert os.environ["NIJA_WRITER_FENCING_TOKEN"] == "tok"
    assert os.environ["NIJA_WRITER_LEASE_GENERATION"] == "3337"
    assert os.environ["NIJA_NONCE_LEASE_GENERATION"] == "10"


def test_tracker_reacquisition_uses_entrypoint_not_nonce(monkeypatch):
    install_runtime(monkeypatch)
    module = types.ModuleType("bot.writer_generation_tracker")
    module.get_local_generation = lambda: 10
    assert v45._patch_tracker_module(module) is True
    ok, generation, reason = module.attempt_lock_reacquisition()
    assert ok is True
    assert generation == 3337
    assert "canonical_process_writer" in reason


def test_heartbeat_never_recreates_missing_lock(monkeypatch):
    _, redis = install_runtime(monkeypatch, Redis(lock=""))
    module = types.ModuleType("bot.authority_heartbeat")

    class Monitor:
        pass

    Monitor._write_heartbeat_to_redis = lambda self: None
    module.AuthorityHeartbeatMonitor = Monitor
    assert v45._patch_heartbeat_module(module) is True
    Monitor()._write_heartbeat_to_redis()
    assert redis.sets == []
    assert redis.expires == []


def test_heartbeat_telemetry_never_extends_owned_process_lock(monkeypatch):
    _, redis = install_runtime(monkeypatch)
    module = types.ModuleType("bot.authority_heartbeat")

    class Monitor:
        pass

    Monitor._write_heartbeat_to_redis = lambda self: None
    module.AuthorityHeartbeatMonitor = Monitor
    assert v45._patch_heartbeat_module(module) is True
    Monitor()._write_heartbeat_to_redis()
    assert len(redis.sets) == 1
    assert redis.sets[0][0][0] == "nija:writer_heartbeat_active"
    assert redis.expires == []


def test_v42_expected_generation_prefers_proven_runtime(monkeypatch):
    install_runtime(monkeypatch)
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "10")
    module = types.ModuleType("bot.heartbeat_authority_reanchor_v42_patch")
    module._expected_generation = lambda: 10
    assert v45._patch_v42_module(module) is True
    assert module._expected_generation() == 3337
    assert os.environ["NIJA_WRITER_LEASE_GENERATION"] == "3337"


def test_env_token_mismatch_rejected(monkeypatch):
    install_runtime(monkeypatch)
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "bad")
    ok, _, reason = v45.repair_process_generation("test")
    assert ok is False
    assert reason == "env_fencing_token_mismatch"


def test_runtime_resolver_prefers_acquired_candidate_across_import_aliases(monkeypatch):
    stale = types.SimpleNamespace(
        acquired=False,
        lost=False,
        _local_fallback=False,
        _generation=0,
    )
    active = Runtime(Redis())
    package_module = types.ModuleType("bot.entrypoint_writer_authority")
    package_module.get_entrypoint_writer_authority = lambda: stale
    compatibility_module = types.ModuleType("entrypoint_writer_authority")
    compatibility_module.get_entrypoint_writer_authority = lambda: active
    monkeypatch.setitem(sys.modules, "bot.entrypoint_writer_authority", package_module)
    monkeypatch.setitem(sys.modules, "entrypoint_writer_authority", compatibility_module)

    runtime, error = v45._runtime()

    assert runtime is active
    assert error == ""
