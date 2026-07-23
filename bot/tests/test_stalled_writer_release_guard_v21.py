from __future__ import annotations

import os
import threading
import types

import bot.stalled_writer_release_guard_v21 as guard


def _snapshot(**overrides):
    values = {
        "live_mode": True,
        "writer_acquired": True,
        "token": "token-1234",
        "generation": "42",
        "state": "LIVE_PENDING_CONFIRMATION",
        "authority": False,
        "startup_complete": False,
        "shutdown_requested": False,
        "fsm_initialized": False,
        "sources_registered": False,
        "attempts_finalized": False,
        "hydrated": False,
        "capital": 0.0,
        "stale": True,
        "valid_brokers": 0,
    }
    values.update(overrides)
    return guard.RuntimeSnapshot(**values)


def test_releases_only_after_timeout_for_nonlive_uninitialized_writer():
    snapshot = _snapshot()

    assert not guard._should_release(snapshot, elapsed_s=359.9, timeout_s=360.0)
    assert guard._should_release(snapshot, elapsed_s=360.0, timeout_s=360.0)
    assert "broker_manager_not_initialized" in guard._release_reason(snapshot)
    assert "execution_authority=0" in guard._release_reason(snapshot)


def test_never_releases_live_active_or_authorized_runtime():
    live_active = _snapshot(
        state="LIVE_ACTIVE",
        authority=True,
        startup_complete=True,
        fsm_initialized=True,
        sources_registered=True,
        attempts_finalized=True,
        hydrated=True,
        capital=125.0,
        stale=False,
        valid_brokers=1,
    )
    authorized_pending = _snapshot(authority=True)

    assert not guard._should_release(live_active, elapsed_s=999.0, timeout_s=30.0)
    assert not guard._should_release(authorized_pending, elapsed_s=999.0, timeout_s=30.0)


def test_trigger_requests_shutdown_releases_own_lease_and_exits(monkeypatch):
    shutdown_event = threading.Event()
    release_calls = []
    exit_codes = []

    def release():
        release_calls.append(True)
        os.environ["NIJA_WRITER_LEASE_ACQUIRED"] = "0"
        os.environ.pop("NIJA_WRITER_FENCING_TOKEN", None)
        os.environ.pop("NIJA_WRITER_LEASE_GENERATION", None)

    fake_bot_main = types.SimpleNamespace(
        _shutdown_event=shutdown_event,
        _release_writer_authority=release,
    )

    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "token-1234")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "42")
    monkeypatch.setenv("NIJA_STALLED_WRITER_EXIT_PROCESS", "true")
    monkeypatch.setattr(guard, "_terminate_process", lambda code: exit_codes.append(code))

    snapshot = _snapshot()
    guard._trigger_release(fake_bot_main, snapshot, "broker_manager_not_initialized")

    assert shutdown_event.is_set()
    assert release_calls == [True]
    assert exit_codes == [78]
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert os.environ["NIJA_RUNTIME_TRADING_STATE"] == "OFF"
    assert os.environ["NIJA_STALLED_WRITER_RELEASE_TRIGGERED"] == "1"


def test_does_not_release_when_writer_lineage_is_missing():
    snapshot = _snapshot(writer_acquired=False, token="", generation="")
    assert not guard._should_release(snapshot, elapsed_s=999.0, timeout_s=30.0)
