from __future__ import annotations

import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from bot.control.decision_context import UserDecisionContext, UserScopedIdempotencyRegistry
from bot.execution_pipeline import ExecutionPipeline, PipelineRequest
from bot.execution_router import ExecutionRouter
from bot.multi_broker_execution_router import MultiBrokerExecutionRouter
from bot.pipeline_order_submitter import _v2_duplicate_metadata_state


def _decision() -> UserDecisionContext:
    return UserDecisionContext(
        user_id="user-a",
        account_id="acct-a",
        broker="coinbase",
        portfolio_id="portfolio-a",
        strategy_signal_id="break-retest-signal",
        trade_id="trade-a",
        execution_mode="paper",
        environment="test",
    )


class TestPost2823FinalSafety(unittest.TestCase):
    def test_key_and_token_without_shared_authority_flag_is_partial(self):
        self.assertEqual(
            _v2_duplicate_metadata_state(
                {"duplicate_key": "v2:key", "duplicate_token": "token"}
            ),
            "partial",
        )
        self.assertEqual(
            _v2_duplicate_metadata_state(
                {
                    "duplicate_key": "v2:key",
                    "duplicate_token": "token",
                    "duplicate_shared_required": False,
                }
            ),
            "complete",
        )

    def test_stale_local_handle_cannot_overwrite_newer_fallback_reservation(self):
        with patch("bot.control.decision_context._default_redis_client", return_value=None):
            registry = UserScopedIdempotencyRegistry(redis_client=None, ttl_seconds=1.0)
            context = _decision()
            ok_old, old_handle = registry.reserve(
                context,
                symbol="BTC-USD",
                direction="long",
            )
            self.assertTrue(ok_old)

            with registry._lock:
                registry._states[old_handle.key]["expires_at"] = time.monotonic() - 1.0

            ok_new, new_handle = registry.reserve(
                context,
                symbol="BTC-USD",
                direction="long",
            )
            self.assertTrue(ok_new)
            self.assertEqual(old_handle.key, new_handle.key)
            self.assertNotEqual(old_handle.token, new_handle.token)

            self.assertFalse(registry.mark_state(old_handle, "state_unknown"))
            self.assertEqual(registry.get_state(new_handle), "submitted")
            self.assertFalse(registry.release(old_handle))
            self.assertEqual(registry.get_state(new_handle), "submitted")

    def test_break_retest_entry_does_not_dispatch_without_protection_capability(self):
        pipeline = object.__new__(ExecutionPipeline)
        pipeline._ecel_required = True
        pipeline._ack_timeout_s = 1.0
        pipeline._multi_router = MagicMock()
        pipeline._multi_router.supports_v2_protected_entry = False
        pipeline._router = MagicMock()
        pipeline._router.supports_v2_protected_entry = False

        request = PipelineRequest(
            strategy="BREAK_RETEST",
            symbol="BTC-USD",
            side="buy",
            size_usd=100.0,
            intent_type="entry",
            stop_loss_pct=0.01,
            take_profit_pct=0.02,
            validated=True,
        )

        with patch(
            "bot.execution_pipeline.runtime_authority_snapshot",
            return_value=SimpleNamespace(dispatch_enabled=True),
        ):
            result = pipeline._dispatch(request, time.monotonic())

        self.assertFalse(result.success)
        self.assertIn("entry_protection_unavailable", result.error)
        pipeline._multi_router.route.assert_not_called()
        pipeline._router.execute.assert_not_called()

    def test_router_must_explicitly_advertise_protected_entry_support(self):
        request = PipelineRequest(
            strategy="BREAK_RETEST",
            symbol="BTC-USD",
            side="buy",
            size_usd=100.0,
            intent_type="entry",
            stop_loss_pct=0.01,
            take_profit_pct=0.02,
            validated=True,
        )
        unsupported = SimpleNamespace()
        supported = SimpleNamespace(supports_v2_protected_entry=True)
        self.assertFalse(
            ExecutionPipeline._router_supports_verified_entry_protection(
                unsupported,
                request,
            )
        )
        self.assertTrue(
            ExecutionPipeline._router_supports_verified_entry_protection(
                supported,
                request,
            )
        )

    def test_concrete_live_routers_explicitly_fail_closed_for_break_retest(self):
        self.assertFalse(ExecutionRouter.supports_v2_protected_entry)
        self.assertFalse(MultiBrokerExecutionRouter.supports_v2_protected_entry)

    def test_capability_enabled_multi_router_can_route_protected_entry(self):
        pipeline = object.__new__(ExecutionPipeline)
        pipeline._ecel_required = True
        pipeline._ack_timeout_s = 1.0
        pipeline._multi_router = MagicMock()
        pipeline._multi_router.supports_v2_protected_entry = True
        pipeline._multi_router.route.return_value = SimpleNamespace(
            success=True,
            fill_price=101.0,
            filled_size_usd=100.0,
            broker="verified-protection-router",
            order_id="order-1",
            error="",
        )
        pipeline._router = None

        request = PipelineRequest(
            strategy="BREAK_RETEST",
            symbol="BTC-USD",
            side="buy",
            size_usd=100.0,
            intent_type="entry",
            stop_loss_pct=0.01,
            take_profit_pct=0.02,
            validated=True,
        )

        with patch(
            "bot.execution_pipeline.runtime_authority_snapshot",
            return_value=SimpleNamespace(dispatch_enabled=True),
        ):
            result = pipeline._dispatch(request, time.monotonic())

        self.assertTrue(result.success)
        pipeline._multi_router.route.assert_called_once()

    def test_capability_enabled_single_router_can_route_when_multi_unavailable(self):
        pipeline = object.__new__(ExecutionPipeline)
        pipeline._ecel_required = True
        pipeline._ack_timeout_s = 1.0
        pipeline._multi_router = None
        pipeline._router = MagicMock()
        pipeline._router.supports_v2_protected_entry = True
        pipeline._router.execute.return_value = SimpleNamespace(
            success=True,
            fill_price=101.0,
            filled_size_usd=100.0,
            order_id="order-2",
            error="",
        )

        request = PipelineRequest(
            strategy="BREAK_RETEST",
            symbol="BTC-USD",
            side="buy",
            size_usd=100.0,
            intent_type="entry",
            stop_loss_pct=0.01,
            take_profit_pct=0.02,
            validated=True,
        )

        with patch(
            "bot.execution_pipeline.runtime_authority_snapshot",
            return_value=SimpleNamespace(dispatch_enabled=True),
        ):
            result = pipeline._dispatch(request, time.monotonic())

        self.assertTrue(result.success)
        pipeline._router.execute.assert_called_once()

    def test_expired_local_handle_cannot_be_revived_by_state_transition(self):
        with patch("bot.control.decision_context._default_redis_client", return_value=None):
            registry = UserScopedIdempotencyRegistry(redis_client=None, ttl_seconds=1.0)
            context = _decision()
            ok, handle = registry.reserve(
                context,
                symbol="ETH-USD",
                direction="long",
            )
            self.assertTrue(ok)
            with registry._lock:
                registry._states[handle.key]["expires_at"] = time.monotonic() - 1.0

            self.assertFalse(registry.mark_state(handle, "state_unknown"))
            self.assertIsNone(registry.get_state(handle))
            self.assertNotIn(handle.key, registry._reservation_tokens)


    def test_router_capability_flags_preserve_class_docstrings(self):
        self.assertIsInstance(ExecutionRouter.__doc__, str)
        self.assertIn("Smart Order Router", ExecutionRouter.__doc__)
        self.assertIsInstance(MultiBrokerExecutionRouter.__doc__, str)
        self.assertIn("Routes trade orders", MultiBrokerExecutionRouter.__doc__)



if __name__ == "__main__":
    unittest.main()
