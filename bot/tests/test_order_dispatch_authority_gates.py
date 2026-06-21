import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bot.broker_integration import (
    CoinbaseBrokerAdapter,
    KrakenBrokerAdapter,
    OKXBrokerAdapter,
)
from bot.execution_pipeline import ExecutionPipeline, PipelineRequest, PipelineResult


class _FakeSeak:
    def __init__(self, halted: bool, reason: str = ""):
        self.is_halted = halted
        self._halt_reason = reason


class TestBrokerLimitOrderAuthorityGates(unittest.TestCase):
    def test_coinbase_limit_order_requires_authority_gate(self):
        sentinel = {"status": "blocked"}
        adapter = CoinbaseBrokerAdapter()
        with patch(
            "bot.broker_integration._reject_if_unauthorized_order_submit",
            return_value=sentinel,
        ) as mock_gate:
            result = adapter.place_limit_order("BTC-USD", "buy", 1.0, 100.0)

        self.assertEqual(result, sentinel)
        mock_gate.assert_called_once_with("coinbase", "BTC-USD", "buy", 1.0)

    def test_kraken_limit_order_requires_authority_gate(self):
        sentinel = {"status": "blocked"}
        adapter = KrakenBrokerAdapter(api_key="k", api_secret="s")
        with patch(
            "bot.broker_integration._reject_if_unauthorized_order_submit",
            return_value=sentinel,
        ) as mock_gate:
            result = adapter.place_limit_order("BTC-USD", "buy", 1.0, 100.0)

        self.assertEqual(result, sentinel)
        mock_gate.assert_called_once_with("kraken", "BTC-USD", "buy", 1.0)

    def test_okx_limit_order_requires_authority_gate(self):
        sentinel = {"status": "blocked"}
        adapter = OKXBrokerAdapter()
        with patch(
            "bot.broker_integration._reject_if_unauthorized_order_submit",
            return_value=sentinel,
        ) as mock_gate:
            result = adapter.place_limit_order("BTC-USD", "buy", 1.0, 100.0)

        self.assertEqual(result, sentinel)
        mock_gate.assert_called_once_with("okx", "BTC-USD", "buy", 1.0)


class TestExecutionPipelineAuthorityHalts(unittest.TestCase):
    def test_execute_blocks_when_seak_halted(self):
        pipeline = ExecutionPipeline.__new__(ExecutionPipeline)
        pipeline._execution_observer = None
        pipeline._allocation_clamp = None
        pipeline._exchange_normalizer = None
        pipeline._pre_trade_risk_engine = None
        pipeline._ecel = None
        pipeline._ecel_required = False
        pipeline._ecel_fail_closed = False
        pipeline._throttler = None
        pipeline._router = None
        pipeline._multi_router = None
        pipeline._enforce_execution_gate = lambda request, t_start: None
        pipeline._emit_execution_rejection_telemetry = lambda **kwargs: None
        pipeline._dispatch = lambda request, t_start: (_ for _ in ()).throw(AssertionError("dispatch must not run"))

        request = PipelineRequest(symbol="BTC-USD", side="buy", size_usd=25.0)
        with patch.dict(
            os.environ,
            {"LIVE_CAPITAL_VERIFIED": "false", "NIJA_WRITER_FENCING_TOKEN": ""},
            clear=False,
        ), patch(
            "bot.execution_pipeline.assert_distributed_writer_authority",
            return_value=None,
        ), patch(
            "bot.execution_pipeline.get_seak",
            return_value=_FakeSeak(halted=True, reason="unit test halt"),
        ):
            result = pipeline.execute(request)

        self.assertFalse(result.success)
        self.assertIn("SEAK halted", result.error)

    def test_execute_blocks_when_runtime_authority_snapshot_not_ready(self):
        pipeline = ExecutionPipeline.__new__(ExecutionPipeline)
        pipeline._execution_observer = None
        pipeline._allocation_clamp = None
        pipeline._exchange_normalizer = None
        pipeline._pre_trade_risk_engine = None
        pipeline._ecel = None
        pipeline._ecel_required = False
        pipeline._ecel_fail_closed = False
        pipeline._throttler = None
        pipeline._router = None
        pipeline._multi_router = None
        pipeline._enforce_execution_gate = lambda request, t_start: None
        pipeline._emit_execution_rejection_telemetry = lambda **kwargs: None
        pipeline._dispatch = lambda request, t_start: (_ for _ in ()).throw(AssertionError("dispatch must not run"))

        request = PipelineRequest(symbol="BTC-USD", side="buy", size_usd=25.0)
        with patch.dict(
            os.environ,
            {"LIVE_CAPITAL_VERIFIED": "false", "NIJA_WRITER_FENCING_TOKEN": ""},
            clear=False,
        ), patch(
            "bot.execution_pipeline.assert_distributed_writer_authority",
            return_value=None,
        ), patch(
            "bot.execution_pipeline.assert_execution_dispatch_permitted",
            return_value=None,
        ), patch(
            "bot.execution_pipeline.runtime_authority_snapshot",
            return_value=SimpleNamespace(ready=False),
        ), patch(
            "bot.execution_pipeline.get_seak",
            return_value=_FakeSeak(halted=False),
        ):
            result = pipeline.execute(request)

        self.assertFalse(result.success)
        self.assertIn("Runtime authority convergence lost", result.error)

    def test_execute_normalizes_uppercase_market_order_before_contract_validation(self):
        pipeline = ExecutionPipeline.__new__(ExecutionPipeline)
        pipeline._execution_observer = None
        pipeline._allocation_clamp = None
        pipeline._exchange_normalizer = None
        pipeline._pre_trade_risk_engine = None
        pipeline._ecel = None
        pipeline._ecel_required = False
        pipeline._ecel_fail_closed = False
        pipeline._throttler = None
        pipeline._router = None
        pipeline._multi_router = None
        pipeline._downstream_guard = None
        pipeline._margin_position_ledger = None
        pipeline._broker_capability_registry = None
        pipeline._enforce_execution_gate = lambda request, t_start: None
        pipeline._gate_capital_margin_authorization = lambda request, t_start: None
        pipeline._emit_execution_rejection_telemetry = lambda **kwargs: None
        seen = {}

        def _dispatch(request, t_start):
            seen["side"] = request.side
            seen["order_type"] = request.order_type
            return PipelineResult(
                success=True,
                symbol=request.symbol,
                side=request.side,
                size_usd=request.size_usd,
                broker=request.preferred_broker or "kraken",
                error="",
                latency_ms=0.0,
            )

        pipeline._dispatch = _dispatch
        request = PipelineRequest(
            strategy="force_trade_probe",
            symbol="BTC-USD",
            side="LONG",
            size_usd=25.0,
            order_type="MARKET",
            preferred_broker="kraken",
        )

        with patch.dict(
            os.environ,
            {"LIVE_CAPITAL_VERIFIED": "false", "NIJA_WRITER_FENCING_TOKEN": ""},
            clear=False,
        ), patch(
            "bot.execution_pipeline.assert_distributed_writer_authority",
            return_value=None,
        ), patch(
            "bot.execution_pipeline.assert_execution_dispatch_permitted",
            return_value=None,
        ), patch(
            "bot.execution_pipeline.runtime_authority_snapshot",
            return_value=SimpleNamespace(ready=True),
        ), patch(
            "bot.execution_pipeline.get_seak",
            return_value=_FakeSeak(halted=False),
        ), patch(
            "bot.execution_pipeline.append_execution_journal_event",
            return_value=None,
        ):
            result = pipeline.execute(request)

        self.assertTrue(result.success)
        self.assertEqual(seen, {"side": "buy", "order_type": "market"})


class TestExecutionPipelineRejectionTelemetry(unittest.TestCase):
    def test_skips_exchange_rejection_telemetry_for_authority_blocks(self):
        pipeline = ExecutionPipeline.__new__(ExecutionPipeline)

        class _Protector:
            def __init__(self):
                self.calls = 0

            def record_order_result(self, order_id: str, accepted: bool):
                self.calls += 1

        protector = _Protector()
        with patch(
            "bot.execution_pipeline.get_exchange_kill_switch_protector",
            return_value=protector,
        ):
            pipeline._emit_execution_rejection_telemetry(
                symbol="BTC-USD",
                side="buy",
                reason="Execution gate pending (state_machine=EMERGENCY_STOP)",
            )

        self.assertEqual(protector.calls, 0)

    def test_records_exchange_rejection_telemetry_for_real_exchange_error(self):
        pipeline = ExecutionPipeline.__new__(ExecutionPipeline)

        class _Protector:
            def __init__(self):
                self.calls = 0

            def record_order_result(self, order_id: str, accepted: bool):
                self.calls += 1

        protector = _Protector()
        with patch(
            "bot.execution_pipeline.get_exchange_kill_switch_protector",
            return_value=protector,
        ):
            pipeline._emit_execution_rejection_telemetry(
                symbol="BTC-USD",
                side="buy",
                reason="EOrder:Insufficient funds",
            )

        self.assertEqual(protector.calls, 1)


if __name__ == "__main__":
    unittest.main()
