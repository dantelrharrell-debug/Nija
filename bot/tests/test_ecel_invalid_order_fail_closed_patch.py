from __future__ import annotations

from dataclasses import dataclass
from types import ModuleType, SimpleNamespace

from bot import ecel_invalid_order_fail_closed_patch as patch


@dataclass
class PipelineResult:
    success: bool
    symbol: str
    side: str
    size_usd: float
    error: str
    latency_ms: float


class RejectingPipeline:
    def _on_order_rejected(self, request, error):
        raise SystemError("ECEL FAILURE — INVALID ORDER ESCAPED")

    def execute(self, request):
        raise SystemError("ECEL FAILURE — INVALID ORDER ESCAPED")


def test_on_order_rejected_ecel_failure_is_fail_closed():
    module = ModuleType("bot.execution_pipeline")
    module.ExecutionPipeline = RejectingPipeline
    module.PipelineResult = PipelineResult

    assert patch._patch_execution_pipeline(module) is True

    pipeline = module.ExecutionPipeline()
    request = SimpleNamespace(symbol="ANIME-USD", side="buy", size_usd=10.0)

    assert pipeline._on_order_rejected(request, "unknown exchange rejection") is None


def test_execute_ecel_failure_returns_rejected_pipeline_result():
    module = ModuleType("bot.execution_pipeline")
    module.ExecutionPipeline = RejectingPipeline
    module.PipelineResult = PipelineResult

    assert patch._patch_execution_pipeline(module) is True

    pipeline = module.ExecutionPipeline()
    request = SimpleNamespace(symbol="A-USD", side="buy", size_usd=10.0)
    result = pipeline.execute(request)

    assert result.success is False
    assert result.symbol == "A-USD"
    assert result.side == "buy"
    assert result.size_usd == 10.0
    assert "ECEL invalid order rejected before broker dispatch" in result.error


def test_non_ecel_system_error_still_raises():
    class OtherFailurePipeline:
        def _on_order_rejected(self, request, error):
            raise SystemError("different hard failure")

        def execute(self, request):
            raise SystemError("different hard failure")

    module = ModuleType("bot.execution_pipeline")
    module.ExecutionPipeline = OtherFailurePipeline
    module.PipelineResult = PipelineResult

    assert patch._patch_execution_pipeline(module) is True

    pipeline = module.ExecutionPipeline()
    request = SimpleNamespace(symbol="BTC-USD", side="buy", size_usd=10.0)

    try:
        pipeline._on_order_rejected(request, "different hard failure")
    except SystemError as exc:
        assert "different hard failure" in str(exc)
    else:
        raise AssertionError("non-ECEL SystemError should still raise")
