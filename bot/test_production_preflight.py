import json
import os

import pytest

from bot import production_preflight as preflight
from bot.distributed_nonce_manager import make_api_key_id


class FakeRedis:
    def __init__(self, *, persistence=None, info=None, kv=None):
        self._persistence = persistence or {}
        self._info = info or {}
        self._kv = kv or {}

    def info(self, section=None):
        if section == "persistence":
            return dict(self._persistence)
        return dict(self._info)

    def get(self, key):
        return self._kv.get(key)


def _write_health_state(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload))


def _base_persistence():
    return {
        "aof_enabled": 1,
        "aof_last_write_status": "ok",
        "aof_last_write_errno": 0,
        "rdb_last_bgsave_status": "ok",
        "rdb_bgsave_in_progress": 0,
    }


def test_redis_reset_requires_manual_ack(tmp_path, monkeypatch):
    monkeypatch.setenv("DRY_RUN_MODE", "true")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("NIJA_STRICT_REDIS_LEASE", "true")
    monkeypatch.setenv("NIJA_REDIS_RESET_POLICY", "require_confirmation")
    monkeypatch.setenv("KRAKEN_PLATFORM_API_KEY", "test-key")
    state_path = tmp_path / "redis_health_state.json"
    monkeypatch.setenv("NIJA_REDIS_HEALTH_STATE_PATH", str(state_path))

    key_id = make_api_key_id("test-key")
    kv = {
        f"nija:kraken:writer:lease_version:{key_id}": 5,
        f"nija:kraken:nonce:{key_id}": 120,
    }
    _write_health_state(
        state_path,
        {"nonce_lease_version": 10, "nonce_value": 200, "writer_fence_token": 0, "redis_run_id": "r1"},
    )

    redis_client = FakeRedis(
        persistence=_base_persistence(),
        info={"run_id": "r1", "loading": 0},
        kv=kv,
    )

    with pytest.raises(SystemExit):
        preflight._step3_redis_health(redis_client)


def test_auto_reinit_requires_reconciliation(tmp_path, monkeypatch):
    monkeypatch.setenv("DRY_RUN_MODE", "true")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("NIJA_STRICT_REDIS_LEASE", "true")
    monkeypatch.setenv("NIJA_REDIS_RESET_POLICY", "auto_reinit")
    monkeypatch.setenv("KRAKEN_PLATFORM_API_KEY", "test-key")
    state_path = tmp_path / "redis_health_state.json"
    monkeypatch.setenv("NIJA_REDIS_HEALTH_STATE_PATH", str(state_path))

    key_id = make_api_key_id("test-key")
    kv = {
        f"nija:kraken:writer:lease_version:{key_id}": 3,
        f"nija:kraken:nonce:{key_id}": 50,
    }
    _write_health_state(
        state_path,
        {"nonce_lease_version": 9, "nonce_value": 80, "writer_fence_token": 0, "redis_run_id": "r2"},
    )

    redis_client = FakeRedis(
        persistence=_base_persistence(),
        info={"run_id": "r2", "loading": 0},
        kv=kv,
    )

    with pytest.raises(SystemExit):
        preflight._step3_redis_health(redis_client)


def test_persistence_aof_write_failure_blocks_live(tmp_path, monkeypatch):
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("NIJA_STRICT_REDIS_LEASE", "true")
    monkeypatch.setenv("NIJA_REDIS_RESET_POLICY", "require_confirmation")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "123")
    monkeypatch.setenv("KRAKEN_PLATFORM_API_KEY", "test-key")
    state_path = tmp_path / "redis_health_state.json"
    monkeypatch.setenv("NIJA_REDIS_HEALTH_STATE_PATH", str(state_path))

    key_id = make_api_key_id("test-key")
    kv = {
        preflight._resolve_writer_lock_key(): "123:holder",
        f"nija:kraken:writer:lease_version:{key_id}": 2,
        f"nija:kraken:nonce:{key_id}": 10,
    }

    persistence = _base_persistence()
    persistence["aof_last_write_status"] = "err"
    redis_client = FakeRedis(
        persistence=persistence,
        info={"run_id": "r3", "loading": 0},
        kv=kv,
    )

    with pytest.raises(SystemExit):
        preflight._step3_redis_health(redis_client)


def test_writer_lock_token_mismatch_blocks_live(tmp_path, monkeypatch):
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("NIJA_STRICT_REDIS_LEASE", "true")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "222")
    monkeypatch.setenv("KRAKEN_PLATFORM_API_KEY", "test-key")
    state_path = tmp_path / "redis_health_state.json"
    monkeypatch.setenv("NIJA_REDIS_HEALTH_STATE_PATH", str(state_path))

    key_id = make_api_key_id("test-key")
    kv = {
        preflight._resolve_writer_lock_key(): "999:holder",
        f"nija:kraken:writer:lease_version:{key_id}": 2,
        f"nija:kraken:nonce:{key_id}": 10,
    }

    redis_client = FakeRedis(
        persistence=_base_persistence(),
        info={"run_id": "r4", "loading": 0},
        kv=kv,
    )

    with pytest.raises(SystemExit):
        preflight._step3_redis_health(redis_client)


def test_strict_lease_missing_attempts_acquire_before_fail(tmp_path, monkeypatch):
    monkeypatch.setenv("DRY_RUN_MODE", "true")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("NIJA_STRICT_REDIS_LEASE", "true")
    monkeypatch.setenv("KRAKEN_PLATFORM_API_KEY", "test-key")
    state_path = tmp_path / "redis_health_state.json"
    monkeypatch.setenv("NIJA_REDIS_HEALTH_STATE_PATH", str(state_path))

    key_id = make_api_key_id("test-key")
    lease_key = f"nija:kraken:writer:lease_version:{key_id}"
    nonce_key = f"nija:kraken:nonce:{key_id}"
    kv = {
        nonce_key: 0,
    }
    redis_client = FakeRedis(
        persistence=_base_persistence(),
        info={"run_id": "r5", "loading": 0},
        kv=kv,
    )

    class DummyDNM:
        def ensure_writer_lock(self, _api_key_id: str) -> None:
            kv[lease_key] = 7

    monkeypatch.setattr(
        "bot.distributed_nonce_manager.get_distributed_nonce_manager",
        lambda redis_client=None: DummyDNM(),
    )

    preflight._step3_redis_health(redis_client)
    assert int(kv.get(lease_key, 0)) == 7
