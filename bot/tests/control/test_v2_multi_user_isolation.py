from __future__ import annotations

import concurrent.futures
import json
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import ANY, MagicMock, patch

import pandas as pd

from bot.control.control_compiler import ControlCompiler, RawSignal
from bot.control.isolation_guards import (
    ExecutionOwnershipEnvelope,
    PositionSizingDecision,
    ScopedRiskSnapshot,
    context_cache_key,
    validate_owner_account_authorization,
    validate_queue_event_context,
    verify_execution_ownership,
    verify_position_ownership,
)
from bot.control.risk_engine import RiskEngine
from bot.control.signal_pipeline import SignalPipeline
from bot.control.strategy_signal import StrategySignal
from bot.control.trading_context import TradingContext


def _ctx(user: str, account: str, broker_account: str, strategy: str = "orb_v2") -> TradingContext:
    return TradingContext(
        user_id=user,
        trading_account_id=account,
        broker="kraken",
        broker_account_id=broker_account,
        strategy_instance_id=strategy,
        portfolio_id=f"pf_{user}",
        request_id=f"req_{user}",
        correlation_id=f"corr_{user}",
        environment="test",
        mode="paper",
    )


def _raw(context: TradingContext, **overrides) -> RawSignal:
    base = dict(
        symbol="BTC-USD",
        side="buy",
        action="enter_long",
        size_usd=100.0,
        confidence=0.8,
        regime="trending",
        strategy="swing",
        approved=True,
        account_id=context.trading_account_id,
        trading_context=context,
    )
    base.update(overrides)
    return RawSignal(**base)


def _position(context: TradingContext, symbol: str = "BTC-USD", size_usd: float = 100.0) -> dict:
    return {
        "position_id": f"pos_{context.user_id}_{symbol}",
        "symbol": symbol,
        "size_usd": size_usd,
        "user_id": context.user_id,
        "trading_account_id": context.trading_account_id,
        "broker": context.broker,
        "broker_account_id": context.broker_account_id,
    }


def _snapshot(
    context: TradingContext,
    *,
    balance: float = 1_000.0,
    portfolio: float = 10_000.0,
    daily_pnl: float = 0.0,
    peak: float | None = None,
    positions=(),
) -> ScopedRiskSnapshot:
    return ScopedRiskSnapshot.from_values(
        context=context,
        portfolio_value_usd=portfolio,
        current_positions=positions,
        daily_pnl=daily_pnl,
        peak_portfolio_value=peak,
        available_balance_usd=balance,
    )


class TestV2MultiUserIsolation(unittest.TestCase):
    def setUp(self):
        self.ctx_a = _ctx("user_a", "acct_a", "kraken_a", strategy="orb_a")
        self.ctx_b = _ctx("user_b", "acct_b", "kraken_b", strategy="orb_b")
        self.risk = RiskEngine()
        self.pipeline = SignalPipeline(compiler=ControlCompiler(), risk_engine=self.risk)

    def test_01_user_a_low_balance_does_not_change_user_b_decision(self):
        denied_a, notes_a = self.risk.validate_trade(
            "BTC-USD", "buy", 100.0, 10_000.0, [],
            available_balance_usd=25.0,
            trading_context=self.ctx_a,
        )
        approved_b, notes_b = self.risk.validate_trade(
            "BTC-USD", "buy", 100.0, 10_000.0, [],
            available_balance_usd=1_000.0,
            trading_context=self.ctx_b,
        )
        self.assertFalse(denied_a)
        self.assertIn("insufficient_available_balance", notes_a[0])
        self.assertTrue(approved_b, notes_b)

    def test_02_user_a_open_position_does_not_block_user_b(self):
        positions = [_position(self.ctx_a) for _ in range(8)] + [_position(self.ctx_b, "ETH-USD")]
        ok, notes = self.risk.validate_trade(
            symbol="BTC-USD",
            side="buy",
            size_usd=100.0,
            portfolio_value_usd=10_000.0,
            current_positions=positions,
            trading_context=self.ctx_b,
            enforce_isolation=True,
        )
        self.assertTrue(ok, notes)

    def test_03_user_a_position_not_in_user_b_exposure(self):
        positions = [
            {"symbol": "BTC-USD", "size_usd": 100.0, "user_id": "user_a", "trading_account_id": "acct_a", "broker": "kraken", "broker_account_id": "kraken_a"},
            {"symbol": "ETH-USD", "size_usd": 100.0, "user_id": "user_b", "trading_account_id": "acct_b", "broker": "kraken", "broker_account_id": "kraken_b"},
        ]
        filtered = self.risk._filter_positions_for_context(positions, self.ctx_b)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["symbol"], "ETH-USD")

    def test_04_user_a_realized_loss_does_not_trigger_user_b_limit(self):
        denied_a, _ = self.risk.validate_trade(
            symbol="BTC-USD",
            side="buy",
            size_usd=50.0,
            portfolio_value_usd=10_000.0,
            current_positions=[],
            daily_pnl=-500.0,
            trading_context=self.ctx_a,
        )
        approved_b, _ = self.risk.validate_trade(
            symbol="BTC-USD",
            side="buy",
            size_usd=50.0,
            portfolio_value_usd=10_000.0,
            current_positions=[],
            daily_pnl=-10.0,
            trading_context=self.ctx_b,
            enforce_isolation=True,
        )
        self.assertFalse(denied_a)
        self.assertTrue(approved_b)

    def test_05_user_a_drawdown_does_not_change_user_b_approval(self):
        denied_a, _ = self.risk.validate_trade(
            symbol="ETH-USD",
            side="buy",
            size_usd=50.0,
            portfolio_value_usd=8_000.0,
            peak_portfolio_value=10_000.0,
            current_positions=[],
            trading_context=self.ctx_a,
        )
        approved_b, _ = self.risk.validate_trade(
            symbol="ETH-USD",
            side="buy",
            size_usd=50.0,
            portfolio_value_usd=10_000.0,
            peak_portfolio_value=10_100.0,
            current_positions=[],
            trading_context=self.ctx_b,
            enforce_isolation=True,
        )
        self.assertFalse(denied_a)
        self.assertTrue(approved_b)

    def test_06_user_a_loss_streak_does_not_cooldown_user_b(self):
        ok_a, _ = self.risk.validate_trade("BTC-USD", "buy", 50.0, 10_000.0, [], trading_context=self.ctx_a, enforce_isolation=True)
        ok_b, _ = self.risk.validate_trade("BTC-USD", "buy", 50.0, 10_000.0, [], trading_context=self.ctx_b, enforce_isolation=True)
        self.assertTrue(ok_a)
        self.assertTrue(ok_b)

    def test_07_user_kill_switch_only_blocks_target_user(self):
        self.risk.set_user_kill_switch("user_a", True, "manual")
        denied, notes = self.risk.validate_trade("BTC-USD", "buy", 50.0, 10_000.0, [], trading_context=self.ctx_a, enforce_isolation=True)
        allowed, _ = self.risk.validate_trade("BTC-USD", "buy", 50.0, 10_000.0, [], trading_context=self.ctx_b, enforce_isolation=True)
        self.assertFalse(denied)
        self.assertIn("user_kill_switch", notes[0])
        self.assertTrue(allowed)

    def test_08_account_kill_switch_only_blocks_target_account(self):
        self.risk.set_account_kill_switch(self.ctx_a, True, "account_suspend")
        denied, _ = self.risk.validate_trade("BTC-USD", "buy", 50.0, 10_000.0, [], trading_context=self.ctx_a, enforce_isolation=True)
        allowed, _ = self.risk.validate_trade("BTC-USD", "buy", 50.0, 10_000.0, [], trading_context=self.ctx_b, enforce_isolation=True)
        self.assertFalse(denied)
        self.assertTrue(allowed)

    def test_09_platform_kill_switch_blocks_both_users(self):
        self.risk.set_platform_kill_switch(True, "platform_emergency")
        denied_a, _ = self.risk.validate_trade("BTC-USD", "buy", 50.0, 10_000.0, [], trading_context=self.ctx_a, enforce_isolation=True)
        denied_b, _ = self.risk.validate_trade("ETH-USD", "buy", 50.0, 10_000.0, [], trading_context=self.ctx_b, enforce_isolation=True)
        self.assertFalse(denied_a)
        self.assertFalse(denied_b)

    def test_10_broker_auth_failure_isolated_to_user(self):
        self.risk.set_broker_connection_kill_switch(self.ctx_a, True, "auth_failed")
        denied_a, _ = self.risk.validate_trade("BTC-USD", "buy", 50.0, 10_000.0, [], trading_context=self.ctx_a, enforce_isolation=True)
        allowed_b, _ = self.risk.validate_trade("BTC-USD", "buy", 50.0, 10_000.0, [], trading_context=self.ctx_b, enforce_isolation=True)
        self.assertFalse(denied_a)
        self.assertTrue(allowed_b)

    def test_11_retry_failure_counters_are_scoped(self):
        self.risk.record_broker_failure(self.ctx_a)
        self.risk.record_broker_failure(self.ctx_a)
        self.risk.record_broker_failure(self.ctx_b)
        self.assertEqual(self.risk._broker_failure_counters[(self.ctx_a.user_id, self.ctx_a.broker, self.ctx_a.broker_account_id)], 2)
        self.assertEqual(self.risk._broker_failure_counters[(self.ctx_b.user_id, self.ctx_b.broker, self.ctx_b.broker_account_id)], 1)

    def test_12_user_a_rejection_does_not_alter_user_b_state(self):
        self.risk.validate_trade("BTC-USD", "buy", 50.0, 10_000.0, [], trading_context=self.ctx_a, enforce_isolation=True)
        rejected_a, _ = self.risk.validate_trade("BTC-USD", "buy", 50.0, 10_000.0, [], trading_context=self.ctx_a, enforce_isolation=True)
        approved_b, _ = self.risk.validate_trade("BTC-USD", "buy", 50.0, 10_000.0, [], trading_context=self.ctx_b, enforce_isolation=True)
        self.assertFalse(rejected_a)
        self.assertTrue(approved_b)

    def test_13_strategy_state_keys_are_scoped_by_strategy_instance(self):
        key_a = context_cache_key(self.ctx_a, "orb", "BTC-USD")
        key_b = context_cache_key(self.ctx_b, "orb", "BTC-USD")
        self.assertNotEqual(key_a, key_b)

    def test_14_same_symbol_keeps_separate_state(self):
        a_key = self.ctx_a.make_idempotency_key(symbol="BTC-USD", side="buy", action="submit_order")
        b_key = self.ctx_b.make_idempotency_key(symbol="BTC-USD", side="buy", action="submit_order")
        self.assertNotEqual(a_key, b_key)

    def test_15_sl_tp_attach_only_to_owner_position(self):
        position = {"position_id": "pos_a", "user_id": "user_a", "trading_account_id": "acct_a", "broker": "kraken", "broker_account_id": "kraken_a"}
        verify_position_ownership(context=self.ctx_a, position=position)
        with self.assertRaises(ValueError):
            verify_position_ownership(context=self.ctx_b, position=position)

    def test_16_monitoring_job_cannot_modify_other_user_position(self):
        position = {"position_id": "pos_a", "user_id": "user_a", "trading_account_id": "acct_a", "broker": "kraken", "broker_account_id": "kraken_a"}
        with self.assertRaises(ValueError):
            verify_position_ownership(context=self.ctx_b, position=position)

    def test_17_mismatched_user_and_account_fails_closed(self):
        with self.assertRaises(ValueError):
            validate_owner_account_authorization(self.ctx_a, authorized_accounts={"acct_a": "user_b"})

    def test_18_missing_context_fails_closed(self):
        with self.assertRaises(ValueError):
            validate_queue_event_context({})

    def test_19_cross_user_cache_key_collisions_impossible(self):
        self.assertNotEqual(context_cache_key(self.ctx_a, "positions"), context_cache_key(self.ctx_b, "positions"))

    def test_20_cross_user_idempotency_cannot_suppress_orders(self):
        id_a = self.ctx_a.make_idempotency_key(symbol="BTC-USD", side="buy", action="submit_order")
        id_b = self.ctx_b.make_idempotency_key(symbol="BTC-USD", side="buy", action="submit_order")
        self.assertNotEqual(id_a, id_b)

    def test_21_concurrent_decisions_remain_isolated(self):
        results = []
        lock = threading.Lock()

        def _run(ctx: TradingContext, symbol: str) -> bool:
            ok, _ = self.risk.validate_trade(symbol, "buy", 50.0, 10_000.0, [], trading_context=ctx, enforce_isolation=True)
            with lock:
                results.append((ctx.user_id, ok))
            return ok

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            a = pool.submit(_run, self.ctx_a, "BTC-USD")
            b = pool.submit(_run, self.ctx_b, "BTC-USD")
            self.assertTrue(a.result(timeout=2))
            self.assertTrue(b.result(timeout=2))
        self.assertEqual({u for u, _ in results}, {"user_a", "user_b"})

    def test_22_queue_serialization_round_trip_restores_owner_scope(self):
        payload = {"trading_context": self.ctx_a.to_log_fields()}
        recovered = validate_queue_event_context(payload)
        self.assertEqual(recovered.user_id, "user_a")
        self.assertEqual(recovered.trading_account_id, "acct_a")

    def test_22b_queue_event_decision_id_mismatch_rejected(self):
        altered = TradingContext.from_mapping({**self.ctx_a.to_log_fields(), "decision_id": "other_decision"})
        with self.assertRaises(ValueError):
            validate_queue_event_context(
                {"trading_context": altered.to_log_fields()},
                expected_context=self.ctx_a,
                require_same_decision=True,
            )

    def test_23_scoped_snapshot_filters_foreign_kraken_positions(self):
        positions = [
            {"symbol": "BTC-USD", "size_usd": 100.0, "user_id": "user_a", "trading_account_id": "acct_a", "broker": "kraken", "broker_account_id": "kraken_a"},
            {"symbol": "BTC-USD", "size_usd": 200.0, "user_id": "user_b", "trading_account_id": "acct_b", "broker": "kraken", "broker_account_id": "kraken_b"},
        ]
        filtered = _snapshot(self.ctx_a, positions=positions).positions_for_owner()
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["broker_account_id"], "kraken_a")

    def test_24_logs_include_scope_without_credentials(self):
        redis = MagicMock()
        pipeline = SignalPipeline(compiler=ControlCompiler(redis_client=redis), risk_engine=RiskEngine(redis_client=redis), redis_client=redis)
        pipeline.process_signal(_raw(self.ctx_a), current_positions=[], portfolio_value_usd=10_000.0)
        self.assertTrue(redis.setex.called)
        key = redis.setex.call_args[0][0]
        payload = json.loads(redis.setex.call_args[0][2])
        self.assertNotIn("user_a", key)
        self.assertEqual(payload["context"]["user_id"], "user_a")
        self.assertNotIn("api_key", json.dumps(payload))

    def test_25_symbol_only_lookup_cannot_cross_user(self):
        positions = [
            {"symbol": "BTC-USD", "size_usd": 100.0, "user_id": "user_a", "trading_account_id": "acct_a", "broker": "kraken", "broker_account_id": "kraken_a"},
            {"symbol": "BTC-USD", "size_usd": 100.0, "user_id": "user_b", "trading_account_id": "acct_b", "broker": "kraken", "broker_account_id": "kraken_b"},
        ]
        filtered = self.risk._filter_positions_for_context(positions, self.ctx_b)
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["user_id"], "user_b")

    def test_adversarial_swapped_user_account_rejected(self):
        bad = TradingContext.from_mapping({**self.ctx_a.to_log_fields(), "user_id": "user_b"})
        with self.assertRaises(ValueError):
            validate_owner_account_authorization(bad, authorized_accounts={"acct_a": "user_a"})

    def test_adversarial_reused_request_ids_stay_scoped(self):
        b_same_req = TradingContext.from_mapping({**self.ctx_b.to_log_fields(), "request_id": self.ctx_a.request_id})
        self.assertNotEqual(
            self.ctx_a.make_idempotency_key(symbol="BTC-USD", side="buy", action="submit_order"),
            b_same_req.make_idempotency_key(symbol="BTC-USD", side="buy", action="submit_order"),
        )

    def test_adversarial_broker_account_mismatch_rejected(self):
        sizing = PositionSizingDecision(context=self.ctx_a, symbol="BTC-USD", side="buy", quantity=1.0, size_usd=100.0, stop_distance=10.0)
        mismatched = ExecutionOwnershipEnvelope(
            context=self.ctx_b,
            symbol="BTC-USD",
            side="buy",
            quantity=1.0,
            idempotency_key=self.ctx_b.make_idempotency_key(symbol="BTC-USD", side="buy", action="submit_order"),
            sizing_decision=sizing,
            risk_context=self.ctx_b,
        )
        with self.assertRaises(ValueError):
            verify_execution_ownership(mismatched)

    def test_detector_path_propagates_context_end_to_end(self):
        candidate = StrategySignal(
            strategy="swing",
            symbol="BTC-USD",
            broker="kraken",
            direction="long",
            trading_context=self.ctx_b,
            confidence=0.9,
            market_regime="trending",
        )
        self.pipeline._regime_engine.detect = MagicMock(
            return_value=SimpleNamespace(
                regime=SimpleNamespace(value="trending"),
                confidence=0.9,
                adx=30.0,
                rsi=55.0,
            ),
        )
        self.pipeline._detector_registry.detect = MagicMock(return_value=[candidate])
        self.pipeline._scoring_engine.score = MagicMock(return_value=SimpleNamespace(rejected=False, score=0.9))
        self.pipeline._confirmation_engine.confirm = MagicMock(
            return_value=SimpleNamespace(approved=True, reasons=[]),
        )
        result = self.pipeline.process_market_snapshot(
            symbol="BTC-USD",
            broker="kraken",
            df=pd.DataFrame({"close": [1.0]}),
            trading_context=self.ctx_b,
            risk_snapshot=_snapshot(self.ctx_b),
            requested_size_usd=100.0,
        )
        self.assertIsNotNone(result)
        self.assertEqual(result.trading_context.scope_key, self.ctx_b.scope_key)
        self.pipeline._detector_registry.detect.assert_called_once_with(
            df=ANY,
            symbol="BTC-USD",
            broker="kraken",
            market_regime="trending",
            trading_context=self.ctx_b,
        )

    def test_live_context_requires_server_side_authorizer(self):
        live = TradingContext.from_mapping({**self.ctx_a.to_log_fields(), "mode": "live"})
        snapshot = _snapshot(live)
        denied = self.pipeline.process_signal(_raw(live), risk_snapshot=snapshot)
        self.assertIsNone(denied)

        authorized_pipeline = SignalPipeline(
            compiler=ControlCompiler(),
            risk_engine=RiskEngine(),
            context_authorizer=lambda context: context.owner_key == live.owner_key,
        )
        approved = authorized_pipeline.process_signal(_raw(live), risk_snapshot=snapshot)
        self.assertIsNotNone(approved)

    def test_control_disabled_still_rejects_missing_context(self):
        with patch("bot.control.control_compiler._CONTROL_ENABLED", False):
            compiled, notes = ControlCompiler().compile(
                RawSignal(symbol="BTC-USD", side="buy", action="enter_long", size_usd=10.0),
            )
        self.assertIsNone(compiled)
        self.assertIn("context_invalid:missing_trading_context", notes)

    def test_risk_disabled_still_rejects_missing_context(self):
        with patch("bot.control.risk_engine._RISK_ENGINE_ENABLED", False):
            approved, notes = RiskEngine().validate_trade("BTC-USD", "buy", 10.0, 100.0, [])
        self.assertFalse(approved)
        self.assertIn("context_missing:missing_trading_context", notes)

    def test_scoped_risk_rule_update_cannot_change_other_user(self):
        self.risk.update_rules({"max_position_size_pct": 1.0}, trading_context=self.ctx_a)
        rules_a = self.risk.get_rules(trading_context=self.ctx_a)
        rules_b = self.risk.get_rules(trading_context=self.ctx_b)
        self.assertEqual(rules_a.max_position_size_pct, 1.0)
        self.assertNotEqual(rules_b.max_position_size_pct, 1.0)

    def test_delimiter_characters_cannot_collide_scope_or_idempotency_keys(self):
        first = _ctx("a|b", "c", "broker_acct")
        second = _ctx("a", "b|c", "broker_acct")
        self.assertNotEqual(first.scope_key, second.scope_key)
        self.assertNotEqual(
            first.make_idempotency_key(symbol="BTC-USD", side="buy", action="submit_order"),
            second.make_idempotency_key(symbol="BTC-USD", side="buy", action="submit_order"),
        )

    def test_unscoped_position_fails_closed_but_foreign_scoped_position_does_not(self):
        approved, notes = self.risk.validate_trade(
            "BTC-USD", "buy", 50.0, 10_000.0,
            [_position(self.ctx_a), {"symbol": "ETH-USD", "size_usd": 50.0}],
            trading_context=self.ctx_b,
        )
        self.assertFalse(approved)
        self.assertIn("missing_owner_metadata", notes[0])


if __name__ == "__main__":
    unittest.main()
