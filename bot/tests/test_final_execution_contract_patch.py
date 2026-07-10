from __future__ import annotations

import time
from dataclasses import dataclass, field
from types import ModuleType, SimpleNamespace

import pytest

from bot import execution_contract_authority as authority
from bot import execution_contract_engine as engine_patch
from bot import execution_contract_pipeline as pipeline_patch
from bot import execution_contract_primitives as contract


class Broker:
    def __init__(self, name: str, cash: float = 100.0):
        self.broker_type = SimpleNamespace(value=name)
        self._venue_available_cash_usd = cash


@dataclass
class Request:
    symbol: str = "BABY-USD"
    side: str = "buy"
    size_usd: float = 9.64
    preferred_broker: str = "okx"
    account_id: str = "master"
    request_id: str = "req-1"
    intent_id: str = ""
    notional_usd: float | None = None
    available_balance_usd: float | None = None
    metadata: dict = field(default_factory=dict)


@dataclass
class Result:
    success: bool
    symbol: str
    side: str
    size_usd: float
    fill_price: float = 0.0
    filled_size_usd: float = 0.0
    broker: str = ""
    error: str = ""
    latency_ms: float = 0.0


def test_route_object_mismatch_is_blocked():
    request = Request(metadata={"broker_client": Broker("kraken")})
    _, broker, error = contract.freeze_request(request)
    assert broker == "okx"
    assert error == "execution_route_object_mismatch:selected=okx:broker_client=kraken"


def test_venue_cash_resolves_one_canonical_notional(monkeypatch):
    monkeypatch.setenv("OKX_MIN_ORDER_USD", "10")
    request = Request(metadata={"broker_client": Broker("okx", 100.0)})
    frozen, broker, error = contract.freeze_request(request)
    assert error is None
    assert broker == "okx"
    assert frozen.size_usd == 10.0
    assert frozen.notional_usd == 10.0
    assert frozen.available_balance_usd == 100.0
    assert frozen.metadata["canonical_order_notional_usd"] == 10.0
    assert frozen.metadata["balance_broker"] == "okx"


def test_ack_key_survives_pipeline_request_conversion():
    pipeline_request = Request(
        request_id="",
        size_usd=10.0,
        metadata={"execution_broker": "okx", "account_id": "master"},
    )
    route_request = SimpleNamespace(
        symbol="BABY-USD",
        side="buy",
        size_usd=10.0,
        preferred_broker="okx",
        account_id="master",
        metadata={"execution_broker": "okx", "account_id": "master"},
    )
    assert contract.request_key(pipeline_request) == contract.request_key(route_request)


def _pipeline_module(*, with_ack: bool):
    module = ModuleType("execution_pipeline")
    module.PipelineResult = Result
    module.runtime_authority_snapshot = lambda: SimpleNamespace(ready=True, dispatch_enabled=True)

    class ExecutionPipeline:
        def execute(self, request):
            return self._dispatch(request, time.monotonic())

        def _dispatch(self, request, started):
            if with_ack:
                contract.store_ack(
                    request,
                    SimpleNamespace(
                        success=True,
                        order_id="OKX-REAL-123",
                        broker="okx",
                        fill_price=0.01347,
                        filled_size_usd=request.size_usd,
                    ),
                )
            return Result(
                True,
                request.symbol,
                request.side,
                request.size_usd,
                fill_price=0.01347,
                filled_size_usd=request.size_usd,
                broker="okx",
            )

    module.ExecutionPipeline = ExecutionPipeline
    return module


def test_pipeline_propagates_real_broker_order_id(monkeypatch):
    monkeypatch.setenv("OKX_MIN_ORDER_USD", "10")
    module = _pipeline_module(with_ack=True)
    assert pipeline_patch.patch_pipeline(module)
    request = Request(size_usd=10.0, metadata={"broker_client": Broker("okx")})
    result = module.ExecutionPipeline().execute(request)
    assert result.success is True
    assert result.order_id == "OKX-REAL-123"
    assert result.broker == "okx"


def test_pipeline_rejects_synthetic_success_without_ack(monkeypatch):
    monkeypatch.setenv("OKX_MIN_ORDER_USD", "10")
    module = _pipeline_module(with_ack=False)
    assert pipeline_patch.patch_pipeline(module)
    request = Request(size_usd=10.0, metadata={"broker_client": Broker("okx")})
    result = module.ExecutionPipeline().execute(request)
    assert result.success is False
    assert "broker_ack_missing_real_order_id" in result.error


def test_authority_snapshot_repair_remains_fail_closed(monkeypatch):
    snapshot = SimpleNamespace(ready=False, dispatch_enabled=False, lifecycle_phase="WARM")
    monkeypatch.setattr(authority, "authority_proof", lambda: (False, "heartbeat_stale"))
    assert authority.repair_snapshot(snapshot).ready is False
    monkeypatch.setattr(authority, "authority_proof", lambda: (True, "writer_lineage_verified"))
    repaired = authority.repair_snapshot(snapshot)
    assert repaired.ready is True
    assert repaired.dispatch_enabled is True
    assert repaired.lifecycle_phase == "LIVE"


def test_engine_replaces_pipeline_id_before_ledger_write():
    module = ModuleType("execution_engine")

    class ExecutionEngine:
        def __init__(self):
            self.records = []

        def record_trade_execution(self, *args, **kwargs):
            self.records.append((args, kwargs))

        def execute_entry(self, *args, **kwargs):
            return None

        def _submit_market_order_via_pipeline(self, client, symbol, side, size, *args, **kwargs):
            contract.LAST_ACK.set(
                {
                    "order_id": "OKX-REAL-456",
                    "broker": "okx",
                    "fill_price": 0.50,
                    "filled_size_usd": size,
                }
            )
            self.record_trade_execution(
                order_id="pipeline",
                broker="okx",
                fill_price=0.50,
                fill_amount_usd=size,
            )
            return {
                "status": "filled",
                "order_id": "pipeline",
                "broker": "okx",
                "filled_price": 0.50,
                "filled_size_usd": size,
            }

    module.ExecutionEngine = ExecutionEngine
    assert engine_patch.patch_engine(module)
    engine = module.ExecutionEngine()
    result = engine._submit_market_order_via_pipeline(
        Broker("okx"),
        "AERO-USD",
        "buy",
        10.0,
        preferred_broker="okx",
    )
    assert result["order_id"] == "OKX-REAL-456"
    assert len(engine.records) == 1
    assert engine.records[0][1]["order_id"] == "OKX-REAL-456"
