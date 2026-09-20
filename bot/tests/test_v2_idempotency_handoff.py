from __future__ import annotations

import unittest
from unittest.mock import patch

from bot.control.decision_context import (
    IdempotencyReservationHandle,
    UserDecisionContext,
    get_user_scoped_idempotency_registry,
)
from bot.pipeline_order_submitter import _finalize_v2_duplicate
from bot.signal_broadcaster import SignalBroadcaster


class _Broker:
    broker_name = "coinbase"
    user_id = "user-a"

    def get_account_balance(self):
        return 1000.0


class TestV2IdempotencyHandoff(unittest.TestCase):
    def _reserve(self, trade_id: str) -> tuple[str, str]:
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
        allowed, key, token = registry.reserve(context, symbol="BTC-USD", direction="long")
        self.assertTrue(allowed)
        return key, token

    def test_release_removes_shared_reservation(self):
        registry = get_user_scoped_idempotency_registry()
        key, token = self._reserve("trade-release")
        _finalize_v2_duplicate({"duplicate_key": key, "duplicate_token": token}, "released")
        self.assertIsNone(registry.get_state(key))

    def test_pending_submission_remains_blocked_for_reconciliation(self):
        registry = get_user_scoped_idempotency_registry()
        key, token = self._reserve("trade-pending")
        _finalize_v2_duplicate({"duplicate_key": key, "duplicate_token": token}, "submitted_pending")
        self.assertEqual(registry.get_state(key), "submitted_pending")

    def test_filled_submission_records_terminal_state(self):
        registry = get_user_scoped_idempotency_registry()
        key, token = self._reserve("trade-filled")
        _finalize_v2_duplicate({"duplicate_key": key, "duplicate_token": token}, "reconciled_filled")
        self.assertEqual(registry.get_state(key), "reconciled_filled")
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
                    "duplicate_token": "owner-token",
                    "duplicate_token": "token-1",
                    "duplicate_shared_required": True,
                },
                "BTC-USD",
                "buy",
                None,
            )

        self.assertEqual(result.status, "pending")
        self.assertEqual(seen["metadata_override"]["duplicate_key"], "v2:test-key")
        self.assertEqual(seen["metadata_override"]["duplicate_token"], "owner-token")
        self.assertEqual(seen["metadata_override"]["duplicate_token"], "token-1")
        self.assertTrue(seen["metadata_override"]["duplicate_shared_required"])


if __name__ == "__main__":
    unittest.main()
