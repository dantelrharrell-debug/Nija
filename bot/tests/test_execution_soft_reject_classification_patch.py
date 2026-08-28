from __future__ import annotations

from types import SimpleNamespace

from bot import execution_soft_reject_classification_patch as patch


class FakePipeline:
    def __init__(self):
        self.original_called = False
        self.telemetry_calls = []

    def _emit_execution_rejection_telemetry(self, **kwargs):
        self.telemetry_calls.append(kwargs)

    def _on_order_rejected(self, request, error):
        self.original_called = True
        raise SystemError("ECEL FAILURE — INVALID ORDER ESCAPED")


def _patched_pipeline():
    module = SimpleNamespace(ExecutionPipeline=FakePipeline, __name__="bot.execution_pipeline")
    assert patch._patch_module(module) is True
    return module.ExecutionPipeline()


def test_emergency_stop_reject_is_soft_not_ecel_failure_or_exchange_sample():
    pipeline = _patched_pipeline()
    request = SimpleNamespace(symbol="A-USD", side="buy")

    assert pipeline._on_order_rejected(
        request,
        "Execution gate pending (state_machine=EMERGENCY_STOP)",
    ) is None
    assert pipeline.original_called is False
    assert pipeline.telemetry_calls == []


def test_terminal_unfilled_reject_is_soft_not_ecel_failure_or_exchange_sample():
    pipeline = _patched_pipeline()
    request = SimpleNamespace(symbol="AXS-USD", side="buy")

    assert pipeline._on_order_rejected(request, "terminal_reject_status:unfilled") is None
    assert pipeline.original_called is False
    assert pipeline.telemetry_calls == []


def test_ack_timeout_reject_is_soft_not_exchange_sample():
    pipeline = _patched_pipeline()
    request = SimpleNamespace(symbol="BTC-USD", side="buy")

    assert pipeline._on_order_rejected(
        request,
        "confirmed_order_rejected:ack_timeout_no_confirmed_fill_within_30s",
    ) is None
    assert pipeline.original_called is False
    assert pipeline.telemetry_calls == []


def test_direct_soft_telemetry_call_is_suppressed_by_v254_boundary():
    pipeline = _patched_pipeline()

    assert pipeline._emit_execution_rejection_telemetry(
        symbol="BTC-USD",
        side="buy",
        reason="ack_timeout_no_confirmed_fill",
    ) is None
    assert pipeline.telemetry_calls == []


def test_unknown_direct_telemetry_still_reaches_original_boundary():
    pipeline = _patched_pipeline()

    pipeline._emit_execution_rejection_telemetry(
        symbol="BTC-USD",
        side="buy",
        reason="Kraken AddOrder rejected: EOrder:Insufficient margin",
    )
    assert len(pipeline.telemetry_calls) == 1
    assert "Kraken AddOrder rejected" in pipeline.telemetry_calls[0]["reason"]


def test_unknown_reject_still_uses_original_path():
    pipeline = _patched_pipeline()
    request = SimpleNamespace(symbol="AXS-USD", side="buy")

    try:
        pipeline._on_order_rejected(request, "unknown exchange rejection")
    except SystemError:
        pass

    assert pipeline.original_called is True
