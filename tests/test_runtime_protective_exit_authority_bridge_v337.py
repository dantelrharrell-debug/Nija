from __future__ import annotations

from types import SimpleNamespace


def _snapshot(**overrides):
    base = {
        "ready": False,
        "authority_ready": True,
        "nonce_ready": True,
        "dispatch_health_ready": True,
        "dispatch_enabled": False,
        "kill_switch_active": False,
        "coordinator_state": "ACTIVATION_CONVERGING",
        "runtime_state": "VERIFYING",
        "reason": "global_epoch_stale",
        "lifecycle_phase": "BOOT",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _decision(**overrides):
    from bot.execution_authority_context import ExecutionDecision

    base = {
        "allowed": False,
        "reason": "lifecycle_phase:BOOT",
        "circuit_state": "CLOSED",
        "state_live_active": False,
        "lease_valid": False,
        "lease_generation_current": False,
        "nonce_ready": True,
        "heartbeat_fresh": False,
        "heartbeat_stage_sufficient": False,
        "broker_health_ok": True,
        "circuit_breaker_closed": False,
        "dispatch_enabled": False,
        "stability_allowed": False,
        "stability_halt_state": "UNKNOWN",
        "stability_throttle": 0.0,
        "stability_size_multiplier": 0.0,
        "stability_stress_score": 1.0,
        "stability_collapsed_risk_score": 1.0,
        "stability_reason": "lifecycle_gate",
        "first_failed_gate": "lifecycle.phase",
        "reason_code": "lifecycle_phase_not_live",
        "reason_detail": "lifecycle_phase:BOOT",
        "lifecycle_phase": "BOOT",
    }
    base.update(overrides)
    return ExecutionDecision(**base)


def _stability(allowed=True):
    return SimpleNamespace(
        allowed=allowed,
        halt_state="STABLE" if allowed else "HALT",
        throttle=0.0,
        size_multiplier=1.0 if allowed else 0.0,
        stress_score=0.1 if allowed else 1.0,
        collapsed_risk_score=0.1 if allowed else 1.0,
        reason="stable" if allowed else "hard_collapse_containment",
    )


def test_hard_exit_authority_proof_accepts_only_current_hard_write_safety(monkeypatch):
    from bot import execution_authority_context as eac
    from bot import runtime_protective_exit_authority_bridge_v337_patch as v337

    monkeypatch.setattr(eac, "runtime_authority_snapshot", lambda: _snapshot())
    monkeypatch.setattr(eac, "assert_distributed_writer_authority", lambda: None)
    monkeypatch.setattr(eac, "require_startup_execution_authority", lambda **kwargs: {"ready": True})
    monkeypatch.setattr(eac, "is_seak_halted", lambda: False)
    monkeypatch.setattr(v337, "_circuit_permits_exit", lambda: (True, "CLOSED"))
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "writer-token")

    ok, reason, snap = v337._hard_exit_authority_proof()

    assert ok is True
    assert reason == "hard_exit_authority_proven"
    assert snap.lifecycle_phase == "BOOT"
    assert snap.ready is False


def test_hard_exit_authority_proof_denies_nonce_not_ready(monkeypatch):
    from bot import execution_authority_context as eac
    from bot import runtime_protective_exit_authority_bridge_v337_patch as v337

    monkeypatch.setattr(eac, "runtime_authority_snapshot", lambda: _snapshot(nonce_ready=False))
    monkeypatch.setattr(eac, "assert_distributed_writer_authority", lambda: None)
    monkeypatch.setattr(eac, "require_startup_execution_authority", lambda **kwargs: {"ready": True})
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "writer-token")

    ok, reason, _ = v337._hard_exit_authority_proof()

    assert ok is False
    assert reason == "nonce_not_ready"


def test_hard_exit_authority_proof_denies_kill_switch(monkeypatch):
    from bot import execution_authority_context as eac
    from bot import runtime_protective_exit_authority_bridge_v337_patch as v337

    monkeypatch.setattr(eac, "runtime_authority_snapshot", lambda: _snapshot(kill_switch_active=True))
    monkeypatch.setattr(eac, "assert_distributed_writer_authority", lambda: None)
    monkeypatch.setattr(eac, "require_startup_execution_authority", lambda **kwargs: {"ready": True})
    monkeypatch.setenv("NIJA_WRITER_FENCING_TOKEN", "writer-token")

    ok, reason, _ = v337._hard_exit_authority_proof()

    assert ok is False
    assert reason == "kill_switch_active"


def test_hard_exit_authority_proof_denies_writer_failure(monkeypatch):
    from bot import execution_authority_context as eac
    from bot import runtime_protective_exit_authority_bridge_v337_patch as v337

    monkeypatch.setattr(eac, "runtime_authority_snapshot", lambda: _snapshot())

    def reject_writer():
        raise RuntimeError("other-instance")

    monkeypatch.setattr(eac, "assert_distributed_writer_authority", reject_writer)

    ok, reason, _ = v337._hard_exit_authority_proof()

    assert ok is False
    assert reason.startswith("distributed_writer:")


def test_initial_authority_bridge_allows_only_trusted_lifecycle_block(monkeypatch):
    from bot import execution_authority_context as eac
    from bot import runtime_protective_exit_authority_bridge_v337_patch as v337

    monkeypatch.setattr(v337, "_trusted_close", lambda: True)
    monkeypatch.setattr(v337, "_hard_exit_authority_proof", lambda: (True, "hard_exit_authority_proven", _snapshot()))
    monkeypatch.setattr(eac, "_evaluate_stability_authority", lambda **kwargs: _stability(True))

    bridged = v337._bridge_initial_authority_decision(_decision())

    assert bridged.allowed is True
    assert bridged.reason == "protective_exit_lifecycle_bridge"
    assert bridged.lifecycle_phase == "LIVE"
    assert bridged.stability_allowed is True
    assert bridged.first_failed_gate == ""


def test_initial_authority_bridge_never_changes_entry(monkeypatch):
    from bot import runtime_protective_exit_authority_bridge_v337_patch as v337

    original = _decision()
    monkeypatch.setattr(v337, "_trusted_close", lambda: False)

    assert v337._bridge_initial_authority_decision(original) is original


def test_initial_authority_bridge_never_overrides_non_lifecycle_denial(monkeypatch):
    from bot import runtime_protective_exit_authority_bridge_v337_patch as v337

    original = _decision(
        reason="nonce.authority:blocked",
        first_failed_gate="nonce.authority",
        reason_code="nonce_authority_missing",
        reason_detail="nonce.authority:blocked",
        lifecycle_phase="LIVE",
    )
    monkeypatch.setattr(v337, "_trusted_close", lambda: True)

    assert v337._bridge_initial_authority_decision(original) is original


def test_initial_authority_bridge_fails_closed_when_hard_proof_fails(monkeypatch):
    from bot import runtime_protective_exit_authority_bridge_v337_patch as v337

    original = _decision()
    monkeypatch.setattr(v337, "_trusted_close", lambda: True)
    monkeypatch.setattr(v337, "_hard_exit_authority_proof", lambda: (False, "nonce_not_ready", _snapshot()))

    assert v337._bridge_initial_authority_decision(original) is original


def test_initial_authority_bridge_preserves_stability_halt(monkeypatch):
    from bot import execution_authority_context as eac
    from bot import runtime_protective_exit_authority_bridge_v337_patch as v337

    original = _decision()
    monkeypatch.setattr(v337, "_trusted_close", lambda: True)
    monkeypatch.setattr(v337, "_hard_exit_authority_proof", lambda: (True, "hard_exit_authority_proven", _snapshot()))
    monkeypatch.setattr(eac, "_evaluate_stability_authority", lambda **kwargs: _stability(False))

    assert v337._bridge_initial_authority_decision(original) is original
