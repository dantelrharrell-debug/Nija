from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

from bot import execution_ack_timeout_failover_patch as patch


@dataclass
class FakeResult:
    success: bool
    symbol: str = "ALLO-USDT"
    side: str = "buy"
    size_usd: float = 35.47
    broker: str = "okx"
    error: str = ""


@dataclass
class FakeRequest:
    symbol: str = "ALLO-USDT"
    side: str = "buy"
    size_usd: float = 35.47
    preferred_broker: str = "okx"
    request_id: str = "request-1"
    intent_id: str = "intent-1"
    metadata: dict = field(default_factory=dict)


class FakePipeline:
    def __init__(self):
        self.calls = 0

    def _dispatch(self, request, t_start):
        self.calls += 1
        return FakeResult(False, error="confirmed_order_rejected:ack_timeout_no_confirmed_fill_within_30s")


def test_ack_timeout_is_not_resubmitted_and_is_marked_uncertain():
    module = SimpleNamespace(ExecutionPipeline=FakePipeline, __name__="bot.execution_pipeline")
    assert patch._patch_module(module) is True
    pipeline = module.ExecutionPipeline()
    request = FakeRequest()

    result = pipeline._dispatch(request, 0.0)

    assert result.success is False
    assert pipeline.calls == 1
    assert result.broker == "okx"
    assert request.metadata["ack_state"] == "uncertain"
    assert request.metadata["ack_retry_suppressed"] is True
    assert "retry suppressed" in result.error


def test_non_timeout_failure_is_returned_without_mutation():
    class NonTimeoutPipeline(FakePipeline):
        def _dispatch(self, request, t_start):
            self.calls += 1
            return FakeResult(False, error="confirmed_order_rejected:insufficient_funds")

    module = SimpleNamespace(ExecutionPipeline=NonTimeoutPipeline, __name__="bot.execution_pipeline")
    assert patch._patch_module(module) is True
    pipeline = module.ExecutionPipeline()
    request = FakeRequest()

    result = pipeline._dispatch(request, 0.0)

    assert result.success is False
    assert result.error == "confirmed_order_rejected:insufficient_funds"
    assert pipeline.calls == 1
    assert request.metadata == {}
