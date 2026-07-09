from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

from bot import execution_ack_timeout_failover_patch as patch


@dataclass
class FakeResult:
    success: bool
    symbol: str = "ALLO-USD"
    side: str = "buy"
    size_usd: float = 35.47
    broker: str = ""
    error: str = ""


class FakePipeline:
    def __init__(self):
        self._multi_router = object()
        self._router = object()
        self.calls = 0

    def _dispatch(self, request, t_start):
        self.calls += 1
        if self._multi_router is not None:
            return FakeResult(False, error="confirmed_order_rejected:ack_timeout_no_confirmed_fill_within_30s")
        return FakeResult(True, broker="single-router")


def test_ack_timeout_failover_retries_single_router():
    module = SimpleNamespace(ExecutionPipeline=FakePipeline, __name__="bot.execution_pipeline")
    assert patch._patch_module(module) is True
    pipeline = module.ExecutionPipeline()
    request = SimpleNamespace(symbol="ALLO-USD", side="buy", size_usd=35.47, preferred_broker="okx")

    result = pipeline._dispatch(request, 0.0)

    assert result.success is True
    assert result.broker == "single-router"
    assert pipeline.calls == 2
    assert pipeline._multi_router is not None


def test_ack_timeout_failover_does_not_retry_non_timeout():
    class NonTimeoutPipeline(FakePipeline):
        def _dispatch(self, request, t_start):
            self.calls += 1
            return FakeResult(False, error="confirmed_order_rejected:insufficient_funds")

    module = SimpleNamespace(ExecutionPipeline=NonTimeoutPipeline, __name__="bot.execution_pipeline")
    assert patch._patch_module(module) is True
    pipeline = module.ExecutionPipeline()
    request = SimpleNamespace(symbol="ALLO-USD", side="buy", size_usd=35.47, preferred_broker="okx")

    result = pipeline._dispatch(request, 0.0)

    assert result.success is False
    assert result.error == "confirmed_order_rejected:insufficient_funds"
    assert pipeline.calls == 1
