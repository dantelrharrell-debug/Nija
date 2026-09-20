from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from bot.control.control_compiler import RawSignal
from bot.control.decision_context import UserDecisionContext, get_user_scoped_idempotency_registry
from bot.control.signal_pipeline import SignalPipeline
from bot.control.trading_context import TradingContext
from bot.pipeline_order_submitter import _classify_failed_submission, submit_market_order_via_pipeline
from bot.signal_broadcaster import SignalBroadcaster


class TestPost2807Safety(unittest.TestCase):
    @staticmethod
    def _reserve_duplicate_handle(trade_id: str):
        registry = get_user_scoped_idempotency_registry()
        context = UserDecisionContext(
            user_id="user-a",
            account_id="acct-a",
            broker="coinbase",
            portfolio_id="coinbase:acct-a",
            strategy_signal_id="post2807-safety",
            trade_id=f"{trade_id}-{uuid4().hex}",
            execution_mode="paper",
            environment="test",
        )
        allowed, handle = registry.reserve(context, symbol="BTC-USD", direction="long")
        if not allowed:
            raise AssertionError("unique test reservation was unexpectedly denied")
        return registry, handle

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
        registry, handle = self._reserve_duplicate_handle("ack-timeout")
        result = SimpleNamespace(success=False, order_id=None, error="ACK timeout after dispatch")
        pipeline = SimpleNamespace(execute=lambda request: result)
        request_type = lambda **kwargs: SimpleNamespace(**kwargs)
        with patch("bot.pipeline_order_submitter.assert_distributed_writer_authority", return_value=None), \
             patch("bot.pipeline_order_submitter.get_execution_pipeline", return_value=pipeline), \
             patch("bot.pipeline_order_submitter.PipelineRequest", request_type):
            out = submit_market_order_via_pipeline(
                broker, "BTC-USD", "buy", 10.0,
                metadata_override=handle.to_metadata(),
            )
        self.assertEqual(out["status"], "state_unknown")
        self.assertEqual(registry.get_state(handle), "state_unknown")

    def test_scalar_portfolio_mismatch_rejected_with_explicit_decision_context(self):
        tc = TradingContext(
            user_id="user-a", trading_account_id="acct-a", broker="kraken",
            broker_account_id="ka", strategy_instance_id="orb", portfolio_id="pf-a",
            request_id="req", correlation_id="corr", environment="test", mode="paper",
        )
        raw = RawSignal(
            symbol="ETH-USD", side="buy", action="enter_long", size_usd=10,
            confidence=.8, regime="trending", strategy="orb", approved=True,
            portfolio_id="pf-b", trading_context=tc,
        )
        dc = UserDecisionContext(
            user_id="user-a", account_id="acct-a", broker="kraken",
            portfolio_id="pf-a", strategy_signal_id="sig", trade_id="trade",
        )
        self.assertIsNone(SignalPipeline._resolve_decision_context(raw, dc))

    def test_dispatch_disabled_direct_submitter_releases_reservation(self):
        broker = SimpleNamespace(broker_name="coinbase", connected=True, get_account_balance=lambda: 1000.0)
        result = SimpleNamespace(success=False, order_id=None, error="dispatch_disabled: dispatch.enabled=false")
        pipeline = SimpleNamespace(execute=lambda request: result)
        registry, handle = self._reserve_duplicate_handle("pre-submit-denial")
        request_type = lambda **kwargs: SimpleNamespace(**kwargs)
        with patch("bot.pipeline_order_submitter.assert_distributed_writer_authority", return_value=None), \
             patch("bot.pipeline_order_submitter.get_execution_pipeline", return_value=pipeline), \
             patch("bot.pipeline_order_submitter.PipelineRequest", request_type):
            out = submit_market_order_via_pipeline(
                broker, "BTC-USD", "buy", 10.0, metadata_override=handle.to_metadata(),
            )
        self.assertEqual(out["status"], "error")
        self.assertTrue(out["v2_pre_submit_proven"])
        self.assertIsNone(registry.get_state(handle))

    def test_kraken_v366_open_positions_success_proves_margin_visibility(self):
        broker = SimpleNamespace(connected=True)
        with patch(
            "bot.runtime_kraken_margin_canonical_coverage_v366_patch.fetch_margin_positions",
            return_value=(True, {"ETH-USD": {"quantity": 0.1}}, "ok"),
        ):
            self.assertTrue(SignalBroadcaster._kraken_margin_visibility_proven(broker))

    def test_kraken_v366_open_positions_error_fails_closed(self):
        broker = SimpleNamespace(connected=True)
        with patch(
            "bot.runtime_kraken_margin_canonical_coverage_v366_patch.fetch_margin_positions",
            return_value=(False, {}, "openpositions_rejected:EGeneral:Temporary lockout"),
        ):
            self.assertFalse(SignalBroadcaster._kraken_margin_visibility_proven(broker))

    def test_connection_reset_without_order_id_stays_state_unknown(self):
        broker = SimpleNamespace(broker_name="coinbase", connected=True, get_account_balance=lambda: 1000.0)
        result = SimpleNamespace(success=False, order_id=None, error="connection reset by peer")
        pipeline = SimpleNamespace(execute=lambda request: result)
        registry, handle = self._reserve_duplicate_handle("connection-reset")
        request_type = lambda **kwargs: SimpleNamespace(**kwargs)
        with patch("bot.pipeline_order_submitter.assert_distributed_writer_authority", return_value=None), \
             patch("bot.pipeline_order_submitter.get_execution_pipeline", return_value=pipeline), \
             patch("bot.pipeline_order_submitter.PipelineRequest", request_type):
            out = submit_market_order_via_pipeline(
                broker, "BTC-USD", "buy", 10.0, metadata_override=handle.to_metadata(),
            )
        self.assertEqual(out["status"], "state_unknown")
        self.assertEqual(registry.get_state(handle), "state_unknown")

    def test_missing_strategy_uses_stable_v2_scope_not_signal_uuid(self):
        raw = RawSignal(
            symbol="ETH-USD", side="buy", action="enter_long", size_usd=10,
            confidence=.8, regime="trending", strategy="   ", approved=True,
        )
        dc = UserDecisionContext(
            user_id="user-a", account_id="acct-a", broker="coinbase",
            portfolio_id="pf-a", strategy_signal_id="random-signal-uuid", trade_id="trade",
        )
        tc = SignalPipeline._trading_context_from_decision_context(raw, dc)
        self.assertEqual(tc.strategy_instance_id, "v2_strategy")


if __name__ == "__main__":
    unittest.main()
