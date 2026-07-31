from __future__ import annotations

import os


def test_timeout_grace_suppresses_lockdown_when_writer_lock_matches(monkeypatch):
    from bot import authority_heartbeat
    from bot import authority_heartbeat_timeout_grace_patch as patch

    class FakeRedis:
        def get(self, key):
            if key == "nija:lease:generation":
                return b"2881"
            if key == "nija:writer_lock:platform":
                return b"token-123:owner"
            return None

        def set(self, *args, **kwargs):
            return True

        def expire(self, *args, **kwargs):
            return True

    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "token-123")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "2881")
    monkeypatch.setenv("NIJA_WRITER_SCOPE", "platform")
    monkeypatch.setenv("HEARTBEAT_MARKER_PATH", os.devnull)
    monkeypatch.setattr(patch, "_redis_url", lambda: "redis://example/0")
    monkeypatch.setattr(patch, "_redis_client", lambda redis_url, timeout_s: FakeRedis())
    monkeypatch.setattr(authority_heartbeat, "_write_heartbeat_marker", lambda: None)

    assert patch.install_import_hook() is True

    lockdown_called = []
    monitor = authority_heartbeat.AuthorityHeartbeatMonitor(
        interval_s=999,
        timeout_s=5,
        max_failures=3,
        lockdown_callback=lambda reason: lockdown_called.append(reason),
    )
    monitor._consecutive_failures = 3

    monitor._trigger_lockdown("Authority check timed out after 5.0s")

    assert lockdown_called == []
    assert monitor.is_locked_down is False
    assert monitor.consecutive_failures == 0
    assert os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] == "1"


def test_timeout_grace_denies_when_writer_lock_token_differs(monkeypatch):
    from bot import authority_heartbeat
    from bot import authority_heartbeat_timeout_grace_patch as patch

    class FakeRedis:
        def get(self, key):
            if key == "nija:lease:generation":
                return b"2881"
            if key == "nija:writer_lock:platform":
                return b"other-token:owner"
            return None

    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "token-123")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "2881")
    monkeypatch.setenv("NIJA_WRITER_SCOPE", "platform")
    monkeypatch.setattr(patch, "_redis_url", lambda: "redis://example/0")
    monkeypatch.setattr(patch, "_redis_client", lambda redis_url, timeout_s: FakeRedis())

    assert patch.install_import_hook() is True

    lockdown_called = []
    monitor = authority_heartbeat.AuthorityHeartbeatMonitor(
        interval_s=999,
        timeout_s=5,
        max_failures=3,
        lockdown_callback=lambda reason: lockdown_called.append(reason),
    )
    monitor._consecutive_failures = 3

    monitor._trigger_lockdown("Authority check timed out after 5.0s")

    assert lockdown_called
    assert monitor.is_locked_down is True
