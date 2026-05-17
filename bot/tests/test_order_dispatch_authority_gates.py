import os
import unittest
from unittest.mock import patch

from bot.broker_integration import (
    CoinbaseBrokerAdapter,
    KrakenBrokerAdapter,
    OKXBrokerAdapter,
)
from bot.execution_pipeline import ExecutionPipeline, PipelineRequest


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


if __name__ == "__main__":
    unittest.main()
