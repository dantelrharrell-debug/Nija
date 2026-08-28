from __future__ import annotations

from types import SimpleNamespace

from bot import exchange_kill_switch_internal_reject_guard_patch as guard


class FakeExecutionPipeline:
    def __init__(self):
        self.telemetry_calls = []

    def _emit_execution_rejection_telemetry(self, *, symbol, side, reason):
        self.telemetry_calls.append({"symbol": symbol, "side": side, "reason": reason})
        return "original"


def _pipeline():
    module = SimpleNamespace(ExecutionPipeline=FakeExecutionPipeline, __name__="bot.execution_pipeline")
    assert guard._patch_execution_pipeline_module(module) is True
    return module.ExecutionPipeline()


def test_v254_classifier_marks_unconfirmed_ack_timeout_non_exchange():
    assert guard._soft_non_exchange_reason(
        "confirmed_order_rejected:ack_timeout_no_confirmed_fill_within_30s"
    ) is True
    assert guard._soft_non_exchange_reason("terminal_reject_status:unfilled") is True


def test_v254_classifier_preserves_concrete_exchange_reject():
    assert guard._soft_non_exchange_reason(
        "Kraken AddOrder rejected: EOrder:Insufficient margin"
    ) is False


def test_startup_guard_suppresses_ack_timeout_exchange_telemetry():
    pipeline = _pipeline()
    result = pipeline._emit_execution_rejection_telemetry(
        symbol="BTC-USD",
        side="buy",
        reason="confirmed_order_rejected:ack_timeout_no_confirmed_fill_within_30s",
    )
    assert result is None
    assert pipeline.telemetry_calls == []


def test_startup_guard_suppresses_lifecycle_and_dispatch_local_blocks():
    pipeline = _pipeline()
    for reason in (
        "dispatch_disabled: dispatch.enabled=false",
        "Execution blocked: lifecycle_phase:BOOT",
        "Execution gate pending (state_machine=EMERGENCY_STOP)",
    ):
        assert pipeline._emit_execution_rejection_telemetry(
            symbol="ETH-USD",
            side="sell",
            reason=reason,
        ) is None
    assert pipeline.telemetry_calls == []


def test_startup_guard_allows_concrete_exchange_rejection_to_original_boundary():
    pipeline = _pipeline()
    result = pipeline._emit_execution_rejection_telemetry(
        symbol="BTC-USD",
        side="buy",
        reason="Kraken AddOrder rejected: EOrder:Insufficient margin",
    )
    assert result == "original"
    assert len(pipeline.telemetry_calls) == 1
