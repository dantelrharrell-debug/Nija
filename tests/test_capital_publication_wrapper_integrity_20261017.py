"""Regression coverage for the v142 capital wrapper-installation ownership proof.

Copied functools.wraps metadata does not prove the live refresh owner or
publication fence is installed. No test grants execution authority, refreshes
capital, or touches an exchange.
"""
from __future__ import annotations

from functools import wraps
from types import SimpleNamespace
import threading
import time
from datetime import datetime, timedelta, timezone

from bot import capital_publication_liveness_v142_patch as v142


def _fake_execute(self, broker_map, trigger="coordinator", open_exposure_usd=0.0):
    return "untouched"


def _fake_publish(self, snapshot, writer_id):
    return True


def test_copied_marker_alone_is_never_an_ownership_proof():
    @wraps(_fake_execute)
    def impostor(*args, **kwargs):
        return _fake_execute(*args, **kwargs)

    setattr(impostor, v142._PATCH_ATTR, True)
    assert not v142._has_exact_v142_wrapper(impostor, "execute_refresh_v142")
    assert not v142._has_exact_v142_wrapper(impostor, "publish_snapshot_v142")


def test_real_v142_execute_wrapper_remains_proven_under_other_wrappers(monkeypatch):
    from bot import capital_flow_state_machine as flow

    monkeypatch.setattr(flow.CapitalRefreshCoordinator, "execute_refresh", _fake_execute)
    assert v142._patch_coordinator_execute()
    real_wrapper = flow.CapitalRefreshCoordinator.execute_refresh
    assert v142._has_exact_v142_wrapper(real_wrapper, "execute_refresh_v142")

    @wraps(real_wrapper)
    def outer(*args, **kwargs):
        return real_wrapper(*args, **kwargs)

    monkeypatch.setattr(flow.CapitalRefreshCoordinator, "execute_refresh", outer)
    assert v142._has_exact_v142_wrapper(outer, "execute_refresh_v142")
    assert v142._patch_coordinator_execute()
    assert flow.CapitalRefreshCoordinator.execute_refresh is outer


def test_stale_marker_does_not_block_reinstallation_of_execute_wrapper(monkeypatch):
    from bot import capital_flow_state_machine as flow

    @wraps(_fake_execute)
    def unrelated(*args, **kwargs):
        return _fake_execute(*args, **kwargs)

    setattr(unrelated, v142._PATCH_ATTR, True)
    monkeypatch.setattr(flow.CapitalRefreshCoordinator, "execute_refresh", unrelated)
    assert not v142._has_exact_v142_wrapper(unrelated, "execute_refresh_v142")

    assert v142._patch_coordinator_execute()
    repaired = flow.CapitalRefreshCoordinator.execute_refresh
    assert repaired is not unrelated
    assert repaired.__wrapped__ is unrelated
    assert v142._has_exact_v142_wrapper(repaired, "execute_refresh_v142")


def test_stale_marker_does_not_block_reinstallation_of_publication_fence(monkeypatch):
    from bot import capital_authority as ca

    @wraps(_fake_publish)
    def unrelated(*args, **kwargs):
        return _fake_publish(*args, **kwargs)

    setattr(unrelated, v142._PATCH_ATTR, True)
    monkeypatch.setattr(ca.CapitalAuthority, "publish_snapshot", unrelated)
    assert not v142._has_exact_v142_wrapper(unrelated, "publish_snapshot_v142")

    assert v142._patch_publication_generation_fence()
    repaired = ca.CapitalAuthority.publish_snapshot
    assert repaired is not unrelated
    assert repaired.__wrapped__ is unrelated
    assert v142._has_exact_v142_wrapper(repaired, "publish_snapshot_v142")
    assert v142._patch_publication_generation_fence()
    assert ca.CapitalAuthority.publish_snapshot is repaired


def test_stale_untracked_owner_log_names_missing_wrapper_without_changing_rollover(monkeypatch, caplog):
    from bot import capital_publication_deadline_v137_patch as v137

    now = datetime.now(timezone.utc)
    authority = SimpleNamespace(
        get_snapshot_publication_status=lambda: SimpleNamespace(
            accepted=True, stale=False, reason="accepted",
            timestamp=now - timedelta(seconds=91),
            expiry=now - timedelta(seconds=1),
        )
    )
    old = SimpleNamespace(
        _in_flight=True,
        _boot=SimpleNamespace(state=SimpleNamespace(value="RUNNING")),
        _nija_v142_sync_owner_thread=threading.current_thread(),
        _nija_v142_sync_started_monotonic=time.monotonic() - 120.0,
    )
    replacement = SimpleNamespace(_in_flight=False)
    manager = SimpleNamespace(_capital_coordinator=old)
    monkeypatch.setattr(v142, "_authority", lambda: authority)
    monkeypatch.setattr(v142, "_runtime_pipeline_deadline_seconds", lambda: 80.0)

    def rollover(target, *, expected_old=None, reason):
        assert expected_old is old
        assert reason == "untracked_inflight_with_expired_publication"
        target._capital_coordinator = replacement
        return replacement

    monkeypatch.setattr(v142, "_rollover_coordinator", rollover)
    caplog.set_level("WARNING", logger="nija.capital_publication_liveness_v142")
    assert v137._publication_meta(authority, now=now)[0] is False
    assert v142._coordinator_in_flight_v142(manager) is False
    assert manager._capital_coordinator is replacement
    assert "sync_owner_present=True" in caplog.text
    assert "sync_owner_alive=True" in caplog.text
    assert "execute_wrapper_verified=False" in caplog.text
    assert "publication_expiry_unchanged=true" in caplog.text
