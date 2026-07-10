from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

from bot import execution_route_context_integrity_patch as patch


@dataclass(frozen=True)
class Route:
    selected_broker: str
    symbol: str


@dataclass
class Request:
    symbol: str
    side: str
    size_usd: float
    preferred_broker: str = ""
    request_id: str = ""
    intent_id: str = ""
    metadata: dict = field(default_factory=dict)


@dataclass
class Result:
    success: bool
    symbol: str
    side: str
    size_usd: float
    broker: str = ""
    error: str = ""


class FakePipeline:
    def __init__(self):
        self.seen = None

    def _dispatch(self, request, t_start):
        self.seen = request
        return Result(
            True,
            request.symbol,
            request.side,
            request.size_usd,
            broker=request.preferred_broker,
        )


def test_preserves_okx_route_and_normalizes_native_symbol():
    module = SimpleNamespace(
        ExecutionPipeline=FakePipeline,
        PipelineResult=Result,
        __name__="bot.execution_pipeline",
    )
    assert patch._patch(module) is True

    pipeline = module.ExecutionPipeline()
    request = Request(
        symbol="APT-USD",
        side="buy",
        size_usd=27.56,
        preferred_broker="okx",
        metadata={
            "execution_route": Route(selected_broker="okx", symbol="APT-USD"),
            "broker_name": "coinbase",
            "broker_client": SimpleNamespace(broker_type="coinbase"),
        },
    )

    result = pipeline._dispatch(request, 0.0)

    assert result.success is True
    assert result.broker == "okx"
    assert pipeline.seen.symbol == "APT-USDT"
    assert pipeline.seen.preferred_broker == "okx"
    assert pipeline.seen.metadata["broker_name"] == "okx"
    assert pipeline.seen.metadata["selected_broker"] == "okx"
    assert pipeline.seen.metadata["execution_route"].selected_broker == "okx"
    assert pipeline.seen.metadata["execution_route"].symbol == "APT-USDT"
    assert pipeline.seen.request_id
    assert pipeline.seen.intent_id == pipeline.seen.request_id
    assert "broker_client" not in pipeline.seen.metadata
