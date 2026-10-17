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


def test_v142_repair_preserves_v176_proactive_deadline_context(monkeypatch):
    """Surviving inner v176 wrappers cannot be relied on for caller context."""
    from bot import capital_flow_state_machine as flow
    from bot import runtime_capital_refresh_ownership_v166_patch as v166
    from bot import runtime_capital_pipeline_completion_v176_patch as v176

    monkeypatch.setattr(v142, "_runtime_pipeline_deadline_seconds", lambda: 80.0)
    monkeypatch.setattr(v166, "_proactive_pipeline_deadline_seconds", lambda: 40.0)
    assert v176._patch_proactive_deadline_context()

    @wraps(_fake_execute)
    def surviving_v176(*args, **kwargs):
        return _fake_execute(*args, **kwargs)

    setattr(surviving_v176, v176._PATCH_ATTR, True)
    setattr(surviving_v176, v142._PATCH_ATTR, True)  # copied stale marker
    monkeypatch.setattr(flow.CapitalRefreshCoordinator, "execute_refresh", surviving_v176)
    assert v142._patch_coordinator_execute()
    repaired = flow.CapitalRefreshCoordinator.execute_refresh
    assert repaired.__wrapped__ is surviving_v176

    assert not v166._is_proactive_trigger()
    assert v142._runtime_deadline_with_caller_context_v142(
        "publication_deadline_v137"
    ) == 40.0
    assert v142._runtime_deadline_with_caller_context_v142("startup") == 80.0
    assert not v166._is_proactive_trigger()


def test_v142_repaired_runtime_path_uses_proactive_caller_deadline(monkeypatch):
    """Exercise the actual worker wait, not just the deadline helper."""
    from bot import capital_flow_state_machine as flow
    from bot import runtime_capital_refresh_ownership_v166_patch as v166
    from bot import runtime_capital_pipeline_completion_v176_patch as v176

    monkeypatch.setattr(v142, "_reassert_bounded_fetch_contract", lambda: (True, "ok"))
    monkeypatch.setattr(v142, "_runtime_terminal", lambda _: True)
    monkeypatch.setattr(v142, "_runtime_pipeline_deadline_seconds", lambda: 80.0)
    monkeypatch.setattr(v166, "_proactive_pipeline_deadline_seconds", lambda: 40.0)
    assert v176._patch_proactive_deadline_context()

    @wraps(_fake_execute)
    def surviving_v176(*args, **kwargs):
        raise AssertionError("runtime worker must not use stale inner execute chain")

    setattr(surviving_v176, v142._PATCH_ATTR, True)
    setattr(surviving_v176, v176._PATCH_ATTR, True)
    monkeypatch.setattr(flow.CapitalRefreshCoordinator, "execute_refresh", surviving_v176)
    assert v142._patch_coordinator_execute()

    observed = []
    original_deadline = v142._runtime_pipeline_deadline_seconds

    def capture_deadline():
        deadline = original_deadline()
        observed.append((v166._is_proactive_trigger(), deadline))
        return deadline

    monkeypatch.setattr(v142, "_runtime_pipeline_deadline_seconds", capture_deadline)
    coordinator = SimpleNamespace(
        _lock=threading.RLock(),
        _in_flight=False,
        _pipeline=lambda **kwargs: {"fresh": True},
    )
    result = flow.CapitalRefreshCoordinator.execute_refresh(
        coordinator, {}, trigger="publication_deadline_v137"
    )
    assert result == {"fresh": True}
    assert observed == [(True, 40.0)]
    assert not v166._is_proactive_trigger()


def _runtime_coordinator(pipeline):
    return SimpleNamespace(
        _lock=threading.RLock(),
        _in_flight=False,
        _pipeline=pipeline,
    )


def _install_v142_outside_v176(monkeypatch, *, callback):
    from bot import capital_flow_state_machine as flow
    from bot import runtime_capital_reactivation_v176_patch as v176

    monkeypatch.setattr(flow.CapitalRefreshCoordinator, "execute_refresh", _fake_execute)
    assert v176._patch_coordinator()
    monkeypatch.setattr(v176, "_rearm_after_publication", callback)
    monkeypatch.setattr(v142, "_reassert_bounded_fetch_contract", lambda: (True, "ok"))
    monkeypatch.setattr(v142, "_runtime_terminal", lambda _coordinator: True)
    monkeypatch.setattr(v142, "_runtime_pipeline_deadline_seconds", lambda: 0.02)
    monkeypatch.setattr(v142, "_runtime_publication_matches_result", lambda _snapshot: True)
    monkeypatch.setattr(v142, "_canonical_manager", lambda: None)
    assert v142._patch_coordinator_execute()
    return flow.CapitalRefreshCoordinator.execute_refresh


def test_v142_outside_v176_rearms_only_successful_current_publication(monkeypatch):
    calls = []
    execute = _install_v142_outside_v176(monkeypatch, callback=calls.append)
    old_active = v142._ACTIVE_GENERATION
    old_next = v142._NEXT_GENERATION
    old_rollover = v142._ROLLOVER_OCCURRED
    try:
        snapshot = SimpleNamespace(computed_at=object())
        assert execute(_runtime_coordinator(lambda **_kwargs: snapshot), {}) is snapshot
        assert calls == ["coordinator"]

        calls.clear()
        assert execute(
            _runtime_coordinator(lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("failed"))),
            {},
        ) is None
        assert calls == []

        monkeypatch.setattr(v142, "_runtime_publication_matches_result", lambda _snapshot: False)
        assert execute(_runtime_coordinator(lambda **_kwargs: snapshot), {}) is snapshot
        assert calls == []

        monkeypatch.setattr(v142, "_runtime_publication_matches_result", lambda _snapshot: True)

        def retired_pipeline(**_kwargs):
            v142._retire_generation(
                getattr(v142._LOCAL, "refresh_generation", None),
                "test_retired_generation",
            )
            return snapshot

        assert execute(_runtime_coordinator(retired_pipeline), {}) is snapshot
        assert calls == []
    finally:
        v142._ACTIVE_GENERATION = old_active
        v142._NEXT_GENERATION = old_next
        v142._ROLLOVER_OCCURRED = old_rollover


def test_v176_outside_v142_rearms_once_after_runtime_refresh(monkeypatch):
    from bot import capital_flow_state_machine as flow
    from bot import runtime_capital_reactivation_v176_patch as v176

    calls = []
    monkeypatch.setattr(flow.CapitalRefreshCoordinator, "execute_refresh", _fake_execute)
    monkeypatch.setattr(v142, "_reassert_bounded_fetch_contract", lambda: (True, "ok"))
    monkeypatch.setattr(v142, "_runtime_terminal", lambda _coordinator: True)
    monkeypatch.setattr(v142, "_runtime_pipeline_deadline_seconds", lambda: 0.02)
    monkeypatch.setattr(v142, "_runtime_publication_matches_result", lambda _snapshot: True)
    monkeypatch.setattr(v142, "_canonical_manager", lambda: None)
    assert v142._patch_coordinator_execute()
    assert v176._patch_coordinator()
    monkeypatch.setattr(v176, "_rearm_after_publication", calls.append)

    old_active = v142._ACTIVE_GENERATION
    old_next = v142._NEXT_GENERATION
    old_rollover = v142._ROLLOVER_OCCURRED
    try:
        result = SimpleNamespace()
        execute = flow.CapitalRefreshCoordinator.execute_refresh
        assert execute(_runtime_coordinator(lambda **_kwargs: result), {}) is result
        assert calls == ["coordinator"]
    finally:
        v142._ACTIVE_GENERATION = old_active
        v142._NEXT_GENERATION = old_next
        v142._ROLLOVER_OCCURRED = old_rollover


def test_rearm_wrapper_detection_uses_code_identity_not_copied_markers(monkeypatch):
    from bot import capital_flow_state_machine as flow
    from bot import runtime_capital_reactivation_v176_patch as v176

    _install_v142_outside_v176(monkeypatch, callback=lambda _trigger: None)
    wrapper_code = v176._EXECUTE_REFRESH_V176_CODE
    assert wrapper_code is not None
    assert v142._callable_chain_has_code(
        flow.CapitalRefreshCoordinator.execute_refresh,
        wrapper_code,
        v176.__name__,
    )

    @wraps(_fake_execute)
    def copied_marker(*args, **kwargs):
        return _fake_execute(*args, **kwargs)

    setattr(copied_marker, v176._PATCH_ATTR, True)
    assert not v142._callable_chain_has_code(copied_marker, wrapper_code, v176.__name__)


def test_v142_timeout_does_not_rearm_inner_v176(monkeypatch):
    import threading as threading_module

    calls = []
    execute = _install_v142_outside_v176(monkeypatch, callback=calls.append)
    started = threading_module.Event()
    release = threading_module.Event()
    finished = threading_module.Event()
    old_active = v142._ACTIVE_GENERATION
    old_next = v142._NEXT_GENERATION
    old_rollover = v142._ROLLOVER_OCCURRED

    def slow_pipeline(**_kwargs):
        started.set()
        release.wait(1.0)
        finished.set()
        return SimpleNamespace()

    try:
        assert execute(_runtime_coordinator(slow_pipeline), {}) is None
        assert started.is_set()
        assert calls == []
    finally:
        release.set()
        assert finished.wait(1.0)
        v142._ACTIVE_GENERATION = old_active
        v142._NEXT_GENERATION = old_next
        v142._ROLLOVER_OCCURRED = old_rollover


def _bootstrap_publication_chain(monkeypatch, *, v142_is_outer):
    from bot import capital_authority as ca
    from bot import runtime_bootstrap_capital_publication_v179_patch as v179

    calls = []

    def base_publish(self, snapshot, writer_id):
        calls.append((snapshot, writer_id))
        return writer_id == self._AUTHORIZED_WRITER_ID

    monkeypatch.setattr(ca.CapitalAuthority, "publish_snapshot", base_publish)
    monkeypatch.setattr(v179, "_canonical_ca_module", lambda: ca)
    monkeypatch.setattr(v179, "_v142_module", lambda: v142)
    if not v142_is_outer:
        assert v142._patch_publication_generation_fence()
    assert v179._patch_capital_publish_seed_context()
    if v142_is_outer:
        assert v142._patch_publication_generation_fence()
    return ca, v179, calls


def _reset_generation_context(monkeypatch, *, active):
    monkeypatch.setattr(v142, "_ACTIVE_GENERATION", active)
    monkeypatch.setattr(v142, "_NEXT_GENERATION", active)
    monkeypatch.setattr(v142, "_ROLLOVER_OCCURRED", True)
    try:
        delattr(v142._LOCAL, "refresh_generation")
    except AttributeError:
        pass


def test_v142_outer_fence_allows_only_exact_authorized_v179_seed(monkeypatch):
    ca, v179, calls = _bootstrap_publication_chain(monkeypatch, v142_is_outer=True)
    _reset_generation_context(monkeypatch, active=42)
    authority = object.__new__(ca.CapitalAuthority)
    authority._AUTHORIZED_WRITER_ID = "mabm_capital_refresh_coordinator"

    authorized_seed = SimpleNamespace()
    v179._mark_bootstrap_seed(authorized_seed)
    assert authority.publish_snapshot(
        authorized_seed, authority._AUTHORIZED_WRITER_ID
    ) is True
    assert calls == [(authorized_seed, authority._AUTHORIZED_WRITER_ID)]
    assert not v179._is_marked_bootstrap_seed(authorized_seed)
    assert not hasattr(v142._LOCAL, "refresh_generation")

    unmarked = SimpleNamespace()
    assert authority.publish_snapshot(unmarked, authority._AUTHORIZED_WRITER_ID) is False
    assert calls == [(authorized_seed, authority._AUTHORIZED_WRITER_ID)]

    unauthorized_seed = SimpleNamespace()
    v179._mark_bootstrap_seed(unauthorized_seed)
    assert authority.publish_snapshot(unauthorized_seed, "untrusted-writer") is False
    assert calls[-1] == (unauthorized_seed, "untrusted-writer")
    assert not v179._is_marked_bootstrap_seed(unauthorized_seed)

    retired_seed = SimpleNamespace()
    v179._mark_bootstrap_seed(retired_seed)
    v142._LOCAL.refresh_generation = 41
    assert authority.publish_snapshot(
        retired_seed, authority._AUTHORIZED_WRITER_ID
    ) is False
    assert calls[-1] == (unauthorized_seed, "untrusted-writer")
    assert not v179._is_marked_bootstrap_seed(retired_seed)
    assert v142._LOCAL.refresh_generation == 41
    delattr(v142._LOCAL, "refresh_generation")


def test_v179_outer_seed_context_preserves_v142_publication_fence(monkeypatch):
    ca, v179, calls = _bootstrap_publication_chain(monkeypatch, v142_is_outer=False)
    _reset_generation_context(monkeypatch, active=43)
    authority = object.__new__(ca.CapitalAuthority)
    authority._AUTHORIZED_WRITER_ID = "mabm_capital_refresh_coordinator"
    seed = SimpleNamespace()
    v179._mark_bootstrap_seed(seed)

    assert authority.publish_snapshot(seed, authority._AUTHORIZED_WRITER_ID) is True
    assert calls == [(seed, authority._AUTHORIZED_WRITER_ID)]
    assert not v179._is_marked_bootstrap_seed(seed)
    assert not hasattr(v142._LOCAL, "refresh_generation")
