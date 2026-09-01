from __future__ import annotations

import importlib
from dataclasses import replace


def _snapshot(eac, **changes):
    base = eac.RuntimeAuthoritySnapshot(
        ready=False,
        authority_ready=False,
        nonce_ready=True,
        dispatch_health_ready=True,
        dispatch_enabled=False,
        kill_switch_active=False,
        coordinator_state="ACTIVATION_CONVERGING",
        runtime_state="VERIFYING",
        reason="global_epoch_stale",
        lifecycle_phase="BOOT",
    )
    return replace(base, **changes)


def test_bridge_not_trusted_without_v335_scope(monkeypatch):
    v337 = importlib.import_module("bot.runtime_protective_exit_authority_bridge_v337_patch")
    monkeypatch.setattr(v337, "_trusted_close", lambda: False)
    assert v337._trusted_close() is False


def test_hard_exit_proof_fails_closed_on_kill_switch(monkeypatch):
    v337 = importlib.import_module("bot.runtime_protective_exit_authority_bridge_v337_patch")
    eac = importlib.import_module("bot.execution_authority_context")
    monkeypatch.setattr(eac, "runtime_authority_snapshot", lambda: _snapshot(eac, kill_switch_active=True))
    monkeypatch.setattr(eac, "assert_distributed_writer_authority", lambda: None)
    monkeypatch.setattr(eac, "require_startup_execution_authority", lambda **kwargs: {"ready": True})
    monkeypatch.setattr(eac, "is_seak_halted", lambda: False)
    ok, reason, _ = v337._hard_exit_authority_proof()
    assert ok is False
    assert reason == "kill_switch_active"


def test_hard_exit_proof_requires_nonce_and_health(monkeypatch):
    v337 = importlib.import_module("bot.runtime_protective_exit_authority_bridge_v337_patch")
    eac = importlib.import_module("bot.execution_authority_context")
    monkeypatch.setattr(eac, "assert_distributed_writer_authority", lambda: None)
    monkeypatch.setattr(eac, "require_startup_execution_authority", lambda **kwargs: {"ready": True})
    monkeypatch.setattr(eac, "is_seak_halted", lambda: False)
    monkeypatch.setenv("NIJA_EXECUTION_CIRCUIT_STATE", "CLOSED")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "5085")

    monkeypatch.setattr(eac, "runtime_authority_snapshot", lambda: _snapshot(eac, nonce_ready=False))
    ok, reason, _ = v337._hard_exit_authority_proof()
    assert not ok and reason == "nonce_not_ready"

    monkeypatch.setattr(eac, "runtime_authority_snapshot", lambda: _snapshot(eac, dispatch_health_ready=False))
    ok, reason, _ = v337._hard_exit_authority_proof()
    assert not ok and reason == "broker_dispatch_health_not_ready"


def test_hard_exit_proof_accepts_startup_only_block_with_hard_proofs(monkeypatch):
    v337 = importlib.import_module("bot.runtime_protective_exit_authority_bridge_v337_patch")
    eac = importlib.import_module("bot.execution_authority_context")
    monkeypatch.setattr(eac, "runtime_authority_snapshot", lambda: _snapshot(eac))
    monkeypatch.setattr(eac, "assert_distributed_writer_authority", lambda: None)
    monkeypatch.setattr(eac, "require_startup_execution_authority", lambda **kwargs: {"ready": True})
    monkeypatch.setattr(eac, "is_seak_halted", lambda: False)
    monkeypatch.setenv("NIJA_EXECUTION_CIRCUIT_STATE", "CLOSED")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "5085")
    ok, reason, snap = v337._hard_exit_authority_proof()
    assert ok is True
    assert reason == "hard_exit_authority_proven"
    assert snap.lifecycle_phase == "BOOT"
    assert snap.ready is False


def test_hard_exit_proof_does_not_accept_nonstartup_degraded_reason(monkeypatch):
    v337 = importlib.import_module("bot.runtime_protective_exit_authority_bridge_v337_patch")
    eac = importlib.import_module("bot.execution_authority_context")
    monkeypatch.setattr(
        eac,
        "runtime_authority_snapshot",
        lambda: _snapshot(
            eac,
            lifecycle_phase="DEGRADED",
            coordinator_state="FAILED",
            reason="broker_execution_corruption",
        ),
    )
    monkeypatch.setattr(eac, "assert_distributed_writer_authority", lambda: None)
    monkeypatch.setattr(eac, "require_startup_execution_authority", lambda **kwargs: {"ready": True})
    monkeypatch.setattr(eac, "is_seak_halted", lambda: False)
    monkeypatch.setenv("NIJA_EXECUTION_CIRCUIT_STATE", "CLOSED")
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "5085")
    ok, reason, _ = v337._hard_exit_authority_proof()
    assert ok is False
    assert reason.startswith("non_startup_runtime_block:")
