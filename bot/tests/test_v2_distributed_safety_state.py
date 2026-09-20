from __future__ import annotations

import threading
import time
import unittest
from unittest.mock import patch

from bot.control.decision_context import (
    UserDecisionContext,
    UserScopedIdempotencyRegistry,
)
from bot.control.risk_engine import RiskEngine
from bot.control.trading_context import TradingContext


class _SharedFakeRedis:
    """Tiny thread-safe Redis subset for distributed-safety tests."""

    def __init__(self):
        self._lock = threading.Lock()
        self._values = {}
        self._expires = {}

    def _purge(self, key):
        expires = self._expires.get(key)
        if expires is not None and time.monotonic() >= expires:
            self._values.pop(key, None)
            self._expires.pop(key, None)

    def set(self, key, value, nx=False, px=None, ex=None):
        with self._lock:
            self._purge(key)
            if nx and key in self._values:
                return False
            self._values[key] = value
            ttl = (float(px) / 1000.0) if px is not None else (float(ex) if ex is not None else None)
            if ttl is None:
                self._expires.pop(key, None)
            else:
                self._expires[key] = time.monotonic() + ttl
            return True

    def get(self, key):
        with self._lock:
            self._purge(key)
            return self._values.get(key)

    def delete(self, key):
        with self._lock:
            existed = key in self._values
            self._values.pop(key, None)
            self._expires.pop(key, None)
            return int(existed)


def _decision(
    *,
    user="user-a",
    account="acct-a",
    trade="trade-a",
    mode="paper",
    environment="test",
):
    return UserDecisionContext(
        user_id=user,
        account_id=account,
        broker="kraken",
        portfolio_id=f"kraken:{account}",
        strategy_signal_id="FIRST_CANDLE_ORB:BTC-USD:session",
        trade_id=trade,
        execution_mode=mode,
        environment=environment,
    )


def _trading(
    *,
    user="user-a",
    account="acct-a",
    environment="test",
    mode="paper",
):
    return TradingContext(
        user_id=user,
        trading_account_id=account,
        broker="kraken",
        broker_account_id=f"kraken-{account}",
        strategy_instance_id="FIRST_CANDLE_ORB",
        portfolio_id=f"kraken:{account}",
        request_id=f"request:{user}:{account}",
        correlation_id=f"corr:{user}:{account}",
        environment=environment,
        mode=mode,
        decision_id=f"decision:{user}:{account}",
    )


class TestDistributedV2Idempotency(unittest.TestCase):
    def test_two_registry_instances_share_one_atomic_reservation(self):
        redis = _SharedFakeRedis()
        a = UserScopedIdempotencyRegistry(redis_client=redis)
        b = UserScopedIdempotencyRegistry(redis_client=redis)
        ctx = _decision()

        first, key_a, token_a = a.reserve(ctx, symbol="BTC-USD", direction="long")
        second, key_b, token_b = b.reserve(ctx, symbol="BTC-USD", direction="long")

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(key_a, key_b)
        self.assertTrue(token_a)
        self.assertFalse(token_b)
        self.assertEqual(b.get_state(key_b), "submitted")
        first, handle_a = a.reserve(ctx, symbol="BTC-USD", direction="long")
        second, handle_b = b.reserve(ctx, symbol="BTC-USD", direction="long")

        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(handle_a.key, handle_b.key)
        self.assertEqual(b.get_state(handle_b), "submitted")

    def test_different_users_do_not_collide_across_workers(self):
        redis = _SharedFakeRedis()
        a = UserScopedIdempotencyRegistry(redis_client=redis)
        b = UserScopedIdempotencyRegistry(redis_client=redis)

        ok_a, key_a, _ = a.reserve(
            _decision(user="user-a", account="acct-a"), symbol="BTC-USD", direction="long"
        )
        ok_b, key_b, _ = b.reserve(
            _decision(user="user-b", account="acct-b"), symbol="BTC-USD", direction="long"
        )
        ok_a, handle_a = a.reserve(_decision(user="user-a", account="acct-a"), symbol="BTC-USD", direction="long")
        ok_b, handle_b = b.reserve(_decision(user="user-b", account="acct-b"), symbol="BTC-USD", direction="long")

        self.assertTrue(ok_a)
        self.assertTrue(ok_b)
        self.assertNotEqual(handle_a.key, handle_b.key)

    def test_state_unknown_remains_visible_to_other_worker(self):
        redis = _SharedFakeRedis()
        a = UserScopedIdempotencyRegistry(redis_client=redis)
        b = UserScopedIdempotencyRegistry(redis_client=redis)
        ctx = _decision()

        ok, key, token = a.reserve(ctx, symbol="BTC-USD", direction="long")
        self.assertTrue(ok)
        a.mark_state(key, "state_unknown", token=token)

        self.assertEqual(b.get_state(key), "state_unknown")
        retry, _, _ = b.reserve(ctx, symbol="BTC-USD", direction="long")
        ok, handle = a.reserve(ctx, symbol="BTC-USD", direction="long")
        self.assertTrue(ok)
        a.mark_state(handle, "state_unknown")

        self.assertEqual(b.get_state(handle), "state_unknown")
        retry, _ = b.reserve(ctx, symbol="BTC-USD", direction="long")
        self.assertFalse(retry)

    def test_proven_pre_submit_release_allows_retry_on_other_worker(self):
        redis = _SharedFakeRedis()
        a = UserScopedIdempotencyRegistry(redis_client=redis)
        b = UserScopedIdempotencyRegistry(redis_client=redis)
        ctx = _decision()

        ok, key, token = a.reserve(ctx, symbol="BTC-USD", direction="long")
        self.assertTrue(ok)
        a.release(key, token=token)
        ok, handle = a.reserve(ctx, symbol="BTC-USD", direction="long")
        self.assertTrue(ok)
        a.release(handle)

        retry, _, _ = b.reserve(ctx, symbol="BTC-USD", direction="long")
        self.assertTrue(retry)

    def test_production_live_fails_closed_without_shared_backend(self):
        with patch("bot.control.decision_context._default_redis_client", return_value=None):
            registry = UserScopedIdempotencyRegistry(redis_client=None)
            ok, _, _ = registry.reserve(
                _decision(mode="live", environment="production"),
                symbol="BTC-USD",
                direction="long",
            )
        self.assertFalse(ok)


class TestDistributedV2RiskState(unittest.TestCase):
    def test_user_kill_switch_propagates_between_engine_instances(self):
        redis = _SharedFakeRedis()
        setter = RiskEngine(redis_client=redis)
        reader = RiskEngine(redis_client=redis)
        ctx = _trading()

        setter.set_user_kill_switch(ctx.user_id, True, "manual_halt")
        approved, notes = reader.validate_trade(
            "BTC-USD", "buy", 50.0, 10_000.0, [],
            trading_context=ctx,
            enforce_isolation=True,
        )

        self.assertFalse(approved)
        self.assertIn("user_kill_switch:manual_halt", notes[0])

    def test_account_kill_switch_isolated_across_users(self):
        redis = _SharedFakeRedis()
        setter = RiskEngine(redis_client=redis)
        reader = RiskEngine(redis_client=redis)
        ctx_a = _trading(user="user-a", account="acct-a")
        ctx_b = _trading(user="user-b", account="acct-b")

        setter.set_account_kill_switch(ctx_a, True, "account_halt")
        denied_a, _ = reader.validate_trade(
            "BTC-USD", "buy", 50.0, 10_000.0, [],
            trading_context=ctx_a, enforce_isolation=True,
        )
        allowed_b, notes_b = reader.validate_trade(
            "BTC-USD", "buy", 50.0, 10_000.0, [],
            trading_context=ctx_b, enforce_isolation=True,
        )

        self.assertFalse(denied_a)
        self.assertTrue(allowed_b, notes_b)

    def test_trade_frequency_is_atomic_across_engine_instances(self):
        redis = _SharedFakeRedis()
        first = RiskEngine(redis_client=redis)
        second = RiskEngine(redis_client=redis)
        ctx = _trading()

        approved_first, notes_first = first.validate_trade(
            "BTC-USD", "buy", 50.0, 10_000.0, [],
            trading_context=ctx, enforce_isolation=True,
        )
        approved_second, notes_second = second.validate_trade(
            "BTC-USD", "buy", 50.0, 10_000.0, [],
            trading_context=ctx, enforce_isolation=True,
        )

        self.assertTrue(approved_first, notes_first)
        self.assertFalse(approved_second)
        self.assertIn("trade_frequency_limit", notes_second[0])

    def test_production_live_fails_closed_without_shared_risk_state(self):
        ctx = _trading(environment="production", mode="live")
        with patch("bot.control.decision_context._default_redis_client", return_value=None):
            engine = RiskEngine(redis_client=None)
            approved, notes = engine.validate_trade(
                "BTC-USD", "buy", 50.0, 10_000.0, [],
                trading_context=ctx, enforce_isolation=True,
            )
        self.assertFalse(approved)
        self.assertIn("shared_risk_state_unavailable", notes[0])


if __name__ == "__main__":
    unittest.main()
