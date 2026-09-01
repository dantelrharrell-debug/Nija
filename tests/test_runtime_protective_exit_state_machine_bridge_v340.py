from __future__ import annotations

from types import SimpleNamespace


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
            SimpleNamespace(lifecycle_phase="BOOT", coordinator_state="ACTIVATION_CONVERGING"),
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
