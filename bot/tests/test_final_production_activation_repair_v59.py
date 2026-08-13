from __future__ import annotations

import os
import sys
import threading
import time
import types

from bot import final_production_activation_repair_v59_patch as repair


def test_stalled_writer_is_diagnostic_only_on_canonical_path(monkeypatch):
    monkeypatch.setenv("NIJA_CANONICAL_ENTRYPOINT_FAST_PATH", "1")
    monkeypatch.setenv("NIJA_DEFER_RUNTIME_SITE_HOOKS", "1")
    import bot.stalled_writer_release_guard_v22 as guard

    original_bootstrap = guard._attempt_bootstrap_progression
    original_authority = guard._attempt_authority_convergence_retry
    try:
        assert repair._patch_stalled_writer_diagnostic_only() is True
        assert guard._attempt_bootstrap_progression("test") is False
        assert guard._attempt_authority_convergence_retry("test") is False
    finally:
        guard._attempt_bootstrap_progression = original_bootstrap
        guard._attempt_authority_convergence_retry = original_authority


def test_writer_registration_reconciliation_dispatches_async(monkeypatch):
    import bot.entrypoint_writer_authority as module

    original = module.EntrypointWriterAuthority._notify_runtime_reconciliation
    try:
        assert repair._patch_writer_reconciliation_async() is True
        runtime = module.EntrypointWriterAuthority()
        started = threading.Event()
        release = threading.Event()

        def slow_reconcile(trigger):
            started.set()
            release.wait(timeout=2.0)

        runtime._run_runtime_reconciliation = slow_reconcile
        t0 = time.monotonic()
        runtime._notify_runtime_reconciliation("core_thread_registered")
        elapsed = time.monotonic() - t0

        assert elapsed < 0.25
        assert started.wait(timeout=1.0)
        release.set()
        worker = runtime._runtime_reconcile_thread
        if worker is not None:
            worker.join(timeout=1.0)
    finally:
        module.EntrypointWriterAuthority._notify_runtime_reconciliation = original


def test_writer_reconciliation_coalesces_and_replays_latest_trigger(monkeypatch):
    import bot.entrypoint_writer_authority as module

    original = module.EntrypointWriterAuthority._notify_runtime_reconciliation
    try:
        assert repair._patch_writer_reconciliation_async() is True
        runtime = module.EntrypointWriterAuthority()
        first_started = threading.Event()
        release_first = threading.Event()
        replay_finished = threading.Event()
        calls: list[str] = []

        def reconcile(trigger: str) -> None:
            calls.append(trigger)
            if len(calls) == 1:
                first_started.set()
                release_first.wait(timeout=2.0)
            else:
                replay_finished.set()

        runtime._run_runtime_reconciliation = reconcile
        runtime._notify_runtime_reconciliation("watchdog")
        assert first_started.wait(timeout=1.0)

        runtime._notify_runtime_reconciliation("heartbeat_renewed")
        runtime._notify_runtime_reconciliation("writer_authority_active")
        release_first.set()

        assert replay_finished.wait(timeout=1.0)
        worker = runtime._runtime_reconcile_thread
        if worker is not None:
            worker.join(timeout=1.0)

        assert calls == ["watchdog", "writer_authority_active"]
        assert runtime._runtime_reconcile_thread is None
        assert getattr(runtime, "_runtime_reconcile_pending_trigger", None) is None
    finally:
        module.EntrypointWriterAuthority._notify_runtime_reconciliation = original


def test_proof_convergence_starts_existing_monitors(monkeypatch):
    calls = []

    identity = types.ModuleType("runtime_module_identity_convergence_patch")
    identity.install = lambda: calls.append("identity")
    v15 = types.ModuleType("runtime_convergence_v15_patch")
    v15.install = lambda: calls.append("v15") or True
    v16 = types.ModuleType("preactivation_readiness_convergence_v16_patch")
    v16._mark_proven_readiness = lambda proofs: (False, [])
    v16.install = lambda: calls.append("v16") or True

    monkeypatch.setitem(sys.modules, identity.__name__, identity)
    monkeypatch.setitem(sys.modules, v15.__name__, v15)
    monkeypatch.setitem(sys.modules, v16.__name__, v16)

    assert repair._install_proof_convergence() is True
    assert calls == ["identity", "v15", "v16"]


def test_first_snapshot_uses_existing_fail_closed_bridge(monkeypatch):
    bridge = types.ModuleType("bot.activation_snapshot_bridge_patch")
    calls = []
    bridge.install_import_hook = lambda: calls.append("bridge")
    monkeypatch.setitem(sys.modules, bridge.__name__, bridge)

    assert repair._install_first_snapshot_bridge() is True
    assert calls == ["bridge"]


def test_v59_declared_after_v58_in_canonical_entrypoint():
    path = os.path.join(os.path.dirname(__file__), "..", "bot.py")
    source = open(path, encoding="utf-8").read()
    assert source.index("FINAL_PRODUCTION_ACTIVATION_V58") < source.index("FINAL_PRODUCTION_ACTIVATION_V59")


def test_v59_does_not_force_trade_or_lower_thresholds():
    path = os.path.join(os.path.dirname(__file__), "..", "final_production_activation_repair_v59_patch.py")
    source = open(path, encoding="utf-8").read()
    for forbidden in (
        "MIN_ENTRY_SCORE =",
        "MIN_TRADE_USD =",
        "FORCE_TRADE =",
        "NIJA_FORCE_ACTIVATION =",
        "_first_snap_accepted = True",
    ):
        assert forbidden not in source
