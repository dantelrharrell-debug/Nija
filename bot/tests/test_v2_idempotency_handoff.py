from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import patch

from bot.control.decision_context import (
    IdempotencyReservationHandle,
    UserDecisionContext,
    get_user_scoped_idempotency_registry,
)
import bot.pipeline_order_submitter as submitter
from bot.pipeline_order_submitter import _finalize_v2_duplicate
from bot.signal_broadcaster import SignalBroadcaster


class _Broker:
    broker_name = "coinbase"
    user_id = "user-a"

    def get_account_balance(self):
        return 1000.0


class TestV2IdempotencyHandoff(unittest.TestCase):
    def _reserve(self, trade_id: str) -> IdempotencyReservationHandle:
        registry = get_user_scoped_idempotency_registry()
        context = UserDecisionContext(
            user_id="user-a",
            account_id="acct-a",
            broker="coinbase",
            portfolio_id="coinbase:acct-a",
            strategy_signal_id="sig-handoff",
            trade_id=trade_id,
        )
        allowed, handle = registry.reserve(context, symbol="BTC-USD", direction="long")
        self.assertTrue(allowed)
        return handle

    def test_release_removes_shared_reservation(self):
        registry = get_user_scoped_idempotency_registry()
        handle = self._reserve("trade-release")
        _finalize_v2_duplicate(handle.to_metadata(), "released")
        self.assertIsNone(registry.get_state(handle))

    def test_pending_submission_remains_blocked_for_reconciliation(self):
        registry = get_user_scoped_idempotency_registry()
        handle = self._reserve("trade-pending")
        _finalize_v2_duplicate(handle.to_metadata(), "submitted_pending")
        self.assertEqual(registry.get_state(handle), "submitted_pending")

    def test_filled_submission_records_terminal_state(self):
        registry = get_user_scoped_idempotency_registry()
        handle = self._reserve("trade-filled")
        _finalize_v2_duplicate(handle.to_metadata(), "reconciled_filled")
        self.assertEqual(registry.get_state(handle), "reconciled_filled")

    def test_broadcaster_forwards_duplicate_key_to_submitter(self):
        broadcaster = SignalBroadcaster(risk_fraction=0.1)
        broker = _Broker()
        broadcaster.register_account("acct-a", broker, balance=1000.0)
        seen = {}

        def fake_submit(**kwargs):
            seen.update(kwargs)
            return {"status": "pending", "order_id": "order-1"}

        with patch("bot.signal_broadcaster.submit_market_order_via_pipeline", side_effect=fake_submit):
            result = broadcaster._execute_single(
                broadcaster._accounts["acct-a"],
                {
                    "symbol": "BTC-USD",
                    "duplicate_key": "v2:test-key",
                    "duplicate_token": "token-1",
                    "duplicate_shared_required": True,
                },
                "BTC-USD",
                "buy",
                None,
            )

        self.assertEqual(result.status, "pending")
        self.assertEqual(seen["metadata_override"]["duplicate_key"], "v2:test-key")
        self.assertEqual(seen["metadata_override"]["duplicate_token"], "token-1")
        self.assertTrue(seen["metadata_override"]["duplicate_shared_required"])

    def test_broadcaster_preserves_partial_duplicate_metadata_for_fail_closed_submitter(self):
        broadcaster = SignalBroadcaster(risk_fraction=0.1)
        broker = _Broker()
        broadcaster.register_account("acct-a", broker, balance=1000.0)

        for partial_metadata in (
            {"duplicate_key": "v2:missing-token"},
            {"duplicate_token": "token-without-key"},
        ):
            with self.subTest(partial_metadata=partial_metadata):
                seen = {}

                def fake_submit(**kwargs):
                    seen.update(kwargs)
                    return {"status": "error", "error": "v2_duplicate_metadata_incomplete"}

                with patch(
                    "bot.signal_broadcaster.submit_market_order_via_pipeline",
                    side_effect=fake_submit,
                ):
                    result = broadcaster._execute_single(
                        broadcaster._accounts["acct-a"],
                        {"symbol": "BTC-USD", **partial_metadata},
                        "BTC-USD",
                        "buy",
                        None,
                    )

                self.assertEqual(result.status, "error")
                self.assertEqual(result.order_result["error"], "v2_duplicate_metadata_incomplete")
                for field_name, value in partial_metadata.items():
                    self.assertEqual(seen["metadata_override"][field_name], value)

    def test_broadcaster_forwards_break_retest_protection_to_submitter(self):
        broadcaster = SignalBroadcaster(risk_fraction=0.1)
        broker = _Broker()
        broadcaster.register_account("acct-a", broker, balance=1000.0)
        seen = {}

        def fake_submit(**kwargs):
            seen.update(kwargs)
            return {"status": "pending", "order_id": "order-1"}

        with patch("bot.signal_broadcaster.submit_market_order_via_pipeline", side_effect=fake_submit):
            result = broadcaster._execute_single(
                broadcaster._accounts["acct-a"],
                {
                    "symbol": "BTC-USD",
                    "strategy": "BREAK_RETEST",
                    "stop_loss_pct": 0.01,
                    "take_profit_pct": 0.02,
                    "duplicate_key": "v2:test-key",
                    "duplicate_token": "token-1",
                    "duplicate_shared_required": True,
                },
                "BTC-USD",
                "buy",
                None,
            )

        self.assertEqual(result.status, "pending")
        self.assertEqual(seen["strategy"], "BREAK_RETEST")
        self.assertEqual(seen["metadata_override"]["stop_loss_pct"], 0.01)
        self.assertEqual(seen["metadata_override"]["take_profit_pct"], 0.02)

    def test_submitter_carries_protection_and_arms_reservation_before_dispatch(self):
        seen = {}

        def execute(request):
            seen["request"] = request
            return SimpleNamespace(
                success=False,
                error="dispatch_disabled: dispatch.enabled=false",
                order_id="",
            )

        pipeline = SimpleNamespace(execute=execute)
        with patch.object(submitter, "_resolve_execution_pipeline_dependencies", return_value=(SimpleNamespace, lambda: pipeline)), \
             patch.object(submitter, "assert_distributed_writer_authority"), \
             patch.object(submitter, "_prepare_v2_duplicate_handoff", return_value=True) as prepare, \
             patch.object(submitter, "_finalize_v2_duplicate", return_value=True):
            result = submitter.submit_market_order_via_pipeline(
                _Broker(),
                "BTC-USD",
                "buy",
                25.0,
                strategy="BREAK_RETEST",
                metadata_override={
                    "duplicate_key": "v2:test-key",
                    "duplicate_token": "token-1",
                    "duplicate_shared_required": True,
                    "stop_loss_pct": 0.01,
                    "take_profit_pct": 0.02,
                },
            )

        self.assertEqual(result["status"], "error")
        prepare.assert_called_once()
        self.assertEqual(seen["request"].stop_loss_pct, 0.01)
        self.assertEqual(seen["request"].take_profit_pct, 0.02)
        self.assertTrue(seen["request"].metadata["protection_required"])


if __name__ == "__main__":
    unittest.main()
