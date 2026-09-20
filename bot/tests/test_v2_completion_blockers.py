from __future__ import annotations

import os
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from bot.control.control_compiler import ControlCompiler, RawSignal
from bot.control.decision_context import UserDecisionContext, UserScopedIdempotencyRegistry
from bot.control.isolation_guards import ScopedRiskSnapshot
from bot.control.regime_engine import MarketRegime
from bot.control.risk_engine import RiskEngine
from bot.control.signal_pipeline import SignalPipeline
from bot.control.situation_analysis import SituationAnalysisEngine
from bot.control.strategy_detectors import BreakRetestDetector, DetectorContext
from bot.control.strategy_registry import StrategyDetectorRegistry
from bot.control.strategy_signal import StrategySignal
from bot.control.trading_context import TradingContext
from bot.feature_flags import FeatureFlag, FeatureFlagManager
from bot.signal_broadcaster import SignalBroadcaster
from bot.pipeline_order_submitter import _prepare_v2_duplicate_handoff


class _FakeRedis:
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
            self._purge(key)
            existed = key in self._values
            self._values.pop(key, None)
            self._expires.pop(key, None)
            return int(existed)


class _Broker:
    broker_name = "coinbase"
    user_id = "user-a"
    connected = True

    def get_account_balance(self):
        return {"trading_balance": 1000.0, "available_balance": 1000.0}

    def get_positions(self):
        return []

    def get_open_orders(self):
        return []


class _CompareDeleteErrorRedis(_FakeRedis):
    def compare_delete(self, key, token):
        raise RuntimeError("compare_delete_unavailable")


def _trading_context(*, mode="paper", environment="test"):
    return TradingContext(
        user_id="user-a",
        trading_account_id="acct-a",
        broker="kraken",
        broker_account_id="kraken-a",
        strategy_instance_id="BREAK_RETEST",
        portfolio_id="portfolio-a",
        request_id="request-a",
        correlation_id="corr-a",
        environment=environment,
        mode=mode,
        decision_id="decision-a",
    )


def _decision_context(*, mode="paper", environment="test"):
    return UserDecisionContext(
        user_id="user-a",
        account_id="acct-a",
        broker="kraken",
        portfolio_id="portfolio-a",
        strategy_signal_id="BREAK_RETEST:BTC-USD:test",
        trade_id="trade-a",
        execution_mode=mode,
        environment=environment,
    )


def _break_retest_frame():
    rows = []
    for _ in range(40):
        rows.append({"open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 100.0})
    rows[-2] = {"open": 100.5, "high": 103.0, "low": 100.4, "close": 102.0, "volume": 150.0}
    rows[-1] = {"open": 101.0, "high": 102.2, "low": 100.8, "close": 101.7, "volume": 120.0}
    return pd.DataFrame(rows)


class TestCompletionBlockers(unittest.TestCase):
    def test_live_missing_environment_requires_shared_idempotency(self):
        with patch("bot.control.decision_context._default_redis_client", return_value=None):
            registry = UserScopedIdempotencyRegistry(redis_client=None)
            ok, _ = registry.reserve(
                _decision_context(mode="live", environment=None),
                symbol="BTC-USD",
                direction="long",
            )
        self.assertFalse(ok)

    def test_trading_context_accepts_rollout_modes(self):
        self.assertEqual(_trading_context(mode="shadow").mode, "shadow")
        self.assertEqual(_trading_context(mode="limited_live", environment="production").mode, "limited_live")

    def test_limited_live_missing_environment_also_requires_shared_idempotency(self):
        with patch("bot.control.decision_context._default_redis_client", return_value=None):
            registry = UserScopedIdempotencyRegistry(redis_client=None)
            ok, _ = registry.reserve(
                _decision_context(mode="limited_live", environment=None),
                symbol="BTC-USD",
                direction="long",
            )
        self.assertFalse(ok)

    def test_live_reservation_uses_uncertain_ttl_before_handoff(self):
        redis = _FakeRedis()
        registry = UserScopedIdempotencyRegistry(
            redis_client=redis,
            ttl_seconds=1.0,
            uncertain_ttl_seconds=30.0,
        )
        ok, handle = registry.reserve(
            _decision_context(mode="live", environment="production"),
            symbol="BTC-USD",
            direction="long",
        )
        self.assertTrue(ok)
        remaining = redis._expires[registry._redis_key(handle.key)] - time.monotonic()
        self.assertGreater(remaining, 20.0)

    def test_stale_registry_cannot_release_newer_reservation(self):
        redis = _FakeRedis()
        old = UserScopedIdempotencyRegistry(redis_client=redis, ttl_seconds=1.0)
        new = UserScopedIdempotencyRegistry(redis_client=redis, ttl_seconds=5.0)
        context = _decision_context()

        ok_old, old_handle = old.reserve(context, symbol="BTC-USD", direction="long")
        self.assertTrue(ok_old)
        time.sleep(1.05)
        ok_new, new_handle = new.reserve(context, symbol="BTC-USD", direction="long")
        self.assertTrue(ok_new)
        self.assertEqual(old_handle.key, new_handle.key)

        old.release(old_handle)
        self.assertEqual(new.get_state(new_handle), "submitted")
        self.assertNotIn(old_handle.key, old._reservation_tokens)

    def test_prepare_v2_duplicate_handoff_rejects_incomplete_metadata(self):
        self.assertFalse(_prepare_v2_duplicate_handoff({"duplicate_key": "v2:test-key"}))

    def test_release_clears_local_state_when_compare_delete_errors(self):
        redis = _CompareDeleteErrorRedis()
        registry = UserScopedIdempotencyRegistry(redis_client=redis, ttl_seconds=5.0)
        context = _decision_context()

        ok, handle = registry.reserve(context, symbol="BTC-USD", direction="long")
        self.assertTrue(ok)
        registry.mark_state(handle, "submitted_pending")
        self.assertIn(handle.key, registry._reservation_tokens)
        self.assertIn(handle.key, registry._states)

        registry.release(handle)

        self.assertNotIn(handle.key, registry._reservation_tokens)
        self.assertNotIn(handle.key, registry._states)

    def test_production_live_account_kill_switch_requires_durable_shared_write(self):
        ctx = _trading_context(mode="live", environment="production")
        with patch("bot.control.decision_context._default_redis_client", return_value=None):
            engine = RiskEngine(redis_client=None)
            with self.assertRaises(RuntimeError):
                engine.set_account_kill_switch(ctx, True, "operator_halt")

    def test_blank_environment_live_context_requires_shared_kill_switch_state(self):
        ctx = SimpleNamespace(mode="live", environment=None)
        self.assertTrue(RiskEngine._requires_shared_state(ctx))

    def test_paper_account_kill_switch_reports_success_without_shared_state(self):
        ctx = _trading_context()
        with patch("bot.control.decision_context._default_redis_client", return_value=None):
            engine = RiskEngine(redis_client=None)
            self.assertTrue(engine.set_account_kill_switch(ctx, True, "paper_halt"))

    def test_platform_kill_switch_reports_success_without_shared_state(self):
        with patch("bot.control.decision_context._default_redis_client", return_value=None):
            engine = RiskEngine(redis_client=None)
            self.assertTrue(engine.set_platform_kill_switch(True, "platform_halt"))

    def test_user_kill_switch_reports_success_without_shared_state(self):
        with patch("bot.control.decision_context._default_redis_client", return_value=None):
            engine = RiskEngine(redis_client=None)
            self.assertTrue(engine.set_user_kill_switch("user-a", True, "user_halt"))


    def test_live_runtime_platform_kill_switch_requires_shared_persistence(self):
        with patch.dict(
            os.environ,
            {"NIJA_STRATEGY_EXECUTION_MODE": "LIVE", "NIJA_ENVIRONMENT": "production"},
        ), patch("bot.control.decision_context._default_redis_client", return_value=None):
            engine = RiskEngine(redis_client=None)
            with self.assertRaises(RuntimeError):
                engine.set_platform_kill_switch(True, "platform_halt")

    def test_live_runtime_user_kill_switch_requires_shared_persistence(self):
        with patch.dict(
            os.environ,
            {"NIJA_STRATEGY_EXECUTION_MODE": "LIMITED_LIVE", "NIJA_ENVIRONMENT": "production"},
        ), patch("bot.control.decision_context._default_redis_client", return_value=None):
            engine = RiskEngine(redis_client=None)
            with self.assertRaises(RuntimeError):
                engine.set_user_kill_switch("user-a", True, "user_halt")

    def test_production_limited_live_account_kill_switch_requires_durable_shared_write(self):
        ctx = _trading_context(mode="limited_live", environment="production")
        with patch("bot.control.decision_context._default_redis_client", return_value=None):
            engine = RiskEngine(redis_client=None)
            with self.assertRaises(RuntimeError):
                engine.set_account_kill_switch(ctx, True, "operator_halt")

    def test_situation_analysis_accepts_nested_owned_context(self):
        ctx = _trading_context()
        regime = SimpleNamespace(regime=MarketRegime.TRENDING, confidence=0.8, volatility=0.02)
        result = SituationAnalysisEngine().assess(
            trading_context=ctx,
            regime_result=regime,
            positions=[{"symbol": "BTC-USD", "trading_context": ctx}],
            authoritative_position_proven=True,
        )
        self.assertTrue(result.eligible_for_strategy_evaluation, result.reasons)
        self.assertEqual(result.open_positions, 1)

    def test_pipeline_fails_closed_when_owner_positions_are_malformed(self):
        ctx = _trading_context()
        regime_engine = MagicMock()
        regime_engine.detect.return_value = SimpleNamespace(
            regime=MarketRegime.TRENDING,
            confidence=0.8,
            volatility=0.02,
        )
        pipeline = SignalPipeline(
            compiler=MagicMock(),
            regime_engine=regime_engine,
            risk_engine=MagicMock(),
        )
        snapshot = MagicMock()
        snapshot.context = ctx
        snapshot.positions_for_owner.side_effect = ValueError("position_missing_owner_metadata:index=0")
        result = pipeline.process_market_snapshot(
            symbol="BTC-USD",
            broker="kraken",
            df=pd.DataFrame([{"open": 1, "high": 2, "low": 0.5, "close": 1.5, "volume": 10}]),
            trading_context=ctx,
            risk_snapshot=snapshot,
            requested_size_usd=10.0,
        )
        self.assertIsNone(result)

    def test_limited_live_pipeline_requires_context_authorizer(self):
        ctx = SimpleNamespace(
            user_id="user-a",
            trading_account_id="acct-a",
            broker="kraken",
            portfolio_id="portfolio-a",
            request_id="request-a",
            mode="limited_live",
            environment="production",
        )
        pipeline = SignalPipeline(
            compiler=MagicMock(),
            regime_engine=MagicMock(),
            risk_engine=MagicMock(),
        )
        raw = RawSignal(
            symbol="BTC-USD",
            side="buy",
            action="enter_long",
            size_usd=10.0,
            confidence=0.8,
            regime="trending",
            strategy="BREAK_RETEST",
            user_id=ctx.user_id,
            account_id=ctx.trading_account_id,
            broker=ctx.broker,
            portfolio_id=ctx.portfolio_id,
            strategy_signal_id="sig",
            trade_id=ctx.request_id,
            trading_context=ctx,
            execution_mode=ctx.mode,
        )
        # The authorization gate executes before financial-state processing.
        self.assertIsNone(pipeline.process_signal(raw_signal=raw))

    def test_limited_live_conversion_defaults_to_production_environment(self):
        decision = _decision_context(mode="limited_live", environment=None)
        raw = RawSignal(
            symbol="BTC-USD",
            side="buy",
            action="enter_long",
            size_usd=10.0,
            confidence=0.8,
            regime="trending",
            strategy="BREAK_RETEST",
            user_id=decision.user_id,
            account_id=decision.account_id,
            broker=decision.broker,
            portfolio_id=decision.portfolio_id,
            strategy_signal_id=decision.strategy_signal_id,
            trade_id=decision.trade_id,
        )
        ctx = SignalPipeline._trading_context_from_decision_context(raw, decision)
        self.assertEqual(ctx.mode, "limited_live")
        self.assertEqual(ctx.environment, "production")

    def test_broadcaster_uses_configured_v2_execution_mode(self):
        broadcaster = SignalBroadcaster()
        broadcaster.register_account("acct-a", _Broker(), balance=1000.0)
        with patch.dict(os.environ, {"NIJA_STRATEGY_EXECUTION_MODE": "PAPER"}):
            decisions = broadcaster.build_account_decisions({
                "symbol": "BTC-USD",
                "strategy_signal_id": "sig-a",
                "trade_id": "trade-a",
                "strategy": "BREAK_RETEST",
            })
        self.assertEqual(len(decisions), 1)
        self.assertEqual(decisions[0].decision_context.execution_mode, "paper")
        self.assertEqual(decisions[0].decision_context.environment, "test")

    def test_break_retest_is_compiler_compatible_with_trending_and_breakout(self):
        for regime in ("trending", "breakout"):
            ok, reason = ControlCompiler._validate_regime_compatibility(
                SimpleNamespace(action="enter_long", regime=regime, strategy="BREAK_RETEST")
            )
            self.assertTrue(ok, reason)

    def test_break_retest_flag_defaults_off_and_registry_can_enable(self):
        env_key = "FEATURE_BREAK_RETEST_ENABLED"
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop(env_key, None)
            manager = FeatureFlagManager()
        self.assertFalse(manager.get_all_flags().get("break_retest_enabled", True))

        registry = StrategyDetectorRegistry()
        detector = next(
            (
                value
                for flag, value in registry.detectors.items()
                if getattr(flag, "value", "") == "break_retest_enabled"
            ),
            None,
        )
        self.assertIsInstance(detector, BreakRetestDetector)

        detector_context = DetectorContext(
            symbol="BTC-USD",
            broker="kraken",
            trading_context=_trading_context(),
            market_regime="trending",
        )
        enabled_flags = SimpleNamespace(
            is_enabled=lambda flag: getattr(flag, "value", "") == "break_retest_enabled"
        )
        with patch("bot.control.strategy_registry.get_feature_flags", return_value=enabled_flags):
            signals = registry.detect(
                _break_retest_frame(),
                symbol="BTC-USD",
                broker="kraken",
                market_regime="trending",
                trading_context=detector_context.trading_context,
            )
        self.assertTrue(any(signal.strategy == "BREAK_RETEST" for signal in signals))

    def test_live_reservation_preserves_uncertain_ttl_until_submission_uncertain(self):
        redis = _FakeRedis()
        registry = UserScopedIdempotencyRegistry(
            redis_client=redis,
            ttl_seconds=1.0,
            uncertain_ttl_seconds=30.0,
        )
        ok, handle = registry.reserve(
            _decision_context(mode="live", environment="production"),
            symbol="BTC-USD",
            direction="long",
        )
        self.assertTrue(ok)
        redis_key = registry._redis_key(handle.key)
        initial_remaining = redis._expires[redis_key] - time.monotonic()
        self.assertGreater(initial_remaining, 20.0)

        registry.mark_state(handle, "state_unknown")
        extended_remaining = redis._expires[redis_key] - time.monotonic()
        self.assertGreater(extended_remaining, 20.0)



    def test_cross_worker_live_handle_cannot_fallback_local_without_redis(self):
        redis = _FakeRedis()
        producer = UserScopedIdempotencyRegistry(redis_client=redis)
        ok, handle = producer.reserve(
            _decision_context(mode="live", environment="production"),
            symbol="AVAX-USD",
            direction="long",
        )
        self.assertTrue(ok)
        self.assertTrue(handle.shared_required)

        with patch("bot.control.decision_context._default_redis_client", return_value=None):
            consumer = UserScopedIdempotencyRegistry(redis_client=None)
            self.assertFalse(consumer.mark_state(handle, "submitted_pending"))

    def test_pre_dispatch_handoff_durably_extends_live_reservation(self):
        redis = _FakeRedis()
        registry = UserScopedIdempotencyRegistry(
            redis_client=redis,
            ttl_seconds=1.0,
            uncertain_ttl_seconds=30.0,
        )
        ok, handle = registry.reserve(
            _decision_context(mode="live", environment="production"),
            symbol="SOL-USD",
            direction="long",
        )
        self.assertTrue(ok)
        with patch(
            "bot.control.decision_context.get_user_scoped_idempotency_registry",
            return_value=registry,
        ):
            self.assertTrue(_prepare_v2_duplicate_handoff(handle.to_metadata()))
        self.assertEqual(registry.get_state(handle), "submitted_pending")
        remaining = redis._expires[registry._redis_key(handle.key)] - time.monotonic()
        self.assertGreater(remaining, 20.0)

    def test_mark_duplicate_execution_complete_preserves_shared_authority_flag(self):
        pipeline = SignalPipeline.__new__(SignalPipeline)
        pipeline._idempotency_registry = MagicMock()

        pipeline.mark_duplicate_execution_complete(
            "dup-key",
            "dup-token",
            duplicate_shared_required=True,
            state="submitted_pending",
        )

        handle = pipeline._idempotency_registry.mark_state.call_args[0][0]
        self.assertTrue(handle.shared_required)

    def test_stale_finalizer_cannot_overwrite_newer_reservation(self):
        redis = _FakeRedis()
        old = UserScopedIdempotencyRegistry(redis_client=redis, ttl_seconds=1.0)
        new = UserScopedIdempotencyRegistry(redis_client=redis, ttl_seconds=5.0)
        ctx = _decision_context()
        ok_old, old_handle = old.reserve(ctx, symbol="ETH-USD", direction="long")
        self.assertTrue(ok_old)
        time.sleep(1.05)
        ok_new, new_handle = new.reserve(ctx, symbol="ETH-USD", direction="long")
        self.assertTrue(ok_new)

        old.mark_state(old_handle, "state_unknown")
        self.assertEqual(new.get_state(new_handle), "submitted")

    def test_break_retest_rejects_zero_volume_breakout(self):
        df = _break_retest_frame()
        df["volume"] = 0.0
        detector = BreakRetestDetector()
        signal = detector.detect(
            df,
            DetectorContext(
                symbol="BTC-USD",
                broker="kraken",
                trading_context=_trading_context(),
                market_regime="trending",
            ),
        )
        self.assertIsNone(signal)

    def test_break_retest_stop_and_target_reach_compiled_execution_fields(self):
        ctx = _trading_context()
        df = _break_retest_frame()
        candidate = StrategySignal(
            strategy="BREAK_RETEST",
            symbol="BTC-USD",
            broker="kraken",
            direction="long",
            trading_context=ctx,
            invalidation_level=100.0,
            suggested_stop=100.0,
            target_candidates=[104.0],
            confidence=0.8,
            raw_score=0.8,
            market_regime="trending",
            supporting_evidence=["structure_break_up", "retest_hold", "volume_confirmed"],
        )
        regime = SimpleNamespace(
            regime=MarketRegime.TRENDING,
            confidence=0.8,
            volatility=0.02,
            adx=30.0,
            rsi=55.0,
        )
        regime_engine = MagicMock()
        regime_engine.detect.return_value = regime
        pipeline = SignalPipeline(
            compiler=ControlCompiler(),
            regime_engine=regime_engine,
            risk_engine=RiskEngine(redis_client=_FakeRedis()),
        )
        pipeline._idempotency_registry = UserScopedIdempotencyRegistry(redis_client=_FakeRedis())
        pipeline._detector_registry = MagicMock()
        pipeline._detector_registry.detect.return_value = [candidate]
        pipeline._scoring_engine = MagicMock()
        pipeline._scoring_engine.score.return_value = SimpleNamespace(rejected=False, score=0.8)
        pipeline._confirmation_engine = MagicMock()
        pipeline._confirmation_engine.confirm.return_value = SimpleNamespace(approved=True, reasons=[])
        snapshot = ScopedRiskSnapshot.from_values(
            context=ctx,
            portfolio_value_usd=10_000.0,
            current_positions=[],
            available_balance_usd=1_000.0,
        )

        compiled = pipeline.process_market_snapshot(
            symbol="BTC-USD",
            broker="kraken",
            df=df,
            trading_context=ctx,
            risk_snapshot=snapshot,
            requested_size_usd=50.0,
            authoritative_position_proven=True,
        )
        self.assertIsNotNone(compiled)
        self.assertIsNotNone(compiled.stop_loss_pct)
        self.assertIsNotNone(compiled.take_profit_pct)
        self.assertGreater(compiled.stop_loss_pct, 0.0)
        self.assertGreater(compiled.take_profit_pct, 0.0)
        kwargs = compiled.to_pipeline_kwargs()
        self.assertEqual(kwargs["stop_loss_pct"], compiled.stop_loss_pct)
        self.assertEqual(kwargs["take_profit_pct"], compiled.take_profit_pct)
        self.assertEqual(kwargs["metadata"]["suggested_stop"], 100.0)
        self.assertEqual(kwargs["metadata"]["target_candidates"][0], 104.0)
        self.assertTrue(kwargs["metadata"].get("duplicate_key"))
        self.assertTrue(kwargs["metadata"].get("duplicate_token"))



if __name__ == "__main__":
    unittest.main()
