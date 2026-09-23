from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bot.execution_pipeline import ExecutionPipeline, PipelineRequest
from bot.multi_broker_execution_router import MultiBrokerExecutionRouter
from bot.pipeline_order_submitter import submit_market_order_via_pipeline
from bot.pipeline_request_contract import validate_pipeline_request


class _CoinbaseBroker:
    broker_type = "coinbase"
    NAME = "coinbase"
    connected = True

    def get_account_balance(self):
        return {"available_balance": 1000.0}


class TestLiquidityFvgRetraceExecutionContract(unittest.TestCase):
    def test_pipeline_contract_requires_protection_and_limit_price(self):
        missing_protection = PipelineRequest(
            strategy="LIQUIDITY_FVG_RETRACE",
            symbol="BTC-USD",
            side="buy",
            size_usd=25.0,
            intent_type="entry",
            position_effect="open",
            order_type="limit",
            limit_price=103.0,
            price_hint_usd=103.0,
        )
        ok, reason = validate_pipeline_request(missing_protection)
        self.assertFalse(ok)
        self.assertEqual(reason, "liquidity_fvg_retrace_protection_required")

        protected = PipelineRequest(
            strategy="LIQUIDITY_FVG_RETRACE",
            symbol="BTC-USD",
            side="buy",
            size_usd=25.0,
            intent_type="entry",
            position_effect="open",
            order_type="limit",
            limit_price=103.0,
            price_hint_usd=103.0,
            stop_loss_pct=0.015,
            take_profit_pct=0.05,
        )
        ok, reason = validate_pipeline_request(protected)
        self.assertTrue(ok, reason)

    def test_verified_entry_protection_is_required_for_new_strategy(self):
        request = PipelineRequest(
            strategy="LIQUIDITY_FVG_RETRACE",
            symbol="BTC-USD",
            side="buy",
            size_usd=25.0,
            intent_type="entry",
            position_effect="open",
            order_type="limit",
            limit_price=103.0,
            price_hint_usd=103.0,
            stop_loss_pct=0.015,
            take_profit_pct=0.05,
        )
        self.assertTrue(ExecutionPipeline._requires_verified_entry_protection(request))

    def test_market_only_protected_router_cannot_downgrade_limit_entry(self):
        broker = SimpleNamespace(
            supports_atomic_protected_entry=True,
            place_market_order_with_protection=lambda *args, **kwargs: None,
        )
        request = SimpleNamespace(
            order_type="limit",
            stop_loss_pct=0.015,
            take_profit_pct=0.05,
            metadata={"broker_client": broker},
        )
        self.assertFalse(MultiBrokerExecutionRouter().supports_v2_protected_entry(request))

    def test_submitter_preserves_limit_order_and_price(self):
        broker = _CoinbaseBroker()
        captured = {}

        class _Pipeline:
            def execute(self, request):
                captured["request"] = request
                raise RuntimeError("stop_after_capture")

        with patch(
            "bot.pipeline_order_submitter._resolve_execution_pipeline_dependencies",
            return_value=(SimpleNamespace, lambda: _Pipeline()),
        ), patch(
            "bot.pipeline_order_submitter.assert_distributed_writer_authority",
            return_value=None,
        ):
            result = submit_market_order_via_pipeline(
                broker,
                "BTC-USD",
                "buy",
                25.0,
                strategy="LIQUIDITY_FVG_RETRACE",
                order_type="limit",
                limit_price=103.0,
                time_in_force="gtc",
                metadata_override={
                    "stop_loss_pct": 0.015,
                    "take_profit_pct": 0.05,
                },
            )

        self.assertEqual(result["status"], "state_unknown")
        request = captured["request"]
        self.assertEqual(request.order_type, "limit")
        self.assertEqual(request.limit_price, 103.0)
        self.assertEqual(request.price_hint_usd, 103.0)
        self.assertEqual(request.time_in_force, "gtc")
        self.assertEqual(request.stop_loss_pct, 0.015)
        self.assertEqual(request.take_profit_pct, 0.05)


if __name__ == "__main__":
    unittest.main()
