from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any


class _FakeRedis:
    def __init__(self, result: Any) -> None:
        self.result = result
        self.calls: list[tuple[Any, ...]] = []

    def eval(self, *args: Any) -> Any:
        self.calls.append(args)
        return self.result


def _module():
    return importlib.import_module("bot.writer_lock_release_guard")


def _clear_authority_env(monkeypatch) -> None:
    for name in (
        "NIJA_WRITER_FENCING_TOKEN",
        "NIJA_WRITER_OWNER_ID",
        "NIJA_WRITER_INSTANCE_ID",
        "NIJA_WRITER_LEASE_GENERATION",
        "NIJA_WRITER_LEASE_ACQUIRED",
        "NIJA_LOCK_ACQUIRED",
        "NIJA_WRITER_HEARTBEAT_ACTIVE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_hostname_or_service_identity_cannot_release_writer_lock(monkeypatch) -> None:
    module = _module()
    _clear_authority_env(monkeypatch)
    monkeypatch.setenv("HOSTNAME", "shared-container-host")
    monkeypatch.setenv("RENDER_SERVICE_ID", "srv-shared")

    fake = _FakeRedis([1, "60:provider=render|instance_id=shared-container-host|pid=40"])
    monkeypatch.setattr(module, "_redis_client", lambda: fake)

    assert module.release_owned_writer_lock("healthcheck_exit") is False
    assert fake.calls == []


def test_child_process_pid_mismatch_cannot_release_parent_lease(monkeypatch) -> None:
    module = _module()
    _clear_authority_env(monkeypatch)
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "60")
    monkeypatch.setenv("NIJA_WRITER_OWNER_ID", "provider=render|instance_id=x|pid=999999")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "12")
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    monkeypatch.setenv("NIJA_LOCK_ACQUIRED", "true")

    fake = _FakeRedis([1, "60:provider=render|instance_id=x|pid=999999"])
    monkeypatch.setattr(module, "_redis_client", lambda: fake)

    assert module.release_owned_writer_lock("child_exit") is False
    assert fake.calls == []


def test_exact_local_owner_uses_atomic_compare_and_delete(monkeypatch) -> None:
    module = _module()
    _clear_authority_env(monkeypatch)
    owner = f"provider=render|instance_id=test|pid={os.getpid()}"
    expected = f"60:{owner}"
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "60")
    monkeypatch.setenv("NIJA_WRITER_OWNER_ID", owner)
    monkeypatch.setenv("NIJA_WRITER_INSTANCE_ID", "test")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "12")
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    monkeypatch.setenv("NIJA_LOCK_ACQUIRED", "true")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "1")

    fake = _FakeRedis([1, expected])
    monkeypatch.setattr(module, "_redis_client", lambda: fake)

    assert module.release_owned_writer_lock("unit_test") is True
    assert len(fake.calls) == 1
    args = fake.calls[0]
    assert args[1] == 3
    assert expected in args
    assert "NIJA_WRITER_FENCING_TOKEN" not in os.environ
    assert "NIJA_WRITER_OWNER_ID" not in os.environ
    assert os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] == "0"


def test_mismatched_redis_value_is_not_deleted(monkeypatch) -> None:
    module = _module()
    _clear_authority_env(monkeypatch)
    owner = f"provider=render|instance_id=test|pid={os.getpid()}"
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "60")
    monkeypatch.setenv("NIJA_WRITER_OWNER_ID", owner)
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "12")
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    monkeypatch.setenv("NIJA_LOCK_ACQUIRED", "true")

    fake = _FakeRedis([0, "61:provider=render|instance_id=other|pid=50"])
    monkeypatch.setattr(module, "_redis_client", lambda: fake)

    assert module.release_owned_writer_lock("unit_test_mismatch") is False
    assert len(fake.calls) == 1
    assert os.environ["NIJA_WRITER_FENCING_TOKEN"] == "60"


def test_docker_healthcheck_uses_isolated_stdlib_python() -> None:
    root = Path(__file__).resolve().parents[2]
    dockerfile = (root / "Dockerfile").read_text(encoding="utf-8")
    healthcheck = dockerfile.split("HEALTHCHECK", 1)[1].split("CMD [", 1)[0]

    assert "python -S -c" in healthcheck
    assert "urllib.request" in healthcheck
    assert "/healthz" in healthcheck
    assert "import requests" not in healthcheck
