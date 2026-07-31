from __future__ import annotations

import os
import threading
import types

import bot.stalled_writer_release_guard_v22 as guard


def _snapshot(**overrides):
    values = {
        "production_intent": True,
        "writer_acquired": True,
        "token": "1090",
        "generation": "1738",
        "state": "LIVE_PENDING_CONFIRMATION",
        "authority": False,
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


def test_live_pending_is_production_intent_without_live_capital_verified(monkeypatch):
    monkeypatch.delenv("LIVE_CAPITAL_VERIFIED", raising=False)
    monkeypatch.delenv("NIJA_EXECUTION_ACTIVE", raising=False)
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_PENDING_CONFIRMATION")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")

    assert guard._production_writer_intent() is True


def test_runtime_object_proves_lease_when_env_boolean_drifts(monkeypatch):
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "1090")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "1738")
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "0")
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_PENDING_CONFIRMATION")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setattr(guard, "_manager_snapshot", lambda: (False, False, False))
    monkeypatch.setattr(guard, "_capital_snapshot", lambda: (False, 0.0, True, 0))

    bot_main = types.SimpleNamespace(
        _writer_authority_runtime=types.SimpleNamespace(acquired=True),
        _shutdown_event=threading.Event(),
    )

    snapshot = guard._runtime_snapshot(bot_main)

    assert snapshot.writer_acquired is True
    assert snapshot.production_intent is True


def test_releases_unready_writer_after_timeout():
    snapshot = _snapshot()

    assert not guard._should_release(snapshot, elapsed_s=359.9, timeout_s=360.0)
    assert guard._should_release(snapshot, elapsed_s=360.0, timeout_s=360.0)
    assert "broker_manager_not_initialized" in guard._release_reason(snapshot)


def test_capital_handoff_corroborates_stale_capital_snapshot(monkeypatch):
    monkeypatch.setenv("NIJA_CAPITAL_READINESS_HANDOFF_V34", "1")

    authority = types.SimpleNamespace(
        is_hydrated=True,
        get_real_capital=lambda: 125.0,
        is_stale=lambda: True,
        valid_brokers=1,
    )
    module = types.SimpleNamespace(get_capital_authority=lambda: authority)
    monkeypatch.setitem(guard.sys.modules, "bot.capital_authority", module)
    monkeypatch.setitem(guard.sys.modules, "capital_authority", module)

    hydrated, capital, stale, valid_brokers = guard._capital_snapshot()

    assert hydrated is True
    assert capital == 125.0
    assert stale is False
    assert valid_brokers == 1


def test_does_not_release_when_v34_handoff_corroborates_capital(monkeypatch):
    monkeypatch.setenv("NIJA_CAPITAL_READINESS_HANDOFF_V34", "1")
    monkeypatch.setenv("NIJA_WRITER_LEASE_ACQUIRED", "1")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "1090")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "1738")
    monkeypatch.setenv("NIJA_RUNTIME_TRADING_STATE", "LIVE_PENDING_CONFIRMATION")
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")
    monkeypatch.setenv("NIJA_RUNTIME_EXECUTION_AUTHORITY", "0")
    monkeypatch.setattr(guard, "_manager_snapshot", lambda: (True, True, True))

    authority = types.SimpleNamespace(
        is_hydrated=True,
        get_real_capital=lambda: 125.0,
        is_stale=lambda: True,
        valid_brokers=1,
    )
    module = types.SimpleNamespace(get_capital_authority=lambda: authority)
    monkeypatch.setitem(guard.sys.modules, "bot.capital_authority", module)
    monkeypatch.setitem(guard.sys.modules, "capital_authority", module)

    bot_main = types.SimpleNamespace(
        _writer_authority_runtime=types.SimpleNamespace(acquired=True),
        _shutdown_event=threading.Event(),
    )

    snapshot = guard._runtime_snapshot(bot_main)

    assert snapshot.manager_ready is True
    assert snapshot.capital_ready is True
    assert not guard._should_release(snapshot, elapsed_s=999.0, timeout_s=30.0)


def test_never_releases_live_active_or_authorized_runtime():
    live_active = _snapshot(
        state="LIVE_ACTIVE",
        authority=True,
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


def test_releases_early_boot_stall_regardless_of_production_intent(monkeypatch):
    """An instance stuck before any LIVE_* state (e.g. broker connection hangs in
    prepare_canonical_broker_runtime) has state='OFF' and production_intent=False.
    The guard must still release the lock after the timeout so the new instance
    can acquire it."""
    monkeypatch.setenv("DRY_RUN_MODE", "false")
    monkeypatch.setenv("PAPER_MODE", "false")

    early_boot = _snapshot(
        production_intent=False,
        state="OFF",
        writer_acquired=True,
        authority=False,
        shutdown_requested=False,
        fsm_initialized=False,
        sources_registered=False,
        attempts_finalized=False,
        hydrated=False,
        capital=0.0,
        stale=True,
        valid_brokers=0,
    )

    assert not guard._should_release(early_boot, elapsed_s=359.9, timeout_s=360.0)
    assert guard._should_release(early_boot, elapsed_s=360.0, timeout_s=360.0)


def test_does_not_release_dry_run_early_boot_stall(monkeypatch):
    monkeypatch.setenv("DRY_RUN_MODE", "true")
    monkeypatch.setenv("PAPER_MODE", "false")

    dry_run = _snapshot(
        production_intent=False,
        state="OFF",
        writer_acquired=True,
        authority=False,
        shutdown_requested=False,
        fsm_initialized=False,
        sources_registered=False,
        attempts_finalized=False,
        hydrated=False,
        capital=0.0,
        stale=True,
        valid_brokers=0,
    )

    assert not guard._should_release(dry_run, elapsed_s=999.0, timeout_s=30.0)


def test_attempt_emergency_stop_recovery_clears_and_converges(monkeypatch):
    calls = []

    clear_module = types.SimpleNamespace(run_once=lambda: 1)
    convergence_module = types.SimpleNamespace(
        converge_runtime_authority=lambda source: calls.append(source)
    )
    monkeypatch.setitem(guard.sys.modules, "bot.operator_emergency_stop_clear_patch", clear_module)
    monkeypatch.setitem(
        guard.sys.modules,
        "bot.runtime_authority_convergence_repair_patch",
        convergence_module,
    )

    assert guard._attempt_emergency_stop_recovery("unit_test") == 1
    assert calls == ["stalled_writer_emergency_stop_recovery:unit_test"]


def test_trigger_releases_current_lease_and_exits(monkeypatch):
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
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "1090")
    monkeypatch.setenv("NIJA_WRITER_LEASE_GENERATION", "1738")
    monkeypatch.setenv("NIJA_STALLED_WRITER_EXIT_PROCESS", "true")
    monkeypatch.setattr(guard, "_terminate_process", lambda code: exit_codes.append(code))

    guard._trigger_release(fake_bot_main, _snapshot(), "broker_manager_not_initialized")

    assert shutdown_event.is_set()
    assert release_calls == [True]
    assert exit_codes == [78]
    assert os.environ["NIJA_RUNTIME_EXECUTION_AUTHORITY"] == "0"
    assert os.environ["NIJA_RUNTIME_TRADING_STATE"] == "OFF"
