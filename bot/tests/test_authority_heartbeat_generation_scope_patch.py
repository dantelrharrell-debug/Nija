from __future__ import annotations

import json
import os
import sys
from types import ModuleType

import authority_heartbeat_generation_scope_patch as patch


class FakeRedisClient:
    def __init__(self) -> None:
        self.values = {"nija:writer_lock:platform": b"token123:owner"}
        self.set_calls: list[tuple[str, object, int | None, bool | None]] = []
        self.get_calls: list[str] = []
        self.expire_calls: list[tuple[str, int]] = []

    def get(self, key: str):
        self.get_calls.append(key)
        return self.values.get(key)

    def set(self, key: str, value, ex=None, nx=None):
        self.set_calls.append((key, value, ex, nx))
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    def expire(self, key: str, ttl: int):
        self.expire_calls.append((key, ttl))
        return True


class FakeRedisModule(ModuleType):
    def __init__(self, client: FakeRedisClient) -> None:
        super().__init__("redis")
        self._client = client

    def from_url(self, *_args, **_kwargs):
        return self._client


def _fake_authority_module() -> tuple[ModuleType, type]:
    module = ModuleType("bot.authority_heartbeat")

    class AuthorityHeartbeatMonitor:
        def _write_heartbeat_to_redis(self):
            raise AssertionError("legacy global-generation writer must not run")

    module.AuthorityHeartbeatMonitor = AuthorityHeartbeatMonitor
    return module, AuthorityHeartbeatMonitor


def test_heartbeat_writer_uses_platform_generation_not_global_counter(monkeypatch):
    module, cls = _fake_authority_module()
    client = FakeRedisClient()
    monkeypatch.setitem(sys.modules, "redis", FakeRedisModule(client))
    monkeypatch.setattr(patch, "_platform_generation", lambda: (439, ""))
    monkeypatch.setattr(patch, "_redis_url", lambda: "redis://example")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "441")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "token123")
    monkeypatch.setenv("NIJA_WRITER_OWNER_ID", "owner")

    assert patch._patch_module(module) is True
    monitor = cls()
    monitor._write_heartbeat_to_redis()

    assert os.environ["NIJA_WRITER_LEASE_GENERATION"] == "439"
    assert "nija:lease:generation" not in client.get_calls
    heartbeat_call = next(call for call in client.set_calls if call[0] == "nija:writer_heartbeat_active")
    payload = json.loads(heartbeat_call[1])
    assert payload["generation"] == "439"
    assert payload["generation_scope"] == "platform_kraken_key"
    assert client.expire_calls == [("nija:writer_lock:platform", 90)]


def test_heartbeat_writer_fails_closed_when_platform_generation_missing(monkeypatch):
    module, cls = _fake_authority_module()
    client = FakeRedisClient()
    monkeypatch.setitem(sys.modules, "redis", FakeRedisModule(client))
    monkeypatch.setattr(patch, "_platform_generation", lambda: (0, "platform_lease_version_missing"))
    monkeypatch.setattr(patch, "_redis_url", lambda: "redis://example")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "439")

    assert patch._patch_module(module) is True
    cls()._write_heartbeat_to_redis()

    assert client.set_calls == []
    assert os.environ["NIJA_WRITER_LEASE_GENERATION"] == "439"


def test_patch_is_idempotent():
    module, cls = _fake_authority_module()
    assert patch._patch_module(module) is True
    first = cls._write_heartbeat_to_redis
    assert patch._patch_module(module) is True
    assert cls._write_heartbeat_to_redis is first
