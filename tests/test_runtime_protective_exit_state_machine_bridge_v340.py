from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_pending_state_bridge_requires_trusted_close_and_hard_proof(monkeypatch):
    from bot import execution_pipeline
    from bot import runtime_protective_exit_state_machine_bridge_v340_patch as v340

    original = execution_pipeline.ExecutionPipeline._enforce_execution_gate

    class FakeResult:
        error = "Execution gate pending (state_machine=LIVE_PENDING_CONFIRMATION)"

    monkeypatch.setattr(
        execution_pipeline.ExecutionPipeline,
        "_enforce_execution_gate",
        lambda self, request, t_start: FakeResult(),
    )
    monkeypatch.setattr(v340, "_trusted_close_active", lambda: True)
    monkeypatch.setattr(
        v340,
        "_hard_exit_proof",
        lambda: (
            True,
            "hard_exit_authority_proven",
            SimpleNamespace(
                lifecycle_phase="BOOT", coordinator_state="ACTIVATION_CONVERGING", kill_switch_active=False,
            ),
        ),
    )

    assert v340._patch_execution_gate() is True
    pipeline = object.__new__(execution_pipeline.ExecutionPipeline)
    request = SimpleNamespace(
        symbol="ETH-USD",
        side="sell",
        intent_type="exit",
        position_effect="close",
    )
    assert execution_pipeline.ExecutionPipeline._enforce_execution_gate(pipeline, request, 0.0) is None

    monkeypatch.setattr(execution_pipeline.ExecutionPipeline, "_enforce_execution_gate", original)


def test_pending_state_bridge_preserves_block_when_hard_proof_fails(monkeypatch):
    from bot import execution_pipeline
    from bot import runtime_protective_exit_state_machine_bridge_v340_patch as v340

    original = execution_pipeline.ExecutionPipeline._enforce_execution_gate

    class FakeResult:
        error = "Execution gate pending (state_machine=LIVE_PENDING_CONFIRMATION)"

    monkeypatch.setattr(
        execution_pipeline.ExecutionPipeline,
        "_enforce_execution_gate",
        lambda self, request, t_start: FakeResult(),
    )
    monkeypatch.setattr(v340, "_trusted_close_active", lambda: True)
    monkeypatch.setattr(v340, "_hard_exit_proof", lambda: (False, "nonce_not_ready", None))

    assert v340._patch_execution_gate() is True
    pipeline = object.__new__(execution_pipeline.ExecutionPipeline)
    request = SimpleNamespace(
        symbol="ETH-USD",
        side="sell",
        intent_type="exit",
        position_effect="close",
    )
    result = execution_pipeline.ExecutionPipeline._enforce_execution_gate(pipeline, request, 0.0)
    assert isinstance(result, FakeResult)

    monkeypatch.setattr(execution_pipeline.ExecutionPipeline, "_enforce_execution_gate", original)


def test_other_state_machine_blocks_are_never_bridged(monkeypatch):
    from bot import execution_pipeline
    from bot import runtime_protective_exit_state_machine_bridge_v340_patch as v340

    original = execution_pipeline.ExecutionPipeline._enforce_execution_gate

    class FakeResult:
        error = "Execution gate pending (state_machine=VERIFYING)"

    monkeypatch.setattr(
        execution_pipeline.ExecutionPipeline,
        "_enforce_execution_gate",
        lambda self, request, t_start: FakeResult(),
    )
    monkeypatch.setattr(v340, "_trusted_close_active", lambda: True)
    monkeypatch.setattr(v340, "_hard_exit_proof", lambda: (True, "hard_exit_authority_proven", None))

    assert v340._patch_execution_gate() is True
    pipeline = object.__new__(execution_pipeline.ExecutionPipeline)
    request = SimpleNamespace(symbol="ETH-USD", side="sell", intent_type="exit", position_effect="close")
    result = execution_pipeline.ExecutionPipeline._enforce_execution_gate(pipeline, request, 0.0)
    assert isinstance(result, FakeResult)

    monkeypatch.setattr(execution_pipeline.ExecutionPipeline, "_enforce_execution_gate", original)


def test_emergency_stop_bridge_denies_even_claimed_exit_only_kill_switch_proof(monkeypatch):
    from bot import execution_pipeline
    from bot import runtime_protective_exit_state_machine_bridge_v340_patch as v340

    original = execution_pipeline.ExecutionPipeline._enforce_execution_gate

    class FakeResult:
        error = "Emergency stop is active - delete EMERGENCY_STOP file to resume"

    monkeypatch.setattr(
        execution_pipeline.ExecutionPipeline,
        "_enforce_execution_gate",
        lambda self, request, t_start: FakeResult(),
    )
    monkeypatch.setattr(v340, "_trusted_close_active", lambda: True)
    monkeypatch.setattr(
        v340,
        "_hard_exit_proof",
        lambda: (
            True,
            "hard_exit_authority_proven_kill_switch_exit_only",
            SimpleNamespace(lifecycle_phase="BOOT", coordinator_state="ACTIVATION_CONVERGING"),
        ),
    )

    assert v340._patch_execution_gate() is True
    pipeline = object.__new__(execution_pipeline.ExecutionPipeline)
    request = SimpleNamespace(symbol="BTC-USD", side="sell", intent_type="exit", position_effect="close")
    result = execution_pipeline.ExecutionPipeline._enforce_execution_gate(pipeline, request, 0.0)
    assert isinstance(result, FakeResult)

    monkeypatch.setattr(execution_pipeline.ExecutionPipeline, "_enforce_execution_gate", original)

@pytest.mark.parametrize("state", [True, None, "false", 0])
def test_pending_bridge_denies_active_or_unproven_stop_state(monkeypatch, state):
    from bot import execution_pipeline
    from bot import runtime_protective_exit_state_machine_bridge_v340_patch as v340

    blocked = SimpleNamespace(error="Execution gate pending (state_machine=LIVE_PENDING_CONFIRMATION)")
    monkeypatch.setattr(
        execution_pipeline.ExecutionPipeline, "_enforce_execution_gate",
        lambda self, request, t_start: blocked,
    )
    monkeypatch.setattr(v340, "_trusted_close_active", lambda: True)
    snap = SimpleNamespace() if state is None else SimpleNamespace(kill_switch_active=state)
    monkeypatch.setattr(v340, "_hard_exit_proof", lambda: (True, "kill_switch_exit_only", snap))
    assert v340._patch_execution_gate()
    request = SimpleNamespace(symbol="BTC-USD", side="sell", intent_type="exit", position_effect="close")
    pipeline = object.__new__(execution_pipeline.ExecutionPipeline)
    assert pipeline._enforce_execution_gate(request, 0.0) is blocked


@pytest.mark.parametrize("intent,effect,side", [
    ("entry", "open", "buy"),
    ("entry", "close", "sell"),
    ("exit", "open", "sell"),
    ("exit", "close", "buy"),
])
def test_pending_bridge_cannot_borrow_context_for_non_close_request(monkeypatch, intent, effect, side):
    from bot import execution_pipeline
    from bot import runtime_protective_exit_state_machine_bridge_v340_patch as v340

    blocked = SimpleNamespace(error="Execution gate pending (state_machine=LIVE_PENDING_CONFIRMATION)")
    monkeypatch.setattr(
        execution_pipeline.ExecutionPipeline, "_enforce_execution_gate",
        lambda self, request, t_start: blocked,
    )
    monkeypatch.setattr(v340, "_trusted_close_active", lambda: True)
    monkeypatch.setattr(
        v340, "_hard_exit_proof",
        lambda: (True, "hard_exit_authority_proven", SimpleNamespace(kill_switch_active=False)),
    )
    assert v340._patch_execution_gate()
    request = SimpleNamespace(symbol="BTC-USD", side=side, intent_type=intent, position_effect=effect)
    pipeline = object.__new__(execution_pipeline.ExecutionPipeline)
    assert pipeline._enforce_execution_gate(request, 0.0) is blocked


@pytest.mark.parametrize("mode_flag", ["APP_STORE_MODE", "DRY_RUN_MODE", "PAPER_MODE", "LIVE_CAPITAL_VERIFIED"])
@pytest.mark.parametrize("provenance", ["MANUAL", "OPERATOR", "FILE_SYSTEM", "UNKNOWN"])
def test_real_emergency_stop_denial_survives_modes_and_claimed_provenance(monkeypatch, tmp_path,
                                                                       mode_flag, provenance):
    from bot import execution_pipeline
    from bot.safety_controller import SafetyController
    from bot import runtime_protective_exit_state_machine_bridge_v340_patch as v340

    monkeypatch.chdir(tmp_path)
    (tmp_path / "EMERGENCY_STOP").write_text("Stop all orders", encoding="utf-8")
    monkeypatch.setenv(mode_flag, "true")
    safety = SafetyController()
    allowed, error = safety.is_trading_allowed()
    assert allowed is False
    blocked = SimpleNamespace(error=error)
    monkeypatch.setattr(
        execution_pipeline.ExecutionPipeline, "_enforce_execution_gate",
        lambda self, request, t_start: blocked,
    )
    monkeypatch.setattr(v340, "_trusted_close_active", lambda: True)
    proof_calls = []

    def claimed_proof():
        proof_calls.append(True)
        return True, "kill_switch_exit_only", SimpleNamespace(kill_switch_active=True)

    monkeypatch.setattr(v340, "_hard_exit_proof", claimed_proof)
    assert v340._patch_execution_gate()
    request = SimpleNamespace(
        symbol="BTC-USD", side="sell", intent_type="exit", position_effect="close",
        metadata={"stop_source": provenance, "verified_position_quantity": 999.0},
    )
    pipeline = object.__new__(execution_pipeline.ExecutionPipeline)
    assert pipeline._enforce_execution_gate(request, 0.0) is blocked
    assert proof_calls == []
    assert (tmp_path / "EMERGENCY_STOP").read_text(encoding="utf-8") == "Stop all orders"

def test_emergency_stop_bridge_fails_closed_without_exit_only_proof(monkeypatch):
    from bot import execution_pipeline
    from bot import runtime_protective_exit_state_machine_bridge_v340_patch as v340

    original = execution_pipeline.ExecutionPipeline._enforce_execution_gate

    class FakeResult:
        error = "Emergency stop is active - delete EMERGENCY_STOP file to resume"

    monkeypatch.setattr(
        execution_pipeline.ExecutionPipeline,
        "_enforce_execution_gate",
        lambda self, request, t_start: FakeResult(),
    )
    monkeypatch.setattr(v340, "_trusted_close_active", lambda: True)
    monkeypatch.setattr(
        v340,
        "_hard_exit_proof",
        lambda: (
            True,
            "hard_exit_authority_proven",
            SimpleNamespace(lifecycle_phase="BOOT", coordinator_state="ACTIVATION_CONVERGING"),
        ),
    )

    assert v340._patch_execution_gate() is True
    pipeline = object.__new__(execution_pipeline.ExecutionPipeline)
    request = SimpleNamespace(symbol="BTC-USD", side="sell", intent_type="exit", position_effect="close")
    result = execution_pipeline.ExecutionPipeline._enforce_execution_gate(pipeline, request, 0.0)
    assert isinstance(result, FakeResult)

    monkeypatch.setattr(execution_pipeline.ExecutionPipeline, "_enforce_execution_gate", original)


def test_emergency_stop_bridge_preserves_block_for_untrusted_entry(monkeypatch):
    from bot import execution_pipeline
    from bot import runtime_protective_exit_state_machine_bridge_v340_patch as v340

    original = execution_pipeline.ExecutionPipeline._enforce_execution_gate

    class FakeResult:
        error = "Emergency stop is active - delete EMERGENCY_STOP file to resume"

    monkeypatch.setattr(
        execution_pipeline.ExecutionPipeline,
        "_enforce_execution_gate",
        lambda self, request, t_start: FakeResult(),
    )
    monkeypatch.setattr(v340, "_trusted_close_active", lambda: False)
    monkeypatch.setattr(
        v340,
        "_hard_exit_proof",
        lambda: (
            True,
            "hard_exit_authority_proven_kill_switch_exit_only",
            SimpleNamespace(lifecycle_phase="BOOT", coordinator_state="ACTIVATION_CONVERGING"),
        ),
    )

    assert v340._patch_execution_gate() is True
    pipeline = object.__new__(execution_pipeline.ExecutionPipeline)
    request = SimpleNamespace(symbol="BTC-USD", side="buy", intent_type="entry", position_effect="open")
    result = execution_pipeline.ExecutionPipeline._enforce_execution_gate(pipeline, request, 0.0)
    assert isinstance(result, FakeResult)

    monkeypatch.setattr(execution_pipeline.ExecutionPipeline, "_enforce_execution_gate", original)
