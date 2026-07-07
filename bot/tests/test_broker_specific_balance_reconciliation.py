from __future__ import annotations

import importlib
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from bot import pipeline_order_submitter
from bot.execution_pipeline import ExecutionPipeline, PipelineRequest, PipelineResult


def _make_pipeline() -> ExecutionPipeline:
    pipeline = ExecutionPipeline.__new__(ExecutionPipeline)
    pipeline._ecel_required = False
    pipeline._ecel_fail_closed = False
    pipeline._ecel = None
    pipeline._pre_trade_risk_engine = None
    pipeline._exchange_normalizer = None
    pipeline._allocation_clamp = None
    pipeline._execution_observer = None
    pipeline._throttler = None
    pipeline._router = None
    pipeline._multi_router = None
    pipeline._margin_health_gate = None
    pipeline._capability_matrix = None
    pipeline._downstream_guard = None
    pipeline._margin_position_ledger = None
    pipeline._broker_capability_registry = None
    pipeline._enforce_execution_gate = lambda request, t_start: None
    return pipeline


class TestBrokerSpecificBalanceReconciliation(unittest.TestCase):
    def test_execution_pipeline_uses_selected_broker_balance_before_capital_gate(self):
        pipeline = _make_pipeline()
        captured: dict[str, float] = {}

        def _gate(request, t_start):
            captured["available_balance_usd"] = float(request.available_balance_usd)
            return PipelineResult(
                success=False,
                symbol=request.symbol,
                side=request.side,
                size_usd=request.size_usd,
                error="stop_after_gate",
                latency_ms=0.0,
            )

        pipeline._gate_capital_margin_authorization = _gate

        class _Authority:
            def get_per_broker(self, broker_id: str) -> float:
                return 25.0 if broker_id == "kraken" else 0.0

            def is_registered(self, broker_id: str) -> bool:
                return broker_id == "kraken"

        request = PipelineRequest(
            strategy="balance-reconciliation-test",
            symbol="BTC-USD",
            side="buy",
            size_usd=50.0,
            preferred_broker="kraken",
        )

        with patch("bot.execution_pipeline.get_capital_authority", return_value=_Authority()):
            result = pipeline.execute(request)

        self.assertFalse(result.success)
        self.assertEqual(captured["available_balance_usd"], 25.0)

    def test_pipeline_order_submitter_passes_broker_specific_balance_to_pipeline(self):
        class _Broker:
            broker_type = "kraken"
            account_identifier = ""

        class _Authority:
            def get_per_broker(self, broker_id: str) -> float:
                return 30.0 if broker_id == "kraken" else 0.0

            def is_registered(self, broker_id: str) -> bool:
                return broker_id == "kraken"

        class _CapitalAuthorityModule:
            @staticmethod
            def get_capital_authority():
                return _Authority()

        class _FakePipeline:
            def __init__(self) -> None:
                self.request = None

            def execute(self, request):
                self.request = request
                return SimpleNamespace(
                    success=True,
                    fill_price=100.0,
                    filled_size_usd=request.size_usd,
                    broker=request.preferred_broker,
                )

        fake_pipeline = _FakePipeline()
        real_import_module = importlib.import_module

        def _patched_import_module(name: str, package=None):
            if name in {"bot.capital_authority", "capital_authority"}:
                return _CapitalAuthorityModule()
            return real_import_module(name, package)

        with patch("bot.pipeline_order_submitter.assert_distributed_writer_authority", return_value=None), patch(
            "bot.pipeline_order_submitter.get_execution_pipeline",
            return_value=fake_pipeline,
        ), patch("importlib.import_module", side_effect=_patched_import_module):
            result = pipeline_order_submitter.submit_market_order_via_pipeline(
                broker=_Broker(),
                symbol="BTC-USD",
                side="buy",
                quantity=40.0,
            )

        self.assertEqual(result["status"], "filled")
        self.assertIsNotNone(fake_pipeline.request)
        self.assertEqual(fake_pipeline.request.preferred_broker, "kraken")
        self.assertEqual(fake_pipeline.request.available_balance_usd, 30.0)
