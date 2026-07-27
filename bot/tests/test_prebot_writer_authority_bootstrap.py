from __future__ import annotations

from types import SimpleNamespace
import sys

import prebot_writer_authority_bootstrap as prebot


def test_live_main_process_is_targeted(monkeypatch) -> None:
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.delenv("NIJA_PREBOT_WRITER_AUTHORITY_DISABLE", raising=False)
    monkeypatch.delenv("NIJA_PREBOT_WRITER_AUTHORITY_FORCE", raising=False)
    monkeypatch.setattr(sys, "argv", ["/app/main.py"])

    assert prebot._target_process() is True


def test_healthcheck_python_subprocess_is_not_targeted(monkeypatch) -> None:
    monkeypatch.setenv("LIVE_CAPITAL_VERIFIED", "true")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.delenv("NIJA_PREBOT_WRITER_AUTHORITY_FORCE", raising=False)
    monkeypatch.setattr(sys, "argv", ["-c"])

    assert prebot._target_process() is False


def test_render_private_redis_is_prioritized(monkeypatch) -> None:
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv(
        "NIJA_REDIS_URL",
        "redis://default:secret@legacy.proxy.rlwy.net:12345/0",
    )
    monkeypatch.setenv("REDIS_URL", "redis://red-renderprivate:6379")
    monkeypatch.delenv("REDIS_PRIVATE_URL", raising=False)
    monkeypatch.delenv("REDIS_PUBLIC_URL", raising=False)
    monkeypatch.delenv("REDIS_TLS_URL", raising=False)

    candidates = prebot._candidate_urls()

    assert candidates[0] == "redis://red-renderprivate:6379"
    assert candidates[1].startswith("rediss://")


def test_prebot_identity_never_requires_bot_package(monkeypatch) -> None:
    monkeypatch.setenv("RENDER", "true")
    monkeypatch.setenv("RENDER_INSTANCE_ID", "srv-instance-1")
    monkeypatch.setenv("RENDER_SERVICE_ID", "srv-service-1")

    identity, owner, instance_id = prebot._instance_identity_prebot()

    assert instance_id == "srv-instance-1"
    assert identity["service_id"] == "srv-service-1"
    assert "instance_id=srv-instance-1" in owner


def test_prebot_redis_ready_log_is_idempotent(monkeypatch) -> None:
    prebot._READY_ENDPOINTS.clear()
    messages: list[tuple[str, str]] = []

    class FakeRedis:
        def ping(self) -> None:
            return None

    monkeypatch.setenv("REDIS_URL", "redis://red-renderprivate:6379")
    monkeypatch.setitem(sys.modules, "redis", SimpleNamespace(Redis=SimpleNamespace(from_url=lambda *args, **kwargs: FakeRedis())))
    monkeypatch.setattr(prebot.logger, "warning", lambda message, marker, endpoint: messages.append((marker, endpoint)))

    first = prebot._connect_redis_prebot()
    second = prebot._connect_redis_prebot()

    assert first[0] is not None
    assert second[0] is not None
    assert messages == [(prebot._MARKER, "redis://***@red-renderprivate:6379")]
