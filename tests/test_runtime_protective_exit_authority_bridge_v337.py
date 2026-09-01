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
