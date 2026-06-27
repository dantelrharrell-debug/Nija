from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from bot.execution_pipeline import ExecutionPipeline, PipelineRequest
from bot.multi_broker_execution_router import MultiBrokerExecutionRouter


class _Broker:
    def __init__(self) -> None:
        self.calls = []

    def place_market_order(self, symbol, side, quantity, size_type="quote"):
        self.calls.append((symbol, side, quantity, size_type))
        return {
            "status": "filled",
            "order_id": "ord-1",
            "filled_price": 101.25,
            "filled_size_usd": quantity,
        }


def test_multi_broker_router_dispatches_to_direct_broker_client_before_inner_router():
    router = MultiBrokerExecutionRouter()
    broker = _Broker()

    fill_price, filled_usd = router._dispatch_via_inner_router(
        symbol="BTC-USD",
        side="buy",
        size_usd=25.0,
        order_type="MARKET",
        broker_name="kraken",
        metadata={"broker_client": broker, "price_hint_usd": 100.0},
    )

    assert fill_price == 101.25
    assert filled_usd == 25.0
    assert broker.calls == [("BTC-USD", "buy", 25.0, "quote")]


def test_direct_broker_ack_with_order_id_uses_price_hint_as_fill_price():
    class AckOnlyBroker:
        def place_market_order(self, symbol, side, quantity, size_type="quote"):
            return {"status": "open", "order_id": "ord-2", "filled_size_usd": quantity}

    fill_price, filled_usd = MultiBrokerExecutionRouter._dispatch_direct_broker_market_order(
        AckOnlyBroker(),
        symbol="ETH-USD",
        side="buy",
        size_usd=15.0,
        metadata={"price_hint_usd": 2050.0},
    )

    assert fill_price == 2050.0
    assert filled_usd == 15.0


class _FakeMultiRouter:
    def __init__(self):
        self.request = None

    def route(self, request):
        self.request = request
        return SimpleNamespace(
            success=True,
            fill_price=99.0,
            filled_size_usd=request.size_usd,
            broker=request.preferred_broker,
            error="",
        )


def test_execution_pipeline_preserves_direct_broker_metadata_to_multi_router():
    router = _FakeMultiRouter()
    pipeline = ExecutionPipeline.__new__(ExecutionPipeline)
    pipeline._ecel_required = False
    pipeline._ecel_fail_closed = False
    pipeline._ecel = None
    pipeline._execution_observer = None
    pipeline._allocation_clamp = None
    pipeline._exchange_normalizer = None
    pipeline._pre_trade_risk_engine = None
    pipeline._throttler = None
    pipeline._router = None
    pipeline._multi_router = router
    pipeline._downstream_guard = None
    pipeline._margin_position_ledger = None
    pipeline._broker_capability_registry = None
    pipeline._capability_matrix = None
    pipeline._margin_health_gate = None
    pipeline._ack_timeout_s = 5.0
    pipeline._enforce_execution_gate = lambda request, t_start: None
    pipeline._gate_capital_margin_authorization = lambda request, t_start: None
    pipeline._emit_execution_rejection_telemetry = lambda **kwargs: None

    broker = _Broker()
    request = PipelineRequest(
        strategy="force_trade_probe",
        symbol="BTC-USD",
        side="buy",
        size_usd=25.0,
        order_type="MARKET",
        preferred_broker="kraken",
        metadata={"broker_client": broker, "price_hint_usd": 100.0},
    )

    with patch("bot.execution_pipeline.assert_distributed_writer_authority", return_value=None), patch(
        "bot.execution_pipeline.assert_execution_dispatch_permitted", return_value=None
    ), patch("bot.execution_pipeline.runtime_authority_snapshot", return_value=SimpleNamespace(ready=True)), patch(
        "bot.execution_pipeline.get_seak", return_value=SimpleNamespace(is_halted=False)
    ), patch("bot.execution_pipeline.append_execution_journal_event", return_value=None):
        result = pipeline.execute(request)

    assert result.success
    assert router.request is not None
    assert router.request.metadata["broker_client"] is broker
    assert router.request.metadata["price_hint_usd"] == 100.0


def test_route_uses_direct_broker_client_even_when_global_registry_empty():
    from bot.multi_broker_execution_router import RouteRequest

    class EmptyManager:
        def get_all_brokers(self):
            return {}

        def is_execution_eligible(self, broker):
            return False

    router = MultiBrokerExecutionRouter()
    router._broker_manager = EmptyManager()
    broker = _Broker()

    result = router.route(
        RouteRequest(
            strategy="force_trade_probe",
            symbol="BTC-USD",
            side="buy",
            size_usd=25.0,
            preferred_broker="kraken",
            metadata={"broker_client": broker, "price_hint_usd": 100.0},
        )
    )

    assert result.success
    assert result.broker == "kraken"
    assert broker.calls == [("BTC-USD", "buy", 25.0, "quote")]
