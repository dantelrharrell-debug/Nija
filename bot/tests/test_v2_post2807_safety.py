from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bot.control.control_compiler import RawSignal
from bot.control.decision_context import UserDecisionContext, get_user_scoped_idempotency_registry
from bot.control.signal_pipeline import SignalPipeline
from bot.control.trading_context import TradingContext
from bot.pipeline_order_submitter import submit_market_order_via_pipeline
from bot.signal_broadcaster import SignalBroadcaster


class TestPost2807Safety(unittest.TestCase):
    def test_mixed_trading_context_identity_rejected(self):
        tc = TradingContext(
            user_id="user-a", trading_account_id="acct-a", broker="kraken",
            broker_account_id="ka", strategy_instance_id="orb", portfolio_id="pf-a",
            request_id="req", correlation_id="corr", environment="test", mode="paper",
        )
        raw = RawSignal(
            symbol="ETH-USD", side="buy", action="enter_long", size_usd=10,
            confidence=.8, regime="trending", strategy="orb", approved=True,
            user_id="user-b", account_id="acct-a", broker="kraken",
            portfolio_id="pf-a", trading_context=tc,
        )
        self.assertIsNone(SignalPipeline._resolve_decision_context(raw, None))

    def test_explicit_decision_context_must_match_trading_context(self):
        tc = TradingContext(
            user_id="user-a", trading_account_id="acct-a", broker="kraken",
            broker_account_id="ka", strategy_instance_id="orb", portfolio_id="pf-a",
            request_id="req", correlation_id="corr", environment="test", mode="paper",
        )
        raw = RawSignal(
            symbol="ETH-USD", side="buy", action="enter_long", size_usd=10,
            confidence=.8, regime="trending", strategy="orb", approved=True,
            trading_context=tc,
        )
        dc = UserDecisionContext(
            user_id="user-b", account_id="acct-a", broker="kraken",
            portfolio_id="pf-a", strategy_signal_id="sig", trade_id="trade",
        )
        self.assertIsNone(SignalPipeline._resolve_decision_context(raw, dc))

    def test_kraken_balance_proof_does_not_prove_margin_visibility(self):
        broker = SimpleNamespace(connected=True)
        self.assertFalse(SignalBroadcaster._kraken_margin_visibility_proven(broker))

    def test_kraken_explicit_open_positions_proof_is_required(self):
        broker = SimpleNamespace(kraken_open_positions_visibility_proven=True)
        self.assertTrue(SignalBroadcaster._kraken_margin_visibility_proven(broker))

    def test_ack_timeout_without_order_id_stays_state_unknown(self):
        broker = SimpleNamespace(broker_name="coinbase", connected=True, get_account_balance=lambda: 1000.0)
        result = SimpleNamespace(success=False, order_id=None, error="ACK timeout after dispatch")
        pipeline = SimpleNamespace(execute=lambda request: result)
        with patch("bot.pipeline_order_submitter.assert_distributed_writer_authority", return_value=None), \
             patch("bot.pipeline_order_submitter.get_execution_pipeline", return_value=pipeline):
            out = submit_market_order_via_pipeline(
                broker, "BTC-USD", "buy", 10.0,
                metadata_override={"duplicate_key": "v2:ack-timeout-test"},
            )
        self.assertEqual(out["status"], "state_unknown")
        self.assertEqual(
            get_user_scoped_idempotency_registry().get_state("v2:ack-timeout-test"),
            "state_unknown",
        )


if __name__ == "__main__":
    unittest.main()
