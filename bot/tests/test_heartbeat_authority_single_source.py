from __future__ import annotations

import json
import os
import time

from bot.heartbeat_state import reset_heartbeat_state_for_testing
from bot.heartbeat_authority_single_source_patch import (
    heartbeat_check,
    refresh_heartbeat,
)


def test_transient_probe_failure_cannot_invalidate_fresh_heartbeat(monkeypatch):
    """ACTIVE + recently refreshed must not become unhealthy on one failed probe."""
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "41")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_ACTIVE", "1")
    state = reset_heartbeat_state_for_testing()
    state.record_heartbeat(generation=41)

    state.record_heartbeat_failure()

    healthy, age_s, authoritative, _ts = state.health_for_generation(
        expected_generation=41,
        max_age_s=120.0,
    )
    assert authoritative is True
    assert age_s < 1.0
    assert healthy is True


def test_freshness_uses_monotonic_not_wall_clock(monkeypatch):
    """A wall-clock jump cannot make a recently successful heartbeat stale."""
    state = reset_heartbeat_state_for_testing()
    real_epoch = time.time()
    real_mono = time.monotonic()
    state.record_heartbeat(
        generation=7,
        timestamp=real_epoch,
        monotonic_timestamp=real_mono,
    )

    # The freshness reader uses monotonic time only. An extreme epoch jump must
    # not change its result.
    monkeypatch.setattr("bot.heartbeat_state.time.time", lambda: real_epoch + 86400.0)
    healthy, age_s, authoritative, heartbeat_ts = state.health_for_generation(
        expected_generation=7,
        max_age_s=120.0,
    )

    assert authoritative is True
    assert healthy is True
    assert age_s < 1.0
    assert heartbeat_ts == real_epoch


def test_successful_refresh_updates_env_marker_and_canonical_state(monkeypatch, tmp_path):
    """Every refresh publishes the same epoch to env, marker, and canonical state."""
    marker = tmp_path / "heartbeat_verified.flag"
    monkeypatch.setenv("HEARTBEAT_MARKER_PATH", str(marker))
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "88")
    monkeypatch.setenv("NIJA_WRITER_HEARTBEAT_MAX_AGE_S", "120")
    state = reset_heartbeat_state_for_testing()

    heartbeat_ts = refresh_heartbeat(source="test", generation=88)

    assert heartbeat_ts > 0.0
    assert os.environ["NIJA_WRITER_HEARTBEAT_ACTIVE"] == "1"
    assert float(os.environ["NIJA_WRITER_HEARTBEAT_ALIVE_TS"]) == heartbeat_ts
    assert float(os.environ["NIJA_WRITER_HEARTBEAT_LAST_TS"]) == heartbeat_ts

    payload = json.loads(marker.read_text(encoding="utf-8"))
    assert payload["verified_at_epoch"] == heartbeat_ts
    assert payload["stage"] == "FILL_VERIFY"

    snapshot = state.snapshot()
    assert snapshot.timestamp == heartbeat_ts
    assert snapshot.marker_timestamp == heartbeat_ts
    assert snapshot.generation == 88
    assert snapshot.healthy is True

    healthy, _now, checked_ts, age_s, authoritative = heartbeat_check(source="test")
    assert authoritative is True
    assert checked_ts == heartbeat_ts
    assert age_s < 1.0
    assert healthy is True


def test_canonical_freshness_expires_when_heartbeat_actually_stops(monkeypatch):
    """A stopped heartbeat still fails closed once its monotonic age exceeds max age."""
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "9")
    state = reset_heartbeat_state_for_testing()
    now_epoch = time.time()
    now_mono = time.monotonic()
    state.record_heartbeat(
        generation=9,
        timestamp=now_epoch,
        monotonic_timestamp=now_mono - 121.0,
    )

    healthy, age_s, authoritative, _ts = state.health_for_generation(
        expected_generation=9,
        max_age_s=120.0,
    )
    assert authoritative is True
    assert age_s >= 121.0
    assert healthy is False


def test_generation_change_invalidates_old_heartbeat():
    """A heartbeat from an old fencing generation cannot authorize a new writer."""
    state = reset_heartbeat_state_for_testing()
    state.record_heartbeat(generation=12)

    healthy, _age_s, authoritative, _ts = state.health_for_generation(
        expected_generation=13,
        max_age_s=120.0,
    )
    assert authoritative is False
    assert healthy is False
