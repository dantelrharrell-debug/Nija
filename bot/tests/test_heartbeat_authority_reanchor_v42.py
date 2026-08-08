from __future__ import annotations

import importlib
import os
import sys
import types


MODULE = "bot.heartbeat_authority_reanchor_v42_patch"


def _load():
    return importlib.import_module(MODULE)


class _Client:
    def __init__(self, lock="77:owner", generation="8", pttl=45000):
        self.lock = lock
        self.generation = generation
        self.pttl_value = pttl

    def get(self, key):
        if "generation" in key:
            return self.generation
        return self.lock

    def pttl(self, _key):
        return self.pttl_value


class _Runtime:
    def __init__(self):
        self.acquired = True
        self.lost = False
        self._local_fallback = False
        self._generation = 8
        self._token = "77"
        self._lock_key = "nija:writer_lock:test"
        self._lock_value = "77:owner"
        self._client = _Client()
        self._stop = types.SimpleNamespace(is_set=lambda: False)
        self._heartbeat_thread = types.SimpleNamespace(is_alive=lambda: True)

    def _nija_lease_renewal_health(self):
        return True, "renewal_healthy", 0.1, 15.0


class _State:
    def __init__(self, generation=7, timestamp=123.0):
        self.generation = generation
        self.timestamp = timestamp

    def snapshot(self):
        return types.SimpleNamespace(
            generation=self.generation,
            timestamp=self.timestamp,
        )


def _install_runtime(runtime, state):
    ewa = types.ModuleType("bot.entrypoint_writer_authority")
    ewa.get_entrypoint_writer_authority = lambda: runtime
    hs = types.ModuleType("bot.heartbeat_state")
    hs.get_heartbeat_state = lambda: state
    sys.modules["bot.entrypoint_writer_authority"] = ewa
    sys.modules["entrypoint_writer_authority"] = ewa
    sys.modules["bot.heartbeat_state"] = hs
    sys.modules["heartbeat_state"] = hs
    os.environ["NIJA_WRITER_LEASE_GENERATION"] = "8"
    os.environ["NIJA_WRITER_GENERATION"] = "8"
    os.environ["NIJA_WRITER_FENCING_TOKEN"] = "77"
    os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "1"
    os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] = "1"
    os.environ["NIJA_LEASE_GENERATION_KEY"] = "nija:lease:generation"


def test_exact_lineage_allows_reanchor(monkeypatch):
    mod = _load()
    runtime, state = _Runtime(), _State(generation=7)
    _install_runtime(runtime, state)
    single = types.ModuleType("bot.heartbeat_authority_single_source_patch")
    calls = []
    single.refresh_heartbeat = (
        lambda *, source, generation: calls.append((source, generation)) or 999.0
    )
    monkeypatch.setitem(
        sys.modules,
        "bot.heartbeat_authority_single_source_patch",
        single,
    )
    ok, proof = mod._attempt_reanchor("test")
    assert ok
    assert proof["reason"] == "canonical_heartbeat_reanchored"
    assert calls and calls[-1][1] == 8


def test_other_writer_blocks():
    mod = _load()
    runtime, state = _Runtime(), _State(generation=7)
    runtime._client.lock = "88:other"
    _install_runtime(runtime, state)
    proof = mod._redis_lineage_proof(8)
    assert not proof["ok"]
    assert proof["reason"] == "redis_lock_not_owned_exactly"


def test_generation_mismatch_blocks():
    mod = _load()
    runtime, state = _Runtime(), _State(generation=7)
    runtime._client.generation = "9"
    _install_runtime(runtime, state)
    proof = mod._redis_lineage_proof(8)
    assert not proof["ok"]
    assert proof["reason"].startswith("redis_generation_mismatch")


def test_expired_ttl_blocks():
    mod = _load()
    runtime, state = _Runtime(), _State(generation=7)
    runtime._client.pttl_value = -2
    _install_runtime(runtime, state)
    proof = mod._redis_lineage_proof(8)
    assert not proof["ok"]
    assert proof["reason"].startswith("redis_lock_ttl_not_positive")


def test_stale_renewal_blocks():
    mod = _load()
    runtime, state = _Runtime(), _State(generation=7)
    runtime._nija_lease_renewal_health = lambda: (
        False,
        "renewal_success_stale",
        99.0,
        15.0,
    )
    _install_runtime(runtime, state)
    proof = mod._redis_lineage_proof(8)
    assert not proof["ok"]
    assert proof["reason"] == "renewal_not_healthy:renewal_success_stale"


def test_newer_canonical_generation_never_regresses():
    mod = _load()
    runtime, state = _Runtime(), _State(generation=9)
    _install_runtime(runtime, state)
    ok, proof = mod._attempt_reanchor("test")
    assert not ok
    assert proof["reason"] == "canonical_generation_newer_than_expected"


def test_env_token_mismatch_blocks():
    mod = _load()
    runtime, state = _Runtime(), _State(generation=7)
    _install_runtime(runtime, state)
    os.environ["NIJA_WRITER_FENCING_TOKEN"] = "66"
    proof = mod._redis_lineage_proof(8)
    assert not proof["ok"]
    assert proof["reason"] == "fencing_token_mismatch"


def test_dead_worker_restart_requires_canonical_starter():
    mod = _load()
    runtime = _Runtime()
    runtime._heartbeat_thread = types.SimpleNamespace(is_alive=lambda: False)
    runtime._nija_lease_renewal_health = lambda: (
        False,
        "renewal_thread_not_alive",
        float("inf"),
        15.0,
    )
    called = []
    runtime._start_heartbeat = lambda: called.append(True)
    assert not mod._restart_dead_renewal_worker(
        runtime,
        "renewal_thread_not_alive",
    )
    assert called == [True]


def test_local_fallback_not_accepted_as_redis_proof():
    mod = _load()
    runtime, state = _Runtime(), _State(generation=7)
    runtime._local_fallback = True
    _install_runtime(runtime, state)
    proof = mod._redis_lineage_proof(8)
    assert not proof["ok"]
    assert proof["reason"] == "local_fallback_not_redis_proven"
