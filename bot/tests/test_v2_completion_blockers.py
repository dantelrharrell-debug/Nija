from __future__ import annotations

import os
import threading
import time
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd

from bot.control.control_compiler import ControlCompiler
from bot.control.decision_context import UserDecisionContext, UserScopedIdempotencyRegistry
from bot.control.isolation_guards import ScopedRiskSnapshot
from bot.control.regime_engine import MarketRegime
from bot.control.risk_engine import RiskEngine
from bot.control.signal_pipeline import SignalPipeline
from bot.control.situation_analysis import SituationAnalysisEngine
from bot.control.strategy_detectors import BreakRetestDetector, DetectorContext
from bot.control.strategy_registry import StrategyDetectorRegistry
from bot.control.trading_context import TradingContext
from bot.feature_flags import FeatureFlag, FeatureFlagManager


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

    def test_stale_registry_cannot_release_newer_reservation(self):
        redis = _FakeRedis()
        old = UserScopedIdempotencyRegistry(redis_client=redis, ttl_seconds=0.05)
        new = UserScopedIdempotencyRegistry(redis_client=redis, ttl_seconds=5.0)
        context = _decision_context()

        ok_old, key = old.reserve(context, symbol="BTC-USD", direction="long")
        self.assertTrue(ok_old)
        time.sleep(0.07)
        ok_new, new_key = new.reserve(context, symbol="BTC-USD", direction="long")
        self.assertTrue(ok_new)
        self.assertEqual(key, new_key)

        old.release(key)
        self.assertEqual(new.get_state(new_key), "submitted")

    def test_live_account_kill_switch_requires_durable_shared_write(self):
        ctx = _trading_context(mode="live", environment=None)
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
        self.assertFalse(manager.is_enabled(FeatureFlag.BREAK_RETEST_ENABLED))

        manager.enable(FeatureFlag.BREAK_RETEST_ENABLED)
        registry = StrategyDetectorRegistry()
        self.assertIsInstance(registry.detectors[FeatureFlag.BREAK_RETEST_ENABLED], BreakRetestDetector)

        detector_context = DetectorContext(
            symbol="BTC-USD",
            broker="kraken",
            trading_context=_trading_context(),
            market_regime="trending",
        )
        with patch("bot.control.strategy_registry.get_feature_flags", return_value=manager):
            signals = registry.detect(
                _break_retest_frame(),
                symbol="BTC-USD",
                broker="kraken",
                market_regime="trending",
                trading_context=detector_context.trading_context,
            )
        self.assertTrue(any(signal.strategy == "BREAK_RETEST" for signal in signals))


if __name__ == "__main__":
    unittest.main()
