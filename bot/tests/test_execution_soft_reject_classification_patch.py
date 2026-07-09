from __future__ import annotations

from types import SimpleNamespace

from bot import execution_soft_reject_classification_patch as patch


class FakePipeline:
    def __init__(self):
        self.original_called = False

    def _emit_execution_rejection_telemetry(self, **kwargs):
        self.telemetry = kwargs

    def _on_order_rejected(self, request, error):
        self.original_called = True
        raise SystemError("ECEL FAILURE — INVALID ORDER ESCAPED")


def test_emergency_stop_reject_is_soft_not_ecel_failure():
    module = SimpleNamespace(ExecutionPipeline=FakePipeline, __name__="bot.execution_pipeline")
    assert patch._patch_module(module) is True
    pipeline = module.ExecutionPipeline()
    request = SimpleNamespace(symbol="A-USD", side="buy")

    assert pipeline._on_order_rejected(request, "Execution gate pending (state_machine=EMERGENCY_STOP)") is None
    assert pipeline.original_called is False


def test_terminal_unfilled_reject_is_soft_not_ecel_failure():
    module = SimpleNamespace(ExecutionPipeline=FakePipeline, __name__="bot.execution_pipeline")
    assert patch._patch_module(module) is True
    pipeline = module.ExecutionPipeline()
    request = SimpleNamespace(symbol="AXS-USD", side="buy")

    assert pipeline._on_order_rejected(request, "terminal_reject_status:unfilled") is None
    assert pipeline.original_called is False


def test_unknown_reject_still_uses_original_path():
    module = SimpleNamespace(ExecutionPipeline=FakePipeline, __name__="bot.execution_pipeline")
    assert patch._patch_module(module) is True
    pipeline = module.ExecutionPipeline()
    request = SimpleNamespace(symbol="AXS-USD", side="buy")

    try:
        pipeline._on_order_rejected(request, "unknown exchange rejection")
    except SystemError:
        pass

    assert pipeline.original_called is True
